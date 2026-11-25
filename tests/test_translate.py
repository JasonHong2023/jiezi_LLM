"""翻譯測試（add-translation）：意圖、語言偵測、檢查、簡轉繁、逐段翻譯與續跑、gateway、CLI。不載入模型。
Translation tests: intent, language detection, checks, script conversion, chunked translation and resume, gateway, CLI."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import documents as D  # noqa: E402
from jiezi import translate as T  # noqa: E402
from jiezi.runtime import escalation  # noqa: E402

# 每節一個不同的數字，譯文漏掉哪一段就查得出來 / one distinct number per section, so a dropped chunk shows
LONG_ZH = "\n\n".join(f"第{i}節：本季的營收是 {1000 + i * 37} 萬元，主要來自海外市場的成長，團隊預計明年持續擴大投資。" * 4
                      for i in range(1, 31))


def fake_en(src: str) -> str:
    """假的「英文譯文」：保留數字，長度合理。 / A fake English translation keeping the numbers."""
    import re
    nums = re.findall(r"\d[\d,]*", src)
    return " ".join(f"Section revenue was {n} units, driven by overseas growth and continued investment." for n in nums) \
        or "A short translated sentence about the topic."


class TestIntentAndDetect(unittest.TestCase):
    def test_intent(self):
        cases = {"請翻譯成英文": ("en", False), "把這份中文文件翻成英文": ("en", False),
                 "把這份英文報告翻成中文": ("zh-TW", False), "translate this into Traditional Chinese": ("zh-TW", False),
                 "幫我翻譯": (None, False), "簡體轉繁體": ("zh-TW", True), "把這份簡體文件轉成繁體": ("zh-TW", True)}
        for q, (to, conv) in cases.items():
            self.assertEqual(T.intent(q), {"to": to, "convert": conv}, q)
        for q in ("請摘要", "翻譯是什麼意思", "請把上面翻成日文", "translate to Japanese", "翻成簡體中文", "", "轉帳要怎麼做",
                  "翻譯" + "很長的內容" * 60):
            self.assertIsNone(T.intent(q), q)

    def test_detect_and_target(self):
        self.assertEqual(T.detect("本季營收成長 12%，主要來自海外市場。"), "zh-Hant")
        self.assertEqual(T.detect("本季营收增长 12%，软件业务贡献最多，这个数据来自内部报告。"), "zh-Hans")
        self.assertEqual(T.detect("Quarterly revenue grew 12 percent."), "en")
        self.assertEqual(T.detect("12345"), "other")
        self.assertEqual(T.detect("皇后在後台，群峰之間有床。"), "zh-Hant")       # 正體字不誤判 / not mistaken for Simplified
        self.assertEqual((T.resolve_target(None, "zh-Hant"), T.resolve_target(None, "en"), T.resolve_target("en", "en")),
                         ("en", "zh-TW", "en"))
        with self.assertRaises(T.TranslateError):
            T.resolve_target("ja", "en")                                    # 初版只有 zh-TW 與 en / only two targets


class TestCheck(unittest.TestCase):
    def test_numbers_units_and_language(self):
        src = "本季營收 1,250 萬元，成長 12%，於 2026 年 11 月 16 日公布。"
        self.assertEqual(T.check(src, "Revenue was 12.5 million, up 12%, announced on November 16, 2026.", "en"), [])
        self.assertIn("1,250", T.check(src, "Revenue grew 12% in 2026, announced November 16.", "en")[0])
        self.assertIn("16", T.check(src, "Revenue was 12.5 million, up 12%, announced in November 2026.", "en")[0])  # 日期的日不能漏
        self.assertIn("仍是中文", T.check("今天天氣很好。", "今天天氣很好。", "en")[0])
        self.assertIn("不是中文", T.check("The weather is nice.", "The weather is nice.", "zh-TW")[0])
        self.assertEqual(T.check("Revenue grew 12% in 2026.", "2026 年營收成長 12%。", "zh-TW"), [])
        self.assertEqual(T.check("x", "", "en"), ["譯文是空的 / empty translation"])
        self.assertEqual(T.check("ＧＤＰ成長１２．５％", "GDP grew 12.5%", "en"), [])    # 全形數字 / full-width digits

    def test_ratio_and_glossary(self):
        src = LONG_ZH.split("\n\n")[0]
        self.assertTrue(any("太短" in e for e in T.check(src, "Revenue 1037.", "en")))
        self.assertTrue(any("太長" in e for e in T.check(src, fake_en(src) * 12, "en")))
        self.assertEqual(T.check(src, fake_en(src), "en"), [])
        self.assertEqual(T.check("標題", "Title", "en"), [])                 # 很短的段不看比例 / short chunks skip the ratio
        g = [("芥子", "Jiezi")]
        self.assertIn("Jiezi", T.check("芥子是本機助理。", "The mustard seed is a local assistant.", "en", g)[0])
        self.assertEqual(T.check("芥子是本機助理。", "jiezi is a local assistant.", "en", g), [])
        self.assertEqual(T.check("這段沒有那個詞。", "No such term here.", "en", g), [])

    def test_glossary_parsing(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "g.tsv"
            f.write_text("# 註解\n芥子\tJiezi\n須彌=Sumeru\n壞的一行\n\n", encoding="utf-8")
            self.assertEqual(T.read_glossary(f), [["芥子", "Jiezi"], ["須彌", "Sumeru"]])
        self.assertEqual(T.parse_glossary([["a", "b"], ["x"], "bad", ["", "y"]]), [("a", "b")])
        with self.assertRaises(T.TranslateError):
            T.parse_glossary([["a", "b"]] * (T.MAX_GLOSSARY + 1))


class TestPrompt(unittest.TestCase):
    def test_english_target_uses_english_prompt_without_chinese_context(self):
        # 2026-11-25：中文提示加中文前文時 r3 常照抄原文 / the r3 core echoed the source with a Chinese prompt
        msgs = T.prompt("第一條 為保障著作人著作權益，特制定本法。", "en", prev="前一段的中文結尾",
                        glossary=[("著作權", "copyright")], error="the output is still mostly Chinese")
        self.assertNotIn("前一段", msgs[0]["content"])
        self.assertTrue(msgs[0]["content"].startswith("You are a professional translator."))
        self.assertIn("著作權 → copyright", msgs[0]["content"])
        self.assertIn("still mostly Chinese", msgs[0]["content"])
        self.assertTrue(msgs[1]["content"].startswith("Translate into English:"))
        msgs = T.prompt("Hello.", "zh-TW", prev="previous tail")           # 英翻中維持原樣 / unchanged
        self.assertIn("previous tail", msgs[0]["content"])
        self.assertEqual(msgs[1]["content"], "Hello.")


class TestConversion(unittest.TestCase):
    def test_word_level_conversion(self):
        src = "这个软件的后台服务器运行稳定。皇后的头发很干净，里面有三只猫。发展中国家的网络信息。我们为了群众登上山峰。面条和台风。"
        out = T.convert(src)
        for want in ("軟體", "後臺", "伺服器", "皇后", "頭髮", "乾淨", "裡面", "三隻貓", "發展中國家", "網路資訊", "為了群眾",
                     "山峰", "麵條", "颱風"):
            self.assertIn(want, out)
        self.assertEqual(T.detect(out), "zh-Hant")
        self.assertEqual(T.convert('print("你好") 3.12 ABC'), 'print("你好") 3.12 ABC')

    def test_model_output_conversion_is_unchanged(self):
        from jiezi.textconv import to_taiwan
        self.assertEqual(to_taiwan("皇后在後台，群峰之間有床。"), "皇后在後台，群峰之間有床。")   # 原本的行為不變
        from jiezi.textconv import simplified_to_taiwan
        self.assertEqual(simplified_to_taiwan("下载技术文件"), "下載技術文件")   # 「文件」不換成「檔案」


class TestChunked(unittest.TestCase):
    def run_tr(self, complete, store=None, glossary=None, text=LONG_ZH):
        return anyio.run(lambda: T.translate_text("報告.pdf", text, "en", complete, glossary, store))

    def test_every_chunk_translated_in_order(self):
        seen = []

        async def complete(msgs, n):
            seen.append(msgs)
            return fake_en(msgs[-1]["content"].removeprefix("Translate into English:\n\n"))
        pairs, info = self.run_tr(complete)
        self.assertGreater(len(pairs), 3)
        self.assertEqual((info["chunks"], info["failed"], info["retried"]), (len(pairs), [], 0))
        self.assertEqual("".join(s for s, _ in pairs).replace("\n", ""), LONG_ZH.replace("\n", ""))   # 原文一字不漏 / nothing dropped
        for src, tr in pairs:
            self.assertEqual(T.numbers(src) - T.numbers(tr), set())
        # 中翻英不附中文前文（r3 會照抄原文，2026-11-25）/ no Chinese context for Chinese → English
        self.assertFalse([m for m in seen if "前文結尾" in m[0]["content"]])
        self.assertTrue(all(m[1]["content"].startswith("Translate into English:") for m in seen))
        text = T.render("報告.pdf", pairs, True, False)
        self.assertIn(f"〔原文 1/{len(pairs)}〕", text)
        self.assertIn(f"〔譯文 {len(pairs)}/{len(pairs)}〕", text)
        self.assertNotIn("〔原文", T.render("報告.pdf", pairs, False, False))

    def test_retry_then_keep_source_marked(self):
        calls = {"n": 0}

        async def complete(msgs, n):
            calls["n"] += 1
            src = msgs[-1]["content"].removeprefix("Translate into English:\n\n")
            if "1037" in src:                       # 第 1 段永遠漏數字 / the first chunk always drops its numbers
                return "Revenue grew thanks to overseas markets and the team will keep investing next year. " * 6
            if "1407" in src and "failed a check" not in msgs[0]["content"]:
                return ""                           # 這一段第一次空白，重試後成功 / empty once, fine on retry
            return fake_en(src)
        pairs, info = self.run_tr(complete)
        self.assertEqual([f["chunk"] for f in info["failed"]], [1])
        self.assertIn("numbers missing", " ".join(info["failed"][0]["errors"]))
        self.assertEqual(info["retried"], 2)
        self.assertIsNone(pairs[0][1])
        text = T.render("報告.pdf", pairs, True, False)
        self.assertIn("第 1/", text)
        self.assertIn("未能翻譯", text)
        self.assertIn(pairs[0][0], text)                                    # 保留原文 / the source is kept

    def test_resume_skips_finished_chunks(self):
        with tempfile.TemporaryDirectory() as d:
            n = {"calls": 0, "fail": True}

            async def complete(msgs, _):
                n["calls"] += 1
                if n["fail"] and "1037" in msgs[-1]["content"]:
                    return ""
                return fake_en(msgs[-1]["content"])
            pairs, first = self.run_tr(complete, Path(d))
            self.assertEqual(len(first["failed"]), 1)
            n["fail"], before = False, n["calls"]
            pairs, second = self.run_tr(complete, Path(d))
            self.assertEqual((second["resumed"], second["failed"]), (len(pairs) - 1, []))
            self.assertEqual(n["calls"] - before, 1)                         # 只重翻失敗的那一段 / only the failed chunk
            self.assertEqual(len(list(Path(d).glob("*.json"))), 1)
            _, other = anyio.run(lambda: T.translate_text("報告.pdf", LONG_ZH, "en", complete, [("營收", "revenue")], Path(d)))
            self.assertEqual(other["resumed"], 0)                            # 詞彙表不同就不沿用 / a new glossary starts over

    def test_estimate(self):
        short, long = T.estimate_seconds(["短文"], 100.0), T.estimate_seconds([LONG_ZH * 20], 20.0)
        self.assertLess(short, 5)
        self.assertGreater(long, T.ASK_ABOVE_S)
        self.assertGreater(T.estimate_seconds([LONG_ZH], None), T.estimate_seconds([LONG_ZH], 200.0))


class TestGateway(unittest.TestCase):
    def post(self, body, answer=None, policy_kw=None, held=False, **kw):
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        seen = []

        def handler(request):
            b = json.loads(request.content)
            seen.append(b)
            content = answer(b) if answer else fake_en(b["messages"][-1]["content"])
            return httpx.Response(200, json={"id": "x", "object": "chat.completion", "model": "core", "choices": [
                {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "timings": {"predicted_per_second": 100.0}})
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp, **{"samples": 1, **kw})
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(handler)), log=lambda *_: None)
            gw.last_tps = 100.0
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"}, json=body)
            recs = [json.loads(x) for f in (tmp / "traj").glob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
            stored = len(list((tmp / "var" / "translate").glob("*.json"))) if (tmp / "var" / "translate").is_dir() else 0
        return r, seen, recs, stored

    def doc(self, q, text=LONG_ZH, **extra):
        return {"model": "jiezi-local", "messages": [{"role": "user", "content": D.attach({"name": "報告.pdf", "text": text}, q)}],
                **extra}

    def test_whole_document_bilingual_by_default(self):
        r, seen, recs, stored = self.post(self.doc("請翻譯成英文"))
        self.assertEqual(r.status_code, 200)
        j = r.json()
        info = j["jiezi"]["translation"]
        self.assertEqual((info["mode"], info["to"], info["source"], info["failed"], info["bilingual"]),
                         ("chunked", "en", "zh-Hant", 0, True))
        self.assertEqual(len(seen), info["chunks"])                          # 每段一次呼叫，沒有改寫那一輪 / no rewriting pass
        text = j["choices"][0]["message"]["content"]
        self.assertIn("〔原文 1/", text)
        self.assertIn("1037", text)
        self.assertIn(str(1000 + 30 * 37), text)                             # 最後一節也在 / the last section is there
        self.assertEqual(j["jiezi"]["verification"], "pass")
        self.assertIs(recs[0]["training_use"], False)
        self.assertNotIn("jiezi_translate", seen[0])                         # 不把自訂欄位丟給引擎 / never sent to the engine
        self.assertEqual(stored, 1)

    def test_plain_option_and_glossary(self):
        r, seen, _, _ = self.post(self.doc("請翻譯", jiezi_translate={"to": "en", "bilingual": False,
                                                                       "glossary": [["營收", "revenue"]]}))
        text = r.json()["choices"][0]["message"]["content"]
        self.assertNotIn("〔原文", text)
        self.assertIn("營收 → revenue", seen[0]["messages"][0]["content"])

    def test_failed_chunks_are_reported_not_hidden(self):
        r, _, _, _ = self.post(self.doc("請翻譯成英文"),
                               answer=lambda b: "" if "1037" in b["messages"][-1]["content"] else fake_en(b["messages"][-1]["content"]))
        j = r.json()
        self.assertEqual((j["jiezi"]["verification"], j["jiezi"]["translation"]["failed"]), ("fail", 1))
        self.assertIn("未能翻譯", j["choices"][0]["message"]["content"])

    def test_simplified_conversion_needs_no_engine(self):
        src = "这个软件的后台服务器运行稳定，头发很干净。" * 3
        r, seen, recs, _ = self.post(self.doc("請轉成繁體中文", text=src))
        j = r.json()
        self.assertEqual(seen, [])                                           # 沒有呼叫模型 / no model call
        self.assertEqual(j["jiezi"]["translation"]["mode"], "conversion")
        self.assertIn("軟體的後臺伺服器", j["choices"][0]["message"]["content"])
        self.assertIn("未經模型", j["choices"][0]["message"]["content"])
        self.assertIs(recs[0]["training_use"], False)

    def test_long_job_needs_confirmation(self):
        big = LONG_ZH * 60
        r, seen, _, _ = self.post(self.doc("請翻譯成英文", text=big))
        info = r.json()["jiezi"]["translation"]
        self.assertTrue(info["needs_confirmation"])
        self.assertGreater(info["estimate_s"], T.ASK_ABOVE_S)
        self.assertEqual(seen, [])                                           # 還沒開始翻 / nothing started
        self.assertIn("scripts/jiezi translate", r.json()["choices"][0]["message"]["content"])

    def test_not_taken_over(self):
        r, seen, _, _ = self.post(self.doc("請摘要重點"), answer=lambda b: "- 重點")
        self.assertNotIn("translation", r.json()["jiezi"])                   # 摘要照舊 / summaries are untouched
        r, seen, _, _ = self.post(self.doc("請翻譯成英文"), answer=lambda b: "- 重點", translate=False)
        self.assertNotIn("translation", r.json()["jiezi"])                   # JIEZI_TRANSLATE=off
        r, seen, _, _ = self.post(self.doc("請翻成日文"), answer=lambda b: "- 重點")
        self.assertNotIn("translation", r.json()["jiezi"])                   # 不支援的目標語言 / unsupported target
        r, _, _, _ = self.post(self.doc("x", jiezi_translate={"to": "ja"}))
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (400, "invalid_translation"))

    def test_short_text_is_checked(self):
        body = {"model": "jiezi-local", "messages": [{"role": "user", "content": "請翻譯成英文：本季營收 1,250 萬元。"}]}
        answers = iter(["本季營收很好。", "Revenue this quarter was 12.5 million."])
        r, seen, _, _ = self.post(body, answer=lambda b: next(answers))
        meta = r.json()["jiezi"]
        self.assertEqual((meta["tier"], meta["verification"]), (1, "pass"))  # 第一次沒過，重試通過 / retried
        self.assertIn("仍是中文", seen[1]["messages"][-1]["content"])
        v = escalation.verify({"jiezi_translate": {"short": True, "to": "en"},
                               "messages": [{"role": "user", "content": "翻成英文：共 250 人"}]}, {"content": "There were many people."})
        self.assertEqual(v["status"], "fail")


class TestCli(unittest.TestCase):
    def run_cli(self, responses, tty=False, typed="", **kw):
        import httpx
        from jiezi.cli import translate as C
        from jiezi.cli.client import Connection
        seen, it = [], iter(responses)

        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(200, json=next(it))

        class In(io.StringIO):
            def isatty(self):
                return tty
        out, err = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "報告.txt"
            f.write_text(LONG_ZH, encoding="utf-8")
            if kw.get("out"):
                kw["out"] = str(Path(d) / kw["out"])
            rc = anyio.run(lambda: C.run_translate(str(f), kw.pop("to", "en"), Connection("http://gw", "k" * 32), In(typed), out, err,
                                                   client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw))
            written = Path(kw["out"]).read_text(encoding="utf-8") if kw.get("out") else None
        return rc, out.getvalue(), err.getvalue(), seen, written

    def resp(self, text, **info):
        return {"choices": [{"message": {"content": text}}], "jiezi": {"model": "core", "translation": info} if info else
                {"model": "claude", "escalation": "engine_unavailable"}}

    def test_success_options_and_exit_codes(self):
        ok = self.resp("譯文", mode="chunked", chunks=4, failed=0, seconds=3.0, source="zh-Hant", to="en", documents=[])
        rc, out, err, seen, _ = self.run_cli([ok], plain=True)
        self.assertEqual((rc, out), (0, "譯文\n"))
        opts = seen[0]["jiezi_translate"]
        self.assertEqual((opts["to"], opts["bilingual"], opts["confirmed"]), ("en", False, False))
        self.assertIn("【文件：報告.txt】", seen[0]["messages"][0]["content"])
        bad = self.resp("部分", mode="chunked", chunks=4, failed=1, seconds=3.0, source="zh-Hant", to="en",
                        documents=[{"failed": [{"chunk": 2, "errors": ["x"]}]}])
        rc, out, err, _, written = self.run_cli([bad], out="o.md")
        self.assertEqual((rc, out, written), (5, "", "部分\n"))
        self.assertIn("2", err)

    def test_confirmation(self):
        ask = self.resp("要先確認", mode="chunked", needs_confirmation=True, estimate_s=1200.0)
        ok = self.resp("譯文", mode="chunked", chunks=9, failed=0, seconds=9.0, source="zh-Hant", to="en", documents=[])
        rc, out, err, seen, _ = self.run_cli([ask])                           # 非互動 → 6 / not interactive
        self.assertEqual((rc, out, len(seen)), (6, "", 1))
        self.assertIn("--yes", err)
        rc, out, err, seen, _ = self.run_cli([ask, ok], tty=True, typed="y\n")
        self.assertEqual((rc, out, seen[1]["jiezi_translate"]["confirmed"]), (0, "譯文\n", True))
        self.assertIn("20 分鐘", err)
        rc, out, _, seen, _ = self.run_cli([ask], tty=True, typed="n\n")
        self.assertEqual((rc, out, len(seen)), (0, "", 1))                    # 取消就不送第二次 / cancelled
        rc, _, _, seen, _ = self.run_cli([ok], yes=True)
        self.assertTrue(seen[0]["jiezi_translate"]["confirmed"])

    def test_not_chunked_is_said_plainly(self):
        rc, out, err, _, _ = self.run_cli([self.resp("Claude 的譯文")])
        self.assertEqual((rc, out), (0, "Claude 的譯文\n"))
        self.assertIn("沒有走逐段翻譯", err)


if __name__ == "__main__":
    unittest.main()

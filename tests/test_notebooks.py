"""add-notebooks：儲存、段落位置、檢索、引用檢查、查證與記憶。 / Storage, offsets, retrieval, citations, checks, memory."""

import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.memory import Memory  # noqa: E402
from jiezi.notebooks import cite, memory_link, verify  # noqa: E402
from jiezi.notebooks.store import NotebookError, NotebookStore, split_offsets  # noqa: E402

LEASE = ("租賃契約書。出租人王大明將台北市大安區房屋出租給承租人。租期自 2026 年 1 月 1 日起至 2027 年 12 月 31 日止。"
         "每月租金新台幣 25000 元，應於每月 5 日前匯入出租人帳戶。押金為兩個月租金，共 50000 元，租期屆滿無欠款時返還。"
         "承租人不得飼養寵物。房屋內的冷氣與冰箱由出租人負責維修。")
RULES = ("社區管理規約。住戶應遵守社區規定。垃圾於每週一、三、五晚上八點收取。訪客車輛不得停放於地下室。"
         "公共設施開放時間為早上六點到晚上十點。")
OTHER_LEASE = "補充協議。押金為三個月租金，共 75000 元。其餘條款依原契約。"


def fake_embed(texts):
    out = []
    for t in texts:
        v = array("f", [0.0] * 8)
        for ch in t:
            v[ord(ch) % 8] += 1.0
        out.append(v)
    return out


class CliTests(unittest.TestCase):
    def test_long_pasted_text_is_not_a_path(self):
        from jiezi.notebooks.cli import _is_file
        self.assertFalse(_is_file(LEASE * 3))          # 原本丟 OSError: File name too long
        self.assertTrue(_is_file(__file__))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.store = NotebookStore(Path(self._t.name) / "nb")
        self.addCleanup(self.store.close)

    def test_offsets_cover_text_and_overlap(self):
        text = "。".join(f"第{i}句話說明某件事情的細節內容" for i in range(200)) + "。"
        spans = split_offsets(text, size=60)
        self.assertGreater(len(spans), 5)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(text))
        self.assertTrue(any(b[0] < a[1] for a, b in zip(spans, spans[1:])))          # 有重疊 / overlap
        self.assertTrue(all(b[0] > a[0] for a, b in zip(spans, spans[1:])))          # 一直往前 / always advances

    def test_add_dedupe_remove_and_offsets(self):
        nb = self.store.create("租屋")
        s, new = nb.add_source("租約", "file", LEASE, origin="lease.pdf", embed=fake_embed)
        self.assertTrue(new)
        again, new2 = nb.add_source("租約（重傳）", "file", LEASE)
        self.assertFalse(new2)
        self.assertEqual(again["id"], s["id"])
        full = nb.source(s["id"])["text"]
        for c in nb.chunks():
            self.assertEqual(full[c["start"]:c["end"]], c["text"])                 # 位置對得回原文 / offsets
        self.assertEqual(len(nb.vectors()), len(nb.chunks()))
        self.assertEqual(self.store.list()[0]["sources"], 1)
        self.assertTrue(nb.remove_source(s["id"]))
        self.assertEqual(nb.chunks(), [])
        self.assertEqual(nb.vectors(), {})
        with self.assertRaises(NotebookError):
            nb.add_source("空", "text", "   ")
        with self.assertRaises(NotebookError):
            self.store.get("../etc")
        self.assertTrue(self.store.delete(nb.id))
        self.assertEqual(self.store.list(), [])


class CiteTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.store = NotebookStore(Path(self._t.name) / "nb")
        self.addCleanup(self.store.close)
        self.nb = self.store.create("租屋")
        self.lease, _ = self.nb.add_source("租約", "file", LEASE)
        self.rules, _ = self.nb.add_source("管理規約", "text", RULES)
        self.titles = {s["id"]: s["title"] for s in self.nb.sources()}

    def passages(self, q):
        return cite.number(cite.retrieve(self.nb.chunks(), q), self.titles)

    def test_retrieve_relevant_and_nothing_for_unrelated(self):
        ps = self.passages("押金是多少錢？")
        self.assertTrue(ps)
        self.assertEqual(ps[0]["sid"], self.lease["id"])
        self.assertTrue(self.passages("可以養貓嗎？"))                   # 沒有共同字詞也給段落 / no threshold
        self.assertEqual(cite.retrieve(self.nb.chunks(), "量子電腦的原理是什麼", strict=True), [])

    def test_check_keeps_supported_and_removes_fabricated(self):
        ps = self.passages("押金和垃圾收取時間")
        lease_n = next(p["n"] for p in ps if p["sid"] == self.lease["id"])
        ans = f"押金為兩個月租金，共 50000 元 [{lease_n}]。社區有游泳池可以使用 [{lease_n}]。月租金是三萬元 [9]。"
        r = cite.check(ans, ps)
        self.assertIn(f"共 50000 元[{lease_n}]。", r["answer"])
        self.assertIn("社區有游泳池可以使用" + cite.UNSOURCED, r["answer"])
        self.assertEqual({x["n"] for x in r["removed"]}, {lease_n, 9})
        self.assertEqual([c["n"] for c in r["citations"]], [lease_n])
        self.assertEqual(r["citations"][0]["source_id"], self.lease["id"])
        self.assertIn("租約", cite.appendix(r["citations"]))

    def test_unmarked_sentences_get_cited_or_flagged(self):
        ps = self.passages("押金")
        lease_n = next(p["n"] for p in ps if p["sid"] == self.lease["id"])
        r = cite.check("押金為兩個月租金。屋主住在台中市。", ps)
        self.assertIn(f"押金為兩個月租金[{lease_n}]。", r["answer"])             # 段落支持就補編號 / cited
        self.assertIn("屋主住在台中市" + cite.UNSOURCED, r["answer"])           # 否則標示 / flagged
        self.assertEqual(r["auto_cited"], 1)

    def test_numbers_must_match_the_passage(self):
        ps = self.passages("押金")
        n = next(p["n"] for p in ps if p["sid"] == self.lease["id"])
        r = cite.check(f"押金為兩個月租金 [{n}]。押金為九個月租金 [{n}]。", ps)
        self.assertIn(f"押金為兩個月租金[{n}]。", r["answer"])
        self.assertIn("押金為九個月租金" + cite.UNSOURCED, r["answer"])
        self.assertTrue(any(x["why"].startswith("number not in the passage: 9") for x in r["removed"]))
        r = cite.check(f"押金為 2 個月租金 [{n}]。", ps)                          # 2 == 兩
        self.assertEqual(r["citations"][0]["n"], n)

    def test_paraphrase_anchored_by_numbers(self):
        # 2026-11-25 實測：「八天」對「八日」、「過世」對「喪亡」，雙字詞支持度太低，正確答案被刪掉
        t = ("三、婚假：員工結婚者給予婚假八日，工資照給。\n"
             "四、喪假：父母、配偶喪亡者，給予喪假八日；祖父母、子女喪亡者，給予喪假六日。\n"
             "五、特別休假：滿一年以上未滿二年者，七日；滿二年以上未滿三年者，十日。")
        ps = [{"n": 1, "text": t, "sid": "s", "title": "規則", "id": "c", "start": 0, "end": len(t)}]
        r = cite.check("結婚可以請八天假[1]。祖父過世可以請六天假[1]。", ps)
        self.assertEqual(r["answer"], "結婚可以請八天假[1]。祖父過世可以請六天假[1]。")
        for wrong in ("結婚可以請六天假[1]。", "祖父過世可以請八天假[1]。",      # 數字在別的條文 / other clause
                      "祖父過世可以請八日喪假[1]。",                          # 「喪假」在父母那條 / generic word only
                      "工作滿一年以上未滿二年者，有十日特別休假[1]。"):       # 1、2、10 分散在不同條 / scattered
            self.assertTrue(cite.check(wrong, ps)["not_found"], wrong)
        r = cite.check("工作滿一年以上未滿二年者，有十日特別休假[1]。", ps)
        self.assertEqual(r["removed"][0]["why"], "numbers not in the same clause of the passage")
        ok = "結婚給予婚假八日，祖父母喪亡給予喪假六日[1]。"                    # 跨兩條各自對得上 / two clauses
        self.assertEqual(cite.check(ok, ps)["answer"], ok)

    def test_unknown_marker_falls_back_to_auto_cite(self):
        t = "五、特別休假：服務滿一年以上未滿二年者，七日。"
        ps = [{"n": 1, "text": t, "sid": "s", "title": "規則", "id": "c", "start": 0, "end": len(t)}]
        r = cite.check("工作滿一年半（滿一年以上未滿二年）有七日特別休假[5]。", ps)   # [5] 是條號 / clause number
        self.assertIn("七日特別休假[1]。", r["answer"])
        self.assertEqual([x["why"] for x in r["removed"]], ["no such passage"])
        self.assertEqual(r["removed"][0]["recited"], 1)                         # 已改正，不算查證發現 / corrected
        from jiezi.notebooks import verify
        self.assertFalse([f for f in verify.verify("特休", r, ps, {}) if f["check"] == "citation_removed"])

    def test_number_spans(self):
        from jiezi.notebooks.numbers import spans
        t = "[1] 婚假八日，喪假 6 日"
        self.assertEqual([(v, t[a:b]) for v, a, b in spans(t)], [("8", "八"), ("6", "6")])

    def test_number_values(self):
        from jiezi.notebooks.numbers import values
        self.assertEqual(values("從五十萬元增加到八十萬元"), values("從 50 萬元增加到 80 萬元"))
        self.assertEqual(values("二〇二六年一月一日"), {"2026", "1"})
        self.assertEqual(values("1. 一般來說統一處理 [3]"), set())               # 清單編號、引用、非數字詞 / ignored
        self.assertEqual(values("[00:12] 工程部要在 12 月 5 日前修好"), {"12", "5"})
        self.assertEqual(values("下午兩點，第三條，1,900 餘件，7.4%"), {"2", "3", "1900", "7.4"})

    def test_marker_after_full_stop(self):
        ps = self.passages("押金")
        n = next(p["n"] for p in ps if p["sid"] == self.lease["id"])
        r = cite.check(f"押金為兩個月租金。[{n}]", ps)
        self.assertEqual(r["answer"], f"押金為兩個月租金[{n}]。")

    def test_not_found_and_prompt(self):
        r = cite.check(cite.NOT_FOUND, [])
        self.assertTrue(r["not_found"])
        r = cite.check("量子電腦用量子位元 [1]。", self.passages("量子電腦"))    # 沒有任何有效出處 / nothing sourced
        self.assertTrue(r["not_found"])
        self.assertEqual(r["answer"], cite.NOT_FOUND)
        p = cite.prompt(self.passages("押金"), "租屋")
        self.assertIn("[1]《租約》", p)
        self.assertIn(cite.NOT_FOUND, p)
        self.assertIn("一般知識", cite.prompt([], "租屋", general=True))


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        tmp = Path(self._t.name)
        self.store = NotebookStore(tmp / "nb")
        self.addCleanup(self.store.close)
        self.nb = self.store.create("租屋")
        self.lease, _ = self.nb.add_source("租約", "file", LEASE)
        self.extra, _ = self.nb.add_source("補充協議", "file", OTHER_LEASE)
        self.memory = Memory(tmp / "wiki", root=tmp)   # 每個測試自己的信任把關 / a gate of its own
        self.sources = {s["id"]: s for s in self.nb.sources()}
        self.titles = {k: v["title"] for k, v in self.sources.items()}

    def run_check(self, q, answer, ps=None):
        ps = ps if ps is not None else cite.number(cite.retrieve(self.nb.chunks(), q), self.titles)
        checked = cite.check(answer.format(**{f"n{p['n']}": p["n"] for p in ps}), ps)
        return checked, verify.verify(q, checked, ps, self.sources, self.memory, multi_source=True), ps

    def test_clean_answer_passes_and_is_saved(self):
        ps = [p for p in cite.number(cite.retrieve(self.nb.chunks(), "每月租金多少"), self.titles)
              if p["sid"] == self.lease["id"]][:1]
        ps[0]["n"] = 1
        checked, findings, _ = self.run_check("每月租金多少", "每月租金新台幣 25000 元 [1]。", ps)
        self.assertEqual(findings, [])
        page = memory_link.save_answer(self.memory, self.nb, "每月租金多少", checked)
        self.assertTrue(page)
        e, _ = self.memory.find_answer("每月租金多少")
        self.assertIn("25000", e.text)
        self.assertIn("租約", e.text)

    def test_each_check_reports(self):
        ps = cite.number(cite.retrieve(self.nb.chunks(), "押金是幾個月"), self.titles)
        n = next(p["n"] for p in ps if p["sid"] == self.lease["id"])
        m = next(p["n"] for p in ps if p["sid"] == self.extra["id"])
        _, f, _ = self.run_check("押金是幾個月", f"押金為兩個月租金 [{n}]，補充協議改為三個月租金 [{m}]。", ps)
        self.assertIn("source_conflict", {x["check"] for x in f})                       # b
        _, f, _ = self.run_check("押金是幾個月", "押金可能是兩個月租金 [%d]。" % n, ps)
        self.assertIn("uncertain", {x["check"] for x in f})                             # e
        _, f, _ = self.run_check("那份的押金是幾個月", "押金為兩個月租金 [%d]。" % n, ps)
        self.assertIn("ambiguous_question", {x["check"] for x in f})                    # e
        _, f, _ = self.run_check("押金是幾個月", "押金為兩個月租金 [%d]。屋主住在台中市。" % n, ps)
        self.assertIn("unsourced", {x["check"] for x in f})                             # a
        _, f, _ = self.run_check("押金是幾個月", "屋主住在台中市。房東姓王。", ps)
        self.assertEqual({x["check"] for x in f}, {"not_found"})                        # 全無出處 / nothing sourced
        self.memory.save_correction("押金是幾個月", "押金其實是 1 個月")
        _, f, _ = self.run_check("押金是幾個月", "押金為兩個月租金，共 50000 元 [%d]。" % n, ps)
        self.assertIn("memory_conflict", {x["check"] for x in f})                       # c
        self.assertEqual(verify._nums("押金兩個月 [1]、共 50000 元［2］"), {"2", "50000"})   # 編號不算 / markers ignored
        self.sources[self.lease["id"]]["trust"] = {"level": "tainted"}
        _, f, _ = self.run_check("押金", "押金為兩個月租金 [%d]。" % n, ps)
        self.assertIn("flagged_source", {x["check"] for x in f})                        # d


class RecallTests(unittest.TestCase):
    def test_digest_and_recall_from_normal_chat(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            store = NotebookStore(tmp / "nb")
            nb = store.create("租屋")
            nb.add_source("租約", "file", LEASE)
            p = memory_link.write_digest(tmp / "wiki", nb)
            self.assertIn("### 租約", p.read_text(encoding="utf-8"))
            got = memory_link.recall_block(store, "我的租約押金是多少？", wiki=tmp / "wiki")
            self.assertIsNotNone(got)
            content, sources, trainable, _, extra = got
            self.assertIn("[1]《租約》", content)
            self.assertFalse(trainable)
            self.assertEqual(sources[0]["source"], "notebook")
            self.assertIsNone(memory_link.recall_block(store, "台灣最高的山是哪一座？", wiki=tmp / "wiki"))
            memory_link.remove_digest(tmp / "wiki", "租屋")
            self.assertFalse(p.exists())
            store.close()


if __name__ == "__main__":
    unittest.main()


# ── gateway 整合 / gateway integration ──
import json  # noqa: E402

import httpx  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from jiezi.runtime.gateway import Gateway, create_app  # noqa: E402
from jiezi.runtime.trajectory import TrajectoryWriter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_runtime_gateway as RG  # noqa: E402

H = {"Authorization": f"Bearer {RG.KEY}"}


class GatewayNotebookTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.tmp = Path(self._t.name)

    def client(self, answers):
        sup, _, patch = RG.make_supervisor(self.tmp)
        patch.start()
        self.addCleanup(patch.stop)
        lh, self.seen = RG.local_handler(answers)
        self.gw = Gateway(sup.s, sup, TrajectoryWriter(self.tmp / "traj", log=lambda *_: None),
                          local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)),
                          cloud_http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))),
                          log=lambda *_: None)
        return TestClient(create_app(self.gw))

    def notebook(self, c):
        nb = c.post("/v1/notebooks", headers=H, json={"name": "租屋"}).json()
        r = c.post(f"/v1/notebooks/{nb['id']}/sources", headers=H, json={"title": "租約", "text": LEASE})
        self.assertEqual(r.status_code, 201, r.text)
        again = c.post(f"/v1/notebooks/{nb['id']}/sources", headers=H, json={"title": "租約", "text": LEASE}).json()
        self.assertFalse(again["created"])
        return nb, r.json()["source"]

    def ask(self, c, nid, q, stream=False):
        return c.post("/v1/chat/completions", headers=H, json={
            "model": "jiezi-local", "stream": stream, "jiezi_notebook": nid,
            "messages": [{"role": "user", "content": q}]})

    def test_cited_answer_is_checked_and_saved_to_memory(self):
        with self.client([{"role": "assistant", "content": "每月租金新台幣 25000 元 [1]。"}]) as c:
            nb, src = self.notebook(c)
            r = self.ask(c, nb["id"], "每月租金是多少？").json()
            meta = r["jiezi"]["notebook"]
            self.assertEqual(meta["citations"][0]["source_id"], src["id"])
            self.assertTrue(meta["memory"]["saved"], meta["memory"])
            content = r["choices"][0]["message"]["content"]
            self.assertIn("25000 元[1]。", content)
            self.assertIn("【筆記本來源】", content)
            sent = json.dumps(self.seen[0], ensure_ascii=False)
            self.assertIn("[1]《租約》", sent)                              # 段落有送給模型 / passages reached the model
            e, _ = self.gw.memory.find_answer("每月租金是多少？")
            self.assertIn("筆記本《租屋》", e.provider)
            wiki = self.tmp / "var" / "memory" / "wiki"
            self.assertTrue(any((wiki / "notebooks").glob("*.md")))          # 摘要頁 / digest page
            full = c.get(f"/v1/notebooks/{nb['id']}/sources/{src['id']}", headers=H).json()
            cit = meta["citations"][0]
            self.assertIn("25000", full["text"][cit["start"]:cit["end"]])

    def test_findings_block_saving_until_user_confirms(self):
        with self.client([{"role": "assistant", "content": "押金可能是兩個月租金 [1]。社區有游泳池 [1]。"}]) as c:
            nb, _ = self.notebook(c)
            r = self.ask(c, nb["id"], "押金是幾個月？").json()
            mem = r["jiezi"]["notebook"]["memory"]
            self.assertFalse(mem["saved"])
            checks = {f["check"] for f in mem["findings"]}
            self.assertTrue({"uncertain", "citation_removed"} <= checks, checks)
            self.assertIn("（未找到出處）", r["choices"][0]["message"]["content"])
            self.assertIsNone(self.gw.memory.find_answer("押金是幾個月？"))
            ok = c.post(f"/v1/notebooks/{nb['id']}/remember", headers=H,
                        json={"trajectory_id": r["jiezi"]["trajectory_id"]}).json()
            self.assertTrue(ok["saved"])
            e, _ = self.gw.memory.find_answer("押金是幾個月？")
            self.assertIn("仍存", e.text)

    def test_not_found_stream_and_unknown_notebook(self):
        with self.client([{"role": "assistant", "content": "量子電腦用量子位元 [1]。"}]) as c:
            nb, _ = self.notebook(c)
            r = self.ask(c, nb["id"], "量子電腦的原理是什麼？").json()
            self.assertEqual(r["choices"][0]["message"]["content"], cite_NOT_FOUND)
            self.assertEqual(r["jiezi"]["notebook"]["memory"].get("skipped"), "not_found")
            s = self.ask(c, nb["id"], "量子電腦的原理是什麼？", stream=True)
            self.assertIn(cite_NOT_FOUND, s.text)                              # 串流也是檢查後的答案 / stream too
            self.assertEqual(self.ask(c, "zzzzzzzz", "hi").status_code, 404)

    def test_normal_chat_recalls_notebook(self):
        with self.client([{"role": "assistant", "content": "押金為兩個月租金，共 50000 元 [1]。"}]) as c:
            self.notebook(c)
            r = c.post("/v1/chat/completions", headers=H, json={
                "model": "jiezi-local", "messages": [{"role": "user", "content": "我的租約押金是多少？"}]}).json()
            self.assertTrue(r["jiezi"]["notebook"]["recall"])
            self.assertIn("【筆記本來源】", r["choices"][0]["message"]["content"])
            self.assertNotIn("memory", r["jiezi"]["notebook"])                 # 召回不自動存 / recall does not save
            t = [json.loads(x) for f in (self.tmp / "traj").glob("*.jsonl") for x in f.read_text().splitlines()]
            self.assertFalse(t[-1]["training_use"])

    def test_api_auth_and_delete(self):
        with self.client([{"role": "assistant", "content": "x"}]) as c:
            self.assertEqual(c.get("/v1/notebooks").status_code, 401)
            nb, src = self.notebook(c)
            self.assertEqual(len(c.get(f"/v1/notebooks/{nb['id']}", headers=H).json()["sources"]), 1)
            self.assertTrue(c.delete(f"/v1/notebooks/{nb['id']}/sources/{src['id']}", headers=H).json()["deleted"])
            self.assertTrue(c.delete(f"/v1/notebooks/{nb['id']}", headers=H).json()["deleted"])
            self.assertEqual(c.get("/v1/notebooks", headers=H).json()["data"], [])


cite_NOT_FOUND = cite.NOT_FOUND


class NotesTests(unittest.TestCase):
    def test_map_reduce_checks_citations_and_saves_a_note(self):
        import anyio
        from jiezi.notebooks import notes
        with tempfile.TemporaryDirectory() as d:
            store = NotebookStore(Path(d))
            nb = store.create("租屋")
            nb.add_source("租約", "file", LEASE)
            nb.add_source("管理規約", "text", RULES)
            calls = []

            async def complete(msgs, max_tokens):
                calls.append(msgs[-1]["content"])
                if "各段重點" in msgs[-1]["content"]:
                    return "押金為兩個月租金，共 50000 元 [1]。垃圾於每週一、三、五晚上八點收取 [2]。社區有健身房 [1]。"
                return "押金兩個月、共 50000 元。" if "押金" in msgs[-1]["content"] else "垃圾每週一、三、五晚上八點收取。"
            out = anyio.run(notes.generate, None, nb, "summary", complete)
            self.assertEqual(len(calls), 3)                                     # 2 段 map＋1 次 reduce
            self.assertEqual({c["n"] for c in out["citations"]}, {1, 2})
            self.assertIn("社區有健身房（未找到出處）", out["answer"])
            note = nb.source(out["source"]["id"])
            self.assertEqual(note["kind"], "note")
            self.assertIn("出處：", note["text"])
            out2 = anyio.run(notes.generate, None, nb, "faq", complete)          # 舊筆記不再被整理 / notes not re-mapped
            self.assertEqual(len(calls), 6)
            self.assertEqual(out2["label"], "常見問答")
            with self.assertRaises(ValueError):
                anyio.run(notes.generate, None, nb, "poem", complete)
            one = [{"sid": "a", "i": i} for i in range(100)]
            self.assertEqual([c["i"] for c in notes.pick(one, 10)[0]], [0, 10, 20, 30, 40, 50, 60, 70, 80, 90])
            mixed = [{"sid": "pdf", "i": 0}, {"sid": "pdf", "i": 1}, {"sid": "mp3", "i": 0}] + one
            got, sampled = notes.pick(mixed, 10)                      # 每份來源都有 / every source is covered
            self.assertTrue(sampled)
            self.assertEqual(len(got), 10)
            self.assertEqual({c["sid"] for c in got}, {"pdf", "mp3", "a"})
            store.close()

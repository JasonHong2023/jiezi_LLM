"""長文件與讀檔測試（add-long-documents）：各格式讀取、子行程限制、分段、挑段落、map-reduce、gateway 濃縮、CLI 附檔。
Long-document and reader tests: formats, the child-process reader, chunking, selection, map-reduce, gateway, CLI."""

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import anyio

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import documents as D  # noqa: E402
from jiezi import longdoc as L  # noqa: E402
from jiezi.runtime.context import est_tokens  # noqa: E402


def make_pdf(text: str) -> bytes:
    """手工產生一頁含 ASCII 文字的 PDF（不需要額外套件）。 / A one-page PDF with ASCII text, built by hand."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    return bytes(out)


def make_docx(paras: list[str], table: list[list[str]] | None = None, doctype: bool = False) -> bytes:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paras)
    if table:
        body += "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row)
                                    + "</w:tr>" for row in table) + "</w:tbl>"
    xml = (('<!DOCTYPE x [<!ENTITY a "b">]>' if doctype else "") +
           f'<?xml version="1.0"?><w:document {w}><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


class TestReaders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_pdf_in_child_process(self):
        p = self.d / "a.pdf"
        p.write_bytes(make_pdf("Quarterly revenue grew 12 percent in Taipei"))
        r = D.read(p)
        self.assertIn("revenue grew 12 percent", r["text"])
        self.assertEqual((r["kind"], r["pages"]), ("pdf", 1))

    def test_scanned_page_goes_to_ocr(self):
        class Img:
            data = b"png"

        class Page:
            images = [Img()]

            def extract_text(self):
                return ""

        class Reader:
            is_encrypted = False
            pages = [Page()]
        import pypdf
        orig = pypdf.PdfReader
        pypdf.PdfReader = lambda *_a, **_k: Reader()
        try:
            r = D.read_pdf(b"x", ocr=lambda data: "掃描的文字內容")
        finally:
            pypdf.PdfReader = orig
        self.assertEqual(r["ocr_pages"], [1])
        self.assertIn("掃描的文字內容", r["text"])

    def test_docx_text_and_table(self):
        p = self.d / "b.docx"
        p.write_bytes(make_docx(["第一段文字", "第二段"], [["項目", "金額"], ["房租", "12000"]]))
        r = D.read(p)
        self.assertIn("第一段文字", r["text"])
        self.assertIn("房租 | 12000", r["text"])

    def test_docx_with_dtd_is_refused(self):
        p = self.d / "c.docx"
        p.write_bytes(make_docx(["x"], doctype=True))
        with self.assertRaisesRegex(D.DocumentError, "DTD"):
            D.read(p)

    def test_html_drops_scripts(self):
        p = self.d / "d.html"
        p.write_text("<html><head><title>t</title><script>alert(1)</script></head><body><h1>標題</h1>"
                     "<p>內文&amp;說明</p></body></html>", encoding="utf-8")
        r = D.read(p)
        self.assertIn("標題", r["text"])
        self.assertIn("內文&說明", r["text"])
        self.assertNotIn("alert", r["text"])

    def test_big5_text_and_errors(self):
        p = self.d / "e.txt"
        p.write_bytes("繁體中文的文件".encode("cp950"))
        self.assertEqual(D.read(p)["text"], "繁體中文的文件")
        with self.assertRaisesRegex(D.DocumentError, "不支援"):
            (self.d / "f.exe").write_bytes(b"x")
            D.read(self.d / "f.exe")
        with self.assertRaisesRegex(D.DocumentError, "找不到"):
            D.read(self.d / "missing.pdf")
        (self.d / "g.pdf").write_bytes(b"not a pdf at all")
        with self.assertRaises(D.DocumentError):  # 損壞檔只讓子行程失敗 / a broken file only fails the child
            D.read(self.d / "g.pdf")


LONG = "\n\n".join(f"第{i}節：這是一份關於台灣能源政策的報告，本節討論{topic}，相關數據為{i * 7}億元。" * 6
                   for i, topic in enumerate(["太陽能", "風力發電", "核能", "天然氣", "節能補助", "電網韌性"] * 8, 1))


async def fake_complete(msgs, max_tokens, calls=None):
    if calls is not None:
        calls.append(msgs)
    return "- 重點：" + msgs[-1]["content"][:30]


class TestLongdoc(unittest.TestCase):
    def test_chunks_fit(self):
        parts = L.chunks(LONG)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(est_tokens(p) <= L.CHUNK_TOKENS for p in parts))
        self.assertTrue(all(est_tokens(p) <= L.CHUNK_TOKENS for p in L.chunks("無標點" * 5000)))

    def test_split_message(self):
        content = D.attach({"name": "報告.pdf", "text": LONG}, "請摘要這份報告")
        docs, q = L.split_message(content)
        self.assertEqual((docs[0][0], q), ("報告.pdf", "請摘要這份報告"))
        docs, q = L.split_message("很長的內容" * 10 + "\n\n這段在說什麼？")
        self.assertEqual(q, "這段在說什麼？")

    def test_summary_map_reduce(self):
        calls = []
        new, info = anyio.run(L.condense, D.attach({"name": "報告.pdf", "text": LONG}, "請整理重點"),
                              lambda m, n: fake_complete(m, n, calls))
        self.assertEqual(info["mode"], "summary")
        self.assertEqual(info["summaries"][0]["chunks"], len(L.chunks(LONG)))
        self.assertGreaterEqual(len(calls), info["summaries"][0]["chunks"])
        self.assertIn("請整理重點", new)
        self.assertLessEqual(est_tokens(new), L.LIMIT + 200)

    def test_question_selects_relevant_chunks(self):
        parts = L.chunks(LONG, L.QA_CHUNK_TOKENS)
        target = next(i for i, p in enumerate(parts) if "風力發電" in p)
        new, info = anyio.run(L.condense, D.attach({"name": "報告.pdf", "text": LONG}, "風力發電的數據是多少？"),
                              fake_complete)
        self.assertEqual(info["mode"], "qa")
        self.assertIn(target, info["selected"][0]["kept"])
        self.assertIn("風力發電", new)
        self.assertLessEqual(est_tokens(new), L.LIMIT + 200)

    def test_short_messages_untouched(self):
        self.assertFalse(L.needed("短問題"))
        self.assertTrue(L.needed(LONG))


class TestGatewayLongdoc(unittest.TestCase):
    def test_condensed_before_answer(self):
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp, samples=1)
            lh, seen = local_handler([{"role": "assistant", "content": "- 重點"}])
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
            content = D.attach({"name": "報告.pdf", "text": LONG}, "請摘要")
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                           json={"model": "jiezi-local", "messages": [{"role": "user", "content": content}]})
            self.assertEqual(r.status_code, 200)
            final = seen[-1]["messages"][-1]["content"]
            self.assertIn("分", final)
            self.assertNotIn(LONG[:200], final)              # 原文沒有整份送進去 / not sent whole
            self.assertGreater(len(seen), 2)                  # 先分段整理 / chunks summarized first
            self.assertLessEqual(est_tokens(final), L.LIMIT + 200)


class TestFollowUp(unittest.TestCase):
    """長文件追問（add-document-followup）。 / Follow-up questions over the same document."""

    def test_hint_finds_chunk_for_vague_follow_up(self):
        parts = L.chunks(LONG, L.QA_CHUNK_TOKENS)
        target = next(i for i, p in enumerate(parts) if "風力發電" in p)
        vague = "那相關數據是多少？"
        with_hint = L.rank(vague, parts, hint="風力發電的發展如何？\n報告提到風力發電持續成長。")
        self.assertIn("風力發電", parts[with_hint[0][1]])                 # 靠上一輪問答找到 / found through the hint
        top = L.rank("核能的數據是多少？", parts, hint="風力發電的發展如何？")[0][1]
        self.assertIn("核能", parts[top])                                 # 這一題的字比上一輪重要 / the question outweighs
        self.assertEqual(L.rank(vague, parts), L.rank(vague, parts, hint="  "))
        self.assertIsNotNone(target)

    def test_budget_leaves_room_for_previous_turn(self):
        content = D.attach({"name": "報告.pdf", "text": LONG}, "風力發電的數據是多少？")
        full, _ = anyio.run(L.condense, content, fake_complete)
        small, _ = anyio.run(lambda: L.condense(content, fake_complete, budget=L.LIMIT - L.FOLLOWUP_RESERVE))
        self.assertLess(est_tokens(small), est_tokens(full))
        self.assertLessEqual(est_tokens(small), L.LIMIT - L.FOLLOWUP_RESERVE + 200)

    def test_notes_cache_skips_map_step(self):
        cache, calls = L.NotesCache(size=2), []
        content = D.attach({"name": "報告.pdf", "text": LONG}, "請整理重點")

        async def run():
            return await L.condense(content, lambda m, n: fake_complete(m, n, calls), cache=cache)
        _, first = anyio.run(run)
        n = len(calls)
        self.assertFalse(first["summaries"][0]["cached"])
        _, second = anyio.run(run)
        self.assertTrue(second["summaries"][0]["cached"])
        self.assertLess(len(calls) - n, first["summaries"][0]["chunks"])  # 不重跑各段整理 / map step not repeated
        for i in range(3):                                                # 只留最近幾份 / bounded
            cache.put(f"d{i}", "x", ["n"])
        self.assertEqual(len(cache.rows), 2)
        self.assertIsNone(cache.get("報告.pdf", LONG))

    def test_failed_chunk_is_not_cached(self):
        cache = L.NotesCache()

        async def flaky(msgs, max_tokens):
            return "" if "第 2/" in msgs[0]["content"] else "- 重點"
        anyio.run(lambda: L.summarize("a", LONG, flaky, cache=cache))
        self.assertEqual(len(cache.rows), 0)

    def test_gateway_follow_up(self):
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp, samples=1)
            lh, seen = local_handler([{"role": "assistant", "content": "- 重點"}])
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
            h = {"Authorization": f"Bearer {KEY}"}
            doc = {"name": "報告.pdf", "text": LONG}
            with patch, TestClient(create_app(gw)) as c:
                c.post("/v1/chat/completions", headers=h, json={"model": "jiezi-local", "messages": [
                    {"role": "user", "content": D.attach(doc, "請摘要")}]})
                first = len(seen)
                c.post("/v1/chat/completions", headers=h, json={"model": "jiezi-local", "messages": [
                    {"role": "user", "content": "請摘要"}, {"role": "assistant", "content": "這份報告談能源政策。"},
                    {"role": "user", "content": D.attach(doc, "再整理一次重點")}]})
                second = len(seen) - first
                c.post("/v1/chat/completions", headers=h, json={"model": "jiezi-local", "messages": [
                    {"role": "user", "content": "核能那一節談了什麼？"}, {"role": "assistant", "content": "談核能的預算。"},
                    {"role": "user", "content": D.attach(doc, "那相關數據是多少？")}]})
            recs = [json.loads(x) for f in (tmp / "traj").glob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
        self.assertLess(second, first)                                    # 第二次摘要用快取 / the second summary is cached
        self.assertTrue(recs[1]["longdoc"]["summaries"][0]["cached"])
        self.assertEqual([r["longdoc"]["followup"] for r in recs], [False, True, True])
        final = seen[-1]["messages"]
        self.assertEqual(recs[2]["longdoc"]["mode"], "qa")
        self.assertIn("核能", final[-1]["content"])                        # 依上一輪挑到核能的段落 / chosen via the hint
        self.assertEqual([m["content"] for m in final if m["role"] == "assistant"], ["談核能的預算。"])  # 上一輪還在 / kept
        self.assertLessEqual(est_tokens(final[-1]["content"]), L.LIMIT)
        self.assertLess(len(final[-1]["content"]), len(LONG) // 2)       # 不是整份送 / not sent whole


class TestChatDocuments(unittest.TestCase):
    def test_documents_ride_with_every_question(self):
        from jiezi.cli.chat import with_documents
        docs = [{"name": "a.pdf", "text": "甲文件"}, {"name": "b.docx", "text": "乙文件"}]
        history = [{"role": "user", "content": "第一題"}, {"role": "assistant", "content": "答"},
                   {"role": "user", "content": "第二題"}]
        out = with_documents(history, docs)
        got, q = L.split_message(out[-1]["content"])
        self.assertEqual(([n for n, _ in got], q), (["a.pdf", "b.docx"], "第二題"))
        self.assertEqual(history[-1]["content"], "第二題")                  # 歷史只存問題 / history keeps the bare question
        self.assertEqual(out[0]["content"], "第一題")                       # 舊的問題不重附 / older turns stay bare
        self.assertIs(with_documents(history, []), history)
        multi = [{"role": "user", "content": [{"type": "text", "text": "看圖"}, {"type": "image_url", "image_url": {"url": "x"}}]}]
        out = with_documents(multi, docs[:1])
        self.assertIn("【文件：a.pdf】", out[0]["content"][0]["text"])
        self.assertEqual(multi[0]["content"][0]["text"], "看圖")

    def test_chat_file_stays_attached_until_cleared(self):
        from unittest import mock
        from jiezi.cli import chat
        from jiezi.cli.client import Connection
        sent = []

        async def fake_stream(conn, messages, policy, **kw):
            sent.append(messages)
            yield "delta", "答案"
            yield "meta", {"tier": 0, "model": "core"}

        async def go():
            with tempfile.TemporaryDirectory() as d:
                f = Path(d) / "筆記.txt"
                f.write_text("芥子納須彌的出處是維摩詰經。", encoding="utf-8")
                app = chat.ChatApp(Connection("http://x", "k"), reporter=mock.Mock())
                with mock.patch.object(chat, "stream_chat", fake_stream):
                    async with app.run_test(size=(80, 24)) as pilot:
                        async def ask(q):
                            app.query_one("#prompt").text = q
                            await pilot.press("enter")
                            await app.workers.wait_for_complete()
                            await pilot.pause()
                        await ask(f"/file {f}")
                        await ask("出處是什麼")
                        await ask("再說一次")
                        await ask("/file clear")
                        await ask("謝謝")
                        return app.history
        history = anyio.run(go)
        self.assertEqual(len(sent), 3)
        self.assertIn("【文件：筆記.txt】", sent[0][-1]["content"])
        self.assertIn("【文件：筆記.txt】", sent[1][-1]["content"])           # 追問仍帶文件 / follow-up carries it
        self.assertNotIn("【文件：", sent[1][0]["content"])                    # 上一題不重複帶 / not duplicated in history
        self.assertNotIn("【文件：", sent[2][-1]["content"])                   # 取消後不帶 / detached
        self.assertEqual([m["content"] for m in history if m["role"] == "user"], ["出處是什麼", "再說一次", "謝謝"])


class TestAskFile(unittest.TestCase):
    def test_build_messages_wraps_documents(self):
        from jiezi.cli.ask import build_messages
        m = build_messages("摘要", "管線的內容", [{"name": "a.pdf", "text": "PDF 內容"}])
        docs, q = L.split_message(m[0]["content"])
        self.assertEqual([n for n, _ in docs], ["管線輸入", "a.pdf"])
        self.assertEqual(q, "摘要")


if __name__ == "__main__":
    unittest.main()

"""問題裡打的本機檔案路徑（使用者 2026-11-18）。 / Local file paths typed into a question."""
import base64
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jiezi.localpaths import PATH_NOTE, find_paths, is_image, strip_paths, to_local  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class TestFind(unittest.TestCase):
    def test_windows_quoted_bare_and_not_paths(self):
        q = r"'D:\download\istockphoto-1194518176-1024x1024.jpg' 這圖片中有那些動物"
        self.assertEqual(find_paths(q), [r"D:\download\istockphoto-1194518176-1024x1024.jpg"])
        self.assertEqual(strip_paths(q, find_paths(q)), "這圖片中有那些動物")
        self.assertEqual(find_paths(r"看 C:\Users\me\報告.pdf 的重點"), [r"C:\Users\me\報告.pdf"])
        self.assertEqual(find_paths("「D:\\my pics\\cat.webp」裡是什麼"), ["D:\\my pics\\cat.webp"])
        self.assertEqual(find_paths("~/圖/a.png 和 /mnt/c/x/b.txt"), ["~/圖/a.png", "/mnt/c/x/b.txt"])
        for not_path in ("http://example.com/a.jpg 是什麼", "版本 1.2.png 不是路徑", "沒有路徑的問題"):
            self.assertEqual(find_paths(not_path), [], not_path)

    def test_to_local_and_kind(self):
        self.assertEqual(to_local(r"D:\download\a b.jpg", Path("/mnt")), Path("/mnt/d/download/a b.jpg"))
        self.assertEqual(to_local("/tmp/x.png"), Path("/tmp/x.png"))
        self.assertTrue(is_image("X.JPEG"))
        self.assertFalse(is_image("x.pdf"))
        self.assertIn("不要猜測", PATH_NOTE)


class TestGatewayNote(unittest.TestCase):
    def test_note_only_when_nothing_attached(self):
        sys.path.insert(0, str(ROOT / "tests"))
        from jiezi.runtime.gateway import Gateway
        gw = Gateway.__new__(Gateway)
        body = {"messages": [{"role": "user", "content": r"'D:\a\cat.jpg' 這圖片中有那些動物"}]}
        rec = {}
        gw._path_note(body, rec)
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn("D:\\a\\cat.jpg", body["messages"][0]["content"])
        self.assertEqual(rec["path_note"], [r"D:\a\cat.jpg"])
        img = {"messages": [{"role": "user", "content": [{"type": "text", "text": r"D:\a\cat.jpg 是什麼"},
                                                         {"type": "image_url", "image_url": {"url": "data:image/png;base64,x"}}]}]}
        gw._path_note(img, {})
        self.assertEqual(len(img["messages"]), 1)                                # 已附圖 / image attached
        plain = {"messages": [{"role": "user", "content": "玉山多高？"}]}
        gw._path_note(plain, {})
        self.assertEqual(len(plain["messages"]), 1)


class TestGatewayReadPaths(unittest.TestCase):
    """gateway 讀使用者打的路徑（add-image-paths）。 / The gateway reads typed paths."""

    def setUp(self):
        import types
        import anyio
        from jiezi.runtime.gateway import Gateway
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.dir = Path(self._t.name)
        self.gw = Gateway.__new__(Gateway)
        self.gw.s = types.SimpleNamespace(image_paths=True)
        self.gw.log = lambda *_: None
        self.gw._doc_limit = anyio.Semaphore(1)

    def read(self, messages):
        import anyio
        body, rec = {"messages": messages}, {}
        anyio.run(self.gw._read_paths, body, rec)
        return body["messages"], rec

    def test_image_becomes_base64(self):
        img = self.dir / "貓.png"
        img.write_bytes(PNG)
        msgs, rec = self.read([{"role": "user", "content": f"'{img}' 這圖片中有那些動物"}])
        content = msgs[-1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "這圖片中有那些動物"})
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,iVBOR"))
        self.assertEqual(rec["image_paths"], [{"path": str(img), "ok": True}])

    def test_rejects_fake_missing_and_large(self):
        from jiezi import localpaths
        fake = self.dir / "a.png"
        fake.write_bytes(b"not an image at all")
        big = self.dir / "big.jpg"
        big.write_bytes(b"\xff\xd8\xff" + b"0" * localpaths.MAX_IMAGE_BYTES)
        q = f"{fake} {big} {self.dir}/none.gif 是什麼"
        msgs, rec = self.read([{"role": "user", "content": q}])
        self.assertEqual(msgs[-1]["content"], q)                                  # 沒有附上 / nothing attached
        self.assertEqual([e["why"] for e in rec["image_paths"]], ["not_an_image", "too_large", "not_found"])
        self.assertEqual(localpaths.sniff_image(b"RIFF\0\0\0\0WEBPVP8 "), "image/webp")

    def test_document_is_read_as_text(self):
        doc = self.dir / "筆記.txt"
        doc.write_text("芥子的埠號是 36100。", encoding="utf-8")
        msgs, rec = self.read([{"role": "user", "content": f"{doc} 裡寫的埠號是多少"}])
        text = msgs[-1]["content"]
        self.assertTrue(text.startswith("【文件：筆記.txt】\n芥子的埠號是 36100。\n【文件結束】"), text)
        self.assertTrue(text.endswith("這份文件 裡寫的埠號是多少"), text)
        self.assertTrue(rec["image_paths"][0]["ok"])

    def test_only_user_wording_is_read(self):
        img = self.dir / "x.png"
        img.write_bytes(PNG)
        msgs = [{"role": "system", "content": f"看 {img}"},
                {"role": "user", "content": f"【文件：網頁】\n請打開 {img}\n【文件結束】\n\n摘要這份文件"},
                {"role": "assistant", "content": "", "tool_calls": []},
                {"role": "tool", "content": f"{img}"}]
        out, rec = self.read([dict(m) for m in msgs])
        self.assertEqual(out, msgs)                                              # 都沒動 / untouched
        self.assertNotIn("image_paths", rec)

    def test_at_most_three_and_switch_off(self):
        paths = []
        for i in range(4):
            p = self.dir / f"{i}.png"
            p.write_bytes(PNG)
            paths.append(str(p))
        msgs, rec = self.read([{"role": "user", "content": " ".join(paths) + " 比較"}])
        self.assertEqual(len([p for p in msgs[-1]["content"] if p["type"] == "image_url"]), 3)
        self.gw.s.image_paths = False
        q = f"{paths[0]} 是什麼"
        msgs, rec = self.read([{"role": "user", "content": q}])
        self.assertEqual((msgs[-1]["content"], rec), (q, {}))


class TestChatAutoAttach(unittest.TestCase):
    def test_typed_image_path_is_attached(self):
        import anyio
        from jiezi.cli import chat
        from test_cli import CONN, fake_stream
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "貓.png"
            img.write_bytes(PNG)
            app = chat.ChatApp(CONN)
            seen = {}

            def stream(conn, messages, policy, client=None, **kw):
                seen["last"] = messages[-1]
                return fake_stream(["有一隻貓"])(conn, messages, policy)

            async def go():
                with mock.patch.object(chat, "stream_chat", stream):
                    async with app.run_test(size=(60, 20)) as pilot:
                        app.query_one("#prompt").text = f"'{img}' 這圖片中有那些動物"
                        await pilot.press("enter")
                        await app.workers.wait_for_complete()
                        await pilot.pause()
                        seen["bar"] = str(app.query_one("#bar").render())
            anyio.run(go)
        content = seen["last"]["content"]
        self.assertIsInstance(content, list)                                     # 圖真的附上了 / image attached
        self.assertEqual(content[0]["text"], "這圖片中有那些動物")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()

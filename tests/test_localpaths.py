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

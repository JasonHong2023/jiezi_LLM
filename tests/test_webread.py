"""讀使用者給的網址（add-web-read）。 / Reading typed URLs locally."""
import asyncio
import socket
import sys
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jiezi import webread as W  # noqa: E402

PAGE = b"<html><head><title>Python 3 docs</title></head><body><h1>Python</h1><p>Tutorial and library.</p></body></html>"


def resolver(table):
    def resolve(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (table.get(host, "93.184.216.34"), 0))]
    return resolve


def client(routes):
    def handler(request):
        status, headers, body = routes[str(request.url)]
        return httpx.Response(status, headers=headers, content=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


class TestWebRead(unittest.TestCase):
    def run_fetch(self, url, routes, table=None):
        return asyncio.run(W.fetch(url, client(routes), resolver(table or {})))

    def test_reads_html(self):
        out = self.run_fetch("https://docs.python.org/3/", {
            "https://docs.python.org/3/": (200, {"content-type": "text/html; charset=utf-8"}, PAGE)})
        self.assertEqual(out["title"], "Python 3 docs")
        self.assertIn("Tutorial and library.", out["text"])

    def test_refuses_private_and_redirect_to_private(self):
        with self.assertRaisesRegex(W.WebError, "private_address"):
            self.run_fetch("http://router.local/", {}, {"router.local": "192.168.1.1"})
        with self.assertRaisesRegex(W.WebError, "private_address"):
            self.run_fetch("https://a.example/", {
                "https://a.example/": (302, {"location": "http://127.0.0.1:36100/admin/doctor"}, b"")})

    def test_limits(self):
        with self.assertRaisesRegex(W.WebError, "not_text"):
            self.run_fetch("https://a.example/x.zip", {
                "https://a.example/x.zip": (200, {"content-type": "application/zip"}, b"PK")})
        with self.assertRaisesRegex(W.WebError, "http_404"):
            self.run_fetch("https://a.example/", {"https://a.example/": (404, {}, b"")})
        big = b"<p>" + b"x" * (W.MAX_BYTES + 1)
        with self.assertRaisesRegex(W.WebError, "too_large"):
            self.run_fetch("https://a.example/", {"https://a.example/": (200, {"content-type": "text/html"}, big)})
        with self.assertRaisesRegex(W.WebError, "not_http"):
            self.run_fetch("file:///etc/passwd", {})

    def test_find_urls_and_memo(self):
        q = "仔細閱讀和分析這個網址的內容並記憶起來 https://docs.ubuntu.com/。"
        self.assertEqual(W.find_urls(q), ["https://docs.ubuntu.com/"])
        self.assertTrue(W.MEMO.search(q))
        self.assertFalse(W.MEMO.search("摘要 https://a.example/"))


class TestWebMemo(unittest.TestCase):
    def test_site_keys_and_recall(self):
        import tempfile
        self.assertEqual(W.site_keys("https://docs.ubuntu.com/", "Ubuntu documentation"), ["ubuntu"])
        self.assertEqual(W.site_keys("https://docs.python.org/3/", "3.15.2 Documentation"), ["python"])
        with tempfile.TemporaryDirectory() as d:
            W.remember(d, "https://docs.ubuntu.com/", "Ubuntu documentation", "Canonical 的官方文件目錄。", "p")
            self.assertEqual([r["url"] for r in W.recall(d, "Ubuntu 官方文件網站有哪些產品的文件？")],
                             ["https://docs.ubuntu.com/"])
            self.assertEqual(W.recall(d, "Python 怎麼安裝？"), [])
            W.remember(d, "https://docs.ubuntu.com/", "Ubuntu documentation", "新版重點", "p")    # 同網址取代 / replaced
            self.assertEqual([r["summary"] for r in W.recall(d, "ubuntu")], ["新版重點"])

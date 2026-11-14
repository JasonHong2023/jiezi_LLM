"""OpenAI 相容客戶端測試：本機假伺服器模擬正常、卡住、429、5xx、換模型。
Client tests against a local fake server simulating success, hangs, 429, 5xx, and swapped models."""

import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval.client import ChatClient, ModelGuard  # noqa: E402


class Server:
    """script：依序回應的動作清單。 / script: a list of actions answered in order."""

    def __init__(self, script):
        self.script = list(script)
        self.bodies = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                outer.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                kind, arg = outer.script.pop(0) if outer.script else ("ok", "m")
                if kind == "hang":
                    time.sleep(arg)
                    kind, arg = "ok", "m"
                if kind == "ok":
                    body = json.dumps({"model": arg, "choices": [{"message": {"content": "答案：B"}}],
                                       "usage": {"total_tokens": 5}, "timings": {"predicted_per_second": 40.0}})
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(body.encode())
                else:
                    self.send_response(arg)
                    if arg == 429:
                        self.send_header("Retry-After", "3")
                    self.end_headers()
                    self.wfile.write(b"err")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestClient(unittest.TestCase):
    def client(self, srv, **kw):
        self.sleeps = []
        return ChatClient(srv.url, "alias", sleep=self.sleeps.append, **kw)

    def run_script(self, script, **kw):
        srv = Server(script)
        try:
            reply = self.client(srv, **kw).complete([{"role": "user", "content": "q"}])
            return reply, srv.bodies
        finally:
            srv.close()

    def test_ok_reads_content_usage_timings(self):
        reply, bodies = self.run_script([("ok", "m")])
        self.assertEqual((reply.status, reply.content, reply.attempts), ("ok", "答案：B", 1))
        self.assertEqual(reply.timings["predicted_per_second"], 40.0)
        self.assertNotIn("disable_fallbacks", bodies[0])

    def test_baseline_sends_disable_fallbacks_and_voids_swaps(self):
        srv = Server([("ok", "nvidia/nemotron-3-ultra-550b"), ("ok", "gemini-x")])
        try:
            c = self.client(srv, baseline=True)
            first = c.complete([{"role": "user", "content": "q"}])
            second = c.complete([{"role": "user", "content": "q"}])
        finally:
            srv.close()
        self.assertTrue(all(b["disable_fallbacks"] for b in srv.bodies))
        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "void_model_mismatch")

    def test_model_match_substring(self):
        reply, _ = self.run_script([("ok", "other-model")], baseline=True, model_match="nemotron-3-ultra")
        self.assertEqual(reply.status, "void_model_mismatch")
        reply, _ = self.run_script([("ok", "nvidia/Nemotron-3-Ultra-550b")], baseline=True, model_match="nemotron-3-ultra")
        self.assertEqual(reply.status, "ok")

    def test_hang_times_out_after_retries(self):
        reply, bodies = self.run_script([("hang", 1.0)] * 3, timeout_s=0.2)
        self.assertEqual(reply.status, "error_timeout")
        self.assertEqual(reply.attempts, 3)
        self.assertEqual(self.sleeps, [10, 30])

    def test_hang_then_recover(self):
        reply, _ = self.run_script([("hang", 1.0), ("ok", "m")], timeout_s=0.2)
        self.assertEqual((reply.status, reply.attempts), ("ok", 2))

    def test_429_honours_retry_after(self):
        reply, _ = self.run_script([("http", 429), ("ok", "m")])
        self.assertEqual(reply.status, "ok")
        self.assertEqual(self.sleeps, [3.0])

    def test_5xx_exhausts_retries(self):
        reply, _ = self.run_script([("http", 502)] * 3)
        self.assertEqual((reply.status, reply.attempts), ("error_http", 3))

    def test_4xx_is_not_retried(self):
        reply, bodies = self.run_script([("http", 400)])
        self.assertEqual((reply.status, reply.attempts, len(bodies)), ("error_http", 1, 1))


class TestGuard(unittest.TestCase):
    def test_lock_on_first(self):
        g = ModelGuard(None)
        self.assertTrue(g.accept("A"))
        self.assertTrue(g.accept("a"))
        self.assertFalse(g.accept("b"))
        self.assertFalse(g.accept(None))


if __name__ == "__main__":
    unittest.main()

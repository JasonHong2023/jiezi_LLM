"""本機引擎管理測試：以假的 llama-server（小型 Python HTTP 程式）測試啟動、port、關閉與記憶體取樣。
Engine tests with a fake llama-server (a tiny Python HTTP program)."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError, engine  # noqa: E402

FAKE_SERVER = f"""#!{sys.executable}
import sys, http.server
args = sys.argv[1:]
if "--crash" in open(args[args.index("-m") + 1]).read():
    sys.exit(3)
port = int(args[args.index("--port") + 1]); host = args[args.index("--host") + 1]
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404); self.end_headers()
http.server.HTTPServer((host, port), H).serve_forever()
"""

FACTS = {"budgets": {"cpu": {"usable_threads": 3, "affinity_hint": None}}}


class TestEngine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        b = self.root / "build-cpu" / "bin"
        b.mkdir(parents=True)
        (b / "llama-server").write_text(FAKE_SERVER)
        (b / "llama-server").chmod(0o755)
        self.model = self.root / "m.gguf"
        self.model.write_text("fake")
        self.base = engine.find_port(36100 + 2000)  - 10  # 測試用空閒區段 / a free block for tests

    def tearDown(self):
        self._tmp.cleanup()

    def test_ports(self):
        self.assertEqual(engine.find_port(36100, lambda p: p != 36110), 36111)
        with self.assertRaisesRegex(EvalError, "no free port in 36110–36119"):
            engine.find_port(36100, lambda p: False)

    def test_command_is_local_and_budgeted(self):
        e = engine.LocalEngine(self.root, FACTS, self.model, 36100, is_free=lambda p: True)
        cmd = e.cmd
        self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")
        self.assertEqual(cmd[cmd.index("-t") + 1], "3")
        self.assertEqual(cmd[cmd.index("--port") + 1], "36110")
        self.assertIn("nice", cmd)
        self.assertEqual(cmd[cmd.index("--cache-ram") + 1], "0")  # 提示快取關閉 / prompt cache off
        self.assertEqual(e.describe()["binary"], "build-cpu/bin/llama-server")

    def test_start_health_and_stop(self):
        with engine.LocalEngine(self.root, FACTS, self.model, self.base, health_timeout_s=20) as e:
            e.start(self.root / "server.log")
            self.assertTrue(e.alive())
            pid = e.proc.pid
        self.assertFalse(e.alive())
        self.assertIsNotNone(e.proc.returncode)
        self.assertGreater(e.peak_rss_mib or 0, 0)
        self.assertFalse(Path(f"/proc/{pid}").exists() and e.proc.poll() is None)

    def test_stopped_on_exception(self):
        with self.assertRaises(RuntimeError):
            with engine.LocalEngine(self.root, FACTS, self.model, self.base, health_timeout_s=20) as e:
                e.start(self.root / "server.log")
                raise RuntimeError("boom")
        self.assertFalse(e.alive())

    def test_startup_crash(self):
        self.model.write_text("--crash")
        with engine.LocalEngine(self.root, FACTS, self.model, self.base, health_timeout_s=20) as e:
            with self.assertRaisesRegex(EvalError, "exited with 3"):
                e.start(self.root / "server.log")

    def test_missing_binary_or_model(self):
        with self.assertRaisesRegex(EvalError, "build-cuda"):
            engine.LocalEngine(self.root, FACTS, self.model, 36100, ngl=99, is_free=lambda p: True)
        with self.assertRaisesRegex(EvalError, "model not found"):
            engine.LocalEngine(self.root, FACTS, self.root / "none.gguf", 36100, is_free=lambda p: True)

    def test_memory_readers(self):
        proc = self.root / "proc" / "42"
        proc.mkdir(parents=True)
        (proc / "status").write_text("Name: x\nVmHWM:\t  204800 kB\n")
        self.assertEqual(engine.read_vm_hwm_kib(42, self.root / "proc"), 204800)
        out = SimpleNamespace(stdout="41, 100\n42, 1234\n")
        self.assertEqual(engine.read_vram_mib(42, run=lambda *a, **k: out), 1234)
        na = SimpleNamespace(stdout="42, [N/A]\n")
        self.assertIsNone(engine.read_vram_mib(42, run=lambda *a, **k: na))


if __name__ == "__main__":
    unittest.main()

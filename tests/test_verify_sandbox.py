"""沙盒測試（實際啟動 bubblewrap；沒有建置 bwrap 時略過）：逾時、記憶體、fork 炸彈、輸出上限、網路與寫入被擋。
Sandbox tests (real bubblewrap; skipped when bwrap is not built): timeout, memory, fork bomb, output cap,
blocked network and writes."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.verify.sandbox import Limits, Sandbox, SandboxUnavailable  # noqa: E402

BWRAP = ROOT / "var" / "tools" / "bubblewrap" / "bin" / "bwrap"


@unittest.skipUnless(BWRAP.is_file(), "bubblewrap not built (scripts/bootstrap)")
class TestSandbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sb = Sandbox(ROOT, probe_port=4000)
        ok, reason = cls.sb.available()
        if not ok:
            raise AssertionError(reason)

    def run_code(self, code, **limits):
        return self.sb.run_python({"m.py": code}, ["m.py"], Limits(**limits))

    def test_runs_python_and_reads_stdin(self):
        r = self.sb.run_python({"m.py": "import sys, json; print(json.dumps(sys.stdin.read()[::-1]))"},
                               ["m.py"], stdin=b"abc")
        self.assertEqual((r.returncode, r.stdout.strip(), r.limit), (0, '"cba"', None))

    def test_timeout(self):
        r = self.run_code("while True: pass", wall_s=1.5)
        self.assertEqual(r.limit, "timeout")
        self.assertLess(r.duration_s, 5)

    def test_memory_limit(self):
        r = self.run_code("x = bytearray(600 * 2**20)\nx[::4096] = b'1' * len(x[::4096])\nprint('big')",
                          memory_mib=200)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("big", r.stdout)

    def test_fork_bomb_is_bounded(self):
        code = ("import os, time\nn = 0\ntry:\n    for _ in range(500):\n        if os.fork() == 0:\n"
                "            time.sleep(3); os._exit(0)\n        n += 1\nexcept OSError:\n    pass\nprint(n)")
        r = self.run_code(code, tasks=16, wall_s=8)
        self.assertLess(int(r.stdout.strip() or 0), 500)

    def test_output_capped(self):
        r = self.run_code("import sys\nwhile True: sys.stdout.write('x' * 65536)", output_mib=1, wall_s=5,
                          read_bytes=1000)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(r.stdout), 1000)

    def test_no_network_no_home_no_project(self):
        code = (f"import os, socket\ntry:\n    socket.create_connection(('127.0.0.1', 4000), timeout=2); print('NET')\n"
                f"except OSError: print('no-net')\nprint(os.path.exists({str(Path.home())!r}), "
                f"os.path.exists({str(ROOT)!r}))\n"
                "try:\n    open('/usr/x', 'w'); print('USR')\nexcept OSError: print('ro')")
        r = self.run_code(code)
        self.assertEqual(r.stdout.split(), ["no-net", "False", "False", "ro"])

    def test_workdir_files_and_cleanup(self):
        r = self.sb.run_python({"m.py": "print(open('data/in.txt').read())", "data/in.txt": "hi"}, ["m.py"])
        self.assertEqual(r.stdout.strip(), "hi")


class TestUnavailable(unittest.TestCase):
    def test_missing_bwrap_never_runs(self):
        with tempfile.TemporaryDirectory() as d:
            sb = Sandbox(Path(d))
            ok, reason = sb.available()
            self.assertFalse(ok)
            self.assertIn("not found", reason)
            with self.assertRaises(SandboxUnavailable):
                sb.run_python({"m.py": "print(1)"}, ["m.py"])


if __name__ == "__main__":
    unittest.main()

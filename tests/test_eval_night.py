"""夜間時段與排程測試（注入時鐘與假的 systemd-run，不建立真的排程）。
Night window and scheduling tests (injected clock and fake systemd-run; no real timers are created)."""

import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError, night  # noqa: E402

T = lambda h, m=0: datetime(2026, 11, 14, h, m)  # noqa: E731


class TestWindow(unittest.TestCase):
    def test_default_window(self):
        w = night.parse_window(None)
        self.assertTrue(w.contains(T(0)))
        self.assertTrue(w.contains(T(6, 59)))
        self.assertFalse(w.contains(T(7)))
        self.assertFalse(w.contains(T(20, 9)))

    def test_cross_midnight(self):
        w = night.parse_window("23:00-06:00")
        self.assertTrue(w.contains(T(23, 30)))
        self.assertTrue(w.contains(T(2)))
        self.assertFalse(w.contains(T(12)))

    def test_invalid(self):
        for bad in ("7-8", "25:00-01:00", "01:00-01:00", "abc"):
            with self.subTest(bad=bad), self.assertRaises(EvalError):
                night.parse_window(bad)

    def test_planned_time(self):
        w = night.parse_window("00:00-07:00")
        self.assertEqual(night.planned_time(w, T(20, 9)), datetime(2026, 11, 15, 0, 5))
        self.assertEqual(night.planned_time(w, T(3)), T(3, 1))  # 已在時段內 / already inside


class TestSchedule(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "scripts").mkdir()
        fake_eval = self.root / "scripts" / "eval"
        fake_eval.write_text('#!/usr/bin/env bash\necho "args: $*"\n[ "$1" = "fail" ] && exit 4\nexit 0\n')
        fake_eval.chmod(0o755)

    def tearDown(self):
        self._tmp.cleanup()

    def test_systemd_command(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        rec = night.schedule(self.root, [["run", "--bank", "r0"]], datetime(2026, 11, 15, 0, 5), run=run, use_systemd=True)
        cmd = calls[0]
        self.assertEqual(cmd[:3], ["systemd-run", "--user", "--collect"])
        self.assertIn("--on-calendar=2026-11-15 00:05:00", cmd)
        self.assertEqual(rec["method"], "systemd-user")
        listed = night.list_schedules(self.root)
        self.assertTrue(listed[0]["state"].startswith("waiting"))

    def test_launcher_runs_jobs_in_order_and_records(self):
        ok = lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr="")  # noqa: E731
        for jobs, want in (([["run", "a"], ["bank", "verify"]], "done job1=0 job2=0"),
                           ([["fail"], ["run", "b"]], "failed job1=4 job2=0")):
            rec = night.schedule(self.root, jobs, datetime(2026, 11, 15, 0, 5), run=ok, use_systemd=True)
            d = night.schedule_dir(self.root)
            subprocess.run(["/bin/bash", str(d / f"{rec['id']}.sh")], check=True)
            self.assertTrue((d / f"{rec['id']}.state").read_text().startswith(want))
            log = (d / f"{rec['id']}.log").read_text()
            self.assertLess(log.index(f"args: {jobs[0][0]}"), log.index(f"args: {jobs[1][0]}"))  # 依序 / in order

    def test_empty_jobs(self):
        with self.assertRaises(EvalError):
            night.schedule(self.root, [], T(23), use_systemd=True)

    def test_detached_fallback(self):
        started = {}

        def popen(cmd, **kw):
            started.update(cmd=cmd, kw=kw)
            return SimpleNamespace(pid=1234)
        rec = night.schedule(self.root, [["run"]], datetime(2026, 11, 15, 0, 5), popen=popen, use_systemd=False,
                             now=T(20, 5))
        self.assertEqual(rec["method"], "detached-process")
        self.assertTrue(started["kw"]["start_new_session"])
        self.assertIn("sleep 14400;", started["cmd"][2])  # 20:05 → 00:05

    def test_systemd_failure(self):
        bad = lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="no bus")  # noqa: E731
        with self.assertRaisesRegex(EvalError, "no bus"):
            night.schedule(self.root, [["run"]], T(23), run=bad, use_systemd=True)


if __name__ == "__main__":
    unittest.main()

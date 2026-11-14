"""bootstrap 步驟執行器、.env 建立、cuda 決策與冒煙測試解析的測試。
Tests for the bootstrap runner, .env creation, the cuda decision, and smoke-test parsing."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import jiezi_bootstrap.__main__ as bs  # noqa: E402
from jiezi_bootstrap import smoke  # noqa: E402
from jiezi_bootstrap.common import StepError  # noqa: E402


class TestRunner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.logs = []

    def tearDown(self):
        self._tmp.cleanup()

    def test_failure_records_step_and_resume(self):
        calls = []
        broken = {"on": True}

        def ok(name):
            def f(ctx):
                calls.append(name)
                return f"{name} done"
            return f

        def flaky(ctx):
            calls.append("b")
            if broken["on"]:
                raise StepError("boom")
            return "b done"

        steps = [("a", ok("a")), ("b", flaky), ("c", ok("c"))]
        ctx = bs.Ctx(self.root, offer_setup=False)
        self.assertEqual(bs.run_steps(ctx, steps, self.logs.append), 1)
        self.assertEqual(calls, ["a", "b"])  # c 沒有執行 / c never ran
        state = json.loads(bs.state_path(self.root).read_text())
        self.assertEqual(state["failed_step"], "b")
        self.assertEqual(state["steps"]["b"]["detail"], "boom")

        broken["on"] = False
        self.assertEqual(bs.run_steps(ctx, steps, self.logs.append), 0)
        self.assertTrue(any("last run failed at 'b'" in m for m in self.logs))
        state = json.loads(bs.state_path(self.root).read_text())
        self.assertNotIn("failed_step", state)
        self.assertEqual({s["status"] for s in state["steps"].values()}, {"ok"})

    def test_env_created_from_example_and_local_only_note(self):
        (self.root / ".env.example").write_text("JIEZI_CLOUD_BASE_URL=\n")
        ctx = bs.Ctx(self.root, offer_setup=False)
        with mock.patch.dict("os.environ", {"JIEZI_CLOUD_BASE_URL": ""}):
            self.assertIn("created", bs.step_env(ctx))
            self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o600)
            self.assertTrue(any("local-only" in n for n in ctx.notes))
            self.assertEqual(bs.step_env(bs.Ctx(self.root, False)), ".env present")

    def test_env_never_overwritten(self):
        (self.root / ".env.example").write_text("X=\n")
        (self.root / ".env").write_text("JIEZI_CLOUD_BASE_URL=http://127.0.0.1:1\n")
        bs.step_env(bs.Ctx(self.root, False))
        self.assertIn("127.0.0.1", (self.root / ".env").read_text())


class TestCudaDecision(unittest.TestCase):
    def ctx(self, cuda, offer=True):
        c = bs.Ctx(Path("/nonexistent"), offer_setup=offer)
        c.facts = {"backends": {"buildable": {"cuda": cuda}}}
        return c

    def test_no_driver_is_skipped_without_prompt(self):
        r = bs.step_cuda(self.ctx({"ok": False, "reason": "missing: nvidia driver, nvcc (cuda-toolkit)"}))
        self.assertTrue(r.startswith("skipped"))

    def test_present(self):
        self.assertEqual(bs.step_cuda(self.ctx({"ok": True, "reason": None})), "CUDA toolkit present")

    def test_no_setup_flag(self):
        with mock.patch.object(bs.sudo_window, "detect_platform", return_value="wsl2"):
            r = bs.step_cuda(self.ctx({"ok": False, "reason": "missing: nvcc (cuda-toolkit)"}, offer=False))
        self.assertIn("--no-setup", r)


class TestSmokeParse(unittest.TestCase):
    def test_eval_not_prompt_eval(self):
        err = ("common_perf_print: prompt eval time =  271.61 ms / 16 tokens ( 16.98 ms per token, 58.91 tokens per second)\n"
               "common_perf_print:        eval time =  672.01 ms / 15 runs   ( 44.80 ms per token, 22.32 tokens per second)\n")
        self.assertEqual(smoke.parse_tps(err), 22.32)
        self.assertIsNone(smoke.parse_tps("nothing"))

    def test_command_is_cpu_budgeted(self):
        facts = {"budgets": {"cpu": {"usable_threads": 6, "affinity_hint": None}}}
        cmd, threads, _ = smoke.command(Path("/b/llama-completion"), Path("/m.gguf"), facts)
        self.assertEqual(threads, 6)
        self.assertEqual(cmd[cmd.index("-t") + 1], "6")
        self.assertIn("nice", cmd)


if __name__ == "__main__":
    unittest.main()

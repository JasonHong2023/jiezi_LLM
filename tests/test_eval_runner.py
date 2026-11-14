"""執行器測試：以假客戶端測試續跑、條件不符、失敗暫停、補跑、夜間時段與引擎中止。
Runner tests with a fake client: resume, condition mismatch, failure pause, retry, night window, engine death."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError, runner  # noqa: E402
from jiezi.eval.client import Reply  # noqa: E402

QUIET = lambda *_: None  # noqa: E731


def mc(i, answer="B"):
    return {"source": "s", "id": f"q{i}", "task": "qa", "group": "knowledge", "scorer": "multiple_choice",
            "stratum": "x", "data": {"question": "題", "answer": answer,
                                     "choices": {"A": "a", "B": "b", "C": "c", "D": "d"}}}


class FakeClient:
    def __init__(self, statuses=None):
        self.statuses = list(statuses or [])
        self.calls = 0

    def complete(self, messages, temperature=0.0, max_tokens=0, extra=None):
        self.calls += 1
        st = self.statuses.pop(0) if self.statuses else "ok"
        if st == "ok":
            return Reply("ok", content="答案：B", model="m", usage={"completion_tokens": 2}, latency_s=0.5, attempts=1)
        return Reply(st, model="other" if st.startswith("void") else None, error="x", attempts=3)


ID = {"model": "m", "temperature": 0.0, "bank_hash": "h"}


class TestRunner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "run"
        runner.prepare_run_dir(self.dir, ID, {"date": "d"}, resume=False)

    def tearDown(self):
        self._tmp.cleanup()

    def results(self):
        return runner.latest_results(self.dir)

    def test_complete_run(self):
        items = [mc(i) for i in range(3)] + [mc(9, answer="A")]
        s = runner.run(items, FakeClient(), self.dir, log=QUIET)
        self.assertEqual((s["state"], s["recorded"]), ("complete", 4))
        scores = sorted(r["score"] for r in self.results().values())
        self.assertEqual(scores, [0, 1, 1, 1])
        self.assertEqual(self.results()["s/q0#0"]["tps"], 4.0)  # 2 tokens / 0.5 s

    def test_resume_skips_done_and_checks_conditions(self):
        items = [mc(i) for i in range(4)]
        calls = {"n": 0}

        def stop_after_two():
            calls["n"] += 1
            return calls["n"] <= 2
        s = runner.run(items, FakeClient(), self.dir, may_continue=stop_after_two, log=QUIET)
        self.assertEqual((s["state"], s["recorded"]), ("paused_window", 2))
        runner.prepare_run_dir(self.dir, ID, {"date": "later"}, resume=True)  # context 可以不同 / context may differ
        client = FakeClient()
        s = runner.run(items, client, self.dir, log=QUIET)
        self.assertEqual((s["state"], client.calls), ("complete", 2))
        with self.assertRaisesRegex(EvalError, "temperature: run=0.0 now=0.7"):
            runner.prepare_run_dir(self.dir, dict(ID, temperature=0.7), {}, resume=True)

    def test_new_run_refuses_existing_dir(self):
        runner.run([mc(0)], FakeClient(), self.dir, log=QUIET)
        with self.assertRaisesRegex(EvalError, "already exists"):
            runner.prepare_run_dir(self.dir, ID, {}, resume=False)

    def test_outage_pause_and_retry_errors(self):
        items = [mc(i) for i in range(8)]
        s = runner.run(items, FakeClient(["ok"] + ["error_timeout"] * 5), self.dir, log=QUIET)
        self.assertEqual((s["state"], s["errors"], s["recorded"]), ("paused_outage", 5, 6))
        self.assertEqual(len((self.dir / "errors.jsonl").read_text().splitlines()), 5)
        # 一般續跑不重做錯誤題；--retry-errors 才重做 / plain resume keeps errors; --retry-errors reruns them
        client = FakeClient()
        s = runner.run(items, client, self.dir, log=QUIET)
        self.assertEqual((client.calls, s["errors"]), (2, 5))
        client = FakeClient()
        s = runner.run(items, client, self.dir, retry_errors=True, log=QUIET)
        self.assertEqual((client.calls, s["errors"], s["state"]), (5, 0, "complete"))

    def test_void_is_not_an_outage(self):
        items = [mc(i) for i in range(7)]
        s = runner.run(items, FakeClient(["void_model_mismatch"] * 6), self.dir, log=QUIET)
        self.assertEqual(s["state"], "complete")
        self.assertEqual(sum(r["status"] == "void_model_mismatch" for r in self.results().values()), 6)

    def test_engine_death_stops(self):
        s = runner.run([mc(0), mc(1)], FakeClient(), self.dir, engine_alive=lambda: False, log=QUIET)
        self.assertEqual((s["state"], s["recorded"]), ("engine_died", 0))

    def test_samples(self):
        s = runner.run([mc(0)], FakeClient(), self.dir, samples=3, temperature=0.7, log=QUIET)
        self.assertEqual(sorted(self.results()), ["s/q0#0", "s/q0#1", "s/q0#2"])
        self.assertEqual(json.loads((self.dir / "run_state.json").read_text())["total"], 3)


if __name__ == "__main__":
    unittest.main()

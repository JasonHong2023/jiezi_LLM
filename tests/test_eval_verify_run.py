"""事後評分測試：原始回答不變、不重複驗證、失敗補驗、連續失敗暫停、報表合併與小計規則。
After-the-fact scoring tests: raw responses unchanged, no re-verification, failures redone, outage pause,
report overlay and subtotal rules."""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError, report, verify_run  # noqa: E402
from jiezi.eval import __main__ as cli  # noqa: E402

TOOL_ITEM = {"source": "acebench-zh", "id": "t1", "task": "tool", "group": "reasoning", "scorer": "pending_verifier",
             "data": {"functions": [{"name": "f", "parameters": {"type": "object", "required": ["a"],
                                                                  "properties": {"a": {"type": "integer"}}}}],
                      "ground_truth": {"f": {"a": 1}}}}
SUM_ITEM = {"source": "zhwiki-featured", "id": "w1", "task": "summary", "group": "reasoning",
            "scorer": "pending_verifier", "data": {"text": "原文。"}}
QA_ITEM = {"source": "chinese-simpleqa", "id": "q1", "task": "qa", "group": "knowledge", "scorer": "simpleqa_approx",
           "data": {"question": "?", "answer": "玉山"}}


def rec(item, content, status="pending_verifier", score=None):
    return {"key": f"{item['source']}/{item['id']}#0", "source": item["source"], "id": item["id"],
            "task": item["task"], "group": item["group"], "scorer": item["scorer"], "sample": 0, "status": status,
            "score": score, "content": content, "model": "m", "usage": {}, "latency_s": 1.0, "tps": 10.0}


class TestVerifyRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "run"
        self.dir.mkdir()
        (self.dir / "conditions.json").write_text(json.dumps({"identity": {"samples": 1}, "context": {}}))
        (self.dir / "run_state.json").write_text(json.dumps({"state": "complete", "total": 3}))
        recs = [rec(TOOL_ITEM, "[f(a=1)]"), rec(SUM_ITEM, "臺" * 120), rec(QA_ITEM, "玉山", "correct", 1)]
        (self.dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
        self.items = [TOOL_ITEM, SUM_ITEM, QA_ITEM]

    def tearDown(self):
        self._tmp.cleanup()

    def quick(self):
        v, ver = verify_run.quick_verifiers()
        return verify_run.verify_run(self.dir, self.items, ["tool", "summary_rules"], v, ver, log=lambda *_: None)

    def test_raw_results_unchanged_and_no_reverification(self):
        before = (self.dir / "results.jsonl").read_bytes()
        s = self.quick()
        self.assertEqual((s["tool"]["verified"], s["summary_rules"]["verified"]), (1, 1))
        self.assertEqual((self.dir / "results.jsonl").read_bytes(), before)
        s = self.quick()
        self.assertEqual((s["tool"]["skipped"], s["tool"]["verified"]), (1, 0))

    def test_report_overlay_and_subtotal(self):
        self.quick()
        rep = report.write(self.dir)
        src = rep["groups"]["reasoning"]["sources"]
        self.assertEqual((src["acebench-zh"]["scorer"], src["acebench-zh"]["correct"]), ("acebench-normal", 1))
        self.assertEqual(src["zhwiki-featured"]["scorer"], "summary rules")
        self.assertEqual(rep["groups"]["reasoning"]["summary"]["scored"], 1)  # 摘要規則不列入 / rules excluded
        self.assertEqual(rep["verification"]["summary_rules"]["length_ok"], 1)
        self.assertIn("tool", rep["known_differences"])

    def test_judge_errors_redone_and_outage_pause(self):
        items = [QA_ITEM] + [{**QA_ITEM, "id": f"q{i}"} for i in range(2, 8)]
        recs = [rec(i, "x", "wrong", 0) for i in items]
        (self.dir / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
        calls = []

        def failing(item, content):
            calls.append(item["id"])
            return {"status": "error_timeout", "score": None}
        s = verify_run.verify_run(self.dir, items, ["simpleqa_judge"], {"simpleqa_judge": failing},
                                  {"simpleqa_judge": "j@1"}, log=lambda *_: None)
        self.assertEqual((s["state"], len(calls)), ("paused_outage", verify_run.MAX_CONSECUTIVE_FAILURES))
        ok = lambda item, content: {"status": "correct", "score": 1}  # noqa: E731
        s = verify_run.verify_run(self.dir, items, ["simpleqa_judge"], {"simpleqa_judge": ok},
                                  {"simpleqa_judge": "j@1"}, log=lambda *_: None)
        self.assertEqual((s["state"], s["simpleqa_judge"]["verified"]), ("complete", 7))
        rep = report.build(self.dir)
        self.assertEqual(rep["verification"]["simpleqa_judge"]["correct"], 1.0)

    def test_unknown_item_is_an_error(self):
        v, ver = verify_run.quick_verifiers()
        with self.assertRaises(EvalError):
            verify_run.verify_run(self.dir, [QA_ITEM], ["tool"], v, ver, log=lambda *_: None)


class TestVerifyCli(unittest.TestCase):
    def test_long_kinds_refused_outside_window(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = root / "var" / "eval" / "runs" / "r1"
            run.mkdir(parents=True)
            (run / "conditions.json").write_text(json.dumps({"identity": {"bank": "r0"}}))
            noon = datetime.now().replace(hour=12, minute=0)
            args = SimpleNamespace(run_id="r1", only=["code"], now=False, timeout=None, reasoning_budget=0)
            with mock.patch.object(cli, "load_env", return_value={"JIEZI_NIGHT_WINDOW": "00:00-07:00"}), \
                    mock.patch.object(cli, "datetime", mock.Mock(now=mock.Mock(return_value=noon))):
                with self.assertRaisesRegex(EvalError, "long jobs"):
                    cli.cmd_verify(args, root)

    def test_judge_model_override_parses(self):
        a = cli.parser().parse_args(["verify", "r1", "--judge-model", "m2", "--judge-match", "m2"])
        self.assertEqual((a.judge_model, a.judge_match), ("m2", "m2"))
        self.assertIsNone(cli.parser().parse_args(["verify", "r1"]).judge_model)


if __name__ == "__main__":
    unittest.main()

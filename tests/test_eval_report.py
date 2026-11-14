"""報表測試：分組、無合併總分、不完整標示、多樣本標示。
Report tests: grouping, no merged score, incompleteness label, multi-sample label."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import report  # noqa: E402


def rec(key, group, source, scorer, status, score, tps=10.0):
    return {"key": key, "source": source, "id": key, "task": "qa", "group": group, "scorer": scorer, "sample": 0,
            "status": status, "score": score, "model": "m", "usage": {"completion_tokens": 3},
            "latency_s": 1.0, "tps": tps}


class TestReport(unittest.TestCase):
    def make(self, records, identity=None, state="complete"):
        d = Path(self._tmp.name) / "run-1"
        d.mkdir()
        (d / "conditions.json").write_text(json.dumps({"identity": identity or {"samples": 1, "temperature": 0.0},
                                                       "context": {}}))
        (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
        (d / "run_state.json").write_text(json.dumps({"state": state, "total": len(records)}))
        (d / "engine.json").write_text(json.dumps({"peak_rss_mib": 900.5, "peak_vram_mib": None}))
        return report.write(d), d

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_groups_and_no_overall_score(self):
        rep, d = self.make([
            rec("a", "knowledge", "ceval", "multiple_choice", "correct", 1, tps=10),
            rec("b", "knowledge", "ceval", "multiple_choice", "unparsed", 0, tps=20),
            rec("c", "knowledge", "sq", "simpleqa_approx", "correct", 1),
            rec("d", "reasoning", "he", "pending_verifier", "pending_verifier", None),
        ])
        k = rep["groups"]["knowledge"]["summary"]
        self.assertEqual((k["scored"], k["correct"], k["accuracy"], k["unparsed"]), (3, 2, 0.6667, 1))
        r = rep["groups"]["reasoning"]["summary"]
        self.assertEqual((r["scored"], r["accuracy"], r["pending_verifier"]), (0, None, 1))
        self.assertNotIn("accuracy", rep["counts"])  # 沒有合併總分 / no merged score
        self.assertEqual(rep["mode"], "greedy")
        self.assertEqual(rep["completeness"], "complete")
        self.assertEqual(rep["tokens_per_second"]["mean"], 12.5)
        self.assertTrue(any("approximate" in n for n in rep["notes"]))
        md = (d / "report.md").read_text()
        self.assertIn("知識題", md)
        self.assertIn("no merged score", md)

    def test_errors_and_void_make_it_incomplete(self):
        rep, d = self.make([rec("a", "knowledge", "ceval", "multiple_choice", "correct", 1),
                            rec("b", "knowledge", "ceval", "multiple_choice", "error_timeout", None),
                            rec("c", "knowledge", "ceval", "multiple_choice", "void_model_mismatch", None)])
        self.assertEqual(rep["completeness"], "incomplete")
        k = rep["groups"]["knowledge"]["summary"]
        self.assertEqual((k["scored"], k["errors"], k["void_model_mismatch"]), (1, 1, 1))
        self.assertIn("⚠️", (d / "report.md").read_text())

    def test_truncated_makes_it_incomplete(self):
        rep, d = self.make([rec("a", "knowledge", "s", "multiple_choice", "correct", 1),
                            rec("b", "knowledge", "s", "multiple_choice", "truncated", None)])
        self.assertEqual(rep["completeness"], "incomplete")
        self.assertEqual(rep["counts"]["truncated"], 1)
        self.assertEqual(rep["groups"]["knowledge"]["summary"]["scored"], 1)
        self.assertIn("截斷 / Truncated", (d / "report.md").read_text(encoding="utf-8"))

    def test_multi_sample_label(self):
        rep, _ = self.make([rec("a", "knowledge", "ceval", "multiple_choice", "correct", 1)],
                           identity={"samples": 8, "temperature": 0.7})
        self.assertEqual(rep["mode"], "multi-sample (N=8, T=0.7)")


if __name__ == "__main__":
    unittest.main()

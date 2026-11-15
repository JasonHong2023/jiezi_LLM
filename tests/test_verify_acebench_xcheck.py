"""ACEBench 官方對照測試：分類規則、沙盒輸出解析、官方檔案取用（不執行官方程式）。
ACEBench side-by-side tests: classification, sandbox-output parsing, upstream file handling (upstream code
is not executed here)."""

import hashlib
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

from jiezi.eval import EvalError  # noqa: E402
from jiezi.eval import __main__ as cli  # noqa: E402
from jiezi.verify import acebench_xcheck as xc  # noqa: E402
from jiezi.verify import tool_call  # noqa: E402
from jiezi.verify.sandbox import Result  # noqa: E402


class FakeSandbox:
    def __init__(self, result):
        self.result, self.calls = result, []

    def run_python(self, files, argv, limits=None, stdin=b"", collect=None):
        self.calls.append((files, argv, limits))
        return self.result

    def describe(self):
        return {"version": "fake"}


class TestClassify(unittest.TestCase):
    def mine(self, content, case=None):
        c = case or xc.HAND_CASES[0]
        return tool_call.verify({"data": c}, content)

    def test_agree_and_disagree(self):
        self.assertEqual(xc.classify({"valid": True}, {"status": "correct", "score": 1}), "agree")
        self.assertEqual(xc.classify({"valid": False}, {"status": "unparsed", "score": 0}), "agree")
        self.assertEqual(xc.classify({"valid": False}, {"status": "correct", "score": 1}), "disagree")

    def test_known_differences(self):
        f_int = next(c for c in xc.HAND_CASES if c["id"] == "hand/arith_name")
        mine = tool_call.verify({"data": f_int}, "[f(a=x+1)]")
        self.assertEqual(xc.classify({"valid": True}, mine), "known_eval")
        crash = next(c for c in xc.HAND_CASES if c["id"] == "hand/unknown_type")
        mine = tool_call.verify({"data": crash}, crash["content"])
        self.assertEqual(xc.classify({"valid": None, "crash": "KeyError"}, mine), "known_crash")
        self.assertEqual(xc.classify({"valid": None, "crash": "x"}, {"status": "wrong", "score": 0}), "disagree")
        self.assertEqual(xc.classify({"valid": None, "limit": "resource_limit"}, mine), "upstream_limit")

    def test_hand_cases_cover_unit_test_rules_and_port_handles_all(self):
        self.assertGreaterEqual(len(xc.HAND_CASES), 25)
        self.assertEqual(len({c["id"] for c in xc.HAND_CASES}), len(xc.HAND_CASES))
        for c in xc.HAND_CASES:
            r = tool_call.verify({"data": c}, c["content"])
            self.assertIn(r["status"], ("correct", "wrong", "unparsed"), c["id"])


class TestUpstreamRun(unittest.TestCase):
    def test_parses_marker_line_and_limits(self):
        sb = FakeSandbox(Result(0, 'noise\nXCHECK:{"valid": true}\n', ""))
        self.assertEqual(xc.run_upstream(sb, {"up/x.py": ""}, xc.HAND_CASES[0]), {"valid": True})
        files, argv, limits = sb.calls[0]
        self.assertEqual(argv, ["harness.py"])
        self.assertEqual(json.loads(files["case.json"])["id"], xc.HAND_CASES[0]["id"])
        self.assertLessEqual(limits.memory_mib, 512)
        sb = FakeSandbox(Result(-9, "", "", limit="resource_limit"))
        self.assertEqual(xc.run_upstream(sb, {}, xc.HAND_CASES[0]), {"valid": None, "limit": "resource_limit"})
        sb = FakeSandbox(Result(1, "", "Traceback ... ImportError"))
        self.assertIn("ImportError", xc.run_upstream(sb, {}, xc.HAND_CASES[0])["crash"])

    def test_compare_counts(self):
        sb = FakeSandbox(Result(0, 'XCHECK:{"valid": true}\n', ""))
        rep = xc.compare(sb, {}, xc.HAND_CASES[:2])
        self.assertEqual(rep["counts"], {"agree": 2})

    def test_fetch_extracts_only_bracket_function(self):
        main_src = "import pandas\n\ndef extract_outermost_bracket_content(text):\n    return text\n\nrun()\n"
        blobs = {"eval_main.py": main_src, "model_inference/utils.py": "A=1\n", "model_eval/utils.py": "B=1\n",
                 "model_eval/checker.py": "C=1\n"}
        shas = {k: hashlib.sha256(v.encode()).hexdigest() for k, v in blobs.items()}

        def download(url, dest):
            dest.write_text(blobs[url.split(xc.COMMIT + "/", 1)[1]], encoding="utf-8")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(xc, "UPSTREAM", shas):
            files = xc.fetch_upstream(Path(d), download=download)
        self.assertEqual(set(files), {"up/model_inference/utils.py", "up/model_eval/utils.py",
                                      "up/model_eval/checker.py", "up/extract.py"})
        self.assertNotIn("pandas", files["up/extract.py"])
        self.assertIn("def extract_outermost_bracket_content", files["up/extract.py"])

    def test_fetch_rejects_changed_upstream(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(EvalError):
            xc.fetch_upstream(Path(d), download=lambda url, dest: dest.write_text("changed"))

    def test_run_cases_only_tool_answers(self):
        item = {"source": "acebench-zh", "id": "t1",
                "data": {"functions": [], "ground_truth": {}, "question": "q", "category": "normal_x"}}
        results = {"a": {"key": "acebench-zh/t1#0", "source": "acebench-zh", "id": "t1", "task": "tool",
                         "status": "pending_verifier", "content": "[f()]"},
                   "b": {"key": "x/q#0", "source": "x", "id": "q", "task": "qa", "status": "correct", "content": "y"},
                   "c": {"key": "acebench-zh/t1#1", "source": "acebench-zh", "id": "t1", "task": "tool",
                         "status": "error_timeout", "content": None}}
        cases = xc.run_cases(Path("."), [item], results)
        self.assertEqual([(c["id"], c["category"]) for c in cases], [("acebench-zh/t1#0", "normal_x")])


class TestCli(unittest.TestCase):
    def test_refused_outside_window(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = root / "var" / "eval" / "runs" / "r1"
            run.mkdir(parents=True)
            (run / "conditions.json").write_text(json.dumps({"identity": {"bank": "r0"}}))
            noon = datetime.now().replace(hour=12, minute=0)
            with mock.patch.object(cli, "load_env", return_value={"JIEZI_NIGHT_WINDOW": "00:00-07:00"}), \
                    mock.patch.object(cli, "datetime", mock.Mock(now=mock.Mock(return_value=noon))):
                with self.assertRaisesRegex(EvalError, "long job"):
                    cli.cmd_xcheck_tool(SimpleNamespace(run_id="r1", now=False), root)

    def test_schedulable(self):
        self.assertIn("xcheck-tool", cli.SCHEDULABLE)


if __name__ == "__main__":
    unittest.main()

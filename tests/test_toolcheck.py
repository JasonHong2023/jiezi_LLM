"""工具呼叫系統評測測試：題目轉換、tool_calls 轉回 ACEBench 文字、用同一評分器判分。 / Tool-check tests."""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi import toolcheck as T  # noqa: E402
from jiezi.eval.bank import Source  # noqa: E402

ITEM = {"id": "normal_1", "source": "acebench-zh", "task": "tool", "data": {
    "question": "user: 幫我查台北天氣\nsystem: 要查哪一天？\nuser: 明天\n",
    "functions": [{"name": "get_weather", "description": "查天氣",
                   "parameters": {"type": "object", "properties": {"city": {"type": "string"},
                                                                    "day": {"type": "string"}},
                                  "required": ["city", "day"]}}],
    "ground_truth": {"get_weather": {"city": "台北", "day": "明天"}}}}

BFCL_ITEM = {"id": "irrelevance_0", "source": "bfcl", "stratum": "irrelevance", "task": "tool", "data": {
    "category": "irrelevance", "question": [[{"role": "user", "content": "hi"}]],
    "functions": [{"name": "check", "description": "查",
                   "parameters": {"type": "dict", "properties": {"x": {"type": "integer"}}, "required": ["x"]}}],
    "ground_truth": []}}


def source(key: str) -> Source:
    return Source(key=key, license_key="x", task="tool", group="reasoning", scorer="pending_verifier",
                  format="x", count=3)


class TestToolcheck(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual([m["role"] for m in T.to_messages(ITEM["data"]["question"])], ["user", "assistant", "user"])
        self.assertEqual(T.to_tools(ITEM["data"]["functions"])[0]["function"]["parameters"]["required"], ["city", "day"])
        msg = {"tool_calls": [{"function": {"name": "get_weather", "arguments": json.dumps({"city": "台北", "day": "明天"})}}]}
        self.assertEqual(T.calls_text(msg), "[get_weather(city='台北', day='明天')]")

    def test_bfcl_schema_and_messages(self):
        fn = {"name": "f", "parameters": {"type": "dict", "properties": {
            "a": {"type": "tuple", "items": {"type": "any"}},
            "b": {"type": "float"}, "c": {"type": "dict", "properties": {"d": {"type": "integer"}}}}}}
        params = T.to_tools([fn])[0]["function"]["parameters"]
        self.assertEqual(params["type"], "object")
        self.assertEqual(params["properties"]["a"]["type"], "array")
        self.assertEqual(params["properties"]["a"]["items"]["type"], "string")
        self.assertEqual(params["properties"]["b"]["type"], "number")
        self.assertEqual(params["properties"]["c"]["type"], "object")
        self.assertEqual(T.to_messages(BFCL_ITEM["data"]["question"]), [{"role": "user", "content": "hi"}])
        self.assertEqual(T.calls_text({"content": "no tool"}), "no tool")

    def test_suite_items(self):
        def fake_load_items(src, cache):
            return [{"id": f"{src.key}-{n}", "source": src.key} for n in range(3)]

        with patch.object(T, "load_sources", return_value=(source("acebench-zh-normal"), source("bfcl"))), \
                patch.object(T, "load_items", side_effect=fake_load_items):
            full = T.items(Path("/tmp"), "all", limit=2)
            bfcl_only = T.items(Path("/tmp"), "bfcl", limit=1)
        self.assertEqual([i["id"] for i in full],
                         ["acebench-zh-normal-0", "acebench-zh-normal-1", "bfcl-0", "bfcl-1"])
        self.assertEqual([i["id"] for i in bfcl_only], ["bfcl-0"])
        with self.assertRaises(ValueError):
            T.items(Path("/tmp"), "unknown")
        with self.assertRaises(ValueError):
            T.items(Path("/tmp"), "r0", limit=-1)

    def test_r0_items_limit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bank = root / "var" / "eval" / "banks" / "r0"
            bank.mkdir(parents=True)
            rows = [dict(ITEM, id=f"n{i}") for i in range(2)]
            rows.insert(0, {"id": "other", "source": "chinese-simpleqa"})
            (bank / "items.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                              encoding="utf-8")
            self.assertEqual([r["id"] for r in T.items(root, "r0", limit=1)], ["n0"])

    def test_run_scores_with_the_acebench_checker(self):
        call = {"tool_calls": [{"function": {"name": "get_weather",
                                            "arguments": json.dumps({"city": "台北", "day": "明天"})}}]}
        answers = iter([call])

        def fake(url, key, policy, messages, tools):
            return {"choices": [{"message": next(answers)}], "jiezi": {"tier": 0, "confidence": 1.0}}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bank = root / "var" / "eval" / "banks" / "r0"
            bank.mkdir(parents=True)
            (bank / "items.jsonl").write_text(json.dumps(ITEM, ensure_ascii=False) + "\n", encoding="utf-8")
            out, summary = T.run(root, "http://x", "k", ask_fn=fake, log=lambda *_: None)
        self.assertEqual((summary["items"], summary["correct"]), (1, 1))
        self.assertEqual(summary["suite"], "r0")
        self.assertEqual(out.name.split("-")[0], "toolcheck")

    def test_run_dispatches_bfcl_checker_and_no_call(self):
        def fake(url, key, policy, messages, tools):
            name = tools[0]["function"]["name"]
            if name == "get_weather":
                msg = {"tool_calls": [{"function": {"name": name, "arguments": json.dumps(
                    {"city": "台北", "day": "明天"})}}]}
            else:
                msg = {"content": "不需要工具"}
            return {"choices": [{"message": msg}], "jiezi": {"tier": 0}}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with patch.object(T, "items", return_value=[ITEM, BFCL_ITEM]):
                out, summary = T.run(root, "http://x", "k", ask_fn=fake, log=lambda *_: None, suite="all")
            text = out.read_text(encoding="utf-8")
            rows = [json.loads(line) for line in out.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual((summary["items"], summary["correct"]), (2, 2))
        self.assertEqual(summary["by_source"], {"acebench-zh": 1, "bfcl": 1})
        self.assertTrue(out.name.startswith("toolcheck-all-"))
        self.assertIn("BFCL 已知差異", text)
        self.assertEqual([r["verifier"].split("@")[0] for r in rows], ["acebench-normal", "bfcl-v4"])

    def test_cli_forwards_suite_and_limit(self):
        from jiezi.runtime import __main__ as cli

        summary = {"suite": "bfcl", "correct": 1, "items": 2,
                   "by_status": {"correct": 1, "wrong": 1}, "by_source": {"bfcl": 2}}
        out = io.StringIO()
        with patch.object(T, "run", return_value=(Path("report.md"), summary)) as run:
            with redirect_stdout(out):
                rc = cli.main(["toolcheck", "--suite", "bfcl", "--limit", "2"])
        self.assertEqual(rc, 0)
        self.assertEqual(run.call_args.kwargs["suite"], "bfcl")
        self.assertEqual(run.call_args.kwargs["limit"], 2)
        self.assertIn("[bfcl] 1/2 correct", out.getvalue())


if __name__ == "__main__":
    unittest.main()

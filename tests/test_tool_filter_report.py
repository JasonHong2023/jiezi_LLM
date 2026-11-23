"""add-client-tool-filter 5.x：離線量測腳本。 / Offline tool-filter measurement."""

import json
import tempfile
import unittest
from pathlib import Path

from jiezi.eval import tool_filter_report as R


def tool(name, desc="generic helper " * 40):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": {}}}}


class ReportTests(unittest.TestCase):
    def test_collect_dedupe_retention_and_files(self):
        tools = [tool(f"t{i}") for i in range(30)] + [tool("weather_get", "weather forecast")]
        msgs = [{"role": "user", "content": "weather today"},
                {"role": "assistant", "content": None,
                 "tool_calls": [{"id": "1", "type": "function", "function": {"name": "weather_get", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "1", "content": "sunny"}]
        rec = {"id": "a", "at": "x", "policy": "jiezi-local", "request": {"messages": msgs, "tools": tools}}
        small = {"id": "b", "request": {"messages": msgs, "tools": tools[:2]}}   # 一般聊天，不收 / not an agent
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / "2026-11-23.jsonl").write_text(
                "\n".join(json.dumps(r) for r in (rec, rec, small)) + "\nnot json\n", encoding="utf-8")
            reqs = R.collect(root)
            self.assertEqual(len(reqs), 1)                                   # 重複與小請求都排除 / deduped
            cases = R.retention_cases(reqs)
            self.assertEqual([(c["name"], c["new"]) for c in cases], [("weather_get", True)])
            self.assertEqual(R.retention(cases, 12)["new_tool"]["rate"], 1.0)
            md, s = R.report(root, "20261123")
            self.assertTrue(md.exists() and (root / "var" / "reports" / "tool-filter-20261123.jsonl").exists())
            self.assertEqual(s["requests"], 1)
            self.assertLess(s["tool_tokens_after_median"], s["tool_tokens_before_median"])


if __name__ == "__main__":
    unittest.main()

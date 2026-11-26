"""add-long-context 3.1：代理程式請求重放評測的挑選與判分。 / Selection and scoring of the agent replay."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jiezi.eval import agent_replay as R  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": n, "parameters": {"type": "object", "properties": {}}}}
         for n in ("terminal", "read_file")]


def rec(i, system="You are Hermes Agent", tools=TOOLS, answer=None, provider="cloud", extra="", **kw):
    ans = answer or {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "terminal", "arguments": "{}"}}]}
    return {"id": f"r{i}", "request": {"messages": [{"role": "system", "content": system + extra},
                                                    {"role": "user", "content": f"問題 {i}"}], "tools": tools},
            "tiers": [{"tier": 3, "provider": provider, "answer": ans}], **kw}


class SelectTests(unittest.TestCase):
    def test_only_agent_requests_answered_by_the_cloud(self):
        items = R.select([rec(1), rec(2, system="你的名字是芥子"), rec(3, tools=[]), rec(4, provider=None),
                          rec(5, eval=True)])
        self.assertEqual([i["id"] for i in items], ["r1"])
        self.assertEqual((items[0]["cloud_tools"], items[0]["fits"]), (["terminal"], True))

    def test_within_budget_requests_come_first(self):
        big = "很長" * 20000
        items = R.select([rec(1, extra=big), rec(2), rec(3, extra=big), rec(4)], limit=3)
        self.assertEqual([(i["id"], i["fits"]) for i in items], [("r2", True), ("r4", True), ("r1", False)])

    def test_duplicates_dropped(self):
        self.assertEqual(len(R.select([rec(1), {**rec(1), "id": "again"}])), 1)


class JudgeTests(unittest.TestCase):
    item = {"tools": TOOLS, "cloud_tools": ["terminal"]}

    def test_same_valid_tool(self):
        j = R.judge(self.item, {"status": 200, "tools": ["terminal"], "jiezi": {"tier": 0, "verification": "pass"}})
        self.assertEqual(j, {"local": True, "valid": True, "same": True})

    def test_unknown_tool_is_invalid(self):
        j = R.judge(self.item, {"status": 200, "tools": ["manage_catalog"], "jiezi": {"tier": 1, "verification": "fail"}})
        self.assertEqual((j["local"], j["valid"], j["same"]), (True, False, False))

    def test_413_is_not_local(self):
        self.assertEqual(R.judge(self.item, {"status": 413, "error": "context_too_large"}),
                         {"local": False, "valid": False, "same": False})

    def test_summary(self):
        items = {"a": self.item, "b": self.item}
        rows = [{"id": "a", "status": 200, "tools": ["terminal"], "jiezi": {"tier": 0, "verification": "pass"},
                 "seconds": 12.0},
                {"id": "b", "status": 200, "tools": ["read_file"], "jiezi": {"tier": 0, "verification": "pass"},
                 "seconds": 20.0}]
        s = R.summary(items, rows)
        self.assertEqual((s["requests"], s["local"], s["valid"], s["same_tool"], s["median_s"]), (2, 2, 1.0, 0.5, 16.0))


if __name__ == "__main__":
    unittest.main()

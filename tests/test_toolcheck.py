"""工具呼叫系統評測測試：題目轉換、tool_calls 轉回 ACEBench 文字、用同一評分器判分。 / Tool-check tests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi import toolcheck as T  # noqa: E402

ITEM = {"id": "normal_1", "source": "acebench-zh", "task": "tool", "data": {
    "question": "user: 幫我查台北天氣\nsystem: 要查哪一天？\nuser: 明天\n",
    "functions": [{"name": "get_weather", "description": "查天氣",
                   "parameters": {"type": "object", "properties": {"city": {"type": "string"},
                                                                   "day": {"type": "string"}},
                                  "required": ["city", "day"]}}],
    "ground_truth": {"get_weather": {"city": "台北", "day": "明天"}}}}


class TestToolcheck(unittest.TestCase):
    def test_conversions(self):
        self.assertEqual([m["role"] for m in T.to_messages(ITEM["data"]["question"])], ["user", "assistant", "user"])
        self.assertEqual(T.to_tools(ITEM["data"]["functions"])[0]["function"]["parameters"]["required"], ["city", "day"])
        msg = {"tool_calls": [{"function": {"name": "get_weather", "arguments": json.dumps({"city": "台北", "day": "明天"})}}]}
        self.assertEqual(T.calls_text(msg), "[get_weather(city='台北', day='明天')]")

    def test_run_scores_with_the_acebench_checker(self):
        answers = iter([{"tool_calls": [{"function": {"name": "get_weather",
                                                      "arguments": json.dumps({"city": "台北", "day": "明天"})}}]}])

        def fake(url, key, policy, messages, tools):
            return {"choices": [{"message": next(answers)}], "jiezi": {"tier": 0, "confidence": 1.0}}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bank = root / "var" / "eval" / "banks" / "r0"
            bank.mkdir(parents=True)
            (bank / "items.jsonl").write_text(json.dumps(ITEM, ensure_ascii=False) + "\n", encoding="utf-8")
            out, summary = T.run(root, "http://x", "k", ask_fn=fake, log=lambda *_: None)
        self.assertEqual((summary["items"], summary["correct"]), (1, 1))


if __name__ == "__main__":
    unittest.main()

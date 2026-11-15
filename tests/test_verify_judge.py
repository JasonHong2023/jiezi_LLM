"""LLM 評審測試（假客戶端，不發出任何網路請求）：判定解析、重試、快取、拒絕自評、官方彙總。
LLM judge tests (fake client, no network): parsing, retry, cache, self-judging refusal, official aggregation."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval.client import Reply  # noqa: E402
from jiezi.verify import judge as jd  # noqa: E402


class FakeClient:
    def __init__(self, replies):
        self.replies, self.prompts, self.limits = list(replies), [], []

    def complete(self, messages, temperature=0.0, max_tokens=0, extra=None):
        self.prompts.append(messages[0]["content"])
        self.limits.append(max_tokens)
        r = self.replies.pop(0)
        return r if isinstance(r, Reply) else Reply("ok", content=r, model="deepseek-v4.1-flash")


QA = {"source": "chinese-simpleqa", "id": "q1", "data": {"question": "台灣最高峰？", "answer": "玉山"}}
WIKI = {"source": "zhwiki-featured", "id": "w1", "data": {"text": "玉山是台灣最高峰，海拔3952公尺。\n位於中部。"}}


class TestJudge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def judge(self, replies):
        c = FakeClient(replies)
        return jd.Judge(c, "nvidia-deepseek-v4.1-flash", self.cache, reasoning_budget=100), c

    def test_simpleqa_grades_and_official_prompt(self):
        j, c = self.judge(["<think>嗯</think>A"])
        r = j.simpleqa(QA, "玉山")
        self.assertEqual((r["status"], r["score"]), ("correct", 1))
        self.assertIn("正确答案: 玉山", c.prompts[0])
        self.assertIn("预测答案: 玉山", c.prompts[0])
        self.assertEqual(c.limits, [16 + 100])
        for letter, status in (("B", "incorrect"), ("C", "not_attempted")):
            j, _ = self.judge([letter])
            self.assertEqual(j.simpleqa({**QA, "id": letter}, "x")["status"], status)

    def test_cache_prevents_second_call(self):
        j, c = self.judge(["A"])
        j.simpleqa(QA, "玉山")
        r = j.simpleqa(QA, "玉山")
        self.assertTrue(r["cached"])
        self.assertEqual(len(c.prompts), 1)

    def test_unparsed_after_one_retry_not_scored(self):
        j, c = self.judge(["我覺得對", "嗯"])
        r = j.simpleqa(QA, "玉山")
        self.assertEqual((r["status"], r["score"], len(c.prompts)), ("judge_unparsed", None, 2))

    def test_errors_not_cached(self):
        j, _ = self.judge([Reply("error_timeout", error="timeout")])
        self.assertEqual(j.simpleqa(QA, "玉山")["status"], "error_timeout")
        self.assertEqual(list(self.cache.glob("*.json")), [])

    def test_refuses_self_judging(self):
        j, _ = self.judge([])
        with self.assertRaises(jd.JudgeRefused):
            j.check_not_self("NVIDIA-DeepSeek-v4.1-Flash")
        j.check_not_self("nvidia-nemotron-3-ultra")

    def test_summary_faithfulness_and_coverage(self):
        reply = json.dumps({"sentences": [{"text": "玉山最高", "supported": True},
                                          {"text": "海拔5000", "supported": False}],
                            "coverage": 2, "reason": "第二句錯"}, ensure_ascii=False)
        j, c = self.judge(["```json\n" + reply + "\n```"])
        r = j.summary(WIKI, "玉山是台灣最高峰。海拔5000公尺。")
        self.assertEqual((r["status"], r["details"]["faithfulness"], r["details"]["coverage"]), ("judged", 0.5, 2))
        self.assertIn("原文第一段：\n玉山是台灣最高峰，海拔3952公尺。\n", c.prompts[0])

    def test_summary_bad_json_and_empty(self):
        j, _ = self.judge(['{"sentences": [], "coverage": 2}', '{"coverage": 5}'])
        self.assertEqual(j.summary(WIKI, "摘要")["status"], "judge_unparsed")
        j, c = self.judge([])
        self.assertEqual(j.summary(WIKI, "<think>x</think>")["status"], "unparsed")
        self.assertEqual(c.prompts, [])

    def test_official_metrics(self):
        m = jd.simpleqa_metrics(["correct"] * 2 + ["incorrect"] * 1 + ["not_attempted"] * 1)
        self.assertEqual((m["correct"], m["accuracy_given_attempted"]), (0.5, round(2 / 3, 4)))
        self.assertAlmostEqual(m["f1"], 2 * (2 / 3) * 0.5 / (2 / 3 + 0.5), places=4)


if __name__ == "__main__":
    unittest.main()

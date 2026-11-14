"""提示模板與評分測試（規格 eval：Scoring）。 / Prompt and scoring tests."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import prompts, scoring  # noqa: E402

MC = {"scorer": "multiple_choice", "task": "qa", "data": {"question": "題", "answer": "B",
                                                          "choices": {"A": "a", "B": "b", "C": "c", "D": "d"}}}
SQ = {"scorer": "simpleqa_approx", "task": "qa", "data": {"question": "伏兔穴所属的经脉是什么？", "answer": "足阳明胃经"}}


class TestChoice(unittest.TestCase):
    def test_formats(self):
        cases = {"B": "B", "答案：B": "B", "答案是 (C)": "C", "（Ｄ）": "D", "我選擇A。": "A",
                 "A和B都不對，答案是C": "C", "<think>也許是A</think>B": "B", "Because": None, "": None}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(scoring.extract_choice(text), want)

    def test_score_mc(self):
        self.assertEqual(scoring.score(MC, "答案：B")["status"], "correct")
        self.assertEqual(scoring.score(MC, "C")["score"], 0)
        r = scoring.score(MC, "我不知道")
        self.assertEqual((r["status"], r["score"]), ("unparsed", 0))


class TestSimpleQA(unittest.TestCase):
    def test_traditional_and_punctuation_match(self):
        self.assertEqual(scoring.score(SQ, "伏兔穴屬於「足陽明胃經」。")["status"], "correct")
        self.assertEqual(scoring.score(SQ, "足太陰脾經")["status"], "wrong")

    def test_width_and_case(self):
        item = {"scorer": "simpleqa_approx", "task": "qa", "data": {"question": "q", "answer": "ABC 123"}}
        self.assertEqual(scoring.score(item, "答案是ａｂｃ１２３")["status"], "correct")

    def test_empty_gold_never_matches(self):
        item = {"scorer": "simpleqa_approx", "task": "qa", "data": {"question": "q", "answer": "。"}}
        self.assertEqual(scoring.score(item, "任何回答")["status"], "wrong")

    def test_pending(self):
        item = {"scorer": "pending_verifier", "task": "code", "data": {"prompt": "def f():"}}
        self.assertEqual(scoring.score(item, "x"), {"status": "pending_verifier", "score": None, "extracted": None})


class TestPrompts(unittest.TestCase):
    def test_render_each_kind(self):
        items = [MC, SQ,
                 {"scorer": "pending_verifier", "task": "code", "data": {"prompt": "def f():"}},
                 {"scorer": "pending_verifier", "task": "tool",
                  "data": {"question": "user: 查天氣\n", "functions": [{"name": "weather"}]}},
                 {"scorer": "pending_verifier", "task": "summary", "data": {"text": "內文"}}]
        for it in items:
            msgs, max_tokens = prompts.render(it)
            self.assertEqual(msgs[0]["role"], "user")
            self.assertGreater(max_tokens, 0)
        tool_msg = prompts.render(items[3])[0][0]["content"]
        self.assertIn('"weather"', tool_msg)
        self.assertNotIn("user:", tool_msg)

    def test_template_hash_stable(self):
        self.assertEqual(prompts.template_hash(), prompts.template_hash())
        self.assertEqual(len(prompts.template_hash()), 16)


if __name__ == "__main__":
    unittest.main()

"""摘要規則檢查測試：字數邊界、簡體字判定（含繁簡同形字）。
Summary rule tests: length bounds and simplified-character detection (incl. shared forms)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.verify import summary_rules as sr  # noqa: E402


class TestSummaryRules(unittest.TestCase):
    def test_length_bounds_ignore_whitespace(self):
        for n, ok in ((99, False), (100, True), (150, True), (151, False)):
            text = "臺" * (n - 2) + " \n" + "灣。"
            r = sr.verify({}, text)
            self.assertEqual((r["details"]["chars"], r["details"]["length_ok"]), (n, ok))

    def test_shared_forms_are_not_simplified(self):
        self.assertEqual(sr.verify({}, "皇后在台上看表，公里外有麵食與干戈")["details"]["simplified_chars"], [])

    def test_simplified_only_chars_flagged(self):
        r = sr.verify({}, "这是发表的干净文章" + "臺" * 100)
        self.assertEqual(r["details"]["simplified_chars"], ["净", "发", "这"])
        self.assertEqual((r["status"], r["score"]), ("wrong", 0))

    def test_pass_and_thinking_removed(self):
        r = sr.verify({}, "<think>这里发</think>" + "臺灣是島嶼。" * 20)
        self.assertEqual((r["status"], r["score"], r["details"]["traditional_ok"]), ("correct", 1, True))

    def test_empty_is_unparsed(self):
        self.assertEqual(sr.verify({}, "<think>x</think>")["status"], "unparsed")


if __name__ == "__main__":
    unittest.main()

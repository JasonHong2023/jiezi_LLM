import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jiezi.eval import vision_text as VT  # noqa: E402


class TestScore(unittest.TestCase):
    def test_recall_and_numbers(self):
        truth = "山海麵線\n營業時間 08:30-20:30\n電話 07-7498-2327"
        s = VT.score_one(truth, "圖上寫著：「山海麵線」，營業時間 08:30-20:30，電話 07-7498-2327。")
        self.assertEqual(s["recall"], 1.0)
        self.assertEqual((s["number_hits"], s["numbers"]), (2, 2))
        s = VT.score_one(truth, "山海面線，營業 8:30 到 20:30，電話 07-7498-2372")
        self.assertLess(s["recall"], 1.0)
        self.assertEqual(s["number_hits"], 0)

    def test_tai_variants_and_width(self):
        self.assertEqual(VT.score_one("違者處新臺幣600元罰鍰", "違者處新台幣６００元罰鍰")["recall"], 1.0)

    def test_summary(self):
        items = {"a": {"text": "日日咖啡"}, "b": {"text": "菜單 紅茶 30元"}}
        rows = [{"id": "a", "answer": "日日咖啡", "seconds": 2.0}, {"id": "b", "error": "boom"}]
        s = VT.summary(rows, items)
        self.assertEqual((s["images"], s["errors"], s["char_recall"]), (2, 1, 1.0))

    def test_prepare_without_fonts(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(VT.prepare(Path(d), 2, font_dir=d, log=lambda *_: None), 1)


if __name__ == "__main__":
    unittest.main()

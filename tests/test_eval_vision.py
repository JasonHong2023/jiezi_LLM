"""看圖評測的計分（add-vision-tools 1.2）。 / Scoring of the vision evaluation."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jiezi.eval import vision as EV  # noqa: E402

KNOWN = {"person", "man", "woman", "boy", "girl", "dog", "cat", "car", "land vehicle", "tree", "plant", "clothing",
         "mobile phone", "human face", "zebra", "horse"}


class TestMatch(unittest.TestCase):
    def test_classes_for(self):
        self.assertEqual(EV.classes_for("Dogs", KNOWN), {"dog"})
        self.assertEqual(EV.classes_for("red car", KNOWN), {"car"})
        self.assertEqual(EV.classes_for("people", KNOWN), {"person", "man", "woman", "boy", "girl"})
        self.assertEqual(EV.classes_for("smartphone", KNOWN), {"mobile phone"})
        self.assertEqual(EV.classes_for("sky", KNOWN), set())                 # 不是類別 / not a class
        self.assertEqual(EV.classes_for("giraffe", KNOWN), set())

    def test_score_one(self):
        s = EV.score_one(["man", "dog", "zebra", "tree", "giraffe", "Dog"], pos={"man", "dog", "clothing"},
                         neg={"zebra", "cat"}, known=KNOWN)
        self.assertEqual((s["correct"], s["wrong"], s["unknown"], s["unmatched"]), (2, 1, 1, 1))
        self.assertEqual(s["named_pos"], ["dog", "man"])
        self.assertEqual(s["wrong_names"], ["zebra"])

    def test_summary(self):
        items = {"a": {"positives": ["dog", "man"], "negatives": ["cat"]},
                 "b": {"positives": ["horse"], "negatives": ["zebra"]}}
        rows = [{"id": "a", "objects": ["dog", "cat"], "seconds": 10}, {"id": "b", "objects": ["horse"], "seconds": 30},
                {"id": "c", "objects": ["x"]}, {"id": "b", "error": "boom"}]
        s = EV.summary(rows, items, KNOWN)
        self.assertEqual((s["images"], s["correct"], s["wrong"], s["errors"]), (2, 2, 1, 1))
        self.assertEqual(s["precision"], round(2 / 3, 4))
        self.assertEqual(s["recall"], round(2 / 3, 4))


if __name__ == "__main__":
    unittest.main()

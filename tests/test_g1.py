"""G1 推薦測試：速度門檻、信賴區間內選小的、知識差距。 / G1 recommendation tests."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.runtime import g1  # noqa: E402


def c(name, size, reas, ci, know, tps):
    return {"name": name, "size_mib": size, "placement": "gpu", "reasoning": reas, "reasoning_ci": ci,
            "knowledge": know, "faithful": 0.8, "tps": tps, "ram": 0, "vram": 0}


class TestG1(unittest.TestCase):
    def test_prefers_smaller_within_ci_and_skips_slow(self):
        cands = [c("big", 2600, 0.50, (0.40, 0.60), 0.55, 40), c("small", 1200, 0.46, (0.36, 0.56), 0.45, 80),
                 c("slow", 5000, 0.70, (0.60, 0.80), 0.70, 4)]
        r = g1.recommend(cands)
        self.assertEqual(r["winner"]["name"], "small")              # 0.46 ≥ 0.40：打平選小的 / tie → smaller
        self.assertEqual(r["slow"], ["slow"])                      # 太慢不列入 / too slow
        self.assertEqual(r["knowledge_gap_points"], 10.0)

    def test_clear_winner(self):
        r = g1.recommend([c("a", 1000, 0.30, (0.2, 0.4), 0.3, 50), c("b", 2000, 0.60, (0.5, 0.7), 0.4, 30)])
        self.assertEqual(r["winner"]["name"], "b")

    def test_nothing_eligible(self):
        self.assertIsNone(g1.recommend([c("x", 1, 0.5, None, 0.5, 2)])["winner"])


if __name__ == "__main__":
    unittest.main()

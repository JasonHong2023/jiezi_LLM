"""回答的過程（add-answer-process）。 / The steps behind an answer."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jiezi.runtime.process import DRAFT_MAX, TimedTiers, steps  # noqa: E402


class TestProcess(unittest.TestCase):
    def test_escalated_question(self):
        tiers = TimedTiers()
        tiers.append({"tier": 0, "model": "qwen", "answer": {"content": "兒童節 5/20\n\n---\n【參考資料】\n- x"},
                      "verification": {"status": "fail", "error": "「冬至」在資料裡找不到 / not found"},
                      "needs_help": "unsupported_claims"})
        tiers.append({"tier": 3, "provider": "claude", "model": "claude-opus-5-5", "reason": "unsupported_claims",
                      "answer": {"content": "正確答案"}})
        rec = {"tiers": tiers, "sources": [{"source": "taiwan-md", "article": "國定假日", "section": "台灣史"},
                                           {"source": "tools", "tool": "lunar"}]}
        out = steps(rec)
        self.assertEqual([s["label"] for s in out], ["查資料", "本機作答", "請教 Claude"])
        self.assertEqual(out[0]["items"], ["Taiwan.md〈國定假日〉：台灣史", "計算（lunar）"])
        self.assertEqual(out[1]["draft"], "兒童節 5/20")                      # 附錄拿掉 / appendix removed
        self.assertEqual(out[1]["check"], "沒通過：「冬至」在資料裡找不到")
        self.assertNotIn("draft", out[2])                                     # 最後的回答不重複 / final not repeated
        self.assertEqual(out[2]["why"], "unsupported_claims")
        self.assertTrue(all(isinstance(s.get("t_s"), float) for s in out[1:]))

    def test_long_draft_and_failures(self):
        tiers = TimedTiers()
        tiers.append({"tier": 0, "answer": {"content": "字" * (DRAFT_MAX + 10)}, "needs_help": "self_reported_unsure"})
        tiers.append({"tier": 3, "provider": "claude", "error": "usage limit"})
        tiers.append({"tier": 3, "provider": "cloud", "answer": {"content": "雲端答案"}})
        out = steps({"tiers": tiers, "vision": {"detections": {"Dog": 2}, "tiles": {"grid": 8, "seconds": 18.1}}})
        self.assertEqual(out[0]["items"], ["偵測：Dog×2", "切塊放大 8 塊，18.1 秒"])
        self.assertEqual(len(out[1]["draft"]), DRAFT_MAX + 1)
        self.assertEqual(out[1]["check"], "本機說不確定")
        self.assertEqual(out[2]["error"], "usage limit")
        self.assertEqual(out[3]["label"], "雲端模型")
        self.assertEqual(steps({}), [])
        mem = steps({"sources": [{"source": "memory", "page": "台灣2027年的國定假日有哪些", "kind": "answer"}]})
        self.assertEqual(mem[0]["items"], ["記憶〈台灣2027年的國定假日有哪些〉"])


if __name__ == "__main__":
    unittest.main()

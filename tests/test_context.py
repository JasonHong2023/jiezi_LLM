"""上下文把關測試：不超過就不動；超過時依序裁舊對話、長資料、問題；身分提示與最後的問題保留。 / Context guard tests."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.runtime import context as C  # noqa: E402


class TestContext(unittest.TestCase):
    def test_untouched_when_small(self):
        msgs = [{"role": "system", "content": "你是芥子"}, {"role": "user", "content": "早安"}]
        out, info = C.fit(msgs)
        self.assertEqual(out, msgs)
        self.assertEqual(info["dropped_turns"], 0)

    def test_order_of_trimming(self):
        persona = {"role": "system", "content": "你是芥子"}
        old = [{"role": "user", "content": "舊" * 800}, {"role": "assistant", "content": "答" * 800}]
        data = {"role": "system", "content": "資料" * 1700}  # 丟掉舊對話後仍超出 / still over after dropping turns
        q = {"role": "user", "content": "最新的問題"}
        out, info = C.fit([persona, *old, data, q])
        self.assertLessEqual(info["after"], C.SLOT_CTX - C.DEFAULT_ANSWER)
        self.assertEqual(out[0], persona)                         # 身分提示不動 / persona kept
        self.assertEqual(out[-1], q)                              # 最後的問題不動 / question kept
        self.assertEqual(info["dropped_turns"], 2)                # 先丟舊對話 / old turns first
        self.assertGreater(info["shortened_data"], 0)             # 再截資料 / then data
        self.assertIn("已截短", out[1]["content"])

    def test_long_question_kept_head_and_tail(self):
        q = "開頭" + "中" * 6000 + "結尾"
        out, info = C.fit([{"role": "user", "content": q}])
        self.assertTrue(info["shortened_question"])
        self.assertTrue(out[0]["content"].startswith("開頭") and out[0]["content"].endswith("結尾"))

    def test_estimate(self):
        self.assertEqual(C.est_tokens("中文字"), 4)
        self.assertLess(C.est_tokens("hello world " * 10), 40)


if __name__ == "__main__":
    unittest.main()

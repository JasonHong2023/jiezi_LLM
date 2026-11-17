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

    def test_data_at_the_floor_never_loops(self):
        # 2026-11-17 實測的卡死：附加資料剛好比下限長一點、問題又超長時，截短後加上標記並沒有變短
        # The live hang: data just above the floor plus an over-long question never got shorter
        for extra in range(0, 12):
            msgs = [{"role": "system", "content": "身分"}, {"role": "system", "content": "規" * (C.MIN_DATA_CHARS + extra)},
                    {"role": "user", "content": "長" * 20000}]
            out, info = C.fit(msgs, ctx=4096)
            self.assertTrue(info["shortened_question"])
            self.assertLessEqual(len(out[1]["content"]), C.MIN_DATA_CHARS + 12)

    def test_system_messages_merge_to_the_front(self):
        msgs = [{"role": "system", "content": "身分"}, {"role": "user", "content": "問一"},
                {"role": "assistant", "content": "答一"}, {"role": "system", "content": "資料"},
                {"role": "system", "content": [{"type": "text", "text": "提醒"}]}, {"role": "user", "content": "問二"}]
        out = C.merge_system(msgs)
        self.assertEqual([m["role"] for m in out], ["system", "user", "assistant", "user"])
        self.assertEqual(out[0]["content"], "身分\n\n資料\n\n提醒")
        self.assertEqual(C.merge_system(msgs[1:3]), msgs[1:3])               # 沒有 system 就不動 / untouched

    def test_retry_keeps_a_long_question_with_its_document(self):
        from jiezi.runtime import escalation as E
        doc = "【文件：a.txt】\n" + "條文內容。" * 560 + "\n\n每天最多工作幾小時？"
        self.assertEqual(C.fit([{"role": "system", "content": "身分"}, {"role": "user", "content": doc}])[1]["dropped_turns"], 0)
        msgs = [{"role": "system", "content": "身分"}, {"role": "user", "content": doc}]
        retry = E.retry_messages(msgs, {"content": "答錯的內容" * 300}, "數字找不到")
        self.assertEqual([m["role"] for m in retry], ["system", "user"])          # 一則，不是三則 / one message
        out, info = C.fit(retry, ctx=4096)
        self.assertEqual(info["dropped_turns"], 0)
        last = out[-1]["content"]
        self.assertTrue(last.startswith("【文件：a.txt】"))                        # 文件還在 / the document survives
        self.assertFalse(info["shortened_question"])                              # 自己讓出空間，不靠把關亂裁 / makes its own room
        self.assertIn("每天最多工作幾小時？", last)                                # 問題還在 / the question survives
        self.assertIn("答錯的內容", last)
        self.assertIn("數字找不到", last)
        short = E.retry_messages([{"role": "user", "content": "1+1？"}], {"content": "3"}, "算錯")
        self.assertEqual([m["role"] for m in short], ["user", "assistant", "user"])  # 短問題照舊 / short ones unchanged

    def test_estimate(self):
        self.assertEqual(C.est_tokens("中文字"), 4)
        self.assertLess(C.est_tokens("hello world " * 10), 40)


if __name__ == "__main__":
    unittest.main()

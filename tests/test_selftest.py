"""自我評測測試：出題可重現、判分只看模型文字、數值容差、知識庫看來源。 / Self-test tests."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi import selftest as S  # noqa: E402


class TestSelftest(unittest.TestCase):
    def test_reproducible_without_data(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = S.build(Path(d)), S.build(Path(d))
        self.assertEqual([i.question for i in a], [i.question for i in b])
        self.assertEqual({i.kind for i in a}, {"calc", "units", "dates"})  # 沒建資料就只有工具題 / tools only

    def test_scoring(self):
        num = S.Item("x", "units", "q", number=1.2)
        self.assertTrue(S.score(num, "是 1.2 公斤", []))
        self.assertFalse(S.score(num, "是 1.5 公斤\n\n---\n【計算】\n- 2 台斤 = 1.2 公斤", []))  # 附錄不算 / appendix ignored
        exp = S.Item("y", "dict-zh", "q", expect=["ㄕˊ ㄧㄢˊ ㄦˊ ㄈㄟˊ"])
        self.assertTrue(S.score(exp, "注音是ㄕˊㄧㄢˊㄦˊㄈㄟˊ。", []))
        kb = S.Item("z", "knowledge", "q", article="刈包")
        self.assertTrue(S.score(kb, "", [{"article": "刈包"}]))
        self.assertFalse(S.score(kb, "刈包", []))

    def test_scoring_variants_and_punctuation(self):
        tw = S.Item("t", "dict-tw", "q", expect=["lia̍h-tsò/lia̍h-tsuè"])
        self.assertTrue(S.score(tw, "「掠做」台羅是：lia̍h-tsò（或 lia̍h-tsuè）。", []))
        self.assertTrue(S.score(tw, "念 lia̍h-tsuè", []))
        self.assertFalse(S.score(tw, "念 lia̍h-tsō", []))
        book = S.Item("b", "textbook", "q", expect=["跨科：氣候變遷與調適"])
        self.assertTrue(S.score(book, "第 3 單元是：跨科——氣候變遷與調適。", []))

    def test_run_with_fake_gateway(self):
        def fake(url, key, policy, q):
            return {"choices": [{"message": {"content": "不知道"}}], "jiezi": {"tier": 0, "sources": []}}
        with tempfile.TemporaryDirectory() as d:
            out, summary = S.run(Path(d), "http://x", "k", limit=2, ask_fn=fake, log=lambda *_: None)
            self.assertEqual((summary["items"], summary["correct"]), (6, 0))
            self.assertTrue(out.exists() and out.with_suffix(".jsonl").exists())



class TestDataBuild(unittest.TestCase):
    def test_one_failure_does_not_stop_the_rest(self):
        from unittest import mock
        from jiezi.runtime import __main__ as M
        built = []

        class Ok:
            @staticmethod
            def build(root):
                built.append(root)
                return "ok"

        class Bad:
            @staticmethod
            def build(root):
                raise RuntimeError("no network")
        mods = {"jiezi.dictionary": Bad, "jiezi.curriculum": Ok, "jiezi.knowledge": Ok, "jiezi.laws": Ok,
                "jiezi.writing_refs": Ok}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch("importlib.import_module", side_effect=lambda name: mods[name]):
            rc = M.cmd_data_build(Path(d), log=lambda *_: None)
        self.assertEqual((rc, len(built)), (1, 4))


if __name__ == "__main__":
    unittest.main()

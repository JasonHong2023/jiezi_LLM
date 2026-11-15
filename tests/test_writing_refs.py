"""寫作教學連結索引測試：只取站內文章連結、觸發與不觸發、請教提示。
Writing-link index tests: site article links only, trigger rules, consultation hint."""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi import writing_refs as W  # noqa: E402

PAGE = """<h3> </h3><h3><b>【人物】</b></h3>
<div><a href="/2015/11/flbw.html" target="_blank">FLBW角色壓力設計法</a></div>
<div><a href="/2015/11/Role.html">小說的８種角色原型</a></div>
<h3><b>【靈感】</b></h3>
<div><a href="/2015/05/idea.html">找靈感的基本觀念</a></div>
<a href="/shop">進階課程</a><a href="https://example.com/2015/x">外站</a>"""


class TestWritingRefs(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        self.assertEqual(W.build(self.root, fetch=lambda url: PAGE), 3)
        self.w = W.WritingRefs(W.index_path(self.root))

    def tearDown(self):
        self._t.cleanup()

    def test_parse(self):
        self.assertEqual(self.w.refs[0], {"category": "人物", "title": "FLBW角色壓力設計法",
                                          "url": "https://www.rocknovels.com/2015/11/flbw.html"})
        self.assertEqual(self.w.refs[2]["category"], "靈感")

    def test_appendix(self):
        self.assertIsNone(self.w.appendix("早安"))
        self.assertIsNone(self.w.appendix("寫一個 Python 函式"))
        text, sources = self.w.appendix("小說角色要怎麼設計？")
        self.assertIn("【延伸閱讀】", text)
        self.assertIn("https://www.rocknovels.com/2015/11/flbw.html", text)
        self.assertIn("© 故事革命", text)
        self.assertEqual(sources[0]["source"], "rocknovels-teachlist")

    def test_consult_hint(self):
        self.assertIsNone(self.w.consult_hint("今天天氣如何"))
        hint = self.w.consult_hint("寫小說沒有靈感怎麼辦")
        self.assertIn("找靈感的基本觀念", hint)
        self.assertIn("不要大段照抄", hint)


if __name__ == "__main__":
    unittest.main()

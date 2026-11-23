"""全國法規資料庫測試：建置、條號（含中文數字與之 N）、簡稱、不存在的條、廢止法、觸發。 / Law database tests."""

import hashlib
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi import laws as L  # noqa: E402

XML = """<?xml version="1.0" encoding="UTF-8"?>
<LAWS UpdateDate="2026/11/6 上午 12:00:00">
  <法規><法規名稱>勞動基準法</法規名稱><法規網址>https://example.invalid/L1</法規網址><廢止註記></廢止註記>
    <法規內容><編章節>第 四 章 工作時間</編章節>
      <條文><條號>第 32 條</條號><條文內容><![CDATA[延長之工作時間，一個月不得超過四十六小時。]]></條文內容></條文>
      <條文><條號>第 32-1 條</條號><條文內容><![CDATA[補休的規定。]]></條文內容></條文>
    </法規內容></法規>
  <法規><法規名稱>舊工廠法</法規名稱><法規網址>https://example.invalid/L2</法規網址><廢止註記>廢</廢止註記>
    <法規內容><條文><條號>第 1 條</條號><條文內容><![CDATA[工廠工人工作時間的處罰規定。]]></條文內容></條文></法規內容></法規>
</LAWS>"""


def blob():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("FalV.xml", XML)
    return b.getvalue()


BLOB = blob()
MANIFEST = f"""[source]
key = "moj-laws"
title = "測試法規"
url = "https://example.invalid/laws.zip"
sha256 = "{hashlib.sha256(BLOB).hexdigest()}"
size = {len(BLOB)}
data_date = "2026-11-06"
license = "政府資料開放授權條款第 1 版"
license_url = "https://example.invalid/l"
training_use = true
attribution = "資料來源：測試法規"
license_checked = "2026-11-16"
"""


class TestLaws(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.root = Path(self._t.name)
        (self.root / "laws").mkdir()
        (self.root / "laws" / "manifest.toml").write_text(MANIFEST, encoding="utf-8")
        self.assertEqual(L.build(self.root, download=lambda u, d: d.write_bytes(BLOB), log=lambda *_: None),
                         {"laws": 2, "articles": 3})
        self.lw = L.Laws(L.db_path(self.root))

    def tearDown(self):
        self._t.cleanup()

    def test_articles(self):
        for q in ("勞動基準法第32條", "勞基法第三十二條規定什麼？", "勞基法 第 32 條"):
            content, sources, trainable, appendix = L.grounding(self.lw, q)
            self.assertEqual(sources, [{"source": "moj-laws", "law": "勞動基準法", "article": "第 32 條"}], q)
        for q in ("勞基法第32條之1", "勞基法第32-1條"):
            _, sources, _, appendix = L.grounding(self.lw, q)
            self.assertEqual(sources[0]["article"], "第 32-1 條", q)
        self.assertIn("不構成法律意見", appendix)
        self.assertTrue(trainable)

    def test_vector_hits_carry_scores(self):
        aid = self.lw.con.execute("SELECT id FROM articles ORDER BY id LIMIT 1").fetchone()[0]
        _, sources, _, _ = L.grounding(self.lw, "加班費有什麼規定", hybrid=lambda text, n: [(aid, 0.6612)])
        self.assertEqual(sources[0]["score"], 0.6612)

    def test_missing_abolished_and_triggers(self):
        content, sources, _, _ = L.grounding(self.lw, "勞基法第999條")
        self.assertEqual(sources, [])
        self.assertIn("勞動基準法沒有第999條", content)
        self.assertIsNone(L.grounding(self.lw, "我今天好累"))
        self.assertIsNone(self.lw.law_in("舊工廠法第1條"))                  # 廢止法不當現行法 / abolished
        self.assertEqual(L._cn_int("一百八十四"), 184)
        self.assertEqual(L._cn_int("３２"), 32)


if __name__ == "__main__":
    unittest.main()

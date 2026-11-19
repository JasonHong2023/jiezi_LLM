"""國定假日計算測試：條文解析、曆法換算、補假推算、觸發與降級。 / Holiday computation tests."""

import hashlib
import io
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi import holidays as H  # noqa: E402
from jiezi import laws as L  # noqa: E402

XML = """<?xml version="1.0" encoding="UTF-8"?>
<LAWS UpdateDate="2026/11/6 上午 12:00:00">
  <法規><法規名稱>紀念日及節日實施條例</法規名稱><法規網址>https://example.invalid/holiday</法規網址>
    <法規內容>
      <條文><條號>第 3 條</條號><條文內容><![CDATA[紀念日之名稱及日期如下：
一、中華民國開國紀念日：一月一日。
二、和平紀念日：二月二十八日。
三、孔子誕辰紀念日：九月二十八日。
四、國慶日：十月十日。
五、臺灣光復暨金門古寧頭大捷紀念日：十月二十五日。
六、行憲紀念日：十二月二十五日。]]></條文內容></條文>
      <條文><條號>第 4 條</條號><條文內容><![CDATA[下列紀念日均放假一日，其餘均不放假：
一、中華民國開國紀念日。
二、和平紀念日。
三、孔子誕辰紀念日。
四、國慶日。
五、臺灣光復暨金門古寧頭大捷紀念日。
六、行憲紀念日。]]></條文內容></條文>
      <條文><條號>第 5 條</條號><條文內容><![CDATA[節日之名稱及日期如下：
一、民俗節日：
（一）春節：農曆一月一日。
（二）清明節：定於清明日。
（三）端午節：農曆五月五日。
（四）中秋節：農曆八月十五日。
（五）除夕：農曆十二月之末日。
二、兒童節：四月四日。
三、勞動節：五月一日。
四、教師節：九月二十八日。]]></條文內容></條文>
      <條文><條號>第 6 條</條號><條文內容><![CDATA[前條所列節日之放假依下列規定辦理：
一、除夕及春節：自農曆十二月末日之前一日至翌年一月三日，放假五日。
二、兒童節、清明節、勞動節、端午節、教師節及中秋節：均放假一日。
兒童節與清明節同一日時，於前一日放假。但逢星期四時，於後一日放假。]]></條文內容></條文>
      <條文><條號>第 8 條</條號><條文內容><![CDATA[紀念日及節日之放假日逢例假日者，應予補假。調整放假及補行上班日期，除其他法令另有規定者外，由目的事業主管機關調移並公告之。]]></條文內容></條文>
    </法規內容></法規>
</LAWS>"""


def blob(xml=XML):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("FalV.xml", xml)
    return b.getvalue()


def manifest(data):
    return f"""[source]
key = "moj-laws"
title = "測試法規"
url = "https://example.invalid/laws.zip"
sha256 = "{hashlib.sha256(data).hexdigest()}"
size = {len(data)}
data_date = "2026-11-06"
license = "政府資料開放授權條款第 1 版"
license_url = "https://example.invalid/l"
training_use = true
attribution = "資料來源：測試法規"
license_checked = "2026-11-16"
"""


def build(xml=XML):
    t = tempfile.TemporaryDirectory()
    root = Path(t.name)
    (root / "laws").mkdir()
    data = blob(xml)
    (root / "laws" / "manifest.toml").write_text(manifest(data), encoding="utf-8")
    L.build(root, download=lambda u, d: d.write_bytes(data), log=lambda *_: None)
    return t, root


class TestHolidays(unittest.TestCase):
    def setUp(self):
        self._t, self.root = build()
        self.lw = L.Laws(L.db_path(self.root))

    def tearDown(self):
        self._t.cleanup()

    def test_2027(self):
        result = H.holidays(2027, lw=self.lw)
        self.assertIsNotNone(result)
        by_date = {e["date"]: e for e in result["entries"]}
        self.assertEqual(by_date["2027-02-04"]["name"], "除夕前一日")
        self.assertEqual(by_date["2027-02-05"]["name"], "除夕")
        self.assertEqual(by_date["2027-02-06"]["name"], "春節")
        self.assertEqual(by_date["2027-02-08"]["name"], "春節")
        self.assertIn("兒童節", by_date["2027-04-04"]["name"])
        self.assertIn("清明節", by_date["2027-04-05"]["name"])
        self.assertIn("端午節", by_date["2027-06-09"]["name"])
        self.assertIn("中秋節", by_date["2027-09-15"]["name"])
        self.assertIn("孔子誕辰紀念日", by_date["2027-09-28"]["name"])
        self.assertIn("教師節", by_date["2027-09-28"]["name"])
        self.assertNotIn("2027-02-03", by_date)  # 人事總處 116 年公告：初一、初二補 2/9、2/10
        for d in ("2027-02-09", "2027-02-10", "2027-03-01", "2027-04-06",
                  "2027-04-30", "2027-10-11", "2027-12-24", "2027-12-31"):
            self.assertTrue(by_date[d]["estimated"], d)
        self.assertFalse(by_date["2027-02-05"]["estimated"])
        self.assertIn("2028年開國紀念日補假", by_date["2027-12-31"]["name"])
        self.assertTrue(all(e["articles"] for e in by_date.values()))

    def test_spring_weekend_makeup_forward(self):
        # 春節逢例假日往後補：2021 初二／初三、2026 除夕前一日。
        by_date = {e["date"]: e for e in H.holidays(2021, lw=self.lw)["entries"]}
        for d in ("2021-02-15", "2021-02-16"):
            self.assertIn(d, by_date)
            self.assertTrue(by_date[d]["estimated"])
            self.assertIn("春節補假", by_date[d]["name"])
        by_date = {e["date"]: e for e in H.holidays(2026, lw=self.lw)["entries"]}
        self.assertIn("2026-02-20", by_date)
        self.assertTrue(by_date["2026-02-20"]["estimated"])
        self.assertIn("除夕前一日補假", by_date["2026-02-20"]["name"])

    def test_cross_year_new_year_makeup(self):
        # 1/1 逢星期六：補在上一年 12/31（2022、2028 案例）。
        by_date = {e["date"]: e for e in H.holidays(2022, lw=self.lw)["entries"]}
        self.assertIn("2021-12-31", by_date)
        self.assertIn("開國紀念日補假", by_date["2021-12-31"]["name"])
        by_date = {e["date"]: e for e in H.holidays(2028, lw=self.lw)["entries"]}
        self.assertIn("2027-12-31", by_date)
        self.assertIn("開國紀念日補假", by_date["2027-12-31"]["name"])

    def test_children_qingming_same_day(self):
        by_date = {e["date"]: e for e in H.holidays(2025, lw=self.lw)["entries"]}
        self.assertIn("兒童節", by_date["2025-04-04"]["name"])
        self.assertIn("清明節", by_date["2025-04-04"]["name"])
        self.assertIn("兒童節與清明節同一日之放假", by_date["2025-04-03"]["name"])

    def test_question_and_render(self):
        self.assertEqual(H.question_year("台灣2027年的國定假日有哪些?", date(2026, 11, 19)), 2027)
        self.assertEqual(H.question_year("明年有幾天假?", date(2026, 11, 19)), 2027)
        self.assertIsNone(H.question_year("今天天氣如何?", date(2026, 11, 19)))
        self.assertTrue(H.wants_holidays("2027年國定假日"))
        self.assertFalse(H.wants_holidays("今天天氣如何?"))
        result = H.holidays(2027, lw=self.lw)
        content, appendix = H.render(result)
        self.assertIn("【計算】", content)
        self.assertIn("以公告為準", content)
        self.assertIn("【法規出處】", appendix)
        self.assertIn("https://example.invalid/holiday", appendix)

    def test_grounding(self):
        grounded = H.grounding(self.lw, "台灣2027年的國定假日有哪些?", date(2026, 11, 19))
        self.assertIsNotNone(grounded)
        content, sources, trainable, appendix = grounded
        self.assertIn("2027-02-05", content)
        self.assertEqual(sources[0]["source"], "computed-holidays")
        self.assertTrue(trainable)
        self.assertIn("【計算】", appendix)
        self.assertIsNone(H.grounding(self.lw, "今天天氣如何?", date(2026, 11, 19)))

    def test_degrade(self):
        other = """<?xml version="1.0" encoding="UTF-8"?><LAWS><法規><法規名稱>其他法</法規名稱>
        <法規網址>https://example.invalid/other</法規網址><法規內容><條文><條號>第 1 條</條號>
        <條文內容><![CDATA[其他規定。]]></條文內容></條文></法規內容></法規></LAWS>"""
        t, root = build(other)
        try:
            lw = L.Laws(L.db_path(root))
            self.assertIsNone(H.holidays(2027, lw=lw))
            self.assertIsNone(H.grounding(lw, "台灣2027年的國定假日有哪些?"))
        finally:
            t.cleanup()


if __name__ == "__main__":
    unittest.main()

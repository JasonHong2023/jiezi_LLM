"""內建工具測試：計算、單位、日期、誤判防護、gateway。 / Built-in tool tests."""

import sys
import tempfile
import unittest
from datetime import datetime
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import tools as T  # noqa: E402

NOW = datetime(2026, 11, 16, 10, 30)


def facts(q):
    r = T.grounding(q, NOW)
    return r[3].split("\n", 3)[-1] if r else None


class TestCalculator(unittest.TestCase):
    def test_evaluate(self):
        self.assertEqual(T.evaluate("(12.5*4-3)/7"), Fraction(47, 7))
        self.assertEqual(T.evaluate("0.1+0.2"), Fraction(3, 10))          # 精確 / exact
        self.assertEqual(T.evaluate("根號16"), 4)
        for bad in ("2**100000", "__import__('os')", "10/0", "根號(-4)"):
            with self.assertRaises(T.CalcError):
                T.evaluate(bad)

    def test_phrases(self):
        self.assertIn("1+3 = 4（題目寫的 2 不正確）", facts("1+3=2 多少?"))
        self.assertIn("3*7+2 = 23", facts("3 乘以 7 加 2 等於多少"))
        self.assertIn("除數不能是 0", facts("100 除以 0 是多少"))

    def test_not_math(self):
        for q in ("Qwen3.5-2B 是什麼", "電話 02-2345-6789", "我的電話是 0912-345-678 對嗎?", "我 2026-11-16 要開會",
                  "我加油了 3 次", "台北101有多高"):
            self.assertIsNone(facts(q), q)


class TestUnitsAndDates(unittest.TestCase):
    def test_units(self):
        self.assertIn("3 公里 = 1.86411 英里", facts("3 公里是多少英里"))
        self.assertIn("2 台斤 = 1.2 公斤", facts("2 台斤是幾公斤"))
        self.assertIn("5 坪 = 16.5289 平方公尺", facts("5 坪等於幾平方公尺"))
        self.assertIn("攝氏 30 度 = 華氏 86 度", facts("攝氏 30 度是華氏幾度"))
        self.assertIn("60 公里/小時 = 16.6667 公尺/秒", facts("速度 60 km/h 是多少 m/s"))

    def test_dates(self):
        self.assertIn("今天是 2026-11-16（民國 115 年 11 月 16 日，星期一）", facts("今天星期幾？"))
        self.assertIn("民國 115 年 = 西元 2026 年", facts("民國115年是西元幾年"))
        self.assertIn("2027-01-01 是星期五", facts("2027年1月1日是星期幾"))
        self.assertIn("還有 39 天", facts("距離 12月25日 還有幾天"))
        self.assertIn("相差 93 天", facts("2026-11-16 到 2027/2/17 差幾天"))
        self.assertIn("2027-02-24", facts("100天後是幾號"))


class TestGatewayTools(unittest.TestCase):
    def test_grounded_and_checked(self):
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp)
            lh, seen = local_handler([{"role": "assistant", "content": "答案是 2048。"},
                                      {"role": "assistant", "content": "答案是 1024。"}])
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                           json={"model": "jiezi-local", "messages": [{"role": "user", "content": "2^10 是多少"}]}).json()
            self.assertTrue(any("2^10 = 1024" in m["content"] for m in seen[0]["messages"] if m["role"] == "system"))
            self.assertEqual(r["jiezi"]["tier"], 1)                    # 2048 被查核抓到，重答 / caught and retried
            self.assertIn("【計算】", r["choices"][0]["message"]["content"])



class FakeSolar:
    def __init__(self, y, m, d):
        self.y, self.m, self.d = y, m, d

    @classmethod
    def fromYmd(cls, y, m, d):
        return cls(y, m, d)

    def toYmd(self):
        return f"{self.y:04d}-{self.m:02d}-{self.d:02d}"

    def getYear(self):
        return self.y

    def next(self, n):
        from datetime import date, timedelta
        x = date(self.y, self.m, self.d) + timedelta(days=n)
        return FakeSolar(x.year, x.month, x.day)

    def getLunar(self):
        return FakeLunar(self.y, 9, 27)


class FakeLunar:
    def __init__(self, y, m, d):
        self.y, self.m, self.d = y, m, d

    @classmethod
    def fromYmd(cls, y, m, d):
        return cls(y, m, d)

    def getSolar(self):  # 假的對應：農曆 m/d → 國曆 m+1/d / fake mapping
        return FakeSolar(self.y, min(abs(self.m) + 1, 12), self.d)

    def getYearInGanZhi(self):
        return "丙午"

    def getYearShengXiao(self):
        return "马"  # 簡體，應轉成正體 / Simplified on purpose

    def getMonthInChinese(self):
        return "九"

    def getDayInChinese(self):
        return "廿七"

    def getJieQiTable(self):
        return {"冬至": FakeSolar(self.y, 12, 22), "清明": FakeSolar(self.y, 4, 5)}


class FakeLib:
    Solar, Lunar = FakeSolar, FakeLunar


class TestLunar(unittest.TestCase):
    def test_conversions_with_fake_library(self):
        f = lambda q: T.lunar_facts(q, NOW, lib=FakeLib)  # noqa: E731
        self.assertEqual(f("今天農曆幾號？"), ["國曆 2026-11-16 是農曆丙午年（馬年）九月廿七"])  # 簡轉繁 / converted
        self.assertIn("農曆 2026 年8 月 15 日是國曆 2026-09-15", f("農曆八月十五是國曆幾號"))
        self.assertIn("2027 年中秋（農曆 8 月 15 日）是國曆 2027-09-15", f("2027年中秋節是哪天"))
        self.assertIn("2026 年冬至是國曆 2026-12-22", f("今年冬至是哪一天"))
        self.assertIn("2026 年農曆除夕是國曆 2027-01-31", f("除夕是哪天"))  # 隔年春節前一天 / day before next 春節
        self.assertEqual(f("我今天好累"), [])

    def test_missing_library_is_explained(self):
        from unittest import mock
        with mock.patch.object(T, "_lunar", return_value=None):
            self.assertIn("lunar-python", T.lunar_facts("中秋節是哪天", NOW)[0])


if __name__ == "__main__":
    unittest.main()

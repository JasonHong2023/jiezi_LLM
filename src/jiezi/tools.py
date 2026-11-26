"""內建工具：計算、單位換算、日期與國定假日（add-tools、add-holiday-tool）。由程式算好再交給模型。
Built-in tools: arithmetic, unit conversion, dates and statutory holidays. Computed by code, not by the small model.

計算、換算、日期只用標準函式庫且用語法樹白名單求值，不使用 eval；國定假日在有法規資料庫時才延遲載入
lunar-python。 / Core math uses only the standard library; holidays load lunar-python lazily when a law DB is present."""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 避免在純工具測試裡拉進法規／曆法模組 / keep the pure tool path dependency-light
    from .laws import Laws

FW = str.maketrans("０１２３４５６７８９．，＋－＊／（）＝％", "0123456789.,+-*/()=%")
MAX_EXP, MAX_DIGITS = 200, 60
WEEKDAY = "一二三四五六日"


CN_OPS = [("乘以", "*"), ("除以", "/"), ("加上", "+"), ("減去", "-"), ("乘", "*"), ("加", "+"), ("減", "-")]


def _norm(text: str) -> str:
    t = (text or "").translate(FW).replace("×", "*").replace("÷", "/").replace("^", "**").replace("√", "根號")
    for w, op in CN_OPS:  # 只換夾在兩個數字之間的中文運算詞 / only between two numbers
        t = re.sub(rf"(\d)\s*{w}\s*(?=\d)", rf"\1{op}", t)
    return t


# ── 計算 / Arithmetic ──
class CalcError(ValueError):
    pass


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sqrt" and len(node.args) == 1:
        v = _eval(node.args[0])
        if v < 0:
            raise CalcError("負數不能開平方根 / square root of a negative number")
        r = math.isqrt(v.numerator) if v.denominator == 1 else None
        if r is not None and r * r == v.numerator:
            return Fraction(r)
        return Fraction(math.sqrt(v))
    if isinstance(node, ast.BinOp):
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            if b == 0:
                raise CalcError("除數不能是 0 / division by zero")
            if isinstance(node.op, ast.Div):
                return a / b
            return Fraction(a // b) if isinstance(node.op, ast.FloorDiv) else a % b
        if isinstance(node.op, ast.Pow):
            if b.denominator != 1 or abs(b) > MAX_EXP or (abs(a) > 10 ** 6 and b > 20):
                raise CalcError("次方太大或不是整數 / exponent too large or not an integer")
            return a ** int(b)
    raise CalcError("只支援加減乘除、次方、括號、開根號 / only + - * / ** ( ) and sqrt")


def evaluate(expr: str) -> Fraction:
    src = _norm(expr).strip().rstrip("=").strip()
    src = re.sub(r"根號\s*\(([^()]+)\)|根號\s*(\d+(?:\.\d+)?)", lambda m: f"sqrt({m.group(1) or m.group(2)})", src)
    src = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", src)
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as exc:
        raise CalcError(f"看不懂的算式 / cannot parse: {expr}") from exc
    v = _eval(tree)
    if len(str(abs(v.numerator))) > MAX_DIGITS:
        raise CalcError("結果太大 / result too large")
    return v


def fmt(v: Fraction) -> str:
    if v.denominator == 1:
        return f"{v.numerator:,}" if abs(v.numerator) >= 10000 else str(v.numerator)
    dec = f"{float(v):.10g}"
    if v.denominator <= 1000 and abs(v.numerator) < 10 ** 9:
        return f"{dec}（= {v.numerator}/{v.denominator}）"
    return dec


EXPR = re.compile(r"(?:根號\s*)?[(\d](?:[\d\s.()+\-*/%根號]*[\d)%])?(?:\s*=\s*-?\d+(?:\.\d+)?)?")
CALC_CUE = re.compile(r"多少|等於|=|算|幾|結果|答案|[?？]")
_DATE_PARTS = re.compile(r"^\s*(\d{2,4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})\s*$")


class _DateLike:
    """月 1–12、日 1–31 才算日期（「38-8-43」是算式）。 / Only plausible month/day counts as a date."""

    @staticmethod
    def match(s: str) -> bool:
        m = _DATE_PARTS.match(s)
        return bool(m) and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31


DATE_LIKE = _DateLike()
_NUMBERED = set("條項款目號章節編頁點樓巷弄段")   # 「51-1」後面接這些字是編號 / numbering suffixes


def calculations(text: str) -> list[str]:
    t = _norm(text)
    out = []
    cue = bool(CALC_CUE.search(t))
    for m in EXPR.finditer(t):
        raw = m.group(0).strip()
        before, after = t[m.start() - 1:m.start()], t[m.end():m.end() + 1]
        if (before and before.isascii() and before.isalpha()) or (after and after.isascii() and after.isalpha()):
            continue  # 「Qwen3.5-2B」這類名稱 / names like Qwen3.5-2B
        claim = None
        if "=" in raw:
            raw, claim = (x.strip() for x in raw.split("=", 1))
        ops = len(re.findall(r"(?<=[\d)%])\s*[+\-*/]|根號", raw))
        if not ops or DATE_LIKE.match(raw) or len(re.findall(r"\d+(?:\.\d+)?", raw)) < (1 if "根號" in raw else 2):
            continue
        dashes_only = not re.search(r"[+*/%]|根號", raw)
        if dashes_only and re.search(r"(?<![\d.])0\d", raw):
            continue  # 0912-345-678、02-2345-6789：電話 / phone numbers
        if not cue and dashes_only:
            continue  # 只有減號又沒有問計算：多半是電話、編號 / dashes only, no question: phone numbers, codes
        if dashes_only and (t[:m.start()].rstrip().endswith("第") or t[m.end():].lstrip()[:1] in _NUMBERED):
            continue  # 「第51-1條」「3-2號」：條號、門牌 / article and address numbers
        try:
            v = evaluate(raw)
        except CalcError as exc:
            if cue:
                out.append(f"{raw}：無法計算（{exc}）")
            continue
        line = f"{raw.replace('**', '^')} = {fmt(v)}"
        if claim is not None:
            try:
                ok = Fraction(claim) == v
            except ValueError:
                ok = None
            if ok is False:
                line += f"（題目寫的 {claim} 不正確）"
        out.append(line)
    return list(dict.fromkeys(out))[:5]


# ── 單位換算 / Unit conversion ──
@dataclass(frozen=True)
class Unit:
    dim: str
    factor: float  # 換成基本單位的倍數 / multiplier to the base unit
    name: str


_UNITS: dict[str, Unit] = {}


def _add(dim: str, factor: float, name: str, *aliases: str) -> None:
    for a in (name, *aliases):
        _UNITS[a] = Unit(dim, factor, name)


for args in [
    ("length", 1000, "公里", "千米", "km"), ("length", 1, "公尺", "米", "m"), ("length", 0.01, "公分", "釐米", "cm"),
    ("length", 0.001, "毫米", "公釐", "mm"), ("length", 1609.344, "英里", "哩", "mile", "miles"),
    ("length", 0.9144, "碼", "yard", "yards"), ("length", 0.3048, "英尺", "呎", "ft", "feet", "foot"),
    ("length", 0.0254, "英吋", "吋", "inch", "inches"), ("length", 1852, "海里", "浬"), ("length", 10 / 33, "台尺"),
    ("mass", 1, "公斤", "千克", "kg"), ("mass", 0.001, "公克", "克", "g"), ("mass", 1e-6, "毫克", "mg"),
    ("mass", 0.6, "台斤", "斤"), ("mass", 0.0375, "台兩", "兩"), ("mass", 1000, "公噸", "噸"),
    ("mass", 0.45359237, "磅", "lb", "lbs"), ("mass", 0.028349523125, "盎司", "oz"),
    ("area", 1, "平方公尺", "平方米", "㎡", "m2"), ("area", 1e6, "平方公里", "km2"), ("area", 1e4, "公頃"),
    ("area", 400 / 121, "坪"), ("area", 9699.17, "甲"), ("area", 4046.8564224, "英畝"),
    ("area", 1e-4, "平方公分", "cm2"),
    ("volume", 1, "公升", "升", "L"), ("volume", 0.001, "毫升", "c.c.", "cc", "ml", "mL"),
    ("volume", 3.785411784, "加侖", "gallon"), ("volume", 1000, "立方公尺", "立方米", "m3"),
    ("speed", 1 / 3.6, "公里/小時", "公里每小時", "km/h", "kmh"), ("speed", 1, "公尺/秒", "公尺每秒", "m/s"),
    ("speed", 0.44704, "英里/小時", "mph"), ("speed", 1852 / 3600, "節", "knot", "knots"),
]:
    _add(*args)
TEMP_NAME = {"C": "攝氏", "F": "華氏", "K": "克耳文"}
TEMPS = {"攝氏": "C", "°C": "C", "℃": "C", "華氏": "F", "°F": "F", "℉": "F", "克耳文": "K", "凱氏": "K"}
_ALIASES = sorted(list(_UNITS) + list(TEMPS), key=len, reverse=True)
_ALIAS_RE = re.compile("|".join((re.escape(a) + r"(?![A-Za-z])") if a.isascii() else re.escape(a) for a in _ALIASES))
CONVERT_CUE = re.compile(r"換算|換成|轉成|轉換|等於|是多少|多少|幾|=|\bin\b|\bto\b")


def _to_c(v: float, u: str) -> float:
    return v if u == "C" else (v - 32) * 5 / 9 if u == "F" else v - 273.15


def _from_c(c: float, u: str) -> float:
    return c if u == "C" else c * 9 / 5 + 32 if u == "F" else c + 273.15


def _num(v: float) -> str:
    return f"{v:,.6g}" if abs(v) >= 1e4 else f"{v:.6g}"


def conversions(text: str) -> list[str]:
    t = _norm(text)
    if not CONVERT_CUE.search(t):
        return []
    hits = [(m.start(), m.end(), m.group(0)) for m in _ALIAS_RE.finditer(t)]
    out = []
    for i, (s, e, a) in enumerate(hits):
        nm = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:度)?\s*$", t[:s]) if a in TEMPS else None
        if a in TEMPS:  # 「攝氏 30 度」：數字在單位後 / temperature: number after the name
            nm2 = re.match(r"\s*(-?\d+(?:\.\d+)?)", t[e:])
            val = float(nm2.group(1)) if nm2 else (float(nm.group(1)) if nm else None)
        else:
            nm = re.search(r"(-?\d+(?:\.\d+)?)\s*$", t[:s])
            val = float(nm.group(1)) if nm else None
        if val is None:
            continue
        for _s2, _e2, b in hits[i + 1:]:
            if a in TEMPS and b in TEMPS and TEMPS[a] != TEMPS[b]:
                r = _from_c(_to_c(val, TEMPS[a]), TEMPS[b])
                out.append(f"{TEMP_NAME[TEMPS[a]]} {_num(val)} 度 = {TEMP_NAME[TEMPS[b]]} {_num(r)} 度")
                break
            if a in _UNITS and b in _UNITS and _UNITS[a].dim == _UNITS[b].dim and _UNITS[a].name != _UNITS[b].name:
                r = val * _UNITS[a].factor / _UNITS[b].factor
                out.append(f"{_num(val)} {_UNITS[a].name} = {_num(r)} {_UNITS[b].name}")
                break
    return list(dict.fromkeys(out))[:3]


# ── 日期 / Dates ──
DATE_RE = re.compile(r"(?:(民國|西元)\s*)?(\d{2,4})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})\s*(?:日|號)?")
MD_RE = re.compile(r"(?<![\d年/.-])(\d{1,2})\s*月\s*(\d{1,2})\s*(?:日|號)")
TODAY = re.compile(r"(今天|今日)(是)?(幾月幾號|幾月幾日|幾號|星期幾|禮拜幾|週幾|日期|什麼日子)|現在幾點|今年是民國幾年|今年是西元幾年")
WEEKDAY_Q = re.compile(r"星期幾|禮拜幾|週幾")
DAYS_Q = re.compile(r"幾天|多少天")
OFFSET = re.compile(r"(\d+)\s*天(後|以後|之後|前|以前|之前)")
ROC = re.compile(r"民國\s*(\d{1,3})\s*年")
AD_TO_ROC = re.compile(r"(?:西元\s*)?(\d{4})\s*年.{0,6}民國")


def _date(m: re.Match) -> date | None:
    era, y, mo, d = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))
    if era == "民國" or (y < 1000 and era != "西元"):
        y += 1911
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _desc(d: date) -> str:
    return f"{d.isoformat()}（民國 {d.year - 1911} 年 {d.month} 月 {d.day} 日，星期{WEEKDAY[d.weekday()]}）"


def date_facts(text: str, now: datetime | None = None) -> list[str]:
    t = _norm(text)
    now = now or datetime.now()
    today = now.date()
    out = []
    if TODAY.search(t):
        out.append(f"今天是 {_desc(today)}；現在時間 {now:%H:%M}")
    for m in ROC.finditer(t):
        y = int(m.group(1))
        out.append(f"民國 {y} 年 = 西元 {y + 1911} 年")
    for m in AD_TO_ROC.finditer(t):
        y = int(m.group(1))
        if y > 1911:
            out.append(f"西元 {y} 年 = 民國 {y - 1911} 年")
    dates = [d for d in (_date(m) for m in DATE_RE.finditer(t)) if d]
    for m in MD_RE.finditer(t):
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
        if d < today and re.search(r"還有|距離|離", t):
            d = d.replace(year=today.year + 1)
        dates.append(d)
    if dates and WEEKDAY_Q.search(t):
        out += [f"{d.isoformat()} 是星期{WEEKDAY[d.weekday()]}" for d in dates]
    if DAYS_Q.search(t) and dates:
        if len(dates) >= 2:
            a, b = dates[0], dates[1]
            out.append(f"{a.isoformat()} 到 {b.isoformat()} 相差 {abs((b - a).days)} 天")
        else:
            diff = (dates[0] - today).days
            out.append(f"今天（{today.isoformat()}）到 {dates[0].isoformat()} " +
                       (f"還有 {diff} 天" if diff >= 0 else f"已經過了 {-diff} 天"))
    for m in OFFSET.finditer(t):
        n = int(m.group(1))
        base = dates[0] if dates else today
        d = base + timedelta(days=n if "後" in m.group(2) else -n)
        out.append(f"{'今天' if not dates else base.isoformat()}{m.group(0)}是 {_desc(d)}")
    return list(dict.fromkeys(out))[:5]


# ── 對話 / Chat ──
def grounding(text: str, now: datetime | None = None, laws: Laws | None = None) -> tuple[str, list[dict], bool, str] | None:
    """回傳 (system 訊息, 來源, 可訓練, 附錄)；沒有可算的就回傳 None。 / Computed facts for the chat, or None."""
    text = (text or "")[:2000]
    calc, conv, dates = calculations(text), conversions(text), date_facts(text, now)
    lunar = lunar_facts(text, now)
    lines = [*calc, *conv, *dates, *lunar]

    holiday = None
    if laws is not None:
        from .holidays import grounding as holidays_grounding  # noqa: PLC0415 - 有法規 DB 才載入
        holiday = holidays_grounding(laws, text, now.date() if now else None)
    if not lines and not holiday:
        return None

    sources = ([{"source": "tools", "tool": "calculator"}] if calc else []) + \
              ([{"source": "tools", "tool": "units"}] if conv else []) + \
              ([{"source": "tools", "tool": "dates"}] if dates else []) + \
              ([{"source": "tools", "tool": "lunar"}] if lunar else [])
    trainable = True
    if lines:
        body = "\n".join(f"- {x}" for x in lines)
        content = ("以下是程式計算的結果，是正確的。回答時直接採用這些數字，不要自己重算或改動；"
                   "不必另外說明計算方式，系統會在回答後附上計算過程。\n\n" + body)
        appendix = "\n\n---\n【計算】\n" + body
    else:
        content, appendix = "", ""

    if holiday:
        hc, hs, ht, ha = holiday
        sources = sources + hs + [{"source": "tools", "tool": "holidays"}]
        trainable = trainable and ht
        content = (content + "\n\n" + hc).lstrip("\n")
        appendix += ha

    return content, sources, trainable, appendix


# ── 農曆（lunar-python，MIT；使用者 2026-11-16 同意；沒裝時略過）──
# Lunar calendar via lunar-python (MIT; installed by the user); skipped when absent.
LUNAR_CUE = re.compile(r"農曆|陰曆|舊曆|農民曆|生肖|干支|節氣|春節|過年|元宵|端午|七夕|中元|中秋|重陽|除夕|清明|冬至|"
                       r"立春|夏至|驚蟄|穀雨|立秋|秋分|春分|大寒|小寒|立夏|小滿|芒種|小暑|大暑|處暑|白露|寒露|霜降|立冬|"
                       r"(?:\d{4}|今|明|去)\s*年\s*(?:的)?(?:雨水|小雪|大雪)")
FESTIVALS = {"春節": (1, 1), "過年": (1, 1), "元宵": (1, 15), "端午": (5, 5), "七夕": (7, 7), "中元": (7, 15),
             "中秋": (8, 15), "重陽": (9, 9)}
JIEQI = ("立春", "雨水", "驚蟄", "春分", "清明", "穀雨", "立夏", "小滿", "芒種", "夏至", "小暑", "大暑", "立秋", "處暑",
         "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至", "小寒", "大寒")
# lunar-python 的節氣表對跨年的那幾個用拼音鍵（實測 1.4.9）/ the table uses pinyin keys for the wrap-around terms
JIEQI_KEYS = {"DA_XUE": "大雪", "DONG_ZHI": "冬至", "XIAO_HAN": "小寒", "DA_HAN": "大寒", "LI_CHUN": "立春",
              "YU_SHUI": "雨水", "JING_ZHE": "驚蟄",
              "惊蛰": "驚蟄", "谷雨": "穀雨", "小满": "小滿", "芒种": "芒種", "处暑": "處暑"}
LMONTH = {"正": 1, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
          "十一": 11, "冬": 11, "十二": 12, "臘": 12}
LUNAR_DATE = re.compile(r"農曆\s*(?:(\d{4})\s*年)?\s*(閏)?\s*(正|十一|十二|冬|臘|[一二三四五六七八九十]|\d{1,2})\s*月\s*"
                        r"(初[一二三四五六七八九十]|[二三]十[一二三四五六七八九]?|十[一二三四五六七八九]?|廿[一二三四五六七八九]?|\d{1,2})\s*(?:日|號)?")
YEAR_RE = re.compile(r"(?:西元\s*)?(\d{4})\s*年|民國\s*(\d{1,3})\s*年")


def _lunar():
    try:
        import lunar_python  # noqa: PLC0415 - 選用相依 / optional dependency
        return lunar_python
    except ImportError:
        return None


def _lday(s: str) -> int:
    if s.isdigit():
        return int(s)
    s = s.replace("初", "").replace("廿", "二十")
    return _cn_small(s)


def _cn_small(s: str) -> int:
    d = {c: i for i, c in enumerate("零一二三四五六七八九")}
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        return (d.get(a, 1) if a else 1) * 10 + (d.get(b, 0) if b else 0)
    return d.get(s, 0)


def _ldesc(lunar) -> str:
    from .textconv import to_traditional
    return to_traditional(f"農曆{lunar.getYearInGanZhi()}年（{lunar.getYearShengXiao()}年）"
                          f"{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}")


def lunar_facts(text: str, now: datetime | None = None, lib=None) -> list[str]:
    t = _norm(text)
    if not LUNAR_CUE.search(t):
        return []
    lib = lib or _lunar()
    if lib is None:
        return ["（農曆換算需要 lunar-python，尚未安裝：uv add lunar-python==1.4.9）"]
    now = now or datetime.now()
    today = now.date()
    ym = YEAR_RE.search(t)
    year = (int(ym.group(1)) if ym.group(1) else int(ym.group(2)) + 1911) if ym else today.year
    out = []
    # 國曆日期 → 農曆 / solar → lunar
    lunar_spans = [m.span() for m in LUNAR_DATE.finditer(t)]  # 「農曆 2026 年 1 月 1 日」不當國曆 / not a solar date
    solar_dates = [d for d in (_date(m) for m in DATE_RE.finditer(t)
                               if not any(a < m.end() and m.start() < b for a, b in lunar_spans)) if d]
    if TODAY.search(t) or re.search(r"今天.{0,4}農曆|農曆.{0,4}今天", t):
        solar_dates.append(today)
    for d in solar_dates:
        out.append(f"國曆 {d.isoformat()} 是{_ldesc(lib.Solar.fromYmd(d.year, d.month, d.day).getLunar())}")
    # 農曆日期 → 國曆 / lunar → solar
    for m in LUNAR_DATE.finditer(t):
        y = int(m.group(1)) if m.group(1) else year
        mo = int(m.group(3)) if m.group(3).isdigit() else LMONTH[m.group(3)]
        day = _lday(m.group(4))
        s = lib.Lunar.fromYmd(y, -mo if m.group(2) else mo, day).getSolar()
        out.append(f"農曆 {y} 年{'閏' if m.group(2) else ''}{mo} 月 {day} 日是國曆 {s.toYmd()}")
    # 節日 / festivals
    for name, (mo, day) in FESTIVALS.items():
        if name in t:
            s = lib.Lunar.fromYmd(year, mo, day).getSolar()
            out.append(f"{year} 年{name}（農曆 {mo} 月 {day} 日）是國曆 {s.toYmd()}")
    if "除夕" in t:
        # 「2026 年除夕」有兩種意思：國曆 2026 年裡的那一天（春節前一天），或農曆 2026 年的最後一天；指定年份時兩個都給
        # "New Year's Eve 2026" is ambiguous (within solar 2026, or the end of lunar 2026); give both when a year is named
        s = lib.Lunar.fromYmd(year + 1, 1, 1).getSolar().next(-1)
        if ym:
            first = lib.Lunar.fromYmd(year, 1, 1).getSolar().next(-1)
            out.append(f"國曆 {year} 年裡的除夕（{year} 年春節前一天）是 {first.toYmd()}；"
                       f"農曆 {year} 年的除夕（年底）是國曆 {s.toYmd()}")
        else:
            out.append(f"{year} 年農曆除夕是國曆 {s.toYmd()}")
    # 節氣 / solar terms
    from .textconv import to_traditional
    for name in JIEQI:
        if name in t:
            table = lib.Lunar.fromYmd(year, 6, 1).getJieQiTable()
            hit = next((v for k, v in table.items()
                        if JIEQI_KEYS.get(k, to_traditional(k)) == name and v.getYear() == year), None)
            if hit:
                out.append(f"{year} 年{name}是國曆 {hit.toYmd()}")
    # 生肖 / zodiac
    if "生肖" in t and not solar_dates:
        lunar = lib.Lunar.fromYmd(year, 6, 1)
        out.append(to_traditional(f"{year} 年（農曆{lunar.getYearInGanZhi()}年）的生肖是{lunar.getYearShengXiao()}"))
    return list(dict.fromkeys(out))[:5]

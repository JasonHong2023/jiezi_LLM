"""以本機法規資料庫計算台灣國定假日（add-holiday-tool）。

法規條文是唯一資料來源：日期、放假清單與補假規則都從《紀念日及節日實施條例》
第 3、4、5、6、8 條解析；lunar-python 只做國曆／農曆與節氣換算。補假是往例推算，
不是行政院公告，輸出一律註明「以公告為準」。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

from lunar_python import Lunar, LunarMonth, Solar

from .errors import JieziError
from .laws import Laws, _cn_int, db_path

LAW_NAME = "紀念日及節日實施條例"
ARTICLES = (3, 4, 5, 6, 8)
WEEKDAY = "星期"
HOLIDAY_CUE = re.compile(r"國定假日|放假|連假|補假|假日|紀念日|節日|holiday", re.I)
YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
RELATIVE = {"今年": 0, "明年": 1, "後年": 2, "去年": -1, "前年": -2}
CN_NUM = re.compile(r"[0-9０-９零〇一二兩三四五六七八九十百]+")
ENTRY = re.compile(r"^[（(]?\s*[一二三四五六七八九十]+\s*[）)]?[、.]?\s*([^：]+)：\s*([^。]+)。?$")
ITEM = re.compile(r"^[一二三四五六七八九十]+、([^：]+)：(.+)$")
SOLAR_DATE = re.compile(rf"^({CN_NUM.pattern})月({CN_NUM.pattern})日$")
LUNAR_DATE = re.compile(rf"^農曆({CN_NUM.pattern})月({CN_NUM.pattern})日$")
JIEQI_DATE = re.compile(r"^定於(.+日)$")


def _solar(s: Solar | str) -> date:
    """lunar-python 的 Solar 或 YYYY-MM-DD 字串轉 datetime.date。"""
    return date.fromisoformat(s.toYmd() if isinstance(s, Solar) else str(s))


def _jieqi(year: int, name: str) -> date:
    table = Lunar.fromYmd(year, 4, 1).getJieQiTable()
    if name not in table:
        raise JieziError(f"節氣 {name} 不在 lunar-python 表中")
    return _solar(table[name])


def _date_from_spec(name: str, spec: str, year: int) -> tuple[date, str]:
    """回傳 (國曆日期, 農曆說明)。spec 来自法規條文，不硬編日期。"""
    spec = spec.strip()
    m = SOLAR_DATE.match(spec)
    if m:
        return date(year, _cn_int(m.group(1)), _cn_int(m.group(2))), ""
    m = LUNAR_DATE.match(spec)
    if m:
        lm, ld = _cn_int(m.group(1)), _cn_int(m.group(2))
        return _solar(Lunar.fromYmd(year, lm, ld).getSolar()), f"農曆{m.group(1)}月{m.group(2)}日"
    if "末日" in spec and "農曆" in spec:
        # 除夕：所求西元年 y 的除夕，是農曆 y-1 年十二月的最後一天。
        count = LunarMonth.fromYm(year - 1, 12).getDayCount()
        lunar = Lunar.fromYmd(year - 1, 12, count)
        return _solar(lunar.getSolar()), f"農曆十二月{_cn_text(count)}日"
    m = JIEQI_DATE.match(spec)
    if m:
        term = m.group(1).removesuffix("日")
        return _jieqi(year, term), term
    raise JieziError(f"無法解析《{LAW_NAME}》的日期：{name}：{spec}")


def _cn_text(n: int) -> str:
    digits = "零一二三四五六七八九"
    if n < 10:
        return digits[n]
    if n < 20:
        return "十" + (digits[n % 10] if n % 10 else "")
    return digits[n // 10] + "十" + (digits[n % 10] if n % 10 else "")


def _parse_entries(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = ENTRY.match(line.strip())
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def _parse_items(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = ITEM.match(line.strip())
        if m:
            out[m.group(1).strip()] = m.group(2).strip()
    return out


def _names(key: str) -> list[str]:
    return [n.strip() for n in re.split(r"[、及]", key) if n.strip()]


def _weekday(d: date) -> str:
    return WEEKDAY + "日一二三四五六"[d.isoweekday() % 7]


def _neighbor_workday(start: date, busy: set[date], forward: bool, limit: int = 30) -> date:
    step = timedelta(days=1 if forward else -1)
    d = start + step
    for _ in range(limit):
        if d.weekday() < 5 and d not in busy:
            return d
        d += step
    raise JieziError("找不到可補假的上班日")


def _load(lw: Laws) -> dict[int, str] | None:
    lid = lw.by_name.get(LAW_NAME)
    if lid is None:
        return None
    arts: dict[int, str] = {}
    for num in ARTICLES:
        art = lw.article(lid, num)
        if art is None or not art.get("text"):
            return None
        arts[num] = art["text"]
    return arts


def question_year(text: str, today: date | None = None) -> int | None:
    """從問題取年份；只認四位西元年或今年／明年等。"""
    text = text or ""
    m = YEAR_RE.search(text)
    if m:
        return int(m.group(1))
    base = today or datetime.now().astimezone().date()
    for word, delta in RELATIVE.items():
        if word in text:
            return base.year + delta
    return None


def wants_holidays(text: str) -> bool:
    return bool(HOLIDAY_CUE.search(text or ""))


def holidays(year: int, lw: Laws | None = None, root: Path | None = None) -> dict | None:
    """計算 year 年放假日期。讀不到條文或解析失敗時回 None（降級照舊回答）。"""
    if lw is None:
        lw = Laws(db_path(root or Path(__file__).resolve().parents[2]))
    arts = _load(lw)
    if arts is None:
        return None
    try:
        dates = {**_parse_entries(arts[3]), **_parse_entries(arts[5])}
        items = _parse_items(arts[6])
        if not dates or not items:
            return None
        spring_item = next((v for k, v in items.items() if "除夕" in k and "春節" in k), None)
        one_day_item = next((v for k, v in items.items() if "均放假一日" in v), None)
        if not spring_item or not one_day_item:
            return None
        if "逢例假日" not in arts[8] or "補假" not in arts[8]:
            return None

        base: dict[date, list[str]] = {}
        spring_dates: set[date] = set()
        lunar_notes: dict[date, str] = {}
        article_of: dict[date, set[str]] = {}

        # 第 4 條：放假的紀念日（一日）。
        memorial_names = [m.group(1).strip() for m in
                          (re.match(r"^[一二三四五六七八九十]+、([^。]+)。$", line.strip())
                           for line in arts[4].splitlines()) if m]
        for name in memorial_names:
            if name not in dates:
                return None
            d, lunar = _date_from_spec(name, dates[name], year)
            base.setdefault(d, []).append(name)
            article_of.setdefault(d, set()).add("第 4 條")
            if lunar:
                lunar_notes[d] = lunar

        # 第 6 條第一項：除夕及春節，自除夕前一日開始的連續 N 日。
        count_m = re.search(rf"放假({CN_NUM.pattern})日", spring_item)
        jan_m = re.search(rf"至翌年一月({CN_NUM.pattern})日", spring_item)
        if not count_m or not jan_m or "除夕" not in dates:
            return None
        count, jan_day = _cn_int(count_m.group(1)), _cn_int(jan_m.group(1))
        eve, _ = _date_from_spec("除夕", dates["除夕"], year)
        start = eve - timedelta(days=1)
        end = _solar(Lunar.fromYmd(year, 1, jan_day).getSolar())
        if (end - start).days + 1 != count:
            return None
        for i in range(count):
            d = start + timedelta(days=i)
            label = "除夕前一日" if i == 0 else (
                "除夕" if d == eve else "春節")
            base.setdefault(d, []).append(label)
            spring_dates.add(d)
            article_of.setdefault(d, set()).add("第 6 條")

        # 第 6 條第二項：兒童節、清明節、勞動節、端午節、教師節、中秋節。
        one_day_names = _names(next((k for k, v in items.items() if "均放假一日" in v), ""))
        if not one_day_names:
            return None
        for name in one_day_names:
            if name not in dates:
                return None
            d, lunar = _date_from_spec(name, dates[name], year)
            base.setdefault(d, []).append(name)
            article_of.setdefault(d, set()).add("第 6 條")
            if lunar:
                lunar_notes[d] = lunar

        # 第 6 條：兒童節與清明節同一日的特別規則。
        child = next((d for d, ns in base.items() if "兒童節" in ns), None)
        qing = next((d for d, ns in base.items() if "清明節" in ns), None)
        if child and qing and child == qing:
            extra = child + timedelta(days=1 if _solar(child).weekday() == 3 else -1)
            base.setdefault(extra, []).append("兒童節與清明節同一日之放假")
            article_of.setdefault(extra, set()).add("第 6 條")

        # 第 8 條：逢例假日補假。一般往例「六補前、日補後」；
        # 除夕及春節依人事總處 116 年公告往例，逢例假日往後補，且補假不可互撞。
        busy = set(base)
        makeups: dict[date, list[str]] = {}
        for d, names in list(base.items()):
            if d.weekday() not in (5, 6):
                continue
            forward = d.weekday() == 6 or d in spring_dates
            md = _neighbor_workday(d, busy, forward=forward)
            makeups.setdefault(md, []).append("、".join(names) + "補假（推算）")
            article_of.setdefault(md, set()).add("第 8 條")
            busy.add(md)

        # 隔年 1/1 逢星期六時，補假落在當年 12/31（人事總處 116 年公告往例）。
        next_new_year = date(year + 1, 1, 1)
        if next_new_year.weekday() == 5:
            md = _neighbor_workday(next_new_year, busy, forward=False)
            if md.year == year:
                makeups.setdefault(md, []).append(f"{year + 1}年開國紀念日補假（推算）")
                article_of.setdefault(md, set()).add("第 8 條")

        all_dates = sorted(set(base) | set(makeups))
        entries = []
        for d in all_dates:
            names = base.get(d, []) + makeups.get(d, [])
            entries.append({
                "date": d.isoformat(),
                "weekday": _weekday(d),
                "names": names,
                "name": "、".join(dict.fromkeys(names)),
                "lunar": lunar_notes.get(d, ""),
                "articles": sorted(article_of.get(d, set())),
                "estimated": d in makeups and d not in base,
            })

        lid = lw.by_name[LAW_NAME]
        law = lw.by_id(lw.article(lid, 3)["id"])
        sources = [{"source": "computed-holidays", "law": LAW_NAME, "year": year, "url": law["url"]}]
        return {
            "year": year,
            "law": LAW_NAME,
            "url": law["url"],
            "entries": entries,
            "sources": sources,
            "trainable": lw.meta.get("training_use") == "1",
            "data_date": lw.meta.get("data_date", ""),
        }
    except (JieziError, ValueError, KeyError, IndexError):
        return None


def render(result: dict) -> tuple[str, str]:
    """回傳 (給模型的計算內容, 回答後Attachment)。"""
    year = result["year"]
    lines = [f"【計算】依《{result['law']}》第 3、4、5、6、8 條計算 {year} 年台灣放假日（補假為推算，以公告為準）："]
    for e in result["entries"]:
        lunar = f"（{e['lunar']}）" if e["lunar"] else ""
        mark = "〔補假推算〕" if e["estimated"] else ""
        lines.append(f"- {e['date']}（{e['weekday']}）{e['name']}{lunar}{mark}〔{'、'.join(e['articles'])}〕")
    body = "\n".join(lines)
    notice = "補假日期依往例規則推算，僅供參考；以行政院人事行政總處當年度公告為準。"
    content = ("以下是依本機法規資料庫條文與內建曆法程式算好的事實。請用繁體中文直接依這份清單回答，"
               "不要自行增減日期或猜測未列的日子；回答後系統會附上【計算】與法規出處。\n\n" + body + "\n\n" + notice)
    appendix = ("\n\n---\n" + body + f"\n【法規出處】《{result['law']}》第 3、4、5、6、8 條：{result['url']}"
                f"（法規資料日期 {result['data_date']}）\n{notice}")
    return content, appendix


def grounding(lw: Laws, text: str, today: date | None = None) -> tuple[str, list[dict], bool, str] | None:
    """供 tools.grounding 呼叫：符合觸發條件才回與 laws.grounding 同形狀的結果。"""
    if not wants_holidays(text):
        return None
    year = question_year(text, today)
    if year is None:
        return None
    result = holidays(year, lw=lw)
    if result is None:
        return None
    content, appendix = render(result)
    return content, result["sources"], result["trainable"], appendix

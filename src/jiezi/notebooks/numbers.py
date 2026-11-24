"""文字裡的數值，中文數字與阿拉伯數字換成同一種寫法（add-notebooks 引用檢查用）。
Numeric values in text, with Chinese and Arabic numerals normalized to one form (used by the citation check).

2026-11-24 實測：出處檢查只比雙字詞，「病假一年最多 40 日 [1]」和原文「不得超過三十日」用字幾乎一樣，會通過。
現在句子裡的每個數值都要出現在被引用的段落裡；「三十日」和「30 日」、「五十萬元」和「50 萬元」、「兩點」和「2 點」
算同一個數。Live test: a wrong number passed the bigram check; now every number in a sentence must appear in the
cited passage, with 三十 = 30, 五十萬 = 50 萬 and 兩 = 2."""

from __future__ import annotations

import re

_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNIT = {"十": 10, "百": 100, "千": 1000}
_BIG = {"萬": 10_000, "億": 100_000_000}
_CN = "零〇一二兩三四五六七八九十百千萬億"
# 中文數字只在後面接量詞／單位，或前面是「第」時才算（避免「一般」「統一」「一律」）
# Chinese numerals count only before a unit or classifier, or after 第 (so 一般 or 統一 are not numbers)
_UNITS = ("個|年|月|日|天|元|塊|人|次|%|％|成|週|周|點|時|分|秒|歲|名|位|件|張|頁|條|段|號|樓|倍|項|種|家|間|台|臺|"
          "公里|公尺|公斤|度|期|屆|任|集|章|節|堂|班|輛|台|部|本|份|杯|碗|顆|隻|匹|頭|棵|間|坪|折")
_CN_RE = re.compile(rf"(?<=第)[{_CN}]+|[{_CN}]+(?=\s*(?:{_UNITS}))")
_AR_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(\s*[萬億])?")
_LIST = re.compile(r"^\s*(?:\d{1,2}[.、)）]|[-*•])\s*", re.M)
_MARK = re.compile(r"[\[［【]\s*\d{1,2}(?:\s*[,，、]\s*\d{1,2})*\s*[\]］】]")
_TIME = re.compile(r"\[\d{1,2}:\d{2}(?::\d{2})?\]")      # 逐字稿的時間標記 / transcript timestamps


def cn_to_int(s: str) -> int | None:
    """中文數字 → 整數；「二〇二六」逐位讀。 / Chinese numeral → int; 二〇二六 is read digit by digit."""
    if not s:
        return None
    if len(s) > 1 and all(c in _DIGIT for c in s):
        return int("".join(str(_DIGIT[c]) for c in s))
    total, section, num = 0, 0, 0
    for c in s:
        if c in _DIGIT:
            num = _DIGIT[c]
        elif c in _UNIT:
            section += (num or 1) * _UNIT[c]
            num = 0
        elif c in _BIG:
            total += (section + num or 1) * _BIG[c]
            section = num = 0
        else:
            return None
    return total + section + num


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def values(text: str, list_items: bool = False) -> set[str]:
    """文字裡的數值（字串，例如 {"30", "500000", "7.4"}）；引用編號、逐字稿時間不算。
    list_items=False 時，行首的清單編號（「1.」「2、」）也不算。
    Numeric values in text; citation markers, transcript timestamps and (by default) list numbering are ignored."""
    text = _TIME.sub(" ", _MARK.sub(" ", text or ""))
    if not list_items:
        text = _LIST.sub("", text)
    out = set()
    for m in _AR_RE.finditer(text):
        v = float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
        if m.group(3):
            v *= _BIG[m.group(3).strip()]
        out.add(_fmt(v))
    for m in _CN_RE.finditer(text):
        if text[:m.start()].rstrip()[-1:].isdigit():     # 「50 萬元」的「萬」已算在阿拉伯數字裡 / part of 50 萬
            continue
        v = cn_to_int(m.group(0))
        if v is not None:
            out.add(_fmt(v))
    return out

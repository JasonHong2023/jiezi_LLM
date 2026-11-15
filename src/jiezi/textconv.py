"""把模型輸出中的「純簡體字」換成繁體（使用者偏好繁體中文；監控 2026-11-15 發現 0.6B 把「禪」寫成「禅」）。
Replace Simplified-only characters in model output with Traditional ones (user preference; on 2026-11-15
monitoring caught the 0.6B writing 禅 for 禪).

只換 OpenCC 簡轉繁表中「候選不含自己」的字，取第一個候選；「后、台、干、表」等本身也是正體字的字不動，
所以不會把正確的正體字改錯。只用在本機模型的輸出，不用在辭典原文或 Claude 的回答。
Only characters whose OpenCC candidates exclude themselves are replaced (first candidate); characters that
are also Traditional (后, 台, 干, 表) are left alone. Applied to local model output only, never to dictionary text
or Claude's answers.

2026-11-15 修正：OpenCC 表會把正體字換成異體字（群→羣、峰→峯、床→牀）。現在只換「不在 Big5（cp950）裡」的字，
Big5 收的都是正體字形，所以只有真正的簡體字（双、湾、禅、内）會被換掉。
Fix: the OpenCC table also turned Traditional characters into variants (群→羣). Only characters outside Big5
(cp950) are replaced now; Big5 holds Traditional forms, so only true Simplified characters change."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_TABLE = Path(__file__).resolve().parent / "eval" / "data" / "STCharacters.txt"


def _in_big5(ch: str) -> bool:
    try:
        ch.encode("cp950")
        return True
    except UnicodeEncodeError:
        return False


@lru_cache(maxsize=1)
def _map() -> dict[int, str]:
    out = {}
    for line in _TABLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        k, v = line.split("\t", 1)
        cands = v.split()
        if len(k) == 1 and cands and k not in cands and not _in_big5(k):
            out[ord(k)] = cands[0]
    return out


def to_traditional(text: str | None) -> str | None:
    return text.translate(_map()) if text else text

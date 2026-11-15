"""摘要規則檢查（不需模型；add-verifiers design D6）。
Summary rule checks (no model needed; add-verifiers design D6).

- 字數：去除空白後 100–150 字。 / Length: 100–150 characters excluding whitespace.
- 含簡體字：OpenCC 簡轉繁表（`STCharacters.txt`，Apache-2.0，登記鍵 opencc-tscharacters）中，
  轉換候選不包含自己的字，才算「只屬於簡體」（例如「发→發 髮」）；「后→後 后」「台→臺 檯 颱 台」等也是正體字，不算。
  Simplified-only: in OpenCC's S→T table, a character whose candidates do not include itself
  (e.g. 发→發 髮); 后→後 后 or 台→臺 檯 颱 台 are also Traditional, so they are not flagged."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..eval.scoring import strip_thinking

VERSION = "summary-rules@1"
MIN_CHARS, MAX_CHARS = 100, 150
_TABLE = Path(__file__).resolve().parent.parent / "eval" / "data" / "STCharacters.txt"


@lru_cache(maxsize=1)
def simplified_only() -> frozenset[str]:
    out = set()
    for line in _TABLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        k, v = line.split("\t", 1)
        if len(k) == 1 and k not in v.split():
            out.add(k)
    return frozenset(out)


def char_count(text: str) -> int:
    return sum(1 for c in text if not c.isspace())


def verify(item: dict, response: str) -> dict:
    """回傳兩項規則的結果；score 為兩項都通過時 1，否則 0（評審分數另計，不合併）。
    Return both rule results; score is 1 when both pass, else 0 (judge scores are separate, never merged)."""
    text = strip_thinking(response)
    n = char_count(text)
    found = sorted({c for c in text if c in simplified_only()})
    length_ok = MIN_CHARS <= n <= MAX_CHARS
    details = {"chars": n, "length_ok": length_ok, "simplified_chars": found, "traditional_ok": not found}
    if not text:
        return {"status": "unparsed", "score": 0, "details": details, "verifier": VERSION}
    ok = length_ok and not found
    return {"status": "correct" if ok else "wrong", "score": int(ok), "details": details, "verifier": VERSION}

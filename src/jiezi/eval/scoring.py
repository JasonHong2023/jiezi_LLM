"""評分（規格 eval：Scoring；design D7）。
Scoring (spec eval: Scoring; design D7).

- 選擇題：取出 A–D。 / Multiple choice: extract A–D.
- Chinese SimpleQA：近似比對，**非官方評分**（官方用 LLM 評審，留給 add-verifiers）。
  Chinese SimpleQA: approximate matching, **not the official scorer** (an LLM judge, left to add-verifiers).
- 程式、工具、摘要：pending_verifier。 / Code, tools, summaries: pending_verifier."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_THINK = re.compile(r"<think>.*?</think>", re.S)
_ANSWER_TAG = re.compile(r"答案\s*(?:是|為|为)?\s*[:：]?\s*[\(（\[【]?\s*([A-D])(?![A-Za-z])")
_STANDALONE = re.compile(r"(?<![A-Za-z])([A-D])(?![A-Za-z])")
_PUNCT_CATEGORIES = ("P", "S", "Z")


def strip_thinking(text: str) -> str:
    return _THINK.sub("", text or "").strip()


def extract_choice(text: str) -> str | None:
    t = unicodedata.normalize("NFKC", strip_thinking(text))
    m = _ANSWER_TAG.search(t) or _STANDALONE.search(t)
    return m.group(1) if m else None


@lru_cache(maxsize=1)
def _t2s() -> dict[str, str]:
    """OpenCC 繁轉簡單字表（Apache-2.0，登記鍵 opencc-tscharacters）；多個候選取第一個。
    OpenCC Traditional→Simplified character table (Apache-2.0); the first candidate wins."""
    table = {}
    path = Path(__file__).with_name("data") / "TSCharacters.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        k, v = line.split("\t", 1)
        if len(k) == 1 and v.split():
            table[k] = v.split()[0]
    return table


def normalize(text: str) -> str:
    """全半形統一、轉小寫、繁轉簡、去除標點與空白。 / Unify width, lowercase, Traditional→Simplified, drop punctuation and spaces."""
    t = unicodedata.normalize("NFKC", text).lower()
    table = _t2s()
    t = "".join(table.get(c, c) for c in t)
    return "".join(c for c in t if not unicodedata.category(c).startswith(_PUNCT_CATEGORIES))


def score(item: dict, content: str) -> dict:
    """回傳 {"status", "score", "extracted"}；score 為 1、0 或 None（未評分）。
    Return {"status", "score", "extracted"}; score is 1, 0, or None (unscored)."""
    if item["scorer"] == "multiple_choice":
        choice = extract_choice(content)
        if choice is None:
            return {"status": "unparsed", "score": 0, "extracted": None}
        ok = choice == item["data"]["answer"]
        return {"status": "correct" if ok else "wrong", "score": int(ok), "extracted": choice}
    if item["scorer"] == "simpleqa_approx":
        gold = normalize(item["data"]["answer"])
        got = normalize(strip_thinking(content))
        ok = bool(gold) and gold in got
        return {"status": "correct" if ok else "wrong", "score": int(ok), "extracted": None}
    return {"status": "pending_verifier", "score": None, "extracted": None}

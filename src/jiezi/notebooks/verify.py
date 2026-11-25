"""筆記本回答存進記憶前的查證（add-notebooks；使用者 2026-11-24：「每題自動存 存之前要查證 如有錯誤或不清楚的地方
要提出來」）。全部通過才自動存；沒過就列出發現，等使用者決定。
Checks before a notebook answer is saved to memory; saved only when every check passes, otherwise the findings
are shown and the user decides."""

from __future__ import annotations

import re

from ..longdoc import _bigrams

UNCERTAIN = re.compile(r"可能|也許|或許|不確定|不清楚|無法確定|似乎|大概|應該是|據推測|來源(?:裡)?(?:沒有|未)(?:說明|提到|寫)|"
                       r"找不到|未找到出處")
VAGUE_Q = re.compile(r"^(那|它|這|上面|剛才|剛剛)|那份|這份|那個|這個|上次|之前那")
_NUM = re.compile(r"\d+(?:[.,]\d+)?|[零一二兩三四五六七八九十百千萬]+(?=個|年|月|日|天|元|人|次|%|％|成)")
_SENT = re.compile(r"[^。！？!?\n]+")
SIMILAR = 0.6


_CITE = re.compile(r"[\[［【]\s*\d{1,2}(?:\s*[,，、]\s*\d{1,2})*\s*[\]］】]")


def _nums(text: str) -> set[str]:
    """文字裡的數字；引用編號 [1] 不算（否則 [1] 會和「1 個月」相符而漏掉衝突）。
    Numbers in the text, ignoring citation markers."""
    from .numbers import values
    return values(_CITE.sub("", text or ""))         # 「兩個月」與「2 個月」算同一個數 / 兩 == 2


def _strip_nums(text: str) -> set[str]:
    return set(_bigrams(_NUM.sub("", text or "")))


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _contain(a: set, b: set) -> float:
    """短句被長句包含的比例（兩份來源常一詳一略）。 / Share of the shorter sentence found in the longer."""
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def conflicts_between(passages: list[dict]) -> list[dict]:
    """被引用的不同來源裡，講同一件事（去掉數字後很像）但數字不同的句子。
    Sentences in different cited sources that say the same thing (similar without numbers) with different numbers."""
    found, seen = [], set()
    sents = [(p, s.strip()) for p in passages for s in _SENT.findall(p["text"]) if _nums(s)]
    for i, (pa, a) in enumerate(sents):
        for pb, b in sents[i + 1:]:
            if pa["sid"] == pb["sid"]:
                continue
            na, nb = _nums(a), _nums(b)
            if na == nb or _contain(_strip_nums(a), _strip_nums(b)) < SIMILAR:
                continue
            key = (pa["sid"], pb["sid"], a[:40], b[:40])
            if key in seen:
                continue
            seen.add(key)
            found.append({"check": "source_conflict",
                          "message": f"來源《{pa['title']}》說「{a[:60]}」，來源《{pb['title']}》說「{b[:60]}」",
                          "sources": [pa["sid"], pb["sid"]]})
    return found[:5]


def against_memory(question: str, answer: str, memory) -> list[dict]:
    """與使用者更正、先前存過的答案衝突。 / Conflicts with user corrections or earlier saved answers."""
    if memory is None:
        return []
    out = []
    ans_nums = _nums(answer)
    for c in memory.corrections_for(question):
        cn = _nums(c.text)
        if (cn and ans_nums and not (cn & ans_nums)) or (not cn and _jaccard(set(_bigrams(c.text)),
                                                                             set(_bigrams(answer))) < 0.15):
            out.append({"check": "memory_conflict", "message": f"與你 {c.at[:10]} 的更正不同：「{c.text[:80]}」",
                        "page": c.title})
    found = memory.find_answer(question)
    if found:
        e, sim = found
        en = _nums(e.text)
        if sim >= 0.85 and en and ans_nums and not (en & ans_nums):
            out.append({"check": "memory_conflict",
                        "message": f"與記憶裡 {e.at[:10]} 存過的答案數字不同：「{e.text[:80]}」", "page": e.title})
    return out


def verify(question: str, checked: dict, passages: list[dict], sources: dict[str, dict], memory=None,
           multi_source: bool = False) -> list[dict]:
    """回傳查證發現；空清單＝全部通過。 / Findings; an empty list means every check passed.
    checked：cite.check 的結果；sources：sid → 來源中繼資料（含 trust）。"""
    findings = []
    if checked.get("not_found"):
        return [{"check": "not_found", "message": "來源裡找不到答案，不存進記憶"}]
    # a. 出處完整 / every fact has a source
    for r in checked.get("removed") or []:
        if r.get("recited"):        # 編號錯但已改成支持的段落 / the marker was corrected
            continue
        findings.append({"check": "citation_removed",
                         "message": f"「{r['sentence'][:60]}」標了 [{r['n']}]，但{'沒有這一段' if r['why'] == 'no such passage' else '那一段沒有支持這句話'}"})
    for s in checked.get("unsourced") or []:
        findings.append({"check": "unsourced", "message": f"「{s[:60]}」沒有出處"})
    if not checked.get("citations"):
        findings.append({"check": "unsourced", "message": "整則回答沒有任何有效的引用"})
    cited = {c["source_id"] for c in checked.get("citations") or []}
    cited_passages = [p for p in passages if p["sid"] in cited]
    # b. 來源互相矛盾 / sources disagree
    findings += conflicts_between(cited_passages)
    # c. 與記憶衝突 / conflicts with memory
    findings += against_memory(question, checked.get("answer") or "", memory)
    # d. 來源被標記 / flagged sources
    for sid in cited:
        t = (sources.get(sid) or {}).get("trust") or {}
        if t.get("level") == "tainted" or t.get("injection"):
            findings.append({"check": "flagged_source",
                             "message": f"引用的來源《{sources[sid].get('title')}》被標記為可疑"
                                        f"（{', '.join(t.get('injection') or []) or t.get('level')}）"})
    # e. 不確定或含糊 / uncertain or ambiguous
    m = UNCERTAIN.search(re.sub(r"（未找到出處）", "", checked.get("answer") or ""))
    if m:
        findings.append({"check": "uncertain", "message": f"回答裡有不確定的說法「{m.group(0)}」"})
    if multi_source and VAGUE_Q.search(question.strip()):
        findings.append({"check": "ambiguous_question",
                         "message": "問題沒有指明是哪一份來源（例如「那份」「這個」），答案可能對應到別份資料"})
    return findings

"""工具參數值還原成使用者的原文（add-strong-tool-calling）。
Restore tool-call argument values to the user's own wording (add-strong-tool-calling).

本機模型在「用繁體中文回答」的系統提示下，常把參數值轉成繁體（使用者寫「阅读量」，參數變「閱讀量」），
工具端就查不到。這裡逐字正規化（繁體與異體字折成簡體，一字對一字、長度不變）後到對話裡找同一段，找到就換回原文。
值本來就出現在對話裡、或對話裡找不到對應的字串時都不動。
Under the "answer in Traditional Chinese" prompt the local model often converts argument values. Each value is
folded character by character (Traditional and variants → Simplified, length-preserving) and looked up in the conversation;
when found, the user's original span replaces it. Values already in the conversation, or with no match, are kept."""

from __future__ import annotations

import json
from functools import lru_cache

MIN_LEN = 2   # 單字太容易誤配 / single characters match too easily


@lru_cache(maxsize=1)
def _fold_map() -> dict[int, str]:
    """繁體與異體字 → 簡體（OpenCC STCharacters 的反查，一字對一字）；「讚」「贊」都折成「赞」。
    Traditional and variant characters → Simplified (reverse OpenCC STCharacters, one to one)."""
    from ..textconv import _TABLE
    out: dict[int, str] = {}
    for line in _TABLE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        k, v = line.split("\t", 1)
        if len(k) != 1:
            continue
        for c in v.split():
            if len(c) == 1 and c != k:
                out.setdefault(ord(c), k)
    return out


def _fold(text: str) -> str:
    """比對用的正規化：一字對一字、長度不變。 / Matching normalisation, length-preserving."""
    return text.translate(_fold_map())


def conversation_text(messages: list[dict]) -> str:
    """使用者與工具結果的文字（參數值的合法出處）。 / User and tool-result text: where argument values come from."""
    parts = []
    for m in messages or []:
        if m.get("role") not in ("user", "tool"):
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        if isinstance(c, str):
            parts.append(c)
    return "\n".join(parts)


def restore(value, text: str, norm: str | None = None, changed: list | None = None):
    """遞迴處理字串、清單、物件裡的字串值。 / Recurse through strings, lists and objects."""
    norm = _fold(text) if norm is None else norm
    if isinstance(value, str):
        if len(value) < MIN_LEN or value in text:
            return value
        i = norm.find(_fold(value))
        if i < 0:
            return value
        orig = text[i:i + len(value)]
        if changed is not None and orig != value:
            changed.append((value, orig))
        return orig
    if isinstance(value, list):
        return [restore(v, text, norm, changed) for v in value]
    if isinstance(value, dict):
        return {k: restore(v, text, norm, changed) for k, v in value.items()}
    return value


def restore_calls(message: dict, messages: list[dict]) -> list[tuple[str, str]]:
    """就地修改 message 的 tool_calls；回傳 (改前, 改後) 清單。
    Fix message["tool_calls"] in place; return the (before, after) pairs."""
    calls = message.get("tool_calls") or []
    if not calls:
        return []
    text = conversation_text(messages)
    if not text:
        return []
    norm, changed = _fold(text), []
    for tc in calls:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (TypeError, ValueError):
            continue
        fixed = restore(args, text, norm, changed)
        if fixed != args:
            fn["arguments"] = json.dumps(fixed, ensure_ascii=False)
    return changed

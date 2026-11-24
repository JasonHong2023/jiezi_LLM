"""朗讀前的文字處理（add-tts）：去掉 Markdown、程式碼與附註，依標點分段。
Text preparation for speech: strip markup, code and notes; split at punctuation."""

from __future__ import annotations

import re

MAX_INPUT_CHARS = 20_000
CHUNK_CHARS = 80              # 一段的上限；BlueMagpie 一次唸太長容易漏字 / long chunks drop words
CODE_PLACEHOLDER = "（程式碼略）"

_FENCE = re.compile(r"```.*?(```|\Z)", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]{1,60})`")
_LONG_INLINE = re.compile(r"`[^`\n]+`")
_NOTE = re.compile(r"\n-{3,}\s*\n\s*【[^】]{1,10}】.*\Z", re.S)        # 回答後的【記憶】【來源】等附註
_NOTE_LINE = re.compile(r"^\s*【(記憶|來源|參考|附註|注意)】.*$", re.M)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_WIKI = re.compile(r"\[\[([^\]|]+)(\|[^\]]+)?\]\]")
_HEAD = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
_BULLET = re.compile(r"^\s*([-*+]|\d+[.)])\s+", re.M)
_EMPH = re.compile(r"(\*\*|__|\*|~~)")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}.*$", re.M)
_HTML = re.compile(r"<[^>\n]{1,80}>")
_SPACES = re.compile(r"[ \t　]+")
_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
_SOFT = re.compile(r"(?<=[，、,：:])")


def clean_for_speech(text: str) -> str:
    """回答 → 可以唸的文字。 / An answer → speakable text."""
    t = (text or "").replace("\r\n", "\n")
    t = _NOTE.sub("", t)
    t = _NOTE_LINE.sub("", t)
    t = _FENCE.sub(CODE_PLACEHOLDER, t)
    t = _INLINE_CODE.sub(r"\1", t)
    t = _LONG_INLINE.sub(CODE_PLACEHOLDER, t)
    t = _WIKI.sub(r"\1", t)
    t = _LINK.sub(r"\1", t)
    t = _URL.sub("（網址略）", t)
    t = _TABLE_RULE.sub("", t)
    t = t.replace("|", "，")
    t = _HEAD.sub("", t)
    t = _BULLET.sub("", t)
    t = _EMPH.sub("", t)
    t = _HTML.sub("", t)
    lines = [_SPACES.sub(" ", ln).strip(" ，") for ln in t.split("\n")]
    out = "\n".join(ln for ln in lines if ln)
    return re.sub(r"\n{2,}", "\n", out).strip()


def _hard_split(s: str, limit: int) -> list[str]:
    parts, cur = [], ""
    for piece in _SOFT.split(s):
        while len(piece) > limit:                       # 沒有標點的長串 / long runs without punctuation
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(piece[:limit])
            piece = piece[limit:]
        if len(cur) + len(piece) > limit and cur:
            parts.append(cur)
            cur = ""
        cur += piece
    if cur:
        parts.append(cur)
    return parts


def split_chunks(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """依句號等標點分段，每段不超過 limit 字；太長的句子再依逗號切。 / Sentence chunks of at most `limit`."""
    chunks, cur = [], ""
    for sent in _SPLIT.split(text or ""):
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks += [p.strip() for p in _hard_split(sent, limit) if p.strip()]
            continue
        if cur and len(cur) + len(sent) > limit:
            chunks.append(cur)
            cur = ""
        cur += sent
    if cur:
        chunks.append(cur)
    return [c for c in chunks if re.search(r"[0-9A-Za-z㐀-鿿]", c)]

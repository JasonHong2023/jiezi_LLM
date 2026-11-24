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


# Big5 也收、但在台灣文字裡幾乎都是簡體混入的字（2026-11-24：模型寫出「体验」只換成「体驗」）
# Characters that are in Big5 but in Taiwan writing are almost always Simplified leaking in
_CHAR_EXTRA = {"体": "體"}


@lru_cache(maxsize=1)
def _map() -> dict[int, str]:
    out = {ord(k): v for k, v in _CHAR_EXTRA.items()}
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


# ── 台灣用語（使用者 2026-11-15：「1 2 先做」）/ Taiwan phrasing ──
# OpenCC TWPhrases（Apache-2.0，commit fae2a0a9）篩選後的對照表：只收候選不含原詞的詞（取第一個候選），並以 Taiwan.md
# 當台灣寫作參照——原詞在台灣文章裡少見（< 3 次），或台灣用語的次數超過原詞兩倍才收（「保存、參數、設備」不換）。
# Filtered OpenCC TWPhrases: entries whose candidates exclude the key, kept when the source phrase is rare in Taiwan.md or
# the Taiwan phrase is more than twice as common there.
_TW_TABLE = Path(__file__).resolve().parent / "eval" / "data" / "TWPhrases-jiezi.txt"
_FENCE = "```"
# 2026-11-24 參考 prompts.tw「繁中潤稿（去簡體化）」對照表後的人工調整 / manual adjustments after reviewing that list：
# - 補：「聯系」在台灣寫「聯繫」（OpenCC 單字表不換「系」）/ add: 聯系 is written 聯繫 in Taiwan
# - 不換：「文件」在台灣也指 document（官方文件、技術文件），一律換成「檔案」會改錯 / skip: 文件 also means document
# 依文意才能決定的（實現、優化、關注、質量、非常）不收，交給模型潤稿 / context-dependent pairs are left to the model
_TW_EXTRA = {"聯系": "聯繫"}
_TW_SKIP = {"文件"}


@lru_cache(maxsize=1)
def _tw() -> tuple[dict[str, str], int]:
    table = {}
    if _TW_TABLE.exists():
        for line in _TW_TABLE.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "\t" in line:
                k, v = line.split("\t", 1)
                if k not in _TW_SKIP:
                    table[k] = v
    table.update(_TW_EXTRA)
    return table, max((len(k) for k in table), default=1)


def _phrases(text: str) -> str:
    table, longest = _tw()
    if not table:
        return text
    out, i = [], 0
    while i < len(text):
        for n in range(min(longest, len(text) - i), 1, -1):
            v = table.get(text[i:i + n])
            if v:
                out.append(v)
                i += n
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def to_taiwan(text: str | None) -> str | None:
    """純簡體字轉正體，再把大陸用語換成台灣用語；``` 程式碼區塊裡不換詞。
    Simplified-only characters → Traditional, then mainland phrasing → Taiwan phrasing; code fences untouched."""
    if not text:
        return text
    parts = to_traditional(text).split(_FENCE)
    return _FENCE.join(p if i % 2 else _phrases(p) for i, p in enumerate(parts))


# ── 整份簡體文件 → 繁體（add-translation；不經模型）/ Whole Simplified documents → Traditional, no model ──
# 上面的 to_traditional 只換「純簡體字」，給模型輸出用（輸出本來就大多是繁體，不能動到正體字）。整份簡體文件不一樣：
# 「后、发、干、里」在簡體文裡要依詞決定（后台→後臺、皇后→皇后、头发→頭髮、发展→發展），所以照 OpenCC 的 s2twp 流程：
# 詞語表（STPhrases）最長比對 → 單字表（STCharacters）取第一個候選 → 台灣異體字（TWVariants：裏→裡、爲→為）→ 台灣用語。
# to_traditional above only swaps Simplified-only characters, for model output. A Simplified document is different:
# 后, 发, 干, 里 depend on the word, so this follows OpenCC's s2twp chain: longest match in STPhrases, first candidate
# in STCharacters, Taiwan variants, then Taiwan phrasing.
_DATA = Path(__file__).resolve().parent / "eval" / "data"


def _read_table(name: str) -> dict[str, str]:
    out = {}
    for line in (_DATA / name).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "\t" in line:
            k, v = line.split("\t", 1)
            cands = v.split()
            if cands:
                out[k] = cands[0]
    return out


@lru_cache(maxsize=1)
def _s2t() -> tuple[dict[str, str], int, dict[int, str], dict[int, str]]:
    phrases = _read_table("STPhrases.txt")
    chars = {ord(k): v for k, v in _read_table("STCharacters.txt").items() if len(k) == 1}
    variants = {ord(k): v for k, v in _read_table("TWVariants.txt").items() if len(k) == 1 and len(v) == 1}
    return phrases, max((len(k) for k in phrases), default=1), chars, variants


def simplified_to_taiwan(text: str | None) -> str | None:
    """簡體中文文件轉成台灣的繁體中文（字、異體字、用語）。只用在確定是簡體的原文上。
    Convert a Simplified Chinese document to Taiwan Traditional Chinese; only for text known to be Simplified."""
    if not text:
        return text
    phrases, longest, chars, variants = _s2t()
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] > "\u2e7f":  # 只有中日韓字需要查詞 / only CJK needs the phrase lookup
            for size in range(min(longest, n - i), 1, -1):
                v = phrases.get(text[i:i + size])
                if v:
                    out.append(v)
                    i += size
                    break
            else:
                out.append(text[i].translate(chars))
                i += 1
        else:
            out.append(text[i])
            i += 1
    return _phrases("".join(out).translate(variants))


class TaiwanStream:
    """串流版：只在後面的字夠判斷最長詞時才送出，詞不會被切在兩段之間；``` 程式碼區塊裡不換詞。
    Streaming version: text is released only when enough lookahead exists for the longest phrase, so phrases are
    never split across chunks; code fences are left alone."""

    def __init__(self):
        self.pending, self.in_code = "", False
        self.table, self.longest = _tw()

    def _scan(self, final: bool) -> str:
        text, out, i = self.pending, [], 0
        need = max(self.longest, len(_FENCE))
        while i < len(text) and (final or i + need <= len(text)):
            if text.startswith(_FENCE, i):
                out.append(_FENCE)
                self.in_code = not self.in_code
                i += len(_FENCE)
                continue
            if not self.in_code:
                for n in range(min(self.longest, len(text) - i), 1, -1):
                    v = self.table.get(text[i:i + n])
                    if v:
                        out.append(v)
                        i += n
                        break
                else:
                    out.append(text[i])
                    i += 1
            else:
                out.append(text[i])
                i += 1
        self.pending = text[i:]
        return "".join(out)

    def feed(self, delta: str) -> str:
        self.pending += to_traditional(delta)
        return self._scan(final=False)

    def flush(self) -> str:
        return self._scan(final=True)


def generate_tw_table(twphrases: Path, corpus: str, commit: str) -> str:
    """產生 TWPhrases-jiezi.txt 的內容（規則見上）。 / Build the filtered table (rule above)."""
    rows = []
    for line in twphrases.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        k, v = line.split("\t", 1)
        cands = v.split()
        if not cands or k in cands:  # 候選含原詞代表原詞也可能對 / the key itself may be right
            continue
        nk, nv = corpus.count(k), corpus.count(cands[0])
        if nk < 3 or nv > 2 * nk:
            rows.append(f"{k}\t{cands[0]}")
    head = ["# 由 OpenCC TWPhrases.txt 篩選（https://github.com/BYVoid/OpenCC ，commit " + commit + "，Apache-2.0，見 "
            "OpenCC-LICENSE.txt）/ filtered from OpenCC TWPhrases.txt",
            "# 規則：候選不含原詞（取第一個候選）；原詞在 Taiwan.md 少於 3 次，或台灣用語次數超過原詞兩倍",
            "# Rule: candidates exclude the key (first one is used); key < 3 times in Taiwan.md or the candidate > 2x the key",
            "# 產生方式 / generated by: jiezi.textconv.generate_tw_table"]
    return "\n".join(head + rows) + "\n"

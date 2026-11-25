"""翻譯（add-translation）：整份文件逐段翻譯、每段檢查、簡體轉繁體不經模型。
Translation: whole documents chunk by chunk, every chunk checked, Simplified-to-Traditional without a model.

為什麼不沿用長文件的摘要／挑段落：翻譯要的是「每一段都在」，摘要與節錄會讓譯文殘缺。做法是依段落切成小段
（譯文和原文差不多長，所以每段比摘要用的段小）→ 各段平行翻譯 → 依原文順序接回，接回後直接回傳，不再讓模型改寫。
Why not the long-document summary or selection: a translation needs every passage. Paragraph-aligned chunks (smaller
than summary chunks, since output is as long as input) are translated in parallel, joined in source order and
returned as is, with no rewriting pass.

檢查只看結構（空白、長度比例、數字、語言、詞彙表），抓得到漏譯與數字錯，**抓不到意思翻錯**。
The checks are structural (empty, length ratio, numbers, language, glossary): they catch omissions and wrong numbers,
**not wrong meaning**.

使用者決定（2026-11-16）：目標語言只做 zh-TW 與 en；失敗的段保留原文並標記、不外送；預設輸出原文／譯文對照；
預估超過 5 分鐘先問。
User decisions (2026-11-16): zh-TW and en only; failed chunks keep their source and are never sent out; bilingual
output by default; ask first above an estimated five minutes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Awaitable, Callable

from .runtime.context import est_tokens

LANGS = {"zh-TW": "繁體中文（台灣用語）", "en": "English"}
CHUNK_TOKENS = 900            # 每段原文上限；譯文約等長，加提示後放得進 4096 的槽位 / source tokens per chunk
ANSWER_TOKENS = 1800          # 每段譯文的生成上限 / generation cap per chunk
RATIO_MIN, RATIO_MAX = 0.4, 2.5   # 譯文與原文的估計 token 比 / translated-to-source token ratio
RATIO_MIN_TOKENS = 40         # 太短的段不看比例（標題、單句）/ short chunks skip the ratio check
CONTEXT_TAIL = 200            # 附上前一段原文結尾的字數 / characters of the previous source chunk given as context
PARALLEL = 4                  # 引擎的平行槽位數 / engine parallel slots
ASK_ABOVE_S = 300             # 預估超過這麼久要先問（使用者決定）/ ask first above this estimate
DEFAULT_TPS, PARALLEL_GAIN = 20.0, 2.0   # 沒有實測速度時的保守值；4 槽平行的總吞吐約為單槽的 2 倍 [估]
MAX_GLOSSARY = 200

_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_LATIN = re.compile(r"[A-Za-z]")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MONTH = re.compile(r"(?<!\d)(1[0-2]|0?[1-9])\s*月")
_FW = str.maketrans("０１２３４５６７８９．，", "0123456789.,")
# 翻譯意圖：要有「翻譯」類動詞；「這句話的翻譯是什麼意思」這種問句不算，所以動詞後面要接對象或目標語言
# Intent needs a translation verb followed by an object or target language
INTENT = re.compile(r"(翻譯|翻成|翻為|翻作|譯成|譯為|轉成|轉為|轉換成|translate|translation)", re.I)
TO_EN = re.compile(r"英文|英語|英譯|English|\ben\b", re.I)
TO_ZH = re.compile(r"中文|繁體|繁中|正體|國語|台灣|Chinese|Traditional|zh-?TW", re.I)
OTHER = re.compile(r"(成|為|into|to)\s*(日文|日語|韓文|韓語|法文|德文|西班牙文|俄文|越南文|泰文|印尼文|簡體|简体|"
                   r"Japanese|Korean|French|German|Spanish|Russian|Vietnamese|Thai|Simplified)", re.I)
CONVERT = re.compile(r"(簡|簡體).{0,4}(轉|翻|變|換).{0,4}(繁|正體)|轉(成|為|換成)?(繁體|正體)|簡轉繁")

Complete = Callable[[list[dict], int], Awaitable[str]]


class TranslateError(ValueError):
    """翻譯請求寫錯（例如不支援的目標語言）。 / A malformed translation request."""


# ── 辨識 / Detection ──
def detect(text: str) -> str:
    """原文語言：zh-Hans、zh-Hant、en、other。只看字元比例，不需要模型。
    Source language from character ratios only: zh-Hans, zh-Hant, en or other."""
    from .textconv import _map
    cjk = _CJK.findall(text)
    latin = len(_LATIN.findall(text))
    if len(cjk) >= max(4, latin // 4):
        simp = _map()
        n = sum(1 for c in cjk if ord(c) in simp)
        return "zh-Hans" if n >= max(2, len(cjk) // 50) else "zh-Hant"
    return "en" if latin >= 8 else "other"


def intent(question: str) -> dict | None:
    """問題是不是要翻譯；回傳 {"to": 目標代碼或 None, "convert": 是否只是簡轉繁}。
    Whether the question asks for a translation: {"to": code or None, "convert": script conversion only}."""
    q = (question or "").strip()
    if not q or len(q) > 200:      # 很長的「問題」多半本身就是要處理的內容 / a long question is content, not a request
        return None
    if CONVERT.search(q):
        return {"to": "zh-TW", "convert": True}
    if not INTENT.search(q):
        return None
    if re.search(r"(翻譯|translation)\s*(是|的意思|是什麼|怎麼說)", q, re.I) and not (TO_EN.search(q) or TO_ZH.search(q)):
        return None
    if OTHER.search(q):   # 日文等初版不支援的目標：不接手，照一般問題處理 / unsupported targets are left to the normal path
        return None
    en, zh = TO_EN.search(q), TO_ZH.search(q)
    if en and zh:   # 「把這份中文文件翻成英文」：取動詞後面先出現的 / the language named after the verb wins
        verb = INTENT.search(q).end()
        after = [(m.start(), code) for m, code in ((TO_EN.search(q, verb), "en"), (TO_ZH.search(q, verb), "zh-TW")) if m]
        return {"to": min(after)[1] if after else None, "convert": False}
    return {"to": "en" if en else "zh-TW" if zh else None, "convert": False}


def resolve_target(to: str | None, source_lang: str) -> str:
    if to is None:
        return "en" if source_lang.startswith("zh") else "zh-TW"
    if to not in LANGS:
        raise TranslateError(f"目前只支援翻成 {', '.join(LANGS)} / supported targets: {', '.join(LANGS)}")
    return to


def parse_glossary(rows) -> list[tuple[str, str]]:
    """詞彙對照表：[[原文詞, 指定譯法], …]。 / Glossary rows: [[source term, required translation], …]."""
    out = []
    for row in rows or []:
        if isinstance(row, (list, tuple)) and len(row) == 2 and all(isinstance(x, str) and x.strip() for x in row):
            out.append((row[0].strip(), row[1].strip()))
    if len(out) > MAX_GLOSSARY:
        raise TranslateError(f"詞彙表最多 {MAX_GLOSSARY} 筆 / at most {MAX_GLOSSARY} glossary rows")
    return out


DEFAULT_GLOSSARY = Path(__file__).parent / "data" / "tw-agencies.tsv"


def default_glossary() -> list[tuple[str, str, str]]:
    """內建的台灣機關英文名（中文, 英文, 來源網址）；add-default-glossary。
    Built-in English names of Taiwan agencies: (Chinese, English, source URL)."""
    rows = []
    try:
        lines = DEFAULT_GLOSSARY.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) == 3 and parts[0].strip() and parts[1].strip():
            rows.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return rows


def with_default(glossary: list[tuple[str, str]], text: str, target: str, use_default: bool = True
                 ) -> tuple[list[tuple[str, str]], list[dict]]:
    """中翻英時把原文出現的內建機關名併進詞彙表；使用者詞彙表同詞時以使用者為準。
    長詞先比、比到的地方遮掉再比短詞（「國立故宮博物院」不會再多要求「故宮博物院」）。
    回傳 (合併後的詞彙表, 套用的內建詞 [{"term","translation","source"}])。
    For Chinese → English, add the built-in agency names found in the text; the user's glossary wins; longer terms
    are matched first and masked so a shorter name inside them is not required again."""
    if target != "en" or not use_default or not text:
        return list(glossary), []
    mine = {a for a, _ in glossary}
    rest, used = text, []
    for zh, en, src in sorted(default_glossary(), key=lambda r: -len(r[0])):
        if zh in rest:
            rest = rest.replace(zh, "\u3000" * len(zh))
            if zh not in mine:
                used.append({"term": zh, "translation": en, "source": src})
    return list(glossary) + [(u["term"], u["translation"]) for u in used], used


def read_glossary(path: str | Path) -> list[list[str]]:
    """TSV 或「原文=譯法」；# 開頭是註解。 / TSV or `source=translation`; lines starting with # are comments."""
    rows = []
    for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t") if "\t" in line else line.split("=", 1)
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            rows.append([parts[0].strip(), parts[1].strip()])
    return rows


# ── 分段與提示 / Chunks and prompts ──
def chunks(text: str) -> list[str]:
    from .longdoc import chunks as split
    return split(text, CHUNK_TOKENS)


def prompt(chunk: str, target: str, prev: str = "", glossary: list[tuple[str, str]] | None = None,
           error: str | None = None) -> list[dict]:
    if target == "en":
        return _prompt_en(chunk, glossary, error)
    rules = [f"你是專業譯者。把使用者給的內容完整翻譯成{LANGS[target]}。",
             "規則：每一句都要翻，不可省略、摘要或加入原文沒有的內容；數字、日期、專有名詞要保留正確；"
             "保留原本的分段與清單格式；只輸出譯文，不要解釋。"]
    used = [(a, b) for a, b in glossary or [] if a in chunk]
    if used:
        rules.append("以下詞語必須使用指定譯法：" + "；".join(f"{a} → {b}" for a, b in used))
    if prev:
        rules.append(f"前文結尾（只供理解上下文，不要翻譯這一段）：……{prev}")
    if error:
        rules.append(f"上一次的譯文沒有通過檢查：{error}。請修正後重新翻譯整段。")
    return [{"role": "system", "content": "\n".join(rules)}, {"role": "user", "content": chunk}]


def _prompt_en(chunk: str, glossary: list[tuple[str, str]] | None, error: str | None) -> list[dict]:
    """中翻英用英文提示、不附前文。2026-11-25 實測（qwen3.5-4b-r3，思考關閉）：中文提示加中文前文時，
    模型常把原文照抄回來（著作權法 3 段中 2 段「譯文大部分仍是中文」）；英文提示、使用者訊息開頭加
    「Translate into English:」、不附中文前文，同一段 5 次全過，附前文則 5 次錯 1–2 次。
    Chinese → English uses an English prompt and no Chinese context: with the Chinese prompt and the previous
    source tail, the r3 core often echoed the source instead of translating it."""
    rules = ["You are a professional translator. Translate the user's text from Chinese into English completely. "
             "Translate every sentence; do not omit, summarize or add anything. Keep numbers, dates and proper names "
             "correct; keep the paragraphs and list formatting. Output only the English translation, no explanations."]
    used = [(a, b) for a, b in glossary or [] if a in chunk]
    if used:
        rules.append("Use these required translations: " + "; ".join(f"{a} → {b}" for a, b in used))
    if error:
        rules.append(f"The previous attempt failed a check ({error}). Translate the whole text again, in English.")
    return [{"role": "system", "content": "\n".join(rules)},
            {"role": "user", "content": "Translate into English:\n\n" + chunk}]


# ── 檢查 / Checks ──
def _num_key(s: str) -> str:
    """數字的有效位數：1,250 與 12.5 都是 125（萬 ↔ million 換單位後仍算保留）。
    Significant digits: 1,250 and 12.5 both give 125, so a unit change (萬 ↔ million) still counts as preserved."""
    return re.sub(r"[.,]", "", s).strip("0")


def numbers(text: str) -> set[str]:
    return {k for k in (_num_key(m) for m in _NUM.findall((text or "").translate(_FW))) if len(k) >= 2}


def check(source: str, out: str, target: str, glossary: list[tuple[str, str]] | None = None,
          ratio: bool = True) -> list[str]:
    """回傳錯誤（空的表示通過）。 / Return the errors; empty means the chunk passes."""
    out = (out or "").strip()
    if not out:
        return ["譯文是空的 / empty translation"]
    err = []
    cjk, latin = len(_CJK.findall(out)), len(_LATIN.findall(out))
    if target == "en" and cjk > max(4, (cjk + latin) * 0.3):
        err.append("譯文大部分仍是中文 / the output is still mostly Chinese")
    if target == "zh-TW" and cjk < max(2, (cjk + latin / 4) * 0.3):
        err.append("譯文大部分不是中文 / the output is mostly not Chinese")
    if ratio and est_tokens(source) >= RATIO_MIN_TOKENS:
        r = est_tokens(out) / est_tokens(source)
        if r < RATIO_MIN:
            err.append(f"譯文太短（約為原文的 {r:.0%}），可能漏譯 / too short, probably omissions")
        elif r > RATIO_MAX:
            err.append(f"譯文太長（約為原文的 {r:.0%}），可能加了原文沒有的內容 / too long, probably additions")
    # 中翻英時月份會變成英文月名（11 月 → November），不算漏掉 / month numbers become names in English
    src_nums = numbers(_MONTH.sub("月", source) if target == "en" else source)
    missing = sorted(src_nums - numbers(out))
    if missing:
        raw = [m for m in _NUM.findall(source.translate(_FW)) if _num_key(m) in missing]
        err.append("缺少原文的數字 / numbers missing: " + "、".join(dict.fromkeys(raw))[:120])
    for a, b in glossary or []:
        if a in source and b.lower() not in out.lower():
            err.append(f"「{a}」必須譯為「{b}」 / {a!r} must be translated as {b!r}")
    return err[:6]


# ── 簡體 → 繁體（不經模型）/ Simplified to Traditional, no model ──
def convert(text: str) -> str:
    from .textconv import simplified_to_taiwan
    return simplified_to_taiwan(text) or ""


# ── 續跑用的暫存 / Resume store ──
class Store:
    """已翻好的段存在 var/translate/<雜湊>.json（只在本機），中斷後重送同一份文件會接著做。
    Finished chunks live in var/translate/<hash>.json (local only); re-sending the same document resumes."""

    def __init__(self, directory: Path | None, key_parts: list):
        self.path = None
        self.rows: dict[str, str] = {}
        if directory is not None:
            key = hashlib.sha256(json.dumps(key_parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
            self.path = directory / f"{key}.json"
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.rows = {k: v for k, v in data.items() if isinstance(v, str)}
            except (OSError, ValueError, AttributeError):
                self.rows = {}

    def get(self, i: int) -> str | None:
        return self.rows.get(str(i))

    def put(self, i: int, text: str) -> None:
        self.rows[str(i)] = text
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.rows, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # 存不了只是不能續跑，翻譯照常 / without the store the run simply cannot resume


# ── 預估 / Estimate ──
def estimate_seconds(texts: list[str], tps: float | None) -> float:
    """[估] 譯文約與原文等長；4 槽平行的總吞吐取單槽的 2 倍。 / Output about as long as input; four slots ≈ 2× one."""
    tokens = sum(est_tokens(t) for t in texts)
    n = sum(len(chunks(t)) for t in texts)
    speed = (tps or DEFAULT_TPS) * (PARALLEL_GAIN if n > 1 else 1.0)
    return round(tokens / max(speed, 1.0) * 1.15, 1)   # 15% 留給重試 / 15% for retries


# ── 整份翻譯 / Whole documents ──
async def translate_text(name: str, text: str, target: str, complete: Complete,
                         glossary: list[tuple[str, str]] | None = None, store_dir: Path | None = None) -> tuple[list, dict]:
    """回傳 ([(原文段, 譯文或 None)], 資訊)。 / Return ([(source chunk, translation or None)], info)."""
    import anyio
    parts = chunks(text)
    store = Store(store_dir, [name, text, target, glossary or []])
    out: list[str | None] = [None] * len(parts)
    info = {"document": name, "chunks": len(parts), "resumed": 0, "retried": 0, "failed": [], "calls": 0}
    sem = anyio.Semaphore(PARALLEL)

    async def one(i: int) -> None:
        saved = store.get(i)
        if saved is not None:
            out[i] = saved
            info["resumed"] += 1
            return
        prev = parts[i - 1][-CONTEXT_TAIL:] if i else ""
        async with sem:
            got = (await complete(prompt(parts[i], target, prev, glossary), ANSWER_TOKENS)).strip()
            info["calls"] += 1
            errors = check(parts[i], got, target, glossary)
            if errors:
                info["retried"] += 1
                got = (await complete(prompt(parts[i], target, prev, glossary, "；".join(errors)), ANSWER_TOKENS)).strip()
                info["calls"] += 1
                errors = check(parts[i], got, target, glossary)
        if errors:
            info["failed"].append({"chunk": i + 1, "errors": errors})
            return
        out[i] = got
        store.put(i, got)

    async with anyio.create_task_group() as tg:
        for i in range(len(parts)):
            tg.start_soon(one, i)
    info["failed"].sort(key=lambda f: f["chunk"])
    return list(zip(parts, out)), info


def render(name: str, pairs: list, bilingual: bool, many: bool) -> str:
    """接成最後的文字；失敗的段保留原文並標記。 / Join the result; failed chunks keep their source, marked."""
    n = len(pairs)
    blocks = [f"# {name}"] if many else []
    for i, (src, tr) in enumerate(pairs, 1):
        if tr is None:
            blocks.append(f"〔第 {i}/{n} 段未能翻譯，以下為原文 / chunk {i} of {n} could not be translated; source follows〕\n{src}")
        elif bilingual:
            blocks.append(f"〔原文 {i}/{n}〕\n{src}\n\n〔譯文 {i}/{n}〕\n{tr}")
        else:
            blocks.append(tr)
    return "\n\n".join(blocks)

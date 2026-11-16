"""長文件處理（add-long-documents）：本機模型每個槽位只有 4096 token，放不下的文件先濃縮再回答。
Long documents: the local model has 4096 tokens per slot, so documents that do not fit are condensed first.

- 要摘要（問題含「摘要、重點、整理……」或沒有問題）：分段 → 每段整理重點（可平行）→ 合起來還太長就再整理一輪（map-reduce）。
  Summaries: split → bullet points per chunk (in parallel) → reduce again while still too long.
- 要問答：依問題的雙字詞（加權 IDF）挑最相關的段落，照原文順序放進去，標出段落編號。
  Questions: pick the chunks most relevant to the question (IDF-weighted bigrams), in document order, labeled.

濃縮後的內容取代原本的長文件，之後照常走平行取樣、驗證與轉交。 / The condensed text replaces the document; the normal
pipeline (sampling, verification, escalation) then runs as usual.

追問（add-document-followup）：客戶端每一題都重新附上文件，所以每題都依「這一題」重新挑段落；挑段落時也參考上一輪
的問答（權重減半），「那第二點呢」這類問題才找得到段落；留一點空間給上一輪對話；各段重點放在記憶體快取，
同一份文件再次要摘要時不必重跑。
Follow-ups: the client re-attaches the document with every question, so chunks are re-selected per question; the
previous exchange is a half-weight hint for ranking, some room is reserved for it, and per-chunk notes are cached in
memory so a second summary of the same document does not redo the map step."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, OrderedDict
from typing import Awaitable, Callable

from .runtime.context import DEFAULT_ANSWER, SLOT_CTX, est_tokens

SUMMARY = re.compile(r"摘要|總結|重點|大意|概要|整理|歸納|摘錄|精簡|濃縮|說了什麼|講了什麼|在講什麼|summar|tl;?dr|overview|key points",
                     re.I)
LIMIT = SLOT_CTX - DEFAULT_ANSWER - 400      # 超過就濃縮（留給系統提示與附加資料）/ condense above this
CHUNK_TOKENS = 1800                          # 每段（留空間給提示與回答）/ per chunk, leaving room for prompt and answer
QA_CHUNK_TOKENS = 600                        # 問答挑段落用較小的段，才挑得準、也塞得進多段 / smaller chunks for selection
MAP_ANSWER = 450                             # 每段重點的長度上限 / bullet points per chunk
MAX_CHUNKS = 60                              # 超過就只處理前面這麼多段並註明 / beyond this, process the first ones and say so
MAX_ROUNDS = 3
PARALLEL = 4                                 # 引擎的平行槽位數 / engine parallel slots
HINT_WEIGHT = 0.5                            # 上一輪問答在挑段落時的權重 / weight of the previous exchange in ranking
FOLLOWUP_RESERVE = 600                       # 追問時最多留給上一輪對話的 token / room kept for the previous exchange
MIN_BUDGET = 1200


class NotesCache:
    """各段重點的記憶體快取（最近幾份文件；不寫入磁碟）。 / In-memory cache of per-chunk notes; never on disk."""

    def __init__(self, size: int = 8):
        self.size, self.rows = size, OrderedDict()

    @staticmethod
    def key(name: str, text: str) -> str:
        return hashlib.sha256(f"{name}\0{text}".encode("utf-8")).hexdigest()

    def get(self, name: str, text: str):
        k = self.key(name, text)
        if k in self.rows:
            self.rows.move_to_end(k)
            return self.rows[k]
        return None

    def put(self, name: str, text: str, value) -> None:
        self.rows[self.key(name, text)] = value
        self.rows.move_to_end(self.key(name, text))
        while len(self.rows) > self.size:
            self.rows.popitem(last=False)

Complete = Callable[[list[dict], int], Awaitable[str]]

MAP_PROMPT = ("你在整理一份長文件。以下是《{name}》的第 {i}/{n} 段。請用繁體中文條列這一段的重點，"
              "保留關鍵的數字、日期、人名、地名與結論，不要加入原文沒有的內容，最多 8 點。")
REDUCE_PROMPT = ("以下是《{name}》各段的重點整理（第 {i}/{n} 組）。請合併成一份不重複、依原文順序的繁體中文重點清單，"
                 "保留關鍵數字與結論，不要加入原文沒有的內容，最多 12 點。")


# ── 分析訊息 / Parse the message ──
def split_message(content: str) -> tuple[list[tuple[str, str]], str]:
    """回傳 ([(文件名, 內容)], 問題)。沒有文件標記時，最後一段短文字當問題，其餘當文件。
    Return ([(name, text)], question). Without markers the last short paragraph is the question."""
    from .documents import DOC_RE
    docs = [(m["name"], m["text"]) for m in DOC_RE.finditer(content)]
    if docs:
        return docs, DOC_RE.sub("", content).strip()
    paras = content.rstrip().rsplit("\n\n", 1)
    if len(paras) == 2 and len(paras[1]) <= 300:
        return [("你提供的文字", paras[0])], paras[1].strip()
    return [("你提供的文字", content)], ""


def needed(content, budget: int = LIMIT) -> bool:
    return isinstance(content, str) and est_tokens(content) > budget


# ── 分段 / Chunking ──
def chunks(text: str, size: int = CHUNK_TOKENS) -> list[str]:
    """依段落切，段落太長再依句子切，最後才硬切。 / Split by paragraph, then sentence, then hard."""
    units = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if est_tokens(para) <= size:
            units.append(para)
            continue
        for sent in re.split(r"(?<=[。！？!?；;])|\n", para):
            sent = sent.strip()
            while est_tokens(sent) > size:   # 沒有標點的超長段 / very long unpunctuated runs
                cut = size * 2 // 3          # 約等於 size 個 token（中文 1 字 1 token、英文較短）/ roughly size tokens
                units.append(sent[:cut])
                sent = sent[cut:]
            if sent:
                units.append(sent)
    out, cur = [], ""
    for u in units:
        joined = f"{cur}\n\n{u}" if cur else u
        if cur and est_tokens(joined) > size:
            out.append(cur)
            cur = u
        else:
            cur = joined
    if cur:
        out.append(cur)
    return out


# ── 問答：挑相關段落 / Questions: pick relevant chunks ──
def _bigrams(text: str) -> list[str]:
    t = re.sub(r"\s+", "", text.lower())
    return [t[i:i + 2] for i in range(len(t) - 1)]


def _coverage(query: str, sets: list[set]) -> list[float]:
    q = set(_bigrams(query))
    df = Counter(b for s in sets for b in q & s)
    n = len(sets)
    # 只算文件裡出現過的雙字詞：文件沒有的字不該稀釋分數（否則問題和提示的分數無法相比）
    # Only bigrams the document contains count, so question and hint scores stay comparable
    idf = {b: math.log((n + 1) / (df[b] + 0.5)) for b in q if df[b]}
    total = sum(idf.values()) or 1.0
    return [sum(idf.get(b, 0.0) for b in q & s) / total for s in sets]


def rank(question: str, parts: list[str], hint: str = "") -> list[tuple[float, int]]:
    """IDF 加權的雙字詞覆蓋率；hint（上一輪問答）以一半權重計入。
    IDF-weighted bigram coverage of the question; the hint (previous exchange) counts at half weight."""
    sets = [set(_bigrams(p)) for p in parts]
    score = _coverage(question, sets)
    if hint.strip():
        score = [a + HINT_WEIGHT * b for a, b in zip(score, _coverage(hint, sets))]
    return sorted(((sc, i) for i, sc in enumerate(score)), key=lambda x: -x[0])


def select(question: str, parts: list[str], budget: int = LIMIT, hint: str = "") -> list[int]:
    picked, used = [], est_tokens(question) + 200
    for score, i in rank(question, parts, hint):
        t = est_tokens(parts[i]) + 20
        if used + t > budget:
            continue
        picked.append(i)
        used += t
    return sorted(picked)


# ── 摘要：map-reduce / Summaries: map-reduce ──
async def _gather(prompts: list[list[dict]], complete: Complete, max_tokens: int) -> list[str]:
    import anyio
    out: list[str] = [""] * len(prompts)
    sem = anyio.Semaphore(PARALLEL)

    async def one(i: int) -> None:
        async with sem:
            out[i] = (await complete(prompts[i], max_tokens)).strip()

    async with anyio.create_task_group() as tg:
        for i in range(len(prompts)):
            tg.start_soon(one, i)
    return out


async def summarize(name: str, text: str, complete: Complete, budget: int = LIMIT,
                    cache: NotesCache | None = None) -> tuple[str, dict]:
    parts = chunks(text)
    info = {"chunks": len(parts), "rounds": 0, "truncated": False, "calls": 0, "cached": False}
    if len(parts) > MAX_CHUNKS:
        parts, info["truncated"] = parts[:MAX_CHUNKS], True
    notes = cache.get(name, text) if cache is not None else None
    if notes is not None:
        info["cached"] = True
    else:
        prompts = [[{"role": "system", "content": MAP_PROMPT.format(name=name, i=i, n=len(parts))},
                    {"role": "user", "content": p}] for i, p in enumerate(parts, 1)]
        notes = await _gather(prompts, complete, MAP_ANSWER)
        info["calls"] += len(prompts)
        if cache is not None and all(notes):  # 有任何一段失敗就不快取 / never cache a partial result
            cache.put(name, text, notes)
    info["rounds"] = 1
    current = "\n\n".join(f"〔第 {i} 段〕\n{t}" for i, t in enumerate(notes, 1) if t)
    while est_tokens(current) > budget and info["rounds"] < MAX_ROUNDS:
        groups = chunks(current)
        prompts = [[{"role": "system", "content": REDUCE_PROMPT.format(name=name, i=i, n=len(groups))},
                    {"role": "user", "content": g}] for i, g in enumerate(groups, 1)]
        merged = await _gather(prompts, complete, MAP_ANSWER)
        info["calls"] += len(prompts)
        info["rounds"] += 1
        current = "\n\n".join(t for t in merged if t)
    return current, info


# ── 入口 / Entry ──
async def condense(content: str, complete: Complete, hint: str = "", budget: int = LIMIT,
                   cache: NotesCache | None = None) -> tuple[str, dict]:
    """把含長文件的訊息改寫成放得進本機上下文的版本。hint：上一輪問答（追問時幫忙挑段落）。
    Rewrite a long-document message to fit the local context. hint: the previous exchange, for follow-ups."""
    budget = max(MIN_BUDGET, budget)
    docs, question = split_message(content)
    mode = "summary" if not question or SUMMARY.search(question) else "qa"
    info = {"mode": mode, "documents": [n for n, _ in docs], "chars": sum(len(t) for _, t in docs)}
    blocks = []
    if mode == "summary":
        per = []
        for name, text in docs:
            s, i = await summarize(name, text, complete, budget // max(1, len(docs)), cache)
            per.append(i)
            note = "（文件過長，只整理了前面部分）" if i["truncated"] else ""
            blocks.append(f"以下是《{name}》（原文 {len(text)} 字，分 {i['chunks']} 段整理）的重點{note}：\n{s}")
        info["summaries"] = per
        instruction = question or "請依上面的重點，用繁體中文寫一份完整的摘要。"
    else:
        for name, text in docs:
            parts = chunks(text, QA_CHUNK_TOKENS)
            keep = select(question, parts, budget // max(1, len(docs)), hint)
            info.setdefault("selected", []).append({"document": name, "chunks": len(parts), "kept": keep})
            body = "\n\n".join(f"〔第 {i + 1}/{len(parts)} 段〕\n{parts[i]}" for i in keep)
            blocks.append(f"以下是《{name}》（原文 {len(text)} 字）中和問題最相關的段落：\n{body}")
        instruction = (question + "\n（只根據上面的段落回答；段落裡找不到答案就說文件中沒有提到，並指出依據的段落編號。）")
    new = "\n\n".join(blocks) + "\n\n" + instruction
    info["after_tokens"] = est_tokens(new)
    return new, info

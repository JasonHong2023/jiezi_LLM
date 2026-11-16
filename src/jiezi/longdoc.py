"""長文件處理（add-long-documents）：本機模型每個槽位只有 4096 token，放不下的文件先濃縮再回答。
Long documents: the local model has 4096 tokens per slot, so documents that do not fit are condensed first.

- 要摘要（問題含「摘要、重點、整理……」或沒有問題）：分段 → 每段整理重點（可平行）→ 合起來還太長就再整理一輪（map-reduce）。
  Summaries: split → bullet points per chunk (in parallel) → reduce again while still too long.
- 要問答：依問題的雙字詞（加權 IDF）挑最相關的段落，照原文順序放進去，標出段落編號。
  Questions: pick the chunks most relevant to the question (IDF-weighted bigrams), in document order, labeled.

濃縮後的內容取代原本的長文件，之後照常走平行取樣、驗證與轉交。 / The condensed text replaces the document; the normal
pipeline (sampling, verification, escalation) then runs as usual."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Awaitable, Callable

from .runtime.context import DEFAULT_ANSWER, SLOT_CTX, est_tokens

SUMMARY = re.compile(r"摘要|總結|重點|大意|概要|整理|歸納|摘錄|說了什麼|講了什麼|在講什麼|summar|tl;?dr|overview|key points",
                     re.I)
LIMIT = SLOT_CTX - DEFAULT_ANSWER - 400      # 超過就濃縮（留給系統提示與附加資料）/ condense above this
CHUNK_TOKENS = 1800                          # 每段（留空間給提示與回答）/ per chunk, leaving room for prompt and answer
MAP_ANSWER = 450                             # 每段重點的長度上限 / bullet points per chunk
MAX_CHUNKS = 60                              # 超過就只處理前面這麼多段並註明 / beyond this, process the first ones and say so
MAX_ROUNDS = 3
PARALLEL = 4                                 # 引擎的平行槽位數 / engine parallel slots

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


def needed(content) -> bool:
    return isinstance(content, str) and est_tokens(content) > LIMIT


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


def rank(question: str, parts: list[str]) -> list[tuple[float, int]]:
    """IDF 加權的雙字詞覆蓋率。 / IDF-weighted bigram coverage of the question."""
    q = set(_bigrams(question))
    sets = [set(_bigrams(p)) for p in parts]
    df = Counter(b for s in sets for b in q & s)
    n = len(parts)
    idf = {b: math.log((n + 1) / (df[b] + 0.5)) for b in q}
    total = sum(idf.values()) or 1.0
    return sorted(((sum(idf[b] for b in q & s) / total, i) for i, s in enumerate(sets)), key=lambda x: -x[0])


def select(question: str, parts: list[str], budget: int = LIMIT) -> list[int]:
    picked, used = [], est_tokens(question) + 200
    for score, i in rank(question, parts):
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


async def summarize(name: str, text: str, complete: Complete) -> tuple[str, dict]:
    parts = chunks(text)
    info = {"chunks": len(parts), "rounds": 0, "truncated": False, "calls": 0}
    if len(parts) > MAX_CHUNKS:
        parts, info["truncated"] = parts[:MAX_CHUNKS], True
    prompts = [[{"role": "system", "content": MAP_PROMPT.format(name=name, i=i, n=len(parts))},
                {"role": "user", "content": p}] for i, p in enumerate(parts, 1)]
    notes = await _gather(prompts, complete, MAP_ANSWER)
    info["calls"] += len(prompts)
    info["rounds"] = 1
    current = "\n\n".join(f"〔第 {i} 段〕\n{t}" for i, t in enumerate(notes, 1) if t)
    while est_tokens(current) > LIMIT and info["rounds"] < MAX_ROUNDS:
        groups = chunks(current)
        prompts = [[{"role": "system", "content": REDUCE_PROMPT.format(name=name, i=i, n=len(groups))},
                    {"role": "user", "content": g}] for i, g in enumerate(groups, 1)]
        merged = await _gather(prompts, complete, MAP_ANSWER)
        info["calls"] += len(prompts)
        info["rounds"] += 1
        current = "\n\n".join(t for t in merged if t)
    return current, info


# ── 入口 / Entry ──
async def condense(content: str, complete: Complete) -> tuple[str, dict]:
    """把含長文件的訊息改寫成放得進本機上下文的版本。 / Rewrite a long-document message to fit the local context."""
    docs, question = split_message(content)
    mode = "summary" if not question or SUMMARY.search(question) else "qa"
    info = {"mode": mode, "documents": [n for n, _ in docs], "chars": sum(len(t) for _, t in docs)}
    blocks = []
    if mode == "summary":
        per = []
        for name, text in docs:
            s, i = await summarize(name, text, complete)
            per.append(i)
            note = "（文件過長，只整理了前面部分）" if i["truncated"] else ""
            blocks.append(f"以下是《{name}》（原文 {len(text)} 字，分 {i['chunks']} 段整理）的重點{note}：\n{s}")
        info["summaries"] = per
        instruction = question or "請依上面的重點，用繁體中文寫一份完整的摘要。"
    else:
        for name, text in docs:
            parts = chunks(text)
            keep = select(question, parts, LIMIT // max(1, len(docs)))
            info.setdefault("selected", []).append({"document": name, "chunks": len(parts), "kept": keep})
            body = "\n\n".join(f"〔第 {i + 1}/{len(parts)} 段〕\n{parts[i]}" for i in keep)
            blocks.append(f"以下是《{name}》（原文 {len(text)} 字）中和問題最相關的段落：\n{body}")
        instruction = (question + "\n（只根據上面的段落回答；段落裡找不到答案就說文件中沒有提到，並指出依據的段落編號。）")
    new = "\n\n".join(blocks) + "\n\n" + instruction
    info["after_tokens"] = est_tokens(new)
    return new, info

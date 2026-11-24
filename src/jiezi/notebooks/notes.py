"""一鍵筆記（add-notebooks 3.1）：摘要、常見問答、學習指南。
One-click notes: summary, FAQ and study guide, via map (key points per chunk) → reduce, with checked citations.

4B 核心一次只能看約 4,000 token，所以先逐段抽重點（map），再把各段重點彙整（reduce）。段落太多時平均取樣，
筆記裡會註明。產生的筆記存成這本筆記本的「筆記」來源，之後也能被引用。"""

from __future__ import annotations

import datetime as _dt
import re

import anyio

from . import cite

KINDS = {
    "summary": ("摘要", "寫一份摘要：先用 3 到 5 句話總覽，再列出 5 到 8 個重點（每點一行，以「- 」開頭）。"),
    "faq": ("常見問答", "列出 5 到 8 組讀者最可能問的問題與回答，每組兩行：「Q：問題」與「A：回答」。"),
    "study_guide": ("學習指南", "寫一份學習指南，分三段：「關鍵名詞」（每行「名詞：解釋」）、「重點整理」（每點一行）、"
                                "「自我測驗」（3 到 5 題，每題附答案）。"),
}
MAX_MAP = 40                 # 最多逐段處理幾段 / chunks mapped at most
POINT_CHARS = 160            # 每段重點的長度上限 / characters of key points per chunk
_LOCK = anyio.Lock()         # 一次只做一份筆記 / one notes job at a time


def pick(chunks: list[dict], limit: int = MAX_MAP) -> tuple[list[dict], bool]:
    """段落太多就取樣：每份來源至少一段，其餘依各來源段數比例分配，來源內平均取樣（保留原順序）。
    2026-11-24 實測：對全部段落平均取樣時，只有 1 段的會議錄音被跳過，摘要完全沒提到它。
    Sample when there are too many chunks: every source gets at least one, the rest is shared in proportion to each
    source's size, evenly inside a source (order kept). Plain even sampling skipped a one-chunk recording."""
    if len(chunks) <= limit:
        return chunks, False
    groups: dict[str, list[dict]] = {}
    for c in chunks:
        groups.setdefault(c["sid"], []).append(c)
    quota = {sid: 1 for sid in groups}
    rest = limit - len(quota)
    if rest > 0:
        extra = {sid: (len(g) - 1) * rest / (len(chunks) - len(groups) or 1) for sid, g in groups.items()}
        for sid in groups:
            quota[sid] += int(extra[sid])
        left = limit - sum(quota.values())
        for sid in sorted(groups, key=lambda k: extra[k] - int(extra[k]), reverse=True)[:max(left, 0)]:
            quota[sid] += 1
    chosen = set()
    for sid, g in groups.items():
        q = min(quota[sid], len(g))
        step = len(g) / q
        chosen.update(id(g[int(i * step)]) for i in range(q))
    return [c for c in chunks if id(c) in chosen][:max(limit, len(groups))], True


async def generate(gw, nb, kind: str, complete, progress=None) -> dict:
    """complete(messages, max_tokens) -> str：呼叫本機模型。 / `complete` calls the local model."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    label, instruction = KINDS[kind]
    titles = {s["id"]: s["title"] for s in nb.sources() if s["kind"] != "note"}
    chunks = [c for c in nb.chunks() if c["sid"] in titles]       # 不拿舊筆記再做筆記 / skip earlier notes
    if not chunks:
        raise ValueError("this notebook has no sources yet")
    chosen, sampled = pick(chunks)
    passages = cite.number(chosen, titles)
    points = []
    async with _LOCK:
        for k, p in enumerate(passages, 1):
            if progress:
                progress(f"整理第 {k}/{len(passages)} 段")
            msgs = [{"role": "system", "content": "你負責整理資料重點。只寫段落裡明確有的事實，不要推測，用繁體中文。"},
                    {"role": "user", "content": f"《{p['title']}》的一段：\n{p['text']}\n\n用 1 到 3 句話列出這段的重點。"}]
            text = (await complete(msgs, 200)).strip()
            points.append((p, re.sub(r"\s+", " ", text)[:POINT_CHARS]))
        if progress:
            progress("彙整中")
        body = "\n".join(f"[{p['n']}]《{p['title']}》{t}" for p, t in points if t)
        msgs = [{"role": "system", "content": "你根據使用者筆記本的段落重點寫筆記。只能使用下列重點，每一句陳述事實的話後面"
                                              "都要標出處 [編號]，編號就是重點前面的數字；不要編造。用繁體中文。"},
                {"role": "user", "content": f"筆記本《{nb.meta['name']}》各段重點：\n{body}\n\n{instruction}"}]
        draft = await complete(msgs, 1200)
    # 筆記是重點的再改寫：引用檢查對照「原文＋該段重點」，引用位置仍指向原文
    # Notes paraphrase the key points, so the check compares against the chunk text plus its key points
    by_n = dict((p["n"], t) for p, t in points)
    checked = cite.check(draft, [{**p, "text": p["text"] + "\n" + by_n.get(p["n"], "")} for p in passages])
    for c in checked["citations"]:
        src = next(p for p in passages if p["n"] == c["n"])
        c["quote"] = src["text"].strip()[:160]
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    notice = f"\n\n（依 {len(chunks)} 段中的 {len(passages)} 段取樣整理）" if sampled else ""
    refs = "\n".join(f"[{c['n']}]《{c['title']}》{c['quote'][:60]}" for c in checked["citations"])
    text = f"{checked['answer']}{notice}\n\n出處：\n{refs}" if refs else checked["answer"] + notice
    saved = None
    if not checked["not_found"]:
        saved, _ = nb.add_source(f"{label}（自動產生 {stamp}）", "note", text, "",
                                 {"level": "unverified", "generated": True}, {"note_kind": kind})
    return {"kind": kind, "label": label, "answer": checked["answer"], "citations": checked["citations"],
            "removed": checked["removed"], "unsourced": checked["unsourced"], "sampled": sampled,
            "chunks": len(chunks), "used": len(passages), "source": saved}

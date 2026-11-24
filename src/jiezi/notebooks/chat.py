"""筆記本在聊天管線裡的兩個步驟（add-notebooks）：附段落（ground）與回答後處理（引用檢查、查證、存記憶）。
The two notebook steps in the chat pipeline: attach passages, then check citations, verify and save to memory."""

from __future__ import annotations

import json
from pathlib import Path

from . import cite, memory_link, verify


def ground(gw, body: dict, rec: dict, last: dict, data: list | None) -> None:
    """筆記本模式：檢索段落、編號，插入系統訊息；附上使用者更正（不附舊答案）。
    Notebook mode: retrieve and number passages, insert them; attach user corrections but no stale answers."""
    nb = gw.notebooks.get(rec["notebook"]["id"])
    question = last["content"] or ""
    qv = None
    if getattr(gw, "embedder", None) is not None:
        try:
            nb.embed_missing(gw.embedder.embed)
            qv = gw.embedder.embed_query(question)
        except Exception as exc:  # noqa: BLE001 - 向量失敗就只用字面 / lexical only
            gw.log(f"notebook: embedding failed, lexical only: {type(exc).__name__}: {exc}")
    found = cite.retrieve(nb.chunks(), question, qv, nb.vectors() if qv is not None else None)
    titles = {s["id"]: s["title"] for s in nb.sources()}
    passages = cite.number(found, titles)
    general = rec["notebook"]["general"]
    rec["notebook_ctx"] = {"nid": nb.id, "passages": passages, "general": general, "recall": False,
                           "question": question}
    idx = body["messages"].index(last.get("_target", last))
    blocks = []
    if gw.memory is not None:
        from ..memory import recall_block
        r = recall_block(question, gw.memory, include_answer=False)    # 只有更正 / corrections only
        if r:
            blocks.append(r[0])
            rec["sources"] = (rec.get("sources") or []) + r[1]
    blocks.append(cite.prompt(passages, nb.meta["name"], general))
    for content in blocks:
        body["messages"].insert(idx, {"role": "system", "content": content})
        if data is not None:
            data.append(body["messages"][idx])
        idx += 1
        rec["grounding_text"] = (rec.get("grounding_text") or "") + "\n" + content
    rec["sources"] = (rec.get("sources") or []) + [
        {"source": "notebook", "notebook": nb.id, "name": nb.meta["name"], "source_id": p["sid"], "title": p["title"],
         "n": p["n"]} for p in passages]
    gw._untrainable(rec, "notebook")       # 使用者的私人資料預設不訓練 / private content is not trainable


def _pending_path(nb, tid: str) -> Path:
    return nb.path / "pending" / f"{tid}.json"


def after(gw, rec: dict, resp: dict) -> dict:
    """回答完成後：引用檢查；筆記本模式再查證並自動存記憶。回傳要放進 meta 的欄位。
    After the answer: check citations; in notebook mode also verify and save to memory automatically."""
    ctx = rec.get("notebook_ctx")
    if not ctx:
        return {}
    msg = ((resp.get("choices") or [{}])[0]).get("message") or {}
    answer = msg.get("content")
    if not isinstance(answer, str) or msg.get("tool_calls"):
        return {}
    from ..runtime.gateway import strip_appendix
    nb, passages = gw.notebooks.get(ctx["nid"]), ctx["passages"]
    if not passages and not ctx["general"]:
        checked = {"answer": cite.NOT_FOUND, "citations": [], "removed": [], "unsourced": [], "not_found": True}
    else:
        checked = cite.check(strip_appendix(answer), passages, ctx["general"])
    rec["notebook_answer"] = checked["answer"]
    extra = cite.appendix(checked["citations"])
    if extra and extra not in (rec.get("dict_appendix") or ""):
        rec["dict_appendix"] = (rec.get("dict_appendix") or "") + extra
    out = {"notebook_id": nb.id, "notebook": nb.meta["name"], "recall": ctx["recall"],
           "answer": checked["answer"], "citations": checked["citations"],
           "removed_citations": checked["removed"], "unsourced": checked["unsourced"],
           "not_found": checked["not_found"]}
    rec["notebook_check"] = {"citations": len(checked["citations"]), "removed": len(checked["removed"]),
                             "unsourced": len(checked["unsourced"]), "not_found": checked["not_found"]}
    if ctx["recall"] or rec.get("eval"):
        return {"notebook": out}
    # 筆記本模式：每題查證後自動存記憶（使用者 2026-11-24）/ verify, then save automatically
    sources = {s["id"]: s for s in nb.sources()}
    findings = verify.verify(ctx["question"], checked, passages, sources, gw.memory, multi_source=len(sources) > 1)
    memory = {"saved": False, "findings": findings}
    if checked["not_found"]:
        memory = {"saved": False, "skipped": "not_found", "findings": []}
    elif not findings and gw.memory is not None and not rec.get("_notebook_saved"):
        page = memory_link.save_answer(gw.memory, nb, ctx["question"], checked)
        rec["_notebook_saved"] = True
        memory = {"saved": bool(page), "page": page, "findings": []}
    elif findings:
        p = _pending_path(nb, rec["id"])    # 留給「仍要存」/ kept for "save anyway"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"question": ctx["question"], "checked": checked, "findings": findings},
                                ensure_ascii=False), encoding="utf-8")
    out["memory"] = memory
    rec["notebook_check"]["memory_saved"] = memory["saved"]
    rec["notebook_check"]["findings"] = [f["check"] for f in memory.get("findings") or []]
    return {"notebook": out}


def remember_anyway(gw, nb, tid: str) -> dict:
    """使用者在查證沒過時選「仍要存」。 / The user chose to save despite the findings."""
    p = _pending_path(nb, tid)
    if not tid.replace("-", "").isalnum() or not p.is_file():
        return {"saved": False, "error": "no pending answer for this id"}
    data = json.loads(p.read_text(encoding="utf-8"))
    page = memory_link.save_answer(gw.memory, nb, data["question"], data["checked"], data["findings"])
    p.unlink()
    return {"saved": bool(page), "page": page}

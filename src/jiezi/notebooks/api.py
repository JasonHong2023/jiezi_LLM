"""筆記本 API（add-notebooks）。全部需要 gateway 金鑰。 / Notebook endpoints; all need the gateway key.

GET  /v1/notebooks                         列表
POST /v1/notebooks                         {"name", "description"} 建立
GET  /v1/notebooks/{id}                    筆記本＋來源清單
PATCH /v1/notebooks/{id}                   改名、說明
DELETE /v1/notebooks/{id}                  刪除（含記憶 wiki 的摘要頁）
POST /v1/notebooks/{id}/sources            multipart file，或 JSON {"url"} / {"text", "title"}
GET  /v1/notebooks/{id}/sources/{sid}      來源全文（引用跳轉用）
DELETE /v1/notebooks/{id}/sources/{sid}
POST /v1/notebooks/{id}/remember           {"trajectory_id"} 查證沒過時「仍要存」"""

from __future__ import annotations

import tempfile
from pathlib import Path

import anyio
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import memory_link
from .store import NotebookError

MAX_UPLOAD = 100 * 1024 * 1024
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".webm", ".mp4", ".mkv", ".mov"}


def _err(status: int, message: str, code: str = "invalid_request") -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": code, "code": code}}, status_code=status)


def _digest(gw, nb) -> None:
    if gw.memory is None:
        return
    try:
        from ..memory import wiki_path
        memory_link.write_digest(wiki_path(gw.s.root), nb)
    except OSError as exc:
        gw.log(f"notebook digest: {exc}")


def _trust(gw, text: str, channel: str, origin: str) -> dict:
    """提示注入掃描＋信任等級。 / Injection scan plus trust level."""
    from ..injection import scan
    hits = scan(text[:200_000])
    level = "unverified" if channel in ("url", "audio") else "trusted_user"
    try:
        lv, _, _ = gw._trust_gate().evaluate_trust(text[:200_000], "web" if channel == "url" else "user",
                                                    origin or channel, {"retrieval_method": "notebook"})
        level = lv.name.lower()
    except Exception:  # noqa: BLE001 - 把關失敗不擋加入，照掃描結果標 / scan result still applies
        pass
    out = {"level": "tainted" if hits and level == "tainted" else level}
    if hits:
        out["injection"] = hits
    return out


async def _read_upload(gw, request: Request) -> tuple[bytes, str]:
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_UPLOAD + 1_000_000:
            raise NotebookError(f"the upload is larger than {MAX_UPLOAD >> 20} MB", 413)
    from email.parser import BytesParser
    from email.policy import HTTP
    ctype = request.headers.get("content-type", "")
    msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body)
    for part in msg.iter_parts() if msg.is_multipart() else []:
        if part.get_param("name", header="content-disposition") == "file":
            return part.get_payload(decode=True) or b"", part.get_filename() or "upload"
    raise NotebookError("multipart field `file` is missing")


async def _add(gw, request: Request, nb) -> dict:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        data, name = await _read_upload(gw, request)
        if not data:
            raise NotebookError("the uploaded file is empty")
        suffix = Path(name).suffix.lower()
        if suffix in AUDIO_EXT:                       # 音檔／影片 → 逐字稿 / audio or video → transcript
            if gw.asr is None:
                raise NotebookError("audio sources need speech recognition (JIEZI_ASR=on)", 503)
            res = await gw.asr.transcribe(data, name)
            text = "\n".join(f"[{_mmss(s['start'])}] {s['text']}" for s in res["segments"]) or res["text"]
            return _store(gw, nb, name, "audio", text, name, {"audio_s": res["audio_s"]})
        from ..documents import DocumentError, read
        with tempfile.TemporaryDirectory(dir=gw.s.var) as d:
            safe = "".join(c for c in Path(name).name if c.isalnum() or c in "._- ") or "upload"
            p = Path(d) / safe
            p.write_bytes(data)
            try:
                doc = await anyio.to_thread.run_sync(read, p)
            except DocumentError as exc:
                raise NotebookError(str(exc)) from exc
        return _store(gw, nb, name, "file", doc.get("text") or "", name,
                      {"ocr_pages": doc.get("ocr_pages")} if doc.get("ocr_pages") else None)
    body = await gw._read_json_any(request)
    if isinstance(body, Response):
        raise NotebookError("expected JSON or multipart")
    if body.get("url"):
        from ..webread import WebError, fetch
        try:
            page = await fetch(str(body["url"]))
        except WebError as exc:
            raise NotebookError(f"cannot read the page: {exc}") from exc
        return _store(gw, nb, body.get("title") or page.get("title") or body["url"], "url", page.get("text") or "",
                      page.get("final_url") or body["url"])
    if body.get("text"):
        kind = "note" if body.get("kind") == "note" else "text"
        return _store(gw, nb, body.get("title") or "貼上的文字", kind, str(body["text"]), "")
    raise NotebookError("give a file, a url or text")


def _mmss(t) -> str:
    t = int(t or 0)
    return f"{t // 60:02d}:{t % 60:02d}"


def _store(gw, nb, title: str, kind: str, text: str, origin: str, extra: dict | None = None) -> dict:
    trust = _trust(gw, text, kind, origin)
    embed = gw.embedder.embed if getattr(gw, "embedder", None) is not None else None
    try:
        rec, new = nb.add_source(title, kind, text, origin, trust, extra, embed=embed)
    except NotebookError:
        raise
    except Exception as exc:  # noqa: BLE001 - 向量失敗：來源已存，之後提問時再補 / vectors are filled later
        gw.log(f"notebook: embedding failed while adding a source: {type(exc).__name__}: {exc}")
        rec, new = nb.add_source(title, kind, text, origin, trust, extra)
    _digest(gw, nb)
    return {"source": rec, "created": new}


async def handle(gw, request: Request) -> Response:
    if not gw._authorized(request):
        return _err(401, "invalid or missing gateway key", "unauthorized")
    if gw.notebooks is None:
        return _err(404, "notebooks are off (JIEZI_NOTEBOOKS=on)", "not_found")
    nid, sid = request.path_params.get("nid"), request.path_params.get("sid")
    action = request.path_params.get("action")
    store, m = gw.notebooks, request.method
    try:
        if nid is None:
            if m == "GET":
                return JSONResponse({"object": "list", "data": store.list()})
            body = await gw._read_json_any(request)
            if isinstance(body, Response):
                return body
            nb = store.create(str(body.get("name") or ""), str(body.get("description") or ""))
            _digest(gw, nb)
            return JSONResponse(nb.meta, status_code=201)
        nb = store.get(nid)
        if action == "sources" and sid is None:
            return JSONResponse(await _add(gw, request, nb), status_code=201)
        if action == "sources":
            if m == "DELETE":
                ok = nb.remove_source(sid)
                _digest(gw, nb)
                return JSONResponse({"deleted": ok}, status_code=200 if ok else 404)
            s = nb.source(sid)
            return JSONResponse(s) if s else _err(404, "no such source", "not_found")
        if action == "remember":
            body = await gw._read_json_any(request)
            if isinstance(body, Response):
                return body
            from .chat import remember_anyway
            return JSONResponse(remember_anyway(gw, nb, str(body.get("trajectory_id") or "")))
        if m == "DELETE":
            name = nb.meta["name"]
            ok = store.delete(nid)
            if gw.memory is not None:
                from ..memory import wiki_path
                memory_link.remove_digest(wiki_path(gw.s.root), name)
            return JSONResponse({"deleted": ok})
        if m == "PATCH":
            body = await gw._read_json_any(request)
            if isinstance(body, Response):
                return body
            meta = store.rename(nid, body.get("name"), body.get("description"))
            _digest(gw, nb)
            return JSONResponse(meta)
        return JSONResponse({**nb.meta, "sources": nb.sources()})
    except NotebookError as exc:
        return _err(exc.status, str(exc), "notebook_error")
    except Exception as exc:  # noqa: BLE001 - ASR 等錯誤轉成清楚的訊息 / surface ASR and other errors
        status = getattr(exc, "status", 500)
        return _err(status if isinstance(status, int) else 500, f"{type(exc).__name__}: {exc}"[:300],
                    getattr(exc, "code", "notebook_error"))


def routes(gw):
    from starlette.routing import Route
    async def h(request: Request) -> Response:
        return await handle(gw, request)
    return [Route("/v1/notebooks", h, methods=["GET", "POST"]),
            Route("/v1/notebooks/{nid}", h, methods=["GET", "PATCH", "DELETE"]),
            Route("/v1/notebooks/{nid}/{action:str}", h, methods=["POST"]),
            Route("/v1/notebooks/{nid}/{action:str}/{sid}", h, methods=["GET", "DELETE"])]

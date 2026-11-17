"""四個唯讀工具（add-agent-readonly）。每個工具先經授權檢查；任何寫入、執行、網路功能都沒有。
The four read-only tools. Every call passes the grant check first; nothing writes, executes or reaches the network."""

from __future__ import annotations

import datetime as _dt
import fnmatch
import mimetypes
import os
import stat as _stat
from pathlib import Path

from .grants import Grants

MAX_LIST, MAX_FIND, MAX_DEPTH, MAX_READ_CHARS = 500, 200, 8, 20_000

SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_dir", "description": "列出資料夾內容（名稱、大小、修改時間、是否為資料夾）。List a folder.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "資料夾的完整路徑"}},
                       "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "find_files", "description": "在資料夾（含子資料夾）裡依檔名樣式找檔案，可依大小或修改時間排序。"
                                           "Find files by name pattern, optionally sorted by size or time.",
        "parameters": {"type": "object", "properties": {
            "root": {"type": "string", "description": "從哪個資料夾開始找"},
            "pattern": {"type": "string", "description": "檔名樣式，例如 *.pdf；預設 *"},
            "sort": {"type": "string", "enum": ["name", "size", "mtime"], "description": "排序；size 與 mtime 由大到小"}},
            "required": ["root"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "讀取檔案的文字（純文字、PDF、Word、PowerPoint、Excel 等）。Read a file as text.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "檔案的完整路徑"}},
                       "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {
        "name": "file_info", "description": "檔案或資料夾的大小、修改時間與類型。Size, time and type of a path.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"], "additionalProperties": False}}},
]
NAMES = {s["function"]["name"] for s in SCHEMAS}


class ToolError(Exception):
    pass


def _when(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _entry(p: Path, st: os.stat_result) -> dict:
    return {"name": p.name, "path": str(p), "is_dir": _stat.S_ISDIR(st.st_mode), "size": st.st_size,
            "modified": _when(st.st_mtime)}


def list_dir(g: Grants, path: str) -> dict:
    real, why = g.check(path)
    if why:
        raise ToolError(why)
    if not real.is_dir():
        raise ToolError(f"not a folder: {real}")
    out, more = [], 0
    for child in sorted(real.iterdir(), key=lambda c: c.name):
        if g.denied(child.resolve(strict=False)):
            continue  # 機密項目不列出 / secrets are not listed
        if len(out) >= MAX_LIST:
            more += 1
            continue
        try:
            out.append(_entry(child, child.stat()))
        except OSError:
            continue
    return {"path": str(real), "entries": out, "omitted": more}


def find_files(g: Grants, root: str, pattern: str = "*", sort: str = "name") -> dict:
    real, why = g.check(root)
    if why:
        raise ToolError(why)
    if not real.is_dir():
        raise ToolError(f"not a folder: {real}")
    pattern = (pattern or "*").strip() or "*"
    hits, scanned = [], 0
    base_depth = len(real.parts)
    for dirpath, dirnames, filenames in os.walk(real, followlinks=False):
        d = Path(dirpath)
        if len(d.parts) - base_depth >= MAX_DEPTH:
            dirnames[:] = []
        dirnames[:] = [n for n in dirnames if not g.denied((d / n).resolve(strict=False))]
        for n in filenames:
            scanned += 1
            if not fnmatch.fnmatch(n.lower(), pattern.lower()):
                continue
            p = d / n
            if g.check(p)[1]:  # 指向授權外的符號連結 / symlinks leading outside
                continue
            try:
                hits.append(_entry(p, p.stat()))
            except OSError:
                continue
        if scanned > 200_000:
            break
    key = {"size": lambda e: -e["size"], "mtime": lambda e: e["modified"]}.get(sort, lambda e: e["path"])
    hits.sort(key=key, reverse=(sort == "mtime"))
    return {"root": str(real), "pattern": pattern, "sort": sort, "matches": hits[:MAX_FIND],
            "total": len(hits), "truncated": len(hits) > MAX_FIND}


def read_file(g: Grants, path: str, sandbox=None) -> dict:
    from ..documents import DocumentError, read
    from ..injection import clean, scan
    real, why = g.check(path)
    if why:
        raise ToolError(why)
    if not real.is_file():
        raise ToolError(f"not a file: {real}")
    try:
        d = read(str(real), sandbox=sandbox)
    except DocumentError as exc:
        raise ToolError(f"cannot read: {exc}") from exc
    text, _ = clean(d.get("text") or "")
    cut = len(text) > MAX_READ_CHARS
    return {"path": str(real), "kind": d.get("kind"), "chars": len(text), "truncated": cut,
            "suspicious": scan(text)[:5],
            "text": text[:MAX_READ_CHARS] + ("\n……（檔案過長，只讀了前 20,000 字）" if cut else "")}


def file_info(g: Grants, path: str) -> dict:
    real, why = g.check(path)
    if why:
        raise ToolError(why)
    try:
        st = real.stat()
    except OSError as exc:
        raise ToolError(f"not found: {real}") from exc
    e = _entry(real, st)
    e["type"] = "folder" if e["is_dir"] else (mimetypes.guess_type(real.name)[0] or "unknown")
    return e


def call(g: Grants, name: str, args: dict, sandbox=None) -> dict:
    """依名稱執行；參數不對丟 ToolError。 / Dispatch by name; bad arguments raise ToolError."""
    if name not in NAMES:
        raise ToolError(f"unknown tool {name!r}")
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    allowed = set(next(s for s in SCHEMAS if s["function"]["name"] == name)["function"]["parameters"]["properties"])
    extra = set(args) - allowed
    if extra:
        raise ToolError(f"unexpected arguments: {', '.join(sorted(extra))}")
    try:
        if name == "list_dir":
            return list_dir(g, str(args["path"]))
        if name == "find_files":
            return find_files(g, str(args["root"]), str(args.get("pattern") or "*"), str(args.get("sort") or "name"))
        if name == "read_file":
            return read_file(g, str(args["path"]), sandbox)
        return file_info(g, str(args["path"]))
    except KeyError as exc:
        raise ToolError(f"missing argument {exc.args[0]!r}") from exc


def summary(name: str, result: dict | None, error: str | None) -> dict:
    """稽核與轉交用的摘要：只有中繼資料，沒有內容。 / Metadata only, for audit and escalation."""
    if error:
        return {"tool": name, "ok": False, "error": error[:300]}
    r = result or {}
    s = {"tool": name, "ok": True, "path": r.get("path") or r.get("root")}
    if name == "list_dir":
        s["entries"] = len(r.get("entries") or [])
    elif name == "find_files":
        s.update(matches=r.get("total"), pattern=r.get("pattern"))
    elif name == "read_file":
        s.update(chars=r.get("chars"), kind=r.get("kind"), truncated=r.get("truncated"), suspicious=r.get("suspicious"))
    else:
        s.update(size=r.get("size"), type=r.get("type"))
    return s

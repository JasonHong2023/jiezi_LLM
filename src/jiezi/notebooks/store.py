"""筆記本的儲存（add-notebooks）：筆記本、來源、帶字元位置的段落、SQLite 索引（雙字詞＋向量）。
Notebook storage: notebooks, sources, chunks with character offsets, and an SQLite index (bigrams + vectors).

版面 / Layout（全部在本機 var/notebooks/，不進版控）：
  <id>/notebook.json          名稱、說明、建立／更新時間
  <id>/sources/<sid>.json     來源的中繼資料與全文（引用跳轉用）
  <id>/index.sqlite           chunks(id, sid, ord, start, end, text)、vecs(id, v)"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import threading
from array import array
from pathlib import Path

from ..runtime.context import est_tokens

CHUNK_TOKENS = 350
OVERLAP = 0.15
KINDS = ("file", "url", "text", "audio", "note")
MAX_SOURCE_CHARS = 2_000_000
_ID = re.compile(r"^[a-z0-9]{6,32}$")
_SENT = re.compile(r"[^。！？!?；;\n]*(?:[。！？!?；;]+|\n+|$)")


class NotebookError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_offsets(text: str, size: int = CHUNK_TOKENS, overlap: float = OVERLAP) -> list[tuple[int, int]]:
    """依句子切段，回傳每段在原文的 (start, end)；相鄰段重疊約 overlap 比例的句子。
    Sentence-based chunks as (start, end) offsets into the original text, with sentence overlap."""
    units = []
    for m in _SENT.finditer(text):
        s, e = m.start(), m.end()
        if e <= s:
            continue
        while est_tokens(text[s:e]) > size:          # 沒有標點的超長句硬切 / hard-cut long runs
            cut = s + size * 2 // 3
            units.append((s, cut))
            s = cut
        if text[s:e].strip():
            units.append((s, e))
    out, i = [], 0
    while i < len(units):
        j, tok = i, 0
        while j < len(units) and (j == i or tok + est_tokens(text[units[j][0]:units[j][1]]) <= size):
            tok += est_tokens(text[units[j][0]:units[j][1]])
            j += 1
        out.append((units[i][0], units[j - 1][1]))
        if j >= len(units):
            break
        back, k = 0, j                                # 往回帶幾句當重疊 / carry a few sentences back
        while k - 1 > i and back + est_tokens(text[units[k - 1][0]:units[k - 1][1]]) <= size * overlap:
            k -= 1
            back += est_tokens(text[units[k][0]:units[k][1]])
        if k == j and j - 1 > i and est_tokens(text[units[j - 1][0]:units[j - 1][1]]) <= size * 0.4:
            k = j - 1                                 # 至少帶一句（句子比重疊比例長時）/ at least one sentence
        i = k if k > i else j
    return out


class Notebook:
    """一本筆記本。執行緒安全（同一本只有一個寫入者）。 / One notebook; writes are serialized."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.meta = json.loads((path / "notebook.json").read_text(encoding="utf-8"))
        self.db = sqlite3.connect(path / "index.sqlite", check_same_thread=False)
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, sid TEXT, ord INTEGER, start INTEGER,"
            " end INTEGER, text TEXT);"
            "CREATE INDEX IF NOT EXISTS chunks_sid ON chunks(sid);"
            "CREATE TABLE IF NOT EXISTS vecs(id INTEGER PRIMARY KEY, v BLOB);")

    @property
    def id(self) -> str:
        return self.meta["id"]

    def close(self) -> None:
        self.db.close()

    def _save_meta(self) -> None:
        self.meta["updated_at"] = _now()
        tmp = self.path / "notebook.json.tmp"
        tmp.write_text(json.dumps(self.meta, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path / "notebook.json")

    # ── 來源 / sources ──
    def _source_path(self, sid: str) -> Path:
        if not _ID.match(sid or ""):
            raise NotebookError("bad source id")
        return self.path / "sources" / f"{sid}.json"

    def sources(self) -> list[dict]:
        out = []
        for p in sorted((self.path / "sources").glob("*.json")):
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            out.append({k: v for k, v in s.items() if k != "text"})
        return sorted(out, key=lambda s: s["added_at"])

    def source(self, sid: str, with_text: bool = True) -> dict | None:
        p = self._source_path(sid)
        if not p.is_file():
            return None
        s = json.loads(p.read_text(encoding="utf-8"))
        return s if with_text else {k: v for k, v in s.items() if k != "text"}

    def add_source(self, title: str, kind: str, text: str, origin: str = "", trust: dict | None = None,
                   extra: dict | None = None, embed=None) -> tuple[dict, bool]:
        """加入來源；內容相同就回傳既有的（第二個值 False）。 / Add a source; duplicates return the existing one."""
        if kind not in KINDS:
            raise NotebookError(f"kind must be one of {', '.join(KINDS)}")
        text = (text or "").replace("\r\n", "\n").strip()
        if not text:
            raise NotebookError("the source has no text")
        if len(text) > MAX_SOURCE_CHARS:
            raise NotebookError(f"the source is longer than {MAX_SOURCE_CHARS} characters", 413)
        digest = sha256(text)
        with self.lock:
            for s in self.sources():
                if s["sha256"] == digest:
                    return s, False
            sid = secrets.token_hex(6)
            spans = split_offsets(text)
            rec = {"id": sid, "title": (title or "未命名來源")[:200], "kind": kind, "origin": origin[:2000],
                   "sha256": digest, "chars": len(text), "chunks": len(spans), "added_at": _now(),
                   "trust": trust or {"level": "unverified"}, **(extra or {}), "text": text}
            (self.path / "sources").mkdir(exist_ok=True)
            tmp = self._source_path(sid).with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._source_path(sid))
            rows = [(sid, i, s, e, text[s:e]) for i, (s, e) in enumerate(spans)]
            cur = self.db.executemany("INSERT INTO chunks(sid, ord, start, end, text) VALUES (?,?,?,?,?)", rows)
            self.db.commit()
            del cur
            self._save_meta()
        if embed is not None:
            self.embed_missing(embed)
        return {k: v for k, v in rec.items() if k != "text"}, True

    def remove_source(self, sid: str) -> bool:
        with self.lock:
            p = self._source_path(sid)
            if not p.is_file():
                return False
            ids = [r[0] for r in self.db.execute("SELECT id FROM chunks WHERE sid=?", (sid,))]
            self.db.executemany("DELETE FROM vecs WHERE id=?", [(i,) for i in ids])
            self.db.execute("DELETE FROM chunks WHERE sid=?", (sid,))
            self.db.commit()
            p.unlink()
            self._save_meta()
            return True

    # ── 段落與向量 / chunks and vectors ──
    def chunks(self) -> list[dict]:
        return [{"id": r[0], "sid": r[1], "ord": r[2], "start": r[3], "end": r[4], "text": r[5]}
                for r in self.db.execute("SELECT id, sid, ord, start, end, text FROM chunks ORDER BY sid, ord")]

    def embed_missing(self, embed, batch: int = 32) -> int:
        """補算還沒有向量的段落；embed(list[str]) → list[array]。 / Embed chunks that have no vector yet."""
        todo = [(r[0], r[1]) for r in self.db.execute(
            "SELECT c.id, c.text FROM chunks c LEFT JOIN vecs v ON v.id = c.id WHERE v.id IS NULL")]
        n = 0
        for k in range(0, len(todo), batch):
            part = todo[k:k + batch]
            vecs = embed([t for _, t in part])
            with self.lock:
                self.db.executemany("INSERT OR REPLACE INTO vecs VALUES (?, ?)",
                                    [(i, v.tobytes()) for (i, _), v in zip(part, vecs)])
                self.db.commit()
            n += len(part)
        return n

    def vectors(self) -> dict[int, array]:
        out = {}
        for i, blob in self.db.execute("SELECT id, v FROM vecs"):
            a = array("f")
            a.frombytes(blob)
            out[i] = a
        return out


class NotebookStore:
    def __init__(self, root: Path):
        self.root = root
        self._open: dict[str, Notebook] = {}
        self._lock = threading.Lock()

    def _dir(self, nid: str) -> Path:
        if not _ID.match(nid or ""):
            raise NotebookError("bad notebook id", 404)
        return self.root / nid

    def list(self) -> list[dict]:
        out = []
        for p in sorted(self.root.glob("*/notebook.json")) if self.root.exists() else []:
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            m["sources"] = len(list((p.parent / "sources").glob("*.json")))
            out.append(m)
        return sorted(out, key=lambda m: m.get("updated_at", ""), reverse=True)

    def create(self, name: str, description: str = "") -> Notebook:
        name = (name or "").strip()
        if not name:
            raise NotebookError("a notebook needs a name")
        nid = secrets.token_hex(6)
        d = self.root / nid
        (d / "sources").mkdir(parents=True)
        now = _now()
        (d / "notebook.json").write_text(json.dumps(
            {"id": nid, "name": name[:100], "description": description[:1000], "created_at": now, "updated_at": now},
            ensure_ascii=False, indent=1), encoding="utf-8")
        return self.get(nid)

    def get(self, nid: str) -> Notebook:
        d = self._dir(nid)
        with self._lock:
            nb = self._open.get(nid)
            if nb is None:
                if not (d / "notebook.json").is_file():
                    raise NotebookError("no such notebook", 404)
                nb = self._open[nid] = Notebook(d)
            return nb

    def find(self, name: str) -> Notebook | None:
        for m in self.list():
            if m["name"] == name or m["id"] == name:
                return self.get(m["id"])
        return None

    def rename(self, nid: str, name: str | None = None, description: str | None = None) -> dict:
        nb = self.get(nid)
        with nb.lock:
            if name is not None and name.strip():
                nb.meta["name"] = name.strip()[:100]
            if description is not None:
                nb.meta["description"] = description[:1000]
            nb._save_meta()
        return nb.meta

    def delete(self, nid: str) -> bool:
        d = self._dir(nid)
        with self._lock:
            nb = self._open.pop(nid, None)
            if nb:
                nb.close()
            if not d.is_dir():
                return False
            shutil.rmtree(d)
            return True

    def close(self) -> None:
        with self._lock:
            for nb in self._open.values():
                nb.close()
            self._open.clear()

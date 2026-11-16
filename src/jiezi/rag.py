"""向量檢索：Qwen3-Embedding 為台灣知識庫段落建向量，查詢時「全文候選＋向量重排」（add-rag；開發計畫 5.1）。
Vector retrieval: Qwen3-Embedding vectors for the knowledge-base sections; queries use full-text candidates reranked
by cosine similarity (add-rag; dev plan 5.1).

不需要 numpy：全文索引先取最多 200 個候選，只對它們算相似度（約 20 萬次乘加）。
No numpy: the full-text index yields at most 200 candidates and only those are scored."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import urllib.request
from array import array
from pathlib import Path
from typing import Callable

from .errors import JieziError

EMBED_MODEL = "qwen3-embedding-0.6b-q8_0"
QUERY_INSTRUCT = ("Instruct: Given a question in Traditional Chinese, retrieve passages from a Taiwan knowledge base "
                  "that answer it\nQuery: ")
DOC_CHARS, CANDIDATES, BATCH = 800, 200, 16
DEFAULT_MIN = 0.5


def vectors_path(root: Path) -> Path:
    return root / "var" / "knowledge" / "vectors.sqlite"


def _norm(v: list[float]) -> array:
    s = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / s for x in v))


def cosine(a: array, b: array) -> float:
    return sum(x * y for x, y in zip(a, b))  # 都已正規化 / both normalized


class Embedder:
    """embedding 引擎：第一次用到才啟動，閒置後由 tick() 關閉。 / Started on first use, stopped by tick() when idle."""

    def __init__(self, engine_factory: Callable[[], object], log_path: Path | None = None, idle_s: float = 900,
                 clock=time.monotonic):
        self.factory, self.log_path, self.idle_s, self.clock = engine_factory, log_path, idle_s, clock
        self.engine, self.last = None, 0.0
        self.lock = threading.Lock()

    def _ensure(self):
        with self.lock:
            if self.engine is None:
                eng = self.factory()
                eng.start(self.log_path or Path("/dev/null"))
                self.engine = eng
            self.last = self.clock()
            return self.engine

    def embed(self, texts: list[str]) -> list[array]:
        eng = self._ensure()
        req = urllib.request.Request(f"{eng.base_url}/v1/embeddings", method="POST",
                                     data=json.dumps({"input": texts, "model": EMBED_MODEL}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())["data"]
        self.last = self.clock()
        return [_norm(d["embedding"]) for d in sorted(data, key=lambda d: d["index"])]

    def embed_query(self, text: str) -> array:
        return self.embed([QUERY_INSTRUCT + text[:500]])[0]

    def tick(self) -> None:
        with self.lock:
            if self.engine is not None and self.clock() - self.last > self.idle_s:
                self.stop_locked()

    def stop_locked(self) -> None:
        try:
            self.engine.stop()
        finally:
            self.engine = None

    def stop(self) -> None:
        with self.lock:
            if self.engine is not None:
                self.stop_locked()


class VectorStore:
    def __init__(self, path: Path, model_sha: str | None = None, create: bool = False):
        if not create and not path.exists():
            raise JieziError(f"{path} not found; run `scripts/jiezi knowledge embed`")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.executescript("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);"
                               "CREATE TABLE IF NOT EXISTS vecs(section INTEGER PRIMARY KEY, v BLOB);")
        old = dict(self.con.execute("SELECT k, v FROM meta")).get("model_sha")
        if model_sha and old and old != model_sha:  # 換了模型就重建 / a different model invalidates vectors
            self.con.execute("DELETE FROM vecs")
        if model_sha:
            self.con.execute("INSERT OR REPLACE INTO meta VALUES ('model_sha', ?)", (model_sha,))
        self.con.commit()

    def have(self) -> set[int]:
        return {r[0] for r in self.con.execute("SELECT section FROM vecs")}

    def put(self, items: list[tuple[int, array]]) -> None:
        self.con.executemany("INSERT OR REPLACE INTO vecs VALUES (?, ?)", [(i, v.tobytes()) for i, v in items])
        self.con.commit()

    def get(self, ids: list[int]) -> dict[int, array]:
        out = {}
        for chunk in range(0, len(ids), 500):
            part = ids[chunk:chunk + 500]
            q = f"SELECT section, v FROM vecs WHERE section IN ({','.join('?' * len(part))})"
            for sid, blob in self.con.execute(q, part):
                a = array("f")
                a.frombytes(blob)
                out[sid] = a
        return out

    def count(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM vecs").fetchone()[0]


def doc_text(section: dict) -> str:
    return f"{section['title']}｜{section['heading']}\n{section['text'][:DOC_CHARS]}"


def build(knowledge, store: VectorStore, embedder: Embedder, log=print) -> dict:
    """為還沒有向量的段落建向量，可中斷後續跑。 / Embed sections that lack vectors; resumable."""
    ids = [r[0] for r in knowledge.con.execute("SELECT id FROM sections ORDER BY id")]
    todo = [i for i in ids if i not in store.have()]
    t0 = time.monotonic()
    for n in range(0, len(todo), BATCH):
        batch = todo[n:n + BATCH]
        vecs = embedder.embed([doc_text(knowledge.section(i)) for i in batch])
        store.put(list(zip(batch, vecs)))
        if (n // BATCH) % 25 == 0:
            log(f"  {min(n + BATCH, len(todo))}/{len(todo)} ({time.monotonic() - t0:.0f}s)")
    return {"sections": len(ids), "embedded_now": len(todo), "total": store.count()}


class HybridRetriever:
    """全文候選＋向量重排；給 knowledge.grounding 用。 / Full-text candidates reranked by vectors."""

    def __init__(self, knowledge, store: VectorStore, embedder: Embedder, min_score: float = DEFAULT_MIN):
        self.k, self.store, self.embedder, self.min = knowledge, store, embedder, min_score

    def __call__(self, text: str, limit: int = 2) -> list[tuple[int, float]]:
        cands = self.k.candidates(text, CANDIDATES)
        if not cands:
            return []
        vecs = self.store.get(cands)
        if not vecs:
            return []
        q = self.embedder.embed_query(text)
        scored = sorted(((sid, cosine(q, v)) for sid, v in vecs.items()), key=lambda x: -x[1])
        return [(sid, s) for sid, s in scored[:limit] if s >= self.min]

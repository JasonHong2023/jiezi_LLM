"""向量檢索：Qwen3-Embedding 為知識庫段落與法規條文建向量（add-rag；開發計畫 5.1）。
Vector retrieval: Qwen3-Embedding vectors for knowledge sections and statutes (add-rag; dev plan 5.1).

不需要 numpy：記憶體只放截短到 256 維的向量（Qwen3-Embedding 支援 MRL），用 C 實作的 math.sumprod 全部掃描
（4.7 萬條約 0.4 秒），前 50 名再用完整 1024 維重排（2026-11-16：「酒駕」這類與條文用語不同的問題，全文候選撈不到）。
No numpy: 256-dim prefixes (MRL) are scanned with math.sumprod (47k items in about 0.4 s); the top 50 are reranked
with full vectors. Full-text candidates missed questions worded unlike the statutes."""

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
DOC_CHARS, CANDIDATES, BATCH, SCAN_DIM, RERANK = 800, 200, 16, 256, 50
DEFAULT_MIN = 0.5
# 重排序（add-reranker）：向量階段的前 N 名交給「問題＋段落一起讀」的模型重新排序
# Reranking: the top N of the vector stage are re-scored by a model that reads question and passage together
RERANK_MODEL, RERANK_TOP, RERANK_SLACK, RERANK_TIMEOUT_S = "qwen3-reranker-0.6b-q8_0", 20, 0.1, 10.0
# 自我檢查用的樣本（問題、相關、不相關）；已知有些 GGUF 轉檔分數都接近 0，分不開就停用
# Self-check samples (query, relevant, irrelevant): some GGUF conversions score everything near 0
RERANK_PROBES = (
    ("酒後開車會被怎麼處罰？", "駕駛人吐氣所含酒精濃度達每公升零點二五毫克以上而駕駛動力交通工具者，處三年以下有期徒刑。",
     "臺灣的珍珠奶茶起源於一九八〇年代的臺中與臺南茶店。"),
    ("玉山有多高？", "玉山主峰海拔三千九百五十二公尺，是臺灣的最高峰。", "勞工每日正常工作時間不得超過八小時。"),
    ("What is the capital of Taiwan?", "Taipei is the seat of the central government of Taiwan.",
     "Bubble sort repeatedly swaps adjacent elements that are out of order."),
)


def vectors_path(root: Path) -> Path:
    return root / "var" / "knowledge" / "vectors.sqlite"


def _norm(v: list[float]) -> array:
    s = math.sqrt(sum(x * x for x in v)) or 1.0
    return array("f", (x / s for x in v))


def cosine(a: array, b: array) -> float:
    return math.sumprod(a, b) if len(a) == len(b) else sum(x * y for x, y in zip(a, b))  # 都已正規化 / normalized


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


class Reranker(Embedder):
    """重排序引擎（R11 的 engine-rerank 埠）：延遲啟動、閒置卸載；第一次使用先自我檢查，沒過就停用。
    The reranking engine (R11 engine-rerank port): lazy start, idle stop; self-checked on first use and disabled
    when relevant and irrelevant passages cannot be told apart."""

    def __init__(self, engine_factory, log_path: Path | None = None, idle_s: float = 900, clock=time.monotonic,
                 timeout_s: float = RERANK_TIMEOUT_S):
        super().__init__(engine_factory, log_path, idle_s, clock)
        self.timeout_s, self.checked, self.note = timeout_s, None, "not checked yet"

    def _post(self, query: str, docs: list[str], timeout: float) -> list[float]:
        eng = self._ensure()
        req = urllib.request.Request(f"{eng.base_url}/v1/rerank", method="POST",
                                     data=json.dumps({"model": RERANK_MODEL, "query": query,
                                                      "documents": docs}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            results = json.loads(r.read())["results"]
        self.last = self.clock()
        out = [0.0] * len(docs)
        for item in results:
            out[item["index"]] = float(item["relevance_score"])
        return out

    def check(self) -> bool:
        """三組樣本都要「相關 > 不相關」而且分數有分開；結果記住，不重跑。
        Every probe must rank the relevant passage first with a real gap; the result is remembered."""
        if self.checked is None:
            try:
                gaps = []
                for q, good, bad in RERANK_PROBES:
                    a, b = self._post(q, [good, bad], 120)  # 含第一次載入模型 / includes the first model load
                    gaps.append(a - b)
                self.checked = all(g > 1e-3 for g in gaps)
                self.note = "ok" if self.checked else f"self-check failed (gaps {[round(g, 4) for g in gaps]}); disabled"
            except Exception as exc:  # noqa: BLE001 - 起不來就停用，不影響回答 / unusable means disabled
                self.checked, self.note = False, f"unavailable: {type(exc).__name__}: {exc}"
            if not self.checked:
                self.stop()
        return self.checked

    def score(self, query: str, docs: list[str]) -> list[float]:
        if not self.check():
            raise JieziError(f"reranker {self.note}")
        return self._post(query[:500], docs, self.timeout_s)


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

    def prefixes(self, dim: int = SCAN_DIM) -> tuple[list[int], list[array]]:
        """全部向量的前 dim 維（重新正規化），掃描用。 / Normalized dim-prefixes of all vectors, for scanning."""
        ids, vecs = [], []
        for sid, blob in self.con.execute("SELECT section, v FROM vecs ORDER BY section"):
            a = array("f")
            a.frombytes(blob[:dim * 4])
            ids.append(sid)
            vecs.append(_norm(list(a)))
        return ids, vecs


def doc_text(section: dict) -> str:
    return f"{section['title']}｜{section['heading']}\n{section['text'][:DOC_CHARS]}"


def build(knowledge, store: VectorStore, embedder: Embedder, log=print, ids: list[int] | None = None,
          text_of: Callable[[int], str] | None = None) -> dict:
    """為還沒有向量的項目建向量，可中斷後續跑；預設是知識庫段落。 / Embed missing items; resumable."""
    if ids is None:
        ids = [r[0] for r in knowledge.con.execute("SELECT id FROM sections ORDER BY id")]
        text_of = lambda i: doc_text(knowledge.section(i))  # noqa: E731
    todo = [i for i in ids if i not in store.have()]
    t0 = time.monotonic()
    for n in range(0, len(todo), BATCH):
        batch = todo[n:n + BATCH]
        vecs = embedder.embed([text_of(i) for i in batch])
        store.put(list(zip(batch, vecs)))
        if (n // BATCH) % 25 == 0:
            log(f"  {min(n + BATCH, len(todo))}/{len(todo)} ({time.monotonic() - t0:.0f}s)")
    return {"sections": len(ids), "embedded_now": len(todo), "total": store.count()}


class HybridRetriever:
    """截短向量全掃描 → 完整向量重排 → 門檻。 / Prefix scan, full rerank, threshold."""

    def __init__(self, knowledge, store: VectorStore, embedder: Embedder, min_score: float = DEFAULT_MIN,
                 reranker: "Reranker | None" = None, text_of: Callable[[int], str] | None = None,
                 top_n: int = RERANK_TOP):
        self.k, self.store, self.embedder, self.min = knowledge, store, embedder, min_score
        self.reranker, self.text_of, self.top_n = reranker, text_of, top_n
        self.last_error, self.reranked = None, 0
        self._ids, self._pref = store.prefixes()

    def __call__(self, text: str, limit: int = 2) -> list[tuple[int, float]]:
        if not self._ids:
            return []
        q = self.embedder.embed_query(text)
        qp = _norm(list(q[:SCAN_DIM]))
        top = sorted(zip(self._ids, (cosine(qp, v) for v in self._pref)), key=lambda x: -x[1])[:RERANK]
        full = self.store.get([i for i, _ in top])
        scored = sorted(((sid, cosine(q, v)) for sid, v in full.items()), key=lambda x: -x[1])
        if self.reranker is not None and self.text_of is not None and scored and scored[0][1] >= self.min:
            # 向量先判定「有相關段落」，再讓重排序在門檻附近的前 N 名裡挑；失敗或逾時就用向量排序
            # Vectors decide relevance exists; the reranker picks among the top N near the threshold; errors fall back
            cands = [(sid, s) for sid, s in scored[:self.top_n] if s >= self.min - RERANK_SLACK]
            if len(cands) > 1:
                try:
                    scores = self.reranker.score(text, [self.text_of(sid) for sid, _ in cands])
                    order = sorted(range(len(cands)), key=lambda i: -scores[i])
                    self.reranked += 1
                    return [cands[i] for i in order[:limit]]
                except Exception as exc:  # noqa: BLE001 - 重排序不可影響回答 / reranking never blocks an answer
                    self.last_error = f"{type(exc).__name__}: {exc}"
        return [(sid, s) for sid, s in scored[:limit] if s >= self.min]


def measure(knowledge, hybrid_plain: "HybridRetriever", hybrid_rerank: "HybridRetriever", n: int = 40, k: int = 3,
            seed: int = 20261117, log=print) -> dict:
    """A/B 量測（add-reranker 2.1）：從知識庫隨機抽段落，拿段落中間的一句話當問題，看該段落有沒有進前 k 名。
    這是「已知項目檢索」的合成題，只能比較有無重排序的相對差異，不代表真實問題的命中率。
    A/B measurement: a sentence from the middle of a random section is the query and the section is the target.
    Synthetic known-item retrieval: good for the relative difference only, not a real-question hit rate."""
    import random
    import re
    rng = random.Random(seed)
    ids = [r[0] for r in knowledge.con.execute("SELECT id FROM sections ORDER BY id")]
    rng.shuffle(ids)
    items = []
    for sid in ids:
        text = knowledge.section(sid)["text"][:DOC_CHARS]
        sents = [x.strip() for x in re.split(r"[。！？\n]", text) if 14 <= len(x.strip()) <= 60]
        if len(sents) >= 3:
            items.append((sid, sents[len(sents) // 2]))
        if len(items) >= n:
            break
    out = {"n": len(items), "k": k}
    for name, h in (("vector", hybrid_plain), ("rerank", hybrid_rerank)):
        hit, t0 = 0, time.monotonic()
        for sid, q in items:
            hit += sid in [i for i, _ in h(q, k)]
        out[name] = {"hit_at_k": round(hit / max(1, len(items)), 4),
                     "seconds_per_query": round((time.monotonic() - t0) / max(1, len(items)), 3)}
        log(f"  {name}: hit@{k} {out[name]['hit_at_k']:.1%}, {out[name]['seconds_per_query']} s/query")
    out["reranked_queries"], out["rerank_errors"] = hybrid_rerank.reranked, hybrid_rerank.last_error
    out["gain_points"] = round((out["rerank"]["hit_at_k"] - out["vector"]["hit_at_k"]) * 100, 1)
    out["extra_seconds"] = round(out["rerank"]["seconds_per_query"] - out["vector"]["seconds_per_query"], 3)
    return out

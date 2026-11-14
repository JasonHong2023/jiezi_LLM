"""來源下載（驗 SHA-256）與各格式解析為統一題目格式（規格 eval：Pinned Bank Sources；design D1、D2）。
Source download (SHA-256 verified) and parsing of each format into one item schema
(spec eval: Pinned Bank Sources; design D1, D2).

統一題目格式 / Item schema:
    {"id": 來源內唯一 ID, "source": 來源鍵, "task", "group", "scorer", "stratum": 分層值, "data": {...}}"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterator

from . import EvalError
from .bank import Source, SourceFile

USER_AGENT = "jiezi-eval/0.1 (research)"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _http_download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as fh:
        while chunk := r.read(1 << 16):
            fh.write(chunk)


def fetch(f: SourceFile, cache: Path, download: Callable[[str, Path], None] = _http_download) -> Path:
    """下載到快取並驗證 SHA-256；已存在且吻合就略過；不符就刪除並停止。
    Download into the cache and verify SHA-256; skip when present and valid; delete and stop on mismatch."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{f.sha256[:16]}-{f.name}"
    if path.exists() and sha256_file(path) == f.sha256:
        return path
    part = path.with_name(path.name + ".part")
    try:
        download(f.url, part)
        got = sha256_file(part)
        if got != f.sha256:
            raise EvalError(f"{f.name}: SHA-256 mismatch (got {got}, expected {f.sha256}); "
                            "the upstream file changed — not using it")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(path)
    return path


# ── 解析器 / Parsers ────────────────────────────────────────────────────────

def _item(src: Source, item_id: str, stratum: str, data: dict) -> dict:
    return {"id": item_id, "source": src.key, "task": src.task, "group": src.group,
            "scorer": src.scorer, "stratum": stratum, "data": data}


def _csv_rows(raw: bytes) -> list[dict]:
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


def parse_simpleqa(src: Source, paths: dict[str, Path]) -> Iterator[dict]:
    with paths[src.files[0].name].open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                yield _item(src, r["id"], r.get(src.stratify or "primary_category", ""),
                            {"question": r["question"], "answer": r["answer"],
                             "category": r.get("primary_category"), "subcategory": r.get("secondary_category")})


def _mc(src: Source, subject: str, row_id: str, q: str, row: dict, answer: str) -> dict:
    return _item(src, f"{subject}/{row_id}", subject,
                 {"subject": subject, "question": q, "choices": {k: row[k] for k in "ABCD"}, "answer": answer.strip()})


def parse_ceval_zip(src: Source, paths: dict[str, Path]) -> Iterator[dict]:
    """C-Eval val 分割（test 沒有公開答案，design D3）。 / C-Eval val split (test has no public answers)."""
    with zipfile.ZipFile(paths[src.files[0].name]) as z:
        for name in sorted(n for n in z.namelist() if n.startswith("val/") and n.endswith(".csv")):
            subject = Path(name).stem.removesuffix("_val")
            for row in _csv_rows(z.read(name)):
                yield _mc(src, subject, row["id"], row["question"], row, row["answer"])


def parse_cmmlu_zip(src: Source, paths: dict[str, Path]) -> Iterator[dict]:
    with zipfile.ZipFile(paths[src.files[0].name]) as z:
        for name in sorted(n for n in z.namelist() if n.startswith("test/") and n.endswith(".csv")):
            subject = Path(name).stem
            for row in _csv_rows(z.read(name)):
                yield _mc(src, subject, row[""], row["Question"], row, row["Answer"])


def parse_evalplus(src: Source, paths: dict[str, Path]) -> Iterator[dict]:
    """保留驗證器需要的全部欄位。 / Keep every field the verifiers will need."""
    with gzip.open(paths[src.files[0].name], "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                yield _item(src, r["task_id"], "", r)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_acebench(src: Source, paths: dict[str, Path]) -> Iterator[dict]:
    """ACEBench 每個類別兩個檔：題目與標準答案，以 id 對應。
    Each ACEBench category has a question file and an answer file, joined by id."""
    for f in src.files:
        if not f.name.startswith("data_"):
            continue
        category = f.name.removeprefix("data_").removesuffix(".json")
        answers = {a["id"]: a["ground_truth"] for a in _jsonl(paths[f"answer_{category}.json"])}
        for r in _jsonl(paths[f.name]):
            if r["id"] not in answers:
                raise EvalError(f"acebench {category}: no ground truth for {r['id']}")
            yield _item(src, r["id"], category,
                        {"category": category, "question": r["question"], "functions": r["function"],
                         "ground_truth": answers[r["id"]]})


PARSERS: dict[str, Callable[[Source, dict[str, Path]], Iterator[dict]]] = {
    "simpleqa_jsonl": parse_simpleqa,
    "ceval_zip": parse_ceval_zip,
    "cmmlu_zip": parse_cmmlu_zip,
    "evalplus_jsonl_gz": parse_evalplus,
    "acebench_jsonl": parse_acebench,
}


def load_items(src: Source, cache: Path, download=_http_download) -> list[dict]:
    """下載（或使用快取）並解析一個檔案型來源。 / Fetch (or reuse the cache) and parse one file-based source."""
    parser = PARSERS.get(src.format)
    if parser is None:
        raise EvalError(f"{src.key}: no parser for format {src.format!r}")
    paths = {f.name: fetch(f, cache, download) for f in src.files}
    items = list(parser(src, paths))
    ids = [i["id"] for i in items]
    if len(ids) != len(set(ids)):
        raise EvalError(f"{src.key}: duplicate item ids")
    return items

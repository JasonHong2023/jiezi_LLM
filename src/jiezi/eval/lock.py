"""分層抽題、鎖定檔產生與驗證、題庫實體化（規格 eval：Reproducible Bank Lock、Bank Composition；design D2）。
Stratified sampling, lock generation and verification, and bank materialization
(spec eval: Reproducible Bank Lock, Bank Composition; design D2).

重現性來自鎖定檔（記錄抽中的 ID 與內容雜湊），不依賴亂數演算法在不同 Python 版本間一致。
Reproducibility comes from the lock (selected IDs and content hashes), not from the RNG staying
identical across Python versions."""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Callable

from . import EvalError, sources, wiki
from .bank import MIN_PER_TASK, TASKS, Bank, Source


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def item_hash(item: dict) -> str:
    return hashlib.sha256(canonical(item)).hexdigest()


def stratified_order(items: list[dict], seed: int, key: str) -> list[dict]:
    """依層輪流排序全部候選：各層內洗牌，層的順序也洗牌；取前 N 個即為分層平均抽樣。
    Order all candidates round-robin across shuffled strata (each shuffled internally);
    the first N form an evenly stratified sample."""
    rng = random.Random(f"{seed}:{key}")
    strata: dict[str, list[dict]] = defaultdict(list)
    for it in sorted(items, key=lambda i: i["id"]):
        strata[str(it.get("stratum") or "")].append(it)
    names = sorted(strata)
    rng.shuffle(names)
    for n in names:
        rng.shuffle(strata[n])
    order: list[dict] = []
    depth = 0
    while len(order) < len(items):
        for n in names:
            if depth < len(strata[n]):
                order.append(strata[n][depth])
        depth += 1
    return order


def bank_hash(lock_sources: list[dict]) -> str:
    lines = [f"{s['key']}\t{i['id']}\t{i['sha256']}" for s in lock_sources for i in s["items"]]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def definition_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wiki_for(src: Source, get=None) -> wiki.Wiki:
    kw = {"get": get} if get else {}
    return wiki.Wiki(src.options["site"], src.options.get("variant", "zh-tw"), **kw)


def _lock_wiki(src: Source, bank_seed: int, w: wiki.Wiki, log) -> tuple[list[dict], list[dict]]:
    order = stratified_order(wiki.population(src, w), bank_seed, src.key)
    picked, items, skipped = [], [], []
    for start in range(0, len(order), 50):
        if len(picked) >= src.count:
            break
        batch = order[start:start + 50]
        revids = w.latest_revids([c["id"] for c in batch])
        for cand in batch:
            if len(picked) >= src.count:
                break
            title = cand["id"]
            if title not in revids:
                skipped.append({"id": title, "reason": "missing"})
                continue
            try:
                item = wiki.materialize(src, w, title, revids[title], cand["stratum"])
            except EvalError as exc:
                skipped.append({"id": title, "reason": str(exc)})
                continue
            items.append(item)
            picked.append({"id": title, "revid": revids[title], "stratum": cand["stratum"], "sha256": item_hash(item)})
            log(f"  {src.key}: {len(picked)}/{src.count} {title}")
    return picked, items, skipped


def build_lock(bank: Bank, definition: Path, cache: Path, download=sources._http_download,
               wiki_get=None, log: Callable[[str], None] = print) -> tuple[dict, list[dict]]:
    """依種子抽題並產生鎖定檔內容；回傳 (lock, 題目)。
    Sample by seed and build the lock content; return (lock, items)."""
    lock_sources, all_items = [], []
    for src in bank.sources:
        if src.format == "wiki_featured":
            picked, items, skipped = _lock_wiki(src, bank.seed, _wiki_for(src, wiki_get), log)
        else:
            chosen = stratified_order(sources.load_items(src, cache, download), bank.seed, src.key)[:src.count]
            picked = [{"id": i["id"], "sha256": item_hash(i)} for i in chosen]
            items, skipped = chosen, []
            log(f"  {src.key}: {len(picked)}/{src.count}")
        if len(picked) < src.count:
            raise EvalError(f"{src.key}: only {len(picked)} of {src.count} items available")
        entry = {"key": src.key, "items": picked}
        if skipped:
            entry["skipped"] = skipped
        lock_sources.append(entry)
        all_items.extend(items)
    check_composition(bank, lock_sources)
    lock = {"bank": bank.name, "version": bank.version, "seed": bank.seed,
            "definition_sha256": definition_hash(definition), "created": date.today().isoformat(),
            "sources": lock_sources, "bank_hash": bank_hash(lock_sources)}
    return lock, all_items


def check_composition(bank: Bank, lock_sources: list[dict]) -> None:
    by_key = {s.key: s for s in bank.sources}
    per_task = {t: 0 for t in TASKS}
    for entry in lock_sources:
        per_task[by_key[entry["key"]].task] += len(entry["items"])
    short = [f"{t}={n}" for t, n in per_task.items() if n < MIN_PER_TASK]
    if short:
        raise EvalError(f"lock has too few items per task type: {', '.join(short)}")


def materialize(bank: Bank, lock: dict, definition: Path, cache: Path, download=sources._http_download,
                wiki_get=None, log: Callable[[str], None] = print) -> list[dict]:
    """依鎖定檔取得題目並逐題驗證雜湊；任何不符都停止。
    Materialize items from the lock and verify every hash; stop on any mismatch."""
    if lock.get("definition_sha256") != definition_hash(definition):
        raise EvalError(f"{definition} changed since the lock was made; run `scripts/eval bank lock` "
                        "to create a new bank version")
    if bank_hash(lock["sources"]) != lock.get("bank_hash"):
        raise EvalError("lock file is internally inconsistent (bank_hash does not match its items)")
    by_key = {s.key: s for s in bank.sources}
    items, mismatched = [], []
    for entry in lock["sources"]:
        src = by_key.get(entry["key"])
        if src is None:
            raise EvalError(f"lock source {entry['key']!r} is not in {definition}")
        if src.format == "wiki_featured":
            w = _wiki_for(src, wiki_get)
            got = {}
            for it in entry["items"]:
                got[it["id"]] = wiki.materialize(src, w, it["id"], it["revid"], it.get("stratum"))
        else:
            got = {i["id"]: i for i in sources.load_items(src, cache, download)}
        for it in entry["items"]:
            item = got.get(it["id"])
            if item is None or item_hash(item) != it["sha256"]:
                mismatched.append(f"{entry['key']}/{it['id']}")
            else:
                items.append(item)
        log(f"  {entry['key']}: {len(entry['items'])} items")
    if mismatched:
        raise EvalError("items differ from the lock (not evaluating different items):\n  "
                        + "\n  ".join(mismatched[:20]) + (f"\n  … and {len(mismatched) - 20} more" if len(mismatched) > 20 else ""))
    return items


def write_items(items: list[dict], path: Path, lock: dict) -> None:
    """題目快取：第一行是 bank_hash 標頭，其後每行一題。 / Item cache: a bank_hash header line, then one item per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"bank": lock["bank"], "bank_hash": lock["bank_hash"]}) + "\n")
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")


def read_items(path: Path, lock: dict) -> list[dict] | None:
    """快取存在且 bank_hash 相符、逐題雜湊也相符時回傳題目，否則回傳 None。
    Return cached items when the header and every item hash match the lock; otherwise None."""
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or json.loads(lines[0]).get("bank_hash") != lock["bank_hash"]:
        return None
    items = [json.loads(line) for line in lines[1:] if line.strip()]
    expected = [(s["key"], i["id"], i["sha256"]) for s in lock["sources"] for i in s["items"]]
    actual = [(i["source"], i["id"], item_hash(i)) for i in items]
    return items if actual == expected else None

"""抽題與鎖定檔測試（規格 eval：Reproducible Bank Lock、Bank Composition）。
Tests for sampling and the lock file."""

import hashlib
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError, lock  # noqa: E402
from jiezi.eval.bank import Bank, Source, SourceFile  # noqa: E402

QUIET = lambda *_: None  # noqa: E731


def simpleqa_lines(n, cats=("甲", "乙", "丙")):
    rows = [{"id": f"q{i:03d}", "primary_category": cats[i % len(cats)], "question": f"問{i}", "answer": f"答{i}"}
            for i in range(n)]
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()


class Env:
    def __init__(self, d: Path, n_per_task=60):
        self.d = d
        d.mkdir(parents=True, exist_ok=True)
        self.blobs = {}
        srcs = []
        for task in ("qa", "code", "summary", "tool"):
            content = simpleqa_lines(n_per_task)
            url = f"https://example.invalid/{task}.jsonl"
            self.blobs[url] = content
            srcs.append(Source(key=f"s-{task}", license_key="x", task=task, group="knowledge",
                               scorer="simpleqa_approx", format="simpleqa_jsonl", count=50,
                               stratify="primary_category",
                               files=(SourceFile(f"{task}.jsonl", url, hashlib.sha256(content).hexdigest()),)))
        self.bank = Bank(name="t", version=1, seed=7, sources=tuple(srcs))
        self.definition = d / "t.toml"
        self.definition.write_text("definition v1")
        self.cache = d / "cache"

    def download(self, url, dest):
        dest.write_bytes(self.blobs[url])


class TestOrder(unittest.TestCase):
    def test_even_strata_and_deterministic(self):
        items = [{"id": f"i{i}", "stratum": "abc"[i % 3]} for i in range(30)]
        a = lock.stratified_order(items, 1, "k")
        b = lock.stratified_order(list(reversed(items)), 1, "k")
        self.assertEqual([i["id"] for i in a], [i["id"] for i in b])  # 與輸入順序無關 / input order irrelevant
        self.assertEqual(Counter(i["stratum"] for i in a[:9]), {"a": 3, "b": 3, "c": 3})
        self.assertNotEqual([i["id"] for i in a], [i["id"] for i in lock.stratified_order(items, 2, "k")])

    def test_uneven_strata_use_everything(self):
        items = [{"id": "x1", "stratum": "x"}] + [{"id": f"y{i}", "stratum": "y"} for i in range(5)]
        self.assertEqual(len(lock.stratified_order(items, 1, "k")), 6)


class TestLock(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.env = Env(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def build(self):
        return lock.build_lock(self.env.bank, self.env.definition, self.env.cache, self.env.download, log=QUIET)

    def test_build_and_materialize_round_trip(self):
        lk, items = self.build()
        self.assertEqual(sum(len(s["items"]) for s in lk["sources"]), 200)
        again = lock.materialize(self.env.bank, lk, self.env.definition, self.env.cache, self.env.download, log=QUIET)
        self.assertEqual([lock.item_hash(i) for i in again], [lock.item_hash(i) for i in items])
        self.assertEqual(lk, self.build()[0] | {"created": lk["created"]})  # 重建結果相同 / rebuild is identical

    def test_definition_change_requires_new_lock(self):
        lk, _ = self.build()
        self.env.definition.write_text("definition v2")
        with self.assertRaisesRegex(EvalError, "changed since the lock"):
            lock.materialize(self.env.bank, lk, self.env.definition, self.env.cache, self.env.download, log=QUIET)

    def test_item_content_mismatch_stops(self):
        lk, _ = self.build()
        lk["sources"][0]["items"][0]["sha256"] = "0" * 64
        lk["bank_hash"] = lock.bank_hash(lk["sources"])
        with self.assertRaisesRegex(EvalError, "items differ from the lock"):
            lock.materialize(self.env.bank, lk, self.env.definition, self.env.cache, self.env.download, log=QUIET)

    def test_tampered_lock_detected(self):
        lk, _ = self.build()
        lk["sources"][0]["items"].pop()
        with self.assertRaisesRegex(EvalError, "internally inconsistent"):
            lock.materialize(self.env.bank, lk, self.env.definition, self.env.cache, self.env.download, log=QUIET)

    def test_too_few_items(self):
        small = Env(Path(self._tmp.name) / "small", n_per_task=40)
        with self.assertRaisesRegex(EvalError, "only 40 of 50"):
            lock.build_lock(small.bank, small.definition, small.cache, small.download, log=QUIET)

    def test_item_cache(self):
        lk, items = self.build()
        p = Path(self._tmp.name) / "items.jsonl"
        lock.write_items(items, p, lk)
        self.assertEqual(len(lock.read_items(p, lk)), 200)
        other = dict(lk, bank_hash="different")
        self.assertIsNone(lock.read_items(p, other))


if __name__ == "__main__":
    unittest.main()

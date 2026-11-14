"""來源下載與解析測試（本機迷你樣本，不連網）。 / Source download and parser tests (local mini fixtures, no network)."""

import gzip
import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError, sources  # noqa: E402
from jiezi.eval.bank import Source, SourceFile  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Fixture:
    """在暫存目錄建立假的「遠端檔案」，以 file 名稱當 URL。 / Fake remote files keyed by URL."""

    def __init__(self, d: Path):
        self.d = d
        self.blobs: dict[str, bytes] = {}

    def add(self, name: str, content: bytes) -> SourceFile:
        url = f"https://example.invalid/{name}"
        self.blobs[url] = content
        return SourceFile(name, url, sha(content))

    def download(self, url, dest):
        dest.write_bytes(self.blobs[url])


def src(key, fmt, files, task="qa", stratify=None):
    return Source(key=key, license_key="x", task=task, group="knowledge", scorer="multiple_choice",
                  format=fmt, count=1, stratify=stratify, files=tuple(files))


def zipped(entries: dict[str, str]) -> bytes:
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, t in entries.items():
            z.writestr(n, t.encode("utf-8-sig"))
    return buf.getvalue()


class TestSources(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.fx = Fixture(self.dir)
        self.cache = self.dir / "cache"

    def tearDown(self):
        self._tmp.cleanup()

    def load(self, s):
        return sources.load_items(s, self.cache, self.fx.download)

    def test_simpleqa(self):
        line = {"id": "q1", "primary_category": "社会", "secondary_category": "x", "question": "問?", "answer": "答"}
        f = self.fx.add("sq.jsonl", (json.dumps(line, ensure_ascii=False) + "\n").encode())
        items = self.load(src("sq", "simpleqa_jsonl", [f], stratify="primary_category"))
        self.assertEqual(items[0]["stratum"], "社会")
        self.assertEqual(items[0]["data"]["answer"], "答")

    def test_ceval_uses_val_only(self):
        f = self.fx.add("c.zip", zipped({
            "val/law_val.csv": "id,question,A,B,C,D,answer\n0,題,a,b,c,d,B\n",
            "test/law_test.csv": "id,question,A,B,C,D\n0,題,a,b,c,d\n",
        }))
        items = self.load(src("ce", "ceval_zip", [f]))
        self.assertEqual([i["id"] for i in items], ["law/0"])
        self.assertEqual(items[0]["data"]["answer"], "B")
        self.assertEqual(items[0]["data"]["choices"]["D"], "d")

    def test_cmmlu_unnamed_index_column(self):
        f = self.fx.add("m.zip", zipped({"test/logical.csv": ",Question,A,B,C,D,Answer\n7,題,a,b,c,d,C\n",
                                         "dev/logical.csv": ",Question,A,B,C,D,Answer\n0,x,a,b,c,d,A\n"}))
        items = self.load(src("cm", "cmmlu_zip", [f]))
        self.assertEqual([(i["id"], i["stratum"]) for i in items], [("logical/7", "logical")])

    def test_evalplus_keeps_fields(self):
        rec = {"task_id": "HumanEval/0", "prompt": "def f():", "entry_point": "f", "plus_input": [[1]]}
        f = self.fx.add("he.jsonl.gz", gzip.compress((json.dumps(rec) + "\n").encode()))
        items = self.load(src("he", "evalplus_jsonl_gz", [f], task="code"))
        self.assertEqual(items[0]["data"]["plus_input"], [[1]])

    def test_acebench_join(self):
        q = {"id": "a_0", "question": "user: 查", "function": [{"name": "f"}]}
        a = {"id": "a_0", "ground_truth": {"f": {"x": 1}}}
        files = [self.fx.add("data_cat.json", (json.dumps(q, ensure_ascii=False) + "\n").encode()),
                 self.fx.add("answer_cat.json", (json.dumps(a) + "\n").encode())]
        items = self.load(src("ace", "acebench_jsonl", files, task="tool"))
        self.assertEqual(items[0]["data"]["ground_truth"], {"f": {"x": 1}})
        self.assertEqual(items[0]["stratum"], "cat")

    def test_sha_mismatch_deletes_and_stops(self):
        f = self.fx.add("sq.jsonl", b"{}\n")
        bad = SourceFile(f.name, f.url, "0" * 64)
        with self.assertRaisesRegex(EvalError, "SHA-256 mismatch"):
            sources.fetch(bad, self.cache, self.fx.download)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_cache_hit_does_not_download(self):
        f = self.fx.add("x.bin", b"abc")
        sources.fetch(f, self.cache, self.fx.download)

        def boom(*_):
            raise AssertionError("downloaded twice")
        sources.fetch(f, self.cache, boom)

    def test_unknown_format(self):
        with self.assertRaisesRegex(EvalError, "no parser"):
            self.load(src("x", "parquet", []))


if __name__ == "__main__":
    unittest.main()

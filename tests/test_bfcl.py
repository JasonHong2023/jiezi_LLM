"""BFCL 資料解析與 checker 測試（迷你樣本，不連網）。 / Offline BFCL parser and checker tests."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import sources  # noqa: E402
from jiezi.eval.bank import Source, SourceFile  # noqa: E402
from jiezi.verify import bfcl  # noqa: E402


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Fixture:
    def __init__(self, d: Path):
        self.d = d
        self.blobs: dict[str, bytes] = {}

    def add(self, name: str, content: bytes) -> SourceFile:
        url = f"https://example.invalid/{name}"
        self.blobs[url] = content
        return SourceFile(name, url, sha(content))

    def download(self, url, dest):
        dest.write_bytes(self.blobs[url])


def source(files) -> Source:
    return Source(key="bfcl", license_key="x", task="tool", group="reasoning", scorer="pending_verifier",
                  format="bfcl_jsonl", count=1, stratify="category", files=tuple(files))


def item(category, functions, ground_truth, item_id="bfcl_0") -> dict:
    return {"id": item_id, "source": "bfcl", "stratum": category,
            "data": {"category": category, "question": [[{"role": "user", "content": "hi"}]],
                     "functions": functions, "ground_truth": ground_truth}}


CALC = {"name": "math_calculate", "description": "算",
        "parameters": {"type": "dict", "properties": {
            "base": {"type": "integer"}, "height": {"type": "integer"}},
            "required": ["base", "height"]}}


class TestBfcl(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.fx = Fixture(self.dir)
        self.cache = self.dir / "cache"

    def tearDown(self):
        self._tmp.cleanup()

    def test_parse_normalizes_dotted_names_and_joins_answers(self):
        data = {"id": "simple_0", "question": [[{"role": "user", "content": "算"}]],
                "function": [{"name": "math.calculate", "description": "算", "parameters": CALC["parameters"]}]}
        answer = {"id": "simple_0", "ground_truth": [{"math.calculate": {"base": [10], "height": [5]}}]}
        files = [self.fx.add("bfcl-data-simple_python.json",
                             (json.dumps(data, ensure_ascii=False) + "\n").encode()),
                 self.fx.add("bfcl-answer-simple_python.json",
                             (json.dumps(answer, ensure_ascii=False) + "\n").encode())]
        items = sources.load_items(source(files), self.cache, self.fx.download)
        self.assertEqual(items[0]["data"]["functions"][0]["name"], "math_calculate")
        self.assertEqual(items[0]["data"]["ground_truth"],
                         [{"math_calculate": {"base": [10], "height": [5]}}])
        self.assertEqual(items[0]["stratum"], "simple_python")

    def test_parse_irrelevance_without_answer_file(self):
        data = {"id": "irrelevance_0", "question": [[{"role": "user", "content": "hi"}]], "function": [CALC]}
        f = self.fx.add("bfcl-data-irrelevance.json", (json.dumps(data, ensure_ascii=False) + "\n").encode())
        items = sources.load_items(source([f]), self.cache, self.fx.download)
        self.assertEqual(items[0]["data"]["ground_truth"], [])

    def test_simple_checker(self):
        it = item("simple_python", [CALC], [{"math_calculate": {"base": [10], "height": [5]}}])
        ok = bfcl.verify(it, "[math_calculate(base=10, height=5)]")
        bad = bfcl.verify(it, "[math_calculate(base=11, height=5)]")
        self.assertEqual((ok["status"], bad["status"]), ("correct", "wrong"))
        self.assertEqual(bad["details"]["error_type"], "value_error:others")

    def test_multiple_checker_uses_the_ground_truth_function(self):
        alt = {"name": "other_calculate", "description": "其他",
               "parameters": {"type": "dict", "properties": {"x": {"type": "integer"}}, "required": ["x"]}}
        it = item("multiple", [alt, CALC], [{"math_calculate": {"base": [10], "height": [5]}}])
        r = bfcl.verify(it, "[math_calculate(base=10, height=5)]")
        self.assertEqual(r["status"], "correct")

    def test_parallel_checker_is_order_independent(self):
        play = {"name": "spotify_play", "description": "播",
                "parameters": {"type": "dict", "properties": {
                    "artist": {"type": "string"}, "duration": {"type": "integer"}},
                    "required": ["artist", "duration"]}}
        gt = [{"spotify_play": {"artist": ["Maroon 5"], "duration": [15]}},
              {"spotify_play": {"artist": ["Taylor Swift"], "duration": [20]}}]
        it = item("parallel", [play], gt)
        r = bfcl.verify(it, "[spotify_play(artist='Taylor Swift', duration=20), "
                            "spotify_play(artist='Maroon 5', duration=15)]")
        self.assertEqual(r["status"], "correct")
        self.assertEqual(bfcl.verify(it, "[spotify_play(artist='Taylor Swift', duration=20)]")["status"], "wrong")

    def test_irrelevance_needs_no_call(self):
        it = item("irrelevance", [CALC], [])
        self.assertEqual(bfcl.verify(it, "", no_call=True)["status"], "correct")
        self.assertEqual(bfcl.verify(it, "[]", no_call=False)["status"], "wrong")
        self.assertEqual(bfcl.verify(it, "[]", no_call=False)["details"]["error_type"], "irrelevance:unexpected_call")

    def test_unknown_type_is_wrong_not_a_crash(self):
        bad = {"name": "f", "parameters": {"type": "dict", "properties": {
            "x": {"type": "mystery"}}, "required": ["x"]}}
        it = item("simple_python", [bad], [{"f": {"x": [1]}}])
        r = bfcl.verify(it, "[f(x=1)]")
        self.assertEqual((r["status"], r["details"]["error_type"]), ("wrong", "unsupported_type"))


if __name__ == "__main__":
    unittest.main()

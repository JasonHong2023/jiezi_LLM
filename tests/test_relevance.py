"""知識庫相關度門檻量測（tune-knowledge-relevance）。 / Relevance threshold measurement."""
import json
import sys
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jiezi import rag  # noqa: E402


class FakeStore:
    """三段：1 珍奶（向量 [1,0]）、2 夜市（[0.8,0.6]）、3 玉山（[0,1]）。 / Three sections."""
    vecs = {1: [1.0, 0.0], 2: [0.8, 0.6], 3: [0.0, 1.0]}

    def prefixes(self):
        return list(self.vecs), [array("f", v) for v in self.vecs.values()]

    def get(self, ids):
        return {i: array("f", self.vecs[i]) for i in ids}


class FakeEmbedder:
    q = {"粉圓飲料": [1.0, 0.05], "說個笑話": [0.6, 0.8], "高山": [0.05, 1.0]}

    def embed_query(self, text):
        v = self.q[text]
        n = sum(x * x for x in v) ** 0.5
        return array("f", [x / n for x in v])


class FakeKnowledge:
    names = {1: "珍珠奶茶", 2: "夜市文化", 3: "玉山"}

    def articles_named(self, q):
        return [1] if "珍珠奶茶" in q else []

    def retrieve(self, q, hybrid):
        return [{"name": "珍珠奶茶"}]

    def section(self, sid):
        return {"name": self.names[sid]}


class TestRelevance(unittest.TestCase):
    def test_attach_rules(self):
        scored = [(1, 0.9), (2, 0.7), (3, 0.2)]
        self.assertEqual(rag._attach(scored, None, 0.8, 2), [1])
        self.assertEqual(rag._attach(scored, None, 0.5, 2), [1, 2])
        self.assertEqual(rag._attach(scored, {1: 0.1, 2: 0.9}, 0.75, 2), [2, 1])   # 重排序 / reranked
        self.assertEqual(rag._attach(scored, {1: 0.1, 2: 0.9}, 0.95, 2), [])

    def test_grid_and_best(self):
        rows = [{"q": "粉圓飲料", "expect": ["珍珠奶茶"], "kind": "on"},
                {"q": "說個笑話", "expect": [], "kind": "off"},
                {"q": "高山", "expect": ["玉山"], "kind": "on"},
                {"q": "珍珠奶茶是什麼", "expect": ["珍珠奶茶"], "kind": "real"},
                {"q": "說個笑話", "expect": [], "kind": "real", "unsure": True}]
        res = rag.relevance(FakeKnowledge(), FakeStore(), FakeEmbedder(), rows, [0.5, 0.95], log=lambda *_: None)
        g = {x["threshold"]: x for x in res["grid"]}
        # 0.5：笑話（與夜市 cos≈0.96）被附上 → 不該附卻附了 100%；0.95 擋掉笑話以外的弱命中
        self.assertEqual((g[0.5]["on_hit"], g[0.5]["false_attach"]), (1.0, 1.0))
        self.assertEqual(g[0.95]["on_n"], 3)
        self.assertEqual(g[0.95]["off_n"], 1)                                      # unsure 不計 / unsure skipped
        self.assertEqual(res["best"], None if g[0.95]["false_attach"] > rag.FALSE_ATTACH_MAX else res["best"])
        self.assertEqual(res["questions"][3]["named"], ["珍珠奶茶"])

    def test_question_set(self):
        rows = [json.loads(x) for x in rag.RELEVANCE_SET.read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertGreaterEqual(len(rows), 200)
        self.assertEqual({r["kind"] for r in rows}, {"real", "on", "off"})
        self.assertTrue(all(r["expect"] for r in rows if r["kind"] == "on"))
        self.assertFalse(any(r["expect"] for r in rows if r["kind"] == "off"))


if __name__ == "__main__":
    unittest.main()

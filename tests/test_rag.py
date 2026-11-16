"""向量檢索測試：向量庫存取、可續跑建置、候選重排與門檻、出錯退回全文。 / Vector retrieval tests."""

import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import rag  # noqa: E402


class FakeEmbedder:
    """以關鍵字決定向量方向：玉山、颱風、其他。 / Direction by keyword."""

    def __init__(self):
        self.calls = 0

    def _v(self, t, query):
        # 段落與問題各有一個專屬維度，只有關鍵字相同才會相似 / similar only through shared keywords
        return rag._norm([1.0 if "玉山" in t or "最高" in t else 0.0, 1.0 if "颱風" in t else 0.0,
                          0.0 if query else 1.0, 1.0 if query else 0.0])

    def embed(self, texts):
        self.calls += 1
        return [self._v(t, False) for t in texts]

    def embed_query(self, text):
        return self._v(text, True)


class TestRag(unittest.TestCase):
    def setUp(self):
        from test_knowledge import TestKnowledge
        self.t = TestKnowledge("test_parse_and_index")
        self.t.setUp()
        self.k = self.t.built()
        self.store = rag.VectorStore(Path(self.t.root) / "vec.sqlite", model_sha="x", create=True)

    def tearDown(self):
        self.t.tearDown()

    def test_store_and_resumable_build(self):
        emb = FakeEmbedder()
        r1 = rag.build(self.k, self.store, emb, log=lambda *_: None)
        r2 = rag.build(self.k, self.store, emb, log=lambda *_: None)
        self.assertEqual((r1["embedded_now"], r2["embedded_now"], r2["total"]), (3, 0, 3))
        v = self.store.get([1])[1]
        self.assertAlmostEqual(sum(x * x for x in v), 1.0, places=5)
        rag.VectorStore(Path(self.t.root) / "vec.sqlite", model_sha="other")  # 換模型清空 / new model clears
        self.assertEqual(self.store.count(), 0)

    def test_hybrid_threshold_and_fallback(self):
        emb = FakeEmbedder()
        rag.build(self.k, self.store, emb, log=lambda *_: None)
        h = rag.HybridRetriever(self.k, self.store, emb, min_score=0.9)
        self.assertEqual(h("尾牙 職工 刈包"), [])                          # 都不像 / nothing similar enough
        self.assertEqual(self.k.retrieve("尾牙 職工 慰勞的意義", h), [])     # 向量說沒有就不附 / no grounding

        def broken(text, limit):
            raise RuntimeError("engine down")
        hits = self.k.retrieve("尾牙為什麼要吃虎咬豬慰勞職工", broken)      # 出錯退回全文 / full-text fallback
        self.assertEqual(hits[0]["heading"], "尾牙與職工")

    def test_cosine(self):
        a = rag._norm([3.0, 4.0])
        self.assertAlmostEqual(rag.cosine(a, a), 1.0, places=6)
        self.assertIsInstance(a, array)


class TestEmbedderLifecycle(unittest.TestCase):
    def test_lazy_start_and_idle_stop(self):
        events, now = [], [0.0]

        class Eng:
            base_url = "http://x"

            def start(self, log_path):
                events.append("start")

            def stop(self):
                events.append("stop")
        e = rag.Embedder(lambda: Eng(), idle_s=10, clock=lambda: now[0])
        e._ensure()
        e._ensure()
        now[0] = 5
        e.tick()
        now[0] = 20
        e.tick()
        self.assertEqual(events, ["start", "stop"])


if __name__ == "__main__":
    unittest.main()

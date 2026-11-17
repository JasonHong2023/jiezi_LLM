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

    def test_rerank_reorders_and_falls_back(self):
        emb = FakeEmbedder()
        rag.build(self.k, self.store, emb, log=lambda *_: None)
        text_of = lambda i: rag.doc_text(self.k.section(i))  # noqa: E731
        plain = rag.HybridRetriever(self.k, self.store, emb, min_score=-1.0)("尾牙 職工", 3)
        self.assertEqual(len(plain), 3)

        class Fake:
            def __init__(self, fail=False):
                self.fail, self.calls = fail, []

            def score(self, query, docs):
                self.calls.append((query, docs))
                if self.fail:
                    raise TimeoutError("slow")
                return [float(i) for i in range(len(docs))]  # 把向量順序反過來 / reverse the vector order
        rr = Fake()
        h = rag.HybridRetriever(self.k, self.store, emb, min_score=-1.0, reranker=rr, text_of=text_of)
        got = h("尾牙 職工", 3)
        self.assertEqual([i for i, _ in got], [i for i, _ in reversed(plain)])
        self.assertEqual(len(rr.calls[0][1]), 3)
        self.assertIn("｜", rr.calls[0][1][0])                               # 段落文字含標題 / title-prefixed text
        self.assertEqual(h("尾牙 職工", 1), got[:1])                         # 取前 k / top k after reranking
        bad = rag.HybridRetriever(self.k, self.store, emb, min_score=-1.0, reranker=Fake(fail=True), text_of=text_of)
        self.assertEqual(bad("尾牙 職工", 3), plain)                         # 逾時退回向量排序 / timeout falls back
        self.assertIn("TimeoutError", bad.last_error)
        gate = Fake()                                                        # 向量說沒有相關就不重排 / gate stays
        self.assertEqual(rag.HybridRetriever(self.k, self.store, emb, min_score=0.99, reranker=gate,
                                             text_of=text_of)("完全無關的問題", 3), [])
        self.assertEqual(gate.calls, [])

    def test_reranker_self_check_disables_a_bad_model(self):
        class Engine:
            base_url = "http://127.0.0.1:1"

            def __init__(self):
                self.stopped = False

            def start(self, log):
                pass

            def stop(self):
                self.stopped = True

        def make(scores):
            eng = Engine()
            r = rag.Reranker(lambda: eng, clock=lambda: 0.0)
            r._post = lambda q, docs, timeout: scores(docs)  # 不連網路 / no network
            return r, eng
        good, _ = make(lambda docs: [0.9, 0.1][:len(docs)] + [0.0] * (len(docs) - 2))
        self.assertTrue(good.check())
        self.assertEqual(good.note, "ok")
        self.assertEqual(len(good.score("問題", ["甲", "乙", "丙"])), 3)
        flat, eng = make(lambda docs: [1e-6] * len(docs))                   # 已知的壞轉檔：分數都接近 0
        self.assertFalse(flat.check())
        self.assertIn("self-check failed", flat.note)
        with self.assertRaises(Exception):
            flat.score("問題", ["甲", "乙"])

        def boom(docs):
            raise OSError("no engine")
        down, _ = make(boom)
        self.assertFalse(down.check())
        self.assertIn("unavailable", down.note)

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



class TestEmbeddingsEndpoint(unittest.TestCase):
    def test_openai_shape_auth_and_limits(self):
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        seen = []

        class Emb:
            def embed(self, texts):
                seen.extend(texts)
                return [rag._norm([1.0, 2.0]) for _ in texts]

            def tick(self):
                pass

            def stop(self):
                pass
        with tempfile.TemporaryDirectory() as d:
            sup, _, patch = make_supervisor(Path(d))
            gw = Gateway(sup.s, sup, TrajectoryWriter(Path(d) / "traj", log=lambda *_: None), embedder=Emb(),
                         log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                h = {"Authorization": f"Bearer {KEY}"}
                self.assertEqual(c.post("/v1/embeddings", json={"input": "x"}).status_code, 401)
                r = c.post("/v1/embeddings", headers=h, json={"input": ["甲", "乙"]}).json()
                self.assertEqual([x["index"] for x in r["data"]], [0, 1])
                self.assertAlmostEqual(sum(v * v for v in r["data"][0]["embedding"]), 1.0, places=5)
                c.post("/v1/embeddings", headers=h, json={"input": "問題", "input_type": "query"})
                self.assertTrue(seen[-1].startswith("Instruct:"))
                self.assertEqual(c.post("/v1/embeddings", headers=h, json={"input": ["x"] * 65}).status_code, 400)


if __name__ == "__main__":
    unittest.main()

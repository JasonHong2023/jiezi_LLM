"""add-notebooks：儲存、段落位置、檢索、引用檢查、查證與記憶。 / Storage, offsets, retrieval, citations, checks, memory."""

import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.memory import Memory  # noqa: E402
from jiezi.notebooks import cite, memory_link, verify  # noqa: E402
from jiezi.notebooks.store import NotebookError, NotebookStore, split_offsets  # noqa: E402

LEASE = ("租賃契約書。出租人王大明將台北市大安區房屋出租給承租人。租期自 2026 年 1 月 1 日起至 2027 年 12 月 31 日止。"
         "每月租金新台幣 25000 元，應於每月 5 日前匯入出租人帳戶。押金為兩個月租金，共 50000 元，租期屆滿無欠款時返還。"
         "承租人不得飼養寵物。房屋內的冷氣與冰箱由出租人負責維修。")
RULES = ("社區管理規約。住戶應遵守社區規定。垃圾於每週一、三、五晚上八點收取。訪客車輛不得停放於地下室。"
         "公共設施開放時間為早上六點到晚上十點。")
OTHER_LEASE = "補充協議。押金為三個月租金，共 75000 元。其餘條款依原契約。"


def fake_embed(texts):
    out = []
    for t in texts:
        v = array("f", [0.0] * 8)
        for ch in t:
            v[ord(ch) % 8] += 1.0
        out.append(v)
    return out


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.store = NotebookStore(Path(self._t.name) / "nb")
        self.addCleanup(self.store.close)

    def test_offsets_cover_text_and_overlap(self):
        text = "。".join(f"第{i}句話說明某件事情的細節內容" for i in range(200)) + "。"
        spans = split_offsets(text, size=60)
        self.assertGreater(len(spans), 5)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(text))
        self.assertTrue(any(b[0] < a[1] for a, b in zip(spans, spans[1:])))          # 有重疊 / overlap
        self.assertTrue(all(b[0] > a[0] for a, b in zip(spans, spans[1:])))          # 一直往前 / always advances

    def test_add_dedupe_remove_and_offsets(self):
        nb = self.store.create("租屋")
        s, new = nb.add_source("租約", "file", LEASE, origin="lease.pdf", embed=fake_embed)
        self.assertTrue(new)
        again, new2 = nb.add_source("租約（重傳）", "file", LEASE)
        self.assertFalse(new2)
        self.assertEqual(again["id"], s["id"])
        full = nb.source(s["id"])["text"]
        for c in nb.chunks():
            self.assertEqual(full[c["start"]:c["end"]], c["text"])                 # 位置對得回原文 / offsets
        self.assertEqual(len(nb.vectors()), len(nb.chunks()))
        self.assertEqual(self.store.list()[0]["sources"], 1)
        self.assertTrue(nb.remove_source(s["id"]))
        self.assertEqual(nb.chunks(), [])
        self.assertEqual(nb.vectors(), {})
        with self.assertRaises(NotebookError):
            nb.add_source("空", "text", "   ")
        with self.assertRaises(NotebookError):
            self.store.get("../etc")
        self.assertTrue(self.store.delete(nb.id))
        self.assertEqual(self.store.list(), [])


class CiteTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        self.store = NotebookStore(Path(self._t.name) / "nb")
        self.addCleanup(self.store.close)
        self.nb = self.store.create("租屋")
        self.lease, _ = self.nb.add_source("租約", "file", LEASE)
        self.rules, _ = self.nb.add_source("管理規約", "text", RULES)
        self.titles = {s["id"]: s["title"] for s in self.nb.sources()}

    def passages(self, q):
        return cite.number(cite.retrieve(self.nb.chunks(), q), self.titles)

    def test_retrieve_relevant_and_nothing_for_unrelated(self):
        ps = self.passages("押金是多少錢？")
        self.assertTrue(ps)
        self.assertEqual(ps[0]["sid"], self.lease["id"])
        self.assertEqual(self.passages("量子電腦的原理是什麼"), [])

    def test_check_keeps_supported_and_removes_fabricated(self):
        ps = self.passages("押金和垃圾收取時間")
        lease_n = next(p["n"] for p in ps if p["sid"] == self.lease["id"])
        ans = f"押金為兩個月租金，共 50000 元 [{lease_n}]。社區有游泳池可以使用 [{lease_n}]。月租金是三萬元 [9]。"
        r = cite.check(ans, ps)
        self.assertIn(f"共 50000 元[{lease_n}]。", r["answer"])
        self.assertIn("社區有游泳池可以使用" + cite.UNSOURCED, r["answer"])
        self.assertEqual({x["n"] for x in r["removed"]}, {lease_n, 9})
        self.assertEqual([c["n"] for c in r["citations"]], [lease_n])
        self.assertEqual(r["citations"][0]["source_id"], self.lease["id"])
        self.assertIn("租約", cite.appendix(r["citations"]))

    def test_not_found_and_prompt(self):
        r = cite.check(cite.NOT_FOUND, [])
        self.assertTrue(r["not_found"])
        p = cite.prompt(self.passages("押金"), "租屋")
        self.assertIn("[1]《租約》", p)
        self.assertIn(cite.NOT_FOUND, p)
        self.assertIn("一般知識", cite.prompt([], "租屋", general=True))


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.addCleanup(self._t.cleanup)
        tmp = Path(self._t.name)
        self.store = NotebookStore(tmp / "nb")
        self.addCleanup(self.store.close)
        self.nb = self.store.create("租屋")
        self.lease, _ = self.nb.add_source("租約", "file", LEASE)
        self.extra, _ = self.nb.add_source("補充協議", "file", OTHER_LEASE)
        self.memory = Memory(tmp / "wiki", root=tmp)   # 每個測試自己的信任把關 / a gate of its own
        self.sources = {s["id"]: s for s in self.nb.sources()}
        self.titles = {k: v["title"] for k, v in self.sources.items()}

    def run_check(self, q, answer, ps=None):
        ps = ps if ps is not None else cite.number(cite.retrieve(self.nb.chunks(), q), self.titles)
        checked = cite.check(answer.format(**{f"n{p['n']}": p["n"] for p in ps}), ps)
        return checked, verify.verify(q, checked, ps, self.sources, self.memory, multi_source=True), ps

    def test_clean_answer_passes_and_is_saved(self):
        ps = [p for p in cite.number(cite.retrieve(self.nb.chunks(), "每月租金多少"), self.titles)
              if p["sid"] == self.lease["id"]][:1]
        ps[0]["n"] = 1
        checked, findings, _ = self.run_check("每月租金多少", "每月租金新台幣 25000 元 [1]。", ps)
        self.assertEqual(findings, [])
        page = memory_link.save_answer(self.memory, self.nb, "每月租金多少", checked)
        self.assertTrue(page)
        e, _ = self.memory.find_answer("每月租金多少")
        self.assertIn("25000", e.text)
        self.assertIn("租約", e.text)

    def test_each_check_reports(self):
        ps = cite.number(cite.retrieve(self.nb.chunks(), "押金是幾個月"), self.titles)
        n = next(p["n"] for p in ps if p["sid"] == self.lease["id"])
        m = next(p["n"] for p in ps if p["sid"] == self.extra["id"])
        _, f, _ = self.run_check("押金是幾個月", f"押金為兩個月租金 [{n}]，補充協議改為三個月租金 [{m}]。", ps)
        self.assertIn("source_conflict", {x["check"] for x in f})                       # b
        _, f, _ = self.run_check("押金是幾個月", "押金可能是兩個月租金 [%d]。" % n, ps)
        self.assertIn("uncertain", {x["check"] for x in f})                             # e
        _, f, _ = self.run_check("那份的押金是幾個月", "押金為兩個月租金 [%d]。" % n, ps)
        self.assertIn("ambiguous_question", {x["check"] for x in f})                    # e
        _, f, _ = self.run_check("押金是幾個月", "押金為兩個月。屋主人很好。", ps)
        self.assertIn("unsourced", {x["check"] for x in f})                             # a
        self.memory.save_correction("押金是幾個月", "押金其實是 1 個月")
        _, f, _ = self.run_check("押金是幾個月", "押金為兩個月租金，共 50000 元 [%d]。" % n, ps)
        self.assertIn("memory_conflict", {x["check"] for x in f})                       # c
        self.assertEqual(verify._nums("押金兩個月 [1]、共 50000 元［2］"), {"兩", "50000"})   # 編號不算 / markers ignored
        self.sources[self.lease["id"]]["trust"] = {"level": "tainted"}
        _, f, _ = self.run_check("押金", "押金為兩個月租金 [%d]。" % n, ps)
        self.assertIn("flagged_source", {x["check"] for x in f})                        # d


class RecallTests(unittest.TestCase):
    def test_digest_and_recall_from_normal_chat(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            store = NotebookStore(tmp / "nb")
            nb = store.create("租屋")
            nb.add_source("租約", "file", LEASE)
            p = memory_link.write_digest(tmp / "wiki", nb)
            self.assertIn("### 租約", p.read_text(encoding="utf-8"))
            got = memory_link.recall_block(store, "我的租約押金是多少？", wiki=tmp / "wiki")
            self.assertIsNotNone(got)
            content, sources, trainable, _, extra = got
            self.assertIn("[1]《租約》", content)
            self.assertFalse(trainable)
            self.assertEqual(sources[0]["source"], "notebook")
            self.assertIsNone(memory_link.recall_block(store, "台灣最高的山是哪一座？", wiki=tmp / "wiki"))
            memory_link.remove_digest(tmp / "wiki", "租屋")
            self.assertFalse(p.exists())
            store.close()


if __name__ == "__main__":
    unittest.main()

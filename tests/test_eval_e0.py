"""E0 測試：矩陣與清單檢查、擺放規則、冒煙判定、跨夜流程、取樣指標、帕累托與 SVG（不載入任何模型）。
E0 tests: matrix / manifest checks, placement, smoke judging, the night pipeline, sampled metrics, Pareto and SVG
(no model is loaded)."""

import hashlib
import json
import sys
import tempfile
import unittest
import xml.dom.minidom
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.eval import EvalError, e0  # noqa: E402

BLOB = b"gguf-bytes"
SHA = hashlib.sha256(BLOB).hexdigest()
MODEL = """
[[model]]
name = "m{n}"
file = "m{n}.gguf"
url = "https://example.invalid/m{n}.gguf"
sha256 = "{sha}"
size = {size}
license = "Apache-2.0"
license_url = "https://example.invalid/LICENSE"
commercial_use = true
training_use = true
license_checked = "2026-11-15"
source = "test"
"""
ROW = """
[[row]]
name = "r{n}"
model = "m{n}"
group = "{group}"
base = "B"
quant = "{quant}"
placement = "{placement}"
"""
BUDGETS = {"ram": {"usable_mib": 8000}, "vram": {"usable_mib": 3500}}


def row(name="r", size_mib=1000, quant="Q4_K_M", placement="gpu", **kw):
    return e0.Row(name=name, model="m", group="int4", base="B", quant=quant, placement=placement,
                  file="m.gguf", size=int(size_mib * 2**20), sha256=SHA, url="u", **kw)


class TestMatrix(unittest.TestCase):
    def write(self, d, models, rows):
        (d / "manifest.toml").write_text(models)
        (d / "matrix.toml").write_text(rows)
        return e0.load_matrix(d, d / "matrix.toml", d / "manifest.toml")

    def test_loads_and_hashes(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            rows, h = self.write(d, MODEL.format(n=1, sha=SHA, size=len(BLOB)),
                                 ROW.format(n=1, group="ternary", quant="Q2_0", placement="gpu"))
            self.assertEqual((rows[0].name, rows[0].size, rows[0].run_id, len(h)), ("r1", len(BLOB), "e0-r1", 12))

    def test_missing_license_or_unknown_model_refused(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            bad = MODEL.format(n=1, sha=SHA, size=1).replace('license = "Apache-2.0"\n', "")
            with self.assertRaisesRegex(EvalError, "license"):
                self.write(d, bad, ROW.format(n=1, group="int4", quant="Q4_K_M", placement="cpu"))
            with self.assertRaisesRegex(EvalError, "not in"):
                self.write(d, MODEL.format(n=1, sha=SHA, size=1),
                           ROW.format(n=2, group="int4", quant="Q4_K_M", placement="cpu"))
            with self.assertRaisesRegex(EvalError, "group"):
                self.write(d, MODEL.format(n=1, sha=SHA, size=1),
                           ROW.format(n=1, group="int3", quant="Q4_K_M", placement="cpu"))

    def test_project_matrix_is_valid(self):
        rows, _ = e0.load_matrix(ROOT)
        self.assertGreaterEqual(len(rows), 17)
        self.assertFalse(any("bitnet" in r.model for r in rows))  # OQ1：排除 / excluded


class TestPlacement(unittest.TestCase):
    def test_gpu_when_it_fits(self):
        p = e0.place(row(size_mib=2000), BUDGETS)
        self.assertEqual((p["placement"], p["ngl"]), ("gpu", 99))

    def test_cpu_fallback_with_reason(self):
        p = e0.place(row(size_mib=3000), BUDGETS)
        self.assertEqual((p["placement"], p["ngl"]), ("cpu", 0))
        self.assertIn("VRAM", p["reason"])
        p = e0.place(row(quant="TQ2_0"), BUDGETS)
        self.assertEqual(p["placement"], "cpu")
        self.assertIn("CUDA", p["reason"])

    def test_excluded_over_ram(self):
        p = e0.place(row(size_mib=7500, placement="cpu"), BUDGETS)
        self.assertEqual(p["excluded"], "excluded_budget")

    def test_estimate_scales_with_size(self):
        self.assertAlmostEqual(e0.estimate_minutes(row(size_mib=e0.REF_BYTES / 2**20), "cpu"), e0.REF_MINUTES, 0)
        self.assertLess(e0.estimate_minutes(row(), "gpu"), e0.estimate_minutes(row(), "cpu"))
        self.assertIsNone(e0.estimate_minutes(row(), None))


MC = {"source": "c", "id": "1", "task": "qa", "scorer": "multiple_choice", "data": {}}
QA = {"source": "s", "id": "1", "task": "qa", "scorer": "simpleqa_approx", "data": {}}
CODE = {"source": "h", "id": "1", "task": "code", "scorer": "pending_verifier", "data": {}}
TOOL = {"source": "a", "id": "1", "task": "tool", "scorer": "pending_verifier", "data": {}}
SUM = {"source": "w", "id": "1", "task": "summary", "scorer": "pending_verifier", "data": {}}


class TestSmoke(unittest.TestCase):
    GOOD = [(MC, "答案：B"), (QA, "玉山"), (CODE, "```python\ndef f():\n    return 1\n```"),
            (TOOL, "[f(a=1)]"), (SUM, "這是一段足夠長的摘要內容，描述了文章的重點與結論。")]

    def test_pass(self):
        self.assertEqual(e0.judge_smoke(self.GOOD)["parsed"], 5)
        self.assertTrue(e0.judge_smoke(self.GOOD)["ok"])

    def test_thinking_leak_and_empty(self):
        bad = [(MC, "<think>嗯</think>答案：B")] + self.GOOD[1:]
        r = e0.judge_smoke(bad)
        self.assertFalse(r["ok"])
        self.assertIn("thinking", r["reasons"][0])
        r = e0.judge_smoke([(MC, ""), (QA, None), (CODE, "x"), (TOOL, "no"), (SUM, "短")])
        self.assertFalse(r["ok"])
        self.assertIn("only 0/5", r["reasons"][-1])

    def test_fixed_items(self):
        items = [MC, {**MC, "id": "0"}, QA, CODE, TOOL, SUM]
        self.assertEqual([i["id"] for i in e0.smoke_items(items)], ["0", "1", "1", "1", "1"])
        with self.assertRaises(EvalError):
            e0.smoke_items([MC])


class TestDownload(unittest.TestCase):
    def test_verify_and_never_overwrite(self):
        r = row(size_mib=len(BLOB) / 2**20)
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            p = e0.ensure_model(r, d, download=lambda u, dest, log: dest.write_bytes(BLOB), log=lambda *_: None)
            self.assertEqual(p.read_bytes(), BLOB)
            self.assertEqual(e0.ensure_model(r, d, download=None), p)  # 已存在 / present
            p.write_bytes(b"other-bytes")
            with self.assertRaisesRegex(EvalError, "does not match"):
                e0.ensure_model(r, d, download=None)
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(EvalError, "SHA-256"):
                e0.ensure_model(r, Path(t), download=lambda u, dest, log: dest.write_bytes(b"x" * len(BLOB)),
                                log=lambda *_: None)
            self.assertEqual(list(Path(t).iterdir()), [])


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.mdir = Path(self._t.name)
        self.calls = []
        self.window = [True]
        self.smoke_ok = {"ok": True, "parsed": 5, "reasons": []}

    def tearDown(self):
        self._t.cleanup()

    def hooks(self, run_rc=0, verify_rc=0, smoke=None):
        def run(r, ngl, resume, samples, temp, sources, run_id=None):
            self.calls.append(("run", r.name, ngl, resume))
            return run_rc

        def verify(run_id, only):
            self.calls.append(("verify", run_id))
            return verify_rc
        return e0.Hooks(fresh_facts=lambda: {"budgets": BUDGETS}, models_dir=self.mdir,
                        in_window=lambda: self.window[0], run=run, verify=verify,
                        smoke=lambda r, p, ngl: smoke or self.smoke_ok,
                        download=lambda u, dest, log: dest.write_bytes(BLOB), log=lambda *_: None)

    def rows(self):
        small = len(BLOB) / 2**20
        return [row("a", small), row("b", small, quant="TQ2_0"), row("big", 7900, placement="cpu")]

    def test_full_flow_and_exclusions(self):
        state = {"matrix_hash": "h", "rows": {}}
        h = self.hooks()
        h.smoke = lambda r, p, ngl: self.smoke_ok if r.name == "a" else {"ok": False, "parsed": 1, "reasons": ["x"]}
        rows = self.rows()[:2]
        self.assertEqual(e0.run_rows(rows, state, h, lambda: None), "complete")
        self.assertEqual(state["rows"]["a"]["state"], "verified")
        self.assertEqual(state["rows"]["a"]["ngl"], 99)
        self.assertEqual(state["rows"]["b"]["state"], "excluded_smoke")
        self.assertEqual(self.calls, [("run", "a", 99, False), ("verify", "e0-a")])
        self.assertEqual(e0.run_rows(rows, state, h, lambda: None), "complete")  # 不重跑 / no rerun
        self.assertEqual(len(self.calls), 2)

    def test_budget_exclusion(self):
        state = {"matrix_hash": "h", "rows": {}}
        r = row("big", len(BLOB) / 2**20, placement="cpu")
        h = self.hooks()
        h.fresh_facts = lambda: {"budgets": {"ram": {"usable_mib": 500}, "vram": {"usable_mib": 0}}}
        e0.run_rows([r], state, h, lambda: None)
        self.assertEqual(state["rows"]["big"]["state"], "excluded_budget")

    def test_window_end_pauses_and_resumes(self):
        state = {"matrix_hash": "h", "rows": {}}
        rows = self.rows()[:1]
        h = self.hooks(run_rc=3)
        self.window[0] = True

        def run(r, ngl, resume, samples, temp, sources, run_id=None):
            self.calls.append(("run", resume))
            self.window[0] = False  # 跑到一半時段結束 / window ends mid-run
            return 3
        h.run = run
        self.assertEqual(e0.run_rows(rows, state, h, lambda: None), "paused_window")
        self.assertEqual(state["rows"]["a"]["state"], "running")
        self.window[0] = True
        h.run = lambda r, ngl, resume, *a, **k: self.calls.append(("run", resume)) or 0
        self.assertEqual(e0.run_rows(rows, state, h, lambda: None), "complete")
        self.assertEqual(self.calls[-2:], [("run", True), ("verify", "e0-a")])

    def test_placement_change_blocks_resume(self):
        state = {"matrix_hash": "h", "rows": {"a": {"state": "running", "ngl": 0}}}
        e0.run_rows(self.rows()[:1], state, self.hooks(), lambda: None)
        self.assertEqual(state["rows"]["a"]["state"], "running")
        self.assertEqual(self.calls, [])

    def test_verify_failure_moves_on(self):
        state = {"matrix_hash": "h", "rows": {}}
        rows = [row("a", len(BLOB) / 2**20), row("c", len(BLOB) / 2**20)]
        e0.run_rows(rows, state, self.hooks(verify_rc=3), lambda: None)
        self.assertEqual([state["rows"][n]["state"] for n in "ac"], ["run_complete", "run_complete"])


class TestMetrics(unittest.TestCase):
    def test_wilson(self):
        lo, hi = e0.wilson(25, 50)
        self.assertTrue(0.36 < lo < 0.37 and 0.63 < hi < 0.64)
        self.assertIsNone(e0.wilson(0, 0))

    def test_pareto(self):
        pts = [("a", 100, 0.3), ("b", 200, 0.5), ("c", 300, 0.4), ("d", 400, 0.6), ("e", 100, 0.2)]
        self.assertEqual(e0.pareto_front(pts), ["a", "b", "d"])

    def test_svg_is_well_formed(self):
        pts = [{"name": "x<1>", "group": g, "size_mib": 500 * (i + 1), "acc": 0.1 * i, "lo": 0.0, "hi": 0.5}
               for i, g in enumerate(e0.GROUPS)]
        svg = e0.svg_chart(pts, "標題 & title", "說明")
        xml.dom.minidom.parseString(svg)
        self.assertIn("polyline", svg)

    def test_sampled_metrics(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            res, ver = [], []
            calls = [{"f": {"a": 1}}, {"f": {"a": 1}}, {"f": {"a": 2}}]
            for s, (call, score) in enumerate(zip(calls, (1, 1, 0))):
                k = f"a/t1#{s}"
                res.append({"key": k, "source": "a", "id": "t1", "task": "tool", "sample": s, "content": "x"})
                ver.append({"key": k, "kind": "tool", "status": "correct" if score else "wrong", "score": score,
                            "details": {"calls": [call]}})
            for s, (code, score) in enumerate([("def f():\n  return 2  # c", 0), ("def f():\n  return 2", 0),
                                               ("def f():\n  return 1", 1)]):
                k = f"h/c1#{s}"
                res.append({"key": k, "source": "h", "id": "c1", "task": "code", "sample": s, "content": code})
                ver.append({"key": k, "kind": "code", "status": "wrong", "score": score, "details": {}})
            (d / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in res))
            (d / "verifications.jsonl").write_text("".join(json.dumps(v) + "\n" for v in ver))
            m = e0.sampled_metrics(d)
        self.assertEqual((m["tool"]["pass@1"], m["tool"]["majority"], m["tool"]["pass@8"]), (0.6667, 1, 1))
        self.assertEqual((m["code"]["majority"], m["code"]["pass@8"]), (0, 1))  # 註解不影響多數決 / comments ignored


if __name__ == "__main__":
    unittest.main()

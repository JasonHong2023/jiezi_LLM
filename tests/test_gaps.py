"""缺口報告測試：原因判斷、分類、略過正常回答、直接請教另列。 / Gap report tests."""

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi.runtime import gaps as G  # noqa: E402


def rec(q, policy="jiezi", tiers=(), final=0, status="ok", sources=None):
    return {"at": "2026-11-15T10:00:00+08:00", "policy": policy, "status": status, "final_tier": final,
            "request": {"messages": [{"role": "user", "content": q}]}, "tiers": list(tiers), "sources": sources}


class FakeProbe:
    def related(self, q):
        return ["知識庫〈玉山〉"] if "山" in q else []


class TestGaps(unittest.TestCase):
    def test_report(self):
        rows = [rec("早安", tiers=[{"tier": 0}]),                                          # 正常 / fine
                rec("台灣最高的山？", tiers=[{"tier": 0, "needs_help": "self_reported_unsure"}], final="consult"),
                rec("某歌手的單曲哪年發行", tiers=[{"tier": 0, "needs_help": "self_reported_unsure"}]),
                rec("你叫什麼名字", tiers=[{"tier": 0, "needs_help": "self_reported_unsure"}]),
                rec("幫我找今日新聞", tiers=[{"tier": 0, "needs_help": "empty_answer"}]),
                rec("hi", status="engine_unavailable"),
                rec("刈包", tiers=[{"tier": 0, "verification": {"status": "fail", "checks": [
                    {"check": "grounded", "status": "fail"}]}}], sources=[{"article": "刈包"}]),
                rec("什麼是 LoRA", policy="jiezi-ask-claude", final="consult")]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / "2026-11-15.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
            md, s = G.report(root, days=1, today=date(2026, 11, 15), probe=FakeProbe())
        self.assertEqual((s["records"], s["needed_help"], s["direct"]), (8, 6, 1))
        self.assertEqual(s["by_kind"], {"trigger": 1, "data": 1, "self": 1, "web": 1, "error": 1, "model": 1})
        self.assertEqual(s["by_reason"]["verification_failed:grounded"], 1)
        self.assertIn("知識庫〈玉山〉", md)
        self.assertIn("jiezi-ask-claude：什麼是 LoRA", md)
        self.assertNotIn("早安", md)


class TestDashboard(unittest.TestCase):
    def test_tool_candidates_and_local_solves(self):
        """可以用程式算的題目列為工具候選；本機重想答對的列為訓練候選（local-first-solving）。"""
        esc = [{"tier": 0, "needs_help": "unsupported_claims"}, {"tier": 3, "provider": "claude"}]
        holiday = rec("台灣2027年的國定假日有哪些?", tiers=esc, final=3)
        self.assertEqual(G.classify(holiday, FakeProbe())[0], "tool")
        computed = rec("2027年的除夕是哪一天?", tiers=esc, final=3, sources=[{"source": "tools"}])
        self.assertNotEqual(G.classify(computed, FakeProbe())[0], "tool")          # 已經有工具 / already a tool
        doc = rec("以下是《勞動基準法.txt》中和問題最相關的段落：第 30 條 每日不得超過八小時，平均每週…", tiers=esc, final=3)
        self.assertNotEqual(G.classify(doc, FakeProbe())[0], "tool")              # 文件題不算 / document questions
        solved = rec("國花是什麼", tiers=[{"tier": 0}, {"tier": 1, "step": "retry"}], final=1)
        solved["ladder"] = {"first_error": "x", "solved_by": "retry"}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(
                "\n".join(json.dumps(x, ensure_ascii=False) for x in (holiday, solved)))
            md, summary = G.report(root, 1, probe=FakeProbe())
        self.assertEqual(summary["solved_locally"], 1)
        self.assertIn("可以用程式算", md)
        self.assertIn("本機重想後自己答對", md)

    def test_builds_without_results(self):
        from jiezi.runtime import dashboard
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(
                json.dumps(rec("你好", tiers=[{"tier": 0, "tps": 50.0}]), ensure_ascii=False))
            md = dashboard.build(root)
        self.assertIn("請求 1；本機處理 1（100.0%", md)
        self.assertIn("50.0 t/s", md)


if __name__ == "__main__":
    unittest.main()

"""訓練資料匯出測試：只收強驗證的本機回答、排除不可訓練與評測重疊、附來源與授權。 / Training-data export tests."""

import json
import sys
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jiezi import training_data as T  # noqa: E402

TOOL_OK = {"status": "pass", "checks": [{"check": "tool_schema", "status": "pass"}]}
GROUNDED_OK = {"status": "pass", "checks": [{"check": "grounded", "status": "pass"}]}


def rec(q, answer, tier=0, ver=TOOL_OK, training=None, sources=None, policy="jiezi"):
    return {"id": q, "status": "ok", "policy": policy, "final_tier": tier, "training_use": training,
            "sources": sources or [], "jiezi": {"verification": ver["status"]},
            "request": {"messages": [{"role": "user", "content": q}]},
            "tiers": [{"tier": tier, "answer": {"role": "assistant", "content": answer}, "verification": ver}]}


class TestTrainingData(unittest.TestCase):
    def test_filters(self):
        rows = [rec("查台北天氣", "[get_weather(city='台北')]"),                            # 收 / kept
                rec("刈包是什麼", "刈包是四川菜", ver=GROUNDED_OK),                          # 弱驗證 / weak
                rec("LoRA 是什麼", "低秩適配", tier="memory", training=False),               # Claude 的內容 / Claude text
                rec("「芥子」的意思", "芥菜的種子", sources=[{"source": "moedict-revised"}]),  # 禁止改作 / ND
                rec("寫程式", "x", ver={"status": "fail", "checks": []}),                    # 沒過 / failed
                rec("2^10", "1024\n\n---\n【計算】\n- 2^10 = 1024")]                          # 附錄要去掉 / appendix
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
            out, m = T.export(root, limit_per_source=5)
            kept = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([k["messages"][0]["content"] for k in kept], ["查台北天氣", "2^10"])
        self.assertEqual(kept[1]["messages"][-1]["content"], "1024")
        self.assertTrue(all(k["training_use"] and k["license"] and k["sha256"] for k in kept))
        self.assertEqual(m["excluded"]["weak_verification"], 1)
        self.assertEqual(m["excluded"]["marked_not_trainable"], 1)
        self.assertEqual(m["excluded"]["non_trainable_source"], 1)
        self.assertEqual(m["excluded"]["not_verified"], 1)

    def test_trust_fields_and_tainted_content(self):
        # add-agent-trust-gate T4：範例帶 trust_level／provenance；taint index 裡的內容不收
        import hashlib
        from jiezi.trust import get_gate, reset_gate
        self.addCleanup(reset_gate)
        bad = "[get_weather(city='台中')]"
        rows = [rec("查台北天氣", "[get_weather(city='台北')]"), rec("查台中天氣", bad)]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            get_gate(root).register_hash(hashlib.sha256(bad.encode()).hexdigest(), "request", "tool:1", "x")
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
            out, m = T.export(root, limit_per_source=5)
            kept = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([k["messages"][0]["content"] for k in kept], ["查台北天氣"])
        self.assertEqual(m["excluded"]["tainted_content"], 1)
        self.assertEqual(kept[0]["trust_level"], "trusted")
        self.assertEqual((kept[0]["provenance"]["source_channel"], kept[0]["provenance"]["content_hash"]),
                         ("trajectory", kept[0]["sha256"]))

    def test_toolcall_datasets(self):
        # add-strong-tool-calling 3.1：外部資料集只收通過 schema 的呼叫；含中文不收；評測題（含前 80 字）不收
        from jiezi import toolcall_data as TC
        toolace_sys = ('Here is a list of functions in JSON format that you can invoke:\n[{"name": "Market Trends API", '
                       '"description": "trends", "parameters": {"type": "dict", "properties": {"country": '
                       '{"type": "string"}}, "required": ["country"]}, "required": null}]')
        rows = [{"system": toolace_sys, "conversations": [
                    {"from": "user", "value": "Get the top market trends in the US please"},
                    {"from": "assistant", "value": '[Market Trends API(country="us")]'}]},
                {"system": toolace_sys, "conversations": [                                   # 缺必填 / missing
                    {"from": "user", "value": "trends?"}, {"from": "assistant", "value": "[Market Trends API()]"}]},
                {"system": toolace_sys, "conversations": [                                   # 中文 / CJK
                    {"from": "user", "value": "查美国市场趋势"},
                    {"from": "assistant", "value": '[Market Trends API(country="us")]'}]},
                {"system": toolace_sys, "conversations": [                                   # 評測題 / eval item
                    {"from": "user", "value": "Find the distance from San Francisco to Los Angeles in kilometers, with the scenic route"},
                    {"from": "assistant", "value": '[Market Trends API(country="tw")]'}]}]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ds = root / "var" / "datasets" / "toolcall" / "toolace"
            ds.mkdir(parents=True)
            (ds / "SOURCE.jsonl").write_text('{"repo": "Team-ACE/ToolACE", "revision": "abc", "license": "Apache-2.0"}\n')
            (ds / "data.json").write_text(json.dumps(rows))
            (root / "var" / "trajectories").mkdir(parents=True)
            with mock.patch.object(T, "eval_targets",
                                   return_value=({T._norm("Find the distance from San Francisco to Los Angeles in kilometers")}, set())):
                off, _ = T.export(root, limit_per_source=5)                  # 預設不收 / off by default
                self.assertEqual(off.read_text(encoding="utf-8"), "")
                out, m = T.export(root, limit_per_source=5, toolcall_datasets=True)
            kept = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(kept), 1)
        k = kept[0]
        self.assertEqual(k["tools"][0]["function"]["name"], "Market_Trends_API")
        self.assertEqual(k["tools"][0]["function"]["parameters"]["type"], "object")
        self.assertEqual(json.loads(k["messages"][-1]["tool_calls"][0]["function"]["arguments"]), {"country": "us"})
        self.assertEqual((k["source"], k["origin"]), ("toolace", "dataset"))
        self.assertIn("Apache-2.0", k["license"])
        self.assertEqual(m["excluded"]["toolace:schema_check_failed"], 1)
        self.assertEqual(m["excluded"]["toolace:cjk_text"], 1)
        self.assertEqual(m["excluded"]["overlaps_evaluation"], 1)

    def test_toolcall_too_long_for_training_is_skipped(self):
        from jiezi import toolcall_data as TC
        props = {f"p{i}": {"type": "string", "description": "long description " * 20} for i in range(10)}
        sysmsg = "functions:\n" + json.dumps([{"name": "big", "description": "d", "parameters": {
            "type": "dict", "properties": props, "required": ["p0"]}}])
        rows = [{"system": sysmsg, "conversations": [{"from": "user", "value": "call big please"},
                                                       {"from": "assistant", "value": '[big(p0="x")]'}]}]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ds = root / "var" / "datasets" / "toolcall" / "toolace"
            ds.mkdir(parents=True)
            (ds / "SOURCE.jsonl").write_text('{"repo": "r", "revision": "x", "license": "Apache-2.0"}\n')
            (ds / "data.json").write_text(json.dumps(rows))
            import random
            ex, why = TC.load(root, random.Random(1), 10)
        self.assertEqual((ex, why["toolace:too_long_for_training"]), ([], 1))

    def test_ladder_keeps_the_corrected_local_answer(self):
        """階梯中本機重答才對：匯出對的那一次（使用者 2026-11-18：本機自己答對的答案當訓練資料）。
        On the ladder, the corrected local answer is exported, not the first failed one."""
        fail = {"status": "fail", "checks": [{"check": "tool_schema", "status": "fail"}]}
        r = rec("查高雄天氣", "[get_weather()]", ver=fail)
        r["final_tier"] = 1
        r["jiezi"]["verification"] = "pass"
        r["ladder"] = {"first_error": "x", "solved_by": "think"}
        r["tiers"] += [{"tier": 1, "step": "retry", "answer": {"content": "[get_weather(c='x')]"}, "verification": fail},
                       {"tier": "think", "step": "think", "answer": {"content": "[get_weather(city='高雄')]"},
                        "verification": TOOL_OK}]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(json.dumps(r, ensure_ascii=False))
            out, _ = T.export(root, limit_per_source=5)
            kept = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(kept[0]["messages"][-1]["content"], "[get_weather(city='高雄')]")
        self.assertEqual(kept[0]["ladder_step"], "think")

    def test_evaluation_overlap(self):
        with tempfile.TemporaryDirectory() as d:
            qs, targets = T.eval_targets(Path(d))
        from jiezi.selftest import build
        with tempfile.TemporaryDirectory() as d:
            q = build(Path(d))[0].question
        self.assertIn(T._norm(q), qs)                                              # 自我評測題 / self-test items


if __name__ == "__main__":
    unittest.main()

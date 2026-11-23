"""技能庫 v0 測試：只收強驗證範例、函式必須可用、gateway 附範例並學會新的成功呼叫。 / Skill library tests."""

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import skills as S  # noqa: E402
from jiezi import trust as T  # noqa: E402

TOOL = {"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {
    "city": {"type": "string"}}, "required": ["city"]}}}
PASS = {"status": "pass", "checks": [{"check": "tool_schema", "status": "pass"}]}


def rec(q, content, ver=PASS, conf=None):
    return {"id": q, "at": "2026-11-16T10:00", "status": "ok", "request": {"messages": [{"role": "user", "content": q}],
            "tools": [TOOL]}, "tiers": [{"tier": 0, "answer": {"role": "assistant", "content": content},
                                         "verification": ver, "confidence": conf}]}


class TestSkills(unittest.TestCase):
    def test_collect_and_examples(self):
        rows = [rec("台北明天天氣如何", "[get_weather(city='台北')]"),
                rec("高雄天氣", "[get_weather()]", ver={"status": "fail", "checks": []}),
                rec("台中天氣", "[get_weather(city='台中')]", conf=0.5)]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
            self.assertEqual(S.build(root)["skills"], 1)
            sk = S.Skills(S.skills_path(root))
            self.assertEqual(len(sk.examples("台北後天天氣如何", {"get_weather"})), 1)
            self.assertEqual(sk.examples("台北後天天氣如何", {"search"}), [])

    def test_gateway_attaches_and_learns(self):
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp, samples=1)
            lh, seen = local_handler([{"role": "assistant", "content": "[get_weather(city='高雄')]"}])
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
            gw.skills.add({"question": "台北明天天氣如何", "call": "[get_weather(city='台北')]",
                           "functions": ["get_weather"], "used": ["get_weather"], "at": "x"})
            with patch, TestClient(create_app(gw)) as c:
                c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                       json={"messages": [{"role": "user", "content": "高雄明天天氣如何"}], "tools": [TOOL]})
                n = len(gw.skills.rows)
                c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}", "X-Jiezi-Eval": "1"},
                       json={"messages": [{"role": "user", "content": "屏東天氣"}], "tools": [TOOL]})
            sys_msgs = [m["content"] for m in seen[0]["messages"] if m["role"] == "system"]
            self.assertTrue(any("get_weather(city='台北')" in s for s in sys_msgs))
            self.assertTrue(any(r["call"] == "[get_weather(city='高雄')]" for r in gw.skills.rows))
            self.assertEqual(len(gw.skills.rows), n)

    def test_build_output_includes_trust_provenance(self):
        rows = [rec("台北天氣", "[get_weather(city='台北')]")]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
            S.build(root)
            skills_file = S.skills_path(root)
            lines = skills_file.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            skill = json.loads(lines[0])
            self.assertIn("trust_level", skill)
            self.assertEqual(skill["trust_level"], "verified")
            self.assertIn("provenance", skill)
            prov = skill["provenance"]
            self.assertEqual(prov["source_channel"], "skill")
            self.assertIn("content_hash", prov)
            self.assertIn("fetched_at", prov)

    def test_collect_filters_unverified_and_tainted(self):
        """collect() 產生的技能 trust_level 為 verified（軌跡驗證成功的呼叫）。"""
        rows = [rec("測試正常", "[get_weather(city='台北')]")]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
            result = S.build(root)
            self.assertEqual(result["skills"], 1)
            skills_file = S.skills_path(root)
            lines = skills_file.read_text(encoding="utf-8").strip().splitlines()
            skill = json.loads(lines[0])
            self.assertEqual(skill["trust_level"], "verified")

    def test_add_with_cloud_content_not_added(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skills_file = S.skills_path(root)
            sk = S.Skills(skills_file)
            gate = T.get_gate()
            content = "雲端回答\n[get_weather(city='台北')]"
            level, prov, _ = gate.evaluate_trust(content, "cloud", "claude-3")
            self.assertEqual(level, T.TrustLevel.UNVERIFIED)

            sk.add({"question": "雲端問天氣", "call": "[get_weather(city='台北')]",
                    "functions": ["get_weather"], "used": ["get_weather"], "at": "x",
                    "source_channel": "cloud", "source_id": "claude-3"})
            self.assertEqual(len(sk.rows), 0)

    def test_add_with_trusted_mcp_content_added(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skills_file = S.skills_path(root)
            sk = S.Skills(skills_file)
            sk.add({"question": "MCP 問天氣", "call": "[get_weather(city='高雄')]",
                    "functions": ["get_weather"], "used": ["get_weather"], "at": "x",
                    "trust_level": "verified",
                    "provenance": {"source_channel": "mcp", "source_id": "weather-server",
                                   "content_hash": "a"*64, "fetched_at": "2024-01-01T00:00:00Z",
                                   "retrieval_method": "mcp_call"}})
            self.assertEqual(len(sk.rows), 1)
            self.assertEqual(sk.rows[0]["trust_level"], "verified")

    def test_examples_respects_trust_level(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            skills_file = S.skills_path(root)
            sk = S.Skills(skills_file)
            sk.rows = [
                {"question": "台北天氣如何", "call": "[f()]", "functions": ["f"], "used": ["f"], "at": "x",
                 "trust_level": "verified", "provenance": {}},
                {"question": "高雄天氣如何", "call": "[f()]", "functions": ["f"], "used": ["f"], "at": "x",
                 "trust_level": "unverified", "provenance": {}},
                {"question": "台中天氣如何", "call": "[f()]", "functions": ["f"], "used": ["f"], "at": "x",
                 "trust_level": "tainted", "provenance": {}},
            ]
            ex = sk.examples("台北明天天氣", {"f"})
            self.assertEqual(len(ex), 1)
            self.assertEqual(ex[0]["question"], "台北天氣如何")


if __name__ == "__main__":
    unittest.main()

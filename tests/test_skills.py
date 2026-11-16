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
                rec("高雄天氣", "[get_weather()]", ver={"status": "fail", "checks": []}),     # 沒過 / failed
                rec("台中天氣", "[get_weather(city='台中')]", conf=0.5)]                     # 信心低 / low confidence
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows))
            self.assertEqual(S.build(root)["skills"], 1)
            sk = S.Skills(S.skills_path(root))
            self.assertEqual(len(sk.examples("台北後天天氣如何", {"get_weather"})), 1)
            self.assertEqual(sk.examples("台北後天天氣如何", {"search"}), [])        # 函式不在清單 / unavailable

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
            self.assertTrue(any("get_weather(city='台北')" in s for s in sys_msgs))   # 附範例 / example attached
            self.assertTrue(any(r["call"] == "[get_weather(city='高雄')]" for r in gw.skills.rows))  # 學會 / learned
            self.assertEqual(len(gw.skills.rows), n)                                  # 評測流量不學 / eval not learned


if __name__ == "__main__":
    unittest.main()

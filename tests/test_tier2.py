"""第 2 層測試（add-partial-escalation）：只要回饋、本機重答；通過用第 2 層，沒通過才第 3 層。
Tier-2 tests: feedback only, local answer; pass answers at tier 2, otherwise tier 3."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi.runtime import escalation  # noqa: E402

TOOL = {"type": "function", "function": {"name": "get_weather", "parameters": {
    "type": "object", "required": ["city"], "properties": {"city": {"type": "string"}}}}}
GOOD, BAD = "[get_weather(city='台北')]", "[get_weather()]"


class Helper:
    """假的 Claude：記下收到的訊息，回傳指定的回饋或完整答案。 / A fake Claude recording what it was asked."""

    def __init__(self, feedback="- 缺少必要參數 city，請補上城市名稱。", fail=False):
        self.feedback, self.fail, self.asked = feedback, fail, []

    async def ask(self, body):
        from jiezi.runtime.consult import ConsultError
        self.asked.append(body)
        if self.fail:
            raise ConsultError("quota")
        full = not any("審稿人" in (m.get("content") or "") for m in body["messages"] if m.get("role") == "system")
        return {"content": GOOD if full else self.feedback, "model": "claude-x",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class TestTier2(unittest.TestCase):
    def post(self, answers, helper, body=None, **kw):
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, local_handler, make_supervisor
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp, **{"samples": 1, "tier2": True, **kw})
            lh, seen = local_handler([{"role": "assistant", "content": a} for a in answers])
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), consultant=helper,
                         log=lambda *_: None)
            body = body or {"model": "jiezi", "tools": [TOOL], "messages": [{"role": "user", "content": "台北的氣象資料"}]}
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"}, json=body)
            recs = [json.loads(x) for f in (tmp / "traj").glob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
            skills = list(gw.skills.rows) if gw.skills is not None else []
        return r, seen, recs, skills

    def test_feedback_then_local_answer_at_tier_2(self):
        h = Helper()
        r, seen, recs, skills = self.post([BAD, BAD, GOOD], h)
        meta = r.json()["jiezi"]
        self.assertEqual((meta["tier"], meta["verification"], meta["escalation"], meta["feedback_from"]),
                         (2, "pass", "feedback", "claude"))
        self.assertEqual(r.json()["choices"][0]["message"]["content"], GOOD)      # 本機寫的答案 / written locally
        self.assertEqual(len(h.asked), 1)                                          # 只問一次回饋，沒有整題轉交 / feedback only
        asked = h.asked[0]["messages"]
        self.assertIn("不要寫出完整的正確答案", asked[0]["content"])
        for want in ("台北的氣象資料", "get_weather", BAD, "missing required"):
            self.assertIn(want, asked[1]["content"])
        self.assertIn("缺少必要參數 city", seen[2]["messages"][-1]["content"])    # 本機第三次帶著回饋 / retried with feedback
        self.assertEqual([t["tier"] for t in recs[0]["tiers"]], [0, 1, 2])
        self.assertIs(recs[0]["training_use"], False)                              # 受協助者影響 / shaped by the helper
        self.assertIs(meta["training_use"], False)

    def test_still_failing_goes_to_tier_3(self):
        h = Helper()
        r, seen, recs, _ = self.post([BAD, BAD, BAD], h)
        meta = r.json()["jiezi"]
        self.assertEqual((meta["tier"], meta["escalation"]), (3, "verification_failed"))
        self.assertEqual(len(h.asked), 2)                                          # 回饋一次＋整題一次 / feedback, then full
        self.assertEqual([t["tier"] for t in recs[0]["tiers"]], [0, 1, 2, 3])

    def test_helper_failure_falls_through(self):
        r, _, recs, _ = self.post([BAD, BAD, GOOD], Helper(fail=True))
        self.assertEqual(recs[0]["tiers"][2]["tier"], 2)
        self.assertIn("feedback unavailable", recs[0]["tiers"][2]["error"])
        self.assertNotEqual(r.json()["jiezi"]["tier"], 2)
        r, _, recs, _ = self.post([BAD, BAD, GOOD], Helper(feedback="  "))
        self.assertEqual(recs[0]["tiers"][2]["error"], "empty feedback")

    def test_off_by_default_and_not_for_passing_or_unverified(self):
        from jiezi.runtime.settings import load_settings
        key = {"JIEZI_GATEWAY_KEY": "k" * 32}
        self.assertFalse(load_settings(Path("/x"), key).tier2)                     # 預設關閉 / off by default
        self.assertTrue(load_settings(Path("/x"), {**key, "JIEZI_TIER2": "on"}).tier2)
        h = Helper()
        r, _, recs, _ = self.post([BAD, BAD, GOOD], h, tier2=False)
        self.assertEqual(r.json()["jiezi"]["tier"], 3)                             # 關閉時和原本一樣 / unchanged when off
        self.assertEqual([t["tier"] for t in recs[0]["tiers"]], [0, 1, 3])
        h = Helper()
        r, _, _, _ = self.post([BAD, GOOD], h)
        self.assertEqual((r.json()["jiezi"]["tier"], h.asked), (1, []))            # 第 1 層過了就不問 / no feedback needed
        h = Helper()
        r, _, _, _ = self.post(["你好！"], h, body={"model": "jiezi", "messages": [{"role": "user", "content": "你好"}]})
        self.assertEqual((r.json()["jiezi"]["tier"], h.asked), (0, []))            # 沒有驗證器的問答不進第 2 層

    def test_local_only_policy_never_asks(self):
        h = Helper()
        body = {"model": "jiezi-local", "tools": [TOOL], "messages": [{"role": "user", "content": "台北的氣象資料"}]}
        r, _, _, _ = self.post([BAD, BAD, GOOD], h, body=body)
        self.assertEqual((r.json()["jiezi"]["escalation"], h.asked), ("local_only_policy", []))

    def test_prompts(self):
        req = {"messages": [{"role": "user", "content": "問"}], "response_format": {"type": "json_object"}}
        msgs = escalation.feedback_request(req, {"content": "答"}, "not valid JSON")
        self.assertIn("json_object", msgs[1]["content"])
        out = escalation.feedback_messages(req["messages"], {"content": "答"}, "錯", "意見" * 2000)
        self.assertLess(len(out[-1]["content"]), escalation.FEEDBACK_MAX_CHARS + 400)   # 回饋有長度上限 / capped
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "user"])

    def test_status_line(self):
        from jiezi.cli.client import status_line
        self.assertIn("claude 回饋", status_line({"tier": 2, "model": "core", "feedback_from": "claude"}))


if __name__ == "__main__":
    unittest.main()

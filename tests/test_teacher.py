"""老師模型（add-open-teacher）。 / Teacher models."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jiezi import teacher as T  # noqa: E402


class TestTeacher(unittest.TestCase):
    def test_forbidden_services_are_never_teachers(self):
        for m in ("claude-opus-5-5", "gemini-2.5-flash", "openrouter-claude", "openrouter-gpt-4o",
                  "openrouter-gemini-2.5-pro"):
            self.assertFalse(T.allowed(m), m)
        for m in ("cloudflare-gpt-oss-120b", "openrouter-deepseek", "nvidia-nemotron-3-ultra", "mad-glm",
                  "nvidia-kimi-k3", "amd-qwen3.8-flash-next", "openai/gpt-oss-120b"):
            self.assertTrue(T.allowed(m), m)

    def test_agreement(self):
        delivered = "2027 年的除夕是 **2 月 5 日**，春節連假從 2/4 到 2/10。"
        self.assertTrue(T.agree("除夕在 2027 年 **2 月 5 日**（星期五），連假 2/4–2/10。", delivered))
        self.assertFalse(T.agree("2027 年除夕是 1 月 25 日。", delivered, "2027 年的除夕是哪一天？"))
        kept = T.judge({"a": "除夕 2027 年 2 月 5 日，連假 2/4 到 2/10", "b": "2027 年 1 月 25 日", "c": ""}, delivered,
                       "2027 年的除夕是哪一天？")
        self.assertEqual(kept, {"a": "delivered"})
        kept = T.judge({"a": "玉山 3952 公尺", "b": "玉山高 3952 公尺"}, "我不確定")
        self.assertEqual(kept, {"a": "teacher:b", "b": "teacher:a"})          # 老師之間一致 / teachers agree

    def test_daily_cap_and_export(self):
        from datetime import date
        from jiezi import training_data as TD
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertTrue(all(T.take(root, "m", 2) for _ in range(2)))
            self.assertFalse(T.take(root, "m", 2))
            self.assertTrue(T.take(root, "n", 2))
            T.save(root, [{"role": "user", "content": "玉山多高？"}], "3952 公尺", "nvidia-nemotron-3-ultra",
                   "delivered", "t1")
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text("")
            out, _ = TD.export(root, limit_per_source=5)
            rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        t = [r for r in rows if r.get("source") == "teacher"]
        self.assertEqual(t[0]["messages"][-1]["content"], "3952 公尺")
        self.assertEqual(t[0]["teacher"], "nvidia-nemotron-3-ultra")


class TestGatewayTeachers(unittest.TestCase):
    def test_escalated_question_is_asked_to_teachers(self):
        import time
        import httpx
        from starlette.testclient import TestClient
        from test_runtime_gateway import KEY, FakeProc, TestConsult, cloud_handler, local_handler, make_supervisor
        from jiezi.runtime.consult import ClaudeCliConsultant
        from jiezi.runtime.gateway import Gateway, create_app
        from jiezi.runtime.trajectory import TrajectoryWriter
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)

            async def run(cmd, input=None, cwd=None, check=False):
                return FakeProc({**TestConsult.OK, "result": "cloud"})
            sup, _, patch = make_supervisor(tmp, consult="claude-cli", teacher_models=["nemotron-teacher", "claude-x"],
                                            cloud_base="http://cloud")
            lh, _ = local_handler([{"role": "assistant", "content": "我不知道"}])
            calls = []
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)),
                         cloud_http=httpx.AsyncClient(transport=httpx.MockTransport(cloud_handler(calls))),
                         consultant=ClaudeCliConsultant(tmp / "cwd", binary="/usr/bin/claude", run_process=run),
                         log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                           json={"messages": [{"role": "user", "content": "哪座山最高？"}]}).json()
                for _ in range(100):
                    if T.out_path(tmp).exists():
                        break
                    time.sleep(0.02)
            self.assertEqual(r["jiezi"]["provider"], "claude")
            self.assertEqual([c["model"] for c in calls if c.get("disable_fallbacks")], ["nemotron-teacher"])
            rows = T.load(tmp)
            self.assertEqual((rows[0]["teacher"], rows[0]["messages"][-1]["content"]), ("nemotron-teacher", "cloud"))


if __name__ == "__main__":
    unittest.main()

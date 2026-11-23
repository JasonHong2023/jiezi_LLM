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
            T.save(root, [{"role": "system", "content": "你是芥子"}, {"role": "system", "content": "資料：玉山 3952"},
                          {"role": "user", "content": "玉山多高？"}], "3952 公尺", "nvidia-nemotron-3-ultra",
                   "delivered", "t1")
            (root / "var" / "trajectories").mkdir(parents=True)
            (root / "var" / "trajectories" / f"{date.today().isoformat()}.jsonl").write_text("")
            out, _ = TD.export(root, limit_per_source=5)
            rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
        t = [r for r in rows if r.get("source") == "teacher"]
        self.assertFalse(any(m["role"] == "system" for r in rows for m in r["messages"][1:]))   # 只在開頭 / leading only
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




class TestTakeConcurrency(unittest.TestCase):
    """2026-11-23 實測：8 位老師同時扣額度會讀到寫一半的檔案。 / Concurrent takes must not corrupt the usage file."""

    def test_concurrent_takes_count_exactly(self):
        import tempfile
        import threading
        from pathlib import Path
        from jiezi import teacher as T
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            errors = []

            def go(model):
                try:
                    for _ in range(25):
                        T.take(root, model, 1000)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
            threads = [threading.Thread(target=go, args=(f"m{i}",)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            import json
            day = next(iter(json.loads(T.usage_path(root).read_text(encoding="utf-8")).values()))
            self.assertEqual(day, {f"m{i}": 25 for i in range(8)})

    def test_corrupt_usage_file_starts_over(self):
        import tempfile
        from pathlib import Path
        from jiezi import teacher as T
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            T.usage_path(root).parent.mkdir(parents=True)
            T.usage_path(root).write_text('{"2026-', encoding="utf-8")
            self.assertTrue(T.take(root, "m", 5))


class TestSelfAgreement(unittest.TestCase):
    """交付答案的模型也是老師時，不能拿「和交付答案一致」當理由。"""

    def test_same_model_cannot_agree_with_itself(self):
        from jiezi import teacher as T
        self.assertTrue(T.same_model("nvidia_nim/minimaxai/minimax-m3.1-flash", "minimax-m3.1-flash"))
        self.assertFalse(T.same_model("", "x"))
        q = "台北 101 有多高？"
        answers = {"minimax": "台北 101 高 508 公尺。", "ultra": "", "step": "大約 600 公尺。"}
        self.assertEqual(T.judge(answers, "台北 101 高 508 公尺。", q, {"minimax"}), {})
        self.assertEqual(T.judge(answers, "台北 101 高 508 公尺。", q), {"minimax": "delivered"})
        answers["ultra"] = "508 公尺。"
        self.assertEqual(T.judge(answers, "台北 101 高 508 公尺。", q, {"minimax"}),
                         {"minimax": "teacher:ultra", "ultra": "delivered"})


if __name__ == "__main__":
    unittest.main()

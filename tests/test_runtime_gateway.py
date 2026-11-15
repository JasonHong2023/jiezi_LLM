"""runtime 測試：設定檢查、執行期驗證器、每日上限、軌跡、supervisor（假引擎）、gateway（假本機與假雲端）。
Runtime tests: settings, runtime verifiers, daily cap, trajectories, supervisor (fake engine), gateway (fake
local and cloud). No model is loaded."""

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import anyio  # noqa: E402
import httpx  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from jiezi.config import ensure_gateway_key  # noqa: E402
from jiezi.errors import JieziError  # noqa: E402
from jiezi.runtime import escalation  # noqa: E402
from jiezi.runtime.gateway import Gateway, create_app  # noqa: E402
from jiezi.runtime.settings import Settings, load_settings  # noqa: E402
from jiezi.runtime.supervisor import EngineUnavailable, Supervisor  # noqa: E402
from jiezi.runtime.trajectory import TrajectoryWriter  # noqa: E402

KEY = "k" * 32
TOOLS = [{"type": "function", "function": {"name": "get_weather", "parameters": {
    "type": "object", "required": ["city"], "properties": {"city": {"type": "string"}, "days": {"type": "integer"}}}}}]


class TestSettings(unittest.TestCase):
    def test_local_only_and_key_required(self):
        with self.assertRaisesRegex(JieziError, "127.0.0.1"):
            load_settings(Path("."), {"JIEZI_GATEWAY_HOST": "0.0.0.0", "JIEZI_GATEWAY_KEY": KEY})
        with self.assertRaisesRegex(JieziError, "KEY"):
            load_settings(Path("."), {})
        s = load_settings(Path("/x"), {"JIEZI_GATEWAY_KEY": KEY, "JIEZI_CLOUD_ESCALATION": "on",
                                       "JIEZI_CLOUD_BASE_URL": "http://c/", "JIEZI_ESCALATION_MODELS": "a, b"})
        self.assertEqual((s.gateway_port, s.engine_port, s.escalation_models, s.cloud_ready),
                         (36100, 36101, ["a", "b"], True))
        self.assertFalse(load_settings(Path("/x"), {"JIEZI_GATEWAY_KEY": KEY}).cloud_ready)  # 預設關閉 / off

    def test_key_generation(self):
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / ".env"
            env.write_text("A=1\nJIEZI_GATEWAY_KEY=\n")
            self.assertTrue(ensure_gateway_key(Path(d)))
            text = env.read_text()
            self.assertEqual(text.count("JIEZI_GATEWAY_KEY="), 1)
            self.assertGreater(len(text.split("JIEZI_GATEWAY_KEY=")[1].strip()), 30)
            self.assertEqual(env.stat().st_mode & 0o777, 0o600)
            self.assertFalse(ensure_gateway_key(Path(d)))  # 不覆寫 / never overwritten


class TestVerifiers(unittest.TestCase):
    def call(self, args):
        return {"tool_calls": [{"type": "function", "function": {"name": "get_weather", "arguments": json.dumps(args)}}]}

    def test_tool_schema(self):
        self.assertEqual(escalation.verify_tools(TOOLS, self.call({"city": "台北"}))["status"], "pass")
        self.assertIn("missing required", escalation.verify_tools(TOOLS, self.call({}))["error"])
        self.assertIn("type", escalation.verify_tools(TOOLS, self.call({"city": "a", "days": "3"}))["error"])
        self.assertIn("unknown function", escalation.verify_tools(
            TOOLS, {"content": "[book(x=1)]"})["error"])
        self.assertEqual(escalation.verify_tools(TOOLS, {"content": "[get_weather(city='台北')]"})["status"], "pass")
        self.assertEqual(escalation.verify_tools(TOOLS, {"content": "請問哪個城市？"})["status"], "not_applicable")
        bad = {"tool_calls": [{"function": {"name": "get_weather", "arguments": "{oops"}}]}
        self.assertEqual(escalation.verify_tools(TOOLS, bad)["status"], "fail")

    def test_code_syntax_never_runs(self):
        self.assertEqual(escalation.verify_code("```python\nimport os\nos.remove('x')\n```")["status"], "pass")
        self.assertEqual(escalation.verify_code("```python\ndef f(:\n```")["status"], "fail")
        self.assertEqual(escalation.verify_code("沒有程式")["status"], "not_applicable")
        self.assertEqual(escalation.verify({}, {"content": "hi"})["status"], "not_applicable")

    def test_daily_cap(self):
        with tempfile.TemporaryDirectory() as d:
            cap = escalation.DailyCap(Path(d), 2, today=lambda: date(2026, 11, 15))
            cap.take()
            cap.take()
            self.assertFalse(cap.available())
            self.assertTrue(escalation.DailyCap(Path(d), 2, today=lambda: date(2026, 11, 16)).available())


class TestTrajectory(unittest.TestCase):
    def test_write_off_and_retention(self):
        with tempfile.TemporaryDirectory() as d:
            t = TrajectoryWriter(Path(d), retention_days=3, log=lambda *_: None)
            old = Path(d) / f"{(date.today() - timedelta(days=10)).isoformat()}.jsonl"
            old.write_text("{}\n")
            self.assertTrue(t.write({"id": "a"}))
            self.assertFalse(old.exists())
            self.assertFalse(TrajectoryWriter(Path(d) / "off", enabled=False).write({"id": "b"}))
            self.assertFalse((Path(d) / "off").exists())

    def test_write_failure_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "file"
            f.write_text("x")
            t = TrajectoryWriter(f / "sub", log=lambda *_: None)  # 父路徑是檔案 / parent is a file
            self.assertFalse(t.write({"id": "a"}))
            self.assertIsNotNone(t.last_error)


class FakeEngine:
    def __init__(self, port):
        self.base_url = f"http://engine:{port}"
        self.started = self.stopped = False
        self.dead = False
        self.proc = None

    def start(self, log_path):
        self.started = True

    def alive(self):
        return not self.dead

    def stop(self):
        self.stopped = True


def settings(tmp: Path, **kw) -> Settings:
    return Settings(root=tmp, key=KEY, gateway_port=36100, engine_port=36101, models_dir=tmp, **kw)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_supervisor(tmp: Path, clock=None, now=datetime.now, **kw):
    engines = []

    def factory(facts, path, ngl, port, alias=None):
        e = FakeEngine(port)
        engines.append(e)
        return e
    sup = Supervisor(settings(tmp, **kw), lambda: {"budgets": {"ram": {"usable_mib": 8000},
                                                               "vram": {"usable_mib": 3000}}},
                     factory, clock=clock or Clock(), now=now, log=lambda *_: None)
    core = {"name": "core", "file": "core.gguf", "path": tmp / "core.gguf", "size": 600 << 20, "sha256": "0" * 64,
            "quant": "other"}
    return sup, engines, mock.patch("jiezi.runtime.supervisor.resolve_core", return_value=core)


class TestSupervisor(unittest.TestCase):
    def test_lazy_load_idle_unload_and_reload(self):
        with tempfile.TemporaryDirectory() as d:
            clock = Clock()
            sup, engines, patch = make_supervisor(Path(d), clock, idle_unload_s=60)
            with patch:
                async def go():
                    self.assertEqual(sup.status, "unloaded")
                    self.assertEqual(await sup.acquire(), "http://engine:36101")
                    self.assertEqual((sup.status, sup.placement["placement"]), ("loaded", "gpu"))
                    sup.release()
                    clock.t += 61
                    await sup.tick()
                    self.assertEqual(sup.status, "unloaded")
                    self.assertTrue(engines[0].stopped)
                    await sup.acquire()
                    self.assertEqual(len(engines), 2)
                anyio.run(go)
            state = json.loads((Path(d) / "var" / "runtime" / "state.json").read_text())
            self.assertEqual(state["status"], "loaded")

    def test_bounded_restart(self):
        with tempfile.TemporaryDirectory() as d:
            sup, engines, patch = make_supervisor(Path(d))
            with patch:
                async def go():
                    await sup.acquire()
                    sup.release()
                    for _ in range(4):
                        engines[-1].dead = True
                        await sup.tick()
                    self.assertEqual(sup.status, "unavailable")
                    with self.assertRaises(EngineUnavailable):
                        await sup.acquire()
                anyio.run(go)
            self.assertEqual(len(engines), 4)  # 首次 + 3 次重啟 / first + 3 restarts

    def test_hold_for_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            now = [datetime(2026, 11, 16, 0, 5)]
            sup, engines, patch = make_supervisor(Path(d), now=lambda: now[0])
            with patch:
                async def go():
                    await sup.acquire()
                    sup.release()
                    r = await sup.unload(datetime(2026, 11, 16, 7, 0), "night eval")
                    self.assertEqual((r["was"], r["status"]), ("loaded", "held"))
                    with self.assertRaisesRegex(EngineUnavailable, "held"):
                        await sup.acquire()
                    now[0] = datetime(2026, 11, 16, 7, 1)
                    await sup.acquire()
                    self.assertEqual(sup.status, "loaded")
                anyio.run(go)


def local_handler(answers):
    """依序回傳本機答案的假 llama-server。 / A fake llama-server returning answers in order."""
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        msg = answers[min(len(seen) - 1, len(answers) - 1)]
        if body.get("stream"):
            lines = [f'data: {json.dumps({"id": "x", "model": "core", "choices": [{"index": 0, "delta": {"content": c}}]})}'
                     for c in ("你", "好")]
            lines.append('data: {"id": "x", "model": "core", "choices": [], "timings": {"predicted_per_second": 42.0}}')
            return httpx.Response(200, text="\n\n".join(lines + ["data: [DONE]"]) + "\n\n",
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "model": "core",
                                         "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                                         "timings": {"predicted_per_second": 40.0}})
    return handler, seen


def cloud_handler(calls, fail=False):
    def handler(request):
        calls.append(json.loads(request.content))
        if fail:
            return httpx.Response(500, json={"error": "x"})
        return httpx.Response(200, json={"model": "nemotron", "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "cloud"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 12}}, headers={"x-litellm-response-cost": "0.0"})
    return handler


class TestGateway(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def client(self, answers, cloud_on=False, cloud_fail=False, cap=200, engine_ok=True):
        sup, engines, patch = make_supervisor(
            self.tmp, cloud_escalation=cloud_on, cloud_base="http://cloud" if cloud_on else None,
            escalation_models=["nemotron"] if cloud_on else [], cloud_daily_max=cap)
        self.patch = patch
        patch.start()
        self.addCleanup(patch.stop)
        if not engine_ok:
            sup.status, sup.reason = "unavailable", "crashed"
        lh, self.local_seen = local_handler(answers)
        self.cloud_calls = []
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.tmp / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)),
                     cloud_http=httpx.AsyncClient(transport=httpx.MockTransport(cloud_handler(self.cloud_calls, cloud_fail))),
                     log=lambda *_: None)
        self.sup = sup
        return TestClient(create_app(gw))

    def post(self, c, body, key=KEY):
        return c.post("/v1/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"})

    def traj(self):
        files = list((self.tmp / "traj").glob("*.jsonl"))
        return [json.loads(line) for f in files for line in f.read_text().splitlines()]

    def test_auth_models_health(self):
        with self.client([{"role": "assistant", "content": "hi"}]) as c:
            self.assertEqual(self.post(c, {"messages": []}, key="wrong").status_code, 401)
            self.assertEqual(c.get("/v1/models").status_code, 401)
            ids = [m["id"] for m in c.get("/v1/models", headers={"Authorization": f"Bearer {KEY}"}).json()["data"]]
            self.assertEqual(ids, ["jiezi", "jiezi-local", "jiezi-cloud", "jiezi-ask-claude"])
            self.assertEqual(c.get("/health").json()["engine"]["status"], "unloaded")
            self.assertEqual(self.post(c, {"model": "gpt-4", "messages": []}).status_code, 400)
        self.assertEqual(self.traj(), [])  # 401 不寫軌跡 / no trajectory on 401

    def test_tier0_plain(self):
        with self.client([{"role": "assistant", "content": "你好"}]) as c:
            r = self.post(c, {"model": "jiezi", "messages": [{"role": "user", "content": "hi"}]}).json()
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["verification"]), (0, "not_applicable"))
        self.assertEqual(self.local_seen[0]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(self.local_seen[0]["model"], "core")
        t = self.traj()[0]
        self.assertEqual((t["final_tier"], t["policy"], t["id"]), (0, "jiezi", r["jiezi"]["trajectory_id"]))

    def test_tier1_fixes_tool_call(self):
        bad = {"role": "assistant", "content": "[get_weather()]"}
        good = {"role": "assistant", "content": "[get_weather(city='台北')]"}
        with self.client([bad, good]) as c:
            r = self.post(c, {"messages": [{"role": "user", "content": "台北天氣"}], "tools": TOOLS}).json()
        self.assertEqual(r["jiezi"]["tier"], 1)
        self.assertIn("missing required", self.local_seen[1]["messages"][-1]["content"])
        self.assertEqual([t["tier"] for t in self.traj()[0]["tiers"]], [0, 1])

    def test_escalates_to_cloud_and_daily_cap(self):
        bad = {"role": "assistant", "content": "[get_weather()]"}
        body = {"messages": [{"role": "user", "content": "x"}], "tools": TOOLS}
        with self.client([bad], cloud_on=True, cap=1) as c:
            r = self.post(c, body).json()
            self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["escalation"], r["jiezi"]["model"]),
                             (3, "verification_failed", "nemotron"))
            self.assertNotIn("chat_template_kwargs", self.cloud_calls[0])
            r = self.post(c, body).json()
            self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["escalation"]), (1, "daily_cap_reached"))
        self.assertEqual(len(self.cloud_calls), 1)

    def test_cloud_off_and_local_only(self):
        bad = {"role": "assistant", "content": "[get_weather()]"}
        with self.client([bad]) as c:
            r = self.post(c, {"messages": [{"role": "user", "content": "x"}], "tools": TOOLS}).json()
            self.assertEqual(r["jiezi"]["escalation"], "cloud_escalation_off")
            r = self.post(c, {"model": "jiezi-local", "messages": [{"role": "user", "content": "x"}],
                              "tools": TOOLS}).json()
            self.assertEqual(r["jiezi"]["escalation"], "local_only_policy")
            self.assertEqual(self.post(c, {"model": "jiezi-cloud", "messages": []}).status_code, 503)
        self.assertEqual(self.cloud_calls, [])

    def test_engine_unavailable(self):
        with self.client([{"role": "assistant", "content": "x"}], engine_ok=False) as c:
            self.assertEqual(self.post(c, {"model": "jiezi-local", "messages": []}).status_code, 503)
        with self.client([{"role": "assistant", "content": "x"}], cloud_on=True, engine_ok=False) as c:
            r = self.post(c, {"messages": [{"role": "user", "content": "x"}]}).json()
            self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["escalation"]), (3, "engine_unavailable"))

    def test_cloud_failure_falls_back_to_local(self):
        bad = {"role": "assistant", "content": "[get_weather()]"}
        with self.client([bad], cloud_on=True, cloud_fail=True) as c:
            r = self.post(c, {"messages": [{"role": "user", "content": "x"}], "tools": TOOLS}).json()
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["escalation"]), (1, "cloud_failed"))

    def test_streaming_relay_and_synthesized(self):
        with self.client([{"role": "assistant", "content": "[get_weather(city='台北')]"}]) as c:
            with c.stream("POST", "/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                          json={"messages": [{"role": "user", "content": "hi"}], "stream": True}) as r:
                events = [line[6:] for line in r.iter_lines() if line.startswith("data: ")]
            self.assertEqual(events[-1], "[DONE]")
            meta = json.loads(events[-2])["jiezi"]
            self.assertEqual((meta["tier"], meta["tps"]), (0, 42.0))
            text = "".join((json.loads(e)["choices"][0]["delta"].get("content") or "")
                           for e in events[:-2] if json.loads(e).get("choices"))
            self.assertEqual(text, "你好")
            with c.stream("POST", "/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                          json={"messages": [{"role": "user", "content": "x"}], "tools": TOOLS, "stream": True}) as r:
                events = [line[6:] for line in r.iter_lines() if line.startswith("data: ")]
            self.assertIn("get_weather", events[0])
            self.assertEqual(json.loads(events[-2])["jiezi"]["verification"], "pass")
        self.assertEqual(self.sup.in_flight, 0)
        self.assertEqual(len(self.traj()), 2)

    def test_request_size_limit_and_admin_unload(self):
        with self.client([{"role": "assistant", "content": "x"}]) as c:
            big = {"messages": [{"role": "user", "content": "x" * (2 << 20)}]}
            self.assertEqual(self.post(c, big).status_code, 413)
            r = c.post("/admin/unload", json={"hold_until": "2099-01-01T07:00:00"},
                       headers={"Authorization": f"Bearer {KEY}"}).json()
            self.assertEqual(r["status"], "held")
            self.assertEqual(self.post(c, {"model": "jiezi-local", "messages": []}).status_code, 503)


class TestCoordination(unittest.TestCase):
    """評測端的協調：只用標準函式庫，以小型 HTTP 伺服器模擬 gateway。 / Eval-side coordination with a stub gateway."""

    def serve(self, engine_status):
        import http.server
        import threading
        calls = []

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, obj):
                data = json.dumps(obj).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._json({"engine": {"status": engine_status}})

            def do_POST(self):
                calls.append((self.headers.get("Authorization"),
                              json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self._json({"was": engine_status, "status": "held"})
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        return srv.server_address[1], calls

    def write_state(self, root, port):
        (root / "var" / "runtime").mkdir(parents=True)
        (root / "var" / "runtime" / "state.json").write_text(json.dumps({"gateway_port": port}))

    def test_not_running_and_stale(self):
        from jiezi.runtime.coord import release_for_eval
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(release_for_eval(Path(d), KEY, None), "not_running")
            self.write_state(Path(d), 1)  # 沒有服務的 port / nothing listens there
            self.assertEqual(release_for_eval(Path(d), KEY, None), "not_running")

    def test_unload_and_hold(self):
        from jiezi.runtime.coord import release_for_eval
        port, calls = self.serve("loaded")
        with tempfile.TemporaryDirectory() as d:
            self.write_state(Path(d), port)
            self.assertEqual(release_for_eval(Path(d), KEY, datetime(2026, 11, 16, 7, 0)), "unloaded_for_eval")
        self.assertEqual(calls[0][0], f"Bearer {KEY}")
        self.assertEqual(calls[0][1]["hold_until"], "2026-11-16T07:00")

    def test_idle_gateway_untouched_without_hold(self):
        from jiezi.runtime.coord import release_for_eval
        port, calls = self.serve("unloaded")
        with tempfile.TemporaryDirectory() as d:
            self.write_state(Path(d), port)
            self.assertTrue(release_for_eval(Path(d), KEY, None).startswith("idle"))
        self.assertEqual(calls, [])


class FakeProc:
    def __init__(self, out: dict | str, rc: int = 0):
        self.stdout = (json.dumps(out) if isinstance(out, dict) else out).encode()
        self.stderr, self.returncode = b"", rc


class TestConsult(unittest.TestCase):
    OK = {"type": "result", "is_error": False, "result": "玉山", "total_cost_usd": 0.02,
          "usage": {"input_tokens": 2, "cache_read_input_tokens": 10, "output_tokens": 5},
          "modelUsage": {"claude-opus-5-5": {}}}

    def consultant(self, tmp, out, rc=0, seen=None):
        from jiezi.runtime.consult import ClaudeCliConsultant

        async def run(cmd, input=None, cwd=None, check=False):
            if seen is not None:
                seen.append((cmd, input.decode(), cwd))
            return FakeProc(out, rc)
        return ClaudeCliConsultant(tmp / "cwd", binary="/usr/bin/claude", run_process=run)

    def test_safe_flags_and_prompt(self):
        from jiezi.runtime import consult
        self.assertIn("--tools", consult.ARGS)
        self.assertEqual(consult.ARGS[consult.ARGS.index("--tools") + 1], "")
        for flag in ("--strict-mcp-config", "--no-session-persistence", "--setting-sources"):
            self.assertIn(flag, consult.ARGS)
        web = consult.build_args(True)
        self.assertEqual(web[web.index("--tools") + 1], "WebFetch,WebSearch")  # 只有網路工具 / web tools only
        self.assertEqual(web[web.index("--allowedTools") + 1], "WebFetch,WebSearch")
        self.assertNotIn("Bash", " ".join(web))
        p = consult.render_prompt({"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}],
                                   "tools": TOOLS})
        self.assertIn("q", p)
        self.assertIn("get_weather", p)

    def test_gateway_consult_marks_not_for_training(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            seen = []
            sup, _, patch = make_supervisor(tmp)
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         consultant=self.consultant(tmp, self.OK, seen=seen), log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                           json={"model": "jiezi-ask-claude", "messages": [{"role": "user", "content": "最高的山？"}]}).json()
            self.assertEqual(r["choices"][0]["message"]["content"], "玉山")
            self.assertEqual((r["model"], r["jiezi"]["tier"], r["jiezi"]["training_use"]),
                             ("claude-opus-5-5", "consult", False))
            self.assertEqual(sup.status, "unloaded")  # 不載入本機模型 / the local model is not loaded
            self.assertEqual(seen[0][2], str(tmp / "cwd"))
            t = json.loads(next((tmp / "traj").glob("*.jsonl")).read_text().splitlines()[0])
            self.assertIs(t["training_use"], False)
            self.assertIs(t["tiers"][0]["training_use"], False)

    def test_consult_off_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp)
            body = {"model": "jiezi-ask-claude", "messages": [{"role": "user", "content": "x"}]}
            hdr = {"Authorization": f"Bearer {KEY}"}
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None), log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                self.assertEqual(c.post("/v1/chat/completions", headers=hdr, json=body).json()["error"]["code"],
                                 "consult_off")
            bad = {"type": "result", "is_error": True, "result": "usage limit reached"}
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         consultant=self.consultant(tmp, bad), log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                r = c.post("/v1/chat/completions", headers=hdr, json=body)
            self.assertEqual(r.status_code, 503)
            self.assertIn("usage limit", r.json()["error"]["message"])

    def test_consult_settings(self):
        s = load_settings(Path("/x"), {"JIEZI_GATEWAY_KEY": KEY, "JIEZI_CONSULT": "claude-cli"})
        self.assertEqual((s.consult, s.consult_daily_max), ("claude-cli", 0))
        with self.assertRaises(JieziError):
            load_settings(Path("/x"), {"JIEZI_GATEWAY_KEY": KEY, "JIEZI_CONSULT": "openai"})


class TestAutoConsult(unittest.TestCase):
    """jiezi 自己判斷要不要請教 Claude（使用者 2026-11-15）。 / jiezi decides by itself when to consult Claude."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def run_one(self, answers, body, consult_out=None, consult_auto=True, cloud_on=False, engine_ok=True):
        from jiezi.runtime.consult import ClaudeCliConsultant
        self.asked = []

        async def run(cmd, input=None, cwd=None, check=False):
            self.asked.append(input.decode())
            return FakeProc(consult_out if consult_out is not None else TestConsult.OK)
        sup, _, patch = make_supervisor(self.tmp, consult="claude-cli", consult_auto=consult_auto,
                                        cloud_escalation=cloud_on, cloud_base="http://cloud" if cloud_on else None,
                                        escalation_models=["nemotron"] if cloud_on else [])
        if not engine_ok:
            sup.status, sup.reason = "unavailable", "crashed"
        lh, _ = local_handler(answers)
        self.cloud_calls = []
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.tmp / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)),
                     cloud_http=httpx.AsyncClient(transport=httpx.MockTransport(cloud_handler(self.cloud_calls))),
                     consultant=ClaudeCliConsultant(self.tmp / "cwd", binary="/usr/bin/claude", run_process=run),
                     log=lambda *_: None)
        with patch, TestClient(create_app(gw)) as c:
            return c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"}, json=body).json()

    def test_needs_help(self):
        self.assertEqual(escalation.needs_help({"content": "我不確定答案"}, "stop"), "self_reported_unsure")
        self.assertEqual(escalation.needs_help({"content": ""}, "length"), "truncated")
        self.assertEqual(escalation.needs_help({"content": " "}, "stop"), "empty_answer")
        self.assertIsNone(escalation.needs_help({"content": "玉山"}, "stop"))
        self.assertIsNone(escalation.needs_help({"content": "x" * 300 + "我不知道"}, "stop"))  # 只看開頭 / start only

    def test_unsure_answer_consults_claude(self):
        r = self.run_one([{"role": "assistant", "content": "抱歉，我不確定。"}],
                         {"messages": [{"role": "user", "content": "最高的山？"}]})
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["provider"], r["jiezi"]["escalation"]),
                         (3, "claude", "self_reported_unsure"))
        self.assertIs(r["jiezi"]["training_use"], False)
        self.assertEqual(r["choices"][0]["message"]["content"], "玉山")

    def test_failed_verification_consults_before_cloud(self):
        bad = {"role": "assistant", "content": "[get_weather()]"}
        r = self.run_one([bad], {"messages": [{"role": "user", "content": "x"}], "tools": TOOLS}, cloud_on=True)
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["provider"]), (3, "claude"))
        self.assertEqual(self.cloud_calls, [])
        self.assertIn("get_weather", self.asked[0])

    def test_engine_unavailable_consults(self):
        r = self.run_one([], {"messages": [{"role": "user", "content": "x"}]}, engine_ok=False)
        self.assertEqual((r["jiezi"]["provider"], r["jiezi"]["escalation"]), ("claude", "engine_unavailable"))

    def test_consult_failure_falls_back(self):
        bad_consult = {"type": "result", "is_error": True, "result": "usage limit"}
        unsure = [{"role": "assistant", "content": "我不知道"}]
        r = self.run_one(unsure, {"messages": [{"role": "user", "content": "x"}]}, consult_out=bad_consult)
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["escalation"]), (0, "consult_failed"))
        r = self.run_one(unsure, {"messages": [{"role": "user", "content": "x"}]}, consult_out=bad_consult,
                         cloud_on=True)
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["model"]), (3, "nemotron"))

    def test_auto_off_and_confident_answer(self):
        r = self.run_one([{"role": "assistant", "content": "我不知道"}],
                         {"messages": [{"role": "user", "content": "x"}]}, consult_auto=False)
        self.assertEqual((r["jiezi"]["tier"], self.asked), (0, []))
        r = self.run_one([{"role": "assistant", "content": "玉山"}], {"messages": [{"role": "user", "content": "x"}]})
        self.assertEqual((r["jiezi"]["tier"], self.asked), (0, []))

    def test_stream_appends_claude_answer(self):
        from jiezi.runtime.consult import ClaudeCliConsultant

        async def run(cmd, input=None, cwd=None, check=False):
            return FakeProc(TestConsult.OK)
        sup, _, patch = make_supervisor(self.tmp, consult="claude-cli")

        def unsure(request):
            lines = ['data: ' + json.dumps({"id": "x", "model": "core", "choices": [
                {"index": 0, "delta": {"content": "我不知道"}, "finish_reason": "stop"}]}), "data: [DONE]"]
            return httpx.Response(200, text="\n\n".join(lines) + "\n\n", headers={"content-type": "text/event-stream"})
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.tmp / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(unsure)),
                     consultant=ClaudeCliConsultant(self.tmp / "cwd", binary="/usr/bin/claude", run_process=run),
                     log=lambda *_: None)
        with patch, TestClient(create_app(gw)) as c:
            with c.stream("POST", "/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                          json={"messages": [{"role": "user", "content": "x"}], "stream": True}) as r:
                events = [line[6:] for line in r.iter_lines() if line.startswith("data: ")]
        text = "".join((json.loads(e)["choices"][0]["delta"].get("content") or "")
                       for e in events[:-1] if json.loads(e).get("choices"))
        self.assertTrue(text.startswith("我不知道"))
        self.assertIn("Claude", text)
        self.assertTrue(text.endswith("玉山"))
        meta = json.loads(events[-2])["jiezi"]
        self.assertEqual((meta["tier"], meta["provider"], meta["training_use"]), (3, "claude", False))
        self.assertEqual(sup.in_flight, 0)


class TestSystemPrompt(unittest.TestCase):
    def test_default_prompt_added_only_without_client_system(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp, system_prompt="你是芥子")
            lh, seen = local_handler([{"role": "assistant", "content": "我是芥子"}])
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)), log=lambda *_: None)
            hdr = {"Authorization": f"Bearer {KEY}"}
            with patch, TestClient(create_app(gw)) as c:
                c.post("/v1/chat/completions", headers=hdr, json={"messages": [{"role": "user", "content": "你是誰"}]})
                c.post("/v1/chat/completions", headers=hdr, json={"messages": [
                    {"role": "system", "content": "client"}, {"role": "user", "content": "x"}]})
        self.assertEqual(seen[0]["messages"][0], {"role": "system", "content": "你是芥子"})
        self.assertEqual([m["content"] for m in seen[1]["messages"] if m["role"] == "system"], ["client"])

    def test_settings(self):
        s = load_settings(Path("/x"), {"JIEZI_GATEWAY_KEY": KEY})
        self.assertIn("芥子", s.system_prompt)
        self.assertIn("繁體中文", s.system_prompt)
        self.assertIsNone(load_settings(Path("/x"), {"JIEZI_GATEWAY_KEY": KEY,
                                                     "JIEZI_SYSTEM_PROMPT_FILE": "off"}).system_prompt)


if __name__ == "__main__":
    unittest.main()

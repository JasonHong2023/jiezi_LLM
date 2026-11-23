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

from jiezi.agent import audit  # noqa: E402
from jiezi.config import ensure_gateway_key  # noqa: E402
from jiezi.errors import JieziError  # noqa: E402
from jiezi.runtime import escalation  # noqa: E402
from jiezi.runtime.gateway import Gateway, create_app  # noqa: E402
from jiezi.runtime.settings import Settings, load_settings  # noqa: E402
from jiezi.runtime.supervisor import EngineUnavailable, Supervisor  # noqa: E402
from jiezi.runtime.trajectory import TrajectoryWriter  # noqa: E402
from jiezi.scrapling_mcp import Backend  # noqa: E402
from jiezi.scrapling_policy import PolicyConfig  # noqa: E402
from jiezi.webread import WebError  # noqa: E402

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

    def test_scrapling_defaults_off_and_env(self):
        s = load_settings(Path("/x"), {"JIEZI_GATEWAY_KEY": KEY})
        self.assertFalse(s.scrapling.enabled)
        self.assertEqual(s.scrapling.allowed_hosts, frozenset())
        self.assertEqual((s.scrapling.timeout_seconds, s.scrapling.max_bytes), (15.0, 1_000_000))
        self.assertEqual(s.scrapling.approved_tools, frozenset({"make_request"}))
        s = load_settings(Path("/x"), {
            "JIEZI_GATEWAY_KEY": KEY,
            "JIEZI_SCRAPLING_MCP": "on",
            "JIEZI_SCRAPLING_ALLOWED_HOSTS": " Example.COM , books.toscrape.com ",
            "JIEZI_SCRAPLING_TIMEOUT_SECONDS": "7.5",
            "JIEZI_SCRAPLING_MAX_BYTES": "2048",
            "JIEZI_SCRAPLING_ALLOW_JS_STEALTH": "yes",
        })
        self.assertTrue(s.scrapling.enabled)
        self.assertEqual(s.scrapling.allowed_hosts, frozenset({"example.com", "books.toscrape.com"}))
        self.assertEqual((s.scrapling.timeout_seconds, s.scrapling.max_bytes), (7.5, 2048))
        self.assertEqual(s.scrapling.approved_tools, frozenset({"make_request", "browser_fetch_once"}))

    def test_scrapling_blank_numbers_use_defaults_and_bad_numbers_fail(self):
        s = load_settings(Path("/x"), {
            "JIEZI_GATEWAY_KEY": KEY,
            "JIEZI_SCRAPLING_MCP": "on",
            "JIEZI_SCRAPLING_TIMEOUT_SECONDS": " ",
            "JIEZI_SCRAPLING_MAX_BYTES": "",
        })
        self.assertEqual((s.scrapling.timeout_seconds, s.scrapling.max_bytes), (15.0, 1_000_000))
        with self.assertRaisesRegex(JieziError, "JIEZI_SCRAPLING.*invalid"):
            load_settings(Path("/x"), {"JIEZI_GATEWAY_KEY": KEY, "JIEZI_SCRAPLING_TIMEOUT_SECONDS": "abc"})


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
    # 階梯（local-first-solving）預設開；舊測試測的是沒有階梯時的各層，明確關掉，階梯另有測試
    # The ladder is on by default; older tests cover the tiers without it and switch it off
    return Settings(root=tmp, key=KEY, gateway_port=36100, engine_port=36101, models_dir=tmp,
                    **{"ladder": False, **kw})


class FakeScraplingAdapter:
    def __init__(self, text: str = "fallback body", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def fetch(self, tool: str, url: str) -> str:
        self.calls.append((tool, url))
        if self.error is not None:
            raise self.error
        return self.text

    def close(self) -> None:
        self.closed = True


class TestScraplingFallback(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def gateway(self, config: PolicyConfig) -> Gateway:
        gw = Gateway.__new__(Gateway)   # 只測 _read_urls／_scrapling_page，不載入模型或附件
        gw.s = settings(self.tmp, scrapling=config)
        gw.log = lambda *_: None
        return gw

    def test_web_fetch_success_logs_backend_and_starts_no_adapter(self):
        gw = self.gateway(PolicyConfig(enabled=True, allowed_hosts=frozenset({"example.com"})))
        body = {"messages": [{"role": "user", "content": "https://example.com/"}]}
        page = {"url": "https://example.com/", "final_url": "https://example.com/",
                "title": "Example", "text": "page body", "bytes": 9}
        with mock.patch("jiezi.webread.fetch", new=mock.AsyncMock(return_value=page)), \
                mock.patch("jiezi.scrapling_mcp.build_adapter") as build:
            rec = {}
            anyio.run(gw._read_urls, body, rec)
        self.assertEqual(rec["web_read"][0]["backend"], Backend.WEB_FETCH)
        build.assert_not_called()
        self.assertFalse(audit.audit_dir(self.tmp).exists())

    def test_disabled_scrapling_keeps_original_error(self):
        gw = self.gateway(PolicyConfig())
        body = {"messages": [{"role": "user", "content": "https://example.com/"}]}
        with mock.patch("jiezi.webread.fetch", new=mock.AsyncMock(side_effect=WebError("offline"))), \
                mock.patch("jiezi.scrapling_mcp.build_adapter") as build:
            rec = {}
            anyio.run(gw._read_urls, body, rec)
        self.assertEqual(rec["web_read"], [{"url": "https://example.com/", "why": "offline"}])
        build.assert_not_called()
        self.assertFalse(audit.audit_dir(self.tmp).exists())

    def test_enabled_scrapling_fallback_is_logged_and_audited_without_body(self):
        config = PolicyConfig(enabled=True, allowed_hosts=frozenset({"example.com"}))
        gw = self.gateway(config)
        body = {"messages": [{"role": "user", "content": "https://example.com/"}]}
        adapter = FakeScraplingAdapter()
        with mock.patch("jiezi.webread.fetch", new=mock.AsyncMock(side_effect=WebError("offline"))), \
                mock.patch("jiezi.scrapling_mcp.build_adapter", return_value=adapter) as build:
            rec = {}
            anyio.run(gw._read_urls, body, rec)
        build.assert_called_once_with(config, self.tmp)
        self.assertEqual(adapter.calls, [("make_request", "https://example.com/")])
        self.assertTrue(adapter.closed)
        self.assertEqual(rec["web_read"][0]["backend"], Backend.SCRAPLING)
        self.assertEqual((rec["web_read"][0]["fallback_from"], rec["web_read"][0]["why"]),
                         ("web-fetch", "offline"))
        self.assertIn("fallback body", body["messages"][-1]["content"])
        rows = audit.read(self.tmp)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["tool"], row["host"], row["decision"], row["status"]),
                         ("make_request", "example.com", "fallback", "selected"))
        self.assertEqual((row["backend"], row["why"]), (Backend.SCRAPLING, "offline"))
        self.assertNotIn("fallback body", repr(row))

    def test_failed_fallback_keeps_original_error_and_closes_adapter(self):
        gw = self.gateway(PolicyConfig(enabled=True, allowed_hosts=frozenset({"example.com"})))
        body = {"messages": [{"role": "user", "content": "https://example.com/"}]}
        adapter = FakeScraplingAdapter(error=RuntimeError("boom"))
        with mock.patch("jiezi.webread.fetch", new=mock.AsyncMock(side_effect=WebError("offline"))), \
                mock.patch("jiezi.scrapling_mcp.build_adapter", return_value=adapter):
            rec = {}
            anyio.run(gw._read_urls, body, rec)
        self.assertEqual(rec["web_read"], [{"url": "https://example.com/", "why": "offline"}])
        self.assertTrue(adapter.closed)
        self.assertEqual(audit.read(self.tmp)[0]["decision"], "fallback")


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
                    with self.assertRaisesRegex(EngineUnavailable, "reserved for an evaluation until 2026"):
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

    def client(self, answers, cloud_on=False, cloud_fail=False, cap=200, engine_ok=True, samples=1):
        sup, engines, patch = make_supervisor(
            self.tmp, cloud_escalation=cloud_on, cloud_base="http://cloud" if cloud_on else None,
            escalation_models=["nemotron"] if cloud_on else [], cloud_daily_max=cap, samples=samples)
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

    def test_oversized_tool_list_gets_a_clear_error_or_escalates(self):
        # 2026-11-17 實測：OpenCode 一次送 58,000 token 的工具清單，本機引擎只會回 400
        tools = [{"type": "function", "function": {"name": f"tool_{i}", "description": "說明" * 200,
                                                    "parameters": {"type": "object", "properties": {}}}} for i in range(60)]
        body = {"model": "jiezi-local", "messages": [{"role": "user", "content": "hi"}], "tools": tools}
        with self.client([{"role": "assistant", "content": "不該送到本機"}]) as c:
            r = self.post(c, body)
            self.assertEqual(r.status_code, 413)
            self.assertEqual(r.json()["error"]["code"], "context_too_large")
            self.assertEqual(self.local_seen, [])                               # 沒有送到引擎 / never reached the engine
        with self.client([{"role": "assistant", "content": "不該送到本機"}], cloud_on=True) as c:
            r = self.post(c, {**body, "model": "jiezi"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["jiezi"]["escalation"], "context_too_large")
            self.assertEqual(self.local_seen, [])

    def test_tool_filter_lets_agent_requests_run_locally(self):
        # add-client-tool-filter：60 個無關工具＋必留 read＋相關的 weather_lookup → 篩完放得下，走本機
        noise = [{"type": "function", "function": {"name": f"tool_{i}", "description": "說明" * 200,
                                                    "parameters": {"type": "object", "properties": {}}}} for i in range(60)]
        keep = [{"type": "function", "function": {"name": n, "description": d, "parameters": {"type": "object", "properties": {}}}}
                for n, d in (("read", "Read a file"), ("weather_lookup", "Get the weather forecast for a city"))]
        body = {"model": "jiezi-local", "messages": [{"role": "user", "content": "what is the weather in Taipei"}],
                "tools": noise[:30] + keep + noise[30:]}
        with self.client([{"role": "assistant", "content": "晴"}]) as c:
            r = self.post(c, body)
            self.assertEqual(r.status_code, 200)
        self.assertEqual([t["function"]["name"] for t in self.local_seen[0]["tools"]], ["read", "weather_lookup"])
        tf = self.traj()[0]["tool_filter"]
        self.assertEqual((tf["original"], tf["kept"], tf["stage"]), (62, 2, "full"))

    def test_protected_tool_too_big_still_413(self):
        huge = {"type": "object", "properties": {"p": {"type": "string", "enum": [f"值{j}" for j in range(3000)]}}}
        tools = [{"type": "function", "function": {"name": "read", "description": "說明" * 3000, "parameters": huge}}]
        body = {"model": "jiezi-local", "messages": [{"role": "user", "content": "hi"}], "tools": tools}
        with self.client([{"role": "assistant", "content": "x"}]) as c:
            self.assertEqual(self.post(c, body).status_code, 413)              # 必留工具本身就太大 / protected tool too big

    def test_escalation_carries_only_the_filtered_tools(self):
        # OQ0 (C)：放不下就轉交雲端，但只帶篩過的工具，省雲端 token
        huge = {"type": "object", "properties": {f"p{i}": {"type": "string", "enum": [f"值{j}" for j in range(1000)]}
                                                 for i in range(5)}}
        tools = [{"type": "function", "function": {"name": "bash", "description": "Run a shell command", "parameters": huge}}]
        tools += [{"type": "function", "function": {"name": f"tool_{i}", "description": "說明" * 200,
                                                     "parameters": {"type": "object", "properties": {}}}} for i in range(60)]
        body = {"model": "jiezi", "messages": [{"role": "user", "content": "run the shell command ls"}], "tools": tools}
        with self.client([{"role": "assistant", "content": "不該送到本機"}], cloud_on=True) as c:
            r = self.post(c, body)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["jiezi"]["escalation"], "context_too_large")
        self.assertEqual(self.local_seen, [])
        self.assertEqual([t["function"]["name"] for t in self.cloud_calls[0]["tools"]], ["bash"])
        self.assertEqual(self.traj()[0]["tool_filter"]["stage"], "exhausted")

    def test_admin_memory_lists_topics_and_lessons(self):
        # local-first-solving 3.3：狀態頁列出記憶主題與經驗（只有標題、計數、摘要）
        from jiezi.experience import Experience
        from jiezi.memory import Memory, wiki_path
        with self.client([{"role": "assistant", "content": "x"}]) as c:
            wiki = wiki_path(self.sup.s.root)
            Memory(wiki).save_note("我住台中")
            Experience(wiki).record("台北到高雄多遠", "數字錯", "retry", "先查距離再算")
            self.assertEqual(c.get("/admin/memory").status_code, 401)
            out = c.get("/admin/memory", headers={"Authorization": f"Bearer {KEY}"}).json()
        self.assertEqual(out["topics"][0]["note"], 1)
        self.assertEqual((out["lessons"][0]["lesson"], out["lessons"][0]["active"]), ("先查距離再算", True))

    def test_holiday_question_is_grounded_locally(self):
        from jiezi import laws as L
        from test_holidays import blob, manifest
        data = blob()
        (self.tmp / "laws").mkdir()
        (self.tmp / "laws" / "manifest.toml").write_text(manifest(data), encoding="utf-8")
        L.build(self.tmp, download=lambda u, d: d.write_bytes(data), log=lambda *_: None)
        answer = {"role": "assistant", "content": "依本機法規計算，2027 年 2 月 5 日是除夕。"}
        with self.client([answer], cloud_on=True) as c:
            r = self.post(c, {"model": "jiezi", "messages": [{"role": "user", "content": "台灣2027年的國定假日有哪些?"}]}).json()
        self.assertEqual((r["jiezi"]["tier"], self.cloud_calls), (0, []))
        self.assertTrue(any("【計算】" in m["content"] and "2027-02-05" in m["content"]
                            for m in self.local_seen[0]["messages"] if m["role"] == "system"))
        self.assertIn("computed-holidays", [s["source"] for s in r["jiezi"]["sources"]])
        out = r["choices"][0]["message"]["content"]
        self.assertIn("【計算】", out)
        self.assertIn("【法規出處】", out)

    def test_stale_claude_memory_does_not_override_holiday_calculation(self):
        from jiezi import laws as L
        from jiezi.memory import Memory, wiki_path
        from test_holidays import blob, manifest
        data = blob()
        (self.tmp / "laws").mkdir()
        (self.tmp / "laws" / "manifest.toml").write_text(manifest(data), encoding="utf-8")
        L.build(self.tmp, download=lambda u, d: d.write_bytes(data), log=lambda *_: None)
        Memory(wiki_path(self.tmp)).save_answer("台灣2027年的國定假日有哪些?", "舊答案：不是 2 月 5 日。",
                                                "claude", "claude-opus-5-5")
        answer = {"role": "assistant", "content": "依本機法規計算，2027 年 2 月 5 日是除夕。"}
        with self.client([answer], cloud_on=True) as c:
            r = self.post(c, {"model": "jiezi", "messages": [
                {"role": "user", "content": "台灣2027年的國定假日有哪些?"}]}).json()
        self.assertEqual((r["jiezi"]["tier"], self.cloud_calls), (0, []))
        self.assertIn("computed-holidays", [s["source"] for s in r["jiezi"]["sources"]])
        out = r["choices"][0]["message"]["content"]
        self.assertIn("【計算】", out)
        self.assertNotIn("舊答案", out)
        self.assertFalse(any("舊答案" in m["content"] for m in self.local_seen[0]["messages"]))

    def test_document_words_do_not_trigger_web_routing(self):
        from jiezi.documents import attach
        q = attach({"name": "週會.txt", "text": "決議：新版網站 12 月 1 日上線。\n待辦：王小明完成測試"}, "待辦事項有哪些？")
        with self.client([{"role": "assistant", "content": "王小明完成測試"}], cloud_on=True) as c:
            r = self.post(c, {"model": "jiezi", "messages": [{"role": "user", "content": q}]}).json()
            self.assertEqual(r["jiezi"]["tier"], 0)                              # 不因文件裡的「網站」轉交
            r = self.post(c, {"model": "jiezi", "messages": [{"role": "user", "content": "今天台北天氣如何？"}]}).json()
            self.assertEqual(r["jiezi"]["escalation"], "needs_web")             # 問題本身要上網照舊轉交

    def test_parallel_sampling_picks_verified_majority(self):
        bad = {"role": "assistant", "content": "[get_weather()]"}
        good = {"role": "assistant", "content": "[get_weather(city='台北')]"}
        other = {"role": "assistant", "content": "[get_weather(city='高雄')]"}
        with self.client([bad, good, other, good], samples=4) as c:
            r = self.post(c, {"messages": [{"role": "user", "content": "台北天氣"}], "tools": TOOLS}).json()
        self.assertEqual(r["choices"][0]["message"]["content"], good["content"])  # 通過驗證的多數 / verified majority
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["confidence"]), (0, 0.5))
        self.assertEqual(len(self.local_seen), 4)
        self.assertEqual({b["seed"] for b in self.local_seen}, {1000, 1001, 1002, 1003})
        self.assertTrue(all(b["temperature"] == 0.7 for b in self.local_seen))
        t = self.traj()[0]["tiers"][0]
        self.assertEqual([x["verification"] for x in t["samples"]], ["fail", "pass", "pass", "pass"])

    def test_sampling_skips_plain_chat_and_streams_code(self):
        with self.client([{"role": "assistant", "content": "你好"}], samples=4) as c:
            self.post(c, {"messages": [{"role": "user", "content": "hi"}]})
            self.assertEqual(len(self.local_seen), 1)                              # 閒聊不取樣 / chat not sampled
            r = self.post(c, {"messages": [{"role": "user", "content": "寫一個 Python 函式算平方"}]}).json()
        self.assertEqual(len(self.local_seen), 5)                                   # 程式題取 4 個 / code sampled
        self.assertIsNotNone(r["jiezi"]["confidence"])

    def test_router_v0_sends_web_questions_straight_to_claude(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sup, _, patch = make_supervisor(tmp, consult="claude-cli", samples=1)
            lh, seen = local_handler([{"role": "assistant", "content": "本機回答"}])
            gw = Gateway(sup.s, sup, TrajectoryWriter(tmp / "traj", log=lambda *_: None),
                         local_http=httpx.AsyncClient(transport=httpx.MockTransport(lh)),
                         consultant=TestConsult("test_safe_flags_and_prompt").consultant(tmp, TestConsult.OK),
                         log=lambda *_: None)
            with patch, TestClient(create_app(gw)) as c:
                h = {"Authorization": f"Bearer {KEY}"}
                r = c.post("/v1/chat/completions", headers=h,
                           json={"messages": [{"role": "user", "content": "今天台北天氣如何？"}]}).json()
                self.assertEqual((r["jiezi"]["escalation"], len(seen)), ("needs_web", 0))  # 沒先問本機 / no local try
                r = c.post("/v1/chat/completions", headers=h,
                           json={"messages": [{"role": "user", "content": "今天星期幾？"}]}).json()
                self.assertEqual((r["jiezi"]["tier"], len(seen)), (0, 1))                 # 程式算得出 / computed
                r = c.post("/v1/chat/completions", headers=h,
                           json={"messages": [{"role": "user", "content": "我今天心情不好"}]}).json()
                self.assertEqual((r["jiezi"]["tier"], len(seen)), (0, 2))                 # 閒聊照常 / chat stays local

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
            events = [e for e in events if "jiezi.progress" not in e]             # 進度事件另測 / tested separately
            self.assertIn("get_weather", events[0])
            self.assertEqual(json.loads(events[-2])["jiezi"]["verification"], "pass")
        self.assertEqual(self.sup.in_flight, 0)
        self.assertEqual(len(self.traj()), 2)

    def stream_events(self, c, body):
        with c.stream("POST", "/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                      json={**body, "stream": True}) as r:
            return r.status_code, [json.loads(line[6:]) for line in r.iter_lines()
                                   if line.startswith("data: ") and line[6:] != "[DONE]"]

    def test_progress_events(self):
        """add-progress-events：回答前送階段、一般 chunk 不變、錯誤碼照舊、可關閉。"""
        with self.client([{"role": "assistant", "content": "你好"}, {"role": "assistant", "content": "[get_weather(city='台北')]"}]) as c:
            code, events = self.stream_events(c, {"messages": [{"role": "user", "content": "hi"}]})
            stages = [e["jiezi_progress"]["stage"] for e in events if e.get("object") == "jiezi.progress"]
            self.assertEqual(stages, ["loading_model", "thinking"])                  # 冷啟動 / cold start
            self.assertTrue(all(e["choices"] == [] for e in events if e.get("object") == "jiezi.progress"))
            answer = [e for e in events if e.get("object") != "jiezi.progress"]
            text = "".join((e["choices"][0]["delta"].get("content") or "") for e in answer if e.get("choices"))
            self.assertEqual(text, "你好")                                           # 回答不變 / answer unchanged
            self.assertEqual(answer[-1]["jiezi"]["tier"], 0)
            code, events = self.stream_events(c, {"messages": [{"role": "user", "content": "x"}], "tools": TOOLS})
            stages = [e["jiezi_progress"]["stage"] for e in events if e.get("object") == "jiezi.progress"]
            self.assertEqual(stages, ["thinking"])                                    # 已載入 / already loaded
            self.assertEqual(events[-1]["jiezi"]["verification"], "pass")
            code, _ = self.stream_events(c, {"model": "jiezi-cloud", "messages": [{"role": "user", "content": "x"}]})
            self.assertEqual(code, 503)                                               # 送出前的錯誤照舊 / HTTP code kept
            r = self.post(c, {"messages": [{"role": "user", "content": "hi"}]}).json()
            self.assertNotIn("jiezi_progress", json.dumps(r))                        # 非串流沒有 / not for non-stream
        self.assertEqual(self.sup.in_flight, 0)

    def test_progress_off(self):
        with self.client([{"role": "assistant", "content": "你好"}]) as c:
            self.sup.s.progress = False
            _, events = self.stream_events(c, {"messages": [{"role": "user", "content": "hi"}]})
        self.assertFalse(any(e.get("object") == "jiezi.progress" for e in events))

    def test_request_size_limit_and_admin_unload(self):
        with self.client([{"role": "assistant", "content": "x"}]) as c:
            big = {"messages": [{"role": "user", "content": "x" * (9 << 20)}]}  # 上限 8 MB / limit is 8 MB
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

    def test_path_without_file_is_not_escalated(self):
        """只打路徑沒附檔，「看不到」就是正確答案（2026-11-18 實測被轉給 Claude）。 / No escalation for a bare path."""
        r = self.run_one([{"role": "assistant", "content": "抱歉，我無法看到你電腦上的檔案，請用 /image 附上圖片。"}],
                         {"messages": [{"role": "user", "content": r"'D:\download\a.jpg' 這圖片中有那些動物"}]})
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["escalation"]), (0, None))
        self.assertEqual(self.asked, [])
        self.assertIn("只輸出要給使用者看的回答本身", __import__("jiezi.runtime.consult", fromlist=["x"]).render_prompt(
            {"messages": [{"role": "user", "content": "x"}]}))

    def test_failed_verification_consults_before_cloud(self):
        bad = {"role": "assistant", "content": "[get_weather()]"}
        r = self.run_one([bad], {"messages": [{"role": "user", "content": "x"}], "tools": TOOLS}, cloud_on=True)
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["provider"]), (3, "claude"))
        self.assertEqual(self.cloud_calls, [])
        self.assertIn("get_weather", self.asked[0])

    def test_consulted_text_call_becomes_tool_calls(self):
        """Claude 用文字寫的 `[f(a=1)]` 要轉成 tool_calls，Hermes 才會執行（2026-11-18 Hermes 停住）。
        A consulted text call is returned as tool_calls so agents act on it."""
        bad = {"role": "assistant", "content": "[get_weather()]"}
        out = {**TestConsult.OK, "result": '[get_weather(city="台北", days=2)]'}
        r = self.run_one([bad], {"messages": [{"role": "user", "content": "台北天氣"}], "tools": TOOLS}, consult_out=out)
        choice = r["choices"][0]
        self.assertEqual(choice["finish_reason"], "tool_calls")
        self.assertIsNone(choice["message"]["content"])
        fn = choice["message"]["tool_calls"][0]["function"]
        self.assertEqual((fn["name"], json.loads(fn["arguments"])), ("get_weather", {"city": "台北", "days": 2}))
        # 不是整段呼叫、或函式不在清單裡：照文字回 / prose or unknown functions stay text
        from jiezi.runtime.escalation import text_calls_to_tool_calls
        for text in ("先查一下：[rm_rf(path='/')]", "[rm_rf(path='/')]", "[1, 2]", "答案是 [1]"):
            msg = {"role": "assistant", "content": text}
            self.assertFalse(text_calls_to_tool_calls(msg, TOOLS), text)
            self.assertEqual(msg["content"], text)
        msg = {"role": "assistant", "content": "```\n[get_weather(city='x')]\n```"}
        self.assertTrue(text_calls_to_tool_calls(msg, TOOLS))
        # 呼叫前夾了漏出的思考（2026-11-18 Hermes 第二次停住）：丟掉前文、轉成呼叫 / leaked reasoning before the call
        msg = {"role": "assistant", "content": "Next sensible step: try [x] first. Output the function call."
                                               "[get_weather(city='台北')]"}
        self.assertTrue(text_calls_to_tool_calls(msg, TOOLS))
        self.assertIsNone(msg["content"])
        self.assertEqual(json.loads(msg["tool_calls"][0]["function"]["arguments"]), {"city": "台北"})
        msg = {"role": "assistant", "content": "[get_weather(city='x')] 是我會用的呼叫。"}  # 呼叫不在結尾 / not at the end
        self.assertFalse(text_calls_to_tool_calls(msg, TOOLS))

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


class TestConsultModelPick(unittest.TestCase):
    def test_costliest_model_wins(self):
        from jiezi.runtime.consult import ClaudeCliConsultant
        out = {"type": "result", "is_error": False, "result": "ok", "usage": {},
               "modelUsage": {"claude-haiku-5-5": {"outputTokens": 900, "costUSD": 0.001},
                              "claude-fable-5-2": {"outputTokens": 200, "costUSD": 0.05}}}

        async def run(cmd, input=None, cwd=None, check=False):
            return FakeProc(out)
        with tempfile.TemporaryDirectory() as d:
            c = ClaudeCliConsultant(Path(d), binary="/usr/bin/claude", run_process=run)
            self.assertEqual(anyio.run(c.ask, {"messages": []})["model"], "claude-fable-5-2")


if __name__ == "__main__":
    unittest.main()


class TestHistoryAppendix(unittest.TestCase):
    """對話紀錄裡系統加的附錄要拿掉、問芥子自己不附知識庫（使用者 2026-11-18：「回答怪怪的」）。
    Gateway appendices are stripped from the history; questions about Jiezi get no knowledge-base text."""

    def test_strip_appendix(self):
        from jiezi.runtime.gateway import strip_appendix
        a = "除夕是 2/5。\n\n---\n【計算】\n- 國曆 2027 年裡的除夕是 2027-02-05\n\n---\n【參考資料】\n- x"
        self.assertEqual(strip_appendix(a), "除夕是 2/5。")
        self.assertEqual(strip_appendix("分隔線\n---\n不是附錄"), "分隔線\n---\n不是附錄")
        self.assertEqual(strip_appendix("模型自己寫的\n---\n【計算】\n- 根據已知資料"), "模型自己寫的")

    def test_creative_requests(self):
        from jiezi.runtime.gateway import CREATIVE
        for q in ("說一個笑話", "寫一首詩給媽媽", "講個故事", "出個謎語"):
            self.assertTrue(CREATIVE.search(q), q)
        for q in ("靜夜思的作者是誰", "台灣2027年的國定假日有哪些?", "這首詩在說什麼"):
            self.assertFalse(CREATIVE.search(q), q)
        from jiezi.memory import storable
        self.assertEqual(storable("說一個笑話"), "creative")                  # 不存也不拿舊答案 / never remembered

    def test_self_question_skips_grounding(self):
        from jiezi.runtime.gateway import Gateway
        import types
        gw = Gateway.__new__(Gateway)
        gw.s = types.SimpleNamespace(tools=True)
        gw.memory = gw.dictionary = gw.curriculum = gw.knowledge = gw.writing = gw.laws = None
        body = {"messages": [{"role": "user", "content": "你好!! 你自我介紹一下"}]}
        rec = {}
        gw._ground(body, rec, [])
        self.assertEqual(rec.get("grounding_skipped"), "about_jiezi")
        self.assertEqual(len(body["messages"]), 1)


class TestFewerClaudeEscalations(unittest.TestCase):
    """轉給 Claude 的次數要降低（使用者 2026-11-18）。 / Fewer escalations to Claude."""

    def test_keep_local_for_self_feedback_and_paths(self):
        from jiezi.runtime.gateway import Gateway
        k = Gateway._keep_local
        for q in ("你知道你在哪裡嗎?", "又出現簡體中文字", "你剛剛講錯了"):
            rec = {}
            self.assertIsNone(k("self_reported_unsure", {"messages": [{"role": "user", "content": q}]}, rec), q)
            self.assertIn(rec["kept_local"], ("about_jiezi", "feedback"))
        self.assertIsNone(k("self_reported_unsure", {"messages": [{"role": "user", "content": "x"}]}, {"path_note": ["a"]}))
        body = {"messages": [{"role": "user", "content": "薛影仪的单曲是哪一年发行的？"}]}
        self.assertEqual(k("self_reported_unsure", body, {}), "self_reported_unsure")      # 真的不知道 / really unknown
        self.assertEqual(k("unsupported_claims", {"messages": [{"role": "user", "content": "你是誰"}]}, {}),
                         "unsupported_claims")

    def test_transcript_is_not_a_web_question(self):
        from jiezi.runtime.gateway import LIVE, TRANSCRIPT
        q = "User: hi\n\nAssistant: 嗨，我是你的 Hermes Agent 助理，可以幫你查網站。\n\n請用 5 個字以內下標題"
        self.assertTrue(LIVE.search(q) and TRANSCRIPT.search(q))
        self.assertIsNone(TRANSCRIPT.search("今天台北的天氣如何？"))

    def test_route_for_prefers_cloud_when_too_large(self):
        import types
        from jiezi.runtime.gateway import Gateway
        gw = Gateway.__new__(Gateway)
        gw._can_escalate = lambda: None
        gw._auto_route = lambda: "consult"
        self.assertEqual(gw._route_for("context_too_large"), "cloud")
        self.assertEqual(gw._route_for("engine_unavailable"), "cloud")
        self.assertEqual(gw._route_for("unsupported_claims"), "consult")
        gw._can_escalate = lambda: "cloud_off"
        self.assertEqual(gw._route_for("context_too_large"), "consult")              # 雲端沒開照舊 / cloud off
        _ = types

    def test_escalation_stats(self):
        from jiezi.runtime.stats import escalations
        recs = [{"at": "2026-11-18T10:00:00", "policy": "jiezi", "tiers": [{"tier": 0}, {"tier": 3, "provider": "claude",
                                                                                           "reason": "needs_web"}]},
                {"at": "2026-11-18T11:00:00", "policy": "jiezi", "tiers": [{"tier": 3, "provider": "cloud",
                                                                           "reason": "context_too_large"}]},
                {"at": "2026-11-18T12:00:00", "policy": "jiezi", "tiers": [{"tier": 3, "provider": "claude", "error": "x"},
                                                                           {"tier": 3, "provider": "cloud",
                                                                            "reason": "unsupported_claims"}]},
                {"at": "2026-11-17T09:00:00", "policy": "jiezi-ask-claude", "tiers": [{"provider": "claude"}]},
                {"at": "2026-11-17T09:00:00", "policy": "jiezi", "tiers": [{"tier": 0}]},
                {"at": "2026-11-17T09:00:00", "eval": True, "tiers": [{"provider": "claude"}]}]
        out = escalations(recs)
        self.assertEqual(out["total"], {"requests": 5, "claude": 2, "cloud": 2})
        self.assertEqual(out["days"][0]["day"], "2026-11-18")
        self.assertEqual(out["days"][0]["reasons"], {"claude:needs_web": 1, "cloud:context_too_large": 1,
                                                     "cloud:unsupported_claims": 1})
        self.assertEqual(out["days"][1]["reasons"], {"claude:policy": 1})


class TestLadder(unittest.TestCase):
    """本機先試到底、Claude 最後；解題過程變成經驗（local-first-solving，使用者 2026-11-18）。
    The local model tries every rung before Claude, and the solving process becomes experience."""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.addCleanup(self._t.cleanup)

    def gateway(self, local, consult_out=None, stream_local=None, **kw):
        from jiezi.runtime.consult import ClaudeCliConsultant
        self.asked = []

        async def run(cmd, input=None, cwd=None, check=False):
            self.asked.append(input.decode())
            return FakeProc(consult_out or TestConsult.OK)
        sup, _, patch = make_supervisor(self.tmp, consult="claude-cli", ladder=True, memory=True, **kw)
        handler, self.seen = local_handler(local)
        if stream_local is not None:
            plain = handler

            def handler(request):                       # noqa: F811 - 第一次串流、之後非串流 / stream first
                body = json.loads(request.content)
                if body.get("stream"):
                    self.seen.append(body)
                    lines = ['data: ' + json.dumps({"id": "x", "model": "core", "choices": [
                        {"index": 0, "delta": {"content": stream_local}, "finish_reason": "stop"}]}), "data: [DONE]"]
                    return httpx.Response(200, text="\n\n".join(lines) + "\n\n",
                                          headers={"content-type": "text/event-stream"})
                return plain(request)
        gw = Gateway(sup.s, sup, TrajectoryWriter(self.tmp / "traj", log=lambda *_: None),
                     local_http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
                     consultant=ClaudeCliConsultant(self.tmp / "cwd", binary="/usr/bin/claude", run_process=run),
                     log=lambda *_: None)
        return gw, patch

    def ask(self, gw, patch, q):
        with patch, TestClient(create_app(gw)) as c:
            r = c.post("/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                       json={"messages": [{"role": "user", "content": q}]}).json()
            import time as _t
            for _ in range(50):                             # 等背景寫經驗 / wait for the lesson writer
                if list((self.tmp / "var" / "memory" / "wiki" / "experience").glob("*.md")):
                    break
                _t.sleep(0.02)
        return r

    def test_unsure_then_local_retry_solves_it(self):
        gw, patch = self.gateway([{"role": "assistant", "content": "抱歉，我不確定。"},
                                  {"role": "assistant", "content": "梅花"},
                                  {"role": "assistant", "content": "國花題要先想清楚官方核定的是哪一種花。"}])
        r = self.ask(gw, patch, "中華民國的國花是什麼？")
        self.assertEqual((r["choices"][0]["message"]["content"], r["jiezi"]["tier"]), ("梅花", 1))
        self.assertEqual(self.asked, [])                                           # 沒請教 Claude / no Claude
        self.assertEqual([s["label"] for s in r["jiezi"]["process"]], ["本機作答", "本機重答（附上錯誤）"])
        files = list((self.tmp / "var" / "memory" / "wiki" / "experience").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        self.assertIn("國花題要先想清楚", text)
        self.assertIn("帶著錯誤重答", text)

    def test_every_rung_fails_then_claude(self):
        unsure = {"role": "assistant", "content": "我不知道"}
        gw, patch = self.gateway([unsure, unsure, unsure, {"role": "assistant", "content": "要先查清楚。"}])
        r = self.ask(gw, patch, "薛影仪的单曲是哪一年发行的？")
        self.assertEqual((r["jiezi"]["tier"], r["jiezi"]["provider"]), (3, "claude"))
        self.assertEqual([s["label"] for s in r["jiezi"]["process"]],
                         ["本機作答", "本機重答（附上錯誤）", "本機深入思考後重答", "請教 Claude"])
        think = [b for b in self.seen if (b.get("chat_template_kwargs") or {}).get("enable_thinking")]
        self.assertEqual(len(think), 1)                                            # 只有那一步開思考 / one rung only
        self.assertEqual(len(self.asked), 1)

    def test_experience_is_attached_next_time(self):
        from jiezi.experience import Experience
        from jiezi.memory import wiki_path
        Experience(wiki_path(self.tmp)).record("2027 年台灣的國定假日有哪些？", "unsupported_claims：x", "retry",
                                               "國定假日要先查補假規則，不要自己推算。")
        gw, patch = self.gateway([{"role": "assistant", "content": "元旦、春節……"}])
        r = self.ask(gw, patch, "2028 年台灣的國定假日有哪些？")
        sent = json.dumps(self.seen[0]["messages"], ensure_ascii=False)
        self.assertIn("國定假日要先查補假規則", sent)
        self.assertIn("參考過去的經驗", [s["label"] for s in r["jiezi"]["process"]])
        e = Experience(wiki_path(self.tmp)).load()[0]
        self.assertEqual((e.uses, e.wins), (1, 1))                                 # 用了、答對 / used and helped

    def test_streaming_retry_replaces_the_answer(self):
        # 串流請求也佔一個順位 / the streamed request takes the first slot
        gw, patch = self.gateway([{"role": "assistant", "content": "（串流）"}, {"role": "assistant", "content": "梅花"},
                                  {"role": "assistant", "content": "要先想清楚。"}], stream_local="我不確定")
        with patch, TestClient(create_app(gw)) as c:
            with c.stream("POST", "/v1/chat/completions", headers={"Authorization": f"Bearer {KEY}"},
                          json={"messages": [{"role": "user", "content": "中華民國的國花是什麼？"}],
                                "stream": True}) as r:
                text = "".join(line for line in r.iter_lines())
        self.assertIn("本機重新想過，以下是新的回答", text)
        self.assertIn("梅花", text)
        self.assertEqual(self.asked, [])

    def test_experience_store_counts_and_disables(self):
        from jiezi.experience import FAIL_LIMIT, Experience
        ex = Experience(self.tmp / "wiki")
        e = ex.record("台北101有多高？", "x", "retry", "高度題用資料裡的數字。")
        ex.record("台北101有多高", "y", "think", "")                              # 同一種題目合併 / merged
        self.assertEqual([x.seen for x in ex.load()], [2])
        self.assertEqual([x.id for x in ex.relevant("台北101大樓多高？")], [e.id])
        ex.outcome([e.id], False)
        for _ in range(FAIL_LIMIT - 1):
            ex.outcome([e.id], False)
        self.assertEqual(ex.relevant("台北101大樓多高？"), [])                     # 無效三次停用 / disabled

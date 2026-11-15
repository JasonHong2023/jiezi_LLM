"""客戶端測試：ask 的輸出與結束碼、狀態行、Herdr 回報、chat 的按鍵與版面（假 gateway，不載入模型）。
Client tests: ask output and exit codes, status line, Herdr reporting, chat keys and layout (fake gateway)."""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import anyio  # noqa: E402
import httpx  # noqa: E402
from rich.cells import cell_len  # noqa: E402

from jiezi.cli import ask, chat  # noqa: E402
from jiezi.cli.client import Connection, status_line  # noqa: E402
from jiezi.cli.herdr import HerdrReporter  # noqa: E402

CONN = Connection("http://gw", "k" * 32)
META = {"tier": 0, "model": "qwen3-0.6b-q8_0", "tps": 150.0, "latency_s": 1.2, "verification": "pass",
        "escalation": None, "cloud": None}


def gateway(status=200, chunks=("你", "好"), meta=META, seen=None):
    def handler(request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "engine unavailable", "code": "engine_unavailable"}})
        if not body.get("stream"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "".join(chunks)}}], "jiezi": meta})
        lines = [f'data: {json.dumps({"choices": [{"delta": {"content": c}}]})}' for c in chunks]
        lines += [f'data: {json.dumps({"choices": [], "jiezi": meta})}', "data: [DONE]"]
        return httpx.Response(200, text="\n\n".join(lines) + "\n\n")
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TTY(io.StringIO):
    def __init__(self, text="", tty=False):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


class TestAsk(unittest.TestCase):
    def run_ask(self, stdin="", stdin_tty=True, stdout_tty=False, as_json=False, **gw):
        seen = []
        out, err = TTY(tty=stdout_tty), TTY()
        rc = anyio.run(ask.run_ask, "摘要", "jiezi", CONN, as_json, TTY(stdin, stdin_tty), out, err,
                       gateway(seen=seen, **gw))
        return rc, out.getvalue(), err.getvalue(), seen

    def test_pipe_prints_answer_only_and_attaches_stdin(self):
        rc, out, err, seen = self.run_ask(stdin="報告內容", stdin_tty=False)
        self.assertEqual((rc, out), (0, "你好\n"))
        msg = seen[0]["messages"][0]["content"]
        self.assertTrue(msg.startswith("報告內容") and msg.endswith("摘要"))
        self.assertNotIn("\033", out)

    def test_terminal_adds_status_line(self):
        rc, out, _, _ = self.run_ask(stdout_tty=True)
        self.assertIn("tier 0 (local)", out)
        self.assertIn("150.0 t/s", out)

    def test_json_and_errors(self):
        rc, out, _, _ = self.run_ask(as_json=True)
        self.assertEqual(json.loads(out)["jiezi"]["tier"], 0)
        rc, _, err, _ = self.run_ask(status=503)
        self.assertEqual(rc, 3)
        self.assertIn("engine unavailable", err)

    def test_unreachable_exit_2(self):
        def boom(request):
            raise httpx.ConnectError("refused")
        err = TTY()
        rc = anyio.run(ask.run_ask, "x", "jiezi", CONN, False, TTY(), TTY(), err,
                       httpx.AsyncClient(transport=httpx.MockTransport(boom)))
        self.assertEqual(rc, 2)
        self.assertIn("scripts/jiezi serve", err.getvalue())


class TestStatusLine(unittest.TestCase):
    def test_claude_and_cost(self):
        s = status_line({"tier": 3, "provider": "claude", "model": "claude-opus-5-5", "latency_s": 5.2,
                         "cloud": {"cost": 0.026}, "escalation": "self_reported_unsure"})
        self.assertIn("tier 3 (Claude)", s)
        self.assertIn("~US$0.0260", s)
        self.assertIn("self_reported_unsure", s)
        self.assertTrue(all(ord(ch) < 0x1F000 for ch in s))  # 沒有 emoji / no emoji
        self.assertEqual(status_line(None), "")


class TestHerdr(unittest.TestCase):
    def test_disabled_outside_herdr(self):
        calls = []
        h = HerdrReporter({}, popen=lambda *a, **k: calls.append(a))
        self.assertFalse(h.report("working"))
        self.assertEqual(calls, [])

    def test_reports_with_seq_and_resume(self):
        calls = []
        h = HerdrReporter({"HERDR_ENV": "1", "HERDR_PANE_ID": "p1"}, popen=lambda cmd, **k: calls.append(cmd),
                          which=lambda _: "/usr/bin/herdr")
        h.report("working", "answering")
        h.report("idle")
        self.assertEqual(calls[0][:3], ["/usr/bin/herdr", "pane", "report-agent"])
        self.assertIn("working", calls[0])
        self.assertEqual(calls[1][calls[1].index("--seq") + 1], "2")
        self.assertEqual(calls[1][-3:], ["--", "jiezi", "chat"])
        self.assertEqual(calls[1][calls[1].index("--") - 1], "p1")

    def test_failure_is_swallowed(self):
        def boom(*a, **k):
            raise OSError("no herdr")
        h = HerdrReporter({"HERDR_ENV": "1", "HERDR_PANE_ID": "p1"}, popen=boom, which=lambda _: "/x/herdr")
        self.assertFalse(h.report("idle"))
        self.assertEqual(h.last_error, "no herdr")


def fake_stream(chunks, meta=META, hang=False):
    async def gen(conn, messages, policy, client=None):
        for c in chunks:
            yield "delta", c
        if hang:
            await anyio.sleep(30)
        yield "meta", meta
    return gen


class TestChat(unittest.TestCase):
    def run_app(self, script, stream=None):
        calls = []
        reporter = HerdrReporter({"HERDR_ENV": "1", "HERDR_PANE_ID": "p"}, popen=lambda cmd, **k: calls.append(cmd),
                                 which=lambda _: "/usr/bin/herdr")
        app = chat.ChatApp(CONN, reporter=reporter)
        result = {}

        async def go():
            with mock.patch.object(chat, "stream_chat", stream or fake_stream(["台北", "是首都"])):
                async with app.run_test(size=(60, 20)) as pilot:
                    await script(app, pilot)
                    result["history"] = list(app.history)
                    result["bar"] = str(app.query_one("#bar").render())
        anyio.run(go)
        return app, result, calls

    def test_send_answer_status_and_herdr(self):
        async def script(app, pilot):
            await pilot.press(*"你好")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
        app, r, calls = self.run_app(script)
        self.assertEqual(r["history"], [{"role": "user", "content": "你好"},
                                        {"role": "assistant", "content": "台北是首都"}])
        self.assertIn("tier 0 (local)", app.last_status)
        states = [c[c.index("--state") + 1] for c in calls]
        self.assertEqual(states, ["idle", "working", "idle"])

    def test_newline_policy_and_stop(self):
        async def script(app, pilot):
            await pilot.press("a", "ctrl+j", "b")
            self.assertEqual(app.query_one("#prompt").text, "a\nb")
            await pilot.press("f2")
            self.assertEqual(app.policy, "jiezi-local")
            await pilot.press("enter")
            await pilot.pause(0.2)
            await pilot.press("ctrl+c")
            await app.workers.wait_for_complete()
            await pilot.pause()
        app, r, _ = self.run_app(script, stream=fake_stream(["部分"], hang=True))
        self.assertEqual(r["history"][-1], {"role": "assistant", "content": "部分"})  # 保留已收到的部分 / keep partial
        self.assertTrue(app.is_running is False)

    def test_save_and_cjk_width(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "chat.md"

            async def script(app, pilot):
                await pilot.press(*"問")
                await pilot.press("enter")
                await app.workers.wait_for_complete()
                for ch in f"/save {path}":
                    await pilot.press(ch if ch != " " else "space")
                await pilot.press("enter")
                await pilot.pause()
            _, r, _ = self.run_app(script)
            self.assertIn("台北是首都", path.read_text(encoding="utf-8"))
        self.assertLessEqual(cell_len(r["bar"].splitlines()[0]), 60 * 2)


if __name__ == "__main__":
    unittest.main()

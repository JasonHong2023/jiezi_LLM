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
        self.assertTrue(msg.startswith("【文件：管線輸入】\n報告內容") and msg.endswith("摘要"))  # 文件標記 / document markers
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


class TestSeedBanner(TestChat):
    """開場動畫取代操作說明（使用者 2026-11-18）；說明改在 /help。 / Opening animation; help moved to /help."""

    def test_animation_plays_once_and_help_moves(self):
        self.assertTrue(all(len(f) == len(chat.SEED_FRAMES[0]) for f in chat.SEED_FRAMES))   # 不跳動 / steady height
        self.assertIn("芥子納須彌", chat.SEED_FRAMES[-1][-1])

        async def script(app, pilot):
            banner = app.query_one("#seed")
            texts = {str(w.render()) for w in app.query("Static")}
            self.assertFalse(any("Type a question" in t for t in texts))   # 不再顯示操作說明 / no help lines
            with mock.patch.object(chat, "FRAME_S", 0.01):
                for _ in range(len(chat.SEED_FRAMES) + 2):
                    banner.advance()
            self.assertEqual(banner.frame, len(chat.SEED_FRAMES) - 1)
            self.assertIn("一粒芥子", str(banner.render()))
            await pilot.press(*"/help")
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(any("F3" in str(w.render()) for w in app.query("Static")))
        self.run_app(script)


class TestProgress(TestChat):
    """送出後顯示狀態（使用者 2026-11-18）。 / Live status after sending."""

    def test_phases(self):
        self.assertTrue(chat.first_phase("jiezi-ask-claude", False, False, False).startswith("請教 Claude"))
        self.assertTrue(chat.first_phase("jiezi-cloud", True, False, False).startswith("詢問雲端"))
        self.assertTrue(chat.first_phase("jiezi", True, False, False).startswith("閱讀文件"))
        self.assertTrue(chat.first_phase("jiezi", False, True, False).startswith("看圖"))
        self.assertTrue(chat.first_phase("jiezi", False, False, True).startswith("準備查看"))
        self.assertTrue(chat.first_phase("jiezi", False, False, False).startswith("思考中"))
        p = chat.phase_after("delta", "\n\n—— 本機答不出來，以下由 Claude 回答 ——\n\n", "回答中")
        self.assertTrue(p.startswith("請教 Claude"))
        self.assertEqual(chat.phase_after("delta", "答案", p), p)                # 等轉交的回答 / still escalating
        self.assertTrue(chat.phase_after("delta", "台北", "思考中").startswith("回答中"))
        self.assertTrue(chat.phase_after("thinking", "嗯", "閱讀文件中").startswith("思考中"))
        self.assertIn("查看檔案中", chat.phase_after("agent", {"type": "call", "tool": "list_dir"}, "x"))
        self.assertTrue(chat.phase_after("progress", "loading_model", "思考中").startswith("載入模型中"))
        self.assertEqual(chat.phase_after("progress", "unknown_stage", "思考中"), "思考中")
        self.assertEqual(set(chat.STAGE_TEXT), set(__import__("jiezi.runtime.gateway", fromlist=["STAGES"]).STAGES))

    def test_status_shows_while_waiting_then_final_line(self):
        gate = anyio.Event()

        async def slow(conn, messages, policy, client=None):
            await gate.wait()
            yield "delta", "台北"
            yield "meta", META

        async def script(app, pilot):
            await pilot.press(*"你好")
            await pilot.press("enter")
            await pilot.pause(0.3)
            metas = [str(w.render()) for w in app.query(".meta")]
            self.assertTrue(any("思考中" in m and "秒" in m for m in metas), metas)
            gate.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            metas = [str(w.render()) for w in app.query(".meta")]
            self.assertFalse(any("思考中" in m for m in metas))
            self.assertTrue(any("tier 0" in m for m in metas))
        self.run_app(script, slow)


class TestClipboard(unittest.TestCase):
    def test_picks_detected_tool_and_utf16_for_clip_exe(self):
        from jiezi.cli import clipboard
        calls = []

        class P:
            returncode = 0
        tool = clipboard.system_copy("中文", which=lambda n: "/x" if n == "clip.exe" else None,
                                     run=lambda cmd, input=None, **k: calls.append((cmd, input)) or P())
        self.assertEqual(tool, "clip.exe")
        self.assertEqual(calls[0][1], b"\xff\xfe" + "中文".encode("utf-16-le"))  # 要有 BOM（沒有會被猜成 ANSI）/ BOM
        calls.clear()
        tool = clipboard.system_copy("抱歉，剛才的回答", which=lambda n: "/x" if n in ("clip.exe", "powershell.exe") else None,
                                     run=lambda cmd, input=None, **k: calls.append((cmd, input)) or P())
        self.assertEqual(tool, "powershell.exe")                    # PowerShell 優先 / PowerShell first
        self.assertEqual(calls[0][1], "抱歉，剛才的回答".encode("utf-8"))
        self.assertIn("Set-Clipboard", calls[0][0][-1])
        self.assertIsNone(clipboard.system_copy("x", which=lambda n: None))

    def test_failure_tries_next(self):
        from jiezi.cli import clipboard

        def run(cmd, **k):
            if cmd[0] == "wl-copy":
                raise OSError("no display")

            class P:
                returncode = 0
            return P()
        self.assertEqual(clipboard.system_copy("x", which=lambda n: "/x" if n in ("wl-copy", "xclip") else None,
                                               run=run), "xclip")


class TestChatCopy(TestChat):
    def test_f3_and_copy_command(self):
        copied = []

        async def script(app, pilot):
            await pilot.press(*"問")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.press("f3")
            await pilot.pause()
            await pilot.press(*"/copy")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("ctrl+c")  # 沒有選取也沒有回答進行中：不出錯 / no selection, nothing running
            await pilot.pause()
        with mock.patch.object(chat, "system_copy", lambda text: copied.append(text) or "clip.exe"):
            app, r, _ = self.run_app(script)
        self.assertEqual(copied, ["台北是首都", "台北是首都"])
        self.assertEqual(app.copied, "台北是首都")
        self.assertIn("clip.exe", r["bar"])

    def test_selection_is_copied_on_release(self):
        from textual import events as tev
        copied = []

        async def script(app, pilot):
            await pilot.press(*"問")
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            with mock.patch.object(type(app.screen), "get_selected_text", lambda self: "台北"):
                app.screen.post_message(tev.TextSelected())
                await pilot.pause()
        with mock.patch.object(chat, "system_copy", lambda text: copied.append(text) or "clip.exe"):
            app, r, _ = self.run_app(script)
        self.assertEqual(copied, ["台北"])
        self.assertIn("已複製", r["bar"])

    def test_system_copy_skips_osc52(self):
        """系統剪貼簿成功就不送 OSC 52（多工器轉送的 OSC 52 會蓋掉、弄亂中文）；沒有工具才送。
        No OSC 52 when the system clipboard worked; OSC 52 only as the fallback."""
        sent = []

        async def script(app, pilot):
            with mock.patch.object(app, "copy_to_clipboard", lambda t: sent.append(t)):
                with mock.patch.object(chat, "system_copy", lambda t: "clip.exe"):
                    app.copy_text("中文")
                with mock.patch.object(chat, "system_copy", lambda t: None):
                    app.copy_text("後備")
        self.run_app(script)
        self.assertEqual(sent, ["後備"])

    def test_up_down_recall_inputs(self):
        """↑／↓ 切換輸入過的句子，草稿保留（使用者 2026-11-18）。 / Up/Down walk inputs; the draft is kept."""
        seen = []

        async def script(app, pilot):
            for q in ("第一題", "/help", "第二題"):
                await pilot.press(*q)
                await pilot.press("enter")
                await app.workers.wait_for_complete()
            prompt = app.query_one("#prompt")
            await pilot.press(*"草稿")
            for key in ("up", "up", "up", "up", "down", "down", "down"):
                await pilot.press(key)
                seen.append(prompt.text)
        self.run_app(script)
        self.assertEqual(seen, ["第二題", "/help", "第一題", "第一題", "/help", "第二題", "草稿"])

    def test_inputs_persist(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "history.json"
            app = chat.ChatApp(CONN, history_path=path)
            app._save_inputs(["甲", "/clear", "乙"])
            again = chat.ChatApp(CONN, history_path=path)
            self.assertEqual(again._load_inputs(), ["甲", "/clear", "乙"])
            path.write_text('[{"role": "user", "content": "舊問題"}]', encoding="utf-8")
            (Path(d) / "inputs.json").unlink()
            self.assertEqual(chat.ChatApp(CONN, history_path=path)._load_inputs(), ["舊問題"])


class TestService(unittest.TestCase):
    def test_already_running_and_remote_url_untouched(self):
        from jiezi.cli.client import ensure_gateway
        from jiezi.runtime import service
        with mock.patch.object(service, "health", return_value={"status": "ok"}):
            self.assertEqual(service.start(Path("/x"), 36100), "already_running")
            self.assertIsNone(ensure_gateway(Connection("http://127.0.0.1:36100", "k")))
        self.assertIsNone(ensure_gateway(Connection("http://example.invalid:36100", "k")))

    def test_starts_detached_process_without_systemd(self):
        from jiezi.runtime import service
        calls = []
        states = iter([None, None, {"status": "ok"}])
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(service, "health", side_effect=lambda *a, **k: next(states)), \
                mock.patch.object(service, "_user_systemd", return_value=False), \
                mock.patch.object(service.subprocess, "Popen", lambda cmd, **k: calls.append((cmd, k))), \
                mock.patch.object(service.time, "sleep", lambda s: None):
            res = service.start(Path(d), 36100)
        self.assertEqual(res, "started_process")
        self.assertEqual(calls[0][0][-1], "serve")
        self.assertTrue(calls[0][1]["start_new_session"])  # 與終端機脫鉤 / detached from the terminal


if __name__ == "__main__":
    unittest.main()

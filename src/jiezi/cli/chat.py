"""`jiezi chat`：Textual 全螢幕對話（規格 cli：Interactive Chat；add-cli design D4）。
`jiezi chat`: Textual full-screen chat (spec cli: Interactive Chat; design D4).

按鍵 / Keys：Enter 送出 / send；Shift+Enter 或 Ctrl+J 換行 / newline；↑／↓ 切換輸入過的句子 / earlier inputs；
滑鼠拖曳選取，放開即自動複製（使用者 2026-11-15：跟 Claude Code 一樣）/ select by dragging, copied on release
(user request: behave like Claude Code)；Ctrl+C 中斷生成 / stop generation；F3 複製最後一則回答 / copy the last
answer；F2 切換策略 / switch policy；Ctrl+Q 離開 / quit。
指令 / Commands：`/save 路徑`、`/copy`、`/clear`、`/file 路徑`（附文件，之後每一題都帶著，可以一直追問；`/file clear`
取消）/ attach a document that stays with every following question (`/file clear` detaches)、`/image 路徑`、
`/agent on|off`（唯讀檔案代理：讀你授權的資料夾 / read-only file agent over granted folders）。"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

import anyio
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Footer, Markdown, Static, TextArea
from textual.worker import Worker

from .client import (Connection, GatewayError, GatewayUnreachable, agent_step_text, ensure_gateway, status_line,
                     stream_chat)
from .clipboard import system_copy
from .herdr import HerdrReporter

# F2 切換不含 jiezi-ask-claude（使用者 2026-11-18：拿掉）；`jiezi chat --claude` 仍可用
# F2 no longer cycles to jiezi-ask-claude (user request); `--claude` still works
POLICIES = ("jiezi", "jiezi-local", "jiezi-cloud")
# 聊天歷史（使用者 2026-11-15：重開時接續上次的對話）/ chat history, resumed on restart
MAX_SAVED, MAX_SHOWN, MAX_CONTEXT = 200, 20, 12
MAX_INPUTS = 500   # ↑／↓ 可切換的輸入紀錄 / input history for Up / Down
MAX_DOC_CHARS = 1_500_000  # 附加文件的總字數上限（每題都會送到本機 gateway）/ total attached characters
IMAGE_TYPES, MAX_IMAGE_BYTES = {"image/png", "image/jpeg", "image/webp", "image/gif"}, 5 << 20  # add-vision


def text_of(content) -> str:
    """訊息的文字；圖片換成「[圖片]」。 / The text of a message; images become 「[圖片]」."""
    if isinstance(content, list):
        return " ".join(p.get("text", "") if p.get("type") == "text" else "[圖片 image]"
                        for p in content if isinstance(p, dict)).strip()
    return content or ""


def for_context(history: list[dict]) -> list[dict]:
    """送給 gateway 的上下文：只有最後一則保留圖片，其他只留文字。 / Only the last message keeps its image."""
    out = [{**m, "content": text_of(m["content"])} for m in history[:-1]]
    return out + history[-1:]  # 引擎上下文 4096，只送最近 12 則 / engine ctx is 4096


def with_documents(messages: list[dict], docs: list[dict]) -> list[dict]:
    """把目前附著的文件包進最後一個問題（不改原本的訊息）。歷史只存問題本身，文件每一題重新附上，gateway 才能依
    這一題重新挑段落（add-document-followup）。
    Wrap the attached documents around the last question without touching the stored message. History keeps the
    bare question; documents ride along with each new question so the gateway can re-select chunks for it."""
    if not docs or not messages or messages[-1].get("role") != "user":
        return messages
    from ..documents import attach

    def wrap(text: str) -> str:
        for d in reversed(docs):
            text = attach(d, text)
        return text
    last = messages[-1]
    if isinstance(last.get("content"), list):
        content = [{**p, "text": wrap(p.get("text", ""))} if isinstance(p, dict) and p.get("type") == "text" else p
                   for p in last["content"]]
    else:
        content = wrap(last.get("content") or "")
    return [*messages[:-1], {**last, "content": content}]


class PromptArea(TextArea):
    """Enter 送出，Shift+Enter / Ctrl+J 換行；↑／↓ 在第一行／最後一行時切換輸入過的句子（使用者 2026-11-18：
    跟 Claude Code 一樣），正在打的字會先保留，↓ 回到底時還原。
    Enter sends; Shift+Enter / Ctrl+J insert a newline; Up / Down on the first / last line walk through earlier
    inputs (like Claude Code); the unsent draft is kept and restored at the bottom."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def __init__(self, *args, inputs: list[str] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.inputs: list[str] = inputs if inputs is not None else []
        self.pos: int | None = None     # 正在看第幾筆；None = 正在打的新句子 / index browsed; None = the draft
        self.draft = ""

    def _recall(self, pos: int | None) -> None:
        self.pos = pos
        self.text = self.draft if pos is None else self.inputs[pos]
        self.move_cursor(self.document.end)

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                if not self.inputs or self.inputs[-1] != text:
                    self.inputs.append(text)
                self.pos, self.draft = None, ""
                self.post_message(self.Submitted(text))
                self.clear()
            return
        if event.key == "up" and self.inputs and self.cursor_location[0] == 0 and self.pos != 0:
            event.prevent_default()
            event.stop()
            if self.pos is None:
                self.draft = self.text
            self._recall(len(self.inputs) - 1 if self.pos is None else self.pos - 1)
            return
        if (event.key == "down" and self.pos is not None
                and self.cursor_location[0] == self.document.line_count - 1):
            event.prevent_default()
            event.stop()
            self._recall(None if self.pos == len(self.inputs) - 1 else self.pos + 1)
            return
        if event.key in ("shift+enter", "ctrl+j"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)

    async def _on_mouse_up(self, event: events.MouseUp) -> None:
        await super()._on_mouse_up(event)
        if self.selected_text:  # 輸入框裡的選取也是放開就複製 / the prompt's selection is copied on release too
            self.app.copy_text(self.selected_text)


# 開場動畫：一粒芥子展開成山海星月，再收回成一粒——「芥子納須彌」（使用者 2026-11-18：取代開頭的操作說明，
# 操作說明留在下方的按鍵列與 /help）。每格行數相同，畫面才不會跳動。
# Opening animation: a mustard seed unfolds into a world and holds it ("a mustard seed contains Mount Sumeru");
# replaces the help lines at the top (user request); key help stays in the footer and /help.
SEED_FRAMES: list[list[str]] = [
    ["", "", "·", "", ""],
    ["", "", "( · )", "", ""],
    ["", "˙   ˙   ˙", "(  ●  )", "˙   ˙   ˙", ""],
    ["          ✦", "      ▲", "    ▲▲▲", "～～( ● )～～", ""],
    ["   ✧          ✦", "      ▲    ▲▲", "    ▲▲▲▲  ▲▲▲▲", "～～～～( ● )～～～～", ""],
    ["✦      ✧    ☾     ✦", "    ▲     ▲▲▲", "  ▲▲▲▲  ▲▲▲▲▲▲  ▲▲", "～～～～～～( ● )～～～～～～", ""],
]
_WORLD = SEED_FRAMES[-1][:4]
TITLE = "芥子納須彌"
SUBTITLE = "芥子納須彌 —— 一粒芥子，裝下一整個世界"
SEED_FRAMES += [[*_WORLD, TITLE[:n]] for n in range(1, len(TITLE) + 1)] + [[*_WORLD, SUBTITLE]]
FRAME_S = 0.2
# 送出後的狀態（使用者 2026-11-18）：gateway 在第一個字之前不會送任何東西，所以先依這一題的條件猜階段，
# 等太久就改說「處理中」；收到思考片段、轉交的分隔線、代理步驟或第一個字時再換。
# Status after sending: the gateway sends nothing before the first token, so the first phase is inferred from the
# question, switched to "processing" when it takes long, then updated by reasoning, escalation, agent steps or text.
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
SLOW_S = 8.0
TICK_S = 0.1


def first_phase(policy: str, docs: bool, image: bool, agent: bool) -> str:
    if policy == "jiezi-ask-claude":
        return "請教 Claude 中 / asking Claude"
    if policy == "jiezi-cloud":
        return "詢問雲端模型中 / asking the cloud model"
    if agent:
        return "準備查看你的檔案 / preparing to read your files"
    if image:
        return "看圖中 / looking at the image"
    if docs:
        return "閱讀文件中 / reading the documents"
    return "思考中 / thinking"


STAGE_TEXT = {      # gateway 回報的階段（add-progress-events）/ stages reported by the gateway
    "loading_model": "載入模型中 / loading the model",
    "reading_documents": "閱讀文件中 / reading the documents",
    "looking": "辨識圖中物體 / looking at the image",
    "thinking": "思考中 / thinking",
    "retrying": "本機重新作答 / answering again locally",
    "thinking_hard": "本機深入思考中 / thinking harder locally",
    "asking_claude": "請教 Claude 中 / asking Claude",
    "asking_cloud": "詢問雲端模型中 / asking the cloud model",
    "asking_feedback": "向雲端要提示後重答 / getting hints to retry",
}


def phase_after(kind: str, value, current: str) -> str:
    """依串流事件換階段。 / The next phase for a stream event."""
    if kind == "progress":
        return STAGE_TEXT.get(value, current)
    if kind == "thinking":
        return "思考中 / thinking"
    if kind == "agent":
        return f"查看檔案中 / reading files：{agent_step_text(value)}"
    if kind == "delta":
        if "本機答不出來" in value:
            return "請教 Claude 中 / asking Claude" if "Claude" in value else "詢問雲端模型中 / asking the cloud model"
        if current.startswith(("請教", "詢問")):
            return current      # 轉交中的分隔線之後、真正的回答之前 / still waiting for the escalated answer
        return "回答中 / answering"
    return current


HELP = ("輸入問題後按 Enter，↑／↓ 叫回輸入過的句子；拖曳選取即複製，F3 複製最後一則回答；Ctrl+C 中斷，F2 換策略，Ctrl+Q 離開。\n"
        "指令：/file 路徑（附文件，/file clear 取消）、/image 路徑、/agent on|off、/copy、/save 檔名、/clear、/help\n"
        "Enter to send, Up/Down recall earlier inputs; drag to copy, F3 copies the last answer; Ctrl+C stops, F2 policy, Ctrl+Q quits.")


class SeedBanner(Static):
    """播一次就停在最後一格。 / Plays once and rests on the last frame."""
    DEFAULT_CSS = "SeedBanner { width: 100%; text-align: center; color: $text-muted; margin: 1 0; }"

    def __init__(self, **kw):
        super().__init__("\n".join(SEED_FRAMES[0]), markup=False, **kw)
        self.frame = 0

    def on_mount(self) -> None:
        self.timer = self.set_interval(FRAME_S, self.advance)

    def advance(self) -> None:
        if self.frame >= len(SEED_FRAMES) - 1:      # 停在最後一格 / rest on the last frame
            self.timer.stop()
            return
        self.frame += 1
        self.update("\n".join(SEED_FRAMES[self.frame]))


class ChatApp(App):
    TITLE = "芥子 Jiezi"
    CSS = """
    #log { height: 1fr; padding: 0 1; }
    .user { color: $text-accent; margin-top: 1; }
    .answer { margin: 0; }
    .meta { color: $text-muted; }
    #prompt { height: 5; }
    #bar { height: 1; color: $text-muted; padding: 0 1; }
    """
    BINDINGS = [
        Binding("ctrl+c", "copy_or_stop", "中斷 Stop", priority=True),
        Binding("f3", "copy_last", "複製回答 Copy answer"),
        Binding("f2", "cycle_policy", "策略 Policy"),
        Binding("ctrl+q", "quit", "離開 Quit", priority=True),
    ]

    def __init__(self, conn: Connection, policy: str = "jiezi", reporter: HerdrReporter | None = None,
                 history_path: Path | None = None):
        super().__init__()
        self.conn, self.policy = conn, policy
        self.reporter = reporter or HerdrReporter()
        self.history_path = history_path
        self.history: list[dict] = self._load_history()
        self.cost = 0.0
        self.worker: Worker | None = None
        self.last_status = ""
        self.copied: str | None = None
        self.pending_image: tuple[str, str] | None = None  # (檔名, data URL) / (name, data URL)
        self.docs: list[dict] = []                         # /file 附著的文件，每一題都帶 / attached, sent with every question
        self.agent = False                                 # /agent on：唯讀檔案代理（add-agent-readonly）/ read-only agent

    def compose(self) -> ComposeResult:
        yield VerticalScroll(SeedBanner(id="seed"), id="log")
        yield PromptArea(id="prompt", soft_wrap=True, show_line_numbers=False, inputs=self._load_inputs())
        yield Static(id="bar")
        yield Footer()

    def _load_history(self) -> list[dict]:
        if not self.history_path or not self.history_path.exists():
            return []
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            return [m for m in data if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
        except (OSError, ValueError, AttributeError):
            return []

    @property
    def inputs_path(self) -> Path | None:
        return self.history_path.with_name("inputs.json") if self.history_path else None

    def _load_inputs(self) -> list[str]:
        """輸入過的句子（含指令），/clear 不清；沒有紀錄時用對話歷史裡的問題。
        Earlier inputs (commands included), kept across /clear; falls back to the questions in the history."""
        try:
            data = json.loads(self.inputs_path.read_text(encoding="utf-8"))
            return [x for x in data if isinstance(x, str)][-MAX_INPUTS:]
        except (OSError, ValueError, AttributeError, TypeError):
            return [text_of(m["content"]) for m in self.history if m["role"] == "user"][-MAX_INPUTS:]

    def _save_inputs(self, inputs: list[str]) -> None:
        if not self.inputs_path:
            return
        try:
            self.inputs_path.parent.mkdir(parents=True, exist_ok=True)
            self.inputs_path.write_text(json.dumps(inputs[-MAX_INPUTS:], ensure_ascii=False, indent=0),
                                        encoding="utf-8")
        except OSError:
            pass

    def _save_history(self) -> None:
        if not self.history_path:
            return
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.history_path.with_suffix(".tmp")
            saved = [{**m, "content": text_of(m["content"])} for m in self.history[-MAX_SAVED:]]  # 不存圖片 / no images
            tmp.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.history_path)
        except OSError:
            pass

    async def _show_history(self) -> None:
        if not self.history:
            return
        log = self.query_one("#log", VerticalScroll)
        shown = self.history[-MAX_SHOWN:]
        await log.mount(Static(f"—— 接續上次的對話（共 {len(self.history)} 則，顯示最近 {len(shown)} 則；/clear 清除，"
                               f"或用 --new 開新對話）/ resumed ——", classes="meta", markup=False))
        for m in shown:
            if m["role"] == "user":
                await log.mount(Static(f"> {text_of(m['content'])}", classes="user", markup=False))
            else:
                await log.mount(Markdown(m["content"], classes="answer"))
        log.scroll_end(animate=False)

    async def on_mount(self) -> None:
        await self._show_history()
        self.query_one("#prompt", PromptArea).focus()
        self._update_bar()
        self.reporter.report("idle")

    def _update_bar(self, note: str = "") -> None:
        text = f"策略 policy: {self.policy} | {self.conn.url} | 雲端費用 cloud cost ~US${self.cost:.4f}"
        if self.docs:
            text += f" | 文件 docs: {'、'.join(d['name'] for d in self.docs)}（/file clear 取消）"
        self.query_one("#bar", Static).update(text + (f" | {note}" if note else ""))

    # ── 動作 / Actions ──
    def action_cycle_policy(self) -> None:
        self.policy = POLICIES[(POLICIES.index(self.policy) + 1) % len(POLICIES)] if self.policy in POLICIES \
            else POLICIES[0]
        self._update_bar()

    def action_stop(self) -> None:
        if self.worker and self.worker.is_running:
            self.worker.cancel()

    def action_copy_or_stop(self) -> None:
        """有選取文字就複製；否則中斷正在進行的回答。 / Copy the selection if any; otherwise stop the answer."""
        selected = self.screen.get_selected_text()
        if selected:
            self.copy_text(selected)
        elif self.worker and self.worker.is_running:
            self.worker.cancel()
        else:
            focused = self.focused
            if isinstance(focused, TextArea) and focused.selected_text:
                self.copy_text(focused.selected_text)

    def on_text_selected(self, event: events.TextSelected) -> None:
        """放開滑鼠、選取完成就自動複製。 / Copy automatically when a selection ends (mouse released)."""
        text = self.screen.get_selected_text()
        if text:
            self.copy_text(text)

    def action_copy_last(self) -> None:
        last = next((m["content"] for m in reversed(self.history) if m["role"] == "assistant"), None)
        if last:
            self.copy_text(last)
        else:
            self._update_bar("還沒有回答可以複製 / no answer to copy yet")

    def copy_text(self, text: str) -> None:
        """先寫系統剪貼簿；沒有系統工具才送 OSC 52。兩個都送時，多工器（Herdr 等）轉送的 OSC 52 會晚一步
        蓋掉正確的內容，中文變亂碼（使用者 2026-11-18 回報）。
        System clipboard first; OSC 52 only when no system tool exists. Sending both let a multiplexer's re-encoded
        OSC 52 overwrite the correct text a moment later, garbling CJK (user report, 2026-11-18)."""
        tool = system_copy(text)
        if tool:
            self._clipboard = text      # 給 TextArea 的 Ctrl+V / for the TextArea's own paste
        else:
            self.copy_to_clipboard(text)
        self.copied = text
        self._update_bar(f"已複製 copied {len(text)} 字 chars" + (f" ({tool})" if tool else " (OSC 52)"))

    async def on_prompt_area_submitted(self, message: PromptArea.Submitted) -> None:
        text = message.text
        self._save_inputs(self.query_one("#prompt", PromptArea).inputs)
        if text in ("/help", "/?"):
            log = self.query_one("#log", VerticalScroll)
            await log.mount(Static(HELP, classes="meta", markup=False))
            log.scroll_end(animate=False)
            return
        if text.startswith("/save"):
            self._save(text[5:].strip())
            return
        if text == "/copy":
            self.action_copy_last()
            return
        if text.startswith("/image"):
            self._attach_image(text[6:].strip())
            return
        if text.startswith("/agent"):
            arg = text[6:].strip().lower()
            if arg in ("on", "off"):
                self.agent = arg == "on"
            self._update_bar("唯讀代理 agent: " + ("開 on——可以請芥子列出、尋找、讀取你授權的資料夾裡的檔案"
                                                  "（scripts/jiezi agent grant 資料夾）" if self.agent else "關 off")
                             + "；用法 usage: /agent on|off")
            return
        if text.startswith("/file"):
            await self._attach_file(text[5:].strip())
            return
        if text == "/clear":
            self.history.clear()
            self.docs = []
            if self.history_path:
                self.history_path.unlink(missing_ok=True)
            await self.query_one("#log", VerticalScroll).remove_children()
            return
        if self.worker and self.worker.is_running:
            self._update_bar("上一題還在回答 / still answering")
            return
        if not text.startswith("/"):
            text = await self._auto_attach(text)
        log = self.query_one("#log", VerticalScroll)
        content = text
        if self.docs:  # 文件在送出時才附上（_answer），歷史只存問題 / attached when sending; history keeps the question
            text = f"{text}  [文件 documents: {'、'.join(d['name'] for d in self.docs)}]"
        if self.pending_image:  # 這一題附圖 / this question carries the image
            name, url = self.pending_image
            content = [{"type": "text", "text": content}, {"type": "image_url", "image_url": {"url": url}}]
            text = f"{text}  [圖片 image: {name}]"
            self.pending_image = None
        await log.mount(Static(f"> {text}", classes="user", markup=False))
        answer = Markdown(classes="answer")
        meta = Static("", classes="meta", markup=False)
        await log.mount(answer, meta)
        log.scroll_end(animate=False)
        self.history.append({"role": "user", "content": content})
        phase = first_phase(self.policy, bool(self.docs), not isinstance(content, str), self.agent)
        self.worker = self.run_worker(self._answer(answer, meta, log, phase), exclusive=True)

    async def _answer(self, answer: Markdown, meta_w: Static, log: VerticalScroll,
                      phase: str = "思考中 / thinking") -> None:
        import time
        self.reporter.report("working")
        parts: list[str] = []
        meta = None
        stream = Markdown.get_stream(answer)
        state = {"phase": phase, "t0": time.monotonic(), "events": 0}

        def tick() -> None:
            el = time.monotonic() - state["t0"]
            label = state["phase"]
            if not state["events"] and el > SLOW_S and label.startswith(("思考", "閱讀", "看圖")):
                # 沒收到 gateway 的階段（舊版或關閉 JIEZI_PROGRESS）時才猜 / guess only without reported stages
                label = "處理中（準備模型或整理資料，第一次會久一點）/ processing"
            meta_w.update(f"{SPINNER[int(el / TICK_S) % len(SPINNER)]} {label}… {el:.0f} 秒")
        tick()
        timer = self.set_interval(TICK_S, tick)
        try:
            outgoing = with_documents(for_context(self.history[-MAX_CONTEXT:]), self.docs)
            extra = {"extra": {"jiezi_agent": True}} if self.agent else {}  # /agent on 才帶 / only with /agent on
            async for kind, value in stream_chat(self.conn, outgoing, self.policy, **extra):
                if kind != "meta":
                    state["events"] += 1
                    state["phase"] = phase_after(kind, value, state["phase"])
                if kind == "delta":
                    parts.append(value)
                    await stream.write(value)
                    log.scroll_end(animate=False)
                elif kind == "meta":
                    meta = value
            timer.stop()
            self.last_status = status_line(meta)
            meta_w.update(self.last_status)
            self.cost += ((meta or {}).get("cloud") or {}).get("cost") or 0.0
        except GatewayUnreachable:
            timer.stop()
            # 聊天途中 gateway 被關掉：在背景重新啟動，請使用者再送一次 / restart it and ask to resend
            res = await anyio.to_thread.run_sync(ensure_gateway, self.conn)
            meta_w.update(f"[gateway 剛才沒有在執行，已在背景重新啟動（{res}），請再送一次 / the gateway was not "
                          f"running; restarted in the background ({res}), please send again]")
        except GatewayError as exc:
            timer.stop()
            meta_w.update(f"[錯誤 / error: {exc}]")
        except BaseException:
            timer.stop()
            meta_w.update("[已中斷 / stopped]")
            raise
        finally:
            timer.stop()
            await stream.stop()
            if parts:
                self.history.append({"role": "assistant", "content": "".join(parts)})
            elif self.history and self.history[-1]["role"] == "user":
                self.history.pop()  # 沒有答案就不留問題，避免下一題連續兩個 user / no answer: drop the question
            self._save_history()
            self._update_bar()
            self.reporter.report("idle")

    async def _attach_file(self, path: str) -> None:
        """`/file 路徑`：附上文件（PDF、.docx、.html、純文字），之後每一題都帶著，直到 `/file clear`。
        Attach a document; it stays with every following question until `/file clear`."""
        from ..documents import DocumentError, read
        if path in ("clear", "off", "none"):
            n, self.docs = len(self.docs), []
            self._update_bar(f"已取消 {n} 份文件 / detached {n} document(s)")
            return
        if not path:
            self._update_bar("用法 usage: /file 文件路徑（PDF、.docx、.pptx、.xlsx、.html、.txt、.md）；/file clear 取消附加的文件")
            return
        self._update_bar(f"讀取中 reading: {Path(path).name}……")
        try:
            from ..localpaths import to_local
            d = await anyio.to_thread.run_sync(read, str(to_local(path)))
        except DocumentError as exc:
            self._update_bar(f"無法讀取 cannot read: {exc}")
            return
        if not d["text"].strip():
            self._update_bar("讀不到文字（可能是掃描檔且 OCR 失敗）/ no text found")
            return
        if sum(len(x["text"]) for x in self.docs) + len(d["text"]) > MAX_DOC_CHARS:
            self._update_bar(f"附加的文件合計超過 {MAX_DOC_CHARS} 字，請先 /file clear / attached documents too large")
            return
        self.docs = [x for x in self.docs if x["name"] != d["name"]] + [d]  # 同名視為更新 / same name replaces
        from .client import warm_document  # 先建段落向量，第一題就用得到語意挑段落 / warm chunk vectors
        self.run_worker(warm_document(self.conn, d["text"]), group="warm", exclusive=False)
        extra = f"，OCR {len(d['ocr_pages'])} 頁" if d.get("ocr_pages") else ""
        self._update_bar(f"已附文件 attached: {d['name']}（{d['chars']} 字{extra}）；可以一直追問，/file clear 取消 / "
                         "stays attached for follow-up questions")

    async def _auto_attach(self, text: str) -> str:
        """問題裡直接打的檔案路徑（Windows 的 D:\\… 也可以）：圖片附在這一題、文件照 /file 附著，問題裡的路徑換成
        「這張圖」「這份文件」（使用者 2026-11-18）。找不到的檔案照原樣送出，gateway 會提醒模型別猜。
        File paths typed in a question (Windows paths too): images go with this question, documents attach like /file."""
        from ..localpaths import find_paths, is_image, strip_paths, to_local
        done, missing = [], []
        for raw in find_paths(text):
            local = to_local(raw)
            if not local.is_file():
                missing.append(f"{raw}（{local}）" if str(local) != raw else raw)
                continue
            if is_image(raw):
                self._attach_image(str(local))
                if self.pending_image:
                    done.append(raw)
            else:
                before = len(self.docs)
                await self._attach_file(str(local))
                if any(d["name"] == local.name for d in self.docs) and len(self.docs) >= before:
                    done.append(raw)
        if missing:
            self._update_bar(f"找不到檔案 not found: {'、'.join(missing)}")
        return strip_paths(text, done) if done else text

    def _attach_image(self, path: str) -> None:
        """`/image 路徑`：下一個問題附上這張圖（add-vision）。 / Attach an image to the next question."""
        from ..localpaths import to_local
        p = to_local(path) if path else Path(path)
        kind = mimetypes.guess_type(p.name)[0]
        if not path or not p.is_file():
            self._update_bar("用法 usage: /image 圖片路徑（png、jpg、webp、gif）")
        elif kind not in IMAGE_TYPES:
            self._update_bar(f"不支援的格式 unsupported: {kind or p.suffix}")
        elif p.stat().st_size > MAX_IMAGE_BYTES:
            self._update_bar("圖片超過 5 MB / image larger than 5 MB")
        else:
            self.pending_image = (p.name, f"data:{kind};base64,{base64.b64encode(p.read_bytes()).decode()}")
            self._update_bar(f"已附圖 attached: {p.name}；輸入問題後按 Enter / type your question")

    def _save(self, path: str) -> None:
        if not path:
            self._update_bar("用法 usage: /save 檔案.md")
            return
        lines = []
        for m in self.history:
            lines.append(("## 你 / You\n\n" if m["role"] == "user" else "## 芥子 / Jiezi\n\n") + text_of(m["content"]) + "\n")
        p = Path(path).expanduser()
        p.write_text("\n".join(lines), encoding="utf-8")
        self._update_bar(f"已儲存 saved: {p}")


def main(policy: str = "jiezi", new: bool = False) -> int:
    import sys

    from ..config import project_root
    conn = Connection.from_env()
    if not conn.key:
        sys.stderr.write("jiezi: JIEZI_GATEWAY_KEY is not set; run scripts/jiezi init-key\n")
        return 3
    res = ensure_gateway(conn, log=lambda m: sys.stderr.write(m + "\n"))
    if res == "failed":
        sys.stderr.write("jiezi: gateway 啟動失敗，請看 scripts/jiezi logs / the gateway failed to start; "
                         "see scripts/jiezi logs\n")
    path = project_root() / "var" / "chat" / "history.json"
    if new:
        path.unlink(missing_ok=True)
    ChatApp(conn, policy, history_path=path).run()
    return 0

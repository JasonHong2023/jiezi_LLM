"""`jiezi chat`：Textual 全螢幕對話（規格 cli：Interactive Chat；add-cli design D4）。
`jiezi chat`: Textual full-screen chat (spec cli: Interactive Chat; design D4).

按鍵 / Keys：Enter 送出 / send；Shift+Enter 或 Ctrl+J 換行 / newline；
Ctrl+C 有選取文字時複製，否則中斷生成 / copy the selection, else stop generation；F3 複製最後一則回答 / copy the
last answer；F2 切換策略 / switch policy；Ctrl+Q 離開 / quit。
指令 / Commands：`/save 路徑`、`/copy`、`/clear`。
選取 / Selecting：用滑鼠在對話區拖曳選取；多數終端機按住 Shift 拖曳可改用終端機自己的選取。
Drag with the mouse in the conversation; in most terminals Shift+drag uses the terminal's own selection."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Footer, Markdown, Static, TextArea
from textual.worker import Worker

from .client import Connection, GatewayError, GatewayUnreachable, status_line, stream_chat
from .clipboard import system_copy
from .herdr import HerdrReporter

POLICIES = ("jiezi", "jiezi-local", "jiezi-ask-claude", "jiezi-cloud")


class PromptArea(TextArea):
    """Enter 送出，Shift+Enter / Ctrl+J 換行。 / Enter sends; Shift+Enter / Ctrl+J insert a newline."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                self.post_message(self.Submitted(text))
                self.clear()
            return
        if event.key in ("shift+enter", "ctrl+j"):
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        await super()._on_key(event)


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
        Binding("ctrl+c", "copy_or_stop", "複製/中斷 Copy/Stop", priority=True),
        Binding("f3", "copy_last", "複製回答 Copy answer"),
        Binding("f2", "cycle_policy", "策略 Policy"),
        Binding("ctrl+q", "quit", "離開 Quit", priority=True),
    ]

    def __init__(self, conn: Connection, policy: str = "jiezi", reporter: HerdrReporter | None = None):
        super().__init__()
        self.conn, self.policy = conn, policy
        self.reporter = reporter or HerdrReporter()
        self.history: list[dict] = []
        self.cost = 0.0
        self.worker: Worker | None = None
        self.last_status = ""
        self.copied: str | None = None

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Static("輸入問題後按 Enter / Type a question and press Enter. "
                                    "拖曳選取後 Ctrl+C 複製，F3 複製最後一則回答 / drag to select, Ctrl+C copies, "
                                    "F3 copies the last answer. F2 切換策略 / policy; Ctrl+Q 離開 / quit.",
                                    classes="meta"), id="log")
        yield PromptArea(id="prompt", soft_wrap=True, show_line_numbers=False)
        yield Static(id="bar")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#prompt", PromptArea).focus()
        self._update_bar()
        self.reporter.report("idle")

    def _update_bar(self, note: str = "") -> None:
        text = f"策略 policy: {self.policy} | {self.conn.url} | 雲端費用 cloud cost ~US${self.cost:.4f}"
        self.query_one("#bar", Static).update(text + (f" | {note}" if note else ""))

    # ── 動作 / Actions ──
    def action_cycle_policy(self) -> None:
        self.policy = POLICIES[(POLICIES.index(self.policy) + 1) % len(POLICIES)]
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

    def action_copy_last(self) -> None:
        last = next((m["content"] for m in reversed(self.history) if m["role"] == "assistant"), None)
        if last:
            self.copy_text(last)
        else:
            self._update_bar("還沒有回答可以複製 / no answer to copy yet")

    def copy_text(self, text: str) -> None:
        """OSC 52（終端機）加系統剪貼簿。 / OSC 52 (terminal) plus the system clipboard."""
        self.copy_to_clipboard(text)
        tool = system_copy(text)
        self.copied = text
        self._update_bar(f"已複製 copied {len(text)} 字 chars" + (f" ({tool})" if tool else " (OSC 52)"))

    async def on_prompt_area_submitted(self, message: PromptArea.Submitted) -> None:
        text = message.text
        if text.startswith("/save"):
            self._save(text[5:].strip())
            return
        if text == "/copy":
            self.action_copy_last()
            return
        if text == "/clear":
            self.history.clear()
            await self.query_one("#log", VerticalScroll).remove_children()
            return
        if self.worker and self.worker.is_running:
            self._update_bar("上一題還在回答 / still answering")
            return
        log = self.query_one("#log", VerticalScroll)
        await log.mount(Static(f"> {text}", classes="user", markup=False))
        answer = Markdown(classes="answer")
        meta = Static("", classes="meta", markup=False)
        await log.mount(answer, meta)
        log.scroll_end(animate=False)
        self.history.append({"role": "user", "content": text})
        self.worker = self.run_worker(self._answer(answer, meta, log), exclusive=True)

    async def _answer(self, answer: Markdown, meta_w: Static, log: VerticalScroll) -> None:
        self.reporter.report("working")
        parts: list[str] = []
        meta = None
        stream = Markdown.get_stream(answer)
        try:
            async for kind, value in stream_chat(self.conn, list(self.history), self.policy):
                if kind == "delta":
                    parts.append(value)
                    await stream.write(value)
                    log.scroll_end(animate=False)
                else:
                    meta = value
            self.last_status = status_line(meta)
            meta_w.update(self.last_status)
            self.cost += ((meta or {}).get("cloud") or {}).get("cost") or 0.0
        except GatewayUnreachable as exc:
            meta_w.update(f"[gateway 未啟動 / not running: {exc}; scripts/jiezi serve]")
        except GatewayError as exc:
            meta_w.update(f"[錯誤 / error: {exc}]")
        except BaseException:
            meta_w.update("[已中斷 / stopped]")
            raise
        finally:
            await stream.stop()
            if parts:
                self.history.append({"role": "assistant", "content": "".join(parts)})
            elif self.history and self.history[-1]["role"] == "user":
                self.history.pop()  # 沒有答案就不留問題，避免下一題連續兩個 user / no answer: drop the question
            self._update_bar()
            self.reporter.report("idle")

    def _save(self, path: str) -> None:
        if not path:
            self._update_bar("用法 usage: /save 檔案.md")
            return
        lines = []
        for m in self.history:
            lines.append(("## 你 / You\n\n" if m["role"] == "user" else "## 芥子 / Jiezi\n\n") + m["content"] + "\n")
        p = Path(path).expanduser()
        p.write_text("\n".join(lines), encoding="utf-8")
        self._update_bar(f"已儲存 saved: {p}")


def main(policy: str = "jiezi") -> int:
    import sys
    conn = Connection.from_env()
    if not conn.key:
        sys.stderr.write("jiezi: JIEZI_GATEWAY_KEY is not set; run scripts/jiezi init-key\n")
        return 3
    ChatApp(conn, policy).run()
    return 0

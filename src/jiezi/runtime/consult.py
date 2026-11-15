"""向 Claude 請教（add-gateway design D9；使用者 2026-11-15 要求）。
Consulting Claude (add-gateway design D9; requested by the user on 2026-11-15).

以無頭模式呼叫本機已登入的 Claude Code CLI（`claude -p`），使用使用者自己的帳號與用量額度。
安全設定：預設只開放讀網頁與網路搜尋（`JIEZI_CONSULT_WEB`，使用者 2026-11-15 同意），其他工具全部關閉；
不載入 MCP 與設定檔、不保存工作階段、在空的暫存目錄執行，所以 Claude 不能讀寫檔案或執行指令。
Calls the locally logged-in Claude Code CLI headlessly (`claude -p`) with the user's own account and usage
allowance. Safety: all tools off (`--tools ""`), no MCP or settings loaded, no session persistence, run in an
empty scratch directory, so Claude can only answer in text and cannot read, write or run anything.

Claude 的回答一律標記為不可用於訓練（Anthropic 條款限制用其輸出訓練模型；R18.3、R20）。
Claude's answers are always marked not usable for training (Anthropic's terms restrict training models on its
outputs; R18.3, R20)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import anyio

from ..errors import JieziError

TRAINING_USE = False
# 只開放讀網頁與網路搜尋（使用者 2026-11-15 同意）；不能讀寫檔案、不能執行指令。
# Only web reading and web search (approved by the user on 2026-11-15); no file access, no commands.
WEB_TOOLS = "WebFetch,WebSearch"
BASE_ARGS = ["-p", "--output-format", "json", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
             "--no-session-persistence", "--setting-sources", ""]


def build_args(web: bool) -> list[str]:
    """工具清單：web=True 時只有 WebFetch、WebSearch 並預先允許（無頭模式無法互動確認）；否則全部關閉。
    Tools: with web, only WebFetch and WebSearch, pre-approved (headless mode cannot ask); otherwise none."""
    if web:
        return [*BASE_ARGS, "--tools", WEB_TOOLS, "--allowedTools", WEB_TOOLS]
    return [*BASE_ARGS, "--tools", ""]


ARGS = build_args(False)  # 相容：不含網路的參數 / compatibility: the no-web arguments


class ConsultError(JieziError):
    pass


def render_prompt(body: dict) -> str:
    """把 OpenAI 格式的對話轉成一段文字。 / Turn an OpenAI-style conversation into one text prompt."""
    parts = []
    for m in body.get("messages") or []:
        content = m.get("content")
        if isinstance(content, list):  # 多段內容只取文字 / text parts only
            content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
        role = {"system": "系統 / System", "user": "使用者 / User", "assistant": "助理 / Assistant",
                "tool": "工具結果 / Tool result"}.get(m.get("role"), m.get("role") or "?")
        parts.append(f"[{role}]\n{content or ''}")
    if body.get("tools"):
        specs = [t.get("function") or t for t in body["tools"]]
        parts.append("[可用的函式 / Available functions]\n" + json.dumps(specs, ensure_ascii=False, indent=1) +
                     "\n若要呼叫函式，只輸出 [函式名(參數=值, ...)]；否則直接回答。\n"
                     "To call a function, output only [name(arg=value, ...)]; otherwise answer directly.")
    parts.append("請回答最後一則使用者訊息。 / Answer the last user message.")
    return "\n\n".join(parts)


class ClaudeCliConsultant:
    def __init__(self, workdir: Path, timeout_s: float = 300, model: str | None = None, binary: str | None = None,
                 run_process=None, web: bool = False):
        self.workdir, self.timeout_s, self.model, self.web = workdir, timeout_s, model, web
        self.binary = binary or shutil.which("claude")
        self.run_process = run_process or anyio.run_process
        self._limit = anyio.Semaphore(1)  # 同時只請教一個問題 / one consultation at a time

    def available(self) -> tuple[bool, str]:
        return (True, "ok") if self.binary else (False, "the `claude` CLI was not found in PATH")

    async def ask(self, body: dict) -> dict:
        if not self.binary:
            raise ConsultError("the `claude` CLI was not found in PATH")
        self.workdir.mkdir(parents=True, exist_ok=True)
        cmd = [self.binary, *build_args(self.web)] + (["--model", self.model] if self.model else [])
        async with self._limit:
            try:
                with anyio.fail_after(self.timeout_s):
                    p = await self.run_process(cmd, input=render_prompt(body).encode("utf-8"), cwd=str(self.workdir),
                                               check=False)
            except TimeoutError as exc:
                raise ConsultError(f"Claude did not answer within {self.timeout_s:.0f}s") from exc
        try:
            data = json.loads(p.stdout.decode("utf-8", "replace"))
        except ValueError as exc:
            raise ConsultError(f"claude exited {p.returncode}: {p.stderr.decode('utf-8', 'replace')[-300:]}") from exc
        if data.get("is_error") or p.returncode != 0:
            raise ConsultError(f"Claude could not answer: {str(data.get('result') or data.get('subtype'))[:300]}")
        mu = data.get("modelUsage") or {}
        # 有多個模型（例如輔助模型）時，取輸出最多的那個 / with several models, take the one with the most output
        models = sorted(mu, key=lambda k: (mu[k] or {}).get("outputTokens") or 0, reverse=True)
        usage = data.get("usage") or {}
        return {"content": data.get("result") or "", "model": models[0] if models else "claude",
                "usage": {"prompt_tokens": (usage.get("input_tokens") or 0) + (usage.get("cache_read_input_tokens") or 0)
                          + (usage.get("cache_creation_input_tokens") or 0),
                          "completion_tokens": usage.get("output_tokens") or 0},
                "cost_equivalent_usd": data.get("total_cost_usd"), "duration_ms": data.get("duration_ms")}

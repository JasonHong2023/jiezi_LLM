"""`jiezi ask "問題"`：單次問答，可接管線（規格 cli：One-Shot Ask；add-cli design D3）。
`jiezi ask "question"`: one-shot, pipeable (spec cli: One-Shot Ask; design D3).

結束碼 / Exit codes：0 成功 / success、2 gateway 無法連線 / unreachable、3 gateway 錯誤 / gateway error、
4 文件讀取失敗 / a document could not be read。"""

from __future__ import annotations

import io

import json
import sys
from typing import TextIO

import anyio

from .client import Connection, GatewayError, GatewayUnreachable, complete, ensure_gateway, status_line, stream_chat

DIM, RESET = "\033[2m", "\033[0m"


def build_messages(question: str, attachment: str | None, docs: list[dict] | None = None) -> list[dict]:
    """管線輸入與 --file 文件都用文件標記包起來，gateway 才能在太長時分段處理（add-long-documents）。
    Piped input and --file documents are wrapped in document markers so the gateway can condense them."""
    from ..documents import attach
    docs = list(docs or [])
    if attachment:
        docs.insert(0, {"name": "管線輸入", "text": attachment.rstrip()})
    content = question
    for d in reversed(docs):
        content = attach(d, content)
    return [{"role": "user", "content": content}]


def _piped(stdin: TextIO) -> bool:
    """只有管線或檔案才當附件讀；終端機、socket 等不讀（2026-11-15：開著不關的 socket 讓 ask 一直等）。
    Read stdin as an attachment only from a pipe or a file; never from a TTY or a socket that never closes."""
    import os
    import stat
    try:
        mode = os.fstat(stdin.fileno()).st_mode
    except (OSError, ValueError, AttributeError, io.UnsupportedOperation):
        return not stdin.isatty()  # 測試用的 StringIO 等 / e.g. StringIO in tests
    return stat.S_ISFIFO(mode) or stat.S_ISREG(mode)


async def run_ask(question: str, policy: str, conn: Connection, as_json: bool, stdin: TextIO, stdout: TextIO,
                  stderr: TextIO, client=None, files: list[str] | None = None) -> int:
    from ..documents import DocumentError, read
    attachment = stdin.read() if _piped(stdin) else None
    docs = []
    for f in files or []:
        try:
            d = await anyio.to_thread.run_sync(read, f)
        except DocumentError as exc:
            stderr.write(f"jiezi: {f}: {exc}\n")
            return 4
        for w in d.get("warnings") or []:
            stderr.write(f"jiezi: {f}: {w}\n")
        if not d["text"].strip():
            stderr.write(f"jiezi: {f}: 讀不到文字（可能是掃描檔且 OCR 失敗）/ no text found\n")
            return 4
        docs.append(d)
    messages = build_messages(question, attachment, docs)
    tty = stdout.isatty()
    try:
        if as_json:
            stdout.write(json.dumps(await complete(conn, messages, policy, client=client), ensure_ascii=False, indent=2) + "\n")
            return 0
        meta = None
        async for kind, value in stream_chat(conn, messages, policy, client=client):
            if kind == "delta":
                stdout.write(value)
                stdout.flush()
            else:
                meta = value
        stdout.write("\n")
        if tty and meta:
            stdout.write(f"{DIM}{status_line(meta)}{RESET}\n")
        elif ((meta or {}).get("injection") or {}).get("suspected"):
            # 管線輸出只有答案，警告寫到 stderr / pipes carry the answer only; the warning goes to stderr
            stderr.write(f"jiezi: 注意 warning: {meta['injection'].get('warning')} / possible prompt injection in "
                         f"the attached data ({', '.join(meta['injection']['suspected'])})\n")
        return 0
    except GatewayUnreachable as exc:
        stderr.write(f"jiezi: {exc}; gateway 未啟動，請執行 scripts/jiezi serve / the gateway is not running; "
                     "start it with scripts/jiezi serve\n")
        return 2
    except GatewayError as exc:
        stderr.write(f"jiezi: {exc}\n")
        return 3


def main(question: str, policy: str = "jiezi", as_json: bool = False, files: list[str] | None = None) -> int:
    conn = Connection.from_env()
    if not conn.key:
        sys.stderr.write("jiezi: JIEZI_GATEWAY_KEY is not set; run scripts/jiezi init-key\n")
        return 3
    ensure_gateway(conn, log=lambda m: sys.stderr.write(m + "\n"))
    return anyio.run(lambda: run_ask(question, policy, conn, as_json, sys.stdin, sys.stdout, sys.stderr,
                                     files=files))

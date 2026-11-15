"""`jiezi ask "問題"`：單次問答，可接管線（規格 cli：One-Shot Ask；add-cli design D3）。
`jiezi ask "question"`: one-shot, pipeable (spec cli: One-Shot Ask; design D3).

結束碼 / Exit codes：0 成功 / success、2 gateway 無法連線 / unreachable、3 gateway 錯誤 / gateway error。"""

from __future__ import annotations

import json
import sys
from typing import TextIO

import anyio

from .client import Connection, GatewayError, GatewayUnreachable, complete, ensure_gateway, status_line, stream_chat

DIM, RESET = "\033[2m", "\033[0m"


def build_messages(question: str, attachment: str | None) -> list[dict]:
    if attachment:
        return [{"role": "user", "content": f"{attachment.rstrip()}\n\n---\n\n{question}"}]
    return [{"role": "user", "content": question}]


async def run_ask(question: str, policy: str, conn: Connection, as_json: bool, stdin: TextIO, stdout: TextIO,
                  stderr: TextIO, client=None) -> int:
    attachment = None if stdin.isatty() else stdin.read()
    messages = build_messages(question, attachment)
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
        return 0
    except GatewayUnreachable as exc:
        stderr.write(f"jiezi: {exc}; gateway 未啟動，請執行 scripts/jiezi serve / the gateway is not running; "
                     "start it with scripts/jiezi serve\n")
        return 2
    except GatewayError as exc:
        stderr.write(f"jiezi: {exc}\n")
        return 3


def main(question: str, policy: str = "jiezi", as_json: bool = False) -> int:
    conn = Connection.from_env()
    if not conn.key:
        sys.stderr.write("jiezi: JIEZI_GATEWAY_KEY is not set; run scripts/jiezi init-key\n")
        return 3
    ensure_gateway(conn, log=lambda m: sys.stderr.write(m + "\n"))
    return anyio.run(run_ask, question, policy, conn, as_json, sys.stdin, sys.stdout, sys.stderr)

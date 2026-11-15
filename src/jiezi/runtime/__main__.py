"""scripts/jiezi 的實作：serve、status、init-key（add-gateway）；ask、chat、check-clients（add-cli）。
Implementation of scripts/jiezi: serve, status, init-key (add-gateway); ask, chat, check-clients (add-cli)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from ..config import ensure_gateway_key, load_env, port_base, project_root
from ..errors import JieziError


def cmd_serve(root) -> int:
    import uvicorn

    from ..engine import LocalEngine
    from ..facts import fresh_facts
    from .gateway import Gateway, create_app
    from .settings import load_settings
    from .supervisor import Supervisor, resolve_core
    from .trajectory import TrajectoryWriter

    sys.stdout.reconfigure(line_buffering=True)  # 導向檔案時也逐行輸出 / line-buffered even when redirected
    s = load_settings(root)
    resolve_core(s)  # 啟動前先確認模型檔存在 / fail fast if the model file is missing
    env = load_env(root)
    factory = lambda facts, path, ngl, port, alias=None: LocalEngine(  # noqa: E731
        root, facts, path, port_base(env), ngl=ngl, ctx=4096, port=port, alias=alias)
    sup = Supervisor(s, lambda: fresh_facts(root), factory)
    gw = Gateway(s, sup, TrajectoryWriter(s.var / "trajectories", s.trajectory, s.retention_days))
    print(f"jiezi gateway on http://{s.host}:{s.gateway_port}/v1  (core {s.core_model}, lazy load; "
          f"cloud escalation {'on' if s.cloud_ready else 'off'}; trajectories {'on' if s.trajectory else 'off'})")
    print("Ctrl-C 關閉 gateway 與引擎 / Ctrl-C stops the gateway and the engine")
    uvicorn.run(create_app(gw), host=s.host, port=s.gateway_port, log_level="warning", access_log=False)
    return 0


def cmd_status(root) -> int:
    env = load_env(root)
    url = f"http://127.0.0.1:{port_base(env)}/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            print(json.dumps(json.loads(r.read()), indent=2, ensure_ascii=False))
            return 0
    except OSError:
        state = root / "var" / "runtime" / "state.json"
        print(f"gateway not reachable at {url}" + (f"; last state: {state.read_text()}" if state.exists() else ""))
        return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scripts/jiezi")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the gateway in the foreground (Ctrl-C stops it and the engine)")
    sub.add_parser("status", help="show gateway and engine state")
    sub.add_parser("init-key", help="generate JIEZI_GATEWAY_KEY in .env if missing")
    a = sub.add_parser("ask", help="one-shot question (pipe a file into stdin to attach it)")
    a.add_argument("question")
    a.add_argument("--json", action="store_true", help="print the full response, including the jiezi field")
    for flag, p in (("--local", "jiezi-local"), ("--cloud", "jiezi-cloud"), ("--claude", "jiezi-ask-claude")):
        a.add_argument(flag, dest="policy", action="store_const", const=p)
    c = sub.add_parser("chat", help="full-screen chat (Textual)")
    for flag, p in (("--local", "jiezi-local"), ("--cloud", "jiezi-cloud"), ("--claude", "jiezi-ask-claude")):
        c.add_argument(flag, dest="policy", action="store_const", const=p)
    sub.add_parser("check-clients", help="read-only check; prints suggested Hermes / OpenCode settings")
    args = ap.parse_args(argv)
    root = project_root()
    try:
        if args.cmd == "serve":
            return cmd_serve(root)
        if args.cmd == "status":
            return cmd_status(root)
        if args.cmd == "ask":
            from ..cli import ask
            return ask.main(args.question, args.policy or "jiezi", args.json)
        if args.cmd == "chat":
            from ..cli import chat
            return chat.main(args.policy or "jiezi")
        if args.cmd == "check-clients":
            from ..cli import check
            return check.main()
        created = ensure_gateway_key(root)
        print("generated JIEZI_GATEWAY_KEY in .env" if created else "JIEZI_GATEWAY_KEY already set (or no .env)")
        return 0
    except JieziError as exc:
        print(f"jiezi: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

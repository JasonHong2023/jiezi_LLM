"""scripts/jiezi 的實作：serve、status、init-key（add-gateway）；ask、chat、check-clients（add-cli）；curriculum（add-curriculum）。
Implementation of scripts/jiezi: serve, status, init-key (add-gateway); ask, chat, check-clients (add-cli); curriculum (add-curriculum)."""

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


def cmd_curriculum(root, args) -> int:
    """課綱知識圖譜指令（add-curriculum）。 / Curriculum graph commands."""
    from .. import curriculum as C
    if args.action == "build":
        counts = C.build(root)
        print(f"built {C.cache_dir(root)}: {counts}; restart the gateway (scripts/jiezi stop && scripts/jiezi start) "
              "to use it")
        return 0
    g = C.Graph.load(root)
    if args.action == "plan":
        if not args.subject or not (args.grade or args.stage):
            print("usage: scripts/jiezi curriculum plan --subject 數學 --grade 3 (or --stage 1)", file=sys.stderr)
            return 2
        ids = g.plan(args.subject, grade=args.grade, stage=args.stage)
        for n, i in enumerate(ids, 1):
            t = g.topics[i]
            before = [g.topics[p]["name"] for p, _ in g.prereq[i] if p in ids]
            codes = "、".join(t.get("contentCodes", []) + t.get("performanceCodes", []))
            print(f"{n:3}. {t['name']}（{t['domain']}）{codes}" + (f"  ← {'、'.join(before)}" if before else ""))
        print(f"— {g.src.attribution}")
        return 0 if ids else 1
    if not args.query:
        print(f"usage: scripts/jiezi curriculum {args.action} <微主題名稱、id 或課綱代碼>", file=sys.stderr)
        return 2
    if args.action == "textbook":
        hits = [g.render_textbook(g.textbooks[i]) for i in g.textbook_query(args.query)] or \
            [g.where_unit(t) for t in g.units_in(args.query)]
        for h in hits:
            print(h + "\n")
        if hits and g.tsrc:
            print(f"— {g.tsrc.attribution}")
        return 0 if hits else 1
    keys = g.codes(args.query) if args.action == "lookup" else []
    ids = g.find(args.query)
    for k in keys:
        print(g.render_standard(k) + "\n")
    for i in ids[:10]:
        if args.action == "path":
            chain = g.ancestors(i) + [i]
            print(f"{g.topics[i]['name']} 的學習路徑（{len(chain) - 1} 項先修）：")
            for n, a in enumerate(chain, 1):
                print(f"{n:3}. {g.topics[a]['name']}（{g.topics[a]['subject']}，{g.grade_text(g.topics[a])}）")
            print()
        else:
            print(g.render(i) + "\n")
    if keys or ids:
        print(f"— {g.src.attribution}")
    return 0 if keys or ids else 1


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
    sub.add_parser("start", help="start the gateway in the background (survives closing the terminal)")
    sub.add_parser("stop", help="stop the background gateway and its engine")
    sub.add_parser("logs", help="show recent gateway logs")
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
    dp = sub.add_parser("dict", help="local dictionary (add-dictionary)")
    dp.add_argument("action", choices=["build", "lookup"])
    dp.add_argument("word", nargs="?")
    cp = sub.add_parser("curriculum", help="108 curriculum knowledge graph, tw-taxonomy (add-curriculum)")
    cp.add_argument("action", choices=["build", "lookup", "path", "plan", "textbook"])
    cp.add_argument("query", nargs="?", help="微主題名稱、id、課綱代碼；textbook：如「數學 7上 翰林」或單元名稱 / topic, code; textbook: e.g. 數學 7上 翰林")
    cp.add_argument("--subject", help="plan：科目，如 數學 / subject")
    cp.add_argument("--grade", type=int, choices=range(1, 7), help="plan：年級 / grade")
    cp.add_argument("--stage", type=int, choices=(1, 2, 3), help="plan：學習階段 / learning stage")
    args = ap.parse_args(argv)
    root = project_root()
    try:
        if args.cmd == "serve":
            return cmd_serve(root)
        if args.cmd == "status":
            return cmd_status(root)
        if args.cmd in ("start", "stop", "logs"):
            from . import service
            port = port_base(load_env(root))
            if args.cmd == "logs":
                return service.logs(root)
            res = service.start(root, port) if args.cmd == "start" else service.stop(root, port)
            print(res)
            return 1 if res == "failed" else 0
        if args.cmd == "ask":
            from ..cli import ask
            return ask.main(args.question, args.policy or "jiezi", args.json)
        if args.cmd == "chat":
            from ..cli import chat
            return chat.main(args.policy or "jiezi")
        if args.cmd == "dict":
            from .. import dictionary
            if args.action == "build":
                counts = dictionary.build(root)
                print(f"built {dictionary.db_path(root)}: {counts}; restart the gateway (scripts/jiezi stop && "
                      "scripts/jiezi start) to use it")
                return 0
            if not args.word:
                print("usage: scripts/jiezi dict lookup <word>", file=sys.stderr)
                return 2
            d = dictionary.Dictionary(dictionary.db_path(root))
            hits = d.lookup(args.word)
            for src, entry in hits:
                print(dictionary.render(entry))
                print(f"— {d.meta.get(src, {}).get('attribution', src)}\n")
            return 0 if hits else 1
        if args.cmd == "curriculum":
            return cmd_curriculum(root, args)
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

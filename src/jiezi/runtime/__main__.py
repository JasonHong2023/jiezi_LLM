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
    slots = s.samples if s.samples > 1 else 1  # 平行取樣需要多個槽位 / parallel sampling needs several slots
    factory = lambda facts, path, ngl, port, alias=None, mmproj=None: LocalEngine(  # noqa: E731
        root, facts, path, port_base(env), ngl=ngl, ctx=4096 * slots, parallel=slots, port=port,
        alias=alias, extra=("--mmproj", str(mmproj)) if mmproj else ())
    sup = Supervisor(s, lambda: fresh_facts(root), factory)
    gw = Gateway(s, sup, TrajectoryWriter(s.var / "trajectories", s.trajectory, s.retention_days),
                 embedder=_embedder(root, s, env), reranker=_reranker(root, s, env))
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


def _embedder(root, s, env, ngl: int = 0, port_offset: int = 2):
    """embedding 引擎（R11 的 engine-embed 埠；預設 CPU，不和對話模型搶 GPU）。沒有模型檔就回傳 None。
    The embedding engine on the R11 engine-embed port (CPU by default). None when the model file is absent."""
    from ..engine import LocalEngine
    from ..facts import fresh_facts
    from ..rag import EMBED_MODEL, Embedder
    path = s.models_dir / "Qwen3-Embedding-0.6B-Q8_0.gguf"
    if not s.rag or not path.exists():
        return None
    return Embedder(lambda: LocalEngine(root, fresh_facts(root), path, port_base(env), ngl=ngl, ctx=8192,
                                        port=port_base(env) + port_offset, alias=EMBED_MODEL,
                                        extra=("--embedding", "--pooling", "last", "-ub", "8192")),
                    log_path=s.var / "runtime" / "engine-embed.log", idle_s=s.idle_unload_s)


def _reranker(root, s, env, force: bool = False):
    """重排序引擎（R11 的 engine-rerank 埠 = 起點 + 6）。開關沒開或沒有模型檔就回傳 None。
    The reranking engine on the R11 engine-rerank port (base + 6). None when switched off or the file is absent."""
    from ..engine import LocalEngine
    from ..facts import fresh_facts
    from ..rag import RERANK_MODEL, Reranker
    path = s.models_dir / "qwen3-reranker-0.6b-q8_0.gguf"
    if not ((s.rerank or force) and s.rag and path.exists()):
        return None
    return Reranker(lambda: LocalEngine(root, fresh_facts(root), path, port_base(env), ngl=99 if s.rerank_gpu else 0,
                                        ctx=8192, port=port_base(env) + 6, alias=RERANK_MODEL,
                                        extra=("--reranking", "-ub", "8192")),
                    log_path=s.var / "runtime" / "engine-rerank.log", idle_s=s.idle_unload_s,
                    timeout_s=s.rerank_timeout_s)


def cmd_rag_relevance(root, args) -> int:
    """`scripts/jiezi rag relevance`：知識庫相關度門檻量測（tune-knowledge-relevance）；只跑檢索，用實驗埠。
    Relevance threshold measurement; retrieval only, on experimental ports."""
    import dataclasses
    import json as _json
    import time as _time
    from .. import rag
    from ..knowledge import Knowledge, db_path as kdb
    from .settings import load_settings
    st = load_settings(root)
    if args.gpu:
        st = dataclasses.replace(st, rerank_gpu=True)
    rows = [_json.loads(x) for x in rag.RELEVANCE_SET.read_text(encoding="utf-8").splitlines() if x.strip()]
    emb = _embedder(root, st, load_env(root), port_offset=12)
    if emb is None:
        print("embedding model not found or JIEZI_RAG=off", file=sys.stderr)
        return 1
    rr = None if args.no_rerank else _reranker(root, st, load_env(root), force=True)
    try:
        kn = Knowledge(kdb(root))
        text_of = lambda i: rag.doc_text(kn.section(i))  # noqa: E731
        ts = [round(0.40 + 0.025 * i, 3) for i in range(17)]          # 0.40–0.80
        res = rag.relevance(kn, rag.VectorStore(rag.vectors_path(root)), emb, rows, ts, reranker=rr, text_of=text_of)
        res["current"] = {"threshold": st.rag_min, "rerank": bool(st.rerank)}
        out = st.var / "eval" / "relevance" / f"relevance-{_time.strftime('%Y%m%d-%H%M%S')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        b = res["best"]
        cur = next((g for g in res["grid"] if g["threshold"] == round(st.rag_min, 3) and g["rerank"] == bool(st.rerank and rr)),
                   None)
        if cur:
            print(f"current t={st.rag_min} rerank={'on' if st.rerank else 'off'}: 該附有附到 {cur['on_hit']:.1%}，"
                  f"不該附卻附了 {cur['false_attach']:.1%}")
        print(f"best: {b}" if b else "no threshold keeps false attachments under the cap")
        print(f"report: {out}")
        return 0
    finally:
        emb.stop()
        if rr is not None:
            rr.stop()


DATA_BUILDS = (("dict", "dictionary"), ("curriculum", "curriculum"), ("knowledge", "knowledge"), ("laws", "laws"),
               ("writing-refs", "writing_refs"))


def cmd_data_build(root, log=print) -> int:
    """依序建置所有本機資料；某一項失敗不影響其他項（R21：搬到新電腦一次重建）。
    Build every local data set in turn; one failure never stops the rest (R21: one command on a new machine)."""
    import importlib
    failed = []
    for name, module in DATA_BUILDS:
        log(f"== {name}")
        if module == "writing_refs":
            from ..writing_refs import index_path
            if index_path(root).exists():  # 不重複抓對方網站 / never re-fetch the site needlessly
                log("  ok: index present (skipped)")
                continue
        try:
            mod = importlib.import_module(f"jiezi.{module}")
            res = mod.build(root)
            log(f"  ok: {res}")
        except Exception as exc:  # noqa: BLE001 - 一項失敗不擋其他 / keep going
            failed.append(name)
            log(f"  failed: {type(exc).__name__}: {exc}")
    log("restart the gateway (scripts/jiezi stop && scripts/jiezi start) to use new data")
    if failed:
        log(f"failed: {', '.join(failed)} (re-run `scripts/jiezi data build` later)")
    return 1 if failed else 0


def cmd_train(root, args) -> int:
    """Phase 6 訓練指令；sft、export 需要使用者同意後安裝的套件。 / Training commands."""
    from pathlib import Path as P
    if args.action == "plan":
        from ..facts import fresh_facts
        from ..train.config import fits
        vram = ((fresh_facts(root).get("budgets") or {}).get("vram") or {})
        budget = int(vram.get("total_mib", 0) - vram.get("floor_mib", 1024)) if vram else 0
        for b in ([args.params] if args.params else [0.8, 2, 4, 9]):
            print(f"{b}B: {fits(b, budget)}  [估 / est.]")
        return 0
    if args.action == "gate":
        from ..train.gate import check, snapshot_from_run
        r = check(snapshot_from_run(P(args.before)), snapshot_from_run(P(args.after)), args.target)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["pass"] else 1
    if args.action == "replay":
        return cmd_replay(root, args.model)
    if args.action == "sft":
        from ..train.config import TrainConfig
        from ..train.sft import train
        cfg = TrainConfig(**json.loads(P(args.config).read_text(encoding="utf-8")))
        out, status = train(cfg, root)
        print(f"{status}: {out}")
        return 0 if status == "done" else 3  # 3 = 暫停，下次接著跑 / paused, resume next time
    from ..train.export import merge, to_gguf
    run_dir = root / "var" / "train" / args.run
    merge(run_dir)
    print(json.dumps(to_gguf(root, run_dir, args.quant), ensure_ascii=False))
    return 0


def cmd_replay(root, model_ref: str) -> int:
    """凍結核心對 MBPP 非 test 題作答，沙盒驗證後寫出複習資料（長時間、用 GPU，夜間）。
    The frozen core answers the non-test MBPP problems; verified answers become replay data (GPU, night job)."""
    from ..eval.__main__ import resolve_model
    from ..eval.client import ChatClient
    from ..eval.engine import LocalEngine
    from ..facts import fresh_facts
    from ..train.replay import build
    from ..verify.sandbox import Sandbox
    env = load_env(root)
    model, _ = resolve_model(root, env, model_ref)
    facts = fresh_facts(root)
    sandbox = Sandbox(root, facts)
    ok, reason = sandbox.available()
    if not ok:
        print(f"sandbox unavailable: {reason}")
        return 2
    log_dir = root / "var" / "training"
    log_dir.mkdir(parents=True, exist_ok=True)
    with LocalEngine(root, facts, model, port_base(env), ngl=99, ctx=4096) as eng:
        eng.start(log_dir / "replay.llama-server.log")
        client = ChatClient(eng.base_url, model.name, timeout_s=300)
        extra = {"chat_template_kwargs": {"enable_thinking": False}}

        def complete(msgs, max_tokens):
            r = client.complete(msgs, temperature=0.0, max_tokens=max_tokens, extra=extra)
            if r.status != "ok":
                raise RuntimeError(r.error or r.status)
            return r.content

        out, stats = build(root, complete, sandbox, log=lambda m: print(m, flush=True))
    print(json.dumps(stats, ensure_ascii=False), flush=True)
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
    sub.add_parser("start", help="start the gateway in the background (survives closing the terminal)")
    sub.add_parser("stop", help="stop the background gateway and its engine")
    sub.add_parser("logs", help="show recent gateway logs")
    sub.add_parser("status", help="show gateway and engine state")
    sub.add_parser("init-key", help="generate JIEZI_GATEWAY_KEY in .env if missing")
    a = sub.add_parser("ask", help="one-shot question (pipe a file into stdin to attach it)")
    a.add_argument("question")
    a.add_argument("--json", action="store_true", help="print the full response, including the jiezi field")
    a.add_argument("--schema", metavar="PATH", help="answer as JSON matching this JSON Schema file (exit 5 if it does not)")
    a.add_argument("--json-object", action="store_true", help="answer as a JSON object")
    a.add_argument("--file", "-f", action="append", default=[], metavar="PATH",
                   help="attach a document (PDF, .docx, .html, text); repeatable")
    for flag, p in (("--local", "jiezi-local"), ("--cloud", "jiezi-cloud"), ("--claude", "jiezi-ask-claude")):
        a.add_argument(flag, dest="policy", action="store_const", const=p)
    tr = sub.add_parser("translate", help="translate a whole document chunk by chunk (add-translation)")
    tr.add_argument("file")
    tr.add_argument("--to", choices=["zh-TW", "en"], help="target language (default: Chinese → en, otherwise zh-TW)")
    tr.add_argument("--out", metavar="PATH", help="write the result to a file instead of stdout")
    tr.add_argument("--glossary", metavar="PATH", help="required translations: TSV or `source=translation` lines")
    tr.add_argument("--plain", action="store_true", help="translation only (default: source and translation side by side)")
    tr.add_argument("--yes", "-y", action="store_true", help="do not ask before a long translation")
    tr.add_argument("--local", dest="policy", action="store_const", const="jiezi-local",
                    help="never leave this machine (no escalation when the local engine is unavailable)")
    c = sub.add_parser("chat", help="full-screen chat (Textual)")
    c.add_argument("--new", action="store_true", help="開新對話，不接續上次 / start fresh instead of resuming")
    for flag, p in (("--local", "jiezi-local"), ("--cloud", "jiezi-cloud"), ("--claude", "jiezi-ask-claude")):
        c.add_argument(flag, dest="policy", action="store_const", const=p)
    sub.add_parser("check-clients", help="read-only check; prints suggested Hermes / OpenCode settings")
    cap = sub.add_parser("capabilities", help="capabilities registry validation (add-agent-capability-registry)")
    cap.add_argument("action", choices=["check"], help="check registry and proposals")
    cap.add_argument("--toml", help="預設 <專案>/docs/capabilities.toml / default under the project root")
    cap.add_argument("--changes-root", help="預設 <專案>/openspec/changes / default under the project root")
    dp = sub.add_parser("dict", help="local dictionary (add-dictionary)")
    dp.add_argument("action", choices=["build", "lookup"])
    dp.add_argument("word", nargs="?")
    cp = sub.add_parser("curriculum", help="108 curriculum knowledge graph, tw-taxonomy (add-curriculum)")
    cp.add_argument("action", choices=["build", "lookup", "path", "plan", "textbook"])
    cp.add_argument("query", nargs="?", help="微主題名稱、id、課綱代碼；textbook：如「數學 7上 翰林」或單元名稱 / topic, code; textbook: e.g. 數學 7上 翰林")
    cp.add_argument("--subject", help="plan：科目，如 數學 / subject")
    cp.add_argument("--grade", type=int, choices=range(1, 7), help="plan：年級 / grade")
    cp.add_argument("--stage", type=int, choices=(1, 2, 3), help="plan：學習階段 / learning stage")
    lp = sub.add_parser("laws", help="national law database, MOJ (add-laws)")
    lp.add_argument("action", choices=["build", "lookup", "embed"])
    lp.add_argument("--gpu", action="store_true", help="embed: 用 GPU 建向量 / use the GPU")
    lp.add_argument("query", nargs="?", help="例如「民法第184條」/ e.g. 民法第184條")
    mp = sub.add_parser("memory", help="memory wiki: consulted answers, notes, corrections (add-memory)")
    mp.add_argument("action", choices=["list", "search", "forget", "path"])
    mp.add_argument("query", nargs="?", help="search：問題；forget：主題名稱 / search: question; forget: topic title")
    trp = sub.add_parser("train", help="Phase 6 LoRA training (R20): plan, sft, export, gate")
    trp.add_argument("action", choices=["plan", "sft", "export", "gate", "replay"])
    trp.add_argument("--model", default="qwen3.5-4b-q4_k_m", help="replay: 凍結核心（清單名稱）/ frozen core")
    trp.add_argument("--params", type=float, help="plan: 模型參數量（十億）/ model size in billions")
    trp.add_argument("--config", help="sft: 設定檔 JSON / TrainConfig JSON")
    trp.add_argument("--run", help="export: var/train/<run>")
    trp.add_argument("--quant", default="Q8_0")
    trp.add_argument("--before", help="gate: 訓練前的評測目錄 / run dir before")
    trp.add_argument("--after", help="gate: 訓練後的評測目錄 / run dir after")
    trp.add_argument("--target", action="append", default=[], help="gate: 目標任務 tool|code|qa|summary")
    sub.add_parser("doctor", help="health check of every component, with fixes")
    sub.add_parser("g1", help="G1 recommendation from the E0 results (the user decides)")
    cal = sub.add_parser("calibrate", help="measure speed at several GPU layer counts (dev plan 4.4); heavy")
    cal.add_argument("--model", help="清單名稱，預設為核心 / manifest name, default the core")
    skp = sub.add_parser("skills", help="skill library v0: verified tool-call examples")
    skp.add_argument("action", choices=["build", "list"])
    up = sub.add_parser("ui", help="desktop front end (Phase 8 prototype), served at /ui/")
    up.add_argument("action", choices=["build"])
    sub.add_parser("audit", help="dependency security audit against OSV (R23); queries only")
    dap = sub.add_parser("data", help="build every local data set (dictionaries, curriculum, knowledge, laws, links)")
    dap.add_argument("action", choices=["build"])
    dsp = sub.add_parser("dataset", help="export SFT training data (R20.3 verified only; no evaluation overlap)")
    dsp.add_argument("action", choices=["export"])
    dsp.add_argument("--limit", type=int, default=2000, help="template examples per source")
    dsp.add_argument("--replay", help="複習資料 JSONL（train replay 產生）/ replay JSONL from `train replay`")
    dsp.add_argument("--replay-ratio", type=float, default=0.0, help="複習資料佔全部的比例 / replay share, 0–<1")
    dsp.add_argument("--toolcall-datasets", action="store_true",
                     help="收外部工具呼叫資料集（ToolACE、hermes-fc；預設不收）/ include licensed tool-calling datasets")
    from .. import toolcheck as TC

    tc = sub.add_parser("toolcheck", help="ACEBench/BFCL through the gateway as OpenAI tools (system-level score)")
    tc.add_argument("--policy", default="jiezi-local")
    tc.add_argument("--suite", choices=list(TC.SUITES), default="r0",
                    help="r0 (default 50 ACEBench), acebench-full, bfcl, or all")
    tc.add_argument("--limit", type=int, help="at most N items per source in the suite")
    sub.add_parser("dashboard", help="metrics dashboard: achievement rate, local handling, E0, self-test, gaps")
    sp = sub.add_parser("selftest", help="self-test generated from the bundled data (dictionary, curriculum, tools…)")
    sp.add_argument("--policy", default="jiezi-local", help="gateway policy (default jiezi-local)")
    sp.add_argument("--limit", type=int, help="at most N items per kind")
    sp.add_argument("--list", action="store_true", help="only print the questions")
    sp.add_argument("--dry", action="store_true", help="no model: check whether the attached data holds the answer")
    gp = sub.add_parser("gaps", help="gap report: questions the local model could not handle")
    gp.add_argument("--days", type=int, default=7, help="最近幾天 / how many recent days (default 7)")
    agp = sub.add_parser("agent", help="read-only agent: grants and audit log (add-agent-readonly)")
    agp.add_argument("action", choices=["grant", "revoke", "grants", "audit", "server", "trust-mcp",
                                        "approvals", "show", "approve", "deny", "rollback"])
    agp.add_argument("folder", nargs="?", help="grant／revoke：資料夾；trust-mcp：MCP server 名稱 / folder or server name")
    agp.add_argument("--remove", action="store_true", help="trust-mcp：取消標記 / unmark")
    agp.add_argument("--sha256", default="", help="approve：內容 sha256 的前 12 碼以上（show 會顯示）/ content sha256 prefix")
    agp.add_argument("--reason", default="", help="approve／deny／rollback：理由，寫入稽核 / reason for the audit")
    agp.add_argument("--days", type=int, default=1, help="audit: 最近幾天 / recent days")
    gp = sub.add_parser("rag", help="knowledge-base retrieval measurements (tune-knowledge-relevance)")
    gp.add_argument("action", choices=["relevance"])
    gp.add_argument("--gpu", action="store_true", help="重排序放 GPU / run the reranker on GPU")
    gp.add_argument("--no-rerank", action="store_true", help="只量向量 / vectors only")
    rp = sub.add_parser("rerank", help="reranker self-check and A/B measurement (add-reranker)")
    rp.add_argument("action", choices=["check", "measure"])
    rp.add_argument("--gpu", action="store_true", help="重排序放 GPU / run the reranker on GPU")
    rp.add_argument("-n", type=int, default=40, help="measure: 題數 / number of queries (default 40)")
    kp = sub.add_parser("knowledge", help="Taiwan knowledge base, taiwan-md (add-knowledge)")
    kp.add_argument("action", choices=["build", "search", "embed"])
    kp.add_argument("--gpu", action="store_true", help="embed: 用 GPU 建向量（E0 等評測沒在跑時）/ use the GPU")
    kp.add_argument("query", nargs="?")
    wp = sub.add_parser("writing-refs", help="writing-lesson link index, titles and URLs only (add-curriculum D6)")
    wp.add_argument("action", choices=["build", "search"])
    wp.add_argument("query", nargs="?")
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
            return ask.main(args.question, args.policy or "jiezi", args.json, args.file, args.schema, args.json_object)
        if args.cmd == "translate":
            from ..cli import translate as translate_cli
            return translate_cli.main(args.file, args.to, args.out, args.glossary, args.plain, args.yes,
                                      args.policy or "jiezi")
        if args.cmd == "chat":
            from ..cli import chat
            return chat.main(args.policy or "jiezi", new=args.new)
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
        if args.cmd == "laws":
            from .. import laws as L
            if args.action == "build":
                print(f"built {L.db_path(root)}: {L.build(root)}; restart the gateway to use it")
                return 0
            if args.action == "embed":
                from .. import rag
                from .settings import load_settings
                emb = _embedder(root, load_settings(root), load_env(root), ngl=99 if args.gpu else 0)
                if emb is None:
                    print("embedding model not found or JIEZI_RAG=off", file=sys.stderr)
                    return 1
                lw = L.Laws(L.db_path(root))
                try:
                    res = rag.build(lw, rag.VectorStore(L.vectors_path(root), model_sha="06507c7b4268", create=True),
                                    emb, ids=L.current_ids(lw), text_of=lambda i: L.doc_text(lw, i))
                finally:
                    emb.stop()
                print(f"law vectors: {res}; restart the gateway to use them")
                return 0
            g = L.grounding(L.Laws(L.db_path(root)), args.query or "")
            print(g[3].split("\n", 3)[-1] if g else "（找不到 / not found）")
            return 0 if g else 1
        if args.cmd == "memory":
            from .. import memory as M
            m = M.Memory(M.wiki_path(root), root)
            if args.action == "path":
                print(m.wiki)
                return 0
            if args.action == "list":
                topics = m.topics()
                counts = {}
                for e in m.entries:
                    counts.setdefault(e.title, [0, 0])[0 if e.kind == "qa" else 1] += e.kind != "note"
                print(f"記憶 wiki / memory wiki: {m.wiki}")
                print(f"主題 {len(topics)} 個 / topics:")
                for t in sorted(topics):
                    qa, corr = counts.get(t, [0, 0])
                    print(f"  - {t}（問答 {qa}、更正 {corr}）")
                notes = m.notes()
                print(f"要記住的事 {len(notes)} 條 / notes:")
                for n in notes:
                    print(f"  - {n.at}：{n.text}")
                return 0
            if not args.query:
                print(f"usage: scripts/jiezi memory {args.action} <...>", file=sys.stderr)
                return 2
            if args.action == "forget":
                ok = m.forget(args.query)
                print("已刪除 / deleted" if ok else "找不到這個主題 / no such topic（scripts/jiezi memory list）")
                return 0 if ok else 1
            found = m.find_answer(args.query)
            for c in m.corrections_for(args.query):
                print(f"[更正 correction] {c.title}｜{c.question}\n{c.text}\n")
            if found:
                e, sim = found
                print(f"[答案 answer {sim:.2f}] {e.title}｜{e.question}（{e.at[:10]}，{e.provider}）\n{e.text}")
            return 0 if found else 1
        if args.cmd == "train":
            return cmd_train(root, args)
        if args.cmd == "ui":
            import shutil
            import subprocess
            npm = shutil.which("npm")
            if not npm:
                print("npm not found; install Node.js LTS first", file=sys.stderr)
                return 1
            ui = root / "ui"
            if subprocess.run([npm, "ci", "--no-fund"], cwd=ui).returncode != 0:
                print("failed: ci", file=sys.stderr)
                return 1
            # 高風險漏洞擋下建置；security/accepted.toml 已評估並寫理由的除外（R23；使用者 2026-11-18 同意）
            # High-severity advisories stop the build unless assessed with a reason in security/accepted.toml (R23)
            import json as _json
            from ..audit import accepted, npm_unaccepted
            rep = subprocess.run([npm, "audit", "--json"], cwd=ui, capture_output=True, text=True)
            try:
                bad = npm_unaccepted(_json.loads(rep.stdout or "{}"), accepted(root))
            except ValueError:
                bad = ["npm audit output unreadable"]
            if bad:
                print(f"failed: audit — high-severity advisories not in security/accepted.toml: {', '.join(bad)}",
                      file=sys.stderr)
                return 1
            if subprocess.run([npm, "run", "build"], cwd=ui).returncode != 0:
                print("failed: run build", file=sys.stderr)
                return 1
            print("built ui/dist; restart the gateway, then open http://127.0.0.1:36100/ui/")
            return 0
        if args.cmd == "skills":
            from .. import skills as SK
            if args.action == "build":
                print(SK.build(root))
                return 0
            for r in SK.Skills(SK.skills_path(root)).rows:
                print(f"{r['at'][:16] if r.get('at') else ''}  {r['question'][:50]}  →  {r['call'][:80]}")
            return 0
        if args.cmd == "g1":
            from . import g1
            out, rec = g1.report(root)
            w = rec.get("winner")
            print(f"recommended: {w['name'] if w else None} — {rec['reason']}; report: {out}")
            return 0
        if args.cmd == "calibrate":
            from ..facts import fresh_facts
            from .calibrate import run as calibrate
            from .settings import load_settings
            from .supervisor import resolve_core
            core = resolve_core(load_settings(root), args.model)
            r = calibrate(root, core["name"], core["path"], core["sha256"], fresh_facts(root))
            print(f"{core['name']}: best ngl {r['best_ngl']}; {r['results']}")
            return 0
        if args.cmd == "doctor":
            from . import doctor
            text, rc = doctor.report(root, port_base(load_env(root)))
            print(text)
            return rc
        if args.cmd == "audit":
            from .. import audit
            out, r = audit.run(root)
            print(f"checked {r['checked']}; with vulnerabilities {r['with_vulns']}; unaccepted {r['unaccepted']}; "
                  f"report: {out}")
            return 1 if r["unaccepted"] else 0
        if args.cmd == "data":
            return cmd_data_build(root)
        if args.cmd == "dataset":
            from .. import training_data
            from pathlib import Path as P
            out, m = training_data.export(root, args.limit, P(args.replay) if args.replay else None,
                                          args.replay_ratio, toolcall_datasets=args.toolcall_datasets)
            print(f"{m['examples']} examples {m['by_source']}; excluded {m['excluded']}; file: {out}")
            return 0
        if args.cmd == "toolcheck":
            from .. import toolcheck
            env = load_env(root)
            out, summary = toolcheck.run(root, f"http://127.0.0.1:{port_base(env)}", env.get("JIEZI_GATEWAY_KEY") or "",
                                         args.policy, suite=args.suite, limit=args.limit)
            print(f"[{summary['suite']}] {summary['correct']}/{summary['items']} correct "
                  f"{summary['by_status']} {summary['by_source']}; report: {out}")
            return 0
        if args.cmd == "dashboard":
            from . import dashboard
            print(f"dashboard: {dashboard.write(root)}")
            return 0
        if args.cmd == "selftest":
            from .. import selftest
            if args.list:
                for it in selftest.build(root):
                    print(f"[{it.kind}] {it.question}  →  {it.article or it.number or '、'.join(it.expect[:3])}")
                return 0
            if args.dry:
                cov = selftest.coverage(root)
                print("資料覆蓋 / data coverage:", cov["by_kind"])
                for q in cov["misses"]:
                    print("  miss:", q)
                return 0
            env = load_env(root)
            out, summary = selftest.run(root, f"http://127.0.0.1:{port_base(env)}", env.get("JIEZI_GATEWAY_KEY") or "",
                                        args.policy, args.limit)
            print(f"{summary['correct']}/{summary['items']} correct {summary['by_kind']}; report: {out}")
            return 0
        if args.cmd == "gaps":
            from . import gaps
            out, summary = gaps.write(root, args.days)
            print(f"本機需要幫忙 {summary['needed_help']} 筆 / needed help: {summary['by_kind']}；"
                  f"直接請教 {summary['direct']} 筆；報告 / report: {out}")
            return 0
        if args.cmd == "agent":
            from ..agent import audit as AU
            from ..agent.grants import Grants
            g = Grants(root)
            if args.action == "server":  # MCP stdio 伺服器（給 Hermes／OpenCode 設定用）/ MCP server for other clients
                from ..agent.server import main as serve_mcp
                sys.argv = [sys.argv[0], "mcp"]
                return serve_mcp()
            if args.action in ("grant", "revoke"):
                if not args.folder:
                    print(f"usage: scripts/jiezi agent {args.action} <folder>", file=sys.stderr)
                    return 2
                try:
                    if args.action == "grant":
                        print(f"granted (read-only): {g.grant(args.folder)}")
                    else:
                        print("revoked" if g.revoke(args.folder) else "was not granted")
                except ValueError as exc:
                    print(f"refused: {exc}", file=sys.stderr)
                    return 2
                return 0
            if args.action in ("approvals", "show", "approve", "deny", "rollback"):  # add-agent-approval
                from ..agent.approval import ApprovalError, ApprovalStore, public
                store = ApprovalStore(root)
                if args.action == "approvals":
                    rows = store.list()
                    if not rows:
                        print("（沒有寫入請求 / no write requests）")
                    for r in rows:
                        print(f"{r['id']}  {r['status']:<11} {r['bytes']:>8} B  {r['path']}")
                    return 0
                if not args.folder:
                    print(f"usage: scripts/jiezi agent {args.action} <id>", file=sys.stderr)
                    return 2
                if args.action == "show":
                    r = store.get(args.folder)
                    if r is None:
                        print("no such approval request", file=sys.stderr)
                        return 2
                    meta = public(r)
                    print("\n".join(f"{k}: {meta[k]}" for k in ("id", "status", "path", "bytes", "sha256", "expires_at")))
                    print("----- 將寫入的完整內容 / full content -----")
                    print(r["content"])
                    print("----- 結束 / end -----")
                    print(f"核准 / approve: scripts/jiezi agent approve {r['id']} --sha256 {r['sha256'][:12]}")
                    return 0
                action = {"approve": "allow", "deny": "deny", "rollback": "rollback"}[args.action]
                try:
                    r = store.decide(g, args.folder, action, args.sha256, args.reason, actor="cli")
                except ApprovalError as exc:
                    print(f"refused: {exc}", file=sys.stderr)
                    return 2
                AU.write(root, {"source": "cli", "tool": "write_file", "approval_id": r["id"], "outcome": r["status"],
                                "reason": args.reason[:300], "arguments": {"path": r["path"]}, "allowed": True})
                print(f"{r['status']}: {r['path']}")
                return 0
            if args.action == "trust-mcp":  # add-agent-trust-gate T8.2
                if not args.folder:
                    names = g.trusted_servers()
                    print("\n".join(names) if names else "（沒有受信任的 MCP server / none trusted）")
                    return 0
                try:
                    changed = g.trust_mcp(args.folder, remove=args.remove)
                except ValueError as exc:
                    print(f"refused: {exc}", file=sys.stderr)
                    return 2
                state = "untrusted" if args.remove else "trusted"
                print(f"{state}: {args.folder}" if changed else f"unchanged: {args.folder}")
                return 0
            if args.action == "grants":
                folders = g.folders()
                print("\n".join(str(f) for f in folders) if folders else "（沒有授權任何資料夾 / nothing granted）")
                return 0
            rows = AU.read(root, args.days)
            for r in rows:
                what = r.get("path") or ""
                extra = r.get("error") or (f"{r['chars']} 字" if r.get("chars") is not None else
                                           f"{r.get('entries') or r.get('matches') or ''}")
                print(f"{r['at']}  {'允許' if r.get('allowed') else '拒絕'}  {r.get('tool')}  {what}  {extra}")
            print(f"{len(rows)} entries ({args.days} day(s))")
            return 0
        if args.cmd == "rag":
            return cmd_rag_relevance(root, args)
        if args.cmd == "rerank":
            import dataclasses
            import json as _json
            from .. import rag
            from ..knowledge import Knowledge, db_path as kdb
            from .settings import load_settings
            st = load_settings(root)
            if args.gpu:
                st = dataclasses.replace(st, rerank_gpu=True)
            rr = _reranker(root, st, load_env(root), force=True)
            if rr is None:
                print("reranker model not found (models/manifest.toml: qwen3-reranker-0.6b-q8_0) or JIEZI_RAG=off",
                      file=sys.stderr)
                return 1
            emb = None
            try:
                ok = rr.check()
                print(f"reranker self-check: {rr.note} ({'gpu' if st.rerank_gpu else 'cpu'})")
                if args.action == "check" or not ok:
                    return 0 if ok else 1
                # 量測用實驗埠（R11 的 36110–36119），不和 gateway 的 embedding 引擎搶 36102
                # Measured on an experimental port so the gateway's embedder keeps 36102
                emb = _embedder(root, st, load_env(root), port_offset=12)
                kn = Knowledge(kdb(root))
                store = rag.VectorStore(rag.vectors_path(root))
                text_of = lambda i: rag.doc_text(kn.section(i))  # noqa: E731
                res = rag.measure(kn, rag.HybridRetriever(kn, store, emb, st.rag_min),
                                  rag.HybridRetriever(kn, store, emb, st.rag_min, reranker=rr, text_of=text_of),
                                  n=args.n)
                res["placement"] = "gpu" if st.rerank_gpu else "cpu"
                out = st.var / "reports" / f"rerank-measure-{res['placement']}.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(_json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"gain {res['gain_points']} points, +{res['extra_seconds']} s/query; report: {out}")
                return 0
            finally:
                rr.stop()
                if emb is not None:
                    emb.stop()
        if args.cmd == "knowledge":
            from .. import knowledge as K
            if args.action == "build":
                counts = K.build(root)
                print(f"built {K.db_path(root)}: {counts}; restart the gateway to use it")
                return 0
            if args.action == "embed":
                from .. import rag
                from .settings import load_settings
                s = load_settings(root)
                emb = _embedder(root, s, load_env(root), ngl=99 if args.gpu else 0)
                if emb is None:
                    print("embedding model not found or JIEZI_RAG=off", file=sys.stderr)
                    return 1
                try:
                    res = rag.build(K.Knowledge(K.db_path(root)),
                                    rag.VectorStore(rag.vectors_path(root), model_sha="06507c7b4268", create=True), emb)
                finally:
                    emb.stop()
                print(f"vectors: {res}; restart the gateway to use them")
                return 0
            g = K.grounding(K.Knowledge(K.db_path(root)), args.query or "")
            print(g[0].split("\n\n", 1)[1] + g[3] if g else "（沒有相關段落 / nothing relevant）")
            return 0 if g else 1
        if args.cmd == "writing-refs":
            from .. import writing_refs as W
            if args.action == "build":
                print(f"indexed {W.build(root)} articles into {W.index_path(root)}; restart the gateway to use it")
                return 0
            hits = W.WritingRefs(W.index_path(root)).search(args.query or "", limit=10)
            for r in hits:
                print(f"{r['title']}（{r['category']}）{r['url']}")
            return 0 if hits else 1
        if args.cmd == "curriculum":
            return cmd_curriculum(root, args)
        if args.cmd == "check-clients":
            from ..cli import check
            return check.main()
        if args.cmd == "capabilities":
            from ..cli.capabilities import main as capabilities_main
            return capabilities_main([args.action, "--toml", args.toml or str(root / "docs" / "capabilities.toml"),
                                      "--changes-root", args.changes_root or str(root / "openspec" / "changes")])
        created = ensure_gateway_key(root)
        print("generated JIEZI_GATEWAY_KEY in .env" if created else "JIEZI_GATEWAY_KEY already set (or no .env)")
        return 0
    except JieziError as exc:
        print(f"jiezi: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

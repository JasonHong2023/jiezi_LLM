"""scripts/eval 的實作（規格 eval；design D8、D9）。 / Implementation of scripts/eval (spec eval; design D8, D9).

子指令 / Subcommands:
  bank lock|fetch|verify   產生鎖定檔 / 依鎖定檔取得並驗證題目 / generate the lock; fetch and verify items
  run                      執行評測（只在夜間時段內，除非 --now）/ run an evaluation (night window only unless --now)
  report RUN_ID            產生報表 / produce the report
  verify RUN_ID            事後評分（程式、工具、摘要、評審）/ score a finished run after the fact
  xcheck-tool RUN_ID       在沙盒內執行 ACEBench 官方判定逐題對照移植版 / side-by-side with the official ACEBench checker
  e0 plan|fetch|run|sample|report  E0 多模型對照（add-e0-benchmark）/ E0 multi-model comparison
  schedule [--list] -- …   排程到下一個夜間時段 / schedule into the next night window"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path

from jiezi.config import load_env, port_base, project_root
from jiezi.facts import FACTS_MAX_AGE_S, fresh_facts  # noqa: F401  (共用 / shared)

from . import EvalError, bank, lock, night, prompts, report, runner, verify_run
from .client import ChatClient
from .engine import LocalEngine

KNOWN_LIMITATIONS = ["ceval-val: pinned ZIP may lack the 2025 val re-upload fixes (design D3)"]


# ── 題庫 / Bank ─────────────────────────────────────────────────────────────

def paths(root: Path, name: str) -> dict:
    return {"definition": root / "eval" / "banks" / f"{name}.toml",
            "lock": root / "eval" / "banks" / f"{name}.lock.json",
            "items": root / "var" / "eval" / "banks" / name / "items.jsonl",
            "cache": root / "var" / "eval" / "cache"}


def load_items(root: Path, name: str, log=print) -> tuple[dict, list[dict]]:
    p = paths(root, name)
    b = bank.load_bank(p["definition"])
    if not p["lock"].exists():
        raise EvalError(f"{p['lock']} not found; run `scripts/eval bank lock --bank {name}` first")
    lk = json.loads(p["lock"].read_text(encoding="utf-8"))
    items = lock.read_items(p["items"], lk)
    if items is None:
        log("materializing the bank from the lock (downloads on first use)…")
        items = lock.materialize(b, lk, p["definition"], p["cache"], log=log)
        lock.write_items(items, p["items"], lk)
    return lk, items


def cmd_bank(args, root: Path) -> int:
    p = paths(root, args.bank)
    b = bank.load_bank(p["definition"])
    if args.action == "lock":
        if p["lock"].exists() and not args.force:
            raise EvalError(f"{p['lock']} exists; a new lock is a new bank version — pass --force to replace it")
        lk, items = lock.build_lock(b, p["definition"], p["cache"])
        p["lock"].write_text(json.dumps(lk, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        lock.write_items(items, p["items"], lk)
        print(f"wrote {p['lock'].relative_to(root)}: {len(items)} items, bank_hash {lk['bank_hash'][:16]}")
        return 0
    lk = json.loads(p["lock"].read_text(encoding="utf-8"))
    items = lock.materialize(b, lk, p["definition"], p["cache"])
    lock.write_items(items, p["items"], lk)
    print(f"{len(items)} items verified against {p['lock'].relative_to(root)} (bank_hash {lk['bank_hash'][:16]})")
    return 0


# ── 執行 / Run ──────────────────────────────────────────────────────────────

def resolve_model(root: Path, env: dict, ref: str) -> tuple[Path, str | None]:
    """--model 可以是 models/manifest.toml 的名稱或檔案路徑；回傳 (路徑, 清單中的 SHA-256)。
    --model is a manifest name or a file path; return (path, manifest SHA-256)."""
    models_dir = Path(env["JIEZI_MODELS_DIR"]).expanduser() if env.get("JIEZI_MODELS_DIR") else root / "models"
    manifest = tomllib.loads((root / "models" / "manifest.toml").read_text(encoding="utf-8"))
    for m in manifest.get("model") or []:
        if ref in (m["name"], m["file"]):
            return models_dir / m["file"], m["sha256"]
    path = Path(ref).expanduser()
    return (path if path.is_absolute() else Path.cwd() / path), None


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def build_record(root: Path, backend: str) -> dict:
    f = root / "var" / "builds" / f"{backend}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def select(items: list[dict], args) -> list[dict]:
    out = items
    if args.source:
        out = [i for i in out if i["source"] in set(args.source)]
    if args.group:
        out = [i for i in out if i["group"] == args.group]
    if args.only_scorable:
        out = [i for i in out if i["scorer"] != "pending_verifier"]
    if args.limit:
        per: dict[str, int] = {}
        kept = []
        for i in out:
            if per.get(i["source"], 0) < args.limit:
                per[i["source"]] = per.get(i["source"], 0) + 1
                kept.append(i)
        out = kept
    if not out:
        raise EvalError("no items left after filtering")
    return out


# 推理模型（例如 2026-11-15 的雲端基準 Nemotron）先輸出思考再回答；只給回答所需的 token 會全部用在思考上。
# Reasoning models (e.g. the 2026-11-15 cloud baseline, Nemotron) think before answering; an answer-sized
# max_tokens is spent entirely on thinking.
DEFAULT_REASONING_BUDGET = 4096


def release_gateway(root: Path, env: dict, window, forced: bool) -> str:
    """評測載入模型前請 gateway 卸載並暫停到時段結束（add-gateway D4）；結果記入條件（R17）。
    Ask the gateway to unload and hold until the window ends before loading (add-gateway D4); recorded (R17)."""
    from datetime import timedelta

    from jiezi.runtime.coord import release_for_eval
    now_ = datetime.now()
    hold = None
    if not forced and window.contains(now_):
        end = now_.replace(hour=window.end // 60 % 24, minute=window.end % 60, second=0, microsecond=0)
        hold = end if end > now_ else end + timedelta(days=1)
    try:
        status = release_for_eval(root, env.get("JIEZI_GATEWAY_KEY"), hold)
    except Exception as exc:  # noqa: BLE001 - 協調失敗不可讓評測失敗 / never fail the evaluation over this
        status = f"check_failed ({type(exc).__name__})"
    if status not in ("not_running",) and not status.startswith("idle"):
        print(f"gateway: {status}")
    return status


def cmd_run(args, root: Path) -> int:
    env = load_env(root)
    window = night.parse_window(env.get("JIEZI_NIGHT_WINDOW"))
    if not args.now and not window.contains(datetime.now()):
        raise EvalError("outside the night window (R18.2a); use `scripts/eval schedule -- …` "
                        "or pass --now only if the user explicitly asked to run now")
    lk, items = load_items(root, args.bank)
    items = select(items, args)
    run_id = args.resume or args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{args.backend}"
    run_dir = root / "var" / "eval" / "runs" / run_id

    reasoning_budget = args.reasoning_budget
    if reasoning_budget is None:
        reasoning_budget = DEFAULT_REASONING_BUDGET if (args.backend == "cloud" or args.thinking) else 0
    identity = {"bank": args.bank, "bank_hash": lk["bank_hash"], "template_hash": prompts.template_hash(),
                "reasoning_budget": reasoning_budget,
                "backend": args.backend, "temperature": args.temperature, "samples": args.samples,
                "filters": {"source": sorted(args.source or []), "group": args.group, "limit": args.limit,
                            "only_scorable": args.only_scorable}, "items": len(items)}
    context = {"started": runner.now(), "known_limitations": KNOWN_LIMITATIONS, "timeout_s": args.timeout,
               "night_window": env.get("JIEZI_NIGHT_WINDOW") or night.DEFAULT_WINDOW, "forced_now": args.now}

    if args.backend == "local":
        context["gateway"] = release_gateway(root, env, window, args.now)
        facts = fresh_facts(root)
        model, manifest_sha = resolve_model(root, env, args.model or "qwen3-0.6b-q8_0")
        if not model.is_file():
            raise EvalError(f"model not found: {model}")
        sha = manifest_sha or file_sha256(model)
        build = build_record(root, "cuda" if args.ngl > 0 else "cpu")
        eng = LocalEngine(root, facts, model, port_base(env), ngl=args.ngl, ctx=args.ctx)
        identity.update(model_file=model.name, model_sha256=sha, thinking=args.thinking,
                        llama_cpp_commit=build.get("llama_cpp_commit"), build_configure=build.get("configure"),
                        engine={k: v for k, v in eng.describe().items() if k not in ("port", "notes")})
        context.update(fingerprint=(facts.get("fingerprint") or {}).get("id"),
                       budgets_cpu=(facts.get("budgets") or {}).get("cpu"),
                       budgets_ram=(facts.get("budgets") or {}).get("ram"),
                       budgets_vram=(facts.get("budgets") or {}).get("vram"), engine_notes=eng.describe()["notes"])
        runner.prepare_run_dir(run_dir, identity, context, resume=bool(args.resume))
        extra = {"chat_template_kwargs": {"enable_thinking": bool(args.thinking)}}
        with eng:
            eng.start(run_dir / "llama-server.log")
            client = ChatClient(eng.base_url, model.name, timeout_s=args.timeout or 600)
            summary = runner.run(items, client, run_dir, samples=args.samples, temperature=args.temperature,
                                 extra=extra, retry_errors=args.retry_errors, reasoning_budget=reasoning_budget,
                                 may_continue=lambda: args.now or window.contains(datetime.now()),
                                 engine_alive=eng.alive)
        (run_dir / "engine.json").write_text(json.dumps({**eng.describe(), "peak_rss_mib": eng.peak_rss_mib,
                                                         "peak_vram_mib": eng.peak_vram_mib}, indent=2) + "\n")
    else:
        base, key = env.get("JIEZI_CLOUD_BASE_URL"), env.get("JIEZI_CLOUD_API_KEY")
        model_name = args.model or env.get("JIEZI_BASELINE_MODEL")
        if not base or not model_name:
            raise EvalError("cloud runs need JIEZI_CLOUD_BASE_URL and a model (--model or JIEZI_BASELINE_MODEL) in .env")
        identity.update(cloud_model=model_name, baseline=args.baseline,
                        model_match=env.get("JIEZI_BASELINE_MODEL_MATCH") if args.baseline else None)
        runner.prepare_run_dir(run_dir, identity, context, resume=bool(args.resume))
        client = ChatClient(base, model_name, api_key=key, timeout_s=args.timeout or 120, baseline=args.baseline,
                            model_match=env.get("JIEZI_BASELINE_MODEL_MATCH"))
        summary = runner.run(items, client, run_dir, samples=args.samples, temperature=args.temperature,
                             retry_errors=args.retry_errors, reasoning_budget=reasoning_budget,
                             may_continue=lambda: args.now or window.contains(datetime.now()))
    rep = report.write(run_dir)
    print(f"run {run_id}: {summary['state']} ({summary['recorded']}/{summary['total']}, errors {summary['errors']}); "
          f"report: {(run_dir / 'report.md').relative_to(root)}; completeness: {rep['completeness']}")
    return 0 if summary["state"] == "complete" else 3


def cmd_verify(args, root: Path) -> int:
    """事後評分（add-verifiers design D7）。 / After-the-fact scoring (add-verifiers design D7)."""
    run_dir = root / "var" / "eval" / "runs" / args.run_id
    if not (run_dir / "conditions.json").exists():
        raise EvalError(f"{run_dir} has no conditions.json")
    ident = json.loads((run_dir / "conditions.json").read_text(encoding="utf-8"))["identity"]
    env = load_env(root)
    # --judge-model 只影響這次；此時 .env 的比對字串屬於另一個模型，不沿用。
    # --judge-model applies to this call only; the .env match string belongs to another model then.
    if getattr(args, "judge_model", None):
        judge_model, judge_match = args.judge_model, getattr(args, "judge_match", None)
    else:
        judge_model, judge_match = env.get("JIEZI_JUDGE_MODEL"), env.get("JIEZI_JUDGE_MODEL_MATCH")
    kinds = args.only or [k for k in verify_run.KINDS if "judge" not in k or judge_model]
    window = night.parse_window(env.get("JIEZI_NIGHT_WINDOW"))
    long_kinds = sorted(set(kinds) - verify_run.QUICK_KINDS)
    if long_kinds and not args.now and not window.contains(datetime.now()):
        raise EvalError(f"{', '.join(long_kinds)} are long jobs (R18.2a); outside the night window use "
                        f"`scripts/eval schedule --job \"verify {args.run_id}\"`, or --only tool summary_rules now")
    lk, items = load_items(root, ident.get("bank", "r0"))
    if lk["bank_hash"] != ident.get("bank_hash"):
        raise EvalError("the run used a different bank version than the current lock")
    verifiers, versions = verify_run.quick_verifiers()
    vcond: dict = {"kinds": kinds, "versions": {}, "started": runner.now()}
    if "code" in kinds:
        from jiezi.verify import code as code_v
        from jiezi.verify.sandbox import Sandbox
        sb = Sandbox(root, fresh_facts(root))
        cv = code_v.CodeVerifier(sb, root / "var" / "verify" / "expected")
        verifiers["code"], versions["code"] = cv.verify, f"{code_v.VERSION}/{sb.describe()['version']}"
        ok, reason = sb.available()
        vcond["sandbox"] = {**sb.describe(), "available": ok, "reason": reason}
        if not ok:
            print(f"注意 / Note: sandbox unavailable ({reason}); code items stay pending_verifier")
    judge_kinds = [k for k in kinds if "judge" in k]
    if judge_kinds:
        from jiezi.verify import judge as judge_v
        base, key = env.get("JIEZI_CLOUD_BASE_URL"), env.get("JIEZI_CLOUD_API_KEY")
        if not judge_model or not base:
            raise EvalError("judging needs JIEZI_JUDGE_MODEL and JIEZI_CLOUD_BASE_URL in .env (and user consent)")
        client = ChatClient(base, judge_model, api_key=key, timeout_s=args.timeout or 120, baseline=True,
                            model_match=judge_match)
        j = judge_v.Judge(client, judge_model, root / "var" / "verify" / "judge",
                          reasoning_budget=args.reasoning_budget)
        try:
            j.check_not_self(ident.get("cloud_model"))
        except judge_v.JudgeRefused as exc:
            raise EvalError(str(exc)) from exc
        tag = f"{judge_v.VERSION}/{judge_v.PROMPT_HASH}/{judge_model}"
        verifiers["simpleqa_judge"], versions["simpleqa_judge"] = j.simpleqa, tag
        verifiers["summary_judge"], versions["summary_judge"] = j.summary, tag
        vcond["judge"] = j.describe()
    vcond["versions"] = {k: versions[k] for k in kinds}
    vpath = run_dir / "verify_conditions.json"
    if vpath.exists():  # 累加：保留之前其他種類的條件 / accumulate: keep earlier kinds' conditions
        old = json.loads(vpath.read_text(encoding="utf-8"))
        vcond = {**old, **vcond, "kinds": sorted(set(old.get("kinds", [])) | set(kinds)),
                 "versions": {**old.get("versions", {}), **vcond["versions"]}}
    (run_dir / "verify_conditions.json").write_text(json.dumps(vcond, indent=2, ensure_ascii=False) + "\n",
                                                    encoding="utf-8")
    summary = verify_run.verify_run(run_dir, items, kinds, verifiers, versions,
                                    may_continue=lambda: args.now or not long_kinds or window.contains(datetime.now()))
    rep = report.write(run_dir)
    print(f"verify {args.run_id}: {summary['state']}; report: {(run_dir / 'report.md').relative_to(root)}; "
          f"completeness: {rep['completeness']}")
    return 0 if summary["state"] == "complete" else 3


def cmd_xcheck_tool(args, root: Path) -> int:
    """ACEBench 官方判定（沙盒內）與移植版逐題對照（add-verifiers 3.2）；長時間工作，夜間時段。
    Official ACEBench checker (in the sandbox) vs the port, case by case (add-verifiers 3.2); night-window job."""
    from jiezi.verify import acebench_xcheck as xc
    from jiezi.verify.sandbox import Sandbox
    run_dir = root / "var" / "eval" / "runs" / args.run_id
    if not (run_dir / "conditions.json").exists():
        raise EvalError(f"{run_dir} has no conditions.json")
    window = night.parse_window(load_env(root).get("JIEZI_NIGHT_WINDOW"))
    if not args.now and not window.contains(datetime.now()):
        raise EvalError("xcheck-tool runs upstream code in the sandbox, a long job (R18.2a); "
                        f"use `scripts/eval schedule --job \"xcheck-tool {args.run_id}\"`")
    ident = json.loads((run_dir / "conditions.json").read_text(encoding="utf-8"))["identity"]
    lk, items = load_items(root, ident.get("bank", "r0"))
    if lk["bank_hash"] != ident.get("bank_hash"):
        raise EvalError("the run used a different bank version than the current lock")
    sb = Sandbox(root, fresh_facts(root))
    ok, reason = sb.available()
    if not ok:
        raise EvalError(f"sandbox unavailable ({reason}); upstream code is never run outside it")
    upstream = xc.fetch_upstream(root / "var" / "verify" / "upstream")
    rep = {"version": xc.VERSION, "commit": xc.COMMIT, "port": xc.tool_call.VERSION,
           "sandbox": sb.describe()["version"], "started": runner.now()}
    rep["parts"] = {"hand-written cases": xc.compare(sb, upstream, xc.HAND_CASES),
                    f"run {args.run_id}": xc.compare(sb, upstream, xc.run_cases(run_dir, items,
                                                                                runner.latest_results(run_dir)))}
    rep["finished"] = runner.now()
    (run_dir / "xcheck_tool.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "xcheck_tool.md").write_text(xc.to_markdown(rep), encoding="utf-8")
    bad = sum(p["counts"].get("disagree", 0) for p in rep["parts"].values())
    for name, part in rep["parts"].items():
        print(f"{name}: {part['counts']}")
    print(f"xcheck-tool: {bad} disagreement(s); see {(run_dir / 'xcheck_tool.md').relative_to(root)}")
    return 0 if bad == 0 else 4


def e0_smoke(root: Path, env: dict, row, path: Path, ngl: int, out_dir: Path) -> dict:
    """E0 冒煙檢查：固定 5 題（add-e0-benchmark design D3）。 / E0 smoke check: 5 fixed items (design D3)."""
    from . import e0
    _, items = load_items(root, "r0")
    picked = e0.smoke_items(items)
    answers = []
    release_gateway(root, env, night.parse_window(env.get("JIEZI_NIGHT_WINDOW")), forced=False)
    try:
        eng = LocalEngine(root, fresh_facts(root), path, port_base(env), ngl=ngl, ctx=e0.CTX)
        with eng:
            eng.start(out_dir / f"{row.name}.llama-server.log")
            client = ChatClient(eng.base_url, path.name, timeout_s=600)
            for it in picked:
                messages, max_tokens = prompts.render(it)
                rep = client.complete(messages, temperature=0.0, max_tokens=max_tokens,
                                      extra={"chat_template_kwargs": {"enable_thinking": False}})
                answers.append((it, rep.content if rep.status == "ok" else None))
    except EvalError as exc:
        return {"ok": False, "parsed": 0, "reasons": [f"engine: {exc}"]}
    res = e0.judge_smoke(answers)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{row.name}.json").write_text(json.dumps(
        {**res, "at": runner.now(), "ngl": ngl,
         "answers": [{"key": f"{i['source']}/{i['id']}", "content": c} for i, c in answers]},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  smoke: {'ok' if res['ok'] else 'FAILED'} ({res['parsed']}/5 parse) {'; '.join(res['reasons'])}")
    return res


def cmd_e0(args, root: Path) -> int:
    """E0 多模型對照（規格 e0-benchmark）。 / E0 multi-model comparison (spec e0-benchmark)."""
    from types import SimpleNamespace

    from . import e0
    env = load_env(root)
    window = night.parse_window(env.get("JIEZI_NIGHT_WINDOW"))
    rows, mhash = e0.load_matrix(root)
    state = e0.load_state(root, mhash)
    save = lambda: e0.save_state(root, mhash, state)  # noqa: E731

    if args.action == "plan":
        facts = fresh_facts(root)
        total = 0.0
        print(f"matrix {mhash}: {len(rows)} rows; budgets RAM {facts['budgets']['ram']['usable_mib']} MiB, "
              f"VRAM {facts['budgets']['vram']['usable_mib']} MiB")
        for p in e0.plan(rows, state, facts.get("budgets") or {}):
            total += p["est_minutes"] or 0
            print(f"  {p['row']:<26} {p['group']:<8} {p['quant']:<7} {p['size_mib']:>6} MiB  {p['state']:<15} "
                  f"{p['excluded'] or p['placement']:<15} ~{p['est_minutes'] or 0:>5} min  {p['reason'] or ''}")
        print(f"estimated greedy time left: ~{total / 60:.1f} h (night window {env.get('JIEZI_NIGHT_WINDOW') or night.DEFAULT_WINDOW}) [est.]")
        return 0
    if args.action == "report":
        rep = e0.write_report(root, rows, state)
        status = "complete" if rep["complete"] else f"incomplete ({len(rep['missing'])} rows missing)"
        print(f"e0 report: {(e0.state_dir(root, mhash) / 'report.md').relative_to(root)}; {status}")
        return 0

    if not args.now and not window.contains(datetime.now()):
        raise EvalError(f"e0 {args.action} is a long job (R18.2a); use `scripts/eval schedule --job \"e0 {args.action}\"`")
    in_window = lambda: args.now or window.contains(datetime.now())  # noqa: E731
    mdir = Path(env["JIEZI_MODELS_DIR"]).expanduser() if env.get("JIEZI_MODELS_DIR") else root / "models"

    if args.action == "fetch":
        failed = 0
        for r in rows:
            if not in_window():
                print("night window ended; stopping downloads")
                return 3
            try:
                e0.ensure_model(r, mdir)
                print(f"  {r.model}: ok")
            except (EvalError, OSError) as exc:
                failed += 1
                print(f"  {r.model}: {exc}")
        return 0 if not failed else 4

    def run_hook(row, ngl, resume, samples, temperature, sources, run_id=None):
        rid = run_id or row.run_id
        resume = resume or (root / "var" / "eval" / "runs" / rid / "conditions.json").exists()
        a = SimpleNamespace(bank="r0", backend="local", model=row.model, ngl=ngl, ctx=e0.CTX, thinking=False,
                            reasoning_budget=None, baseline=False, samples=samples, temperature=temperature,
                            timeout=None, source=sources, group=None, only_scorable=False, limit=None,
                            run_id=None if resume else rid, resume=rid if resume else None, retry_errors=resume,
                            now=args.now)
        try:
            return cmd_run(a, root)
        except EvalError as exc:
            print(f"  run failed: {exc}")
            return 2

    def verify_hook(run_id, only):
        a = SimpleNamespace(run_id=run_id, only=only, now=args.now, timeout=None,
                            reasoning_budget=DEFAULT_REASONING_BUDGET, judge_model=args.judge_model,
                            judge_match=args.judge_match)
        try:
            return cmd_verify(a, root)
        except EvalError as exc:
            print(f"  verify failed: {exc}")
            return 2

    def smoke_hook(row, path, ngl):
        return e0_smoke(root, env, row, path, ngl, e0.state_dir(root, mhash) / "smoke")

    hooks = e0.Hooks(fresh_facts=lambda: fresh_facts(root), models_dir=mdir, in_window=in_window,
                     run=run_hook, verify=verify_hook, smoke=smoke_hook)
    if args.action == "run":
        result = e0.run_rows(rows, state, hooks, save)
    else:
        _, items = load_items(root, "r0")
        sources = sorted({i["source"] for i in items if i["task"] in e0.SAMPLE_TASKS})
        result = e0.run_sampling(root, rows, state, hooks, sources, save)
    save()
    e0.write_report(root, rows, state)
    print(f"e0 {args.action}: {result}")
    return 0 if result == "complete" else 3


SCHEDULABLE = {"run", "bank", "report", "verify", "xcheck-tool", "e0"}


def parse_jobs(args) -> list[list[str]]:
    """--job "run --model x" 可重複；或 `-- <run 參數>` 單一 run 工作。
    --job "run --model x" is repeatable; or `-- <run options>` for a single run job."""
    jobs = [shlex.split(j) for j in (args.job or [])]
    rest = [a for a in (args.run_args or []) if a != "--"]
    if rest:
        jobs.append(["run", *rest])
    if not jobs:
        raise EvalError('usage: scripts/eval schedule --job "run …" [--job "…"] | scripts/eval schedule -- <run options>')
    for j in jobs:
        if j[0] not in SCHEDULABLE:
            raise EvalError(f"jobs must start with one of {', '.join(sorted(SCHEDULABLE))}: {' '.join(j)}")
        if "--now" in j:
            raise EvalError("--now makes no sense in a schedule")
    return jobs


def cmd_schedule(args, root: Path) -> int:
    if args.cancel:
        print(night.cancel(root, args.cancel))
        return 0
    if args.list:
        for s in night.list_schedules(root):
            jobs = " ; ".join(" ".join(j) for j in s.get("jobs") or [])
            print(f"{s['id']}  {s['when']}  {s['state']:<40}  {s['method']}  {jobs}")
        return 0
    jobs = parse_jobs(args)
    env = load_env(root)
    window = night.parse_window(env.get("JIEZI_NIGHT_WINDOW"))
    when = night.planned_time(window, datetime.now())
    rec = night.schedule(root, jobs, when)
    print(f"scheduled {rec['id']} at {rec['when']} via {rec['method']}: {len(jobs)} job(s), run in order")
    note = night.linger_note()
    if note:
        print(note)
    return 0


# ── 參數 / Arguments ────────────────────────────────────────────────────────

def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="scripts/eval", description="Jiezi evaluation harness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bank", help="bank lock / fetch / verify")
    b.add_argument("action", choices=["lock", "fetch", "verify"])
    b.add_argument("--bank", default="r0")
    b.add_argument("--force", action="store_true", help="replace an existing lock (new bank version)")

    r = sub.add_parser("run", help="run an evaluation")
    r.add_argument("--bank", default="r0")
    r.add_argument("--backend", choices=["local", "cloud"], default="local")
    r.add_argument("--model", help="local: manifest name or GGUF path (default qwen3-0.6b-q8_0); cloud: model name")
    r.add_argument("--ngl", type=int, default=0, help="GPU layers (0 = CPU only, uses build-cpu)")
    r.add_argument("--ctx", type=int, default=4096)
    r.add_argument("--thinking", action="store_true", help="enable Qwen3 thinking mode (default off, OQ2)")
    r.add_argument("--reasoning-budget", type=int,
                   help=f"extra max_tokens for thinking, added to each answer budget "
                        f"(default {DEFAULT_REASONING_BUDGET} for cloud or --thinking, else 0)")
    r.add_argument("--baseline", action="store_true", help="cloud baseline mode: disable fallbacks, verify model")
    r.add_argument("--samples", type=int, default=1)
    r.add_argument("--temperature", type=float, default=0.0)
    r.add_argument("--timeout", type=float, help="per-request timeout in seconds (cloud 120, local 600)")
    r.add_argument("--source", action="append", help="only this source key (repeatable)")
    r.add_argument("--group", choices=["knowledge", "reasoning"])
    r.add_argument("--only-scorable", action="store_true", help="skip pending_verifier items")
    r.add_argument("--limit", type=int, help="at most N items per source")
    r.add_argument("--run-id")
    r.add_argument("--resume", metavar="RUN_ID")
    r.add_argument("--retry-errors", action="store_true")
    r.add_argument("--now", action="store_true", help="ignore the night window (only when the user asks)")

    rp = sub.add_parser("report", help="(re)build a run's report")
    rp.add_argument("run_id")

    v = sub.add_parser("verify", help="score a finished run after the fact (verifiers)")
    v.add_argument("run_id")
    v.add_argument("--only", nargs="+", choices=list(verify_run.KINDS),
                   help="only these kinds (tool and summary_rules are quick and may run any time)")
    v.add_argument("--reasoning-budget", type=int, default=DEFAULT_REASONING_BUDGET,
                   help="extra max_tokens for a reasoning judge model")
    v.add_argument("--timeout", type=float, help="judge request timeout in seconds (default 120)")
    v.add_argument("--judge-model", help="judge model for this run only (overrides JIEZI_JUDGE_MODEL)")
    v.add_argument("--judge-match", help="expected substring of the judge's reported model (with --judge-model)")
    v.add_argument("--now", action="store_true", help="ignore the night window (only when the user asks)")

    x = sub.add_parser("xcheck-tool", help="side-by-side with the official ACEBench checker (in the sandbox)")
    x.add_argument("run_id")
    x.add_argument("--now", action="store_true", help="ignore the night window (only when the user asks)")

    e = sub.add_parser("e0", help="E0 multi-model comparison (add-e0-benchmark)")
    e.add_argument("action", choices=["plan", "fetch", "run", "sample", "report"])
    e.add_argument("--judge-model", help="judge model for verification (e.g. nvidia-nemotron-3-ultra)")
    e.add_argument("--judge-match", help="expected substring of the judge's reported model")
    e.add_argument("--now", action="store_true", help="ignore the night window (only when the user asks)")

    s = sub.add_parser("schedule", help="schedule a run into the next night window")
    s.add_argument("--list", action="store_true")
    s.add_argument("--cancel", metavar="SCHEDULE_ID", help="cancel a schedule that has not started")
    s.add_argument("--job", action="append", help='one job, e.g. "run --model qwen3-0.6b-q8_0" (repeatable, run in order)')
    s.add_argument("run_args", nargs=argparse.REMAINDER)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    root = project_root()
    try:
        if args.cmd == "bank":
            return cmd_bank(args, root)
        if args.cmd == "run":
            return cmd_run(args, root)
        if args.cmd == "verify":
            return cmd_verify(args, root)
        if args.cmd == "xcheck-tool":
            return cmd_xcheck_tool(args, root)
        if args.cmd == "e0":
            return cmd_e0(args, root)
        if args.cmd == "report":
            rep = report.write(root / "var" / "eval" / "runs" / args.run_id)
            print(f"completeness: {rep['completeness']}")
            return 0
        return cmd_schedule(args, root)
    except EvalError as exc:
        print(f"eval: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""scripts/eval 的實作（規格 eval；design D8、D9）。 / Implementation of scripts/eval (spec eval; design D8, D9).

子指令 / Subcommands:
  bank lock|fetch|verify   產生鎖定檔 / 依鎖定檔取得並驗證題目 / generate the lock; fetch and verify items
  run                      執行評測（只在夜間時段內，除非 --now）/ run an evaluation (night window only unless --now)
  report RUN_ID            產生報表 / produce the report
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

from . import EvalError, bank, lock, night, prompts, report, runner
from .client import ChatClient
from .engine import LocalEngine

FACTS_MAX_AGE_S = 60  # 規則 R18.1 / rule R18.1
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

def fresh_facts(root: Path) -> dict:
    """facts.json 超過 60 秒就重新探測（R18.1）。 / Re-probe when facts.json is older than 60 s (R18.1)."""
    f = root / "facts.json"
    if not f.exists() or time.time() - f.stat().st_mtime > FACTS_MAX_AGE_S:
        p = subprocess.run([sys.executable, str(root / "scripts" / "hwprobe.py"), "--out", str(f)],
                           capture_output=True, text=True)
        if p.returncode != 0 or not f.exists():
            raise EvalError(f"hwprobe failed: {p.stderr.strip()}")
    return json.loads(f.read_text(encoding="utf-8"))


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


SCHEDULABLE = {"run", "bank", "report"}


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

    s = sub.add_parser("schedule", help="schedule a run into the next night window")
    s.add_argument("--list", action="store_true")
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

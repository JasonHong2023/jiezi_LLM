"""逐題執行、結果記錄、續跑、失敗暫停與夜間時段停止（規格 eval：Measurement Conditions、Resumable Runs、
Hang and Failure Handling、Night Window；design D8、D9、D11）。
Per-item execution, result records, resumption, failure pause, and night-window stop."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import EvalError, prompts, scoring
from .client import ChatClient

MAX_CONSECUTIVE_FAILURES = 5
ERROR_STATUSES = ("error_timeout", "error_http")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def prepare_run_dir(run_dir: Path, identity: dict, context: dict, resume: bool) -> None:
    """新執行寫出 conditions.json；續跑時 identity 必須完全相同。
    Write conditions.json for a new run; on resume the identity must match exactly."""
    cond = run_dir / "conditions.json"
    if resume:
        if not cond.exists():
            raise EvalError(f"{run_dir} has no conditions.json; nothing to resume")
        old = json.loads(cond.read_text(encoding="utf-8"))["identity"]
        diff = sorted(k for k in set(old) | set(identity) if old.get(k) != identity.get(k))
        if diff:
            lines = [f"  {k}: run={old.get(k)!r} now={identity.get(k)!r}" for k in diff]
            raise EvalError("cannot resume under different conditions (R17):\n" + "\n".join(lines))
        return
    if run_dir.exists() and any(run_dir.iterdir()):
        raise EvalError(f"{run_dir} already exists; use --resume to continue it")
    run_dir.mkdir(parents=True, exist_ok=True)
    cond.write_text(json.dumps({"identity": identity, "context": context}, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def item_key(item: dict, sample: int) -> str:
    return f"{item['source']}/{item['id']}#{sample}"


def latest_results(run_dir: Path) -> dict[str, dict]:
    """每個 key 取最後一筆（補跑後以新結果為準）。 / Last record per key (reruns supersede)."""
    out: dict[str, dict] = {}
    path = run_dir / "results.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def _append(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()


def _tps(reply) -> float | None:
    t = (reply.timings or {}).get("predicted_per_second")
    if t:
        return round(float(t), 2)
    toks = (reply.usage or {}).get("completion_tokens")
    return round(toks / reply.latency_s, 2) if toks and reply.latency_s else None


def run(items: list[dict], client: ChatClient, run_dir: Path, *, samples: int = 1, temperature: float = 0.0,
        extra: dict | None = None, retry_errors: bool = False,
        may_continue: Callable[[], bool] = lambda: True, engine_alive: Callable[[], bool] = lambda: True,
        log: Callable[[str], None] = print) -> dict:
    """執行（或續跑）所有題目與樣本；回傳並寫出 run_state.json。
    Run (or resume) every item and sample; return and write run_state.json."""
    done = latest_results(run_dir)
    todo = []
    for it in items:
        for s in range(samples):
            k = item_key(it, s)
            prev = done.get(k)
            if prev is None or (retry_errors and prev["status"] in ERROR_STATUSES):
                todo.append((it, s, k))
    total = len(items) * samples
    log(f"{total - len(todo)}/{total} already done; {len(todo)} to run")

    state, consecutive = "complete", 0
    for n, (it, s, k) in enumerate(todo, 1):
        if not may_continue():
            state = "paused_window"
            log("night window ended; stopping before the next item (resume with --resume)")
            break
        if not engine_alive():
            state = "engine_died"
            log("local engine is not running; stopping")
            break
        messages, max_tokens = prompts.render(it)
        reply = client.complete(messages, temperature=temperature, max_tokens=max_tokens, extra=extra)
        rec = {"key": k, "source": it["source"], "id": it["id"], "task": it["task"], "group": it["group"],
               "scorer": it["scorer"], "sample": s, "status": reply.status, "score": None, "extracted": None,
               "content": reply.content, "model": reply.model, "usage": reply.usage, "latency_s": reply.latency_s,
               "tps": _tps(reply), "attempts": reply.attempts, "error": reply.error, "at": now()}
        if reply.status == "ok":
            rec.update(scoring.score(it, reply.content))
            consecutive = 0
        elif reply.status in ERROR_STATUSES:
            consecutive += 1
            _append(run_dir / "errors.jsonl", rec)
        else:  # void_model_mismatch：服務有回應，不算服務中斷 / service answered; not an outage
            consecutive = 0
        _append(run_dir / "results.jsonl", rec)
        if n % 10 == 0 or n == len(todo):
            log(f"  {n}/{len(todo)} ({rec['status']})")
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            state = "paused_outage"
            log(f"{MAX_CONSECUTIVE_FAILURES} consecutive failures; pausing (resume later with --resume --retry-errors)")
            break

    final = latest_results(run_dir)
    summary = {"state": state, "total": total, "recorded": len(final),
               "errors": sum(1 for r in final.values() if r["status"] in ERROR_STATUSES), "updated": now()}
    if state == "complete" and summary["recorded"] < total:
        summary["state"] = "incomplete"
    (run_dir / "run_state.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary

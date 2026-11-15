"""事後評分（規格 eval：After-the-Fact Verification；add-verifiers design D7）。
After-the-fact scoring (spec eval: After-the-Fact Verification; add-verifiers design D7).

讀 results.jsonl（不修改），把驗證結果附加到 verifications.jsonl；同一份回答、同一版驗證器只驗一次。
Reads results.jsonl (never modified) and appends to verifications.jsonl; each response is verified once per
verifier version.

種類 / Kinds：
  tool            ACEBench 規則（秒級，任何時間可跑）/ ACEBench rules (second-scale, any time)
  summary_rules   摘要字數與簡體字（秒級）/ summary length and simplified characters (second-scale)
  code            沙盒執行（長時間工作，夜間時段）/ sandboxed execution (long job, night window)
  simpleqa_judge  官方 LLM 評審（雲端，需同意，夜間）/ official LLM judge (cloud, consent, night)
  summary_judge   摘要忠實度與涵蓋度（雲端，需同意，夜間）/ summary faithfulness and coverage (cloud, consent, night)"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..verify import summary_rules, tool_call
from . import EvalError
from .runner import latest_results

KINDS = ("tool", "summary_rules", "code", "simpleqa_judge", "summary_judge")
QUICK_KINDS = {"tool", "summary_rules"}
NEEDS = {"tool": ("tool",), "summary_rules": ("summary",), "code": ("code",), "simpleqa_judge": ("simpleqa",),
         "summary_judge": ("summary",)}
MAX_CONSECUTIVE_FAILURES = 5


def kind_targets(rec: dict) -> str:
    """結果紀錄對應的題型鍵。 / The item-type key of a result record."""
    if rec["scorer"] == "simpleqa_approx":
        return "simpleqa"
    return rec["task"]


def response_hash(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def latest_verifications(run_dir: Path) -> dict[tuple[str, str], dict]:
    """(key, kind) → 最後一筆。 / (key, kind) → last record."""
    out: dict[tuple[str, str], dict] = {}
    p = run_dir / "verifications.jsonl"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                v = json.loads(line)
                out[(v["key"], v["kind"])] = v
    return out


def _append(path: Path, rec: dict) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def verify_run(run_dir: Path, items: list[dict], kinds: list[str], verifiers: dict[str, Callable],
               versions: dict[str, str], log=print, may_continue: Callable[[], bool] = lambda: True) -> dict:
    """依序驗證；回傳摘要。verifiers[kind](item, content) → 驗證結果。
    Verify in order; return a summary. verifiers[kind](item, content) → result."""
    results = latest_results(run_dir)
    if not results:
        raise EvalError(f"{run_dir} has no results to verify")
    by_id = {(i["source"], i["id"]): i for i in items}
    done = latest_verifications(run_dir)
    out_path = run_dir / "verifications.jsonl"
    summary = {k: {"verified": 0, "skipped": 0} for k in kinds}
    state = "complete"
    for kind in kinds:
        consecutive = 0
        # 失敗、作廢、截斷的題目沒有可驗證的回答 / failed, void, and truncated items have no answer to verify
        targets = [r for r in results.values() if r["status"] in ("pending_verifier", "correct", "wrong", "unparsed")
                   and kind_targets(r) in NEEDS[kind]]
        for rec in targets:
            if not may_continue():
                state = "paused_window"
                break
            rh = response_hash(rec.get("content"))
            prev = done.get((rec["key"], kind))
            if prev and prev.get("response_hash") == rh and prev.get("verifier") == versions[kind] \
                    and prev["status"] not in ("error_timeout", "error_http"):
                summary[kind]["skipped"] += 1
                continue
            item = by_id.get((rec["source"], rec["id"]))
            if item is None:
                raise EvalError(f"item {rec['source']}/{rec['id']} is not in the bank; wrong bank for this run?")
            v = verifiers[kind](item, rec.get("content") or "")
            row = {"key": rec["key"], "kind": kind, "source": rec["source"], "id": rec["id"],
                   "response_hash": rh, "verifier": versions[kind], "status": v["status"], "score": v.get("score"),
                   "details": v.get("details"), "judge_model": v.get("judge_model"),
                   "at": datetime.now().astimezone().isoformat(timespec="seconds")}
            _append(out_path, row)
            summary[kind]["verified"] += 1
            consecutive = consecutive + 1 if v["status"] in ("error_timeout", "error_http") else 0
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                state = "paused_outage"
                log(f"{kind}: {MAX_CONSECUTIVE_FAILURES} consecutive judge failures; pausing (rerun verify later)")
                break
        log(f"  {kind}: {summary[kind]['verified']} verified, {summary[kind]['skipped']} already done")
        if state != "complete":
            break
    summary["state"] = state
    return summary


def quick_verifiers() -> tuple[dict, dict]:
    return ({"tool": tool_call.verify, "summary_rules": summary_rules.verify},
            {"tool": tool_call.VERSION, "summary_rules": summary_rules.VERSION})

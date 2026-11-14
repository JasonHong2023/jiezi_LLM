"""報表（規格 eval：Reports；規則 R17.5）。 / Reports (spec eval: Reports; rule R17.5).

- 知識題與推理 / 工具題分開，**不產生合併總分**。 / Knowledge and reasoning / tools are separate; **no merged score**.
- 貪婪解碼與多樣本分開標示。 / Greedy and multi-sample runs are labeled.
- 未評分、無法解析、作廢、失敗分列；有失敗或作廢就標為「不完整」，不可作為權威基準（R17.6）。
  Unscored, unparsed, void, and failed counts are separate; any failure or void marks the run "incomplete",
  which cannot be an authoritative baseline (R17.6)."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from .runner import ERROR_STATUSES, latest_results

GROUP_TITLES = {"knowledge": "知識題 / Knowledge", "reasoning": "推理與工具題 / Reasoning & tools"}
APPROX_NOTE = "近似比對，非官方評分 / approximate matching, not the official scorer"


def _counts(records: list[dict]) -> dict:
    scored = [r for r in records if r["score"] is not None and r["status"] not in ERROR_STATUSES
              and r["status"] != "void_model_mismatch"]
    correct = sum(r["score"] for r in scored)
    return {
        "records": len(records),
        "scored": len(scored),
        "correct": correct,
        "accuracy": round(correct / len(scored), 4) if scored else None,
        "unparsed": sum(r["status"] == "unparsed" for r in records),
        "truncated": sum(r["status"] == "truncated" for r in records),
        "pending_verifier": sum(r["status"] == "pending_verifier" for r in records),
        "void_model_mismatch": sum(r["status"] == "void_model_mismatch" for r in records),
        "errors": sum(r["status"] in ERROR_STATUSES for r in records),
    }


def _stats(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"mean": round(statistics.fmean(values), 2),
            "stdev": round(statistics.stdev(values), 2) if len(values) > 1 else 0.0, "n": len(values)}


def build(run_dir: Path) -> dict:
    cond = json.loads((run_dir / "conditions.json").read_text(encoding="utf-8"))
    state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8")) \
        if (run_dir / "run_state.json").exists() else {}
    engine = json.loads((run_dir / "engine.json").read_text(encoding="utf-8")) \
        if (run_dir / "engine.json").exists() else {}
    records = list(latest_results(run_dir).values())
    ident = cond["identity"]

    groups: dict[str, dict] = {}
    for g in GROUP_TITLES:
        recs = [r for r in records if r["group"] == g]
        by_source = defaultdict(list)
        for r in recs:
            by_source[r["source"]].append(r)
        groups[g] = {"summary": _counts(recs),
                     "sources": {s: {**_counts(v), "scorer": v[0]["scorer"]} for s, v in sorted(by_source.items())}}

    totals = _counts(records)
    samples, temp = int(ident.get("samples", 1)), float(ident.get("temperature", 0.0))
    complete = (state.get("state") == "complete" and totals["errors"] == 0 and totals["void_model_mismatch"] == 0
                and totals["truncated"] == 0)
    ok = [r for r in records if r["status"] not in ERROR_STATUSES]
    usage = defaultdict(int)
    for r in ok:
        for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
            usage[k] += int((r.get("usage") or {}).get(k) or 0)
    return {
        "run_id": run_dir.name,
        "mode": "greedy" if samples == 1 and temp == 0.0 else f"multi-sample (N={samples}, T={temp})",
        "completeness": "complete" if complete else "incomplete",
        "run_state": state.get("state"),
        "expected_records": state.get("total"),
        "groups": groups,
        "counts": {k: totals[k] for k in ("records", "unparsed", "truncated", "pending_verifier", "void_model_mismatch", "errors")},
        "tokens_per_second": _stats([r["tps"] for r in ok if r.get("tps")]),
        "latency_s": _stats([r["latency_s"] for r in ok if r.get("latency_s")]),
        "tokens": dict(usage),
        "actual_models": sorted({r["model"] for r in records if r.get("model")}),
        "peak_memory": {"ram_mib": engine.get("peak_rss_mib"), "vram_mib": engine.get("peak_vram_mib")},
        "conditions": cond,
        "notes": [f"chinese-simpleqa: {APPROX_NOTE}"] if any(r["scorer"] == "simpleqa_approx" for r in records) else [],
    }


def _fmt_stats(st: dict | None) -> str:
    return "—" if not st else f"{st['mean']} ± {st['stdev']} (n={st['n']})"


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def to_markdown(rep: dict) -> str:
    L = [f"# 評測報表 / Evaluation report — `{rep['run_id']}`", "",
         f"- 模式 / Mode: **{rep['mode']}**",
         f"- 完整性 / Completeness: **{rep['completeness']}**（run state: {rep['run_state']}）",
         f"- 實際模型 / Actual models: {', '.join(rep['actual_models']) or '—'}", ""]
    if rep["completeness"] != "complete":
        L += ["> ⚠️ 不完整的執行不可作為權威基準（R17.6）。 / An incomplete run cannot be an authoritative baseline (R17.6).", ""]
    for g, title in GROUP_TITLES.items():
        grp = rep["groups"][g]
        L += [f"## {title}", "",
              "| 來源 / Source | 評分方式 / Scorer | 已評分 / Scored | 答對 / Correct | 正確率 / Accuracy | 無法解析 / Unparsed | 截斷 / Truncated | 待驗證器 / Pending | 作廢 / Void | 失敗 / Errors |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for s, c in grp["sources"].items():
            L.append(f"| {s} | {c['scorer']} | {c['scored']} | {c['correct']} | {_pct(c['accuracy'])} | {c['unparsed']} "
                     f"| {c['truncated']} | {c['pending_verifier']} | {c['void_model_mismatch']} | {c['errors']} |")
        c = grp["summary"]
        L += [f"| **小計 / Subtotal** | | {c['scored']} | {c['correct']} | **{_pct(c['accuracy'])}** | {c['unparsed']} "
              f"| {c['truncated']} | {c['pending_verifier']} | {c['void_model_mismatch']} | {c['errors']} |", ""]
    L += ["> 知識題與推理 / 工具題分開報告，不提供合併總分（R17.5）。 / Reported separately; no merged score (R17.5).", ""]
    tps, lat, mem = rep["tokens_per_second"], rep["latency_s"], rep["peak_memory"]
    L += ["## 效能 / Performance", "",
          f"- t/s: {_fmt_stats(tps)}",
          f"- 延遲 / Latency (s): {_fmt_stats(lat)}",
          f"- 峰值記憶體 / Peak memory: RAM {mem['ram_mib'] or '—'} MiB, VRAM {mem['vram_mib'] or '—'} MiB",
          f"- Token: {json.dumps(rep['tokens'])}", ""]
    if rep["notes"]:
        L += ["## 注意 / Notes", ""] + [f"- {n}" for n in rep["notes"]] + [""]
    L += ["## 量測條件 / Conditions (R17.1)", "", "```json",
          json.dumps(rep["conditions"], indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(L)


def write(run_dir: Path) -> dict:
    rep = build(run_dir)
    (run_dir / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "report.md").write_text(to_markdown(rep), encoding="utf-8")
    return rep

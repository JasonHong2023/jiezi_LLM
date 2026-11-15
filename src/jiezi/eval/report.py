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
from .verify_run import latest_verifications

GROUP_TITLES = {"knowledge": "知識題 / Knowledge", "reasoning": "推理與工具題 / Reasoning & tools"}
APPROX_NOTE = "近似比對，非官方評分 / approximate matching, not the official scorer"
# 驗證結果覆蓋原始狀態的題型與報表上的評分方式名稱 / item kinds whose status the verifications replace
OVERLAY = {"code": ("code", "evalplus (sandbox)"), "tool": ("tool", "acebench-normal"),
           "summary": ("summary_rules", "summary rules")}
KNOWN_DIFFERENCES = {
    "code": ["沙盒內以純 Python 實作 np.allclose / np.allclose reimplemented in pure Python inside the sandbox",
             "回答缺 import 時補上題目提示的 import 行 / prompt import lines are prepended when missing"],
    "tool": ["回答內容不執行：BinOp 只算純數字、Lambda 一律 unparsed（官方用 eval） / responses never executed: "
             "BinOp numbers only, Lambda unparsed (upstream uses eval)",
             "官方會中斷的情況記為 wrong / cases where upstream crashes count as wrong",
             "提示模板為本專案自寫，非 ACEBench 官方系統提示 / our own prompt template, not ACEBench's system prompt"],
    "simpleqa_judge": ["評審回覆無法解析時重試一次後不計分（官方當作未嘗試） / unparseable grades are retried once, "
                       "then unscored (upstream: not attempted)"],
    "summary_judge": ["評審提示為本專案自寫（非官方）；涵蓋度以清理後內文的第一段為準 / own judge prompt (unofficial); "
                      "coverage is against the first paragraph of the cleaned text"],
}


def _overlay(records: list[dict], verifs: dict) -> list[dict]:
    """以驗證結果取代程式、工具、摘要題的狀態與分數；原始紀錄不變。
    Replace status / score of code, tool and summary items with verification results; raw records untouched."""
    out = []
    for r in records:
        spec = OVERLAY.get(r["task"]) if r["scorer"] != "simpleqa_approx" else None
        v = verifs.get((r["key"], spec[0])) if spec else None
        if v and r["status"] not in ERROR_STATUSES and r["status"] not in ("void_model_mismatch", "truncated"):
            r = {**r, "status": v["status"], "score": v["score"], "scorer": spec[1]}
        out.append(r)
    return out


def _mean(xs):
    return round(statistics.fmean(xs), 4) if xs else None


def _verification_sections(records: list[dict], verifs: dict) -> dict:
    by_kind = defaultdict(list)
    for (_, kind), v in verifs.items():
        by_kind[kind].append(v)
    sec = {}
    if by_kind.get("code"):
        vs = by_kind["code"]
        sec["code"] = {"n": len(vs), "base_pass": sum(bool((v["details"] or {}).get("base_pass")) for v in vs),
                       "plus_pass": sum(v["score"] == 1 for v in vs),
                       "pending": sum(v["status"] == "pending_verifier" for v in vs),
                       "timeouts": sum(v["status"] == "timeout" for v in vs)}
    if by_kind.get("summary_rules"):
        vs = by_kind["summary_rules"]
        d = [v["details"] or {} for v in vs]
        sec["summary_rules"] = {"n": len(vs), "length_ok": sum(bool(x.get("length_ok")) for x in d),
                                "traditional_ok": sum(bool(x.get("traditional_ok")) for x in d),
                                "chars_mean": _mean([x["chars"] for x in d if "chars" in x])}
    if by_kind.get("summary_judge"):
        vs = by_kind["summary_judge"]
        judged = [v["details"] for v in vs if v["status"] == "judged"]
        sec["summary_judge"] = {"n": len(vs), "judged": len(judged),
                                "faithfulness_mean": _mean([d["faithfulness"] for d in judged]),
                                "coverage_mean": _mean([d["coverage"] for d in judged]),
                                "judge_unparsed": sum(v["status"] == "judge_unparsed" for v in vs),
                                "errors": sum(v["status"] in ERROR_STATUSES for v in vs),
                                "judge_models": sorted({v.get("judge_model") or "?" for v in vs})}
    if by_kind.get("simpleqa_judge"):
        from ..verify.judge import simpleqa_metrics
        vs = by_kind["simpleqa_judge"]
        graded = [v["status"] for v in vs if v["status"] in ("correct", "incorrect", "not_attempted")]
        sec["simpleqa_judge"] = {**simpleqa_metrics(graded), "graded": len(graded), "n_records": len(vs),
                                 "judge_unparsed": sum(v["status"] == "judge_unparsed" for v in vs),
                                 "errors": sum(v["status"] in ERROR_STATUSES for v in vs),
                                 "judge_models": sorted({v.get("judge_model") or "?" for v in vs})}
    return sec


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
    verifs = latest_verifications(run_dir)
    records = _overlay(list(latest_results(run_dir).values()), verifs)
    ident = cond["identity"]
    vcond_path = run_dir / "verify_conditions.json"
    vcond = json.loads(vcond_path.read_text(encoding="utf-8")) if vcond_path.exists() else None

    groups: dict[str, dict] = {}
    for g in GROUP_TITLES:
        recs = [r for r in records if r["group"] == g]
        by_source = defaultdict(list)
        for r in recs:
            by_source[r["source"]].append(r)
        # 摘要規則是格式檢查，不是答對率，不列入小計 / summary rules are format checks, not accuracy; excluded
        groups[g] = {"summary": _counts([r for r in recs if r["scorer"] != "summary rules"]),
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
        "verification": _verification_sections(records, verifs),
        "verify_conditions": vcond,
        "known_differences": {k: v for k, v in KNOWN_DIFFERENCES.items()
                              if any(kind == k for (_, kind) in verifs)},
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
    L += ["> 知識題與推理 / 工具題分開報告，不提供合併總分（R17.5）。摘要規則是格式檢查，不列入小計。",
          "> Reported separately; no merged score (R17.5). Summary rules are format checks and are excluded from subtotals.",
          ""]
    tps, lat, mem = rep["tokens_per_second"], rep["latency_s"], rep["peak_memory"]
    L += ["## 效能 / Performance", "",
          f"- t/s: {_fmt_stats(tps)}",
          f"- 延遲 / Latency (s): {_fmt_stats(lat)}",
          f"- 峰值記憶體 / Peak memory: RAM {mem['ram_mib'] or '—'} MiB, VRAM {mem['vram_mib'] or '—'} MiB",
          f"- Token: {json.dumps(rep['tokens'])}", ""]
    if rep["notes"]:
        L += ["## 注意 / Notes", ""] + [f"- {n}" for n in rep["notes"]] + [""]
    sec = rep.get("verification") or {}
    if sec:
        L += ["## 驗證器 / Verifiers", ""]
        if "code" in sec:
            c = sec["code"]
            L.append(f"- 程式 / Code（evalplus）：base 通過 {c['base_pass']}/{c['n']}，plus（計分）通過 "
                     f"{c['plus_pass']}/{c['n']}；逾時 {c['timeouts']}；待驗證 {c['pending']}")
        if "summary_rules" in sec:
            c = sec["summary_rules"]
            L.append(f"- 摘要規則 / Summary rules：字數合格 {c['length_ok']}/{c['n']}，無簡體字 "
                     f"{c['traditional_ok']}/{c['n']}，平均 {c['chars_mean']} 字")
        if "summary_judge" in sec:
            c = sec["summary_judge"]
            L.append(f"- 摘要評審 / Summary judge（{', '.join(c['judge_models'])}）：忠實度平均 "
                     f"{c['faithfulness_mean']}，涵蓋度平均 {c['coverage_mean']}（0–2）；已評 {c['judged']}/{c['n']}，"
                     f"無法解析 {c['judge_unparsed']}，失敗 {c['errors']}（與規則分開，不合併）")
        if "simpleqa_judge" in sec:
            c = sec["simpleqa_judge"]
            if c.get("n"):
                L.append(f"- Chinese SimpleQA 官方評審 / official judge（{', '.join(c['judge_models'])}）："
                         f"correct {_pct(c['correct'])}，not attempted {_pct(c['not_attempted'])}，"
                         f"accuracy given attempted {_pct(c['accuracy_given_attempted'])}，F1 {_pct(c['f1'])}"
                         f"（評定 {c['graded']} 題；無法解析 {c['judge_unparsed']}，失敗 {c['errors']}）")
        L.append("")
    if rep.get("known_differences"):
        L += ["## 與官方的已知差異 / Known differences from upstream", ""]
        for k, items in rep["known_differences"].items():
            L += [f"- {k}: {d}" for d in items]
        L.append("")
    if rep.get("verify_conditions"):
        L += ["## 驗證條件 / Verification conditions", "", "```json",
              json.dumps(rep["verify_conditions"], indent=2, ensure_ascii=False), "```", ""]
    L += ["## 量測條件 / Conditions (R17.1)", "", "```json",
          json.dumps(rep["conditions"], indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(L)


def write(run_dir: Path) -> dict:
    rep = build(run_dir)
    (run_dir / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (run_dir / "report.md").write_text(to_markdown(rep), encoding="utf-8")
    return rep

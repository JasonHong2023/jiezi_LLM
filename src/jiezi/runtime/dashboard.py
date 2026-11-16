"""量測儀表板：開發計畫 §1.3 成功指標（達成率、本機處理率、互動速度）＋ E0、自我評測、缺口摘要（開發計畫 §11）。
Dashboard: the dev-plan §1.3 metrics (achievement rate, local handling rate, speed) plus E0, self-test and gaps.

只讀既有的評測結果與軌跡，寫 `var/reports/dashboard-YYYY-MM-DD.md`。 / Read-only over results; writes one report."""

from __future__ import annotations

import collections
from datetime import date, datetime
from pathlib import Path

# 開發計畫 §1.3 Phase 4 目標（本機 ÷ 雲端）/ Phase 4 targets (local ÷ cloud)
TARGETS = {"tool": 0.8, "summary": 0.8, "code": 0.7, "qa": None}
TASK_NAME = {"tool": "工具呼叫", "code": "程式", "summary": "摘要（忠實度）", "qa": "知識"}
CLOUD_RUNS = ("20261116-r0-cloud-baseline-knowledge", "20261116-r0-cloud-baseline-reasoning")


def task_scores(run_dir: Path) -> dict:
    """各題型的正確率；摘要用評審的忠實度平均。 / Accuracy per task; summaries use mean judged faithfulness."""
    from ..eval import report
    from ..eval.runner import latest_results
    from ..eval.verify_run import latest_verifications
    if not run_dir.exists():
        return {}
    verifs = latest_verifications(run_dir)
    recs = report._overlay(list(latest_results(run_dir).values()), verifs)  # noqa: SLF001 - 同套件 / same package
    out = {}
    for task in ("tool", "code", "qa"):
        rs = [r for r in recs if r["task"] == task and r["score"] is not None and r["status"] != "pending_verifier"]
        if rs:
            out[task] = (sum(r["score"] for r in rs) / len(rs), len(rs))
    sj = (report.build(run_dir)["verification"].get("summary_judge") or {})
    if sj.get("faithfulness_mean") is not None:
        out["summary"] = (sj["faithfulness_mean"], sj.get("judged") or 0)
    return out


def merged(root: Path, run_ids) -> dict:
    out = {}
    for rid in run_ids:
        out.update(task_scores(root / "var" / "eval" / "runs" / rid))
    return out


def traffic(root: Path, days: int = 7) -> dict:
    """軌跡：jiezi 策略的本機處理率、請教次數、第 0 層速度。 / Local handling rate, consults, tier-0 speed."""
    from .gaps import load
    recs = [r for r in load(root, days) if r.get("policy") == "jiezi" and r.get("status") == "ok"]
    final = collections.Counter(str(r.get("final_tier")) for r in recs)
    local = sum(final[k] for k in ("0", "1", "memory"))
    tps = [t["tps"] for r in load(root, days) for t in r.get("tiers") or [] if t.get("tier") == 0 and t.get("tps")]
    return {"requests": len(recs), "local": local, "rate": local / len(recs) if recs else None,
            "escalated": len(recs) - local, "tps": sum(tps) / len(tps) if tps else None, "final": dict(final)}


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def build(root: Path) -> str:
    from ..eval import e0
    cloud = merged(root, CLOUD_RUNS)
    md = [f"# 芥子儀表板 / Dashboard（{date.today().isoformat()}）", "",
          f"- 產生時間：{datetime.now().astimezone().isoformat(timespec='seconds')}",
          f"- 雲端基準 / cloud baseline：{', '.join(CLOUD_RUNS)}", "", "## 雲端基準 / Cloud baseline", "",
          "| 題型 | 分數 | 題數 |", "|---|---|---|"]
    md += [f"| {TASK_NAME[t]} | {_pct(cloud[t][0])} | {cloud[t][1]} |" for t in TASK_NAME if t in cloud] or ["| — | — | — |"]
    # E0 各列的達成率 / per-row achievement
    try:
        rows, mhash = e0.load_matrix(root)
        state = e0.load_state(root, mhash)
    except Exception as exc:  # noqa: BLE001
        rows, state = [], {"rows": {}}
        md += ["", f"（E0 矩陣讀取失敗：{exc}）"]
    md += ["", "## 達成率（本機 ÷ 雲端）/ Achievement rate", "",
           "Phase 4 目標：工具呼叫 ≥ 80%、摘要 ≥ 80%、程式 ≥ 70%（開發計畫 §1.3）。✅ 達標 ⬜ 未達標。", "",
           "| 模型 | 狀態 | 擺放 | 工具 | 程式 | 摘要 | 知識 | t/s |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        st = state.get("rows", {}).get(r.name, {})
        if st.get("state") not in ("verified", "run_complete"):
            continue
        sc = task_scores(root / "var" / "eval" / "runs" / r.run_id)
        cells = []
        for t in ("tool", "code", "summary", "qa"):
            if t in sc and t in cloud and cloud[t][0]:
                ratio = sc[t][0] / cloud[t][0]
                mark = "" if TARGETS[t] is None else (" ✅" if ratio >= TARGETS[t] else " ⬜")
                cells.append(f"{_pct(ratio)}{mark}")
            else:
                cells.append(_pct(sc[t][0]) + "（無基準）" if t in sc else "—")
        try:
            tps = e0.row_metrics(root / "var" / "eval" / "runs" / r.run_id).get("tps")
        except Exception:  # noqa: BLE001
            tps = None
        speed = f"{tps:.1f}" if tps else "—"
        md.append(f"| {r.name} | {st.get('state')} | {st.get('placement') or '—'} | {' | '.join(cells)} | {speed} |")
    t = traffic(root)
    md += ["", "## 實際使用（最近 7 天，jiezi 策略）/ Real use", "",
           f"- 請求 {t['requests']}；本機處理 {t['local']}（{_pct(t['rate'])}，Phase 4 目標 ≥ 50%）；轉交 {t['escalated']}",
           f"- 第 0 層平均速度：{t['tps']:.1f} t/s（目標 ≥ 10）" if t["tps"] else "- 第 0 層平均速度：—",
           f"- 最後由誰回答：{t['final']}"]
    tests = sorted((root / "var" / "reports").glob("selftest-*.md"))
    if tests:
        head = tests[-1].read_text(encoding="utf-8").split("## 答錯的題目")[0].strip().splitlines()
        md += ["", f"## 最近一次自我評測 / Latest self-test（{tests[-1].name}）", ""] + head[2:]
    try:
        from .gaps import report as gaps_report
        _, g = gaps_report(root, 7)
        md += ["", "## 缺口（最近 7 天）/ Gaps", "", f"- 需要幫忙 {g['needed_help']} 筆：{g['by_kind']}",
               f"- 原因：{g['by_reason']}"]
    except Exception as exc:  # noqa: BLE001
        md += ["", f"（缺口報告失敗：{exc}）"]
    return "\n".join(md) + "\n"


def write(root: Path) -> Path:
    out = root / "var" / "reports" / f"dashboard-{date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(root), encoding="utf-8")
    return out


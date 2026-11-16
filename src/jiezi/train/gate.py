"""回歸關卡（規則 R20.1、R20.6；設計原則 P7）：訓練後的模型要過關才保留，不過關就回滾。
Regression gate (R20.1, R20.6; principle P7): a trained model is kept only if it passes; otherwise roll back.

R20.1：目標任務提升，且其他任務退步 ≤ 1 分、回答長度增幅 < 20%、延遲沒有變差。
R20.6：分數上升但靠更長的回答或更多轉交（雲端呼叫）得來的，不算進步。
R20.1: the target improves, others drop ≤ 1 point, answer length grows < 20%, latency does not worsen.
R20.6: gains that come from longer answers or more escalation do not count."""

from __future__ import annotations

from dataclasses import dataclass

MAX_DROP_POINTS = 1.0
MAX_LENGTH_GROWTH = 0.20
LATENCY_TOLERANCE = 0.05   # 量測雜訊容忍 5% / 5% measurement noise


@dataclass
class Snapshot:
    """一次評測的摘要：各任務分數（0–100）、平均回答長度、平均延遲、轉交比例。
    One evaluation summary: task scores (0–100), mean answer length, mean latency, escalation rate."""
    scores: dict[str, float]
    mean_length: float
    mean_latency_s: float
    escalation_rate: float = 0.0


def check(before: Snapshot, after: Snapshot, targets: list[str]) -> dict:
    reasons = []
    for t in targets:
        if after.scores.get(t, 0) <= before.scores.get(t, 0):
            reasons.append(f"目標任務 {t} 沒有提升（{before.scores.get(t)} → {after.scores.get(t)}）")
    for t, b in before.scores.items():
        if t in targets:
            continue
        a = after.scores.get(t)
        if a is None:
            reasons.append(f"缺少 {t} 的分數（可能還沒評審完），不能判定 / missing {t} score")
        elif b - a > MAX_DROP_POINTS:
            reasons.append(f"{t} 退步超過 {MAX_DROP_POINTS} 分（{b} → {a}）")
    if before.mean_length and (after.mean_length - before.mean_length) / before.mean_length >= MAX_LENGTH_GROWTH:
        reasons.append(f"回答長度增加 ≥ 20%（{before.mean_length:.0f} → {after.mean_length:.0f}）")
    if before.mean_latency_s and after.mean_latency_s > before.mean_latency_s * (1 + LATENCY_TOLERANCE):
        reasons.append(f"延遲變差（{before.mean_latency_s:.2f}s → {after.mean_latency_s:.2f}s）")
    if after.escalation_rate > before.escalation_rate + 0.01:  # R20.6
        reasons.append(f"轉交比例上升（{before.escalation_rate:.2%} → {after.escalation_rate:.2%}）")
    return {"pass": not reasons, "reasons": reasons,
            "deltas": {t: round(after.scores.get(t, 0) - b, 2) for t, b in before.scores.items()}}


def snapshot_from_run(run_dir) -> Snapshot:
    """由 E0 格式的評測目錄建立摘要。 / Build a snapshot from an E0-style run directory."""
    from ..eval.e0 import row_metrics
    from ..eval.runner import latest_results
    from ..runtime.dashboard import task_scores
    m = row_metrics(run_dir)
    scores = {t: round(v[0] * 100, 2) for t, v in task_scores(run_dir).items()}
    toks = [(r.get("usage") or {}).get("completion_tokens") for r in latest_results(run_dir).values()]
    toks = [t for t in toks if t]
    return Snapshot(scores=scores, mean_length=sum(toks) / len(toks) if toks else 0.0,
                    mean_latency_s=float(m.get("latency_s") or 0))

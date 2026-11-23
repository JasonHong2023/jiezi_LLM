"""統一觀測欄位：把各模組既有的紀錄轉成同一套欄位（add-agent-observability 第 1 階段）。

讀取端的檢視：既有寫進 var/ 的欄位名稱一律不改（狀態頁、統計、缺口報告、訓練資料匯出都依賴它們），
`normalize()` 回傳新的 dict、不改原紀錄。欄位命名參考 OpenTelemetry GenAI 語意慣例（2026 年仍為
Development 狀態），只借名字，不引入 SDK。

所有值域都取自實際軌跡（2026-11-23 主控掃描 var/trajectories 最近 6 天、2,534 筆）：
status ∈ ok／engine_unavailable／engine_error／client_disconnected／cancelled／consult_failed／
context_too_large；final_tier ∈ 0／1／2／3／memory／consult／convert／None；轉交原因見 ESCALATION_MAP。

Read-side unified fields: existing var/ field names are never renamed; normalize() returns a new dict."""

from __future__ import annotations

import re
from typing import Any

POLICIES = ("jiezi", "jiezi-local", "jiezi-cloud", "jiezi-ask-claude")
PROVIDERS = ("local", "claude", "cloud")
TERMINAL_STATES = ("completed", "failed", "aborted", "fail_closed")
FAIL_CLOSED_REASONS = ("budget_exceeded", "injection_detected", "verification_loop")
ESCALATION_REASONS = ("none", "verification_failed", "daily_cap_reached", "self_reported_unsure", "needs_web",
                      "local_unavailable", "context_too_large", "consult_failed", "consultation_timeout",
                      "cli_unavailable", "policy", "other")
# 既有的轉交原因 → 統一原因碼；不在表裡的 → other（原值放 escalation_reason_raw）
ESCALATION_MAP = {
    "verification_failed": "verification_failed",
    "unsupported_claims": "verification_failed",   # 依據檢查沒過 / grounding check failed
    "feedback": "verification_failed",             # 第 2 層：驗證沒過才請協助者回饋 / tier 2 after a failed check
    "daily_cap": "daily_cap_reached",
    "daily_cap_reached": "daily_cap_reached",
    "self_reported_unsure": "self_reported_unsure",
    "needs_web": "needs_web",
    "engine_unavailable": "local_unavailable",
    "local_unavailable": "local_unavailable",
    "context_too_large": "context_too_large",
    "consult_failed": "consult_failed",
    "consultation_timeout": "consultation_timeout",
    "cli_unavailable": "cli_unavailable",
    "policy": "policy",
    "local_only_policy": "policy",                 # jiezi-local 不允許轉交 / jiezi-local forbids escalation
}
# 軌跡 status → 終態 / trajectory status → terminal state
_STATUS = {"ok": "completed", "cancelled": "aborted", "client_disconnected": "aborted", "fail_closed": "fail_closed"}

# 保守的秘密樣式：只收格式明確的前綴，避免誤遮雜湊值、路徑或 os.environ 之類的正常文字
# Conservative secret patterns: explicit prefixes only, so hashes and ordinary text are left alone
_SECRETS = [re.compile(p) for p in (
    r"\bsk-[A-Za-z0-9_\-]{20,}",
    r"\bnvapi-[A-Za-z0-9_\-]{20,}",
    r"\bAIza[0-9A-Za-z_\-]{35}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{36,}\b",
    r"\bglpat-[A-Za-z0-9_\-]{20,}",
    r"\bxox[bpar]-[A-Za-z0-9\-]{10,}",
    r"\bA[KS]IA[0-9A-Z]{16}\b",
    r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
    "-----BEGIN [A-Z ]*" + "PRIVATE KEY-----[\\s\\S]*?-----END [A-Z ]*" + "PRIVATE KEY-----",
)]
REDACTED = "[REDACTED]"


def scrub_text(text: Any) -> Any:
    """遮掉格式明確的金鑰與私鑰區塊；非字串原樣回傳。 / Redact well-formed secrets; non-strings pass through."""
    if not isinstance(text, str):
        return text
    for rx in _SECRETS:
        text = rx.sub(REDACTED, text)
    return text


def scrub(value: Any) -> Any:
    """遞迴遮罩 dict／list 裡的字串（回傳新物件）。 / Recursively scrub strings; returns new objects."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return scrub_text(value)


def escalation_reason(raw: str | None) -> tuple[str, str | None]:
    """回傳 (統一原因碼, 原值)。沒有轉交 → ("none", None)。 / (unified code, raw value)."""
    if not raw:
        return "none", None
    return ESCALATION_MAP.get(raw, "other"), raw


def _tool_filter(tf: Any) -> dict | None:
    if not isinstance(tf, dict):
        return None
    out = {k: tf.get(k) for k in ("original", "kept", "stage", "names") if k in tf}
    if isinstance(tf.get("original"), int) and isinstance(tf.get("kept"), int):
        out["dropped"] = tf["original"] - tf["kept"]
    return out


def _terminal(agent_state: Any, status: Any, fail_closed: bool) -> str | None:
    """代理迴圈有自己的終態就用它（cancelled → aborted），否則依軌跡 status。 / Agent state first, then status."""
    if fail_closed:
        return "fail_closed"
    if agent_state in TERMINAL_STATES:
        return agent_state
    if agent_state == "cancelled":
        return "aborted"
    return _STATUS.get(status, "failed") if status else None


def _trajectory(rec: dict) -> dict:
    meta = rec.get("jiezi") if isinstance(rec.get("jiezi"), dict) else {}
    tiers = [t for t in rec.get("tiers") or [] if isinstance(t, dict)]
    escalated = next((t for t in reversed(tiers) if t.get("reason")), None)
    code, raw = escalation_reason((escalated or {}).get("reason") or meta.get("escalation"))
    status = rec.get("status")
    agent = rec.get("agent") if isinstance(rec.get("agent"), dict) else {}
    fail_closed = agent.get("terminal_state") == "fail_closed" or status == "fail_closed"
    last = tiers[-1] if tiers else {}
    out = {
        "trace_id": rec.get("id"),
        "timestamp": rec.get("at"),
        "policy": rec.get("policy"),
        "tier": rec.get("final_tier"),           # 保留原值：0–3 或 memory／consult／convert / kept as is
        "terminal_state": _terminal(agent.get("terminal_state"), status, fail_closed),
        "status_raw": status,
        "provider": last.get("provider") or ("local" if tiers else None),
        "model": meta.get("model") or last.get("model"),
        "latency_s": meta.get("latency_s"),
        "verification": meta.get("verification"),
        "escalation_reason": code,
        "escalation_reason_raw": raw,
        "fail_closed": fail_closed,
        "fail_closed_reason": agent.get("terminal_reason") if fail_closed else None,
        "training_use": rec.get("training_use"),
        "trust_level": (rec.get("trust") or {}).get("level") if isinstance(rec.get("trust"), dict) else None,
        "tool_filter": _tool_filter(rec.get("tool_filter")),
    }
    return {k: v for k, v in out.items() if v is not None}


def _audit(rec: dict) -> dict:
    out = {
        "timestamp": rec.get("at"),
        "trace_id": rec.get("trajectory_id"),
        "source": rec.get("source"),
        "step": rec.get("step"),
        "tool_name": rec.get("tool"),
        "tool_ok": rec.get("ok"),
        "allowed": rec.get("allowed"),
        "approval_id": rec.get("approval_id"),
        "outcome": rec.get("outcome"),
        "error": scrub_text(rec.get("error")),
        "path": rec.get("path"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _stats_reason(key: str) -> dict:
    """stats 的複合鍵 `claude:needs_web` → {provider, escalation_reason, escalation_reason_raw}。"""
    who, _, why = key.partition(":")
    code, raw = escalation_reason(why or None)
    return {"provider": who if who in PROVIDERS else "other", "escalation_reason": code, "escalation_reason_raw": raw}


def normalize(record: dict, kind: str) -> dict:
    """把一筆既有紀錄轉成統一欄位（新 dict，不改原紀錄；缺欄位不丟例外）。
    kind：trajectory（var/trajectories）、audit（var/audit）、stats_reason（stats 的複合鍵字串）。
    Map one existing record onto the unified fields without touching the original."""
    if kind == "stats_reason":
        return _stats_reason(str(record))
    if not isinstance(record, dict):
        return {}
    if kind == "trajectory":
        return _trajectory(record)
    if kind == "audit":
        return _audit(record)
    raise ValueError(f"unknown record kind {kind!r}; use trajectory, audit or stats_reason")


def summary(records: list[dict]) -> dict:
    """狀態頁用的彙整（A8 驗收：代理開關之外的成果、轉交、工具、信任）。只有計數，不含內容。
    Status-page summary over normalized trajectories: counts only, no content."""
    from collections import Counter
    states, reasons, closed, trust, providers = Counter(), Counter(), Counter(), Counter(), Counter()
    tf_n = tf_orig = tf_kept = agent_n = 0
    for rec in records:
        n = normalize(rec, "trajectory")
        states[n.get("terminal_state", "unknown")] += 1
        if n.get("escalation_reason", "none") != "none":
            reasons[n["escalation_reason"]] += 1
            providers[n.get("provider") or "unknown"] += 1
        if n.get("fail_closed"):
            closed[n.get("fail_closed_reason") or "unknown"] += 1
        if isinstance(rec.get("trust"), dict) and rec["trust"].get("reason"):
            trust[rec["trust"]["reason"]] += 1
        if isinstance(rec.get("agent"), dict) and rec["agent"].get("enabled", True) is not False:
            agent_n += 1
        tf = n.get("tool_filter")
        if tf and isinstance(tf.get("original"), int) and isinstance(tf.get("kept"), int):
            tf_n, tf_orig, tf_kept = tf_n + 1, tf_orig + tf["original"], tf_kept + tf["kept"]
    return {"requests": len(records), "terminal_states": dict(states), "escalation_reasons": dict(reasons),
            "escalated_to": dict(providers), "fail_closed": dict(closed), "agent_requests": agent_n,
            "untrainable_reasons": dict(trust),
            "tool_filter": {"requests": tf_n, "avg_original": round(tf_orig / tf_n, 1) if tf_n else None,
                            "avg_kept": round(tf_kept / tf_n, 1) if tf_n else None}}

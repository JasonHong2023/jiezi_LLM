"""轉交統計：每天轉給 Claude／雲端的次數與原因（使用者 2026-11-18：「轉給 Claude 的次數一定要降低」，要看得到有沒有降）。
Escalation counts per day and reason, so the user can see whether Claude escalations go down."""

from __future__ import annotations

from collections import Counter, defaultdict


def escalations(records: list[dict]) -> dict:
    """records：trajectory 紀錄（評測的不算）。回傳 {"days": [...新到舊], "total": {...}}。
    Trajectory records (evaluation runs excluded) → per-day and total counts."""
    days: dict[str, dict] = defaultdict(lambda: {"requests": 0, "claude": 0, "cloud": 0, "reasons": Counter()})
    for r in records:
        if r.get("eval") or not r.get("at"):
            continue
        d = days[r["at"][:10]]
        d["requests"] += 1
        done = [t for t in r.get("tiers") or [] if isinstance(t, dict) and t.get("provider") and not t.get("error")]
        if not done:
            continue
        who = done[-1]["provider"]
        if who not in ("claude", "cloud"):
            continue
        d[who] += 1
        reason = "policy" if r.get("policy") in ("jiezi-ask-claude", "jiezi-cloud") else \
            (done[-1].get("reason") or (r.get("jiezi") or {}).get("escalation") or "unknown")
        d["reasons"][f"{who}:{reason}"] += 1
    out = [{"day": k, **{x: v[x] for x in ("requests", "claude", "cloud")}, "reasons": dict(v["reasons"].most_common())}
           for k, v in sorted(days.items(), reverse=True)]
    total = {x: sum(d[x] for d in out) for x in ("requests", "claude", "cloud")}
    return {"days": out, "total": total}

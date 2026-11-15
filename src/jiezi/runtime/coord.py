"""夜間評測與 gateway 的協調（規格 supervisor：Night Evaluation Coordination；design D4）。
只用標準函式庫，評測端呼叫；任何錯誤都不會讓評測失敗，只記錄在條件裡。
Coordination between night evaluations and the gateway (spec supervisor; design D4). Standard library only,
called by evaluation; errors never fail the evaluation, they are only recorded in the conditions."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from pathlib import Path


def release_for_eval(root: Path, key: str | None, hold_until: datetime | None, timeout: float = 30) -> str:
    """回傳記錄用的狀態字串。 / Return a status string for the run conditions."""
    state_path = root / "var" / "runtime" / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "not_running"
    port = state.get("gateway_port")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            engine = json.loads(r.read()).get("engine") or {}
    except (OSError, ValueError):
        return "not_running"  # 狀態檔是舊的 / stale state file
    if engine.get("status") not in ("loaded", "loading") and not hold_until:
        return f"idle ({engine.get('status')})"
    if not key:
        return "loaded_but_no_key" if engine.get("status") == "loaded" else f"idle ({engine.get('status')})"
    body = json.dumps({"hold_until": hold_until.isoformat(timespec="minutes") if hold_until else None,
                       "reason": "night evaluation"}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/admin/unload", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.loads(r.read())
    except (OSError, ValueError) as exc:
        return f"unload_failed ({type(exc).__name__})"
    return "unloaded_for_eval" if res.get("was") in ("loaded", "loading") else f"held ({res.get('was')})"

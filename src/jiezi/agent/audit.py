"""稽核（R22.3）：每個工具呼叫一行 JSON，寫在 var/agent/audit/YYYY-MM-DD.jsonl；不存檔案內容。
Audit: one JSON line per tool call; file contents are never stored."""

from __future__ import annotations

import datetime as _dt
import json
import threading
from pathlib import Path

_LOCK = threading.Lock()


def audit_dir(root: Path) -> Path:
    return root / "var" / "agent" / "audit"


def write(root: Path, entry: dict) -> None:
    now = _dt.datetime.now().astimezone()
    row = {"at": now.isoformat(timespec="seconds"), **entry}
    row.pop("content", None)  # 保險：內容永遠不寫 / contents never written
    d = audit_dir(root)
    with _LOCK:
        d.mkdir(parents=True, exist_ok=True)
        with (d / f"{now:%Y-%m-%d}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def read(root: Path, days: int = 1, limit: int = 500) -> list[dict]:
    today = _dt.date.today()
    out: list[dict] = []
    for n in range(max(1, days) - 1, -1, -1):
        p = audit_dir(root) / f"{today - _dt.timedelta(days=n):%Y-%m-%d}.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    return out[-limit:]

"""軌跡記錄（規格 trajectory；add-gateway design D7）：只存本機，寫入失敗不影響回應。
Trajectory records (spec trajectory; design D7): local only; write failures never break a response."""

from __future__ import annotations

import json
import secrets
import time
from datetime import date, datetime, timedelta
from pathlib import Path


def new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)


class TrajectoryWriter:
    def __init__(self, directory: Path, enabled: bool = True, retention_days: int = 0, log=print):
        self.dir, self.enabled, self.retention_days, self.log = directory, enabled, retention_days, log
        self.last_error: str | None = None
        self._pruned_on: date | None = None

    def write(self, record: dict) -> bool:
        if not self.enabled:
            return False
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / f"{date.today().isoformat()}.jsonl"
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.last_error = None
            self._prune()
            return True
        except OSError as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            self.log(f"warning: trajectory not written ({self.last_error})")
            return False

    def _prune(self) -> None:
        if not self.retention_days or self._pruned_on == date.today():
            return
        self._pruned_on = date.today()
        cutoff = date.today() - timedelta(days=self.retention_days)
        for p in self.dir.glob("*.jsonl"):
            try:
                if date.fromisoformat(p.stem) < cutoff:
                    p.unlink()
            except ValueError:
                continue  # 不是日期檔名就不動 / not a dated file: leave it


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def elapsed(t0: float) -> float:
    return round(time.monotonic() - t0, 3)

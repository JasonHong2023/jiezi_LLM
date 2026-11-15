"""Herdr agent 狀態回報（規格 cli：Herdr Agent Reporting；add-cli design D5）。
Herdr agent state reporting (spec cli: Herdr Agent Reporting; design D5).

只在 Herdr pane 內（`HERDR_ENV=1` 且有 `HERDR_PANE_ID`）啟用；回報在背景執行，失敗只記錄。
Enabled only inside a Herdr pane; reports run in the background, failures are only remembered."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable

STATES = ("idle", "working", "blocked", "unknown")
RESUME = ["jiezi", "chat"]


class HerdrReporter:
    def __init__(self, environ: dict | None = None, popen: Callable = subprocess.Popen, which=shutil.which):
        env = os.environ if environ is None else environ
        self.pane = env.get("HERDR_PANE_ID") if env.get("HERDR_ENV") == "1" else None
        self.binary = which("herdr") if self.pane else None
        self.enabled = bool(self.pane and self.binary)
        self.popen = popen
        self.seq = 0
        self.last_error: str | None = None

    def report(self, state: str, message: str | None = None) -> bool:
        if not self.enabled or state not in STATES:
            return False
        self.seq += 1
        cmd = [self.binary, "pane", "report-agent", "--source", "jiezi", "--agent", "jiezi", "--state", state,
               "--seq", str(self.seq)]
        if message:
            cmd += ["--message", message[:120]]
        cmd += [self.pane, "--", *RESUME]
        try:
            self.popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError as exc:  # 回報失敗不影響對話 / never affects the chat
            self.last_error = str(exc)
            return False

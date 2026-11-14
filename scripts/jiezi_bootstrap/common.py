"""共用工具：專案根目錄、外部指令、錯誤型別。
Shared helpers: project root, external commands, error type."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class StepError(Exception):
    """步驟無法繼續；訊息會直接顯示給使用者。
    A step cannot continue; the message is shown to the user as-is."""


def project_root() -> Path:
    """專案根目錄：由本檔位置推得，可由 JIEZI_HOME 覆寫（design D5）。
    Project root: derived from this file, overridable by JIEZI_HOME (design D5)."""
    env = os.environ.get("JIEZI_HOME", "").strip()
    return Path(env).expanduser().resolve() if env else Path(__file__).resolve().parents[2]


def git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """在 cwd 執行 git；check=True 且失敗時拋出 StepError。
    Run git in cwd; raise StepError on failure when check=True."""
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace")
    if check and p.returncode != 0:
        raise StepError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p

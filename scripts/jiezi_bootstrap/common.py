"""共用工具：專案根目錄、外部指令、錯誤型別。
Shared helpers: project root, external commands, error type."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    from jiezi.config import load_env, project_root  # noqa: F401  (re-exported)
except ImportError:  # 直接執行 bootstrap 時 src/ 不在路徑上 / src/ not on the path when bootstrap runs directly
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from jiezi.config import load_env, project_root  # noqa: F401


class StepError(Exception):
    """步驟無法繼續；訊息會直接顯示給使用者。
    A step cannot continue; the message is shown to the user as-is."""


def git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """在 cwd 執行 git；check=True 且失敗時拋出 StepError。
    Run git in cwd; raise StepError on failure when check=True."""
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace")
    if check and p.returncode != 0:
        raise StepError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p


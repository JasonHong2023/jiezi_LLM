"""在背景啟動 / 停止 gateway，與任何終端機脫鉤（使用者 2026-11-15：關掉終端機後 gateway 跟著結束）。
Start / stop the gateway in the background, detached from any terminal (user report on 2026-11-15: closing the
terminal ended the gateway).

有使用者層 systemd 時用 `systemd-run --user`（記錄進 journal）；沒有時以分離的行程執行，記錄寫到
`var/runtime/gateway.log`（R21：依偵測結果選擇，不假設平台）。
With a user systemd, use `systemd-run --user` (logs in the journal); otherwise a detached process logging to
`var/runtime/gateway.log` (R21: chosen by detection, not assumed)."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

UNIT = "jiezi-gateway"


def health(port: int, timeout: float = 2) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def _user_systemd() -> bool:
    if not shutil.which("systemd-run") or not shutil.which("systemctl"):
        return False
    p = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True, text=True)
    return p.stdout.strip() in ("running", "degraded")


def start(root: Path, port: int, wait_s: float = 20, log=print) -> str:
    """已在執行就不重複啟動。回傳 already_running | started_systemd | started_process | failed。
    Never starts twice. Return already_running | started_systemd | started_process | failed."""
    if health(port):
        return "already_running"
    script = root / "scripts" / "jiezi"
    if _user_systemd():
        subprocess.run(["systemctl", "--user", "reset-failed", UNIT], capture_output=True)
        p = subprocess.run(["systemd-run", "--user", "--unit", UNIT, "--collect", "-p", "Nice=10",
                            f"--working-directory={root}", f"--setenv=PATH={os.environ.get('PATH', '')}",
                            f"--setenv=HOME={Path.home()}", str(script), "serve"], capture_output=True, text=True)
        how = "started_systemd" if p.returncode == 0 else None
        if how is None:
            log(f"systemd-run failed: {p.stderr.strip()[:200]}; falling back to a detached process")
    else:
        how = None
    if how is None:
        logf = root / "var" / "runtime" / "gateway.log"
        logf.parent.mkdir(parents=True, exist_ok=True)
        with logf.open("ab") as fh:
            subprocess.Popen([str(script), "serve"], cwd=root, stdin=subprocess.DEVNULL, stdout=fh,
                             stderr=subprocess.STDOUT, start_new_session=True)
        how = "started_process"
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if health(port):
            return how
        time.sleep(0.5)
    return "failed"


def stop(root: Path, port: int) -> str:
    if _user_systemd():
        p = subprocess.run(["systemctl", "--user", "is-active", UNIT], capture_output=True, text=True)
        if p.stdout.strip() == "active":
            subprocess.run(["systemctl", "--user", "stop", UNIT], capture_output=True)
            return "stopped_systemd"
    state = root / "var" / "runtime" / "state.json"
    try:
        pid = int(json.loads(state.read_text(encoding="utf-8"))["gateway_pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return "not_running"
    if not health(port):
        return "not_running"
    try:
        os.kill(pid, signal.SIGINT)  # 與 Ctrl-C 相同：關閉 gateway 與引擎 / same as Ctrl-C
    except OSError:
        return "not_running"
    return "stopped_process"


def logs(root: Path, lines: int = 50) -> int:
    if _user_systemd():
        return subprocess.run(["journalctl", "--user", "-u", UNIT, "-n", str(lines), "--no-pager"]).returncode
    f = root / "var" / "runtime" / "gateway.log"
    if f.exists():
        sys.stdout.write("".join(f.read_text(encoding="utf-8", errors="replace").splitlines(True)[-lines:]))
        return 0
    print("no gateway log yet")
    return 1

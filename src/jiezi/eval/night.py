"""夜間時段與一次性排程（規格 eval：Night Window、Night Scheduling；design D9；規則 R18.2a）。
Night window and one-shot scheduling (spec eval: Night Window, Night Scheduling; design D9; rule R18.2a).

不需要 sudo：有使用者層級 systemd 時用 `systemd-run --user`，否則用與終端機脫離的背景程序。
No sudo: `systemd-run --user` when user-level systemd exists, otherwise a terminal-detached background process."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import EvalError

DEFAULT_WINDOW = "00:00-07:00"  # 使用者 2026-11-14 決定（OQ1）/ user decision (OQ1)
START_DELAY = timedelta(minutes=5)
_WINDOW = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")


@dataclass(frozen=True)
class Window:
    start: int  # 一天中的分鐘數 / minutes since midnight
    end: int

    def contains(self, t: datetime) -> bool:
        m = t.hour * 60 + t.minute
        if self.start <= self.end:
            return self.start <= m < self.end
        return m >= self.start or m < self.end  # 跨午夜 / crosses midnight

    def next_start(self, t: datetime) -> datetime:
        """下一個時段開始的時間點（嚴格晚於 t）。 / The next window start strictly after t."""
        base = t.replace(hour=self.start // 60, minute=self.start % 60, second=0, microsecond=0)
        return base if base > t else base + timedelta(days=1)


def parse_window(text: str | None) -> Window:
    m = _WINDOW.match(text or DEFAULT_WINDOW)
    if not m:
        raise EvalError(f"JIEZI_NIGHT_WINDOW must look like HH:MM-HH:MM, got {text!r}")
    h1, m1, h2, m2 = map(int, m.groups())
    if not (0 <= h1 < 24 and 0 <= h2 <= 24 and m1 < 60 and m2 < 60):
        raise EvalError(f"invalid time in JIEZI_NIGHT_WINDOW: {text!r}")
    start, end = h1 * 60 + m1, min(h2 * 60 + m2, 24 * 60)
    if start == end:
        raise EvalError("JIEZI_NIGHT_WINDOW start and end must differ")
    return Window(start, end)


def planned_time(window: Window, t: datetime) -> datetime:
    """排程時間：已在時段內就 1 分鐘後開始，否則下一個時段開始後 5 分鐘。
    Planned start: one minute from now if already inside the window, else 5 minutes after the next start."""
    return t + timedelta(minutes=1) if window.contains(t) else window.next_start(t) + START_DELAY


def schedule_dir(root: Path) -> Path:
    return root / "var" / "eval" / "schedule"


def _launcher(root: Path, sid: str, jobs: list[list[str]], uv: str) -> str:
    """產生的啟動腳本（只存在 var/，不進版控）：依序執行各工作（前一個失敗也繼續），逐一記錄狀態；
    以絕對路徑呼叫 uv，因為使用者層級 systemd 沒有終端機的 PATH。
    The generated launcher (only in var/, never committed): runs jobs in order (continuing after a
    failure) and records each state; uv is called by absolute path because user systemd lacks the shell PATH."""
    d = schedule_dir(root)
    state = shlex.quote(str(d / f"{sid}.state"))
    log = shlex.quote(str(d / f"{sid}.log"))
    lines = [
        "#!/usr/bin/env bash",
        f"# jiezi eval 排程 {sid}（自動產生）/ jiezi eval schedule {sid} (generated)",
        f"export PATH={shlex.quote(str(Path(uv).parent))}:\"$PATH\"",
        f"cd {shlex.quote(str(root))}",
        "results=()",
    ]
    for i, args in enumerate(jobs, 1):
        cmd = " ".join(shlex.quote(a) for a in [str(root / "scripts" / "eval"), *args])
        lines += [
            f'echo "running job {i}/{len(jobs)} $(date -Iseconds)" > {state}',
            f'echo "=== job {i}/{len(jobs)}: {" ".join(args)} ($(date -Iseconds))" >> {log}',
            f"{cmd} >> {log} 2>&1",
            f'results+=("job{i}=$?")',
        ]
    lines += [
        'if printf "%s\\n" "${results[@]}" | grep -qv "=0$"; then status=failed; else status=done; fi',
        f'echo "$status ${{results[*]}} $(date -Iseconds)" > {state}',
    ]
    return "\n".join(lines) + "\n"


def has_user_systemd(run=subprocess.run) -> bool:
    if not shutil.which("systemd-run") or not shutil.which("systemctl"):
        return False
    try:
        p = run(["systemctl", "--user", "is-system-running"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.stdout.strip() in {"running", "degraded"}


def schedule(root: Path, jobs: list[list[str]], when: datetime, run=subprocess.run, popen=subprocess.Popen,
             use_systemd: bool | None = None, now: datetime | None = None) -> dict:
    """建立一次性排程（可含多個依序執行的工作）並寫出紀錄。
    Create a one-shot schedule (possibly several sequential jobs) and write its record."""
    if not jobs or not all(jobs):
        raise EvalError("a schedule needs at least one non-empty job")
    uv = shutil.which("uv")
    if not uv:
        raise EvalError("uv not found on PATH; cannot schedule")
    d = schedule_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    sid = when.strftime("%Y%m%d-%H%M") + "-" + os.urandom(3).hex()
    script = d / f"{sid}.sh"
    script.write_text(_launcher(root, sid, jobs, uv), encoding="utf-8")
    script.chmod(0o755)
    (d / f"{sid}.state").write_text(f"waiting {when.isoformat(timespec='minutes')}\n")
    use_systemd = has_user_systemd(run) if use_systemd is None else use_systemd
    if use_systemd:
        unit = f"jiezi-eval-{sid}"
        p = run(["systemd-run", "--user", "--collect", f"--unit={unit}",
                 f"--on-calendar={when.strftime('%Y-%m-%d %H:%M:%S')}", "--timer-property=AccuracySec=1min",
                 "/bin/bash", str(script)], capture_output=True, text=True)
        if p.returncode != 0:
            raise EvalError(f"systemd-run failed: {p.stderr.strip()}")
        method = {"method": "systemd-user", "unit": unit}
    else:
        delay = max(0, int((when - (now or datetime.now())).total_seconds()))
        proc = popen(["/bin/bash", "-c", f"sleep {delay}; exec /bin/bash {shlex.quote(str(script))}"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
        method = {"method": "detached-process", "pid": proc.pid}
    record = {"id": sid, "when": when.isoformat(timespec="minutes"), "jobs": jobs, **method}
    (d / f"{sid}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return record


def cancel(root: Path, sid: str, run=subprocess.run, kill=os.kill) -> str:
    """取消尚未開始的排程。 / Cancel a schedule that has not started."""
    d = schedule_dir(root)
    rec_path, state_path = d / f"{sid}.json", d / f"{sid}.state"
    if not rec_path.exists():
        raise EvalError(f"no schedule {sid}")
    state = state_path.read_text().strip() if state_path.exists() else ""
    if not state.startswith("waiting"):
        raise EvalError(f"schedule {sid} is not waiting ({state or 'unknown'}); not cancelling")
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if rec.get("method") == "systemd-user":
        p = run(["systemctl", "--user", "stop", f"{rec['unit']}.timer"], capture_output=True, text=True)
        if p.returncode != 0:
            raise EvalError(f"systemctl stop failed: {p.stderr.strip()}")
    else:
        try:
            kill(-int(rec["pid"]), 15)  # 背景程序以新 session 啟動 / started in its own session
        except ProcessLookupError:
            pass
    state_path.write_text(f"cancelled {datetime.now().isoformat(timespec='seconds')}\n")
    return f"cancelled {sid}"


def list_schedules(root: Path) -> list[dict]:
    out = []
    for f in sorted(schedule_dir(root).glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        st = f.with_suffix(".state")
        rec["state"] = st.read_text().strip() if st.exists() else "unknown"
        out.append(rec)
    return out


def linger_note(run=subprocess.run) -> str | None:
    """提醒：沒有 linger 時，關閉所有終端機後使用者層級 systemd 可能停止，排程就不會執行。
    Reminder: without linger, user-level systemd may stop once every terminal closes, and the timer won't fire."""
    user = os.environ.get("USER") or ""
    try:
        p = run(["loginctl", "show-user", user, "-p", "Linger", "--value"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.stdout.strip() == "no":
        return ("注意：未啟用 linger，請保持至少一個終端機開著（WSL 也不要關），排程才會執行 / "
                "Note: linger is off; keep a terminal open (and WSL running) so the schedule fires")
    return None

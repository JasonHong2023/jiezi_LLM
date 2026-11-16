"""程式執行沙盒（規格 verifiers：Sandboxed Code Execution；add-verifiers design D2）。
Code-execution sandbox (spec verifiers: Sandboxed Code Execution; add-verifiers design D2).

- bubblewrap（bootstrap 建置於 var/tools/bubblewrap，使用者 2026-11-15 決定）：無網路、系統唯讀、不掛家目錄與專案目錄。
  bubblewrap (built by bootstrap into var/tools/bubblewrap, user decision 2026-11-15): no network, read-only
  system, no home or project mounts.
- 上限：有 `systemd-run --user --scope` 就用 cgroup（MemoryMax、TasksMax），否則用 RLIMIT_AS；
  一律加上 RLIMIT_FSIZE（輸出檔大小）、RLIMIT_CPU、實際時間上限，並綁定預算核心（R18.2）。
  Limits: cgroups via `systemd-run --user --scope` when available, else RLIMIT_AS; always RLIMIT_FSIZE,
  RLIMIT_CPU, a wall-clock limit, and budget cores (R18.2).
- 沙盒不可用時**不提供**沙盒外執行的後備路徑。 / There is **no** unsandboxed fallback."""

from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..budget import budget_prefix

VERSION = "bwrap-sandbox@1"
PY_MOUNT = "/opt/py"
WORK = "/work"
SELF_TEST = r"""
import os, socket, sys
bad = []
for port in [int(p) for p in sys.argv[1:2] if p] + [80]:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
        bad.append(f"connected to 127.0.0.1:{port}")
    except OSError:
        pass
for path in sys.argv[2:]:
    try:
        with open(os.path.join(path, ".jiezi-sandbox-probe"), "w") as fh:
            fh.write("x")
        bad.append(f"wrote into {path}")
    except OSError:
        pass
    if os.path.exists(path) and os.listdir(path):
        bad.append(f"can list {path}")
print("BAD: " + "; ".join(bad) if bad else "OK")
"""


@dataclass
class Limits:
    wall_s: float = 10.0
    memory_mib: int = 1024
    tasks: int = 64
    output_mib: int = 16
    read_bytes: int = 1 << 20


@dataclass
class Result:
    returncode: int
    stdout: str
    stderr: str
    limit: str | None = None  # None | "timeout" | "resource_limit"
    duration_s: float = 0.0
    files: dict = field(default_factory=dict)


class SandboxUnavailable(Exception):
    pass


class Sandbox:
    def __init__(self, root: Path, facts: dict | None = None, bwrap: Path | None = None,
                 python_prefix: str | None = None, use_cgroup: bool | None = None, probe_port: int | None = None):
        self.root = root = Path(root).resolve()
        self.bwrap = bwrap or root / "var" / "tools" / "bubblewrap" / "bin" / "bwrap"
        self.python_prefix = Path(python_prefix or sys.base_prefix).resolve()
        self.prefix, self.threads, self.notes = budget_prefix(facts or {})
        self.use_cgroup = (shutil.which("systemd-run") is not None and _user_systemd()) \
            if use_cgroup is None else use_cgroup
        self.probe_port = probe_port
        self._checked: tuple[bool, str] | None = None

    # ── 狀態 / State ──
    def describe(self) -> dict:
        return {"version": VERSION, "bwrap": str(self.bwrap), "python_prefix": str(self.python_prefix),
                "limits_via": "cgroup (systemd-run --user --scope)" if self.use_cgroup else "rlimit",
                "budget_notes": self.notes, "network": "none (--unshare-all)",
                "mounts": ["/usr ro", f"{PY_MOUNT} ro (python)", f"{WORK} rw (per-run temp)", "/tmp tmpfs"]}

    def available(self) -> tuple[bool, str]:
        """bwrap 存在、不是 setuid、自我檢查通過。結果快取。 / bwrap present, not setuid, self-test passes. Cached."""
        if self._checked is None:
            self._checked = self._check()
        return self._checked

    def _check(self) -> tuple[bool, str]:
        if not self.bwrap.is_file():
            return False, f"bubblewrap not found at {self.bwrap} (run scripts/bootstrap)"
        if self.bwrap.stat().st_mode & 0o6000:
            return False, f"{self.bwrap} is setuid/setgid; refusing to use it"
        paths = [str(Path.home()), str(self.root)]
        try:
            r = self._run({"probe.py": SELF_TEST}, ["probe.py", str(self.probe_port or ""), *paths], Limits(wall_s=20))
        except OSError as exc:
            return False, f"cannot start bubblewrap: {exc}"
        out = r.stdout.strip()
        if r.returncode != 0 or out != "OK":
            return False, f"sandbox self-test failed: {out or r.stderr.strip()[:300]}"
        return True, "ok"

    # ── 執行 / Execution ──
    def run_python(self, files: dict[str, str | bytes], argv: list[str], limits: Limits | None = None,
                   stdin: bytes = b"", collect: list[str] | None = None, extra_ro: list[str] | None = None) -> Result:
        """在沙盒內執行；collect 列出結束後要取回的 /work 檔案（大小受 output_mib 限制，以位元組回傳）。
        Run in the sandbox; `collect` names /work files to return as bytes afterwards (bounded by output_mib)."""
        ok, reason = self.available()
        if not ok:
            raise SandboxUnavailable(reason)
        # extra_ro：額外唯讀掛入的系統目錄（例如 /etc/libreoffice）；只接受 /etc 或 /usr 之下、實際存在的目錄
        # extra_ro: more read-only system directories (e.g. /etc/libreoffice); only existing ones under /etc or /usr
        ro = [d for d in extra_ro or [] if d.startswith(("/etc/", "/usr/")) and ".." not in d and Path(d).is_dir()]
        return self._run(files, argv, limits or Limits(), stdin, collect or [], ro)

    def _bwrap_args(self, work: Path, extra_ro: list[str] | None = None) -> list[str]:
        args = [str(self.bwrap), "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
                "--ro-bind", "/usr", "/usr"]
        for name in ("lib", "lib64", "bin", "sbin"):
            if Path("/" + name).is_symlink():
                args += ["--symlink", os.readlink("/" + name), "/" + name]
            elif Path("/" + name).is_dir():
                args += ["--ro-bind", "/" + name, "/" + name]
        for d in extra_ro or []:
            args += ["--ro-bind", d, d]
        py = self.python_prefix
        if not str(py).startswith("/usr/"):
            args += ["--ro-bind", str(py), PY_MOUNT]
            exe = f"{PY_MOUNT}/bin/python3"
        else:
            exe = str(py / "bin" / "python3")
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--bind", str(work), WORK,
                 "--chdir", WORK, "--remount-ro", "/",
                 "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "HOME", "/tmp",
                 "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "PYTHONHASHSEED", "0",
                 exe, "-I", "-S"]
        return args

    def _run(self, files: dict, argv: list[str], limits: Limits, stdin: bytes = b"",
             collect: list[str] | None = None, extra_ro: list[str] | None = None) -> Result:
        tmp = Path(tempfile.mkdtemp(prefix="jiezi-sbx-"))
        work, io_dir = tmp / "work", tmp / "io"
        work.mkdir()
        io_dir.mkdir()
        try:
            for name, content in files.items():
                p = work / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
            cmd = list(self.prefix)
            if self.use_cgroup:
                cmd += ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                        "-p", f"MemoryMax={limits.memory_mib}M", "-p", "MemorySwapMax=0",
                        "-p", f"TasksMax={limits.tasks}"]
            cmd += self._bwrap_args(work, extra_ro) + argv
            out_p, err_p = io_dir / "stdout", io_dir / "stderr"
            t0 = time.monotonic()
            with out_p.open("wb") as out, err_p.open("wb") as err:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err,
                                        start_new_session=True,
                                        preexec_fn=lambda: _limit(limits, rlimit_as=not self.use_cgroup))
                limit = None
                try:
                    proc.communicate(stdin, timeout=limits.wall_s)
                except subprocess.TimeoutExpired:
                    limit = "timeout"
                    _killpg(proc)
                    proc.wait()
            rc = proc.returncode
            if limit is None and rc in (-signal.SIGKILL, -signal.SIGTERM, -signal.SIGXFSZ, -signal.SIGXCPU,
                                        128 + signal.SIGKILL, 128 + signal.SIGTERM):
                limit = "resource_limit"
            got = {}
            for name in collect or []:
                p = (work / name)
                # 不跟隨沙盒內建立的符號連結 / never follow symlinks created inside the sandbox
                if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(work.resolve()) \
                        and p.stat().st_size <= limits.output_mib << 20:
                    got[name] = p.read_bytes()
            return Result(rc, _read(out_p, limits.read_bytes), _read(err_p, limits.read_bytes), limit,
                          round(time.monotonic() - t0, 3), got)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _user_systemd() -> bool:
    try:
        return subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True,
                              timeout=5).stdout.strip() in (b"running", b"degraded")
    except (OSError, subprocess.TimeoutExpired):
        return False


def _limit(limits: Limits, rlimit_as: bool) -> None:
    out = limits.output_mib << 20
    resource.setrlimit(resource.RLIMIT_FSIZE, (out, out))
    cpu = int(limits.wall_s * 2) + 1
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if rlimit_as:
        mem = limits.memory_mib << 20
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))


def _killpg(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()


def _read(path: Path, n: int) -> str:
    with path.open("rb") as fh:
        return fh.read(n).decode("utf-8", errors="replace")

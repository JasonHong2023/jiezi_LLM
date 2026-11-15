"""從鎖定的上游原始碼建置 bubblewrap 到 var/tools/bubblewrap（add-verifiers design D2、OQ1）。
Build bubblewrap from the pinned upstream source into var/tools/bubblewrap (add-verifiers design D2, OQ1).

- 使用者 2026-11-15 決定：不用 Ubuntu 24.04 套件（0.9.0-1ubuntu0.3 撤回了 CVE-2026-87766 的修正），
  改建上游 v0.13.1（已修正 GHSA-pxhw-h44j-8pfx / CVE-2026-87766）。
  User decision 2026-11-15: not the Ubuntu 24.04 package (0.9.0-1ubuntu0.3 reverted the CVE-2026-87766 fix);
  build upstream v0.13.1 instead (fixed).
- 不設 setuid（0.13 起 setuid 的執行檔會拒絕執行）；不安裝到系統目錄，不需要 sudo。
  Never setuid (0.13+ refuses to run setuid); nothing goes to system directories, no sudo.
- 系統前置：libcap 開發檔與 pkg-config（`scripts/setup/common/install_sandbox_deps`）。
  System prerequisites: libcap headers and pkg-config (`scripts/setup/common/install_sandbox_deps`)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import source
from .common import StepError

NAME = "bubblewrap"
MESON_OPTIONS = ("-Dman=disabled", "-Dselinux=disabled", "-Dtests=false",
                 "-Dbash_completion=disabled", "-Dzsh_completion=disabled")
DEPS_HINT = "scripts/setup/common/install_sandbox_deps"


def install_dir(root: Path) -> Path:
    return root / "var" / "tools" / NAME


def binary(root: Path) -> Path:
    return install_dir(root) / "bin" / "bwrap"


def record_path(root: Path) -> Path:
    return root / "var" / "tools" / f"{NAME}.json"


def has_build_deps(run=subprocess.run) -> str | None:
    """回傳缺少的前置條件說明；齊全時回傳 None。 / Describe what is missing, or None when complete."""
    if not shutil.which("pkg-config"):
        return "pkg-config"
    if run(["pkg-config", "--exists", "libcap"]).returncode != 0:
        return "libcap headers (libcap-dev)"
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current(root: Path, commit: str) -> dict | None:
    """已建置且與鎖定 commit 相符、執行檔雜湊未變就回傳紀錄。 / The record if built at the pin and unchanged."""
    try:
        rec = json.loads(record_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    b = binary(root)
    if rec.get("commit") != commit or not b.is_file() or _sha256(b) != rec.get("binary_sha256"):
        return None
    if b.stat().st_mode & 0o6000:
        raise StepError(f"{b} is setuid/setgid; refusing to use it (remove the file and re-run)")
    return rec


def _tool(root: Path, name: str) -> str:
    venv = root / ".venv" / "bin" / name
    found = str(venv) if venv.exists() else shutil.which(name)
    if not found:
        raise StepError(f"{name} not found; run `uv sync` (it is in the dev dependency group)")
    return found


def build(root: Path, prefix: list[str] | None = None, run=subprocess.run, log=print) -> tuple[str, dict]:
    """取得原始碼、建置並安裝；回傳 ('present' | 'built', 紀錄)。
    Fetch, build and install; return ('present' | 'built', record)."""
    pin = source.read_pin(root / "openspec" / "specs" / "stack.md", name=NAME)
    rec = current(root, pin.commit)
    if rec:
        return "present", rec
    missing = has_build_deps(run)
    if missing:
        raise StepError(f"missing {missing}; install with {DEPS_HINT} (needs sudo, ask the user first)")
    src = root / "vendor" / NAME
    source.fetch(src, pin, log=log)
    out = root / "build-bwrap"
    shutil.rmtree(out, ignore_errors=True)
    shutil.rmtree(install_dir(root), ignore_errors=True)
    prefix = list(prefix or [])
    log_path = root / "var" / "tools" / f"{NAME}-build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    meson, ninja = _tool(root, "meson"), _tool(root, "ninja")
    env_path = str(Path(ninja).parent)
    cmds = [
        [*prefix, meson, "setup", str(out), str(src), f"--prefix={install_dir(root)}", "--buildtype=release",
         *MESON_OPTIONS],
        [*prefix, ninja, "-C", str(out), "install"],
    ]
    env = {**os.environ, "PATH": env_path + os.pathsep + os.environ.get("PATH", "")}
    with log_path.open("w", encoding="utf-8") as fh:
        for cmd in cmds:
            fh.write("$ " + " ".join(cmd) + "\n")
            fh.flush()
            p = run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env)
            if p.returncode != 0:
                raise StepError(f"bubblewrap build failed at `{cmd[len(prefix)]} {cmd[len(prefix) + 1]}` "
                                f"(log: {log_path.relative_to(root)})")
    b = binary(root)
    if not b.is_file():
        raise StepError(f"bubblewrap build finished but {b} is missing")
    if b.stat().st_mode & 0o6000:
        raise StepError(f"{b} is setuid/setgid; refusing to use it")
    version = run([str(b), "--version"], capture_output=True, text=True).stdout.strip()
    rec = {"name": NAME, "commit": pin.commit, "url": pin.url, "version": version,
           "binary": str(b.relative_to(root)), "binary_sha256": _sha256(b),
           "meson_options": list(MESON_OPTIONS),
           "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    record_path(root).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return "built", rec

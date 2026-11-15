"""取得鎖定版本的 llama.cpp 原始碼（規格 build / Pinned Source、No Vendor Modification；design D3）。
Fetch llama.cpp at the pinned commit (spec build / Pinned Source, No Vendor Modification; design D3).

鎖定值只有一個來源：openspec/specs/stack.md。
The pinned values have exactly one source: openspec/specs/stack.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .common import StepError, git, project_root

def _row(name: str) -> re.Pattern:
    return re.compile(r"^\|[^|]*\|\s*" + re.escape(name) + r"\b[^|]*\|[^|]*`([0-9a-f]{40})`[^|]*\|\s*`(https://[^`]+)`",
                      re.M)


@dataclass(frozen=True)
class Pin:
    commit: str
    url: str


def read_pin(stack_md: Path | None = None, name: str = "llama.cpp") -> Pin:
    """從 stack.md 的技術棧表格讀出某個上游原始碼（預設 llama.cpp）的 commit 與來源網址。
    Read an upstream source's (default llama.cpp) commit and source URL from the stack.md table."""
    path = stack_md or project_root() / "openspec" / "specs" / "stack.md"
    m = _row(name).search(path.read_text(encoding="utf-8"))
    if not m:
        raise StepError(f"{path}: no {name} row with a 40-hex commit and a source URL")
    return Pin(commit=m.group(1), url=m.group(2))


def _dirty_files(repo: Path) -> list[str]:
    out = git(["status", "--porcelain", "--untracked-files=no"], repo).stdout
    return [line[3:] for line in out.splitlines() if line.strip()]


def verify(repo: Path, pin: Pin) -> None:
    """確認 HEAD 等於鎖定 commit 且沒有未提交改動；否則停止，不自動覆蓋。
    Require HEAD == pin and a clean tree; otherwise stop without overwriting."""
    head = git(["rev-parse", "HEAD"], repo).stdout.strip()
    if head != pin.commit:
        raise StepError(
            f"{repo}: HEAD is {head}, but stack.md pins {pin.commit}. "
            "Not overwriting: changing the commit is a major change (rules R4, R17.3). "
            "Either update stack.md through an R4 discussion or remove the directory."
        )
    dirty = _dirty_files(repo)
    if dirty:
        raise StepError(
            f"{repo}: uncommitted changes (rule R6.2 forbids editing vendor sources; "
            "use patches/*.patch instead):\n  " + "\n  ".join(dirty)
        )


def fetch(dest: Path, pin: Pin, log=print) -> str:
    """取得原始碼到 dest；回傳 'present'（已存在且有效）或 'fetched'。
    Fetch the sources into dest; return 'present' (already valid) or 'fetched'."""
    if dest.exists():
        if not (dest / ".git").exists():
            raise StepError(f"{dest} exists but is not a git checkout; remove it and re-run")
        verify(dest, pin)
        return "present"

    dest.mkdir(parents=True)
    try:
        git(["init", "-q"], dest)
        git(["remote", "add", "origin", pin.url], dest)
        shallow = git(["fetch", "-q", "--depth", "1", "origin", pin.commit], dest, check=False)
        if shallow.returncode == 0:
            git(["checkout", "-q", "--detach", "FETCH_HEAD"], dest)
        else:
            log(f"shallow fetch by hash failed ({shallow.stderr.strip()}); falling back to a full fetch")
            git(["fetch", "-q", "origin"], dest)
            git(["checkout", "-q", "--detach", pin.commit], dest)
        verify(dest, pin)
    except BaseException:
        # 半成品不留下，下次重跑才能從乾淨狀態開始 / leave no half-fetched tree behind
        import shutil

        shutil.rmtree(dest, ignore_errors=True)
        raise
    return "fetched"


def default_dest() -> Path:
    return project_root() / "vendor" / "llama.cpp"

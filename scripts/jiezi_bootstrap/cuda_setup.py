"""CUDA toolkit 安裝步驟（規格 bootstrap / Platform Setup Selection；design D8）。
CUDA toolkit installation step (spec bootstrap / Platform Setup Selection; design D8).

- 版本：驅動支援上限（nvidia-smi 標頭）以下、NVIDIA 套件庫中最新的 toolkit。
  Version: the newest toolkit in NVIDIA's repository not above the driver's ceiling (nvidia-smi header).
- 套件庫：WSL2 用 wsl-ubuntu；原生 Ubuntu 用 ubuntu<VERSION_ID>（執行時由 /etc/os-release 取得）。
  Repository: wsl-ubuntu on WSL2; ubuntu<VERSION_ID> on native Ubuntu (read from /etc/os-release at run time).
- 只安裝 toolkit，**絕不安裝驅動**。 / Installs the toolkit only, **never a driver**.

用法 / Usage: python -m jiezi_bootstrap.cuda_setup --platform {wsl2,ubuntu}"""

from __future__ import annotations

import argparse
import platform as _platform
import re
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import sudo_window
from .common import StepError, project_root

REPO_BASE = "https://developer.download.nvidia.com/compute/cuda/repos"
ARCH_DIRS = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "sbsa", "arm64": "sbsa"}

_SMI = re.compile(r"CUDA (?:UMD )?Version:\s*(\d+)\.(\d+)")
_TOOLKIT = re.compile(r"cuda-toolkit-(\d+)-(\d+)_[^'\"<>\s]+\.deb")
_KEYRING = re.compile(r"cuda-keyring_(\d+)\.(\d+)-(\d+)_all\.deb")


def driver_ceiling(nvidia_smi_header: str) -> tuple[int, int] | None:
    """解析驅動支援的最高 CUDA 版本。 / Parse the highest CUDA version the driver supports."""
    m = _SMI.search(nvidia_smi_header)
    return (int(m.group(1)), int(m.group(2))) if m else None


def read_os_release(path: Path = Path("/etc/os-release")) -> dict:
    out = {}
    try:
        for line in path.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k] = v.strip().strip('"')
    except OSError:
        pass
    return out


def repo_url(platform: str, os_release: dict, machine: str) -> str:
    arch = ARCH_DIRS.get(machine.lower())
    if not arch:
        raise StepError(f"unsupported CPU architecture for NVIDIA's repository: {machine}")
    if platform == "wsl2":
        if arch != "x86_64":
            raise StepError("NVIDIA's wsl-ubuntu repository only provides x86_64")
        name = "wsl-ubuntu"
    elif platform == "ubuntu":
        if os_release.get("ID") != "ubuntu" or not os_release.get("VERSION_ID"):
            raise StepError(f"not Ubuntu (ID={os_release.get('ID')!r}); install the CUDA toolkit manually")
        name = "ubuntu" + os_release["VERSION_ID"].replace(".", "")
    else:
        raise StepError(f"no CUDA setup for platform {platform!r}")
    return f"{REPO_BASE}/{name}/{arch}/"


def pick_toolkit(index_html: str, ceiling: tuple[int, int]) -> str | None:
    """從套件庫索引挑「不超過上限的最新版」，回傳例如 '13-3'。
    Pick the newest toolkit not above the ceiling from the index, e.g. '13-3'."""
    versions = {(int(a), int(b)) for a, b in _TOOLKIT.findall(index_html)}
    ok = sorted(v for v in versions if v <= ceiling)
    return f"{ok[-1][0]}-{ok[-1][1]}" if ok else None


def pick_keyring(index_html: str) -> str | None:
    found = sorted({tuple(int(x) for x in m) for m in _KEYRING.findall(index_html)})
    return "cuda-keyring_{}.{}-{}_all.deb".format(*found[-1]) if found else None


def render_script(keyring_file: Path, toolkit: str) -> str:
    """產生安裝腳本（在 sudo 視窗內執行）；金鑰包已由 Python 下載，不依賴 curl / wget。
    Render the install script (runs in the sudo window); the keyring was downloaded by Python,
    so neither curl nor wget is needed."""
    dotted = toolkit.replace("-", ".")
    kf = shlex.quote(str(keyring_file))
    return f"""#!/usr/bin/env bash
set -euo pipefail
echo "[1/3] 安裝套件庫金鑰 / Installing the repository keyring"
sudo dpkg -i {kf}
echo "[2/3] 更新套件清單 / Updating package lists"
sudo apt-get update
echo "[3/3] 安裝 cuda-toolkit-{toolkit}（不含驅動 / no driver）"
sudo apt-get install -y cuda-toolkit-{toolkit}
/usr/local/cuda-{dotted}/bin/nvcc --version
"""


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "jiezi-bootstrap"})
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as fh:
        while chunk := r.read(1 << 16):
            fh.write(chunk)


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "jiezi-bootstrap"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def prepare(platform: str, smi_header: str, os_release: dict, machine: str, fetch=_fetch) -> dict:
    """決定要安裝的內容（不執行）。 / Decide what to install (runs nothing)."""
    ceiling = driver_ceiling(smi_header)
    if not ceiling:
        raise StepError("cannot read the driver's CUDA version from nvidia-smi; is an NVIDIA driver installed?")
    repo = repo_url(platform, os_release, machine)
    try:
        index = fetch(repo)
    except Exception as exc:  # noqa: BLE001
        raise StepError(f"cannot read NVIDIA's repository index {repo}: {exc}") from exc
    toolkit, keyring = pick_toolkit(index, ceiling), pick_keyring(index)
    if not toolkit or not keyring:
        raise StepError(f"{repo} has no cuda-toolkit ≤ {ceiling[0]}.{ceiling[1]} or no keyring package")
    return {"repo": repo, "ceiling": ceiling, "toolkit": toolkit, "keyring": keyring}


def describe(choice: dict) -> str:
    c = choice
    return (
        f"將安裝 CUDA toolkit {c['toolkit'].replace('-', '.')}（驅動支援上限 {c['ceiling'][0]}.{c['ceiling'][1]}）\n"
        f"Will install CUDA toolkit {c['toolkit'].replace('-', '.')} (driver ceiling {c['ceiling'][0]}.{c['ceiling'][1]})\n"
        f"  套件庫 / repository: {c['repo']}\n"
        f"  步驟 / steps: {c['keyring']} → apt-get update → apt-get install cuda-toolkit-{c['toolkit']}\n"
        "  不安裝、不更動 GPU 驅動 / The GPU driver is neither installed nor changed\n"
        "  需要 sudo / Requires sudo"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--platform", choices=["wsl2", "ubuntu"], required=True)
    args = ap.parse_args(argv)

    detected = sudo_window.detect_platform()
    if detected != args.platform:
        print(f"這台機器偵測為 {detected}，不是 {args.platform} / Detected {detected}, not {args.platform}")
        return 2
    try:
        smi = subprocess.run(["nvidia-smi"], capture_output=True, text=True).stdout
    except OSError:
        smi = ""
    try:
        choice = prepare(args.platform, smi, read_os_release(), _platform.machine())
    except StepError as exc:
        print(f"[cuda] {exc}")
        return 1
    desc = describe(choice)
    if not sudo_window.ask_consent(desc):
        print("[cuda] 未同意，略過 / Not approved; skipped")
        return 3
    root = project_root()
    work = root / "var" / "sudo"
    work.mkdir(parents=True, exist_ok=True)
    keyring_file = work / choice["keyring"]
    try:
        download(choice["repo"] + choice["keyring"], keyring_file)
    except Exception as exc:  # noqa: BLE001
        print(f"[cuda] cannot download {choice['keyring']}: {exc}")
        return 1
    script = work / "install_cuda_step.sh"
    script.write_text(render_script(keyring_file, choice["toolkit"]), encoding="utf-8")
    rc = sudo_window.run_with_sudo("install_cuda", script, desc,
                                   title=f"Jiezi CUDA {choice['toolkit'].replace('-', '.')} install", root=root)
    print(f"[cuda] {'完成 / done' if rc == 0 else f'失敗，結束碼 {rc} / failed with exit code {rc}'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

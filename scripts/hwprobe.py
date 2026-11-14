#!/usr/bin/env python3
"""hwprobe — 唯讀硬體探測，輸出 facts.json。

設計原則：
1. 只讀，不修改系統，不寫入 --out 以外的檔案。
2. 任一探測器失敗只影響該區塊（present=false + reason），不影響其他區塊。
3. 每項事實標註 source，使結果可追溯。
4. 區分「後端可用」與「後端可建置」，不混為一談。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"


def project_root() -> Path:
    """專案根目錄：預設由本檔位置推得，可由 JIEZI_HOME 覆寫（規則 R21.3、R21.5）。
    Project root: derived from this file's location, overridable by JIEZI_HOME (rules R21.3, R21.5).
    與目前工作目錄無關。 / Independent of the current working directory."""
    env = os.environ.get("JIEZI_HOME", "").strip()
    return Path(env).expanduser().resolve() if env else Path(__file__).resolve().parent.parent


def venv_tool(name: str) -> str | None:
    """先找 PATH，再找專案 .venv 內的工具；都沒有則回傳 None。
    Look on PATH first, then in the project's .venv; return None if absent."""
    found = shutil.which(name)
    if found:
        return found
    candidate = project_root() / ".venv" / "bin" / name
    return str(candidate) if candidate.exists() else None

# /proc/cpuinfo 的 flags 名稱 → facts 中的標準名稱
ISA_MAP = {
    "sse4_2": "sse4_2",
    "avx": "avx",
    "avx2": "avx2",
    "avx512f": "avx512f",
    "avx512_vnni": "avx512_vnni",
    "avx_vnni": "avx_vnni",
    "avx_vnni_int8": "avx_vnni_int8",
    "amx_tile": "amx",
    "amx_int8": "amx_int8",
    "amx_bf16": "amx_bf16",
    "fma": "fma",
    "f16c": "f16c",
    "avx512_bf16": "avx512_bf16",
}


def run(cmd: list[str], timeout: int = 10) -> tuple[bool, str, str]:
    """執行外部指令，永不拋錯。"""
    if shutil.which(cmd[0]) is None:
        return False, "", f"{cmd[0]}: not found"
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, errors="replace"
        )
        return p.returncode == 0, p.stdout.strip(), p.stderr.strip()
    except Exception as exc:  # noqa: BLE001 - 探測器不得因單一失敗中斷
        return False, "", f"{type(exc).__name__}: {exc}"


def read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------- host
def collect_host() -> dict:
    version = read_text("/proc/version") or ""
    os_release = read_text("/etc/os-release") or ""
    distro = {}
    for line in os_release.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            distro[k] = v.strip().strip('"')
    is_wsl = "microsoft" in version.lower() or "wsl" in version.lower()
    return {
        "present": True,
        "source": "/proc/version, /etc/os-release",
        "kernel": version.strip(),
        "distro": distro.get("PRETTY_NAME", "unknown"),
        "is_wsl": is_wsl,
        "arch": os.uname().machine,
    }


# ---------------------------------------------------------------- cpu
def collect_cpu() -> dict:
    info = read_text("/proc/cpuinfo")
    if not info:
        return {"present": False, "reason": "/proc/cpuinfo not readable"}

    model = "unknown"
    flags: set[str] = set()
    cores: set[tuple[str, str]] = set()
    logical = 0
    current_physical = None
    current_core = None
    current_proc = None
    threads_by_core: dict[tuple[str, str], list[int]] = {}

    for line in info.splitlines():
        if line.startswith("model name"):
            model = line.split(":", 1)[1].strip()
        elif line.startswith("flags"):
            flags.update(line.split(":", 1)[1].split())
        elif line.startswith("processor"):
            logical += 1
            current_proc = int(line.split(":", 1)[1].strip())
        elif line.startswith("physical id"):
            current_physical = line.split(":", 1)[1].strip()
        elif line.startswith("core id"):
            current_core = line.split(":", 1)[1].strip()
            if current_physical is not None and current_core is not None:
                cores.add((current_physical, current_core))
                if current_proc is not None:
                    threads_by_core.setdefault((current_physical, current_core), []).append(current_proc)

    physical = len(cores) if cores else logical
    # 每個實體核對應的邏輯 CPU 編號；邏輯編號不保證連號對應核心
    # （本機 WSL2：cpu0/cpu1 同屬 core 0），親和性必須依此推導。
    core_threads = [
        sorted(threads_by_core[k])
        for k in sorted(threads_by_core, key=lambda k: (int(k[0]), int(k[1])))
    ]

    numa = 0
    numa_dir = Path("/sys/devices/system/node")
    if numa_dir.is_dir():
        numa = len([p for p in numa_dir.iterdir() if p.name.startswith("node")])

    isa = sorted({ISA_MAP[f] for f in flags if f in ISA_MAP})
    caps = {
        "avx2": "avx2" in flags,
        "avx512": any(f.startswith("avx512f") for f in flags),
        "amx": any(f.startswith("amx") for f in flags),
        "avx_vnni": "avx_vnni" in flags,
        "fma": "fma" in flags,
        "f16c": "f16c" in flags,
    }

    return {
        "present": True,
        "source": "/proc/cpuinfo, /sys/devices/system/node",
        "model": model,
        "physical_cores": physical,
        "logical_cores": logical,
        "core_threads": core_threads,
        "numa_nodes": numa,
        "isa": isa,
        "caps": caps,
        # ggml 建議以實體核為執行緒數；HT 對記憶體頻寬受限的 decode 幫助有限
        "recommended_threads": physical,
    }


# ---------------------------------------------------------------- memory
def collect_memory() -> dict:
    info = read_text("/proc/meminfo")
    if not info:
        return {"present": False, "reason": "/proc/meminfo not readable"}
    vals: dict[str, int] = {}
    for line in info.splitlines():
        m = re.match(r"^(\w+):\s+(\d+)", line)
        if m:
            vals[m.group(1)] = int(m.group(2))
    mib = lambda kb: round(kb / 1024)  # noqa: E731
    return {
        "present": True,
        "source": "/proc/meminfo",
        "total_mib": mib(vals.get("MemTotal", 0)),
        "available_mib": mib(vals.get("MemAvailable", 0)),
    }


# ---------------------------------------------------------------- gpu
def collect_gpus() -> dict:
    gpus: list[dict] = []
    ok, out, err = run(
        [
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.free,driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ]
    )
    if ok and out:
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 6:
                continue
            gpus.append(
                {
                    "vendor": "nvidia",
                    "index": int(parts[0]),
                    "name": parts[1],
                    "vram_total_mib": int(parts[2]),
                    "vram_free_mib": int(parts[3]),
                    "driver": parts[4],
                    "compute_cap": parts[5],
                    "source": "nvidia-smi",
                }
            )
        reason = None
    else:
        reason = err or "nvidia-smi unavailable"

    dri = sorted(Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
    return {
        "present": bool(gpus),
        "source": "nvidia-smi, /dev/dri",
        "gpus": gpus,
        "reason": reason,
        "windows_host_bridge": Path("/dev/dxg").exists(),
        "dri_render_nodes": [str(p) for p in dri],
    }


# ---------------------------------------------------------------- npu
def collect_npus() -> dict:
    npus: list[dict] = []
    accel = Path("/sys/class/accel")
    if accel.is_dir():
        for dev in sorted(accel.iterdir()):
            driver = None
            link = dev / "device" / "driver"
            if link.exists():
                driver = os.path.basename(os.path.realpath(link))
            npus.append(
                {
                    "name": dev.name,
                    "driver": driver,
                    "source": "/sys/class/accel",
                    "kind": "accel_class",
                }
            )

    ok, out, _ = run(["lspci", "-nn"])
    pci_found = []
    if ok:
        for line in out.splitlines():
            low = line.lower()
            if "processing accelerators" in low or "1200:" in low or "neural" in low:
                pci_found.append(line.strip())
    for line in pci_found:
        npus.append({"name": line, "source": "lspci", "kind": "pci_processing_accelerator"})

    if npus:
        reason = None
    else:
        parts = []
        parts.append(
            "/sys/class/accel absent" if not accel.is_dir() else "/sys/class/accel empty"
        )
        parts.append(
            "lspci not installed (PCI check skipped)" if not ok else "no PCI processing accelerator"
        )
        reason = "; ".join(parts)

    return {"present": bool(npus), "source": "/sys/class/accel, lspci", "npus": npus, "reason": reason}


# ---------------------------------------------------------------- backends
DEVICE_LINE = re.compile(r"^\s+(\S+?):\s+(.*?)\s+\((\d+)\s+MiB,\s+(\d+)\s+MiB free\)$")


def collect_builds(root: Path | None = None) -> list[dict]:
    root = root or project_root()
    builds = []
    for binary in sorted(root.glob("build-*/bin/llama-cli")):
        ok_ver, ver_out, ver_err = run([str(binary), "--version"])
        ver_text = ver_out or ver_err
        ok_dev, dev_out, _ = run([str(binary), "--list-devices"])
        accelerators = []
        for line in dev_out.splitlines():
            m = DEVICE_LINE.match(line)
            if m:
                accelerators.append(
                    {
                        "name": m.group(1),
                        "description": m.group(2),
                        "memory_total_mib": int(m.group(3)),
                        "memory_free_mib": int(m.group(4)),
                    }
                )
        builds.append(
            {
                "path": str(binary.relative_to(root)),
                "version": ver_text.splitlines()[0] if ok_ver and ver_text else None,
                "runs": ok_dev,
                "accelerators": accelerators,
                "list_devices_excludes_cpu": True,
            }
        )
    return builds


def _cuda_version_key(path: Path) -> tuple:
    # /usr/local/cuda-13.3 → (13, 3)；無法解析者排最後 / unparsable names sort last
    m = re.search(r"cuda-(\d+)\.(\d+)", str(path))
    return (int(m.group(1)), int(m.group(2))) if m else (-1, -1)


def find_nvcc(env: dict | None = None, local: Path = Path("/usr/local")) -> dict:
    """依 design D4 順序尋找 nvcc，回傳 {path, version, found_via, checked}。
    Find nvcc in the design D4 order; return {path, version, found_via, checked}."""
    env = os.environ if env is None else env
    checked: list[str] = []
    candidates: list[tuple[str, Path]] = []
    on_path = shutil.which("nvcc", path=env.get("PATH"))
    if on_path:
        candidates.append(("path", Path(on_path)))
    checked.append("PATH")
    for var, via in (("CUDA_HOME", "cuda_home"), ("CUDA_PATH", "cuda_path")):
        if env.get(var):
            candidates.append((via, Path(env[var]) / "bin" / "nvcc"))
        checked.append(f"${var}/bin")
    candidates.append(("standard_location", local / "cuda" / "bin" / "nvcc"))
    for d in sorted(local.glob("cuda-*"), key=_cuda_version_key, reverse=True):
        candidates.append(("standard_location", d / "bin" / "nvcc"))
    checked.append(f"{local}/cuda/bin, {local}/cuda-*/bin")
    for via, cand in candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            ok, out, err = run([str(cand), "--version"])
            m = re.search(r"release (\d+\.\d+)", out or err or "")
            return {"path": str(cand), "version": m.group(1) if m else None, "found_via": via, "checked": checked}
    return {"path": None, "version": None, "found_via": None, "checked": checked}


def collect_backends() -> dict:
    gcc = shutil.which("gcc")
    gxx = shutil.which("g++")
    nvcc_info = find_nvcc()
    nvcc = nvcc_info["path"]
    # 以專案根目錄定位 .venv，不依賴目前工作目錄 / Locate .venv from the project root, not the cwd
    cmake = venv_tool("cmake")
    ninja = venv_tool("ninja")

    _, nvsmi, _ = run(["nvidia-smi", "-L"])
    has_nvidia = bool(nvsmi)

    icd_dir = Path("/usr/share/vulkan/icd.d")
    icds = sorted(p.stem for p in icd_dir.glob("*.json")) if icd_dir.is_dir() else []

    _, ldout, _ = run(["ldconfig", "-p"])
    has_openvino_lib = "openvino" in ldout.lower() if ldout else False

    buildable: dict[str, dict] = {}

    # CPU：只要有編譯器就能建
    buildable["cpu"] = {
        "ok": bool(gcc and gxx and cmake),
        "reason": None
        if (gcc and gxx and cmake)
        else f"missing: {', '.join(x for x, v in [('gcc', gcc), ('g++', gxx), ('cmake', cmake)] if not v)}",
    }

    # CUDA：需要驅動 + CUDA toolkit(nvcc) + 編譯器
    if has_nvidia and nvcc and gcc:
        buildable["cuda"] = {"ok": True, "reason": None}
    else:
        missing = []
        if not has_nvidia:
            missing.append("nvidia driver")
        if not nvcc:
            missing.append("nvcc (cuda-toolkit; checked: " + "; ".join(nvcc_info["checked"]) + ")")
        if not gcc:
            missing.append("gcc")
        buildable["cuda"] = {"ok": False, "reason": "missing: " + ", ".join(missing)}

    render_nodes = (
        sorted(Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
    )
    software_icds = {"lvp_icd", "lavapipe_icd", "swiftshader_icd"}
    hardware_icds = [i for i in icds if i not in software_icds]
    if not render_nodes:
        vulkan_reason = "no /dev/dri render node (WSL2 does not expose DRM devices)"
    elif not hardware_icds:
        vulkan_reason = f"only software ICDs available: {', '.join(icds) or 'none'}"
    else:
        vulkan_reason = None
    buildable["vulkan"] = {
        "ok": bool(render_nodes) and bool(hardware_icds),
        "reason": vulkan_reason,
        "hardware_icds": hardware_icds,
        "render_nodes": [str(p) for p in render_nodes],
    }

    # OpenVINO
    buildable["openvino"] = {
        "ok": bool(has_openvino_lib),
        "reason": None if has_openvino_lib else "libopenvino not in ldconfig (install OpenVINO runtime)",
    }

    builds = collect_builds()
    available = []
    if builds:
        available.append("cpu")
        for b in builds:
            for dev in b["accelerators"]:
                if dev["name"] not in available:
                    available.append(dev["name"])

    return {
        "source": "which/shutil, /usr/share/vulkan/icd.d, ldconfig -p, build-*/bin/llama-cli",
        "available": available,
        "available_reason": None
        if builds
        else "no llama.cpp binary found (build-*/bin/llama-cli); CPU is not listed by --list-devices",
        "builds": builds,
        "buildable": buildable,
        "toolchain": {
            "gcc": gcc,
            "g++": gxx,
            "cmake": cmake,
            "ninja": ninja,
            "nvcc": nvcc_info,
        },
        "vulkan_icds": icds,
    }


# ---------------------------------------------------------------- fingerprint
def compute_fingerprint(host: dict, cpu: dict, mem: dict, gpus: dict) -> dict:
    """機器指紋：只取靜態欄位，供量測結果標示來源機器（design D6、規則 R21.6）。
    Machine fingerprint from static fields only, so measurements can name their source machine (design D6, rule R21.6).
    RAM 四捨五入到 GiB，吸收核心保留記憶體的小幅浮動；驅動版本刻意納入（會影響效能）。
    RAM is rounded to GiB to absorb small kernel-reserved fluctuations; the driver version is included on purpose (it affects performance)."""
    if host.get("is_wsl"):
        platform = "wsl2"
    else:
        platform = sys.platform  # "linux" / "darwin" / ...
    total_mib = mem.get("total_mib")
    gpu_list = [
        {"name": g.get("name"), "vram_total_mib": g.get("vram_total_mib"), "driver": g.get("driver")}
        for g in (gpus.get("gpus") or [])
    ]
    static = {
        "platform": platform,
        "arch": host.get("arch"),
        "cpu_model": cpu.get("model"),
        "physical_cores": cpu.get("physical_cores"),
        "logical_cores": cpu.get("logical_cores"),
        "ram_total_gib": round(total_mib / 1024) if isinstance(total_mib, (int, float)) else None,
        "gpus": sorted(gpu_list, key=lambda g: json.dumps(g, sort_keys=True)),
    }
    digest = hashlib.sha256(json.dumps(static, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"id": digest[:16], "source": "derived from host/cpu/memory/gpus (static fields only)", **static}


# ---------------------------------------------------------------- verdict
BUDGET_POLICY = {
    "cpu_reserve_cores": 2,
    "ram_floor_mib": 2560,
    "ram_max_fraction_of_available": 0.70,
    "vram_floor_mib": 1024,
    "vram_max_fraction_of_free": 0.85,
    "max_age_seconds": 60,
}


def _usable(available_mib: int, floor_mib: int, fraction: float) -> tuple[int, str]:
    by_fraction = int(available_mib * fraction)
    by_floor = max(0, available_mib - floor_mib)
    if by_fraction <= by_floor:
        return max(0, by_fraction), "fraction"
    return max(0, by_floor), "floor"


def _cpu_list(cpus: list[int]) -> str:
    """[0,1,2,4,6] → "0-2,4,6"（taskset -c 格式）"""
    runs: list[list[int]] = []
    for c in sorted(cpus):
        if runs and c == runs[-1][1] + 1:
            runs[-1][1] = c
        else:
            runs.append([c, c])
    return ",".join(f"{a}" if a == b else f"{a}-{b}" for a, b in runs)


def _affinity(core_threads: list[list[int]], physical: int, reserved: int) -> dict:
    if not core_threads or len(core_threads) != physical:
        return {
            "affinity_hint": None,
            "affinity_reason": "core→thread topology unavailable; refusing to guess "
            "(contiguous logical ids may share physical cores)",
        }
    # 保留編號最小的核：core 0 通常承擔較多 IRQ / housekeeping
    usable = core_threads[reserved:]
    return {
        "affinity_hint": _cpu_list([t[0] for t in usable]),
        "affinity_reason": f"one thread per usable physical core (cores {reserved}..{physical - 1}); "
        f"reserved cores 0..{reserved - 1}" if reserved else "one thread per physical core",
    }


def compute_budgets(facts: dict) -> dict:
    policy = dict(BUDGET_POLICY)
    cpu = facts.get("cpu") or {}
    mem = facts.get("memory") or {}
    gpus = ((facts.get("gpus") or {}).get("gpus")) or []

    physical = int(cpu.get("physical_cores") or 1)
    reserved = min(policy["cpu_reserve_cores"], max(0, physical - 1))
    usable_threads = max(1, physical - reserved)

    avail = int(mem.get("available_mib") or 0)
    ram_usable, ram_binding = _usable(
        avail, policy["ram_floor_mib"], policy["ram_max_fraction_of_available"]
    )

    vram = None
    if gpus:
        g = gpus[0]
        free = int(g.get("vram_free_mib") or 0)
        u, binding = _usable(
            free, policy["vram_floor_mib"], policy["vram_max_fraction_of_free"]
        )
        vram = {
            "device": g.get("name"),
            "total_mib": int(g.get("vram_total_mib") or 0),
            "free_mib": free,
            "floor_mib": policy["vram_floor_mib"],
            "usable_mib": u,
            "binding_constraint": binding,
        }

    return {
        "source": "derived from facts; policy is explicit and auditable",
        "policy": policy,
        "cpu": {
            "physical_cores": physical,
            "reserved_cores": reserved,
            "usable_threads": usable_threads,
            **_affinity(cpu.get("core_threads") or [], physical, reserved),
            **(
                {"topology_note": "WSL2 exposes a virtual CPU topology; vCPUs are not pinned to "
                 "host cores, so core reservation is approximate"}
                if (facts.get("host") or {}).get("is_wsl")
                else {}
            ),
        },
        "ram": {
            "total_mib": int(mem.get("total_mib") or 0),
            "available_mib": avail,
            "floor_mib": policy["ram_floor_mib"],
            "usable_mib": ram_usable,
            "binding_constraint": ram_binding,
        },
        "vram": vram,
        "recheck": {
            "before_model_load": True,
            "max_age_seconds": policy["max_age_seconds"],
        },
    }


def build_verdict(gpus: dict, npus: dict, backends: dict, cpu: dict, mem: dict, budgets: dict) -> dict:
    warnings: list[str] = []
    builds = backends.get("builds") or []
    accels = [d["name"] for b in builds for d in b.get("accelerators", [])]

    if accels:
        primary = accels[0]
        reason = f"accelerator available in built binary: {primary}"
    elif gpus.get("gpus"):
        primary = "cpu"
        reason = (
            "GPU present but no build exposes it; "
            + backends["buildable"]["cuda"]["reason"]
        )
        warnings.append("GPU detected but current builds are CPU-only")
    else:
        primary = "cpu"
        reason = "no GPU detected; CPU is the only device"

    if builds:
        warnings.append(
            f"cpu backend available via {len(builds)} build(s); --list-devices never lists CPU"
        )

    if npus.get("present"):
        warnings.append("NPU detected but ggml-openvino exposes only one device per process")
    else:
        warnings.append("no NPU: " + str(npus.get("reason")))

    if backends["buildable"]["vulkan"]["reason"]:
        warnings.append("vulkan: " + backends["buildable"]["vulkan"]["reason"])

    total = mem.get("total_mib", 0)
    avail = mem.get("available_mib", 0)
    if total and avail < total * 0.6:
        warnings.append(f"low available RAM: {avail} MiB of {total} MiB")

    return {
        "primary_device": primary,
        "reason": reason,
        "recommended_threads": budgets["cpu"]["usable_threads"],
        "budget_notes": [
            f"cpu: {budgets['cpu']['reserved_cores']} physical cores reserved"
            f" (physical {budgets['cpu']['physical_cores']} → usable {budgets['cpu']['usable_threads']})",
            f"ram: usable {budgets['ram']['usable_mib']} MiB of {budgets['ram']['available_mib']} MiB available"
            f" (floor {budgets['ram']['floor_mib']} MiB, binding={budgets['ram']['binding_constraint']})",
        ]
        + (
            [
                f"vram: usable {budgets['vram']['usable_mib']} MiB of {budgets['vram']['free_mib']} MiB free"
                f" (floor {budgets['vram']['floor_mib']} MiB, binding={budgets['vram']['binding_constraint']})"
            ]
            if budgets.get("vram")
            else ["vram: no GPU"]
        ),
        "warnings": warnings,
    }


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only hardware probe → facts.json")
    ap.add_argument(
        "--out",
        default=None,
        help="output path (default: <project root>/facts.json)",
    )
    ap.add_argument("--pretty", action="store_true", help="pretty-print JSON")
    ap.add_argument("--quiet", action="store_true", help="do not print the JSON to stdout")
    args = ap.parse_args()

    failures: list[str] = []

    def safe(name, fn, fallback):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            return fallback

    host = safe("host", collect_host, {"present": False, "reason": "probe failed"})
    cpu = safe("cpu", collect_cpu, {"present": False, "reason": "probe failed"})
    mem = safe("memory", collect_memory, {"present": False, "reason": "probe failed"})
    gpus = safe("gpus", collect_gpus, {"present": False, "gpus": [], "reason": "probe failed"})
    npus = safe("npus", collect_npus, {"present": False, "npus": [], "reason": "probe failed"})
    backends = safe("backends", collect_backends, {"available": [], "buildable": {}})
    facts_core = {
        "host": host,
        "cpu": cpu,
        "memory": mem,
        "gpus": gpus,
        "npus": npus,
        "backends": backends,
    }
    budgets = safe(
        "budgets",
        lambda: compute_budgets(facts_core),
        {"policy": BUDGET_POLICY, "error": "budget computation failed"},
    )
    verdict = safe(
        "verdict",
        lambda: build_verdict(gpus, npus, backends, cpu, mem, budgets),
        {"primary_device": "cpu", "reason": "verdict failed"},
    )

    fingerprint = safe(
        "fingerprint",
        lambda: compute_fingerprint(host, cpu, mem, gpus),
        {"id": None, "reason": "fingerprint computation failed"},
    )

    facts = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprint": fingerprint,
        "host": host,
        "cpu": cpu,
        "memory": mem,
        "gpus": gpus,
        "npus": npus,
        "backends": backends,
        "budgets": budgets,
        "verdict": verdict,
        "probe_failures": failures,
    }

    out = Path(args.out) if args.out else project_root() / "facts.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(facts, indent=2 if args.pretty else None, ensure_ascii=False)
    out.write_text(text + "\n")

    if not args.quiet:
        print(text)
    print(f"[hwprobe] wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

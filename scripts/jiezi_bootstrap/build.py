"""依偵測結果與資源預算建置 llama.cpp（規格 build；design D3–D5）。
Build llama.cpp from detection results within the resource budget (spec build; design D3–D5).

- 後端選擇只看 facts.json 的 backends.buildable；CPU 一律建置。
  Backend choice reads only backends.buildable in facts.json; CPU is always built.
- 旗標不含任何硬體型號（R21）；GGML_RPC 明確設為 OFF（stack.md §3）。
  Flags name no hardware model (R21); GGML_RPC is explicitly OFF (stack.md §3).
- 平行數、nice、taskset 取自 budgets.cpu（R18.1、R18.2）。
  Job count, nice and taskset come from budgets.cpu (R18.1, R18.2)."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .common import StepError, project_root

# 加速後端 → 額外的 CMake 旗標 / Accelerator backend → extra CMake flags
ACCELERATORS = {
    "cuda": ["-DGGML_CUDA=ON", "-DCMAKE_CUDA_ARCHITECTURES=native"],
    "vulkan": ["-DGGML_VULKAN=ON"],
    "openvino": ["-DGGML_OPENVINO=ON"],
}

# 每個建置都帶的旗標；值都明確寫出，不依賴上游預設 / Flags on every build, never relying on upstream defaults
COMMON_FLAGS = [
    "-DCMAKE_BUILD_TYPE=Release",
    "-DGGML_NATIVE=ON",
    "-DGGML_RPC=OFF",  # CVE-2026-34159，見 stack.md §4 / see stack.md §4
    "-DLLAMA_OPENSSL=OFF",  # 模型由 bootstrap 下載，llama.cpp 不需 HTTPS；各機器結果一致
    "-DLLAMA_BUILD_TESTS=ON",  # 保留 test-backend-ops 供後端驗證 / keep test-backend-ops
]

NICE_LEVEL = 10


@dataclass
class Decision:
    backend: str
    build: bool
    reason: str


@dataclass
class Plan:
    backend: str
    build_dir: Path
    configure: list[str]
    compile: list[str]
    notes: list[str] = field(default_factory=list)


def select_backends(facts: dict) -> list[Decision]:
    """CPU 一律建置；加速後端只在 buildable.<name>.ok 為 true 時建置。
    CPU always; an accelerator only when buildable.<name>.ok is true."""
    buildable = (facts.get("backends") or {}).get("buildable") or {}
    decisions = [Decision("cpu", True, "always built")]
    for name in ACCELERATORS:
        entry = buildable.get(name) or {}
        if entry.get("ok") is True:
            decisions.append(Decision(name, True, "buildable per facts.json"))
        else:
            decisions.append(Decision(name, False, entry.get("reason") or "not reported by hwprobe"))
    return decisions


def _tool(name: str, root: Path) -> str:
    local = root / ".venv" / "bin" / name
    if local.exists():
        return str(local)
    found = shutil.which(name)
    if not found:
        raise StepError(f"{name} not found (run `uv sync` to install the dev tools)")
    return found


def plan_build(backend: str, facts: dict, src: Path, root: Path) -> Plan:
    """產生某後端的 configure / compile 指令（純函式，不執行）。
    Produce configure / compile commands for one backend (pure; runs nothing)."""
    cmake, ninja = _tool("cmake", root), _tool("ninja", root)
    build_dir = root / f"build-{backend}"
    flags = ["-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={ninja}", *COMMON_FLAGS, *ACCELERATORS.get(backend, [])]
    notes: list[str] = []

    if backend == "cuda":
        nvcc = (((facts.get("backends") or {}).get("toolchain") or {}).get("nvcc") or {}).get("path")
        if not nvcc:
            raise StepError("cuda selected but facts.json has no backends.toolchain.nvcc.path; re-run hwprobe")
        flags.append(f"-DCMAKE_CUDA_COMPILER={nvcc}")

    cpu = (facts.get("budgets") or {}).get("cpu") or {}
    jobs = max(1, int(cpu.get("usable_threads") or 1))
    prefix = ["nice", "-n", str(NICE_LEVEL)]
    hint = cpu.get("affinity_hint")
    if hint and shutil.which("taskset"):
        prefix = ["taskset", "-c", hint, *prefix]
        notes.append(f"pinned to CPUs {hint}")
    elif hint:
        notes.append("taskset not found; CPU pinning skipped, jobs still limited")
    else:
        notes.append(f"affinity_hint unavailable ({cpu.get('affinity_reason') or 'no reason given'}); "
                     "CPU pinning skipped, jobs still limited")
    notes.append(f"-j {jobs} (budgets.cpu.usable_threads), nice {NICE_LEVEL}")

    return Plan(
        backend=backend,
        build_dir=build_dir,
        configure=[*prefix, cmake, "-S", str(src), "-B", str(build_dir), *flags],
        compile=[*prefix, cmake, "--build", str(build_dir), "--config", "Release", "-j", str(jobs)],
        notes=notes,
    )


def _first_line(cmd: list[str]) -> str | None:
    if not shutil.which(cmd[0]):
        return None
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    return (p.stdout or p.stderr).splitlines()[0].strip() if (p.stdout or p.stderr) else None


def record_path(root: Path, backend: str) -> Path:
    return root / "var" / "builds" / f"{backend}.json"


def _identity(plan: Plan, commit: str, facts: dict) -> dict:
    """決定「同一個建置」的欄位；任何一項改變都要重建。
    The fields that define "the same build"; any change forces a rebuild."""
    return {
        "llama_cpp_commit": commit,
        "configure": plan.configure,
        "fingerprint_id": (facts.get("fingerprint") or {}).get("id"),
    }


def is_current(plan: Plan, commit: str, facts: dict, root: Path) -> bool:
    """上次建置成功、身分相同、執行檔仍在 → 可略過。
    Skip when the last build succeeded with the same identity and the binary still exists."""
    rec_file = record_path(root, plan.backend)
    if not rec_file.exists():
        return False
    try:
        rec = json.loads(rec_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    same = all(rec.get(k) == v for k, v in _identity(plan, commit, facts).items())
    return same and rec.get("result") == "success" and (plan.build_dir / "bin" / "llama-cli").exists()


def run_plan(plan: Plan, commit: str, facts: dict, root: Path, log=print) -> dict:
    """執行建置並寫出建置紀錄（成功或失敗都寫）。
    Run the build and write the record (on success and on failure)."""
    nvcc = (((facts.get("backends") or {}).get("toolchain") or {}).get("nvcc") or {})
    record = {
        **_identity(plan, commit, facts),
        "backend": plan.backend,
        "compile": plan.compile,
        "notes": plan.notes,
        "compiler": _first_line(["c++", "--version"]),
        "cuda_version": nvcc.get("version") if plan.backend == "cuda" else None,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    log_file = root / "var" / "builds" / f"{plan.backend}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    result, failed_stage = "success", None
    with log_file.open("w", encoding="utf-8") as fh:
        for stage, cmd in (("configure", plan.configure), ("compile", plan.compile)):
            fh.write(f"$ {' '.join(cmd)}\n")
            fh.flush()
            if subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT).returncode != 0:
                result, failed_stage = "failure", stage
                break
    record.update(
        result=result,
        failed_stage=failed_stage,
        duration_s=round(time.monotonic() - t0, 1),
        log=str(log_file.relative_to(root)),
    )
    record_path(root, plan.backend).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    return record


def build_all(facts: dict, src: Path, commit: str, root: Path | None = None, log=print) -> list[dict]:
    """依決策建置所有後端；任一必要後端失敗時拋出 StepError。
    Build every selected backend; raise StepError if any of them fails."""
    root = root or project_root()
    summary = []
    for d in select_backends(facts):
        if not d.build:
            log(f"[build] skip {d.backend}: {d.reason}")
            summary.append({"backend": d.backend, "result": "skipped", "reason": d.reason})
            continue
        plan = plan_build(d.backend, facts, src, root)
        if is_current(plan, commit, facts, root):
            log(f"[build] {d.backend}: up to date, skipped")
            summary.append({"backend": d.backend, "result": "up-to-date"})
            continue
        log(f"[build] {d.backend}: building ({'; '.join(plan.notes)})")
        rec = run_plan(plan, commit, facts, root, log)
        log(f"[build] {d.backend}: {rec['result']} in {rec['duration_s']} s (log: {rec['log']})")
        summary.append({"backend": d.backend, "result": rec["result"]})
        if rec["result"] != "success":
            raise StepError(f"build-{d.backend} failed at {rec['failed_stage']}; see {rec['log']}")
    return summary

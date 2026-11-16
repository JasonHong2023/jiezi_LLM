"""calibrator（開發計畫 4.4）：在這台電腦實測不同 GPU 層數（-ngl）的速度，結果寫進 var/runtime/bench.json，
供 supervisor 擺放核心時參考（例如放不進整張顯卡的模型，部分層上 GPU 可能比純 CPU 快）。
Calibrator (dev plan 4.4): measure speed at several -ngl values on this machine and record them, so the supervisor
can use measured partial offload when a model does not fit the GPU whole.

用鎖定版本的 llama-bench；遵守資源預算（保留核心、nice）。這是重度工作，GPU 被評測佔用時不要跑。
Uses the pinned llama-bench under the resource budget; a heavy job, not to run while an evaluation holds the GPU."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

NGL_STEPS = (0, 8, 16, 24, 99)


def bench_path(root: Path) -> Path:
    return root / "var" / "runtime" / "bench.json"


def parse(output: str) -> dict:
    """llama-bench -o json → {"pp": t/s, "tg": t/s}。 / Prompt and generation speeds."""
    out = {}
    for r in json.loads(output or "[]"):
        kind = "pp" if r.get("n_prompt") and not r.get("n_gen") else "tg" if r.get("n_gen") else None
        if kind:
            out[kind] = round(float(r.get("avg_ts") or 0), 2)
    return out


def best(results: dict) -> int | None:
    """生成速度最快的 ngl（互動速度以生成為準）。 / The ngl with the fastest generation."""
    ok = [(v["tg"], int(n)) for n, v in results.items() if v.get("tg")]
    return max(ok)[1] if ok else None


def run(root: Path, name: str, model: Path, sha256: str, facts: dict, steps=NGL_STEPS, run_cmd=subprocess.run,
        log=print) -> dict:
    from ..budget import budget_prefix
    prefix, threads, _ = budget_prefix(facts)
    results = {}
    for ngl in steps:
        build = "build-cuda" if ngl > 0 else "build-cpu"
        exe = root / build / "bin" / "llama-bench"
        cmd = [*prefix, str(exe), "-m", str(model), "-ngl", str(ngl), "-t", str(threads), "-p", "256", "-n", "64",
               "-r", "2", "-o", "json"]
        p = run_cmd(cmd, capture_output=True, text=True, timeout=1800)
        if p.returncode != 0:
            results[str(ngl)] = {"error": (p.stderr or "")[-200:]}
            log(f"  ngl {ngl}: failed")
            continue
        results[str(ngl)] = parse(p.stdout)
        log(f"  ngl {ngl}: {results[str(ngl)]}")
    data = json.loads(bench_path(root).read_text(encoding="utf-8")) if bench_path(root).exists() else {}
    data[name] = {"sha256": sha256, "results": results, "best_ngl": best(results),
                  "measured": datetime.now().astimezone().isoformat(timespec="seconds")}
    bench_path(root).parent.mkdir(parents=True, exist_ok=True)
    bench_path(root).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data[name]


def measured_ngl(root: Path, name: str, sha256: str) -> int | None:
    """同一個檔案（SHA-256 相同）的實測最佳 ngl。 / Measured best ngl for this exact file."""
    try:
        e = json.loads(bench_path(root).read_text(encoding="utf-8")).get(name) or {}
    except (OSError, ValueError):
        return None
    return e.get("best_ngl") if e.get("sha256") == sha256 else None

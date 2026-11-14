"""冒煙測試：純 CPU、不連雲端（規格 bootstrap / Smoke Test；規則 R18、R21）。
Smoke test: CPU-only, no cloud (spec bootstrap / Smoke Test; rules R18, R21)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .build import budget_prefix
from .common import StepError

QUESTION = "Question: What is the capital of France? Answer in one word.\nAnswer:"
MAX_TOKENS = 16
TIMEOUT_S = 600

_EVAL = re.compile(r"(?<!prompt )eval time\s*=.*?([\d.]+) tokens per second")


def parse_tps(stderr: str) -> float | None:
    m = _EVAL.search(stderr)
    return float(m.group(1)) if m else None


def command(binary: Path, model: Path, facts: dict) -> tuple[list[str], int, list[str]]:
    prefix, threads, notes = budget_prefix(facts)
    cmd = [*prefix, str(binary), "-m", str(model), "-p", QUESTION, "-n", str(MAX_TOKENS),
           "-t", str(threads), "--temp", "0", "-no-cnv", "--no-warmup"]
    return cmd, threads, notes


def run(root: Path, model: Path, facts: dict) -> dict:
    """以 build-cpu 執行固定問題；回答為空或無法取得 t/s 時失敗。
    Ask the fixed question with build-cpu; fail on an empty answer or missing t/s."""
    binary = root / "build-cpu" / "bin" / "llama-completion"
    if not binary.exists():
        raise StepError(f"{binary} not found; the build step must succeed first")
    cmd, threads, notes = command(binary, model, facts)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           stdin=subprocess.DEVNULL, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise StepError(f"smoke test exceeded {TIMEOUT_S} s") from exc
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-10:])
        raise StepError(f"llama-completion exited with {p.returncode}:\n{tail}")
    answer = p.stdout.split(QUESTION, 1)[-1].strip()
    if not answer:
        raise StepError("smoke test produced an empty answer")
    tps = parse_tps(p.stderr)
    if tps is None:
        raise StepError("could not read tokens per second from llama-completion output")
    return {
        "build": "build-cpu",
        "model": model.name,
        "threads": threads,
        "tokens_per_second": tps,
        "answer": answer.splitlines()[0][:200],
        "notes": notes,
    }

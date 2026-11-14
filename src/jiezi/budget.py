"""依 facts.json 的 budgets.cpu 產生資源受限的指令前綴（規則 R18.1、R18.2）。
Build a resource-bounded command prefix from budgets.cpu in facts.json (rules R18.1, R18.2)."""

from __future__ import annotations

import shutil

NICE_LEVEL = 10


def budget_prefix(facts: dict) -> tuple[list[str], int, list[str]]:
    """回傳 (指令前綴, 執行緒數, 說明)；建置、冒煙測試、評測引擎共用。
    Return (command prefix, thread count, notes); shared by builds, the smoke test, and the eval engine."""
    cpu = (facts.get("budgets") or {}).get("cpu") or {}
    jobs = max(1, int(cpu.get("usable_threads") or 1))
    prefix = ["nice", "-n", str(NICE_LEVEL)]
    notes: list[str] = []
    hint = cpu.get("affinity_hint")
    if hint and shutil.which("taskset"):
        prefix = ["taskset", "-c", hint, *prefix]
        notes.append(f"pinned to CPUs {hint}")
    elif hint:
        notes.append("taskset not found; CPU pinning skipped, jobs still limited")
    else:
        notes.append(f"affinity_hint unavailable ({cpu.get('affinity_reason') or 'no reason given'}); "
                     "CPU pinning skipped, jobs still limited")
    notes.append(f"{jobs} threads (budgets.cpu.usable_threads), nice {NICE_LEVEL}")
    return prefix, jobs, notes

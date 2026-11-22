"""有效上限單一來源（add-agent-hardening）：代理迴圈、契約與回歸測試共用同一份不可變數值。
Single source of effective limits (add-agent-hardening): the loop, the contract, and regression tests share one immutable set of values.

本模組只放數值，不讀環境變數、不開連線、不引入相依；既有常數名稱仍由 `loop.py` 與 `contract.py` 保留。
This module holds values only: no environment overrides, no I/O, no dependency; legacy names stay in `loop.py` and `contract.py`.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

_EFFECTIVE = {
    "max_steps": 6,
    "max_calls_per_step": 3,
    "result_chars": 2500,
    "old_result_chars": 400,
    "tools_budget": 2600,
    "call_timeout_s": 120,
}

EFFECTIVE_LIMITS: Mapping[str, int] = MappingProxyType(_EFFECTIVE)

__all__ = ["EFFECTIVE_LIMITS"]

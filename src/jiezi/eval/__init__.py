"""評測框架（規格 eval）/ Evaluation harness (spec eval)."""

# 與共用引擎同一個類別，所以評測的 `except EvalError` 也會接住引擎錯誤。
# The same class as the shared engine's, so evaluation's `except EvalError` also catches engine errors.
from ..errors import JieziError as EvalError

__all__ = ["EvalError"]

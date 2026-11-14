"""評測框架（規格 eval）/ Evaluation harness (spec eval)."""


class EvalError(Exception):
    """評測無法繼續；訊息直接顯示給使用者。 / Evaluation cannot continue; the message is shown as-is."""

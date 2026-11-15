"""共用的錯誤類別。 / Shared error class."""


class JieziError(Exception):
    """無法繼續；訊息直接顯示給使用者。評測沿用為 EvalError。
    Cannot continue; the message is shown as-is. Evaluation uses it as EvalError."""

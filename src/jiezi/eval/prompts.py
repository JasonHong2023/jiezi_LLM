"""各題型的固定提示模板（design D10）；模板雜湊納入量測條件。
Fixed prompt templates per item type (design D10); their hash is part of the measurement conditions."""

from __future__ import annotations

import hashlib
import json

TEMPLATES = {
    "multiple_choice": (
        "以下是單選題，請直接回答正確選項的字母（A、B、C 或 D），不要解釋。\n\n"
        "{question}\nA. {A}\nB. {B}\nC. {C}\nD. {D}\n答案："
    ),
    "simpleqa": "請用一句話簡短回答以下問題，只給出答案。\n\n問題：{question}",
    "code": "請完成以下 Python 函式。只輸出完整的程式碼，放在一個 ```python 程式碼區塊中，不要解釋。\n\n{prompt}",
    "tool": (
        "你可以使用以下函式（JSON 格式描述）：\n{functions}\n\n"
        "請根據使用者的需求決定要呼叫哪些函式。只輸出函式呼叫，格式為 "
        "[函式名(參數1=值1, 參數2=值2), 函式名2(...)]，不要輸出其他文字。\n\n{question}"
    ),
    "summary": (
        "請用繁體中文為以下文章寫一段 100 到 150 字的摘要。只根據文章內容，不要加入文章沒有的資訊。\n\n"
        "文章：\n{text}"
    ),
}

MAX_TOKENS = {"multiple_choice": 32, "simpleqa": 64, "code": 768, "tool": 256, "summary": 400}


def template_hash() -> str:
    blob = json.dumps({"templates": TEMPLATES, "max_tokens": MAX_TOKENS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def kind(item: dict) -> str:
    """題目對應的模板種類。 / The template kind for an item."""
    if item["scorer"] == "multiple_choice":
        return "multiple_choice"
    if item["scorer"] == "simpleqa_approx":
        return "simpleqa"
    return {"code": "code", "tool": "tool", "summary": "summary"}[item["task"]]


def render(item: dict) -> tuple[list[dict], int]:
    """回傳 (chat 訊息, max_tokens)。 / Return (chat messages, max_tokens)."""
    k, d = kind(item), item["data"]
    if k == "multiple_choice":
        text = TEMPLATES[k].format(question=d["question"], **d["choices"])
    elif k == "simpleqa":
        text = TEMPLATES[k].format(question=d["question"])
    elif k == "code":
        text = TEMPLATES[k].format(prompt=d["prompt"])
    elif k == "tool":
        question = d["question"].removeprefix("user:").strip()
        text = TEMPLATES[k].format(functions=json.dumps(d["functions"], ensure_ascii=False, indent=1),
                                   question=question)
    else:
        text = TEMPLATES[k].format(text=d["text"])
    return [{"role": "user", "content": text}], MAX_TOKENS[k]

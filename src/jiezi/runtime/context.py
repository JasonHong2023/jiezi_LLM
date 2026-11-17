"""本機模型的上下文長度把關：送出前估算 token 數，超出時依序裁掉最舊的對話、最長的附加資料，最後才截短問題。
Context guard for the local model: estimate tokens before sending; when over budget, drop the oldest turns, then shorten
the longest attached data, and only last of all shorten the question.

只用在本機模型（每個槽位 4096 token）；Claude 與雲端的上下文長得多，不裁。
Local model only (4096 tokens per slot); Claude and the cloud are never trimmed."""

from __future__ import annotations

import json
import re

SLOT_CTX = 4096
IMAGE_TOKENS = 400              # 一張圖的估計 token（不把 base64 長度算進去）/ per image, never the base64 length
DEFAULT_ANSWER = 1024           # 沒指定 max_tokens 時為回答保留 / reserved for the answer when max_tokens is unset
MSG_OVERHEAD, MIN_DATA_CHARS = 8, 200
_CJK = re.compile(r"[⺀-鿿豈-﫿＀-￯]")


def est_tokens(text: str) -> int:
    """保守估算：中日韓字約 1 token，其他約 3.5 字元 1 token。 / Conservative: CJK ≈ 1 token each, else 3.5 chars."""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    return cjk + int((len(text) - cjk) / 3.5) + 1


def _msg_tokens(m: dict) -> int:
    c = m.get("content")
    if isinstance(c, list):  # 多段內容：文字照算，圖片固定估計 / text parts counted, images estimated
        text = "".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
        images = sum(1 for p in c if isinstance(p, dict) and p.get("type") in ("image_url", "input_image"))
        return est_tokens(text) + images * IMAGE_TOKENS + MSG_OVERHEAD
    text = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) if c else ""
    if m.get("tool_calls"):
        text += json.dumps(m["tool_calls"], ensure_ascii=False)
    return est_tokens(text) + MSG_OVERHEAD


def total(messages: list[dict], tools: list | None = None) -> int:
    return sum(_msg_tokens(m) for m in messages) + (est_tokens(json.dumps(tools, ensure_ascii=False)) if tools else 0)


def fit(messages: list[dict], tools: list | None = None, max_tokens: int | None = None,
        ctx: int = SLOT_CTX) -> tuple[list[dict], dict]:
    """回傳 (裁好的訊息, 裁了什麼)。 / Return (fitted messages, what was trimmed)."""
    budget = ctx - (max_tokens or DEFAULT_ANSWER)
    msgs = [dict(m) for m in messages]
    info = {"before": total(msgs, tools), "dropped_turns": 0, "shortened_data": 0, "shortened_question": False}
    if info["before"] <= budget:
        info["after"] = info["before"]
        return msgs, info
    last_user = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=len(msgs) - 1)
    # 1. 最舊的對話（保留系統訊息與最後一個問題）/ oldest turns, keeping system messages and the last question
    i = 0
    while total(msgs, tools) > budget and i < last_user:
        if msgs[i].get("role") != "system":
            msgs.pop(i)
            last_user -= 1
            info["dropped_turns"] += 1
        else:
            i += 1
    # 2. 最長的附加資料（第一則系統訊息是身分提示，不動）/ the longest attached data; the first system prompt stays
    while total(msgs, tools) > budget:
        data = [(len(m["content"]), j) for j, m in enumerate(msgs)
                if m.get("role") == "system" and j > 0 and isinstance(m.get("content"), str)
                and len(m["content"]) > MIN_DATA_CHARS]
        if not data:
            break
        _, j = max(data)
        short = msgs[j]["content"][:max(MIN_DATA_CHARS, len(msgs[j]["content"]) // 2)] + "……（已截短）"
        if len(short) >= len(msgs[j]["content"]):
            # 已經截到下限：再截也不會變短，改截問題（2026-11-17 實測：長文件加防注入提醒時在這裡空轉，gateway 卡死）
            # Already at the floor: no further shrinking is possible, so move on to the question (a live hang)
            break
        msgs[j]["content"] = short
        info["shortened_data"] += 1
    # 3. 問題本身（留頭尾）/ the question itself, keeping head and tail
    over = total(msgs, tools) - budget
    q = msgs[last_user].get("content") if 0 <= last_user < len(msgs) else None
    if over > 0 and isinstance(q, str) and len(q) > 400:
        keep = max(200, len(q) - over * 2)
        msgs[last_user]["content"] = q[:keep // 2] + "\n……（中間過長已略過）……\n" + q[-keep // 2:]
        info["shortened_question"] = True
    info["after"] = total(msgs, tools)
    return msgs, info


def merge_system(messages: list[dict]) -> list[dict]:
    """把所有 system 訊息依序合併成開頭的一則。Qwen3.5 等模型的對話範本只接受開頭的 system 訊息，
    中間再出現就整個請求失敗（2026-11-17 實測：附加資料與安全提醒插在對話中間 → 引擎回 500）。
    Merge every system message, in order, into one leading message: chat templates such as Qwen3.5's reject
    a system message anywhere but first (a live HTTP 500 once data and reminders were inserted mid-conversation)."""
    parts, rest = [], []
    for m in messages:
        if m.get("role") == "system":
            c = m.get("content")
            if isinstance(c, list):
                c = "".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
            if isinstance(c, str) and c.strip():
                parts.append(c.strip())
        else:
            rest.append(m)
    if not parts:
        return rest
    return [{"role": "system", "content": "\n\n".join(parts)}, *rest]

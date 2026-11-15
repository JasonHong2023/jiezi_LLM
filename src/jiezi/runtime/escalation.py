"""執行期驗證器與分層轉交 v0（規格 escalation；add-gateway design D5、D6）。
Runtime verifiers and tiered escalation v0 (spec escalation; add-gateway design D5, D6).

驗證器只用不需要標準答案的檢查，絕不執行回答內容。
Verifiers use only checks that need no ground truth and never execute response content."""

from __future__ import annotations

import ast
import json
import re
from datetime import date
from pathlib import Path

from ..verify import tool_call

_CODE = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.S | re.I)
_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list,
               "object": dict, "null": type(None)}

RETRY_PROMPT = ("上一個回答沒有通過檢查：{error}\n請修正後重新回答，只輸出修正後的完整回答。\n"
                "The previous answer failed a check: {error}\nFix it and answer again with the full corrected answer only.")


def _type_ok(value, schema: dict) -> bool:
    t = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        return False
    if t is None:
        return True
    types = t if isinstance(t, list) else [t]
    for name in types:
        py = _JSON_TYPES.get(name)
        if py is None:
            return True  # 不認得的型別不擋 / unknown types are not enforced
        if name in ("integer", "number") and isinstance(value, bool):
            continue
        if isinstance(value, py):
            return True
    return False


def _calls_from_message(message: dict) -> list[tuple[str, dict]] | None:
    """OpenAI tool_calls 或文字中的 `[f(a=1)]`；沒有任何呼叫時回傳 None。
    OpenAI tool_calls or `[f(a=1)]` in text; None when there is no call at all."""
    out = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"arguments of {fn.get('name')!r} are not valid JSON: {exc.msg}") from exc
        if not isinstance(args, dict):
            raise ValueError(f"arguments of {fn.get('name')!r} must be a JSON object")
        out.append((fn.get("name") or "", args))
    if out:
        return out
    text = message.get("content") or ""
    if "[" not in text or "(" not in text:
        return None
    try:
        calls = tool_call.parse_calls(text)
    except tool_call.Unparsed:
        return None
    return [(name, args) for c in calls for name, args in c.items()]


def verify_tools(tools: list[dict], message: dict) -> dict:
    specs = {}
    for t in tools or []:
        fn = t.get("function") or t
        if fn.get("name"):
            specs[fn["name"]] = fn.get("parameters") or {}
    try:
        calls = _calls_from_message(message)
    except ValueError as exc:
        return {"check": "tool_schema", "status": "fail", "error": str(exc)}
    if calls is None:
        return {"check": "tool_schema", "status": "not_applicable"}
    errors = []
    for name, args in calls:
        if name not in specs:
            errors.append(f"unknown function {name!r} (available: {', '.join(sorted(specs)) or 'none'})")
            continue
        params = specs[name]
        props = params.get("properties") or {}
        for req in params.get("required") or []:
            if req not in args:
                errors.append(f"{name}: missing required parameter {req!r}")
        for k, v in args.items():
            if k not in props:
                errors.append(f"{name}: unknown parameter {k!r}")
            elif not _type_ok(v, props[k]):
                errors.append(f"{name}: parameter {k!r} does not match type {props[k].get('type')!r}")
    return {"check": "tool_schema", "status": "fail" if errors else "pass", "error": "; ".join(errors) or None,
            "calls": len(calls)}


def verify_code(content: str) -> dict:
    blocks = _CODE.findall(content or "")
    if not blocks:
        return {"check": "code_syntax", "status": "not_applicable"}
    for i, b in enumerate(blocks, 1):
        try:
            ast.parse(b)  # 只解析，不執行 / parse only, never run
        except SyntaxError as exc:
            return {"check": "code_syntax", "status": "fail",
                    "error": f"code block {i}: SyntaxError: {exc.msg} (line {exc.lineno})"}
    return {"check": "code_syntax", "status": "pass", "blocks": len(blocks)}


def verify(request: dict, message: dict) -> dict:
    """合併各項檢查：有任何失敗就是 fail；都不適用就是 not_applicable。
    Combine checks: any failure is fail; none applicable is not_applicable."""
    checks = []
    if request.get("tools"):
        checks.append(verify_tools(request["tools"], message))
    checks.append(verify_code(message.get("content") or ""))
    applicable = [c for c in checks if c["status"] != "not_applicable"]
    if not applicable:
        return {"status": "not_applicable", "checks": checks}
    failed = [c for c in applicable if c["status"] == "fail"]
    return {"status": "fail" if failed else "pass", "checks": checks,
            "error": "; ".join(c["error"] for c in failed) or None}


# 本機模型自己表示不會的說法（只看回答開頭附近，避免誤判引用的文字）
# Phrases where the local model says it can't answer (checked near the start, to avoid quoted text)
_UNSURE = re.compile(r"我不確定|我不知道|无法回答|無法回答|无法确定|無法確定|沒有足夠的資訊|没有足够的信息|"
                     r"I don't know|I do not know|I'm not sure|I am not sure|I cannot answer|I can't answer", re.I)


def needs_help(message: dict, finish_reason: str | None) -> str | None:
    """本機答案是否明顯需要求助（不需要標準答案）。回傳原因或 None。
    Whether the local answer obviously needs help (no ground truth needed). Return a reason or None."""
    if message.get("tool_calls"):
        return None
    text = (message.get("content") or "").strip()
    if not text:
        return "truncated" if finish_reason == "length" else "empty_answer"
    if _UNSURE.search(text[:200]):
        return "self_reported_unsure"
    return None


def retry_messages(messages: list[dict], answer: dict, error: str) -> list[dict]:
    prev = {"role": "assistant", "content": answer.get("content") or ""}
    if answer.get("tool_calls"):
        prev["content"] = prev["content"] or json.dumps(answer["tool_calls"], ensure_ascii=False)
    return [*messages, prev, {"role": "user", "content": RETRY_PROMPT.format(error=error)}]


class DailyCap:
    """每日雲端轉交次數（存在 var/runtime/cloud-YYYY-MM-DD.json）。 / Daily cloud escalation counter."""

    def __init__(self, directory: Path, limit: int, today=date.today):
        self.dir, self.limit, self.today = directory, limit, today

    def _path(self) -> Path:
        return self.dir / f"cloud-{self.today().isoformat()}.json"

    def used(self) -> int:
        p = self._path()
        try:
            return int(json.loads(p.read_text(encoding="utf-8"))["count"]) if p.exists() else 0
        except (OSError, ValueError, KeyError):
            return 0

    def available(self) -> bool:
        return self.used() < self.limit

    def take(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path().write_text(json.dumps({"count": self.used() + 1}) + "\n", encoding="utf-8")

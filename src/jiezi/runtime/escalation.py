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


_FENCE_END = re.compile(r"\s*(?:```)?\s*$")
_CALL_START = re.compile(r"\[\s*[A-Za-z_][\w.\-]*\s*\(")


def _trailing_calls(text: str) -> tuple[list[tuple[str, dict]], str] | None:
    """回答結尾的 `[f(a=1), ...]` → (呼叫, 前面的文字)；結尾不是呼叫就回傳 None。
    The `[f(a=1), ...]` that ends the answer → (calls, text before it); None when the answer does not end with one."""
    body = _FENCE_END.sub("", text)
    if not body.endswith("]"):
        return None
    for m in _CALL_START.finditer(body):           # 從最前面的候選開始，取第一個能完整解析到結尾的 / earliest full parse
        try:
            calls = tool_call.parse_calls(body[m.start():])
        except tool_call.Unparsed:
            continue
        if tool_call.extract_outermost_bracket_content(body[m.start():]) != body[m.start():]:
            continue                                # 解析到的不是延伸到結尾的那一段 / must reach the end
        return [(n, a) for c in calls for n, a in c.items()], body[:m.start()]
    return None


def text_calls_to_tool_calls(message: dict, tools: list[dict]) -> bool:
    """回答以 `[f(a=1)]` 結尾時，就地改成 OpenAI `tool_calls`（請教 Claude 走文字格式，用戶端只認 tool_calls）。
    2026-11-18 Hermes 兩次停住：文字 `[browser_navigate(...)]` 被當成最終回答；Claude 在呼叫前夾了自言自語
    （「Next sensible step... Output the function call.[browser_get_images()]」）。前面的文字是請教時漏出的思考，丟掉。
    函式名都在 tools 裡才轉。回傳有沒有轉。
    When the answer ends with `[f(a=1)]`, rewrite it in place as OpenAI tool_calls; any text before the call is leaked
    reasoning and is dropped. Only when every name is a listed tool. Returns whether it converted."""
    import uuid
    text = message.get("content")
    if not isinstance(text, str) or message.get("tool_calls"):
        return False
    found = _trailing_calls(text)
    if not found:
        return False
    calls, _ = found
    names = {(t.get("function") or t).get("name") for t in tools or []}
    if not calls or any(n not in names or not isinstance(a, dict) for n, a in calls):
        return False
    message["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:24]}", "type": "function",
                              "function": {"name": n, "arguments": json.dumps(a, ensure_ascii=False)}} for n, a in calls]
    message["content"] = None
    return True


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
            else:  # 巢狀物件、陣列項目、範圍、長度（add-strong-tool-calling 1.2）/ nested, items, ranges, lengths
                from .jsonout import validate
                errors += validate(v, props[k], f"{name}.{k}")
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


# ── 答案查核：回答裡的數字與「」引用要出現在附上的資料或使用者的話裡（使用者 2026-11-15）──
# Grounded check: numbers and quoted terms in the answer must appear in the attached data or the user's words.
_FW = str.maketrans("０１２３４５６７８９．，", "0123456789.,")
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_LIST = re.compile(r"^\s*\d{1,2}[.、)）]\s*", flags=re.M)        # 清單編號 / list numbering
_QUOTE = re.compile(r"[「『]([^」』\n]{2,20})[」』]")
_CN_DIGIT = {c: i for i, c in enumerate("零一二三四五六七八九")} | {"〇": 0, "兩": 2}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000, "萬": 10000, "億": 100000000}
_CN_RUN = re.compile(r"[零〇一二兩三四五六七八九十百千萬億]{1,12}")
MAX_UNSUPPORTED_SHOWN = 6


def _cn_value(run: str) -> list[str]:
    """中文數字 → 阿拉伯數字（「一九二七」→1927、「七十」→70、「一百五十」→150）。 / Chinese numerals → digits."""
    if all(c in _CN_DIGIT for c in run):
        return ["".join(str(_CN_DIGIT[c]) for c in run)] if len(run) >= 2 else [str(_CN_DIGIT[run])]
    total, section, num = 0, 0, 0
    for c in run:
        if c in _CN_DIGIT:
            num = _CN_DIGIT[c]
        elif c in ("萬", "億"):
            total += (section + num) * _CN_UNIT[c]
            section, num = 0, 0
        else:
            section += (num or 1) * _CN_UNIT[c]
            num = 0
    return [str(total + section + num)]


def _numbers(text: str, chinese: bool = False) -> set[str]:
    text = text.translate(_FW)
    out = {n.replace(",", "") for n in _NUM.findall(text)}
    if chinese:
        for run in _CN_RUN.findall(text):
            out.update(_cn_value(run))
    return out


def verify_grounded(message: dict, grounding: str | None) -> dict:
    """有附資料時才檢查；10 以下的整數與清單編號不算。 / Only with attached data; small integers and list numbers skip."""
    if not grounding:
        return {"check": "grounded", "status": "not_applicable"}
    answer = _LIST.sub("", (message.get("content") or "").split("\n---\n")[0])
    known = _numbers(grounding, chinese=True)
    plain = grounding.translate(_FW)
    missing = []
    for n in sorted(_numbers(answer), key=answer.translate(_FW).find):
        try:
            small = float(n) < 10 and "." not in n
        except ValueError:
            small = False
        if not small and n not in known and n not in plain:
            missing.append(n)
    missing += [f"「{q}」" for q in dict.fromkeys(_QUOTE.findall(answer)) if q not in grounding]
    if not missing:
        return {"check": "grounded", "status": "pass"}
    shown = "、".join(missing[:MAX_UNSUPPORTED_SHOWN])
    return {"check": "grounded", "status": "fail", "unsupported": missing,
            "error": f"回答中的 {shown} 在提供的資料裡找不到；請只根據資料回答，資料沒有提到的數字、年份和名稱不要寫"
                     f" / not found in the provided data: {shown}"}


# 要求寫程式的問題（平行取樣的對象）/ requests for code (sampled)
CODE_REQUEST = re.compile(r"寫(一個|一段|個)?.{0,12}(程式|函式|函數|腳本|script|function|code|class|類別)|"
                          r"(python|javascript|js|c\+\+|java|sql|bash)\s*(程式|函式|寫|code)|```", re.I)


def answer_key(message: dict, kind: str) -> str:
    """把答案正規化成比對用的鍵：工具呼叫比對函式與參數，程式比對去空白的程式碼。
    Normalize an answer for agreement: tool calls by name and arguments, code by whitespace-free code."""
    if kind == "tools":
        try:
            calls = _calls_from_message(message) or []
        except ValueError:
            return "invalid"
        return json.dumps(sorted(json.dumps([n, a], ensure_ascii=False, sort_keys=True, default=str) for n, a in calls),
                          ensure_ascii=False)
    if kind == "json":
        from . import jsonout
        return jsonout.key(message)
    blocks = _CODE.findall(message.get("content") or "")
    return re.sub(r"\s+", "", "\n".join(blocks)) or re.sub(r"\s+", "", message.get("content") or "")


def verify(request: dict, message: dict, grounding: str | None = None) -> dict:
    """合併各項檢查：有任何失敗就是 fail；都不適用就是 not_applicable。
    Combine checks: any failure is fail; none applicable is not_applicable."""
    checks = []
    if request.get("tools"):
        checks.append(verify_tools(request["tools"], message))
    if request.get("response_format") and not message.get("tool_calls"):  # add-json-output
        from . import jsonout
        try:
            sp = jsonout.spec(request)
        except jsonout.BadFormat:
            sp = None
        if sp:
            checks.append(jsonout.check(sp, message))
    tr = request.get("jiezi_translate")
    if isinstance(tr, dict) and tr.get("short") and not message.get("tool_calls"):  # add-translation：短文字的譯文檢查
        from .. import translate
        users = [m for m in request.get("messages") or [] if m.get("role") == "user" and isinstance(m.get("content"), str)]
        errors = translate.check(users[-1]["content"] if users else "", message.get("content") or "", tr.get("to"),
                                 translate.parse_glossary(tr.get("glossary")), ratio=False)
        checks.append({"check": "translation", "status": "fail" if errors else "pass", "error": "；".join(errors) or None})
    checks.append(verify_code(message.get("content") or ""))
    checks.append(verify_grounded(message, grounding))
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


UNSURE_MIN_CONTENT = 40


def needs_help(message: dict, finish_reason: str | None) -> str | None:
    """本機答案是否明顯需要求助（不需要標準答案）。回傳原因或 None。
    Whether the local answer obviously needs help (no ground truth needed). Return a reason or None."""
    if message.get("tool_calls"):
        return None
    text = (message.get("content") or "").strip()
    if not text:
        return "truncated" if finish_reason == "length" else "empty_answer"
    m = _UNSURE.search(text[:200])
    if m:
        # 前面已經答了一段內容、最後才補一句「我不確定」（0.6B 常這樣）就不算答不出來（2026-11-15 實測）
        # Substantial content before a trailing "not sure" (a 0.6B habit) does not count as unable to answer
        before = re.sub(r"\s+", "", text[:m.start()])
        if len(before) < UNSURE_MIN_CONTENT:
            return "self_reported_unsure"
    return None


RETRY_INLINE_CHARS, RETRY_PREV_CHARS = 2000, 800
RETRY_CUT = "\n……（文件後段已略過）……"


def retry_messages(messages: list[dict], answer: dict, error: str) -> list[dict]:
    prev = {"role": "assistant", "content": answer.get("content") or ""}
    if answer.get("tool_calls"):
        prev["content"] = prev["content"] or json.dumps(answer["tool_calls"], ensure_ascii=False)
    last = messages[-1] if messages else None
    if last and last.get("role") == "user" and isinstance(last.get("content"), str) \
            and len(last["content"]) > RETRY_INLINE_CHARS:
        # 問題很長（附了文件）：分成三則的話，上下文把關會先丟掉最舊的——也就是問題和文件本身——只剩「上一個回答沒過」，
        # 模型不知道在講什麼（2026-11-17 實測）。改成一則：問題在前、上一個回答與錯誤在後，超出時裁的是文件中段。
        # A long question (with a document): as three turns the context guard drops the oldest first, i.e. the question
        # and the document, leaving only "the previous answer failed". One message instead; overflow trims the middle.
        tail = f"[上一個回答 / previous answer]\n{prev['content'][:RETRY_PREV_CHARS]}\n\n{RETRY_PROMPT.format(error=error)}"
        parts = last["content"].rstrip().rsplit("\n\n", 1)
        body, question = (parts[0], parts[1].strip()) if len(parts) == 2 and len(parts[1]) <= 300 else (last["content"], "")
        # 原本剛好放得下：後面多加幾個字，就從文件尾端讓出幾個字，問題與上一個回答都留著
        # The original just fit: give up as many characters at the end of the document as are appended
        cut = len(tail) + len(RETRY_CUT) + 4
        if len(body) - cut >= 500:
            body = body[:len(body) - cut] + RETRY_CUT
        return [*messages[:-1], {"role": "user", "content": "\n\n".join(x for x in (body, question, tail) if x)}]
    return [*messages, prev, {"role": "user", "content": RETRY_PROMPT.format(error=error)}]


# ── 第 2 層：只要回饋（add-partial-escalation；依據 Self-Refine 的混合修正）/ Tier 2: feedback only ──
FEEDBACK_MAX_TOKENS, FEEDBACK_MAX_CHARS = 300, 1200
FEEDBACK_SYSTEM = ("你是審稿人。下面有一個問題、一個沒有通過自動檢查的答案，以及檢查的錯誤訊息。"
                   "請只指出答案錯在哪裡、該怎麼改，用條列、最多 5 點。不要寫出完整的正確答案，不要重寫整個回答。\n"
                   "You are a reviewer. Point out what is wrong with the answer and how to fix it, in at most five bullets. "
                   "Do not write the full corrected answer.")
FEEDBACK_RETRY = ("上一個回答沒有通過檢查 / the previous answer failed a check：{error}\n"
                  "審稿人的意見 / reviewer feedback：\n{feedback}\n"
                  "請依意見修正，只輸出修正後的完整回答。\nFix it accordingly and answer again with the full corrected answer only.")


def _answer_text(answer: dict) -> str:
    text = answer.get("content") or ""
    if answer.get("tool_calls"):
        text = text or json.dumps(answer["tool_calls"], ensure_ascii=False)
    return text


def feedback_request(request: dict, answer: dict, error: str) -> list[dict]:
    """給協助者的訊息：問題、可用的函式或格式、本機的答案、錯誤。 / What the helper sees."""
    users = [m for m in request.get("messages") or [] if m.get("role") == "user"]
    q = users[-1].get("content") if users else ""
    if isinstance(q, list):
        q = "\n".join(p.get("text", "") for p in q if isinstance(p, dict) and p.get("type") == "text")
    parts = [f"[問題 / Question]\n{q}"]
    if request.get("tools"):
        parts.append("[可用的函式 / Available functions]\n" + json.dumps(
            [t.get("function") or t for t in request["tools"]], ensure_ascii=False)[:4000])
    if request.get("response_format"):
        parts.append("[要求的輸出格式 / Required format]\n" + json.dumps(request["response_format"], ensure_ascii=False)[:4000])
    parts += [f"[沒有通過檢查的答案 / Failing answer]\n{_answer_text(answer)[:4000]}", f"[檢查的錯誤 / Check error]\n{error}"]
    return [{"role": "system", "content": FEEDBACK_SYSTEM}, {"role": "user", "content": "\n\n".join(parts)}]


def feedback_messages(messages: list[dict], answer: dict, error: str, feedback: str) -> list[dict]:
    return [*messages, {"role": "assistant", "content": _answer_text(answer)},
            {"role": "user", "content": FEEDBACK_RETRY.format(error=error, feedback=feedback.strip()[:FEEDBACK_MAX_CHARS])}]


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

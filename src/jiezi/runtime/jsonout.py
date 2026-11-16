"""一般 JSON 格式輸出（add-json-output）：OpenAI 的 `response_format`。
Structured JSON output for OpenAI's `response_format`.

支援 / Supported：
  {"type": "json_object"}                                         任何 JSON 物件 / any JSON object
  {"type": "json_schema", "json_schema": {"schema": {...}}}       符合 schema 的 JSON / JSON matching the schema
  {"type": "text"} 或不給                                          一般文字 / plain text

本機引擎（llama-server）會用文法限制輸出；gateway 另外自己解析、依 schema 檢查，沒過就重試、再轉交，
和工具呼叫走同一套分層。Claude 與雲端的回答常包在程式碼框或夾說明文字，所以先抽出 JSON 再檢查。
The local engine constrains output with a grammar; the gateway still parses and checks the schema itself and
retries or escalates on failure, like tool calls. Claude and cloud answers are often fenced or wrapped in prose,
so the JSON is extracted first.

schema 檢查是常用子集（type、enum、const、required、properties、additionalProperties、items、長度與大小、
anyOf／oneOf／allOf）；不認得的關鍵字不擋（`$ref`、`pattern`、`format` 不檢查）。
The validator covers a common subset; unknown keywords are not enforced (`$ref`, `pattern`, `format` are ignored)."""

from __future__ import annotations

import json
import re

MAX_SCHEMA_BYTES = 64 * 1024
MAX_DEPTH = 32
MAX_ERRORS = 5
_FENCE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.S)
_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict,
          "null": type(None)}
CONSULT_NOTE = ("[輸出格式 / Output format]\n只輸出一個 JSON 值，不要加任何說明文字，也不要用程式碼框。\n"
                "Output a single JSON value only: no commentary, no code fence.")


class BadFormat(ValueError):
    """`response_format` 寫錯（回 400）。 / A malformed `response_format` (HTTP 400)."""


def spec(body: dict) -> dict | None:
    """回傳 {"schema": dict | None}；不是 JSON 模式回 None；寫錯丟 BadFormat。
    Return {"schema": dict | None}, None when not in JSON mode; raise BadFormat when malformed."""
    rf = body.get("response_format")
    if rf is None:
        return None
    if not isinstance(rf, dict) or not isinstance(rf.get("type"), str):
        raise BadFormat("response_format must be an object with a type")
    kind = rf["type"]
    if kind == "text":
        return None
    if kind == "json_object":
        schema = rf.get("schema")  # llama-server 的寫法 / the llama-server spelling
    elif kind == "json_schema":
        js = rf.get("json_schema")
        schema = js.get("schema") if isinstance(js, dict) else None
        if not isinstance(schema, dict):
            raise BadFormat("response_format.json_schema.schema must be an object")
    else:
        raise BadFormat("response_format.type must be text, json_object or json_schema")
    if schema is not None:
        if not isinstance(schema, dict):
            raise BadFormat("the schema must be an object")
        if len(json.dumps(schema, ensure_ascii=False).encode("utf-8")) > MAX_SCHEMA_BYTES:
            raise BadFormat(f"the schema is larger than {MAX_SCHEMA_BYTES} bytes")
    return {"schema": schema}


def extract(text: str):
    """從回答抽出 JSON 值；找不到丟 ValueError。先整段、再程式碼框、最後找第一個完整的 {…} 或 […]。
    Extract the JSON value from an answer: whole text, then a code fence, then the first complete object or array."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty answer")
    try:
        return json.loads(text)
    except ValueError:
        pass
    for block in _FENCE.findall(text):
        try:
            return json.loads(block.strip())
        except ValueError:
            continue
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return dec.raw_decode(text, i)[0]
            except ValueError:
                continue
    raise ValueError("no JSON value found in the answer")


def _is(value, name: str) -> bool:
    py = _TYPES.get(name)
    if py is None:
        return True  # 不認得的型別不擋 / unknown types are not enforced
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    if name == "integer" and isinstance(value, float):
        return value.is_integer()
    return isinstance(value, py)


def validate(value, schema, path: str = "$", depth: int = 0) -> list[str]:
    """回傳錯誤訊息（空的表示通過）。 / Return error messages; empty means valid."""
    if schema is True or schema == {} or not isinstance(schema, dict):
        return [] if schema is not False else [f"{path}: not allowed"]
    if depth > MAX_DEPTH:
        return [f"{path}: nested deeper than {MAX_DEPTH}"]
    err: list[str] = []
    t = schema.get("type")
    if t is not None:
        names = t if isinstance(t, list) else [t]
        if not any(_is(value, n) for n in names):
            return [f"{path}: expected {'/'.join(map(str, names))}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        err.append(f"{path}: must be one of {json.dumps(schema['enum'], ensure_ascii=False)[:120]}")
    if "const" in schema and value != schema["const"]:
        err.append(f"{path}: must equal {json.dumps(schema['const'], ensure_ascii=False)[:80]}")
    if isinstance(value, dict):
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        for k in schema.get("required") or []:
            if k not in value:
                err.append(f"{path}: missing required property {k!r}")
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                err += validate(v, props[k], f"{path}.{k}", depth + 1)
            elif extra is False:
                err.append(f"{path}: unexpected property {k!r}")
            elif isinstance(extra, dict):
                err += validate(v, extra, f"{path}.{k}", depth + 1)
    elif isinstance(value, list):
        if isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            err.append(f"{path}: needs at least {schema['minItems']} items")
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            err.append(f"{path}: allows at most {schema['maxItems']} items")
        if isinstance(schema.get("items"), (dict, bool)):
            for i, v in enumerate(value):
                err += validate(v, schema["items"], f"{path}[{i}]", depth + 1)
                if len(err) >= MAX_ERRORS:
                    break
    elif isinstance(value, str):
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            err.append(f"{path}: shorter than {schema['minLength']} characters")
        if isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
            err.append(f"{path}: longer than {schema['maxLength']} characters")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        for key, bad in (("minimum", lambda a, b: a < b), ("maximum", lambda a, b: a > b),
                         ("exclusiveMinimum", lambda a, b: a <= b), ("exclusiveMaximum", lambda a, b: a >= b)):
            lim = schema.get(key)
            if isinstance(lim, (int, float)) and not isinstance(lim, bool) and bad(value, lim):
                err.append(f"{path}: violates {key} {lim}")
    for sub in schema.get("allOf") or []:
        err += validate(value, sub, path, depth + 1)
    for key in ("anyOf", "oneOf"):
        subs = schema.get(key)
        if isinstance(subs, list) and subs:
            ok = sum(1 for s in subs if not validate(value, s, path, depth + 1))
            if ok == 0 or (key == "oneOf" and ok != 1):
                err.append(f"{path}: matches {ok} of the {key} alternatives")
    return err[:MAX_ERRORS]


def check(sp: dict, message: dict) -> dict:
    """執行期檢查（和 verify_tools 同格式）。 / The runtime check, shaped like verify_tools."""
    try:
        value = extract(message.get("content") or "")
    except ValueError as exc:
        return {"check": "json_schema", "status": "fail", "error": f"not valid JSON: {exc}"}
    if sp.get("schema") is None:
        if not isinstance(value, dict):
            return {"check": "json_schema", "status": "fail", "error": "json_object needs a JSON object at the top level"}
        return {"check": "json_schema", "status": "pass", "error": None}
    errors = validate(value, sp["schema"])
    return {"check": "json_schema", "status": "fail" if errors else "pass", "error": "; ".join(errors) or None}


def normalize(message: dict) -> bool:
    """把回答換成只有 JSON 的文字（去掉程式碼框與說明）；抽不出來就不動。回傳有沒有成功。
    Replace the answer with bare JSON text (no fence, no prose); untouched when nothing can be extracted."""
    try:
        value = extract(message.get("content") or "")
    except ValueError:
        return False
    message["content"] = json.dumps(value, ensure_ascii=False)
    return True


def key(message: dict) -> str:
    """平行取樣比對用：鍵排序後的 JSON。 / For sample agreement: JSON with sorted keys."""
    try:
        return json.dumps(extract(message.get("content") or ""), ensure_ascii=False, sort_keys=True)
    except ValueError:
        return "invalid"


def convert_values(text: str, fn) -> str:
    """只轉換字串「值」（簡→繁、台灣用語），鍵不動，免得和 schema 對不上；不是 JSON 就整段轉。
    Convert string values only (keys stay as the schema names them); non-JSON text is converted whole."""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return fn(text)

    def walk(v):
        if isinstance(v, str):
            return fn(v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v
    return json.dumps(walk(value), ensure_ascii=False)

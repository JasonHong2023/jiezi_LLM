"""工具呼叫驗證器：移植 ACEBench normal 類別的規則判定（add-verifiers design D4）。
Tool-call verifier: a port of ACEBench's rule checker for the normal categories (add-verifiers design D4).

來源 / Source：github.com/chenchen0103/ACEBench @ 56dd66cf6439b0d9655ee1b353e4cd745c6f664e
  `eval_main.py`（extract_outermost_bracket_content、normal_single_turn_eval）、
  `model_inference/utils.py`（ast_parse、resolve_ast_by_type）、
  `model_eval/checker.py`（type_checker … normal_checker）、`model_eval/utils.py`（standardize_string 等）。
授權 / License：MIT, Copyright (c) Microsoft Corporation（全文見 docs/licenses.md 登記鍵 acebench）。
  MIT License, Copyright (c) Microsoft Corporation (full text: docs/licenses.md, key acebench).

與官方的差異（報表「已知差異」）/ Known differences from upstream (listed in reports):
1. 官方解析器對 BinOp 與 Lambda 使用 eval；這裡**絕不執行回答內容**：只計算純數字常數的 + − × ÷，其他一律 unparsed。
   Upstream evals BinOp and Lambda; here response content is **never executed**: only + − × ÷ of numeric
   constants are computed, anything else is unparsed.
2. 官方遇到未知型別名稱或 objectArray 分支會丟例外（程式中斷）；這裡改記為 wrong 並寫明原因。
   Upstream raises on unknown type names and in the objectArray branch (crash); here it is wrong with a reason."""

from __future__ import annotations

import ast
import operator
import re
from collections import Counter

VERSION = "acebench-normal@56dd66cf+jiezi.1"

PYTHON_TYPE_MAPPING = {
    "string": str, "integer": int, "float": float, "boolean": bool, "array": list, "tuple": list, "dict": dict,
    "any": str, "list": list, "object": dict, "objectArray": list, "list(string)": list, "list(enum)": list,
    "int": int, "enum": enumerate, "number": int,
}
PYTHON_NESTED_TYPE_CHECK_LIST = ["array", "tuple", "list(string)", "list(enum)", "object", "objectArray"]


class Unparsed(Exception):
    pass


class _Crash(Exception):
    """官方會中斷的情況。 / A case where upstream would crash."""


# ── 解析（不執行）/ Parsing (never executes) ─────────────────────────────────

def extract_outermost_bracket_content(text: str) -> str | None:
    start, depth = -1, 0
    for i, ch in enumerate(text):
        if ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0 and start != -1:
                return text[start:i + 1]
    return None


_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _number(node) -> int | float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _number(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        try:
            return _BIN[type(node.op)](_number(node.left), _number(node.right))
        except (ZeroDivisionError, OverflowError) as exc:
            raise Unparsed(f"arithmetic error: {exc}") from exc
    raise Unparsed(f"non-numeric expression: {ast.unparse(node)[:80]}")


def _dotted(func) -> str:
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


def _resolve_call(elem: ast.Call) -> dict:
    return {_dotted(elem.func): {kw.arg: _resolve(kw.value) for kw in elem.keywords}}


def _resolve(value):
    if isinstance(value, ast.Constant):
        return "..." if value.value is Ellipsis else value.value
    if isinstance(value, ast.UnaryOp):
        if isinstance(value.op, ast.USub) and isinstance(value.operand, ast.Constant):
            return -value.operand.value  # 與官方相同 / same as upstream
        raise Unparsed(f"unsupported unary expression: {ast.unparse(value)[:80]}")
    if isinstance(value, ast.List):
        return [_resolve(v) for v in value.elts]
    if isinstance(value, ast.Dict):
        if any(k is None for k in value.keys):
            raise Unparsed("dict unpacking")
        return {_resolve(k): _resolve(v) for k, v in zip(value.keys, value.values)}
    if isinstance(value, ast.BinOp):
        return _number(value)  # 官方用 eval；這裡只算純數字 / upstream evals; numbers only here
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Call):
        return {_dotted(value.func): {}} if not value.keywords else _resolve_call(value)
    if isinstance(value, ast.Tuple):
        return tuple(_resolve(v) for v in value.elts)
    if isinstance(value, ast.Subscript):
        return ast.unparse(value.value) + "[" + ast.unparse(value.slice) + "]"
    raise Unparsed(f"unsupported syntax: {type(value).__name__}")


def parse_calls(text: str) -> list[dict]:
    """回答 → [{函式名: {參數: 值}}]；無法解析就丟 Unparsed。 / Response → call list, or raise Unparsed."""
    raw = extract_outermost_bracket_content(text or "")
    if raw is None:
        raise Unparsed("no [...] in the response")
    try:
        tree = ast.parse(raw, mode="eval")
    except SyntaxError as exc:
        raise Unparsed(f"invalid syntax: {exc.msg}") from exc
    except (RecursionError, MemoryError, ValueError) as exc:
        raise Unparsed(f"unparseable: {type(exc).__name__}") from exc
    if not isinstance(tree.body, ast.List):
        raise Unparsed("not a list")
    out = []
    try:
        for elem in tree.body.elts:
            if not isinstance(elem, ast.Call):
                raise Unparsed("list element is not a call")
            out.append(_resolve(elem))
    except RecursionError as exc:
        raise Unparsed("nesting too deep") from exc
    if not all(isinstance(x, dict) for x in out):
        raise Unparsed("the output format does not meet the specified requirements")
    return out


# ── 判定（逐行移植）/ Checking (ported line by line) ─────────────────────────

def standardize_string(s: str) -> str:
    return re.sub(r"[ \,\.\/\-\_\*\^]", "", s).lower().replace("'", '"')


def _possible_type(possible_answer):
    return type(possible_answer) if possible_answer != "" else None


def _flatten_dates(d: dict) -> dict:
    return {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in d.items()}


def _fail(error, error_type):
    return {"valid": False, "error": error, "error_type": error_type}


def type_checker(param, value, possible_answer, expected_desc, expected_type, nested_type, func_name):
    result = {"valid": True, "error": [], "is_variable": False, "error_type": "type_error"}
    is_variable = False
    pa_type = _possible_type(possible_answer)
    if pa_type is not None and pa_type != expected_type:
        is_variable = True
    if value == "true":
        value = True
    if value == "false":
        value = False
    if type(value) == expected_type:
        if nested_type is None:
            result["is_variable"] = is_variable
            return result
        for pa_item in possible_answer:
            flag = True
            if type(pa_item) == list:
                for v in value:
                    if not type_checker(param, v, pa_item, str(nested_type), nested_type, None, func_name)["valid"]:
                        flag = False
                        break
            if flag:
                return {"valid": True, "error": [], "is_variable": is_variable}
        result["valid"] = False
        result["error"] = [f"Nested type checking failed for parameter {param!r}."]
    pa_type = _possible_type(possible_answer)
    if pa_type is not None and (type(value) == pa_type or possible_answer == value):
        result["is_variable"] = True
        return result
    result["valid"] = False
    result["error"] = [f"wrong type for parameter ({param}) of api ({func_name}): "
                       f"[expected: {expected_type}, real: {type(value)}]"]
    result["error_type"] = "type_error"
    return result


def string_checker(param, model_output, possible_answer, func_name):
    if standardize_string(possible_answer) not in standardize_string(model_output):
        return _fail([f"wrong value for parameter ({param}) of api ({func_name})"], "value_error:string")
    return {"valid": True, "error": []}


def list_checker(param, model_output, possible_answer, func_name):
    out = [standardize_string(x) if type(x) == str else x for x in list(model_output)]
    exp = [standardize_string(x) if type(x) == str else x for x in possible_answer]
    if out != exp:
        return _fail([f"wrong value for parameter ({param!r}) of api ({func_name})"], "value_error:list/tuple")
    return {"valid": True, "error": []}


def dict_checker(param, model_output, possible_answer, func_name):
    result = {"valid": True, "error": [], "error_type": "dict_checker:unclear"}
    if not isinstance(model_output, dict) or not isinstance(possible_answer, dict):
        return _fail([f"wrong type for parameter ({param}) of api ({func_name})"], "value_error")
    if len(model_output) != len(possible_answer):
        return _fail([f"wrong value for parameter ({param}) of api ({func_name})"], "value_error")
    for key, value in model_output.items():
        if value == "true":
            value = True
        if value == "false":
            value = False
        if key not in possible_answer:
            return _fail([f"wrong value for parameter ({param}) of api ({func_name})"], "value_error")
        expected = possible_answer[key]
        if isinstance(expected, dict):
            result = dict_checker(param, value, expected, func_name)
            if not result["valid"]:
                return result
        else:
            std_value = standardize_string(value) if type(value) == str else value
            std_exp = standardize_string(expected) if type(expected) == str else expected
            if str(std_exp) not in str(std_value):
                return _fail([f"wrong value for parameter ({param}) of api ({func_name})"], "value_error")
    return result


def list_dict_checker(param, model_output, possible_answers, func_name):
    result = {"valid": True, "error": [], "error_type": "list_dict_checker:unclear"}
    if len(model_output) != len(possible_answers):
        return _fail([f"wrong value for parameter ({param}) of api ({func_name})"], "value_error:list_dict_count")
    for out, exp in zip(model_output, possible_answers):
        result = dict_checker(param, out, exp, func_name)
        if not result["valid"]:
            return result
    return result


def simple_function_checker(func_description: dict, model_output: dict, possible_answers: dict) -> dict:
    result = {"valid": True, "error": [], "error_type": ""}
    possible_answer = list(possible_answers.values())[0]
    params_decl = func_description.get("parameters", {})
    if list(model_output.values())[0] == {} and params_decl == {}:
        return result
    if list(model_output.values())[0] == {} or params_decl == {}:
        return _fail([], "wrong_param")
    if possible_answer == params_decl["properties"]:
        return result
    if possible_answer == {}:
        return _fail([], "wrong_param")
    func_name = func_description["name"]
    if func_name not in model_output:
        return _fail([{"wrong_function": {"expected": func_name, "real": list(model_output)[0]}}],
                     "wrong_function_name")
    model_params = model_output[func_name]
    details = params_decl["properties"]
    for p in params_decl.get("required", []):
        if p not in model_params:
            return _fail(f"lack required_params: {p}", "lack_args")
    for param, value in model_params.items():
        if param not in details or param not in possible_answer:
            return _fail(f"addition params: {param}", "addition_args")
        desc = details[param].get("type")
        if desc not in PYTHON_TYPE_MAPPING:
            raise _Crash(f"unknown parameter type {desc!r} for {param}")
        expected_type, nested = PYTHON_TYPE_MAPPING[desc], None
        if desc in PYTHON_NESTED_TYPE_CHECK_LIST:
            try:
                nested_name = details[param]["items"]["type"]
            except (KeyError, TypeError):
                nested_name = "string" if "string" in desc else "enum" if "enum" in desc else "dict"
            if nested_name not in PYTHON_TYPE_MAPPING:
                raise _Crash(f"unknown item type {nested_name!r} for {param}")
            nested = PYTHON_TYPE_MAPPING[nested_name]
        if desc == "tuple" and type(value) == tuple:
            value = list(value)
        if desc == "float" and type(value) == int:
            value = float(value)
        tc = type_checker(param, value, possible_answer[param], desc, expected_type, nested, func_name)
        if not tc["valid"]:
            return _fail(tc["error"], tc["error_type"])
        if tc["is_variable"]:
            continue
        if expected_type == dict:
            r = dict_checker(param, value, possible_answer[param], func_name)
        elif expected_type == list and nested == dict:
            if desc == "objectArray":
                raise _Crash("objectArray branch (upstream indexes a dict result with [0])")
            r = list_dict_checker(param, value, possible_answer[param], func_name)
        elif expected_type == str:
            r = string_checker(param, value, possible_answer[param], func_name)
        elif expected_type == list:
            r = list_checker(param, value, possible_answer[param], func_name)
        else:
            continue
        if not r["valid"]:
            return _fail(r["error"], r["error_type"])
    return result


def _find_description(funcs, name):
    if isinstance(funcs, list):
        for f in funcs:
            if f["name"] in name:
                return f
        return None
    return funcs


def normal_checker(func_descriptions: list, model_output: list, possible_answers: dict) -> dict:
    if len(model_output) != len(possible_answers):
        return _fail(["The number of functions does not match the answer."], "wrong functions number")
    names = list(possible_answers.keys())
    answers = []
    for key, value in possible_answers.items():
        answers.append({re.sub(r"_\d+$", "", key): value})
    out_count = Counter(k for d in model_output for k in d)
    ans_count = Counter(k for d in answers for k in d)
    for name in out_count:
        if name not in ans_count:
            return _fail([f"extra function detected: {name}"], "function_mismatch")
    for name in ans_count:
        if name not in out_count:
            return _fail([f"missing function: {name}"], "function_mismatch")
    for name, count in out_count.items():
        if count != ans_count[name]:
            return _fail([f"incorrect count for function {name}"], "function_mismatch")
    result = {"valid": True}
    for i, ans in enumerate(answers):
        desc = _find_description(func_descriptions, names[i])
        if desc is None:
            raise _Crash(f"no function description for {names[i]}")
        found = False
        for out in model_output:
            if list(out)[0] == list(ans)[0]:
                result = simple_function_checker(desc, out, ans)
                if result["valid"]:
                    found = True
                    break
            else:
                result = _fail(["wrong_function"], "simple_function_checker:unclear")
        if found:
            continue
        if not result["valid"]:
            return result
    return result


def verify(item: dict, response: str) -> dict:
    """依 ACEBench normal 規則評分一題。 / Score one item with the ACEBench normal rules."""
    d = item["data"]
    try:
        calls = parse_calls(response)
    except Unparsed as exc:
        return {"status": "unparsed", "score": 0, "details": {"reason": str(exc)}, "verifier": VERSION}
    gts = d["ground_truth"] if isinstance(d["ground_truth"], list) else [d["ground_truth"]]
    first = None
    for gt in gts:
        try:
            r = normal_checker(d["functions"], calls, gt)
        except _Crash as exc:
            r = _fail([str(exc)], "upstream_would_crash")
        if r["valid"]:
            return {"status": "correct", "score": 1, "details": {"calls": calls}, "verifier": VERSION}
        first = first or r
    return {"status": "wrong", "score": 0,
            "details": {"calls": calls, "error": first.get("error"), "error_type": first.get("error_type")},
            "verifier": VERSION}

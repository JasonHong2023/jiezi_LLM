"""BFCL V4 AST 檢查器（add-strong-tool-calling task 2.1）：移植 Python/simple/multiple/parallel 的判定。
BFCL V4 AST checker: Python simple/multiple/parallel rules ported for the system-level tool check.

來源 / Source：github.com/ShishirPatil/gorilla @ 58f57e9124ea981403792dd51e00a6577e621fae
  `berkeley-function-call-leaderboard/bfcl_eval/eval_checker/ast_eval/ast_checker.py`
授權 / License：Apache-2.0（全文見 `src/jiezi/verify/data/BFCL-LICENSE.txt`；
  registered as `bfcl-code` in `docs/licenses.md`）。

與官方的差異（報表「已知差異」）/ Known differences from upstream：
1. 只移植 Python 型別；Java/JavaScript 的 type converter 不移植。
2. 回答永不執行：重用 ACEBench checker 的安全 AST parser（只算純數字常數的四則運算）。
3. 未知型別、缺欄位、標準答案與 function description 不相符時記 wrong 並寫原因，不讓程式中斷。
4. function name 的 `.` 正規化為 `_`（OpenAI tools 名稱限制）；standardize_string 也沿用同一規則。
5. `irrelevance` 用 no_call 旗標判定「沒有呼叫工具」為正確；其餘類別沒有 tool_calls 就是 wrong。
"""

from __future__ import annotations

from .tool_call import Unparsed, parse_calls, standardize_string

VERSION = "bfcl-v4@58f57e9+jiezi.1"

PYTHON_TYPE_MAPPING = {
    "string": str,
    "integer": int,
    "float": float,
    "boolean": bool,
    "array": list,
    "tuple": list,
    "dict": dict,
    "any": str,
}
PYTHON_NESTED_TYPE_CHECK_LIST = ("array", "tuple")


def _norm(name) -> str:
    return str(name).replace(".", "_")


def _normalize_calls(calls: list[dict]) -> list[dict]:
    return [{_norm(k): v for k, v in call.items()} for call in calls]


def _normalize_answer(answer: dict) -> dict:
    return {_norm(k): v for k, v in answer.items()}


def _ok() -> dict:
    return {"valid": True, "error": [], "error_type": ""}


def _fail(error, error_type: str) -> dict:
    return {"valid": False, "error": error, "error_type": error_type}


def find_description(func_descriptions: list[dict], name: str) -> dict | None:
    for desc in func_descriptions:
        if _norm(desc.get("name")) == _norm(name):
            return desc
    return None


def get_possible_answer_type(possible_answer: list) -> type | None:
    for answer in possible_answer or []:
        if answer != "":
            return type(answer)
    return None


def type_checker(param, value, possible_answer, expected_description, expected_type, nested_type) -> dict:
    """官方 type_checker；`is_variable` 表示答案用變數名稱代替實際值。"""
    result = {"valid": True, "error": [], "is_variable": False, "error_type": "type_error:simple"}
    answer_type = get_possible_answer_type(possible_answer)
    if answer_type is not None and answer_type is not expected_type:
        result["is_variable"] = True

    if type(value) is expected_type:
        if nested_type is None:
            return result
        for answer_item in possible_answer or []:
            flag = True
            if type(answer_item) is list:
                for value_item in value:
                    r = type_checker(param, value_item, answer_item, str(nested_type), nested_type, None)
                    if not r["valid"]:
                        flag = False
                        break
            if flag:
                return {"valid": True, "error": [], "is_variable": result["is_variable"]}
        result.update(valid=False, error=[
            f"Nested type checking failed for parameter {param!r}; "
            f"expected {expected_description} with inner type {nested_type.__name__}, got {value!r}."
        ], error_type="type_error:nested")

    answer_type = get_possible_answer_type(possible_answer)
    if answer_type is not None and type(value) is answer_type:
        return {"valid": True, "error": [], "is_variable": True, "error_type": ""}
    result.setdefault("error", []).append(
        f"Incorrect type for parameter {param!r}; expected {expected_description}, "
        f"got {type(value).__name__}, value {value!r}."
    )
    result["error_type"] = "type_error:simple"
    return result


def string_checker(param, model_output, possible_answer) -> dict:
    model = standardize_string(model_output) if isinstance(model_output, str) else model_output
    expected = [standardize_string(x) for x in possible_answer if isinstance(x, str)]
    if model not in expected:
        return _fail([f"Invalid value for parameter {param!r}: {model_output!r}; expected one of {possible_answer}."],
                     "value_error:string")
    return _ok()


def list_checker(param, model_output, possible_answer) -> dict:
    if not isinstance(model_output, (list, tuple)):
        return _fail([f"Wrong type for parameter {param!r}: expected list/tuple."], "value_error:list/tuple")
    model = [standardize_string(x) if isinstance(x, str) else x for x in model_output]
    for expected in possible_answer or []:
        if not isinstance(expected, (list, tuple)):
            continue
        std = [standardize_string(x) if isinstance(x, str) else x for x in expected]
        if model == std:
            return _ok()
    return _fail([f"Invalid value for parameter {param!r}: {model_output!r}; expected one of {possible_answer}."],
                 "value_error:list/tuple")


def _dict_answer_values(value) -> list:
    return value if isinstance(value, list) else [value]


def dict_checker(param, model_output, possible_answers) -> dict:
    if not isinstance(model_output, dict):
        return _fail([f"Wrong type for parameter {param!r}: expected dict."], "value_error:dict_key")
    last = _fail([f"No acceptable dict for parameter {param!r}."], "dict_checker:unclear")
    for possible_answer in possible_answers or []:
        if possible_answer == "" or not isinstance(possible_answer, dict):
            continue
        last = _fail([], "dict_checker:unclear")
        flag = True
        for key, value in model_output.items():
            if key not in possible_answer:
                last["error"].append(f"Unexpected dict key parameter: {key!r}.")
                last["error_type"] = "value_error:dict_key"
                flag = False
                break
            model = standardize_string(value) if isinstance(value, str) else value
            std = [standardize_string(x) if isinstance(x, str) else x
                   for x in _dict_answer_values(possible_answer[key])]
            if model not in std:
                last["error"].append(f"Invalid value for parameter {key!r}: {value!r}; expected one of {std}.")
                last["error_type"] = "value_error:dict_value"
                flag = False
                break
        for key, expected in possible_answer.items():
            if key not in model_output and "" not in _dict_answer_values(expected):
                last["error"].append(f"Missing dict key parameter: {key!r}.")
                last["error_type"] = "value_error:dict_key"
                flag = False
                break
        if flag:
            return _ok()
    return last


def list_dict_checker(param, model_output, possible_answers) -> dict:
    if not isinstance(model_output, (list, tuple)):
        return _fail([f"Wrong type for parameter {param!r}: expected list of dict."], "value_error:list_dict_count")
    last = _fail([f"No acceptable list of dict for parameter {param!r}."], "list_dict_checker:unclear")
    for candidate in possible_answers or []:
        if not isinstance(candidate, (list, tuple)):
            continue
        if len(model_output) != len(candidate):
            last = _fail(["Wrong number of dictionaries in the list."], "value_error:list_dict_count")
            continue
        flag = True
        for out, expected in zip(model_output, candidate):
            r = dict_checker(param, out, [expected])
            if not r["valid"]:
                last = r
                flag = False
                break
        if flag:
            return _ok()
    return last


def _expected_types(details: dict, param: str) -> tuple[object, type | None, type | None, dict | None]:
    try:
        description = details[param]["type"]
        expected = PYTHON_TYPE_MAPPING.get(description)
    except (KeyError, TypeError):
        return None, None, None, _fail([f"Missing type for parameter {param!r}."], "unsupported_type")
    if expected is None:
        return None, None, None, _fail([f"Unknown parameter type {description!r} for {param!r}."], "unsupported_type")
    nested = None
    if description in PYTHON_NESTED_TYPE_CHECK_LIST:
        try:
            nested_description = details[param]["items"]["type"]
        except (KeyError, TypeError):
            return None, None, None, _fail([f"Missing nested type for parameter {param!r}."], "unsupported_type")
        nested = PYTHON_TYPE_MAPPING.get(nested_description)
        if nested is None:
            return None, None, None, _fail([f"Unknown nested type {nested_description!r} for {param!r}."],
                                           "unsupported_type")
    return description, expected, nested, None


def simple_function_checker(func_description: dict | None, model_output: dict, possible_answer: dict) -> dict:
    if not isinstance(func_description, dict):
        return _fail(["No function description for the expected function."], "simple_function_checker:no_description")
    if not isinstance(model_output, dict) or len(model_output) != 1:
        return _fail(["Expected exactly one function call."], "simple_function_checker:wrong_count")
    if not isinstance(possible_answer, dict) or len(possible_answer) != 1:
        return _fail(["Expected exactly one ground-truth function."], "simple_function_checker:wrong_count")
    answer = next(iter(possible_answer.values()))
    if not isinstance(answer, dict):
        return _fail(["Malformed ground-truth parameters."], "simple_function_checker:malformed_answer")

    func_name = _norm(func_description.get("name", ""))
    if func_name not in model_output:
        return _fail([f"Function name {func_name!r} not found in model output."],
                     "simple_function_checker:wrong_func_name")
    model_params = model_output[func_name]
    if not isinstance(model_params, dict):
        return _fail([f"Wrong type for arguments of {func_name!r}."], "simple_function_checker:wrong_args")
    try:
        parameters = func_description.get("parameters") or {}
        details = parameters["properties"]
        required = parameters.get("required", [])
    except (KeyError, TypeError):
        return _fail([f"Malformed function description for {func_name!r}."], "simple_function_checker:malformed_description")

    for param in required:
        if param not in model_params:
            return _fail([f"Missing required parameter: {param!r}."], "simple_function_checker:missing_required")

    for param, value in model_params.items():
        if param not in details or param not in answer:
            return _fail([f"Unexpected parameter: {param!r}."], "simple_function_checker:unexpected_param")
        description, expected, nested, problem = _expected_types(details, param)
        if problem:
            return problem
        if description == "tuple" and type(value) is tuple:
            value = list(value)
        if description == "float" and type(value) is int:
            value = float(value)
        tc = type_checker(param, value, answer[param], description, expected, nested)
        if not tc["valid"]:
            return tc
        if not tc["is_variable"]:
            if expected is dict:
                r = dict_checker(param, value, answer[param])
            elif expected is list and nested is dict:
                r = list_dict_checker(param, value, answer[param])
            elif expected is str:
                r = string_checker(param, value, answer[param])
            elif expected is list:
                r = list_checker(param, value, answer[param])
            else:
                r = None
            if r is not None:
                if not r["valid"]:
                    return r
                continue
        if value not in answer[param]:
            return _fail([f"Invalid value for parameter {param!r}: {value!r}; expected one of {answer[param]}."],
                         "value_error:others")

    for param, expected_values in answer.items():
        if param not in model_params and "" not in _dict_answer_values(expected_values):
            return _fail([f"Optional parameter {param!r} was not provided and is not marked optional."],
                         "simple_function_checker:missing_optional")
    return _ok()


def parallel_function_checker_no_order(func_descriptions: list[dict], model_output: list[dict],
                                       possible_answers: list[dict]) -> dict:
    if len(model_output) != len(possible_answers):
        return _fail(["Wrong number of functions."], "parallel_function_checker_no_order:wrong_count")
    matched: set[int] = set()
    for i, answer in enumerate(possible_answers):
        if not isinstance(answer, dict) or len(answer) != 1:
            return _fail([f"Malformed ground-truth function at index {i}."],
                         "parallel_function_checker_no_order:malformed_answer")
        func_name = _norm(next(iter(answer)))
        desc = find_description(func_descriptions, func_name)
        errors = []
        matched_index = None
        for index, out in enumerate(model_output):
            if index in matched:
                continue
            r = simple_function_checker(desc, out, answer)
            if r["valid"]:
                matched_index = index
                break
            errors.append({f"Model Result Index {index}": {
                "sub_error": r["error"], "sub_error_type": r["error_type"],
                "model_output_item": out, "possible_answer_item": answer,
            }})
        if matched_index is None:
            errors.insert(0, f"Could not find a matching function among the unmatched model outputs for answer {i}.")
            return _fail(errors, "parallel_function_checker_no_order:cannot_find_match")
        matched.add(matched_index)
    return _ok()


def multiple_function_checker(func_descriptions: list[dict], model_output: list[dict],
                              possible_answers: list[dict]) -> dict:
    if len(model_output) != len(possible_answers) or not possible_answers:
        return _fail(["Wrong number of functions."], "multiple_function_checker:wrong_count")
    answer = possible_answers[0]
    if not isinstance(answer, dict) or len(answer) != 1:
        return _fail(["Malformed ground-truth function."], "multiple_function_checker:malformed_answer")
    desc = find_description(func_descriptions, _norm(next(iter(answer))))
    return simple_function_checker(desc, model_output[0], answer)


def verify(item: dict, response: str, no_call: bool = False) -> dict:
    """依 BFCL 類別評分一題。 / Score one item with the BFCL category rules."""
    d = item["data"]
    category = d.get("category") or item.get("stratum") or ""
    if category == "irrelevance":
        if no_call:
            return {"status": "correct", "score": 1,
                    "details": {"category": category, "no_call": True}, "verifier": VERSION}
        return {"status": "wrong", "score": 0,
                "details": {"category": category, "error": ["A tool call was made for an irrelevance item."],
                            "error_type": "irrelevance:unexpected_call"}, "verifier": VERSION}
    if no_call:
        return {"status": "wrong", "score": 0,
                "details": {"category": category, "error": ["No tool call was made."],
                            "error_type": "no_tool_call"}, "verifier": VERSION}

    try:
        calls = _normalize_calls(parse_calls(response))
    except Unparsed as exc:
        return {"status": "unparsed", "score": 0,
                "details": {"category": category, "reason": str(exc)}, "verifier": VERSION}

    funcs = d.get("functions") or []
    answers = [_normalize_answer(a) for a in (d.get("ground_truth") or []) if isinstance(a, dict)]
    try:
        if "parallel" in category:
            result = parallel_function_checker_no_order(funcs, calls, answers)
        elif "multiple" in category:
            result = multiple_function_checker(funcs, calls, answers)
        elif len(calls) != 1:
            result = _fail(["Wrong number of functions."], "simple_function_checker:wrong_count")
        elif not funcs or not answers:
            result = _fail(["Missing function descriptions or ground truth."], "simple_function_checker:no_data")
        else:
            result = simple_function_checker(funcs[0], calls[0], answers[0])
    except (AttributeError, IndexError, KeyError, RecursionError, TypeError, ValueError) as exc:
        result = _fail([f"checker error: {type(exc).__name__}: {exc}"], "checker_error")

    status = "correct" if result["valid"] else "wrong"
    return {"status": status, "score": 1 if result["valid"] else 0,
            "details": {"category": category, "calls": calls, "error": result["error"],
                        "error_type": result["error_type"]}, "verifier": VERSION}

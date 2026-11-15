"""ACEBench 官方判定程式逐題對照（add-verifiers 3.2）。
Side-by-side check against ACEBench's official checker (add-verifiers 3.2).

官方程式在解析時會 `eval` 回答內容（BinOp），因此**只在沙盒內執行**，每題一個獨立行程，
任何一題爆記憶體或逾時都不影響其他題。主程式只讀沙盒輸出的 JSON，不 unpickle、不執行任何東西。
The official parser `eval`s response content (BinOp), so it runs **only inside the sandbox**, one process per
case, so a memory blow-up or timeout in one case cannot affect the others. The host only reads JSON from the
sandbox; it never unpickles or executes anything.

官方檔案以鎖定 commit 的網址和 SHA-256 下載（與題庫同一 commit），快取在 var/verify/upstream/。
Official files are downloaded by pinned-commit URL and SHA-256 (same commit as the bank), cached in
var/verify/upstream/.

對照分類 / Comparison classes：
  agree             兩邊判定相同（對 / 錯）/ same verdict
  known_eval        官方執行運算式後判對、移植版不執行而判 unparsed（已知差異 1）/ known difference 1
  known_crash       官方中斷、移植版記為 upstream_would_crash（已知差異 2）/ known difference 2
  upstream_limit    官方在沙盒內逾時或超出資源（例如 'a'*10**9）/ upstream hit a sandbox limit
  disagree          其他不一致：需要修正移植版 / any other mismatch: the port needs fixing"""

from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path

from ..eval.bank import SourceFile
from ..eval.sources import fetch
from . import tool_call
from .sandbox import Limits, Sandbox

VERSION = "acebench-xcheck@1"
COMMIT = "56dd66cf6439b0d9655ee1b353e4cd745c6f664e"
_RAW = f"https://raw.githubusercontent.com/chenchen0103/ACEBench/{COMMIT}/"
UPSTREAM = {
    "eval_main.py": "30d87f1fa262e671d13ae0e14fc424ad6e9fd0bf0c489bdee49c47c92b1ef402",
    "model_inference/utils.py": "f490583893fa207609927de59864d70c59c2fca03164ce488963cd6c3e127dd8",
    "model_eval/utils.py": "3ea5ebabf5643b6649311f45ce1c76c3340340fd1e11435d1d5227fb2c46ddb0",
    "model_eval/checker.py": "9b023482f4c94674cbcad1f4a2e4321c63ef67b9ed87f20d90272672901a5ac2",
}
CASE_LIMITS = Limits(wall_s=10.0, memory_mib=512, tasks=16, output_mib=4, read_bytes=1 << 18)

# 沙盒內的驅動程式：照 eval_main.normal_single_turn_eval 的流程。
# In-sandbox driver following eval_main.normal_single_turn_eval.
HARNESS = r'''
import json, sys
sys.path.insert(0, "/work/up")
sys.setrecursionlimit(10000)
from model_inference.utils import decode_ast
from model_eval.utils import is_function_call_format_valid
from model_eval.checker import normal_checker
from extract import extract_outermost_bracket_content

c = json.load(open("case.json", encoding="utf-8"))
r = {}
try:
    raw = extract_outermost_bracket_content(c["content"])
    dec = decode_ast("jiezi-xcheck", raw)
except BaseException as e:
    r = {"valid": False, "error_type": "wrong_output_format", "error": (type(e).__name__ + ": " + str(e))[:300]}
else:
    if not is_function_call_format_valid(dec):
        r = {"valid": False, "error_type": "wrong_output_format", "error": "format"}
    else:
        gts = c["ground_truth"] if isinstance(c["ground_truth"], list) else [c["ground_truth"]]
        try:
            first = None
            for gt in gts:
                res = normal_checker(c["functions"], dec, gt, c["question"], c["category"])
                if res["valid"]:
                    r = {"valid": True}
                    break
                first = first or res
            else:
                r = {"valid": False, "error_type": first.get("error_type"), "error": str(first.get("error"))[:300]}
        except BaseException as e:
            r = {"valid": None, "crash": (type(e).__name__ + ": " + str(e))[:300]}
sys.stdout.write("XCHECK:" + json.dumps(r, ensure_ascii=False, default=str) + "\n")
'''

# ── 手寫案例（與 tests/test_verify_tool_call.py 同一套規則）/ Hand-written cases (same rules as the unit tests) ──
FUNCS = [
    {"name": "book_hotel", "description": "訂房",
     "parameters": {"type": "object", "required": ["city", "nights"], "properties": {
         "city": {"type": "string"}, "nights": {"type": "integer"}, "breakfast": {"type": "boolean"},
         "guests": {"type": "array", "items": {"type": "string"}},
         "prefs": {"type": "object", "properties": {"floor": {"type": "string"}}},
         "budget": {"type": "float"}}}},
    {"name": "get_weather", "description": "天氣",
     "parameters": {"type": "object", "required": ["city"], "properties": {"city": {"type": "string"}}}},
    {"name": "distractor", "description": "干擾", "arguments": {"type": "object", "properties": {}}},
]
F_INT = [{"name": "f", "description": "f", "parameters": {"type": "object", "required": ["a"],
                                                           "properties": {"a": {"type": "integer"}}}}]
GT = {"book_hotel": {"city": "台北", "nights": 2}}
GT_LIST = {"book_hotel": {"city": "台北", "nights": 1, "guests": ["Amy", "Bob"], "prefs": {"floor": "high"}}}
_LIST_OK = "[book_hotel(city='台北', nights=1, guests=['amy', 'bob'], prefs={'floor': 'High'})]"
_H = [
    ("correct", "[book_hotel(city='台北', nights=2)]", FUNCS, GT),
    ("text_around", "好的：[book_hotel(city='台北', nights=2)] 完成", FUNCS, GT),
    ("substring", "[book_hotel(city='台北市', nights=2)]", FUNCS, GT),
    ("normalize", "[get_weather(city='new-york')]", FUNCS, {"get_weather": {"city": "New York"}}),
    ("wrong_value", "[book_hotel(city='高雄', nights=2)]", FUNCS, GT),
    ("wrong_type", "[book_hotel(city='台北', nights='2')]", FUNCS, GT),
    ("lack_args", "[book_hotel(city='台北')]", FUNCS, GT),
    ("addition_args", "[book_hotel(city='台北', nights=2, breakfast=True)]", FUNCS, GT),
    ("function_mismatch", "[get_weather(city='台北')]", FUNCS, GT),
    ("functions_number", "[book_hotel(city='台北', nights=2), get_weather(city='台北')]", FUNCS, GT),
    ("parallel_suffix", "[get_weather(city='東京'), get_weather(city='台北')]", FUNCS,
     {"get_weather_1": {"city": "台北"}, "get_weather_2": {"city": "東京"}}),
    ("float_int_bool_str", "[book_hotel(city='台北', nights=1, budget=3000, breakfast='true')]", FUNCS,
     {"book_hotel": {"city": "台北", "nights": 1, "budget": 3000.0, "breakfast": True}}),
    ("list_dict_ok", _LIST_OK, FUNCS, GT_LIST),
    ("list_wrong", _LIST_OK.replace("'bob'", "'carl'"), FUNCS, GT_LIST),
    ("dict_wrong", _LIST_OK.replace("'High'", "'low'"), FUNCS, GT_LIST),
    ("alternatives", "[get_weather(city='taipei')]", FUNCS,
     [{"get_weather": {"city": "台北"}}, {"get_weather": {"city": "Taipei"}}]),
    ("unknown_type", "[f(a=1)]", [{"name": "f", "parameters": {"type": "object", "required": [],
                                                                "properties": {"a": {"type": "weird"}}}}],
     {"f": {"a": 1}}),
    ("no_call", "我無法完成", FUNCS, GT),
    ("unclosed", "[book_hotel(city='台北'", FUNCS, GT),
    ("not_calls", "[1, 2]", FUNCS, GT),
    ("arith_numeric", "[f(a=2*3+1)]", F_INT, {"f": {"a": 7}}),
    ("negative", "[f(a=-4)]", F_INT, {"f": {"a": -4}}),
    ("arith_name", "[f(a=x+1)]", F_INT, {"f": {"a": 1}}),
    ("arith_huge_string", "[f(a='a'*10**9)]", F_INT, {"f": {"a": 1}}),
    ("arith_pow", "[f(a=2**64)]", F_INT, {"f": {"a": 1}}),
    ("div_zero", "[f(a=1/0)]", F_INT, {"f": {"a": 1}}),
    ("lambda", "[f(a=lambda: 1)]", F_INT, {"f": {"a": 1}}),
    ("nested_call", "[f(a=__import__('os'))]", F_INT, {"f": {"a": 1}}),
    ("deep_nesting", "[f(a=" + "[" * 5000 + "]" * 5000 + ")]", F_INT, {"f": {"a": 1}}),
]
HAND_CASES = [{"id": f"hand/{name}", "content": content, "functions": funcs, "ground_truth": gt,
               "question": "", "category": "normal_single_turn_single_function"}
              for name, content, funcs, gt in _H]


def fetch_upstream(cache: Path, download=None) -> dict[str, str]:
    """下載並驗證官方檔案；回傳沙盒內的檔案表。 / Download and verify upstream files; return the sandbox file map."""
    kw = {"download": download} if download else {}
    files: dict[str, str] = {}
    for rel, sha in UPSTREAM.items():
        p = fetch(SourceFile(rel.replace("/", "__"), _RAW + rel, sha), cache, **kw)
        files[rel] = p.read_text(encoding="utf-8")
    # eval_main 匯入 pandas 等；只取出 extract_outermost_bracket_content（解析原始碼，不執行）。
    # eval_main imports pandas etc.; extract only extract_outermost_bracket_content (parsed, not run).
    tree = ast.parse(files.pop("eval_main.py"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "extract_outermost_bracket_content")
    return {f"up/{k}": v for k, v in files.items()} | {"up/extract.py": ast.unparse(fn) + "\n"}


def run_upstream(sb: Sandbox, upstream: dict[str, str], case: dict) -> dict:
    """在沙盒內對一題執行官方判定。 / Run the official checker on one case inside the sandbox."""
    files = {**upstream, "harness.py": HARNESS, "case.json": json.dumps(case, ensure_ascii=False)}
    res = sb.run_python(files, ["harness.py"], CASE_LIMITS)
    if res.limit:
        return {"valid": None, "limit": res.limit}
    for line in res.stdout.splitlines():
        if line.startswith("XCHECK:"):
            return json.loads(line[len("XCHECK:"):])
    return {"valid": None, "crash": f"exit {res.returncode}: {res.stderr.strip()[-300:]}"}


def classify(up: dict, mine: dict) -> str:
    if up.get("limit"):
        return "upstream_limit"
    ported_crash = (mine.get("details") or {}).get("error_type") == "upstream_would_crash"
    if up.get("valid") is None:
        return "known_crash" if ported_crash else "disagree"
    if up["valid"] == (mine["score"] == 1):
        return "agree"
    if up["valid"] and mine["status"] == "unparsed" and "expression" in str((mine.get("details") or {}).get("reason")):
        return "known_eval"
    return "disagree"


def compare(sb: Sandbox, upstream: dict[str, str], cases: list[dict]) -> dict:
    rows = []
    for c in cases:
        up = run_upstream(sb, upstream, c)
        mine = tool_call.verify({"data": c}, c["content"])
        rows.append({"id": c["id"], "class": classify(up, mine), "upstream": up,
                     "port": {"status": mine["status"], "error_type": (mine.get("details") or {}).get("error_type"),
                              "reason": (mine.get("details") or {}).get("reason")}})
    return {"counts": dict(Counter(r["class"] for r in rows)), "rows": rows}


def run_cases(run_dir: Path, items: list[dict], results: dict) -> list[dict]:
    """把一次執行的工具呼叫回答轉成對照案例。 / Turn a run's tool-call responses into comparison cases."""
    by_id = {(i["source"], i["id"]): i for i in items}
    out = []
    for rec in results.values():
        if rec["task"] != "tool" or rec["status"] not in ("pending_verifier", "correct", "wrong", "unparsed"):
            continue
        d = by_id[(rec["source"], rec["id"])]["data"]
        out.append({"id": rec["key"], "content": rec.get("content") or "", "functions": d["functions"],
                    "ground_truth": d["ground_truth"], "question": d.get("question", ""),
                    "category": d.get("category", "normal")})
    return out


def to_markdown(rep: dict) -> str:
    lines = [f"# ACEBench 官方判定對照 / Side-by-side with the official checker", "",
             f"- 官方 commit / upstream: `{rep['commit']}`；移植版 / port: `{rep['port']}`；"
             f"沙盒 / sandbox: `{rep['sandbox']}`；對照 / xcheck: `{rep['version']}`", ""]
    for name, part in rep["parts"].items():
        lines += [f"## {name}", "", "| 分類 / Class | 題數 / Count |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(part["counts"].items())]
        odd = [r for r in part["rows"] if r["class"] != "agree"]
        if odd:
            lines += ["", "| id | 分類 / Class | 官方 / Upstream | 移植版 / Port |", "|---|---|---|---|"]
            for r in odd:
                up = json.dumps(r["upstream"], ensure_ascii=False).replace("|", "\\|")[:160]
                pt = f"{r['port']['status']} {r['port']['error_type'] or r['port']['reason'] or ''}".replace("|", "\\|")
                lines.append(f"| `{r['id'][:60]}` | {r['class']} | {up} | {pt[:120]} |")
        lines.append("")
    return "\n".join(lines)

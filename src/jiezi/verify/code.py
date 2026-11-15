"""程式驗證器：依 evalplus 判定 HumanEval+ / MBPP+（規格 verifiers：Code Verifier；design D3）。
Code verifier: HumanEval+ / MBPP+ judged the evalplus way (spec verifiers: Code Verifier; design D3).

來源 / Source：github.com/evalplus/evalplus v0.3.1（e5d0ed0b）
  `evalplus/eval/__init__.py`（unsafe_execute、untrusted_check；檔頭 MIT, Copyright (c) OpenAI）、
  `evalplus/eval/_special_oracle.py`、`evalplus/evaluate.py`（get_groundtruth、check_correctness）、
  `evalplus/gen/util/__init__.py`（trusted_exec）、`evalplus/data/mbpp.py`（mbpp_deserialize_inputs）、
  `evalplus/config.py`（時間係數 4.0、最低 1.0 秒）。授權 Apache-2.0（repo）＋ MIT（OpenAI 檔頭）；見 docs/licenses.md。

流程 / Flow：
1. 期望輸出：標準解答在沙盒內執行，輸出以 pickle 存成**不透明位元組**（主程式從不 unpickle），並回傳耗時。
   Expected outputs: the canonical solution runs in the sandbox; outputs are kept as **opaque pickle bytes**
   (the host never unpickles) together with timings.
2. 判定：候選程式與期望輸出一起放進沙盒，比對結果以 JSON 回傳。base 與 plus 分開，`score` = base 與 plus 都通過。
   Judging: the candidate and the expected bytes go into the sandbox; results come back as JSON. base and plus are
   separate; `score` = both pass.

與官方的差異 / Known differences：
- 沙盒內只有標準函式庫：`np.allclose` 以等價的純 Python 實作（rtol=1e-7、equal_nan=False）。
  The sandbox has the stdlib only: `np.allclose` is reimplemented in pure Python (rtol=1e-7, equal_nan=False).
- 回答若沒有 import，會補上題目提示中的 import 行（evalplus 的 sanitize 不補）。
  When the response lacks imports, the import lines of the item prompt are prepended (evalplus's sanitize does not).
- 與官方相同的限制：候選程式和比對程式在同一個程序，刻意作弊的程式可以竄改結果；這裡假設模型不是對抗者。
  Same limitation as upstream: candidate and checker share a process, so deliberately adversarial code could forge
  results; the model is assumed not to be adversarial."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .sandbox import Limits, Sandbox, SandboxUnavailable

VERSION = "evalplus@0.3.1+jiezi.1"
GT_TIME_LIMIT_FACTOR = 4.0
MIN_TIME_LIMIT = 1.0
TASK_TIMEOUT_CAP_S = 60.0

# evalplus/data/mbpp.py mbpp_deserialize_inputs 的分組（逐字移植）/ groups ported verbatim
_MBPP_TUPLE_EACH = {2, 116, 132, 143, 222, 261, 273, 394, 399, 421, 424, 429, 470, 560, 579, 596, 616, 630, 726,
                    740, 744, 809}
_MBPP_TUPLE_NESTED = {63, 64, 70, 94, 120, 237, 272, 299, 400, 409, 417, 438, 473, 614, 780}
_MBPP_FIRST_LIST_OF_TUPLES = {75, 413, 444, 753}
_MBPP_SECOND_TUPLE = {106, 750}
_MBPP_FIRST_TUPLE = {250, 405, 446, 617, 720, 763, 808}
_MBPP_TUPLE_NESTED_THEN_EACH = {259, 401, 445}
_MBPP_ALL_TUPLE = {580, 615, 791}

# 沙盒內執行的程式（只用標準函式庫）。 / Runs inside the sandbox (stdlib only).
HARNESS = r'''
import contextlib, copy, io, json, math, os, pickle, signal, sys, time

MBPP_OUTPUT_NOT_NONE_TASKS = ["check_str", "text_match_three", "text_starta_endb"]
MBPP_OUTPUT_SET_EQ_TASKS = ["similar_elements", "find_char_long", "common_in_nested_lists", "extract_singly",
                            "larg_nnum", "intersection_array", "find_dissimilar", "Diff"]

def _surface_Area(base_edge, height):
    slant_height = math.sqrt((base_edge / 2) ** 2 + height**2)
    return round(base_edge**2 + 4 * (base_edge * slant_height) / 2)

def _digit_distance_nums(num1, num2):
    a, b = str(num1), str(num2)
    n = max(len(a), len(b))
    a, b = a.zfill(n), b.zfill(n)
    return sum(abs(int(x) - int(y)) for x, y in zip(a, b))

def _poly(xs, x):
    return sum([coeff * math.pow(x, i) for i, coeff in enumerate(xs)])

def deserialize(task_num, inputs, groups):
    g = {k: set(v) for k, v in groups.items()}
    if task_num is None:
        return inputs
    if task_num in g["tuple_each"]:
        return [[tuple(lst) for lst in inp] for inp in inputs]
    if task_num in g["tuple_nested"]:
        return [[[tuple(lst) for lst in lst_lst] for lst_lst in inp] for inp in inputs]
    if task_num in g["first_list_of_tuples"]:
        return [[[tuple(lst) for lst in inp[0]]] + [inp[1]] for inp in inputs]
    if task_num in g["second_tuple"]:
        return [[inp[0]] + [tuple(inp[1])] for inp in inputs]
    if task_num == 115:
        return [[[set(item) if isinstance(item, list) and len(item) else {} for item in inp[0]]] for inp in inputs]
    if task_num == 124:
        return [(float(inp[0]), complex(inp[1])) for inp in inputs]
    if task_num in g["first_tuple"]:
        return [[tuple(inp[0])] + [inp[1]] for inp in inputs]
    if task_num in g["tuple_nested_then_each"]:
        m = [[[tuple(lst) for lst in lst_lst] for lst_lst in inp] for inp in inputs]
        return [[tuple(lst) for lst in inp] for inp in m]
    if task_num == 278:
        m = [[[tuple(item) if isinstance(item, list) else item for item in inp[0]]] for inp in inputs]
        return [[tuple(lst) for lst in inp] for inp in m]
    if task_num == 307:
        return [[tuple(inp[0])] + [inp[1], inp[2]] for inp in inputs]
    if task_num == 722:
        return [[{key: tuple(value) for key, value in inp[0].items()}] + inp[1:] for inp in inputs]
    if task_num == 252:
        return [[complex(inp[0])] for inp in inputs]
    if task_num in g["all_tuple"]:
        def t(x):
            return tuple(t(i) for i in x) if isinstance(x, list) else x
        return [t(inp) for inp in inputs]
    return inputs

class _Timeout(BaseException):
    pass

def _alarm(signum, frame):
    raise _Timeout()

@contextlib.contextmanager
def time_limit(seconds):
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)

@contextlib.contextmanager
def swallow_io():
    s = io.StringIO()
    with contextlib.redirect_stdout(s), contextlib.redirect_stderr(s):
        yield

def is_floats(x):
    if isinstance(x, float):
        return True
    if isinstance(x, (list, tuple)) and x:
        return all(isinstance(i, float) for i in x)
    return False

def _flat(x):
    if isinstance(x, (list, tuple)):
        out = []
        for i in x:
            out.extend(_flat(i))
        return out
    return [x]

def allclose(out, exp, rtol, atol):
    """np.allclose(out, exp, rtol, atol) 的純 Python 版本（形狀需一致；NaN 不相等）。"""
    a, b = _flat(out), _flat(exp)
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        x, y = complex(x), complex(y)
        if any(math.isnan(v) for v in (x.real, x.imag, y.real, y.imag)):
            return False
        if math.isinf(abs(x)) or math.isinf(abs(y)):
            if x != y:
                return False
            continue
        if not abs(x - y) <= atol + rtol * abs(y):
            return False
    return True

def run_expected(p):
    g = {}
    exec(p["code"], g)
    fn = g[p["entry_point"]]
    res = {}
    for part in ("base", "plus"):
        rets, times = [], []
        for inp in p["inputs"][part]:
            inp = copy.deepcopy(inp)
            t0 = time.time()
            rets.append(fn(*inp))
            times.append(time.time() - t0)
        if p["output_not_none"]:
            rets = [i is not None for i in rets]
        res[part] = {"out": rets, "time": times}
    with open("expected.pkl", "wb") as fh:
        pickle.dump({k: v["out"] for k, v in res.items()}, fh)
    return {k: v["time"] for k, v in res.items()}

def check(p, inputs, expected, time_limits):
    dataset, entry_point, atol = p["dataset"], p["entry_point"], p["atol"]
    details, stat = [], "fail"
    try:
        g = {}
        with swallow_io():
            exec(p["code"], g)
            fn = g[entry_point]
        for i, inp in enumerate(inputs):
            try:
                with time_limit(time_limits[i]):
                    with swallow_io():
                        out = fn(*inp)
                exp = expected[i]
                exact_match = out == exp
                if dataset == "mbpp":
                    if "are_equivalent" == entry_point:
                        exact_match = exact_match or True
                    elif "sum_div" == entry_point:
                        exact_match = exact_match or out == 0
                    elif "surface_Area" == entry_point:
                        exact_match = exact_match or abs(out - _surface_Area(*inp)) <= atol
                    elif "digit_distance_nums" == entry_point:
                        exact_match = exact_match or out == _digit_distance_nums(*inp)
                    elif entry_point in MBPP_OUTPUT_SET_EQ_TASKS:
                        exact_match = set(out) == set(exp)
                    elif entry_point in MBPP_OUTPUT_NOT_NONE_TASKS:
                        exact_match = (out == exp) if isinstance(out, bool) else exp == (out is not None)
                if dataset == "humaneval" and "find_zero" == entry_point:
                    assert abs(_poly(*inp, out)) <= atol
                    details.append(True)
                    continue
                tol = atol
                if tol == 0 and is_floats(exp):
                    tol = 1e-6
                if not exact_match and tol != 0:
                    assert type(out) == type(exp)
                    if isinstance(exp, (list, tuple)):
                        assert len(out) == len(exp)
                    assert allclose(out, exp, 1e-07, tol)
                else:
                    assert exact_match
            except _Timeout:
                details.append(False)
                return "timeout", details
            except BaseException:
                details.append(False)
                continue
            details.append(True)
        stat = "pass"
    except BaseException:
        stat = "fail"
    if stat == "pass" and (len(details) != len(inputs) or not all(details)):
        stat = "fail"
    return stat, details

def main():
    p = json.load(open("payload.json"))
    groups = p["groups"]
    inputs = {k: deserialize(p["task_num"], v, groups) for k, v in p["inputs"].items()}
    p["inputs"] = inputs
    if p["mode"] == "expected":
        result = {"times": run_expected(p)}
    else:
        with open("expected.pkl", "rb") as fh:
            expected = pickle.load(fh)
        result = {}
        for part in ("base", "plus"):
            tl = [max(p["min_time_limit"], p["factor"] * t) for t in p["ref_time"][part]]
            stat, det = check(p, inputs[part], expected[part], tl)
            result[part] = {"status": stat, "passed": sum(det), "total": len(inputs[part])}
    sys.__stdout__.write("\n@@JIEZI_RESULT@@" + json.dumps(result) + "\n")
    sys.__stdout__.flush()

main()
'''

_FENCE = re.compile(r"```(?:python|py|Python)?[ \t]*\n(.*?)```", re.S)


def extract_code(response: str, entry_point: str) -> tuple[str, list[str]]:
    """從回答取出程式碼；回傳 (程式碼, 註記)。 / Extract code from the response; return (code, notes)."""
    text = re.sub(r"<think>.*?</think>\n?", "", response or "", flags=re.S)  # 保留縮排 / keep indentation
    notes = []
    blocks = _FENCE.findall(text)
    if blocks:
        with_def = [b for b in blocks if re.search(rf"\bdef\s+{re.escape(entry_point)}\s*\(", b)]
        code = with_def[-1] if with_def else blocks[0]
    else:
        code = text
        notes.append("no code block; using the whole response")
    return code, notes


def build_solution(item: dict, response: str) -> tuple[str, list[str]]:
    d = item["data"]
    code, notes = extract_code(response, d["entry_point"])
    if not re.search(rf"\bdef\s+{re.escape(d['entry_point'])}\s*\(", code):
        notes.append("no definition of the entry point; treated as a completion of the prompt")
        code = d["prompt"] + code
    imports = [ln for ln in d["prompt"].splitlines() if re.match(r"^(import|from)\s+\w", ln)]
    missing = [ln for ln in imports if ln not in code]
    if missing:
        notes.append("prepended prompt imports")
        code = "\n".join(missing) + "\n" + code
    return code, notes


def _dataset(item: dict) -> str:
    return "mbpp" if item["data"]["task_id"].startswith("Mbpp/") else "humaneval"


def _task_num(item: dict) -> int | None:
    return int(item["data"]["task_id"].split("/")[-1]) if _dataset(item) == "mbpp" else None


def _groups() -> dict:
    return {"tuple_each": sorted(_MBPP_TUPLE_EACH), "tuple_nested": sorted(_MBPP_TUPLE_NESTED),
            "first_list_of_tuples": sorted(_MBPP_FIRST_LIST_OF_TUPLES), "second_tuple": sorted(_MBPP_SECOND_TUPLE),
            "first_tuple": sorted(_MBPP_FIRST_TUPLE), "tuple_nested_then_each": sorted(_MBPP_TUPLE_NESTED_THEN_EACH),
            "all_tuple": sorted(_MBPP_ALL_TUPLE)}


def _item_key(item: dict) -> str:
    blob = json.dumps(item["data"], sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob + VERSION.encode()).hexdigest()[:24]


def _parse_result(stdout: str) -> dict | None:
    marker = stdout.rfind("@@JIEZI_RESULT@@")
    if marker < 0:
        return None
    try:
        return json.loads(stdout[marker + len("@@JIEZI_RESULT@@"):].splitlines()[0])
    except (json.JSONDecodeError, IndexError):
        return None


class CodeVerifier:
    def __init__(self, sandbox: Sandbox, cache_dir: Path):
        self.sb = sandbox
        self.cache = cache_dir

    def _payload(self, item: dict, code: str, mode: str, ref_time: dict | None = None) -> str:
        d = item["data"]
        return json.dumps({
            "mode": mode, "code": code, "entry_point": d["entry_point"], "dataset": _dataset(item),
            "task_num": _task_num(item), "groups": _groups(), "atol": d.get("atol") or 0,
            "inputs": {"base": d["base_input"], "plus": d["plus_input"]},
            "output_not_none": d["entry_point"] in ("check_str", "text_match_three", "text_starta_endb"),
            "ref_time": ref_time, "factor": GT_TIME_LIMIT_FACTOR, "min_time_limit": MIN_TIME_LIMIT,
        })

    def expected(self, item: dict) -> tuple[bytes, dict]:
        """標準解答的期望輸出（不透明 pickle 位元組）與耗時，快取於 var/verify/expected/。
        Canonical expected outputs (opaque pickle bytes) and timings, cached in var/verify/expected/."""
        key = _item_key(item)
        pkl, meta = self.cache / f"{key}.pkl", self.cache / f"{key}.json"
        if pkl.exists() and meta.exists():
            return pkl.read_bytes(), json.loads(meta.read_text(encoding="utf-8"))
        d = item["data"]
        code = d["prompt"] + d["canonical_solution"]
        r = self.sb.run_python({"harness.py": HARNESS, "payload.json": self._payload(item, code, "expected")},
                               ["harness.py"], Limits(wall_s=120, memory_mib=2048), collect=["expected.pkl"])
        res = _parse_result(r.stdout)
        if r.returncode != 0 or not res or "expected.pkl" not in r.files:
            raise RuntimeError(f"canonical solution failed for {d['task_id']}: rc={r.returncode} "
                               f"limit={r.limit} {r.stderr.strip()[-300:]}")
        self.cache.mkdir(parents=True, exist_ok=True)
        pkl.write_bytes(r.files["expected.pkl"])
        meta.write_text(json.dumps(res["times"]), encoding="utf-8")
        return r.files["expected.pkl"], res["times"]

    def verify(self, item: dict, response: str) -> dict:
        ok, reason = self.sb.available()
        if not ok:
            return {"status": "pending_verifier", "score": None, "details": {"reason": reason}, "verifier": VERSION}
        code, notes = build_solution(item, response)
        try:
            exp_bytes, times = self.expected(item)
        except (RuntimeError, SandboxUnavailable) as exc:
            return {"status": "pending_verifier", "score": None, "details": {"reason": str(exc)}, "verifier": VERSION}
        limits = [max(MIN_TIME_LIMIT, GT_TIME_LIMIT_FACTOR * t) for part in ("base", "plus") for t in times[part]]
        wall = min(TASK_TIMEOUT_CAP_S * 2, sum(limits)) + 10
        r = self.sb.run_python({"harness.py": HARNESS, "expected.pkl": exp_bytes,
                                "payload.json": self._payload(item, code, "check", times)},
                               ["harness.py"], Limits(wall_s=wall))
        res = _parse_result(r.stdout)
        details = {"notes": notes, "returncode": r.returncode, "limit": r.limit,
                   "code_sha256": hashlib.sha256(code.encode()).hexdigest()[:16]}
        if not res:
            status = "timeout" if r.limit == "timeout" else "resource_limit" if r.limit else "wrong"
            details["stderr_tail"] = r.stderr.strip()[-300:]
            return {"status": status, "score": 0,
                    "details": {**details, "base_pass": False, "plus_pass": False}, "verifier": VERSION}
        base_ok, plus_ok = res["base"]["status"] == "pass", res["plus"]["status"] == "pass"
        details.update(base_pass=base_ok, plus_pass=plus_ok, base=res["base"], plus=res["plus"])
        ok = base_ok and plus_ok
        return {"status": "correct" if ok else "wrong", "score": int(ok), "details": details, "verifier": VERSION}

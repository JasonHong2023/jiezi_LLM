"""複習資料（add-sft-round2）：凍結核心自己對程式題作答，只收在沙盒裡通過測試的回答，混入訓練避免遺忘。
Replay data (add-sft-round2): the frozen core answers coding problems; only answers that pass their tests in the
sandbox are kept and mixed into training so the round does not forget existing skills.

來源 / Source：MBPP（Google Research，CC BY 4.0），github.com/google-research/google-research
`mbpp/mbpp.jsonl` @ f82046ba（2022-03-31）。只用 prompt（1–10）、validation（511–600）、train（601–974）；
test（11–510）是評測用的，不取（MBPP+ 評測題也出自 test）。使用者 2026-11-18 同意下載。
Only the prompt, validation and train splits are used; the test split (11–510) is the evaluation's and is never
taken."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

from ..errors import JieziError

MBPP_COMMIT = "f82046ba5aabbbb427dbfd38a254d26bff08b533"
MBPP_URL = f"https://raw.githubusercontent.com/google-research/google-research/{MBPP_COMMIT}/mbpp/mbpp.jsonl"
MBPP_SHA256 = "ccf64ceae9c5403bf50a044cb6d505bfd2a2963ee58338ba268fd65beab92a9f"
MBPP_LICENSE = "CC BY 4.0 (MBPP © Google Research; answers: local-model-output, Qwen3.5 Apache-2.0)"
TEST_SPLIT = range(11, 511)                  # 評測用，永不取用 / evaluation split, never used
PROMPT = ("請用 Python 寫一個函式解決以下問題。只輸出完整的程式碼，放在一個 ```python 程式碼區塊中，不要解釋。\n\n"
          "問題：{text}\n\n程式要通過這些測試：\n{tests}")
MAX_TOKENS = 768


def mbpp_path(root: Path) -> Path:
    return root / "var" / "datasets" / "mbpp" / "mbpp.jsonl"


def fetch_mbpp(root: Path, opener=urllib.request.urlopen) -> Path:
    """下載（已有且雜湊相符就略過）並核對 sha256。 / Download unless present, and check the sha256."""
    path = mbpp_path(root)
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == MBPP_SHA256:
        return path
    with opener(MBPP_URL, timeout=60) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != MBPP_SHA256:
        raise JieziError("MBPP download does not match the pinned sha256; refusing to use it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def problems(path: Path) -> list[dict]:
    """非 test 的題目。 / The non-test problems."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        p = json.loads(line)
        if p["task_id"] in TEST_SPLIT:
            continue
        out.append(p)
    return out


def prompt_of(p: dict) -> str:
    return PROMPT.format(text=p["text"].strip(), tests="\n".join(p["test_list"]))


def program(p: dict, code: str) -> str:
    """要在沙盒裡跑的程式：回答的程式碼、題目的前置程式、所有測試（含 challenge）。
    The sandboxed program: the answer, the setup code and every test (challenge tests included)."""
    tests = list(p["test_list"]) + list(p.get("challenge_test_list") or [])
    return "\n\n".join(x for x in (code, p.get("test_setup_code") or "", "\n".join(tests)) if x.strip()) + "\n"


def passes(sandbox, p: dict, response: str) -> bool:
    from ..verify.code import extract_code
    from ..verify.sandbox import Limits
    code, _ = extract_code(response, "")
    if not code.strip():
        return False
    r = sandbox.run_python({"main.py": program(p, code)}, ["main.py"], Limits(wall_s=10))
    return r.returncode == 0 and r.limit is None


def build(root: Path, complete, sandbox, log=print) -> tuple[Path, dict]:
    """complete(messages, max_tokens) → 回答文字（凍結核心，貪婪解碼）。輸出 var/training/replay-mbpp.jsonl。
    complete(messages, max_tokens) → text from the frozen core (greedy). Writes var/training/replay-mbpp.jsonl."""
    from ..training_data import _ex
    probs = problems(fetch_mbpp(root))
    kept, stats = [], {"problems": len(probs), "passed": 0, "failed": 0, "errors": 0}
    for n, p in enumerate(probs, 1):
        msgs = [{"role": "user", "content": prompt_of(p)}]
        try:
            answer = complete(msgs, MAX_TOKENS)
        except Exception as exc:  # noqa: BLE001 - 一題失敗不擋其他 / keep going
            stats["errors"] += 1
            log(f"  {p['task_id']}: error {type(exc).__name__}")
            continue
        if answer and passes(sandbox, p, answer):
            stats["passed"] += 1
            kept.append(_ex(msgs, answer.strip(), "mbpp-replay", MBPP_LICENSE, "replay", task_id=p["task_id"]))
        else:
            stats["failed"] += 1
        if n % 50 == 0:
            log(f"  {n}/{len(probs)}: {stats['passed']} passed")
    out = root / "var" / "training" / "replay-mbpp.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in kept), encoding="utf-8")
    stats["file"] = out.name
    return out, stats

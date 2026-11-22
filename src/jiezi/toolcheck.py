"""系統層級的工具呼叫評測：把 ACEBench／BFCL 題目經 gateway 的 OpenAI `tools` 送出，用原評分器判分
（add-toolcheck、add-strong-tool-calling）。suite：r0（既有 50 題）、acebench-full、bfcl、all。
System-level tool-call evaluation: ACEBench/BFCL items go through the gateway as OpenAI `tools` and are
scored with their own checkers, so raw-text and tool-call paths can be compared.

評測題只拿來評測，不拿來訓練。 / Evaluation items are never used for training."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

from .eval.bank import load_sources
from .eval.sources import load_items
from .verify import bfcl, tool_call

SUITES = ("r0", "acebench-full", "bfcl", "all")
TURN = re.compile(r"^(user|system)\s*[:：]\s*", re.M)

# BFCL 的 schema 用 dict/tuple/any/float；OpenAI tools 要 object/array/string/number。
_SCHEMA_TYPES = {"dict": "object", "tuple": "array", "any": "string", "float": "number",
                 "bool": "boolean"}


def _normalize_schema(value):
    """遞迴轉型 BFCL 的 JSON-Schema-like 型別名稱。 / Normalize BFCL schema type names recursively."""
    if isinstance(value, list):
        return [_normalize_schema(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for key, v in value.items():
            if key == "type" and isinstance(v, str):
                out[key] = _SCHEMA_TYPES.get(v, v)
            elif key in ("properties", "$defs", "definitions") and isinstance(v, dict):
                out[key] = {name: _normalize_schema(schema) for name, schema in v.items()}
            elif key in ("items", "additionalProperties"):
                out[key] = _normalize_schema(v)
            else:
                out[key] = v
        return out
    return value


def items(root: Path, suite: str = "r0", limit: int | None = None) -> list[dict]:
    """讀取題目；`limit` 對每個來源各別套用。 / Load items; `limit` applies to each source."""
    if suite not in SUITES:
        raise ValueError(f"unknown suite {suite!r}; choose one of {', '.join(SUITES)}")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    if suite == "r0":
        out = []
        for line in (root / "var" / "eval" / "banks" / "r0" / "items.jsonl").read_text(encoding="utf-8").splitlines():
            it = json.loads(line)
            if it.get("source") == "acebench-zh":
                out.append(it)
        return out[:limit] if limit is not None else out

    sources = {s.key: s for s in load_sources(root / "eval" / "banks" / "tool.toml",
                                              root / "docs" / "licenses.md")}
    keys = []
    if suite in ("acebench-full", "all"):
        keys.append("acebench-zh-normal")
    if suite in ("bfcl", "all"):
        keys.append("bfcl")

    out = []
    for key in keys:
        src = sources.get(key)
        if src is None:
            raise ValueError(f"tool bank has no source {key!r}")
        part = load_items(src, root / "var" / "eval" / "cache")
        out.extend(part[:limit] if limit is not None else part)
    return out


def to_tools(functions: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {
        "name": f["name"], "description": f.get("description", ""),
        "parameters": _normalize_schema(f.get("parameters") or f.get("arguments")
                                        or {"type": "object", "properties": {}})}}
        for f in functions]


def to_messages(question: str | list) -> list[dict]:
    """ACEBench「user: …/system: …」轉訊息（system 是助手回話）；BFCL 的巢狀 list 直接攤平。
    ACEBench text turns → messages; BFCL's nested message lists are flattened as-is."""
    if isinstance(question, list):
        turns = []
        for turn in question:
            if isinstance(turn, list):
                turns.extend(turn)
            elif isinstance(turn, dict):
                turns.append(turn)
        return [{"role": m.get("role") or "user", "content": m.get("content", "")} for m in turns] or \
            [{"role": "user", "content": str(question)}]

    parts = TURN.split(question.strip())
    msgs = []
    for role, text in zip(parts[1::2], parts[2::2]):
        msgs.append({"role": "user" if role == "user" else "assistant", "content": text.strip()})
    return msgs or [{"role": "user", "content": question.strip()}]


def _py(v) -> str:
    return repr(v)


def calls_text(message: dict) -> str:
    """OpenAI tool_calls → ACEBench 的「[f(a=1)]」文字；沒有 tool_calls 時用回答文字。
    tool_calls → ACEBench "[f(a=1)]" text; the reply text when there are no tool_calls."""
    calls = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            return "unparseable arguments"
        calls.append(f"{fn.get('name')}({', '.join(f'{k}={_py(v)}' for k, v in (args or {}).items())})")
    return f"[{', '.join(calls)}]" if calls else (message.get("content") or "")


def ask(url: str, key: str, policy: str, messages: list[dict], tools: list[dict], timeout: float = 300) -> dict:
    req = urllib.request.Request(f"{url}/v1/chat/completions", method="POST",
                                 data=json.dumps({"model": policy, "messages": messages, "tools": tools}).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "X-Jiezi-Eval": "1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run(root: Path, url: str, key: str, policy: str = "jiezi-local", ask_fn=ask, log=print,
        suite: str = "r0", limit: int | None = None) -> tuple[Path, dict]:
    rows = []
    its = items(root, suite, limit)
    for n, it in enumerate(its, 1):
        t0 = time.monotonic()
        try:
            r = ask_fn(url, key, policy, to_messages(it["data"]["question"]), to_tools(it["data"]["functions"]))
            msg = (r.get("choices") or [{}])[0].get("message") or {}
            answer = calls_text(msg)
            if it.get("source") == "bfcl":
                res = bfcl.verify(it, answer, no_call=not bool(msg.get("tool_calls")))
                verifier = bfcl.VERSION
            else:
                res = tool_call.verify(it, answer)
                verifier = tool_call.VERSION
            meta = r.get("jiezi") or {}
            rows.append({"id": it["id"], "source": it.get("source"), "stratum": it.get("stratum"),
                         "status": res["status"], "score": res["score"], "verifier": verifier,
                         "tier": meta.get("tier"), "confidence": meta.get("confidence"),
                         "verification": meta.get("verification"), "latency_s": round(time.monotonic() - t0, 2),
                         "answer": answer[:300], "error": None})
        except Exception as exc:  # noqa: BLE001 - 單題失敗不中斷 / one failure never stops the run
            rows.append({"id": it["id"], "source": it.get("source"), "stratum": it.get("stratum"),
                         "status": "error", "score": 0, "verifier": None, "tier": None, "confidence": None,
                         "verification": None, "latency_s": None, "answer": "",
                         "error": f"{type(exc).__name__}: {exc}"})
        if n % 10 == 0:
            log(f"  {n}/{len(its)}")

    summary = {"policy": policy, "suite": suite, "items": len(rows), "correct": sum(r["score"] for r in rows),
               "by_status": dict(Counter(r["status"] for r in rows)),
               "by_tier": dict(Counter(str(r["tier"]) for r in rows)),
               "by_source": dict(Counter(str(r["source"]) for r in rows))}
    prefix = "toolcheck" if suite == "r0" else f"toolcheck-{suite}"
    out = root / "var" / "reports" / f"{prefix}-{datetime.now():%Y%m%d-%H%M}-{policy}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    acc = summary["correct"] / len(rows) if rows else 0
    md = [f"# 工具呼叫系統評測 / Tool-call system check（{policy}；{suite}）", "",
          f"- 題數 {len(rows)}，答對 {summary['correct']}（{acc * 100:.1f}%）",
          f"- 狀態：{summary['by_status']}", f"- 最後層級：{summary['by_tier']}",
          f"- 來源：{summary['by_source']}"]
    if suite == "r0":
        md.append("- 對照：E0 的 acebench-zh 是純文字提示的原始分數；這裡經過 gateway（工具呼叫格式、平行取樣、驗證重答）。")
    if suite in ("bfcl", "all"):
        md.append("- BFCL 已知差異：只移植 Python AST 檢查、不執行回答、函式名 `.`→`_`、"
                  "irrelevance 以 no-call 判定、未知型別記錯。")
    md += ["", "| 題目 | 來源 | 結果 | 層級 | 信心 | 回答（前 80 字） |",
           "|---|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['source']} | {r['status']} | {r['tier']} | {r['confidence']} | "
           f"{(r['error'] or r['answer']).replace('|', '｜')[:80]} |" for r in rows]
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    out.with_suffix(".jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                          encoding="utf-8")
    return out, summary

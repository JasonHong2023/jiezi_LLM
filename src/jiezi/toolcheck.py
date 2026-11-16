"""系統層級的工具呼叫評測：R0 題庫的 50 題 ACEBench 改用 OpenAI `tools` 經 gateway 回答，用同一個 ACEBench 評分器判分
（add-toolcheck）。和 E0 的原始分數（純文字提示）比較，看約束解碼、平行取樣、驗證重答的整體效果。
System-level tool-call evaluation: the 50 ACEBench items of the R0 bank are sent through the gateway as OpenAI
`tools` and scored with the same ACEBench checker, to compare with E0's raw text-prompt scores.

評測題只拿來評測，不拿來訓練。 / Evaluation items are never used for training."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from .verify import tool_call

TURN = re.compile(r"^(user|system)\s*[:：]\s*", re.M)


def items(root: Path) -> list[dict]:
    out = []
    for line in (root / "var" / "eval" / "banks" / "r0" / "items.jsonl").read_text(encoding="utf-8").splitlines():
        it = json.loads(line)
        if it.get("source") == "acebench-zh":
            out.append(it)
    return out


def to_tools(functions: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {
        "name": f["name"], "description": f.get("description", ""),
        "parameters": f.get("parameters") or f.get("arguments") or {"type": "object", "properties": {}}}}
        for f in functions]


def to_messages(question: str) -> list[dict]:
    """「user: …\\nsystem: …」→ OpenAI messages（ACEBench 的 system 是助手的回話）。 / system turns are the assistant."""
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


def run(root: Path, url: str, key: str, policy: str = "jiezi-local", ask_fn=ask, log=print) -> tuple[Path, dict]:
    rows = []
    its = items(root)
    for n, it in enumerate(its, 1):
        t0 = time.monotonic()
        try:
            r = ask_fn(url, key, policy, to_messages(it["data"]["question"]), to_tools(it["data"]["functions"]))
            msg = (r.get("choices") or [{}])[0].get("message") or {}
            res = tool_call.verify(it, calls_text(msg))
            meta = r.get("jiezi") or {}
            rows.append({"id": it["id"], "status": res["status"], "score": res["score"], "tier": meta.get("tier"),
                         "confidence": meta.get("confidence"), "verification": meta.get("verification"),
                         "latency_s": round(time.monotonic() - t0, 2), "answer": calls_text(msg)[:300],
                         "error": None})
        except Exception as exc:  # noqa: BLE001 - 單題失敗不中斷 / one failure never stops the run
            rows.append({"id": it["id"], "status": "error", "score": 0, "tier": None, "confidence": None,
                         "verification": None, "latency_s": None, "answer": "", "error": f"{type(exc).__name__}: {exc}"})
        if n % 10 == 0:
            log(f"  {n}/{len(its)}")
    from collections import Counter
    summary = {"policy": policy, "items": len(rows), "correct": sum(r["score"] for r in rows),
               "by_status": dict(Counter(r["status"] for r in rows)),
               "by_tier": dict(Counter(str(r["tier"]) for r in rows))}
    out = root / "var" / "reports" / f"toolcheck-{datetime.now():%Y%m%d-%H%M}-{policy}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    acc = summary["correct"] / len(rows) if rows else 0
    md = [f"# 工具呼叫系統評測 / Tool-call system check（{policy}）", "",
          f"- 題數 {len(rows)}，答對 {summary['correct']}（{acc * 100:.1f}%）",
          f"- 狀態：{summary['by_status']}", f"- 最後層級：{summary['by_tier']}",
          "- 對照：E0 的 acebench-zh 是純文字提示的原始分數；這裡經過 gateway（工具呼叫格式、平行取樣、驗證重答）。", "",
          "| 題目 | 結果 | 層級 | 信心 | 回答（前 80 字） |", "|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['status']} | {r['tier']} | {r['confidence']} | "
           f"{(r['error'] or r['answer']).replace('|', '｜')[:80]} |" for r in rows]
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    out.with_suffix(".jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                                         encoding="utf-8")
    return out, summary

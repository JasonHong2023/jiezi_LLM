"""外部工具呼叫資料集 → 訓練範例（add-strong-tool-calling 3.1）。

只收授權允許、已固定版本的資料集（`var/datasets/toolcall/<name>/SOURCE.jsonl` 記 repo、revision、license；
`docs/licenses.md` 登記）：
- `toolace`：Team-ACE/ToolACE（Apache-2.0）。工具清單寫在 system 的 JSON 裡，呼叫是文字格式 `[f(a=1)]`。
- `hermes-fc`：NousResearch/hermes-function-calling-v1（Apache-2.0）。`tools` 欄位＋`<tool_call>{json}</tool_call>`。

每筆只取第一個「使用者 → 助理呼叫工具」的回合，且**必須通過芥子自己的工具 schema 檢查**（R20.3 只收驗證通過的）。
含中日韓文字的樣本一律不收（ToolACE 的中文為簡體；專案不收簡體中文資料）。不合法的工具名稱（含空格等）統一換成
`[A-Za-z0-9_-]`，工具清單與呼叫一起換。

Licensed, pinned tool-calling datasets → training examples; only the first user→call turn, only if it passes the
schema check, and never samples containing CJK text."""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

_CJK = re.compile(r"[㐀-鿿豈-﫿]")
_BAD = re.compile(r"[^A-Za-z0-9_\-]")
_TOOL_CALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def dataset_dir(root: Path) -> Path:
    return root / "var" / "datasets" / "toolcall"


def _source(d: Path) -> dict:
    rows = [json.loads(x) for x in (d / "SOURCE.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows[0] if rows else {}


def _safe(name: str) -> str:
    return _BAD.sub("_", name.strip())[:64] or "tool"


def _fix_schema(node):
    """BFCL 風格的 `type: dict` → JSON Schema 的 object；遞迴處理。 / BFCL's dict → object, recursively."""
    if isinstance(node, dict):
        out = {k: _fix_schema(v) for k, v in node.items()}
        if out.get("type") == "dict":
            out["type"] = "object"
        if out.get("type") == "float":
            out["type"] = "number"
        if out.get("type") == "tuple":
            out["type"] = "array"
        return out
    if isinstance(node, list):
        return [_fix_schema(v) for v in node]
    return node


def _as_tools(specs: list) -> tuple[list[dict], dict[str, str]]:
    tools, rename = [], {}
    for s in specs or []:
        fn = s.get("function") if isinstance(s, dict) and "function" in s else s
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        safe = _safe(fn["name"])
        rename[fn["name"]] = safe
        params = _fix_schema(fn.get("parameters") or {"type": "object", "properties": {}})
        if params.get("required") is None:
            params.pop("required", None)
        tools.append({"type": "function", "function": {"name": safe, "description": str(fn.get("description") or ""),
                                                       "parameters": params}})
    return tools, rename


def _toolace(row: dict) -> tuple[list, str, dict] | None:
    sysmsg = row.get("system") or ""
    start = sysmsg.find("[{")
    if start < 0:
        return None
    try:
        specs, _ = json.JSONDecoder().raw_decode(sysmsg[start:])
    except ValueError:
        return None
    conv = row.get("conversations") or []
    if len(conv) < 2 or conv[0].get("from") != "user" or conv[1].get("from") != "assistant":
        return None
    tools, rename = _as_tools(specs)
    text = conv[1].get("value") or ""
    for old, new in sorted(rename.items(), key=lambda x: -len(x[0])):  # 長名先換 / longest names first
        text = text.replace(f"{old}(", f"{new}(")
    msg = {"role": "assistant", "content": text}
    from .runtime.escalation import text_calls_to_tool_calls
    if not text_calls_to_tool_calls(msg, tools):
        return None
    return tools, conv[0].get("value") or "", msg


def _hermes(row: dict) -> tuple[list, str, dict] | None:
    conv = row.get("conversations") or []
    human = next((c for c in conv if c.get("from") == "human"), None)
    gpt = next((c for c in conv if c.get("from") == "gpt"), None)
    if not human or not gpt or conv.index(gpt) < conv.index(human):
        return None
    try:
        specs = json.loads(row["tools"]) if isinstance(row.get("tools"), str) else row.get("tools")
    except (ValueError, KeyError):
        return None
    tools, rename = _as_tools(specs or [])
    calls = []
    for m in _TOOL_CALL.finditer(gpt.get("value") or ""):
        try:
            c = json.loads(m.group(1))
        except ValueError:
            return None
        name, args = rename.get(c.get("name"), c.get("name")), c.get("arguments")
        if not isinstance(args, dict):
            return None
        calls.append({"id": f"call_{len(calls)}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
    if not calls:
        return None
    return tools, human.get("value") or "", {"role": "assistant", "content": None, "tool_calls": calls}


PARSERS = {"toolace": _toolace, "hermes-fc": _hermes}


def load(root: Path, rng: random.Random, limit: int) -> tuple[list[dict], Counter]:
    """讀所有已下載的資料集，回傳 (訓練範例, 排除原因計數)。每個資料集最多 limit 筆（固定種子抽樣）。
    Read every downloaded dataset; at most `limit` examples each (seeded sample)."""
    from .runtime.escalation import verify_tools
    from .training_data import _ex
    out, why = [], Counter()
    base = dataset_dir(root)
    for name, parse in PARSERS.items():
        d = base / name
        if not (d / "SOURCE.jsonl").exists():
            continue
        src = _source(d)
        license_ = f"{src.get('license', 'unknown')} ({src.get('repo')}@{str(src.get('revision'))[:12]})"
        rows = []
        for f in sorted(d.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            rows += data if isinstance(data, list) else []
        picked = []
        for row in rows:
            if _CJK.search(json.dumps(row, ensure_ascii=False)):
                why[f"{name}:cjk_text"] += 1      # 不收簡體中文 / no Simplified Chinese
                continue
            got = parse(row)
            if got is None:
                why[f"{name}:not_a_single_call_turn"] += 1
                continue
            tools, question, msg = got
            if not question.strip() or verify_tools(tools, msg).get("status") != "pass":
                why[f"{name}:schema_check_failed"] += 1
                continue
            ex = _ex([{"role": "user", "content": question}], None, name, license_, "dataset")
            ex["messages"][-1] = msg
            ex["tools"] = tools
            from .training_data import _sha
            ex["sha256"] = ex["provenance"]["content_hash"] = _sha(ex["messages"] + [tools])
            picked.append(ex)
        rng.shuffle(picked)
        out += picked[:limit]
        why[f"{name}:over_limit"] += max(0, len(picked) - limit)
    return out, why

"""代理客戶端的工具清單篩選（add-client-tool-filter）。

Hermes、OpenCode 一次送 55–178 個工具，光工具 schema 就遠超本機 4096 token 的槽位。這裡依使用者最近的訊息挑出
相關工具，必留名單、任務契約指定的工具、對話中已經呼叫過的工具一律保留；放不下時走 fallback 階梯：
  1. 篩選後的工具，完整 schema
  2. 同一批工具，保留 parameters、只截短 description（不可拿掉 parameters，模型會產生錯的參數）
  3. 只留受保護的工具（必留、契約、已呼叫），完整 schema
仍放不下由 gateway 決定轉交雲端或回 413（使用者 2026-11-23 選 OQ0 的 (C)：轉交時也只帶篩過的工具，省雲端 token）。

工具由客戶端自己執行，gateway 只轉送 schema，所以這裡不新增任何能力；只用關鍵字與啟發式，不用 embedding。
Tool-list filtering for agent clients: keep the tools relevant to the latest user message plus protected ones
(keep-list, contract tools, tools already called), then fall back stage by stage when the slot is still too small."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Iterable

TOP_K = 12
SHORT_DESC_CHARS = 120
# 各客戶端的核心工具（寫入與 shell 也在內：由客戶端執行，不是芥子執行）/ client core tools, incl. write and shell
KEEP_TOOLS = frozenset({
    # Hermes
    "terminal", "read_file", "write_file", "patch", "search_files", "todo", "clarify",
    # OpenCode
    "bash", "read", "write", "edit", "glob", "grep", "todowrite", "task", "question",
})
STAGES = ("full", "short_descriptions", "protected_only")

_WORD = re.compile(r"[a-z][a-z0-9]{1,}")
_CJK_RUN = re.compile(r"[一-鿿]+")
_STOP = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "into", "you", "your", "are", "can", "use", "will",
    "please", "file", "files", "tool", "tools", "help", "want", "need", "what", "how", "should", "would",
    "幫我", "一下", "可以", "請你", "這個", "那個", "什麼", "怎麼", "我們", "你們", "然後", "現在",
})
# 常見中文用語 → 工具描述裡的英文詞 / common Chinese wording → English words found in tool descriptions
_ZH_HINTS = {
    "讀": ("read", "view", "open"), "看": ("read", "view", "look"), "寫": ("write", "create"),
    "改": ("edit", "patch", "replace"), "修": ("edit", "patch", "fix"), "刪": ("delete", "remove"),
    "找": ("search", "find", "grep", "glob"), "搜": ("search", "find"), "查": ("search", "lookup", "query"),
    "執行": ("run", "execute", "command", "shell", "terminal", "bash"), "跑": ("run", "execute", "test"),
    "測試": ("test", "run"), "網": ("web", "browser", "url", "fetch"), "瀏覽": ("browser", "navigate"),
    "下載": ("download", "fetch"), "圖": ("image", "vision", "render"), "記憶": ("memory", "remember"),
    "排程": ("cron", "schedule"), "提交": ("git", "commit"), "版本": ("git",), "技能": ("skill",),
    "待辦": ("todo",), "子代理": ("task", "delegate", "agent"), "符號": ("symbol", "lsp"), "定義": ("definition", "lsp"),
}


def tool_name(tool: dict) -> str:
    fn = tool.get("function") if isinstance(tool, dict) else None
    return str((fn or {}).get("name") or (tool.get("name") if isinstance(tool, dict) else "") or "")


def _desc(tool: dict) -> str:
    fn = tool.get("function") or {}
    return str(fn.get("description") or "")


def keywords(text: str) -> set[str]:
    """英文單字＋中文提示詞與兩字詞。 / English words plus Chinese hints and bigrams."""
    low = (text or "").lower()
    words = {w for w in _WORD.findall(low) if w not in _STOP}
    for zh, en in _ZH_HINTS.items():
        if zh in low:
            words.update(en)
    for run in _CJK_RUN.findall(low):
        words.update(run[i:i + 2] for i in range(len(run) - 1) if run[i:i + 2] not in _STOP)
    return words


def _name_words(name: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", name.lower()) if len(w) > 1}


def score(tool: dict, words: set[str], clean: Callable[[str], str] = lambda s: s) -> float:
    if not words:
        return 0.0
    name_hits = len(_name_words(tool_name(tool)) & words)
    desc = clean(_desc(tool)).lower()
    desc_hits = sum(1 for w in words if w in desc)
    return name_hits * 3.0 + min(desc_hits, 6)


def called_tools(messages: Iterable[dict]) -> set[str]:
    """對話裡已呼叫過的工具：後續回合還要用到。 / Tools already called in the conversation."""
    out = set()
    for m in messages or []:
        for c in m.get("tool_calls") or [] if isinstance(m, dict) else []:
            name = (c.get("function") or {}).get("name") if isinstance(c, dict) else None
            if name:
                out.add(name)
    return out


def last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
            return c if isinstance(c, str) else ""
    return ""


def _clean_text(text: str) -> str:
    """清掉零寬字元與偽造標記；含注入句型的描述不給分（不讓惡意描述靠關鍵字擠進名單）。
    Strip invisible characters; a description with an injection pattern scores nothing."""
    from ..injection import clean, scan
    out = clean(text)[0]
    return "" if scan(out) else out


def shorten(tool: dict, limit: int = SHORT_DESC_CHARS) -> dict:
    """保留 parameters，只截短工具與參數的 description。 / Keep parameters; shorten descriptions only."""
    t = copy.deepcopy(tool)
    fn = t.get("function") or {}
    if isinstance(fn.get("description"), str) and len(fn["description"]) > limit:
        fn["description"] = fn["description"][:limit].rstrip() + "…"

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "description" and isinstance(v, str) and len(v) > limit // 2:
                    node[k] = v[:limit // 2].rstrip() + "…"
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(fn.get("parameters"))
    return t


def select(tools: list[dict], messages: list[dict], contract_tools: Iterable[str] = (),
           keep: Iterable[str] = KEEP_TOOLS, top_k: int = TOP_K,
           clean: Callable[[str], str] = _clean_text) -> dict:
    """挑出要送的工具（第 1 階段）。回傳 {"tools", "protected", "kept", "dropped"}。
    Pick the stage-1 tools; protected = keep-list ∪ contract ∪ already called (never dropped)."""
    protected_names = set(keep) | set(contract_tools) | called_tools(messages)
    words = keywords(last_user_text(messages))
    protected, others = [], []
    for i, t in enumerate(tools):
        (protected if tool_name(t) in protected_names else others).append((i, t))
    ranked = sorted(((score(t, words, clean), -i, i, t) for i, t in others), reverse=True)
    chosen = {i for s, _, i, _ in ranked[:max(0, top_k - len(protected))] if s > 0}
    keep_idx = {i for i, _ in protected} | chosen
    out = [t for i, t in enumerate(tools) if i in keep_idx]  # 保持客戶端原順序 / client order preserved
    return {"tools": out, "protected": [t for _, t in protected],
            "kept": [tool_name(t) for t in out],
            "dropped": len(tools) - len(out)}


def ladder(tools: list[dict], messages: list[dict], fits: Callable[[list[dict]], bool],
           contract_tools: Iterable[str] = (), keep: Iterable[str] = KEEP_TOOLS, top_k: int = TOP_K,
           clean: Callable[[str], str] = _clean_text) -> dict:
    """依階梯嘗試，回傳 {"tools", "stage", "fits", "original", "kept"}；stage 為 None 表示原清單就放得下。
    Try each stage; stage None means the original list already fits. When nothing fits, "tools" is the
    stage-1 selection (full schema), used for cloud escalation."""
    base = {"original": len(tools)}
    if fits(tools):
        return {**base, "tools": tools, "stage": None, "fits": True, "kept": [tool_name(t) for t in tools]}
    sel = select(tools, messages, contract_tools, keep, top_k, clean)
    candidates = [("full", sel["tools"]),
                  ("short_descriptions", [shorten(t) for t in sel["tools"]]),
                  ("protected_only", sel["protected"])]
    for stage, cand in candidates:
        if cand and fits(cand):
            return {**base, "tools": cand, "stage": stage, "fits": True, "kept": [tool_name(t) for t in cand]}
    return {**base, "tools": sel["tools"], "stage": "exhausted", "fits": False, "kept": sel["kept"]}

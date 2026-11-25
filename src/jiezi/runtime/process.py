"""回答的過程：給畫面摺疊顯示（add-answer-process，使用者 2026-11-18：「思考和請教的過程可以摺疊起來，我要看再展開」）。
The steps behind an answer, for the front end to show folded (add-answer-process)."""

from __future__ import annotations

import time

DRAFT_MAX = 3000          # 沒採用的草稿最多給多少字 / characters of an unused draft
ERROR_MAX = 300
SOURCE_NAMES = {"memory": "記憶", "taiwan-md": "Taiwan.md", "laws": "法規", "curriculum": "課綱", "dictionary": "辭典"}


class TimedTiers(list):
    """每加一層就記下完成時間（從請求開始算的秒數）。 / Stamps each tier with the seconds since the request began."""

    def __init__(self, t0: float | None = None):
        super().__init__()
        self.t0 = time.monotonic() if t0 is None else t0

    def append(self, item) -> None:  # noqa: D401 - list API
        if isinstance(item, dict):
            item.setdefault("t_s", round(time.monotonic() - self.t0, 2))
        super().append(item)


def _who(t: dict) -> str:
    tier, provider = t.get("tier"), t.get("provider")
    if tier == "memory":
        return "記憶"
    if provider == "claude":
        return "請教 Claude"
    if provider == "cloud":
        return "雲端模型"
    if t.get("step") == "think" or tier == "think":
        return "本機深入思考後重答"
    if t.get("step") == "hint":
        return "依雲端提示本機重答"
    return {0: "本機作答", 1: "本機重答（附上錯誤）", 2: "依回饋本機重答"}.get(tier, f"第 {tier} 層")


def _source_label(s: dict) -> str:
    if s.get("tool"):
        return f"計算（{s['tool']}）"
    src = SOURCE_NAMES.get(s.get("source"), s.get("source") or "")
    name = s.get("article") or s.get("title") or s.get("page") or s.get("law") or s.get("word") or ""
    sec = s.get("section")
    return (f"{src}〈{name}〉" if name else src) + (f"：{sec}" if sec and sec != name else "")


def _short(text, n: int) -> str:
    text = str(text or "").split(" / ")[0].strip()   # 中英雙語的錯誤只留中文 / bilingual errors keep the Chinese half
    return text if len(text) <= n else text[:n] + "…"


def steps(rec: dict) -> list[dict]:
    """依序列出這題做了什麼。最後一層的回答就是畫面上的回答，不重複給草稿。
    What happened, in order. The last tier's answer is the one shown, so its draft is not repeated."""
    from .gateway import strip_appendix
    out: list[dict] = []
    if rec.get("image_paths"):
        out.append({"kind": "files", "label": "讀取檔案",
                    "items": [p["path"] + ("" if p.get("ok") else f"（{p.get('why')}）") for p in rec["image_paths"]]})
    if rec.get("web_read"):
        out.append({"kind": "web", "label": "讀取網頁",
                    "items": [(w.get("title") or w["url"]) + ("" if w.get("ok") else f"（{w.get('why')}）")
                              for w in rec["web_read"]]})
    if rec.get("sources"):
        labels = list(dict.fromkeys(_source_label(s) for s in rec["sources"] if isinstance(s, dict)))
        if labels:
            out.append({"kind": "lookup", "label": "查資料", "items": labels})
    v = rec.get("vision") or {}
    if v:
        items = []
        if v.get("detections"):
            items.append("偵測：" + "、".join(f"{k}×{n}" for k, n in v["detections"].items()))
        ocr = v.get("ocr") or {}
        if ocr.get("lines"):
            items.append(f"圖中文字 {ocr['lines']} 行，{ocr.get('seconds')} 秒")
        elif ocr.get("error"):
            items.append(f"文字辨識失敗：{_short(ocr['error'], ERROR_MAX)}")
        tiles = v.get("tiles") or {}
        if tiles:
            items.append(f"切塊放大 {tiles.get('grid')} 塊，{tiles.get('seconds')} 秒")
        if v.get("error"):
            items.append(f"工具失敗：{_short(v['error'], ERROR_MAX)}")
        out.append({"kind": "look", "label": "看圖工具", "items": items})
    if rec.get("experience_lessons"):
        out.append({"kind": "experience", "label": "參考過去的經驗", "items": rec["experience_lessons"]})
    tiers = [t for t in rec.get("tiers") or [] if isinstance(t, dict)]
    for i, t in enumerate(tiers):
        step = {"kind": "answer", "label": _who(t), "model": t.get("model"), "t_s": t.get("t_s")}
        if t.get("error"):
            step["error"] = _short(t["error"], ERROR_MAX)
        ver = t.get("verification") or {}
        if ver.get("status") in ("pass", "fail"):
            step["check"] = "通過" if ver["status"] == "pass" else "沒通過：" + _short(ver.get("error"), ERROR_MAX)
        if t.get("needs_help") and "check" not in step:
            step["check"] = {"self_reported_unsure": "本機說不確定", "truncated": "回答被截斷",
                             "empty_answer": "沒有回答"}.get(t["needs_help"], t["needs_help"])
        if t.get("reason") and t.get("provider"):
            step["why"] = t["reason"]
        ans = t.get("answer") or {}
        draft = ans.get("content") if isinstance(ans, dict) else None
        if i < len(tiers) - 1 and isinstance(draft, str) and draft.strip():
            draft = strip_appendix(draft).strip()
            step["draft"] = draft if len(draft) <= DRAFT_MAX else draft[:DRAFT_MAX] + "…"
        out.append(step)
    return out

"""缺口報告：統計哪些問題本機答不好、最後要請教 Claude 或轉雲端，找出該補的資料（使用者 2026-11-15「第6項」）。
Gap report: which questions the local model could not handle, so we know what data to add (user, 2026-11-15).

只讀 `var/trajectories/`，報告寫到 `var/reports/`（都在本機、不進版控）。每一題分成：
- 觸發缺口：本機資料庫其實有相關內容，但這次沒有查到 → 該調整觸發規則；
- 資料缺口：本機完全沒有相關資料 → 該找新的資料來源；
- 有查到資料仍答不好 → 模型能力或資料品質問題。
Reads trajectories only; writes the report under `var/reports/`. Each question is classed as a trigger gap (local
data exists but was not used), a data gap (nothing local), or a model gap (data was attached but it still failed)."""

from __future__ import annotations

import collections
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

HELP_TIERS = {3, "consult"}
# 問芥子自己（名字、身分、作者）→ 改系統提示，不是補資料 / about jiezi itself → system prompt, not data
SELF = re.compile(r"芥子|自我介紹|你是誰|你叫什麼|你的名字|你在哪|你會哪些|你會那些|你能做什麼|誰做的你|你的作者")
# 要上網、即時或網頁內容 → 本機做不到，交給 Claude / needs the web or live data
WEB = re.compile(r"https?://|網路上|上網|網頁|網站|新聞|今天|今日|現在幾點|最新|即時|天氣|股價|匯率")
PROBE_HITS, PROBE_COVER = 3, 0.4
DIRECT = {"jiezi-ask-claude", "jiezi-cloud"}
MAX_LISTED = 40


def _question(rec: dict) -> str:
    users = [m.get("content") for m in (rec.get("request") or {}).get("messages") or []
             if m.get("role") == "user" and isinstance(m.get("content"), str)]
    return (users[-1] if users else "").strip()


def _reason(rec: dict) -> str | None:
    """本機需要幫忙的原因；不需要回傳 None。 / Why the local model needed help, or None."""
    tiers = [t for t in rec.get("tiers") or [] if t.get("tier") in (0, 1)]
    for t in tiers:
        if t.get("needs_help"):
            return t["needs_help"]
    if tiers and all((t.get("verification") or {}).get("status") == "fail" for t in tiers):
        checks = [c["check"] for c in (tiers[-1].get("verification") or {}).get("checks") or []
                  if c.get("status") == "fail"]
        return "verification_failed:" + ",".join(checks)
    if rec.get("final_tier") in HELP_TIERS and rec.get("policy") == "jiezi":
        return (rec.get("jiezi") or {}).get("escalation") or "escalated"
    if rec.get("status") not in (None, "ok"):
        return f"error:{rec['status']}"
    return None


def load(root: Path, days: int, today: date | None = None) -> list[dict]:
    today = today or date.today()
    out = []
    for i in range(days):
        f = root / "var" / "trajectories" / f"{(today - timedelta(days=i)).isoformat()}.jsonl"
        if f.exists():
            out += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()]
    return out


class LocalProbe:
    """問題丟進本機資料庫（放寬門檻）看有沒有相關內容。 / Probe local data with loose thresholds."""

    def __init__(self, root: Path):
        self.k = self.d = self.g = None
        try:
            from ..knowledge import Knowledge, db_path
            self.k = Knowledge(db_path(root))
        except Exception:  # noqa: BLE001 - 沒建置就不查 / not built
            pass
        try:
            from ..dictionary import Dictionary, db_path as dict_db
            self.d = Dictionary(dict_db(root))
        except Exception:  # noqa: BLE001
            pass
        try:
            from ..curriculum import Graph
            self.g = Graph.load(root)
        except Exception:  # noqa: BLE001
            pass

    def related(self, q: str) -> list[str]:
        found = []
        if self.k:
            for aid in self.k.articles_named(q):
                found.append("知識庫〈" + self.k.con.execute("SELECT name FROM articles WHERE id = ?",
                                                             (aid,)).fetchone()[0] + "〉")
            if not found:
                from ..knowledge import STOP, bigrams
                qs = [g for g in dict.fromkeys(bigrams(q[:500])) if g not in STOP]
                if qs:
                    expr = " OR ".join('"' + g.replace('"', "") + '"' for g in qs)
                    rows = self.k.con.execute(
                        "SELECT a.name, grams.g FROM grams JOIN sections s ON s.id = grams.rowid "
                        "JOIN articles a ON a.id = s.article WHERE grams MATCH ? ORDER BY bm25(grams) LIMIT 5",
                        (expr,)).fetchall()
                    for name, g in rows:
                        hits = len(set(qs) & set(g.split()))
                        if hits >= PROBE_HITS and hits >= PROBE_COVER * len(qs) and \
                                not any(f"〈{name}〉" in x for x in found):
                            found.append(f"知識庫〈{name}〉（命中 {hits}/{len(qs)}）")
        if self.g:
            found += [f"課綱〈{self.g.topics[t]['name']}〉" for t in self.g.topics_in(q)]
        if self.d:
            # 辭典：不管有沒有「意思、解釋」等提問用語，看問題裡有沒有辭典收錄的 3 字以上詞語
            words, i = [], 0
            while i < len(q) and len(words) < 3:
                hit = next((q[i:i + n] for n in range(min(8, len(q) - i), 2, -1) if self.d.has(q[i:i + n])), None)
                if hit:
                    words.append(hit)
                    i += len(hit)
                else:
                    i += 1
            found += [f"辭典「{w}」" for w in words]
        return found[:4]


def classify(rec: dict, probe: LocalProbe | None, why: str = "") -> tuple[str, list[str]]:
    q = _question(rec)
    if why.startswith("error:"):
        return "error", []
    if SELF.search(q):
        return "self", []
    if WEB.search(q):
        return "web", []
    if rec.get("sources"):
        return "model", [s.get("article") or s.get("topic") or s.get("title") or s.get("volume") or s.get("code")
                         or s.get("source") for s in rec["sources"]]
    related = probe.related(q) if probe else []
    return ("trigger" if related else "data"), related


KIND = {"trigger": "觸發缺口（本機有資料但沒查到）", "data": "資料缺口（本機沒有相關資料）",
        "model": "有附資料仍答不好", "self": "問芥子自己（該改系統提示）",
        "web": "需要上網或即時資料（本機做不到，交給 Claude）", "error": "系統錯誤（引擎、請教失敗）"}
ORDER = ("data", "trigger", "model", "self", "web", "error")


def report(root: Path, days: int = 7, today: date | None = None, probe: LocalProbe | None = None) -> tuple[str, dict]:
    recs = load(root, days, today)
    probe = probe if probe is not None else LocalProbe(root)
    rows, direct = [], []
    for rec in recs:
        q = _question(rec)
        if not q:
            continue
        if rec.get("policy") in DIRECT:
            direct.append((rec, q))
            continue
        why = _reason(rec)
        if why:
            kind, related = classify(rec, probe, why)
            rows.append({"at": rec.get("at", ""), "q": q, "why": why, "kind": kind, "related": related,
                         "final": rec.get("final_tier"), "policy": rec.get("policy")})
    summary = {"records": len(recs), "needed_help": len(rows), "direct": len(direct),
               "by_reason": dict(collections.Counter(r["why"] for r in rows).most_common()),
               "by_kind": dict(collections.Counter(r["kind"] for r in rows).most_common())}
    span = f"{((today or date.today()) - timedelta(days=days - 1)).isoformat()} ~ {(today or date.today()).isoformat()}"
    md = [f"# 芥子缺口報告 / Gap report（{span}）", "",
          f"- 對話紀錄 {summary['records']} 筆；本機需要幫忙 {summary['needed_help']} 筆；直接指定請教 Claude／雲端 "
          f"{summary['direct']} 筆", f"- 產生時間：{datetime.now().astimezone().isoformat(timespec='seconds')}", "",
          "## 原因 / Reasons", ""]
    md += [f"- {k}：{v}" for k, v in summary["by_reason"].items()] or ["- （無）"]
    md += ["", "## 缺口類型 / Gap types", ""]
    md += [f"- {KIND[k]}：{v}" for k, v in summary["by_kind"].items()] or ["- （無）"]
    for kind in ORDER:
        group = [r for r in rows if r["kind"] == kind]
        if not group:
            continue
        md += ["", f"## {KIND[kind]}", "", "| 時間 | 問題 | 原因 | 最後由誰回答 | 相關本機資料 |", "|---|---|---|---|---|"]
        seen = collections.Counter(r["q"] for r in group)
        for r in group[:MAX_LISTED]:
            if seen[r["q"]] == 0:
                continue
            times = f"（×{seen[r['q']]}）" if seen[r["q"]] > 1 else ""
            seen[r["q"]] = 0
            q = r["q"].replace("|", "｜").replace("\n", " ")[:80]
            md.append(f"| {r['at'][5:16]} | {q}{times} | {r['why']} | {r['final']} | {'、'.join(r['related']) or '—'} |")
    if direct:
        md += ["", "## 直接指定請教 Claude／雲端的問題 / Asked Claude or the cloud directly", "",
               "（使用者自己判斷本機不夠用的題目，也是補資料的線索 / also a hint of what to add）", ""]
        seen = collections.Counter(q for _, q in direct)
        for rec, q in direct[:MAX_LISTED]:
            if seen[q]:
                md.append(f"- {rec.get('at', '')[5:16]} {rec.get('policy')}：{q.replace(chr(10), ' ')[:80]}"
                          + (f"（×{seen[q]}）" if seen[q] > 1 else ""))
                seen[q] = 0
    md += ["", "## 建議 / Suggestions", ""]
    if summary["by_kind"].get("trigger"):
        md.append("- 觸發缺口：檢查上表「相關本機資料」，調整觸發規則（提問用語、門檻）讓它們被查到。")
    if summary["by_kind"].get("data"):
        md.append("- 資料缺口：依上表的主題找有開放授權的資料來源（先登記 docs/licenses.md，R18.3）。")
    if summary["by_kind"].get("model"):
        md.append("- 有附資料仍答不好：看查核原因；常見的是模型轉述錯誤，可考慮換更大的核心模型或改提示。")
    if summary["by_kind"].get("self"):
        md.append("- 問芥子自己：在系統提示（src/jiezi/runtime/data/system_prompt.md）補上名字由來、能做什麼等說明。")
    if summary["by_kind"].get("error"):
        md.append("- 系統錯誤：看 scripts/jiezi logs。")
    if not rows and not direct:
        md.append("- 這段期間本機都能自己回答。")
    return "\n".join(md) + "\n", summary


def write(root: Path, days: int = 7) -> tuple[Path, dict]:
    md, summary = report(root, days)
    out = root / "var" / "reports" / f"gaps-{date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return out, summary

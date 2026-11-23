"""工具篩選離線量測（add-client-tool-filter 5.1–5.4）。

用軌跡裡存下的真實代理請求（Hermes 約 55 個工具、OpenCode 約 177–179 個工具）離線重算，不呼叫模型：
- token：篩選前後的估算 token（與 gateway 用同一個 `context.total`）。
- 階段分布（fallback 觸發率）：full／short_descriptions／protected_only／exhausted，含精簡客戶端提示後的結果。
- 保留工具準確率：對話歷史裡每一次助理呼叫工具，用「呼叫當下之前的訊息」重跑 `select`，看被呼叫的工具有沒有留下。
  分成「之前沒呼叫過的新工具」（真正考驗關鍵字排序）與「之前呼叫過的」（一律保護，應為 100%）。
- 延遲：`ladder`（含精簡）的純計算時間。
- 不同 top_k 的保留率與階段分布，供 5.4 建議值。

輸出 `var/reports/tool-filter-YYYYMMDD.md` 與 `.jsonl`（var/ 不進版控）。
Offline tool-filter measurement over real agent requests stored in trajectories; no model calls."""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import statistics
import time
from collections import Counter
from pathlib import Path

from ..runtime.context import SLOT_CTX, fit, total
from ..runtime.tool_filter import KEEP_TOOLS, TOP_K, called_tools, ladder, select, tool_name, with_compact_system

TOO_LARGE_ROOM = 128          # 與 gateway 相同 / same as the gateway
MIN_TOOLS = 20                # 代理程式請求才算（一般聊天只有 1–5 個工具）/ agent clients only
TOP_KS = (8, 12, 16, 20)


def client_of(n_tools: int) -> str:
    return "hermes" if n_tools < 100 else "opencode"


def collect(root: Path, min_tools: int = MIN_TOOLS) -> list[dict]:
    """讀所有軌跡，取出帶大量工具的請求；內容完全相同的只留一筆。 / Agent requests, exact duplicates removed."""
    out, seen = [], set()
    for f in sorted((root / "var" / "trajectories").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            req = rec.get("request") if isinstance(rec.get("request"), dict) else {}
            tools, msgs = req.get("tools"), req.get("messages")
            if not isinstance(tools, list) or len(tools) < min_tools or not isinstance(msgs, list):
                continue
            key = hashlib.sha256(json.dumps([msgs, tools], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            out.append({"id": rec.get("id"), "at": rec.get("at"), "policy": rec.get("policy"), "messages": msgs,
                        "tools": tools, "max_tokens": req.get("max_tokens") or req.get("max_completion_tokens")})
    return out


def _fits(messages, max_tokens):
    def check(ts):
        _, info = fit(messages, ts, max_tokens)
        return info["after"] <= SLOT_CTX - TOO_LARGE_ROOM
    return check


def measure(req: dict, top_k: int = TOP_K) -> dict:
    msgs, tools, mt = req["messages"], req["tools"], req.get("max_tokens")
    t0 = time.perf_counter()
    res = ladder(tools, msgs, _fits(msgs, mt), top_k=top_k)
    row = {"id": req["id"], "client": client_of(len(tools)), "tools": len(tools),
           "tokens_before": total(msgs, tools), "tokens_tools_before": total([], tools),
           "stage": res["stage"] or "fits_unfiltered", "kept": len(res["tools"]),
           "tokens_after": total(msgs, res["tools"]), "tokens_tools_after": total([], res["tools"])}
    if res["stage"] == "exhausted":
        small, before, after = with_compact_system(msgs)
        res2 = ladder(tools, small, _fits(small, mt), top_k=top_k)
        row.update(compact_stage=res2["stage"] if res2["fits"] else "exhausted",
                   compact_tokens_after=total(small, res2["tools"]), compact_chars=[before, after])
    row["latency_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return row


def retention_cases(reqs: list[dict]) -> list[dict]:
    """歷史裡每一次工具呼叫 → (呼叫前的訊息, 被呼叫的工具)。同一前綴只算一次。 / One case per real call."""
    cases, seen = [], set()
    for req in reqs:
        names = {tool_name(t) for t in req["tools"]}
        for k, m in enumerate(req["messages"]):
            for c in m.get("tool_calls") or [] if isinstance(m, dict) else []:
                name = (c.get("function") or {}).get("name") if isinstance(c, dict) else None
                if not name or name not in names:
                    continue
                prefix = req["messages"][:k]
                key = hashlib.sha256(json.dumps([prefix, name], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                if key in seen:
                    continue
                seen.add(key)
                cases.append({"req": req, "k": k, "name": name, "client": client_of(len(req["tools"])),
                              "new": name not in called_tools(prefix), "kept_list": name in KEEP_TOOLS})
    return cases


def retention(cases: list[dict], top_k: int) -> dict:
    out = {}
    for label, sub in (("all", cases), ("new_tool", [c for c in cases if c["new"]]),
                       ("new_not_keep_list", [c for c in cases if c["new"] and not c["kept_list"]])):
        hit = sum(1 for c in sub if c["name"] in select(c["req"]["tools"], c["req"]["messages"][:c["k"]],
                                                         top_k=top_k)["kept"])
        out[label] = {"n": len(sub), "kept": hit, "rate": round(hit / len(sub), 3) if sub else None}
    return out


def _pct(n, d):
    return f"{n}/{d}（{100 * n / d:.0f}%）" if d else "0/0"


def report(root: Path, today: str | None = None) -> tuple[Path, dict]:
    today = today or _dt.date.today().strftime("%Y%m%d")
    reqs = collect(root)
    rows = [measure(r) for r in reqs]
    cases = retention_cases(reqs)
    by_k = {k: {"retention": retention(cases, k),
                "stages": dict(Counter(measure(r, k)["stage"] for r in reqs)),
                "compact_stages": dict(Counter(x.get("compact_stage") for x in (measure(r, k) for r in reqs)
                                               if x.get("compact_stage")))} for k in TOP_KS}
    lat = [r["latency_ms"] for r in rows]
    summary = {
        "requests": len(rows), "clients": dict(Counter(r["client"] for r in rows)),
        "stages": dict(Counter(r["stage"] for r in rows)),
        "compact_stages": dict(Counter(r["compact_stage"] for r in rows if "compact_stage" in r)),
        "tokens_before_median": statistics.median([r["tokens_before"] for r in rows]) if rows else None,
        "tokens_after_median": statistics.median([r["tokens_after"] for r in rows]) if rows else None,
        "tool_tokens_before_median": statistics.median([r["tokens_tools_before"] for r in rows]) if rows else None,
        "tool_tokens_after_median": statistics.median([r["tokens_tools_after"] for r in rows]) if rows else None,
        "latency_ms_median": statistics.median(lat) if lat else None,
        "latency_ms_max": max(lat) if lat else None,
        "retention_cases": len(cases), "by_top_k": by_k,
    }
    out = root / "var" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    jl = out / f"tool-filter-{today}.jsonl"
    jl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    md = out / f"tool-filter-{today}.md"
    md.write_text(_markdown(summary, today), encoding="utf-8")
    return md, summary


def _markdown(s: dict, today: str) -> str:
    n = s["requests"]
    lines = [f"# 工具篩選離線量測 {today}（add-client-tool-filter 5.1–5.4）", "",
             f"- 樣本：軌跡裡帶 ≥{MIN_TOOLS} 個工具的真實代理請求，去重後 {n} 個（{s['clients']}）；不呼叫模型，純計算。",
             f"- 本機槽位 {SLOT_CTX} token，需留 {TOO_LARGE_ROOM} token 給回答；token 為 gateway 同款保守估算。", "",
             "## Token（中位數）", "",
             f"- 整個請求：{s['tokens_before_median']} → {s['tokens_after_median']}",
             f"- 只算工具清單：{s['tool_tokens_before_median']} → {s['tool_tokens_after_median']}", "",
             f"## 階段分布（top_k={TOP_K}）", ""]
    for k, v in sorted(s["stages"].items()):
        lines.append(f"- {k}：{_pct(v, n)}")
    if s["compact_stages"]:
        lines += ["", "工具篩完仍放不下（exhausted）→ 換精簡客戶端提示後：", ""]
        for k, v in sorted(s["compact_stages"].items()):
            lines.append(f"- {k}：{v}")
    lines += ["", f"## 延遲：ladder（含精簡）中位數 {s['latency_ms_median']} ms、最大 {s['latency_ms_max']} ms", "",
              f"## 保留工具準確率（歷史中 {s['retention_cases']} 次真實工具呼叫）與 top_k", "",
              "| top_k | 全部 | 新工具 | 新工具且不在保護清單 | 階段分布 | 精簡後 |", "|---|---|---|---|---|---|"]
    for k, v in s["by_top_k"].items():
        r = v["retention"]
        cell = lambda x: f"{x['kept']}/{x['n']}" + (f"（{100 * x['rate']:.0f}%）" if x["rate"] is not None else "")
        lines.append(f"| {k} | {cell(r['all'])} | {cell(r['new_tool'])} | {cell(r['new_not_keep_list'])} | "
                     f"{v['stages']} | {v['compact_stages']} |")
    lines += ["", "「新工具」＝呼叫當下之前沒呼叫過（不受「已呼叫過」保護），才真正考驗關鍵字排序；"
              "「之前呼叫過」的一律保護、保留率必為 100%。", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="offline tool-filter measurement (add-client-tool-filter 5.x)")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    a = ap.parse_args(argv)
    md, s = report(a.root)
    print(md)
    print(json.dumps({k: v for k, v in s.items() if k != "by_top_k"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

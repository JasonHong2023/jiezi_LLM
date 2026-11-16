"""關卡 G1 推薦（開發計畫 §6）：在 VRAM 預算內、速度達標的候選中，取推理／工具題分數最高者；
差距落在信賴區間內時偏好較小、較快的；知識題差距交給外掛資料（RAG、辭典、法規）補。
G1 recommendation (dev plan §6): among candidates that fit the VRAM budget and meet the speed target, take the
best reasoning/tool score; within the confidence interval prefer smaller and faster; knowledge gaps go to RAG.

只是推薦，最後由使用者決定（R4）。 / A recommendation only; the user decides (R4)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

MIN_TPS = 10.0       # 開發計畫 §1.3 Phase 4 互動速度 / interaction speed target


def candidates(root: Path) -> tuple[list[dict], list[str]]:
    from ..eval import e0
    rows, mhash = e0.load_matrix(root)
    state = e0.load_state(root, mhash)
    out, notes = [], []
    for r in rows:
        st = state.get("rows", {}).get(r.name, {})
        if r.placement_check:
            continue
        if st.get("state") != "verified":
            notes.append(f"{r.name}：{st.get('state', 'pending')}（尚未驗證完，不列入）")
            continue
        m = e0.row_metrics(root / "var" / "eval" / "runs" / r.run_id)
        if m["reasoning"]["acc"] is None or m["reasoning"]["pending"]:
            notes.append(f"{r.name}：推理題還有 {m['reasoning']['pending']} 題待驗證，不列入")
            continue
        out.append({"name": r.name, "size_mib": round(r.size / 2**20), "placement": st.get("placement"),
                    "reasoning": m["reasoning"]["acc"], "reasoning_ci": m["reasoning"]["ci95"],
                    "knowledge": m["knowledge"]["acc"], "faithful": m.get("summary_faithfulness"),
                    "tps": m.get("tps") or 0.0, "ram": m.get("peak_ram_mib"), "vram": m.get("peak_vram_mib")})
    return out, notes


def recommend(cands: list[dict]) -> dict:
    eligible = [c for c in cands if c["tps"] >= MIN_TPS]
    slow = [c["name"] for c in cands if c["tps"] < MIN_TPS]
    if not eligible:
        return {"winner": None, "reason": "沒有速度達標（≥ 10 t/s）且驗證完成的候選", "slow": slow}
    top = max(eligible, key=lambda c: c["reasoning"])
    lo = (top["reasoning_ci"] or (top["reasoning"], top["reasoning"]))[0]
    # 與第一名在信賴區間內打平的，選檔案較小、速度較快的 / ties within the CI go to smaller, faster models
    tied = [c for c in eligible if c["reasoning"] >= lo]
    winner = min(tied, key=lambda c: (c["size_mib"], -c["tps"]))
    best_know = max(eligible, key=lambda c: c["knowledge"] or 0)
    gap = round(((best_know["knowledge"] or 0) - (winner["knowledge"] or 0)) * 100, 1)
    return {"winner": winner, "top_reasoning": top, "tied": [c["name"] for c in tied], "slow": slow,
            "knowledge_gap_points": gap, "best_knowledge": best_know["name"],
            "reason": (f"推理／工具題 {winner['reasoning'] * 100:.1f}%" +
                       (f"，與最高分 {top['name']}（{top['reasoning'] * 100:.1f}%）在 95% 信賴區間內打平，選較小、較快者"
                        if winner is not top else "，為最高分") +
                       f"；{winner['tps']:.0f} t/s、{winner['size_mib']} MiB")}


def report(root: Path) -> tuple[Path, dict]:
    cands, notes = candidates(root)
    rec = recommend(cands)
    pct = lambda x: "—" if x is None else f"{x * 100:.1f}%"  # noqa: E731
    md = [f"# 關卡 G1 推薦 / G1 recommendation（{datetime.now().astimezone().isoformat(timespec='minutes')}）", "",
          "判準（開發計畫 §6）：VRAM 預算內、≥ 10 t/s 的候選中取推理／工具題最高者；信賴區間內打平時選較小、較快的；"
          "知識題差距交給外掛資料補。**這是推薦，最後由使用者決定（R4）。**", ""]
    w = rec.get("winner")
    if w:
        md += [f"## 推薦：`{w['name']}`", "", f"- 理由：{rec['reason']}",
               f"- 知識題：{pct(w['knowledge'])}（最高的 {rec['best_knowledge']} 多 {rec['knowledge_gap_points']} 分；"
               "由辭典、課綱、Taiwan.md、法規與記憶補足）",
               f"- 與最高分打平的候選：{'、'.join(rec['tied'])}", ""]
    else:
        md += [f"## 尚無推薦：{rec['reason']}", ""]
    md += ["## 候選 / Candidates", "", "| 模型 | MiB | 擺放 | 推理／工具 (95% CI) | 知識 | 摘要忠實 | t/s |", "|---|---|---|---|---|---|---|"]
    for c in sorted(cands, key=lambda c: -c["reasoning"]):
        ci = c["reasoning_ci"]
        ci_s = f"（{ci[0] * 100:.0f}–{ci[1] * 100:.0f}%）" if ci else ""
        md.append(f"| {c['name']} | {c['size_mib']} | {c['placement']} | {pct(c['reasoning'])}{ci_s} | {pct(c['knowledge'])} | "
                  f"{c['faithful'] if c['faithful'] is not None else '—'} | {c['tps']:.1f} |")
    if rec.get("slow"):
        md += ["", f"速度未達 10 t/s：{'、'.join(rec['slow'])}"]
    if notes:
        md += ["", "## 未列入 / Not included", ""] + [f"- {n}" for n in notes]
    out = root / "var" / "reports" / "g1-recommendation.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    return out, rec

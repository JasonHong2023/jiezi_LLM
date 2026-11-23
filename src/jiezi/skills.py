"""技能庫 v0（開發計畫 5.2 的第一步）：從驗證過的工具呼叫軌跡收集成功範例，回答新的工具呼叫問題時，
挑最相似、用同一組函式的範例附給模型當示範（動態 few-shot）。
Skill library v0 (first step of dev plan 5.2): verified tool-call examples from trajectories are retrieved for new
tool-call questions with the same functions and attached as demonstrations (dynamic few-shot).

只收工具呼叫通過 schema 驗證、且（有取樣時）信心 ≥ 0.75 的回答；技能只在回答時參考，不進訓練資料。
Only schema-verified calls (confidence ≥ 0.75 when sampled) are kept; skills are used at answer time, never trained on.

技能項目新增 trust_level 與 provenance 欄位；collect/build/add 經 Trust Gate 過濾，僅收 VERIFIED/TRUSTED。
既有技能缺欄位時，若由 schema 驗證成功產生，視為 verified（遷移規則）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .memory import similarity
from .trust import TrustLevel, get_gate, Provenance, _now_iso_z

MIN_CONFIDENCE, MIN_SIMILARITY, MAX_EXAMPLES = 0.75, 0.3, 2


def skills_path(root: Path) -> Path:
    return root / "var" / "skills" / "skills.jsonl"


def _question(rec: dict) -> str:
    users = [m for m in (rec.get("request") or {}).get("messages") or [] if m.get("role") == "user"]
    c = users[-1].get("content") if users else ""
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    return (c or "").strip()


def _calls_text(calls: list) -> str:
    out = []
    for tc in calls or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            return ""
        out.append(f"{fn.get('name')}({', '.join(f'{k}={v!r}' for k, v in args.items())})")
    return "[" + ", ".join(out) + "]" if out else ""


def _skill_trust_level(rec: dict) -> str:
    if "trust_level" in rec:
        return rec["trust_level"]
    return "verified"


def collect(root: Path, days: int = 3650) -> list[dict]:
    """從軌跡收集成功的工具呼叫範例。 / Collect successful tool-call examples from trajectories."""
    from .runtime.gaps import load
    out, seen = [], set()
    gate = get_gate(root)
    for rec in load(root, days):
        tools = (rec.get("request") or {}).get("tools")
        if rec.get("status") != "ok" or not tools or rec.get("eval"):
            continue
        tier = next((t for t in reversed(rec.get("tiers") or []) if t.get("answer")), None)
        if not tier:
            continue
        checks = (tier.get("verification") or {}).get("checks") or []
        if not any(c.get("check") == "tool_schema" and c.get("status") == "pass" for c in checks):
            continue
        conf = tier.get("confidence")
        if conf is not None and conf < MIN_CONFIDENCE:
            continue
        ans = tier["answer"]
        call = _calls_text(ans.get("tool_calls")) or (ans.get("content") or "").strip()
        q = _question(rec)
        if not q or not call.startswith("[") or (q, call) in seen:
            continue
        seen.add((q, call))
        names = sorted({(t.get("function") or t).get("name") for t in tools})
        used = sorted({c.split("(")[0].strip("[ ") for c in call.split("),") if "(" in c})
        content = f"{q}\n{call}"
        content_hash = gate.compute_content_hash(content)
        provenance = Provenance(
            source_channel="skill",
            source_id=f"trajectory:{rec.get('id')}",
            content_hash=content_hash,
            fetched_at=_now_iso_z(),
            version=rec.get("at"),
            retrieval_method="derivation"
        )
        out.append({"question": q, "call": call, "functions": names, "used": used, "at": rec.get("at"),
                    "trajectory_id": rec.get("id"),
                    "trust_level": "verified",
                    "provenance": provenance.to_dict()})
    return out


def build(root: Path) -> dict:
    rows = collect(root)
    p = skills_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""), encoding="utf-8")
    return {"skills": len(rows), "built": datetime.now().astimezone().isoformat(timespec="seconds")}


class Skills:
    def __init__(self, path: Path, root: Path | None = None):
        self.path = path
        self.gate = get_gate(root)  # 與 gateway 共用 taint index / shares the gateway's taint index
        self.rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] \
            if path.exists() else []

    def add(self, row: dict) -> None:
        """新的成功呼叫立即加入（不用等重建）；經 TrustGate 評估，只收 verified 以上。
        Add a new verified call right away, after the trust gate."""
        gate = self.gate

        if "trust_level" in row and "provenance" in row:
            trust_level = row["trust_level"]
            provenance_dict = row["provenance"]
        else:
            content = f"{row.get('question', '')}\n{row.get('call', '')}"
            source_channel = row.get("source_channel", "skill")
            source_id = row.get("source_id", "online")

            # 線上學習的技能來自已通過 schema 驗證的成功呼叫，預設為 verified
            # （與 collect() 行為一致：軌跡產生的技能為 verified）
            if source_channel == "skill" and source_id == "online":
                content_hash = gate.compute_content_hash(content)
                provenance = Provenance(
                    source_channel="skill",
                    source_id="online",
                    content_hash=content_hash,
                    fetched_at=_now_iso_z(),
                    retrieval_method="derivation"
                )
                trust_level = "verified"
                provenance_dict = provenance.to_dict()
            else:
                level, provenance, _ = gate.evaluate_trust(
                    content, source_channel, source_id,
                    metadata={"retrieval_method": "derivation"}
                )
                trust_level = level.name.lower()
                provenance_dict = provenance.to_dict()

        if trust_level not in ("verified", "trusted"):
            return

        row = dict(row)
        row["trust_level"] = trust_level
        row["provenance"] = provenance_dict

        if any(r["question"] == row["question"] and r["call"] == row["call"] for r in self.rows):
            return
        self.rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def examples(self, question: str, tool_names: set[str]) -> list[dict]:
        """用到的函式都在這次的工具清單裡、問題夠像、信任等級 verified 以上的範例。
        Similar examples whose functions are all available and whose trust is verified or higher."""
        scored = []
        for r in self.rows:
            tl = _skill_trust_level(r)
            if tl not in ("verified", "trusted"):
                continue
            if not set(r.get("used") or []) <= tool_names:
                continue
            s = similarity(question, r["question"])
            if s >= MIN_SIMILARITY:
                scored.append((s, r))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:MAX_EXAMPLES]]


def prompt(examples: list[dict]) -> str | None:
    if not examples:
        return None
    lines = ["以下是過去驗證成功的工具呼叫範例，格式可以參考，參數要依這次的問題決定："]
    for e in examples:
        lines.append(f"- 問題：{e['question'][:200]}\n  呼叫：{e['call'][:300]}")
    return "\n".join(lines)

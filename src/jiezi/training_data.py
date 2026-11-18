"""訓練資料匯出：Phase 6 的 SFT 教材（add-training-data；規則 R20.3、R18.3）。
Training-data export: SFT material for Phase 6 (rules R20.3, R18.3).

兩種來源 / Two sources：
1. 軌跡：本機自己答、且驗證通過（R20.3：教材必須先過驗證器）的回答；含不可訓練來源或被標為不可訓練的一律排除。
   Trajectories: local answers that passed verification; anything touching non-trainable material is excluded.
2. 範本問答：從可訓練的資料（法規、課綱、課本、Taiwan.md）以範本產生，答案直接取自原文。
   Templates over trainable data, answers taken verbatim.

和評測重疊的題目（自我評測、R0 題庫）一律剔除，避免污染評測。每筆都帶來源、授權與雜湊。
Questions overlapping evaluation (self-test, R0 bank) are dropped. Every example carries source, license and hash."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

SEED = 20261117
# 不可訓練的來源（授權禁止改作、或是第三方輸出）/ non-trainable sources
NON_TRAINABLE = {"moedict-revised", "moedict-twblg", "moedict-hakka", "rocknovels-teachlist", "hackmd-chemistry"}
LOCAL_TIERS = {0, 1, "think"}   # 本機作答、帶錯誤重答、思考模式重答（local-first-solving）
# 夠強、可以當教材的驗證：工具呼叫 schema。答案查核只看數字與引號（「刈包是四川菜」也會通過），
# 程式只檢查語法，都不足以證明答案正確（2026-11-16）。
# Strong enough to make teaching material: tool-call schema checks. The grounded check only covers numbers and
# quotes, and code is only syntax-checked, so neither proves an answer right.
STRONG_CHECKS = {"tool_schema"}


def _norm(q: str) -> str:
    return re.sub(r"[\s\W_]+", "", q or "").lower()


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def eval_targets(root: Path) -> tuple[set[str], set[str]]:
    """評測用到的題目（正規化）與「目標」（課本冊別、課綱主題、法條、文章名）。
    同一目標換個問法也會洩題（「第 3 單元是什麼」vs「有哪些單元」），所以目標出現在訓練題裡就剔除。
    Normalized evaluation questions plus their targets; a target in a training question is a leak."""
    from .selftest import build
    items = build(root)
    qs = {_norm(i.question) for i in items}
    targets = set()
    for i in items:
        if i.kind == "textbook":
            targets.add(_norm(i.question.split("的第")[0]))
        elif i.kind in ("curriculum", "knowledge", "dict-zh", "dict-tw"):
            m = re.search(r"「(.+?)」", i.question)
            if m:
                targets.add(_norm(m.group(1)))
        elif i.kind == "laws":
            targets.add(_norm(i.question.replace("規定什麼？", "")))
    bank = root / "var" / "eval" / "banks" / "r0" / "items.jsonl"
    if bank.exists():
        for line in bank.read_text(encoding="utf-8").splitlines():
            d = json.loads(line).get("data") or {}
            for k in ("question", "prompt", "instruction"):
                if isinstance(d.get(k), str):
                    qs.add(_norm(d[k]))
    return qs, {t for t in targets if len(t) >= 2}


def _ex(messages, answer, source, license_, origin, **extra) -> dict:
    msgs = [*messages, {"role": "assistant", "content": answer}]
    return {"messages": msgs, "source": source, "license": license_, "training_use": True, "origin": origin,
            "sha256": _sha(msgs), **extra}


# ── 1. 軌跡 / Trajectories ──
def from_trajectories(root: Path, days: int = 3650) -> tuple[list[dict], Counter]:
    from .runtime.gaps import load
    out, why = [], Counter()
    for rec in load(root, days):
        if rec.get("status") != "ok" or rec.get("policy") not in ("jiezi", "jiezi-local"):
            why["not_local_policy_or_error"] += 1
            continue
        if (rec.get("injection") or {}).get("suspected"):  # 疑似提示注入（add-injection-guard）/ suspected injection
            why["suspected_injection"] += 1
            continue
        if rec.get("training_use") is False:
            why["marked_not_trainable"] += 1
            continue
        if rec.get("eval"):
            why["evaluation_traffic"] += 1
            continue
        if rec.get("final_tier") not in LOCAL_TIERS:
            why["not_answered_locally"] += 1
            continue
        if any(s.get("source") in NON_TRAINABLE for s in rec.get("sources") or []):
            why["non_trainable_source"] += 1
            continue
        meta = rec.get("jiezi") or {}
        if meta.get("verification") != "pass":  # R20.3：只收驗證通過的 / verified only
            why["not_verified"] += 1
            continue
        # 取最後一個「通過檢查」的本機答案：階梯裡先答錯、重答才對時，要的是對的那一次（使用者 2026-11-18：本機在階梯
        # 自己答對的答案當訓練資料）/ the last local answer that passed: on the ladder, the corrected one
        tier = next((t for t in reversed(rec.get("tiers") or []) if t.get("tier") in LOCAL_TIERS and t.get("answer")
                     and (t.get("verification") or {}).get("status") == "pass"), None)
        if not tier:
            why["no_answer"] += 1
            continue
        checks = (tier.get("verification") or {}).get("checks") or []
        if not any(c.get("check") in STRONG_CHECKS and c.get("status") == "pass" for c in checks):
            why["weak_verification"] += 1
            continue
        answer = (tier["answer"].get("content") or "").split("\n\n---\n", 1)[0].strip()  # 去掉 gateway 附錄 / no appendix
        calls = tier["answer"].get("tool_calls")
        if not answer and not calls:
            why["empty_answer"] += 1
            continue
        msgs = [m for m in (rec.get("request") or {}).get("messages") or [] if m.get("role") in ("system", "user", "assistant")]
        ex = _ex(msgs, answer, "trajectory", "local-model-output (Qwen3 Apache-2.0)", "trajectory",
                 trajectory_id=rec.get("id"), sources=[s.get("source") for s in rec.get("sources") or []],
                 **({"ladder_step": (rec.get("ladder") or {}).get("solved_by")} if rec.get("ladder") else {}))
        if calls:
            ex["messages"][-1]["tool_calls"] = calls
            ex["tools"] = (rec.get("request") or {}).get("tools")
        out.append(ex)
    return out, why


# ── 2. 範本 / Templates ──
def from_laws(root: Path, rng: random.Random, limit: int) -> list[dict]:
    from .laws import Laws, current_ids, db_path, load_manifest
    try:
        lw, src = Laws(db_path(root)), load_manifest(root)
    except Exception:  # noqa: BLE001 - 沒建置就跳過 / skipped when not built
        return []
    ids = current_ids(lw)
    out = []
    for aid in rng.sample(ids, min(limit, len(ids))):
        a = lw.by_id(aid)
        if len(a["text"]) < 10:
            continue
        q = f"{a['law']}{a['no'].replace(' ', '')}規定什麼？"
        out.append(_ex([{"role": "user", "content": q}], f"{a['law']}{a['no'].replace(' ', '')}規定：\n{a['text']}",
                       src["key"], src["license"], "template"))
    return out


def from_curriculum(root: Path, rng: random.Random, limit: int) -> list[dict]:
    from .curriculum import Graph
    try:
        g = Graph.load(root)
    except Exception:  # noqa: BLE001
        return []
    out, lic = [], g.src.license
    for tid in sorted(g.topics):
        t = g.topics[tid]
        pre = [g.topics[p]["name"] for p, s in g.prereq[tid] if s == "hard"]
        if pre:
            out.append(_ex([{"role": "user", "content": f"國小{t['subject']}的「{t['name']}」要先學會什麼？"}],
                           f"要先學會：{'、'.join(pre)}。\n{t.get('description', '')}", g.src.key, lic, "template"))
    if g.tsrc:
        for tb in g.textbooks:
            units = "；".join(f"{n}. {u}" for n, (u, _s) in enumerate(tb["units"], 1))
            out.append(_ex([{"role": "user", "content": f"{tb['level']}{tb['subject']} {tb['volume']} {tb['publisher']}有哪些單元？"}],
                           units, g.tsrc.key, g.tsrc.license, "template"))
    rng.shuffle(out)
    return out[:limit]


def from_knowledge(root: Path, rng: random.Random, limit: int) -> list[dict]:
    from .knowledge import Knowledge, db_path, load_manifest
    try:
        k, src = Knowledge(db_path(root)), load_manifest(root)
    except Exception:  # noqa: BLE001
        return []
    rows = k.con.execute("SELECT a.name, s.text FROM articles a JOIN sections s ON s.article = a.id "
                         "WHERE s.id = (SELECT MIN(id) FROM sections WHERE article = a.id)").fetchall()
    out = []
    for name, text in rng.sample(rows, min(limit, len(rows))):
        if len(text) > 80:
            out.append(_ex([{"role": "user", "content": f"請簡單介紹「{name}」。"}], text[:800].strip(),
                           src.key, src.license, "template"))
    return out


def _overlaps(ex: dict, banned: set[str], targets: set[str]) -> bool:
    q = next((m["content"] for m in reversed(ex["messages"][:-1]) if m["role"] == "user"), "")
    nq = _norm(q)
    return nq in banned or any(t in nq for t in targets)


def mix_replay(kept: list[dict], replay: list[dict], ratio: float, rng: random.Random) -> list[dict]:
    """把複習資料補到佔全部的 ratio（題目不夠就重複取樣，每輪打亂），再和新資料一起打亂。
    Top replay up to `ratio` of the total (repeating, reshuffled each pass, when short), then shuffle everything."""
    if not replay or ratio <= 0:
        return kept
    want = round(len(kept) * ratio / (1 - ratio))
    picked: list[dict] = []
    while len(picked) < want:
        batch = replay[:]
        rng.shuffle(batch)
        picked += batch[:want - len(picked)]
    out = kept + picked
    rng.shuffle(out)
    return out


def export(root: Path, limit_per_source: int = 2000, replay: Path | None = None,
           replay_ratio: float = 0.0) -> tuple[Path, dict]:
    """replay：凍結核心通過驗證的回答（add-sft-round2），依 replay_ratio 混入。
    replay: verified answers of the frozen core (add-sft-round2), mixed in at replay_ratio."""
    if not 0 <= replay_ratio < 1:
        raise ValueError("replay_ratio must be in [0, 1)")
    rng = random.Random(SEED)
    banned, targets = eval_targets(root)
    traj, why = from_trajectories(root)
    pool = traj + from_laws(root, rng, limit_per_source) + from_curriculum(root, rng, limit_per_source) + \
        from_knowledge(root, rng, limit_per_source)
    kept, seen = [], set()
    for ex in pool:
        if _overlaps(ex, banned, targets):
            why["overlaps_evaluation"] += 1
            continue
        if ex["sha256"] in seen:
            why["duplicate"] += 1
            continue
        seen.add(ex["sha256"])
        kept.append(ex)
    rep: list[dict] = []
    if replay is not None:
        for line in replay.read_text(encoding="utf-8").splitlines():
            ex = json.loads(line)
            if not ex.get("training_use") or _overlaps(ex, banned, targets):
                why["replay_overlaps_evaluation" if ex.get("training_use") else "replay_not_trainable"] += 1
                continue
            rep.append(ex)
    kept = mix_replay(kept, rep, replay_ratio, rng)
    out = root / "var" / "training" / f"sft-{date.today().isoformat()}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in kept) + ("\n" if kept else ""), encoding="utf-8")
    manifest = {"created": datetime.now().astimezone().isoformat(timespec="seconds"), "file": out.name,
                "examples": len(kept), "by_source": dict(Counter(e["source"] for e in kept)),
                "licenses": dict(Counter(e["license"] for e in kept)), "excluded": dict(why),
                "rules": "R20.3 verified only; non-trainable sources and evaluation overlaps removed",
                "limit_per_source": limit_per_source, "replay_ratio": replay_ratio, "replay_unique": len(rep)}
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return out, manifest

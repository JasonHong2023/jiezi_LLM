"""E0 多模型對照（規格 e0-benchmark；add-e0-benchmark design D1–D7）。
E0 multi-model comparison (spec e0-benchmark; add-e0-benchmark design D1–D7).

子指令 / Subcommands（`scripts/eval e0 …`）：
  plan     依當下預算判斷擺放與預估時間（秒級）/ placement and time estimate against current budgets (second-scale)
  fetch    下載矩陣中的模型並核對 SHA-256（夜間）/ download matrix models and verify SHA-256 (night)
  run      冒煙 → 評測 → 驗證，逐列、跨夜續跑（夜間）/ smoke → run → verify per row, resumable (night)
  sample   前 3 名的 N=8 取樣設定（夜間）/ N=8 sampled setting for the top 3 (night)
  report   帕累托報表與 SVG 圖（秒級）/ Pareto report and SVG charts (second-scale)"""

from __future__ import annotations

import hashlib
import json
import math
import re
import tomllib
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import EvalError, prompts, report, scoring
from .runner import latest_results, now
from .verify_run import latest_verifications

GROUPS = ("ternary", "1-bit", "int8", "int4", "int2")
PLACEMENTS = ("gpu", "cpu")
CPU_ONLY_QUANTS = {"TQ1_0", "TQ2_0"}  # 2026-11-14 實測沒有 CUDA kernel / no CUDA kernels (measured)
OVERHEAD_MIB = 1024  # 上下文 4096 的 KV 快取與計算緩衝估計 [估] / KV cache + compute buffers at ctx 4096 [est.]
MANIFEST_REQUIRED = ("name", "file", "url", "sha256", "size", "license", "license_url",
                     "commercial_use", "training_use", "license_checked", "source")
# 時間預估基準：Qwen3-0.6B-Q8_0（639,446,688 位元組）純 CPU 300 題 29 分鐘（2026-11-15）。
# Estimate anchor: Qwen3-0.6B-Q8_0 (639,446,688 bytes), CPU only, 300 items in 29 minutes (2026-11-15).
REF_BYTES, REF_MINUTES = 639_446_688, 29.0
GPU_SPEED_FACTOR = 0.35  # GPU 相對 CPU 的時間比例 [估]；實測後由 plan 更新 / GPU time relative to CPU [est.]
CTX = 4096
SAMPLE_N, SAMPLE_T, SAMPLE_TOP = 8, 0.7, 3
SAMPLE_TASKS = ("code", "tool")
DONE_STATES = ("verified",)
EXCLUDED = ("excluded_budget", "excluded_smoke")


@dataclass(frozen=True)
class Row:
    name: str
    model: str
    group: str
    base: str
    quant: str
    placement: str
    file: str
    size: int
    sha256: str
    url: str
    reference_run: str | None = None
    placement_check: bool = False

    @property
    def size_mib(self) -> float:
        return self.size / 2**20

    @property
    def run_id(self) -> str:
        return self.reference_run or f"e0-{self.name}"


# ── 矩陣 / Matrix ───────────────────────────────────────────────────────────

def load_matrix(root: Path, matrix: Path | None = None, manifest: Path | None = None) -> tuple[list[Row], str]:
    """讀矩陣並對照模型清單；欄位缺漏（含授權）就停止。回傳 (列, 矩陣雜湊)。
    Read the matrix against the manifest; stop on any missing field (licenses included). Return (rows, hash)."""
    matrix = matrix or root / "eval" / "e0" / "matrix.toml"
    manifest = manifest or root / "models" / "manifest.toml"
    raw = matrix.read_bytes()
    models = {m.get("name"): m for m in tomllib.loads(manifest.read_text(encoding="utf-8")).get("model") or []}
    rows, seen = [], set()
    for r in tomllib.loads(raw.decode("utf-8")).get("row") or []:
        name = r.get("name")
        if not name or name in seen:
            raise EvalError(f"{matrix}: missing or duplicate row name {name!r}")
        seen.add(name)
        m = models.get(r.get("model"))
        if m is None:
            raise EvalError(f"{matrix}: row {name}: model {r.get('model')!r} is not in {manifest.name}")
        missing = [k for k in MANIFEST_REQUIRED if m.get(k) in (None, "")]
        if missing:
            raise EvalError(f"{manifest.name}: {m['name']} is missing {', '.join(missing)} (license fields are mandatory)")
        if r.get("group") not in GROUPS or r.get("placement") not in PLACEMENTS or not r.get("base") or not r.get("quant"):
            raise EvalError(f"{matrix}: row {name} needs group in {GROUPS}, placement in {PLACEMENTS}, base and quant")
        rows.append(Row(name=name, model=m["name"], group=r["group"], base=r["base"], quant=r["quant"],
                        placement=r["placement"], file=m["file"], size=int(m["size"]), sha256=str(m["sha256"]).lower(),
                        url=m["url"], reference_run=r.get("reference_run"),
                        placement_check=bool(r.get("placement_check", False))))
    if not rows:
        raise EvalError(f"{matrix}: no [[row]] entries")
    return rows, hashlib.sha256(raw).hexdigest()[:12]


def state_dir(root: Path, mhash: str) -> Path:
    return root / "var" / "eval" / "e0" / mhash


def load_state(root: Path, mhash: str) -> dict:
    p = state_dir(root, mhash) / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"matrix_hash": mhash, "rows": {}}


def save_state(root: Path, mhash: str, state: dict) -> None:
    d = state_dir(root, mhash)
    d.mkdir(parents=True, exist_ok=True)
    state["updated"] = now()
    (d / "state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def row_state(state: dict, name: str) -> dict:
    return state["rows"].setdefault(name, {"state": "pending"})


# ── 擺放與預估 / Placement and estimate ─────────────────────────────────────

def place(row: Row, budgets: dict) -> dict:
    """design D2：整個放 GPU，否則純 CPU，放不下就排除。 / Whole model on GPU, else CPU only, else excluded."""
    vram = ((budgets.get("vram") or {}).get("usable_mib")) or 0
    ram = ((budgets.get("ram") or {}).get("usable_mib")) or 0
    need = row.size_mib + OVERHEAD_MIB
    out = {"intended": row.placement, "need_mib": round(need), "vram_usable_mib": vram, "ram_usable_mib": ram}
    if row.placement == "gpu":
        if row.quant in CPU_ONLY_QUANTS:
            reason = f"{row.quant} has no CUDA kernels"
        elif need > vram:
            reason = f"needs about {round(need)} MiB but {vram} MiB VRAM is usable"
        else:
            return {**out, "placement": "gpu", "ngl": 99, "reason": None}
    else:
        reason = None
    if need > ram:
        return {**out, "placement": None, "ngl": None, "excluded": "excluded_budget",
                "reason": f"needs about {round(need)} MiB but {ram} MiB RAM is usable"}
    return {**out, "placement": "cpu", "ngl": 0, "reason": reason}


def estimate_minutes(row: Row, placement: str | None, measured: dict | None = None) -> float | None:
    """以檔案大小按比例推算（解碼受記憶體頻寬限制）；有實測就用實測的比例。
    Scale by file size (decoding is memory-bound); use measured ratios when available."""
    if placement is None:
        return None
    base = REF_MINUTES * row.size / REF_BYTES
    factor = (measured or {}).get(placement, GPU_SPEED_FACTOR if placement == "gpu" else 1.0)
    return round(base * factor, 1)


def plan(rows: list[Row], state: dict, budgets: dict) -> list[dict]:
    out = []
    for r in rows:
        st = state["rows"].get(r.name, {"state": "pending"})
        p = place(r, budgets)
        todo = st["state"] not in DONE_STATES + EXCLUDED and not r.reference_run
        out.append({"row": r.name, "group": r.group, "quant": r.quant, "size_mib": round(r.size_mib),
                    "state": st["state"], "placement": p.get("placement"), "excluded": p.get("excluded"),
                    "reason": p.get("reason"),
                    "est_minutes": estimate_minutes(r, p.get("placement")) if todo else 0})
    return out


# ── 下載 / Download ─────────────────────────────────────────────────────────

def _download(url: str, dest: Path, log=print) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "jiezi-eval"})
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as fh:
        total, done, nxt = int(r.headers.get("Content-Length") or 0), 0, 0.25
        while chunk := r.read(1 << 20):
            fh.write(chunk)
            done += len(chunk)
            if total and done / total >= nxt:
                log(f"    {done * 100 // total}%")
                nxt += 0.25


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def ensure_model(row: Row, models_dir: Path, download: Callable = _download, log=print) -> Path:
    """模型存在且大小、SHA-256 吻合就回傳；否則下載並核對。不覆蓋不明檔案。
    Return the model when size and SHA-256 match; else download and verify. Never overwrites an unknown file."""
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / row.file
    if path.exists():
        if path.stat().st_size == row.size and _sha256(path) == row.sha256:
            return path
        raise EvalError(f"{path} exists but does not match the manifest; remove it to re-download")
    part = path.with_name(path.name + ".part")
    part.unlink(missing_ok=True)
    log(f"  downloading {row.model} ({round(row.size_mib)} MiB)")
    try:
        download(row.url, part, log)
        if part.stat().st_size != row.size or _sha256(part) != row.sha256:
            raise EvalError(f"{row.model}: downloaded file does not match the manifest SHA-256; deleted")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(path)
    return path


# ── 冒煙檢查 / Smoke check（design D3）──────────────────────────────────────

SMOKE_KINDS = ("multiple_choice", "simpleqa", "code", "tool", "summary")


def smoke_items(items: list[dict]) -> list[dict]:
    """每種題型取 (source, id) 排序後的第一題，固定不變。 / The first item of each kind by (source, id); fixed."""
    out = []
    for k in SMOKE_KINDS:
        cands = sorted((i for i in items if prompts.kind(i) == k), key=lambda i: (i["source"], i["id"]))
        if not cands:
            raise EvalError(f"the bank has no {k} item for the smoke check")
        out.append(cands[0])
    return out


def _parses(item: dict, content: str) -> bool:
    from ..verify import tool_call
    text = scoring.strip_thinking(content).strip()
    k = prompts.kind(item)
    if k == "multiple_choice":
        return scoring.extract_choice(text) is not None
    if k == "code":
        return "def " in text
    if k == "tool":
        try:
            tool_call.parse_calls(text)
            return True
        except tool_call.Unparsed:
            return False
    if k == "summary":
        return len(text) >= 20
    return bool(text)


def judge_smoke(answers: list[tuple[dict, str | None]]) -> dict:
    """answers: (題目, 回答或 None)。 / answers: (item, content or None)."""
    reasons, parsed = [], 0
    for item, content in answers:
        k = prompts.kind(item)
        if not content or not content.strip():
            reasons.append(f"{k}: empty answer")
            continue
        if "<think>" in content:
            reasons.append(f"{k}: thinking content present (thinking not disabled)")
        if _parses(item, content):
            parsed += 1
    if parsed < 3:
        reasons.append(f"only {parsed}/5 answers parse")
    return {"ok": not reasons, "parsed": parsed, "reasons": reasons}


# ── 指標 / Metrics ──────────────────────────────────────────────────────────

def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)


def row_metrics(run_dir: Path) -> dict:
    """知識題（選擇題 + SimpleQA）與推理題（程式 + 工具）的分數。SimpleQA 有完整評審時用評審，否則用近似比對。
    Knowledge (MC + SimpleQA) and reasoning (code + tool) scores; SimpleQA uses the judge when fully judged."""
    rep = report.build(run_dir)
    verifs = latest_verifications(run_dir)
    records = report._overlay(list(latest_results(run_dir).values()), verifs)  # noqa: SLF001 - 同套件 / same package
    know = [r for r in records if r["group"] == "knowledge"]
    mc = [r for r in know if r["scorer"] == "multiple_choice" and r["score"] is not None]
    sqa = [r for r in know if r["scorer"] == "simpleqa_approx"]
    judged = [verifs.get((r["key"], "simpleqa_judge")) for r in sqa]
    use_judge = bool(sqa) and all(v and v["status"] in ("correct", "incorrect", "not_attempted") for v in judged)
    sqa_correct = sum(v["status"] == "correct" for v in judged) if use_judge else \
        sum(r["score"] or 0 for r in sqa if r["score"] is not None)
    sqa_n = len(sqa) if use_judge else sum(r["score"] is not None for r in sqa)
    k_correct, k_n = sum(r["score"] for r in mc) + sqa_correct, len(mc) + sqa_n
    reas = [r for r in records if r["task"] in SAMPLE_TASKS]
    r_scored = [r for r in reas if r["score"] is not None and r["status"] != "pending_verifier"]
    r_correct = sum(r["score"] for r in r_scored)
    sj = rep["verification"].get("summary_judge") or {}
    return {
        "knowledge": {"correct": k_correct, "n": k_n, "acc": round(k_correct / k_n, 4) if k_n else None,
                      "ci95": wilson(k_correct, k_n), "simpleqa": "judge" if use_judge else "approx"},
        "reasoning": {"correct": r_correct, "n": len(r_scored), "pending": len(reas) - len(r_scored),
                      "acc": round(r_correct / len(r_scored), 4) if r_scored else None,
                      "ci95": wilson(r_correct, len(r_scored))},
        "summary_faithfulness": sj.get("faithfulness_mean"), "summary_coverage": sj.get("coverage_mean"),
        "tps": (rep["tokens_per_second"] or {}).get("mean"), "latency_s": (rep["latency_s"] or {}).get("mean"),
        "peak_ram_mib": rep["peak_memory"]["ram_mib"], "peak_vram_mib": rep["peak_memory"]["vram_mib"],
        "ngl": ((rep["conditions"]["identity"].get("engine") or {}).get("ngl")),
        "completeness": rep["completeness"],
    }


def pareto_front(points: list[tuple[str, float, float]]) -> list[str]:
    """(名稱, 大小, 分數)：沒有其他點「更小或一樣大且分數更高或一樣，且至少一項嚴格更好」。
    (name, size, score): no other point is at most as large and at least as good, strictly better in one."""
    front = []
    for n, s, a in points:
        if not any((s2 <= s and a2 >= a) and (s2 < s or a2 > a) for n2, s2, a2 in points if n2 != n):
            front.append(n)
    return front


MARKERS = {"ternary": "triangle", "1-bit": "diamond", "int8": "square", "int4": "circle", "int2": "cross"}
COLORS = {"ternary": "#c0392b", "1-bit": "#8e44ad", "int8": "#2471a3", "int4": "#1e8449", "int2": "#b9770e"}


def _marker(kind: str, x: float, y: float, color: str) -> str:
    if kind == "triangle":
        return f'<polygon points="{x},{y - 6} {x - 6},{y + 5} {x + 6},{y + 5}" fill="{color}"/>'
    if kind == "diamond":
        return f'<polygon points="{x},{y - 7} {x + 6},{y} {x},{y + 7} {x - 6},{y}" fill="{color}"/>'
    if kind == "square":
        return f'<rect x="{x - 5}" y="{y - 5}" width="10" height="10" fill="{color}"/>'
    if kind == "cross":
        return (f'<path d="M{x - 5},{y - 5}L{x + 5},{y + 5}M{x - 5},{y + 5}L{x + 5},{y - 5}" '
                f'stroke="{color}" stroke-width="2.5"/>')
    return f'<circle cx="{x}" cy="{y}" r="5.5" fill="{color}"/>'


def svg_chart(points: list[dict], title: str, caption: str) -> str:
    """points: {name, group, size_mib, acc, lo, hi}；x 對數刻度。 / x on a log scale."""
    W, H, L, R, T, B = 760, 480, 70, 170, 50, 70
    pw, ph = W - L - R, H - T - B
    xs = [p["size_mib"] for p in points] or [100, 10000]
    lo_x, hi_x = math.log10(min(xs) * 0.8), math.log10(max(xs) * 1.25)
    if hi_x - lo_x < 0.5:
        hi_x = lo_x + 0.5
    X = lambda v: L + (math.log10(v) - lo_x) / (hi_x - lo_x) * pw  # noqa: E731
    Y = lambda a: T + (1 - a) * ph  # noqa: E731
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" font-family="sans-serif" font-size="12">',
         f'<rect width="{W}" height="{H}" fill="white"/>',
         f'<text x="{L}" y="28" font-size="16" font-weight="bold">{esc(title)}</text>']
    for t in range(0, 11, 2):
        y = Y(t / 10)
        o += [f'<line x1="{L}" y1="{y}" x2="{L + pw}" y2="{y}" stroke="#e5e5e5"/>',
              f'<text x="{L - 8}" y="{y + 4}" text-anchor="end">{t * 10}%</text>']
    for v in (100, 200, 500, 1000, 2000, 5000, 10000, 20000):
        if lo_x <= math.log10(v) <= hi_x:
            x = X(v)
            o += [f'<line x1="{x}" y1="{T}" x2="{x}" y2="{T + ph}" stroke="#f0f0f0"/>',
                  f'<text x="{x}" y="{T + ph + 18}" text-anchor="middle">{v if v < 1000 else f"{v // 1000}k"}</text>']
    o += [f'<rect x="{L}" y="{T}" width="{pw}" height="{ph}" fill="none" stroke="#888"/>',
          f'<text x="{L + pw / 2}" y="{H - 30}" text-anchor="middle">檔案大小 / File size (MiB, log)</text>',
          f'<text x="{L}" y="{H - 10}" fill="#555" font-size="11">{esc(caption)}</text>']
    scored = [p for p in points if p.get("acc") is not None]
    front = set(pareto_front([(p["name"], p["size_mib"], p["acc"]) for p in scored]))
    fp = sorted((p for p in scored if p["name"] in front), key=lambda p: p["size_mib"])
    if len(fp) > 1:
        o.append('<polyline fill="none" stroke="#333" stroke-dasharray="5,4" points="'
                 + " ".join(f"{X(p['size_mib']):.1f},{Y(p['acc']):.1f}" for p in fp) + '"/>')
    for p in scored:
        x, y, c = X(p["size_mib"]), Y(p["acc"]), COLORS[p["group"]]
        if p.get("lo") is not None:
            o.append(f'<line x1="{x:.1f}" y1="{Y(p["lo"]):.1f}" x2="{x:.1f}" y2="{Y(p["hi"]):.1f}" '
                     f'stroke="{c}" stroke-opacity="0.35" stroke-width="2"/>')
        o.append(_marker(MARKERS[p["group"]], round(x, 1), round(y, 1), c))
        o.append(f'<text x="{x + 8:.1f}" y="{y - 6:.1f}" font-size="10" fill="#333">{esc(p["name"])}</text>')
    for i, g in enumerate(GROUPS):
        y = T + 14 + i * 22
        o.append(_marker(MARKERS[g], L + pw + 24, y, COLORS[g]))
        o.append(f'<text x="{L + pw + 36}" y="{y + 4}">{g}</text>')
    o.append(f'<text x="{L + pw + 18}" y="{T + 14 + len(GROUPS) * 22 + 10}" font-size="11" fill="#555">'
             '--- 帕累托前緣 / Pareto front</text>')
    o.append("</svg>")
    return "\n".join(o)


# ── 取樣設定 / Sampled setting（design D6）──────────────────────────────────

def _norm_code(text: str) -> str:
    body = scoring.strip_thinking(text or "")
    m = re.search(r"```(?:python)?\n(.*?)```", body, re.S)
    body = m.group(1) if m else body
    lines = [ln.split("#", 1)[0].rstrip() for ln in body.splitlines()]
    return "\n".join(ln for ln in lines if ln.strip())


def sampled_metrics(run_dir: Path) -> dict:
    """pass@1（平均）、多數決、pass@8（需要標準答案，只當上限）。 / pass@1, majority vote, pass@8 (upper bound)."""
    results = latest_results(run_dir)
    verifs = latest_verifications(run_dir)
    by_item: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in results.values():
        if r["task"] in SAMPLE_TASKS:
            v = verifs.get((r["key"], r["task"]))
            by_item[(r["source"], r["id"])].append({**r, "v": v})
    out = {}
    for task in SAMPLE_TASKS:
        items = {k: v for k, v in by_item.items() if v and v[0]["task"] == task}
        p1, p8, maj, ties, n = [], [], [], 0, 0
        for samples in items.values():
            samples.sort(key=lambda r: r["sample"])
            scores = [(s["v"] or {}).get("score") for s in samples]
            if any(x is None for x in scores):
                continue
            n += 1
            p1.append(sum(scores) / len(scores))
            p8.append(1 if any(scores) else 0)
            if task == "tool":
                keys = [json.dumps(((s["v"].get("details") or {}).get("calls")), sort_keys=True, ensure_ascii=False)
                        if s["v"]["status"] != "unparsed" else None for s in samples]
            else:
                keys = [_norm_code(s.get("content") or "") or None for s in samples]
            votes = Counter(k for k in keys if k is not None)
            if not votes:
                maj.append(0)
                continue
            top = votes.most_common()
            if len(top) > 1 and top[0][1] == top[1][1]:
                ties += 1
            best = next(k for k in keys if k is not None and votes[k] == top[0][1])  # 平手取先出現者 / first wins
            maj.append(scores[keys.index(best)])
        out[task] = {"items": n, "pass@1": round(sum(p1) / n, 4) if n else None,
                     "majority": round(sum(maj) / n, 4) if n else None,
                     "pass@8": round(sum(p8) / n, 4) if n else None, "ties": ties}
    return out


# ── 報表 / Report（design D7）───────────────────────────────────────────────

def build_report(root: Path, rows: list[Row], state: dict) -> dict:
    runs = root / "var" / "eval" / "runs"
    out_rows, missing = [], []
    for r in rows:
        st = state["rows"].get(r.name, {"state": "pending"})
        rd = runs / r.run_id
        m = row_metrics(rd) if (rd / "conditions.json").exists() and (rd / "results.jsonl").exists() else None
        if st["state"] in EXCLUDED or m is None or m["completeness"] != "complete" or m["reasoning"]["pending"]:
            missing.append({"row": r.name, "state": st["state"], "reason": st.get("reason")})
        out_rows.append({"row": r.name, "group": r.group, "base": r.base, "quant": r.quant,
                         "size_mib": round(r.size_mib), "placement_check": r.placement_check,
                         "state": st["state"], "placement": st.get("placement"), "metrics": m})
    sampled = {}
    for name, st in state["rows"].items():
        if st.get("sampled_run") and (runs / st["sampled_run"] / "results.jsonl").exists():
            sampled[name] = sampled_metrics(runs / st["sampled_run"])
    return {"matrix_hash": state["matrix_hash"], "built": now(), "rows": out_rows, "missing": missing,
            "complete": not missing, "sampled": sampled}


def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def _ci(ci):
    return "—" if not ci else f"{ci[0] * 100:.0f}–{ci[1] * 100:.0f}%"


def write_report(root: Path, rows: list[Row], state: dict) -> dict:
    rep = build_report(root, rows, state)
    d = state_dir(root, state["matrix_hash"])
    d.mkdir(parents=True, exist_ok=True)
    plotted = [r for r in rep["rows"] if r["metrics"] and not r["placement_check"]
               and r["row"] not in {m["row"] for m in rep["missing"]}]
    judge_all = all(r["metrics"]["knowledge"]["simpleqa"] == "judge" for r in plotted) if plotted else False
    for key, title, cap in (
            ("knowledge", "E0：知識題 / Knowledge (C-Eval + CMMLU + Chinese SimpleQA)",
             "SimpleQA：" + ("官方評審 / official judge" if judge_all else "部分或全部為近似比對 / approximate matching (some or all)")),
            ("reasoning", "E0：推理與工具題 / Reasoning & tools (HumanEval+ / MBPP+ + ACEBench)",
             "程式 plus 測試 + ACEBench normal 規則 / code plus tests + ACEBench normal rules")):
        pts = [{"name": r["row"], "group": r["group"], "size_mib": r["size_mib"],
                "acc": r["metrics"][key]["acc"],
                "lo": (r["metrics"][key]["ci95"] or (None, None))[0],
                "hi": (r["metrics"][key]["ci95"] or (None, None))[1]} for r in plotted]
        (d / f"pareto-{key}.svg").write_text(svg_chart(pts, title, cap), encoding="utf-8")
        rep[f"front_{key}"] = pareto_front([(p["name"], p["size_mib"], p["acc"]) for p in pts if p["acc"] is not None])
    (d / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (d / "report.md").write_text(to_markdown(rep), encoding="utf-8")
    return rep


def to_markdown(rep: dict) -> str:
    L = [f"# E0 報表 / E0 report（矩陣 / matrix `{rep['matrix_hash']}`）", "",
         f"- 產生時間 / Built: {rep['built']}",
         f"- 完整度 / Completeness: {'complete' if rep['complete'] else 'incomplete'}",
         "- 圖 / Charts: `pareto-knowledge.svg`、`pareto-reasoning.svg`（同目錄 / same directory）",
         f"- 帕累托前緣 / Pareto front — 知識 / knowledge: {', '.join(rep.get('front_knowledge') or []) or '—'}；"
         f"推理 / reasoning: {', '.join(rep.get('front_reasoning') or []) or '—'}", "",
         "## 全部模型 / All models", "",
         "| 列 / Row | 組 / Group | 量化 / Quant | MiB | 擺放 / Placement | 知識 / Knowledge (95% CI) | "
         "推理 / Reasoning (95% CI) | 摘要忠實 / Faithful | t/s | 延遲 / Latency s | RAM MiB | VRAM MiB |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        m = r["metrics"]
        if not m:
            L.append(f"| {r['row']} | {r['group']} | {r['quant']} | {r['size_mib']} | — | {r['state']} | | | | | | |")
            continue
        k, q = m["knowledge"], m["reasoning"]
        pl = "GPU" if (m["ngl"] or 0) > 0 else "CPU"
        flag = "（擺放對照 / placement check）" if r["placement_check"] else ""
        L.append(f"| {r['row']}{flag} | {r['group']} | {r['quant']} | {r['size_mib']} | {pl} | "
                 f"{_pct(k['acc'])} ({_ci(k['ci95'])}; SimpleQA {k['simpleqa']}) | "
                 f"{_pct(q['acc'])} ({_ci(q['ci95'])}{'; pending ' + str(q['pending']) if q['pending'] else ''}) | "
                 f"{'—' if m['summary_faithfulness'] is None else m['summary_faithfulness']} | {m['tps'] or '—'} | "
                 f"{m['latency_s'] or '—'} | {m['peak_ram_mib'] or '—'} | {m['peak_vram_mib'] or '—'} |")
    by_base = defaultdict(list)
    for r in rep["rows"]:
        if r["metrics"] and not r["placement_check"]:
            by_base[r["base"]].append(r)
    L += ["", "## 同基底對照 / Same-base comparison", "",
          "| 基底 / Base | 量化 / Quant | MiB | 知識 / Knowledge | 推理 / Reasoning |", "|---|---|---|---|---|"]
    for base, rs in sorted(by_base.items()):
        if len(rs) < 2:
            continue
        for r in sorted(rs, key=lambda r: -r["size_mib"]):
            L.append(f"| {base} | {r['quant']} | {r['size_mib']} | {_pct(r['metrics']['knowledge']['acc'])} | "
                     f"{_pct(r['metrics']['reasoning']['acc'])} |")
    if rep["sampled"]:
        L += ["", "## 取樣設定 / Sampled setting（N=8, T=0.7）", "",
              "pass@8 需要標準答案，只能當上限參考；程式題的多數決以正規化後的程式文字比對，是較弱的近似。",
              "pass@8 needs the ground truth and is an upper bound only; code majority vote matches normalized "
              "program text, a weaker approximation.", "",
              "| 列 / Row | 題型 / Task | 題數 / Items | pass@1 | 多數決 / Majority | pass@8（上限 / bound） | 平手 / Ties |",
              "|---|---|---|---|---|---|---|"]
        for name, s in rep["sampled"].items():
            for task, x in s.items():
                L.append(f"| {name} | {task} | {x['items']} | {_pct(x['pass@1'])} | {_pct(x['majority'])} | "
                         f"{_pct(x['pass@8'])} | {x['ties']} |")
    if rep["missing"]:
        L += ["", "## 未完成或排除 / Incomplete or excluded", "", "| 列 / Row | 狀態 / State | 原因 / Reason |",
              "|---|---|---|"]
        L += [f"| {m['row']} | {m['state']} | {m['reason'] or '—'} |" for m in rep["missing"]]
    L += ["", "## 說明 / Notes", "",
          "- 每個模型只跑一次；50 題時約 ±7 分的差距不具統計意義，請看 95% 信賴區間（Wilson）。",
          "  One run per model; with 50 items, gaps of about ±7 points are not significant; see the 95% Wilson intervals.",
          "- 推理分數只含程式（plus 測試）與工具呼叫；摘要另列忠實度。",
          "  Reasoning covers code (plus tests) and tool calls only; summaries are listed as faithfulness.", ""]
    return "\n".join(L)


# ── 夜間流程 / Night pipeline（design D5）──────────────────────────────────

@dataclass
class Hooks:
    """呼叫外部的接點，測試時可替換。 / Points that call outside, replaceable in tests."""
    fresh_facts: Callable[[], dict]
    models_dir: Path
    in_window: Callable[[], bool]
    run: Callable[..., int]          # (row, ngl, resume, samples, temperature, sources, run_id=None) -> rc
    verify: Callable[..., int]       # (run_id, only) -> rc
    smoke: Callable[..., dict]       # (row, model_path, ngl) -> judge_smoke result
    download: Callable = _download
    log: Callable[[str], None] = print
    extra: dict = field(default_factory=dict)


def run_rows(rows: list[Row], state: dict, h: Hooks, save: Callable[[], None], defer_verify: bool = False) -> str:
    """逐列：下載 → 擺放 → 冒煙 → 評測 → 驗證。回傳 complete | paused_window | stopped。
    defer_verify：生成完就換下一列，驗證交給另一個行程（`e0 verify`），GPU 不必等評審（2026-11-16）。
    Per row: download → placement → smoke → run → verify. Return complete | paused_window | stopped.
    defer_verify: move on after generation and leave verification to a separate `e0 verify` process."""
    for r in rows:
        st = row_state(state, r.name)
        if st["state"] in DONE_STATES + EXCLUDED:
            continue
        if not h.in_window():
            h.log("night window ended; stopping before the next row")
            return "paused_window"
        h.log(f"== {r.name} ({st['state']})")
        if r.reference_run:
            if defer_verify:
                continue
            rc = h.verify(r.run_id, None)
            st.update(state="verified" if rc == 0 else "run_complete", placement="reference")
            save()
            if rc != 0 and not h.in_window():
                return "paused_window"
            continue
        try:
            path = ensure_model(r, h.models_dir, h.download, h.log)
        except (EvalError, OSError) as exc:
            st.update(reason=f"download failed: {exc}")
            save()
            h.log(f"  download failed: {exc}; next row")
            continue
        if st["state"] == "pending":
            st["state"] = "downloaded"
            save()
        budgets = (h.fresh_facts().get("budgets") or {})
        p = place(r, budgets)
        if p.get("excluded"):
            st.update(state=p["excluded"], reason=p["reason"], budget=p)
            save()
            continue
        if st.get("ngl") is not None and st["ngl"] != p["ngl"] and st["state"] in ("smoke_ok", "running"):
            # 已開始的執行不能換擺放續跑（R17）；今晚先跳過 / a started run cannot resume with another placement
            h.log(f"  placement now {p['placement']} but the run started with ngl={st['ngl']}; skipping tonight")
            continue
        st.update(placement=p["placement"], ngl=p["ngl"], placement_note=p["reason"], budget=p)
        if st["state"] == "downloaded":
            res = h.smoke(r, path, p["ngl"])
            st["smoke"] = res
            if not res["ok"]:
                st.update(state="excluded_smoke", reason="; ".join(res["reasons"]))
                save()
                continue
            st["state"] = "smoke_ok"
            save()
        if st["state"] in ("smoke_ok", "running"):
            resume = st["state"] == "running"
            st["state"] = "running"
            save()
            rc = h.run(r, p["ngl"], resume, 1, 0.0, None)
            if rc != 0:
                save()
                return "paused_window" if not h.in_window() else "stopped"
            st["state"] = "run_complete"
            save()
        if st["state"] == "run_complete" and defer_verify:
            continue
        if st["state"] == "run_complete":
            rc = h.verify(r.run_id, None)
            if rc != 0:
                if not h.in_window():
                    return "paused_window"
                # 評審暫時中斷等：先跑下一列，驗證留到下次 / e.g. a judge outage: go on, verify next time
                h.log(f"  verify did not finish (exit {rc}); continuing with the next row")
                continue
            st["state"] = "verified"
            save()
    return "complete"


def verify_generated(root: Path, rows: list[Row], h: Hooks, state: dict | None = None) -> dict:
    """驗證已經生成完的列；只讀 state.json（略過已排除的列），不寫（生成行程會寫）。
    Verify generated rows; state.json is read (excluded rows are skipped) but never written."""
    done, todo = [], []
    for r in rows:
        if (state or {}).get("rows", {}).get(r.name, {}).get("state") in EXCLUDED:
            continue
        rs = root / "var" / "eval" / "runs" / r.run_id / "run_state.json"
        try:
            complete = json.loads(rs.read_text(encoding="utf-8")).get("state") == "complete"
        except (OSError, ValueError):
            complete = False
        if not complete:
            todo.append(r.name)
            continue
        rc = h.verify(r.run_id, None)
        (done if rc == 0 else todo).append(r.name)
    return {"verified": done, "not_ready": todo}


def top_rows(root: Path, rows: list[Row], state: dict, n: int = SAMPLE_TOP) -> list[Row]:
    """貪婪解碼推理分數前 n 名（已驗證、非擺放對照）。 / Top n by greedy reasoning score."""
    scored = []
    for r in rows:
        if r.placement_check or state["rows"].get(r.name, {}).get("state") != "verified":
            continue
        m = row_metrics(root / "var" / "eval" / "runs" / r.run_id)
        if m["reasoning"]["acc"] is not None and not m["reasoning"]["pending"]:
            scored.append((m["reasoning"]["acc"], -r.size, r))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [t[2] for t in scored[:n]]


def run_sampling(root: Path, rows: list[Row], state: dict, h: Hooks, sources: list[str],
                 save: Callable[[], None]) -> str:
    pending = [r for r in rows if not r.placement_check and not r.reference_run
               and state["rows"].get(r.name, {}).get("state") not in DONE_STATES + EXCLUDED]
    if pending:
        raise EvalError(f"greedy runs are not finished: {', '.join(r.name for r in pending)}")
    for r in top_rows(root, rows, state):
        st = row_state(state, r.name)
        if st.get("sampled_state") == "verified":
            continue
        if not h.in_window():
            return "paused_window"
        st["sampled_run"] = f"e0s-{r.name}"
        resume = st.get("sampled_state") == "running"
        st["sampled_state"] = "running"
        save()
        path = ensure_model(r, h.models_dir, h.download, h.log)  # noqa: F841 - 確認仍在 / still present
        rc = h.run(r, st["ngl"], resume, SAMPLE_N, SAMPLE_T, sources, run_id=st["sampled_run"])
        if rc != 0:
            return "paused_window" if not h.in_window() else "stopped"
        rc = h.verify(st["sampled_run"], ["code", "tool"])
        if rc != 0:
            return "paused_window" if not h.in_window() else "stopped"
        st["sampled_state"] = "verified"
        save()
    return "complete"


"""代理程式請求重放評測（add-long-context 3.1）：把某天 Hermes 等代理程式的請求原樣交給本機重答，只看回答、不執行工具，
和當時雲端的回答比對。量：工具呼叫合法率、和雲端選同一個工具的比例、秒數、本機有沒有接下（沒有被 413 擋掉）。
請求內容是使用者的私人資料：只存在 var/（不進 git），報告只寫統計與工具名稱。
Replay one day's agent-client requests (Hermes and the like) on the local model without running any tool, and compare
with the cloud answers given at the time: valid tool calls, same tool as the cloud, seconds, and whether the local
engine took the request at all. Requests are private: they stay in var/ and the report holds only counts and tool names.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

DIR = "var/eval/agent-replay"
SET = f"{DIR}/set.jsonl"
CLIENTS = ("Hermes",)          # 系統提示開頭含這些字的請求 / requests whose system prompt names these clients


def _text(c) -> str:
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return c if isinstance(c, str) else ""


def _names(msg: dict | None) -> list[str]:
    return [(c.get("function") or {}).get("name") for c in (msg or {}).get("tool_calls") or []]


def _cloud_answer(rec: dict) -> dict | None:
    for t in reversed(rec.get("tiers") or []):
        if t.get("provider") in ("cloud", "claude") and isinstance(t.get("answer"), dict):
            return t["answer"]
    return None


BUDGET = 30000 - 1024           # 代理預算減回答保留 / the agent budget minus the answer reserve


def _even(xs: list, n: int) -> list:
    if len(xs) <= n:
        return xs
    step = len(xs) / n
    return [xs[int(i * step)] for i in range(n)]


def select(records: list[dict], limit: int = 100) -> list[dict]:
    """挑出帶工具、來自代理程式、當時由雲端回答的請求。放得進代理預算的優先全收（fits=True，OQ1 看這組），
    其餘平均抽樣補到 limit 筆（fits=False：Hermes 改 context_length 前累積的超長對話，本機會裁掉舊對話）。
    Tool-bearing agent requests the cloud answered. Those within the agent budget come first (fits=True, judged by
    OQ1); over-budget ones fill up to `limit` (fits=False, trimmed locally)."""
    from ..runtime.context import total
    picked, seen = [], set()
    for r in records:
        req = r.get("request") or {}
        msgs, tools = req.get("messages") or [], req.get("tools") or []
        if not msgs or not tools or r.get("eval"):
            continue
        head = _text(msgs[0].get("content"))[:300]
        if not any(c in head for c in CLIENTS):
            continue
        ans = _cloud_answer(r)
        if ans is None:
            continue
        key = json.dumps(msgs[-3:], ensure_ascii=False, sort_keys=True)[-2000:]
        if key in seen:
            continue
        seen.add(key)
        picked.append({"id": r["id"], "messages": msgs, "tools": tools, "fits": total(msgs, tools) <= BUDGET,
                       "cloud_tools": _names(ans), "cloud_text": bool(_text(ans.get("content")).strip())})
    fits = _even([i for i in picked if i["fits"]], limit)
    return fits + _even([i for i in picked if not i["fits"]], limit - len(fits))


def prepare(root: Path, days: list[str], limit: int = 100) -> int:
    records = []
    for day in days:
        src = root / "var" / "trajectories" / f"{day}.jsonl"
        if src.is_file():
            records += [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    items = select(records, limit)
    (root / DIR).mkdir(parents=True, exist_ok=True)
    (root / SET).write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    print(f"{len(items)} requests ({sum(i['fits'] for i in items)} within the agent budget) from {days} → {SET}")
    return 0


def judge(item: dict, row: dict) -> dict:
    """單筆結果：本機有沒有接、工具呼叫合不合法、和雲端是否選同一個工具。
    One row: taken locally, valid tool call, and the same first tool as the cloud."""
    offered = {(t.get("function") or t).get("name") for t in item["tools"]}
    meta = row.get("jiezi") or {}
    names = row.get("tools") or []
    local = row.get("status") == 200 and not meta.get("escalation") and meta.get("tier") in (0, 1, 2, "think")
    if names:
        valid = all(n in offered for n in names) and meta.get("verification") in ("pass", None, "not_applicable")
    else:
        valid = bool(row.get("text"))
    cloud = item.get("cloud_tools") or []
    same = (names[:1] == cloud[:1]) if (names or cloud) else True
    return {"local": local, "valid": local and valid, "same": local and same}


def summary(items: dict[str, dict], rows: list[dict]) -> dict:
    js = [judge(items[r["id"]], r) for r in rows if r["id"] in items]
    secs = [r["seconds"] for r, j in zip(rows, js) if j["local"] and r.get("seconds") is not None]
    n = len(js) or 1
    return {"requests": len(js), "local": sum(j["local"] for j in js), "valid": round(sum(j["valid"] for j in js) / n, 3),
            "same_tool": round(sum(j["same"] for j in js) / n, 3),
            "median_s": round(statistics.median(secs), 1) if secs else None,
            "p90_s": round(sorted(secs)[int(len(secs) * 0.9) - 1], 1) if len(secs) >= 10 else None,
            "errors": sum(1 for r in rows if r.get("error"))}


def run(root: Path, url: str, key: str, label: str, log=print) -> Path:
    """逐筆重放（jiezi-local：不轉交雲端），可接續。 / Replay one by one on jiezi-local; resumable."""
    import httpx
    items = [json.loads(x) for x in (root / SET).read_text(encoding="utf-8").splitlines() if x.strip()]
    out = root / DIR / f"run-{label}.jsonl"
    done = {json.loads(x)["id"] for x in out.read_text(encoding="utf-8").splitlines() if x.strip()} \
        if out.is_file() else set()
    headers = {"Authorization": f"Bearer {key}", "x-jiezi-eval": "1"}
    with httpx.Client(timeout=900) as c, out.open("a", encoding="utf-8") as f:
        for it in items:
            if it["id"] in done:
                continue
            t0, row = time.monotonic(), {"id": it["id"], "label": label}
            try:
                r = c.post(url + "/v1/chat/completions", headers=headers, json={
                    "model": "jiezi-local", "messages": it["messages"], "tools": it["tools"], "stream": False})
                row["status"] = r.status_code
                data = r.json()
                if r.status_code == 200:
                    msg = data["choices"][0]["message"]
                    row["tools"], row["text"] = _names(msg), bool(_text(msg.get("content")).strip())
                    meta = data.get("jiezi") or {}
                    row["jiezi"] = {k: meta.get(k) for k in ("tier", "escalation", "verification")}
                else:
                    row["error"] = ((data.get("error") or {}).get("code") or str(r.status_code))
                row["seconds"] = round(time.monotonic() - t0, 1)
            except Exception as exc:  # noqa: BLE001 - 一筆失敗記下來繼續 / record and go on
                row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            j = judge(it, row)
            log(f"{it['id']} {row.get('seconds')}s local={j['local']} valid={j['valid']} same={j['same']} "
                f"{row.get('tools')} vs cloud {it['cloud_tools']} {row.get('error') or ''}")
    return out


def report(root: Path, labels: list[str]) -> str:
    items = {i["id"]: i for i in (json.loads(x) for x in (root / SET).read_text(encoding="utf-8").splitlines()
                                  if x.strip())}
    lines = ["# 代理程式請求重放 / Agent request replay", "",
             f"- 請求：{len(items)} 筆代理程式（Hermes）帶工具的請求，當時由雲端回答；本機用 jiezi-local 重答，不執行工具",
             "- 合法＝本機接下且工具名稱都在清單、參數符合 schema（或沒有工具呼叫時有文字回答）；同工具＝第一個工具和雲端相同",
             "- 門檻（OQ1）：看「放得進預算」那組：合法 ≥ 0.85、同工具 ≥ 0.60、中位秒數 ≤ 20", "",
             "| 條件 | 筆數 | 本機接下 | 合法率 | 同工具 | 中位秒數 | P90 秒數 | 錯誤 |", "|---|---|---|---|---|---|---|---|"]
    res = {}
    for lab in labels:
        p = root / DIR / f"run-{lab}.jsonl"
        if not p.is_file():
            continue
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        for group, keep in (("fits", True), ("over", False)):
            sub = [r for r in rows if r["id"] in items and bool(items[r["id"]].get("fits")) == keep]
            if not sub:
                continue
            s = res[f"{lab}/{group}"] = summary(items, sub)
            s["passes"] = bool(s["valid"] >= 0.85 and s["same_tool"] >= 0.60 and (s["median_s"] or 999) <= 20)
            lines.append(f"| {lab}（{'放得進預算' if keep else '超過預算、裁舊對話'}） | {s['requests']} | {s['local']} | "
                         f"{s['valid']} | {s['same_tool']} | {s['median_s']} | {s['p90_s']} | {s['errors']} |")
    vram = root / DIR / "vram.log"
    if vram.is_file():
        vals = [int(x) for x in vram.read_text().split() if x.isdigit()]
        if vals:
            lines += ["", f"- VRAM 峰值：{max(vals)} MiB（取樣 {len(vals)} 次）"]
    out = root / DIR / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from ..config import load_env, port_base
    ap = argparse.ArgumentParser(prog="python -m jiezi.eval.agent_replay")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("days", nargs="+")
    p.add_argument("-n", type=int, default=100)
    r = sub.add_parser("run")
    r.add_argument("label")
    rp = sub.add_parser("report")
    rp.add_argument("labels", nargs="+")
    a = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    if a.cmd == "prepare":
        return prepare(root, a.days, a.n)
    if a.cmd == "run":
        env = load_env(root)
        print(run(root, f"http://127.0.0.1:{port_base(env)}", env.get("JIEZI_GATEWAY_KEY") or "", a.label))
        return 0
    print(report(root, a.labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

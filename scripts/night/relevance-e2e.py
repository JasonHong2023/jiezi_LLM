"""tune-knowledge-relevance 2.4：知識庫門檻新舊比較（真實問題，jiezi-local，不請教 Claude）。
Usage: relevance-e2e.py <threshold> <out.json>；由 relevance-e2e.sh 在夜間呼叫。
量：第一次作答就通過（沒有說不確定、查核沒失敗）的比例、最後通過的比例、平均秒數。這兩者在 jiezi 策略下分別對應
「不用轉交」與「階梯救回來」。/ First-answer pass rate (no escalation needed), final pass rate, seconds."""
import json, sys, time, httpx
sys.path.insert(0, "src")
from jiezi import rag
T, OUT = sys.argv[1:3]
KEY = next(l.split("=", 1)[1].strip() for l in open(".env") if l.startswith("JIEZI_GATEWAY_KEY="))
rows = [json.loads(x) for x in rag.RELEVANCE_SET.read_text(encoding="utf-8").splitlines() if x.strip()]
rows = [r for r in rows if r["kind"] == "real" and not r.get("unsure")]
out = []
with httpx.Client(timeout=600) as c:
    for r in rows:
        t0 = time.monotonic()
        try:
            j = c.post("http://127.0.0.1:36100/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}", "x-jiezi-eval": "1"},
                       json={"model": "jiezi-local", "messages": [{"role": "user", "content": r["q"]}]}).json()["jiezi"]
            proc = j.get("process") or []
            answers = [p for p in proc if p.get("kind") == "answer"]
            first_ok = bool(answers) and not answers[0].get("check", "").startswith("沒通過") \
                and answers[0].get("check") not in ("本機說不確定", "回答被截斷", "沒有回答")
            out.append({"q": r["q"], "expect": r["expect"], "first_ok": first_ok, "final_ok": j.get("escalation") is None,
                        "steps": len(answers), "sources": [s.get("article") or s.get("source") for s in j.get("sources") or []],
                        "seconds": round(time.monotonic() - t0, 1)})
        except Exception as exc:  # noqa: BLE001
            out.append({"q": r["q"], "error": f"{type(exc).__name__}: {exc}"})
ok = [x for x in out if "error" not in x]
summary = {"threshold": float(T), "n": len(out), "errors": len(out) - len(ok),
           "first_ok": sum(x["first_ok"] for x in ok), "final_ok": sum(x["final_ok"] for x in ok),
           "avg_s": round(sum(x["seconds"] for x in ok) / max(1, len(ok)), 1)}
json.dump({"summary": summary, "rows": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"t={T} first_ok {summary['first_ok']}/{len(ok)} final_ok {summary['final_ok']}/{len(ok)} avg {summary['avg_s']}s "
      f"errors {summary['errors']}")

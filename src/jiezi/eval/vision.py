"""看圖評測（add-vision-tools 1.2、3.1）：Open Images V7 驗證集子集，量「說出的物體」的精確率與召回率。
Vision evaluation: precision and recall of the objects an answer names, on an Open Images V7 validation subset.

- 圖片：只取授權欄位為 CC BY 2.0 的驗證集圖片（docs/licenses.md `eval-openimages-v7`），檔案只放 var/，不散布；
  每張記作者與原始網址。Images: CC BY 2.0 only, kept under var/ with author and source URL.
- 標註：人工驗證的影像層級標籤（boxable 600 類）。Confidence 1 是「有」，0 是「確認沒有」。
- 計分：回答由核心抽出物體英文名（與看圖核對同一個提示），對到類別名稱：
  有 → 對；確認沒有 → 錯；類別存在但這張圖沒驗證 → 無法判定；對不到任何類別 → 對不到。
  精確率 = 對 /（對＋錯）；召回率 = 說到的「有」類別 / 全部「有」類別。比的是工具開關前後的差，不是絕對值。
Scoring: names are matched to classes; verified positives are correct, verified negatives wrong, others unknown.
Compare tools on and off; the absolute numbers matter less."""

from __future__ import annotations

import base64
import csv
import io
import json
import random
import re
import time
from pathlib import Path

QUESTION = "這張圖裡有哪些東西？請列出你看得到的物體。"
SEED = 20261125
META = "var/eval/vision/meta"
SET = "var/eval/vision/set.jsonl"
IMAGES = "var/eval/vision/images"
MIN_POS, MAX_POS = 3, 15
S3 = "https://open-images-dataset.s3.amazonaws.com/validation/{}.jpg"
MAX_SIDE = 1024
# 常見說法 → 類別（小寫）；人類相關的說「person」時，Man／Woman／Boy／Girl 任一有就算對
# Common names → classes; "person" counts when any of the person classes is positive
ALIASES = {
    "person": {"person", "man", "woman", "boy", "girl"}, "people": {"person", "man", "woman", "boy", "girl"},
    "human": {"person", "man", "woman", "boy", "girl"}, "child": {"boy", "girl"}, "kid": {"boy", "girl"},
    "men": {"man"}, "women": {"woman"}, "children": {"boy", "girl"},
    "automobile": {"car"}, "vehicle": {"land vehicle", "vehicle", "car"}, "plant": {"plant", "houseplant", "tree", "flower"},
    "shirt": {"shirt", "clothing"}, "clothes": {"clothing"}, "jeans": {"jeans", "trousers"},
    "pants": {"trousers"}, "bike": {"bicycle"}, "sky": set(), "grass": {"plant"},
    "puppy": {"dog"}, "kitten": {"cat"}, "cup": {"coffee cup", "mug"}, "phone": {"mobile phone", "telephone"},
    "cellphone": {"mobile phone"}, "smartphone": {"mobile phone"}, "sign": {"traffic sign", "billboard"},
    "glasses": {"glasses", "sunglasses"}, "hat": {"hat", "fedora", "cowboy hat", "sun hat", "sombrero"},
    "face": {"human face"}, "hair": {"human hair"}, "hand": {"human hand"}, "eye": {"human eye"},
    "building": {"building", "house", "skyscraper", "tower", "office building"},
}


def _norm(name: str) -> str:
    n = re.sub(r"[^a-z0-9 \-]", "", (name or "").lower()).strip()
    n = re.sub(r"\s+", " ", n)
    return n


def _singular(n: str) -> str:
    for suf, rep in (("ies", "y"), ("ves", "f"), ("ches", "ch"), ("shes", "sh"), ("ses", "s"), ("s", "")):
        if n.endswith(suf) and len(n) > len(suf) + 2:
            return n[: -len(suf)] + rep
    return n


def classes_for(name: str, known: set[str]) -> set[str]:
    """回答說的英文名 → 可能的類別名稱（小寫）。 / Class names (lower case) a claimed name may refer to."""
    n = _norm(name)
    if not n:
        return set()
    for cand in (n, _singular(n)):
        if cand in ALIASES:
            return {c for c in ALIASES[cand] if c in known}
        if cand in known:
            return {cand}
    last = _singular(n.split(" ")[-1])              # 「red car」→ car / the head noun
    if last in ALIASES:
        return {c for c in ALIASES[last] if c in known}
    return {last} if last in known else set()


def score_one(claims: list[str], pos: set[str], neg: set[str], known: set[str]) -> dict:
    """一張圖：claims 是回答說的英文名；pos／neg 是這張圖驗證過有／沒有的類別（小寫）。"""
    out = {"correct": 0, "wrong": 0, "unknown": 0, "unmatched": 0, "named_pos": set(), "wrong_names": []}
    for c in dict.fromkeys(_norm(x) for x in claims if _norm(x)):
        cls = classes_for(c, known)
        if not cls:
            out["unmatched"] += 1
        elif cls & pos:
            out["correct"] += 1
            out["named_pos"] |= cls & pos
        elif cls <= neg:
            out["wrong"] += 1
            out["wrong_names"].append(c)
        else:
            out["unknown"] += 1
    out["named_pos"] = sorted(out["named_pos"])
    return out


def summary(rows: list[dict], items: dict[str, dict], known: set[str]) -> dict:
    tot = {"images": 0, "correct": 0, "wrong": 0, "unknown": 0, "unmatched": 0, "pos": 0, "named_pos": 0,
           "seconds": [], "errors": 0}
    for r in rows:
        it = items.get(r["id"])
        if it is None:
            continue
        if r.get("error"):
            tot["errors"] += 1
            continue
        s = score_one(r.get("objects") or [], set(it["positives"]), set(it["negatives"]), known)
        tot["images"] += 1
        for k in ("correct", "wrong", "unknown", "unmatched"):
            tot[k] += s[k]
        tot["pos"] += len(it["positives"])
        tot["named_pos"] += len(s["named_pos"])
        tot["seconds"].append(r.get("seconds") or 0)
    judged = tot["correct"] + tot["wrong"]
    secs = sorted(tot.pop("seconds"))
    tot["precision"] = round(tot["correct"] / judged, 4) if judged else None
    tot["recall"] = round(tot["named_pos"] / tot["pos"], 4) if tot["pos"] else None
    tot["median_s"] = secs[len(secs) // 2] if secs else None
    return tot


# ── 準備資料 / Prepare the subset ──
def _labels(root: Path) -> tuple[dict[str, str], set[str]]:
    names = {}
    with open(root / META / "oidv7-class-descriptions-boxable.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            names[row["LabelName"]] = row["DisplayName"].lower()
    return names, set(names.values())


def prepare(root: Path, n: int = 100, log=print) -> int:
    """抽 n 張（多抽一些以防下載失敗）、下載並縮到最長邊 1024px、寫 set.jsonl。 / Sample, download and write the set."""
    import httpx
    names, _ = _labels(root)
    pos: dict[str, set] = {}
    neg: dict[str, set] = {}
    with open(root / META / "validation-annotations-human-imagelabels-boxable.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = names.get(row["LabelName"])
            if name is None:
                continue
            (pos if row["Confidence"] == "1" else neg).setdefault(row["ImageID"], set()).add(name)
    meta = {}
    with open(root / META / "validation-images-with-rotation.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["License"].rstrip("/").endswith("licenses/by/2.0") and row.get("Rotation") in ("", "0.0", "0"):
                meta[row["ImageID"]] = row
    pool = sorted(i for i in meta if MIN_POS <= len(pos.get(i, ())) <= MAX_POS and neg.get(i))
    random.Random(SEED).shuffle(pool)
    out_dir = root / IMAGES
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        for i in pool:
            if len(rows) >= n:
                break
            m, path = meta[i], out_dir / f"{i}.jpg"
            if not path.is_file():
                # 官方下載來源（CVDF 的 S3）；Flickr 縮圖網址會回 429 / the official CVDF S3 mirror (Flickr rate-limits)
                try:
                    r = c.get(S3.format(i))
                    if r.status_code != 200 or len(r.content) < 5000:
                        continue
                    from PIL import Image
                    img = Image.open(io.BytesIO(r.content)).convert("RGB")
                    img.thumbnail((MAX_SIDE, MAX_SIDE))
                    img.save(path, "JPEG", quality=90)
                except (httpx.HTTPError, OSError):
                    continue
            rows.append({"id": i, "file": str(path.relative_to(root)), "positives": sorted(pos[i]),
                         "negatives": sorted(neg[i] - pos[i]), "author": m["Author"],
                         "source": m["OriginalLandingURL"], "license": m["License"]})
    (root / SET).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    log(f"{len(rows)} images in {SET}")
    return 0 if len(rows) >= n else 1


# ── 執行 / Run against the gateway ──
def _extract(c, url: str, headers: dict, answer: str) -> list[str]:
    from ..vision_tools import EXTRACT_PROMPT, EXTRACT_SCHEMA
    r = c.post(url + "/v1/chat/completions", headers=headers, json={
        "model": "jiezi-local", "temperature": 0, "max_tokens": 1600,
        "messages": [{"role": "user", "content": EXTRACT_PROMPT.format(answer=answer[:4000])}],
        "response_format": {"type": "json_schema", "json_schema": {"schema": EXTRACT_SCHEMA}}})
    r.raise_for_status()
    content = (r.json()["choices"][0]["message"].get("content") or "{}")
    objs = json.loads(content).get("objects") or []
    return [o["en"] for o in objs if isinstance(o, dict) and o.get("en")]


def run(root: Path, url: str, key: str, label: str, limit: int | None = None, log=print) -> Path:
    """每張圖問一次、抽出物體，可接續（已有的不重問）。 / One question per image; resumable."""
    import httpx
    items = [json.loads(x) for x in (root / SET).read_text(encoding="utf-8").splitlines() if x.strip()]
    out = root / "var" / "eval" / "vision" / f"run-{label}.jsonl"
    done = {json.loads(x)["id"] for x in out.read_text(encoding="utf-8").splitlines() if x.strip()} \
        if out.is_file() else set()
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=600) as c, out.open("a", encoding="utf-8") as f:
        for it in items[:limit]:
            if it["id"] in done:
                continue
            data = base64.b64encode((root / it["file"]).read_bytes()).decode()
            t0 = time.monotonic()
            row = {"id": it["id"], "label": label}
            try:
                r = c.post(url + "/v1/chat/completions", headers=headers, json={
                    "model": "jiezi-local", "messages": [{"role": "user", "content": [
                        {"type": "text", "text": QUESTION},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]}]})
                r.raise_for_status()
                j = r.json()
                row["answer"] = j["choices"][0]["message"].get("content") or ""
                row["seconds"] = round(time.monotonic() - t0, 1)
                row["vision_check"] = (j.get("jiezi") or {}).get("vision_check")
                row["objects"] = _extract(c, url, headers, row["answer"])
            except Exception as exc:  # noqa: BLE001 - 一張失敗記下來繼續 / record and go on
                row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            log(f"{it['id']} {row.get('seconds')}s {len(row.get('objects') or [])} objects {row.get('error') or ''}")
    return out


def report(root: Path, labels: list[str]) -> str:
    items = {r["id"]: r for r in (json.loads(x) for x in (root / SET).read_text(encoding="utf-8").splitlines()
                                  if x.strip())}
    _, known = _labels(root)
    lines = ["# 看圖評測 / Vision evaluation", "",
             f"- 圖片：Open Images V7 驗證集 CC BY 2.0 子集 {len(items)} 張（種子 {SEED}）；問題「{QUESTION}」",
             "- 精確率＝說對／（說對＋說了確認沒有的）；召回率＝說到的已驗證物體／全部已驗證物體",
             "", "| 條件 | 張數 | 精確率 | 召回率 | 說對 | 說錯 | 無法判定 | 對不到類別 | 中位秒數 | 錯誤 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    res = {}
    for lab in labels:
        p = root / "var" / "eval" / "vision" / f"run-{lab}.jsonl"
        if not p.is_file():
            continue
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        s = res[lab] = summary(rows, items, known)
        lines.append(f"| {lab} | {s['images']} | {s['precision']} | {s['recall']} | {s['correct']} | {s['wrong']} | "
                     f"{s['unknown']} | {s['unmatched']} | {s['median_s']} | {s['errors']} |")
    out = root / "var" / "eval" / "vision" / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out.with_suffix(".json")).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from ..config import load_env, port_base
    ap = argparse.ArgumentParser(prog="python -m jiezi.eval.vision")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("-n", type=int, default=100)
    r = sub.add_parser("run")
    r.add_argument("label")
    r.add_argument("--limit", type=int)
    rp = sub.add_parser("report")
    rp.add_argument("labels", nargs="+")
    a = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    if a.cmd == "prepare":
        return prepare(root, a.n)
    if a.cmd == "run":
        env = load_env(root)
        print(run(root, f"http://127.0.0.1:{port_base(env)}", env.get("JIEZI_GATEWAY_KEY") or "", a.label, a.limit))
        return 0
    print(report(root, a.labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

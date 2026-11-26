"""圖中文字評測（add-image-ocr 3.1、3.2）：自製的繁中招牌、告示、菜單、截圖，量「答案寫出圖中文字」的正確率。
Text-in-image evaluation: synthetic Traditional Chinese signs, notices, menus and screenshots.

- 圖片：本機渲染，文字取自全國法規資料庫條文（政府資料開放授權）與程式隨機組合的店名、價格、時間、電話（虛構）；
  不含真實人物或商家。字型用本機已有的繁中字型（預設 Windows 字型資料夾，可用 --fonts 指定），圖片只放 var/，不散布。
  Images are rendered locally from law text (open government data) and made-up shop data; kept under var/ only.
- 干擾：旋轉、透視、模糊、雜訊、JPEG 壓縮、深底淺字、直排，模擬實拍。
- 計分：字元召回率＝正解文字（去空白標點，台＝臺）與答案的最長共同子序列長度／正解長度；
  數字命中率＝正解裡每個數字串（價格、電話、時間、條號）是否原樣出現在答案。
Scoring: character recall via the longest common subsequence, and whether every digit string appears verbatim."""

from __future__ import annotations

import base64
import io
import json
import random
import re
import time
import unicodedata
from pathlib import Path

QUESTION = "這張圖上寫了什麼？請把圖中的文字完整寫出來。"
SEED = 20261126
DIR = "var/eval/vision-text"
SET = DIR + "/set.jsonl"
FONTS = ("msjh.ttc", "msjhbd.ttc", "kaiu.ttf", "mingliu.ttc")
DEFAULT_FONT_DIR = "/mnt/c/Windows/Fonts"

_SHOP = ["阿嬤", "老街", "巷口", "福記", "永和", "大稻埕", "日日", "山海", "小村", "金華"]
_KIND = ["麵線", "豆花", "牛肉麵", "便當", "雞排", "咖啡", "滷肉飯", "水煎包", "鍋貼", "珍珠奶茶"]
_DISH = ["招牌滷肉飯", "排骨便當", "肉圓", "蚵仔煎", "大腸麵線", "紅茶", "綠豆湯", "燙青菜", "貢丸湯", "蘿蔔糕"]
_NOTICE = ["本店週一公休", "請勿在此吸菸", "施工中 請改道", "內有監視器", "停車場 限時兩小時", "禁止停車 違者拖吊"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").replace("臺", "台")
    return re.sub(r"[^\w]|_", "", s)


def _lcs(a: str, b: str) -> int:
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b):
            cur.append(prev[j] + 1 if ca == cb else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def score_one(truth: str, answer: str) -> dict:
    t, a = _norm(truth), _norm(answer)
    nums = list(dict.fromkeys(re.findall(r"\d+(?:[:\-.]\d+)*", unicodedata.normalize("NFKC", truth))))
    ans = unicodedata.normalize("NFKC", answer or "")
    hit = [n for n in nums if n in ans]
    return {"chars": len(t), "recall": round(_lcs(t, a) / len(t), 4) if t else 0.0,
            "numbers": len(nums), "number_hits": len(hit)}


def summary(rows: list[dict], items: dict[str, dict]) -> dict:
    ok = [r for r in rows if "answer" in r and r["id"] in items]
    sc = [score_one(items[r["id"]]["text"], r["answer"]) for r in ok]
    secs = sorted(r["seconds"] for r in ok)
    nums = sum(s["numbers"] for s in sc)
    return {"images": len(rows), "errors": len(rows) - len(ok),
            "char_recall": round(sum(s["recall"] for s in sc) / len(sc), 4) if sc else 0.0,
            "number_hit": round(sum(s["number_hits"] for s in sc) / nums, 4) if nums else 0.0,
            "median_s": secs[len(secs) // 2] if secs else 0.0}


# ── 產生圖片 / Rendering ──
def _texts(rng: random.Random, root: Path, n: int) -> list[tuple[str, str]]:
    """(種類, 文字)；換行分隔。 / (kind, text) pairs; lines separated by newlines."""
    out = []
    laws = []
    try:
        from ..laws import Laws, db_path
        lw = Laws(db_path(root))
        laws = [(name, no, text) for name, no, text in lw.con.execute(
            "SELECT l.name, a.no, a.text FROM articles a JOIN laws l ON l.id = a.law "
            "WHERE l.abolished = 0 AND length(a.text) BETWEEN 24 AND 60 ORDER BY a.id LIMIT 4000")]
    except Exception:  # noqa: BLE001 - 沒有法規資料庫就只用自製文字 / no law DB: synthetic text only
        laws = []
    for i in range(n):
        k = i % 5
        if k == 0 and laws:
            name, no, text = rng.choice(laws)
            body = re.sub(r"\s+", "", text)
            lines = [f"{name} {no.replace(' ', '')}"] + [body[j:j + 16] for j in range(0, len(body), 16)]
            out.append(("law", "\n".join(lines)))
        elif k == 1:
            shop = rng.choice(_SHOP) + rng.choice(_KIND)
            phone = f"0{rng.choice([2, 4, 7])}-{rng.randint(2000, 8999)}-{rng.randint(1000, 9999)}"
            hours = f"{rng.randint(6, 11):02d}:{rng.choice(['00', '30'])}-{rng.randint(19, 23)}:{rng.choice(['00', '30'])}"
            out.append(("sign", f"{shop}\n營業時間 {hours}\n電話 {phone}"))
        elif k == 2:
            dishes = rng.sample(_DISH, 4)
            out.append(("menu", "菜單\n" + "\n".join(f"{d} {rng.randint(3, 24) * 5}元" for d in dishes)))
        elif k == 3:
            fine = rng.choice([600, 1200, 1800, 3000, 6000])
            out.append(("notice", f"{rng.choice(_NOTICE)}\n違者處新臺幣{fine}元罰鍰"))
        elif i % 10 == 4:
            shop = rng.choice(_SHOP) + rng.choice(_KIND)
            out.append(("vertical", shop))
        else:                                      # 多欄直排告示，由右而左讀 / multi-column, read right to left
            cn = "〇一二三四五六七八九"
            o, c = rng.randint(6, 11), rng.randint(19, 22)
            def num(v):
                return ("十" if v == 10 else "十" + cn[v - 10] if v < 20 else "二十" + (cn[v - 20] if v > 20 else "")) \
                    if v >= 10 else cn[v]
            cols = [rng.choice(_NOTICE[:2]).replace(" ", ""), f"營業時間上午{num(o)}時", f"至晚上{num(c - 12)}時"]
            out.append(("vertical-multi", "\n".join(cols)))
    return out


def _render(rng: random.Random, kind: str, text: str, font_path: Path):
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    dark = rng.random() < 0.35
    bg = tuple(rng.randint(10, 60) for _ in range(3)) if dark else tuple(rng.randint(200, 250) for _ in range(3))
    fg = (rng.randint(220, 255), rng.randint(200, 255), rng.randint(120, 255)) if dark else \
        (rng.randint(0, 60), rng.randint(0, 40), rng.randint(0, 60))
    size = {"law": 30, "sign": 52, "menu": 38, "notice": 46, "vertical": 70, "vertical-multi": 48}[kind]
    font = ImageFont.truetype(str(font_path), size)
    lines = text.split("\n")
    if kind == "vertical-multi":
        w, h = (size + 30) * len(lines) + 80, size * max(map(len, lines)) + 100
        img = Image.new("RGB", (w, h), bg)
        d = ImageDraw.Draw(img)
        for i, col in enumerate(lines):                       # 第一欄在最右 / first column on the right
            x = w - 40 - (i + 1) * (size + 30) + 15
            for j, ch in enumerate(col):
                d.text((x, 50 + j * size), ch, font=font, fill=fg)
    elif kind == "vertical":
        w, h = size + 80, size * len(text) + 100
        img = Image.new("RGB", (w, h), bg)
        d = ImageDraw.Draw(img)
        for j, ch in enumerate(text):
            d.text((40, 50 + j * size), ch, font=font, fill=fg)
    else:
        w = max(int(font.getlength(x)) for x in lines) + 120
        h = int(size * 1.4) * len(lines) + 100
        img = Image.new("RGB", (w, h), bg)
        d = ImageDraw.Draw(img)
        for j, x in enumerate(lines):
            d.text((60, 50 + j * int(size * 1.4)), x, font=font, fill=fg)
    # 放到較大的背景上再旋轉，模擬拍照 / place on a larger backdrop and rotate, like a photo
    pad = 60
    back = Image.new("RGB", (img.width + 2 * pad, img.height + 2 * pad),
                     tuple(rng.randint(80, 170) for _ in range(3)))
    back.paste(img, (pad, pad))
    back = back.rotate(rng.uniform(-5, 5), expand=True, fillcolor=back.getpixel((0, 0)))
    if rng.random() < 0.5:
        back = back.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.4)))
    if rng.random() < 0.5:
        import numpy as np
        a = np.asarray(back).astype("int16") + np.random.default_rng(rng.randint(0, 2**31)).integers(
            -18, 18, size=(back.height, back.width, 3))
        back = Image.fromarray(a.clip(0, 255).astype("uint8"))
    scale = min(1.0, 1024 / max(back.size))
    if scale < 1:
        back = back.resize((int(back.width * scale), int(back.height * scale)))
    buf = io.BytesIO()
    back.save(buf, "JPEG", quality=rng.randint(45, 85))
    return buf.getvalue()


def prepare(root: Path, n: int = 20, font_dir: str = DEFAULT_FONT_DIR, log=print) -> int:
    fonts = [Path(font_dir) / f for f in FONTS if (Path(font_dir) / f).is_file()]
    if not fonts:
        log(f"no Traditional Chinese fonts in {font_dir}; pass --fonts DIR")
        return 1
    rng = random.Random(SEED)
    d = root / DIR / "images"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, (kind, text) in enumerate(_texts(rng, root, n)):
        font = fonts[i % len(fonts)] if not kind.startswith("vertical") else next((f for f in fonts if f.name == "kaiu.ttf"), fonts[0])
        data = _render(rng, kind, text, font)
        f = d / f"t{i:02d}-{kind}.jpg"
        f.write_bytes(data)
        rows.append({"id": f.stem, "kind": kind, "font": font.name, "file": str(f.relative_to(root)), "text": text})
    (root / SET).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    log(f"{len(rows)} images -> {root / SET}")
    return 0


def run(root: Path, url: str, key: str, label: str, log=print) -> Path:
    """每張圖問一次，可接續。 / One question per image; resumable."""
    import httpx
    items = [json.loads(x) for x in (root / SET).read_text(encoding="utf-8").splitlines() if x.strip()]
    out = root / DIR / f"run-{label}.jsonl"
    done = {json.loads(x)["id"] for x in out.read_text(encoding="utf-8").splitlines() if x.strip()} \
        if out.is_file() else set()
    headers = {"Authorization": f"Bearer {key}"}
    with httpx.Client(timeout=600) as c, out.open("a", encoding="utf-8") as f:
        for it in items:
            if it["id"] in done:
                continue
            data = base64.b64encode((root / it["file"]).read_bytes()).decode()
            t0, row = time.monotonic(), {"id": it["id"], "label": label}
            try:
                r = c.post(url + "/v1/chat/completions", headers=headers, json={
                    "model": "jiezi-local", "messages": [{"role": "user", "content": [
                        {"type": "text", "text": QUESTION},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]}]})
                r.raise_for_status()
                row["answer"] = r.json()["choices"][0]["message"].get("content") or ""
                row["seconds"] = round(time.monotonic() - t0, 1)
            except Exception as exc:  # noqa: BLE001 - 一張失敗記下來繼續 / record and go on
                row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            s = score_one(it["text"], row.get("answer", ""))
            log(f"{it['id']} {row.get('seconds')}s recall {s['recall']} numbers {s['number_hits']}/{s['numbers']} "
                f"{row.get('error') or ''}")
    return out


def report(root: Path, labels: list[str]) -> str:
    items = {r["id"]: r for r in (json.loads(x) for x in (root / SET).read_text(encoding="utf-8").splitlines()
                                  if x.strip())}
    lines = ["# 圖中文字評測 / Text-in-image evaluation", "",
             f"- 圖片：自製繁中招牌、告示、菜單、法規告示、直排招牌 {len(items)} 張（種子 {SEED}）；問題「{QUESTION}」",
             "- 字元召回率＝正解與答案的最長共同子序列／正解長度（去空白標點，台＝臺）；數字命中率＝數字串原樣出現的比例",
             "", "| 條件 | 張數 | 字元召回率 | 數字命中率 | 中位秒數 | 錯誤 |", "|---|---|---|---|---|---|"]
    res = {}
    for lab in labels:
        p = root / DIR / f"run-{lab}.jsonl"
        if not p.is_file():
            continue
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        s = res[lab] = summary(rows, items)
        lines.append(f"| {lab} | {s['images']} | {s['char_recall']} | {s['number_hit']} | {s['median_s']} | {s['errors']} |")
    by_kind = {}
    for lab in labels:
        p = root / DIR / f"run-{lab}.jsonl"
        if p.is_file():
            for x in p.read_text(encoding="utf-8").splitlines():
                r = json.loads(x)
                if "answer" in r and r["id"] in items:
                    by_kind.setdefault(items[r["id"]]["kind"], {}).setdefault(lab, []).append(
                        score_one(items[r["id"]]["text"], r["answer"])["recall"])
    lines += ["", "| 種類 | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    for k, v in sorted(by_kind.items()):
        lines.append(f"| {k} | " + " | ".join(
            str(round(sum(v.get(lab, [0])) / max(1, len(v.get(lab, []))), 3)) for lab in labels) + " |")
    out = root / DIR / "report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(out)


def main(argv: list[str] | None = None) -> int:
    import argparse
    from ..config import load_env, port_base
    ap = argparse.ArgumentParser(prog="python -m jiezi.eval.vision_text")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--fonts", default=DEFAULT_FONT_DIR)
    r = sub.add_parser("run")
    r.add_argument("label")
    rp = sub.add_parser("report")
    rp.add_argument("labels", nargs="+")
    a = ap.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    if a.cmd == "prepare":
        return prepare(root, a.n, a.fonts)
    if a.cmd == "run":
        env = load_env(root)
        print(run(root, f"http://127.0.0.1:{port_base(env)}", env.get("JIEZI_GATEWAY_KEY") or "", a.label))
        return 0
    print(report(root, a.labels))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

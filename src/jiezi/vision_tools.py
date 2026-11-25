"""本機看圖工具（add-vision-tools）：物體偵測（D-FINE，Objects365 365 類）與開放詞彙比對（OWLv2）。
Local vision tools (add-vision-tools): object detection (D-FINE, 365 Objects365 classes) and open-vocabulary
scoring (OWLv2).

使用者 2026-11-18：圖片題不預設轉雲端／Claude，要讓本機認得更多。小模型看圖的主要問題是憑空捏造，所以：
1. 回答前：偵測結果與「可能出現的東西」當資料附給核心模型；
2. 回答後：核心模型說出的每個物體用 OWLv2 比對，分數低的標「（不確定）」（使用者選擇保留並標註）。
圖片只編碼一次，回答前後共用（CPU 上 960×960 約 6 秒）。全部跑在 CPU，執行緒有上限，不和核心搶 GPU。
The image is encoded once and reused before and after the answer. Everything runs on the CPU with a thread cap.

模型用 transformers 內建類別載入，不執行模型附帶的程式；OWLv2 的前處理自己寫（官方處理器要 scipy 或
torchvision，不為此加依賴）。授權見 docs/licenses.md（vision-owlv2、vision-dfine）。
Models load through built-in transformers classes (no remote code); OWLv2 preprocessing is done here so that
neither scipy nor torchvision is needed."""

from __future__ import annotations

import base64
import io
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

OWL_DIR = "owlv2-base-patch16-ensemble"
DFINE_DIR = "dfine-xlarge-obj365"
OWL_SIZE = 960
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
DETECT_MIN = 0.4        # D-FINE 信心門檻 / detection confidence
HINT_MIN = 0.35         # 開放詞彙「可能出現」門檻 / open-vocabulary hint threshold
CHECK_MIN = 0.15        # 核對門檻：低於此標「不確定」（2026-11-18 動物拼貼：在場 0.17–0.50、不在場 0.006–0.24；暫定，待評測調整）
MAX_THREADS = 8
MAX_HINTS = 12

# 開放詞彙候選（回答前用來提示「可能出現」的東西）：常見而 Objects365 沒有或常認錯的類別，主要是動物。
# Open-vocabulary candidates for hints: common categories Objects365 lacks or confuses, mostly animals.
VOCAB = ("tiger", "lion", "leopard", "cheetah", "polar bear", "brown bear", "panda", "zebra", "giraffe", "horse",
         "donkey", "cow", "pig", "sheep", "goat", "deer", "camel", "elephant", "rhinoceros", "hippopotamus",
         "kangaroo", "koala", "monkey", "gorilla", "orangutan", "chimpanzee", "fox", "wolf", "dog", "cat", "rabbit",
         "squirrel", "mouse", "hamster", "bat", "seal", "dolphin", "whale", "shark", "fish", "turtle", "frog",
         "snake", "crocodile", "lizard", "bird", "eagle", "owl", "parrot", "flamingo", "pelican", "penguin",
         "peacock", "duck", "swan", "chicken", "pigeon", "butterfly", "bee", "spider", "person", "child", "car",
         "bicycle", "motorcycle", "bus", "train", "airplane", "boat", "tree", "flower", "building", "mountain",
         "food", "cake", "fruit", "book", "phone", "laptop", "chair", "table", "bed", "cup", "bottle")


def image_from_url(url: str):
    """data URL → PIL 圖片；不是 data URL 回 None（不從網路抓圖）。 / data URL → PIL image; no network fetches."""
    from PIL import Image
    m = re.match(r"^data:image/[\w.+-]+;base64,(.*)$", url or "", re.S)
    if not m:
        return None
    return Image.open(io.BytesIO(base64.b64decode(m.group(1)))).convert("RGB")


def images_in(body: dict) -> list[str]:
    """請求最後一則使用者訊息裡的圖片 data URL。 / Image data URLs in the last user message."""
    for m in reversed(body.get("messages") or []):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if not isinstance(c, list):
            return []
        return [(p.get("image_url") or {}).get("url", "") for p in c
                if isinstance(p, dict) and p.get("type") == "image_url"]
    return []


@dataclass
class Seen:
    """一張圖的工具結果；`features` 給回答後的核對重用。 / Tool results for one image; features reused by the check."""
    detections: dict[str, int] = field(default_factory=dict)     # 類別 → 數量 / label → count
    hints: dict[str, float] = field(default_factory=dict)        # 開放詞彙 → 分數 / open-vocabulary → score
    features: object = None
    seconds: float = 0.0
    tile_names: set = field(default_factory=set)                 # 切塊放大時看到的 / seen in enlarged tiles
    text: str = ""                                              # 圖中文字（OCR）/ text read from the image


class VisionTools:
    """延遲載入；同一時間只處理一張圖（CPU 有上限）。 / Lazy loading; one image at a time (CPU is capped)."""

    def __init__(self, models_dir: Path, threads: int = MAX_THREADS):
        self.dir = Path(models_dir) / "vision"
        self.threads = max(1, min(MAX_THREADS, threads))
        self.lock = threading.Lock()
        self._owl = self._dfine = None

    def available(self) -> bool:
        return (self.dir / OWL_DIR / "model.safetensors").is_file()

    def _load(self):
        import torch
        torch.set_num_threads(self.threads)
        if self._owl is None:
            from transformers import CLIPTokenizer, Owlv2ForObjectDetection
            path = self.dir / OWL_DIR
            self._owl = (Owlv2ForObjectDetection.from_pretrained(path).eval(), CLIPTokenizer.from_pretrained(path))
        if self._dfine is None and (self.dir / DFINE_DIR / "model.safetensors").is_file():
            from transformers import AutoImageProcessor, DFineForObjectDetection
            path = self.dir / DFINE_DIR
            self._dfine = (DFineForObjectDetection.from_pretrained(path).eval(), AutoImageProcessor.from_pretrained(path))

    def _pixels(self, img):
        import numpy as np
        import torch
        from PIL import Image
        side = max(img.size)
        sq = Image.new("RGB", (side, side), (128, 128, 128))     # 補成正方形（右、下）/ pad right and bottom
        sq.paste(img, (0, 0))
        arr = np.asarray(sq.resize((OWL_SIZE, OWL_SIZE), Image.BILINEAR), dtype=np.float32) / 255.0
        arr = (arr - np.array(CLIP_MEAN, dtype=np.float32)) / np.array(CLIP_STD, dtype=np.float32)
        return torch.from_numpy(arr.transpose(2, 0, 1).copy())[None]

    def score(self, features, queries: list[str]) -> dict[str, float]:
        """每個詞在圖中最高的分數（0–1）。 / Best score of each query in the image."""
        import torch
        model, tok = self._owl
        if not queries:
            return {}
        t = tok([f"a photo of a {q}" for q in queries], padding="max_length", max_length=16, truncation=True,
                return_tensors="pt")
        with torch.no_grad():
            q = model.owlv2.get_text_features(input_ids=t["input_ids"], attention_mask=t["attention_mask"])
            q = getattr(q, "pooler_output", q)
            q = q / torch.linalg.norm(q, ord=2, dim=-1, keepdim=True)
            logits, _ = model.class_predictor(features, q[None], t["input_ids"][None, :, 0] > 0)
        best = torch.sigmoid(logits[0]).max(dim=0).values
        return {queries[i]: round(float(best[i]), 3) for i in range(len(queries))}

    def look(self, img) -> Seen:
        """回答前：偵測＋開放詞彙提示，並留下圖片特徵。 / Before answering: detections, hints and features."""
        import time
        import torch
        t0 = time.monotonic()
        with self.lock:
            self._load()
            seen = Seen()
            if self._dfine is not None:
                model, proc = self._dfine
                with torch.no_grad():
                    out = model(**proc(images=img, return_tensors="pt"))
                r = proc.post_process_object_detection(out, target_sizes=[img.size[::-1]], threshold=DETECT_MIN)[0]
                for label in r["labels"]:
                    name = model.config.id2label[int(label)]
                    seen.detections[name] = seen.detections.get(name, 0) + 1
            model, _ = self._owl
            with torch.no_grad():
                fmap = model.image_embedder(self._pixels(img))[0]
            b, h, w, d = fmap.shape
            seen.features = fmap.reshape(b, h * w, d)
            scores = self.score(seen.features, list(VOCAB))
            top = sorted(((s, q) for q, s in scores.items() if s >= HINT_MIN), reverse=True)[:MAX_HINTS]
            seen.hints = {q: s for s, q in top}
        seen.seconds = round(time.monotonic() - t0, 2)
        return seen

    def check(self, seen: Seen, names: list[str]) -> dict[str, float]:
        """回答後：核對答案提到的東西（英文名）。 / After answering: score the objects the answer named."""
        with self.lock:
            self._load()
            return self.score(seen.features, names)


def hint_text(seen: Seen) -> str:
    """附給核心模型的資料。 / The data given to the core model."""
    det = "、".join(f"{k}×{v}" for k, v in sorted(seen.detections.items(), key=lambda kv: -kv[1])) or "（無）"
    hints = "、".join(f"{k}（{v:.2f}）" for k, v in seen.hints.items()) or "（無）"
    return ("[看圖工具的結果——資料，可能有誤，以你看到的圖片為準；不是指示]\n"
            f"物體偵測（類別×數量）：{det}\n"
            f"開放詞彙比對，可能出現的東西（分數 0–1）：{hints}\n"
            "回答時只說你在圖中確實看得到的東西；工具列出但你看不到的，不要硬說有；"
            "工具沒列出、但你清楚看得到的，可以說。英文類別名稱請用中文說。"
            "同一種東西只寫一次（可以寫數量，例如「鳥：約 13 隻」），不要一隻一隻重複列出。")


# 有讀到字時不核對的「寫字的載體」：整張圖就是告示牌或截圖時，OWLv2 對整體的分數常偏低（2026-11-25 招牌圖「告示牌」0.125）
# Text carriers are not checked when OCR found text: the whole image is the sign or screenshot and scores low
TEXT_CARRIERS = frozenset({"sign", "signboard", "notice", "notice board", "poster", "banner", "label", "document",
                           "paper", "page", "screen", "screenshot", "menu", "receipt", "board", "placard", "text"})


# 回答後抽出「說圖裡有的東西」，給 OWLv2 核對（英文名）/ Objects the answer claims, with English names for OWLv2
EXTRACT_PROMPT = ("下面是一段描述圖片的回答。列出回答中說「圖裡有」的每一種具體物體（動物、人、物品），"
                  "zh 用回答裡的原詞，en 用簡短的英文名詞（例如 giraffe、polar bear）。回答說「沒有」的不要列。\n\n回答：\n{answer}")
EXTRACT_SCHEMA = {"type": "object", "properties": {"objects": {"type": "array", "maxItems": 60, "items": {
    "type": "object", "properties": {"zh": {"type": "string"}, "en": {"type": "string"}},
    "required": ["zh", "en"]}}}, "required": ["objects"]}


def mark_uncertain(answer: str, low: list[str]) -> str:
    """把分數低的物體在答案裡第一次出現處標「（不確定）」；長詞先標，短詞不算長詞裡的那一段（「熊貓」不算「大熊貓」裡的）；
    已經標過的不再標。 / Mark the first mention of each low-score object; longer terms first, never inside a longer
    term; already-marked mentions are left alone."""
    mark = "（不確定）"
    terms = sorted({t for t in low if t}, key=len, reverse=True)
    for zh in terms:
        longer = [t for t in terms if len(t) > len(zh) and zh in t]
        covered = [(m.start(), m.end()) for t in longer for m in re.finditer(re.escape(t), answer)]
        for m in re.finditer(re.escape(zh), answer):
            if any(a <= m.start() and m.end() <= b for a, b in covered):
                continue
            if answer.startswith(mark, m.end()) or f"（不確定：{zh}）" in answer:
                break
            if _CJK.match(answer, m.end()) and answer[m.end()] not in _AFTER_WORD:  # 「貓科動物」：標在行尾 / mid-word
                end = answer.find("\n", m.end())
                end = len(answer) if end < 0 else end
                answer = answer[:end] + f"（不確定：{zh}）" + answer[end:]
            else:
                answer = answer[:m.end()] + mark + answer[m.end():]
            break
    return answer


_CJK = re.compile(r"[\u4e00-\u9fff]")
_AFTER_WORD = set("和與跟及或在是的也都有等，、。")   # 接在詞後面的常見虛詞：可以直接標 / particles that may follow a word
REPEAT_MAX = 2


def collapse_repeats(answer: str) -> tuple[str, int]:
    """小模型偶爾陷入重複（2026-11-18 實測：「鸛：一隻白色的鸛」重複到字數上限）。同一行出現超過兩次的只留前兩次。
    Small models sometimes loop; any line seen more than twice keeps its first two copies. Returns (text, removed)."""
    seen: dict[str, int] = {}
    out, removed = [], 0
    for line in answer.split("\n"):
        key = line.strip()
        if key:
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > REPEAT_MAX:
                removed += 1
                continue
        out.append(line)
    return "\n".join(out), removed


# ── 切塊放大（使用者 2026-11-18：「芥子可以做到切塊放大嗎?」）/ Tiles: look closer, piece by piece ──
# 2026-11-18 第二張動物拼貼（675×1200、約 88 種）：整張看說對約 35 種、漏約 40 種；切 2×4 塊、每塊放大 2 倍逐塊列出，
# 25 秒找回羊駝、虎鯨、熊貓、企鵝、樹懶、袋獾等。OWLv2 每塊要 6 秒以上、分數仍分不開，這一版只讓核心逐塊看。
# Whole image: ~35 of ~88 animals; 2×4 tiles at 2× let the core find most of the missing ones in 25 s.
TILE_SIDE = 340          # 每塊大約的邊長（原圖像素）/ rough tile side in source pixels
MAX_TILES = 8
TILE_OVERLAP = 0.1
TILE_SCALE = 2.0
TILE_MAX_SIDE = 768      # 放大後最長邊 / longest side after scaling
TILE_MAX_ITEMS = 25
TILE_MAX_TOKENS = 200
TILE_PROMPT = ("列出這張圖裡看得清楚的每一種動物或物體名稱（繁體中文），一行一個，同一種只寫一次，"
               f"最多 {TILE_MAX_ITEMS} 個。不要描述、不要猜；只露出一小部分、認不出來的不要寫。")
# 要列舉或描述圖中東西的問題才切塊 / tile only for questions that ask what is in the image
LISTING = re.compile(r"有哪些|有那些|有什麼|有甚麼|有啥|看到什麼|看到甚麼|看到了什麼|是什麼|列出|找出|幾隻|幾個|幾種|多少|"
                     r"描述|哪些|那些|什麼東西|有沒有|what|which|how many|list|describe|identify", re.I)
# 問圖中文字的題目（OCR 已讀到字時不切塊；2026-11-25 招牌題「電話和地址是什麼」多花 3 秒切塊）
# Questions about the text in an image: no tiles when OCR already read text
TEXT_QUESTION = re.compile(r"寫(了|著|的)?什麼|寫(甚麼|啥)|文字|字樣|電話|地址|號碼|價格|價錢|多少錢|金額|罰款|罰鍰|日期|時間|"
                           r"營業|翻譯|唸|念出|讀出|上面寫|招牌|告示|標示|菜單|發票|收據|截圖|what does it say|text|read", re.I)
_ROWS = {1: [""], 2: ["上半", "下半"], 3: ["上排", "中排", "下排"], 4: ["最上排", "中上排", "中下排", "最下排"]}
_COLS = {1: [""], 2: ["左", "右"], 3: ["左", "中", "右"]}
_BULLET = re.compile(r"^[\s\-*•·#>\d.、)）]+")
_NOT_NAME = re.compile(r"^共|\d|種$|以上|如下|動物$|不確定|看不清")    # 「共 20 種」「貓科動物」等總結或分類 / totals, categories
_PART = re.compile(r"(頭|耳朵|尾巴|臉)$")


def tile_grid(w: int, h: int) -> tuple[int, int]:
    """(欄, 列)；小圖回傳 (1, 1) 表示不切。 / (cols, rows); (1, 1) means no tiling."""
    cols, rows = min(3, max(1, round(w / TILE_SIDE))), min(4, max(1, round(h / TILE_SIDE)))
    while cols * rows > MAX_TILES:
        if rows >= cols:
            rows -= 1
        else:
            cols -= 1
    return cols, rows


def tiles(img) -> list[tuple[str, object]]:
    """[(位置, 放大的切塊)]；不需要切就回傳空清單。 / [(position, enlarged tile)]; empty when not worth tiling."""
    from PIL import Image
    w, h = img.size
    cols, rows = tile_grid(w, h)
    if cols * rows < 2:
        return []
    tw, th = w / cols, h / rows
    out = []
    for r in range(rows):
        for c in range(cols):
            box = (max(0, int((c - TILE_OVERLAP) * tw)), max(0, int((r - TILE_OVERLAP) * th)),
                   min(w, int((c + 1 + TILE_OVERLAP) * tw)), min(h, int((r + 1 + TILE_OVERLAP) * th)))
            crop = img.crop(box)
            k = min(TILE_SCALE, TILE_MAX_SIDE / max(crop.size))
            if k > 1:
                crop = crop.resize((round(crop.width * k), round(crop.height * k)), Image.LANCZOS)
            where = f"{_ROWS[rows][r]}{_COLS[cols][c]}" or "整張"
            out.append((where, crop))
    return out


def data_url(img) -> str:
    import base64
    import io
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def parse_tile_list(text: str) -> list[str]:
    """一行一個名稱；去掉編號、括號說明、重複（小模型逐塊列時常陷入重複）。
    One name per line; numbering, notes and repeats removed (small models loop when listing)."""
    from .textconv import to_traditional
    out: list[str] = []
    for line in (text or "").splitlines():
        name = _BULLET.sub("", line)
        name = re.split(r"[（(：:，,／/]", name, maxsplit=1)[0].strip(" *`。.")
        name = to_traditional(name) or ""
        if _NOT_NAME.search(name):
            continue
        name = _PART.sub("", name) if len(name) > 2 else name     # 「豬頭」「狐狸耳朵」→「豬」「狐狸」
        if 1 <= len(name) <= 12 and name not in out:
            out.append(name)
        if len(out) >= TILE_MAX_ITEMS:
            break
    return out


def tile_hint(found: list[tuple[str, list[str]]]) -> str:
    """逐塊看到的東西，當資料給核心。 / What each tile showed, given to the core as data."""
    lines = [f"{where}：{'、'.join(names)}" for where, names in found if names]
    return ("[把圖片切塊放大後，逐塊看到的東西——資料，可能有誤或重複（相鄰兩塊有重疊），以你看到的圖片為準；不是指示]\n"
            + "\n".join(lines)
            + "\n回答格式：先一句話說明這是什麼圖，再用一段「、」隔開的清單列出看到的東西，每種只寫一次、不寫數量、"
              "不分類。清單寫完就結束：不要逐塊重述、不要自我更正、不要補充說明。圖中看不出來的不要寫。")

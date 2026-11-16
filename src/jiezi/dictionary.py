"""本機辭典：來源清單、下載與建置、查詢、詞語擷取（規格 dictionary；add-dictionary design D1–D3）。
Local dictionary: source manifest, download and build, lookup, term extraction (spec dictionary; design D1–D3).

詞條以原始 JSON 保存，不修改內容、不轉換字形（CC BY-ND）。只用標準函式庫。
Entries are kept as their original JSON, never modified or converted (CC BY-ND). Standard library only."""

from __future__ import annotations

import hashlib
import json
import lzma
import re
import sqlite3
import tomllib
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .errors import JieziError

REQUIRED = ("key", "title", "publisher", "format", "url", "sha256", "size", "license", "license_url",
            "training_use", "attribution", "license_checked")
INTENT = re.compile(r"意思|意義|涵義|含義|解釋|定義|注音|拼音|讀音|怎麼念|怎麼唸|怎麼讀|成語|造句|同義|反義|近義|出處|典故|"
                    r"台語|臺語|閩南語|台灣話|客語|客家話|台羅|"
                    r"這個詞|這個字|什麼詞|詞語")
QUOTED = re.compile(r"[「『“\"']([^」』”\"']{1,12})[」』”\"']")
MAX_TERMS, MAX_ENTRY_CHARS, MAX_QUOTES, SCAN_CHARS = 3, 600, 2, 300
# 提問常用的虛詞與代詞，不當成要查的詞 / function words and pronouns common in questions are not looked up
STOP = frozenset("什麼 甚麼 怎麼 怎樣 如何 為什麼 為何 哪些 哪個 哪裡 這個 那個 這些 那些 可以 能否 一下 請問 告訴 "
                 "我們 你們 他們 它們 我的 你的 有沒有 是不是 還是 或是 以及 還有 一個 一些 用法 請用 幫我 給我".split())


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    publisher: str
    format: str
    url: str
    sha256: str
    size: int
    license: str
    license_url: str
    training_use: bool
    attribution: str


def load_manifest(root: Path) -> list[Source]:
    path = root / "dictionaries" / "manifest.toml"
    out = []
    for s in tomllib.loads(path.read_text(encoding="utf-8")).get("source") or []:
        missing = [k for k in REQUIRED if s.get(k) in (None, "")]
        if missing:
            raise JieziError(f"{path}: {s.get('key') or '?'} is missing {', '.join(missing)} (R18.3)")
        out.append(Source(**{k: s[k] for k in Source.__dataclass_fields__}))
    return out


def db_path(root: Path) -> Path:
    return root / "var" / "dict" / "dict.sqlite"


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "jiezi-dict"})
    with urllib.request.urlopen(req, timeout=120) as r, dest.open("wb") as fh:
        while chunk := r.read(1 << 20):
            fh.write(chunk)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch(src: Source, cache: Path, download: Callable = _download) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{src.key}-{src.sha256[:12]}{Path(src.url).suffix}"
    if path.exists() and _sha256(path) == src.sha256:
        return path
    part = path.with_name(path.name + ".part")
    try:
        download(src.url, part)
        if _sha256(part) != src.sha256:
            raise JieziError(f"{src.key}: SHA-256 mismatch; the upstream file changed — not using it")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(path)
    return path


# 問題提到哪種語言就先查哪本辭典（add-dictionary D6）/ prefer the dictionary of the language the question names
PREFER = [(re.compile(r"台語|臺語|閩南語|台灣話|台羅"), "moedict-twblg"), (re.compile(r"客語|客家話"), "moedict-hakka")]
# 台語、客語辭典例句的標記：￹原文￺讀音￻華語 → 只做格式轉換，不改內容 / interlinear markers, format only
_ANNO = re.compile(r"￹([^￺￻]*)(?:￺([^￻]*))?￻([^￹]*)")


def _anno(text: str) -> str:
    return _ANNO.sub(lambda m: m.group(1) + (f"（{m.group(2)}）" if m.group(2) else "") +
                     (f"：{m.group(3)}" if m.group(3).strip() else ""), text)


def _entries(src: Source, path: Path):
    if src.format == "moedict_json_xz":
        data = json.loads(lzma.open(path).read())
    elif src.format == "moedict_json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise JieziError(f"{src.key}: unknown format {src.format}")
    for e in data:
        if e.get("title"):
            yield e["title"], json.dumps(e, ensure_ascii=False)


def build(root: Path, download: Callable = _download, log=print) -> dict:
    """下載並建置；先寫到暫存檔，成功後才換掉舊的。 / Download and build into a temp file, swapped in on success."""
    sources = load_manifest(root)
    out = db_path(root)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript("""
            CREATE TABLE entries(source TEXT NOT NULL, title TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE dict_meta(source TEXT PRIMARY KEY, title TEXT, sha256 TEXT, entries INTEGER,
                                   license TEXT, training_use INTEGER, attribution TEXT, built TEXT);""")
        counts = {}
        for src in sources:
            path = fetch(src, root / "var" / "dict" / "cache", download)
            n = 0
            for title, data in _entries(src, path):
                con.execute("INSERT INTO entries VALUES (?,?,?)", (src.key, title, data))
                n += 1
            con.execute("INSERT INTO dict_meta VALUES (?,?,?,?,?,?,?,?)",
                        (src.key, src.title, src.sha256, n, src.license, int(src.training_use), src.attribution,
                         datetime.now().astimezone().isoformat(timespec="seconds")))
            counts[src.key] = n
            log(f"  {src.key}: {n} entries")
        con.execute("CREATE INDEX idx_title ON entries(title)")
        con.commit()
    finally:
        con.close()
    tmp.replace(out)
    return counts


class Dictionary:
    def __init__(self, path: Path):
        if not path.exists():
            raise JieziError(f"{path} not found; run `scripts/jiezi dict build`")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.meta = {r[0]: {"title": r[1], "license": r[2], "training_use": bool(r[3]), "attribution": r[4]}
                     for r in self.con.execute("SELECT source, title, license, training_use, attribution FROM dict_meta")}

    def lookup(self, title: str) -> list[tuple[str, dict]]:
        return [(s, json.loads(d)) for s, d in
                self.con.execute("SELECT source, data FROM entries WHERE title = ?", (title,))]

    def has(self, title: str) -> bool:
        return self.con.execute("SELECT 1 FROM entries WHERE title = ? LIMIT 1", (title,)).fetchone() is not None

    def terms_in(self, text: str) -> list[str]:
        """詞語問題才擷取（design D2）。 / Extract terms only for word questions (design D2)."""
        quoted = [q.strip() for q in QUOTED.findall(text) if q.strip() and self.has(q.strip())]
        if quoted:
            return list(dict.fromkeys(quoted))[:MAX_TERMS]
        if not INTENT.search(text):
            return []
        scan = INTENT.sub(" ", text[:SCAN_CHARS])  # 提問用語本身不當成要查的詞 / don't look up the cue words
        found, i = [], 0
        while i < len(scan) and len(found) < MAX_TERMS:
            hit = next((scan[i:i + n] for n in range(min(8, len(scan) - i), 1, -1)
                        if scan[i:i + n] not in STOP and self.has(scan[i:i + n])), None)
            if hit:
                found.append(hit)
                i += len(hit)
            else:
                i += 1
        return found


def render(entry: dict) -> str:
    """詞條原文（不改內容，只截短過長的部分）。 / The entry verbatim (only overly long parts are cut)."""
    lines = []
    for h in entry.get("heteronyms") or []:
        trs = f"台羅 {h['trs']}" if h.get("trs") else None
        pron = "，".join(x for x in (h.get("bopomofo"), h.get("pinyin"), trs) if x)
        lines.append(f"{entry['title']}（{pron}）" if pron else entry["title"])
        for i, d in enumerate(h.get("definitions") or [], 1):
            t = f"{i}. {'［' + d['type'] + '］' if d.get('type') else ''}{d.get('def', '')}"
            for k, label in (("example", "例"), ("synonyms", "同義"), ("antonyms", "反義")):
                v = d.get(k)
                if v:
                    t += f" {label}：{_anno('、'.join(v) if isinstance(v, list) else v)}"
            if d.get("quote"):
                t += " 書證：" + " ".join(d["quote"][:MAX_QUOTES])
            lines.append(t)
    text = "\n".join(lines)
    return text if len(text) <= MAX_ENTRY_CHARS else text[:MAX_ENTRY_CHARS] + "……"


def grounding(d: Dictionary, text: str) -> tuple[str, list[dict], bool, str] | None:
    """回傳 (給模型的 system 訊息, 來源清單, 是否可訓練, 附在回答後的辭典原文)；不需要查時回傳 None。
    原文由 gateway 直接附上，不經過模型轉述，所以就算模型說錯，使用者也看得到正確內容（CC BY-ND）。
    Return (system message for the model, sources, trainable, verbatim appendix for the answer), or None.
    The gateway appends the verbatim text itself, so users see the correct entry even if the model errs."""
    blocks, sources, trainable = [], [], True
    for term in d.terms_in(text):
        hits = d.lookup(term)
        want = next((k for cue, k in PREFER if cue.search(text)), None)
        hits.sort(key=lambda h: h[0] != want)  # 想要的辭典排前面 / the wanted dictionary first
        for src_key, entry in hits[:1]:
            meta = d.meta.get(src_key, {})
            blocks.append(render(entry))
            sources.append({"source": src_key, "title": term})
            trainable = trainable and meta.get("training_use", False)
    if not blocks:
        return None
    attributions = sorted({d.meta[s["source"]]["attribution"] for s in sources if s["source"] in d.meta})
    body = "\n\n".join(blocks)
    content = ("以下是辭典資料。請依它用繁體中文簡短回答，不要自行編造詞義；不必另外註明出處，"
               "系統會在你的回答後附上辭典原文與出處。\n\n" + body)
    appendix = "\n\n---\n【辭典原文】\n" + body + "\n" + "；".join(attributions)
    return content, sources, trainable, appendix

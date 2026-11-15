"""台灣知識庫：taiwan-md 文章的下載、全文索引、檢索與對話引用（add-knowledge D1–D4）。
Taiwan knowledge base: download, full-text index, retrieval and chat grounding for taiwan-md articles (design D1–D4).

文章逐檔以 git blob 雜湊核對（清單在 knowledge/taiwan-md.lock.json，鎖定 commit）。索引用「中文雙字」切詞的
SQLite FTS5，兩個字的詞（刈包、夜市）也找得到。只用標準函式庫。
Files are verified by git blob hash against a lock file pinned to one commit. The index is SQLite FTS5 over
Chinese character bigrams, so two-character words are searchable. Standard library only."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import tomllib
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .errors import JieziError
from .textconv import to_traditional

REQUIRED = ("key", "title", "repo", "commit", "license", "license_url", "training_use", "attribution",
            "license_checked", "lock")
TRANSLATIONS = {"de", "hi", "pt", "en", "id", "ko", "es", "vi", "fr", "ja", "ar", "ru"}
MAX_SECTION_CHARS, MAX_SECTIONS, SCAN_CHARS = 1200, 2, 500
MIN_HITS, MIN_COVER = 3, 0.3
SKIP_HEADINGS = re.compile(r"延伸閱讀|參考資料|參考文獻|資料來源|相關連結|外部連結|註釋|附註")  # 全文檢索的門檻 / thresholds for full-text matches
# 提問常用、不帶主題的雙字 / bigrams common in questions that say nothing about the topic
STOP = {"什麼", "甚麼", "怎麼", "如何", "為什", "麼是", "是什", "請問", "可以", "一下", "告訴", "介紹", "有沒", "沒有",
        "哪些", "哪裡", "哪個", "是不", "不是", "我們", "你們", "知道", "關於", "台灣", "臺灣", "灣的", "的是", "是哪",
        "一個", "這個", "那個", "嗎？", "說明", "簡單", "解釋", "幫我", "給我", "有哪", "有什", "麼樣", "為何"}


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    repo: str
    commit: str
    license: str
    training_use: bool
    attribution: str
    lock: str


def load_manifest(root: Path) -> Source:
    path = root / "knowledge" / "manifest.toml"
    s = tomllib.loads(path.read_text(encoding="utf-8")).get("source") or {}
    missing = [k for k in REQUIRED if s.get(k) in (None, "")]
    if missing:
        raise JieziError(f"{path}: missing {', '.join(missing)} (R18.3)")
    return Source(s["key"], s["title"], s["repo"], s["commit"], s["license"], bool(s["training_use"]),
                  s["attribution"], s["lock"])


def db_path(root: Path) -> Path:
    return root / "var" / "knowledge" / "knowledge.sqlite"


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def wanted(path: str) -> bool:
    """只要繁體中文原文；跳過各語言翻譯與 `_` 開頭的目錄頁。 / zh-TW originals only; no translations or hubs."""
    parts = path.split("/")
    return (len(parts) >= 3 and parts[0] == "knowledge" and parts[1] not in TRANSLATIONS
            and path.endswith(".md") and not parts[-1].startswith("_"))


def make_lock(repo: str, commit: str, fetch_json: Callable | None = None) -> list[dict]:
    """GitHub tree API → [{path, sha, size}]（一次請求）。 / One tree request → file list."""
    def default(url):
        req = urllib.request.Request(url, headers={"User-Agent": "jiezi-knowledge",
                                                   "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    tree = (fetch_json or default)(f"https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1")
    if tree.get("truncated"):
        raise JieziError("GitHub tree listing was truncated")
    return [{"path": t["path"], "sha": t["sha"], "size": t["size"]} for t in tree["tree"]
            if t["type"] == "blob" and wanted(t["path"])]


def _raw_url(src: Source, path: str) -> str:
    return f"https://raw.githubusercontent.com/{src.repo}/{src.commit}/{urllib.parse.quote(path)}"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "jiezi-knowledge"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def bigrams(text: str) -> list[str]:
    """中文連續字切成雙字；英數字詞保留整個字詞（小寫）。 / Han runs → bigrams; Latin words kept whole."""
    out = []
    for run in re.findall(r"[㐀-鿿]+|[A-Za-z0-9]{2,}", text):
        if run[0].isascii():
            out.append(run.lower())
        elif len(run) == 1:
            continue
        else:
            out += [run[i:i + 2] for i in range(len(run) - 1)]
    return out


def parse_article(text: str) -> tuple[dict, list[tuple[str, str]]]:
    """frontmatter 與依 `## ` 切開的段落。 / Frontmatter and `## ` sections."""
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep and not line.startswith(" "):
                meta[k.strip()] = v.strip().strip("'\"")
    body = re.sub(r"^\[\^[^\]]+\]:.*$", "", body, flags=re.M)        # 註腳定義 / footnote definitions
    body = re.sub(r"\[\^[^\]]+\]", "", body)                           # 註腳標記 / footnote markers
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)\n?(_[^\n]*_\n)?", "", body)  # 圖片與圖說 / images and captions
    body = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", body)              # 連結只留文字 / link text only
    sections, head, buf = [], meta.get("title", ""), []
    for line in body.splitlines():
        if line.startswith("## "):
            if "".join(buf).strip():
                sections.append((head, "\n".join(buf).strip()))
            head, buf = line[3:].strip(), []
        else:
            buf.append(line)
    if "".join(buf).strip():
        sections.append((head, "\n".join(buf).strip()))
    return meta, sections


def build(root: Path, get: Callable = _get, log=print, workers: int = 4) -> dict:
    """依鎖定清單下載（逐檔核對 git blob 雜湊）並建索引；先寫暫存檔。 / Download per lock, verify, index."""
    src = load_manifest(root)
    lock = json.loads((root / "knowledge" / src.lock).read_text(encoding="utf-8"))
    if lock.get("commit") != src.commit:
        raise JieziError(f"lock file is for commit {lock.get('commit')}, manifest pins {src.commit}")
    cache = root / "var" / "knowledge" / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    def one(f):
        p = cache / f"{f['sha']}.md"
        if p.exists() and git_blob_sha(p.read_bytes()) == f["sha"]:
            return f, p
        data = get(_raw_url(src, f["path"]))
        if git_blob_sha(data) != f["sha"]:
            raise JieziError(f"{f['path']}: git blob hash mismatch; the upstream file changed — not using it")
        p.write_bytes(data)
        return f, p

    with ThreadPoolExecutor(max_workers=workers) as ex:  # 少量並行，不給對方太大負擔 / modest concurrency
        files = list(ex.map(one, lock["files"]))
    out = db_path(root)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    n_sections = 0
    try:
        con.executescript("""
            CREATE TABLE articles(id INTEGER PRIMARY KEY, path TEXT, name TEXT, title TEXT, category TEXT,
                                  reviewed INTEGER, url TEXT);
            CREATE TABLE sections(id INTEGER PRIMARY KEY, article INTEGER, heading TEXT, text TEXT);
            CREATE VIRTUAL TABLE grams USING fts5(g, tokenize='unicode61');
            CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);""")
        for aid, (f, p) in enumerate(files, 1):
            # 純簡體字改正體（CC BY-SA 允許改作；使用者：不要有簡體中文）/ Simplified-only chars → Traditional
            meta, sections = parse_article(to_traditional(p.read_text(encoding="utf-8")))
            name = Path(f["path"]).stem
            con.execute("INSERT INTO articles VALUES (?,?,?,?,?,?,?)",
                        (aid, f["path"], name, meta.get("title") or name, meta.get("category", ""),
                         int(meta.get("lastHumanReview", "").lower() == "true"),
                         f"https://github.com/{src.repo}/blob/{src.commit}/{urllib.parse.quote(f['path'])}"))
            for head, text in sections:
                if SKIP_HEADINGS.search(head):  # 只有連結清單的段落不收 / link-list sections are skipped
                    continue
                n_sections += 1
                con.execute("INSERT INTO sections VALUES (?,?,?,?)", (n_sections, aid, head, text))
                con.execute("INSERT INTO grams(rowid, g) VALUES (?,?)",
                            (n_sections, " ".join(bigrams(f"{name} {head} {text}"))))
        con.executemany("INSERT INTO meta VALUES (?,?)", [
            ("source", src.key), ("commit", src.commit), ("license", src.license),
            ("training_use", str(int(src.training_use))), ("attribution", src.attribution),
            ("built", datetime.now().astimezone().isoformat(timespec="seconds"))])
        con.commit()
    finally:
        con.close()
    tmp.replace(out)
    counts = {"articles": len(files), "sections": n_sections}
    log(f"  {counts}")
    return counts


class Knowledge:
    def __init__(self, path: Path):
        if not path.exists():
            raise JieziError(f"{path} not found; run `scripts/jiezi knowledge build`")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.meta = dict(self.con.execute("SELECT k, v FROM meta"))
        self.names = sorted(((n, a) for a, n in self.con.execute("SELECT id, name FROM articles") if len(n) >= 2),
                            key=lambda x: len(x[0]), reverse=True)

    def articles_named(self, text: str) -> list[int]:
        """問題裡出現的文章主題名稱（長的優先）。 / Article names mentioned in the question (longest first)."""
        found = []
        for name, aid in self.names:
            if name in text and not any(name in other for other, _ in found):
                found.append((name, aid))
        return [a for _, a in found[:MAX_SECTIONS]]

    def search(self, text: str, article: int | None = None, limit: int = MAX_SECTIONS) -> list[tuple[int, int]]:
        """回傳 [(section_id, 命中雙字數)]。 / Return [(section id, matched bigram count)]."""
        q = [g for g in dict.fromkeys(bigrams(text[:SCAN_CHARS])) if g not in STOP]
        if not q:
            return []
        expr = " OR ".join('"' + g.replace('"', "") + '"' for g in q)
        sql = ("SELECT grams.rowid, g FROM grams JOIN sections s ON s.id = grams.rowid WHERE grams MATCH ? "
               + ("AND s.article = ? " if article else "") + "ORDER BY bm25(grams) LIMIT 20")
        rows = self.con.execute(sql, (expr, article) if article else (expr,)).fetchall()
        qs = set(q)
        scored = sorted(((sid, len(qs & set(g.split()))) for sid, g in rows), key=lambda x: -x[1])
        if article:
            return scored[:limit]
        # 沒點名文章時更嚴格：命中夠多，且文章名稱或段落標題也要跟問題有共同的字詞，
        # 避免「寫 Python 函式」這類問題配到碰巧提到 Python 的文章
        # Stricter without a named article: enough hits, and the article name or heading must share a term
        out = []
        for sid, n in scored:
            if n < MIN_HITS or n < MIN_COVER * len(qs):
                continue
            name, head = self.con.execute("SELECT a.name, s.heading FROM sections s JOIN articles a "
                                          "ON a.id = s.article WHERE s.id = ?", (sid,)).fetchone()
            if len(qs & set(bigrams(f"{name} {head}"))) >= 2:  # 至少兩個共同雙字 / at least two shared
                out.append((sid, n))
        return out[:limit]

    def section(self, sid: int) -> dict:
        row = self.con.execute("SELECT s.heading, s.text, a.title, a.name, a.url, a.reviewed, a.id FROM sections s "
                               "JOIN articles a ON a.id = s.article WHERE s.id = ?", (sid,)).fetchone()
        return dict(zip(("heading", "text", "title", "name", "url", "reviewed", "article"), row))

    def retrieve(self, text: str) -> list[dict]:
        sids = []
        named = self.articles_named(text)
        for aid in named:
            # 先放文章開頭（30 秒概覽）；問題還有別的字詞時，再加最相關的一段
            # The article's opening (overview) first; plus the best-matching section when the question says more
            first = self.con.execute("SELECT id FROM sections WHERE article = ? ORDER BY id LIMIT 1", (aid,)).fetchone()
            sids += [first[0]] if first else []
            name = self.con.execute("SELECT name FROM articles WHERE id = ?", (aid,)).fetchone()[0]
            rest = set(bigrams(text[:SCAN_CHARS])) - set(bigrams(name)) - STOP
            if rest and len(named) == 1:
                sids += [s for s, n in self.search(text, article=aid, limit=2) if n and s not in sids][:1]
        if not sids:
            sids = [s for s, _ in self.search(text)]
        return [self.section(s) for s in dict.fromkeys(sids)][:MAX_SECTIONS]


def grounding(k: Knowledge, text: str) -> tuple[str, list[dict], bool, str] | None:
    """回傳 (給模型的 system 訊息, 來源清單, 是否可訓練, 附在回答後的出處)；查不到回傳 None。
    Return (system message, sources, trainable, attribution appendix), or None."""
    hits = k.retrieve(text)
    if not hits:
        return None
    blocks, refs, sources = [], [], []
    for h in hits:
        body = h["text"] if len(h["text"]) <= MAX_SECTION_CHARS else h["text"][:MAX_SECTION_CHARS] + "……"
        blocks.append(f"【{h['title']}｜{h['heading']}】\n{body}")
        note = "" if h["reviewed"] else "（未經人工審核）"
        if all(h["url"] not in r for r in refs):
            refs.append(f"- {h['title']}{note}：{h['url']}")
        sources.append({"source": k.meta.get("source"), "article": h["name"], "section": h["heading"]})
    content = ("以下是 Taiwan.md 台灣知識庫的相關段落，可能有錯。請依它用繁體中文回答，段落沒有提到的事不要編造；"
               "不必另外註明出處，系統會在你的回答後附上出處。\n\n" + "\n\n".join(blocks))
    appendix = "\n\n---\n【參考資料】\n" + "\n".join(refs) + "\n" + k.meta.get("attribution", "")
    return content, sources, k.meta.get("training_use") == "1", appendix

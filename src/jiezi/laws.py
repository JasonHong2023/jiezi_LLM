"""全國法規資料庫：法務部「中文法規_法律資料檔」的下載、索引、條文查詢與對話引用（add-laws）。
National law database: download, index, article lookup and chat grounding for the MOJ law data file (add-laws).

來源是政府資料開放平台資料集 18289 的官方分發網址（政府資料開放授權條款第 1 版；法律條文依著作權法第 9 條
不受著作權保護，可訓練）。資料每月更新，清單鎖定一次下載的 SHA-256。只用標準函式庫。
Source: the official distribution of data.gov.tw dataset 18289 (Open Government Data License v1; statutes are
not copyrightable, so trainable). Monthly updates; the manifest pins one download by SHA-256. Standard library only."""

from __future__ import annotations

import re
import sqlite3
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import dictionary
from .errors import JieziError
from .knowledge import ASKING, STOP, bigrams

REQUIRED = ("key", "title", "url", "sha256", "size", "license", "license_url", "training_use", "attribution",
            "license_checked", "data_date")
# 常用簡稱 / common short names
ALIASES = {"刑法": "中華民國刑法", "憲法": "中華民國憲法", "勞基法": "勞動基準法", "個資法": "個人資料保護法",
           "消保法": "消費者保護法", "道交條例": "道路交通管理處罰條例", "道交法": "道路交通管理處罰條例",
           "民訴法": "民事訴訟法", "刑訴法": "刑事訴訟法", "公司法": "公司法", "著作權法": "著作權法",
           "性平法": "性別平等工作法", "家暴法": "家庭暴力防治法", "所得稅法": "所得稅法", "健保法": "全民健康保險法",
           "就服法": "就業服務法", "勞保條例": "勞工保險條例", "勞退條例": "勞工退休金條例", "國賠法": "國家賠償法",
           "行程法": "行政程序法", "政採法": "政府採購法", "公寓大廈條例": "公寓大廈管理條例", "租賃條例": "租賃住宅市場發展及管理條例"}
CN = {c: i for i, c in enumerate("零一二三四五六七八九")} | {"兩": 2, "〇": 0}
ARTICLE = re.compile(r"第\s*([0-9０-９零〇一二兩三四五六七八九十百千]+)(?:\s*-\s*([0-9０-９]+))?\s*條"
                     r"(?:\s*之\s*([0-9０-９一二三四五六七八九十]+))?")
LAW_CUE = re.compile(r"法律|法規|條文|違法|合法|犯法|罰則|罰鍰|罰金|處罰|刑責|判刑|規定|權利|義務|告人|提告|訴訟")
MAX_ARTICLES, MAX_ARTICLE_CHARS, CANDIDATES = 3, 900, 50
DISCLAIMER = "本資料僅供參考，不構成法律意見；條文以全國法規資料庫最新公告為準。"


def _cn_int(s: str) -> int:
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for c in s:
        if c in CN:
            num = CN[c]
        else:
            unit = {"十": 10, "百": 100, "千": 1000}[c]
            total += (num or 1) * unit
            num = 0
    return total + num


def load_manifest(root: Path) -> dict:
    path = root / "laws" / "manifest.toml"
    s = tomllib.loads(path.read_text(encoding="utf-8")).get("source") or {}
    missing = [k for k in REQUIRED if s.get(k) in (None, "")]
    if missing:
        raise JieziError(f"{path}: missing {', '.join(missing)} (R18.3)")
    return s


def db_path(root: Path) -> Path:
    return root / "var" / "laws" / "laws.sqlite"


class _Pinned:
    def __init__(self, s: dict):
        self.key, self.url, self.sha256 = s["key"], s["url"], s["sha256"]


def build(root: Path, download: Callable = dictionary._download, log=print) -> dict:
    src = load_manifest(root)
    cache = root / "var" / "laws" / "cache"
    zpath = dictionary.fetch(_Pinned(src), cache, download)
    xml = zipfile.ZipFile(zpath).read("FalV.xml")
    top = ET.fromstring(xml)  # 官方資料；Python 3.13 的 expat 有實體展開防護 / official data; expat guards expansion
    out = db_path(root)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    n_laws = n_articles = 0
    try:
        con.executescript("""
            CREATE TABLE laws(id INTEGER PRIMARY KEY, name TEXT, url TEXT, category TEXT, abolished INTEGER,
                              updated TEXT);
            CREATE TABLE articles(id INTEGER PRIMARY KEY, law INTEGER, no TEXT, num INTEGER, sub INTEGER,
                                  chapter TEXT, text TEXT);
            CREATE INDEX idx_article ON articles(law, num, sub);
            CREATE VIRTUAL TABLE grams USING fts5(g, tokenize='unicode61');
            CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);""")
        for law in top.findall("法規"):
            n_laws += 1
            name = (law.findtext("法規名稱") or "").strip()
            con.execute("INSERT INTO laws VALUES (?,?,?,?,?,?)",
                        (n_laws, name, (law.findtext("法規網址") or "").strip(), (law.findtext("法規類別") or "").strip(),
                         int(bool((law.findtext("廢止註記") or "").strip())), (law.findtext("最新異動日期") or "").strip()))
            chapter = ""
            for el in law.find("法規內容") if law.find("法規內容") is not None else []:
                if el.tag == "編章節":
                    chapter = " ".join((el.text or "").split())
                    continue
                if el.tag != "條文":
                    continue
                no = " ".join((el.findtext("條號") or "").split())
                m = re.match(r"第\s*(\d+)(?:-(\d+))?\s*條", no)
                text = (el.findtext("條文內容") or "").strip()
                n_articles += 1
                con.execute("INSERT INTO articles VALUES (?,?,?,?,?,?,?)",
                            (n_articles, n_laws, no, int(m.group(1)) if m else None,
                             int(m.group(2)) if m and m.group(2) else 0, chapter, text))
                con.execute("INSERT INTO grams(rowid, g) VALUES (?,?)",
                            (n_articles, " ".join(bigrams(f"{name} {chapter} {text}"))))
        con.executemany("INSERT INTO meta VALUES (?,?)", [
            ("data_date", top.attrib.get("UpdateDate", src["data_date"])), ("attribution", src["attribution"]),
            ("training_use", str(int(bool(src["training_use"])))),
            ("built", datetime.now().astimezone().isoformat(timespec="seconds"))])
        con.commit()
    finally:
        con.close()
    tmp.replace(out)
    counts = {"laws": n_laws, "articles": n_articles}
    log(f"  {counts}")
    return counts


class Laws:
    def __init__(self, path: Path):
        if not path.exists():
            raise JieziError(f"{path} not found; run `scripts/jiezi laws build`")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.meta = dict(self.con.execute("SELECT k, v FROM meta"))
        rows = self.con.execute("SELECT id, name, abolished FROM laws").fetchall()
        self.by_name = {n: i for i, n, ab in rows if not ab}
        self.abolished = {n: i for i, n, ab in rows if ab}
        self._names = sorted(list(self.by_name) + list(ALIASES), key=len, reverse=True)

    def law_in(self, text: str) -> tuple[int, str] | None:
        """問題中提到的現行法律（長的優先，含簡稱）。 / The law named in the question (longest first, aliases)."""
        for n in self._names:
            if n in text:
                name = ALIASES.get(n, n)
                if name in self.by_name:
                    return self.by_name[name], name
        return None

    def article(self, law: int, num: int, sub: int = 0) -> dict | None:
        r = self.con.execute("SELECT a.id, a.no, a.chapter, a.text, l.name, l.url FROM articles a JOIN laws l "
                             "ON l.id = a.law WHERE a.law = ? AND a.num = ? AND a.sub = ?", (law, num, sub)).fetchone()
        return dict(zip(("id", "no", "chapter", "text", "law", "url"), r)) if r else None

    def by_id(self, aid: int) -> dict:
        r = self.con.execute("SELECT a.id, a.no, a.chapter, a.text, l.name, l.url FROM articles a JOIN laws l "
                             "ON l.id = a.law WHERE a.id = ?", (aid,)).fetchone()
        return dict(zip(("id", "no", "chapter", "text", "law", "url"), r))

    def search(self, text: str, law: int | None = None, limit: int = 2, strict: bool = True) -> list[int]:
        q = [g for g in dict.fromkeys(bigrams(ASKING.sub(" ", text[:500]))) if g not in STOP]
        if not q:
            return []
        expr = " OR ".join('"' + g.replace('"', "") + '"' for g in q)
        sql = ("SELECT grams.rowid, g FROM grams JOIN articles a ON a.id = grams.rowid JOIN laws l ON l.id = a.law "
               "WHERE grams MATCH ? AND l.abolished = 0 " + ("AND a.law = ? " if law else "") +
               "ORDER BY bm25(grams) LIMIT ?")
        rows = self.con.execute(sql, (expr, law, CANDIDATES) if law else (expr, CANDIDATES)).fetchall()
        qs = set(q)
        scored = sorted(((aid, len(qs & set(g.split()))) for aid, g in rows), key=lambda x: -x[1])
        if strict:
            scored = [(a, n) for a, n in scored if n >= 3 and n >= 0.5 * len(qs)]
        return [a for a, n in scored[:limit] if n]


def _render(a: dict) -> str:
    text = a["text"] if len(a["text"]) <= MAX_ARTICLE_CHARS else a["text"][:MAX_ARTICLE_CHARS] + "……"
    where = f"（{a['chapter']}）" if a["chapter"] else ""
    return f"【{a['law']} {a['no']}】{where}\n{text}"


def grounding(lw: Laws, text: str) -> tuple[str, list[dict], bool, str] | None:
    text = (text or "")[:2000]
    named = lw.law_in(text)
    hits: list[dict] = []
    notes = []
    if named:
        lid, name = named
        for m in ARTICLE.finditer(text):
            sub = m.group(2) or m.group(3)  # 「第 51-1 條」或「第 51 條之 1」/ either form
            a = lw.article(lid, _cn_int(m.group(1)), _cn_int(sub) if sub else 0)
            if a:
                hits.append(a)
            else:
                notes.append(f"{name}沒有{m.group(0)}（或已刪除）")
        if not hits and not notes:
            hits = [lw.by_id(i) for i in lw.search(text, law=lid, strict=False)]
    elif LAW_CUE.search(text):
        hits = [lw.by_id(i) for i in lw.search(text)]
        for n, _ in sorted(lw.abolished.items(), key=lambda x: -len(x[0])):
            if n in text:
                notes.append(f"《{n}》已廢止")
                break
    hits = list({a["id"]: a for a in hits}.values())[:MAX_ARTICLES]
    if not hits and not notes:
        return None
    body = "\n\n".join([_render(a) for a in hits] + notes)
    links = "\n".join(dict.fromkeys(f"- {a['law']}：{a['url']}" for a in hits))
    content = ("以下是全國法規資料庫的條文原文。請依條文用繁體中文說明，不要自行編造條號或內容，"
               "並提醒使用者這不是法律意見；系統會在回答後附上條文與出處。\n\n" + body)
    appendix = ("\n\n---\n【法規原文】\n" + body + ("\n" + links if links else "") + "\n" +
                lw.meta.get("attribution", "") + f"（資料日期 {lw.meta.get('data_date', '')}）\n" + DISCLAIMER)
    sources = [{"source": "moj-laws", "law": a["law"], "article": a["no"]} for a in hits]
    return content, sources, lw.meta.get("training_use") == "1", appendix

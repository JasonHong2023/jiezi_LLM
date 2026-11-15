"""課綱知識圖譜：tw-taxonomy 的下載、查詢、先修鏈、排課序與對話引用，加上 zetria-org/curriculum 的國高中
各版本課本章節對照（規格 curriculum；add-curriculum D1–D5）。
Curriculum knowledge graph: download, lookup, prerequisite chains, lesson ordering and chat grounding for
tw-taxonomy, plus the zetria-org/curriculum textbook chapter comparison (spec curriculum; design D1–D5).

資料不修改，只讀取。上游附的腳本不執行，排課序由這裡依資料自行計算。只用標準函式庫。
Data is read, never modified. Upstream scripts are not run; ordering is computed here. Standard library only."""

from __future__ import annotations

import heapq
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import dictionary
from .textconv import to_traditional
from .errors import JieziError

REQUIRED = ("key", "title", "publisher", "commit", "license", "license_url", "training_use", "attribution",
            "license_checked")
FILES = ("topics", "dependencies", "curriculum-standards", "clusters")
ROMAN = str.maketrans({"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V", "Ⅵ": "VI"})
# 課綱代碼：N-1-1、n-I-1、Ca-II-1、1-I-1、Bc-III-2，可加科目前綴 math: / Curriculum codes, optional subject prefix
CODE = re.compile(r"(?<![A-Za-z0-9])(?:([a-z][a-z-]*):)?((?:[A-Za-z]{1,3}|\d{1,2})-(?:[IVX]{1,4}|\d)-\d{1,2})(?![0-9])")
CUE = re.compile(r"課綱|學習重點|學習內容|學習表現|先修|先學|先備|前置|國小|小學|年級|學習階段|教學|怎麼教|教案|備課|"
                 r"精熟|評量|檢核|差異化|分級|補救|預習|複習|孩子|小孩|學童|學生|微主題")
OVERVIEW = re.compile(r"學什麼|學哪些|教什麼|教哪些|要學|內容|課程|進度|範圍|單元")
PREREQ = re.compile(r"先修|先學|先備|前置|基礎|之前|打底")
SUBJECTS = {  # 別名 → 正式名稱 / alias → subject name（長的放前面 / longer first）
    "健康與體育": "健康與體育", "自然科學": "自然科學", "綜合活動": "綜合活動", "生活課程": "生活課程",
    "國語文": "國語文", "英語文": "英語文", "閩南語": "本土語文（閩南語文）", "客語": "本土語文（客語文）",
    "原住民族語": "本土語文（原住民族語文）", "閩東語": "本土語文（閩東語文）", "新住民語": "新住民語文",
    "臺灣手語": "臺灣手語", "台灣手語": "臺灣手語", "健體": "健康與體育", "國語": "國語文", "英語": "英語文",
    "英文": "英語文", "數學": "數學", "自然": "自然科學", "社會": "社會", "藝術": "藝術", "綜合": "綜合活動",
    "生活": "生活課程",
}
GRADE = re.compile(r"([一二三四五六1-6])\s*年級|(低|中|高)年級")
CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
STAGE_OF_BAND = {"低": 1, "中": 2, "高": 3}
GRADE_NAME = "一二三四五六"
MAX_TOPICS, MAX_TOPIC_CHARS, MAX_CHAIN, MAX_OVERVIEW = 3, 900, 10, 30
TIER = {"advanced": "進階", "basic": "基本", "foundational": "基礎"}
# 國中、高中的問題不套用國小年級規則（「國中一年級」不是國小一年級）/ secondary-school questions skip primary rules
SECONDARY = re.compile(r"國中|高中|國[一二三]|高[一二三]|[七八九]年級")
# ── 課本章節對照（D5）/ Textbook chapters ──
PUBLISHERS = ("翰林", "康軒", "南一", "龍騰", "泰宇", "三民", "全華")
TB_SUBJECTS = {"地球科學": "地科", "公民": "公民", "地理": "地理", "地科": "地科", "數學": "數學", "歷史": "歷史",
               "理化": "理化", "生物": "生物", "化學": "化學", "物理": "物理"}
TB_CUE = re.compile(r"課本|教科書|版本|章節|單元|目錄|進度|第幾章|哪一章|哪一課|學到|教到|" + "|".join(PUBLISHERS))
VOL = re.compile(r"(?<![0-9])([789])\s*([上下])|國([一二三])\s*([上下])?|([七八九])年級\s*([上下])?|高([一二三123])\s*([上下])?")
MAX_TB_CHARS = 2500


@dataclass(frozen=True)
class Source:
    key: str
    title: str
    commit: str
    license: str
    training_use: bool
    attribution: str
    files: tuple  # ((name, url, sha256), ...)


@dataclass(frozen=True)
class _Pinned:  # dictionary.fetch 需要的欄位 / the fields dictionary.fetch uses
    key: str
    url: str
    sha256: str


@dataclass(frozen=True)
class TextbookSource:
    key: str
    title: str
    license: str
    training_use: bool
    attribution: str
    files: tuple  # ((name, level, subject, url, sha256), ...)


def load_textbook_manifest(root: Path) -> TextbookSource | None:
    path = root / "curriculum" / "manifest.toml"
    t = tomllib.loads(path.read_text(encoding="utf-8")).get("textbooks")
    if not t:
        return None
    missing = [k for k in REQUIRED if t.get(k) in (None, "")]
    missing += [f"textbooks.file {f.get('name') or '?'}" for f in t.get("file") or []
                if not all(f.get(k) for k in ("name", "level", "subject", "url", "sha256"))]
    if missing:
        raise JieziError(f"{path}: missing {', '.join(missing)} (R18.3)")
    return TextbookSource(t["key"], t["title"], t["license"], bool(t["training_use"]), t["attribution"],
                          tuple((f["name"], f["level"], f["subject"], f["url"], f["sha256"]) for f in t["file"]))


def _no_simplified(text: str) -> str:
    """把純簡體字換成正體（MIT 允許修改；使用者：不要有簡體中文）；群 等本身是正體的字不動。
    Replace Simplified-only characters (MIT allows changes; the user wants no Simplified text); 群 stays."""
    return to_traditional(text)


def parse_textbook(text: str, level: str, subject: str) -> list[dict]:
    """`## 科目 7上` / `### 翰林版` / `- 單元` / `  - 小節` → [{level, subject, volume, publisher, units}]。"""
    out, volume, cur = [], None, None
    for line in _no_simplified(text).splitlines():
        if line.startswith("## "):
            volume, cur = line[3:].split()[-1], None
        elif line.startswith("### ") and volume:
            pub = line[4:].strip().replace("版本", "版")
            pub = pub[:-1] + "版" if pub.endswith("板") else pub  # 上游「全華板」/ upstream typo
            cur = {"level": level, "subject": subject, "volume": volume, "publisher": pub, "units": []}
            out.append(cur)
        elif cur is not None and re.match(r"^- ", line):
            cur["units"].append([line[2:].strip(), []])
        elif cur is not None and cur["units"] and re.match(r"^\s+- ", line):
            cur["units"][-1][1].append(line.strip()[2:].strip())
    return out


def load_manifest(root: Path) -> Source:
    path = root / "curriculum" / "manifest.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    s = data.get("source") or {}
    missing = [k for k in REQUIRED if s.get(k) in (None, "")]
    files = {f.get("name"): f for f in data.get("file") or []}
    missing += [f"file {n}" for n in FILES if not (files.get(n) or {}).get("sha256") or not files[n].get("url")]
    if missing:
        raise JieziError(f"{path}: missing {', '.join(missing)} (R18.3)")
    return Source(s["key"], s["title"], s["commit"], s["license"], bool(s["training_use"]), s["attribution"],
                  tuple((n, files[n]["url"], files[n]["sha256"]) for n in FILES))


def cache_dir(root: Path) -> Path:
    return root / "var" / "curriculum"


def _paths(src: Source, cache: Path) -> dict[str, Path]:
    return {n: cache / f"{src.key}-{n}-{sha[:12]}.json" for n, _url, sha in src.files}


def _tb_paths(src: TextbookSource, cache: Path) -> dict[str, Path]:
    return {n: cache / f"{src.key}-{n}-{sha[:12]}.md" for n, _lv, _s, _url, sha in src.files}


def build(root: Path, download: Callable = dictionary._download, log=print) -> dict:
    """下載四個檔並核對 SHA-256，再載入一次確認資料完整。 / Fetch, verify, then load once as a check."""
    src = load_manifest(root)
    cache = cache_dir(root)
    for name, url, sha in src.files:
        got = dictionary.fetch(_Pinned(f"{src.key}-{name}", url, sha), cache, download)
        log(f"  {name}: {got.name}")
    tsrc = load_textbook_manifest(root)
    for name, _lv, _s, url, sha in (tsrc.files if tsrc else ()):
        got = dictionary.fetch(_Pinned(f"{tsrc.key}-{name}", url, sha), cache, download)
        log(f"  {name}: {got.name}")
    g = Graph.load(root)
    counts = {"topics": len(g.topics), "dependencies": g.edge_count, "standards": len(g.standards),
              "clusters": len(g.clusters), "textbook_volumes": len(g.textbooks)}
    log(f"  {counts}")
    return counts


class Graph:
    def __init__(self, src: Source, topics: list, deps: list, standards: dict, subjects: dict, clusters: list,
                 textbooks: list | None = None, tsrc: TextbookSource | None = None):
        self.src, self.tsrc = src, tsrc
        self.textbooks = textbooks or []    # 每冊每版本一筆 / one per volume and publisher
        self.unit_index: dict[str, list[int]] = {}  # 單元或小節名稱 → textbooks 索引 / title → indexes
        for i, tb in enumerate(self.textbooks):
            for unit, sections in tb["units"]:
                for title in [unit, *sections]:
                    if len(title) >= 3 and i not in self.unit_index.setdefault(title, []):
                        self.unit_index[title].append(i)
        self._units_by_len = sorted(self.unit_index, key=len, reverse=True)
        self.topics = {t["id"]: t for t in topics}
        self.order = {t["id"]: i for i, t in enumerate(topics)}
        self.by_name = {t["name"]: t["id"] for t in topics}
        self.prereq: dict[str, list[tuple[str, str]]] = {i: [] for i in self.topics}
        self.after: dict[str, list[str]] = {i: [] for i in self.topics}
        self.edge_reason: dict[tuple[str, str], str] = {}
        for d in deps:
            a, b = d["topicId"], d["prerequisiteId"]
            if a not in self.topics or b not in self.topics:
                raise JieziError(f"dependency refers to an unknown topic: {b} → {a}")
            self.prereq[a].append((b, d.get("strength") or "hard"))
            self.after[b].append(a)
            self.edge_reason[(a, b)] = d.get("reason") or ""
        self.edge_count = len(deps)
        self.standards = standards          # key → entry（含 subject）/ key → entry (with subject)
        self.subjects = subjects            # slug → name
        self.clusters = clusters
        self.by_code: dict[str, list[str]] = {}
        for t in topics:
            for c in t.get("contentCodes", []) + t.get("performanceCodes", []):
                self.by_code.setdefault(c, []).append(t["id"])
        self._names_by_len = sorted(self.by_name, key=len, reverse=True)
        self.topo = self._toposort(list(self.topics))  # 有環會丟錯 / raises on a cycle

    @classmethod
    def load(cls, root: Path) -> "Graph":
        src = load_manifest(root)
        paths = _paths(src, cache_dir(root))
        missing = [str(p) for p in paths.values() if not p.exists()]
        if missing:
            raise JieziError(f"{missing[0]} not found; run `scripts/jiezi curriculum build`")
        data = {n: json.loads(p.read_text(encoding="utf-8")) for n, p in paths.items()}
        standards, subjects = {}, {}
        for s in data["curriculum-standards"]["subjects"]:
            subjects[s["slug"]] = s["name"]
            for e in s["entries"]:
                standards[e["key"]] = {**e, "subject": s["name"]}
        tsrc, textbooks = load_textbook_manifest(root), []
        if tsrc:
            tpaths = _tb_paths(tsrc, cache_dir(root))
            gone = [str(p) for p in tpaths.values() if not p.exists()]
            if gone:
                raise JieziError(f"{gone[0]} not found; run `scripts/jiezi curriculum build`")
            for name, level, subject, _url, _sha in tsrc.files:
                textbooks += parse_textbook(tpaths[name].read_text(encoding="utf-8"), level, subject)
        return cls(src, data["topics"]["topics"], data["dependencies"]["dependencies"], standards, subjects,
                   data["clusters"]["clusters"], textbooks, tsrc)

    # ── 查詢 / Lookup ──
    def find(self, query: str) -> list[str]:
        """名稱、id 或課綱代碼 → 微主題 id。 / Name, id or curriculum code → topic ids."""
        q = query.strip().translate(ROMAN)
        if q in self.topics:
            return [q]
        if q in self.by_name:
            return [self.by_name[q]]
        hits = []
        for key in self.codes(q):
            hits += [i for i in self.by_code.get(key, []) if i not in hits]
        if hits:
            return hits
        return [self.by_name[n] for n in self.by_name if q and q in n]

    def codes(self, text: str) -> list[str]:
        """文字中的課綱代碼 → 存在的完整鍵（沒寫科目就比對所有科目）。 / Codes in text → existing keys."""
        out = []
        for slug, code in CODE.findall(text.translate(ROMAN)):
            keys = [f"{slug}:{code}"] if slug else [f"{s}:{code}" for s in self.subjects]
            out += [k for k in keys if k in self.standards and k not in out]
        return out

    def ancestors(self, tid: str, hard_only: bool = False) -> list[str]:
        """所有先修（依學習順序）。 / Every prerequisite, in learning order."""
        seen, stack = set(), [tid]
        while stack:
            for p, strength in self.prereq[stack.pop()]:
                if p not in seen and (strength == "hard" or not hard_only):
                    seen.add(p)
                    stack.append(p)
        return self._toposort(list(seen))

    def _toposort(self, ids: list[str]) -> list[str]:
        """Kahn；同時可學的依年級、中心性高者、原檔順序。 / Kahn's; ties by grade, centrality, file order."""
        sub = set(ids)
        indeg = {i: sum(1 for p, _ in self.prereq[i] if p in sub) for i in sub}
        key = lambda i: (self.topics[i].get("gradeStart") or 0, -(self.topics[i].get("centrality") or 0),  # noqa: E731
                         self.order[i], i)
        heap = [key(i) for i in sub if indeg[i] == 0]
        heapq.heapify(heap)
        out = []
        while heap:
            i = heapq.heappop(heap)[-1]
            out.append(i)
            for n in self.after[i]:
                if n in indeg:
                    indeg[n] -= 1
                    if indeg[n] == 0:
                        heapq.heappush(heap, key(n))
        if len(out) != len(sub):
            raise JieziError("tw-taxonomy dependencies contain a cycle")
        return out

    def plan(self, subject: str, grade: int | None = None, stage: int | None = None) -> list[str]:
        """某科某年級（或學習階段）的教學序列。 / Teaching order for a subject and grade (or stage)."""
        name = SUBJECTS.get(subject, subject)
        ids = [i for i, t in self.topics.items() if t["subject"] == name
               and (grade is None or (t.get("gradeStart") or 0) <= grade <= (t.get("gradeEnd") or 0))
               and (stage is None or t.get("stage") == stage)]
        return self._toposort(ids)

    # ── 呈現 / Rendering ──
    def grade_text(self, t: dict) -> str:
        a, b = t.get("gradeStart"), t.get("gradeEnd")
        if not a:
            return f"第{t.get('stage')}學習階段"
        return f"{GRADE_NAME[a - 1]}年級" if a == b else f"{GRADE_NAME[a - 1]}到{GRADE_NAME[b - 1]}年級"

    def names(self, ids: list[str]) -> str:
        return "、".join(self.topics[i]["name"] for i in ids)

    def render(self, tid: str, chain: bool = False, shown: frozenset = frozenset()) -> str:
        """shown：上面已列出原文的課綱代碼，只寫代碼不重複條文。 / Codes already shown are listed without text."""
        t = self.topics[tid]
        hard = [p for p, s in self.prereq[tid] if s == "hard"]
        soft = [p for p, s in self.prereq[tid] if s != "hard"]
        lines = [f"【微主題】{t['name']}（{t['subject']}／{t['domain']}，{self.grade_text(t)}）",
                 f"說明：{t.get('description', '')}"]
        if t.get("evidence"):
            lines.append("精熟證據：" + "；".join(t["evidence"]))
        if hard or soft:
            lines.append("先修：" + (self.names(hard) or "（無）") + (f"（建議先會：{self.names(soft)}）" if soft else ""))
        if chain:
            anc = self.ancestors(tid)
            if anc:
                more = f"……共 {len(anc)} 項" if len(anc) > MAX_CHAIN else ""
                lines.append("完整先修鏈（由淺到深）：" + self.names(anc[-MAX_CHAIN:]) + more)
        if self.after[tid]:
            lines.append("後續銜接：" + self.names(self.after[tid][:5]))
        codes = t.get("contentCodes", []) + t.get("performanceCodes", [])
        if any(c in shown for c in codes):
            lines.append("課綱（條文見上）：" + "、".join(c for c in codes if c in shown))
        for c in codes:
            e = self.standards.get(c)
            if e and c not in shown:
                lines.append(f"課綱 {c}（{'學習內容' if e['kind'] == 'content' else '學習表現'}）：{e['text']}")
        tasks = t.get("differentiatedTasks") or {}
        if tasks:
            lines.append("分級任務：" + "／".join(f"{TIER.get(k, k)}：{v}" for k, v in tasks.items()))
        if t.get("assessmentPrompt"):
            lines.append("家長檢核：" + t["assessmentPrompt"].replace("{{name}}", "孩子"))
        text = "\n".join(lines)
        return text if len(text) <= MAX_TOPIC_CHARS else text[:MAX_TOPIC_CHARS] + "……"

    def render_standard(self, key: str) -> str:
        e = self.standards[key]
        kind = "學習內容" if e["kind"] == "content" else "學習表現"
        mapped = self.by_code.get(key, [])
        tail = f"\n對應微主題：{self.names(mapped)}" if mapped else ""
        return f"【課綱 {key}】{e['subject']}，{kind}（{e.get('category') or ''}，第{e.get('stage')}學習階段）：{e['text']}{tail}"

    def overview(self, subject: str, grade: int | None, stage: int | None) -> str:
        if grade and not stage:
            stage = (grade + 1) // 2
        name = SUBJECTS.get(subject, subject)
        parts = [c["summary"] for c in self.clusters if c["subject"] == name and c.get("stage") == stage]
        ids = self.plan(name, grade=grade, stage=None if grade else stage)
        head = f"【{name}，{f'{GRADE_NAME[grade - 1]}年級' if grade else f'第{stage}學習階段'}】"
        more = f"……共 {len(ids)} 個" if len(ids) > MAX_OVERVIEW else ""
        lines = [head + "依先修關係排序的微主題：" + self.names(ids[:MAX_OVERVIEW]) + more] if ids else [head]
        lines += [f"領域摘要：{p}" for p in parts]
        return "\n".join(lines)

    # ── 課本 / Textbooks ──
    def render_textbook(self, tb: dict) -> str:
        units = "；".join(f"{n}. {u}" + (f"（{'、'.join(secs)}）" if secs else "")
                         for n, (u, secs) in enumerate(tb["units"], 1))
        return f"【課本】{tb['level']}{tb['subject']} {tb['volume']} {tb['publisher']}：{units}"

    def textbook_query(self, text: str) -> list[int]:
        """科目＋冊別（＋版本）→ textbooks 索引。 / Subject + volume (+ publisher) → indexes."""
        subject = next((TB_SUBJECTS[a] for a in TB_SUBJECTS if a in text), None)
        vols = _volumes(text)
        if not subject or not vols:
            return []
        pubs = [p for p in PUBLISHERS if p in text]
        return [i for i, tb in enumerate(self.textbooks) if tb["subject"] == subject and tb["volume"] in vols
                and (not pubs or any(tb["publisher"].startswith(p) for p in pubs))]

    def units_in(self, text: str) -> list[str]:
        found, taken = [], []
        for title in self._units_by_len:
            for m in re.finditer(re.escape(title), text):
                span = set(range(m.start(), m.end()))
                if not any(span & t for t in taken):
                    taken.append(span)
                    if title not in found:
                        found.append(title)
            if len(found) >= MAX_TOPICS:
                break
        return found[:MAX_TOPICS]

    def where_unit(self, title: str) -> str:
        locs = []
        for i in self.unit_index[title]:
            tb = self.textbooks[i]
            n, unit = next((n, u) for n, (u, secs) in enumerate(tb["units"], 1) if title == u or title in secs)
            locs.append(f"{tb['level']}{tb['subject']} {tb['volume']} {tb['publisher']} 第{n}單元「{unit}」")
        return f"【課本位置】「{title}」：" + "；".join(locs)

    # ── 對話 / Chat ──
    def topics_in(self, text: str) -> list[str]:
        """文字中出現的微主題名稱（長的優先、不重疊）。 / Topic names in text (longest first, no overlap)."""
        found, taken = [], []
        for n in self._names_by_len:
            for m in re.finditer(re.escape(n), text):
                span = range(m.start(), m.end())
                if not any(set(span) & set(r) for r in taken):
                    taken.append(span)
                    if self.by_name[n] not in found:
                        found.append(self.by_name[n])
            if len(found) >= MAX_TOPICS:
                break
        return found[:MAX_TOPICS]


def _subject_grade(text: str) -> tuple[str | None, int | None, int | None]:
    subject = next((SUBJECTS[a] for a in SUBJECTS if a in text), None)
    m = GRADE.search(text)
    grade = stage = None
    if m and m.group(1):
        grade = CN.get(m.group(1)) or int(m.group(1))
    elif m:
        stage = STAGE_OF_BAND[m.group(2)]
    return subject, grade, stage


def _volumes(text: str) -> list[str]:
    """「7上」「國一上」「八年級」「高一上」→ 冊別清單。 / Volume names mentioned in text."""
    out = []
    text = re.sub(r"國中\s*([一二三])\s*年級", r"國\1", text)  # 國中一年級 = 國一 / junior-high grade 1
    for m in VOL.finditer(text):
        a, b, c, d, e, f, h, i = m.groups()
        if a:
            grade, sem = a, b
        elif c:
            grade, sem = str(6 + CN[c]), d
        elif e:
            grade, sem = str("七八九".index(e) + 7), f
        else:
            grade, sem = "高" + str(CN.get(h) or h), i
        out += [grade + s for s in ([sem] if sem else ["上", "下"]) if grade + s not in out]
    return out


def textbook_blocks(g: Graph, text: str) -> tuple[list[str], list[dict]]:
    if not g.textbooks or not TB_CUE.search(text):
        return [], []
    blocks, sources, used = [], [], 0
    for i in g.textbook_query(text):
        b = g.render_textbook(g.textbooks[i])
        if used + len(b) > MAX_TB_CHARS:
            blocks.append("……（其餘版本省略，請指定版本）")
            break
        blocks.append(b)
        used += len(b)
        tb = g.textbooks[i]
        sources.append({"source": g.tsrc.key, "volume": f"{tb['level']}{tb['subject']} {tb['volume']}",
                        "publisher": tb["publisher"]})
    if not blocks:
        for title in g.units_in(text):
            blocks.append(g.where_unit(title))
            sources.append({"source": g.tsrc.key, "unit": title})
    return blocks, sources


def grounding(g: Graph, text: str) -> tuple[str, list[dict], bool, str] | None:
    """回傳 (給模型的 system 訊息, 來源清單, 是否可訓練, 附在回答後的原文)；不需要查時回傳 None。
    Return (system message, sources, trainable, verbatim appendix), or None when no lookup is needed."""
    text = text[:2000]
    blocks, sources = [], []
    codes = g.codes(text)
    for key in codes[:MAX_TOPICS]:
        blocks.append(g.render_standard(key))
        sources.append({"source": g.src.key, "code": key})
    secondary = bool(SECONDARY.search(text))
    has_cue = bool(CUE.search(text)) and not secondary
    if has_cue or codes:
        chain = bool(PREREQ.search(text))
        tids = g.topics_in(text)
        for key in codes:
            tids += [i for i in g.by_code.get(key, []) if i not in tids]
        for tid in tids[:MAX_TOPICS]:
            blocks.append(g.render(tid, chain=chain, shown=frozenset(codes[:MAX_TOPICS])))
            sources.append({"source": g.src.key, "topic": g.topics[tid]["name"]})
        if not tids and has_cue and OVERVIEW.search(text):
            subject, grade, stage = _subject_grade(text)
            if subject and (grade or stage):
                blocks.append(g.overview(subject, grade, stage))
                sources.append({"source": g.src.key, "subject": subject, "grade": grade, "stage": stage})
    trainable = g.src.training_use
    attributions = [g.src.attribution] if blocks else []
    tb_blocks, tb_sources = textbook_blocks(g, text)
    if tb_blocks:
        blocks += tb_blocks
        sources += tb_sources
        attributions.append(g.tsrc.attribution)
        trainable = trainable and g.tsrc.training_use
    if not blocks:
        return None
    body = "\n\n".join(blocks)
    content = ("以下是 108 課綱的課綱知識圖譜與課本章節資料。請依它用繁體中文回答，不要自行編造課綱代碼、先修關係或"
               "課本章節；不必另外註明出處，系統會在你的回答後附上原文與出處。\n\n" + body)
    appendix = "\n\n---\n【課綱資料原文】\n" + body + "\n" + "\n".join(attributions)
    return content, sources, trainable, appendix

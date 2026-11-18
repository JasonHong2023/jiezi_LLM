"""芥子的記憶：Hermes llm-wiki 格式的 Markdown wiki（add-memory；使用者 2026-11-15「不只是請教他要會記憶」、
「記憶模組可以用 HERMES 的 WIKI 方式嗎?」）。
Jiezi's memory as a Markdown wiki in the Hermes llm-wiki format.

Markdown 頁面是正本，可以用 Obsidian 或 Hermes dashboard（WIKI_PATH 指到這裡）瀏覽、修改、刪除；SQLite 只是
搜尋索引，頁面有變動就自動重建。位置 `var/memory/wiki/`（只在本機、不進版控；使用者選擇不放進會公開備份的 ~/wiki）。
Pages are the source of truth (browse or edit them in Obsidian or the Hermes dashboard); SQLite is only a search
index rebuilt when pages change. Lives under var/ (local only).

版面 / Layout：
- `topics/<主題>.md`：依主題合併（Karpathy 式）。「## 問答」放請教 Claude／雲端得到的答案，「## 使用者更正」放你的
  更正，「## 相關」放 [[連結]]。新問題依文字相似度歸到既有主題，不靠 0.6B 改寫。
- `notes/使用者要我記住的事.md`：「記住：…」的內容，每次對話都附上。
- `index.md`、`log.md`：目錄與操作紀錄（與 Hermes wiki 相同的表格格式）。
Claude／雲端的答案只用來「查」，頁面標 `training_use: false`（Anthropic 條款限制用輸出訓練模型），自我進化必須排除。
Answers from Claude or the cloud are lookup-only and marked training_use: false."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .knowledge import ASKING, bigrams
from .textconv import to_traditional

# 問芥子自己 / about jiezi itself
SELF = re.compile(r"自我介紹|你是誰|你叫什麼|你的名字|你在哪|你會哪些|你會那些|你能做什麼|誰做的你|你的作者|"
                  r"你是芥子|芥子(?:的作者|是誰做|是什麼模型|這個名字|的名字)")
# 創作類請求：每次都該重新創作，不存也不拿記憶裡的舊答案（2026-11-18：「說一個笑話」每次都回同一則）
# Creative requests: never stored or answered from memory (a joke kept coming back verbatim)
CREATIVE = re.compile(r"笑話|講個?故事|說個?故事|編一?個|寫一?(?:首|篇|段|則)?(?:詩|歌詞|故事|小說|散文|對聯|笑話)|"
                      r"作一?首詩|繞口令|謎語|腦筋急轉彎|順口溜|藏頭詩|打油詩")
# 要上網、即時或網頁內容 / needs the web or live data
WEB = re.compile(r"https?://|網路上|上網|網頁|網站|新聞|今天|今日|昨天|明天|現在幾點|最新|即時|天氣|股價|匯率|目前")
# 依賴前文的追問 / follow-ups that depend on earlier turns
CONTEXTUAL = re.compile(r"^(那|它|他|她|這個|那個|上面|剛才|剛剛|還有呢|然後呢|為什麼呢|繼續)|它的|他的|她的|上一題|剛才")
REMEMBER = re.compile(r"^\s*(?:請|幫我)?(?:記住|記得|記下)(?:一下)?\s*[：:，,]?\s*(.+)$", re.S)
CORRECTION = re.compile(r"^\s*(?:不對|錯了|你錯了|不是這樣|更正)\s*[，,。：:！!]?\s*(.+)$", re.S)
EXACT, RELATED, TOPIC = 0.85, 0.35, 0.6  # 直接回答、當參考、歸到同一主題 / serve, reference, same topic
ANSWER_DAYS = 180
MAX_NOTES_IN_PROMPT, MAX_NOTE_CHARS, MAX_ANSWER_CHARS = 20, 300, 2000
NOTES_PAGE = "notes/使用者要我記住的事.md"


def normalize(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", to_traditional(text or "")).lower()


def _grams(text: str) -> set[str]:
    return set(bigrams(to_traditional(text or "")))


def _core(text: str) -> str:
    """去掉提問用語後的內容。 / The content left after dropping question wording."""
    return ASKING.sub(" ", to_traditional(text or ""))


def similarity(a: str, b: str) -> float:
    """去掉提問用語後比較雙字的 Jaccard。 / Bigram Jaccard after dropping question wording."""
    if normalize(a) == normalize(b) or (normalize(_core(a)) and normalize(_core(a)) == normalize(_core(b))):
        return 1.0
    ga, gb = _grams(_core(a)) or _grams(a), _grams(_core(b)) or _grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def storable(question: str, earlier_user_turns: int = 0) -> str | None:
    """不存的原因；可以存回傳 None。 / Why a question is not stored, or None."""
    q = (question or "").strip()
    if len(_grams(q)) < 2:
        return "too_short"
    if SELF.search(q):
        return "about_jiezi"
    if CREATIVE.search(q):
        return "creative"
    if WEB.search(q):
        return "web_or_live"
    if earlier_user_turns and (CONTEXTUAL.search(q) or len(q) < 8):
        return "depends_on_context"
    return None


def topic_title(question: str) -> str:
    t = " ".join(_core(question).split())
    return (t or question.strip())[:30]


def safe_name(title: str) -> str:
    """與 Hermes llm-wiki 相同的檔名規則。 / Same filename rule as the Hermes llm-wiki."""
    s = re.sub(r"[-\s]+", "_", re.sub(r"[^\w\s一-鿿㐀-䶿-]", "", title).strip())[:80]
    return s or "untitled"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="minutes")


@dataclass
class Entry:
    page: str       # 相對路徑 / relative path
    title: str
    kind: str       # qa | correction | note
    question: str
    text: str
    at: str
    provider: str = ""


# ── 頁面讀寫 / Page I/O ──
_ENTRY = re.compile(r"^### (.+?)\n- 日期：([^\s｜]+)(?:｜來源：(.+?))?\n\n(.*?)(?=^### |^## |\Z)", re.S | re.M)


def _sections(body: str) -> dict[str, str]:
    out, cur = {}, None
    for line in body.splitlines(keepends=True):
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = ""
        elif cur:
            out[cur] += line
    return out


def parse_page(text: str) -> tuple[dict, dict[str, str]]:
    meta, body = {}, text
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    if m:
        body = text[m.end():]
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep:
                meta[k.strip()] = v.strip()
    return meta, _sections(body)


def _entries(section: str) -> list[tuple[str, str, str, str]]:
    return [(q.strip(), at, (src or "").strip(), txt.strip()) for q, at, src, txt in _ENTRY.findall(section)]


def render_page(title: str, created: str, qa: list, corrections: list, related: list[str], tags: list[str]) -> str:
    fm = ["---", f"title: {title}", "type: concept", f"created: {created}", f"updated: {_now()}",
          f"tags: [{', '.join(tags)}]", "confidence: medium", "training_use: false", "---", "", f"# {title}", ""]
    parts = ["## 問答", ""]
    for q, at, src, txt in qa:
        parts += [f"### {q}", f"- 日期：{at}" + (f"｜來源：{src}" if src else ""), "", txt, ""]
    if corrections:
        parts += ["## 使用者更正", ""]
        for q, at, _src, txt in corrections:
            parts += [f"### {q}", f"- 日期：{at}", "", txt, ""]
    if related:
        parts += ["## 相關", ""] + [f"- [[{r}]]" for r in related] + [""]
    return "\n".join(fm + parts)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class Memory:
    def __init__(self, wiki: Path):
        self.wiki = wiki
        for d in ("topics", "notes"):
            (wiki / d).mkdir(parents=True, exist_ok=True)
        if not (wiki / "index.md").exists():
            _atomic_write(wiki / "index.md", "# 芥子記憶 Index\n")
        if not (wiki / "log.md").exists():
            _atomic_write(wiki / "log.md", "# Wiki Log\n\nChronological record of all wiki actions. Append-only.\n\n"
                                           "| Date | Action | Subject | Details |\n|------|--------|---------|---------|\n")
        self._stamp: tuple | None = None
        self.entries: list[Entry] = []
        self.titles: dict[str, str] = {}  # title → page

    # ── 索引（頁面變動就重建）/ Index, rebuilt when pages change ──
    def _scan(self) -> None:
        files = sorted(self.wiki.glob("topics/*.md")) + sorted(self.wiki.glob("notes/*.md"))
        stamp = tuple((str(f), f.stat().st_mtime_ns) for f in files)
        if stamp == self._stamp:
            return
        entries, titles = [], {}
        for f in files:
            rel = f.relative_to(self.wiki).as_posix()
            meta, secs = parse_page(f.read_text(encoding="utf-8"))
            title = meta.get("title") or f.stem
            if rel == NOTES_PAGE:
                for line in secs.get("筆記", "").splitlines():
                    m = re.match(r"^- (\S+)：(.+)$", line.strip())
                    if m:
                        entries.append(Entry(rel, title, "note", "", m.group(2), m.group(1)))
                continue
            titles[title] = rel
            for q, at, src, txt in _entries(secs.get("問答", "")):
                entries.append(Entry(rel, title, "qa", q, txt, at, src))
            for q, at, src, txt in _entries(secs.get("使用者更正", "")):
                entries.append(Entry(rel, title, "correction", q, txt, at, src))
        self.entries, self.titles, self._stamp = entries, titles, stamp

    def _log(self, action: str, subject: str, details: str) -> None:
        with (self.wiki / "log.md").open("a", encoding="utf-8") as fh:
            fh.write(f"| {_now()[:16]} | {action} | {subject} | {details.replace('|', '｜')} |\n")

    def _index(self) -> None:
        self._scan()
        lines = ["# 芥子記憶 Index", "", "## 主題", ""] + [f"- [[{t}]]" for t in sorted(self.titles)]
        lines += ["", "## 筆記", "", "- [[使用者要我記住的事]]", ""]
        _atomic_write(self.wiki / "index.md", "\n".join(lines))

    # ── 主題歸類 / Topic assignment ──
    def topic_for(self, question: str) -> str | None:
        """既有主題頁：標題幾乎都出現在問題裡，或已有很像的問題。 / An existing topic page for the question."""
        self._scan()
        q = _grams(question)
        best, score = None, 0.0
        for title, page in self.titles.items():
            tg = _grams(title)
            cover = len(tg & q) / len(tg) if tg else 0.0
            if normalize(title) and normalize(title) in normalize(question):
                cover = 1.0
            if cover >= TOPIC and cover > score:
                best, score = page, cover
        for e in self.entries:
            if e.kind != "note" and similarity(question, e.question) >= RELATED and score < 1.0:
                return e.page
        return best

    def _write_entry(self, question: str, text: str, kind: str, source: str) -> str:
        page = self.topic_for(question)
        if page is None:
            title = topic_title(question)
            page = f"topics/{safe_name(title)}.md"
            n = 1
            while (self.wiki / page).exists():
                n += 1
                page = f"topics/{safe_name(title)}_{n}.md"
            meta, secs, created = {"title": title}, {}, _now()
        else:
            meta, secs = parse_page((self.wiki / page).read_text(encoding="utf-8"))
            created = meta.get("created") or _now()
        title = meta.get("title") or Path(page).stem
        qa, corr = _entries(secs.get("問答", "")), _entries(secs.get("使用者更正", ""))
        # 內文的 Markdown 標題改成粗體，避免打亂頁面結構 / headings in the text become bold so sections stay intact
        text = re.sub(r"^#{1,6}\s+(.+)$", r"**\1**", text.strip(), flags=re.M)
        new = (question.strip(), _now(), source, text)
        if kind == "qa":  # 同一題只留最新的 / keep only the newest answer to the same question
            qa = [e for e in qa if normalize(e[0]) != normalize(question)] + [new]
        else:
            corr = [e for e in corr if normalize(e[0]) != normalize(question)] + [new]
        self._scan()
        others = [t for t in self.titles if t != title]
        related = sorted({r.strip("[]") for r in re.findall(r"^- \[\[(.+?)\]\]", secs.get("相關", ""), re.M)} |
                         {t for t in others if t in text or t in question})
        tags = ["jiezi-memory", "correction" if corr else "consult"]
        _atomic_write(self.wiki / page, render_page(title, created, qa, corr, related, tags))
        self._log("remember" if kind == "qa" else "correct", Path(page).name,
                  f"question={question.strip()[:60]}; source={source or 'user'}")
        self._index()
        return page

    # ── 寫入 / Write ──
    def save_answer(self, question: str, answer: str, provider: str, model: str | None) -> str | None:
        if not answer or not answer.strip():
            return None
        who = "Claude" if provider == "claude" else "雲端"
        return self._write_entry(question, answer, "qa", f"{who}（{model}）" if model else who)

    def save_correction(self, question: str, text: str) -> str:
        return self._write_entry(question, text, "correction", "使用者")

    def save_note(self, text: str) -> None:
        path = self.wiki / NOTES_PAGE
        meta, secs = parse_page(path.read_text(encoding="utf-8")) if path.exists() else ({}, {})
        lines = [ln for ln in secs.get("筆記", "").splitlines() if ln.strip().startswith("- ")]
        lines.append(f"- {_now()[:10]}：{' '.join(text.split())[:MAX_NOTE_CHARS]}")
        fm = ["---", "title: 使用者要我記住的事", "type: general", f"created: {meta.get('created') or _now()}",
              f"updated: {_now()}", "tags: [jiezi-memory, notes]", "confidence: high", "---", "",
              "# 使用者要我記住的事", "", "> 每次對話都會附上這一頁。可以直接修改或刪除條目。", "", "## 筆記", ""]
        _atomic_write(path, "\n".join(fm + lines) + "\n")
        self._log("note", "使用者要我記住的事.md", text[:60])
        self._index()

    def forget(self, title: str) -> bool:
        self._scan()
        page = self.titles.get(title)
        if not page:
            return False
        (self.wiki / page).unlink()
        self._log("delete", Path(page).name, "reason=使用者要求忘記")
        self._index()
        return True

    # ── 查詢 / Read ──
    def find_answer(self, question: str) -> tuple[Entry, float] | None:
        self._scan()
        cutoff = (datetime.now().astimezone() - timedelta(days=ANSWER_DAYS)).isoformat()
        best = None
        for e in self.entries:
            if e.kind == "qa" and e.at >= cutoff[:16]:
                sim = similarity(question, e.question)
                if best is None or sim > best[1]:
                    best = (e, sim)
        return best if best and best[1] >= RELATED else None

    def corrections_for(self, question: str) -> list[Entry]:
        self._scan()
        return [e for e in self.entries if e.kind == "correction" and similarity(question, e.question) >= RELATED][:3]

    def notes(self) -> list[Entry]:
        self._scan()
        return [e for e in self.entries if e.kind == "note"]

    def topics(self) -> dict[str, str]:
        self._scan()
        return dict(self.titles)


def wiki_path(root: Path) -> Path:
    return root / "var" / "memory" / "wiki"


def notes_prompt(m: Memory) -> str | None:
    """每次對話附上的「使用者要你記住的事」。 / The remember-notes attached to every chat."""
    notes = m.notes()[-MAX_NOTES_IN_PROMPT:]
    if not notes:
        return None
    return "使用者先前要你記住的事（回答時要遵守、參考）：\n" + "\n".join(f"- {n.text}" for n in notes)


def recall_block(question: str, m: Memory) -> tuple[str, list[dict], bool, str] | None:
    """類似問題的記憶（更正優先，再來是先前請教的答案）→ (system 訊息, 來源, 可訓練, 附錄)。
    Corrections first, then earlier answers → (system message, sources, trainable, appendix)."""
    blocks, sources, trainable, notes = [], [], True, []
    for c in m.corrections_for(question):
        blocks.append(f"【使用者更正（{c.at[:10]}）】問題：{c.question}\n正確說法：{c.text}")
        sources.append({"source": "memory", "page": c.title, "kind": "correction"})
        notes.append(f"- 依你 {c.at[:10]} 的更正（[[{c.title}]]）")
    found = m.find_answer(question)
    if found:
        a, sim = found
        text = a.text if len(a.text) <= MAX_ANSWER_CHARS else a.text[:MAX_ANSWER_CHARS] + "……"
        blocks.append(f"【先前請教的答案（{a.at[:10]}，{a.provider}）】問題：{a.question}\n{text}")
        sources.append({"source": "memory", "page": a.title, "kind": "answer", "similarity": round(sim, 2)})
        notes.append(f"- 參考 {a.at[:10]} 請教{a.provider}的答案（[[{a.title}]]）")
        trainable = False  # 含 Claude／雲端的輸出 / contains Claude or cloud output
    if not blocks:
        return None
    content = ("以下是你的記憶：使用者的更正最優先，其次是先前請教得到的答案。請依它用繁體中文回答，不要編造。\n\n"
               + "\n\n".join(blocks))
    return content, sources, trainable, "\n\n---\n【記憶】\n" + "\n".join(notes)

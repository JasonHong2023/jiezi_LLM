"""中文維基百科典範條目摘要題（design D4；授權 CC BY-SA 4.0，登記鍵 zh-wikipedia）。
Chinese Wikipedia featured-article summary items (design D4; CC BY-SA 4.0, registry key zh-wikipedia).

- 母體：鎖定 revision 的典範條目列表頁，依頂層章節分層。
  Population: the featured-articles list page at a pinned revision, stratified by top-level section.
- 內容：指定 revision 的條目 HTML（字詞轉換 zh-tw），只取正文段落，在段落邊界截斷。
  Content: article HTML at a pinned revision (zh-tw variant), body paragraphs only, cut at a paragraph boundary."""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Callable

from . import EvalError
from .bank import Source

USER_AGENT = "jiezi-eval/0.1 (research)"
REQUEST_GAP_S = 0.5  # 對維基伺服器保持禮貌 / be polite to Wikimedia servers
RETRY_DELAYS_S = (5, 15)  # 504 等暫時性錯誤（2026-11-14 實際遇到）/ transient errors such as 504 (seen 2026-11-14)

_HEADING = re.compile(r"^==\s*([^=].*?)\s*==\s*$", re.M)
_LINK = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")


def _get(url: str, headers: dict | None = None, sleep=time.sleep, opener=urllib.request.urlopen) -> str:
    """GET；5xx、429、逾時、連線錯誤最多重試 2 次，仍失敗就拋出 EvalError。
    GET with up to two retries on 5xx, 429, timeouts, and connection errors; raise EvalError if it still fails."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    last = None
    for attempt in range(len(RETRY_DELAYS_S) + 1):
        if attempt:
            sleep(RETRY_DELAYS_S[attempt - 1])
        try:
            with opener(req, timeout=60) as r:
                text = r.read().decode("utf-8", errors="replace")
            sleep(REQUEST_GAP_S)
            return text
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
            if exc.code != 429 and exc.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            last = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
    raise EvalError(f"wikipedia request failed ({last}): {url}")


def list_titles(wikitext: str) -> list[tuple[str, str]]:
    """從列表頁 wikitext 取出 (頂層章節, 條目名稱)；略過其他命名空間與重複項目。
    Extract (top-level section, article title) from the list page; skip other namespaces and duplicates."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    parts = _HEADING.split(wikitext)
    # parts = [前言, 章節1, 內容1, 章節2, 內容2, ...] / [preamble, h1, body1, h2, body2, ...]
    for section, body in zip(parts[1::2], parts[2::2]):
        for m in _LINK.finditer(body):
            title = m.group(1).strip().replace("_", " ")
            if not title or ":" in title or title in seen:
                continue
            seen.add(title)
            out.append((section.strip(), title))
    return out


class _BodyText(HTMLParser):
    """收集正文 <p> 的文字；略過表格、上標引用、樣式與腳本。
    Collect text of body <p> elements; skip tables, reference superscripts, styles, and scripts."""

    SKIP = {"table", "sup", "style", "script", "math", "figure"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._skip = 0
        self._in_p = 0
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "p" and not self._skip:
            self._in_p += 1
            self._buf = []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "p" and self._in_p:
            self._in_p -= 1
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if text:
                self.paragraphs.append(text)

    def handle_data(self, data):
        if self._in_p and not self._skip:
            self._buf.append(data)


def article_text(html: str, max_chars: int) -> str:
    """取正文段落，在不超過 max_chars 的段落邊界截斷；第一段就超過時在句號處截斷。
    Body paragraphs cut at a paragraph boundary within max_chars; if the first paragraph is already
    too long, cut it at a full stop."""
    p = _BodyText()
    p.feed(html)
    out: list[str] = []
    total = 0
    for para in p.paragraphs:
        if total + len(para) + (1 if out else 0) > max_chars:
            break
        out.append(para)
        total += len(para) + (1 if len(out) > 1 else 0)
    if not out and p.paragraphs:
        first = p.paragraphs[0][:max_chars]
        cut = first.rfind("。")
        out = [first[: cut + 1] if cut > 0 else first]
    return "\n".join(out)


class Wiki:
    """維基 API 存取；get 可注入以便測試。 / Wikipedia API access; `get` is injectable for tests."""

    def __init__(self, site: str, variant: str, get: Callable[..., str] = _get):
        self.site = site.rstrip("/")
        self.variant = variant
        self.get = get

    def wikitext(self, revid: int) -> str:
        url = f"{self.site}/w/api.php?action=parse&oldid={revid}&prop=wikitext&format=json&formatversion=2"
        data = json.loads(self.get(url))
        if "error" in data:
            raise EvalError(f"wikipedia revision {revid}: {data['error'].get('info')}")
        return data["parse"]["wikitext"]

    def latest_revids(self, titles: list[str]) -> dict[str, int]:
        """一次最多 50 個條目查目前 revision。 / Look up current revisions, at most 50 titles per request."""
        out: dict[str, int] = {}
        for i in range(0, len(titles), 50):
            chunk = titles[i:i + 50]
            q = urllib.parse.urlencode({"action": "query", "prop": "revisions", "rvprop": "ids",
                                        "titles": "|".join(chunk), "format": "json", "formatversion": "2",
                                        "redirects": "1"})
            data = json.loads(self.get(f"{self.site}/w/api.php?{q}"))
            back = {r["to"]: r["from"] for r in (data["query"].get("redirects") or [])}
            back.update({n["to"]: n["from"] for n in (data["query"].get("normalized") or [])})
            for page in data["query"]["pages"]:
                if page.get("missing") or not page.get("revisions"):
                    continue
                original = back.get(page["title"], page["title"])
                original = back.get(original, original)
                out[original] = page["revisions"][0]["revid"]
        return out

    def article_html(self, title: str, revid: int) -> str:
        path = urllib.parse.quote(title.replace(" ", "_"), safe="")
        return self.get(f"{self.site}/api/rest_v1/page/html/{path}/{revid}", {"Accept-Language": self.variant})


def population(src: Source, wiki: Wiki) -> list[dict]:
    """列表頁上的所有候選條目（尚未取內容），供分層抽題。
    All candidate articles from the list page (content not yet fetched), for stratified sampling."""
    rows = list_titles(wiki.wikitext(int(src.options["list_revid"])))
    if not rows:
        raise EvalError(f"{src.key}: no article links found on the list page")
    return [{"id": title, "source": src.key, "task": src.task, "group": src.group, "scorer": src.scorer,
             "stratum": section, "data": {"title": title}} for section, title in rows]


def materialize(src: Source, wiki: Wiki, title: str, revid: int, stratum: str | None = None) -> dict:
    """取指定 revision 的條目內容，產生完整題目。 / Fetch an article at a pinned revision into a full item."""
    text = article_text(wiki.article_html(title, revid), int(src.options.get("max_chars", 2000)))
    if len(text) < 200:
        raise EvalError(f"{src.key}: article {title!r} rev {revid} yields only {len(text)} characters")
    return {"id": title, "source": src.key, "task": src.task, "group": src.group, "scorer": src.scorer,
            "stratum": stratum, "data": {"title": title, "revid": revid, "text": text, "chars": len(text),
                                      "url": f"{wiki.site}/w/index.php?oldid={revid}",
                                      "license": "CC BY-SA 4.0"}}

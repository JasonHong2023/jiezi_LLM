"""寫作教學文章索引：只存標題與網址，不複製內文、不用於訓練（add-curriculum D6）。
Writing-lesson link index: titles and URLs only; article text is never copied or used for training (design D6).

來源 rocknovels.com（© 故事革命，未開放授權）。使用者 2026-11-15 決定：建標題索引推薦文章，並在請教 Claude 時
提示可上網參考。`build` 只抓一頁目錄（robots.txt 要求 Crawl-delay 120 秒，這裡只發一次請求）。
Source: rocknovels.com (all rights reserved). `build` fetches the single index page once."""

from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from .errors import JieziError

SITE = "https://www.rocknovels.com"
INDEX_URL = SITE + "/teachlist"
SOURCE = "rocknovels-teachlist"
ATTRIBUTION = "文章來源：故事革命 rocknovels.com（© 故事革命，請至原網站閱讀）"
CUE = re.compile(r"寫作|寫小說|小說|故事|劇情|情節|角色|人物|大綱|靈感|主題|修稿|投稿|世界觀|場景|伏筆|對白|對話|"
                 r"開頭|結局|衝突|文筆|描寫|敘事|觀點|視角|節奏|題材|創作|作家")
MAX_REFS = 3
GENERIC = ("小說", "故事", "雜談", "觀念")  # 分類名稱太籠統時不加分 / no bonus for generic categories


def index_path(root: Path) -> Path:
    return root / "var" / "refs" / "rocknovels.json"


def parse_index(page: str) -> list[dict]:
    """目錄頁 → [{category, title, url}]；只取站內文章連結。 / Index page → site article links."""
    out, category = [], ""
    for m in re.finditer(r'<h3>(.*?)</h3>|<a[^>]+href="(/20\d\d/[^"]+)"[^>]*>(.*?)</a>', page, flags=re.S):
        if m.group(1) is not None:
            text = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            if text:
                category = text.strip("【】")
            continue
        title = html.unescape(re.sub(r"<[^>]+>|\s+", " ", m.group(3))).strip()
        url = SITE + m.group(2)
        if title and all(r["url"] != url for r in out):
            out.append({"category": category, "title": title, "url": url})
    return out


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "jiezi-refs"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def build(root: Path, fetch=_fetch) -> int:
    refs = parse_index(fetch(INDEX_URL))
    if not refs:
        raise JieziError(f"{INDEX_URL}: no article links found (page layout changed?)")
    p = index_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"source": SOURCE, "url": INDEX_URL, "fetched": datetime.now().astimezone()
                             .isoformat(timespec="seconds"), "refs": refs}, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return len(refs)


def _bigrams(text: str) -> set[str]:
    han = re.sub(r"[^一-鿿]", " ", text)
    return {w[i:i + 2] for w in han.split() for i in range(len(w) - 1)}


class WritingRefs:
    def __init__(self, path: Path):
        if not path.exists():
            raise JieziError(f"{path} not found; run `scripts/jiezi writing-refs build`")
        self.refs = json.loads(path.read_text(encoding="utf-8"))["refs"]
        self._grams = [_bigrams(r["title"] + " " + r["category"]) for r in self.refs]

    def search(self, text: str, limit: int = MAX_REFS) -> list[dict]:
        """標題用字重疊最多的文章（至少 2 組雙字）。 / Articles whose titles share the most character pairs."""
        q = _bigrams(text) - _bigrams("什麼 怎麼 如何 可以 請問 一下 寫作 小說 故事 創作 作家")  # 太常見的詞不計分 / too common to score
        # 問題裡提到分類名稱（靈感、人物、對白…）加 1 分 / +1 when the question names the category
        scored = sorted(((len(q & g) + (r["category"] in text and r["category"] not in GENERIC if r["category"] else 0), -i)
                         for i, (r, g) in enumerate(zip(self.refs, self._grams))), reverse=True)
        return [self.refs[-i] for s, i in scored[:limit] if s >= 2]

    def appendix(self, text: str) -> tuple[str, list[dict]] | None:
        """寫作問題 → 附在回答後的延伸閱讀連結。 / Writing questions → further-reading links appended."""
        if not CUE.search(text):
            return None
        hits = self.search(text[:1000])
        if not hits:
            return None
        lines = "\n".join(f"- {r['title']}：{r['url']}" for r in hits)
        return (f"\n\n---\n【延伸閱讀】\n{lines}\n{ATTRIBUTION}",
                [{"source": SOURCE, "title": r["title"], "url": r["url"]} for r in hits])

    def consult_hint(self, text: str) -> str | None:
        """請教 Claude 時的提示：可上網讀這些文章。 / Hint for Claude consultations: these pages may be read."""
        if not CUE.search(text):
            return None
        hits = self.search(text[:1000])
        urls = "、".join(f"{r['title']}（{r['url']}）" for r in hits) or INDEX_URL
        return ("這是寫作相關問題。需要時可上網閱讀故事革命的寫作教學作為參考（請用自己的話說明，不要大段照抄），"
                f"相關文章：{urls}；完整目錄：{INDEX_URL}。")

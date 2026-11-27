"""讀使用者給的網址（add-web-read；使用者 2026-11-18：「仔細閱讀這個網址的內容並記憶起來」被轉給 Claude）。
Read URLs the user typed, locally (add-web-read).

只做 GET，只收 HTML／純文字，≤ 5 MB、15 秒、最多轉址 5 次；本機、內網、保留位址一律拒絕（每次轉址後都重新檢查）；
不帶 cookie、不送任何使用者資料。網頁內容之後當「文件」附給模型，照 injection-guard 只當資料。
GET only, HTML or text, size/time/redirect limits; loopback, private and reserved addresses are refused, after every
redirect too. No cookies, no user data. The page text is attached as a document and treated as data."""

from __future__ import annotations

import ipaddress
import html
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx

MAX_URLS = 3
MAX_BYTES = 5 << 20
TIMEOUT_S = 15.0
MAX_REDIRECTS = 5
ENCODING_RETRIES = 3
USER_AGENT = "jiezi-webread/1 (local assistant; read-only)"
URL_RE = re.compile(r"https?://[^\s<>\"'）)」』，、。]+", re.I)
# 「記住／記憶起來」：讀完要存進記憶 / the user asks to remember the page
MEMO = re.compile(r"記住|記得|記下|記憶|記起來|背下來|存起來|remember|memori[sz]e", re.I)
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "text/markdown")


class WebError(Exception):
    """讀不了的網址；訊息是給 metadata 的簡短原因。 / An unreadable URL; the message is a short reason."""


def find_urls(text: str) -> list[str]:
    return list(dict.fromkeys(u.rstrip(".,;:!?") for u in URL_RE.findall(text or "")))[:MAX_URLS]


def _blocked(host: str, resolve=socket.getaddrinfo) -> str | None:
    """主機解析後若是本機、內網、保留位址就回傳原因。 / Why a host is refused, if it is."""
    if not host:
        return "no_host"
    try:   # 網址直接寫 IP 就直接檢查 / IP literals are checked as they are
        addrs = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        try:
            addrs = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in resolve(host, None, type=socket.SOCK_STREAM)]
        except OSError:
            return "dns_failed"
    for ip in addrs:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast \
                or ip.is_unspecified or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global):
            return "private_address"
    return None


async def fetch(url: str, client: httpx.AsyncClient | None = None, resolve=socket.getaddrinfo) -> dict:
    """GET 一個網址並轉成文字 → {url, final_url, title, text, bytes}；失敗丟 WebError。
    GET a URL and extract its text; raises WebError."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=False,
                                         headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9",
                                                  # 只要解得開的壓縮（沒裝 brotli 時 br 會變成亂碼；2026-11-18 實測）
                                                  "Accept-Encoding": "gzip, deflate"})
    try:
        current, tries = url, 0
        for _ in range(MAX_REDIRECTS + 1 + ENCODING_RETRIES):
            parts = urlsplit(current)
            if parts.scheme not in ("http", "https"):
                raise WebError("not_http")
            why = _blocked(parts.hostname or "", resolve)
            if why:
                raise WebError(why)
            try:
                async with client.stream("GET", current) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        current = urljoin(current, r.headers["location"])
                        continue
                    if r.status_code >= 400:
                        raise WebError(f"http_{r.status_code}")
                    enc = (r.headers.get("content-encoding") or "identity").lower()
                    if enc not in ("identity", "gzip", "deflate", "x-gzip"):
                        # 有些快取伺服器不管 Accept-Encoding 都回 brotli（2026-11-18 docs.ubuntu.com），沒有解碼器時
                        # 換個查詢參數重抓 / some caches send brotli regardless; retry with a cache-busting parameter
                        tries += 1
                        if tries > ENCODING_RETRIES:
                            raise WebError(f"encoding: {enc}")
                        current = url + ("&" if "?" in url else "?") + f"_jiezi={tries}"
                        continue
                    kind = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                    if kind and not kind.startswith(TEXT_TYPES):
                        raise WebError(f"not_text: {kind}")
                    data = b""
                    async for chunk in r.aiter_bytes():
                        data += chunk
                        if len(data) > MAX_BYTES:
                            raise WebError("too_large")
                    break
            except httpx.TimeoutException as exc:
                raise WebError("timeout") from exc
            except httpx.HTTPError as exc:
                raise WebError(f"{type(exc).__name__}") from exc
        else:
            raise WebError("too_many_redirects")
    finally:
        if own:
            await client.aclose()
    from .documents import read_html
    if kind.startswith("text/plain") or kind.startswith("text/markdown"):
        text = data.decode(r.charset_encoding or "utf-8", errors="replace")
    else:
        text = read_html(data)["text"]
    title = re.search(rb"<title[^>]*>(.*?)</title>", data, re.I | re.S)
    # 標題的 HTML entity 要解碼（2026-11-26 實機：「&amp;」原樣存進記憶）/ decode entities in the title
    title = re.sub(r"\s+", " ", html.unescape(title.group(1).decode("utf-8", "replace"))).strip()[:120] if title else ""
    if not text.strip():
        raise WebError("no_text")
    return {"url": url, "final_url": current, "title": title, "text": text, "bytes": len(data)}


# ── 記住的網頁（索引）/ Remembered pages (index) ──
# 問題提到網站名稱（例：「Ubuntu 官方文件網站」）就附上記住的重點；字詞相似度對不上這種問法（2026-11-18 實測 0.05）
# A question naming the site gets the remembered summary; word similarity cannot match such questions
GENERIC = {"www", "docs", "doc", "documentation", "home", "index", "welcome", "official", "the", "and", "com", "org",
           "net", "html", "page", "site", "blog", "wiki", "en", "zh", "tw", "us", "latest", "stable", "main"}


def site_keys(url: str, title: str) -> list[str]:
    host = (urlsplit(url).hostname or "").lower()
    words = [w for w in re.split(r"[.\-]", host) if w] + re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", title or "")
    return list(dict.fromkeys(w.lower() for w in words if w.lower() not in GENERIC and len(w) >= 3))


def memo_path(root) -> "Path":
    from pathlib import Path
    return Path(root) / "var" / "memory" / "web_memo.json"


def remember(root, url: str, title: str, summary: str, page: str | None) -> None:
    import json
    p = memo_path(root)
    rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    rows = [r for r in rows if r.get("url") != url]
    rows.append({"url": url, "title": title, "keys": site_keys(url, title), "summary": summary[:3000], "page": page})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def recall(root, question: str, k: int = 2) -> list[dict]:
    import json
    p = memo_path(root)
    if not p.exists():
        return []
    q = (question or "").lower()
    rows = json.loads(p.read_text(encoding="utf-8"))
    return [r for r in rows if any(key in q for key in r.get("keys") or [])][:k]

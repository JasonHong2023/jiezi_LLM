"""讀取文件（add-long-documents）：PDF、Word（.docx）、網頁（.html）、純文字轉成文字，掃描版 PDF 用 tesseract 繁中 OCR。
Read documents: PDF, Word (.docx), HTML and plain text to text; scanned PDF pages go through tesseract OCR.

解析在獨立子行程裡跑，限制時間與記憶體：惡意或損壞的檔案（pypdf 的已知漏洞多為耗時、耗記憶體）只會讓子行程失敗。
Parsing runs in a child process with time and memory limits, so a hostile or broken file only kills the child."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

MAX_FILE_BYTES = 50 * 2**20           # 單一檔案上限 / per-file limit
MAX_DOCX_XML_BYTES = 64 * 2**20       # .docx 解壓後的 XML 上限（防壓縮炸彈）/ zip-bomb guard
MEM_LIMIT = 1536 * 2**20              # 子行程記憶體上限 / child memory limit
TIMEOUT_S, OCR_PAGE_TIMEOUT_S = 600, 60   # 掃描檔每頁約 2 秒，上百頁要幾分鐘 / ~2 s per scanned page
OCR_THREADS = "2"                         # 不佔滿 CPU（資源預算）/ never take every core
MIN_PAGE_CHARS = 20                   # 少於這個字數的 PDF 頁視為掃描頁 / fewer chars → scanned page
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".rst", ".py", ".js", ".toml", ".yaml",
                 ".yml"}
SUPPORTED = TEXT_SUFFIXES | {".pdf", ".docx", ".html", ".htm"}


class DocumentError(Exception):
    pass


# ── 各格式 / Formats ──
def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp950", "big5hkscs", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _ocr(image: bytes, run=subprocess.run) -> str:
    """tesseract 繁中＋英文 OCR。 / tesseract OCR, Traditional Chinese plus English."""
    p = run(["tesseract", "stdin", "stdout", "-l", "chi_tra+eng", "--psm", "3"], input=image, capture_output=True,
            timeout=OCR_PAGE_TIMEOUT_S, env={**os.environ, "OMP_THREAD_LIMIT": OCR_THREADS})
    if p.returncode != 0:
        raise DocumentError(f"OCR failed: {p.stderr.decode(errors='replace')[-200:]}")
    text = p.stdout.decode("utf-8", errors="replace")
    return re.sub(r"(?<=[⺀-鿿])[ \t]+(?=[⺀-鿿])", "", text)  # tesseract 在中文字間插空白 / drop spaces between CJK


def read_pdf(data: bytes, ocr=_ocr) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise DocumentError("PDF 有密碼保護 / the PDF is password-protected")
        except Exception as exc:  # noqa: BLE001 - pypdf 的解密錯誤種類多 / many decrypt error types
            raise DocumentError("PDF 有密碼保護 / the PDF is password-protected") from exc
    pages, ocr_pages, warnings = [], [], []
    for n, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if len(text) < MIN_PAGE_CHARS:
            images = list(page.images)
            if images:
                try:
                    text = "\n".join(ocr(img.data) for img in images).strip()
                    ocr_pages.append(n)
                except (DocumentError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
                    warnings.append(f"第 {n} 頁 OCR 失敗 / page {n} OCR failed: {exc}")
        pages.append(text)
    body = "\n\n".join(f"〔第 {n} 頁〕\n{t}" for n, t in enumerate(pages, 1) if t)
    return {"text": body, "pages": len(pages), "ocr_pages": ocr_pages, "warnings": warnings}


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx(data: bytes) -> dict:
    from xml.etree import ElementTree as ET
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        info = z.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise DocumentError("不是有效的 .docx（舊的 .doc 請先另存成 .docx）/ not a valid .docx") from exc
    if info.file_size > MAX_DOCX_XML_BYTES:
        raise DocumentError("文件內容過大 / document too large")
    xml = z.read(info)
    if b"<!DOCTYPE" in xml[:4096] or b"<!ENTITY" in xml:  # .docx 不會用 DTD；有就拒絕 / no DTDs in real .docx
        raise DocumentError("文件含 DTD，拒絕解析 / document contains a DTD")
    root = ET.fromstring(xml)
    out = []

    def para(p) -> str:
        parts = []
        for el in p.iter():
            if el.tag == _W + "t":
                parts.append(el.text or "")
            elif el.tag == _W + "tab":
                parts.append("\t")
            elif el.tag in (_W + "br", _W + "cr"):
                parts.append("\n")
        return "".join(parts)

    body = root.find(_W + "body")
    for el in (body if body is not None else []):
        if el.tag == _W + "p":
            out.append(para(el))
        elif el.tag == _W + "tbl":
            for tr in el.iter(_W + "tr"):
                cells = [" ".join(para(p) for p in tc.iter(_W + "p")).strip() for tc in tr.iter(_W + "tc")]
                out.append(" | ".join(cells))
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return {"text": text, "pages": None, "ocr_pages": [], "warnings": []}


class _Html(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def read_html(data: bytes) -> dict:
    p = _Html()
    p.feed(_decode(data))
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return {"text": text, "pages": None, "ocr_pages": [], "warnings": []}


def extract(path: Path) -> dict:
    """在目前行程解析（由子行程呼叫）。 / Parse in this process (called inside the child)."""
    suf = path.suffix.lower()
    if suf not in SUPPORTED:
        raise DocumentError(f"不支援的格式 {suf or '（無副檔名）'}；支援 PDF、.docx、.html、純文字 / unsupported format")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DocumentError(f"檔案超過 {MAX_FILE_BYTES // 2**20} MB / file too large")
    data = path.read_bytes()
    if suf == ".pdf":
        r = read_pdf(data)
    elif suf == ".docx":
        r = read_docx(data)
    elif suf in (".html", ".htm"):
        r = read_html(data)
    else:
        r = {"text": _decode(data).strip(), "pages": None, "ocr_pages": [], "warnings": []}
    return {"name": path.name, "kind": suf.lstrip("."), "chars": len(r["text"]), **r}


def _limit():  # pragma: no cover - 在子行程中執行 / runs in the child
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEM_LIMIT, MEM_LIMIT))


def read(path: str | Path, timeout: float = TIMEOUT_S) -> dict:
    """在受限的子行程中讀取文件。 / Read a document inside a limited child process."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise DocumentError(f"找不到檔案 / no such file: {path}")
    if path.suffix.lower() not in SUPPORTED:
        raise DocumentError(f"不支援的格式 {path.suffix or '（無副檔名）'}；支援 PDF、.docx、.html、純文字 / unsupported format")
    src = str(Path(__file__).resolve().parent.parent)
    env = {**os.environ, "PYTHONPATH": src}
    try:
        p = subprocess.run([sys.executable, "-m", "jiezi.documents", str(path)], capture_output=True, text=True,
                           timeout=timeout, env=env, preexec_fn=_limit if os.name == "posix" else None)
    except subprocess.TimeoutExpired as exc:
        raise DocumentError(f"讀取逾時（{timeout:.0f} 秒）/ reading timed out") from exc
    try:
        out = json.loads(p.stdout or "{}")
    except ValueError:
        out = {}
    if p.returncode != 0 or "error" in out or "text" not in out:
        raise DocumentError(out.get("error") or f"無法讀取（可能是檔案損壞或過大）/ could not read: {p.stderr[-200:]}")
    return out


# ── 附到問題裡 / Attach to a question ──
DOC_OPEN, DOC_CLOSE = "【文件：{name}】", "【文件結束】"
DOC_RE = re.compile(r"【文件：(?P<name>[^】\n]{1,200})】\n(?P<text>.*?)\n【文件結束】", re.S)


def attach(doc: dict, question: str) -> str:
    """把文件包進問題，gateway 會辨認標記並在太長時分段處理。 / Wrap the document so the gateway can find it."""
    from .injection import clean
    text, _ = clean(doc["text"])                  # 中和偽造的結束標記，文件才不會提早「結束」/ forged markers
    name = re.sub(r"[】\n]", "", str(doc["name"]))[:200] or "文件"
    return f"{DOC_OPEN.format(name=name)}\n{text}\n{DOC_CLOSE}\n\n{question.strip()}"


def main() -> int:  # pragma: no cover - 子行程入口 / child entry point
    try:
        print(json.dumps(extract(Path(sys.argv[1])), ensure_ascii=False))
        return 0
    except DocumentError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001 - 任何解析錯誤都回報為讀取失敗 / report any parse error
        print(json.dumps({"error": f"無法解析 / could not parse: {type(exc).__name__}: {str(exc)[:200]}"},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())

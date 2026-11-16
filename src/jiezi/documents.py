"""讀取文件（add-long-documents）：PDF、Word（.docx）、網頁（.html）、純文字轉成文字，掃描版 PDF 用 tesseract 繁中 OCR。
Read documents: PDF, Word (.docx), HTML and plain text to text; scanned PDF pages go through tesseract OCR.

解析在獨立子行程裡跑，限制時間與記憶體：惡意或損壞的檔案（pypdf 的已知漏洞多為耗時、耗記憶體）只會讓子行程失敗。
Parsing runs in a child process with time and memory limits, so a hostile or broken file only kills the child."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
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
# 舊版與其他辦公室格式：先在沙盒內用 LibreOffice 轉成新格式再讀（add-legacy-office）
# Legacy and other office formats: converted by LibreOffice inside the sandbox first (add-legacy-office)
LEGACY = {".doc": "docx", ".rtf": "docx", ".odt": "docx", ".ppt": "pptx", ".odp": "pptx", ".xls": "xlsx", ".ods": "xlsx"}
OFFICE_INSTALL = ("sudo apt install --no-install-recommends libreoffice-writer-nogui libreoffice-calc-nogui "
                  "libreoffice-impress-nogui")
CONVERT_S, CONVERT_MIB, CONVERT_OUT_MIB = 120, 1536, 64
SUPPORTED = TEXT_SUFFIXES | {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"} | set(LEGACY)


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


# ── PowerPoint、Excel（add-office-documents；只用標準函式庫）/ PowerPoint and Excel, stdlib only ──
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
MAX_SLIDES, MAX_SHEETS, MAX_CELLS, MAX_COLS = 500, 50, 200_000, 60
_DATE_FMT_IDS = set(range(14, 23)) | set(range(27, 37)) | {45, 46, 47} | set(range(50, 59))


def _open_zip(data: bytes, kind: str) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentError(f"不是有效的 {kind}（舊格式請先另存成新格式）/ not a valid {kind}") from exc


def _zip_xml(z: zipfile.ZipFile, name: str, budget: list[int]):
    """讀出並解析壓縮檔裡的一個 XML；累計大小有上限（防壓縮炸彈），含 DTD 就拒絕。
    Parse one XML member; the running total is capped (zip bombs) and DTDs are refused."""
    from xml.etree import ElementTree as ET
    info = z.getinfo(name)
    budget[0] -= info.file_size
    if budget[0] < 0:
        raise DocumentError("文件內容過大 / document too large")
    xml = z.read(info)
    if b"<!DOCTYPE" in xml[:4096] or b"<!ENTITY" in xml:
        raise DocumentError("文件含 DTD，拒絕解析 / document contains a DTD")
    return ET.fromstring(xml)


def _numbered(names: list[str], prefix: str) -> list[str]:
    rx = re.compile(re.escape(prefix) + r"(\d+)\.xml$")
    hits = [(rx.match(n), n) for n in names]
    return [n for _, n in sorted((int(m.group(1)), n) for m, n in hits if m)]


def read_pptx(data: bytes) -> dict:
    z = _open_zip(data, ".pptx")
    slides = _numbered(z.namelist(), "ppt/slides/slide")
    if not slides:
        raise DocumentError("不是有效的 .pptx（舊的 .ppt 請先另存成 .pptx）/ not a valid .pptx")
    budget, warnings, out = [MAX_DOCX_XML_BYTES], [], []
    if len(slides) > MAX_SLIDES:
        warnings.append(f"投影片超過 {MAX_SLIDES} 張，只讀前面的 / only the first {MAX_SLIDES} slides were read")

    def paras(root) -> list[str]:
        lines = []
        for p in root.iter(_A + "p"):
            t = "".join((el.text or "") if el.tag == _A + "t" else "\n" if el.tag == _A + "br" else ""
                        for el in p.iter()).strip()
            if t:
                lines.append(t)
        return lines

    names = set(z.namelist())
    for i, name in enumerate(slides[:MAX_SLIDES], 1):
        lines = paras(_zip_xml(z, name, budget))
        note = f"ppt/notesSlides/notesSlide{name[len('ppt/slides/slide'):-4]}.xml"
        notes = [t for t in paras(_zip_xml(z, note, budget)) if not t.isdigit()] if note in names else []
        block = f"〔第 {i} 張投影片〕\n" + "\n".join(lines)
        if notes:
            block += "\n（備忘稿）" + "\n".join(notes)
        out.append(block.strip())
    text = "\n\n".join(out)
    body = sum(len(b.split("\n", 1)[1]) if "\n" in b else 0 for b in out)
    if body < MIN_PAGE_CHARS * len(out):  # 實測：整張是圖片的簡報幾乎沒有文字 / image-only decks carry almost no text
        warnings.append("投影片幾乎沒有文字（可能整張是圖片）；可先匯出成 PDF 再附上，會自動 OCR / "
                        "slides contain almost no text (probably images); export to PDF to get OCR")
    return {"text": text, "pages": len(slides), "ocr_pages": [], "warnings": warnings}


def _is_date_format(code: str) -> bool:
    code = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", code or "")
    return bool(re.search(r"[ymdhs]", code, re.I)) and "General" not in code


def _serial_date(v: float, date1904: bool) -> str:
    from datetime import datetime, timedelta
    base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
    d = base + timedelta(days=v)
    if v < 1:
        return d.strftime("%H:%M:%S")
    return d.strftime("%Y-%m-%d") if abs(v - round(v)) < 1e-9 else d.strftime("%Y-%m-%d %H:%M")


def _col(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return n - 1


def read_xlsx(data: bytes) -> dict:
    z = _open_zip(data, ".xlsx")
    names = set(z.namelist())
    if "xl/workbook.xml" not in names:
        raise DocumentError("不是有效的 .xlsx（舊的 .xls 請先另存成 .xlsx）/ not a valid .xlsx")
    budget, warnings = [MAX_DOCX_XML_BYTES], []
    wb = _zip_xml(z, "xl/workbook.xml", budget)
    pr = wb.find(_S + "workbookPr")
    date1904 = pr is not None and pr.get("date1904") in ("1", "true")
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        for r in _zip_xml(z, "xl/_rels/workbook.xml.rels", budget).iter(_PR + "Relationship"):
            target = r.get("Target") or ""
            rels[r.get("Id")] = target.lstrip("/") if target.startswith("/") else "xl/" + target
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in _zip_xml(z, "xl/sharedStrings.xml", budget).iter(_S + "si"):
            # 注音／拼音標註（rPh）不算內容 / phonetic runs are not content
            shared.append("".join(t.text or "" for r in si if r.tag != _S + "rPh" for t in
                                  ([r] if r.tag == _S + "t" else r.iter(_S + "t"))))
    date_styles = set()
    if "xl/styles.xml" in names:
        st = _zip_xml(z, "xl/styles.xml", budget)
        custom = {int(n.get("numFmtId")): n.get("formatCode") or "" for n in st.iter(_S + "numFmt")
                  if (n.get("numFmtId") or "").isdigit()}
        xfs = st.find(_S + "cellXfs")
        for i, xf in enumerate(xfs if xfs is not None else []):
            fid = int(xf.get("numFmtId") or 0)
            if fid in _DATE_FMT_IDS or _is_date_format(custom.get(fid, "")):
                date_styles.add(i)

    def value(c) -> str:
        t, v = c.get("t"), c.find(_S + "v")
        if t == "inlineStr":
            return "".join(x.text or "" for x in c.iter(_S + "t"))
        if v is None or v.text is None:
            return ""
        if t == "s":
            return shared[int(v.text)] if v.text.isdigit() and int(v.text) < len(shared) else ""
        if t == "b":
            return "TRUE" if v.text == "1" else "FALSE"
        if t in (None, "n") and (c.get("s") or "").isdigit() and int(c.get("s")) in date_styles:
            try:
                return _serial_date(float(v.text), date1904)
            except (ValueError, OverflowError):
                return v.text
        if t in (None, "n"):
            try:
                f = float(v.text)
                return str(int(f)) if f.is_integer() and abs(f) < 1e15 else repr(round(f, 10))
            except ValueError:
                return v.text
        return v.text  # str（公式的文字結果）、e（錯誤值）/ formula strings, error values

    sheets = [(s.get("name") or "?", rels.get(s.get(_R + "id"))) for s in wb.iter(_S + "sheet")]
    if len(sheets) > MAX_SHEETS:
        warnings.append(f"工作表超過 {MAX_SHEETS} 張，只讀前面的 / only the first {MAX_SHEETS} sheets were read")
    out, cells, truncated = [], 0, False
    for name, target in sheets[:MAX_SHEETS]:
        if not target or target not in names:
            continue
        rows = []
        for row in _zip_xml(z, target, budget).iter(_S + "row"):
            vals: dict[int, str] = {}
            for k, c in enumerate(row.iter(_S + "c")):
                col = _col(c.get("r") or "") if c.get("r") else k
                text = value(c).replace("\n", " ").strip()
                if text and 0 <= col < MAX_COLS:
                    vals[col] = text
            if vals:
                cells += len(vals)
                rows.append(" | ".join(vals.get(i, "") for i in range(max(vals) + 1)))
            if cells > MAX_CELLS:
                truncated = True
                break
        if rows:
            out.append(f"〔工作表：{name}〕\n" + "\n".join(rows))
        if truncated:
            break
    if truncated:
        warnings.append(f"儲存格超過 {MAX_CELLS} 個，只讀前面的 / only the first {MAX_CELLS} cells were read")
    return {"text": "\n\n".join(out), "pages": len(sheets), "ocr_pages": [], "warnings": warnings}


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
        raise DocumentError(f"不支援的格式 {suf or '（無副檔名）'}；支援 PDF、Word、PowerPoint、Excel（含舊版 .doc／.ppt／.xls、.rtf、OpenDocument）、.html、純文字 / unsupported format")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DocumentError(f"檔案超過 {MAX_FILE_BYTES // 2**20} MB / file too large")
    if suf in LEGACY:  # 舊版格式由 read() 先轉檔；這裡不該收到 / converted by read() first, never parsed here
        raise DocumentError(f"{suf} 需要先轉檔 / {suf} must be converted first")
    data = path.read_bytes()
    if suf == ".pdf":
        r = read_pdf(data)
    elif suf == ".docx":
        r = read_docx(data)
    elif suf == ".pptx":
        r = read_pptx(data)
    elif suf == ".xlsx":
        r = read_xlsx(data)
    elif suf in (".html", ".htm"):
        r = read_html(data)
    else:
        r = {"text": _decode(data).strip(), "pages": None, "ocr_pages": [], "warnings": []}
    return {"name": path.name, "kind": suf.lstrip("."), "chars": len(r["text"]), **r}


def _limit():  # pragma: no cover - 在子行程中執行 / runs in the child
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEM_LIMIT, MEM_LIMIT))


# 在沙盒裡執行的轉檔程式：只看得到 /work 裡的那一個檔案；LibreOffice 的設定檔目錄放在沙盒的 /tmp
# The converter driver run inside the sandbox: it sees one file in /work; the LibreOffice profile lives in the sandbox /tmp
_CONVERT_DRIVER = """
import os, subprocess, sys
src, fmt, exe = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs("/tmp/lo", exist_ok=True)
os.makedirs("out", exist_ok=True)
r = subprocess.run([exe, "--headless", "--norestore", "--nolockcheck", "--nodefault", "--nofirststartwizard",
                    "-env:UserInstallation=file:///tmp/lo", "--convert-to", fmt, "--outdir", "out", src],
                   capture_output=True, text=True,
                   env={"HOME": "/tmp", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "SAL_USE_VCLPLUGIN": "svp"})
sys.stdout.write(r.stdout[-1500:])
sys.stderr.write(r.stderr[-1500:])
sys.exit(r.returncode)
"""
_MACRO_MARKS = (b"_VBA_PROJECT", "_VBA_PROJECT".encode("utf-16-le"), b"Basic/script-lc.xml")


def find_soffice(which=shutil.which) -> str | None:
    """LibreOffice 的執行檔；沙盒只掛 /usr，所以必須在 /usr 之下。 / The soffice binary; it must live under /usr."""
    for name in ("soffice", "libreoffice"):
        p = which(name)
        if p:
            real = str(Path(p).resolve())
            if real.startswith("/usr/"):
                return real
    return None


def convert_legacy(path: Path, sandbox=None, soffice: str | None = None) -> tuple[bytes, str, list[str]]:
    """把舊版檔案轉成新格式；回傳 (新檔內容, 新副檔名, 警告)。只在沙盒內執行，沙盒或 LibreOffice 不可用就報錯。
    Convert a legacy file to the modern format: (bytes, new suffix, warnings). Sandbox only; errors when the
    sandbox or LibreOffice is unavailable."""
    suf = path.suffix.lower()
    fmt = LEGACY[suf]
    if path.stat().st_size > MAX_FILE_BYTES:
        raise DocumentError(f"檔案超過 {MAX_FILE_BYTES // 2**20} MB / file too large")
    soffice = soffice or find_soffice()
    if not soffice:
        raise DocumentError(f"讀取 {suf} 需要 LibreOffice（或先另存成 .{fmt}）；安裝：{OFFICE_INSTALL} / "
                            f"reading {suf} needs LibreOffice (or re-save as .{fmt})")
    if sandbox is None:
        from .config import project_root
        from .verify.sandbox import Sandbox
        root = project_root()
        try:
            facts = json.loads((root / "facts.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            facts = {}
        sandbox = Sandbox(root, facts)
    from .verify.sandbox import Limits, SandboxUnavailable
    data = path.read_bytes()
    name = f"in{suf}"
    try:
        r = sandbox.run_python({"convert.py": _CONVERT_DRIVER, name: data}, ["convert.py", name, fmt, soffice],
                               Limits(wall_s=CONVERT_S, memory_mib=CONVERT_MIB, tasks=256, output_mib=CONVERT_OUT_MIB),
                               collect=[f"out/in.{fmt}"], extra_ro=["/etc/libreoffice", "/etc/fonts"])
    except SandboxUnavailable as exc:
        # 沙盒不可用就不轉檔（絕不在沙盒外執行 LibreOffice）/ never convert outside the sandbox
        raise DocumentError(f"無法安全地轉換 {suf}（沙盒不可用：{exc}）；請先另存成 .{fmt} / "
                            f"cannot convert {suf} safely (sandbox unavailable); re-save as .{fmt}") from exc
    out = r.files.get(f"out/in.{fmt}")
    if r.limit or not out:
        why = {"timeout": f"超過 {CONVERT_S} 秒", "resource_limit": "超過記憶體或輸出上限"}.get(r.limit or "", "")
        raise DocumentError(f"LibreOffice 無法轉換這個檔案（{why or (r.stderr or r.stdout).strip()[-200:] or '沒有輸出'}）；"
                            f"可能是損壞、加密或格式不符 / LibreOffice could not convert the file")
    warnings = []
    if any(m in data for m in _MACRO_MARKS):
        warnings.append("檔案含巨集；只取文字，巨集不會執行 / the file contains macros; only its text is read, macros never run")
    return out, f".{fmt}", warnings


def read(path: str | Path, timeout: float = TIMEOUT_S, sandbox=None) -> dict:
    """在受限的子行程中讀取文件。 / Read a document inside a limited child process."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise DocumentError(f"找不到檔案 / no such file: {path}")
    if path.suffix.lower() in LEGACY:
        # 轉檔在這裡（子行程之外）做：子行程有位址空間上限，LibreOffice 在裡面起不來；轉檔自己有沙盒與上限
        # Conversion happens here, outside the address-space-limited child; it has its own sandbox and limits
        import tempfile
        converted, suffix, warnings = convert_legacy(path, sandbox)
        with tempfile.TemporaryDirectory(prefix="jiezi-doc-") as d:
            tmp = Path(d) / f"converted{suffix}"
            tmp.write_bytes(converted)
            out = read(tmp, timeout)
        out.update(name=path.name, kind=path.suffix.lower().lstrip("."), warnings=warnings + (out.get("warnings") or []),
                   converted_from=path.suffix.lower())
        return out
    if path.suffix.lower() not in SUPPORTED:
        raise DocumentError(f"不支援的格式 {path.suffix or '（無副檔名）'}；支援 PDF、Word、PowerPoint、Excel（含舊版 .doc／.ppt／.xls、.rtf、OpenDocument）、.html、純文字 / unsupported format")
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

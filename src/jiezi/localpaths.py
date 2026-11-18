"""問題裡打的本機檔案路徑（使用者 2026-11-18：在問題裡寫 `'D:\\download\\x.jpg' 這圖片中有那些動物`，模型看不到圖、
還猜了內容）。chat 會把路徑換成實際附檔；gateway 在沒附檔時提醒模型別猜。
Local file paths typed into a question: chat attaches the file itself; the gateway tells the model not to guess when
nothing was attached."""

from __future__ import annotations

import base64
import re
from pathlib import Path

IMAGE_EXT = ("png", "jpg", "jpeg", "webp", "gif")
DOC_EXT = ("pdf", "docx", "pptx", "xlsx", "doc", "ppt", "xls", "rtf", "odt", "odp", "ods", "html", "htm", "txt", "md",
           "csv", "json", "log")
_EXT = "|".join(IMAGE_EXT + DOC_EXT)
# 引號裡的路徑可以有空白；沒有引號的路徑到空白為止 / quoted paths may contain spaces; bare ones end at whitespace
_QUOTED = re.compile(rf"""(['"「『])((?:[A-Za-z]:[\\/]|~/|/|\\\\)[^'"」』\n]*?\.(?:{_EXT}))(['"」』])""", re.I)
_BARE = re.compile(rf"""(?<![\w/\\])((?:[A-Za-z]:[\\/]|~/|/(?:mnt|home|tmp)/)[^\s'"「」『』]*?\.(?:{_EXT}))(?![\w])""", re.I)


def find_paths(text: str) -> list[str]:
    """問題裡的本機檔案路徑（依出現順序、不重複）。 / Local file paths in a question, in order, unique."""
    out: list[str] = []
    for m in _QUOTED.finditer(text or ""):
        out.append(m.group(2))
    rest = _QUOTED.sub(" ", text or "")
    for m in _BARE.finditer(rest):
        out.append(m.group(1))
    return list(dict.fromkeys(out))


def strip_paths(text: str, paths: list[str]) -> str:
    """把路徑（連同引號）換成「這張圖」「這份文件」，留下真正的問題。
    Replace the paths (with quotes) by "this image" / "this document", keeping the question."""
    for p in paths:
        word = "這張圖" if is_image(p) else "這份文件"
        text = re.sub(rf"""['"「『]?{re.escape(p)}['"」』]?""", f" {word} ", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    return re.sub(r"^(這張圖|這份文件) (?=這)", "", text)      # 「這張圖 這圖片中…」→「這圖片中…」


def is_image(path: str) -> bool:
    return path.lower().rsplit(".", 1)[-1] in IMAGE_EXT


def to_local(path: str, mnt: Path = Path("/mnt")) -> Path:
    """Windows 路徑換成 WSL 看得到的路徑（D:\\a\\b.jpg → /mnt/d/a/b.jpg）；其他路徑照原樣展開 ~。
    A Windows path as WSL sees it (D:\\a\\b.jpg → /mnt/d/a/b.jpg); other paths just expand ~."""
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", path)
    if m:
        return mnt / m.group(1).lower() / m.group(2).replace("\\", "/")
    return Path(path).expanduser()


PATH_NOTE = ("使用者在問題裡寫了電腦上的檔案路徑（{paths}），但沒有附上檔案本身，你看不到它的內容。"
             "不要猜測或憑檔名推測內容；請直接說明看不到，並請使用者附上檔案："
             "在 jiezi chat 用 /image 路徑（圖片）或 /file 路徑（文件），在桌面版按「附加檔案」，或把圖片貼上。")


# ── gateway 讀檔（add-image-paths）/ Reading typed paths in the gateway ──
MAX_IMAGE_BYTES = 5 << 20      # 同 jiezi chat 的 /image / same cap as /image
MAX_PATHS = 3                  # 一題最多讀幾個路徑 / paths read per question
# 檔頭 → MIME：副檔名對了、內容也要是圖 / file header → MIME type
_MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"), (b"GIF87a", "image/gif"),
          (b"GIF89a", "image/gif"))


def sniff_image(head: bytes) -> str | None:
    """依檔頭判斷圖片格式。 / Image type from the file header."""
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


class PathError(ValueError):
    """讀不了的路徑；訊息是給 metadata 的簡短原因。 / An unreadable path; the message is a short reason."""


def image_data_url(path: Path) -> str:
    """一般檔案、檔頭是 PNG／JPEG／WebP／GIF、≤ 5 MB → base64 data URL。
    A regular PNG/JPEG/WebP/GIF file of at most 5 MB → a base64 data URL."""
    if not path.is_file():
        raise PathError("not_found")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise PathError("too_large")
    data = path.read_bytes()
    kind = sniff_image(data[:16])
    if kind is None:
        raise PathError("not_an_image")
    return f"data:{kind};base64,{base64.b64encode(data).decode()}"

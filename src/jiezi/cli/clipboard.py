"""複製到剪貼簿：同時寫終端機的 OSC 52（由 Textual 送出）與系統剪貼簿，後者讓 Herdr 等不轉送 OSC 52 的
終端機也能複製（使用者 2026-11-15 回報「文字無法複製」）。
Copy to the clipboard: OSC 52 through the terminal (sent by Textual) plus the system clipboard, so copying
also works in terminals that do not forward OSC 52, such as Herdr (user report, 2026-11-15)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable


PS_SET = "[Console]::InputEncoding=[Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"


def _candidates(which: Callable[[str], str | None]) -> list[tuple[list[str], str]]:
    """(指令, 編碼)；依偵測到的工具決定，不假設平台（R21）。 / (command, encoding), detected not assumed."""
    out = []
    # WSL → Windows；放在 wl-copy 前面：WSLg 的剪貼簿同步會弄亂中文 / before wl-copy: WSLg sync garbles CJK
    if which("powershell.exe"):
        # 第一選擇：Set-Clipboard 讀 UTF-8，任何文字都完全相符（約 0.5 秒）/ exact for any text (~0.5 s)
        out.append((["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_SET], "utf-8"))
    if which("clip.exe"):
        # 備用：clip.exe 沒有 BOM 時靠猜編碼，「抱歉，剛才的回答」會被當成 ANSI 變亂碼（使用者 2026-11-18 第二次回報）；
        # 加 BOM 就判斷正確，代價是剪貼簿開頭多一個看不見的 U+FEFF
        # Fallback: without a BOM clip.exe guesses the encoding and garbles some CJK text; with one it is right,
        # at the cost of an invisible U+FEFF at the start
        out.append((["clip.exe"], "utf-16"))   # Python 的 utf-16 會加 BOM / Python's utf-16 adds the BOM
    if which("wl-copy"):
        out.append((["wl-copy"], "utf-8"))
    if which("xclip"):
        out.append((["xclip", "-selection", "clipboard"], "utf-8"))
    if which("xsel"):
        out.append((["xsel", "--clipboard", "--input"], "utf-8"))
    if which("pbcopy"):
        out.append((["pbcopy"], "utf-8"))
    return out


def system_copy(text: str, which: Callable[[str], str | None] = shutil.which, run=subprocess.run) -> str | None:
    """寫入第一個可用的系統剪貼簿工具；回傳使用的工具名稱，沒有就回傳 None。
    Write to the first working system clipboard tool; return its name, or None."""
    for cmd, enc in _candidates(which):
        try:
            p = run(cmd, input=text.encode(enc), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if p.returncode == 0:
            return cmd[0]
    return None

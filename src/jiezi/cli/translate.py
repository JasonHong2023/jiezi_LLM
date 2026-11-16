"""`jiezi translate 檔案 --to en`：整份文件逐段翻譯（add-translation）。
`jiezi translate FILE --to en`: translate a whole document chunk by chunk.

預設輸出原文／譯文對照（`--plain` 只要譯文）；預估超過 5 分鐘先問（`--yes` 略過）；中斷後重跑會接著做。
Bilingual output by default (`--plain` for the translation alone); asks first above an estimated five minutes
(`--yes` skips); an interrupted run resumes.

結束碼 / Exit codes：0 完成；2 gateway 未啟動；3 gateway 錯誤；4 檔案讀不了或參數錯；5 有段落未能翻譯（結果仍輸出）；
6 需要確認但不是互動終端機（加 `--yes`）。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

import anyio

from .client import Connection, GatewayError, GatewayUnreachable, complete, ensure_gateway

MIN_TIMEOUT_S = 900


async def run_translate(path: str, to: str | None, conn: Connection, stdin: TextIO, stdout: TextIO, stderr: TextIO,
                        out: str | None = None, glossary: str | None = None, plain: bool = False, yes: bool = False,
                        policy: str = "jiezi", client=None) -> int:
    from .. import translate as T
    from ..documents import DocumentError, attach, read
    try:
        rows = T.read_glossary(glossary) if glossary else []
        T.parse_glossary(rows)
    except (OSError, T.TranslateError) as exc:
        stderr.write(f"jiezi: --glossary {glossary}: {exc}\n")
        return 4
    try:
        doc = await anyio.to_thread.run_sync(read, path)
    except DocumentError as exc:
        stderr.write(f"jiezi: {path}: {exc}\n")
        return 4
    for w in doc.get("warnings") or []:
        stderr.write(f"jiezi: {path}: {w}\n")
    if not doc["text"].strip():
        stderr.write(f"jiezi: {path}: 讀不到文字（可能是掃描檔且 OCR 失敗）/ no text found\n")
        return 4
    question = f"請翻譯成{T.LANGS[to]}" if to else "請翻譯"
    messages = [{"role": "user", "content": attach(doc, question)}]
    opts = {"bilingual": not plain, "glossary": rows, "confirmed": yes, **({"to": to} if to else {})}

    async def call(timeout: float) -> dict:
        return await complete(conn, messages, policy, timeout=timeout, client=client, extra={"jiezi_translate": opts})

    try:
        stderr.write(f"jiezi: 翻譯中 translating: {doc['name']}（{doc['chars']} 字）…\n")
        resp = await call(MIN_TIMEOUT_S)
        info = (resp.get("jiezi") or {}).get("translation") or {}
        if info.get("needs_confirmation"):
            est = float(info.get("estimate_s") or 0)
            stderr.write(f"jiezi: 預估需要約 {max(1, round(est / 60))} 分鐘（估算）；可隨時 Ctrl+C 中斷，重跑會接著做。\n"
                         f"       estimated about {max(1, round(est / 60))} minutes; safe to interrupt and resume.\n")
            if not stdin.isatty():
                stderr.write("jiezi: 需要確認；非互動環境請加 --yes / confirmation needed; add --yes when not interactive\n")
                return 6
            stderr.write("繼續？continue? [y/N] ")
            stderr.flush()
            if stdin.readline().strip().lower() not in ("y", "yes", "是", "好"):
                stderr.write("jiezi: 已取消 / cancelled\n")
                return 0
            opts["confirmed"] = True
            resp = await call(max(MIN_TIMEOUT_S, est * 4))
            info = (resp.get("jiezi") or {}).get("translation") or {}
    except GatewayUnreachable as exc:
        stderr.write(f"jiezi: {exc}; gateway 未啟動，請執行 scripts/jiezi serve / the gateway is not running\n")
        return 2
    except GatewayError as exc:
        stderr.write(f"jiezi: {exc}\n")
        return 3
    text = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    if out:
        Path(out).expanduser().write_text(text + "\n", encoding="utf-8")
        stderr.write(f"jiezi: 已寫入 written: {out}\n")
    else:
        stdout.write(text + "\n")
    meta = resp.get("jiezi") or {}
    if not info:
        # 沒有走逐段翻譯（例如本機引擎不可用而轉交、或 JIEZI_TRANSLATE=off）：照實說，不假裝檢查過
        # Not the chunked path (escalated, or switched off): say so rather than imply it was checked
        stderr.write(f"jiezi: 注意 warning: 這次沒有走逐段翻譯與檢查（由 {meta.get('model') or '?'} 直接回答，"
                     f"原因 {meta.get('escalation') or '—'}）；長文件可能不完整。\n"
                     "       not the chunked, checked path; long documents may be incomplete.\n")
        return 0
    if info.get("mode") == "conversion":
        stderr.write(f"jiezi: 簡體 → 繁體字詞轉換完成（{info.get('chars')} 字，未經模型）/ script conversion, no model\n")
        return 0
    failed = info.get("failed") or 0
    stderr.write(f"jiezi: 完成 done: {info.get('chunks')} 段，{failed} 段未能翻譯，{info.get('seconds')} 秒"
                 f"（{info.get('source')} → {info.get('to')}）\n")
    if failed:
        nums = [str(f["chunk"]) for d in info.get("documents") or [] for f in d.get("failed") or []]
        stderr.write(f"jiezi: 未能翻譯的段（保留原文並已標記）/ untranslated chunks kept as source: {', '.join(nums)}\n")
        return 5
    return 0


def main(path: str, to: str | None = None, out: str | None = None, glossary: str | None = None, plain: bool = False,
         yes: bool = False, policy: str = "jiezi") -> int:
    conn = Connection.from_env()
    if not conn.key:
        sys.stderr.write("jiezi: JIEZI_GATEWAY_KEY is not set; run scripts/jiezi init-key\n")
        return 3
    ensure_gateway(conn, log=lambda m: sys.stderr.write(m + "\n"))
    return anyio.run(lambda: run_translate(path, to, conn, sys.stdin, sys.stdout, sys.stderr, out, glossary, plain, yes,
                                           policy))

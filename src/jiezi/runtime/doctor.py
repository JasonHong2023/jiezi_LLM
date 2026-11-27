"""健康檢查：一個指令看所有元件的狀態與修復方法（規則 R21：搬到新電腦時一眼看出缺什麼）。
Health check: every component's state and how to fix it, in one command (R21: see what a new machine lacks)."""

from __future__ import annotations

import json
import shutil
import sqlite3
import urllib.request
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "fail"


def _health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


def _rows(db: Path, sql: str) -> int | None:
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return con.execute(sql).fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return None


def checks(root: Path, port: int) -> list[tuple[str, str, str, str]]:
    """回傳 [(項目, 狀態, 說明, 修復方法)]。 / [(item, state, detail, fix)]."""
    out = []

    def add(item, state, detail, fix=""):
        out.append((item, state, detail, fix))

    h = _health(port)
    if h:
        e = h.get("engine") or {}
        add("gateway", OK, f"127.0.0.1:{port}，引擎 {e.get('status')}" + (f"（暫停到 {e['hold_until']}）" if e.get("hold_until") else ""))
    else:
        add("gateway", WARN, "沒有在執行", "scripts/jiezi start")
    env = root / ".env"
    key = env.exists() and "JIEZI_GATEWAY_KEY=" in env.read_text(encoding="utf-8")
    add("gateway 金鑰", OK if key else FAIL, ".env 有 JIEZI_GATEWAY_KEY" if key else "缺金鑰", "scripts/jiezi init-key")
    builds = [b for b in ("build-cuda", "build-cpu") if (root / b / "bin" / "llama-server").exists()]
    add("llama.cpp", OK if builds else FAIL, "、".join(builds) or "沒有建置", "scripts/bootstrap")
    models = root / "models"
    try:  # 實際設定的核心（JIEZI_CORE_MODEL），不是 bootstrap 的預設檔 / the configured core, not the bootstrap default
        from .settings import load_settings
        from .supervisor import resolve_core
        core = resolve_core(load_settings(root))
        add("核心模型", OK, f"{core['name']}（{core['file']}）")
    except Exception as exc:  # noqa: BLE001
        add("核心模型", FAIL, str(exc)[:200], "scripts/bootstrap（預設核心），或 scripts/eval e0 fetch")
    emb = models / "Qwen3-Embedding-0.6B-Q8_0.gguf"
    add("embedding 模型", OK if emb.exists() else WARN, emb.name if emb.exists() else "缺檔（向量檢索停用）",
        "見 models/manifest.toml 的 qwen3-embedding-0.6b-q8_0")
    rr = models / "qwen3-reranker-0.6b-q8_0.gguf"  # 重排序（add-reranker；選用）/ optional reranker
    rr_note = (h or {}).get("rerank") or "off"
    add("重排序模型", OK if rr.exists() and "failed" not in rr_note and "unavailable" not in rr_note else WARN,
        (f"{rr.name}（{rr_note}）" if rr.exists() else "缺檔（選用；重排序停用）"),
        "JIEZI_RERANK=on 啟用；`scripts/jiezi rerank check` 自我檢查；模型見 models/manifest.toml")
    try:  # 視覺（add-vision）/ vision
        from .settings import load_settings
        from .supervisor import resolve_core
        core = resolve_core(load_settings(root))
        add("視覺（看圖）", OK if core["vision"] else WARN,
            f"{core['name']} 有視覺模組" if core["vision"] else f"{core['name']} 沒有視覺模組（只能處理文字）",
            "核心選有 mmproj 的模型（Qwen3.5），並下載清單中對應的 *-mmproj-f16")
    except Exception as exc:  # noqa: BLE001
        add("視覺（看圖）", WARN, f"無法判斷：{exc}")
    try:  # 圖中文字（add-image-ocr；選用）/ text in images, optional
        from ..vision_ocr import OcrTool
        from .settings import load_settings
        st = load_settings(root)
        ocr_ok = OcrTool(st.models_dir or models).available()
        mode = {"tools": "跟著看圖工具", "auto": "問圖中文字時", "on": "每張圖", "off": "關閉"}[st.image_ocr]
        add("圖中文字（OCR）", OK if ocr_ok or st.image_ocr == "off" else WARN,
            f"{'可用' if ocr_ok else '未安裝（選用）'}；JIEZI_IMAGE_OCR={st.image_ocr}（{mode}）",
            "uv sync --group ocr --inexact && scripts/jiezi ocr setup")
    except Exception as exc:  # noqa: BLE001
        add("圖中文字（OCR）", WARN, f"無法判斷：{exc}")
    try:  # 代理程式的本機上下文（add-long-context）/ local context for agent clients
        from .settings import engine_ctx, load_settings
        st = load_settings(root)
        slots = st.samples if st.samples > 1 else 1
        add("代理程式上下文", OK,
            (f"JIEZI_AGENT_CTX={st.agent_ctx}：帶工具的請求本機可用 {st.agent_ctx} token（引擎共用池 "
             f"{engine_ctx(st.agent_ctx, slots)}、KV q8_0）") if st.agent_ctx else
            "關（每個槽位 4096 token；Hermes 等代理程式的長請求會轉雲端）",
            "JIEZI_AGENT_CTX=30000 讓代理程式留在本機；Hermes 的 model.context_length 同步設 30000")
    except Exception as exc:  # noqa: BLE001
        add("代理程式上下文", WARN, f"無法判斷：{exc}")
    sandbox = root / "var" / "tools" / "bubblewrap" / "bin" / "bwrap"  # 與 verify/sandbox.py 相同 / same as the sandbox
    add("程式驗證沙盒", OK if sandbox.exists() or shutil.which("bwrap") else WARN,
        "bubblewrap 可用" if sandbox.exists() or shutil.which("bwrap") else "缺（程式題驗證停用）", "scripts/bootstrap")
    from ..documents import OFFICE_INSTALL, find_soffice  # 舊版 Office（add-legacy-office）/ legacy Office formats
    office = find_soffice()
    add("舊版 Office 檔（.doc／.ppt／.xls）", OK if office and sandbox.exists() else WARN,
        "LibreOffice 與沙盒可用" if office and sandbox.exists() else
        ("缺 LibreOffice" if not office else "缺沙盒") + "（這些格式讀不了；其他格式不受影響）",
        OFFICE_INSTALL if not office else "scripts/bootstrap")
    data = [("國語／台語／客語辭典", root / "var" / "dict" / "dict.sqlite", "SELECT COUNT(*) FROM entries"),
            ("台灣知識庫", root / "var" / "knowledge" / "knowledge.sqlite", "SELECT COUNT(*) FROM sections"),
            ("全國法規", root / "var" / "laws" / "laws.sqlite", "SELECT COUNT(*) FROM articles"),
            ("知識庫向量", root / "var" / "knowledge" / "vectors.sqlite", "SELECT COUNT(*) FROM vecs"),
            ("法規向量", root / "var" / "laws" / "vectors.sqlite", "SELECT COUNT(*) FROM vecs")]
    for name, db, sql in data:
        n = _rows(db, sql) if db.exists() else None
        vec = "向量" in name
        fix = ("scripts/jiezi knowledge embed --gpu" if "知識" in name else "scripts/jiezi laws embed --gpu") if vec \
            else "scripts/jiezi data build"
        add(name, OK if n else (WARN if vec else FAIL), f"{n:,} 筆" if n else "沒有建置", fix)
    cur = root / "var" / "curriculum"
    add("課綱與課本", OK if any(cur.glob("*.json")) else FAIL, "已下載" if any(cur.glob("*.json")) else "沒有建置",
        "scripts/jiezi data build")
    refs = root / "var" / "refs" / "rocknovels.json"
    add("寫作連結", OK if refs.exists() else WARN, "已建索引" if refs.exists() else "沒有建置", "scripts/jiezi writing-refs build")
    try:
        import lunar_python  # noqa: F401,PLC0415
        add("農曆", OK, "lunar-python 已安裝")
    except ImportError:
        add("農曆", WARN, "lunar-python 未安裝（農曆問題會提示安裝）", "uv add lunar-python==1.4.9")
    if shutil.which("claude"):
        add("請教 Claude", OK, "Claude Code CLI 可用")
    else:
        add("請教 Claude", WARN, "找不到 claude 指令（自動請教停用）", "安裝並登入 Claude Code")
    free = shutil.disk_usage(root).free / 2**30
    add("磁碟空間", OK if free > 10 else WARN, f"剩 {free:.1f} GiB", "清理 var/ 或 models/")
    return out


def report(root: Path, port: int) -> tuple[str, int]:
    rows = checks(root, port)
    icon = {OK: "✓", WARN: "!", FAIL: "✗"}
    lines = [f"{icon[s]} {item}：{detail}" + (f"  →  {fix}" if fix and s != OK else "") for item, s, detail, fix in rows]
    fails = sum(1 for r in rows if r[1] == FAIL)
    warns = sum(1 for r in rows if r[1] == WARN)
    lines.append(f"\n{len(rows)} 項：{fails} 個需要修復、{warns} 個提醒 / {fails} failing, {warns} warnings")
    return "\n".join(lines), 1 if fails else 0

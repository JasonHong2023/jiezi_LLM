"""OpenAI 相容的本機 gateway（規格 gateway、escalation、trajectory；add-gateway design D3、D5–D7）。
The local OpenAI-compatible gateway (specs gateway, escalation, trajectory; design D3, D5–D7).

端點 / Endpoints：
  POST /v1/chat/completions   三種策略：jiezi、jiezi-local、jiezi-cloud（含串流）/ three policies (streaming too)
  GET  /v1/models             列出策略 / lists the policies
  GET  /health                狀態（不含機密）/ state (no secrets)
  POST /v1/documents          上傳文件、回傳文字（桌面網頁附檔用）/ upload a document, get its text (desktop page)
  POST /admin/unload          卸載引擎，可暫停到指定時間（夜間評測用）/ unload, optionally hold (night evaluations)

串流的取捨（design D5）：請求帶 `tools` 時，先完整取得並驗證答案，再以串流格式送出；沒有 `tools` 時直接轉送本機
串流，驗證只事後記錄、不重試。
Streaming trade-off (design D5): with `tools`, the answer is fetched and verified first, then sent in stream
format; without `tools`, the local stream is relayed directly and verification is only recorded afterwards."""

from __future__ import annotations

import asyncio
import contextlib
import json
from contextvars import ContextVar
import re
import secrets
import time
from datetime import datetime
from typing import AsyncIterator

import anyio
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from ..textconv import TaiwanStream, to_taiwan, to_traditional
from . import consult as consult_mod
from . import escalation
from .settings import POLICIES, Settings

# 一定要上網或即時資料的問題（比記憶的 WEB 嚴格：「我今天心情不好」不算）
# Questions that truly need the web or live data (stricter than memory's WEB)
LIVE = re.compile(r"https?://|網址|網頁|網站|新聞|天氣|氣溫|下雨|颱風動態|股價|匯率|油價|最新消息|即時|"
                  r"現在幾點|上網查|網路上(找|查|搜)|搜尋一下")
# 優先走雲端免費模型的轉交原因（使用者 2026-11-18）/ escalation reasons that go to the free cloud models first
WEB_MEMO_CHARS = 6000   # 整理重點時給本機看的網頁字數（本機上下文 4,096 token）/ page characters for the summary
WEB_MEMO_PROMPT = ("下面是網頁〈{title}〉（{url}）的文字。請用繁體中文整理成可以記住的重點：先一句話說明這個網頁是什麼，"
                   "再用 5 到 12 點條列主要內容（名稱、用途、重要數字或步驟），只寫網頁裡有的，不要加入網頁沒有的內容。"
                   "\n\n網頁文字：\n{text}")
CANT_READ = re.compile(r"無法(讀取|解析|存取|瀏覽)|看不到|亂碼|讀不到|corrupt|cannot (read|access)", re.I)
CLOUD_FIRST = frozenset({"context_too_large", "engine_unavailable"})
# 抱怨或回饋，不是要答案的問題 / complaints and feedback rather than questions
FEEDBACK = re.compile(r"又(出現|變成|是|有)|怎麼又|還是(有|一樣|錯)|不要再|你又|你剛剛|你剛才|講過了|說過了")
# 代理程式請模型摘要或下標題時，把整段對話貼成「User: … Assistant: …」；這不是要上網的問題（2026-11-18 Hermes 誤判）
# Agents paste the conversation as "User: … Assistant: …" to get a title or summary; that is not a web question
TRANSCRIPT = re.compile(r"(^|\n)\s*(User|使用者)\s*[:：].*?\n\s*(Assistant|助理)\s*[:：]", re.S)
CORRECTION_DIRECT = 0.5


def message_text(m: dict) -> str:
    """訊息的文字部分（多段內容只取文字）。 / The text of a message (text parts of multi-part content)."""
    c = m.get("content")
    if isinstance(c, list):
        return "\n".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text").strip()
    return c if isinstance(c, str) else ""


from ..memory import CREATIVE, WEB_MEMO_QUESTION  # noqa: E402 - 創作類請求、網頁記憶句型 / creative requests, web memo wording


# 系統附在回答後面的附錄（辭典原文、計算、參考資料…）。對話紀錄送回模型前要拿掉，否則模型會照抄格式自己寫一段，
# 系統再附一段，變成兩個「【計算】」（使用者 2026-11-18：「對話紀錄怎麼回答怪怪的」）
# Appendices the gateway adds after answers; removed from the history before the model sees it, or the model imitates
# them and the user gets two of each
APPENDIX = re.compile(r"\n*-{3,}[ \t]*\n【(?:字詞轉換|辭典原文|法規原文|參考資料|計算|記憶|課綱資料原文|延伸閱讀)】[\s\S]*\Z")


def strip_appendix(text: str) -> str:
    return APPENDIX.sub("", text) if isinstance(text, str) else text


def has_images(body: dict) -> bool:
    return any(isinstance(m.get("content"), list) and any(
        isinstance(p, dict) and p.get("type") in ("image_url", "input_image") for p in m["content"])
        for m in body.get("messages") or [])
EMBED_MAX_INPUTS, EMBED_MAX_CHARS = 64, 8000  # 問題和更正過的問題相似到這個程度，就直接照更正回答 / serve a correction at this similarity
from .supervisor import EngineUnavailable, Supervisor
from .trajectory import TrajectoryWriter, elapsed, new_id, now_iso

MAX_PATH_DOC_CHARS = 1_500_000  # gateway 讀路徑附上的文件總字數（同 jiezi chat）/ total characters of documents read from paths
MAX_WARM_BYTES = 8 * 1024 * 1024  # 預先建向量的文字上限 / text limit for warming
TOO_LARGE_ROOM = 128            # 至少要留這麼多 token 給回答 / tokens that must remain for an answer
TICK_S = 5.0
COST_HEADER = "x-litellm-response-cost"


# 帶工具的請求給本機模型的提醒（add-strong-tool-calling）：2026-11-17 ACEBench 走 gateway 錯的 17 題裡，6 題是把參數值
# 轉成繁體（預設系統提示要求繁體回答）、2 題把地名翻成英文、7 題自己補了使用者沒給的選填參數。
# Note for tool requests: of 17 misses, 6 converted argument values to Traditional (the default prompt asks for
# Traditional answers), 2 translated values to English and 7 invented optional parameters.
TOOL_NOTE = ("[呼叫工具的規則]\n"
             "1. 參數值照使用者的原文填：使用者寫簡體就填簡體、寫中文就填中文，不要翻譯、不要轉成繁體或換成同義詞"
             "（「用繁體中文回答」只適用於一般文字回答，不適用於參數值）。\n"
             "2. 只填必填參數和使用者明確提供的參數；使用者沒提到的選填參數一律省略，不要自己補預設值或猜測值。\n"
             "3. 數值照使用者給的數字填（使用者說 25% 就填 25），除非參數說明明確要求別的格式。\n"
             "4. 使用者一次要求多件事時，每件事各呼叫一次。")


OCR_TIMEOUT_S = 30.0     # 圖中文字（含第一次載入模型）/ OCR, first load included
VISION_TIMEOUT_S = 45.0  # 看圖工具（含第一次載入模型）最多等多久 / vision tools, first model load included
TILE_TIMEOUT_S = 30.0    # 切塊逐塊看：每塊的時限 / per tile
TILE_BUDGET_S = 90.0     # 切塊逐塊看：全部的時限，超過的塊略過 / all tiles; later tiles are skipped
THINK_MAX_TOKENS = 3072  # 階梯的思考模式：思考加回答的 token 上限 / think rung: tokens for thinking plus the answer
# 本機說「不確定」時重答的提醒 / the note for retrying an "unsure" answer
UNSURE_NOTE = ("你上一次回答說不確定。請再仔細想一次：先看附上的資料與題目，用你確實知道的知識回答；"
               "如果真的不知道，才說不確定，並說明缺什麼資訊。")


def _err(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": code, "code": code}}, status_code=status)


def _sse(obj) -> bytes:
    return b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n"


# ── 進度事件（add-progress-events）/ Progress events ──
# 串流請求一進來就等著：處理過程第一次回報階段時才開始串流（之前發生的錯誤照樣回 HTTP 錯誤碼），
# 之後的階段以 object="jiezi.progress"、choices=[] 的事件送出，一般 OpenAI 用戶端會略過。
# Streamed requests start streaming at the first reported stage (earlier errors keep their HTTP codes); stages are
# sent as object="jiezi.progress" events with empty choices, which generic OpenAI clients skip.
STAGES = ("loading_model", "reading_documents", "looking", "thinking", "retrying", "thinking_hard", "asking_claude",
          "asking_cloud",
          "asking_feedback")


class _Progress:
    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.started = asyncio.Event()
        self.enabled = False            # 只有串流請求才開 / streamed requests only
        self.relaying = False           # 已在轉送內層串流：改由內層直接送事件 / the inner stream emits directly

    def emit(self, stage: str) -> None:
        if not self.enabled or self.relaying:
            return

        def put() -> None:
            self.queue.put_nowait(stage)
            self.started.set()
        try:
            if asyncio.get_running_loop() is self.loop:
                put()
                return
        except RuntimeError:
            pass
        self.loop.call_soon_threadsafe(put)   # 從工作執行緒回報 / from a worker thread


_PROGRESS: ContextVar[_Progress | None] = ContextVar("jiezi_progress", default=None)


def _stage(stage: str) -> None:
    p = _PROGRESS.get()
    if p is not None:
        p.emit(stage)


def _progress_chunk(stage: str) -> bytes:
    return _sse({"id": f"progress-{int(time.time() * 1000)}", "object": "jiezi.progress", "created": int(time.time()),
                 "choices": [], "jiezi_progress": {"stage": stage}})


def _inline_progress(stage: str) -> bytes | None:
    """內層串流（轉送本機、接著轉交）自己送的進度事件；沒開進度時回傳 None。
    A progress event emitted by an inner stream; None when progress is off for this request."""
    p = _PROGRESS.get()
    return _progress_chunk(stage) if p is not None and p.enabled else None


def _bare_question(text: str) -> str:
    """稽核清單只顯示問題：附加的文件換成「〔附文件：檔名〕」。 / The audit list shows the question; documents become a tag."""
    from ..documents import DOC_RE
    names = [m.group("name") for m in DOC_RE.finditer(text or "")]
    q = DOC_RE.sub("", text or "").strip()
    return (f"〔附文件：{'、'.join(names)}〕" if names else "") + q


def _message(resp: dict) -> dict:
    return ((resp.get("choices") or [{}])[0].get("message")) or {}


def _tps(resp: dict) -> float | None:
    t = (resp.get("timings") or {}).get("predicted_per_second")
    return round(float(t), 2) if t else None


class Gateway:
    def __init__(self, settings: Settings, supervisor: Supervisor, trajectories: TrajectoryWriter,
                 local_http: httpx.AsyncClient | None = None, cloud_http: httpx.AsyncClient | None = None,
                 cap: escalation.DailyCap | None = None, consultant=None, log=print, embedder=None,
                 reranker=None):
        self.s, self.sup, self.traj, self.log = settings, supervisor, trajectories, log
        self.consultant = consultant
        self.vision = None              # 本機看圖工具（add-vision-tools）/ local vision tools
        self._seen: dict[str, object] = {}   # 請求 id → 圖片工具結果（不寫進軌跡）/ per request, not logged
        if settings.vision_tools:
            from ..vision_tools import VisionTools
            vt = VisionTools(settings.models_dir or settings.root / "models")
            if vt.available():
                self.vision = vt
            else:
                log("vision tools: models/vision not found; run the vision download first")
        self.ocr = None                 # 圖中文字（add-vision-tools OQ4、add-image-ocr，RapidOCR＋PP-OCRv5）/ text in images
        self.ocr_mode = getattr(settings, "image_ocr", "tools")
        self._long_lock = anyio.Lock()   # add-long-context：同時一個長請求 / one long request at a time
        if self.ocr_mode in ("auto", "on") or (self.ocr_mode == "tools" and settings.vision_tools):
            from ..vision_ocr import OcrTool
            ot = OcrTool(settings.models_dir or settings.root / "models")
            if ot.available():
                self.ocr = ot
            else:
                log("vision ocr: models/vision/ppocrv5 or the ocr packages not found (uv sync --group ocr --inexact)")
        if consultant is None and settings.consult == "claude-cli":
            self.consultant = consult_mod.ClaudeCliConsultant(settings.var / "runtime" / "consult-cwd",
                                                              settings.consult_timeout_s, settings.consult_model,
                                                              web=settings.consult_web)
        self.dictionary, self.dictionary_note = None, None
        if settings.dictionary:
            from ..dictionary import Dictionary, db_path
            try:
                self.dictionary = Dictionary(db_path(settings.root))
            except Exception as exc:  # noqa: BLE001 - 沒建置就跳過 / skipped when not built
                self.dictionary_note = str(exc)
        self.curriculum, self.curriculum_note = None, None
        if settings.curriculum:
            from ..curriculum import Graph
            try:
                self.curriculum = Graph.load(settings.root)
            except Exception as exc:  # noqa: BLE001 - 沒建置就跳過 / skipped when not built
                self.curriculum_note = str(exc)
        self.core_vision = False  # 核心是否有視覺模組（add-vision）/ whether the core has a vision projector
        try:
            from .supervisor import resolve_core
            self.core_vision = bool(resolve_core(settings).get("vision"))
        except Exception:  # noqa: BLE001 - 核心沒裝好時 supervisor 會另外報錯 / reported elsewhere
            pass
        self.memory, self.memory_note = None, None
        if settings.memory:
            from ..memory import Memory, wiki_path
            try:
                self.memory = Memory(wiki_path(settings.root), settings.root)
            except Exception as exc:  # noqa: BLE001 - 記憶壞了不影響回答 / a broken memory never blocks answers
                self.memory_note = str(exc)
        self.experience = None
        if settings.memory and getattr(settings, "experience", False):
            from ..experience import Experience
            from ..memory import wiki_path as _wp
            self.experience = Experience(_wp(settings.root))
        self.knowledge, self.knowledge_note = None, None
        if settings.knowledge:
            from ..knowledge import Knowledge, db_path as knowledge_db
            try:
                self.knowledge = Knowledge(knowledge_db(settings.root))
            except Exception as exc:  # noqa: BLE001 - 沒建置就跳過 / skipped when not built
                self.knowledge_note = str(exc)
        self.skills = None
        if settings.skills:
            from ..skills import Skills, skills_path
            self.skills = Skills(skills_path(settings.root), settings.root)
        self.laws, self.laws_note = None, None
        if settings.laws:
            from ..laws import Laws, db_path as laws_db
            try:
                self.laws = Laws(laws_db(settings.root))
            except Exception as exc:  # noqa: BLE001 - 沒建置就跳過 / skipped when not built
                self.laws_note = str(exc)
        self.embedder, self.hybrid, self.rag_note, self.laws_hybrid = embedder, None, "off", None
        self.reranker = reranker if settings.rerank else None  # add-reranker：預設關 / off by default
        self.doc_vectors = None  # 長文件段落向量（add-semantic-chunks）/ chunk vectors of attached documents
        if settings.doc_semantic and embedder is not None:
            from ..longdoc import ChunkVectors
            self.doc_vectors = ChunkVectors(embedder.embed)
        if settings.rag and self.knowledge is not None and embedder is not None:
            from ..rag import HybridRetriever, VectorStore, vectors_path
            try:
                store = VectorStore(vectors_path(settings.root))
                if store.count():
                    from ..rag import doc_text
                    kn = self.knowledge
                    self.hybrid = HybridRetriever(kn, store, embedder, settings.rag_min, reranker=self.reranker,
                                                  text_of=lambda i: doc_text(kn.section(i)))
                    self.rag_note = f"on ({store.count()} vectors)"
                else:
                    self.rag_note = "no vectors; run scripts/jiezi knowledge embed"
            except Exception as exc:  # noqa: BLE001 - 沒有向量就用全文 / full text without vectors
                self.rag_note = str(exc)
        if settings.rag and self.laws is not None and embedder is not None:
            from ..laws import doc_text as law_text, vectors_path as law_vectors
            from ..rag import HybridRetriever, VectorStore
            try:
                store = VectorStore(law_vectors(settings.root))
                if store.count():
                    lw = self.laws
                    self.laws_hybrid = HybridRetriever(lw, store, embedder, settings.laws_rag_min,
                                                       reranker=self.reranker,
                                                       text_of=lambda i: law_text(lw, i))
                    self.rag_note += f"; laws {store.count()} vectors"
            except Exception:  # noqa: BLE001 - 沒有法規向量就用全文 / full text without law vectors
                pass
        self.writing, self.writing_note = None, None
        if settings.writing_refs:
            from ..writing_refs import WritingRefs, index_path
            try:
                self.writing = WritingRefs(index_path(settings.root))
            except Exception as exc:  # noqa: BLE001 - 沒建置就跳過 / skipped when not built
                self.writing_note = str(exc)
        from ..longdoc import NotesCache
        self.last_tps: float | None = None
        self._doc_limit = anyio.Semaphore(1)  # 一次只讀一份上傳的文件 / one uploaded document at a time
        self.doc_notes = NotesCache()  # 長文件各段重點（只在記憶體）/ per-chunk notes of long documents, memory only
        self.consult_cap = escalation.DailyCap(settings.var / "runtime" / "consult", settings.consult_daily_max) \
            if settings.consult_daily_max else None
        timeout = httpx.Timeout(settings.request_timeout_s, connect=10.0)
        self.local = local_http or httpx.AsyncClient(timeout=timeout)
        self.cloud = cloud_http or httpx.AsyncClient(timeout=timeout)
        self.cap = cap or escalation.DailyCap(settings.var / "runtime", settings.cloud_daily_max)
        self.tts = None                 # 語音合成（add-tts，JIEZI_TTS=on）/ speech synthesis
        if settings.tts:
            from ..tts.manager import TTSManager
            self.tts = TTSManager(settings, supervisor, log=log)
        self.notebooks = None           # 筆記本（add-notebooks）/ notebooks of sources
        if settings.notebooks:
            from ..notebooks.store import NotebookStore
            self.notebooks = NotebookStore(settings.var / "notebooks")
        self.asr = None                 # 語音辨識（add-asr，JIEZI_ASR=on）/ speech recognition
        if settings.asr:
            from ..asr.manager import ASRManager
            self.asr = ASRManager(settings, supervisor, log=log)

    # ── 共用 / Common ──
    def _authorized(self, request: Request) -> bool:
        h = request.headers.get("authorization", "")
        return h.startswith("Bearer ") and secrets.compare_digest(h[7:].strip().encode(), self.s.key.encode())

    async def _read_json(self, request: Request) -> dict | JSONResponse:
        n = request.headers.get("content-length")
        if n and n.isdigit() and int(n) > self.s.request_max_bytes:
            return _err(413, f"request larger than {self.s.request_max_bytes} bytes", "request_too_large")
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > self.s.request_max_bytes:
                return _err(413, f"request larger than {self.s.request_max_bytes} bytes", "request_too_large")
        try:
            data = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            return _err(400, f"invalid JSON: {exc.msg}", "invalid_request")
        if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
            return _err(400, "body must be a JSON object with a messages list", "invalid_request")
        # 客戶端沒有給 system 訊息時，加上預設的身分與語言提示（design D10）
        # Without a client system message, add the default identity and language prompt (design D10)
        if self.s.system_prompt and not any(m.get("role") == "system" for m in data["messages"]):
            data["messages"] = [{"role": "system", "content": self.s.system_prompt}, *data["messages"]]
        return data

    def _local_body(self, body: dict, messages: list | None = None, stream: bool = False) -> dict:
        out = {k: v for k, v in body.items() if k not in ("model", "stream", "stream_options", "jiezi_translate")}
        out["model"] = self.sup.core["name"] if self.sup.core else self.s.core_model
        msgs = messages if messages is not None else body["messages"]
        if body.get("tools") and self.s.tool_note:  # add-strong-tool-calling；放在用戶端的 system 之後 / after the client's
            msgs = [*msgs, {"role": "system", "content": TOOL_NOTE}]  # merge_system 會併到開頭 / merged to the front
        # 每個槽位 4096 token：超出就裁（最舊對話 → 最長資料 → 問題）/ fit the 4096-token slot
        from .context import fit, merge_system
        out["messages"], trim = fit(msgs, body.get("tools"), body.get("max_tokens") or body.get("max_completion_tokens"),
                                    ctx=self._ctx(body))
        out["messages"] = merge_system(out["messages"])  # 範本只接受開頭的 system 訊息 / templates want one leading system message
        if trim["dropped_turns"] or trim["shortened_data"] or trim["shortened_question"]:
            self.log(f"context: trimmed {trim}")
        out["stream"] = stream
        out.setdefault("chat_template_kwargs", {"enable_thinking": False})  # 預設關閉思考 / thinking off by default
        return out

    async def _local_once(self, base: str, body: dict, messages: list | None = None) -> dict:
        r = await self.local.post(f"{base}/v1/chat/completions", json=self._local_body(body, messages))
        r.raise_for_status()
        data = r.json()
        self.last_tps = _tps(data) or self.last_tps  # 給翻譯預估時間用 / for translation estimates
        conv = to_taiwan if self.s.tw_phrases else to_traditional
        for ch in data.get("choices") or []:  # 本機輸出的純簡體字轉繁體 / Simplified-only chars → Traditional
            msg = ch.get("message") or {}
            if body.get("response_format") and msg.get("content"):  # JSON：只轉值，鍵不動 / values only, keys untouched
                from .jsonout import convert_values
                msg["content"] = convert_values(msg["content"], conv)
            else:
                msg["content"] = conv(msg.get("content"))
            if msg.get("tool_calls") and self.s.tool_note:  # 參數值還原成使用者原文 / user's wording for argument values
                from .toolargs import restore_calls
                if fixed := restore_calls(msg, body["messages"]):
                    self.log(f"tool args: restored {len(fixed)} value(s) to the user's wording")
        return data

    async def _cloud_once(self, body: dict) -> tuple[dict, dict]:
        """依序嘗試轉交模型；回傳 (回應, 雲端資訊)。 / Try escalation models in order; return (response, info)."""
        headers = {"Authorization": f"Bearer {self.s.cloud_key}"} if self.s.cloud_key else {}
        payload = {k: v for k, v in body.items()
                   if k not in ("model", "stream", "stream_options", "chat_template_kwargs", "jiezi_translate")}
        last = None
        for model in self.s.escalation_models:
            try:
                r = await self.cloud.post(f"{self.s.cloud_base}/v1/chat/completions", headers=headers,
                                          json={**payload, "model": model, "stream": False})
                r.raise_for_status()
                data = r.json()
                cost = r.headers.get(COST_HEADER)
                return data, {"model": data.get("model") or model, "usage": data.get("usage"),
                              "cost": float(cost) if cost else None}
            except (httpx.HTTPError, ValueError) as exc:
                last = f"{model}: {type(exc).__name__}: {exc}"
                self.log(f"cloud escalation failed on {last}")
        raise httpx.HTTPError(last or "no escalation model configured")

    def _can_escalate(self) -> str | None:
        """None 表示可以轉交；否則回傳原因。 / None means escalation is allowed; otherwise the reason."""
        if not self.s.cloud_ready:
            return "cloud_escalation_off"
        if not self.cap.available():
            return "daily_cap_reached"
        return None

    def _consult_ready(self) -> bool:
        return self.consultant is not None and (self.consult_cap is None or self.consult_cap.available())

    def _auto_route(self) -> str | None:
        """自動轉交的去處：先請教 Claude（開啟自動請教時），否則雲端；都不行回傳 None。
        Where automatic escalation goes: Claude first (when auto-consult is on), else the cloud; None if neither."""
        if self.s.consult_auto and self._consult_ready():
            return "consult"
        if self._can_escalate() is None:
            return "cloud"
        return None

    @staticmethod
    def _keep_local(help_reason: str | None, body: dict, rec: dict) -> str | None:
        """本機說「不確定」也不轉交的情況（2026-11-18 轉交紀錄分析）：只打路徑沒附檔（「看不到，請附上」就是正確答案）、
        問芥子自己（「你知道你在哪裡嗎」）、抱怨或回饋（「又出現簡體中文字」）——Claude 也不會答得更好。
        When "unsure" is still the right local answer: a bare path, a question about Jiezi, or feedback."""
        if help_reason != "self_reported_unsure":
            return help_reason
        if rec.get("path_note"):
            return None
        from ..memory import SELF
        last = next((m for m in reversed(body.get("messages") or []) if m.get("role") == "user"), None)
        q = message_text(last) if last else ""
        if SELF.search(q) or FEEDBACK.search(q):
            rec["kept_local"] = "about_jiezi" if SELF.search(q) else "feedback"
            return None
        return help_reason

    def _route_for(self, reason: str) -> str | None:
        """依轉交原因選去處：本機放不下（Hermes 等代理程式的大請求）或本機被評測保留時，雲端開著就先走雲端免費模型，
        不用 Claude（使用者 2026-11-18：「轉給 Claude 的次數這個一定要降低」，選「改轉雲端免費模型」）。
        Requests the local model cannot hold, or a reserved engine, go to the free cloud models first when available."""
        if reason in CLOUD_FIRST and self._can_escalate() is None:
            return "cloud"
        return self._auto_route()

    def _no_route_reason(self) -> str:
        if self.s.consult_auto and self.consultant is not None:
            return "consult_daily_cap"
        return self._can_escalate() or "no_escalation_route"

    async def _escalate(self, body: dict, rec: dict, t0: float, stream: bool, reason: str) -> Response:
        """自動轉交（design D5、D9）：Claude 失敗時改用雲端，再不行就回本機答案。
        Automatic escalation: on Claude failure try the cloud, else return the local answer."""
        if self._route_for(reason) == "consult":
            _stage("asking_claude")
            try:
                resp, info = await self._consult_once(body)
            except consult_mod.ConsultError as exc:
                rec["tiers"].append({"tier": 3, "provider": "claude", "error": str(exc)})
                if self._can_escalate() is None:
                    return await self._respond_cloud(body, rec, t0, stream, reason=reason)
                return self._fallback_local(rec, t0, stream, "consult_failed", f"cannot consult Claude: {exc}")
            return self._deliver_consult(body, rec, t0, stream, resp, info, tier=3, reason=reason)
        return await self._respond_cloud(body, rec, t0, stream, reason=reason)

    def _fallback_local(self, rec: dict, t0: float, stream: bool, why: str, message: str) -> Response:
        local = next((t for t in reversed(rec["tiers"]) if t.get("answer") and t.get("provider") is None), None)
        if local:
            fake = {"object": "chat.completion", "model": local.get("model"),
                    "choices": [{"index": 0, "message": local["answer"], "finish_reason": "stop"}]}
            meta = self._meta(rec, local["tier"], fake, local.get("verification"), t0, escalation=why)
            return self._deliver(fake, meta, rec, stream)
        return self._finish_error(rec, 502, message, why)

    def _ground(self, body: dict, rec: dict, data: list | None = None) -> None:
        """詞語問題查本機辭典、課綱問題查知識圖譜，把原文附給模型（add-dictionary D2、D3；add-curriculum D2、D3）。
        Attach verbatim dictionary entries for word questions and curriculum-graph data for curriculum questions."""
        if body.get("tools") or (not self.s.tools and all(x is None for x in (
                self.memory, self.dictionary, self.curriculum, self.knowledge, self.writing, self.laws))):
            return
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        if not last:
            return
        if isinstance(last.get("content"), list):  # 圖片訊息：用文字部分查資料 / image messages: use the text parts
            text = message_text(last)
            if not text:
                return
            # 有圖片時問題是在問圖，同樣不撈模糊命中（2026-11-17 實測：看圖題被附上不相干的知識庫文章，驗證判失敗）
            # With an image the question is about the image: no fuzzy hits either (a live false failure)
            img = any(isinstance(p, dict) and p.get("type") in ("image_url", "input_image") for p in last["content"])
            last = {"role": "user", "content": text, "_target": last, "_doc": img, "_img": img}
        elif not isinstance(last.get("content"), str):
            return
        else:
            from ..longdoc import needed, split_message
            if needed(last["content"]):  # 長文件：只用問題查資料 / long documents: look up with the question only
                _, q = split_message(last["content"])
                if not q:
                    return
                last = {"role": "user", "content": q, "_target": last, "_doc": True}
        from ..memory import SELF
        if SELF.search(last["content"] or ""):
            # 問芥子自己：系統提示已經寫好，不附知識庫（2026-11-18 實測：「自我介紹」撈到 Taiwan.md 的自我介紹文章，
            # 芥子說自己能查「創始人吳哲宇」，被判沒有依據而轉給 Claude）
            # Questions about Jiezi itself use the system prompt only (a live test pulled in Taiwan.md's self-introduction)
            rec["grounding_skipped"] = "about_jiezi"
            return
        if rec.get("notebook") and self.notebooks is not None:
            # 筆記本模式：只用這本筆記本的段落＋使用者更正（不附知識庫、辭典與舊答案）
            # Notebook mode: only this notebook's passages plus the user's corrections
            self._notebook_ground(body, rec, last, data)
            return
        tool_grounded = None
        if self.s.tools:
            from ..tools import grounding as tool_grounding
            tool_grounded = tool_grounding(last["content"], laws=self.laws)
            if tool_grounded is not None:
                rec["grounded_by_tools"] = True
        found = []
        # 附了長文件：問題是在問文件，不用語意向量去知識庫／法規撈「看起來相關」的段落（2026-11-17 實測會蓋過文件、
        # 佔掉上下文）；問題裡直接點名的文章或法條照樣附。
        # With a long document attached the question is about the document: no fuzzy vector hits from the knowledge base
        # or statutes (they crowded out the document in a live test); explicitly named articles still attach.
        doc = bool(last.get("_doc"))
        # 創作類（笑話、故事、寫詩…）不用語意向量撈「看起來相關」的知識庫／法規段落：撈到的文章跟題目無關，
        # 事後查核又把笑話內容判成「資料裡找不到」而轉給 Claude（2026-11-18 實測「說一個笑話」）；點名的文章照附
        # Creative requests get no fuzzy knowledge-base or statute hits (a live joke request was checked against them)
        if CREATIVE.search(last["content"] or ""):
            doc = True
            rec["grounding_fuzzy"] = "skipped: creative"
        # 看圖題的答案取決於這張圖，不用文字記憶（2026-11-18 實測：附圖再問，被附上之前「只打路徑」那題的答案）
        # An image question depends on the image: no text memory (a live test recalled the earlier path-only answer)
        if self.memory is not None and not last.get("_img") and not CREATIVE.search(last["content"] or ""):  # 記憶最優先
            from ..memory import recall_block
            found.append(recall_block(last["content"], self.memory, include_answer=tool_grounded is None))
        if getattr(self, "experience", None) is not None and not last.get("_img") \
                and not CREATIVE.search(last["content"] or ""):
            # 過去解題的經驗當提示（local-first-solving）/ lessons from earlier questions as hints
            try:
                from ..experience import hint_text
                lessons = self.experience.relevant(last["content"] or "")
            except OSError:
                lessons = []
            if lessons:
                rec["experience_used"] = [e.id for e in lessons]
                rec["experience_lessons"] = [e.lesson for e in lessons]
                found.append((hint_text(lessons), [], True, ""))
        if getattr(self, "memory", None) is not None and getattr(self.s, "web_read", False):
            # 問題提到記住過的網站：附上當時整理的重點（add-web-read）/ a remembered site is named: attach its summary
            from ..webread import recall as web_recall
            try:
                hits = web_recall(self.s.root, last["content"] or "")
            except (OSError, ValueError):
                hits = []
            for h in hits:
                found.append((f"以下是你先前讀過並記住的網頁重點（{h['url']}），可能已過時：\n{h['summary']}",
                              [{"source": "memory", "page": h.get("page") or h["url"], "kind": "web"}], False,
                              f"\n\n---\n【記憶】先前讀過的網頁：{h.get('title') or h['url']}（{h['url']}）"))
        if self.notebooks is not None and self.s.notebook_recall and not doc and not last.get("_img"):
            # 一般對話也查筆記本（使用者 2026-11-24 選自動查）/ normal chat recalls notebooks too
            try:
                from ..memory import wiki_path
                from ..notebooks.memory_link import recall_block as nb_recall
                got = nb_recall(self.notebooks, last["content"] or "",
                                self.embedder.embed_query if getattr(self, "embedder", None) else None,
                                wiki_path(self.s.root))
            except Exception as exc:  # noqa: BLE001 - 召回失敗照常回答 / recall failure never blocks
                self.log(f"notebook recall: {type(exc).__name__}: {exc}")
                got = None
            if got:
                rec["notebook_ctx"] = {**got[4], "recall": True, "general": True, "question": last["content"]}
                found.append(got[:4])
        if tool_grounded is not None:  # 程式算好的數字 / numbers computed by code
            found.append(tool_grounded)
        if self.dictionary is not None:
            from ..dictionary import grounding
            found.append(grounding(self.dictionary, last["content"]))
        if self.curriculum is not None:
            from ..curriculum import grounding as curriculum_grounding
            found.append(curriculum_grounding(self.curriculum, last["content"]))
        if self.laws is not None:
            from ..laws import grounding as laws_grounding
            if not doc or self.laws.law_in(last["content"][:2000]):
                found.append(laws_grounding(self.laws, last["content"], None if doc else self.laws_hybrid))
        if self.knowledge is not None:
            from ..knowledge import grounding as knowledge_grounding
            if not doc or self.knowledge.articles_named(last["content"]):
                found.append(knowledge_grounding(self.knowledge, last["content"], None if doc else self.hybrid))
        idx = body["messages"].index(last.get("_target", last))
        for g in found:
            if not g:
                continue
            content, sources, trainable, appendix = g
            body["messages"].insert(idx, {"role": "system", "content": content})
            if data is not None:  # 給防提示注入檢查用 / for the injection guard
                data.append(body["messages"][idx])
            idx += 1
            rec["grounding_text"] = (rec.get("grounding_text") or "") + "\n" + content
            rec["sources"] = (rec.get("sources") or []) + sources
            rec["dict_appendix"] = (rec.get("dict_appendix") or "") + appendix
            if not trainable:
                self._untrainable(rec, "license")  # 例如禁止改作的辭典 / e.g. a no-derivatives dictionary
        if self.writing is not None:
            w = self.writing.appendix(last["content"])
            if w:  # 只附連結，不給模型內文 / links only; no article text reaches the model
                rec["sources"] = (rec.get("sources") or []) + w[1]
                rec["dict_appendix"] = (rec.get("dict_appendix") or "") + w[0]

    # ── 防提示注入（add-injection-guard）/ Prompt-injection guard ──
    def _guard(self, body: dict, rec: dict, data: list[dict]) -> None:
        """文件、工具結果、附加資料都只是資料：清理、加上安全規則、偵測到可疑指示就標記這次請求。
        Documents, tool results and attached data are data only: clean, remind, and flag suspicious requests."""
        from .. import injection
        try:
            info = injection.guard(body["messages"], {id(m) for m in data})
        except Exception as exc:  # noqa: BLE001 - 檢查壞了不影響回答 / a broken check never blocks answers
            self.log(f"injection guard: {type(exc).__name__}: {exc}")
            return
        external = info["documents"] or info["tools"]
        if external or info["suspected"]:
            # 使用者附的文件、工具結果：一律加安全規則；gateway 自己查到的資料只有可疑時才加
            # User documents and tool results always get the rule; gateway data only when suspicious
            injection.add_reminder(body["messages"])
        if external or info["suspected"] or info["cleaned"]:
            rec["injection"] = {k: info[k] for k in ("documents", "tools", "suspected", "where", "cleaned")}
        if info["suspected"]:
            self._untrainable(rec, "injection")
            gate = self._trust_gate()  # 可疑內容進 taint index：之後同一段內容進記憶／技能會被擋（add-agent-trust-gate）
            for t in info.get("taints") or []:
                gate.register_hash(t["content_hash"], "request", t["where"], ",".join(info["suspected"]))
            self.log(f"injection guard: suspected {info['suspected']} in {info['where']}")

    async def _read_paths(self, body: dict, rec: dict) -> None:
        """使用者訊息裡打的本機檔案路徑由 gateway 讀檔附上（add-image-paths，使用者 2026-11-18「把你的方法教她，也加入
        base64」）：圖片轉 base64 data URL 附在同一則訊息，文件在受限子行程讀成文字、照 /file 的格式包進問題。
        只看最後一則使用者訊息、已附文件以外的文字；system／assistant／tool 訊息裡的路徑不讀。
        Paths typed in the last user message are read here: images become base64 data URLs, documents are read in the
        limited child process and wrapped like /file. Paths in other roles or inside attached documents are never read."""
        if not self.s.image_paths:
            return
        from .. import documents as D
        from ..localpaths import MAX_PATHS, PathError, find_paths, image_data_url, is_image, strip_paths, to_local
        msgs = body["messages"]
        idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
        if idx is None:
            return
        m = msgs[idx]
        text = message_text(m)
        paths = find_paths(D.DOC_RE.sub(" ", text))[:MAX_PATHS]
        if not paths:
            return
        images, docs, done, log = [], [], [], []
        for raw in paths:
            local, entry = to_local(raw), {"path": raw}
            try:
                if is_image(raw):
                    images.append(await anyio.to_thread.run_sync(image_data_url, local))
                else:
                    if not local.is_file():
                        raise PathError("not_found")
                    if local.stat().st_size > D.MAX_FILE_BYTES:
                        raise PathError("too_large")
                    async with self._doc_limit:
                        d = await anyio.to_thread.run_sync(D.read, local)
                    if not d["text"].strip():
                        raise PathError("no_text")
                    if sum(len(x["text"]) for x in docs) + len(d["text"]) > MAX_PATH_DOC_CHARS:
                        raise PathError("too_large")
                    docs.append(d)
                entry["ok"] = True
                done.append(raw)
            except PathError as exc:
                entry["why"] = str(exc)
            except D.DocumentError as exc:
                entry["why"] = f"unreadable: {str(exc)[:120]}"
            except OSError as exc:
                entry["why"] = type(exc).__name__
            log.append(entry)
        rec["image_paths"] = log
        if not done:
            return
        question = strip_paths(text, done)
        for d in docs:
            question = D.attach(d, question)
        others = [p for p in m["content"] if isinstance(p, dict) and p.get("type") != "text"] \
            if isinstance(m.get("content"), list) else []
        pics = [{"type": "image_url", "image_url": {"url": u}} for u in images]
        m["content"] = [{"type": "text", "text": question}, *others, *pics] if others or pics else question
        self.log(f"read paths: {len(images)} image(s), {len(docs)} document(s)")

    def _scrapling_page(self, url: str, why: str) -> dict | None:
        """opt-in 回退：web-fetch 讀不到時，用政策核准的 scrapling MCP 再試一次；只回中繼資料與清理後文字。
        Opt-in fallback: retry a failed web-fetch through the policy-cleared scrapling MCP, with metadata-only audit."""
        config = getattr(self.s, "scrapling", None)
        if config is None or not config.enabled:
            return None
        from urllib.parse import urlsplit

        from ..agent import audit
        from ..scrapling_mcp import Backend, build_adapter

        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            host = ""
        audit.write(self.s.root, {"tool": "make_request", "host": host, "decision": "fallback",
                                  "status": "selected", "backend": Backend.SCRAPLING, "why": why[:200]})
        adapter = build_adapter(config, self.s.root)
        try:
            text = adapter.fetch("make_request", url)
        except Exception as exc:  # noqa: BLE001 - 回退失敗不擋住原本的 web-read 錯誤 / fallback never blocks the answer
            self.log(f"scrapling fallback: {type(exc).__name__}: {exc}")
            return None
        finally:
            adapter.close()
        if not text.strip():
            return None
        return {"url": url, "final_url": url, "title": "", "text": text,
                "bytes": len(text.encode("utf-8"))}

    async def _read_urls(self, body: dict, rec: dict) -> None:
        """使用者訊息裡的網址由 gateway 在本機讀取，轉成文字當文件附上（add-web-read；使用者 2026-11-18：
        「仔細閱讀這個網址的內容並記憶起來」被轉給 Claude、本機又說讀不到）。只讀最後一則使用者訊息、附件以外的網址。
        URLs in the last user message are fetched locally and attached as documents (add-web-read)."""
        if not self.s.web_read:
            return
        from .. import documents as D
        from ..scrapling_mcp import Backend
        from ..webread import MEMO, WebError, fetch, find_urls
        msgs = body["messages"]
        idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
        if idx is None:
            return
        m = msgs[idx]
        text = message_text(m)
        urls = find_urls(D.DOC_RE.sub(" ", text))
        if not urls:
            return
        _stage("reading_documents")
        pages, log = [], []
        for url in urls:
            try:
                page = await fetch(url)
                pages.append(page)
                log.append({"url": url, "ok": True, "bytes": page["bytes"], "title": page["title"],
                            "backend": Backend.WEB_FETCH})
            except WebError as exc:
                page = await anyio.to_thread.run_sync(self._scrapling_page, url, str(exc))
                if page is not None:
                    pages.append(page)
                    log.append({"url": url, "ok": True, "bytes": page["bytes"], "title": page["title"],
                                "backend": Backend.SCRAPLING, "fallback_from": "web-fetch", "why": str(exc)})
                else:
                    log.append({"url": url, "why": str(exc)})
            except Exception as exc:  # noqa: BLE001 - 讀不到就照舊 / unreadable pages fall back to the old path
                log.append({"url": url, "why": type(exc).__name__})
        rec["web_read"] = log
        if not pages:
            return
        rec["web_read_ok"] = True
        self._untrainable(rec, "license")   # 網頁內容的授權不明 / page licences are unknown
        # 只在使用者剛問的那一輪記；代理程式之後每一步工具呼叫都會帶著同一則使用者訊息再來，不再重記（2026-11-26 實機：
        # Hermes 一個任務把同一批網頁記了約 30 次）。評測請求不寫記憶。
        # Remember only on the turn the user asked; later agent tool steps repeat the same user message (a live Hermes
        # task saved the same pages about 30 times). Evaluation requests never write memory.
        if MEMO.search(text) and idx == len(msgs) - 1 and not rec.get("eval"):
            rec["web_memo"] = [{"url": p["url"], "title": p["title"]} for p in pages]
            rec["_web_pages"] = [p["text"][:WEB_MEMO_CHARS] for p in pages]   # 摘要用，不寫進軌跡 / not logged
        question = text
        for page in pages:
            name = f"{page['title']}（{page['final_url']}）" if page["title"] else page["final_url"]
            question = D.attach({"name": name, "text": page["text"]}, question)
        others = [p for p in m["content"] if isinstance(p, dict) and p.get("type") != "text"] \
            if isinstance(m.get("content"), list) else []
        m["content"] = [{"type": "text", "text": question}, *others] if others else question
        self.log(f"read urls: {len(pages)} page(s)")

    def _web_memo(self, rec: dict) -> None:
        """使用者要記住網頁：在背景請本機把網頁整理成重點，存進記憶，之後相關問題會附上（add-web-read）。
        When asked to remember a page, the local model writes a summary in the background and it goes into memory."""
        if not rec.get("web_memo") or rec.get("_web_memo_done") or getattr(self, "memory", None) is None:
            return
        rec["_web_memo_done"] = True
        pages = rec.pop("_web_pages", None) or []
        rec["memory"] = {"saved": "pending", "why": "web_memo"}
        try:
            asyncio.get_running_loop().create_task(self._summarise_pages(rec["web_memo"], pages))
        except RuntimeError:
            pass

    async def _summarise_pages(self, memo: list[dict], pages: list[str]) -> None:
        for page, text in zip(memo, pages):
            summary = ""
            try:
                base = await self.sup.acquire()
                try:
                    r = await self.local.post(f"{base}/v1/chat/completions", json={
                        "model": self.sup.core["name"] if self.sup.core else self.s.core_model,
                        "messages": [{"role": "user", "content": WEB_MEMO_PROMPT.format(
                            title=page["title"] or page["url"], url=page["url"], text=text)}],
                        "temperature": 0.2, "max_tokens": 700, "chat_template_kwargs": {"enable_thinking": False}})
                    r.raise_for_status()
                    summary = strip_appendix(_message(r.json()).get("content") or "").strip()
                finally:
                    self.sup.release()
            except Exception as exc:  # noqa: BLE001 - 摘要失敗不影響回答 / never blocks answers
                self.log(f"web memo: summary failed: {type(exc).__name__}: {exc}")
            if not summary or escalation.needs_help({"content": summary}, "stop") or CANT_READ.search(summary[:300]):
                self.log(f"web memo: nothing stored for {page['url']}")
                continue
            title = page["title"] or page["url"]
            try:
                saved = await anyio.to_thread.run_sync(
                    self.memory.save_answer, WEB_MEMO_QUESTION.format(title=title),
                    f"{summary}\n\n（來源：{page['url']}，{now_iso()[:10]} 由芥子在本機讀取整理）", "local", None)
                from ..webread import remember
                await anyio.to_thread.run_sync(remember, self.s.root, page["url"], page["title"], summary, saved)
                self.log(f"web memo: saved {saved}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"web memo: {exc}")

    def _path_note(self, body: dict, rec: dict) -> None:
        """問題裡只打了本機檔案路徑、沒附檔：提醒模型看不到內容、不要猜（使用者 2026-11-18：模型憑 iStock 檔名猜了圖片內容）。
        A local path typed without attaching the file: tell the model it cannot see it and must not guess."""
        from ..documents import DOC_RE
        from ..localpaths import PATH_NOTE, find_paths
        if body.get("tools") or has_images(body):
            return
        msgs = body["messages"]
        idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
        if idx is None:
            return
        text = message_text(msgs[idx])
        if DOC_RE.search(text):          # 已附文件 / documents attached
            return
        paths = find_paths(text)
        if not paths:
            return
        msgs.insert(idx, {"role": "system", "content": PATH_NOTE.format(paths="、".join(paths[:3]))})
        rec["path_note"] = paths[:3]

    @staticmethod
    def _injected(rec: dict) -> bool:
        return bool((rec.get("injection") or {}).get("suspected"))

    # ── 記憶 / Memory（add-memory）──
    def _remember(self, body: dict, rec: dict, msg: dict, provider: str, model: str | None) -> None:
        """把請教／雲端的答案存進記憶 wiki；存不了不影響回答。 / Save to the memory wiki; failures never block."""
        if self.memory is None or body.get("tools") or rec.get("eval") or rec.get("json_mode"):
            return
        if has_images(body) or rec.get("path_note"):  # 答案取決於圖或沒附上的檔案 / depends on an image or missing file
            rec["memory"] = {"saved": False, "why": "image" if has_images(body) else "path_without_file"}
            return
        if self._injected(rec):  # 可疑資料影響過的答案不進記憶 / never remember an answer shaped by suspicious data
            rec["memory"] = {"saved": False, "why": "suspected_injection"}
            return
        from ..memory import storable
        users = [m["content"] for m in body["messages"] if m.get("role") == "user" and isinstance(m.get("content"), str)]
        if not users:
            return
        why = storable(users[-1], len(users) - 1)
        if why:
            rec["memory"] = {"saved": False, "why": why}
            return
        try:
            rec["memory"] = {"saved": True, "page": self.memory.save_answer(users[-1], msg.get("content") or "",
                                                                             provider, model)}
        except Exception as exc:  # noqa: BLE001
            rec["memory"] = {"saved": False, "why": f"error: {exc}"}
            self.log(f"memory: could not save: {exc}")

    def _memory_reply(self, rec: dict, t0: float, stream: bool, text: str, training: bool | None = None) -> Response:
        resp = {"id": f"chatcmpl-memory-{int(time.time() * 1000)}", "object": "chat.completion",
                "created": int(time.time()), "model": "jiezi-memory",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
        rec["tiers"].append({"tier": "memory", "answer": resp["choices"][0]["message"]})
        if training is False:
            self._untrainable(rec, "memory")
        meta = self._meta(rec, "memory", resp, None, t0)
        meta["provider"] = "memory"
        return self._deliver(resp, meta, rec, stream)

    def _memory_early(self, body: dict, rec: dict, t0: float, stream: bool, policy: str) -> Response | None:
        """「記住：…」「不對，…」直接處理；幾乎相同的問題直接用記憶回答；其餘附上「要記住的事」。
        Handle remember/correction messages, serve near-identical questions from memory, else attach notes."""
        from ..memory import CORRECTION, EXACT, REMEMBER, notes_prompt, similarity, storable
        msgs = body["messages"]
        users = [m for m in msgs if m.get("role") == "user" and isinstance(m.get("content"), str)]
        if not users:
            return None
        q = users[-1]["content"]
        try:
            m = REMEMBER.match(q)
            from ..webread import URL_RE
            if m and not (self.s.web_read and URL_RE.search(q)):   # 「記住＋網址」要先讀網頁 / read the page first
                self.memory.save_note(m.group(1))
                rec["sources"] = [{"source": "memory", "page": "使用者要我記住的事", "kind": "note"}]
                rec.pop("dict_appendix", None)
                return self._memory_reply(rec, t0, stream, f"好，我記住了：{m.group(1).strip()}\n"
                                          "（存在記憶 wiki 的〈使用者要我記住的事〉，可以用 Obsidian 修改或刪除）")
            m = CORRECTION.match(q)
            answered = any(x.get("role") == "assistant" for x in msgs)
            if m and len(users) >= 2 and answered:
                prev = users[-2]["content"]
                where = f"（於筆記本《{rec['notebook']['name']}》）" if rec.get("notebook") else ""
                page = self.memory.save_correction(prev, m.group(1).strip() + where)
                rec["sources"] = [{"source": "memory", "page": page, "kind": "correction"}]
                rec.pop("dict_appendix", None)
                return self._memory_reply(rec, t0, stream, f"好，已記下更正。之後問到「{prev.strip()[:60]}」會照這個說法回答："
                                          f"\n{m.group(1).strip()}")
            corrections = self.memory.corrections_for(q)
            best = max(corrections, key=lambda c: similarity(q, c.question), default=None)
            if policy in ("jiezi", "jiezi-local") and best and similarity(q, best.question) >= CORRECTION_DIRECT \
                    and len(users) == 1 and not rec.get("notebook"):
                # 使用者自己更正過的答案：直接照更正回答，不讓小模型再說錯 / answer with the user's own correction
                rec["sources"] = [{"source": "memory", "page": best.title, "kind": "correction"}]
                rec.pop("dict_appendix", None)
                return self._memory_reply(rec, t0, stream, f"根據你 {best.at[:10]} 的更正：{best.text}\n\n---\n"
                                          f"【記憶】[[{best.title}]]（問題：{best.question}）")
            if policy in ("jiezi", "jiezi-local") and storable(q, len(users) - 1) is None and not corrections \
                    and not rec.get("grounded_by_tools") and not rec.get("notebook"):
                found = self.memory.find_answer(q)
                if found and found[1] >= EXACT:
                    e = found[0]
                    rec["sources"] = [{"source": "memory", "page": e.title, "kind": "answer", "similarity": 1.0}]
                    rec.pop("dict_appendix", None)
                    return self._memory_reply(
                        rec, t0, stream, e.text + f"\n\n---\n【記憶】{e.at[:10]} 請教{e.provider}的答案（[[{e.title}]]）；"
                        "要重新請教，請說「這個不對」並附上正確說法，或用 jiezi chat --claude。", training=False)
            notes = notes_prompt(self.memory)
        except Exception as exc:  # noqa: BLE001 - 記憶壞了照常回答 / answer normally if memory fails
            self.log(f"memory: {exc}")
            return None
        if notes:
            lead = next((i for i, x in enumerate(msgs) if x.get("role") != "system"), len(msgs))
            msgs.insert(lead, {"role": "system", "content": notes})
        return None

    @staticmethod
    def _grounding(body: dict, rec: dict) -> str | None:
        """查核用的依據：附上的資料加上使用者說過的話；沒有附資料就不查。
        What the grounded check accepts: the attached data plus the user's own words; no data, no check."""
        if not rec.get("grounding_text"):
            return None
        said = "\n".join(m["content"] for m in body["messages"]
                          if m.get("role") == "user" and isinstance(m.get("content"), str))
        return rec["grounding_text"] + "\n" + said

    # ── 端點 / Endpoints ──
    async def models(self, request: Request) -> Response:
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        return JSONResponse({"object": "list", "data": [
            {"id": p, "object": "model", "owned_by": "jiezi"} for p in POLICIES]})

    async def health(self, request: Request) -> Response:
        return JSONResponse({"status": "ok", "engine": self.sup.describe(),
                             "consult": self.s.consult if self.consultant else "off",
                             "dictionary": "on" if self.dictionary else (self.dictionary_note or "off"),
                             "curriculum": "on" if self.curriculum else (self.curriculum_note or "off"),
                             "writing_refs": "on" if self.writing else (self.writing_note or "off"),
                             "knowledge": "on" if self.knowledge else (self.knowledge_note or "off"),
                             "rag": self.rag_note,
                             "rerank": self.reranker.note if self.reranker else "off",
                             "agent": "on" if self.s.agent else "off",
                             "laws": "on" if self.laws else (self.laws_note or "off"),
                             "memory": "on" if self.memory else (self.memory_note or "off"),
                             "tools": "on" if self.s.tools else "off",
                             "cloud_escalation": self.s.cloud_ready, "cloud_used_today": self.cap.used(),
                             "cloud_daily_max": self.s.cloud_daily_max,
                             "trajectory": {"enabled": self.traj.enabled, "error": self.traj.last_error},
                             "tts": self.tts.describe() if self.tts else "off",
                             "asr": self.asr.describe() if self.asr else "off"})

    # ── 語音合成（add-tts）/ speech synthesis ──
    # 這些欄位代表參考音檔或語者向量：聲音只能在本機 CLI 登錄，API 一律拒絕（不提供遠端聲音複製）
    # Fields that would carry reference audio or a speaker vector: voices are enrolled only through the local CLI
    TTS_FORBIDDEN = ("reference_audio", "reference_wav", "reference_wav_path", "ref_wav", "prompt_wav",
                     "prompt_wav_path", "speaker_embedding", "speaker_centroid", "audio", "voice_file", "voice_url")

    async def audio_speech(self, request: Request) -> Response:
        """OpenAI 相容的 /v1/audio/speech。 / OpenAI-compatible speech synthesis."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        if self.tts is None:
            return _err(404, "speech synthesis is off (set JIEZI_TTS=on)", "not_found")
        body = await self._read_json_any(request)
        if isinstance(body, Response):
            return body
        bad = [k for k in self.TTS_FORBIDDEN if k in body]
        voice = body.get("voice")
        if bad or (voice is not None and not isinstance(voice, str)):
            return _err(400, "voices can only be enrolled locally (scripts/jiezi tts voice add); requests cannot "
                             "carry reference audio, paths or speaker vectors", "invalid_voice")
        try:
            speed = float(body.get("speed", 1.0))
            pitch = float(body.get("pitch", 0.0))
        except (TypeError, ValueError):
            return _err(400, "speed and pitch must be numbers", "invalid_request")
        from ..tts.manager import TTSError
        try:
            data, mime, meta = await self.tts.speak(body.get("input"), voice, str(body.get("response_format", "wav")),
                                                    speed, pitch, clean=body.get("clean", True) is not False)
        except TTSError as exc:
            return _err(exc.status, str(exc), exc.code)
        self.log(f"tts: {meta['chars']} chars, voice {meta['voice']}, {meta['audio_s']} s audio in {meta['total_s']} s")
        return Response(data, media_type=mime, headers={"X-Jiezi-Audio-Seconds": str(meta.get("audio_s")),
                                                        "X-Jiezi-Voice": meta["voice"],
                                                        "X-Jiezi-File": str(self.tts.out_dir / meta["file"])})

    async def audio_transcriptions(self, request: Request) -> Response:
        """OpenAI 相容的 /v1/audio/transcriptions（multipart 的 file 欄位；也接受直接上傳音檔）。
        OpenAI-compatible transcription: multipart `file`, or a raw audio body."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        if self.asr is None:
            return _err(404, "speech recognition is off (set JIEZI_ASR=on)", "not_found")
        from ..asr.manager import FORMATS, MAX_BYTES, ASRError, render
        n = request.headers.get("content-length")
        if n and n.isdigit() and int(n) > MAX_BYTES + 1_000_000:
            return _err(413, f"the upload is larger than {MAX_BYTES >> 20} MB", "request_too_large")
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_BYTES + 1_000_000:
                return _err(413, f"the upload is larger than {MAX_BYTES >> 20} MB", "request_too_large")
        ctype = request.headers.get("content-type", "")
        fields, data, filename = {}, b"", request.query_params.get("name", "audio")
        if ctype.startswith("multipart/form-data"):
            from email.parser import BytesParser
            from email.policy import HTTP
            msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body)
            for part in msg.iter_parts() if msg.is_multipart() else []:
                name = part.get_param("name", header="content-disposition")
                payload = part.get_payload(decode=True) or b""
                if name == "file":
                    data, filename = payload, part.get_filename() or filename
                elif name:
                    fields[name] = payload.decode("utf-8", errors="replace")[:2000]
        else:
            data = body
            fields = {k: v for k, v in request.query_params.items()}
        fmt = fields.get("response_format", "json")
        if fmt not in FORMATS:
            return _err(400, f"response_format must be one of {', '.join(FORMATS)}", "invalid_request")
        try:
            res = await self.asr.transcribe(data, filename, fields.get("prompt"))
        except ASRError as exc:
            return _err(exc.status, str(exc), exc.code)
        self.log(f"asr: {res['audio_s']} s audio in {res['total_s']} s, {len(res['text'])} chars")
        text, mime = render(res, fmt)
        return Response(text, media_type=mime, headers={"X-Jiezi-Audio-Seconds": str(res["audio_s"])})

    async def audio_voices(self, request: Request) -> Response:
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        if self.tts is None:
            return _err(404, "speech synthesis is off (set JIEZI_TTS=on)", "not_found")
        from ..tts import voices as V
        return JSONResponse({"object": "list", "data": V.listing(self.s.var)})

    async def embeddings(self, request: Request) -> Response:
        """OpenAI 相容的 /v1/embeddings（add-embeddings-endpoint）：給客戶端做自己的檢索。
        `input_type: "query"` 會加上查詢指令前綴（Qwen3-Embedding 建議）。
        OpenAI-compatible embeddings for clients; `input_type: "query"` adds the query instruction."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        if self.embedder is None:
            return _err(503, "embedding model not available (see scripts/jiezi doctor)", "embeddings_unavailable")
        body = await self._read_json_any(request)
        if isinstance(body, Response):
            return body
        texts = body.get("input")
        texts = [texts] if isinstance(texts, str) else texts
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
            return _err(400, "input must be a string or a list of strings", "invalid_request")
        if len(texts) > EMBED_MAX_INPUTS or any(len(t) > EMBED_MAX_CHARS for t in texts):
            return _err(400, f"at most {EMBED_MAX_INPUTS} inputs of {EMBED_MAX_CHARS} characters", "invalid_request")
        from ..rag import EMBED_MODEL, QUERY_INSTRUCT
        if body.get("input_type") == "query":
            texts = [QUERY_INSTRUCT + t for t in texts]
        try:
            vecs = await anyio.to_thread.run_sync(self.embedder.embed, texts)
        except Exception as exc:  # noqa: BLE001
            return _err(502, f"embedding engine error: {exc}", "engine_error")
        return JSONResponse({"object": "list", "model": EMBED_MODEL,
                             "data": [{"object": "embedding", "index": i, "embedding": list(v)} for i, v in enumerate(vecs)],
                             "usage": {"prompt_tokens": sum(len(t) for t in texts), "total_tokens": sum(len(t) for t in texts)}})

    async def _read_json_any(self, request: Request) -> dict | Response:
        n = request.headers.get("content-length")
        if n and n.isdigit() and int(n) > self.s.request_max_bytes:
            return _err(413, f"request larger than {self.s.request_max_bytes} bytes", "request_too_large")
        try:
            data = json.loads(await request.body() or b"{}")
        except json.JSONDecodeError as exc:
            return _err(400, f"invalid JSON: {exc.msg}", "invalid_request")
        return data if isinstance(data, dict) else _err(400, "body must be a JSON object", "invalid_request")

    async def documents(self, request: Request) -> Response:
        """桌面網頁附檔（add-desktop-documents）：上傳一個檔案（原始位元組，`?name=檔名`），在受限的子行程讀成文字後回傳。
        檔案只暫存在 var/runtime/uploads，讀完就刪；一次只讀一份。
        Desktop attachments: upload one file (raw bytes, `?name=`), read it in the limited child process and return
        the text. The file is kept only while it is read; one at a time."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        import shutil
        import tempfile
        from pathlib import Path
        from .. import documents as D
        from ..injection import clean
        name = Path((request.query_params.get("name") or "").replace("\\", "/")).name[:200]
        suffix = Path(name).suffix.lower()
        if not name or suffix not in D.SUPPORTED:
            return _err(400, f"不支援的格式 {suffix or '（無副檔名）'}；支援 PDF、Word、PowerPoint、Excel（含舊版與 OpenDocument）、.html、純文字 / unsupported format",
                        "unsupported_document")
        n = request.headers.get("content-length")
        if n and n.isdigit() and int(n) > D.MAX_FILE_BYTES:
            return _err(413, f"檔案超過 {D.MAX_FILE_BYTES // 2**20} MB / file too large", "request_too_large")
        base = self.s.var / "runtime" / "uploads"
        base.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(dir=base))
        try:
            path, size = tmp / f"upload{suffix}", 0
            with path.open("wb") as f:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > D.MAX_FILE_BYTES:
                        return _err(413, f"檔案超過 {D.MAX_FILE_BYTES // 2**20} MB / file too large", "request_too_large")
                    f.write(chunk)
            if not size:
                return _err(400, "empty upload", "invalid_request")
            async with self._doc_limit:
                try:
                    d = await anyio.to_thread.run_sync(D.read, path)
                except D.DocumentError as exc:
                    return _err(422, str(exc), "document_unreadable")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        text, _ = clean(d["text"])  # 偽造的文件標記與零寬字元 / forged markers and invisible characters
        if not text.strip():
            return _err(422, "讀不到文字（可能是掃描檔且 OCR 失敗）/ no text found", "document_unreadable")
        self._warm(text)
        return JSONResponse({"name": name, "kind": d.get("kind"), "chars": len(text), "pages": d.get("pages"),
                             "ocr_pages": len(d.get("ocr_pages") or []), "warnings": d.get("warnings") or [],
                             "text": text})

    async def admin_trajectories(self, request: Request) -> Response:
        """桌面 App 的稽核紀錄（Phase 8.1）：最近的對話摘要，只讀、需要金鑰。
        Audit log for the desktop app: recent conversation summaries, read-only, key required."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        from .gaps import load
        try:
            limit = max(1, min(500, int(request.query_params.get("limit", "100"))))
        except ValueError:
            limit = 100
        # 依時間排序再取最近的（檔案是新的一天在前，直接取尾端會拿到最舊的；2026-11-17 實測）
        # Sort by time first: files come newest-day first, so slicing the tail returned the oldest records
        recs = sorted(load(self.s.root, 7), key=lambda r: r.get("at") or "")[-limit:]
        out = []
        for r in reversed(recs):
            users = [m for m in (r.get("request") or {}).get("messages") or [] if m.get("role") == "user"]
            out.append({"id": r.get("id"), "at": r.get("at"), "policy": r.get("policy"), "status": r.get("status"),
                        "final_tier": r.get("final_tier"), "training_use": r.get("training_use"),
                        "question": _bare_question(message_text(users[-1]))[:200] if users else "",
                        "sources": sorted({s.get("source") for s in r.get("sources") or [] if s.get("source")})})
        return JSONResponse({"records": out})

    async def admin_escalations(self, request: Request) -> Response:
        """最近 7 天每天轉給 Claude／雲端的次數與原因（狀態頁用）。 / Escalations per day for the status page."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        from .gaps import load
        from .stats import escalations
        return JSONResponse(await anyio.to_thread.run_sync(lambda: escalations(load(self.s.root, 7))))

    def memory_listing(self) -> dict:
        """記憶 wiki 主題與經驗清單（狀態頁用；local-first-solving 3.3）。只列標題、計數與摘要，不送全文。
        Memory topics and lessons for the status page: titles, counts and short text only."""
        topics = []
        if self.memory is not None:
            self.memory._scan()
            per: dict[str, dict] = {}
            for e in self.memory.entries:
                t = per.setdefault(e.title, {"title": e.title, "page": e.page, "qa": 0, "correction": 0, "note": 0,
                                             "updated": ""})
                t[e.kind] = t.get(e.kind, 0) + 1
                t["updated"] = max(t["updated"], e.at or "")
            topics = sorted(per.values(), key=lambda t: t["updated"], reverse=True)
        lessons = []
        if self.experience is not None:
            lessons = [{"id": x.id, "question": x.question[:80], "step": x.step, "lesson": x.lesson[:160],
                        "seen": x.seen, "uses": x.uses, "wins": x.wins, "fails": x.fails, "active": x.active, "at": x.at}
                       for x in sorted(self.experience.load(), key=lambda x: x.at, reverse=True)]
        return {"topics": topics, "lessons": lessons}

    async def admin_memory(self, request: Request) -> Response:
        """`GET /admin/memory`：記憶與經驗清單。 / Memory topics and lessons."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        return JSONResponse(await anyio.to_thread.run_sync(self.memory_listing))

    async def admin_observability(self, request: Request) -> Response:
        """`GET /admin/observability?days=7`：統一欄位彙整（add-agent-observability）。只有計數。"""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        try:
            days = max(1, min(31, int(request.query_params.get("days", "7"))))
        except ValueError:
            return _err(400, "days must be a number", "invalid_request")
        from ..agent.approval import write_enabled
        from ..observability import summary
        from .gaps import load

        def build():
            out = summary(load(self.s.root, days))
            out.update(days=days, agent_enabled=bool(self.s.agent), agent_write_enabled=write_enabled(),
                       tool_filter_enabled=bool(self.s.tool_filter))
            return out
        return JSONResponse(await anyio.to_thread.run_sync(build))

    async def admin_doctor(self, request: Request) -> Response:
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        from .doctor import checks
        rows = await anyio.to_thread.run_sync(checks, self.s.root, self.s.gateway_port)
        return JSONResponse({"checks": rows})

    async def admin_unload(self, request: Request) -> Response:
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        try:
            data = json.loads(await request.body() or b"{}")
            hold = datetime.fromisoformat(data["hold_until"]) if data.get("hold_until") else None
        except (ValueError, TypeError) as exc:
            return _err(400, f"bad request: {exc}", "invalid_request")
        if hold and hold.tzinfo is not None:
            hold = hold.astimezone().replace(tzinfo=None)
        return JSONResponse(await self.sup.unload(hold, data.get("reason")))

    async def chat(self, request: Request) -> Response:
        if not self.s.progress:
            return await self._chat(request)
        p = _Progress()
        token = _PROGRESS.set(p)
        try:
            task = asyncio.ensure_future(self._chat(request))      # 複製目前的 context / copies the context
        finally:
            _PROGRESS.reset(token)
        started = asyncio.ensure_future(p.started.wait())
        try:
            await asyncio.wait({task, started}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            task.cancel()
            started.cancel()
            raise
        if task.done() and not p.started.is_set():
            started.cancel()
            return task.result()
        return StreamingResponse(self._progress_stream(task, p), media_type="text/event-stream")

    async def _progress_stream(self, task: asyncio.Future, p: _Progress) -> AsyncIterator[bytes]:
        """先送階段，處理完再接上真正的回應（串流照轉；錯誤改成串流裡的 error）。
        Stages first, then the real response (streams relayed; errors become an in-stream error)."""
        it = None
        try:
            while True:
                getter = asyncio.ensure_future(p.queue.get())
                await asyncio.wait({task, getter}, return_when=asyncio.FIRST_COMPLETED)
                if getter.done():
                    yield _progress_chunk(getter.result())
                    continue
                getter.cancel()
                break
            while not p.queue.empty():
                yield _progress_chunk(p.queue.get_nowait())
            resp = task.result()
            if isinstance(resp, StreamingResponse):
                p.relaying = True
                _PROGRESS.set(p)                 # 內層串流在這個 context 裡跑 / the inner stream runs here
                it = resp.body_iterator
                async for chunk in it:
                    yield chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
                return
            payload = json.loads(bytes(resp.body) or b"{}")
            if resp.status_code >= 400:
                yield _sse({"error": payload.get("error") or {"message": f"HTTP {resp.status_code}"}})
            else:                                 # 完整答案轉成串流格式 / a complete answer as chunks
                msg = ((payload.get("choices") or [{}])[0].get("message") or {})
                base = {"id": payload.get("id"), "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": payload.get("model")}
                yield _sse({**base, "choices": [{"index": 0, "delta": {"role": "assistant",
                                                                        "content": msg.get("content") or ""},
                                                  "finish_reason": "stop"}]})
                if payload.get("jiezi"):
                    yield _sse({**base, "choices": [], "jiezi": payload["jiezi"]})
            yield b"data: [DONE]\n\n"
        finally:
            if not task.done():
                task.cancel()                     # 用戶端中斷 / client went away
            if it is not None and hasattr(it, "aclose"):
                await it.aclose()

    async def _chat(self, request: Request) -> Response:
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        body = await self._read_json(request)
        if isinstance(body, Response):
            return body
        policy = body.get("model") or "jiezi"
        if policy not in POLICIES:
            return _err(400, f"model must be one of {', '.join(POLICIES)}", "invalid_model")
        stream = bool(body.get("stream"))
        if stream and _PROGRESS.get() is not None:
            _PROGRESS.get().enabled = True
        from . import jsonout
        try:
            json_mode = jsonout.spec(body) is not None  # add-json-output
        except jsonout.BadFormat as exc:
            return _err(400, str(exc), "invalid_response_format")
        agent_contract = body.pop("agent_contract", None)  # A1：只給代理用，不轉送引擎、不進原始 request
        tid = new_id() if self.traj.enabled else None
        # training_use：None 表示訓練前要依授權表確認；請教 Claude 的回答一律 False（design D9）
        # training_use: None means check the license registry before training; Claude consultations are always False
        from .process import TimedTiers
        rec = {"id": tid, "at": now_iso(), "policy": policy, "stream": stream, "request": body, "tiers": TimedTiers(),
               "final_tier": None, "status": "ok", "training_use": None, "sources": []}
        # 評測流量（selftest、toolcheck）：不學技能、不存記憶，避免評測污染自己（2026-11-16）
        # Evaluation traffic: no skill learning, no memory saving, so evaluations never contaminate themselves
        if request.headers.get("x-jiezi-eval") == "1":
            rec["eval"] = True
        if json_mode:
            rec["json_mode"] = True
        nb_id, nb_general = body.pop("jiezi_notebook", None), body.pop("jiezi_notebook_general", False)
        if nb_id:  # 在筆記本裡回答（add-notebooks）/ answer inside a notebook
            from ..notebooks.store import NotebookError
            if self.notebooks is None:
                return _err(404, "notebooks are off (JIEZI_NOTEBOOKS=on)", "not_found")
            try:
                nb = self.notebooks.get(str(nb_id))
            except NotebookError as exc:
                return _err(exc.status, str(exc), "notebook_not_found")
            rec["notebook"] = {"id": nb.id, "name": nb.meta["name"], "general": bool(nb_general)}
        if body.pop("jiezi_agent", None):  # 唯讀代理（add-agent-readonly）/ read-only agent
            if self.s.agent:
                return await self._agent(body, rec, policy, stream, json_mode, agent_contract)
            rec["agent"] = {"enabled": False}  # 關閉時照一般請求處理 / handled as a normal request when off
        # 查資料可能要啟動 embedding 引擎，放到執行緒以免卡住其他請求 / may start the embedder; off the event loop
        data: list[dict] = []  # gateway 自己附加的資料訊息 / data messages the gateway attached
        for m in body["messages"]:
            if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                m["content"] = strip_appendix(m["content"])
        await self._read_paths(body, rec)
        await self._read_urls(body, rec)
        await anyio.to_thread.run_sync(self._ground, body, rec, data)
        self._attach_skills(body, rec, data)
        self._path_note(body, rec)
        if self.s.injection_guard:
            self._guard(body, rec, data)
        t0 = time.monotonic()
        if hasattr(rec["tiers"], "t0"):
            rec["tiers"].t0 = t0       # 過程的時間和 latency_s 同一個起點 / process times share latency_s's start
        try:
            plan = self._translate_plan(body, policy, json_mode)  # add-translation
        except Exception as exc:  # noqa: BLE001 - TranslateError 等：寫錯的翻譯選項 / malformed translation options
            from ..translate import TranslateError
            if isinstance(exc, TranslateError):
                return _err(400, str(exc), "invalid_translation")
            self.log(f"translate: plan failed, answering normally: {type(exc).__name__}: {exc}")
            plan = None
        if plan is not None:
            done = await self._translate(body, rec, t0, stream, policy, plan)
            if done is not None:
                return done
        if self.memory is not None and not body.get("tools") and not json_mode and not body.get("jiezi_translate") \
                and not has_images(body):
            early = self._memory_early(body, rec, t0, stream, policy)
            if early is not None:
                return early

        if policy == "jiezi-ask-claude":
            if has_images(body):  # Claude Code CLI 只收文字，圖片會遺失 / the CLI takes text only
                if self.s.cloud_ready and not self._can_escalate():
                    return await self._respond_cloud(body, rec, t0, stream, reason="image_needs_vision")
                return self._finish_error(rec, 400, "請教 Claude 的管道目前只能傳文字，無法附圖 / consulting Claude "
                                          "cannot carry images", "vision_unavailable")
            return await self._respond_consult(body, rec, t0, stream)

        if policy == "jiezi-cloud":
            reason = self._can_escalate()
            if reason:
                return self._finish_error(rec, 503, f"cloud is not available ({reason})", reason)
            return await self._respond_cloud(body, rec, t0, stream, reason="policy")

        if has_images(body) and not self.core_vision:
            # 核心不支援圖片：不讓本機對著看不到的圖亂答（add-vision）/ never let a text-only core guess at an image
            if policy != "jiezi-local" and self.s.cloud_ready and not self._can_escalate():
                return await self._respond_cloud(body, rec, t0, stream, reason="image_needs_vision")
            return self._finish_error(rec, 400, "目前的核心模型不支援圖片（需要有視覺模組的核心，例如 Qwen3.5 加 mmproj）"
                                      "；也沒有可用的雲端模型 / the core model cannot read images", "vision_unavailable")
        if body.get("tools") and self.s.tool_filter:
            body = self._filter_tools(body, rec, (agent_contract or {}).get("allowed_tools") or (), policy)
        big = self._too_large(body)
        if big:
            from .tool_filter import STAGES as TOOL_STAGES
            # 工具清單與系統提示本身就超過本機的上下文（例如帶幾十個工具的代理程式）：裁不掉，送了引擎只會回 400。
            # 2026-11-17 實測 OpenCode 一次送 58,000 token。能轉交就轉交，不能就回清楚的錯誤。
            # Tools and system prompts alone exceed the local context (agent clients with dozens of tools): nothing
            # can be trimmed and the engine would answer 400. Escalate when possible, else a clear error.
            rec["too_large"] = big
            if policy == "jiezi" and self._auto_route():
                return await self._escalate(body, rec, t0, stream, reason="context_too_large")
            return self._finish_error(
                rec, 413, (f"已試過工具篩選（{'→'.join(TOOL_STAGES)}）；" if rec.get("tool_filter") else "") +
                f"這個請求裁短後仍約 {big['after']} token，超過本機模型的上下文（{big['ctx']} token）；"
                          "通常是工具清單或系統提示太長。請改用 jiezi 或 jiezi-ask-claude，或減少工具 / "
                          f"the request still needs about {big['after']} tokens after trimming but the local model's "
                          f"context is {big['ctx']}; use the jiezi or jiezi-ask-claude policy, or send fewer tools",
                "context_too_large")
        route = self._pre_route(body, rec) if policy == "jiezi" else None
        if route:
            # 路由器 v0（規則）：本機一定答不了的問題直接轉交，不先浪費一次本機生成
            # Router v0 (rules): questions the local model cannot answer go straight to escalation
            return await self._escalate(body, rec, t0, stream, reason=route)

        if self.sup.status == "unloaded":
            _stage("loading_model")
        try:
            base = await self.sup.acquire()
        except EngineUnavailable as exc:
            if policy == "jiezi" and self._auto_route():
                rec["engine"] = str(exc)
                return await self._escalate(body, rec, t0, stream, reason="engine_unavailable")
            return self._finish_error(rec, 503, f"local engine unavailable: {exc}", "engine_unavailable")

        if self.s.longdoc and not body.get("tools"):
            try:
                await self._condense(base, body, rec)
            except Exception as exc:  # noqa: BLE001 - 濃縮失敗就照原樣（由上下文把關截短）/ fall back to trimming
                self.log(f"longdoc: condensing failed, sending as is: {type(exc).__name__}: {exc}")
                rec["longdoc"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}

        seen = await self._vision_look(base, body, rec) \
            if (self.vision is not None or self.ocr is not None) and has_images(body) else None
        if stream and not body.get("tools") and not json_mode and not body.get("jiezi_translate") \
                and not self._sample_kind(body) and seen is None and not rec.get("notebook_ctx"):
            _stage("thinking")        # 第一個字前還要處理提示（附圖時可能幾十秒）/ prompt processing before the first token
            return StreamingResponse(self._relay_stream(base, body, rec, t0, policy), media_type="text/event-stream")
        try:
            if self._is_long(body):
                # 同時只放行一個長請求，免得共用 KV 池被兩個長提示擠爆（add-long-context）
                # One long request at a time so two long prompts never overflow the shared KV pool
                rec["long_context"] = {"budget": self._ctx(body)}
                async with self._long_lock:
                    return await self._tiered(base, body, rec, t0, policy, stream)
            return await self._tiered(base, body, rec, t0, policy, stream)
        finally:
            self._seen.pop(rec["id"], None)
            self.sup.release()

    # ── 唯讀代理（add-agent-readonly）/ Read-only agent ──
    async def _agent(self, body: dict, rec: dict, policy: str, stream: bool, json_mode: bool,
                     contract: object | None = None) -> Response:
        """模型在本機想、工具在 MCP 子行程裡做（授權與稽核在那裡）；檔案內容不送到 Claude 或雲端（OQ2）。
        The local model plans; tools run in the MCP child (grants and audit live there); file contents never leave
        the machine (OQ2)."""
        import asyncio
        from ..agent import contract as C
        from ..agent import loop as A
        from ..agent import tools as T
        from ..agent.grants import Grants
        started = now_iso()
        messages = body.get("messages") or []
        goal = next((m.get("content") for m in reversed(messages)
                     if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str)), None)
        norm = C.normalize(contract, step_ceiling=self.s.agent_max_steps, available_tools=T.NAMES, implicit_goal=goal)
        initial = {
            "steps": [], "contract": norm.contract,
            "contract_status": "accepted" if norm.ok else "clarification",
            "effective_tools": list(norm.contract.get("effective_tools") or []),
            "effective_budget": dict(norm.contract.get("effective_budget") or {}),
            "terminal_state": "running", "started_at": started, "terminal_at": None,
        }

        def mark_terminal(state: str, reason: str | None = None, info: dict | None = None) -> None:
            a = rec.setdefault("agent", {"steps": []})
            a.update(initial)
            if info:
                a.update(info)
            a.setdefault("started_at", started)
            if not a.get("terminal_at"):
                a["terminal_at"] = now_iso()
            a["terminal_state"] = state
            if reason:
                a["terminal_reason"] = reason

        def fail(code: int, message: str, kind: str, reason: str | None = None) -> JSONResponse:
            mark_terminal("failed", reason or kind)
            return self._finish_error(rec, code, message, kind)

        if policy not in ("jiezi", "jiezi-local"):
            return fail(400, "唯讀代理只在本機執行（檔案內容不送出），請用 jiezi 或 jiezi-local / the agent runs locally "
                             "only; use the jiezi or jiezi-local policy", "agent_policy")
        if body.get("tools") or json_mode or has_images(body):
            return fail(400, "唯讀代理不能同時帶自己的工具、JSON 格式或圖片 / the agent cannot be combined with client "
                             "tools, JSON mode or images", "agent_unsupported")
        self._untrainable(rec, "private")  # 內容是使用者的私人檔案 / the user's private files
        rec.setdefault("agent", {"steps": []})
        t0 = time.monotonic()
        folders = [str(f) for f in Grants(self.s.root).folders()]
        if self.sup.status == "unloaded":
            _stage("loading_model")
        try:
            base = await self.sup.acquire()
        except EngineUnavailable as exc:
            return fail(503, f"唯讀代理需要本機模型（檔案內容不會送到雲端）；本機引擎無法使用：{exc} / "
                             "the agent needs the local engine", "engine_unavailable")

        async def complete(msgs: list[dict], schemas: list | None) -> dict:
            b = {"messages": msgs, "temperature": 0.3, **({"tools": schemas} if schemas else {})}
            return _message(await self._local_once(base, b, msgs))

        async def work(emit) -> tuple[dict, dict]:
            async with A.McpClient(self.s.root) as mcp:
                return await A.run(body["messages"], complete, mcp, folders, emit, rec["id"],
                                   self.s.agent_max_steps, contract)

        def finish(msg: dict, info: dict) -> tuple[dict, dict]:
            mark_terminal(info.get("terminal_state", "completed"), info.get("terminal_reason"), info)
            a = rec["agent"]
            if a.get("suspected"):
                rec["injection"] = {"suspected": a["suspected"], "where": ["agent tool results"]}
            resp = {"id": f"chatcmpl-{rec['id']}", "object": "chat.completion", "created": int(time.time()),
                    "model": self.sup.core["name"] if self.sup.core else self.s.core_model,
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": msg.get("content") or ""},
                                 "finish_reason": "stop"}]}
            meta = self._meta(rec, 0, resp, None, t0)
            meta["agent"] = {"steps": a["steps"], "step_limit": a.get("step_limit", False), "folders": len(folders),
                             "contract_status": a.get("contract_status"), "terminal_state": a.get("terminal_state"),
                             "fail_closed": a.get("terminal_state") == "fail_closed",
                             "fail_closed_reason": a.get("terminal_reason") if a.get("terminal_state") == "fail_closed"
                             else None,
                             "effective_tools": a.get("effective_tools", []),
                             "effective_budget": a.get("effective_budget", {})}
            rec.update(final_tier=0, jiezi=meta)
            return resp, meta

        if not stream:
            async def nothing(_ev):
                return None
            try:
                msg, info = await work(nothing)
            except Exception as exc:  # noqa: BLE001
                mark_terminal("failed", f"{type(exc).__name__}: {exc}")
                return self._finish_error(rec, 502, f"代理執行失敗 / agent failed: {type(exc).__name__}: {exc}",
                                          "agent_error")
            finally:
                self.sup.release()
            resp, meta = finish(msg, info)
            self.traj.write(rec)
            return JSONResponse({**resp, "jiezi": meta})

        async def gen() -> AsyncIterator[bytes]:
            send, recv = anyio.create_memory_object_stream(64)
            out: dict = {}

            async def worker():
                try:
                    out["v"] = await work(send.send)
                except Exception as exc:  # noqa: BLE001
                    out["err"] = exc
                finally:
                    send.close()
            task = asyncio.create_task(worker())
            written = False
            try:
                async with recv:
                    async for ev in recv:  # 每一步即時回報 / report every step as it happens
                        yield _sse({"object": "jiezi.agent.step", "choices": [], "jiezi_agent": ev})
                await task
                if "err" in out:
                    mark_terminal("failed", f"{type(out['err']).__name__}: {out['err']}")
                    rec.update(status="agent_error", error=str(out["err"]))
                    self.traj.write(rec)
                    written = True
                    yield _sse({"error": {"message": f"代理執行失敗 / agent failed: {out['err']}", "code": "agent_error"}})
                    yield b"data: [DONE]\n\n"
                    return
                resp, meta = finish(*out["v"])
                self.traj.write(rec)
                written = True
                async for chunk in self._synth_stream(resp, meta):
                    yield chunk
            finally:
                if not task.done():  # 客戶端中斷：停止迴圈並結束工具子行程 / client stopped: end loop and tools
                    task.cancel()
                    with anyio.CancelScope(shield=True):
                        try:
                            await task
                        except BaseException:  # noqa: BLE001
                            pass
                self.sup.release()
                if not written:
                    mark_terminal("aborted", "client cancelled")
                    rec.update(status="cancelled")
                    self.traj.write(rec)

        return StreamingResponse(gen(), media_type="text/event-stream")

    async def agent_approvals(self, request: Request) -> Response:
        """`GET /v1/agent/approvals`（列表，不含內容）、`GET /v1/agent/approvals/{id}`（含完整內容與 sha256）、
        `POST /v1/agent/approvals/{id}` {action: allow|deny|rollback, sha256, reason}（add-agent-approval）。
        核准必須回填內容 sha256；模型沒有任何管道拿到核准憑證。 / Approve only with the content's sha256."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        from ..agent.approval import ApprovalError, ApprovalStore, public
        from ..agent.grants import Grants
        from ..agent import audit as agent_audit
        store, rid = ApprovalStore(self.s.root), request.path_params.get("rid")
        if request.method == "GET":
            if not rid:
                store.cleanup()  # 順手清掉超過保留期限的已結案請求（T13）/ prune old closed requests
                return JSONResponse({"approvals": [public(r) for r in store.list(request.query_params.get("status"))]})
            try:
                r = store.get(rid)
            except ApprovalError as exc:
                return _err(400, str(exc), "invalid_approval")
            return JSONResponse(public(r, with_content=True)) if r else _err(404, "no such approval request", "not_found")
        data = await self._read_json_any(request)
        if isinstance(data, Response):
            return data
        if not isinstance(data, dict):
            return _err(400, "body must be a JSON object", "invalid_request")
        try:
            r = store.decide(Grants(self.s.root), rid or "", str(data.get("action") or ""), str(data.get("sha256") or ""),
                             str(data.get("reason") or ""), actor="gateway")
        except ApprovalError as exc:
            return _err(409, str(exc), "approval_refused")
        agent_audit.write(self.s.root, {"source": "gateway", "tool": "write_file", "approval_id": r["id"],
                                        "outcome": r["status"], "reason": str(data.get("reason") or "")[:300],
                                        "arguments": {"path": r["path"]}, "allowed": True})
        return JSONResponse(public(r))

    async def agent_audit(self, request: Request) -> Response:
        """`GET /v1/agent/audit?days=1`：稽核紀錄（桌面網頁的稽核頁用）。 / Audit entries for the desktop page."""
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        from ..agent import audit
        from ..agent.grants import Grants
        try:
            days = max(1, min(30, int(request.query_params.get("days") or 1)))
        except ValueError:
            days = 1
        return JSONResponse({"enabled": self.s.agent, "folders": [str(f) for f in Grants(self.s.root).folders()],
                             "entries": audit.read(self.s.root, days)})

    # ── 翻譯（add-translation）/ Translation ──
    def _translate_plan(self, body: dict, policy: str, json_mode: bool) -> dict | None:
        """這個請求要不要由翻譯流程接手。回傳 None（照一般流程；短文字會在 body 留下檢查用的設定）或計畫。
        Whether the translation path takes this request: None (normal path; short texts leave check settings in the
        body) or a plan."""
        from .. import translate as T
        from ..longdoc import split_message
        opts = body.pop("jiezi_translate", None)
        if not self.s.translate or body.get("tools") or json_mode:
            return None
        if opts is not None and not isinstance(opts, dict):
            raise T.TranslateError("jiezi_translate must be an object")
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        if not last or not isinstance(last.get("content"), str):
            return None
        has_docs = "【文件：" in last["content"]
        docs, q = split_message(last["content"]) if has_docs else ([], last["content"])
        it = T.intent(q)
        if opts is None and it is None:
            return None
        to = (opts or {}).get("to") or (it or {}).get("to")
        glossary = T.parse_glossary((opts or {}).get("glossary"))
        if not docs:  # 短文字：照一般流程回答，只加譯文檢查 / short text: normal path plus the checks
            if it is not None and not it["convert"]:
                body["jiezi_translate"] = {"short": True, "to": T.resolve_target(to, T.detect(q)),
                                           "glossary": [list(g) for g in glossary]}
            return None
        source = T.detect("\n".join(t for _, t in docs)[:20000])
        target = T.resolve_target(to, source)
        if source == "zh-Hans" and target == "zh-TW":
            return {"mode": "conversion", "docs": docs, "to": target, "source": source}
        if (it or {}).get("convert") or (source == "zh-Hant" and target == "zh-TW") or source == target:
            return None  # 已經是目標語言 / already in the target language
        if policy not in ("jiezi", "jiezi-local"):
            return None  # 指定雲端或 Claude：照原本的文件流程 / explicit cloud or Claude keeps the normal document path
        # add-default-glossary：中翻英併入原文出現的內建機關英文名 / built-in agency names for Chinese → English
        glossary, builtin = T.with_default(glossary, "\n".join(t for _, t in docs), target,
                                           (opts or {}).get("default_glossary", True) is not False)
        return {"mode": "chunked", "docs": docs, "to": target, "source": source, "glossary": glossary,
                "default_glossary": builtin,
                "bilingual": (opts or {}).get("bilingual", True) is not False,
                "confirmed": bool((opts or {}).get("confirmed"))}

    def _translated(self, rec: dict, t0: float, stream: bool, text: str, tier, model: str, info: dict,
                    ver: dict | None = None) -> Response:
        resp = {"id": f"chatcmpl-translate-{int(time.time() * 1000)}", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
        rec["tiers"].append({"tier": tier, "answer": resp["choices"][0]["message"], "verification": ver, "model": model})
        rec["translation"] = info
        self._untrainable(rec, "unverifiable")   # 譯文對不對無法由程式證明；原文多為私人文件 / unverifiable, usually private
        rec.pop("dict_appendix", None)
        meta = self._meta(rec, tier, resp, ver, t0)
        meta["translation"] = info
        return self._deliver(resp, meta, rec, stream)

    async def _translate(self, body: dict, rec: dict, t0: float, stream: bool, policy: str, plan: dict) -> Response | None:
        """整份文件的翻譯或簡轉繁；回傳 None 表示交回一般流程（例如本機引擎不可用而要轉交）。
        Whole-document translation or script conversion; None hands the request back to the normal path."""
        from .. import translate as T
        docs, many = plan["docs"], len(plan["docs"]) > 1
        base_info = {"mode": plan["mode"], "to": plan["to"], "source": plan["source"]}
        if plan["mode"] == "conversion":
            out = await anyio.to_thread.run_sync(
                lambda: "\n\n".join((f"# {n}\n\n" if many else "") + T.convert(t) for n, t in docs))
            note = "\n\n---\n【字詞轉換】簡體 → 繁體（台灣用語），依 OpenCC 對照表轉換，未經模型；專有名詞與用語請自行確認。"
            return self._translated(rec, t0, stream, out + note, "convert", "jiezi-convert",
                                    {**base_info, "documents": [n for n, _ in docs], "chars": sum(len(t) for _, t in docs)})
        est = T.estimate_seconds([t for _, t in docs], self.last_tps)
        if est > T.ASK_ABOVE_S and not plan["confirmed"]:
            text = (f"這份文件要逐段翻譯，預估需要約 {max(1, round(est / 60))} 分鐘（估算，實際依模型速度而定）。"
                    f"超過 {T.ASK_ABOVE_S // 60} 分鐘的翻譯要先經你確認，請改用指令（會顯示預估、可中斷後續跑）：\n"
                    f"scripts/jiezi translate 檔案路徑 --to {plan['to']}\n"
                    "This translation needs confirmation first; run the command above.")
            return self._translated(rec, t0, stream, text, "translate-estimate", "jiezi-translate",
                                    {**base_info, "needs_confirmation": True, "estimate_s": est})
        if self.sup.status == "unloaded":
            _stage("loading_model")
        try:
            base = await self.sup.acquire()
        except EngineUnavailable as exc:
            if policy == "jiezi" and self._auto_route():
                return None  # 照既有的文件流程轉交 / escalate through the normal document path
            return self._finish_error(rec, 503, f"local engine unavailable: {exc}", "engine_unavailable")

        async def complete(msgs: list[dict], max_tokens: int) -> str:
            r = await self._local_once(base, {"messages": msgs, "max_tokens": max_tokens, "temperature": 0.2}, msgs)
            return ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

        t, blocks, infos = time.monotonic(), [], []
        try:
            for name, text in docs:
                pairs, info = await T.translate_text(name, text, plan["to"], complete, plan["glossary"],
                                                     self.s.var / "translate")
                blocks.append(T.render(name, pairs, plan["bilingual"], many))
                infos.append(info)
        except httpx.HTTPError as exc:
            return self._finish_error(rec, 502, f"local engine error: {exc}", "engine_error")
        finally:
            self.sup.release()
        failed = sum(len(i["failed"]) for i in infos)
        total = sum(i["chunks"] for i in infos)
        info = {**base_info, "bilingual": plan["bilingual"], "documents": infos, "chunks": total, "failed": failed,
                "default_glossary": plan.get("default_glossary") or [],
                "estimate_s": est, "seconds": round(time.monotonic() - t, 1)}
        ver = {"status": "fail" if failed else "pass", "checks": [{"check": "translation", "status": "fail" if failed else "pass"}],
               "error": f"{failed} of {total} chunks could not be translated" if failed else None}
        self.log(f"translate: {total} chunks, {failed} failed, {info['seconds']} s (estimate {est} s)")
        rec["sources"] = (rec.get("sources") or []) + [{"source": "document", "name": n} for n, _ in docs]
        return self._translated(rec, t0, stream, "\n\n".join(blocks), 0, self.sup.core["name"] if self.sup.core else
                                self.s.core_model, info, ver)

    # ── 分層 / Tiers ──
    # ── 長文件（add-long-documents）/ Long documents ──
    def _warm(self, text: str) -> bool:
        """附檔當下就在背景建段落向量（add-semantic-chunks OQ3）；短文件不用。
        Start building chunk vectors as soon as a document is attached; short documents need none."""
        from ..longdoc import needed
        if self.doc_vectors is None or not needed(text):
            return False
        try:
            return self.doc_vectors.start(text) is not None
        except Exception:  # noqa: BLE001 - 預先建置失敗不影響任何事 / best effort
            return False

    async def documents_warm(self, request: Request) -> Response:
        """`POST /v1/documents/warm`：本文（UTF-8 文字）是已讀好的文件，先建段落向量（jiezi chat 的 /file 用）。
        Body: an already extracted document as UTF-8 text; starts building its chunk vectors (used by chat's /file)."""
        from ..injection import clean
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        raw = await request.body()
        if len(raw) > MAX_WARM_BYTES:
            return _err(413, "document too large", "document_too_large")
        text, _ = clean(raw.decode("utf-8", errors="replace"))
        return JSONResponse({"warming": self._warm(text)}, status_code=202)

    async def _condense(self, base: str, body: dict, rec: dict) -> None:
        """最後一個問題放不進本機上下文時，先用本機模型分段濃縮。 / Condense with the local model when it does not fit."""
        from ..documents import DOC_RE
        from ..longdoc import FOLLOWUP_RESERVE, LIMIT, condense, needed
        from .context import _msg_tokens
        msgs = body["messages"]
        idx = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
        if idx is None:
            return
        # 追問：留空間給上一輪問答，並用它幫忙挑段落（add-document-followup）
        # Follow-ups: keep room for the previous exchange and use it as a ranking hint
        prev = [m for m in msgs[:idx] if m.get("role") in ("user", "assistant")][-2:]
        budget = LIMIT - min(FOLLOWUP_RESERVE, sum(_msg_tokens(m) for m in prev))
        if not needed(msgs[idx].get("content"), budget):
            return
        hint = "\n".join(DOC_RE.sub("", message_text(m))[:400] for m in prev)
        _stage("reading_documents")

        async def complete(msgs: list[dict], max_tokens: int) -> str:
            r = await self._local_once(base, {"messages": msgs, "max_tokens": max_tokens, "temperature": 0.3}, msgs)
            return ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

        semantic = None
        if self.doc_vectors is not None:
            vectors, wait_s = self.doc_vectors, self.s.doc_embed_timeout_s

            async def semantic(question: str, text: str, parts: list[str], alt: str | None = None):
                return await anyio.to_thread.run_sync(vectors.order, question, text, parts, wait_s, alt)

        t = time.monotonic()
        new, info = await condense(msgs[idx]["content"], complete, hint, budget, self.doc_notes, semantic,
                                   self.s.doc_recall)
        msgs[idx] = {**msgs[idx], "content": new}
        info["seconds"] = round(time.monotonic() - t, 1)
        info["followup"] = bool(prev)
        rec["longdoc"] = info
        rec["sources"] = (rec.get("sources") or []) + [{"source": "document", "name": n} for n in info["documents"]]
        self.log(f"longdoc: {info['mode']}, {info['chars']} chars → {info['after_tokens']} tokens in {info['seconds']} s")

    # ── 技能庫 v0（開發計畫 5.2）/ Skill library v0 ──
    def _attach_skills(self, body: dict, rec: dict, data: list | None = None) -> None:
        """工具呼叫請求：附上最相似的成功範例。 / Tool-call requests get the most similar verified examples."""
        if self.skills is None or not body.get("tools"):
            return
        from ..skills import prompt
        users = [m for m in body["messages"] if m.get("role") == "user"]
        if not users:
            return
        names = {(t.get("function") or t).get("name") for t in body["tools"]}
        ex = self.skills.examples(message_text(users[-1]), names)
        text = prompt(ex)
        if text:
            idx = body["messages"].index(users[-1])
            body["messages"].insert(idx, {"role": "system", "content": text})
            if data is not None:
                data.append(body["messages"][idx])
            rec["sources"] = (rec.get("sources") or []) + [{"source": "skills", "question": e["question"][:60]}
                                                             for e in ex]

    def _learn_skill(self, body: dict, rec: dict, resp: dict, ver: dict) -> None:
        """通過 schema 驗證、信心夠的本機工具呼叫加入技能庫。 / Verified, confident local calls join the library."""
        if self.skills is None or not body.get("tools") or ver.get("status") != "pass" or rec.get("eval") \
                or self._injected(rec):
            return
        if rec.get("confidence") is not None and rec["confidence"] < 0.75:
            return
        from ..skills import _calls_text
        msg = _message(resp)
        call = _calls_text(msg.get("tool_calls")) or (msg.get("content") or "").strip()
        users = [m for m in body["messages"] if m.get("role") == "user"]
        if not users or not call.startswith("["):
            return
        names = sorted({(t.get("function") or t).get("name") for t in body["tools"]})
        used = sorted({c.split("(")[0].strip("[ ") for c in call.split("),") if "(" in c})
        try:
            self.skills.add({"question": message_text(users[-1]), "call": call, "functions": names, "used": used,
                             "at": rec.get("at"), "trajectory_id": rec.get("id")})
        except OSError as exc:
            self.log(f"skills: could not save: {exc}")

    # ── 路由器 v0（add-router；開發計畫 4.5 的規則版）/ Router v0 ──
    def _trust_gate(self):
        from ..trust import get_gate
        return get_gate(self.s.root)

    def _untrainable(self, rec: dict, reason: str, model: str | None = None) -> None:
        """不可訓練的單一標記點（add-agent-trust-gate）：training_use=False，rec["trust"] 記原因與來源。
        Single place that marks a trajectory untrainable, keeping the reason and provenance."""
        if rec.get("trust", {}).get("reason") == "injection" and reason != "injection":
            rec["training_use"] = False  # 注入標記優先保留 / keep the injection marking
            return
        self._trust_gate().mark_untrainable(rec, reason, model)

    def _filter_tools(self, body: dict, rec: dict, contract_tools=(), policy: str = "jiezi-local") -> dict:
        """工具清單放不進本機槽位時依階梯篩選（add-client-tool-filter）；放得下就原樣。
        放不下時也換成篩過的清單：轉交雲端只帶相關工具，省雲端 token（使用者 2026-11-23 選 OQ0 (C)）。
        Trim an oversized tool list stage by stage; when nothing fits, the stage-1 selection still goes to the cloud."""
        from .tool_filter import KEEP_TOOLS, ladder
        try:
            res = ladder(body["tools"], body["messages"], lambda ts: not self._too_large({**body, "tools": ts}),
                         contract_tools=[str(t) for t in contract_tools if isinstance(t, str)],
                         keep=self.s.tool_keep or KEEP_TOOLS, top_k=self.s.tool_filter_top_k)
        except Exception as exc:  # noqa: BLE001 - 篩選失敗就照舊送 / a filter bug must not break the request
            self.log(f"tool filter failed, sending all tools: {type(exc).__name__}: {exc}")
            return body
        # 只在「不精簡就會失敗」時才精簡：jiezi-local（否則 413），或 jiezi 但沒有可轉交的去處。
        # 2026-11-23 實機：單回合尚可，多回合歷史被裁、選錯工具，品質不如轉交雲端，所以 jiezi 有雲端時照舊轉交。
        # Compact only when the request would otherwise fail: jiezi-local, or jiezi with nowhere to escalate.
        compact_ok = policy == "jiezi-local" or (policy == "jiezi" and not self._auto_route())
        if res["stage"] == "exhausted" and self.s.compact_client_prompt and compact_ok:
            # 客戶端系統提示太長（OQ0 A）：換成精簡版再篩一次；放得下才用 / condensed client prompt, used only if it fits
            from .tool_filter import with_compact_system
            msgs, before, after = with_compact_system(body["messages"])
            small = {**body, "messages": msgs}
            res2 = ladder(body["tools"], msgs, lambda ts: not self._too_large({**small, "tools": ts}),
                          contract_tools=[str(t) for t in contract_tools if isinstance(t, str)],
                          keep=self.s.tool_keep or KEEP_TOOLS, top_k=self.s.tool_filter_top_k)
            if res2["fits"]:
                rec["client_prompt"] = {"compacted": True, "before_chars": before, "after_chars": after}
                self.log(f"client prompt: {before} → {after} chars; {res2['original']} → {len(res2['tools'])} tools")
                rec["tool_filter"] = {"original": res2["original"], "kept": len(res2["tools"]),
                                      "stage": res2["stage"] or "full", "names": res2["kept"]}
                return {**small, "tools": res2["tools"]}
        if res["stage"] is None:
            return body
        if not res["tools"]:  # 一個都沒挑中：轉交時照原清單，不讓雲端沒工具可用 / nothing picked: keep all for the cloud
            rec["tool_filter"] = {"original": res["original"], "kept": res["original"], "stage": "none_relevant"}
            return body
        rec["tool_filter"] = {"original": res["original"], "kept": len(res["tools"]), "stage": res["stage"],
                              "names": res["kept"]}
        self.log(f"tool filter: {res['original']} → {len(res['tools'])} tools ({res['stage']})")
        return {**body, "tools": res["tools"]}

    def _ctx(self, body: dict) -> int:
        """本機上下文預算：帶工具的代理請求在 JIEZI_AGENT_CTX 開著時用代理預算，其餘一個槽位 4096（add-long-context）。
        The local budget: the agent budget for tool-bearing requests when JIEZI_AGENT_CTX is set, else one 4096 slot."""
        from .context import SLOT_CTX
        agent = getattr(self.s, "agent_ctx", 0)
        return agent if agent and body.get("tools") else SLOT_CTX

    def _is_long(self, body: dict) -> bool:
        """超過一個一般槽位的請求（只有代理預算開著時會出現）。 / A request larger than one ordinary slot."""
        from .context import SLOT_CTX, total
        if self._ctx(body) <= SLOT_CTX:
            return False
        try:
            return total(body["messages"], body.get("tools")) > SLOT_CTX - TOO_LARGE_ROOM
        except Exception:  # noqa: BLE001
            return False

    def _too_large(self, body: dict) -> dict | None:
        """裁到不能再裁還是放不進預算就回傳 {"after", "ctx"}。 / Set when even full trimming cannot fit the budget."""
        from .context import fit
        ctx = self._ctx(body)
        try:
            _, info = fit(body["messages"], body.get("tools"),
                          body.get("max_tokens") or body.get("max_completion_tokens"), ctx=ctx)
        except Exception:  # noqa: BLE001 - 估不出來就照舊送 / unknown shapes go through as before
            return None
        return {"after": info["after"], "ctx": ctx} if info["after"] > ctx - TOO_LARGE_ROOM else None

    def _pre_route(self, body: dict, rec: dict) -> str | None:
        """需要上網或即時資料、且沒有程式算好的答案時，直接轉交。 / Web/live questions without computed facts."""
        if body.get("tools") or not self._auto_route():
            return None
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        if not last or not isinstance(last.get("content"), str):
            return None
        from ..documents import DOC_RE
        # 只看問題本身：附加文件裡出現「網站、新聞」等字不代表要上網查（2026-11-17 桌面網頁實測誤判）
        # Only the question counts: words like "website" inside an attached document do not need the web
        if not LIVE.search(DOC_RE.sub("", last["content"])) or TRANSCRIPT.search(last["content"]):
            return None
        if rec.get("web_read_ok"):   # 網頁已在本機讀好附上 / the page was read locally (add-web-read)
            return None
        if any(s.get("source") in ("tools", "memory") for s in rec.get("sources") or []):
            return None  # 「今天星期幾」程式已算好；記憶裡有答案 / computed or remembered
        return "needs_web"

    # ── 平行取樣（add-sampling；開發計畫 4.1）/ Parallel sampling ──
    def _sample_kind(self, body: dict) -> str | None:
        """可驗證、值得取樣的問題種類。 / The kind of verifiable question worth sampling."""
        if self.s.samples <= 1:
            return None
        if self._is_long(body):  # 長請求平行取樣會把共用 KV 池撐爆 / N copies of a long prompt overflow the shared pool
            return None
        if body.get("tools"):
            return "tools"
        if body.get("response_format") and body["response_format"].get("type") in ("json_object", "json_schema"):
            return "json"
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        if last and isinstance(last.get("content"), str) and escalation.CODE_REQUEST.search(last["content"]):
            return "code"
        return None

    async def _sampled(self, base: str, body: dict, rec: dict, kind: str) -> tuple[dict, dict]:
        """同時取 N 個答案；挑通過驗證、最多數一致的那組。 / N concurrent samples; the verified majority wins."""
        n = self.s.samples
        sb = {**body, "temperature": self.s.sample_temperature}

        async def one(i: int) -> dict:
            return await self._local_once(base, {**sb, "seed": 1000 + i})
        results = await asyncio.gather(*(one(i) for i in range(n)), return_exceptions=True)
        ok = [r for r in results if isinstance(r, dict)]
        if not ok:
            raise next(r for r in results if isinstance(r, BaseException))
        grounding = self._grounding(body, rec)
        scored = [(r, escalation.verify(body, _message(r), grounding)) for r in ok]
        passing = [(r, v) for r, v in scored if v["status"] != "fail"]
        groups: dict[str, list] = {}
        for r, v in passing:
            groups.setdefault(escalation.answer_key(_message(r), kind), []).append((r, v))
        best = max(groups.values(), key=len) if groups else [scored[0]]
        resp, ver = best[0]
        confidence = round(len(best) / n, 2) if groups else 0.0
        rec["tiers"].append({"tier": 0, "answer": _message(resp), "verification": ver, "model": resp.get("model"),
                             "tps": _tps(resp), "usage": resp.get("usage"), "confidence": confidence,
                             "samples": [{"verification": v["status"], "key": escalation.answer_key(_message(r), kind)[:120]}
                                         for r, v in scored], "sample_errors": n - len(ok)})
        rec["confidence"] = confidence
        return resp, ver

    async def _tiered(self, base: str, body: dict, rec: dict, t0: float, policy: str, stream: bool) -> Response:
        kind = self._sample_kind(body)
        _stage("thinking")
        try:
            if kind:
                resp, ver = await self._sampled(base, body, rec, kind)
            else:
                resp = await self._local_once(base, body)
        except httpx.HTTPError as exc:
            return self._finish_error(rec, 502, f"local engine error: {exc}", "engine_error")
        if not kind:
            ver = escalation.verify(body, _message(resp), self._grounding(body, rec))
            rec["tiers"].append({"tier": 0, "answer": _message(resp), "verification": ver, "model": resp.get("model"),
                                 "tps": _tps(resp), "usage": resp.get("usage")})
        final, tier, escalate_reason = resp, 0, None
        help_reason = escalation.needs_help(_message(resp), (resp.get("choices") or [{}])[0].get("finish_reason"))
        help_reason = self._keep_local(help_reason, body, rec)
        if help_reason or ver["status"] == "fail":
            if help_reason:
                rec["tiers"][-1]["needs_help"] = help_reason
            reason = help_reason or "verification_failed"
            got = None
            if self.s.ladder and policy in ("jiezi", "jiezi-local"):
                # 本機先試到底（local-first-solving）/ the local model tries every rung first
                got = await self._ladder(base, body, rec, policy, _message(resp), ver, help_reason)
            elif ver["status"] == "fail":   # 舊行為：帶錯誤重答一次 / previous behaviour: one retry with the error
                msgs = escalation.retry_messages(body["messages"], _message(resp), ver["error"])
                _stage("retrying")
                try:
                    resp1 = await self._local_once(base, body, msgs)
                    ver1 = escalation.verify(body, _message(resp1), self._grounding(body, rec))
                    rec["tiers"].append({"tier": 1, "answer": _message(resp1), "verification": ver1,
                                         "model": resp1.get("model"), "tps": _tps(resp1), "usage": resp1.get("usage")})
                    final, tier, ver = resp1, 1, ver1
                    if ver1["status"] != "fail":
                        got = (resp1, ver1, 1)
                except httpx.HTTPError as exc:
                    rec["tiers"].append({"tier": 1, "error": str(exc)})
            if got:
                final, ver, tier = got
                tier = 1 if tier == "think" else tier
            else:
                last_local = next((t for t in reversed(rec["tiers"]) if t.get("answer") and not t.get("provider")
                                   and t.get("tier") != 2), None)
                if policy == "jiezi" and self._auto_route():
                    if not self.s.ladder and self.s.tier2 and ver["status"] == "fail":
                        done = await self._tier2(base, body, rec, t0, stream, final, ver)
                        if done is not None:
                            return done
                    return await self._escalate(body, rec, t0, stream, reason=reason)
                escalate_reason = "local_only_policy" if policy != "jiezi" else self._no_route_reason()
                if last_local and last_local is not rec["tiers"][0]:
                    final = {"model": last_local.get("model"), "choices": [
                        {"index": 0, "message": last_local["answer"], "finish_reason": "stop"}]}
                    ver = last_local.get("verification") or ver
        if not escalate_reason:
            self._learn_skill(body, rec, final, ver)
        if rec["id"] in self._seen:
            await self._vision_check(base, rec, final)
        meta = self._meta(rec, tier, final, ver, t0, escalation=escalate_reason)
        return self._deliver(final, meta, rec, stream)

    # ── 本機先試到底（local-first-solving）/ Local-first ladder ──
    def _ok(self, resp: dict, body: dict, rec: dict) -> tuple[dict, str | None]:
        msg = _message(resp)
        ver = escalation.verify(body, msg, self._grounding(body, rec))
        help_reason = self._keep_local(escalation.needs_help(msg, (resp.get("choices") or [{}])[0].get("finish_reason")),
                                       body, rec)
        return ver, help_reason

    async def _ladder(self, base: str, body: dict, rec: dict, policy: str, answer: dict, ver: dict,
                      help_reason: str | None) -> tuple[dict, dict, object] | None:
        """答不好時，本機先試到底再轉交（使用者 2026-11-18：「請教 Claude 是最後手段，要讓模型學會自己解決問題」）：
        1 帶著錯誤訊息重答；2 開思考模式再答；3 雲端免費模型只給提示，本機依提示再答（只在 jiezi 策略、雲端開著時）。
        成功回傳 (回應, 查核, 層)；都不行回傳 None。
        Before escalating: retry with the error, retry in think mode, then answer with cloud hints. Returns
        (response, verification, tier) on success, None when every rung fails."""
        error = (ver.get("error") if ver.get("status") == "fail" else None) or UNSURE_NOTE
        rec.setdefault("ladder", {"first_error": (help_reason or "verification_failed") + "：" + error[:200]})
        last = answer
        steps = [("retry", 1, "retrying", None)]
        if self.s.ladder_think:
            steps.append(("think", "think", "thinking_hard", {"chat_template_kwargs": {"enable_thinking": True},
                                                              "max_tokens": THINK_MAX_TOKENS}))
        for name, tier, stage, extra in steps:
            _stage(stage)
            try:
                resp = await self._local_once(base, {**body, **(extra or {})},
                                              escalation.retry_messages(body["messages"], last, error))
            except httpx.HTTPError as exc:
                rec["tiers"].append({"tier": tier, "step": name, "error": str(exc)})
                continue
            msg = _message(resp)
            if isinstance(msg.get("content"), str):   # 思考內容不給使用者 / thinking never reaches the user
                msg["content"] = re.sub(r"<think>.*?</think>\s*", "", msg["content"], flags=re.S).strip()
            ver2, help2 = self._ok(resp, body, rec)
            rec["tiers"].append({"tier": tier, "step": name, "answer": msg, "verification": ver2,
                                 "model": resp.get("model"), "tps": _tps(resp), "usage": resp.get("usage"),
                                 **({"needs_help": help2} if help2 else {})})
            if ver2["status"] != "fail" and not help2:
                rec["ladder"]["solved_by"] = name
                return resp, ver2, tier
            last, error = msg, (ver2.get("error") if ver2.get("status") == "fail" else None) or UNSURE_NOTE
        if policy == "jiezi" and self._can_escalate() is None:     # 雲端只給提示 / the cloud gives hints only
            _stage("asking_feedback")
            try:
                self.cap.take()
                hint, info = await self._cloud_once({"messages": escalation.feedback_request(body, last, error),
                                                     "max_tokens": escalation.FEEDBACK_MAX_TOKENS})
                feedback = _message(hint).get("content") or ""
                if feedback.strip():
                    resp = await self._local_once(base, body, escalation.feedback_messages(
                        body["messages"], last, error, feedback))
                    ver2, help2 = self._ok(resp, body, rec)
                    self._untrainable(rec, "cloud_hint", info.get("model"))      # 受雲端提示影響 / shaped by the cloud hint
                    rec["tiers"].append({"tier": 2, "step": "hint", "answer": _message(resp), "verification": ver2,
                                         "model": resp.get("model"), "helper": "cloud", "helper_model": info["model"],
                                         "feedback": feedback[:escalation.FEEDBACK_MAX_CHARS], "training_use": False,
                                         **({"needs_help": help2} if help2 else {})})
                    if ver2["status"] != "fail" and not help2:
                        rec["ladder"]["solved_by"] = "hint"
                        return resp, ver2, 2
            except (httpx.HTTPError, KeyError) as exc:
                rec["tiers"].append({"tier": 2, "step": "hint", "error": f"hint unavailable: {exc}"})
        return None

    def _teachers_later(self, rec: dict, tier, provider: str | None) -> None:
        """轉交過的題目在背景問老師模型（add-open-teacher）。 / Ask the teachers about an escalated question later."""
        from ..teacher import allowed
        teachers = [m for m in (getattr(self.s, "teacher_models", None) or []) if allowed(m)]
        req = rec.get("request") or {}
        if not teachers or tier != 3 or provider not in ("claude", "cloud") or rec.get("eval") \
                or rec.get("_teachers_done") or req.get("tools") or req.get("response_format") or has_images(req) \
                or not self.s.cloud_base or self._injected(rec):
            return
        rec["_teachers_done"] = True
        delivered = next((t["answer"].get("content") for t in reversed(rec.get("tiers") or []) if isinstance(t, dict)
                          and t.get("tier") == 3 and isinstance(t.get("answer"), dict)), "") or ""
        msgs = [{"role": m["role"], "content": m["content"]} for m in req.get("messages") or []
                if m.get("role") in ("system", "user", "assistant") and isinstance(m.get("content"), str)]
        try:
            asyncio.get_running_loop().create_task(
                self._ask_teachers(teachers, msgs, strip_appendix(delivered), rec.get("id") or "",
                                   next((t.get("model") for t in reversed(rec.get("tiers") or []) if isinstance(t, dict)
                                         and t.get("tier") == 3 and t.get("model")), "") or ""))
        except RuntimeError:
            pass

    async def _ask_teachers(self, teachers: list[str], msgs: list[dict], delivered: str, tid: str,
                            delivered_model: str = "") -> None:
        from .. import teacher as T
        headers = {"Authorization": f"Bearer {self.s.cloud_key}"} if self.s.cloud_key else {}

        async def one(model: str) -> tuple[str, str]:
            try:  # 用量記錄出錯只略過這位老師，不拖垮整批 / a usage error skips this teacher only
                if not await anyio.to_thread.run_sync(T.take, self.s.root, model, self.s.teacher_daily_max):
                    return model, ""
            except Exception as exc:  # noqa: BLE001
                self.log(f"teacher: {model}: usage: {type(exc).__name__}: {exc}")
                return model, ""
            try:
                r = await self.cloud.post(f"{self.s.cloud_base}/v1/chat/completions", headers=headers, json={
                    "model": model, "messages": msgs, "max_tokens": T.MAX_TOKENS, "stream": False,
                    "disable_fallbacks": True}, timeout=T.TIMEOUT_S)
                r.raise_for_status()
                data = r.json()
                got = str(data.get("model") or "")
                # LiteLLM 換成別的模型時不收（核對實際回答的模型）/ reject a substituted model
                if not T.allowed(got):
                    self.log(f"teacher: {model} answered as {got}, not kept")
                    return model, ""
                served[model] = got
                return model, strip_appendix(_message(data).get("content") or "").strip()
            except Exception as exc:  # noqa: BLE001 - 老師失敗不影響任何事 / failures are harmless
                self.log(f"teacher: {model}: {type(exc).__name__}: {exc}")
                return model, ""
        served: dict[str, str] = {}
        answers = dict(await asyncio.gather(*(one(m) for m in teachers)))
        question = next((m["content"] for m in reversed(msgs) if m["role"] == "user"), "")
        same = {m for m, got in served.items() if T.same_model(got, delivered_model)}
        kept = T.judge(answers, delivered, question, same)
        for model, agreed in kept.items():
            await anyio.to_thread.run_sync(T.save, self.s.root, msgs, answers[model], model, agreed, tid)
        self.log(f"teacher: {len(kept)}/{len(teachers)} kept for {tid}")

    def _experience_done(self, rec: dict, tier, escalation_reason: str | None, provider: str | None) -> None:
        """回答定案後：附上的經驗記一次有效／無效；走過階梯的題目在背景寫一筆新經驗。
        When an answer is final: count the attached lessons, and write a new lesson for a question that needed the ladder."""
        if getattr(self, "experience", None) is None or rec.get("_experience_done") or rec.get("eval"):
            return
        rec["_experience_done"] = True
        solved_locally = provider is None and tier != 3 and not escalation_reason
        try:
            self.experience.outcome(rec.get("experience_used") or [], solved_locally)
        except OSError as exc:
            self.log(f"experience: {exc}")
        lad = rec.get("ladder")
        if not lad:
            return
        step = lad.get("solved_by") or ("claude" if provider == "claude" else "cloud" if provider == "cloud" else None)
        if not step:
            return
        users = [m for m in (rec.get("request") or {}).get("messages") or [] if m.get("role") == "user"]
        q = _bare_question(message_text(users[-1]))[:300] if users else ""
        if not q:
            return
        try:
            final = next((t["answer"].get("content") for t in reversed(rec.get("tiers") or [])
                          if isinstance(t, dict) and isinstance(t.get("answer"), dict) and t["answer"].get("content")), "")
            asyncio.get_running_loop().create_task(self._write_lesson(q, lad["first_error"], step,
                                                                      strip_appendix(final or "")[:600]))
        except RuntimeError:
            pass

    async def _write_lesson(self, question: str, error: str, step: str, answer: str = "") -> None:
        """本機把解題過程摘要成一兩句「下次要注意」；失敗就用規則寫一句。 / The local model summarises the lesson."""
        from ..experience import LESSON_PROMPT, STEPS
        lesson = ""
        try:
            base = await self.sup.acquire()
            try:
                r = await self.local.post(f"{base}/v1/chat/completions", json={
                    "model": self.sup.core["name"] if self.sup.core else self.s.core_model,
                    "messages": [{"role": "user", "content": LESSON_PROMPT.format(
                        question=question, error=error, step=STEPS.get(step, step), answer=answer or "（無）")}],
                    "temperature": 0, "max_tokens": 220, "chat_template_kwargs": {"enable_thinking": False}})
                r.raise_for_status()
                lesson = (_message(r.json()).get("content") or "").strip()
            finally:
                self.sup.release()
        except Exception as exc:  # noqa: BLE001 - 經驗寫不出來不影響回答 / never blocks answers
            self.log(f"experience: lesson summary failed: {type(exc).__name__}: {exc}")
        if not lesson:
            lesson = f"類似問題第一次容易出錯（{error[:60]}）；要{STEPS.get(step, step)}才解決，作答前先仔細核對資料。"
        try:
            await anyio.to_thread.run_sync(self.experience.record, question, error, step, lesson)
        except OSError as exc:
            self.log(f"experience: {exc}")

    # ── 本機看圖工具（add-vision-tools）/ Local vision tools ──
    async def _vision_look(self, base: str, body: dict, rec: dict):
        """回答前跑偵測與開放詞彙比對，問「有哪些東西」時再切塊放大逐塊看；結果當資料附給核心。
        失敗或逾時就略過那一步，照原本看圖。
        Before answering: detection and open-vocabulary scoring, plus a tile-by-tile look for listing questions.
        Results go to the core as data; a failed or slow step is skipped."""
        from .. import vision_tools as V
        urls = V.images_in(body)
        if not urls:
            return None
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        asks_text = last is not None and bool(V.TEXT_QUESTION.search(message_text(last)))
        # 看圖工具開著就每張都讀字（核對時用）；只開 OCR 時 auto 只在問字時讀（add-image-ocr）
        # With the vision tools on, OCR every image; OCR alone in auto mode reads only for text questions
        tools_on = self.vision is not None or bool(self.s.vision_tools)
        want_ocr = self.ocr is not None and (tools_on or self.ocr_mode == "on" or asks_text)
        if self.vision is None and not want_ocr:
            return None
        _stage("looking")
        try:
            img = V.image_from_url(urls[0])
        except Exception:  # noqa: BLE001 - 壞圖交給引擎處理 / a broken image is the engine's problem
            img = None
        if img is None:
            return None
        seen = None
        if self.vision is not None:
            try:
                seen = await asyncio.wait_for(asyncio.to_thread(self.vision.look, img), VISION_TIMEOUT_S)
                rec["vision"] = {"detections": seen.detections, "hints": seen.hints, "seconds": seen.seconds}
            except asyncio.TimeoutError:
                rec["vision"] = {"error": f"timeout after {VISION_TIMEOUT_S}s"}
            except Exception as exc:  # noqa: BLE001 - 工具壞了不擋回答 / a broken tool never blocks the answer
                rec["vision"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
                self.log(f"vision tools: {rec['vision']['error']}")
        read = await self._vision_ocr(img, rec) if want_ocr else None
        text_q = read is not None and asks_text
        # 問字就不切塊；切塊屬於看圖工具，只開 OCR 時不切 / no tiles for text questions or without the vision tools
        found = [] if text_q or not tools_on else await self._vision_tiles(base, img, body, rec)
        if seen is None and not found and read is None:
            return None
        from ..vision_ocr import ocr_text
        extra = ([{"role": "system", "content": V.hint_text(seen)}] if seen is not None else []) + \
            ([{"role": "system", "content": ocr_text(read)}] if read is not None else []) + \
            ([{"role": "system", "content": V.tile_hint(found)}] if found else [])
        body["messages"] = [*body["messages"], *extra]
        body.setdefault("repeat_penalty", 1.1)   # 列舉圖中物體時小模型容易重複 / small models loop when listing objects
        seen = seen or V.Seen()
        seen.tile_names = {n for _, names in found for n in names}
        seen.text = "\n".join(read.lines) if read is not None else ""
        self._seen[rec["id"]] = seen
        return seen

    async def _vision_ocr(self, img, rec: dict):
        """圖中文字；沒有字、逾時或失敗就回傳 None（照原本看圖）。軌跡只記行數與秒數，不記內容。
        Text in the image; None when there is none or the tool fails. Only counts go to the trajectory."""
        v = rec.setdefault("vision", {})
        try:
            read = await asyncio.wait_for(asyncio.to_thread(self.ocr.read, img), OCR_TIMEOUT_S)
        except asyncio.TimeoutError:
            v["ocr"] = {"error": f"timeout after {OCR_TIMEOUT_S}s"}
            return None
        except Exception as exc:  # noqa: BLE001 - 工具壞了不擋回答 / a broken tool never blocks the answer
            v["ocr"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            self.log(f"vision ocr: {v['ocr']['error']}")
            return None
        v["ocr"] = {"lines": len(read.lines), "seconds": read.seconds}
        return read if read.lines else None

    async def _vision_tiles(self, base: str, img, body: dict, rec: dict) -> list[tuple[str, list[str]]]:
        """問題要列舉圖中東西、圖又夠大時：切塊放大，核心逐塊列出看到的東西（使用者 2026-11-18）。
        For listing questions on large enough images: the core lists what it sees in each enlarged tile."""
        from .. import vision_tools as V
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        if last is None or not V.LISTING.search(message_text(last)):
            return []
        parts = await asyncio.to_thread(V.tiles, img)
        if not parts:
            return []
        t0, found, errors = time.monotonic(), [], 0
        model = self.sup.core["name"] if self.sup.core else self.s.core_model
        for where, crop in parts:
            if time.monotonic() - t0 > TILE_BUDGET_S:
                errors += 1
                continue
            try:
                r = await self.local.post(f"{base}/v1/chat/completions", json={
                    "model": model, "messages": [{"role": "user", "content": [
                        {"type": "text", "text": V.TILE_PROMPT},
                        {"type": "image_url", "image_url": {"url": V.data_url(crop)}}]}],
                    "temperature": 0, "max_tokens": V.TILE_MAX_TOKENS, "repeat_penalty": 1.15,
                    "chat_template_kwargs": {"enable_thinking": False}}, timeout=TILE_TIMEOUT_S)
                r.raise_for_status()
                found.append((where, V.parse_tile_list(_message(r.json()).get("content") or "")))
            except Exception as exc:  # noqa: BLE001 - 一塊失敗就略過那塊 / skip a failed tile
                errors += 1
                self.log(f"vision tiles: {where}: {type(exc).__name__}: {exc}")
        rec.setdefault("vision", {})["tiles"] = {"grid": len(parts), "seconds": round(time.monotonic() - t0, 2),
                                                 "found": {w: n for w, n in found}, "failed": errors}
        return found

    async def _vision_check(self, base: str, rec: dict, final: dict) -> None:
        """回答說圖裡有的東西逐一核對，分數低的標「（不確定）」（使用者 2026-11-18：保留並標註）。
        Score every object the answer claims; low scorers are marked "(uncertain)" and kept."""
        from .. import vision_tools as V
        seen = self._seen.get(rec["id"])
        msg = _message(final)
        answer = msg.get("content") or ""
        if seen is None or seen.features is None or not answer.strip() or msg.get("tool_calls"):
            return
        answer, removed = V.collapse_repeats(answer)
        if removed:
            msg["content"] = answer
            rec["vision_repeats_removed"] = removed
        try:
            r = await self.local.post(f"{base}/v1/chat/completions", json={
                "model": self.sup.core["name"] if self.sup.core else self.s.core_model,
                "messages": [{"role": "user", "content": V.EXTRACT_PROMPT.format(answer=answer[:4000])}],
                "response_format": {"type": "json_schema", "json_schema": {"schema": V.EXTRACT_SCHEMA}},
                "temperature": 0, "max_tokens": 1600, "chat_template_kwargs": {"enable_thinking": False}})
            r.raise_for_status()
            objs = json.loads(_message(r.json()).get("content") or "{}").get("objects") or []
            pairs = [(o["zh"].strip(), o["en"].strip().lower()) for o in objs
                     if isinstance(o, dict) and o.get("zh") and o.get("en")]
            scores = await asyncio.to_thread(self.vision.check, seen, sorted({en for _, en in pairs}))
        except Exception as exc:  # noqa: BLE001 - 核對失敗就不標，照原答案 / no marks when the check fails
            rec["vision_check"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            return
        # 切塊放大時看到的不標：整張縮小後 OWLv2 在密集小圖上分不開（2026-11-18 第二張拼貼：猞猁、德牧、大象在場卻被標）
        # Objects seen in an enlarged tile are not marked: on dense collages the whole-image score cannot separate them
        tiled = getattr(seen, "tile_names", set())
        # 圖中文字裡的詞不是物體（2026-11-25 招牌圖：「電話：(02)…」的「電話」被當成電話機標「不確定」）
        # Words read from the image are text, not objects (the label 電話 on a sign was marked as an absent phone)
        text = getattr(seen, "text", "")
        low = [zh for zh, en in pairs if scores.get(en, 1.0) < V.CHECK_MIN and zh not in tiled
               and not (text and (zh in text or en in V.TEXT_CARRIERS))]
        if low:
            msg["content"] = V.mark_uncertain(answer, low)
        rec["vision_check"] = {"objects": {f"{zh}/{en}": scores.get(en) for zh, en in pairs}, "uncertain": low,
                               "threshold": V.CHECK_MIN}

    async def _tier2(self, base: str, body: dict, rec: dict, t0: float, stream: bool, last: dict, ver: dict
                     ) -> Response | None:
        """第 2 層：協助者只給回饋，本機帶著回饋重答一次。通過就回覆；回傳 None 表示繼續第 3 層。
        Tier 2: the helper gives feedback only and the local model answers once more. None means go on to tier 3."""
        msgs = escalation.feedback_request(body, _message(last), ver.get("error") or "")
        _stage("asking_feedback")
        try:
            if self._auto_route() == "consult":
                ans = await self.consultant.ask({"messages": msgs})
                if self.consult_cap:
                    self.consult_cap.take()
                helper, model, feedback, usage = "claude", ans.get("model"), ans.get("content") or "", ans.get("usage")
            else:
                self.cap.take()
                resp, info = await self._cloud_once({"messages": msgs, "max_tokens": escalation.FEEDBACK_MAX_TOKENS})
                helper, model, feedback, usage = "cloud", info["model"], _message(resp).get("content") or "", info["usage"]
        except (consult_mod.ConsultError, httpx.HTTPError) as exc:
            rec["tiers"].append({"tier": 2, "error": f"feedback unavailable: {exc}"})
            return None
        if not feedback.strip():
            rec["tiers"].append({"tier": 2, "error": "empty feedback"})
            return None
        self._untrainable(rec, "helper", helper)  # 答案受協助者影響（Claude 的內容不當訓練資料；其他雲端待查條款）/ shaped by the helper
        try:
            resp2 = await self._local_once(base, body, escalation.feedback_messages(
                body["messages"], _message(last), ver.get("error") or "", feedback))
        except httpx.HTTPError as exc:
            rec["tiers"].append({"tier": 2, "helper": helper, "error": str(exc)})
            return None
        ver2 = escalation.verify(body, _message(resp2), self._grounding(body, rec))
        rec["tiers"].append({"tier": 2, "answer": _message(resp2), "verification": ver2, "model": resp2.get("model"),
                             "tps": _tps(resp2), "helper": helper, "helper_model": model,
                             "feedback": feedback[:escalation.FEEDBACK_MAX_CHARS], "helper_usage": usage,
                             "training_use": False})
        if ver2["status"] == "fail":
            return None
        meta = self._meta(rec, 2, resp2, ver2, t0, escalation="feedback")
        meta.update(training_use=False, feedback_from=helper)
        return self._deliver(resp2, meta, rec, stream)

    async def _respond_cloud(self, body: dict, rec: dict, t0: float, stream: bool, reason: str) -> Response:
        _stage("asking_cloud")
        self.cap.take()
        try:
            resp, info = await self._cloud_once(body)
        except httpx.HTTPError as exc:
            # 雲端失敗時，若有本機答案就回本機答案 / on cloud failure, fall back to a local answer if any
            rec["tiers"].append({"tier": 3, "provider": "cloud", "error": str(exc)})
            return self._fallback_local(rec, t0, stream, "cloud_failed", f"cloud escalation failed: {exc}")
        rec["tiers"].append({"tier": 3, "provider": "cloud", "answer": _message(resp), "model": info["model"],
                             "reason": reason, "usage": info["usage"], "cost": info["cost"]})
        self._untrainable(rec, "cloud", info["model"])  # 雲端回答不當訓練資料 / cloud answers are never training data
        self._remember(body, rec, _message(resp), "cloud", info["model"])
        ver = escalation.verify(body, _message(resp)) if rec.get("json_mode") else None
        if ver:
            rec["tiers"][-1]["verification"] = ver
        meta = self._meta(rec, 3, resp, ver, t0, escalation=reason, cloud=info)
        return self._deliver(resp, meta, rec, stream)

    async def _consult_once(self, body: dict) -> tuple[dict, dict]:
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        text = last["content"] if last and isinstance(last.get("content"), str) else ""
        from ..consult_hints import hints_for
        hints = ([self.writing.consult_hint(text)] if self.writing is not None else []) + hints_for(text)
        hints = [h for h in hints if h]
        if hints:  # 提示 Claude 可上網參考的網站（使用者 2026-11-15）/ sites Claude may read online
            body = {**body, "messages": [*body["messages"][:-1], {"role": "system", "content": "\n".join(hints)},
                                         body["messages"][-1]]}
        ans = await self.consultant.ask(body)
        if self.consult_cap:
            self.consult_cap.take()
        msg = {"role": "assistant", "content": ans["content"]}
        called = bool(body.get("tools")) and escalation.text_calls_to_tool_calls(msg, body["tools"])
        resp = {"id": f"chatcmpl-consult-{int(time.time() * 1000)}", "object": "chat.completion",
                "created": int(time.time()), "model": ans["model"], "usage": ans["usage"],
                "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if called else "stop"}]}
        return resp, ans

    def _deliver_consult(self, body: dict, rec: dict, t0: float, stream: bool, resp: dict, ans: dict,
                         tier, reason: str) -> Response:
        """Claude 的回答一律標記為不可用於訓練（design D9）。 / Claude's answers are never usable for training."""
        self._untrainable(rec, "consultation", "claude")
        msg = _message(resp)
        self._remember(body, rec, msg, "claude", ans["model"])
        ver = escalation.verify(body, msg) if body.get("tools") or rec.get("json_mode") else None
        rec["tiers"].append({"tier": tier, "provider": "claude", "answer": msg, "model": ans["model"],
                             "reason": reason, "usage": ans["usage"], "cost_equivalent_usd": ans.get("cost_equivalent_usd"),
                             "verification": ver, "training_use": consult_mod.TRAINING_USE})
        total = ans["usage"]["prompt_tokens"] + ans["usage"]["completion_tokens"]
        meta = self._meta(rec, tier, resp, ver, t0, escalation=reason,
                          cloud={"usage": {"total_tokens": total}, "cost": ans.get("cost_equivalent_usd")})
        meta.update(provider="claude", training_use=consult_mod.TRAINING_USE)
        return self._deliver(resp, meta, rec, stream)

    async def _respond_consult(self, body: dict, rec: dict, t0: float, stream: bool) -> Response:
        """`jiezi-ask-claude`：直接請教 Claude（design D9）。 / Ask Claude directly."""
        self._untrainable(rec, "consultation", "claude")
        if self.consultant is None:
            return self._finish_error(rec, 503, "consulting Claude is off (set JIEZI_CONSULT=claude-cli in .env)",
                                      "consult_off")
        if self.consult_cap and not self.consult_cap.available():
            return self._finish_error(rec, 503, "today's Claude consultations are used up", "consult_daily_cap")
        _stage("asking_claude")
        try:
            resp, ans = await self._consult_once(body)
        except consult_mod.ConsultError as exc:
            return self._finish_error(rec, 503, f"cannot consult Claude right now: {exc}", "consult_unavailable")
        return self._deliver_consult(body, rec, t0, stream, resp, ans, tier="consult", reason="policy")

    def _meta(self, rec: dict, tier: int, resp: dict, ver: dict | None, t0: float, escalation: str | None = None,
              cloud: dict | None = None) -> dict:
        usage = (cloud or {}).get("usage") or {}
        inj = rec.get("injection") or {}
        from ..injection import WARNING
        return {"injection": {"suspected": inj["suspected"], "where": inj["where"], "warning": WARNING}
                if inj.get("suspected") else None,
                "tier": tier, "policy": rec["policy"], "model": resp.get("model"),
                "verification": (ver or {}).get("status", "not_applicable" if tier != 3 else "cloud"),
                "verification_error": (ver or {}).get("error"), "escalation": escalation,
                "latency_s": elapsed(t0), "tps": _tps(resp),
                "cloud": {"tokens": usage.get("total_tokens"), "cost": (cloud or {}).get("cost")} if cloud else None,
                "trajectory_id": rec["id"], "sources": rec.get("sources") or [],
                "confidence": rec.get("confidence"),
                **({"vision_check": rec["vision_check"]} if rec.get("vision_check") else {}),
                **({"image_paths": rec["image_paths"]} if rec.get("image_paths") else {}),
                "process": self._process(rec), **self._experience_meta(rec, tier, escalation),
                **self._notebook_meta(rec, resp)}

    def _notebook_ground(self, body: dict, rec: dict, last: dict, data: list | None) -> None:
        from ..notebooks.chat import ground
        ground(self, body, rec, last, data)

    def _notebook_meta(self, rec: dict, resp: dict) -> dict:
        """筆記本：引用檢查、查證、自動存記憶（add-notebooks）；失敗不影響回答。 / Never blocks the answer."""
        if not rec.get("notebook_ctx"):
            return {}
        try:
            from ..notebooks.chat import after
            return after(self, rec, resp)
        except Exception as exc:  # noqa: BLE001
            self.log(f"notebook: {type(exc).__name__}: {exc}")
            return {}

    def _experience_meta(self, rec: dict, tier, escalation_reason: str | None) -> dict:
        """經驗的結算（附上的經驗記有效／無效、寫新經驗）；回傳要放進 meta 的欄位。 / Settle lessons for this answer."""
        provider = next((t.get("provider") for t in reversed(rec.get("tiers") or [])
                         if isinstance(t, dict) and t.get("answer") and t.get("tier") == 3), None)
        try:
            self._web_memo(rec)
        except Exception as exc:  # noqa: BLE001
            self.log(f"web memo: {type(exc).__name__}: {exc}")
        try:
            self._teachers_later(rec, tier, provider)
        except Exception as exc:  # noqa: BLE001
            self.log(f"teacher: {type(exc).__name__}: {exc}")
        try:
            self._experience_done(rec, tier, escalation_reason, provider)
        except Exception as exc:  # noqa: BLE001
            self.log(f"experience: {type(exc).__name__}: {exc}")
        return {"experience": rec["experience_used"]} if rec.get("experience_used") else {}

    def _process(self, rec: dict) -> list[dict]:
        """回答的過程（add-answer-process）；整理失敗不影響回答。 / Steps behind the answer; never blocks it."""
        from .process import steps
        try:
            return steps(rec)
        except Exception as exc:  # noqa: BLE001
            self.log(f"process: {type(exc).__name__}: {exc}")
            return []

    def _deliver(self, resp: dict, meta: dict, rec: dict, stream: bool) -> Response:
        if rec.get("json_mode"):
            # JSON 模式：回答只留 JSON（去掉程式碼框與說明），不加附錄；來源仍在 jiezi.sources
            # JSON mode: the answer is bare JSON, no appendix; sources stay in jiezi.sources
            from .jsonout import normalize
            for ch in resp.get("choices") or []:
                msg = ch.get("message") or {}
                if not msg.get("tool_calls"):
                    normalize(msg)
        elif rec.get("dict_appendix") or rec.get("notebook_answer"):
            for ch in resp.get("choices") or []:
                msg = ch.get("message") or {}
                base = rec.get("notebook_answer") or strip_appendix(msg.get("content") or "")
                msg["content"] = base.rstrip() + (rec.get("dict_appendix") or "")
        rec.update(final_tier=meta["tier"], jiezi=meta)
        self.traj.write(rec)
        if not stream:
            return JSONResponse({**resp, "jiezi": meta})
        return StreamingResponse(self._synth_stream(resp, meta), media_type="text/event-stream")

    async def _synth_stream(self, resp: dict, meta: dict) -> AsyncIterator[bytes]:
        """把完整答案以 OpenAI 串流格式送出。 / Emit a complete answer in OpenAI stream format."""
        msg = _message(resp)
        base = {"id": resp.get("id") or f"chatcmpl-{meta['trajectory_id']}", "object": "chat.completion.chunk",
                "created": int(time.time()), "model": resp.get("model")}
        delta = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            delta["tool_calls"] = [{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])]
        finish = ((resp.get("choices") or [{}])[0]).get("finish_reason") or "stop"
        yield _sse({**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
        yield _sse({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
        yield _sse({**base, "choices": [], "jiezi": meta})
        yield b"data: [DONE]\n\n"

    async def _relay_stream(self, base: str, body: dict, rec: dict, t0: float, policy: str = "jiezi-local"
                            ) -> AsyncIterator[bytes]:
        """直接轉送本機串流；客戶端中斷時取消上游。送完後若本機答不出來（design D9），在同一個串流接著送出
        Claude（或雲端）的回答。
        Relay the local stream; cancel upstream on disconnect. If the local model could not answer (design D9),
        append Claude's (or the cloud's) answer to the same stream."""
        content, last, status, finish, released = [], {}, "ok", None, False
        conv = TaiwanStream() if self.s.tw_phrases else None
        try:
            async with self.local.stream("POST", f"{base}/v1/chat/completions",
                                         json=self._local_body(body, stream=True)) as r:
                if r.status_code != 200:
                    status = f"engine_http_{r.status_code}"
                    yield _sse({"error": {"message": f"local engine HTTP {r.status_code}", "code": "engine_error"}})
                    return
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        yield (line + "\n\n").encode("utf-8")
                        continue
                    last = chunk
                    for ch in chunk.get("choices") or []:
                        delta = ch.get("delta") or {}
                        if delta.get("content"):
                            delta["content"] = conv.feed(delta["content"]) if conv else to_traditional(delta["content"])
                        if conv and ch.get("finish_reason"):  # 結束前送出暫留的字 / release held text before finishing
                            delta["content"] = (delta.get("content") or "") + conv.flush()
                            ch["delta"] = delta
                        content.append(delta.get("content") or "")
                        finish = ch.get("finish_reason") or finish
                    yield _sse(chunk)
            rest = conv.flush() if conv else ""
            if rest:
                content.append(rest)
                yield _sse({"id": last.get("id"), "object": "chat.completion.chunk", "created": int(time.time()),
                            "model": last.get("model"),
                            "choices": [{"index": 0, "delta": {"content": rest}, "finish_reason": None}]})
            self.sup.release()
            released = True
            text = "".join(content)
            ver = escalation.verify(body, {"content": text}, self._grounding(body, rec))
            help_reason = self._keep_local(escalation.needs_help({"content": text}, finish), body, rec)
            grounded = next((c for c in ver.get("checks") or [] if c["check"] == "grounded"), {})
            if grounded.get("status") == "fail":
                # 串流已送出，無法重答：附上提醒，並在 jiezi 策略下自動請教 / already streamed: warn, then consult
                help_reason = help_reason or "unsupported_claims"
                yield _sse({"id": last.get("id"), "object": "chat.completion.chunk", "created": int(time.time()),
                            "model": last.get("model"), "choices": [{"index": 0, "delta": {
                                "content": "\n\n［查核：" + "、".join(grounded["unsupported"][:6])
                                           + " 在附上的資料裡找不到，請小心］"}, "finish_reason": None}]})
            rec["tiers"].append({"tier": 0, "answer": {"role": "assistant", "content": text}, "verification": ver,
                                 "model": last.get("model"), "tps": _tps(last), "needs_help": help_reason})
            if rec.get("dict_appendix"):
                yield _sse({"id": last.get("id"), "object": "chat.completion.chunk", "created": int(time.time()),
                            "model": last.get("model"),
                            "choices": [{"index": 0, "delta": {"content": rec["dict_appendix"]}, "finish_reason": None}]})
            if help_reason and self.s.ladder and policy in ("jiezi", "jiezi-local"):
                # 串流也先本機試到底；成功就接上新的回答，畫面會換成新的（local-first-solving）
                # Streaming also tries the local rungs first; a success is appended and replaces the shown answer
                stage = _inline_progress("retrying")
                if stage:
                    yield stage
                got = await self._ladder(base, body, rec, policy, {"role": "assistant", "content": text}, ver,
                                         help_reason)
                if got:
                    resp2, ver2, tier2 = got
                    sep = "\n\n—— 本機重新想過，以下是新的回答 / The local model reconsidered; new answer below ——\n\n"
                    yield _sse({"id": last.get("id"), "object": "chat.completion.chunk", "created": int(time.time()),
                                "model": resp2.get("model"), "choices": [{"index": 0, "delta": {
                                    "content": sep + strip_appendix(_message(resp2).get("content") or "")},
                                    "finish_reason": None}]})
                    meta = self._meta(rec, 1 if tier2 == "think" else tier2, resp2, ver2, t0)
                    rec.update(final_tier=meta["tier"], jiezi=meta)
                    yield _sse({"id": last.get("id"), "object": "chat.completion.chunk", "created": int(time.time()),
                                "model": resp2.get("model"), "choices": [], "jiezi": meta})
                    yield b"data: [DONE]\n\n"
                    return
            route = self._auto_route() if policy == "jiezi" and help_reason else None
            if route:
                async for chunk in self._stream_escalation(body, rec, t0, last, help_reason, route):
                    yield chunk
                return
            why = help_reason and ("local_only_policy" if policy != "jiezi" else self._no_route_reason())
            meta = self._meta(rec, 0, last, ver, t0,
                              escalation=why or ("not_retried_in_streaming" if ver["status"] == "fail" else None))
            rec.update(final_tier=0, jiezi=meta)
            yield _sse({"id": last.get("id"), "object": "chat.completion.chunk", "created": int(time.time()),
                        "model": last.get("model"), "choices": [], "jiezi": meta})
            yield b"data: [DONE]\n\n"
        except anyio.get_cancelled_exc_class():
            status = "client_disconnected"
            rec["tiers"].append({"tier": 0, "answer": {"role": "assistant", "content": "".join(content)},
                                 "partial": True})
            raise
        except httpx.HTTPError as exc:
            status = "engine_error"
            yield _sse({"error": {"message": f"local engine error: {exc}", "code": "engine_error"}})
        finally:
            rec["status"] = status
            if not released:
                self.sup.release()
            self.traj.write(rec)

    async def _stream_escalation(self, body: dict, rec: dict, t0: float, last: dict, reason: str, route: str
                                 ) -> AsyncIterator[bytes]:
        """在串流後面接上轉交的回答。 / Append the escalated answer to a stream."""
        who = "Claude" if route == "consult" else "雲端 / cloud"
        sep = f"\n\n—— 本機答不出來，以下由 {who} 回答 / The local model could not answer; {who} answers below ——\n\n"
        base = {"id": last.get("id"), "object": "chat.completion.chunk", "created": int(time.time())}
        yield _sse({**base, "model": last.get("model"),
                    "choices": [{"index": 0, "delta": {"content": sep}, "finish_reason": None}]})
        stage = _inline_progress("asking_claude" if route == "consult" else "asking_cloud")
        if stage:
            yield stage
        try:
            if route == "consult":
                resp, ans = await self._consult_once(body)
                self._untrainable(rec, "consultation", "claude")
                msg = _message(resp)
                self._remember(body, rec, msg, "claude", ans["model"])
                rec["tiers"].append({"tier": 3, "provider": "claude", "answer": msg, "model": ans["model"],
                                     "reason": reason, "usage": ans["usage"],
                                     "cost_equivalent_usd": ans.get("cost_equivalent_usd"),
                                     "training_use": consult_mod.TRAINING_USE})
                total = ans["usage"]["prompt_tokens"] + ans["usage"]["completion_tokens"]
                meta = self._meta(rec, 3, resp, None, t0, escalation=reason,
                                  cloud={"usage": {"total_tokens": total}, "cost": ans.get("cost_equivalent_usd")})
                meta.update(provider="claude", training_use=consult_mod.TRAINING_USE)
            else:
                self.cap.take()
                resp, info = await self._cloud_once(body)
                msg = _message(resp)
                self._remember(body, rec, msg, "cloud", info["model"])
                rec["tiers"].append({"tier": 3, "provider": "cloud", "answer": msg, "model": info["model"],
                                     "reason": reason, "usage": info["usage"], "cost": info["cost"]})
                meta = self._meta(rec, 3, resp, None, t0, escalation=reason, cloud=info)
                meta["provider"] = "cloud"
        except (consult_mod.ConsultError, httpx.HTTPError) as exc:
            rec["tiers"].append({"tier": 3, "provider": "claude" if route == "consult" else "cloud", "error": str(exc)})
            note = f"（{who} 目前無法回答 / {who} cannot answer now: {exc}）"
            yield _sse({**base, "model": last.get("model"),
                        "choices": [{"index": 0, "delta": {"content": note}, "finish_reason": None}]})
            meta = self._meta(rec, 0, last, None, t0, escalation=f"{route}_failed")
            rec.update(final_tier=0, jiezi=meta)
            yield _sse({**base, "model": last.get("model"), "choices": [], "jiezi": meta})
            yield b"data: [DONE]\n\n"
            return
        rec.update(final_tier=3, jiezi=meta)
        yield _sse({**base, "model": resp.get("model"),
                    "choices": [{"index": 0, "delta": {"content": msg.get("content") or ""}, "finish_reason": "stop"}]})
        yield _sse({**base, "model": resp.get("model"), "choices": [], "jiezi": meta})
        yield b"data: [DONE]\n\n"

    def _finish_error(self, rec: dict, code: int, message: str, kind: str) -> JSONResponse:
        rec.update(status=kind, error=message)
        self.traj.write(rec)
        return _err(code, message, kind)

    # ── 背景 / Background ──
    async def ticker(self) -> None:
        while True:
            await anyio.sleep(TICK_S)
            try:
                await self.sup.tick()
                if self.embedder is not None:
                    await anyio.to_thread.run_sync(self.embedder.tick)
                if self.reranker is not None:
                    await anyio.to_thread.run_sync(self.reranker.tick)
            except Exception as exc:  # noqa: BLE001 - 背景工作不可中斷 gateway / never kill the gateway
                self.log(f"warning: supervisor tick: {exc}")

    async def aclose(self) -> None:
        await self.local.aclose()
        await self.cloud.aclose()


# Tauri 外殼的來源（Phase 8.4）；只對這些來源開放跨來源請求，其他網站一律不行。
# Origins of the Tauri shell; cross-origin requests are allowed for these only.
TAURI_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"]


def create_app(gw: Gateway) -> Starlette:
    @contextlib.asynccontextmanager
    async def lifespan(app):
        gw.sup.write_state()
        async with anyio.create_task_group() as tg:
            tg.start_soon(gw.ticker)
            try:
                yield
            finally:
                tg.cancel_scope.cancel()
                if gw.tts is not None:
                    gw.tts.shutdown()
                if gw.asr is not None:
                    gw.asr.shutdown()
                if gw.notebooks is not None:
                    gw.notebooks.close()
                gw.sup.shutdown()
                if gw.embedder is not None:
                    gw.embedder.stop()
                if gw.reranker is not None:
                    gw.reranker.stop()
                if gw.doc_vectors is not None:
                    gw.doc_vectors.close()
                await gw.aclose()

    return Starlette(routes=[
        Route("/v1/chat/completions", gw.chat, methods=["POST"]),
        Route("/v1/models", gw.models, methods=["GET"]),
        Route("/v1/embeddings", gw.embeddings, methods=["POST"]),
        Route("/v1/audio/speech", gw.audio_speech, methods=["POST"]),
        Route("/v1/audio/voices", gw.audio_voices, methods=["GET"]),
        Route("/v1/audio/transcriptions", gw.audio_transcriptions, methods=["POST"]),
        *_notebook_routes(gw),
        Route("/v1/documents", gw.documents, methods=["POST"]),
        Route("/v1/documents/warm", gw.documents_warm, methods=["POST"]),
        Route("/v1/agent/audit", gw.agent_audit, methods=["GET"]),
        Route("/v1/agent/approvals", gw.agent_approvals, methods=["GET"]),
        Route("/v1/agent/approvals/{rid}", gw.agent_approvals, methods=["GET", "POST"]),
        Route("/health", gw.health, methods=["GET"]),
        Route("/admin/unload", gw.admin_unload, methods=["POST"]),
        Route("/admin/trajectories", gw.admin_trajectories, methods=["GET"]),
        Route("/admin/doctor", gw.admin_doctor, methods=["GET"]),
        Route("/admin/escalations", gw.admin_escalations, methods=["GET"]),
        Route("/admin/memory", gw.admin_memory, methods=["GET"]),
        Route("/admin/observability", gw.admin_observability, methods=["GET"]),
        *ui_routes(gw.s.root),
    ], lifespan=lifespan, middleware=[_cors()])


def _notebook_routes(gw):
    from ..notebooks.api import routes
    return routes(gw)


def _cors():
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    return Middleware(CORSMiddleware, allow_origins=TAURI_ORIGINS, allow_methods=["GET", "POST"],
                      allow_headers=["Authorization", "Content-Type"], allow_credentials=False)


# 桌面 App 前端（Phase 8.4 雛形）：只提供本機建好的檔案，嚴格 CSP，不載入遠端內容（Phase 8.5）。
# Desktop front end (Phase 8.4 prototype): local build only, strict CSP, no remote content (Phase 8.5).
UI_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
          "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
          "form-action 'none'")


def ui_routes(root):
    from starlette.routing import Mount
    from starlette.staticfiles import StaticFiles
    dist = root / "ui" / "dist"
    if not dist.is_dir():
        return []

    class SecureStatic(StaticFiles):
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            resp.headers["Content-Security-Policy"] = UI_CSP
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Referrer-Policy"] = "no-referrer"
            return resp
    return [Mount("/ui", app=SecureStatic(directory=str(dist), html=True), name="ui")]

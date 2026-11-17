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
CORRECTION_DIRECT = 0.5


def message_text(m: dict) -> str:
    """訊息的文字部分（多段內容只取文字）。 / The text of a message (text parts of multi-part content)."""
    c = m.get("content")
    if isinstance(c, list):
        return "\n".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text").strip()
    return c if isinstance(c, str) else ""


def has_images(body: dict) -> bool:
    return any(isinstance(m.get("content"), list) and any(
        isinstance(p, dict) and p.get("type") in ("image_url", "input_image") for p in m["content"])
        for m in body.get("messages") or [])
EMBED_MAX_INPUTS, EMBED_MAX_CHARS = 64, 8000  # 問題和更正過的問題相似到這個程度，就直接照更正回答 / serve a correction at this similarity
from .supervisor import EngineUnavailable, Supervisor
from .trajectory import TrajectoryWriter, elapsed, new_id, now_iso

MAX_WARM_BYTES = 8 * 1024 * 1024  # 預先建向量的文字上限 / text limit for warming
TOO_LARGE_ROOM = 128            # 至少要留這麼多 token 給回答 / tokens that must remain for an answer
TICK_S = 5.0
COST_HEADER = "x-litellm-response-cost"


def _err(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": code, "code": code}}, status_code=status)


def _sse(obj) -> bytes:
    return b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n\n"


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
                self.memory = Memory(wiki_path(settings.root))
            except Exception as exc:  # noqa: BLE001 - 記憶壞了不影響回答 / a broken memory never blocks answers
                self.memory_note = str(exc)
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
            self.skills = Skills(skills_path(settings.root))
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
                    self.laws_hybrid = HybridRetriever(lw, store, embedder, settings.rag_min,
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
        # 每個槽位 4096 token：超出就裁（最舊對話 → 最長資料 → 問題）/ fit the 4096-token slot
        from .context import fit, merge_system
        out["messages"], trim = fit(msgs, body.get("tools"), body.get("max_tokens") or body.get("max_completion_tokens"))
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

    def _no_route_reason(self) -> str:
        if self.s.consult_auto and self.consultant is not None:
            return "consult_daily_cap"
        return self._can_escalate() or "no_escalation_route"

    async def _escalate(self, body: dict, rec: dict, t0: float, stream: bool, reason: str) -> Response:
        """自動轉交（design D5、D9）：Claude 失敗時改用雲端，再不行就回本機答案。
        Automatic escalation: on Claude failure try the cloud, else return the local answer."""
        if self._auto_route() == "consult":
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
            last = {"role": "user", "content": text, "_target": last,
                    "_doc": any(isinstance(p, dict) and p.get("type") in ("image_url", "input_image")
                                for p in last["content"])}
        elif not isinstance(last.get("content"), str):
            return
        else:
            from ..longdoc import needed, split_message
            if needed(last["content"]):  # 長文件：只用問題查資料 / long documents: look up with the question only
                _, q = split_message(last["content"])
                if not q:
                    return
                last = {"role": "user", "content": q, "_target": last, "_doc": True}
        found = []
        # 附了長文件：問題是在問文件，不用語意向量去知識庫／法規撈「看起來相關」的段落（2026-11-17 實測會蓋過文件、
        # 佔掉上下文）；問題裡直接點名的文章或法條照樣附。
        # With a long document attached the question is about the document: no fuzzy vector hits from the knowledge base
        # or statutes (they crowded out the document in a live test); explicitly named articles still attach.
        doc = bool(last.get("_doc"))
        if self.memory is not None:  # 記憶最優先（使用者的更正）/ memory first (the user's corrections)
            from ..memory import recall_block
            found.append(recall_block(last["content"], self.memory))
        if self.s.tools:  # 程式算好的數字 / numbers computed by code
            from ..tools import grounding as tool_grounding
            found.append(tool_grounding(last["content"]))
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
                rec["training_use"] = False  # 例如禁止改作的辭典 / e.g. a no-derivatives dictionary
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
            rec["training_use"] = False
            self.log(f"injection guard: suspected {info['suspected']} in {info['where']}")

    @staticmethod
    def _injected(rec: dict) -> bool:
        return bool((rec.get("injection") or {}).get("suspected"))

    # ── 記憶 / Memory（add-memory）──
    def _remember(self, body: dict, rec: dict, msg: dict, provider: str, model: str | None) -> None:
        """把請教／雲端的答案存進記憶 wiki；存不了不影響回答。 / Save to the memory wiki; failures never block."""
        if self.memory is None or body.get("tools") or rec.get("eval") or rec.get("json_mode"):
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
            rec["training_use"] = False
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
            if m:
                self.memory.save_note(m.group(1))
                rec["sources"] = [{"source": "memory", "page": "使用者要我記住的事", "kind": "note"}]
                rec.pop("dict_appendix", None)
                return self._memory_reply(rec, t0, stream, f"好，我記住了：{m.group(1).strip()}\n"
                                          "（存在記憶 wiki 的〈使用者要我記住的事〉，可以用 Obsidian 修改或刪除）")
            m = CORRECTION.match(q)
            answered = any(x.get("role") == "assistant" for x in msgs)
            if m and len(users) >= 2 and answered:
                prev = users[-2]["content"]
                page = self.memory.save_correction(prev, m.group(1))
                rec["sources"] = [{"source": "memory", "page": page, "kind": "correction"}]
                rec.pop("dict_appendix", None)
                return self._memory_reply(rec, t0, stream, f"好，已記下更正。之後問到「{prev.strip()[:60]}」會照這個說法回答："
                                          f"\n{m.group(1).strip()}")
            corrections = self.memory.corrections_for(q)
            best = max(corrections, key=lambda c: similarity(q, c.question), default=None)
            if policy in ("jiezi", "jiezi-local") and best and similarity(q, best.question) >= CORRECTION_DIRECT \
                    and len(users) == 1:
                # 使用者自己更正過的答案：直接照更正回答，不讓小模型再說錯 / answer with the user's own correction
                rec["sources"] = [{"source": "memory", "page": best.title, "kind": "correction"}]
                rec.pop("dict_appendix", None)
                return self._memory_reply(rec, t0, stream, f"根據你 {best.at[:10]} 的更正：{best.text}\n\n---\n"
                                          f"【記憶】[[{best.title}]]（問題：{best.question}）")
            if policy in ("jiezi", "jiezi-local") and storable(q, len(users) - 1) is None and not corrections:
                found = self.memory.find_answer(q)
                if found and found[1] >= EXACT:
                    e = found[0]
                    rec["sources"] = [{"source": "memory", "page": e.title, "kind": "answer", "similarity": 1.0}]
                    rec.pop("dict_appendix", None)
                    return self._memory_reply(
                        rec, t0, stream, e.text + f"\n\n---\n【記憶】{e.at[:10]} 請教{e.provider}的答案（[[{e.title}]]）；"
                        "要重新請教，請用 --claude 或在聊天中按 F2 切到 jiezi-ask-claude。", training=False)
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
                             "laws": "on" if self.laws else (self.laws_note or "off"),
                             "memory": "on" if self.memory else (self.memory_note or "off"),
                             "tools": "on" if self.s.tools else "off",
                             "cloud_escalation": self.s.cloud_ready, "cloud_used_today": self.cap.used(),
                             "cloud_daily_max": self.s.cloud_daily_max,
                             "trajectory": {"enabled": self.traj.enabled, "error": self.traj.last_error}})

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
        recs = load(self.s.root, 7)[-limit:]
        out = []
        for r in reversed(recs):
            users = [m for m in (r.get("request") or {}).get("messages") or [] if m.get("role") == "user"]
            out.append({"id": r.get("id"), "at": r.get("at"), "policy": r.get("policy"), "status": r.get("status"),
                        "final_tier": r.get("final_tier"), "training_use": r.get("training_use"),
                        "question": message_text(users[-1])[:200] if users else "",
                        "sources": sorted({s.get("source") for s in r.get("sources") or [] if s.get("source")})})
        return JSONResponse({"records": out})

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
        if not self._authorized(request):
            return _err(401, "invalid or missing gateway key", "unauthorized")
        body = await self._read_json(request)
        if isinstance(body, Response):
            return body
        policy = body.get("model") or "jiezi"
        if policy not in POLICIES:
            return _err(400, f"model must be one of {', '.join(POLICIES)}", "invalid_model")
        stream = bool(body.get("stream"))
        from . import jsonout
        try:
            json_mode = jsonout.spec(body) is not None  # add-json-output
        except jsonout.BadFormat as exc:
            return _err(400, str(exc), "invalid_response_format")
        tid = new_id() if self.traj.enabled else None
        # training_use：None 表示訓練前要依授權表確認；請教 Claude 的回答一律 False（design D9）
        # training_use: None means check the license registry before training; Claude consultations are always False
        rec = {"id": tid, "at": now_iso(), "policy": policy, "stream": stream, "request": body, "tiers": [],
               "final_tier": None, "status": "ok", "training_use": None, "sources": []}
        # 評測流量（selftest、toolcheck）：不學技能、不存記憶，避免評測污染自己（2026-11-16）
        # Evaluation traffic: no skill learning, no memory saving, so evaluations never contaminate themselves
        if request.headers.get("x-jiezi-eval") == "1":
            rec["eval"] = True
        if json_mode:
            rec["json_mode"] = True
        # 查資料可能要啟動 embedding 引擎，放到執行緒以免卡住其他請求 / may start the embedder; off the event loop
        data: list[dict] = []  # gateway 自己附加的資料訊息 / data messages the gateway attached
        await anyio.to_thread.run_sync(self._ground, body, rec, data)
        self._attach_skills(body, rec, data)
        if self.s.injection_guard:
            self._guard(body, rec, data)
        t0 = time.monotonic()
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
        if self.memory is not None and not body.get("tools") and not json_mode and not body.get("jiezi_translate"):
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
        big = self._too_large(body)
        if big:
            # 工具清單與系統提示本身就超過本機的上下文（例如帶幾十個工具的代理程式）：裁不掉，送了引擎只會回 400。
            # 2026-11-17 實測 OpenCode 一次送 58,000 token。能轉交就轉交，不能就回清楚的錯誤。
            # Tools and system prompts alone exceed the local context (agent clients with dozens of tools): nothing
            # can be trimmed and the engine would answer 400. Escalate when possible, else a clear error.
            rec["too_large"] = big
            if policy == "jiezi" and self._auto_route():
                return await self._escalate(body, rec, t0, stream, reason="context_too_large")
            return self._finish_error(
                rec, 413, f"這個請求裁短後仍約 {big['after']} token，超過本機模型的上下文（{big['ctx']} token）；"
                          "通常是工具清單或系統提示太長。請改用 jiezi 或 jiezi-ask-claude，或減少工具 / "
                          f"the request still needs about {big['after']} tokens after trimming but the local model's "
                          f"context is {big['ctx']}; use the jiezi or jiezi-ask-claude policy, or send fewer tools",
                "context_too_large")
        route = self._pre_route(body, rec) if policy == "jiezi" else None
        if route:
            # 路由器 v0（規則）：本機一定答不了的問題直接轉交，不先浪費一次本機生成
            # Router v0 (rules): questions the local model cannot answer go straight to escalation
            return await self._escalate(body, rec, t0, stream, reason=route)

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

        if stream and not body.get("tools") and not json_mode and not body.get("jiezi_translate") \
                and not self._sample_kind(body):
            return StreamingResponse(self._relay_stream(base, body, rec, t0, policy), media_type="text/event-stream")
        try:
            return await self._tiered(base, body, rec, t0, policy, stream)
        finally:
            self.sup.release()

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
        return {"mode": "chunked", "docs": docs, "to": target, "source": source, "glossary": glossary,
                "bilingual": (opts or {}).get("bilingual", True) is not False,
                "confirmed": bool((opts or {}).get("confirmed"))}

    def _translated(self, rec: dict, t0: float, stream: bool, text: str, tier, model: str, info: dict,
                    ver: dict | None = None) -> Response:
        resp = {"id": f"chatcmpl-translate-{int(time.time() * 1000)}", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}
        rec["tiers"].append({"tier": tier, "answer": resp["choices"][0]["message"], "verification": ver, "model": model})
        rec["translation"] = info
        rec["training_use"] = False   # 譯文對不對無法由程式證明；原文多為私人文件 / unverifiable, usually private
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

        async def complete(msgs: list[dict], max_tokens: int) -> str:
            r = await self._local_once(base, {"messages": msgs, "max_tokens": max_tokens, "temperature": 0.3}, msgs)
            return ((r.get("choices") or [{}])[0].get("message") or {}).get("content") or ""

        semantic = None
        if self.doc_vectors is not None:
            vectors, wait_s = self.doc_vectors, self.s.doc_embed_timeout_s

            async def semantic(question: str, text: str, parts: list[str]):
                return await anyio.to_thread.run_sync(vectors.order, question, text, parts, wait_s)

        t = time.monotonic()
        new, info = await condense(msgs[idx]["content"], complete, hint, budget, self.doc_notes, semantic)
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
    def _too_large(self, body: dict) -> dict | None:
        """裁到不能再裁還是放不進一個槽位就回傳 {"after", "ctx"}。 / Set when even full trimming cannot fit one slot."""
        from .context import SLOT_CTX, fit
        try:
            _, info = fit(body["messages"], body.get("tools"),
                          body.get("max_tokens") or body.get("max_completion_tokens"))
        except Exception:  # noqa: BLE001 - 估不出來就照舊送 / unknown shapes go through as before
            return None
        return {"after": info["after"], "ctx": SLOT_CTX} if info["after"] > SLOT_CTX - TOO_LARGE_ROOM else None

    def _pre_route(self, body: dict, rec: dict) -> str | None:
        """需要上網或即時資料、且沒有程式算好的答案時，直接轉交。 / Web/live questions without computed facts."""
        if body.get("tools") or not self._auto_route():
            return None
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        if not last or not isinstance(last.get("content"), str):
            return None
        if not LIVE.search(last["content"]):
            return None
        if any(s.get("source") in ("tools", "memory") for s in rec.get("sources") or []):
            return None  # 「今天星期幾」程式已算好；記憶裡有答案 / computed or remembered
        return "needs_web"

    # ── 平行取樣（add-sampling；開發計畫 4.1）/ Parallel sampling ──
    def _sample_kind(self, body: dict) -> str | None:
        """可驗證、值得取樣的問題種類。 / The kind of verifiable question worth sampling."""
        if self.s.samples <= 1:
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
        if help_reason and ver["status"] != "fail":
            # 本機自己表示不會：本機重試沒有幫助，直接轉交 / the local model says it can't: retrying won't help
            rec["tiers"][-1]["needs_help"] = help_reason
            if policy == "jiezi" and self._auto_route():
                return await self._escalate(body, rec, t0, stream, reason=help_reason)
            escalate_reason = "local_only_policy" if policy != "jiezi" else self._no_route_reason()
        if ver["status"] == "fail":
            msgs = escalation.retry_messages(body["messages"], _message(resp), ver["error"])
            try:
                resp1 = await self._local_once(base, body, msgs)
                ver1 = escalation.verify(body, _message(resp1), self._grounding(body, rec))
                rec["tiers"].append({"tier": 1, "answer": _message(resp1), "verification": ver1,
                                     "model": resp1.get("model"), "tps": _tps(resp1), "usage": resp1.get("usage")})
                final, tier, ver = resp1, 1, ver1
            except httpx.HTTPError as exc:
                rec["tiers"].append({"tier": 1, "error": str(exc)})
            if ver["status"] == "fail":
                if policy == "jiezi":
                    if self._auto_route():
                        if self.s.tier2:  # 第 2 層：先只要回饋，本機再答一次（add-partial-escalation）
                            done = await self._tier2(base, body, rec, t0, stream, final, ver)
                            if done is not None:
                                return done
                        return await self._escalate(body, rec, t0, stream, reason="verification_failed")
                    escalate_reason = self._no_route_reason()
                else:
                    escalate_reason = "local_only_policy"
        if not escalate_reason:
            self._learn_skill(body, rec, final, ver)
        meta = self._meta(rec, tier, final, ver, t0, escalation=escalate_reason)
        return self._deliver(final, meta, rec, stream)

    async def _tier2(self, base: str, body: dict, rec: dict, t0: float, stream: bool, last: dict, ver: dict
                     ) -> Response | None:
        """第 2 層：協助者只給回饋，本機帶著回饋重答一次。通過就回覆；回傳 None 表示繼續第 3 層。
        Tier 2: the helper gives feedback only and the local model answers once more. None means go on to tier 3."""
        msgs = escalation.feedback_request(body, _message(last), ver.get("error") or "")
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
        rec["training_use"] = False  # 答案受協助者影響（Claude 的內容不當訓練資料；其他雲端待查條款）/ shaped by the helper
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
        self.cap.take()
        try:
            resp, info = await self._cloud_once(body)
        except httpx.HTTPError as exc:
            # 雲端失敗時，若有本機答案就回本機答案 / on cloud failure, fall back to a local answer if any
            rec["tiers"].append({"tier": 3, "provider": "cloud", "error": str(exc)})
            return self._fallback_local(rec, t0, stream, "cloud_failed", f"cloud escalation failed: {exc}")
        rec["tiers"].append({"tier": 3, "provider": "cloud", "answer": _message(resp), "model": info["model"],
                             "reason": reason, "usage": info["usage"], "cost": info["cost"]})
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
        resp = {"id": f"chatcmpl-consult-{int(time.time() * 1000)}", "object": "chat.completion",
                "created": int(time.time()), "model": ans["model"], "usage": ans["usage"],
                "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}]}
        return resp, ans

    def _deliver_consult(self, body: dict, rec: dict, t0: float, stream: bool, resp: dict, ans: dict,
                         tier, reason: str) -> Response:
        """Claude 的回答一律標記為不可用於訓練（design D9）。 / Claude's answers are never usable for training."""
        rec["training_use"] = consult_mod.TRAINING_USE
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
        rec["training_use"] = consult_mod.TRAINING_USE
        if self.consultant is None:
            return self._finish_error(rec, 503, "consulting Claude is off (set JIEZI_CONSULT=claude-cli in .env)",
                                      "consult_off")
        if self.consult_cap and not self.consult_cap.available():
            return self._finish_error(rec, 503, "today's Claude consultations are used up", "consult_daily_cap")
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
                "confidence": rec.get("confidence")}

    def _deliver(self, resp: dict, meta: dict, rec: dict, stream: bool) -> Response:
        if rec.get("json_mode"):
            # JSON 模式：回答只留 JSON（去掉程式碼框與說明），不加附錄；來源仍在 jiezi.sources
            # JSON mode: the answer is bare JSON, no appendix; sources stay in jiezi.sources
            from .jsonout import normalize
            for ch in resp.get("choices") or []:
                msg = ch.get("message") or {}
                if not msg.get("tool_calls"):
                    normalize(msg)
        elif rec.get("dict_appendix"):
            for ch in resp.get("choices") or []:
                msg = ch.get("message") or {}
                msg["content"] = (msg.get("content") or "") + rec["dict_appendix"]
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
            help_reason = escalation.needs_help({"content": text}, finish)
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
        try:
            if route == "consult":
                resp, ans = await self._consult_once(body)
                rec["training_use"] = consult_mod.TRAINING_USE
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
        Route("/v1/documents", gw.documents, methods=["POST"]),
        Route("/v1/documents/warm", gw.documents_warm, methods=["POST"]),
        Route("/health", gw.health, methods=["GET"]),
        Route("/admin/unload", gw.admin_unload, methods=["POST"]),
        Route("/admin/trajectories", gw.admin_trajectories, methods=["GET"]),
        Route("/admin/doctor", gw.admin_doctor, methods=["GET"]),
        *ui_routes(gw.s.root),
    ], lifespan=lifespan, middleware=[_cors()])


def _cors():
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    return Middleware(CORSMiddleware, allow_origins=TAURI_ORIGINS, allow_methods=["GET", "POST"],
                      allow_headers=["Authorization", "Content-Type"], allow_credentials=False)


# 桌面 App 前端（Phase 8.4 雛形）：只提供本機建好的檔案，嚴格 CSP，不載入遠端內容（Phase 8.5）。
# Desktop front end (Phase 8.4 prototype): local build only, strict CSP, no remote content (Phase 8.5).
UI_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
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

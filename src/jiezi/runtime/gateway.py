"""OpenAI 相容的本機 gateway（規格 gateway、escalation、trajectory；add-gateway design D3、D5–D7）。
The local OpenAI-compatible gateway (specs gateway, escalation, trajectory; design D3, D5–D7).

端點 / Endpoints：
  POST /v1/chat/completions   三種策略：jiezi、jiezi-local、jiezi-cloud（含串流）/ three policies (streaming too)
  GET  /v1/models             列出策略 / lists the policies
  GET  /health                狀態（不含機密）/ state (no secrets)
  POST /admin/unload          卸載引擎，可暫停到指定時間（夜間評測用）/ unload, optionally hold (night evaluations)

串流的取捨（design D5）：請求帶 `tools` 時，先完整取得並驗證答案，再以串流格式送出；沒有 `tools` 時直接轉送本機
串流，驗證只事後記錄、不重試。
Streaming trade-off (design D5): with `tools`, the answer is fetched and verified first, then sent in stream
format; without `tools`, the local stream is relayed directly and verification is only recorded afterwards."""

from __future__ import annotations

import contextlib
import json
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

from ..textconv import to_traditional
from . import consult as consult_mod
from . import escalation
from .settings import POLICIES, Settings
from .supervisor import EngineUnavailable, Supervisor
from .trajectory import TrajectoryWriter, elapsed, new_id, now_iso

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
                 cap: escalation.DailyCap | None = None, consultant=None, log=print):
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
        self.knowledge, self.knowledge_note = None, None
        if settings.knowledge:
            from ..knowledge import Knowledge, db_path as knowledge_db
            try:
                self.knowledge = Knowledge(knowledge_db(settings.root))
            except Exception as exc:  # noqa: BLE001 - 沒建置就跳過 / skipped when not built
                self.knowledge_note = str(exc)
        self.writing, self.writing_note = None, None
        if settings.writing_refs:
            from ..writing_refs import WritingRefs, index_path
            try:
                self.writing = WritingRefs(index_path(settings.root))
            except Exception as exc:  # noqa: BLE001 - 沒建置就跳過 / skipped when not built
                self.writing_note = str(exc)
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
        out = {k: v for k, v in body.items() if k not in ("model", "stream", "stream_options")}
        out["model"] = self.sup.core["name"] if self.sup.core else self.s.core_model
        out["messages"] = messages if messages is not None else body["messages"]
        out["stream"] = stream
        out.setdefault("chat_template_kwargs", {"enable_thinking": False})  # 預設關閉思考 / thinking off by default
        return out

    async def _local_once(self, base: str, body: dict, messages: list | None = None) -> dict:
        r = await self.local.post(f"{base}/v1/chat/completions", json=self._local_body(body, messages))
        r.raise_for_status()
        data = r.json()
        for ch in data.get("choices") or []:  # 本機輸出的純簡體字轉繁體 / Simplified-only chars → Traditional
            msg = ch.get("message") or {}
            msg["content"] = to_traditional(msg.get("content"))
        return data

    async def _cloud_once(self, body: dict) -> tuple[dict, dict]:
        """依序嘗試轉交模型；回傳 (回應, 雲端資訊)。 / Try escalation models in order; return (response, info)."""
        headers = {"Authorization": f"Bearer {self.s.cloud_key}"} if self.s.cloud_key else {}
        payload = {k: v for k, v in body.items() if k not in ("model", "stream", "stream_options", "chat_template_kwargs")}
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

    def _ground(self, body: dict, rec: dict) -> None:
        """詞語問題查本機辭典、課綱問題查知識圖譜，把原文附給模型（add-dictionary D2、D3；add-curriculum D2、D3）。
        Attach verbatim dictionary entries for word questions and curriculum-graph data for curriculum questions."""
        if body.get("tools") or all(x is None for x in (self.dictionary, self.curriculum, self.knowledge,
                                                         self.writing)):
            return
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        if not last or not isinstance(last.get("content"), str):
            return
        found = []
        if self.dictionary is not None:
            from ..dictionary import grounding
            found.append(grounding(self.dictionary, last["content"]))
        if self.curriculum is not None:
            from ..curriculum import grounding as curriculum_grounding
            found.append(curriculum_grounding(self.curriculum, last["content"]))
        if self.knowledge is not None:
            from ..knowledge import grounding as knowledge_grounding
            found.append(knowledge_grounding(self.knowledge, last["content"]))
        idx = body["messages"].index(last)
        for g in found:
            if not g:
                continue
            content, sources, trainable, appendix = g
            body["messages"].insert(idx, {"role": "system", "content": content})
            idx += 1
            rec["sources"] = (rec.get("sources") or []) + sources
            rec["dict_appendix"] = (rec.get("dict_appendix") or "") + appendix
            if not trainable:
                rec["training_use"] = False  # 例如禁止改作的辭典 / e.g. a no-derivatives dictionary
        if self.writing is not None:
            w = self.writing.appendix(last["content"])
            if w:  # 只附連結，不給模型內文 / links only; no article text reaches the model
                rec["sources"] = (rec.get("sources") or []) + w[1]
                rec["dict_appendix"] = (rec.get("dict_appendix") or "") + w[0]

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
                             "cloud_escalation": self.s.cloud_ready, "cloud_used_today": self.cap.used(),
                             "cloud_daily_max": self.s.cloud_daily_max,
                             "trajectory": {"enabled": self.traj.enabled, "error": self.traj.last_error}})

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
        tid = new_id() if self.traj.enabled else None
        # training_use：None 表示訓練前要依授權表確認；請教 Claude 的回答一律 False（design D9）
        # training_use: None means check the license registry before training; Claude consultations are always False
        rec = {"id": tid, "at": now_iso(), "policy": policy, "stream": stream, "request": body, "tiers": [],
               "final_tier": None, "status": "ok", "training_use": None, "sources": []}
        self._ground(body, rec)
        t0 = time.monotonic()

        if policy == "jiezi-ask-claude":
            return await self._respond_consult(body, rec, t0, stream)

        if policy == "jiezi-cloud":
            reason = self._can_escalate()
            if reason:
                return self._finish_error(rec, 503, f"cloud is not available ({reason})", reason)
            return await self._respond_cloud(body, rec, t0, stream, reason="policy")

        try:
            base = await self.sup.acquire()
        except EngineUnavailable as exc:
            if policy == "jiezi" and self._auto_route():
                rec["engine"] = str(exc)
                return await self._escalate(body, rec, t0, stream, reason="engine_unavailable")
            return self._finish_error(rec, 503, f"local engine unavailable: {exc}", "engine_unavailable")

        if stream and not body.get("tools"):
            return StreamingResponse(self._relay_stream(base, body, rec, t0, policy), media_type="text/event-stream")
        try:
            return await self._tiered(base, body, rec, t0, policy, stream)
        finally:
            self.sup.release()

    # ── 分層 / Tiers ──
    async def _tiered(self, base: str, body: dict, rec: dict, t0: float, policy: str, stream: bool) -> Response:
        try:
            resp = await self._local_once(base, body)
        except httpx.HTTPError as exc:
            return self._finish_error(rec, 502, f"local engine error: {exc}", "engine_error")
        ver = escalation.verify(body, _message(resp))
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
                ver1 = escalation.verify(body, _message(resp1))
                rec["tiers"].append({"tier": 1, "answer": _message(resp1), "verification": ver1,
                                     "model": resp1.get("model"), "tps": _tps(resp1), "usage": resp1.get("usage")})
                final, tier, ver = resp1, 1, ver1
            except httpx.HTTPError as exc:
                rec["tiers"].append({"tier": 1, "error": str(exc)})
            if ver["status"] == "fail":
                if policy == "jiezi":
                    if self._auto_route():
                        return await self._escalate(body, rec, t0, stream, reason="verification_failed")
                    escalate_reason = self._no_route_reason()
                else:
                    escalate_reason = "local_only_policy"
        meta = self._meta(rec, tier, final, ver, t0, escalation=escalate_reason)
        return self._deliver(final, meta, rec, stream)

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
        meta = self._meta(rec, 3, resp, None, t0, escalation=reason, cloud=info)
        return self._deliver(resp, meta, rec, stream)

    async def _consult_once(self, body: dict) -> tuple[dict, dict]:
        last = next((m for m in reversed(body["messages"]) if m.get("role") == "user"), None)
        hint = self.writing.consult_hint(last["content"]) \
            if self.writing is not None and last and isinstance(last.get("content"), str) else None
        if hint:  # 寫作問題：提示 Claude 可上網參考（使用者 2026-11-15）/ writing questions: Claude may read the site
            body = {**body, "messages": [*body["messages"][:-1], {"role": "system", "content": hint},
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
        ver = escalation.verify(body, msg) if body.get("tools") else None
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
        return {"tier": tier, "policy": rec["policy"], "model": resp.get("model"),
                "verification": (ver or {}).get("status", "not_applicable" if tier != 3 else "cloud"),
                "verification_error": (ver or {}).get("error"), "escalation": escalation,
                "latency_s": elapsed(t0), "tps": _tps(resp),
                "cloud": {"tokens": usage.get("total_tokens"), "cost": (cloud or {}).get("cost")} if cloud else None,
                "trajectory_id": rec["id"], "sources": rec.get("sources") or []}

    def _deliver(self, resp: dict, meta: dict, rec: dict, stream: bool) -> Response:
        if rec.get("dict_appendix"):
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
                            delta["content"] = to_traditional(delta["content"])
                        content.append(delta.get("content") or "")
                        finish = ch.get("finish_reason") or finish
                    yield _sse(chunk)
            self.sup.release()
            released = True
            text = "".join(content)
            ver = escalation.verify(body, {"content": text})
            help_reason = escalation.needs_help({"content": text}, finish)
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
            except Exception as exc:  # noqa: BLE001 - 背景工作不可中斷 gateway / never kill the gateway
                self.log(f"warning: supervisor tick: {exc}")

    async def aclose(self) -> None:
        await self.local.aclose()
        await self.cloud.aclose()


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
                await gw.aclose()

    return Starlette(routes=[
        Route("/v1/chat/completions", gw.chat, methods=["POST"]),
        Route("/v1/models", gw.models, methods=["GET"]),
        Route("/health", gw.health, methods=["GET"]),
        Route("/admin/unload", gw.admin_unload, methods=["POST"]),
    ], lifespan=lifespan)

"""OpenAI 相容 chat 客戶端（本機 llama-server 與雲端共用；design D5、D11）。
OpenAI-compatible chat client shared by local llama-server and cloud endpoints (design D5, D11).

- 基準模式：帶 disable_fallbacks，並核對回應的 model（規則 R17.1）。
  Baseline mode: sends disable_fallbacks and checks the response's model (rule R17.1).
- 卡住與失敗：每個請求有逾時；逾時、連線錯誤、429、5xx 最多重試 2 次（使用者：免費模型有時會卡住）。
  Hangs and failures: every request times out; timeouts, connection errors, 429 and 5xx are retried
  at most twice (user: free models sometimes hang)."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

RETRY_DELAYS_S = (10, 30)
RETRY_AFTER_CAP_S = 120


@dataclass
class Reply:
    status: str  # ok | void_model_mismatch | error_timeout | error_http
    content: str = ""
    model: str | None = None
    usage: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    latency_s: float = 0.0
    attempts: int = 0
    error: str | None = None


class ModelGuard:
    """基準模式的實際模型核對：有 match 字串就要求包含它；沒有就鎖定第一個成功回應的模型。
    Baseline actual-model check: require the match substring when given, else lock onto the first
    successful response's model."""

    def __init__(self, match: str | None):
        self.match = (match or "").lower() or None
        self.locked: str | None = None

    def accept(self, model: str | None) -> bool:
        m = (model or "").lower()
        if not m:
            return False
        if self.match:
            return self.match in m
        if self.locked is None:
            self.locked = m
        return m == self.locked


class ChatClient:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout_s: float = 120,
                 baseline: bool = False, model_match: str | None = None,
                 sleep: Callable[[float], None] = time.sleep, opener=urllib.request.urlopen):
        self.url = base_url.rstrip("/") + ("/chat/completions" if base_url.rstrip("/").endswith("/v1")
                                           else "/v1/chat/completions")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.baseline = baseline
        self.guard = ModelGuard(model_match) if baseline else None
        self.sleep = sleep
        self.opener = opener

    def _post(self, body: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        with self.opener(req, timeout=self.timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))

    def complete(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 512,
                 extra: dict | None = None) -> Reply:
        body = {"model": self.model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                **(extra or {})}
        if self.baseline:
            body["disable_fallbacks"] = True
        last_status, last_error = "error_http", None
        t0 = time.monotonic()
        for attempt in range(len(RETRY_DELAYS_S) + 1):
            if attempt:
                delay = RETRY_DELAYS_S[attempt - 1]
                if last_status == "retry_after":
                    delay = min(self._retry_after, RETRY_AFTER_CAP_S)
                self.sleep(delay)
            try:
                data = self._post(body)
            except urllib.error.HTTPError as exc:
                last_error = f"HTTP {exc.code}: {exc.read()[:300].decode('utf-8', 'replace')}"
                if exc.code == 429 or exc.code >= 500:
                    ra = exc.headers.get("Retry-After") if exc.headers else None
                    if exc.code == 429 and ra and ra.strip().isdigit():
                        self._retry_after, last_status = float(ra), "retry_after"
                    else:
                        last_status = "error_http"
                    continue
                return Reply("error_http", error=last_error, attempts=attempt + 1,
                             latency_s=round(time.monotonic() - t0, 3))
            except (TimeoutError, socket.timeout) as exc:
                last_status, last_error = "error_timeout", f"timeout after {self.timeout_s} s ({exc})"
                continue
            except urllib.error.URLError as exc:
                timed_out = isinstance(exc.reason, (TimeoutError, socket.timeout))
                last_status = "error_timeout" if timed_out else "error_http"
                last_error = f"{'timeout' if timed_out else 'connection error'}: {exc.reason}"
                continue
            except (json.JSONDecodeError, ConnectionError, OSError) as exc:
                last_status, last_error = "error_http", f"{type(exc).__name__}: {exc}"
                continue
            return self._reply(data, attempt + 1, time.monotonic() - t0)
        status = "error_timeout" if last_status == "error_timeout" else "error_http"
        return Reply(status, error=last_error, attempts=len(RETRY_DELAYS_S) + 1,
                     latency_s=round(time.monotonic() - t0, 3))

    def _reply(self, data: dict, attempts: int, latency: float) -> Reply:
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        reply = Reply("ok", content=msg.get("content") or "", model=data.get("model"),
                      usage=data.get("usage") or {}, timings=data.get("timings") or {},
                      latency_s=round(latency, 3), attempts=attempts)
        if self.guard and not self.guard.accept(reply.model):
            reply.status = "void_model_mismatch"
            reply.error = f"response model {reply.model!r} does not match the baseline"
        return reply

"""gateway 的 HTTP 客戶端與串流解析，ask 與 chat 共用（add-cli design D1、D2）。
The gateway HTTP client and stream parsing, shared by ask and chat (add-cli design D1, D2)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from ..config import GATEWAY_KEY_VAR, load_env, port_base, project_root

POLICY_FLAGS = {"local": "jiezi-local", "cloud": "jiezi-cloud", "claude": "jiezi-ask-claude"}


class GatewayUnreachable(Exception):
    """gateway 沒有啟動或連不到（結束碼 2）。 / Gateway not running or unreachable (exit 2)."""


class GatewayError(Exception):
    """gateway 回錯誤（結束碼 3）。 / The gateway answered with an error (exit 3)."""


@dataclass
class Connection:
    url: str
    key: str

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Connection":
        env = load_env(project_root()) if env is None else env
        url = (env.get("JIEZI_GATEWAY_URL") or f"http://127.0.0.1:{port_base(env)}").rstrip("/")
        return cls(url=url, key=(env.get(GATEWAY_KEY_VAR) or "").strip())

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"}


def _error_message(r: httpx.Response) -> str:
    try:
        e = r.json().get("error") or {}
        return f"{e.get('message') or r.text} ({e.get('code') or r.status_code})"
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"


async def stream_chat(conn: Connection, messages: list[dict], policy: str = "jiezi",
                      client: httpx.AsyncClient | None = None, timeout: float = 900,
                      extra: dict | None = None) -> AsyncIterator[tuple[str, object]]:
    """產生 ("delta", 文字)、("meta", jiezi 欄位)。 / Yield ("delta", text) and ("meta", jiezi field)."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0))
    try:
        async with client.stream("POST", f"{conn.url}/v1/chat/completions", headers=conn.headers,
                                 json={**(extra or {}), "model": policy, "messages": messages, "stream": True}) as r:
            if r.status_code != 200:
                await r.aread()
                raise GatewayError(_error_message(r))
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if chunk.get("error"):
                    raise GatewayError(str(chunk["error"].get("message")))
                if chunk.get("jiezi"):
                    yield "meta", chunk["jiezi"]
                for ch in chunk.get("choices") or []:
                    text = (ch.get("delta") or {}).get("content")
                    if text:
                        yield "delta", text
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise GatewayUnreachable(f"gateway not reachable at {conn.url}") from exc
    finally:
        if own:
            await client.aclose()


async def warm_document(conn: Connection, text: str, client: httpx.AsyncClient | None = None) -> bool:
    """附檔後請 gateway 先建段落向量（add-semantic-chunks）；失敗不影響任何事。
    Ask the gateway to start building chunk vectors for an attached document; failures are ignored."""
    from ..documents import clean_for_attach
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0))
    try:
        r = await client.post(f"{conn.url}/v1/documents/warm", headers=conn.headers,
                              content=clean_for_attach(text).encode("utf-8"))
        return r.status_code == 202 and bool(r.json().get("warming"))
    except Exception:  # noqa: BLE001 - 只是預先準備 / best effort only
        return False
    finally:
        if own:
            await client.aclose()


async def complete(conn: Connection, messages: list[dict], policy: str = "jiezi", timeout: float = 900,
                   client: httpx.AsyncClient | None = None, extra: dict | None = None) -> dict:
    """非串流，回傳完整 JSON（含 jiezi 欄位）。 / Non-streaming; return the full JSON (with the jiezi field)."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5.0))
    try:
        r = await client.post(f"{conn.url}/v1/chat/completions", headers=conn.headers,
                              json={**(extra or {}), "model": policy, "messages": messages})
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise GatewayUnreachable(f"gateway not reachable at {conn.url}") from exc
    finally:
        if own:
            await client.aclose()
    if r.status_code != 200:
        raise GatewayError(_error_message(r))
    return r.json()


def status_line(meta: dict | None) -> str:
    """每則回答的狀態行（只用 ASCII 與常用中文，不用 emoji）。 / Per-answer status line (ASCII and CJK, no emoji)."""
    if not meta:
        return ""
    tier = meta.get("tier")
    who = {"consult": "Claude", 3: "Claude" if meta.get("provider") == "claude" else "cloud",
           "memory": "記憶 memory"}.get(tier, "local")
    if tier == 2:  # 第 2 層：本機作答，協助者只給回饋 / local answer, helper feedback only
        who = f"local + {meta.get('feedback_from') or 'helper'} 回饋 feedback"
    parts = [f"tier {tier} ({who})", str(meta.get("model") or "?")]
    if meta.get("tps"):
        parts.append(f"{meta['tps']} t/s")
    if meta.get("latency_s") is not None:
        parts.append(f"{meta['latency_s']} s")
    cloud = meta.get("cloud") or {}
    if cloud.get("cost") is not None:
        parts.append(f"~US${cloud['cost']:.4f}")
    if meta.get("confidence") is not None:
        parts.append(f"信心 conf {meta['confidence']:.2f}")
    if meta.get("verification") not in (None, "not_applicable"):
        parts.append(f"verify {meta['verification']}")
    if meta.get("escalation") and meta.get("escalation") != "policy":
        parts.append(f"why {meta['escalation']}")
    line = "[" + " | ".join(parts) + "]"
    inj = meta.get("injection") or {}
    if inj.get("suspected"):  # 疑似提示注入：另起一行提醒 / suspected prompt injection: a warning on its own line
        line += ("\n[注意 warning: " + (inj.get("warning") or "資料中有疑似提示注入的內容") +
                 " / possible prompt injection in the attached data (" + ", ".join(inj["suspected"]) + ")]")
    return line


def ensure_gateway(conn: Connection, log=lambda *_: None) -> str | None:
    """本機 gateway 沒開時在背景啟動（使用者 2026-11-15）；只處理 127.0.0.1 的網址。
    回傳啟動結果，或 None 表示不需要 / 不適用。
    Start a local gateway in the background when it is not running (user request, 2026-11-15); only for
    127.0.0.1 URLs. Return the start result, or None when not needed / not applicable."""
    from urllib.parse import urlparse

    from ..runtime import service
    u = urlparse(conn.url)
    if u.hostname != "127.0.0.1" or not u.port:
        return None
    if service.health(u.port):
        return None
    log("gateway 未啟動，正在背景啟動… / starting the gateway in the background…")
    return service.start(project_root(), u.port)

from __future__ import annotations

import json
import selectors
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from jiezi.scrapling_policy import (
    DenialReason,
    PolicyConfig,
    PolicyError,
    ToolStatus,
    classify_tool,
    clamp_timeout,
    enforce_byte_cap,
    filter_tools,
    validate_resolved_host,
    validate_url,
)


class Backend:
    WEB_FETCH = "web-fetch"
    SCRAPLING = "scrapling"


class BackendUnavailable(RuntimeError):
    pass


@runtime_checkable
class McpTransport(Protocol):
    def list_tools(self) -> Iterable[str]: ...

    def call_tool(self, name: str, arguments: dict[str, object]) -> bytes: ...

    def close(self) -> None: ...


@runtime_checkable
class WebFetcher(Protocol):
    def fetch(self, url: str, timeout_seconds: float, max_bytes: int) -> bytes: ...


@runtime_checkable
class SecurityGate(Protocol):
    def allows(self, backend: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class StaticSecurityGate:
    web_fetch: bool = False
    scrapling: bool = False

    def allows(self, backend: str) -> bool:
        if backend == Backend.WEB_FETCH:
            return self.web_fetch
        if backend == Backend.SCRAPLING:
            return self.scrapling
        return False


@dataclass(frozen=True, slots=True)
class AuditEvent:
    tool: str
    host: str
    decision: str
    status: str
    byte_count: int
    timestamp: str
    backend: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolHandle:
    name: str
    handler: Callable[[str], str]


def select_backend(
    tool: str,
    config: PolicyConfig,
    gate: SecurityGate,
    web_fetcher: WebFetcher | None,
) -> str:
    if not config.enabled:
        raise PolicyError(DenialReason.DISABLED)
    if tool == "browser_fetch_once":
        if not gate.allows(Backend.SCRAPLING):
            raise BackendUnavailable("scrapling backend is not security-cleared")
        return Backend.SCRAPLING
    if web_fetcher is not None and gate.allows(Backend.WEB_FETCH):
        return Backend.WEB_FETCH
    if gate.allows(Backend.SCRAPLING):
        return Backend.SCRAPLING
    raise BackendUnavailable("no security-cleared backend available")


class HttpxWebFetcher:
    def fetch(self, url: str, timeout_seconds: float, max_bytes: int) -> bytes:
        import httpx

        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        remaining = max_bytes - total
                        if remaining <= 0:
                            break
                        take = chunk[:remaining]
                        chunks.append(take)
                        total += len(take)
                    return b"".join(chunks)
        except Exception as exc:
            raise BackendUnavailable(str(exc)) from exc


class StdioMcpTransport:
    def __init__(
        self,
        timeout_seconds: float = 15.0,
        command: tuple[str, ...] = ("scrapling-mcp",),
        max_bytes: int = 1_000_000,
    ) -> None:
        self._timeout = timeout_seconds
        self._command = command
        self._max_bytes = max_bytes
        self._process: subprocess.Popen[str] | None = None
        self._initialized = False
        self._next_id = 1
        self._bytes_read = 0  # 累積讀取位元組數 / cumulative bytes read

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        executable = shutil.which(self._command[0])
        if executable is None:
            raise BackendUnavailable(f"MCP executable not found: {self._command[0]}")
        self._process = subprocess.Popen(
            [executable, *self._command[1:]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._initialized = False
        self._bytes_read = 0

    def _read_line(self, deadline: float) -> str:
        """讀一行，受整體期限與單一請求的位元組上限約束；readline 最多讀到剩餘額度 +1，
        超大回應不會整行先進記憶體。/ Read one line within the request deadline and byte budget;
        readline is bounded by the remaining budget so an oversized reply is never buffered whole."""
        if self._process is None or self._process.stdout is None:
            raise BackendUnavailable("MCP process is not running")
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            raise TimeoutError("MCP stdio response timed out")
        selector = selectors.DefaultSelector()
        selector.register(self._process.stdout, selectors.EVENT_READ)
        try:
            ready = selector.select(remaining_time)
            if not ready:
                raise TimeoutError("MCP stdio response timed out")
            budget = max(self._max_bytes - self._bytes_read, 0)
            line = self._process.stdout.readline(budget + 1)
        finally:
            selector.close()
        if not line:
            raise BackendUnavailable("MCP server closed stdout")
        self._bytes_read += len(line.encode("utf-8"))
        if self._bytes_read > self._max_bytes:
            raise BackendUnavailable(f"MCP response exceeds max_bytes ({self._bytes_read} > {self._max_bytes})")
        return line

    def _write(self, message: dict[str, object]) -> None:
        if self._process is None or self._process.stdin is None:
            raise BackendUnavailable("MCP process is not running")
        self._process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._process.stdin.flush()

    def _read_response(self, expected_id: int) -> dict[str, object]:
        """讀取並解析回應，略過 notification、非 JSON 行、id mismatch，直到拿到預期 id 或逾時。
        Read and parse response, skipping notifications, non-JSON lines, and id mismatches until expected id or timeout."""
        deadline = time.monotonic() + self._timeout  # 整體期限，略過的行也算 / one deadline for the whole reply
        while True:
            line = self._read_line(deadline)
            stripped = line.strip()
            if not stripped:
                continue  # 略過空行 / skip empty lines
            try:
                response = json.loads(stripped)
            except json.JSONDecodeError:
                # 非 JSON 行（如 log）、略過 / non-JSON line (e.g., log), skip
                continue

            # 若無 id，視為 notification，略過 / no id -> notification, skip
            if "id" not in response:
                continue

            # id 不符，略過 / id mismatch, skip
            if response.get("id") != expected_id:
                continue

            # 找到預期的 response
            if "error" in response:
                raise RuntimeError(str(response["error"]))
            result = response.get("result")
            return result if isinstance(result, dict) else {}

    def _request_raw(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self._start()
        message_id = self._next_id
        self._next_id += 1
        self._bytes_read = 0  # 上限是每個請求，不是整個行程生命週期 / the cap is per request, not per process lifetime
        self._write({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params})
        return self._read_response(message_id)

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._request_raw(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "jiezi", "version": "0.1.0"},
            },
        )
        self._write({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        self._initialized = True

    def _request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        self._ensure_initialized()
        return self._request_raw(method, params)

    def list_tools(self) -> tuple[str, ...]:
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        return tuple(tool["name"] for tool in tools if isinstance(tool, dict) and isinstance(tool.get("name"), str))

    def call_tool(self, name: str, arguments: dict[str, object]) -> bytes:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        parts: list[str] = []
        for block in result.get("content", []):
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if result.get("isError"):
            raise RuntimeError("MCP tool returned an error")
        return "".join(parts).encode("utf-8")

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self._timeout)
        self._process = None
        self._initialized = False


class ScraplingMcpAdapter:
    def __init__(
        self,
        config: PolicyConfig,
        *,
        gate: SecurityGate,
        injection_guard: Callable[[str], str],
        audit_sink: Callable[[AuditEvent], None],
        web_fetcher: WebFetcher | None = None,
        transport: McpTransport | None = None,
        transport_factory: Callable[[], McpTransport] | None = None,
        resolve: Callable | None = None,
    ) -> None:
        self.config = config
        self._resolve = resolve
        self.gate = gate
        self.injection_guard = injection_guard
        self.audit_sink = audit_sink
        self.web_fetcher = web_fetcher
        self._transport = transport
        self._transport_factory = transport_factory or (
            # 原始 stdio 上限＝內容上限×2＋64 KiB：留給 JSON-RPC 外框與跳脫字元；內容仍由 enforce_byte_cap 截到 max_bytes
            # raw stdio cap = 2× content cap + 64 KiB for the JSON-RPC envelope and escaping; content is still capped later
            lambda: StdioMcpTransport(timeout_seconds=config.timeout_seconds,
                                      max_bytes=config.max_bytes * 2 + 65_536)
        )

    def _get_transport(self) -> McpTransport:
        if self._transport is None:
            self._transport = self._transport_factory()
        return self._transport

    def _audit(
        self,
        tool: str,
        host: str,
        decision: str,
        status: str,
        byte_count: int,
        backend: str = "",
    ) -> None:
        self.audit_sink(
            AuditEvent(
                tool=tool,
                host=host,
                decision=decision,
                status=status,
                byte_count=byte_count,
                timestamp=datetime.now(UTC).isoformat(),
                backend=backend,
            )
        )

    def register(self, advertised: Iterable[str] | None = None) -> tuple[ToolHandle, ...]:
        if not self.config.enabled:
            return ()
        names = tuple(self.config.approved_tools) if advertised is None else tuple(advertised)
        result = filter_tools(names, self.config)
        handles: list[ToolHandle] = []
        for name in result.approved:
            if name == "browser_fetch_once" and not self.gate.allows(Backend.SCRAPLING):
                self._audit(name, "", "filtered", "ignored", 0)
                continue
            if name == "make_request" and not (
                self.gate.allows(Backend.WEB_FETCH) or self.gate.allows(Backend.SCRAPLING)
            ):
                self._audit(name, "", "filtered", "ignored", 0)
                continue
            handles.append(ToolHandle(name, partial(self.fetch, name)))
        for name, status in result.filtered:
            self._audit(name, "", "filtered", status.value, 0)
        return tuple(handles)

    def fetch(
        self,
        tool: str,
        url: str,
        *,
        requested_timeout: float | None = None,
    ) -> str:
        host = ""
        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            host = ""
        decision = "allow"
        status = "ok"
        byte_count = 0
        backend_name = ""
        try:
            validate_url(url, self.config)
            validate_resolved_host(host, self._resolve or socket.getaddrinfo)
            if classify_tool(tool, self.config) is not ToolStatus.APPROVED:
                raise PolicyError(DenialReason.TOOL_NOT_ALLOWED, tool)
            timeout = clamp_timeout(
                self.config.timeout_seconds if requested_timeout is None else requested_timeout,
                self.config,
            )
            backend = select_backend(tool, self.config, self.gate, self.web_fetcher)
            backend_name = backend
            if backend == Backend.WEB_FETCH:
                if self.web_fetcher is None:
                    raise BackendUnavailable("web-fetch backend is not available")
                try:
                    raw = self.web_fetcher.fetch(url, timeout, self.config.max_bytes)
                except BackendUnavailable:
                    if not self.gate.allows(Backend.SCRAPLING):
                        raise
                    backend = Backend.SCRAPLING
                    backend_name = backend
                    raw = self._get_transport().call_tool(tool, {"url": url})
            else:
                raw = self._get_transport().call_tool(tool, {"url": url})
            capped = enforce_byte_cap(raw, self.config)
            text = self.injection_guard(capped.data.decode("utf-8", errors="replace"))
            byte_count = capped.byte_count
            status = "truncated" if capped.truncated else "ok"
            return text
        except PolicyError as exc:
            decision = exc.reason.value
            status = "blocked"
            raise
        except Exception:
            status = "error"
            raise
        finally:
            self._audit(tool, host, decision, status, byte_count, backend_name)

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()

    def __enter__(self) -> ScraplingMcpAdapter:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


def build_adapter(
    config: PolicyConfig,
    root: Path,
    *,
    web_fetcher: WebFetcher | None = None,
    transport_factory: Callable[[], McpTransport] | None = None,
) -> ScraplingMcpAdapter:
    """把政策、注入清理與稽核接成單一轉接器工廠；不啟動任何 MCP process。
    Wire policy, injection cleaning and audit into one adapter factory; no MCP process is started here."""
    from .agent.audit import write as audit_write
    from .injection import clean

    def audit(event: AuditEvent) -> None:
        audit_write(root, event.as_dict())

    def guard(text: str) -> str:
        return clean(text)[0]

    return ScraplingMcpAdapter(
        config,
        gate=StaticSecurityGate(web_fetch=True, scrapling=True),
        injection_guard=guard,
        audit_sink=audit,
        web_fetcher=web_fetcher,
        transport_factory=transport_factory,
    )

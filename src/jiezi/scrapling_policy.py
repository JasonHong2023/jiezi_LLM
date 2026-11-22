from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit

_SUPPORTED_TOOLS = frozenset({"make_request", "browser_fetch_once"})
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".example", ".invalid")
_EVASION_MARKERS = (
    "login",
    "captcha",
    "paywall",
    "proxy",
    "rotat",
    "state",
    "session",
    "bulk",
    "screenshot",
    "evaluate",
    "network",
    "actions",
    "observe",
    "extract",
)


class DenialReason(StrEnum):
    DISABLED = "disabled"
    UNSAFE_SCHEME = "unsafe_scheme"
    CREDENTIALS = "credentials"
    MISSING_HOST = "missing_host"
    INVALID_URL = "invalid_url"
    PRIVATE_ADDRESS = "private_address"
    LOCAL_NAME = "local_name"
    HOST_NOT_ALLOWED = "host_not_allowed"
    TOOL_NOT_ALLOWED = "tool_not_allowed"
    DNS_FAILED = "dns_failed"
    INVALID_CONFIG = "invalid_config"


class ToolStatus(StrEnum):
    APPROVED = "approved"
    EVASION = "evasion"
    UNLISTED = "unlisted"


class PolicyError(ValueError):
    def __init__(self, reason: DenialReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        message = f"{reason.value}: {detail}" if detail else reason.value
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    enabled: bool = False
    allowed_hosts: frozenset[str] = frozenset()
    timeout_seconds: float = 15.0
    max_bytes: int = 1_000_000
    allow_js_stealth: bool = False
    approved_tools: frozenset[str] = frozenset({"make_request"})

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> PolicyConfig:
        source = os.environ if env is None else env
        hosts = frozenset(
            normalize_host(item)
            for item in source.get("JIEZI_SCRAPLING_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        )
        enabled = parse_bool(source.get("JIEZI_SCRAPLING_MCP", "false"))
        allow_js_stealth = parse_bool(source.get("JIEZI_SCRAPLING_ALLOW_JS_STEALTH", "false"))
        approved = {"make_request"}
        if allow_js_stealth:
            approved.add("browser_fetch_once")
        timeout_seconds = float((source.get("JIEZI_SCRAPLING_TIMEOUT_SECONDS") or "").strip() or "15")
        max_bytes = int((source.get("JIEZI_SCRAPLING_MAX_BYTES") or "").strip() or "1000000")
        # 載入時就拒絕非正數（原本只在使用點攔截）/ reject non-positive limits at load time, not only at use
        if not timeout_seconds > 0:
            raise PolicyError(DenialReason.INVALID_CONFIG, "JIEZI_SCRAPLING_TIMEOUT_SECONDS must be > 0")
        if max_bytes <= 0:
            raise PolicyError(DenialReason.INVALID_CONFIG, "JIEZI_SCRAPLING_MAX_BYTES must be > 0")
        return cls(
            enabled=enabled,
            allowed_hosts=hosts,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            allow_js_stealth=allow_js_stealth,
            approved_tools=frozenset(approved),
        )


@dataclass(frozen=True, slots=True)
class ToolFilterResult:
    approved: tuple[str, ...]
    filtered: tuple[tuple[str, ToolStatus], ...]


@dataclass(frozen=True, slots=True)
class CappedContent:
    data: bytes
    truncated: bool
    byte_count: int


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_host(value: str) -> str:
    return value.strip().lower().rstrip(".")


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def is_public_host(host: str) -> bool:
    normalized = normalize_host(host)
    if not normalized:
        return False
    if is_ip_literal(normalized):
        return ipaddress.ip_address(normalized).is_global
    if normalized == "localhost" or normalized.endswith(_LOCAL_SUFFIXES):
        return False
    return True


def is_allowed_host(host: str, allowed_hosts: frozenset[str]) -> bool:
    normalized = normalize_host(host)
    for entry in allowed_hosts:
        base = normalize_host(entry)
        if not base:
            continue
        if base.startswith("."):
            if normalized.endswith(base):
                return True
        elif normalized == base:
            return True
    return False


def validate_url(url: str, config: PolicyConfig) -> str:
    if not config.enabled:
        raise PolicyError(DenialReason.DISABLED)
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise PolicyError(DenialReason.INVALID_URL, str(exc)) from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise PolicyError(DenialReason.UNSAFE_SCHEME, parsed.scheme)
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise PolicyError(DenialReason.CREDENTIALS)
    host = normalize_host(parsed.hostname or "")
    if not host:
        raise PolicyError(DenialReason.MISSING_HOST)
    if not is_public_host(host):
        reason = DenialReason.PRIVATE_ADDRESS if is_ip_literal(host) else DenialReason.LOCAL_NAME
        raise PolicyError(reason, host)
    if not is_allowed_host(host, config.allowed_hosts):
        raise PolicyError(DenialReason.HOST_NOT_ALLOWED, host)
    return url


def _non_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    return (not ip.is_global or ip.is_multicast or ip.is_unspecified
            or (mapped is not None and not mapped.is_global))


def validate_resolved_host(host: str, resolve: Callable | None = None) -> None:
    """解析主機名後，任何一個位址不是公用網路就拒絕（與 webread._blocked 同一標準）。
    Reject a host when any resolved address is not public (same bar as webread._blocked)."""
    normalized = normalize_host(host)
    if is_ip_literal(normalized):
        addrs = [ipaddress.ip_address(normalized)]
    else:
        try:
            infos = (resolve or socket.getaddrinfo)(normalized, None, type=socket.SOCK_STREAM)
            addrs = [ipaddress.ip_address(str(i[4][0]).split("%")[0]) for i in infos]
        except (OSError, ValueError) as exc:
            raise PolicyError(DenialReason.DNS_FAILED, normalized) from exc
    if not addrs:
        raise PolicyError(DenialReason.DNS_FAILED, normalized)
    for ip in addrs:
        if _non_public(ip):
            raise PolicyError(DenialReason.PRIVATE_ADDRESS, f"{normalized} -> {ip}")


def classify_tool(name: str, config: PolicyConfig) -> ToolStatus:
    normalized = name.strip().lower()
    if any(marker in normalized for marker in _EVASION_MARKERS):
        return ToolStatus.EVASION
    if normalized not in _SUPPORTED_TOOLS:
        return ToolStatus.UNLISTED
    if normalized in config.approved_tools:
        return ToolStatus.APPROVED
    return ToolStatus.UNLISTED


def filter_tools(advertised: Iterable[str], config: PolicyConfig) -> ToolFilterResult:
    approved: list[str] = []
    filtered: list[tuple[str, ToolStatus]] = []
    for name in advertised:
        status = classify_tool(name, config)
        if status is ToolStatus.APPROVED:
            approved.append(name)
        else:
            filtered.append((name, status))
    return ToolFilterResult(tuple(approved), tuple(filtered))


def clamp_timeout(requested: float, config: PolicyConfig) -> float:
    if requested <= 0:
        raise ValueError("timeout must be positive")
    return min(requested, config.timeout_seconds)


def enforce_byte_cap(data: bytes, config: PolicyConfig) -> CappedContent:
    if config.max_bytes < 0:
        raise ValueError("max_bytes must not be negative")
    if len(data) <= config.max_bytes:
        return CappedContent(data, False, len(data))
    return CappedContent(data[: config.max_bytes], True, config.max_bytes)

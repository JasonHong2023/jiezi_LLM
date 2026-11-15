"""runtime 設定：全部來自 `.env` 或環境變數（R21.3），在啟動時檢查（add-gateway design D3、D4、D6、D7）。
Runtime settings, all from `.env` or the environment (R21.3), validated at startup."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import GATEWAY_KEY_VAR, load_env, port_base, project_root
from ..errors import JieziError

LOCAL_HOST = "127.0.0.1"
POLICIES = ("jiezi", "jiezi-local", "jiezi-cloud")
DEFAULT_CORE = "qwen3-0.6b-q8_0"


def _int(env: dict, key: str, default: int) -> int:
    v = env.get(key)
    try:
        return int(v) if v else default
    except ValueError as exc:
        raise JieziError(f"{key} must be an integer, got {v!r}") from exc


def _onoff(env: dict, key: str, default: bool) -> bool:
    v = (env.get(key) or "").strip().lower()
    if not v:
        return default
    if v in ("on", "true", "1", "yes"):
        return True
    if v in ("off", "false", "0", "no"):
        return False
    raise JieziError(f"{key} must be on or off, got {v!r}")


@dataclass
class Settings:
    root: Path
    key: str
    gateway_port: int
    engine_port: int
    core_model: str = DEFAULT_CORE
    models_dir: Path | None = None
    idle_unload_s: int = 900
    cloud_escalation: bool = False
    cloud_base: str | None = None
    cloud_key: str | None = None
    escalation_models: list[str] = field(default_factory=list)
    cloud_daily_max: int = 200
    trajectory: bool = True
    retention_days: int = 0
    request_max_bytes: int = 1 << 20
    request_timeout_s: float = 600.0
    host: str = LOCAL_HOST

    @property
    def cloud_ready(self) -> bool:
        return self.cloud_escalation and bool(self.cloud_base) and bool(self.escalation_models)

    @property
    def var(self) -> Path:
        return self.root / "var"


def load_settings(root: Path | None = None, env: dict | None = None) -> Settings:
    """讀設定並檢查：只允許 127.0.0.1，必須有金鑰。 / Read and validate: 127.0.0.1 only, a key is required."""
    root = root or project_root()
    env = load_env(root) if env is None else env
    host = (env.get("JIEZI_GATEWAY_HOST") or LOCAL_HOST).strip()
    if host != LOCAL_HOST:
        raise JieziError(f"JIEZI_GATEWAY_HOST={host!r}: the gateway binds only to {LOCAL_HOST} (R6.12)")
    key = (env.get(GATEWAY_KEY_VAR) or "").strip()
    if len(key) < 16:
        raise JieziError(f"{GATEWAY_KEY_VAR} is missing or too short; run scripts/bootstrap or "
                         "`scripts/jiezi init-key` to generate one")
    base = port_base(env)
    md = env.get("JIEZI_MODELS_DIR")
    return Settings(
        root=root, key=key, gateway_port=base, engine_port=base + 1,
        core_model=(env.get("JIEZI_CORE_MODEL") or DEFAULT_CORE).strip(),
        models_dir=Path(md).expanduser() if md else root / "models",
        idle_unload_s=_int(env, "JIEZI_IDLE_UNLOAD_S", 900),
        cloud_escalation=_onoff(env, "JIEZI_CLOUD_ESCALATION", False),
        cloud_base=(env.get("JIEZI_CLOUD_BASE_URL") or "").rstrip("/") or None,
        cloud_key=env.get("JIEZI_CLOUD_API_KEY") or None,
        escalation_models=[m.strip() for m in (env.get("JIEZI_ESCALATION_MODELS") or "").split(",") if m.strip()],
        cloud_daily_max=_int(env, "JIEZI_CLOUD_DAILY_MAX", 200),
        trajectory=_onoff(env, "JIEZI_TRAJECTORY", True),
        retention_days=_int(env, "JIEZI_TRAJECTORY_RETENTION_DAYS", 0),
    )

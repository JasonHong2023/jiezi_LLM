"""專案根目錄與本機設定（`.env`）；bootstrap 與產品程式共用（規則 R21.3）。
Project root and local configuration (`.env`), shared by bootstrap and product code (rule R21.3)."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """專案根目錄：由本檔位置推得（src/jiezi/config.py → 根目錄），可由 JIEZI_HOME 覆寫。
    Project root: derived from this file (src/jiezi/config.py → root), overridable by JIEZI_HOME."""
    env = os.environ.get("JIEZI_HOME", "").strip()
    return Path(env).expanduser().resolve() if env else Path(__file__).resolve().parents[2]


def load_env(root: Path | None = None, environ: dict | None = None) -> dict:
    """讀取 <root>/.env（簡單的 KEY=VALUE），程序環境變數優先；空值視為未設定。
    Read <root>/.env (plain KEY=VALUE); process environment wins; empty values count as unset."""
    root = root or project_root()
    environ = os.environ if environ is None else environ
    values: dict[str, str] = {}
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v:
                values[k.strip()] = v
    for k, v in environ.items():
        if k.startswith("JIEZI_") and v.strip():
            values[k] = v.strip()
    return values


def port_base(env: dict | None = None) -> int:
    """本機服務 port 區段起點（預設 36100，規則 R11）。 / Start of the local port block (default 36100, rule R11)."""
    env = load_env() if env is None else env
    try:
        return int(env.get("JIEZI_PORT_BASE") or 36100)
    except ValueError:
        return 36100

"""授權（R22.2 最小權限）：只有使用者以 `scripts/jiezi agent grant` 加入的資料夾可以讀；預設空的。
Grants (least privilege): only folders the user added with `scripts/jiezi agent grant` are readable; empty by default.

每次呼叫都先把路徑解析成跟隨符號連結後的實際路徑再比對；機密位置寫死在程式裡，授權也打不開。
Every call resolves the path through symlinks before matching; secret locations are hard-coded and never grantable.
授權檔只由命令列寫入；工具伺服器沒有任何寫入功能（R22.5）。/ Only the CLI writes the grants file."""

from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
from pathlib import Path

# 一律拒絕：路徑中任何一層符合就拒絕 / Always refused: any path component matching refuses the path
DENY_NAMES = (".env", ".env.*", "*.key", "*.pem", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "id_ecdsa*", "*.kdbx",
              ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".password-store", ".netrc", ".git-credentials",
              ".pgpass", "credentials*", "secrets*", "facts.json")
# 一律拒絕的資料夾（相對家目錄）：瀏覽器設定檔、各工具的金鑰與設定 / browser profiles and tool secrets
DENY_HOME = (".mozilla", ".config/google-chrome", ".config/chromium", ".config/BraveSoftware", ".config/microsoft-edge",
             ".hermes", ".claude", ".config/opencode", ".local/share/keyrings", ".config/gh")
WINDOWS_DENY = ("AppData/Local/Google/Chrome", "AppData/Local/Microsoft/Edge", "AppData/Roaming/Mozilla")


def grants_path(root: Path) -> Path:
    return root / "var" / "agent" / "grants.json"


def _resolve(p: str | Path) -> Path:
    return Path(os.path.expanduser(str(p))).resolve(strict=False)


class Grants:
    def __init__(self, root: Path, home: Path | None = None):
        self.root, self.path = root, grants_path(root)
        self.home = _resolve(home or Path.home())
        self.project_var = _resolve(root / "var")

    def folders(self) -> list[Path]:
        """每次都重讀檔案（命令列改了立即生效）。 / Re-read every time so CLI changes apply at once."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [_resolve(f["path"]) for f in data.get("folders") or [] if isinstance(f, dict) and f.get("path")]

    def denied(self, real: Path) -> str | None:
        """機密位置的理由；不是就回傳 None。 / Why a resolved path is secret, or None."""
        for part in real.parts:
            if any(fnmatch.fnmatch(part, pat) for pat in DENY_NAMES):
                return f"secret location ({part})"
        if real == self.project_var or self.project_var in real.parents:
            return "the project's var/ (keys, trajectories, memory)"
        for d in DENY_HOME:
            p = self.home / d
            if real == p or p in real.parents:
                return f"protected folder (~/{d})"
        s = real.as_posix()
        for d in WINDOWS_DENY:
            if f"/{d}" in s:
                return f"browser profile ({d})"
        return None

    def check(self, path: str | Path) -> tuple[Path | None, str | None]:
        """回傳 (實際路徑, None) 或 (None, 拒絕原因)。 / Return (real path, None) or (None, reason)."""
        if not str(path).strip():
            return None, "empty path"
        real = _resolve(path)
        why = self.denied(real)
        if why:
            return None, f"refused: {why}"
        folders = self.folders()
        if not folders:
            return None, "refused: no folder has been granted (scripts/jiezi agent grant <folder>)"
        if not any(real == f or f in real.parents for f in folders):
            return None, "refused: outside the granted folders"
        return real, None

    def check_write(self, path: str | Path) -> tuple[Path | None, str | None]:
        """建立新檔前的檢查（add-agent-approval）：父資料夾存在且在授權內、目標不存在（含壞掉的符號連結）、
        不在機密位置。回傳 (實際路徑, None) 或 (None, 拒絕原因)。
        Checks before creating a new file: granted existing parent, nothing at the target, not a secret location."""
        if not str(path).strip():
            return None, "empty path"
        given = Path(os.path.expanduser(str(path)))
        if not given.is_absolute():
            return None, "refused: give a full path"
        if given.name in ("", ".", ".."):
            return None, "refused: not a file name"
        if os.path.lexists(given):  # 既有檔、資料夾或符號連結都不行 / existing file, folder or symlink
            return None, "refused: something already exists at that path; this tool only creates new files"
        parent = _resolve(given.parent)  # 解析父資料夾的符號連結後再比對授權 / resolve the parent, then check
        if not parent.is_dir():
            return None, "refused: parent directory does not exist"
        real = parent / given.name
        why = self.denied(real)
        if why:
            return None, f"refused: {why}"
        folders = self.folders()
        if not folders:
            return None, "refused: no folder has been granted (scripts/jiezi agent grant <folder>)"
        if not any(real.parent == f or f in real.parents for f in folders):
            return None, "refused: outside the granted folders"
        return real, None

    # ── 只有命令列會呼叫 / CLI only ──
    def _write(self, folders: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"folders": folders}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def _raw(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("folders") or []
        except (OSError, ValueError):
            return []

    def grant(self, folder: str) -> str:
        real = _resolve(folder)
        if not real.is_dir():
            raise ValueError(f"not a folder: {real}")
        why = self.denied(real)
        if why:
            raise ValueError(f"cannot grant a {why}")
        if real == self.home or real == Path("/") or real in self.home.parents:
            raise ValueError("refusing to grant the whole home folder or a parent of it; grant a specific folder")
        raw = [f for f in self._raw() if _resolve(f.get("path", "")) != real]
        raw.append({"path": str(real), "added": _dt.datetime.now().astimezone().isoformat(timespec="seconds")})
        self._write(raw)
        return str(real)

    def revoke(self, folder: str) -> bool:
        real = _resolve(folder)
        raw = self._raw()
        keep = [f for f in raw if _resolve(f.get("path", "")) != real]
        self._write(keep)
        return len(keep) != len(raw)

    # ── 受信任的 MCP server（add-agent-trust-gate T8.2）/ Trusted MCP servers ──
    # 另存一檔：grants.json 只放資料夾，_write 會整檔覆寫 / a separate file; _write rewrites grants.json whole
    def _trusted_path(self) -> Path:
        return self.path.parent / "trusted_mcp.json"

    def trusted_servers(self) -> list[str]:
        try:
            names = json.loads(self._trusted_path().read_text(encoding="utf-8")).get("servers") or []
        except (OSError, ValueError):
            return []
        return sorted({str(n) for n in names if isinstance(n, str)})

    def is_trusted(self, server: str) -> bool:
        """每次呼叫都重讀，撤銷立即生效。 / Re-read per call so removal takes effect at once."""
        return server in self.trusted_servers()

    def trust_mcp(self, server: str, remove: bool = False) -> bool:
        """標記／取消標記受信任的 MCP server；回傳是否有變更。 / Mark or unmark a server; True when changed."""
        server = server.strip()
        if not server or len(server) > 100:
            raise ValueError("server name must be 1–100 characters")
        names = set(self.trusted_servers())
        before = set(names)
        names.discard(server) if remove else names.add(server)
        if names == before:
            return False
        path = self._trusted_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"servers": sorted(names)}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True

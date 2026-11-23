"""逐次核准的單一寫入工具（add-agent-approval）。

只做一件事：在使用者授權的資料夾裡**建立新檔案**。不覆寫、不刪除、不執行、不連網。
流程：模型呼叫 `write_file` → 這裡建立一筆核准請求（proposed）並回傳「等待核准」；檔案**還沒寫**。
使用者用 `scripts/jiezi agent approve <id> --sha256 <前 12 碼以上>` 或 gateway 的 `/v1/agent/approvals/{id}`
看過完整內容後核准，才真正寫入（applied）；可以拒絕（denied）、逾時（expired）、撤回（rolled_back＝刪掉剛建的檔，
前提是檔案內容沒被改過）。

安全設計（主控 2026-11-23 更正 W7 草稿）：
- 給模型的工具結果**沒有任何核准憑證**，只有請求編號與內容 sha256；模型沒有任何核准的方法（MCP 只有 tools/*）。
  草稿把一次性 token 回傳給模型，等於讓模型自己核准自己。
- 核准必須回填內容的 sha256（至少前 12 碼），證明核准者看過的就是要寫入的那一份。
- 寫入時重新檢查授權（核准後撤銷授權 → 不寫）、`O_CREAT|O_EXCL|O_NOFOLLOW`（不跟隨符號連結、不覆寫）、磁碟剩餘空間。
- 預設關閉：`JIEZI_AGENT_WRITE=on` 才會出現在工具清單。

Per-action approval for a single reversible write tool: create a new file inside a granted folder, only after a
person has seen the full content and echoed its sha256. The model never receives anything that can approve."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import secrets
import shutil
import threading
from pathlib import Path

from .grants import Grants

DEFAULT_TIMEOUT_S = 300                 # 使用者 2026-11-23 授權主控依建議定案（Q2：預設 5 分鐘、可調）
MAX_CONTENT_BYTES = 10_000_000          # Q4：10 MB
MIN_DISK_FREE_BYTES = 100_000_000
RETENTION_DAYS = 7                      # Q3：請求紀錄保留 7 天
MIN_SHA_PREFIX = 12
STATES = ("proposed", "approved", "denied", "expired", "applied", "rolled_back")
_LOCK = threading.Lock()

WRITE_SCHEMA = {"type": "function", "function": {
    "name": "write_file",
    "description": "在已授權的資料夾裡建立一個新的文字檔（不能覆寫或刪除）。呼叫後要等使用者核准才會真的寫入。"
                   "Create a new text file inside a granted folder; it is written only after the user approves.",
    "parameters": {"type": "object", "properties": {
        "path": {"type": "string", "description": "新檔案的完整路徑（父資料夾必須已存在）"},
        "content": {"type": "string", "description": "檔案內容"}},
        "required": ["path", "content"], "additionalProperties": False}}}


class ApprovalError(Exception):
    pass


def write_enabled(env: dict | None = None) -> bool:
    v = (env if env is not None else os.environ).get("JIEZI_AGENT_WRITE", "")
    return v.strip().lower() in ("1", "on", "true", "yes")


def timeout_s(env: dict | None = None) -> int:
    try:
        return max(30, min(3600, int((env if env is not None else os.environ).get("JIEZI_APPROVAL_TIMEOUT_S", ""))))
    except ValueError:
        return DEFAULT_TIMEOUT_S


def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def public(req: dict, with_content: bool = False) -> dict:
    """對外的樣子：預設不含內容（列表、稽核、給模型）。 / Without content unless asked."""
    out = {k: v for k, v in req.items() if k != "content"}
    if with_content:
        out["content"] = req.get("content")
    return out


class ApprovalStore:
    def __init__(self, root: Path):
        self.dir = root / "var" / "agent" / "approvals"

    def _path(self, rid: str) -> Path:
        if not rid or not all(c.isalnum() or c == "-" for c in rid):
            raise ApprovalError("bad approval id")
        return self.dir / f"{rid}.json"

    def _save(self, req: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        p = self._path(req["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(req, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)

    def get(self, rid: str) -> dict | None:
        try:
            req = json.loads(self._path(rid).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return self._expire(req)

    def list(self, status: str | None = None) -> list[dict]:
        out = []
        for p in sorted(self.dir.glob("*.json")) if self.dir.exists() else []:
            req = self.get(p.stem)
            if req and (status is None or req["status"] == status):
                out.append(req)
        return sorted(out, key=lambda r: r["created_at"], reverse=True)

    def _expire(self, req: dict) -> dict:
        if req["status"] == "proposed" and _dt.datetime.fromisoformat(req["expires_at"]) < _now():
            req["status"] = "expired"
            req["history"].append({"at": _now().isoformat(timespec="seconds"), "status": "expired"})
            self._save(req)
        return req

    def cleanup(self, days: int = RETENTION_DAYS) -> int:
        """刪掉超過保留期限、已結案的請求紀錄（寫好的檔案不動）。 / Drop old closed requests; files stay."""
        cutoff, n = _now() - _dt.timedelta(days=days), 0
        for req in self.list():
            if req["status"] != "proposed" and _dt.datetime.fromisoformat(req["created_at"]) < cutoff:
                self._path(req["id"]).unlink(missing_ok=True)
                n += 1
        return n

    # ── 模型那一側：只能提出 / the model's side: propose only ──
    def propose(self, g: Grants, path: str, content: str, meta: dict | None = None) -> dict:
        if not isinstance(content, str):
            raise ApprovalError("content must be text")
        size = len(content.encode("utf-8"))
        if size > MAX_CONTENT_BYTES:
            raise ApprovalError(f"refused: content is {size} bytes, over the {MAX_CONTENT_BYTES} limit")
        real, why = g.check_write(path)
        if why:
            raise ApprovalError(why)
        now = _now()
        req = {"id": f"{now:%Y%m%d%H%M%S}-{secrets.token_hex(4)}", "tool": "write_file", "path": str(real),
               "content": content, "sha256": _sha(content), "bytes": size, "status": "proposed",
               "created_at": now.isoformat(timespec="seconds"),
               "expires_at": (now + _dt.timedelta(seconds=timeout_s())).isoformat(timespec="seconds"),
               "history": [{"at": now.isoformat(timespec="seconds"), "status": "proposed"}], **(meta or {})}
        with _LOCK:
            self._save(req)
        return req

    # ── 人那一側：核准、拒絕、撤回 / the person's side ──
    def decide(self, g: Grants, rid: str, action: str, sha256: str = "", reason: str = "", actor: str = "cli") -> dict:
        with _LOCK:
            req = self.get(rid)
            if req is None:
                raise ApprovalError("no such approval request")
            if action == "allow":
                self._allow(g, req, sha256)
            elif action == "deny":
                if req["status"] != "proposed":
                    raise ApprovalError(f"cannot deny a request that is {req['status']}")
                req["status"] = "denied"
            elif action == "rollback":
                self._rollback(req)
            else:
                raise ApprovalError("action must be allow, deny or rollback")
            req["history"].append({"at": _now().isoformat(timespec="seconds"), "status": req["status"],
                                   "actor": actor, "reason": (reason or "")[:300]})
            self._save(req)
            return req

    def _allow(self, g: Grants, req: dict, sha256: str) -> None:
        if req["status"] != "proposed":  # 重放：已核准、已拒絕、已逾時都不能再核准 / no replays
            raise ApprovalError(f"cannot approve a request that is {req['status']}")
        sha256 = (sha256 or "").strip().lower()
        if len(sha256) < MIN_SHA_PREFIX or not req["sha256"].startswith(sha256):
            raise ApprovalError(f"sha256 does not match the content (give at least {MIN_SHA_PREFIX} characters "
                                "of the sha256 shown with the full content)")
        real, why = g.check_write(req["path"])  # 核准後撤銷授權、或檔案已出現 → 不寫 / re-check at write time
        if why:
            raise ApprovalError(why)
        free = shutil.disk_usage(real.parent).free
        if free - req["bytes"] < MIN_DISK_FREE_BYTES:
            raise ApprovalError("refused: not enough free disk space")
        fd = os.open(real, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(req["content"])
        req["status"] = "applied"

    def _rollback(self, req: dict) -> None:
        if req["status"] != "applied":
            raise ApprovalError(f"cannot roll back a request that is {req['status']}")
        p = Path(req["path"])
        if p.is_symlink() or not p.is_file():
            raise ApprovalError("refused: the written file is gone or was replaced")
        if hashlib.sha256(p.read_bytes()).hexdigest() != req["sha256"]:  # 位元組比對，換行不轉換 / raw bytes
            raise ApprovalError("refused: the file was changed after it was written; not deleting it")
        p.unlink()
        req["status"] = "rolled_back"

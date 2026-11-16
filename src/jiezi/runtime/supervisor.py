"""引擎的延遲載入、閒置卸載、健康檢查、有上限的重啟，以及與夜間評測的協調
（規格 supervisor；add-gateway design D4）。
Lazy engine load, idle unload, health checks, bounded restart, and coordination with night evaluations
(spec supervisor; add-gateway design D4)."""

from __future__ import annotations

import json
import os
import time
import tomllib
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

import anyio

from ..errors import JieziError
from .settings import Settings

RESTART_WINDOW_S = 60
MAX_RESTARTS = 3
CPU_ONLY_MARKERS = ("TQ1_0", "TQ2_0")


class EngineUnavailable(JieziError):
    pass


def resolve_core(settings: Settings, name: str | None = None) -> dict:
    """模型清單中的核心模型；檔案必須存在且大小吻合。 / The core model from the manifest; file must exist."""
    name = name or settings.core_model
    manifest = tomllib.loads((settings.root / "models" / "manifest.toml").read_text(encoding="utf-8"))
    m = next((x for x in manifest.get("model") or [] if x.get("name") == name), None)
    if m is None:
        raise JieziError(f"JIEZI_CORE_MODEL={name!r} is not in models/manifest.toml")
    path = settings.models_dir / m["file"]
    if not path.is_file() or path.stat().st_size != int(m["size"]):
        raise JieziError(f"core model file {path} is missing or incomplete; download it first "
                         "(scripts/bootstrap for the default, or scripts/eval e0 fetch)")
    quant = next((q for q in CPU_ONLY_MARKERS if q.lower() in m["file"].lower()), "other")
    # 視覺模組（add-vision）：清單裡的 mmproj 欄位指向另一筆模型；檔案存在才啟用
    # Vision projector (add-vision): the mmproj field names another manifest entry; enabled only when present
    mmproj = None
    if m.get("mmproj"):
        mm = next((x for x in manifest.get("model") or [] if x.get("name") == m["mmproj"]), None)
        if mm and (settings.models_dir / mm["file"]).is_file():
            mmproj = settings.models_dir / mm["file"]
    return {"name": name, "file": m["file"], "path": path, "size": int(m["size"]), "sha256": m["sha256"],
            "quant": quant, "mmproj_path": mmproj, "vision": mmproj is not None}


def place_core(core: dict, budgets: dict) -> dict:
    """沿用 E0 的擺放規則（整個 GPU，否則純 CPU）。 / Reuse the E0 placement rule (whole GPU, else CPU)."""
    from ..eval import e0
    row = e0.Row(name=core["name"], model=core["name"], group="int4", base="", quant=core["quant"],
                 placement="gpu", file=core["file"], size=core["size"], sha256=core["sha256"], url="")
    return e0.place(row, budgets)


class Supervisor:
    def __init__(self, settings: Settings, facts_fn: Callable[[], dict], engine_factory: Callable,
                 clock: Callable[[], float] = time.monotonic, now: Callable[[], datetime] = datetime.now,
                 log=print):
        self.s, self.facts_fn, self.engine_factory = settings, facts_fn, engine_factory
        self.clock, self.now, self.log = clock, now, log
        self.status = "unloaded"
        self.engine = None
        self.core: dict | None = None
        self.placement: dict | None = None
        self.reason: str | None = None
        self.hold_until: datetime | None = None
        self.in_flight = 0
        self.last_used = clock()
        self.crashes: deque[float] = deque()
        self.loads = 0
        self._lock = anyio.Lock()
        self.state_path = settings.var / "runtime" / "state.json"

    # ── 對外 / Public ──
    @property
    def base_url(self) -> str | None:
        return getattr(self.engine, "base_url", None) if self.status == "loaded" else None

    async def acquire(self) -> str:
        """確保引擎已載入並回傳 base_url；呼叫者用完必須 release()。
        Ensure the engine is loaded and return its base_url; callers must release() afterwards."""
        async with self._lock:
            self._expire_hold()
            if self.status == "held":
                raise EngineUnavailable(f"held for a night evaluation until {self.hold_until:%H:%M}")
            if self.status == "unavailable":
                raise EngineUnavailable(self.reason or "engine unavailable")
            if self.status != "loaded":
                await anyio.to_thread.run_sync(self._load)
            self.in_flight += 1
            self.last_used = self.clock()
            return self.engine.base_url

    def release(self) -> None:
        self.in_flight = max(0, self.in_flight - 1)
        self.last_used = self.clock()

    async def tick(self) -> None:
        """每 5 秒呼叫一次：健康檢查、重啟、閒置卸載、解除暫停。 / Called every 5 s."""
        async with self._lock:
            self._expire_hold()
            if self.status != "loaded":
                return
            if self.in_flight and self.clock() - self.last_used > 2 * self.s.request_timeout_s:
                # 中斷前就結束的串流可能沒有歸還計數 / a stream dropped before it started may not release
                self.in_flight = 0
            if not self.engine.alive():
                await anyio.to_thread.run_sync(self._on_crash)
            elif self.in_flight == 0 and self.clock() - self.last_used > self.s.idle_unload_s:
                self.log(f"engine idle for {self.s.idle_unload_s}s; unloading")
                self._stop("unloaded")

    async def unload(self, hold_until: datetime | None = None, reason: str | None = None) -> dict:
        async with self._lock:
            was = self.status
            self._stop("held" if hold_until else "unloaded")
            self.hold_until, self.reason = hold_until, reason if hold_until else None
            self.write_state()
            return {"was": was, "status": self.status,
                    "hold_until": hold_until.isoformat(timespec="minutes") if hold_until else None}

    def shutdown(self) -> None:
        self._stop("unloaded")

    def describe(self) -> dict:
        eng = self.engine
        return {"status": self.status, "reason": self.reason, "core_model": self.s.core_model,
                "placement": (self.placement or {}).get("placement"), "ngl": (self.placement or {}).get("ngl"),
                "engine_port": self.s.engine_port, "engine_pid": getattr(getattr(eng, "proc", None), "pid", None),
                "peak_rss_mib": getattr(eng, "peak_rss_mib", None), "peak_vram_mib": getattr(eng, "peak_vram_mib", None),
                "in_flight": self.in_flight, "loads": self.loads,
                "hold_until": self.hold_until.isoformat(timespec="minutes") if self.hold_until else None}

    def write_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {**self.describe(), "gateway_pid": os.getpid(), "gateway_port": self.s.gateway_port,
                    "updated": datetime.now().astimezone().isoformat(timespec="seconds")}
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError as exc:
            self.log(f"warning: cannot write {self.state_path}: {exc}")

    # ── 內部 / Internal ──
    def _expire_hold(self) -> None:
        if self.status == "held" and self.hold_until and self.now() >= self.hold_until:
            self.status, self.hold_until, self.reason = "unloaded", None, None
            self.write_state()

    def _load(self) -> None:
        self.status = "loading"
        try:
            core = resolve_core(self.s)
            facts = self.facts_fn()
            p = place_core(core, facts.get("budgets") or {})
            if p.get("excluded"):
                raise EngineUnavailable(f"core model does not fit: {p['reason']}")
            kw = {"alias": core["name"]}
            if core.get("mmproj_path"):  # 有視覺模組才傳 / only with a vision projector
                kw["mmproj"] = core["mmproj_path"]
            eng = self.engine_factory(facts, core["path"], p["ngl"], self.s.engine_port, **kw)
            log_path = self.s.var / "runtime" / "engine-chat.log"
            eng.start(log_path)
        except Exception as exc:
            self.status, self.reason = "unloaded", str(exc)
            self.write_state()
            raise EngineUnavailable(f"cannot load the core model: {exc}") from exc
        self.engine, self.core, self.placement = eng, core, p
        self.status, self.reason = "loaded", None
        self.loads += 1
        self.log(f"engine-chat loaded: {core['name']} on {p['placement']} (port {self.s.engine_port})")
        self.write_state()

    def _stop(self, status: str) -> None:
        if self.engine is not None:
            try:
                self.engine.stop()
            except Exception as exc:  # noqa: BLE001 - 關閉時的任何錯誤只記錄 / only logged on shutdown
                self.log(f"warning: engine stop: {exc}")
        self.engine = None
        self.status = status
        self.write_state()

    def _on_crash(self) -> None:
        t = self.clock()
        self.crashes.append(t)
        while self.crashes and t - self.crashes[0] > RESTART_WINDOW_S:
            self.crashes.popleft()
        self._stop("unloaded")
        if len(self.crashes) > MAX_RESTARTS:
            self.status = "unavailable"
            self.reason = f"engine crashed {len(self.crashes)} times within {RESTART_WINDOW_S}s; see var/runtime/engine-chat.log"
            self.log(self.reason)
            self.write_state()
            return
        self.log(f"engine crashed; restarting ({len(self.crashes)}/{MAX_RESTARTS})")
        try:
            self._load()
        except EngineUnavailable as exc:
            self.log(str(exc))

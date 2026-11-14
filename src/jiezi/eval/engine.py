"""本機 llama-server 的啟動、健康檢查、峰值記憶體取樣與關閉（規格 eval：Local Engine Isolation；design D6）。
Local llama-server lifecycle, health check, peak-memory sampling, and shutdown
(spec eval: Local Engine Isolation; design D6).

只綁 127.0.0.1（規則 R6.12）；port 取自實驗區段 JIEZI_PORT_BASE+10..+19（R11）；
執行緒、nice、taskset 取自 budgets（R18）。
Binds to 127.0.0.1 only (R6.12); port from the experiment block JIEZI_PORT_BASE+10..+19 (R11);
threads, nice, and taskset come from budgets (R18)."""

from __future__ import annotations

import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from jiezi.budget import budget_prefix

from . import EvalError

HOST = "127.0.0.1"
PORT_OFFSETS = range(10, 20)


def find_port(base: int, is_free=None) -> int:
    is_free = is_free or _port_free
    for off in PORT_OFFSETS:
        if is_free(base + off):
            return base + off
    raise EvalError(f"no free port in {base + PORT_OFFSETS[0]}–{base + PORT_OFFSETS[-1]} (experiment block, R11)")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def read_vm_hwm_kib(pid: int, proc: Path = Path("/proc")) -> int | None:
    """程序的峰值常駐記憶體（KiB）。 / Peak resident memory of a process (KiB)."""
    try:
        for line in (proc / str(pid) / "status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def read_vram_mib(pid: int, run=subprocess.run) -> int | None:
    """nvidia-smi 回報的該程序 VRAM（MiB）；WSL2 等環境可能無法取得單一程序數值，回傳 None。
    Per-process VRAM (MiB) from nvidia-smi; returns None where per-process data is unavailable (e.g. WSL2)."""
    try:
        p = run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in p.stdout.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 2 and parts[0] == str(pid) and parts[1].isdigit():
            return int(parts[1])
    return None


class LocalEngine:
    """with LocalEngine(...) as eng: eng.base_url —— 離開 with（含例外與 Ctrl-C）時一定關閉。
    with LocalEngine(...) as eng: eng.base_url — always stopped when leaving the block (exceptions and Ctrl-C included)."""

    def __init__(self, root: Path, facts: dict, model: Path, port_base: int, ngl: int = 0, ctx: int = 4096,
                 health_timeout_s: float = 300, popen=subprocess.Popen, is_free=None, vram=read_vram_mib):
        build = "build-cuda" if ngl > 0 else "build-cpu"
        self.binary = root / build / "bin" / "llama-server"
        if not self.binary.exists():
            raise EvalError(f"{self.binary} not found; run scripts/bootstrap first")
        if not model.is_file():
            raise EvalError(f"model not found: {model}")
        self.model, self.ngl, self.ctx = model, ngl, ctx
        self.port = find_port(port_base, is_free)
        prefix, self.threads, self.notes = budget_prefix(facts)
        self.affinity = ((facts.get("budgets") or {}).get("cpu") or {}).get("affinity_hint")
        self.cmd = [*prefix, str(self.binary), "-m", str(model), "--host", HOST, "--port", str(self.port),
                    "-t", str(self.threads), "-ngl", str(ngl), "-c", str(ctx), "-np", "1"]
        self.base_url = f"http://{HOST}:{self.port}"
        self.health_timeout_s = health_timeout_s
        self.popen, self.vram = popen, vram
        self.proc = None
        self.log_path: Path | None = None
        self.peak_rss_mib: float | None = None
        self.peak_vram_mib: int | None = None
        self._stop = threading.Event()
        self._sampler: threading.Thread | None = None

    def start(self, log_path: Path) -> None:
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = log_path.open("w", encoding="utf-8")
        self.proc = self.popen(self.cmd, stdout=self._log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        deadline = time.monotonic() + self.health_timeout_s
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise EvalError(f"llama-server exited with {self.proc.returncode} during startup; see {log_path}")
            if self._healthy():
                break
            time.sleep(0.5)
        else:
            raise EvalError(f"llama-server not healthy after {self.health_timeout_s} s; see {log_path}")
        self._sampler = threading.Thread(target=self._sample, daemon=True)
        self._sampler.start()

    def _healthy(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=2) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001 - 啟動中任何錯誤都只代表「還沒好」/ any error means "not ready yet"
            return False

    def _sample(self) -> None:
        while not self._stop.is_set():
            self.sample_once()
            self._stop.wait(1.0)

    def sample_once(self) -> None:
        if not self.proc:
            return
        hwm = read_vm_hwm_kib(self.proc.pid)
        if hwm is not None:
            self.peak_rss_mib = max(self.peak_rss_mib or 0, round(hwm / 1024, 1))
        if self.ngl > 0:
            v = self.vram(self.proc.pid)
            if v is not None:
                self.peak_vram_mib = max(self.peak_vram_mib or 0, v)

    def alive(self) -> bool:
        return bool(self.proc) and self.proc.poll() is None

    def stop(self) -> None:
        self._stop.set()
        if self.proc and self.proc.poll() is None:
            self.sample_once()
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=15)
        if getattr(self, "_log", None):
            self._log.close()

    def describe(self) -> dict:
        return {"binary": str(self.binary.relative_to(self.binary.parents[2])), "host": HOST, "port": self.port,
                "threads": self.threads, "affinity_hint": self.affinity, "ngl": self.ngl, "ctx": self.ctx,
                "parallel_slots": 1, "notes": self.notes}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

"""TTS 管理（add-tts）：啟動／停止合成行程、與核心輪流使用 GPU、後製（語速、音高、格式）。
TTS manager: worker lifecycle, GPU turn-taking with the core, and post-processing (speed, pitch, format).

GPU 輪流（使用者 2026-11-24 Q2）：同一時間只有核心或 TTS 一方在 GPU。
- 合成：拿 TTS 鎖 → 等核心沒有進行中的請求 → 卸載核心、標記 GPU 屬於 TTS → 啟動（或沿用）合成行程。
- 聊天：supervisor 載入核心前經 `jiezi.media.release_for_core`（在拿 supervisor 鎖之前，避免互等）→ 等合成結束、停掉行程。
- 合成行程閒置 120 秒自己結束；這裡發現它結束了就把 GPU 標記清掉。
Only one of the core and TTS holds the GPU; each takes it over only when the other is idle."""

from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

import anyio

from . import text as T
from . import voices as V

FORMATS = {"wav": ("audio/wav", []), "flac": ("audio/flac", []),
           "mp3": ("audio/mpeg", ["-c:a", "libmp3lame", "-q:a", "3"]),
           "opus": ("audio/ogg", ["-c:a", "libopus", "-b:a", "64k"])}
SPEED_RANGE, PITCH_RANGE = (0.5, 2.0), (-6.0, 6.0)
READY_TIMEOUT_S = 300           # 第一次載入約 70 秒；磁碟冷時更久 / first load ~70 s
OUT_RETENTION_DAYS = 7


class TTSError(Exception):
    def __init__(self, status: int, message: str, code: str):
        super().__init__(message)
        self.status, self.code = status, code


def venv_python(root: Path) -> Path:
    return root / "var" / "tts" / "venv" / "bin" / "python"


def model_dir(settings) -> Path:
    return settings.models_dir / "bluemagpie-tts"


def installed(settings) -> str | None:
    """沒裝好回傳原因；裝好回傳 None。 / Why TTS is not installed, or None."""
    if not venv_python(settings.root).is_file():
        return "TTS environment missing (scripts/jiezi tts setup)"
    md = model_dir(settings)
    for f in ("pytorch_model.bin", "audiovae.pth", "tokenizer.json", "checkpoints/speaker_centroids.pt"):
        if not (md / f).is_file():
            return f"TTS weights missing: {f} (scripts/jiezi tts setup)"
    return None


def postprocess(src: Path, dst: Path, fmt: str, speed: float = 1.0, pitch: float = 0.0) -> None:
    """語速（atempo）與音高（半音，asetrate＋atempo 補回長度）、轉檔。 / Speed, pitch and format via ffmpeg."""
    filters = []
    if abs(pitch) > 1e-3:
        f = 2 ** (pitch / 12)
        filters += [f"asetrate=48000*{f:.6f}", "aresample=48000"]
        speed = speed / f
    if abs(speed - 1.0) > 1e-3:
        s = speed
        while s > 2.0:                     # atempo 一次只接受 0.5–2.0 / atempo takes 0.5–2.0 per stage
            filters.append("atempo=2.0")
            s /= 2.0
        while s < 0.5:
            filters.append("atempo=0.5")
            s /= 0.5
        filters.append(f"atempo={s:.6f}")
    if fmt == "wav" and not filters:
        shutil.copyfile(src, dst)
        return
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(src)]
    if filters:
        cmd += ["-af", ",".join(filters)]
    cmd += FORMATS[fmt][1] + [str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise TTSError(500, f"audio conversion failed: {r.stderr.strip()[:200]}", "tts_convert_failed")


class TTSManager:
    def __init__(self, settings, sup, log=print, spawn=None):
        self.s, self.sup, self.log = settings, sup, log
        self.proc: subprocess.Popen | None = None
        self.voices_ready: list[str] = []
        self._spawn = spawn or self._spawn_worker
        self.out_dir = settings.var / "tts" / "out"
        self.log_path = settings.var / "tts" / "log.jsonl"
        self.last: dict | None = None
        sup.gpu_stoppers["tts"] = self._kill   # 核心或 ASR 要 GPU 時停掉我 / evicted by the core or ASR

    # ── 行程 / process ──
    def _spawn_worker(self) -> subprocess.Popen:
        cmd = [str(venv_python(self.s.root)), "-I", str(Path(__file__).with_name("worker.py")),
               "--model-dir", str(model_dir(self.s)), "--voices-dir", str(V.voices_dir(self.s.var)),
               "--out-dir", str(self.out_dir), "--idle", str(self.s.tts_idle_s)]
        (self.s.var / "tts").mkdir(parents=True, exist_ok=True)
        err = open(self.s.var / "tts" / "worker.log", "ab")
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "CUDA_VISIBLE_DEVICES",
                                                           "HF_HOME", "TMPDIR")}
        env["HF_HUB_OFFLINE"] = "1"                 # 權重已在本機，不連網 / weights are local; no network
        try:
            return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, env=env,
                                    cwd=str(self.s.var / "tts"), text=True, bufsize=1)
        finally:
            err.close()                            # 子行程已複製一份 / the child holds its own copy

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _readline(self, timeout: float) -> dict:
        box: dict = {}

        def read():
            box["line"] = self.proc.stdout.readline()
        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive() or not box.get("line"):
            self._kill()
            raise TTSError(504 if t.is_alive() else 500,
                           "TTS worker timed out" if t.is_alive() else "TTS worker exited (see var/tts/worker.log)",
                           "tts_worker_failed")
        return json.loads(box["line"])

    def _ensure_worker(self) -> None:
        if self.alive():
            return
        self.proc = self._spawn()
        ready = self._readline(READY_TIMEOUT_S)
        if not ready.get("ready"):
            self._kill()
            raise TTSError(500, f"TTS worker failed to start: {ready.get('error')}", "tts_worker_failed")
        self.voices_ready = ready.get("voices") or []

    def _kill(self) -> None:
        p, self.proc = self.proc, None
        if p is None:
            return
        try:
            if p.poll() is None:
                try:
                    p.stdin.write(json.dumps({"op": "quit"}) + "\n")
                    p.stdin.flush()
                    p.wait(10)
                except (OSError, subprocess.TimeoutExpired):
                    p.kill()
                    p.wait(10)
        finally:
            for f in (p.stdin, p.stdout):          # 關掉管線，避免殘留檔案描述子 / close the pipes
                try:
                    if f:
                        f.close()
                except OSError:
                    pass
            self.sup.gpu_owner = None if self.sup.gpu_owner == "tts" else self.sup.gpu_owner

    def shutdown(self) -> None:
        self._kill()

    def describe(self) -> dict:
        if self.proc is not None and not self.alive():   # 閒置自己結束了 / exited on idle
            self.proc = None
            if self.sup.gpu_owner == "tts":
                self.sup.gpu_owner = None
        return {"enabled": bool(self.s.tts), "installed": installed(self.s) is None,
                "worker": "running" if self.alive() else "stopped", "gpu_owner": self.sup.gpu_owner or "none",
                "last": self.last}

    # ── 合成 / synthesis ──
    def _cleanup(self) -> None:
        cutoff = time.time() - OUT_RETENTION_DAYS * 86400
        for p in self.out_dir.glob("*"):
            try:
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass

    def _synth_blocking(self, chunks: list[str], voice: dict, raw: Path) -> dict:
        self._ensure_worker()
        self.proc.stdin.write(json.dumps({"op": "synth", "chunks": chunks, "voice": voice, "out": str(raw),
                                          "pause_s": 0.25}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        res = self._readline(max(120.0, 30.0 * len(chunks)))
        if not res.get("ok"):
            raise TTSError(500, f"synthesis failed: {res.get('error')}", "tts_failed")
        return res

    async def speak(self, text: str, voice: str | None = None, fmt: str = "wav", speed: float = 1.0,
                    pitch: float = 0.0, clean: bool = True) -> tuple[bytes, str, dict]:
        """文字 → (音檔位元組, MIME, 中繼資料)。 / Text → (audio bytes, MIME type, metadata)."""
        if fmt not in FORMATS:
            raise TTSError(400, f"response_format must be one of {', '.join(FORMATS)}", "invalid_request")
        if not (SPEED_RANGE[0] <= speed <= SPEED_RANGE[1]) or not (PITCH_RANGE[0] <= pitch <= PITCH_RANGE[1]):
            raise TTSError(400, "speed must be 0.5–2.0 and pitch −6 to 6 semitones", "invalid_request")
        if not isinstance(text, str) or not text.strip():
            raise TTSError(400, "input must be non-empty text", "invalid_request")
        if len(text) > T.MAX_INPUT_CHARS:
            raise TTSError(400, f"input is longer than {T.MAX_INPUT_CHARS} characters", "invalid_request")
        try:
            wv, cloned = V.resolve(self.s.var, voice)
        except V.VoiceError as exc:
            raise TTSError(400, str(exc), "invalid_voice") from exc
        chunks = T.split_chunks(T.clean_for_speech(text) if clean else text)
        if not chunks:
            raise TTSError(400, "nothing speakable in the input", "invalid_request")
        why = installed(self.s)
        if why:
            raise TTSError(503, why, "tts_unavailable")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{_dt.datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
        raw, final = self.out_dir / f"{stamp}.raw.wav", self.out_dir / f"{stamp}.{fmt}"
        t0 = time.monotonic()
        from ..media import GpuBusy, take_gpu
        async with self.sup.media_lock:
            try:
                await take_gpu(self.sup, "tts", self.log)
            except GpuBusy as exc:
                raise TTSError(503, str(exc), exc.code) from exc
            res = await anyio.to_thread.run_sync(self._synth_blocking, chunks, wv, raw)
        await anyio.to_thread.run_sync(postprocess, raw, final, fmt, speed, pitch)
        raw.unlink(missing_ok=True)
        data = final.read_bytes()
        meta = {"at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"), "file": final.name,
                "voice": voice or V.DEFAULT_VOICE, "cloned": cloned, "chars": len(text), "chunks": len(chunks),
                "format": fmt, "speed": speed, "pitch": pitch, "audio_s": res.get("audio_s"),
                "gen_s": res.get("gen_s"), "total_s": round(time.monotonic() - t0, 2)}
        self.last = meta
        try:                             # 只記中繼資料，不記文字與音檔 / metadata only
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        except OSError:
            pass
        await anyio.to_thread.run_sync(self._cleanup)
        return data, FORMATS[fmt][0], meta

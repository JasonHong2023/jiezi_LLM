"""ASR 管理（add-asr）：辨識行程、與核心／TTS 輪流用 GPU、字幕格式、台灣用字。
ASR manager: worker lifecycle, GPU turn-taking, subtitle formats and Taiwan Traditional output."""

from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path

import anyio

MAX_BYTES = 200 * 1024 * 1024
MAX_SECONDS = 2 * 3600
FORMATS = ("json", "text", "srt", "vtt", "verbose_json")
READY_TIMEOUT_S = 300
DEFAULT_PROMPT = "芥子"          # 專有名詞提示：冒煙測試把「芥子」聽成「介子」/ the smoke test heard 介子
MODEL_FILES = ("model.safetensors", "config.json", "preprocessor_config.json", "tokenizer.json", "vocab.json",
               "merges.txt", "normalizer.json", "added_tokens.json", "special_tokens_map.json",
               "tokenizer_config.json", "generation_config.json")


class ASRError(Exception):
    def __init__(self, status: int, message: str, code: str):
        super().__init__(message)
        self.status, self.code = status, code


def model_dir(settings) -> Path:
    return settings.models_dir / "breeze-asr-25"


def installed(settings) -> str | None:
    from ..tts.manager import venv_python
    if not venv_python(settings.root).is_file():
        return "speech environment missing (scripts/jiezi tts setup)"
    for f in MODEL_FILES:
        if not (model_dir(settings) / f).is_file():
            return f"ASR weights missing: {f} (scripts/jiezi asr setup)"
    return None


def _ts(t: float | None, sep: str) -> str:
    t = max(0.0, float(t or 0.0))
    h, rem = divmod(int(t * 1000), 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def segments_fixed(segs: list[dict], audio_s: float) -> list[dict]:
    """補上缺的結束時間（最後一段常是 None）。 / Fill missing end times (the last chunk is often None)."""
    out = []
    for i, s in enumerate(segs):
        if not s.get("text"):
            continue
        start = s.get("start") or 0.0
        end = s.get("end")
        if end is None:
            end = segs[i + 1].get("start") if i + 1 < len(segs) and segs[i + 1].get("start") else audio_s
        out.append({"start": round(start, 2), "end": round(max(end, start), 2), "text": s["text"]})
    return out


def render(result: dict, fmt: str) -> tuple[str, str]:
    """(內容, MIME)。 / (body, MIME type)."""
    segs = result["segments"]
    if fmt == "text":
        return result["text"] + "\n", "text/plain; charset=utf-8"
    if fmt == "srt":
        body = "\n".join(f"{i}\n{_ts(s['start'], ',')} --> {_ts(s['end'], ',')}\n{s['text']}\n"
                         for i, s in enumerate(segs, 1))
        return body, "application/x-subrip; charset=utf-8"
    if fmt == "vtt":
        body = "WEBVTT\n\n" + "\n".join(f"{_ts(s['start'], '.')} --> {_ts(s['end'], '.')}\n{s['text']}\n"
                                         for s in segs)
        return body, "text/vtt; charset=utf-8"
    if fmt == "verbose_json":
        return json.dumps({"task": "transcribe", "language": "zh", "duration": result["audio_s"],
                           "text": result["text"], "segments": [{"id": i, **s} for i, s in enumerate(segs)]},
                          ensure_ascii=False), "application/json"
    return json.dumps({"text": result["text"]}, ensure_ascii=False), "application/json"


def taiwan(text: str) -> str:
    from ..textconv import simplified_to_taiwan
    return simplified_to_taiwan(text) or text


class ASRManager:
    def __init__(self, settings, sup, log=print, spawn=None):
        self.s, self.sup, self.log = settings, sup, log
        self.proc: subprocess.Popen | None = None
        self._spawn = spawn or self._spawn_worker
        self.tmp = settings.var / "asr" / "tmp"
        self.log_path = settings.var / "asr" / "log.jsonl"
        self.last: dict | None = None
        sup.gpu_stoppers["asr"] = self._kill

    def _spawn_worker(self) -> subprocess.Popen:
        from ..tts.manager import venv_python
        (self.s.var / "asr").mkdir(parents=True, exist_ok=True)
        cmd = [str(venv_python(self.s.root)), "-I", str(Path(__file__).with_name("worker.py")),
               "--model-dir", str(model_dir(self.s)), "--tmp-dir", str(self.tmp), "--idle", str(self.s.asr_idle_s)]
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL", "CUDA_VISIBLE_DEVICES",
                                                           "TMPDIR")}
        env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        err = open(self.s.var / "asr" / "worker.log", "ab")
        try:
            return subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, env=env,
                                    cwd=str(self.s.var / "asr"), text=True, bufsize=1)
        finally:
            err.close()

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
            raise ASRError(504 if t.is_alive() else 500,
                           "ASR worker timed out" if t.is_alive() else "ASR worker exited (see var/asr/worker.log)",
                           "asr_worker_failed")
        return json.loads(box["line"])

    def _kill(self) -> None:
        p, self.proc = self.proc, None
        if p is not None:
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
                for f in (p.stdin, p.stdout):
                    try:
                        if f:
                            f.close()
                    except OSError:
                        pass
        if self.sup.gpu_owner == "asr":
            self.sup.gpu_owner = None

    def shutdown(self) -> None:
        self._kill()

    def describe(self) -> dict:
        if self.proc is not None and not self.alive():
            self._kill()
        return {"enabled": bool(self.s.asr), "installed": installed(self.s) is None,
                "worker": "running" if self.alive() else "stopped", "gpu_owner": self.sup.gpu_owner or "none",
                "last": self.last}

    def _duration(self, path: Path) -> float:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                            str(path)], capture_output=True, text=True, timeout=60)
        try:
            return float(r.stdout.strip())
        except ValueError as exc:
            raise ASRError(400, "the upload is not a readable audio or video file", "invalid_audio") from exc

    def _run_blocking(self, path: Path, prompt: str) -> dict:
        if not self.alive():
            self.proc = self._spawn()
            ready = self._readline(READY_TIMEOUT_S)
            if not ready.get("ready"):
                self._kill()
                raise ASRError(500, f"ASR worker failed to start: {ready.get('error')}", "asr_worker_failed")
        self.proc.stdin.write(json.dumps({"op": "transcribe", "path": str(path), "prompt": prompt},
                                         ensure_ascii=False) + "\n")
        self.proc.stdin.flush()
        res = self._readline(1800)
        if not res.get("ok"):
            raise ASRError(500, f"recognition failed: {res.get('error')}", "asr_failed")
        return res

    async def transcribe(self, data: bytes, filename: str = "audio", prompt: str | None = None) -> dict:
        """音檔位元組 → {"text", "segments", "audio_s", ...}；上傳檔辨識完就刪。 / Upload deleted afterwards."""
        if not data:
            raise ASRError(400, "the uploaded file is empty", "invalid_request")
        if len(data) > MAX_BYTES:
            raise ASRError(413, f"the upload is larger than {MAX_BYTES >> 20} MB", "request_too_large")
        why = installed(self.s)
        if why:
            raise ASRError(503, why, "asr_unavailable")
        self.tmp.mkdir(parents=True, exist_ok=True)
        suffix = "".join(c for c in Path(filename or "a").suffix[:8] if c.isalnum() or c == ".") or ".bin"
        path = self.tmp / f"{secrets.token_hex(8)}{suffix}"
        path.write_bytes(data)
        t0 = time.monotonic()
        try:
            dur = await anyio.to_thread.run_sync(self._duration, path)
            if dur > MAX_SECONDS:
                raise ASRError(413, f"the audio is longer than {MAX_SECONDS // 3600} hours", "request_too_large")
            from ..media import GpuBusy, take_gpu
            async with self.sup.media_lock:
                try:
                    await take_gpu(self.sup, "asr", self.log)
                except GpuBusy as exc:
                    raise ASRError(503, str(exc), exc.code) from exc
                res = await anyio.to_thread.run_sync(self._run_blocking, path,
                                                     DEFAULT_PROMPT if prompt is None else prompt)
        finally:
            path.unlink(missing_ok=True)
        segs = [{**s, "text": taiwan(s["text"])} for s in segments_fixed(res.get("segments") or [], res["audio_s"])]
        out = {"text": taiwan(res.get("text") or ""), "segments": segs, "audio_s": res["audio_s"],
               "gen_s": res.get("gen_s"), "total_s": round(time.monotonic() - t0, 2)}
        meta = {"at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"), "audio_s": out["audio_s"],
                "gen_s": out["gen_s"], "total_s": out["total_s"], "chars": len(out["text"])}
        self.last = meta
        try:                             # 只記中繼資料 / metadata only
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return out

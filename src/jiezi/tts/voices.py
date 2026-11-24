"""聲音名單（add-tts）：模型內附語者＋使用者在本機登錄、附同意聲明的聲音。
Voice registry: bundled speakers plus voices the user enrolled locally with a consent statement.

登錄只能經本機 CLI（`scripts/jiezi tts voice add`）；gateway 只讀名單，沒有任何登錄或上傳的方法。
Enrollment is CLI-only; the gateway only reads this registry."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

BUNDLED = ("female_voice", "hung_yi_lee")       # models/bluemagpie-tts/checkpoints/speaker_centroids.pt
DEFAULT_VOICE = "female_voice"                  # 使用者 2026-11-24：換預設語者
MIN_REF_S, MAX_REF_S = 3.0, 60.0
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{1,31}$")


class VoiceError(Exception):
    pass


def voices_dir(var: Path) -> Path:
    return var / "tts" / "voices"


def _index(var: Path) -> Path:
    return voices_dir(var) / "index.json"


def enrolled(var: Path) -> dict[str, dict]:
    try:
        data = json.loads(_index(var).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(var: Path, data: dict) -> None:
    voices_dir(var).mkdir(parents=True, exist_ok=True)
    tmp = _index(var).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_index(var))


def listing(var: Path) -> list[dict]:
    out = [{"id": v, "kind": "bundled", "default": v == DEFAULT_VOICE} for v in BUNDLED]
    for name, rec in sorted(enrolled(var).items()):
        out.append({"id": name, "kind": "enrolled", "default": False, "enrolled_at": rec.get("enrolled_at"),
                    "seconds": rec.get("seconds")})
    return out


def resolve(var: Path, name: str | None) -> tuple[dict, bool]:
    """聲音名稱 → (給 worker 的 voice, 是否為複製聲音)。 / Name → (worker voice, cloned?)."""
    name = (name or DEFAULT_VOICE).strip()
    if name in BUNDLED:
        return {"bundled": name}, False
    rec = enrolled(var).get(name)
    if rec and isinstance(rec.get("file"), str) and Path(rec["file"]).name == rec["file"]:
        p = voices_dir(var) / rec["file"]
        if p.is_file():
            return {"ref_wav": str(p)}, True
    raise VoiceError(f"unknown voice {name!r}; available: {', '.join(v['id'] for v in listing(var))}")


def _duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=30)
    try:
        return float(out.stdout.strip())
    except ValueError as exc:
        raise VoiceError(f"cannot read audio duration of {path}") from exc


def add(var: Path, name: str, audio: Path, consent: str) -> dict:
    """登錄一個聲音：必填同意聲明，3–60 秒，轉 16 kHz 單聲道。 / Enroll a voice with a consent statement."""
    consent = (consent or "").strip()
    if len(consent) < 4:
        raise VoiceError("a consent statement is required: who agreed to this voice being cloned, and when")
    if not _NAME.match(name or "") or name in BUNDLED:
        raise VoiceError("name must be 2–32 lowercase letters, digits, _ or -, and not a bundled voice")
    if not shutil.which("ffmpeg"):
        raise VoiceError("ffmpeg is required")
    audio = Path(audio).expanduser()
    if not audio.is_file():
        raise VoiceError(f"no such file: {audio}")
    dur = _duration(audio)
    if not MIN_REF_S <= dur <= MAX_REF_S:
        raise VoiceError(f"reference audio must be {MIN_REF_S:.0f}–{MAX_REF_S:.0f} seconds (got {dur:.1f})")
    data = enrolled(var)
    if name in data:
        raise VoiceError(f"voice {name!r} already exists; remove it first")
    d = voices_dir(var)
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{name}.wav"
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(audio), "-ac", "1", "-ar", "16000",
                        "-sample_fmt", "s16", str(out)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not out.is_file():
        out.unlink(missing_ok=True)
        raise VoiceError(f"ffmpeg could not convert the audio: {r.stderr.strip()[:200]}")
    rec = {"file": out.name, "consent": consent[:500], "seconds": round(dur, 2),
           "enrolled_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
           "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "source_name": audio.name}
    data[name] = rec
    _save(var, data)
    return {"id": name, **rec}


def remove(var: Path, name: str) -> bool:
    data = enrolled(var)
    rec = data.pop(name, None)
    if rec is None:
        return False
    (voices_dir(var) / rec["file"]).unlink(missing_ok=True)
    _save(var, data)
    return True

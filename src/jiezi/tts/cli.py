"""`scripts/jiezi tts`（add-tts）：安裝、聲音登錄、合成。 / TTS setup, voice enrollment and synthesis.

聲音登錄只在這裡（本機 CLI），gateway 沒有對應的方法。 / Voice enrollment exists only here."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import voices as V

# 鎖定版本（2026-11-24 主控查證；docs/licenses.md `bluemagpie-tts`）/ pinned versions
TTS_REPO = "https://github.com/OpenFormosa/BlueMagpie-TTS.git"
TTS_COMMIT = "210e8a8922269c4f65dfe8985e79c0609c240afb"
BARBET_REPO = "https://github.com/OpenFormosa/Barbet.git"
BARBET_COMMIT = "e453176cad9c846c082fadfda29ddfcdda36d69d"
TORCH = "torch==2.15.0"
PYTHON = "3.11"
HF_REPO = "OpenFormosa/BlueMagpie-TTS"
HF_REVISION = "4c2c5bcb7e87041a8eaba9df5821ec7a3e1d0c6c"
WEIGHTS = {   # 檔名 → (位元組, sha256) / file → (bytes, sha256)
    "pytorch_model.bin": (7800079543, "075a553b0981ca0ce8fe77bd9f802fe253bdf0e9f17fbc88fc2b8ae74ad11d3f"),
    "audiovae.pth": (376972749, "cc01a2d5d817910f185d959f8bb23d1a5ab80c9a03b7398ac86d7457cb663332"),
    "config.json": (7667, "b299f68aa8ee5f11953fc708b305a7db35b931ce0fa68b564199e0b82c8c4e68"),
    "tokenizer.json": (9357159, "17719160807d4450cd86f9267039d8f72a054b055c768fbbd9261b6bcc95eba3"),
    "tokenizer_config.json": (5980, "ec4f4ed2b5d61d8cbb706670059df76edbf214b5345d3b257711272e5f12965b"),
    "release_metadata.json": (4958, "edb8aa1c90d27a5b68bb746c7314149e67e16ccd44a10ad88adc75425b38288f"),
    "checkpoints/speaker_centroids.pt": (3311, "e3a155f66b9fc9ea589041b0e4a266a214a4bed2d9125bcddf1fb88c1210c5ae"),
}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch_weights(model_dir: Path, log=print) -> None:
    """下載並逐檔核對；不符就刪掉並停止。 / Download and verify each file; delete and stop on a mismatch."""
    for name, (size, sha) in WEIGHTS.items():
        dst = model_dir / name
        if dst.is_file() and dst.stat().st_size == size and _sha(dst) == sha:
            log(f"  ok  {name}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        part = dst.with_name(dst.name + ".part")
        url = f"https://huggingface.co/{HF_REPO}/resolve/{HF_REVISION}/{name}"
        log(f"  downloading {name} ({size >> 20} MiB)")
        req = urllib.request.Request(url, headers={"User-Agent": "jiezi-setup"})
        with urllib.request.urlopen(req, timeout=120) as r, part.open("wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        if part.stat().st_size != size or _sha(part) != sha:
            part.unlink(missing_ok=True)
            raise SystemExit(f"jiezi: {name}: size or sha256 does not match the pinned value; deleted")
        part.rename(dst)


def setup(root: Path, models_dir: Path, log=print) -> int:
    if not shutil.which("uv"):
        log("jiezi: uv is required")
        return 2
    tts = root / "var" / "tts"
    tts.mkdir(parents=True, exist_ok=True)
    venv = tts / "venv"
    if not (venv / "bin" / "python").is_file():
        log(f"creating {venv} (Python {PYTHON})")
        subprocess.run(["uv", "venv", "-q", "--python", PYTHON, str(venv)], check=True)
    ov = tts / "overrides.txt"
    ov.write_text(f"barbet @ git+{BARBET_REPO}@{BARBET_COMMIT}\n", encoding="utf-8")
    log("installing pinned packages (torch, BlueMagpie-TTS, Barbet, soundfile)")
    subprocess.run(["uv", "pip", "install", "-q", "--override", str(ov), TORCH, "soundfile",
                    f"bluemagpie-tts @ git+{TTS_REPO}@{TTS_COMMIT}"],
                   check=True, env={**os.environ, "VIRTUAL_ENV": str(venv)})
    log(f"fetching weights into {models_dir / 'bluemagpie-tts'} (revision {HF_REVISION[:12]})")
    fetch_weights(models_dir / "bluemagpie-tts", log)
    log("done. Enable with JIEZI_TTS=on in .env and restart the gateway.")
    return 0


def say(text: str, voice: str | None, fmt: str, speed: float, pitch: float, out: str | None) -> int:
    from ..cli.client import Connection
    import httpx
    conn = Connection.from_env()
    body = {"model": "bluemagpie", "input": text, "response_format": fmt, "speed": speed, "pitch": pitch}
    if voice:
        body["voice"] = voice
    try:
        r = httpx.post(conn.url + "/v1/audio/speech", json=body, timeout=1800, headers=conn.headers)
    except httpx.HTTPError as exc:
        sys.stderr.write(f"jiezi: gateway unreachable: {exc}\n")
        return 2
    if r.status_code != 200:
        sys.stderr.write(f"jiezi: {r.status_code} {r.text[:300]}\n")
        return 3
    path = Path(out).expanduser() if out else None
    if path:
        path.write_bytes(r.content)
    print(f"{path or r.headers.get('x-jiezi-file')}  ({r.headers.get('x-jiezi-audio-seconds')} s, "
          f"voice {r.headers.get('x-jiezi-voice')})")
    return 0


def main(args, settings) -> int:
    var = settings.var
    if args.tts_cmd == "setup":
        return setup(settings.root, settings.models_dir, print)
    if args.tts_cmd == "say":
        text = args.text if args.text != "-" else sys.stdin.read()
        return say(text, args.voice, args.format, args.speed, args.pitch, args.out)
    if args.tts_cmd == "voice":
        try:
            if args.voice_cmd == "add":
                rec = V.add(var, args.name, Path(args.audio), args.consent)
                print(json.dumps(rec, ensure_ascii=False, indent=1))
                return 0
            if args.voice_cmd == "remove":
                if not V.remove(var, args.name):
                    print(f"jiezi: no enrolled voice {args.name!r}")
                    return 1
                print(f"removed {args.name}")
                return 0
            for v in V.listing(var):
                extra = f"  enrolled {v['enrolled_at']}, {v['seconds']} s" if v["kind"] == "enrolled" else ""
                print(f"{v['id']:<20} {v['kind']}{' (default)' if v['default'] else ''}{extra}")
            return 0
        except V.VoiceError as exc:
            sys.stderr.write(f"jiezi: {exc}\n")
            return 2
    return 2


def add_parser(sub) -> None:
    tp = sub.add_parser("tts", help="speech synthesis, BlueMagpie-TTS (add-tts): setup, voices, say")
    ts = tp.add_subparsers(dest="tts_cmd", required=True)
    ts.add_parser("setup", help="create var/tts/venv, install pinned packages, download and verify the weights")
    sp = ts.add_parser("say", help="speak text through the gateway (JIEZI_TTS=on); '-' reads stdin")
    sp.add_argument("text")
    sp.add_argument("--voice")
    sp.add_argument("--format", default="wav", choices=["wav", "mp3", "flac", "opus"])
    sp.add_argument("--speed", type=float, default=1.0, help="0.5–2.0")
    sp.add_argument("--pitch", type=float, default=0.0, help="semitones, −6 to 6")
    sp.add_argument("--out", "-o", help="also copy the audio to this file")
    vp = ts.add_parser("voice", help="enrolled voices (voice cloning needs a consent statement)")
    vs = vp.add_subparsers(dest="voice_cmd", required=True)
    va = vs.add_parser("add", help="enroll a voice from 3–60 s of clean speech")
    va.add_argument("name")
    va.add_argument("audio")
    va.add_argument("--consent", required=True, help="who agreed to this voice being cloned, and when")
    vs.add_parser("list")
    vr = vs.add_parser("remove")
    vr.add_argument("name")

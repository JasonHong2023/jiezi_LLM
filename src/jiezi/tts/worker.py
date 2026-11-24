"""BlueMagpie-TTS 合成行程（add-tts）：在獨立的 Python 3.11 環境（var/tts/venv）裡執行，不匯入芥子主程式。

協定：stdin 一行一個 JSON 請求，stdout 一行一個 JSON 回覆（其他輸出一律走 stderr）。
- {"op": "ping"} → {"ok": true, "ready": true, "voices": [...], "sample_rate": 48000}
- {"op": "synth", "chunks": ["…", …], "voice": {"bundled": "female_voice"} | {"ref_wav": "<var/tts/voices 裡的檔>"},
   "out": "<var/tts/out 裡的 .wav>", "pause_s": 0.25}
  → {"ok": true, "audio_s": 3.2, "gen_s": 9.8, "chunks": 2}
- {"op": "quit"}
閒置超過 --idle 秒（預設 120）自動結束，把 GPU 還給核心。
路徑限制在 --voices-dir、--out-dir 底下（gateway 已檢查過，這裡再擋一次）。

Synthesis process for add-tts, run inside the separate TTS venv; JSON lines over stdin/stdout; exits when idle."""

from __future__ import annotations

import argparse
import json
import os
import select
import sys
import time
from pathlib import Path


def _inside(path: str, base: Path) -> Path:
    p = Path(path).resolve()
    if base.resolve() not in p.parents:
        raise ValueError(f"path outside {base}")
    return p


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--voices-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--idle", type=float, default=120.0)
    a = ap.parse_args(argv)
    real_stdout = sys.stdout
    sys.stdout = sys.stderr            # 套件的 print 不可混進協定 / library prints must not corrupt the protocol
    import numpy as np
    import soundfile as sf
    import torch
    from bluemagpie import BlueMagpieModel
    from transformers import PreTrainedTokenizerFast
    sys.stdout = real_stdout

    voices_dir, out_dir = Path(a.voices_dir), Path(a.out_dir)
    tok = PreTrainedTokenizerFast(tokenizer_file=os.path.join(a.model_dir, "tokenizer.json"))
    sys.stdout = sys.stderr
    model = BlueMagpieModel.from_local(a.model_dir, tokenizer=tok, training=False, device=a.device)
    sys.stdout = real_stdout
    table = torch.load(os.path.join(a.model_dir, "checkpoints", "speaker_centroids.pt"),
                       map_location="cpu", weights_only=True)
    ids = list(table["speaker_ids"])
    _reply({"ok": True, "ready": True, "voices": ids, "sample_rate": model.sample_rate})

    last = time.monotonic()
    while True:
        r, _, _ = select.select([sys.stdin], [], [], 1.0)
        if not r:
            if time.monotonic() - last > a.idle:
                return 0
            continue
        line = sys.stdin.readline()
        if not line:
            return 0
        last = time.monotonic()
        try:
            req = json.loads(line)
            op = req.get("op")
            if op == "quit":
                return 0
            if op == "ping":
                _reply({"ok": True, "ready": True, "voices": ids, "sample_rate": model.sample_rate})
                continue
            if op != "synth":
                raise ValueError(f"unknown op {op!r}")
            voice, kw = req.get("voice") or {}, {}
            if "bundled" in voice:
                if voice["bundled"] not in ids:
                    raise ValueError(f"unknown bundled voice {voice['bundled']!r}")
                kw["speaker_centroid"] = table["centroids"][ids.index(voice["bundled"])]
            elif "ref_wav" in voice:
                kw["reference_wav_path"] = str(_inside(voice["ref_wav"], voices_dir))
            else:
                raise ValueError("voice must be bundled or ref_wav")
            out = _inside(req["out"], out_dir)
            pause = np.zeros(int(model.sample_rate * float(req.get("pause_s", 0.25))), dtype=np.float32)
            parts, t0 = [], time.monotonic()
            sys.stdout = sys.stderr
            try:
                for i, chunk in enumerate(req.get("chunks") or []):
                    audio = model.generate(target_text=chunk, cfg_value=float(req.get("cfg", 2.0)),
                                           retry_badcase=True, **kw)
                    if i:
                        parts.append(pause)
                    parts.append(audio.squeeze().float().cpu().numpy().astype(np.float32))
            finally:
                sys.stdout = real_stdout
            if not parts:
                raise ValueError("no text to speak")
            wav = np.concatenate(parts)
            sf.write(str(out), wav, model.sample_rate, subtype="PCM_16")
            _reply({"ok": True, "audio_s": round(len(wav) / model.sample_rate, 2),
                    "gen_s": round(time.monotonic() - t0, 2), "chunks": len(req.get("chunks") or [])})
        except Exception as exc:  # noqa: BLE001 - 回報給 gateway，行程繼續 / report and keep serving
            _reply({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]})
            last = time.monotonic()


if __name__ == "__main__":
    raise SystemExit(main())

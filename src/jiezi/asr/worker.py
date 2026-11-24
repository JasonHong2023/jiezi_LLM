"""Breeze-ASR-25 辨識行程（add-asr）：在 var/tts/venv 裡執行（已有 torch、transformers），不匯入芥子主程式。

協定：stdin 一行一個 JSON 請求，stdout 一行一個 JSON 回覆（其他輸出走 stderr）。
- {"op": "ping"} → {"ok": true, "ready": true}
- {"op": "transcribe", "path": "<--tmp-dir 底下的音檔>", "prompt": "芥子"}
  → {"ok": true, "text": "…", "segments": [{"start": 0.0, "end": 2.1, "text": "…"}], "audio_s": 12.3, "gen_s": 2.0}
- {"op": "quit"}
只載入 safetensors（不讀 pickle）；閒置超過 --idle 秒自動結束，把 GPU 還回去。
Recognition process for add-asr; JSON lines over stdin/stdout; safetensors only; exits when idle."""

from __future__ import annotations

import argparse
import json
import select
import subprocess
import sys
import time
from pathlib import Path


def _reply(obj: dict) -> None:
    sys.__stdout__.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.__stdout__.flush()


def decode(path: str):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, timeout=1800)
    if raw.returncode != 0:
        raise ValueError(f"cannot decode audio: {raw.stderr.decode(errors='replace')[:200]}")
    return np.frombuffer(raw.stdout, dtype=np.float32).copy()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--tmp-dir", required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--idle", type=float, default=120.0)
    a = ap.parse_args(argv)
    sys.stdout = sys.stderr                     # 套件的 print 不可混進協定 / keep the protocol clean
    import torch
    from transformers import AutomaticSpeechRecognitionPipeline, WhisperForConditionalGeneration, WhisperProcessor

    dtype = torch.float16 if a.device == "cuda" else torch.float32
    proc = WhisperProcessor.from_pretrained(a.model_dir, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(a.model_dir, local_files_only=True, dtype=dtype,
                                                            use_safetensors=True).to(a.device).eval()
    pipe = AutomaticSpeechRecognitionPipeline(model=model, tokenizer=proc.tokenizer,
                                              feature_extractor=proc.feature_extractor, chunk_length_s=30,
                                              device=a.device, dtype=dtype)
    tmp = Path(a.tmp_dir).resolve()
    _reply({"ok": True, "ready": True})
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
            if req.get("op") == "quit":
                return 0
            if req.get("op") == "ping":
                _reply({"ok": True, "ready": True})
                continue
            if req.get("op") != "transcribe":
                raise ValueError(f"unknown op {req.get('op')!r}")
            p = Path(req["path"]).resolve()
            if tmp not in p.parents:
                raise ValueError("path outside the upload folder")
            wav = decode(str(p))
            if not len(wav):
                raise ValueError("no audio")
            kw = {"return_timestamps": True}
            prompt = (req.get("prompt") or "").strip()
            if prompt:   # 專有名詞提示（例如「芥子」），提高同音字正確率 / vocabulary hint for homophones
                kw["generate_kwargs"] = {"prompt_ids": torch.tensor(proc.get_prompt_ids(prompt[:200])).to(a.device)}
            t0 = time.monotonic()
            out = pipe(wav, **kw)
            segs = []
            for c in out.get("chunks") or []:
                st, en = (c.get("timestamp") or (None, None))
                segs.append({"start": st, "end": en, "text": (c.get("text") or "").strip()})
            text = out.get("text") or ""
            if prompt and text.strip().startswith(prompt):
                text = text.strip()[len(prompt):]      # 有些版本會把提示詞一起吐出來 / some versions echo the prompt
            _reply({"ok": True, "text": text.strip(), "segments": segs, "audio_s": round(len(wav) / 16000, 2),
                    "gen_s": round(time.monotonic() - t0, 2)})
        except Exception as exc:  # noqa: BLE001 - 回報給 gateway，行程繼續 / report and keep serving
            _reply({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]})
            last = time.monotonic()


if __name__ == "__main__":
    raise SystemExit(main())

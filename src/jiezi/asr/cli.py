"""`scripts/jiezi asr`（add-asr）：下載權重、檔案轉逐字稿。 / Weights setup and file transcription."""

from __future__ import annotations

import sys
from pathlib import Path

HF_REPO = "MediaTek-Research/Breeze-ASR-25"
HF_REVISION = "cffe7ccb404d025296a00758d0a33468bec3a9d0"
# 只下載 safetensors 與設定檔；repo 裡的 optimizer.bin、random_states_*.pkl（pickle）與 whisper-github/*.pt 不下載
# safetensors and config files only; the pickles and checkpoints in the repo are never downloaded
FILES = {
    "model.safetensors": (3086761032, "c5d952b3bc03ea277209aff0ef5b5c4c055d74449ff794c02d8f4e315fdef6b6"),
    "LICENSE": (12624, "609e2cb599f84aaa41d8ef29d8fdb04d164fab22e8d9292ca34a599d0f56a338"),
    "added_tokens.json": (34604, "9715fd2243b6f06a5858b5e32950d2853f73dd5bc201aafcf76f5082a2d8acd1"),
    "config.json": (2281, "152f13a1b4535d16edd05a9168553a967e2b42d07feee59b136f0ab14e522aab"),
    "generation_config.json": (4289, "8cd24239c76189ae8125d09f92bf883d7d7aa0893039462b0413ee19a088c1cc"),
    "merges.txt": (493869, "2df2990a395e35e8dfbc7511e08c12d56018d8d04691e0133e5d63b21e154dc6"),
    "normalizer.json": (52666, "bf1c507dc8724ca9cf9903640dacfb69dae2f00edee4f21ceba106a7392f26dd"),
    "preprocessor_config.json": (339, "a6a76d28c93edb273669eb9e0b0636a2bddbb1272c3261e47b7ca6dfdbac1b8d"),
    "special_tokens_map.json": (2194, "e67ae3a0aaa99abcd9f187138e12db1f65c16a14761c50ef10eef2c174a7a691"),
    "tokenizer.json": (3930832, "ad9d585ff6f7948ae7687f0fbcccf52c9e0ab8105729e542e47a11e2e5f05071"),
    "tokenizer_config.json": (282733, "4a5b5d589336cefaef5fd27995c030a42d7fab3de5ac19b6c6fa0afbcbcc4309"),
    "vocab.json": (835550, "8f680bba319e01a653d2e8a5dbc17a9157179e0576e6ce74ce0c06356c6e24f9"),
}


def transcribe(path: str, fmt: str, out: str | None, prompt: str | None) -> int:
    import httpx
    from ..cli.client import Connection
    conn = Connection.from_env()
    p = Path(path).expanduser()
    if not p.is_file():
        sys.stderr.write(f"jiezi: no such file: {p}\n")
        return 4
    fields = {"model": "breeze-asr-25", "response_format": fmt}
    if prompt is not None:
        fields["prompt"] = prompt
    try:
        with p.open("rb") as f:
            r = httpx.post(conn.url + "/v1/audio/transcriptions", headers=conn.headers, data=fields,
                           files={"file": (p.name, f)}, timeout=7200)
    except httpx.HTTPError as exc:
        sys.stderr.write(f"jiezi: gateway unreachable: {exc}\n")
        return 2
    if r.status_code != 200:
        sys.stderr.write(f"jiezi: {r.status_code} {r.text[:300]}\n")
        return 3
    if out:
        Path(out).expanduser().write_text(r.text, encoding="utf-8")
        sys.stderr.write(f"jiezi: wrote {out} ({r.headers.get('x-jiezi-audio-seconds')} s of audio)\n")
    else:
        sys.stdout.write(r.json()["text"] + "\n" if fmt == "json" else r.text)
    return 0


def main(args, settings) -> int:
    if args.file == "setup":
        from ..tts.cli import fetch_weights
        print(f"fetching Breeze-ASR-25 into {settings.models_dir / 'breeze-asr-25'} (revision {HF_REVISION[:12]})")
        fetch_weights(settings.models_dir / "breeze-asr-25", print, HF_REPO, HF_REVISION, FILES)
        print("done. The speech environment comes from scripts/jiezi tts setup; enable with JIEZI_ASR=on.")
        return 0
    fmt = "srt" if args.srt else "vtt" if args.vtt else "text" if args.text or not args.json else "json"
    return transcribe(args.file, fmt, args.out, args.prompt)


def add_parser(sub) -> None:
    ap = sub.add_parser("asr", help="speech recognition, Breeze-ASR-25 (add-asr): `asr setup` or `asr <file>`")
    ap.add_argument("file", help="audio or video file to transcribe, or `setup` to download the weights")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--srt", action="store_true", help="subtitles (SubRip)")
    g.add_argument("--vtt", action="store_true", help="subtitles (WebVTT)")
    g.add_argument("--text", action="store_true", help="plain text (default)")
    g.add_argument("--json", action="store_true", help="JSON {text}")
    ap.add_argument("--out", "-o", help="write to this file instead of stdout")
    ap.add_argument("--prompt", help="vocabulary hint, e.g. names (default: 芥子; empty string for none)")

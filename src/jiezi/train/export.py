"""LoRA 合併 → GGUF → 量化，產生可給引擎與 E0 評測的模型檔（使用鎖定版本的 llama.cpp 工具）。
Merge LoRA → GGUF → quantize, producing a model for the engine and evaluation (pinned llama.cpp tools)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from ..errors import JieziError
from .sft import require_stack


def merge(run_dir: Path, log=print) -> Path:
    require_stack()
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    base = AutoModelForCausalLM.from_pretrained(cfg["base_model"], revision=cfg["base_revision"],
                                                torch_dtype=torch.bfloat16)  # 合併用完整精度，不用 4-bit / full precision
    merged = PeftModel.from_pretrained(base, run_dir / "adapter").merge_and_unload()
    out = run_dir / "merged"
    merged.save_pretrained(out)
    AutoTokenizer.from_pretrained(cfg["base_model"], revision=cfg["base_revision"]).save_pretrained(out)
    log(f"merged: {out}")
    return out


def to_gguf(root: Path, run_dir: Path, quant: str = "Q8_0", log=print, run=subprocess.run) -> dict:
    """轉 GGUF（f16）再量化；回傳檔案路徑與 SHA-256。 / Convert to f16 GGUF, quantize, return path and SHA-256."""
    merged = run_dir / "merged"
    if not merged.exists():
        raise JieziError(f"{merged} not found; run the merge step first")
    f16 = run_dir / "model-f16.gguf"
    conv = root / "vendor" / "llama.cpp" / "convert_hf_to_gguf.py"
    p = run([sys.executable, str(conv), str(merged), "--outfile", str(f16), "--outtype", "f16"],
            capture_output=True, text=True)
    if p.returncode != 0:
        raise JieziError(f"convert_hf_to_gguf failed: {p.stderr[-500:]}")
    out = run_dir / f"{run_dir.name}-{quant}.gguf"
    quantize = next((root / b / "bin" / "llama-quantize" for b in ("build-cuda", "build-cpu")
                     if (root / b / "bin" / "llama-quantize").exists()), None)
    if quantize is None:
        raise JieziError("llama-quantize not found; run scripts/bootstrap")
    p = run([str(quantize), str(f16), str(out), quant], capture_output=True, text=True)
    if p.returncode != 0:
        raise JieziError(f"llama-quantize failed: {p.stderr[-500:]}")
    h = hashlib.sha256()
    with out.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    f16.unlink(missing_ok=True)
    log(f"gguf: {out}")
    return {"path": str(out), "sha256": h.hexdigest(), "size": out.stat().st_size, "quant": quant}

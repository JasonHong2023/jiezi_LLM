"""LoRA SFT（規則 R20.2：每輪從凍結核心＋全新 LoRA 開始）。需要 torch、transformers、peft（4-bit 另需
bitsandbytes），都在執行時才載入；沒裝時給出清楚的訊息。
LoRA SFT (R20.2: every round starts from the frozen core with a fresh LoRA). torch, transformers and peft (plus
bitsandbytes for 4-bit) are imported at run time; a clear message is given when they are missing.

只對助手回答計算損失（使用者與系統訊息的 token 標成 -100）。 / Loss on assistant tokens only."""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from ..errors import JieziError
from .config import TrainConfig

IGNORE = -100


def require_stack() -> dict:
    """檢查訓練套件；回傳版本。 / Check the training stack and return versions."""
    missing, versions = [], {}
    for name in ("torch", "transformers", "peft"):
        try:
            versions[name] = __import__(name).__version__
        except ImportError:
            missing.append(name)
    if missing:
        raise JieziError(f"training needs {', '.join(missing)}; install after the user approves (Phase 6), "
                         "then run `scripts/jiezi audit` (R23)")
    return versions


def load_examples(path: Path) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    bad = [r.get("sha256") for r in rows if r.get("training_use") is not True]
    if bad:  # R18.3、R20.3：匯出時已把關，這裡再擋一次 / gated at export; checked again here
        raise JieziError(f"{len(bad)} examples are not marked trainable; re-export the dataset")
    return rows


def encode(example: dict, tokenizer, max_len: int) -> dict | None:
    """chat template 編碼；只有最後一則助手回答算損失。 / Chat-template encoding; loss on the final answer only."""
    msgs = example["messages"]
    prompt_ids = tokenizer.apply_chat_template(msgs[:-1], tokenize=True, add_generation_prompt=True,
                                               enable_thinking=False)
    full_ids = tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=False, enable_thinking=False)
    if len(full_ids) > max_len or full_ids[:len(prompt_ids)] != prompt_ids:
        return None  # 太長或模板不一致就略過 / too long or template mismatch
    labels = [IGNORE] * len(prompt_ids) + full_ids[len(prompt_ids):]
    return {"input_ids": full_ids, "labels": labels}


def train(cfg: TrainConfig, root: Path, log=print) -> Path:
    require_stack()
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    out = root / "var" / "train" / cfg.run_name
    if out.exists():
        raise JieziError(f"{out} exists; every round needs a new run name (R20.2)")
    cfg.save(out / "config.json")
    random.seed(cfg.seed)
    torch.manual_seed(cfg.seed)
    tok = AutoTokenizer.from_pretrained(cfg.base_model, revision=cfg.base_revision)
    kw = {"revision": cfg.base_revision, "torch_dtype": torch.bfloat16}
    if cfg.load_in_4bit:
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(cfg.base_model, **kw).to("cuda")
    if cfg.gradient_checkpointing:
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    model = get_peft_model(model, LoraConfig(r=cfg.lora_r, lora_alpha=cfg.lora_alpha, lora_dropout=cfg.lora_dropout,
                                             target_modules=list(cfg.target_modules), task_type="CAUSAL_LM"))
    data = [e for e in (encode(x, tok, cfg.max_len) for x in load_examples(root / cfg.dataset)) if e]
    log(f"examples: {len(data)}; trainable params: {sum(p.numel() for p in model.parameters() if p.requires_grad)}")
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=cfg.learning_rate)
    steps = math.ceil(len(data) * cfg.epochs / (cfg.batch_size * cfg.grad_accum))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 20) * max(0.0, 1 - s / steps))
    model.train()
    step, t0, history = 0, time.monotonic(), []
    for epoch in range(cfg.epochs):
        random.shuffle(data)
        for i, ex in enumerate(data, 1):
            ids = torch.tensor([ex["input_ids"]], device="cuda")
            labels = torch.tensor([ex["labels"]], device="cuda")
            loss = model(input_ids=ids, labels=labels).loss / cfg.grad_accum
            loss.backward()
            if i % cfg.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad()
                step += 1
                history.append({"step": step, "loss": round(loss.item() * cfg.grad_accum, 4)})
                if step % 10 == 0:
                    log(f"  epoch {epoch + 1} step {step}/{steps} loss {history[-1]['loss']} "
                        f"({time.monotonic() - t0:.0f}s, peak {torch.cuda.max_memory_allocated() / 2**20:.0f} MiB)")
    model.save_pretrained(out / "adapter")
    (out / "history.json").write_text(json.dumps({"steps": history, "seconds": round(time.monotonic() - t0),
                                                  "peak_vram_mib": round(torch.cuda.max_memory_allocated() / 2**20)},
                                                 indent=1), encoding="utf-8")
    return out

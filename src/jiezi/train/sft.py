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
from dataclasses import asdict
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


def _template_ready(m: dict) -> dict:
    """OpenAI 格式的工具呼叫參數是 JSON 字串；Qwen3.5 的範本要物件（2026-11-17 冒煙測試）。
    OpenAI tool-call arguments are JSON strings; the Qwen3.5 template iterates them as a mapping."""
    if not m.get("tool_calls"):
        return m
    calls = []
    for tc in m["tool_calls"]:
        fn = dict(tc.get("function") or {})
        if isinstance(fn.get("arguments"), str):
            try:
                fn["arguments"] = json.loads(fn["arguments"] or "{}")
            except ValueError:
                fn["arguments"] = {}
        calls.append({**tc, "function": fn})
    return {**m, "tool_calls": calls}


def encode(example: dict, tokenizer, max_len: int) -> dict | None:
    """chat template 編碼；只有最後一則助手回答算損失。 / Chat-template encoding; loss on the final answer only."""
    msgs = [_template_ready(m) for m in example["messages"]]

    def ids(x):  # transformers 5 預設回傳 dict / transformers 5 returns a dict by default
        x = x.get("input_ids", x) if hasattr(x, "get") else x
        return list(x[0]) if x and isinstance(x[0], (list, tuple)) else list(x)
    prompt_ids = ids(tokenizer.apply_chat_template(msgs[:-1], tokenize=True, add_generation_prompt=True,
                                                   enable_thinking=False))
    full_ids = ids(tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=False,
                                                 enable_thinking=False))
    if len(full_ids) > max_len or full_ids[:len(prompt_ids)] != prompt_ids:
        return None  # 太長或模板不一致就略過 / too long or template mismatch
    labels = [IGNORE] * len(prompt_ids) + full_ids[len(prompt_ids):]
    return {"input_ids": full_ids, "labels": labels}


def answer_loss(model, ids, ex: dict):
    """只算回答部分的損失，而且只產生回答位置的 logits。Qwen3.5 的詞表有 24.8 萬個，整段 logits 會吃掉 1 GB 以上的
    顯示記憶體，6 GB 顯卡放不下（2026-11-17 冒煙測試：峰值 6.5 GB，溢出到系統記憶體、每筆 13 秒）。
    Loss on the answer only, computing logits for answer positions only: full-sequence logits over Qwen3.5's 248k-token
    vocabulary overflowed a 6 GB card in the smoke test."""
    import torch
    labels = ex["labels"]
    first = next(i for i, x in enumerate(labels) if x != IGNORE)   # 回答開始的位置 / where the answer starts
    keep = len(labels) - first + 1                                  # 預測回答需要的最後幾個位置 / positions needed
    logits = model(input_ids=ids, logits_to_keep=keep).logits[0, :-1].float()
    target = torch.tensor(labels[first:], device=logits.device)
    return torch.nn.functional.cross_entropy(logits, target, ignore_index=IGNORE)


def _stop_time(stop_at: str | None, now=None):
    """「06:30」→ 下一個 06:30 的時間點；沒給就 None。 / Next occurrence of HH:MM, or None."""
    import datetime as dt
    if not stop_at:
        return None
    now = now or dt.datetime.now()
    h, m = (int(x) for x in stop_at.split(":"))
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > now else t + dt.timedelta(days=1)


def _say(msg: str) -> None:
    print(msg, flush=True)      # 夜間腳本把輸出導到檔案時也要即時寫出 / visible immediately when redirected to a file


def train(cfg: TrainConfig, root: Path, log=_say) -> tuple[Path, str]:
    """回傳 (輸出目錄, "done" 或 "paused")。可以分好幾晚跑完：每次到 `extra.stop_at`（例如 "06:30"）或跑滿
    `extra.session_examples` 筆就在累積步的邊界存檢查點後結束，下次用同一個設定執行就從檢查點接著跑
    （使用者 2026-11-17：6 GB 顯卡一輪約 13.5 小時，拆成多晚）。
    Return (run dir, "done" or "paused"). A round can span several nights: at `extra.stop_at` or after
    `extra.session_examples` examples it checkpoints on an accumulation boundary; running the same config resumes."""
    require_stack()
    import datetime as dt
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    out = root / "var" / "train" / cfg.run_name
    ckpt = out / "checkpoint"
    resume = (ckpt / "state.json").exists()
    if (out / "adapter").exists():
        raise JieziError(f"{out} is finished; every round needs a new run name (R20.2)")
    if out.exists() and not resume:
        raise JieziError(f"{out} exists without a checkpoint; every round needs a new run name (R20.2)")
    if resume:
        saved = json.loads((out / "config.json").read_text(encoding="utf-8"))
        now = json.loads(json.dumps(asdict(cfg)))  # tuple → list，和存檔的格式一致 / same shape as the saved file
        same = {k: v for k, v in saved.items() if k != "extra"} == {k: v for k, v in now.items() if k != "extra"}
        if not same:
            raise JieziError(f"{out}: the config changed since the checkpoint; resume needs the same settings")
    else:
        cfg.save(out / "config.json")
    extra = cfg.extra or {}
    stop = _stop_time(extra.get("stop_at"))
    session_cap = int(extra.get("session_examples") or 0)
    torch.manual_seed(cfg.seed)
    tok = AutoTokenizer.from_pretrained(cfg.base_model, revision=cfg.base_revision)
    kw = {"revision": cfg.base_revision, "torch_dtype": torch.bfloat16}
    if cfg.load_in_4bit:
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=torch.bfloat16)
    if cfg.load_in_4bit:
        # 4-bit 模型不能 .to()，要在載入時指定裝置（2026-11-17 實裝 transformers 5.23 後修正）
        # A 4-bit model cannot be moved with .to(); place it at load time
        # 不用 peft 的 prepare_model_for_kbit_training：它把所有非 4-bit 參數轉成 fp32，Qwen3.5 的詞嵌入
        # （248,320×2,560）會從 1.2 GB 變 2.4 GB，6 GB 顯卡放不下（2026-11-17 冒煙測試）。只凍結基底、開梯度檢查點。
        # Not peft's prepare_model_for_kbit_training: it upcasts every non-4-bit parameter to fp32, doubling
        # Qwen3.5's 248k-word embedding to 2.4 GB. Freeze the base and enable checkpointing only.
        model = AutoModelForCausalLM.from_pretrained(cfg.base_model, device_map={"": 0}, **kw)
        for prm in model.parameters():
            prm.requires_grad = False
        if cfg.gradient_checkpointing:
            model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
            model.enable_input_require_grads()
    else:
        model = AutoModelForCausalLM.from_pretrained(cfg.base_model, **kw).to("cuda")
        if cfg.gradient_checkpointing:
            model.gradient_checkpointing_enable()
            model.enable_input_require_grads()
    if resume:
        model = PeftModel.from_pretrained(model, ckpt / "adapter", is_trainable=True)
    else:
        model = get_peft_model(model, LoraConfig(r=cfg.lora_r, lora_alpha=cfg.lora_alpha,
                                                 lora_dropout=cfg.lora_dropout,
                                                 target_modules=list(cfg.target_modules), task_type="CAUSAL_LM"))
    raw = load_examples(root / cfg.dataset)
    data = [e for e in (encode(x, tok, cfg.max_len) for x in raw) if e]
    dropped = len(raw) - len(data)       # 超過 max_len 的整筆排除、不截斷 / over-long examples dropped, not truncated
    log(f"examples: {len(data)} (dropped {dropped} over {cfg.max_len} tokens); "
        f"trainable params: {sum(p.numel() for p in model.parameters() if p.requires_grad)}")
    load_peak = torch.cuda.max_memory_allocated() / 2**20
    torch.cuda.reset_peak_memory_stats()  # 載入時的峰值和訓練時分開記 / loading and training peaks recorded apart
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=cfg.learning_rate)
    per_epoch = len(data) // cfg.grad_accum * cfg.grad_accum   # 只用完整的累積步 / whole accumulation steps only
    steps = math.ceil(per_epoch * cfg.epochs / (cfg.batch_size * cfg.grad_accum))
    # 冒煙測試用：只跑幾步就停（extra.max_steps）/ smoke runs stop after a few steps
    max_steps = int(extra.get("max_steps") or 0) or steps
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / 20) * max(0.0, 1 - s / steps))
    state = {"epoch": 0, "index": 0, "step": 0, "history": [], "seconds": 0, "sessions": 0}
    if resume:
        state = json.loads((ckpt / "state.json").read_text(encoding="utf-8"))
        opt.load_state_dict(torch.load(ckpt / "optimizer.pt", weights_only=True))
        sched.load_state_dict(torch.load(ckpt / "scheduler.pt", weights_only=True))
        log(f"resuming at epoch {state['epoch'] + 1}, example {state['index']}, step {state['step']}/{steps}")
    state["sessions"] += 1
    model.train()
    t0, seen = time.monotonic(), 0
    paused = False
    for epoch in range(state["epoch"], cfg.epochs):
        order = list(range(len(data)))
        random.Random(cfg.seed + epoch).shuffle(order)          # 每輪順序固定，接續時才對得上 / reproducible order
        start = state["index"] if epoch == state["epoch"] else 0
        for i in range(start, per_epoch):
            ex = data[order[i]]
            ids = torch.tensor([ex["input_ids"]], device="cuda")
            loss = answer_loss(model, ids, ex) / cfg.grad_accum
            loss.backward()
            seen += 1
            if (i + 1) % cfg.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad()
                state["step"] += 1
                state["history"].append({"step": state["step"], "loss": round(loss.item() * cfg.grad_accum, 4)})
                state["epoch"], state["index"] = epoch, i + 1
                if state["step"] % 10 == 0 or state["step"] <= 3:
                    log(f"  epoch {epoch + 1} step {state['step']}/{steps} loss {state['history'][-1]['loss']} "
                        f"({time.monotonic() - t0:.0f}s, peak {torch.cuda.max_memory_allocated() / 2**20:.0f} MiB)")
                if state["step"] >= max_steps:
                    break
                if (stop and dt.datetime.now() >= stop) or (session_cap and seen >= session_cap):
                    paused = True
                    break
        if paused or state["step"] >= max_steps:
            break
        state["epoch"], state["index"] = epoch + 1, 0
    state["seconds"] += round(time.monotonic() - t0)
    record = {"steps": state["history"], "seconds": state["seconds"], "sessions": state["sessions"],
              "peak_vram_mib": round(torch.cuda.max_memory_allocated() / 2**20), "load_peak_vram_mib": round(load_peak),
              "examples_seen": state["step"] * cfg.grad_accum, "total_steps": steps, "dropped_over_max_len": dropped}
    ceiling = extra.get("vram_ceiling_mib")
    if ceiling:
        record["vram_ceiling_mib"] = ceiling
        record["over_ceiling"] = record["peak_vram_mib"] > ceiling
        if record["over_ceiling"]:
            log(f"WARNING: training peak {record['peak_vram_mib']} MiB is over the {ceiling} MiB ceiling; "
                f"lower max_len next round")
    if paused:
        ckpt.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(ckpt / "adapter")
        torch.save(opt.state_dict(), ckpt / "optimizer.pt")
        torch.save(sched.state_dict(), ckpt / "scheduler.pt")
        (ckpt / "state.json").write_text(json.dumps(state, indent=1), encoding="utf-8")
        (out / "progress.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
        log(f"paused at step {state['step']}/{steps}; run the same config again to resume")
        return out, "paused"
    model.save_pretrained(out / "adapter")
    (out / "history.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    if ckpt.exists():
        import shutil
        shutil.rmtree(ckpt)
    return out, "done"

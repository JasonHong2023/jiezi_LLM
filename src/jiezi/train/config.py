"""訓練設定與顯示記憶體估算。 / Training settings and VRAM estimate."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

# LoRA 目標層（Qwen3／Qwen3.5 的注意力與 MLP 投影）/ LoRA targets (attention and MLP projections)
QWEN_TARGETS = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")


@dataclass
class TrainConfig:
    base_model: str                    # HF repo，例如 Qwen/Qwen3.5-0.8B（G1 決定）/ decided at G1
    base_revision: str                 # 鎖定 commit（R18.3）/ pinned commit
    dataset: str                       # var/training/sft-*.jsonl
    run_name: str
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: tuple = QWEN_TARGETS
    learning_rate: float = 2e-4
    epochs: int = 2
    max_len: int = 2048
    batch_size: int = 1
    grad_accum: int = 16
    load_in_4bit: bool = False         # 2B 以上在 6 GB 顯卡上需要（QLoRA）/ needed for ≥2B on a 6 GB card
    gradient_checkpointing: bool = True
    seed: int = 20261117
    extra: dict = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")


# Qwen3.5 的形狀：詞表 248,320；隱藏層寬度 4B 是 2,560、32 層（讀自官方 config.json）；其他大小為 [估]
# Qwen3.5 shapes: 4B read from the official config.json; the other sizes are estimates
QWEN35_VOCAB = 248_320
QWEN35_SHAPE = {0.8: (1024, 28), 2: (2048, 28), 4: (2560, 32), 9: (4096, 32)}   # 參數量 → (hidden, layers)


def estimate_vram_mib(params_b: float, load_in_4bit: bool, max_len: int = 2048, layers: int | None = None,
                      hidden: int | None = None, lora_r: int = 16, vocab: int = QWEN35_VOCAB) -> dict:
    """粗估 LoRA 訓練的顯示記憶體 [估]。詞嵌入不能 4-bit，以 bf16 另外計算（2026-11-17 更正：原本漏算，4B 估 3.2 GB，
    實測峰值 5.1 GB）。 / A rough estimate [est.]. The embedding cannot be 4-bit and is counted in bf16 (corrected
    2026-11-17: it was missing; 4B was estimated at 3.2 GB but peaked at 5.1 GB)."""
    near = min(QWEN35_SHAPE, key=lambda k: abs(k - params_b))
    hidden = hidden or QWEN35_SHAPE[near][0]
    layers = layers or QWEN35_SHAPE[near][1]
    embed_params = vocab * hidden
    body = max(0.0, params_b * 1e9 - embed_params)
    weights = body * (0.55 if load_in_4bit else 2) / 2**20                     # 4-bit 約 0.55 byte/參數 / about
    embedding = embed_params * 2 / 2**20                                        # bf16，共用給輸出層 / tied, bf16
    lora_params = layers * 7 * 2 * hidden * lora_r                             # 每層 7 個投影、A 與 B / per layer
    lora = lora_params * (2 + 4 + 8) / 2**20                                    # 權重 bf16 + 梯度 fp32 + Adam fp32
    activations = layers * max_len * hidden * 2 * 4 / 2**20                    # 梯度檢查點下的粗估 / with checkpointing
    total = weights + embedding + lora + activations + 600                     # CUDA context 等 / context etc.
    return {"weights_mib": round(weights), "embedding_mib": round(embedding), "lora_mib": round(lora),
            "activations_mib": round(activations), "total_mib": round(total)}


def fits(params_b: float, budget_mib: int, **kw) -> dict:
    """在預算內能不能直接訓練；不行時看 4-bit。 / Whether bf16 fits the budget, else whether 4-bit does."""
    bf16 = estimate_vram_mib(params_b, False, **kw)
    q4 = estimate_vram_mib(params_b, True, **kw)
    return {"bf16": bf16["total_mib"] <= budget_mib, "4bit": q4["total_mib"] <= budget_mib,
            "bf16_mib": bf16["total_mib"], "4bit_mib": q4["total_mib"], "budget_mib": budget_mib}

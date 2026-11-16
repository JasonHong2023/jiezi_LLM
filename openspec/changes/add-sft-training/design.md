## Decisions

### D1 — 每輪從凍結核心開始（R20.2）/ Fresh LoRA every round
`train` 拒絕重用已存在的 run 名稱；每輪都從 HF 基底（鎖定 revision）＋新的 LoRA 開始，最多 3 輪後重新評估。
Each round starts from the pinned base with a new LoRA; run names cannot be reused.

### D2 — 只學回答 / Loss on answers only
用模型自己的 chat template 編碼，提問部分的 label 設 -100；模板前綴對不上或超過長度的樣本略過。資料載入時再檢查一次 `training_use: true`（匯出時已把關）。
Prompt tokens are masked; mismatched or overlong examples are skipped; trainability is rechecked on load.

### D3 — 預設超參數 / Defaults
r=16、alpha=32、dropout 0.05、目標為 7 個投影層、lr 2e-4（前 20 步暖身後線性下降）、2 epochs、max_len 2048、batch 1 × 累積 16、梯度檢查點。依 G1 的核心大小選 bf16 或 4-bit（NF4）。
Standard LoRA defaults; bf16 or NF4 by core size.

### D4 — 匯出 / Export
合併時用完整精度載入基底（不用 4-bit），存 HF 格式，再用 `vendor/llama.cpp/convert_hf_to_gguf.py`（鎖定 commit）轉 f16 GGUF，最後用 `llama-quantize` 量化並記錄 SHA-256，可直接放進 E0 矩陣對照。
Merge at full precision, convert with the pinned llama.cpp tools, quantize and hash.

### D5 — 回歸關卡 / Regression gate
以 E0 格式的評測目錄比較：目標任務必須提升；其他任務退步 ≤ 1 分；平均回答 token 增幅 < 20%；延遲不超過 +5%（量測雜訊）；轉交比例上升 > 1 個百分點不算進步（R20.6）；缺分數時判不過，不猜測。
Compare E0-style runs with the R20.1/R20.6 rules; missing scores fail.

## Risks / Trade-offs
- 範本教材（法規、Taiwan.md）可能讓回答變長或風格改變 → 由長度與其他任務退步規則把關。/ Template material may lengthen answers → gated.
- 顯示記憶體估算是粗估 → 第一次訓練記錄實際峰值（history.json）。/ The estimate is rough → peak VRAM is recorded.

## Why

開發計畫 Phase 6.2：用驗證過的教材（add-training-data 匯出的 3,500 筆）對核心模型做 LoRA SFT，並以 R20 回歸關卡決定保留或回滾。使用者 2026-11-16 決定：先寫訓練程式（不安裝、不執行），E0 結束、G1 選定核心後再安裝 PyTorch 並訓練。
Phase 6.2 LoRA SFT on verified material, kept only if it passes the R20 gate. The user chose to write the code now and install and train after G1.

## What Changes

- `src/jiezi/train/`：`config`（設定、顯示記憶體估算）、`gate`（R20.1、R20.6 回歸關卡）、`sft`（LoRA SFT，只對回答算損失，每輪全新 LoRA）、`export`（合併 → GGUF → 量化，使用鎖定版本的 llama.cpp 工具）。
  Config, regression gate, LoRA SFT and GGUF export.
- `scripts/jiezi train plan|sft|export|gate`。torch、transformers、peft（4-bit 另需 bitsandbytes）在執行時才載入；沒裝時明確提示「使用者同意後安裝，並跑 `scripts/jiezi audit`」。
  Heavy dependencies load at run time with a clear message when missing.

## Non-Goals

- 安裝訓練套件、實際訓練（等 G1 與使用者執行安裝）。/ Installing or training now.
- 偏好學習（6.3）、驗證器訓練（6.1，待 toolcheck 結果）。/ 6.3 and 6.1.

## Capabilities

### New Capabilities

- `training`：LoRA 訓練、匯出與回歸關卡。/ LoRA training, export and the regression gate.

### Modified Capabilities

（無）/ (None)

## Impact

- 6 GB 顯卡（預算約 5.1 GB）[估]：0.8B 與 2B 可用 bf16 LoRA，4B 需 4-bit，9B 不可行（`scripts/jiezi train plan`）。

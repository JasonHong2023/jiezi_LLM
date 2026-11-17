> **狀態 / Status**：提案，**尚未實作**，待使用者審閱（R4）。Proposal only, not implemented; awaiting review.

## Why

第一輪 QLoRA（`qwen3.5-4b-r1`，2026-11-18 夜間）回歸關卡不通過、已回滾 [實測]：

| 任務 | 訓練前 | 訓練後 |
|---|---|---|
| qa（目標） | 64.0 | 61.3 |
| tool | 60 | 56（無法解析 9→15） |
| code | 66 | 54 |
| summary（評審） | — | +9.2 |

推測原因（未驗證）：資料 3,500 筆中 98% 是法規、台灣條目與課綱（moj-laws 1,929、taiwan-md 1,071、tw-taxonomy 407），沒有程式與工具題，模型往「背條文」偏、忘了原本的能力；lr 2e-4 對 4B 偏高。另外訓練峰值 6,367 MiB 略超過顯示卡 6,141 MiB（少量溢出），違反「留資源給系統」的規則。
Round 1 failed the gate and was rolled back. Likely cause: a data mix with no code/tool data plus a high learning rate; peak VRAM also slightly exceeded the card.

## What Changes

- **資料混入「自我複習」（replay）**：從凍結核心自己對一般／程式／工具題的回答（`local-model-output`，Qwen Apache-2.0；只收通過驗證器的，R20.3）取一定比例混入，讓模型練新知識時不忘舊能力。題目來源不得與評測題重疊（沿用 `overlaps_evaluation` 排除）。
  Mix in self-distilled replay from the frozen core (verified only, no eval overlap).
- **降低學習率與資料量**：lr 2e-4 → 5e-5（建議），法規類每源上限 2,000 → 800，讓一輪更短、更溫和。
  Lower lr and cap per-source counts.
- **顯示記憶體上限**：`max_len` 1024 → 768，或超過長度的樣本直接排除；目標峰值 ≤ 5,500 MiB（量測，R17）。
  Keep peak VRAM ≤ 5.5 GB.
- **第二輪設定** `src/jiezi/train/configs/qwen3.5-4b-r2.json`，夜間排程改跑 r2（訓練→匯出→E0 條件評測→驗證→關卡，和第一輪同流程）。
- **關卡不改**（R20）：qa 要提升、其他退步 ≤ 1 分。
- 第一輪的產物保留在 `var/train/qwen3.5-4b-r1/` 當對照，不登記 manifest。

## Non-Goals

- 換基底模型、全參數微調。/ Changing base, full fine-tuning.
- 用 Claude 的回答當訓練資料（使用者規定：Claude 的回答不是訓練資料）。

## Capabilities

### Modified Capabilities

- `training`：訓練資料配比與顯示記憶體上限。/ Data mix and VRAM ceiling.

## Impact

- 要先在本機產生 replay 資料：核心對 N 題作答再過驗證器，約 1–2 小時 GPU [估]，排在夜間。
- 一輪訓練約 1–1.5 小時 [估]，夜間可跑完。

## Open Questions

- **OQ1 replay 題目來源**：(a) 只用已有的本機資料（對話軌跡、知識庫）出題；(b) 另外下載授權允許的程式／工具題訓練集（例如 MBPP 的 train 部分，CC BY 4.0；與評測用的 test 不重疊）。建議 **(b)**，因為退最多的是程式題；下載前會把授權列給你確認。
- **OQ2 混入比例**：建議 replay 佔 30%。
- **OQ3 學習率**：建議 5e-5（保守）；或 1e-4。

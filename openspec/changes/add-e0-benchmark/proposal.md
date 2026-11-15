## Why

開發計畫的關卡 G1 要回答：「核心模型用哪一種壓縮形式？」答案只能靠在本機、同一份 R0 題庫、同樣的檔案大小下實測。`add-eval-harness` 與 `add-verifiers` 已經能對單一模型評分，但還沒有「多模型對照」：候選清單、能否放進本機資源預算、擺在 GPU 還是 CPU、每個模型的冒煙檢查，以及分數對檔案大小的帕累托報表。
Gate G1 of the development plan asks which compression form the core model should use. Only local measurement on the same R0 bank at equal file size can answer it. `add-eval-harness` and `add-verifiers` score one model; there is no multi-model comparison yet: a candidate list, a fit check against local budgets, GPU-or-CPU placement, a per-model smoke check, and a Pareto report of score versus file size.

2026-11-15 重新查證後，候選清單和開發計畫原本寫的不同（細節見 design D1）：
Re-checking on 2026-11-15 changed the candidate list from the plan (details in design D1):
- Qwen3.5（0.8B / 2B / 4B / 9B）已發布；PrismML 的 Ternary-Bonsai-2 是同一批 Qwen3.5 的三值版本，**可以做同一個基底的壓縮對照**。
  Qwen3.5 (0.8B / 2B / 4B / 9B) is out, and PrismML's Ternary-Bonsai-2 are ternary versions of the same Qwen3.5 models, **so compression can be compared on the same base**.
- 1-bit 的 Bonsai（`Q1_0`）已進入主線 llama.cpp，Bonsai-27B 只有 3.5 GiB。
  1-bit Bonsai (`Q1_0`) is in mainline llama.cpp; Bonsai-27B is only 3.5 GiB.
- 主線的 `Q2_0` 是每 64 個權重一組，第一代 Ternary-Bonsai 預設的 g128 檔案在主線上不適用。
  Mainline `Q2_0` uses groups of 64; the default g128 files of first-generation Ternary-Bonsai do not fit mainline.
- 主線的 `bitnet` 架構使用 SiLU，但 BitNet b1.58 2B4T 官方設定是 `relu2`，直接跑分數會失真。
  Mainline's `bitnet` architecture uses SiLU, but BitNet b1.58 2B4T's official config is `relu2`, so scores would be distorted as is.
- Maple 20B-A1B 沒有計畫中所說約 5.3 GB 的檔案，最小的有 11 GiB，超過 RAM 預算。
  Maple 20B-A1B has no ~5.3 GB file as the plan assumed; the smallest is 11 GiB, over the RAM budget.

## What Changes

- 新增 E0 候選矩陣檔 `eval/e0/matrix.toml`：每列指向模型清單中的一個模型，標明分組（三值、1-bit、int8、int4、int2）、基底模型、預設擺放位置。
  Add the E0 matrix `eval/e0/matrix.toml`: each row points to a manifest model and names its group (ternary, 1-bit, int8, int4, int2), base model and default placement.
- 模型清單 `models/manifest.toml` 加入候選模型（鎖定 repo commit、SHA-256、授權欄位）。下載屬長時間工作，只在夜間執行。
  Add the candidates to `models/manifest.toml` (pinned repo commit, SHA-256, license fields). Downloading is a long job and runs only at night.
- 新增 `scripts/eval e0`：
  Add `scripts/eval e0`:
  - `plan`：依當下的資源預算，判斷每個模型能否放進 GPU 或 CPU，列出要跑的組合和預估時間（秒級，任何時間可跑）。
    `plan`: checks each model against the current budgets for GPU or CPU, and lists the runs and estimated time (second-scale, any time).
  - `smoke`：每個模型先跑固定的 5 題冒煙檢查：能載入、思考模式確實關閉、回答格式可解析。沒通過的模型不跑完整評測，並記下原因。
    `smoke`: each model first runs a fixed 5-item smoke check (loads, thinking really off, answers parse); a model that fails is excluded from the full run with the reason recorded.
  - `run`：依矩陣逐一呼叫既有的 `scripts/eval run` 與 `verify`，可中斷、可續跑，跨多個夜晚。
    `run`: calls the existing `scripts/eval run` and `verify` for each row; interruptible and resumable across several nights.
  - `report`：兩張帕累托圖（知識題分數對檔案大小、推理 / 工具題分數對檔案大小），加上 t/s、峰值 RAM / VRAM，以及同基底對照表。
    `report`: two Pareto charts (knowledge score vs file size, reasoning / tool score vs file size) with t/s and peak RAM / VRAM, plus a same-base comparison table.
- 取樣設定（N=8）只對貪婪解碼排名前 3 的模型跑推理 / 工具題。報表分開列出 pass@1、多數決，以及需要標準答案的 pass@8（只當上限參考）。
  The sampled setting (N=8) runs on the reasoning / tool items for the top 3 models under greedy decoding only; the report lists pass@1, majority vote, and pass@8 (needs the ground truth, so an upper bound only) separately.

## Non-Goals

- 自行三值化或 QAT（Phase 3）；IntelLabsChina CAT-Q 目前沒有 GGUF，留到 Phase 3A。
  Our own ternarization or QAT (Phase 3); IntelLabsChina CAT-Q has no GGUF yet and is left to Phase 3A.
- PrismML 分支版 llama.cpp 專用的格式（`PQ2_0`、`PTQ1_0`）：只用主線能跑的檔案，不引入第二套推論引擎。
  Formats only the PrismML llama.cpp fork runs (`PQ2_0`, `PTQ1_0`): mainline-runnable files only, no second inference engine.
- 視覺能力（mmproj）、MTP / 推測解碼：之後的 Phase 4 calibrator。
  Vision (mmproj), MTP / speculative decoding: later, the Phase 4 calibrator.
- 選出核心本身：本變更只產生 G1 需要的數據；選擇由使用者依 G1 規則決定。
  Choosing the core: this change only produces the data G1 needs; the user decides by the G1 rule.

## Capabilities

### New Capabilities

- `e0-benchmark`：候選矩陣、資源適配與擺放、冒煙檢查、跨夜可續跑的多模型評測、帕累托報表。
  `e0-benchmark`: candidate matrix, budget fit and placement, smoke check, resumable multi-night multi-model runs, Pareto report.

### Modified Capabilities

（無；沿用 `eval` 與 `verifiers` 的既有行為。）
(None; existing `eval` and `verifiers` behavior is reused.)

## Impact

- 新檔案：`eval/e0/matrix.toml`、`src/jiezi/eval/e0.py`、`tests/test_eval_e0.py`；`scripts/eval` 增加 `e0` 子指令；`models/manifest.toml` 增加約 17 個模型。
  New files: `eval/e0/matrix.toml`, `src/jiezi/eval/e0.py`, `tests/test_eval_e0.py`; `scripts/eval` gains `e0`; about 17 models are added to `models/manifest.toml`.
- 下載約 34 GiB（硬碟可用 706 GB），只在夜間進行。
  About 34 GiB of downloads (706 GB free on disk), at night only.
- 預估約 3 個夜晚跑完貪婪解碼，另需 2～3 個夜晚跑取樣設定（design D6）。
  About 3 nights for greedy decoding plus 2–3 nights for the sampled setting (design D6).
- 圖表直接輸出 SVG，不新增繪圖套件（design D7）。
  Charts are written as SVG directly; no plotting package is added (design D7).

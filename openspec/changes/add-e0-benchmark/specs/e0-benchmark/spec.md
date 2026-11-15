## ADDED Requirements

### Requirement: Candidate Matrix

系統 SHALL 以版本控管的 `eval/e0/matrix.toml` 定義 E0 候選。每一列 SHALL 指向 `models/manifest.toml` 中的一個模型，並標明分組、基底模型與預設擺放位置。清單中的模型 SHALL 有鎖定的 repo commit、SHA-256 和授權欄位；缺任何一項就 SHALL 拒絕執行。
The system SHALL define E0 candidates in a versioned `eval/e0/matrix.toml`. Each row SHALL point to a model in `models/manifest.toml` and name its group, base model and default placement. Listed models SHALL have a pinned repo commit, SHA-256 and license fields; if any is missing, the system SHALL refuse to run.

#### Scenario: 缺少授權欄位 / Missing license fields

- **WHEN** 矩陣中某一列的模型在清單中沒有授權欄位
  A matrix row's model has no license fields in the manifest
- **THEN** `scripts/eval e0` 停止並列出該模型，不下載也不執行
  `scripts/eval e0` stops and names the model, without downloading or running anything

### Requirement: Budget Fit and Placement

系統 SHALL 在每次載入模型前重新計算資源預算。模型檔加上 KV 快取估算值不超過 VRAM 可用量，而且量化型別有 CUDA kernel 時，SHALL 整個放在 GPU；否則 SHALL 只用 CPU。系統 SHALL NOT 做部分卸載。超過 RAM 可用量的模型 SHALL 記為 `excluded_budget` 並略過。實際擺放與預算數字 SHALL 記入執行條件。
The system SHALL recompute budgets before every model load. When the model file plus the estimated KV cache fits usable VRAM and the quant type has CUDA kernels, the whole model SHALL go on the GPU; otherwise it SHALL use the CPU only. The system SHALL NOT partially offload. A model over usable RAM SHALL be recorded as `excluded_budget` and skipped. The actual placement and budget figures SHALL be recorded in the run conditions.

#### Scenario: VRAM 暫時不足 / VRAM temporarily short

- **WHEN** 預設擺放是 GPU，但載入前的 VRAM 可用量放不下
  The default placement is GPU but usable VRAM at load time is too small
- **THEN** 該模型改用 CPU 執行，條件中記錄原本的擺放、實際擺放與當時的預算
  The model runs on the CPU, and the conditions record the intended placement, actual placement and the budgets at the time

### Requirement: Smoke Check

每個模型在完整評測前 SHALL 先通過固定 5 題的冒煙檢查：能載入、回答不是空的、回答中沒有思考內容、至少 3 題可以解析。沒有通過的模型 SHALL 記為 `excluded_smoke` 並附上原因，SHALL NOT 進行完整評測。
Before a full run, each model SHALL pass a fixed 5-item smoke check: it loads, answers are not empty, answers contain no thinking content, and at least 3 answers parse. A model that fails SHALL be recorded as `excluded_smoke` with the reason and SHALL NOT get a full run.

#### Scenario: 思考內容外洩 / Thinking leaks

- **WHEN** 關閉思考後，模型的回答仍包含 `<think>`
  With thinking off, a model's answer still contains `<think>`
- **THEN** 該模型記為 `excluded_smoke`，原因寫明思考模式沒有關閉，報表列在排除清單
  The model is recorded as `excluded_smoke` with the reason that thinking was not disabled, and the report lists it as excluded

### Requirement: Resumable Multi-Night Runs

`scripts/eval e0 run` SHALL 依矩陣順序執行，記錄每一列的狀態，只在夜間時段內執行（R18.2a），時段結束時在題與題之間停止，下一次從原處續跑。每一列的執行代號 SHALL 固定，重跑 SHALL NOT 產生重複結果。
`scripts/eval e0 run` SHALL follow the matrix order, track each row's state, run only inside the night window (R18.2a), stop between items when the window ends, and resume where it stopped. Each row's run ID SHALL be fixed, and reruns SHALL NOT duplicate results.

#### Scenario: 夜間時段結束 / Night window ends

- **WHEN** 執行到一半，夜間時段結束
  The night window ends mid-run
- **THEN** 目前這一題完成後停止，狀態檔記錄進度；下一晚的排程從下一題繼續
  It stops after the current item, the state file records progress, and the next night's schedule continues from the next item

### Requirement: Pareto Report

`scripts/eval e0 report` SHALL 產生報表與兩張 SVG 圖（知識題分數對檔案大小、推理 / 工具題分數對檔案大小），標出帕累托前緣，並列出 t/s、平均延遲、峰值 RAM / VRAM、擺放位置、95% 信賴區間、同基底對照表，以及被排除的模型與原因。只有評審實際完成時才使用 LLM 評審分數，否則 SHALL 使用近似比對與規則判定，並在圖說寫明。
`scripts/eval e0 report` SHALL produce a report and two SVG charts (knowledge score vs file size, reasoning / tool score vs file size) marking the Pareto front, and list t/s, mean latency, peak RAM / VRAM, placement, 95% confidence intervals, a same-base comparison table, and excluded models with reasons. LLM-judge scores SHALL be used only when judging completed; otherwise approximate matching and rule checks SHALL be used, and the caption SHALL say so.

#### Scenario: 部分模型未完成 / Some models incomplete

- **WHEN** 有模型還沒跑完或被排除
  Some models have not finished or were excluded
- **THEN** 報表標為不完整，圖中只畫已完成的模型，並列出缺少的模型與狀態
  The report is marked incomplete, charts plot completed models only, and the missing models are listed with their state

### Requirement: Sampled Setting

取樣設定 SHALL 只對貪婪解碼推理 / 工具題分數排名前 3 的模型，以 N=8、溫度 0.7 跑程式與工具題（摘要不取樣）。報表 SHALL 分開列出 pass@1、多數決與 pass@8，並 SHALL 標明 pass@8 需要標準答案，只能當上限參考。
The sampled setting SHALL run only for the top 3 models by greedy reasoning / tool score, on the code and tool items with N=8 at temperature 0.7 (summaries are not sampled). The report SHALL list pass@1, majority vote and pass@8 separately, and SHALL state that pass@8 needs the ground truth and is an upper bound only.

#### Scenario: 多數決平手 / Majority tie

- **WHEN** 8 條樣本中有兩種答案票數相同
  Two answers tie among the 8 samples
- **THEN** 取樣本順序中先出現的那一個，並在明細中記錄平手
  The one appearing first in sample order is taken, and the tie is recorded in the details

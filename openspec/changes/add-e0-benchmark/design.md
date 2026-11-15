## Context

- 評測：`scripts/eval run / verify` 已能對一個模型跑完 R0（300 題）並評分；本機 Qwen3-0.6B-Q8_0 純 CPU 一次約 29 分鐘（39 t/s）。
  Evaluation: `scripts/eval run / verify` runs and scores one model on R0 (300 items); local Qwen3-0.6B-Q8_0 on CPU takes about 29 minutes (39 t/s).
- 本機資源預算（`facts.json`，2026-11-15 下午）：12 個執行緒；RAM 可用約 8,355 MiB；VRAM 可用約 3,746 MiB（RTX 4050 6 GB，桌面已占用一部分）。預算每次載入模型前重新計算（R18.1）。
  Local budgets (`facts.json`, afternoon of 2026-11-15): 12 threads; about 8,355 MiB RAM and 3,746 MiB VRAM usable (RTX 4050 6 GB, partly used by the desktop). Budgets are recomputed before every model load (R18.1).
- llama.cpp 鎖定 `93cf736a`（2026-11-12），比 b11556 新 767 個 commit。支援 `qwen3`、`qwen35`、`llama`、`bitnet` 架構，以及 `Q1_0`（每 128 個一組）、`Q2_0`（每 64 個一組）、`TQ1_0`、`TQ2_0`。`Q1_0`、`Q2_0` 有 CUDA kernel；`TQ*` 只能用 CPU（2026-11-14 實測）。
  llama.cpp is pinned at `93cf736a` (2026-11-12), 767 commits after b11556. It supports the `qwen3`, `qwen35`, `llama` and `bitnet` architectures and `Q1_0` (groups of 128), `Q2_0` (groups of 64), `TQ1_0`, `TQ2_0`; `Q1_0` and `Q2_0` have CUDA kernels, `TQ*` is CPU only (measured 2026-11-14).

## Goals / Non-Goals

**Goals：**
- 同一份題庫、同樣的解碼設定，比較不同壓縮形式在本機的「分數 / 檔案大小」。
  Compare "score per file size" of compression forms locally, on the same bank and decoding settings.
- 盡量做到同一個基底的對照（Qwen3.5 的 Q8_0 / Q4_K_M / IQ2_M / 三值），讓差異來自壓縮方式而不是基底。
  Same-base comparisons where possible (Qwen3.5 at Q8_0 / Q4_K_M / IQ2_M / ternary), so differences come from compression, not the base.
- 跨多個夜晚可中斷、可續跑；不超過資源預算；結果可重現。
  Interruptible and resumable across nights; within budgets; reproducible.

**Non-Goals：** 見 proposal。 / See the proposal.

## Decisions

### D1 — 候選清單（17 個檔案，約 34.4 GiB）/ Candidate list (17 files, about 34.4 GiB)

授權欄位都取自 Hugging Face repo（Apache-2.0 或 MIT），實作時逐一讀官方 LICENSE 檔再登記（R10）。檔案大小以 MiB 計。
License fields come from the Hugging Face repos (Apache-2.0 or MIT); each official LICENSE file is read before registering (R10). Sizes in MiB.

| 組 / Group | 模型 / Model | 檔案 / File | MiB | 基底 / Base | 擺放 / Placement |
|---|---|---|---|---|---|
| 三值 / ternary | Ternary-Bonsai-2-2B | `Q2_0` | 521 | Qwen3.5-2B | GPU |
| 三值 / ternary | Ternary-Bonsai-2-4B | `Q2_0` | 1,156 | Qwen3.5-4B | GPU |
| 三值 / ternary | Ternary-Bonsai-2-9B | `Q2_0` | 2,438 | Qwen3.5-9B | GPU |
| 三值 / ternary | BitCPM-CANN-3B | `TQ2_0` | 1,044 | MiniCPM4 | CPU |
| 三值 / ternary | BitCPM-CANN-8B | `TQ2_0` | 2,264 | MiniCPM4 | CPU |
| 三值 / ternary | BitNet b1.58 2B4T（社群轉檔 / community conversion） | `TQ2_0` | 1,148 | BitNet | CPU（見 OQ1 / see OQ1） |
| 1-bit | Bonsai-8B | `Q1_0` | 1,105 | Qwen3-8B | GPU |
| 1-bit | Bonsai-27B | `Q1_0` | 3,627 | Qwen3.6-27B | CPU（VRAM 不足 / VRAM too small） |
| int8 | Qwen3.5-0.8B / 2B / 4B | `Q8_0` | 774 / 1,919 / 4,275 | 同名 / same | GPU / GPU / CPU |
| int4 | Qwen3.5-0.8B / 2B / 4B / 9B | `Q4_K_M` | 508 / 1,222 / 2,614 / 5,417 | 同名 / same | GPU / GPU / GPU / CPU |
| int2 | Qwen3.5-4B / 9B | `UD-IQ2_M` | 1,678 / 3,480 | 同名 / same | GPU / CPU |

另外已有的 Qwen3-0.6B-Q8_0（2026-11-15 執行）作為對照點，不重跑。
The existing Qwen3-0.6B-Q8_0 run (2026-11-15) is kept as a reference point and not rerun.

**排除與原因 / Excluded, with reasons**
- 第一代 Ternary-Bonsai 4B / 8B（Qwen3 基底）：已由同基底可比的第二代取代；而且預設的 g128 `Q2_0` 檔與主線每 64 個一組的 `Q2_0` 不相容（要用 `_g64` 檔）。
  First-generation Ternary-Bonsai 4B / 8B (Qwen3 base): superseded by the second generation, which allows same-base comparison; their default g128 `Q2_0` files also do not match mainline's 64-weight groups (the `_g64` files would be needed).
- Maple-Preview 20B-A1B：最小檔案 11,318 MiB，超過 RAM 預算。
  Maple-Preview 20B-A1B: the smallest file is 11,318 MiB, over the RAM budget.
- Qwen3.5-9B Q8_0（9,086 MiB）：超過 RAM 預算。
  Qwen3.5-9B Q8_0 (9,086 MiB): over the RAM budget.
- `PQ2_0`、`PTQ1_0`：只有 PrismML 分支能跑。
  `PQ2_0`, `PTQ1_0`: PrismML fork only.
- CAT-Q：還沒有 GGUF。
  CAT-Q: no GGUF yet.

### D2 — 擺放：整個模型放 GPU，否則純 CPU / Placement: whole model on GPU, else CPU only

模型檔加上 KV 快取估算值不超過 VRAM 可用量，而且量化型別有 CUDA kernel，才用 `-ngl 99`；否則 `-ngl 0`。不做部分卸載：`hw-autoconfig.md` §6.5.2 的結論是 CPU+GPU 混用不會更快，而且會讓量測難以比較。實際擺放、`ngl` 與預算數字都寫進每次執行的條件。
`-ngl 99` only when the model file plus the estimated KV cache fits usable VRAM and the quant type has CUDA kernels; otherwise `-ngl 0`. No partial offload: `hw-autoconfig.md` §6.5.2 found CPU+GPU splitting is not faster, and it makes measurements hard to compare. The placement, `ngl` and budget figures go into each run's conditions.

另外對一個小模型（Qwen3.5-2B Q4_K_M）GPU 與 CPU 各跑一次，量測擺放對速度的影響。分數應該幾乎相同，若差很多就代表後端有數值問題。
One small model (Qwen3.5-2B Q4_K_M) also runs on both GPU and CPU to measure the effect of placement on speed; scores should be nearly identical, and a large gap would indicate a numeric problem in a backend.

### D3 — 冒煙檢查 / Smoke check

每個模型在完整評測前先跑固定的 5 題（選擇題、SimpleQA、程式、工具、摘要各 1 題），檢查：
Before the full run, each model answers a fixed set of 5 items (one each of multiple choice, SimpleQA, code, tool, summary), checking that:
1. 模型能載入，回答不是空的。
   It loads and answers are not empty.
2. 思考模式確實關閉：回答中沒有 `<think>`。Qwen3.5 與 Bonsai-2 的聊天範本可能和 Qwen3 不同。
   Thinking is really off: no `<think>` in answers (Qwen3.5 and Bonsai-2 chat templates may differ from Qwen3).
3. 至少 3 題可以解析。
   At least 3 answers parse.

沒通過就記為 `excluded_smoke` 並附上原因，不跑完整評測。冒煙檢查約 1～2 分鐘，但屬於「載入模型」，仍排在夜間。
A model that fails is recorded as `excluded_smoke` with the reason and gets no full run. The check takes 1–2 minutes but loads a model, so it still runs at night.

### D4 — 解碼設定 / Decoding

貪婪解碼、思考關閉、上下文 4096，和既有執行相同。BitNet 2B4T 的訓練上下文是 4096，題庫最長的提示約 7,400 字元（ACEBench），在範圍內。
Greedy, thinking off, context 4096, as in existing runs. BitNet 2B4T's trained context is 4096; the longest prompt in the bank is about 7,400 characters (ACEBench), within range.

### D5 — 跨夜執行與續跑 / Multi-night runs and resume

`scripts/eval e0 run` 依矩陣順序執行，並以 `var/eval/e0/<矩陣雜湊>/state.json` 記錄每一列的狀態：`pending`、`downloaded`、`smoke_ok`、`excluded_*`、`run_complete`、`verified`。夜間時段結束時停在題與題之間（沿用 runner 的行為），下一晚從原處續跑。每一列的執行代號固定為 `e0-<矩陣列名>`，所以重跑不會產生重複資料。
`scripts/eval e0 run` follows the matrix order and tracks each row in `var/eval/e0/<matrix hash>/state.json` (`pending`, `downloaded`, `smoke_ok`, `excluded_*`, `run_complete`, `verified`). It stops between items at the end of the night window (existing runner behavior) and resumes the next night. Each row's run ID is fixed (`e0-<row name>`), so reruns never duplicate data.

### D6 — 取樣設定與時間預估 / Sampled setting and time estimate

時間預估：依 0.6B 在 CPU 上的實測（39 t/s，29 分鐘）按 t/s 比例推算。小模型放 GPU 每個約 20～40 分鐘，CPU 上的 8B～27B 每個約 1.5～3 小時，貪婪解碼總計約 15～20 小時，也就是**約 3 個夜晚**（每晚 7 小時）。`e0 plan` 會依實際 t/s 更新預估。
Estimate: scaled by t/s from the measured 0.6B CPU run (39 t/s, 29 minutes). Small models on GPU take about 20–40 minutes each, and 8B–27B on CPU about 1.5–3 hours each, so greedy totals about 15–20 hours, **about 3 nights** (7 hours each). `e0 plan` updates the estimate from measured t/s.

N=8 取樣是貪婪解碼的 8 倍工作量，全部跑不完。所以只對貪婪解碼「推理 / 工具題分數」排名前 3 的模型，跑推理 / 工具 150 題，溫度 0.7。報表列出三個數字：
N=8 sampling is 8× the greedy work and cannot cover everything, so it runs only for the top 3 models by greedy reasoning / tool score, on those 150 items at temperature 0.7. The report lists three numbers:
- **pass@1**：8 條的平均正確率。
  **pass@1**: mean correctness over the 8 samples.
- **多數決**：工具題取最多樣本一致的呼叫，程式題取最多樣本一致的輸出。不需要標準答案，所以部署時也能用。
  **Majority vote**: the most common call for tool items and the most common outputs for code items. It needs no ground truth, so it is usable at deployment.
- **pass@8**：8 條中有任何一條正確。這需要標準答案，**只能當上限參考**，不能當成部署時的能力。
  **pass@8**: any of the 8 correct. This needs the ground truth, so it is **an upper bound only**, not a deployable capability.

### D7 — 報表與圖表 / Report and charts

`var/eval/e0/<矩陣雜湊>/report.md` 與兩張 SVG 圖（知識題、推理 / 工具題），x 軸是檔案大小（對數刻度），y 軸是分數，帕累托前緣用線連起來，各組用不同符號。圖表直接產生 SVG，不新增繪圖套件，所以不需要 R23 查證，也不增加相依。表格另列 t/s、平均延遲、峰值 RAM / VRAM、擺放位置、被排除的模型與原因。
`var/eval/e0/<matrix hash>/report.md` plus two SVG charts (knowledge, reasoning / tool): x is file size (log scale), y is score, the Pareto front is joined by a line, and groups use different markers. Charts are written as SVG directly, so no plotting package (no R23 check, no new dependency). Tables also list t/s, mean latency, peak RAM / VRAM, placement, and excluded models with reasons.

LLM 評審的分數（SimpleQA 官方評審、摘要忠實度）只有評審實際跑完時才放進圖表，否則圖表用近似比對與規則判定，並在圖說寫明。
LLM-judge scores (official SimpleQA grading, summary faithfulness) enter the charts only when judging actually completed; otherwise charts use approximate matching and rule checks, and the caption says so.

## Risks / Trade-offs

- **BitNet 2B4T 在主線上算錯**：主線用 SiLU，模型要 relu²。社群實測，錯誤時困惑度約 77，修正後約 12.5。→ OQ1。
  **BitNet 2B4T is computed wrong on mainline**: SiLU instead of relu²; community measurements show perplexity ~77 when wrong versus ~12.5 when fixed. → OQ1.
- **社群轉檔的 GGUF**（BitNet、unsloth 的 Qwen3.5）：GGUF 是資料不是程式，但 llama.cpp 的解析器本身曾有漏洞。→ 下載後核對 SHA-256，並以鎖定版本的 llama.cpp 載入（R23 已查證此版本）。Qwen 官方沒有提供 Qwen3.5 小模型的 GGUF。
  **Community GGUFs** (BitNet, unsloth Qwen3.5): GGUF is data, not code, but llama.cpp's parser has had vulnerabilities. → Verify SHA-256 after download and load with the pinned llama.cpp (R23-checked). Qwen publishes no official GGUF for the small Qwen3.5 models.
- **聊天範本差異**：BitCPM 的範本格式簡陋；Qwen3.5 關閉思考的方式可能和 Qwen3 不同。→ D3 冒煙檢查；必要時在矩陣中為該列指定範本參數，並記入條件。
  **Chat template differences**: BitCPM's template is crude, and Qwen3.5 may turn thinking off differently from Qwen3. → D3 smoke check; if needed, the matrix row sets template arguments, recorded in conditions.
- **VRAM 可用量會變**：Windows 桌面占用會浮動。→ 每次載入前重算預算；不夠時改用 CPU 並記錄，而不是硬塞。
  **Usable VRAM varies** with Windows desktop usage. → Budgets are recomputed before every load; when short, fall back to CPU and record it rather than force-fitting.
- **單次量測**：每個模型只跑一次，題數 50 時 ±7 分左右的差距不具統計意義。→ 報表附上 95% 信賴區間，G1 判斷時一併考量。
  **Single measurement**: one run per model; with 50 items, gaps of about ±7 points are not significant. → The report shows 95% confidence intervals for G1.

## Open Questions

- **OQ1 BitNet b1.58 2B4T**：
  - (a) 排除。
    Exclude it.
  - (b) 在我們的 llama.cpp 上加一行修正（`bitnet` 改用 `LLM_FFN_RELU_SQR`），以 patch 檔保存並記入 stack.md。這會改動鎖定的引擎原始碼，屬於重大變更（R4）。
    Add a one-line fix to our llama.cpp (`bitnet` uses `LLM_FFN_RELU_SQR`), kept as a patch file and recorded in stack.md. This changes the pinned engine source, a major change (R4).
  - 我建議 (a)：它是唯一 2B 的原生三值模型，有參考價值，但 Ternary-Bonsai-2-2B 已經覆蓋同一個大小。
    I recommend (a): as the only native-ternary 2B model it has reference value, but Ternary-Bonsai-2-2B already covers that size.
- **OQ2 候選清單與下載量**：D1 的 17 個檔案、約 34.4 GiB，夜間下載。是否同意，或要增減？
  **Candidate list and download volume**: the 17 files in D1, about 34.4 GiB, downloaded at night. Approve, or add / remove?
- **OQ3 取樣設定的範圍**：前 3 名、推理 / 工具 150 題、N=8，約 2～3 個夜晚。是否同意？
  **Scope of the sampled setting**: top 3, the 150 reasoning / tool items, N=8, about 2–3 nights. Approve?
- **OQ4 LLM 評審的用量**：每個模型約 100 次評審呼叫（SimpleQA 50 + 摘要 50），16 個模型約 1,600 次，全部用免費模型，夜間進行。是否同意？評審模型用哪一個（deepseek 今天不回應；Nemotron 目前可用）？
  **LLM judge volume**: about 100 judge calls per model (50 SimpleQA + 50 summary), about 1,600 for 16 models, all on free models at night. Approve? Which judge model (deepseek was unresponsive today; Nemotron works now)?

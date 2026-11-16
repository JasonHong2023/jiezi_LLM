> **狀態 / Status**：使用者 2026-11-17 審閱並同意。實作排在 G1 選定核心之後（要先知道顯示記憶體剩多少）。
> Proposal only, **not implemented**; implementation follows G1, once the VRAM left beside the core is known.

## Why

開發計畫 5.1 的檢索是「向量化 + 重排序」。add-rag 只做了前半：全文候選加向量重排。向量是把問題和段落**各自**壓成一個向量再比相似度，問題與段落之間的細節對不上（例如「酒駕」對「不能安全駕駛」要靠向量剛好相近）。重排序模型把「問題＋段落」**一起**讀再打分，通常更準，代價是每個候選都要跑一次模型。
Dev plan 5.1 calls for embedding plus reranking; add-rag did the first half. A reranker reads the question and passage together, which is usually more accurate but costs one model pass per candidate.

是否值得，要量了才知道：0.6B 的重排序模型在 CPU 上對 20 個段落約需數十秒 **[估]**，放 GPU 又會和核心模型搶顯示記憶體。所以本提案是「先量、過門檻才啟用」。
Whether it pays off must be measured: on CPU it may take tens of seconds for 20 passages; on GPU it competes with the core for VRAM. Hence measure first, enable only past a threshold.

## What Changes

- 模型：Qwen3-Reranker-0.6B（GGUF；授權與轉檔正確性見 Impact），登記到 `models/manifest.toml`，bootstrap 不自動下載。
- 引擎：`engine-rerank`，埠 **36106**（R11 的 361xx 區段；同步 R11 表與 R12 流程圖），延遲啟動、閒置卸載、只綁 127.0.0.1；擺放（GPU／CPU）依當下預算決定。
- 檢索流程：知識庫與法規在向量階段取前 N 名（預設 20）→ 重排序 → 取前 k 名附給模型；重排序失敗或逾時就退回向量排序（不影響回答）。`JIEZI_RERANK`（預設 **off**，量測過門檻後才改預設）。
- **轉檔正確性檢查**（已知風險）：啟動時先用內建的 3 組「相關／不相關」樣本自我檢查，分數沒有分開就停用並在 `doctor` 報告，不默默使用壞的模型。
  A startup self-check on built-in relevant/irrelevant pairs disables a mis-converted model instead of using it silently.
- 量測工具：`scripts/jiezi selftest` 的檢索題加上「命中率@k」與延遲，可切換有無重排序做 A/B。

## Non-Goals

- 訓練或微調重排序模型。/ Training a reranker.
- 用在記憶、技能庫、辭典（這些是精確比對或資料量小）。/ Memory, skills and dictionaries.
- NPU 上執行（開發機沒有 NPU）。/ NPU execution.

## Capabilities

### New Capabilities

- `rag`：向量檢索與重排序（`rag` 目前只在已歸檔變更中，`openspec/specs/rag` 尚未建立——歸檔 add-rag 後由本變更補上重排序的需求）。/ Retrieval and reranking.

### Modified Capabilities

（無）/ (None)

## Impact

- 新模型約 640 MB **[估：依同系列 0.6B Q8_0 的大小]**；授權需讀官方 LICENSE 後登記（Qwen3 系列為 Apache-2.0 ⚠️ 尚未對這個模型查證）。
- ⚠️ 已知風險（`docs/analysis/related-resources.md` §6，二手資料）：部分 Qwen3-Reranker 的 GGUF 轉檔在 `/v1/rerank` 回傳接近 0 的分數；要用新版 llama.cpp 並實測。所以才有上面的自我檢查。
- 下載與量測屬長時間工作，排在 00:00 後。

## 已決事項（原 Open Questions）/ Resolved

- **OQ1**：門檻為命中率@3 提升 ≥ 5 個百分點且每題多花 ≤ 3 秒（使用者 2026-11-17 同意）。/ Threshold approved.
- **OQ2**：依量測決定擺放；放不下就 CPU（同意建議）。/ Placement by measurement.

# rag Specification

## Purpose
向量檢索的相關性門檻要有量測依據，重排序可選且失敗時安全退回。
Measured relevance thresholds and optional reranking with a safe fallback.
## Requirements
### Requirement: Optional Reranking With a Safe Fallback

啟用重排序時，知識庫與法規的檢索 SHALL 先取向量排序的前 N 名，再以重排序模型對「問題與段落」打分後取前 k 名；重排序失敗、逾時或自我檢查未通過時 SHALL 退回向量排序，SHALL NOT 讓回答失敗。重排序模型啟動時 SHALL 以內建的相關／不相關樣本自我檢查，分數無法區分兩者時 SHALL 停用並在健康檢查中報告。
With reranking on, retrieval SHALL take the top N by vector score and reorder them with the reranker to pick the top k; on failure, timeout or a failed self-check it SHALL fall back to the vector order and SHALL NOT fail the answer. At startup the reranker SHALL check itself on built-in relevant and irrelevant pairs and SHALL be disabled, and reported by the health check, when it cannot separate them.

#### Scenario: 重排序模型壞掉 / A broken reranker

- **WHEN** 重排序模型對相關與不相關的樣本都回傳接近 0 的分數
  The reranker returns near-zero scores for both relevant and irrelevant pairs
- **THEN** 重排序停用，檢索照向量排序進行，`doctor` 顯示原因
  Reranking is disabled, retrieval uses the vector order, and `doctor` shows why

#### Scenario: 逾時 / Timeout

- **WHEN** 重排序超過時間上限
  Reranking exceeds its time limit
- **THEN** 這一題改用向量排序的結果回答
  The question is answered from the vector order

### Requirement: Relevance Threshold Measurement
The project SHALL keep a labelled relevance question set (real questions, on-topic questions that do not name the article, and off-topic questions) and a retrieval-only command that reports, for each candidate similarity threshold with the reranker on and off, the share of on-topic questions that get the expected article, the share of off-topic questions that get any section, and the time per question; the default threshold SHALL change only after the user approves the measured choice.

#### Scenario: 不該附的題目 / An off-topic question
- **WHEN** 量測集裡「說一個笑話」標為不該附，某個門檻下附了〈台灣科技說故事〉
  An off-topic question gets a section at some threshold
- **THEN** 這一格的「不該附卻附了」比例計入這題
  It counts toward that threshold's false-attach rate

#### Scenario: 改預設 / Changing the default
- **WHEN** 量測選出新門檻
  The measurement picks a new threshold
- **THEN** 先回報使用者，同意後才改 `JIEZI_RAG_MIN` 的預設
  The user is told first and the default changes only after approval


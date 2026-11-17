## ADDED Requirements

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

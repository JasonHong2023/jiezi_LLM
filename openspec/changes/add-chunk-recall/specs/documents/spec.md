## ADDED Requirements

### Requirement: Recall Aids for Document Chunk Selection
When the recall aid is enabled, the gateway SHALL improve chunk selection for questions about an attached long document either by reserving places for the top semantic chunks or by also ranking with a locally drafted hypothetical answer, and SHALL fall back to the existing fused ranking whenever the aid fails or exceeds its time limit.

長文件問答的挑段落 SHALL 可選擇保留語意前幾名的名額，或另用本機模型猜出的答案句排序；失敗或逾時 SHALL 退回現行的合併排序。

#### Scenario: A semantically close chunk is kept
- **WHEN** the reserve mode is on and a chunk is among the top semantic results but ranks low lexically
- **THEN** that chunk is sent to the model

#### Scenario: Drafting the hypothetical answer is too slow
- **WHEN** the hypothetical answer is not ready within the time limit
- **THEN** the existing fused ranking is used and the answer is not blocked

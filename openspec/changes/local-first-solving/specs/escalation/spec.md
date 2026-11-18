## ADDED Requirements

### Requirement: Local-First Escalation Ladder
For policy `jiezi`, in both streaming and non-streaming answers, when the local answer fails its checks or says it is unsure, the gateway SHALL first retry locally with the error, then retry locally with think mode under a token budget, then ask a free cloud model for hints only and answer locally again, and SHALL consult Claude only after these steps fail; each step SHALL be recorded in the answer process.

#### Scenario: 本機重想後答對 / Solved on a local retry
- **WHEN** 本機第一次回答查核沒過，帶著錯誤訊息重答後通過
  The first local answer fails and the retry with the error passes
- **THEN** 回覆重答的結果，不請教 Claude；過程顯示「本機作答 → 檢查沒過 → 本機重答 → 通過」
  The retry is returned without consulting Claude

#### Scenario: 全部失敗才請教 / Claude only at the end
- **WHEN** 重答、思考模式、雲端提示後都沒通過
  Every local and hint step fails
- **THEN** 才請教 Claude；過程列出所有步驟
  Only then is Claude consulted

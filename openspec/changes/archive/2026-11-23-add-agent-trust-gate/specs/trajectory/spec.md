## MODIFIED Requirements

### Requirement: Training-Use Flag
每筆軌跡 SHALL 有 `training_use` 欄位：請教 Claude 的紀錄 SHALL 為 `false`；其他紀錄為 `null`，表示訓練前必須依授權表判斷。任何訓練或自我進化流程 SHALL 排除 `training_use` 為 `false` 的紀錄。
Every trajectory SHALL carry `training_use`: Claude consultations SHALL be `false`; others are `null`, meaning the license registry decides before training. Any training or self-evolution pipeline SHALL exclude records whose `training_use` is `false`.
標為不可訓練的軌跡 SHALL 另含 `trust={level, reason, provenance}`，說明為什麼不可訓練；請教 Claude 或雲端轉交的紀錄 reason 分別為 `consultation`、`cloud`。
Untrainable trajectories SHALL also carry `trust` with the level, reason and provenance; Claude consultations and cloud escalations use reasons consultation and cloud.

#### Scenario: 準備訓練資料 / Preparing training data

- **WHEN** 之後的自我進化從軌跡挑選資料
  Later self-evolution selects data from trajectories
- **THEN** `training_use: false` 的紀錄全部排除，排除數量寫進該輪的報告
  Every `training_use: false` record is excluded, and the excluded count is written into that round's report

#### Scenario: 雲端回答 / A cloud answer

- **WHEN** 請求轉交雲端模型作答
  A request is answered by the cloud model
- **THEN** 軌跡 `training_use=false`、`trust.reason="cloud"`、`trust.provenance.source_channel="cloud"`
  The trajectory is untrainable with reason cloud and a cloud source

## MODIFIED Requirements

### Requirement: Training-Use Flag

每筆軌跡 SHALL 有 `training_use` 欄位：請教 Claude 的紀錄 SHALL 為 `false`；其他紀錄為 `null`，表示訓練前必須依授權表判斷。任何訓練或自我進化流程 SHALL 排除 `training_use` 為 `false` 的紀錄。**每筆軌跡 SHALL 新增 `trust_level` 與 `provenance` 欄位，在記錄建立時從 TrustGate 評估結果填入。雲端輸出的 `trust_level` 為 `"cloud"`，`provenance` 含 `source_channel="cloud"、source_id=<model>、retrieval_method="consult"、extra.reason=<reason>`。**

Every trajectory SHALL carry `training_use`: Claude consultations SHALL be `false`; others are `null`, meaning the license registry decides before training. Any training or self-evolution pipeline SHALL exclude records whose `training_use` is `false`. **Every trajectory SHALL add `trust_level` and `provenance` fields, populated from TrustGate evaluation at record creation. Cloud outputs SHALL have `trust.level="unverified"＋provenance.source_channel="cloud"`, `provenance` with `source_channel="cloud"`, `source_id=<model>`, `retrieval_method="consult"`, `extra.reason=<reason>`.**

#### Scenario: 準備訓練資料 / Preparing training data

- **WHEN** 之後的自我進化從軌跡挑選資料
  Later self-evolution selects data from trajectories
- **THEN** `training_use: false` 的紀錄全部排除，排除數量寫進該輪的報告
  Every `training_use: false` record is excluded, and the excluded count is written into that round's report

#### Scenario: 軌跡包含信任欄位 / Trajectory contains trust fields

- **WHEN** 一次 Claude 諮詢產生軌跡記錄
  A Claude consultation produces a trajectory record
- **THEN** 記錄含 `trust.level="unverified"＋provenance.source_channel="cloud"、training_use=false、provenance={source_channel:"cloud", source_id:"claude", retrieval_method:"consult", extra:{reason:"policy"}}`
  Record contains `trust.level="unverified"＋provenance.source_channel="cloud"`, `training_use=false`, `provenance={source_channel:"cloud", source_id:"claude", retrieval_method:"consult", extra:{reason:"policy"}}`

#### Scenario: 本機回答軌跡 / Local answer trajectory

- **WHEN** 本機模型回答並通過強驗證
  Local model answers and passes strong verification
- **THEN** 記錄含 `trust_level="trusted"、training_use=null、provenance={source_channel:"local", ...}`
  Record contains `trust_level="trusted"`, `training_use=null`, `provenance={source_channel:"local", ...}`

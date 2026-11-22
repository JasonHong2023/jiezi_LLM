## MODIFIED Requirements

### Requirement: Gated Training Export

訓練資料匯出 SHALL 只收可訓練來源與通過強驗證的本機回答，SHALL 排除標為不可訓練或用到不可訓練來源的對話，SHALL 剔除與評測題或評測目標重疊的題目，且每一筆 SHALL 帶來源、授權與雜湊。**每個由 `_ex()` 產出的訓練範例 SHALL 新增 `trust_level`、`provenance`、`fetched_at` 欄位。`TrainingDataExporter.export()` SHALL 只匯出 `trust_level == "trusted"` 且 `training_use == True` 的範例。**

The export SHALL keep only trainable sources and strongly verified local answers, SHALL drop non-trainable conversations and evaluation overlaps, and SHALL label every example with source, license and hash. **Each training example produced by `_ex()` SHALL include `trust_level`, `provenance`, `fetched_at` fields. `TrainingDataExporter.export()` SHALL only export examples where `trust_level == "trusted"` AND `training_use == True`.**

#### Scenario: Claude 的回答 / Claude's answer

- **WHEN** 一筆對話由記憶中的 Claude 答案回覆（`training_use: false`）
  A conversation was answered from a remembered Claude answer
- **THEN** 不進訓練資料
  It is excluded

#### Scenario: 只有弱驗證 / Weak verification only

- **WHEN** 本機回答只通過答案查核（數字、引號）
  A local answer passed only the grounded check
- **THEN** 不進訓練資料
  It is excluded

#### Scenario: 僅匯出受信可訓練範例 / Only trusted trainable examples exported

- **WHEN** 訓練資料包含各信任等級與 training_use 組合的範例
  Training data contains examples at all trust levels and training_use combinations
- **THEN** `export()` 只寫出 `trust_level=="trusted"` 且 `training_use==True` 的範例
  `export()` only writes examples with `trust_level=="trusted"` AND `training_use==True`
- **THEN** `verified + training_use=True` 被排除
  `verified + training_use=True` are excluded
- **THEN** `trusted + training_use=False` 被排除
  `trusted + training_use=False` are excluded
- **THEN** `cloud` 範例被排除
  `cloud` examples are excluded

#### Scenario: 範例包含信任欄位 / Example contains trust fields

- **WHEN** 一個通過強驗證的本機回答產生訓練範例
  A strongly verified local answer produces a training example
- **THEN** 範例含 `trust_level="trusted"、provenance={source_channel:"local",...}、fetched_at`（ISO 8601 UTC）
  Example contains `trust_level="trusted"`, `provenance={source_channel:"local",...}`, `fetched_at` (ISO 8601 UTC)

## ADDED Requirements

### Requirement: Gated Training Export

訓練資料匯出 SHALL 只收可訓練來源與通過強驗證的本機回答，SHALL 排除標為不可訓練或用到不可訓練來源的對話，SHALL 剔除與評測題或評測目標重疊的題目，且每一筆 SHALL 帶來源、授權與雜湊。
The export SHALL keep only trainable sources and strongly verified local answers, SHALL drop non-trainable conversations and evaluation overlaps, and SHALL label every example with source, license and hash.

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

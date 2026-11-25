# training-data Specification

## Purpose
有關卡的訓練資料匯出（授權、可訓練標記）與教師答案。
Gated export of trainable data and teacher answers.
## Requirements
### Requirement: Gated Training Export
訓練資料匯出 SHALL 只收可訓練來源與通過強驗證的本機回答，SHALL 排除標為不可訓練或用到不可訓練來源的對話，SHALL 剔除與評測題或評測目標重疊的題目，且每一筆 SHALL 帶來源、授權與雜湊。
The export SHALL keep only trainable sources and strongly verified local answers, SHALL drop non-trainable conversations and evaluation overlaps, and SHALL label every example with source, license and hash.
每筆匯出的範例 SHALL 另帶 `trust_level="trusted"` 與 provenance（content_hash 等於範例的 sha256）；答案內容在 taint index 裡的 SHALL 排除並計入 `tainted_content`。
Each example SHALL also carry trusted level and provenance; answers found in the taint index SHALL be dropped and counted.

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

#### Scenario: 污染內容不匯出 / Tainted content is not exported

- **WHEN** 一個本機答案通過驗證，但內容已在 taint index
  A verified local answer is in the taint index
- **THEN** 不匯出，manifest 的 `excluded.tainted_content` 加一
  It is not exported and excluded.tainted_content counts it

### Requirement: Teacher Answers
When one or more teacher models whose terms allow training are configured, after each escalated question the system SHALL ask each teacher the same question in the background with provider fallbacks disabled, SHALL keep the answer as a training candidate only when the responding model (and, for routed services, the provider) is the configured teacher, the answer passes the existing checks and its key facts agree with the delivered answer or with another teacher, and SHALL record the teacher's license; consulted Claude answers SHALL NOT be stored as training data.

#### Scenario: 老師與 Claude 一致 / Teacher agrees
- **WHEN** 「2027 年的國定假日」轉給 Claude 回答，老師 gpt-oss-120b 的答案關鍵日期一致
  The teacher's key facts match the delivered answer
- **THEN** 老師的答案存成訓練候選，license 記 gpt-oss Apache-2.0；Claude 的答案只在記憶裡
  The teacher's answer becomes a candidate; Claude's stays in memory only

#### Scenario: 被換成別的模型 / A different model answered
- **WHEN** 回應的 model 不是設定的老師
  The response came from another model
- **THEN** 不收
  It is not kept


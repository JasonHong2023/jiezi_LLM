## ADDED Requirements

### Requirement: Teacher Answers
When a teacher model whose terms allow training is configured, after each escalated question the system SHALL ask the teacher the same question in the background with provider fallbacks disabled, SHALL keep the answer as a training candidate only when the responding model is the configured teacher, the answer passes the existing checks and its key facts agree with the delivered answer, and SHALL record the teacher's license; consulted Claude answers SHALL NOT be stored as training data.

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

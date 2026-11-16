## ADDED Requirements

### Requirement: Reproducible Self-Test

`scripts/jiezi selftest` SHALL 以固定種子從已收錄的資料產生題目與標準答案，經 gateway 回答並判分；判分 SHALL 只看模型自己寫的部分，SHALL NOT 計入 gateway 附上的原文。
The self-test SHALL generate seeded questions and answers from the bundled data, answer them through the gateway, and score only the model's own text.

#### Scenario: 附錄不算分 / The appendix does not count

- **WHEN** 模型回答「1.5 公斤」，gateway 附錄寫著「2 台斤 = 1.2 公斤」
  The model says 1.5 kg while the appendix says 1.2 kg
- **THEN** 這題判為答錯
  The item is scored wrong

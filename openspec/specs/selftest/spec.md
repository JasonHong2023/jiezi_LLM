# selftest Specification

## Purpose
用可重現的題組（計算、單位、日期等）檢查工具呼叫整套系統是否正常。
A reproducible question set that checks the tool-calling system end to end.
## Requirements
### Requirement: Tool-Call System Check

`scripts/jiezi toolcheck` SHALL 把 R0 題庫的 ACEBench 題目以 OpenAI `tools` 經 gateway 回答，並 SHALL 用與 E0 相同的 ACEBench 評分器判分；評測題 SHALL NOT 用於訓練。
The tool check SHALL answer the R0 ACEBench items through the gateway as OpenAI tools and SHALL score them with the same checker as E0; the items SHALL NOT be used for training.

#### Scenario: 正確的呼叫 / A correct call

- **WHEN** gateway 回傳 get_weather(city='台北', day='明天')，標準答案相同
  The gateway returns the expected call
- **THEN** 這題判為答對
  The item is scored correct

### Requirement: Reproducible Self-Test

`scripts/jiezi selftest` SHALL 以固定種子從已收錄的資料產生題目與標準答案，經 gateway 回答並判分；判分 SHALL 只看模型自己寫的部分，SHALL NOT 計入 gateway 附上的原文。
The self-test SHALL generate seeded questions and answers from the bundled data, answer them through the gateway, and score only the model's own text.

#### Scenario: 附錄不算分 / The appendix does not count

- **WHEN** 模型回答「1.5 公斤」，gateway 附錄寫著「2 台斤 = 1.2 公斤」
  The model says 1.5 kg while the appendix says 1.2 kg
- **THEN** 這題判為答錯
  The item is scored wrong


## ADDED Requirements

### Requirement: Tool-Call System Check

`scripts/jiezi toolcheck` SHALL 把 R0 題庫的 ACEBench 題目以 OpenAI `tools` 經 gateway 回答，並 SHALL 用與 E0 相同的 ACEBench 評分器判分；評測題 SHALL NOT 用於訓練。
The tool check SHALL answer the R0 ACEBench items through the gateway as OpenAI tools and SHALL score them with the same checker as E0; the items SHALL NOT be used for training.

#### Scenario: 正確的呼叫 / A correct call

- **WHEN** gateway 回傳 get_weather(city='台北', day='明天')，標準答案相同
  The gateway returns the expected call
- **THEN** 這題判為答對
  The item is scored correct

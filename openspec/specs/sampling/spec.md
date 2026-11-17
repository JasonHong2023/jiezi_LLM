# sampling Specification

## Purpose
TBD - created by archiving change add-sampling. Update Purpose after archive.
## Requirements
### Requirement: Verified Majority Sampling

工具呼叫與寫程式的問題，gateway SHALL 同時取 N 個本機答案、逐一驗證，並 SHALL 從通過驗證的答案中選最多數一致的一組回傳，回應的 `jiezi.confidence` SHALL 為該組數量除以 N；閒聊與知識題 SHALL NOT 取樣。
For tool-call and code questions the gateway SHALL take N local samples, verify each, return the largest agreeing verified group, and report its share as `jiezi.confidence`; chat and knowledge questions SHALL NOT be sampled.

#### Scenario: 多數決 / Majority

- **WHEN** 4 個樣本中 1 個缺參數、2 個呼叫 get_weather(city='台北')、1 個呼叫 get_weather(city='高雄')
  One sample misses an argument, two call 台北, one calls 高雄
- **THEN** 回傳台北那一組，信心度 0.5
  The 台北 call is returned with confidence 0.5

#### Scenario: 閒聊 / Chat

- **WHEN** 使用者說「hi」
  The user says hi
- **THEN** 只呼叫本機模型一次
  The local model is called once


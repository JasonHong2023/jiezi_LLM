## ADDED Requirements

### Requirement: Rule-Based Pre-Routing

`jiezi` 策略下，問題明確需要上網或即時資料、且沒有程式算好或記憶中的答案時，gateway SHALL 不呼叫本機模型、直接轉交，轉交原因 SHALL 為 `needs_web`；一般閒聊與程式算得出的問題 SHALL 照常由本機回答。
Under `jiezi`, questions that need the web or live data and have no computed or remembered answer SHALL skip the local model with reason `needs_web`; chat and computable questions SHALL stay local.

#### Scenario: 問天氣 / Asking about the weather

- **WHEN** 使用者問「今天台北天氣如何？」
  The user asks about today's weather
- **THEN** 不呼叫本機模型，直接請教 Claude
  The local model is skipped and Claude is consulted

#### Scenario: 閒聊 / Chat

- **WHEN** 使用者說「我今天心情不好」
  The user says they feel down today
- **THEN** 本機照常回答
  The local model answers

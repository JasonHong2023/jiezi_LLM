## ADDED Requirements

### Requirement: Local Context Budget For Agent Clients
The gateway SHALL use a separate local context budget, `JIEZI_AGENT_CTX` (default 30000 tokens), for requests that carry tool definitions, while ordinary chat requests SHALL keep the 4096-token slot budget. Only one request above 4096 tokens SHALL run on the local engine at a time; a local tool call that is not valid JSON, names a tool not offered, or does not match its schema SHALL be retried once and then escalated by the existing ladder.

#### Scenario: Hermes 請求放得進代理預算 / A Hermes request fits the agent budget
- **WHEN** Hermes 送來約 19,000 token、帶 12 個工具的請求，`JIEZI_AGENT_CTX=30000`
  Hermes sends a 19,000-token request with 12 tools and the agent budget is 30000
- **THEN** 由本機回答，不以 `context_too_large` 轉雲端
  The local engine answers; it is not escalated as `context_too_large`

#### Scenario: 一般對話不變 / Ordinary chat unchanged
- **WHEN** 沒有帶工具的一般問答超過 4096 token
  A chat request without tools exceeds 4096 tokens
- **THEN** 照舊依序裁掉最舊對話與最長資料，放進 4096
  It is trimmed to the 4096-token slot as before

#### Scenario: 本機工具呼叫壞掉 / A broken local tool call
- **WHEN** 本機回的工具呼叫名稱不在請求的工具清單裡
  The local answer calls a tool that was not offered
- **THEN** 重試一次，仍不合法就轉雲端，軌跡記錄原因
  It retries once, then escalates and records the reason

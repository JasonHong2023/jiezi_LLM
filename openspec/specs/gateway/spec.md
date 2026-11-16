# gateway Specification

## Purpose
TBD - created by archiving change add-gateway. Update Purpose after archive.
## Requirements
### Requirement: Local-Only OpenAI-Compatible Entry

gateway SHALL 只綁定 `127.0.0.1`，使用 R11 區段的 gateway port（預設 36100），提供 `/v1/chat/completions`（含串流）、`/v1/models` 與 `/health`。設定成其他位址時 gateway SHALL 拒絕啟動。
The gateway SHALL bind only to `127.0.0.1` on the R11 gateway port (default 36100) and serve `/v1/chat/completions` (streaming included), `/v1/models` and `/health`. If configured for any other address, the gateway SHALL refuse to start.

#### Scenario: 設定成對外位址 / Configured for an external address

- **WHEN** 設定要求綁定 `0.0.0.0`
  Configuration asks to bind `0.0.0.0`
- **THEN** gateway 不啟動，並說明只允許 `127.0.0.1`（R6.12）
  The gateway does not start and states that only `127.0.0.1` is allowed (R6.12)

### Requirement: Local Key

每個 `/v1/*` 請求 SHALL 帶有與 `.env` 中 `JIEZI_GATEWAY_KEY` 相符的 Bearer 金鑰，否則 SHALL 回 401。沒有設定金鑰時 gateway SHALL 拒絕啟動。
Every `/v1/*` request SHALL carry a Bearer key matching `JIEZI_GATEWAY_KEY` in `.env`, otherwise the gateway SHALL answer 401. Without a configured key the gateway SHALL refuse to start.

#### Scenario: 金鑰錯誤 / Wrong key

- **WHEN** 請求的 Bearer 金鑰不符
  A request's Bearer key does not match
- **THEN** 回 401，不呼叫任何引擎，也不寫軌跡
  It gets 401, no engine is called, and no trajectory is written

### Requirement: Policy by Model Name

gateway SHALL 依請求的模型名稱選擇策略：`jiezi` 本機優先並依分層轉交、`jiezi-local` 只用本機、`jiezi-cloud` 直接用雲端。每個回應 SHALL 附上 `jiezi` 欄位，包含層級、實際模型、驗證結果、延遲、雲端 token 與費用，以及軌跡 ID。
The gateway SHALL pick a policy from the requested model name: `jiezi` (local first with tiered escalation), `jiezi-local` (local only), `jiezi-cloud` (cloud directly). Every response SHALL carry a `jiezi` field with the tier, actual model, verification, latency, cloud tokens and cost, and the trajectory ID.

#### Scenario: 只用本機但引擎不可用 / Local only while the engine is unavailable

- **WHEN** 模型名稱是 `jiezi-local`，且本機引擎被標為不可用
  The model is `jiezi-local` and the local engine is marked unavailable
- **THEN** 回 503，並附上不可用的原因，不轉交雲端
  It answers 503 with the reason and does not escalate to the cloud

### Requirement: Disconnect and Limits

gateway SHALL 限制請求大小與每個請求的總時間；客戶端在串流途中中斷時，gateway SHALL 取消上游請求，讓引擎停止生成。
The gateway SHALL limit request size and per-request time; when a client disconnects mid-stream, the gateway SHALL cancel the upstream request so the engine stops generating.

#### Scenario: 串流中斷 / Stream interrupted

- **WHEN** 客戶端在串流途中關閉連線
  The client closes the connection mid-stream
- **THEN** 上游請求被取消，軌跡記錄為 `client_disconnected`
  The upstream request is cancelled and the trajectory records `client_disconnected`

### Requirement: Embeddings Endpoint

gateway SHALL 提供 OpenAI 相容的 `POST /v1/embeddings`，SHALL 要求 gateway 金鑰，SHALL 限制每次最多 64 段、每段最多 8,000 字；`input_type` 為 `query` 時 SHALL 加上查詢指令前綴；沒有 embedding 模型時 SHALL 回 503。
The gateway SHALL serve OpenAI-compatible embeddings with the key, input limits, an optional query prefix, and 503 when no model is available.

#### Scenario: 沒有金鑰 / No key

- **WHEN** 請求沒有帶金鑰
  A request lacks the key
- **THEN** 回 401
  It gets 401


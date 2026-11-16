## ADDED Requirements

### Requirement: Embeddings Endpoint

gateway SHALL 提供 OpenAI 相容的 `POST /v1/embeddings`，SHALL 要求 gateway 金鑰，SHALL 限制每次最多 64 段、每段最多 8,000 字；`input_type` 為 `query` 時 SHALL 加上查詢指令前綴；沒有 embedding 模型時 SHALL 回 503。
The gateway SHALL serve OpenAI-compatible embeddings with the key, input limits, an optional query prefix, and 503 when no model is available.

#### Scenario: 沒有金鑰 / No key

- **WHEN** 請求沒有帶金鑰
  A request lacks the key
- **THEN** 回 401
  It gets 401

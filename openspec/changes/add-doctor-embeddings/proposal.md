## Why

功能變多後，哪個元件沒建、壞了不容易看出（搬到新電腦時更明顯，R21）；客戶端（Hermes、OpenCode）也需要 embedding 來做自己的檢索，而芥子已經有 embedding 引擎。
With many components, a single health view is needed (R21); clients also need embeddings, which jiezi already serves internally.

## What Changes

- `scripts/jiezi doctor`：檢查 gateway、金鑰、llama.cpp、模型、沙盒、各資料庫與向量、農曆套件、Claude CLI、磁碟空間，每項附修復指令；有必要元件缺失時結束碼 1。
  One-command health check with fixes.
- gateway `POST /v1/embeddings`（OpenAI 相容，需金鑰、只綁 127.0.0.1）；`input_type: "query"` 加 Qwen3-Embedding 的查詢指令；一次最多 64 段、每段 8,000 字。
  OpenAI-compatible embeddings with a query option and limits.

## Non-Goals

- 自動修復（只列出指令）。/ Automatic repair.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `gateway`：新增 `/v1/embeddings`。/ Adds the embeddings endpoint.

## Impact

- 2026-11-16 實跑 doctor：16 項，0 失敗、3 提醒（兩組向量待 E0 後建、農曆套件待安裝）。

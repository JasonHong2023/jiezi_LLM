## Why

E0 量的是純文字提示下的原始工具呼叫能力（0.6B 的 ACEBench 50 題中 19 題是格式無法解析）。使用者實際透過 gateway 用 OpenAI `tools` 時，有模型的工具呼叫格式、引擎的語法限制、平行取樣與驗證重答；要量這整套系統的分數，才知道 Phase 6.1 是否還需要訓練中文工具呼叫驗證器。
E0 measures raw text-prompt ability; the gateway adds native tool formats, constrained decoding, sampling and retries. The system score decides whether training a validator (Phase 6.1) is still needed.

## What Changes

- `scripts/jiezi toolcheck [--policy]`：R0 題庫的 50 題 ACEBench 轉成 OpenAI `tools` 與 messages 送進 gateway，回傳的 `tool_calls` 轉回 ACEBench 文字，用 E0 同一個評分器判分；報告寫到 `var/reports/toolcheck-*.md`。
  The 50 ACEBench items go through the gateway as OpenAI tools and are scored with the same checker.

## Non-Goals

- 用評測題訓練（只評測）。/ Training on evaluation items.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `selftest`：新增工具呼叫系統評測。/ Adds the tool-call system check.

## Impact

- 需要本機模型（E0 結束後跑）。/ Needs the local model (after E0).

## ADDED Requirements

### Requirement: Tiered Escalation v0

`jiezi` 策略 SHALL 先由本機回答（第 0 層）。執行期驗證失敗時 SHALL 把錯誤訊息附在對話後，本機重試一次（第 1 層）；仍失敗，或本機引擎不可用時，SHALL 在雲端轉交開啟的前提下改由雲端完整回答（第 3 層）。雲端轉交關閉或達到每日上限時，SHALL 回傳本機最後一次的答案，並在 `jiezi` 欄位註明沒有轉交的原因。
The `jiezi` policy SHALL answer locally first (tier 0). When runtime verification fails, it SHALL append the error message and retry locally once (tier 1); if that still fails, or the local engine is unavailable, it SHALL use a full cloud answer (tier 3) provided cloud escalation is enabled. When escalation is disabled or the daily cap is reached, it SHALL return the last local answer and state in the `jiezi` field why it did not escalate.

#### Scenario: 工具呼叫第 1 層修正成功 / Tool call fixed at tier 1

- **WHEN** 第 0 層的工具呼叫缺少必填參數，第 1 層重試後通過驗證
  The tier-0 tool call misses a required parameter, and the tier-1 retry passes verification
- **THEN** 回傳第 1 層的答案，`jiezi.tier` 為 1，軌跡記錄兩層的答案與驗證結果
  The tier-1 answer is returned with `jiezi.tier` = 1, and the trajectory records both tiers' answers and verification

#### Scenario: 達到每日上限 / Daily cap reached

- **WHEN** 第 1 層仍失敗，但今天的雲端轉交次數已達上限
  Tier 1 still fails but today's cloud escalations have reached the cap
- **THEN** 回傳第 1 層的答案，`jiezi.escalation` 註明 `daily_cap_reached`，不呼叫雲端
  The tier-1 answer is returned with `jiezi.escalation` = `daily_cap_reached`, and the cloud is not called

### Requirement: Runtime Verifiers Without Ground Truth

執行期驗證器 SHALL 只使用不需要標準答案的檢查，而且 SHALL NOT 執行回答內容：請求帶有 `tools` 時，檢查呼叫的格式、函式名稱、必填參數與 JSON Schema 型別；回答含 Python 程式區塊時，以 `ast.parse` 檢查語法。沒有適用的檢查時，回答 SHALL 視為未驗證，直接在第 0 層回傳。
Runtime verifiers SHALL use only checks that need no ground truth and SHALL NOT execute response content: with `tools` in the request, they check call format, function names, required parameters and JSON Schema types; for Python code blocks they check syntax with `ast.parse`. When no check applies, the answer SHALL count as unverified and return at tier 0.

#### Scenario: 一般問答 / General question

- **WHEN** 請求沒有 `tools`，回答也沒有程式區塊
  The request has no `tools` and the answer has no code block
- **THEN** 第 0 層直接回傳，`jiezi.verification` 為 `not_applicable`
  Tier 0 returns directly with `jiezi.verification` = `not_applicable`

### Requirement: Explicit Claude Consultation

`jiezi-ask-claude` 策略 SHALL 只在 `JIEZI_CONSULT=claude-cli` 時，透過本機 Claude Code CLI 的無頭模式請教 Claude，並 SHALL 關閉所有工具、不載入 MCP 與設定檔、不保存工作階段、在空的工作目錄執行。分層轉交 SHALL NOT 自動使用此策略。關閉時 SHALL 回 503 並說明如何開啟；CLI 回報錯誤（例如額度用完）時 SHALL 回 503 並附原因，不重試。
The `jiezi-ask-claude` policy SHALL consult Claude through the local Claude Code CLI in headless mode only when `JIEZI_CONSULT=claude-cli`, with all tools off, no MCP or settings loaded, no session persistence, in an empty working directory. Tiered escalation SHALL NOT use this policy automatically. When off it SHALL answer 503 explaining how to enable it; when the CLI reports an error (for example an exhausted allowance) it SHALL answer 503 with the reason, without retrying.

#### Scenario: 請教成功 / Consultation succeeds

- **WHEN** 使用者以 `jiezi-ask-claude` 提問，且請教已開啟
  The user asks with `jiezi-ask-claude` and consultation is on
- **THEN** 回傳 Claude 的回答，`jiezi.tier` 為 `consult`、`jiezi.training_use` 為 `false`，本機模型不會被載入
  Claude's answer is returned with `jiezi.tier` = `consult` and `jiezi.training_use` = `false`, and the local model is not loaded

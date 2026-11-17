# escalation Specification

## Purpose
TBD - created by archiving change add-gateway. Update Purpose after archive.
## Requirements
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

### Requirement: Claude Consultation

`JIEZI_CONSULT=claude-cli` 時，系統 SHALL 能透過本機 Claude Code CLI 的無頭模式請教 Claude，並 SHALL 只開放讀網頁與網路搜尋兩個工具（`JIEZI_CONSULT_WEB` 關閉時則關閉所有工具）、不得讀寫檔案或執行指令、不載入 MCP 與設定檔、不保存工作階段、在空的工作目錄執行。`jiezi-ask-claude` 策略 SHALL 直接請教。`jiezi` 策略在 `JIEZI_CONSULT_AUTO` 開啟（預設開啟）時 SHALL 自行判斷並請教 Claude，不需使用者逐次同意，時機為：第 1 層後驗證仍失敗、本機引擎不可用，或本機答案是空的、被長度截斷、開頭表示自己不確定或不知道。自動轉交 SHALL 先請教 Claude，失敗時改用雲端（若已開啟），再不行就回傳本機答案並註明原因。`jiezi-local` SHALL NOT 請教。
With `JIEZI_CONSULT=claude-cli`, the system SHALL be able to consult Claude through the local Claude Code CLI in headless mode, with only the web reading and web search tools (all tools off when `JIEZI_CONSULT_WEB` is off), no file access or commands, no MCP or settings loaded, no session persistence, in an empty working directory. The `jiezi-ask-claude` policy SHALL consult directly. With `JIEZI_CONSULT_AUTO` on (the default), the `jiezi` policy SHALL decide by itself to consult Claude without per-call user approval when: verification still fails after tier 1, the local engine is unavailable, or the local answer is empty, truncated, or opens by saying it is unsure or does not know. Automatic escalation SHALL try Claude first, then the cloud (if enabled), and otherwise return the local answer with the reason. `jiezi-local` SHALL NOT consult.

#### Scenario: 本機自己表示不會 / The local model says it does not know

- **WHEN** 第 0 層的答案開頭是「我不確定」
  The tier-0 answer opens with "I'm not sure"
- **THEN** 不做本機重試，直接請教 Claude；回傳 Claude 的答案，`jiezi.tier` 為 3、`jiezi.provider` 為 `claude`、`jiezi.escalation` 為 `self_reported_unsure`、`jiezi.training_use` 為 `false`
  No local retry; Claude is consulted directly, and its answer is returned with `jiezi.tier` = 3, `jiezi.provider` = `claude`, `jiezi.escalation` = `self_reported_unsure` and `jiezi.training_use` = `false`

#### Scenario: 請教失敗 / Consultation fails

- **WHEN** 自動請教時 Claude CLI 回報錯誤（例如用量額度用完），且雲端轉交關閉
  During automatic escalation the Claude CLI reports an error (for example an exhausted allowance) and cloud escalation is off
- **THEN** 回傳本機答案，`jiezi.escalation` 為 `consult_failed`，不重試
  The local answer is returned with `jiezi.escalation` = `consult_failed`, without retrying

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

### Requirement: Feedback-Only Tier

第 2 層啟用時，帶有驗證器錯誤的請求在本機重試仍未通過後，gateway SHALL 只向協助者要求回饋（錯在哪裡、如何修正），再由本機模型帶著回饋重答一次；通過驗證時 SHALL 以第 2 層回覆，未通過時 SHALL 繼續第 3 層。沒有驗證器錯誤的請求 SHALL NOT 進入第 2 層。受協助者回饋影響的答案 SHALL 標為不可用於訓練。第 2 層關閉時行為 SHALL 與原本相同。
With tier 2 on, a request with a verifier error that still fails after the local retry SHALL get feedback only from the helper and one more local attempt; passing SHALL answer at tier 2, failing SHALL continue to tier 3. Requests without a verifier error SHALL NOT enter tier 2. Answers shaped by helper feedback SHALL be marked non-trainable. With tier 2 off behaviour SHALL be unchanged.

#### Scenario: 回饋後通過 / Passing after feedback

- **WHEN** 工具呼叫兩次都缺必要參數，協助者指出缺 `city`，本機第三次補上
  A tool call misses a required argument twice, the helper names the missing `city`, and the third local attempt includes it
- **THEN** 回應的 `jiezi.tier` 是 2，答案由本機產生
  The response reports tier 2 and the answer comes from the local model

#### Scenario: 回饋後仍失敗 / Still failing

- **WHEN** 本機帶著回饋重答仍未通過驗證
  The local attempt with feedback still fails verification
- **THEN** 照原本的方式進入第 3 層
  The request proceeds to tier 3 as before


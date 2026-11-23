## ADDED Requirements

### Requirement: Cloud Escalation / 雲端轉交（修改版）

雲端轉交（第 3 層）SHALL 經由 `TrustGate.mark_untrainable()` 統一處理：設 `training_use=false`、`trust.level="unverified"＋provenance.source_channel="cloud"`、記錄 `provenance`（含 `reason`：`"needs_web"`、`"engine_unavailable"`、`"daily_cap_reached"` 等）。

Cloud escalation (tier 3) SHALL be processed through `TrustGate.mark_untrainable()`: set `training_use=false`, `trust.level="unverified"＋provenance.source_channel="cloud"`, record `provenance` (with `reason`: `"needs_web"`, `"engine_unavailable"`, `"daily_cap_reached"`, etc.).

#### Scenario: 需要上網直接轉交 / Direct escalation for web

- **WHEN** 使用者問即時天氣，本機無答案
  User asks live weather, no local answer
- **THEN** 直接請教雲端，回傳答案、**軌跡記錄 `trust.level="unverified"＋provenance.source_channel="cloud"、provenance.extra.reason="needs_web"`**
  Direct cloud consult, return answer, **trajectory record has `trust.level="unverified"＋provenance.source_channel="cloud"`, `provenance.extra.reason="needs_web"`**

#### Scenario: 引擎不可用轉交 / Escalation for engine unavailable

- **WHEN** 本機引擎無法載入
  Local engine fails to load
- **THEN** 轉交雲端、**軌跡記錄 `trust.level="unverified"＋provenance.source_channel="cloud"、provenance.extra.reason="engine_unavailable"`**
  Escalate to cloud, **trajectory record has `trust.level="unverified"＋provenance.source_channel="cloud"`, `provenance.extra.reason="engine_unavailable"`**

## MODIFIED Requirements

### Requirement: Claude Consultation

`JIEZI_CONSULT=claude-cli` 時，系統 SHALL 能透過本機 Claude Code CLI 的無頭模式請教 Claude，並 SHALL 只開放讀網頁與網路搜尋兩個工具（`JIEZI_CONSULT_WEB` 關閉時則關閉所有工具）、不得讀寫檔案或執行指令、不載入 MCP 與設定檔、不保存工作階段、在空的工作目錄執行。`jiezi-ask-claude` 策略 SHALL 直接請教。`jiezi` 策略在 `JIEZI_CONSULT_AUTO` 開啟（預設開啟）時 SHALL 自行判斷並請教 Claude，不需使用者逐次同意，時機為：第 1 層後驗證仍失敗、本機引擎不可用，或本機答案是空的、被長度截斷、開頭表示自己不確定或不知道。自動轉交 SHALL 先請教 Claude，失敗時改用雲端（若已開啟），再不行就回傳本機答案並註明原因。`jiezi-local` SHALL NOT 請教。**所有 Claude 諮詢輸出 SHALL 經由 `TrustGate.mark_untrainable()` 統一處理：設 `training_use=false`、`trust.level="unverified"＋provenance.source_channel="cloud"`、記錄 `provenance`（含 `reason`）。**

With `JIEZI_CONSULT=claude-cli`, the system SHALL be able to consult Claude through the local Claude Code CLI in headless mode, with only the web reading and web search tools (all tools off when `JIEZI_CONSULT_WEB` is off), no file access or commands, no MCP or settings loaded, no session persistence, in an empty working directory. The `jiezi-ask-claude` policy SHALL consult directly. With `JIEZI_CONSULT_AUTO` on (the default), the `jiezi` policy SHALL decide by itself to consult Claude without per-call user approval when: verification still fails after tier 1, the local engine is unavailable, or the local answer is empty, truncated, or opens by saying it is unsure or does not know. Automatic escalation SHALL try Claude first, then the cloud (if enabled), and otherwise return the local answer with the reason. `jiezi-local` SHALL NOT consult. **All Claude consultation outputs SHALL be processed through `TrustGate.mark_untrainable()`: set `training_use=false`, `trust.level="unverified"＋provenance.source_channel="cloud"`, record `provenance` (with `reason`).**

#### Scenario: 本機自己表示不會 / The local model says it does not know

- **WHEN** 第 0 層的答案開頭是「我不確定」
  The tier-0 answer opens with "I'm not sure"
- **THEN** 不做本機重試，直接請教 Claude；回傳 Claude 的答案，`jiezi.tier` 為 3、`jiezi.provider` 為 `claude`、`jiezi.escalation` 為 `self_reported_unsure`、`jiezi.training_use` 為 `false`、**軌跡記錄含 `trust.level="unverified"＋provenance.source_channel="cloud"、provenance.extra.reason="self_reported_unsure"`**
  No local retry; Claude is consulted directly, and its answer is returned with `jiezi.tier` = 3, `jiezi.provider` = `claude`, `jiezi.escalation` = `self_reported_unsure`, `jiezi.training_use` = `false`, **trajectory record contains `trust.level="unverified"＋provenance.source_channel="cloud"`, `provenance.extra.reason="self_reported_unsure"`**

#### Scenario: 請教失敗 / Consultation fails

- **WHEN** 自動請教時 Claude CLI 回報錯誤（例如用量額度用完），且雲端轉交關閉
  During automatic escalation the Claude CLI reports an error (for example an exhausted allowance) and cloud escalation is off
- **THEN** 回傳本機答案，`jiezi.escalation` 為 `consult_failed`，不重試
  The local answer is returned with `jiezi.escalation` = `consult_failed`, without retrying

---

### Requirement: Feedback-Only Tier

第 2 層啟用時，帶有驗證器錯誤的請求在本機重試仍未通過後，gateway SHALL 只向協助者要求回饋（錯在哪裡、如何修正），再由本機模型帶著回饋重答一次；通過驗證時 SHALL 以第 2 層回覆，未通過時 SHALL 繼續第 3 層。沒有驗證器錯誤的請求 SHALL NOT 進入第 2 層。受協助者回饋影響的答案 SHALL 標為不可用於訓練。第 2 層關閉時行為 SHALL 與原本相同。**受協助者影響的答案 SHALL 經由 `TrustGate.mark_untrainable()` 處理，`reason` 為 `"cloud_hint"` 或 `"helper_feedback"`。**

With tier 2 on, a request with a verifier error that still fails after the local retry SHALL get feedback only from the helper and one more local attempt; passing SHALL answer at tier 2, failing SHALL continue to tier 3. Requests without a verifier error SHALL NOT enter tier 2. Answers shaped by helper feedback SHALL be marked non-trainable. With tier 2 off behaviour SHALL be unchanged. **Answers shaped by helper feedback SHALL be processed through `TrustGate.mark_untrainable()`, with `reason` = `"cloud_hint"` or `"helper_feedback"`.**

#### Scenario: 回饋後通過 / Passing after feedback

- **WHEN** 工具呼叫兩次都缺必要參數，協助者指出缺 `city`，本機第三次補上
  A tool call misses a required argument twice, the helper names the missing `city`, and the third local attempt includes it
- **THEN** 回應的 `jiezi.tier` 是 2，答案由本機產生、**軌跡記錄 `trust.level="unverified"＋provenance.source_channel="cloud"、provenance.extra.reason="cloud_hint"`**
  The response reports tier 2 and the answer comes from the local model, **trajectory record has `trust.level="unverified"＋provenance.source_channel="cloud"`, `provenance.extra.reason="cloud_hint"`**

#### Scenario: 回饋後仍失敗 / Still failing

- **WHEN** 本機帶著回饋重答仍未通過驗證
  The local attempt with feedback still fails verification
- **THEN** 照原本的方式進入第 3 層
  The request proceeds to tier 3 as before

---

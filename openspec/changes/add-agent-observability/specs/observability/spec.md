## ADDED Requirements

### Requirement: Unified Observability Fields / 統一觀測欄位

系統 SHALL 定義跨 `trajectory`、`audit`、`agent`、`gateway`、`process`、`dashboard`、`stats` 的統一欄位表（欄位名、型別、來源、敏感標記、遮罩規則；欄位命名參考 OpenTelemetry GenAI 語意慣例，並記錄所參考的版本），並提供 `observability.normalize(record)` 把各模組的既有紀錄轉成統一欄位。既有寫入 `var/` 的欄位名稱 SHALL NOT 改名（狀態頁、統計、缺口報告、訓練資料匯出都依賴它們）；統一欄位是讀取端的檢視。
The system SHALL define a unified field table (names informed by the OpenTelemetry GenAI conventions, with the referenced version recorded) and an `observability.normalize(record)` that maps each module's existing records onto it. Field names already written under `var/` SHALL NOT be renamed; the unified fields are a read-side view.

#### Scenario: 欄位一致性檢查 / Field consistency check

- **WHEN** 測試把七個模組各自的輸出紀錄經 `normalize()` 轉換，比對同一概念的欄位
  A test normalises records from all seven modules and compares fields for the same concept
- **THEN** 欄位名稱、型別、值域完全相同
  Names, types and value domains match

#### Scenario: 舊紀錄照常可讀 / Old records still readable

- **WHEN** 讀取本變更之前寫入的軌跡（`final_tier`、`status`、`tool_filter` 沒有 `dropped`）
  Trajectories written before this change are read
- **THEN** `normalize()` 補出 `tier`、`terminal_state`、`tool_filter.dropped = original - kept`；原檔不被改寫
  normalize() derives the unified fields; the files are not rewritten

### Requirement: Standardized Escalation Reasons / 轉交原因碼標準化

統一欄位 `escalation_reason` SHALL 只取 `none`、`verification_failed`、`daily_cap_reached`、`self_reported_unsure`、`needs_web`、`local_unavailable`、`context_too_large`、`consult_failed`、`consultation_timeout`、`cli_unavailable`、`policy` 之一；既有的 `jiezi.escalation` 與 `stats` 複合鍵（例如 `claude:policy`）SHALL 由 `normalize()` 對應，不改寫入端。未知值 SHALL 對應為 `other` 並保留原值於 `escalation_reason_raw`。
The unified `escalation_reason` SHALL take one of the listed codes; existing `jiezi.escalation` values and `stats` composite keys SHALL be mapped by `normalize()` without changing writers. Unknown values map to `other` with the raw value kept.

#### Scenario: 驗證失敗且雲端關閉 / Verification fails with cloud off

- **WHEN** 第 1 層驗證失敗、雲端轉交關閉
  Tier 1 fails verification and cloud escalation is off
- **THEN** `escalation_reason = "verification_failed"`（不是 `daily_cap_reached`）
  The reason is verification_failed

#### Scenario: 自動諮詢失敗 / Automatic consultation fails

- **WHEN** 自動請教 Claude 遇到 CLI 逾時、不可用或額度用完
  Automatic consultation hits a CLI timeout, unavailability or an exhausted allowance
- **THEN** `escalation_reason` 為 `consultation_timeout`、`cli_unavailable` 或 `consult_failed` 之一
  The reason is one of the three codes

### Requirement: Agent Terminal States and Fail-Closed Recording / 代理終態與 fail-closed 紀錄

代理迴圈結束時 SHALL 記錄 `terminal_state`（`completed`／`failed`／`aborted`／`fail_closed`）；觸發 fail-closed（步數或呼叫數或 token 超限 `budget_exceeded`、疑似注入 `injection_detected`、同一請求連續 3 次驗證失敗 `verification_loop`）時 SHALL 立即停止並在稽核、軌跡與回應的 `jiezi` 欄位記錄 `fail_closed: true` 與 `fail_closed_reason`。`effective_budget` SHALL 只有一個來源（`limits.EFFECTIVE_LIMITS` 經 `cap_budget`）。
The agent loop SHALL record a terminal state; on fail-closed (budget exceeded, suspected injection, or three consecutive verification failures) it SHALL stop at once and record `fail_closed` and its reason in the audit, the trajectory and the `jiezi` response field. `effective_budget` SHALL have a single source.

#### Scenario: 預算超限 / Budget exceeded

- **WHEN** 迴圈到達 `max_steps` 仍未完成
  The loop reaches `max_steps` unfinished
- **THEN** 停止，`terminal_state = "fail_closed"`、`fail_closed_reason = "budget_exceeded"`，寫入稽核與軌跡
  It stops and records fail_closed with budget_exceeded

#### Scenario: 工具結果疑似注入 / Suspected injection in a tool result

- **WHEN** 工具結果被判定疑似提示注入
  A tool result is flagged as a suspected injection
- **THEN** 停止，`fail_closed_reason = "injection_detected"`
  It stops with injection_detected

#### Scenario: 預算單一來源 / Single budget source

- **WHEN** 測試比較 `limits.EFFECTIVE_LIMITS`、`contract.budget.effective`、迴圈的 `effective_budget`
  A test compares the three budget values
- **THEN** 六個鍵（`max_steps`、`max_calls_per_step`、`result_chars`、`old_result_chars`、`tools_budget`、`call_timeout_s`）完全相同
  All six keys are identical

### Requirement: Masking Rules / 遮罩規範

系統 SHALL 提供四條集中化遮罩規則，所有寫入 `var/` 的記錄在序列化前 SHALL 經 `_scrub_all()` 處理。

The system SHALL provide four centralized masking rules; all records written to `var/` SHALL pass through `_scrub_all()` before serialization.

| 規則 / Rule | 適用對象 / Applies To | 行為 / Behavior |
|------------|----------------------|----------------|
| `_scrub_text()` | 契約欄位、工具參數字串、使用者訊息 | 替換 `sk-`、`ghp_`、`gho_`、`glpat-`、`xoxb-`、`xoxp-`、AWS AK、GCP SA、JWT、私鑰標頭等模式為 `[REDACTED]`；保留 JSON 結構 |
| `_scrub_tool_result()` | 工具呼叫結果、trajectory tier 答案 | 只保留 `tool`、`ok`、`result_chars`、`error_type`、`latency_ms`；移除檔案內容、完整輸出 |
| `_scrub_messages()` | `request_messages`、`conversation` | system prompt 僅保留 role；user/assistant 訊息截前 200 字並套用 `_scrub_text()` |
| `_scrub_all()` | 完整記錄物件 | 遞迴走訪，依 `UNIFIED_FIELDS` 敏感標記套用上述規則；非敏感欄位保持不變 |

#### Scenario: 紅隊注入測試 / Red-team injection test

- **WHEN** 測試向工具參數、契約欄位、user 訊息注入 `sk-abcdef123456`、`.env` 內容、私鑰 PEM 開頭行（測試中於執行時組字串，不寫進檔案）、檔案路徑 `/home/user/.ssh/id_rsa`。/ **WHEN** a test injects secret patterns into tool args, contract fields, user messages.
- **THEN** 寫入 `var/trajectories/`、`var/audit/` 的 JSONL 經 `_scrub_all()` 後，無明文敏感資訊；結構完整、非敏感欄位正常。/ **THEN** written JSONL files contain no plaintext secrets; structure intact; non-sensitive fields normal.

---

### Requirement: Fail-Closed State Machine / Fail-Closed 狀態機

系統 SHALL 定義包含 `fail_closed` 終態的狀態機，`fail_closed` 可在任何階段觸發，觸發後不再嘗試後續層級，且 SHALL 在 trajectory、agent loop、gateway 回應三處同步記錄。

The system SHALL define a state machine including `fail_closed` terminal state; `fail_closed` MAY trigger at any phase, after which no further tiers are attempted, and SHALL be recorded synchronously in trajectory, agent loop, and gateway response.

#### 狀態 / States

| 狀態 / State | 類型 / Type | 說明 / Description |
|------------|------------|-------------------|
| `request_received` | transient | 金鑰驗證通過 |
| `tier_0_local` | active | 本機回答 |
| `verification` | active | 執行期驗證 |
| `tier_1_retry` | active | 本機重試 |
| `tier_2_feedback` | active | 取得回饋重答 |
| `escalation_claude` | active | 諮詢 Claude CLI |
| `escalation_cloud` | active | 轉交雲端 |
| `completed` | terminal | 正常完成 |
| `failed` | terminal | 驗證失敗且無後續路徑 |
| `aborted` | terminal | 客戶端中斷/取消 |
| `fail_closed` | terminal | **新增**：預算超限/注入偵測/驗證迴圈/諮詢逾時/雲端不可用/每日上限 |

#### 合法轉移 / Valid Transitions

```
request_received → tier_0_local
tier_0_local → verification
verification → completed (passed)
verification → tier_1_retry (failed & retryable)
verification → escalation_claude (failed & no tier2)
tier_1_retry → verification
verification → tier_2_feedback (failed & tier2 enabled)
verification → escalation_claude (failed & tier2 disabled/used)
tier_2_feedback → local_reanswer → verification
verification → completed (passed)
verification → escalation_claude (failed)
escalation_claude → claude_answer → verification
verification → completed (passed)
verification → escalation_cloud (failed & cloud enabled)
escalation_cloud → cloud_answer → completed
```

#### Fail-Closed 觸發點 / Fail-Closed Trigger Points

| 階段 / Phase | 觸發條件 / Condition | 原因碼 / Reason Code |
|------------|---------------------|---------------------|
| `tier_0_local` | 步數/呼叫數/token 超過 `EFFECTIVE_LIMITS` | `budget_exceeded` |
| `tier_0_local`/`tier_1_retry`/`tier_2_feedback` | `injection_suspected == true` | `injection_detected` |
| `verification` (重複 N 次，建議 3) | 驗證持續失敗、進入迴圈 | `verification_loop` |
| `escalation_claude` | Claude CLI 逾時/不可用/額度用罄 | `consultation_timeout` / `cli_unavailable` |
| `escalation_cloud` | 雲端不可用/每日上限 | `cloud_unavailable` / `daily_cap` |

#### 記錄要求 / Recording Requirements

- `fail_closed == true` 寫入 trajectory、`agent.loop.info`、gateway `jiezi` 回應
- `fail_closed_reason` 為上表原因碼之一，必填
- `/health` 暴露 `fail_closed_count_24h`、`last_fail_closed_reason`

#### Scenario: 預算超限觸發 Fail-Closed / Budget exceeded triggers fail_closed

- **WHEN** agent 迴圈第 6 步仍未完成，`max_steps=6` 已達上限。/ **WHEN** agent loop reaches step 6, `max_steps=6` exhausted.
- **THEN** 迴圈停止，`terminal_state = "fail_closed"`，`fail_closed_reason = "budget_exceeded"`，寫入 trajectory、loop info、gateway 回應。/ **THEN** loop stops, terminal_state is fail_closed, reason recorded in all three places.

---

### Requirement: Budget Alignment Rules / 預算對齊規則

系統 SHALL 在 `observability` 規格中明確列出 `task budget` (6 項) 與 `facts budgets` (cpu/vram) 的對應關係，註明為「參考關係，不強制綁定」。

The system SHALL document the alignment between task budget (6 items) and facts budgets (cpu/vram) as "reference only, not enforced".

| Agent Budget (EFFECTIVE_LIMITS) | Facts Budget | 對齊關係 / Alignment |
|--------------------------------|-------------|---------------------|
| `max_steps=6` | — | 固定上限 |
| `max_calls_per_step=3` | — | 固定上限 |
| `result_chars=2500` | `vram.total_mib` | 參考：VRAM < 4GB 建議 1500，**不強制** |
| `old_result_chars=400` | — | 固定 |
| `tools_budget=2600` | `vram.total_mib` | 參考：VRAM < 4GB 建議 1500，**不強制** |
| `call_timeout_s=120` | `cpu.usable_threads` | 參考：threads ≥ 16 建議 60s，**不強制** |

#### Scenario: 規格查閱 / Spec lookup

- **WHEN** 開發者閱讀 `observability` 規格的預算對齊表。/ **WHEN** a developer reads the budget alignment table in observability spec.
- **THEN** 明確看到六項對應、標註「參考關係，不強制綁定」、預留 `budget_policy` 擴充點。/ **THEN** six mappings visible, marked as reference only, extension point noted.
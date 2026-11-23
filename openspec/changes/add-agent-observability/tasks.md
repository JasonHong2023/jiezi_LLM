# add-agent-observability 任務清單 / Tasks

## Phase 0: 準備 / Preparation

- [x] **T0.1** 讀取 dev-plan.md §15.5 A8、rules_20261114.md、既有規格與變更參考
- [x] **T0.2** 掃描現況：audit、trajectory、agent、gateway、process、dashboard、stats、tool_filter、contract、limits
- [x] **T0.3** 建立 `openspec/changes/add-agent-observability/` 目錄結構
- [x] **T0.4** 撰寫 `proposal.md`（含分類判定、現成方案、現況盤點、變更範圍、開放問題、驗收標準）
- [x] **T0.5** 撰寫 `design.md`（統一欄位表、遮罩規則、狀態機、預算對齊、模組對應、規格 Delta、驗證矩陣、優先序）
- [ ] **T0.6** 撰寫 `tasks.md`（本檔案）

## Phase 1: 核心模組建立 / Core Observability Module

### 1.1 統一欄位常數 / Unified Field Constants

- [ ] **T1.1** 建立 `src/jiezi/observability/__init__.py`，匯出所有公用 API
- [ ] **T1.2** 建立 `src/jiezi/observability/fields.py`：
  - `UNIFIED_FIELDS: dict[str, dict]` — 欄位定義（型別、預設值、是否必填、敏感標記、遮罩規則名）
  - `TERMINAL_STATES = ("completed", "failed", "aborted", "fail_closed")`
  - `ESCALATION_REASONS = ("none", "verification_failed", "daily_cap_reached", "self_reported_unsure", "consult_failed", "needs_web", "local_unavailable")`
  - `FAIL_CLOSED_REASONS = ("budget_exceeded", "injection_detected", "verification_loop", "consultation_timeout", "cli_unavailable", "cloud_unavailable", "daily_cap")`
  - `PROVIDERS = ("local", "claude", "cloud")`
  - `POLICIES = ("jiezi", "jiezi-local", "jiezi-cloud", "jiezi-ask-claude")`
- [ ] **T1.3** 單元測試：`tests/test_observability_fields.py` 驗證常數完整性、值域

### 1.2 遮罩函數 / Masking Functions

- [ ] **T1.4** 建立 `src/jiezi/observability/masking.py`：
  - `_SECRET_PATTERNS: list[re.Pattern]` — `sk-`、`ghp_`、`gho_`、`glpat-`、`xoxb-`、`xoxp-`、AWS AK、GCP SA、JWT、私鑰標頭等
  - `_scrub_text(text: str) -> str`：替換秘密模式為 `[REDACTED]`、保留結構
  - `_scrub_tool_result(result: dict) -> dict`：只保留 `tool`、`ok`、`result_chars`、`error_type`、`latency_ms`
  - `_scrub_messages(messages: list[dict]) -> list[dict]`：system 只保留 role、user/assistant 截 200 字並遮罩
  - `_scrub_all(record: dict) -> dict`：遞迴處理整筆記錄，依 `UNIFIED_FIELDS` 敏感標記決定是否處理
- [ ] **T1.5** 單元測試：`tests/test_observability_masking.py` 覆蓋各模式、巢狀結構、非字串值

### 1.3 狀態機 / State Machine

- [ ] **T1.6** 建立 `src/jiezi/observability/state.py`：
  - `TerminalState` (StrEnum)：四態
  - `FailClosedReason` (StrEnum)：七因
  - `EscalationReason` (Str Enum)：七因
  - `TransitionValidator`：`can_transition(from_state, to_state, context) -> bool`、非法轉移丟例外
  - `record_fail_closed(record: dict, reason: FailClosedReason) -> dict`：注入 `fail_closed=true`、`fail_closed_reason`
- [ ] **T1.7** 單元測試：`tests/test_observability_state.py` 合法/非法轉移、`fail_closed` 注入

### 1.4 預算工具 / Budget Utilities

- [ ] **T1.8** 修改 `src/jiezi/agent/limits.py`：
  - `EFFECTIVE_LIMITS` 維持 `MappingProxyType` 不可變
  - 新增 `to_budget_dict() -> dict[str, int]` 回傳六鍵標準字典
  - 新增 `cap_budget(requested: dict) -> dict`：對照六鍵取 min、回傳 effective
- [ ] **T1.9** 單元測試：`tests/test_limits.py` 驗證不可變、`to_budget_dict()`、`cap_budget()` 正確性

## Phase 2: 寫入端對齊 / Writer-Side Alignment

### 2.1 Trajectory Writer

- [ ] **T2.1** 修改 `src/jiezi/runtime/trajectory.py`：
  - `TrajectoryWriter.write()` 產出 `rec` 結構對齊 `UNIFIED_FIELDS`
  - `tool_filter` 物件含 `original`、`kept`、`dropped`、`stage`、`names`
  - `status` → `terminal_state` 值域映射：`ok→completed`、`agent_error→failed`、`cancelled→aborted`、新增 `fail_closed`
  - 新增 `fail_closed`、`fail_closed_reason`、`training_use`（Claude 諮詢 false、其他 null）
  - 寫入前呼叫 `_scrub_all(rec)`
- [ ] **T2.2** 單元測試：`tests/test_trajectory_unified.py` 驗證輸出欄位、值域、遮罩

### 2.2 Agent Audit Log

- [ ] **T2.3** 修改 `src/jiezi/agent/audit.py`：
  - `AuditLog.log_call()` entry 欄位對齊：`request_id`、`timestamp`、`tool`、`arguments`（遮罩）、`allowed`、`result_summary`（`_scrub_tool_result`）、`terminal_state`（統一值域）
  - 寫入前呼叫 `_scrub_all(entry)`
- [ ] **T2.4** 單元測試：`tests/test_agent_audit_unified.py`

### 2.3 Tool Filter Recording

- [ ] **T2.5** 修改 `src/jiezi/runtime/tool_filter.py`：
  - `select()` 回傳 `{"original": int, "kept": int, "dropped": int, "stage": str, "names": list[str]}`，`dropped = original - kept`
  - `ladder()` 對齊回傳結構
- [ ] **T2.6** 修改 `src/jiezi/runtime/gateway.py`：
  - `_filter_tools()` 使用新 `select()` 回傳，寫入 `rec["tool_filter"]`
- [ ] **T2.7** 單元測試：`tests/test_tool_filter_unified.py`、`tests/test_gateway_tool_filter.py`

## Phase 3: 核心邏輯對齊 / Core Logic Alignment

### 3.1 Agent Loop

- [ ] **T3.1** 修改 `src/jiezi/agent/loop.py`：
  - `run()` 回傳 `info` 含 `terminal_state`（統一值域）、`effective_budget`（來自 `limits.to_budget_dict()` 經 `cap_budget()`）、`fail_closed`、`fail_closed_reason`
  - 預算檢查：步數/呼叫數/token 超限時觸發 `fail_closed(reason="budget_exceeded")`
  - 注入檢查：`injection_suspected` 為真時觸發 `fail_closed(reason="injection_detected")`
  - 驗證迴圈超過 N 次（建議 3）觸發 `fail_closed(reason="verification_loop")`
- [ ] **T3.2** 單元測試：`tests/test_loop_fail_closed.py` 覆蓋三種觸發路徑

### 3.2 Contract Normalization

- [ ] **T3.3** 修改 `src/jiezi/agent/contract.py`：
  - `normalize()` 回傳 `budget.effective = limits.cap_budget(budget.requested)`
  - `effective_tools` 取交集、未知拒絕
  - 輸出欄位名對齊統一表（`budget_requested`、`budget_effective`）
- [ ] **T3.4** 單元測試：`tests/test_contract_budget_cap.py`

## Phase 4: 回應端對齊 / Response-Side Alignment

### 4.1 Gateway Response

- [ ] **T4.1** 修改 `src/jiezi/runtime/gateway.py`：
  - `jiezi` 回應物件欄位對齊統一表：`tier`、`provider`、`model`、`latency_s`、`tokens`、`cost`、`verification`、`escalation_reason`、`tool_filter`（完整）、`fail_closed`、`fail_closed_reason`
  - `training_use` 同步
- [ ] **T4.2** 單元測試：`tests/test_gateway_jiezi_response.py`

## Phase 5: 讀取端對齊 / Reader-Side Alignment

### 5.1 Process View

- [ ] **T5.1** 修改 `src/jiezi/runtime/process.py`：
  - `steps()` 輸出每步含 `tier`、`provider`、`verification`、`latency_s`、`tokens`、`tool_filter`、`terminal_state`、`fail_closed`
  - `kind`/`label` 映射標準化
- [ ] **T5.2** 單元測試：`tests/test_process_steps.py`

### 5.2 Dashboard Metrics

- [ ] **T5.3** 修改 `src/jiezi/runtime/dashboard.py`：
  - 指標來源對齊新欄位：`achievement_rate`（completed/total）、`local_handling_rate`（tier 0/1 完成 / total）、`speed_tps`（加權平均）、`fail_closed_rate`（fail_closed/total）
  - `compute()` 回傳含 `fail_closed_count`、`fail_closed_reasons` 分布
- [ ] **T5.4** 單元測試：`tests/test_dashboard_metrics.py`

### 5.3 Stats Aggregation

- [ ] **T5.5** 修改 `src/jiezi/runtime/stats.py`：
  - `escalation_reason` 使用標準化值域
  - `daily_summary()` 輸出含 `fail_closed` 統計
- [ ] **T5.6** 單元測試：`tests/test_stats_escalation.py`

### 5.4 CLI Dashboard Script

- [ ] **T5.7** 修改 `scripts/jiezi_dashboard.py`（或同名模組）：
  - 讀取新欄位、顯示 `fail_closed` 狀態與原因分布
  - 選項 `--include-fail-closed` 顯示詳細
- [ ] **T5.8** 手動驗證：執行腳本確認輸出正確

## Phase 6: 規格 Delta / Spec Delta

### 6.1 ADDED: observability/spec.md

- [ ] **T6.1** 撰寫 `openspec/changes/add-agent-observability/specs/observability/spec.md`：
  - 統一欄位表（Markdown 表格）
  - 遮罩規範（四條規則）
  - 狀態機（Mermaid + 文字）
  - 預算對齊規則（參考關係表）
  - Scenario：紅隊測試驗證遮罩、fail_closed 觸發、預算 cap

### 6.2 MODIFIED: trajectory/spec.md

- [ ] **T6.2** 撰寫 `openspec/changes/add-agent-observability/specs/trajectory/spec.md`：
  - `status` → `terminal_state` 值域變更
  - 新增 `fail_closed`、`fail_closed_reason`、`tool_filter.dropped`
  - `training_use` 語意澄清 Scenario

### 6.3 MODIFIED: audit/spec.md

- [ ] **T6.3** 撰寫 `openspec/changes/add-agent-observability/specs/audit/spec.md`：
  - Agent audit entry 欄位對齊
  - 遮罩要求 Scenario

### 6.4 MODIFIED: agent/spec.md

- [ ] **T6.4** 撰寫 `openspec/changes/add-agent-observability/specs/agent/spec.md`：
  - `terminal_state` 值域
  - `effective_budget` 來源
  - `fail_closed` 觸發條件 Scenario

### 6.5 MODIFIED: gateway/spec.md

- [ ] **T6.5** 撰寫 `openspec/changes/add-agent-observability/specs/gateway/spec.md`：
  - `jiezi` 回應欄位對齊
  - `tool_filter` 完整
  - `fail_closed` 回應欄位

### 6.6 MODIFIED: escalation/spec.md

- [ ] **T6.6** 撰寫 `openspec/changes/add-agent-observability/specs/escalation/spec.md`：
  - `escalation_reason` 標準化值域
  - 對齊 `stats.reasons`

### 6.7 ADDED: dashboard/spec.md

- [ ] **T6.7** 撰寫 `openspec/changes/add-agent-observability/specs/dashboard/spec.md`：
  - 讀取介面規格
  - 指標定義
  - 匯出格式

### 6.8 ADDED: process/spec.md

- [ ] **T6.8** 撰寫 `openspec/changes/add-agent-observability/specs/process/spec.md`：
  - `steps()` 輸出結構
  - 穩定介面承諾

## Phase 7: 測試與驗證 / Test & Validation

### 7.1 整合測試 / Integration Tests

- [ ] **T7.1** `tests/test_observability_integration.py`：端到端流程驗證統一欄位
- [ ] **T7.2** `tests/test_fail_closed_all_paths.py`：7 種觸發路徑全覆蓋
- [ ] **T7.3** `tests/test_redteam_masking.py`：紅隊注入測試（金鑰、.env、私鑰、路徑）

### 7.2 規格驗證 / Spec Validation

- [ ] **T7.4** 執行 `openspec validate add-agent-observability --strict` → 通過
- [ ] **T7.5** 執行 `openspec validate --all --strict` → 通過
- [ ] **T7.6** 執行 `git diff --check` → 乾淨輸出

### 7.3 全量測試 / Full Test Suite

- [ ] **T7.7** 執行 `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` → ≥ 759 通過、0 失敗
- [ ] **T7.8** 比對基準：確認無回歸、無新增錯誤

## Phase 8: 文檔同步 / Documentation Sync

- [ ] **T8.1** 更新 `docs/dev-plan.md` A8 狀態為完成
- [ ] **T8.2** 撰寫 `WORKER_REPORT.md`：
  - 變更檔案清單
  - 驗證指令與結果
  - 未完成項目與開放問題

## 夜間/持續項目 / Nightly & Continuous

- [ ] **TN.1** CI 加入 `openspec validate --all --strict` 檢查
- [ ] **TN.2** CI 加入紅隊遮罩測試
- [ ] **TN.3** 監控 `fail_closed` 率趨勢（dashboard 指標）

---

## 任務依賴圖 / Dependency Graph

```
T0.1-T0.6 (完成)
    │
    ├─► T1.1-T1.3 (fields)
    ├─► T1.4-T1.5 (masking)
    ├─► T1.6-T1.7 (state)
    └─► T1.8-T1.9 (limits) ──► T3.3-T3.4 (contract)
                                 │
    T2.1-T2.2 (trajectory) ◄────┤
    T2.3-T2.4 (audit) ◄─────────┤
    T2.5-T2.7 (tool_filter) ◄───┤
                                 │
    T3.1-T3.2 (loop) ◄──────────┤
                                 │
    T4.1-T4.2 (gateway) ◄───────┤
                                 │
    T5.1-T5.8 (readers) ◄───────┘
                                 │
    T6.1-T6.8 (specs) ◄─────────┘
                                 │
    T7.1-T7.8 (tests) ◄─────────┘
                                 │
    T8.1-T8.2 (docs) ◄──────────┘
```
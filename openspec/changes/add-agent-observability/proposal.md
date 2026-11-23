# add-agent-observability 提案 / Proposal

> **主控更正（2026-11-23）**：W6 兩輪草稿的 MODIFIED 需求都刪改了主規格原文（英文句、Scenario 內容），且 `Claude Consultation`、`Training-Use Flag` 與 A5 `add-agent-trust-gate` 重疊（後歸檔者會覆蓋前者）。改為**不修改任何既有主規格需求**：統一欄位定為讀取端檢視（`observability.normalize()`），**既有寫入 `var/` 的欄位名稱不改名**（原草稿把 `final_tier`→`tier`、`status`→`terminal_state` 等直接改名，會弄壞狀態頁、統計、缺口報告與訓練資料匯出）；原 MODIFIED 的新增內容併入 observability 的 ADDED 需求（Standardized Escalation Reasons、Agent Terminal States and Fail-Closed Recording）；草稿另 ADDED 的 `Task Contract Schema` 與已完成的 `add-agent-contract`（agent-contract 能力）重複，已刪除。下文表格中的「原欄位 → 新欄位」一律理解為 normalize 的對應，不是改名。OQ 依建議定案（OQ1 命名參考 OTel GenAI 不引入 SDK；OQ2–OQ5 依設計）。

## 1. 概述 / Overview

依開發計畫 §15.5 A8：統一 `audit`、`trajectory`、`process`、`dashboard` 欄位；`task budget` 與 `facts budgets` 對齊；`fail-closed` 狀態。驗收：「狀態頁可看到 agent on/off、成果、轉交、工具、資源；不記敏感內容」。

Per dev-plan §15.5 A8: unify fields across `audit`, `trajectory`, `process`, `dashboard`; align `task budget` with `facts budgets`; enforce `fail-closed` state. Acceptance: "status page shows agent on/off, outcomes, escalations, tools, resources; no sensitive content logged."

---

## 2. 分類判定 / Category Classification

| 判定維度 / Dimension | 結果 / Result | 理由 / Rationale |
|---------------------|--------------|-----------------|
| 會改變外部世界嗎？ / Changes external world? | **否 / No** | 僅整理既有觀測欄位、對齊預算、補齊狀態機；不新增寫入、shell、網路工具 |
| 需要新權限嗎？ / Needs new permissions? | **否 / No** | 只讀既有 `var/` 目錄、既有 trajectory、audit 檔案 |
| 要被不同客戶端重用嗎？ / Reused by multiple clients? | **是 / Yes** | 狀態頁（Desktop App TUI/Web）、Hermes/OpenCode、CLI、`scripts/jiezi dashboard` 皆需同一組欄位 |
| 只是「怎麼做」的知識嗎？ / Just procedural knowledge? | **否 / No** | 涉及資料結構標準化、跨模組欄位對齊、規格變更 |

**結論 / Conclusion**：**核心／既有模組** — 屬於既有 `trajectory`、`audit`、`gateway`、`agent` 能力的強化與統一，走 R4 流程（OpenSpec proposal → design → tasks → implement），不歸類為 SKILL 或 MCP。

---

## 3. 現成方案搜尋 / Existing Solutions Survey

> 依 web-research.md §A8（主控 2026-11-23 上網查證）
> Per web-research.md §A8 (Controller 2026-11-23 investigation)

| 方案 / Solution | 適用性 / Fit | 採納狀態 / Adoption |
|----------------|-------------|---------------------|
| **OpenTelemetry GenAI semantic conventions** | 定義 LLM 追蹤的標準屬性（`gen_ai.system`、`gen_ai.request.model`、`gen_ai.usage.*`、`gen_ai.operation.name` 等）。至 2026-07 全部 `gen_ai.*` 仍為 Development（非 Stable），只有 `error.type`、`server.address`、`server.port` 是 Stable；v1.42.0（2026-06-12）起移到獨立 repo `semantic-conventions-genai`。有 agent span（`create_agent`、`invoke_agent`）。 | **採納欄位命名參考，不引入 SDK**：芥子欄位命名參考 gen_ai.*（例如 `gen_ai.operation.name`、`gen_ai.request.model`、`gen_ai.usage.input_tokens`），但不引入 OTel SDK；匯出 OTLP 留作日後選項。來源：https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/ 、https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke |
| **Langfuse** | 開源 LLM 觀測平台，支援 traces、spans、generations、scores、user feedback；有 Python SDK。核心 MIT、可自架，但 ee/ 目錄另授權（audit logging、data retention 屬企業版）；2026-01 併入 ClickHouse；自架需 Postgres＋ClickHouse 等服務。 | **不採用**：違反「不新增服務／占用硬體」。來源：https://langfuse.com/docs/open-source |
| **OpenLLMetry** | 基於 OpenTelemetry 的 LLM 觀測儀器化，自動捕獲 OpenAI/Azure/Anthropic 等呼叫。Apache-2.0 的 OTel instrumentation，不含檢視介面；用自己的語意慣例而非 OTel GenAI。 | **不採用**：不新增相依與服務；僅參考其自動儀器化覆蓋範圍。來源：https://github.com/traceloop/openllmetry/issues/3460 |

**結論**：核心內建、不新增相依與服務；欄位名對齊 OTel GenAI（Development 狀態，需記版本）；若日後要外送，另開 change 做 OTLP 匯出並做 OSV／授權掃描。

---

## 4. 現況盤點 / Current State Survey

### 4.1 欄位不一致總表 / Field Inconsistency Summary

| 概念 / Concept | trajectory.py | agent/audit.py | agent/loop.py (info) | agent/contract.py | runtime/process.py | runtime/dashboard.py | runtime/stats.py | runtime/tool_filter.py |
|---------------|--------------|----------------|----------------------|-------------------|-------------------|---------------------|------------------|------------------------|
| **請求 ID** | `id` | — | — | — | — | — | — | `original` (tool count) |
| **時間戳** | `at` (ISO) | `at` (ISO) | `started_at`, `terminal_at` (ISO) | — | `t_s` (相對秒數) | — | `at` (日級) | — |
| **策略/模式** | `policy` | — | — | — | — | `policy` | `policy` | — |
| **終態** | `status` (`ok`/`agent_error`/`cancelled`) | — | `terminal_state` (`completed`/`failed`/`aborted`) | — | — | `final_tier` | — | `stage` (`full`/`short_descriptions`/`protected_only`/`exhausted`/`none_relevant`) |
| **層級** | `final_tier` (0–3) | — | — | — | — | `final_tier` | — | — |
| **驗證結果** | tier 內 `verification.status` | — | — | — | `check` (`通過`/`沒通過`) | — | — | — |
| **轉交原因** | `jiezi.escalation` | — | — | — | `why` | — | `reasons` (`claude:...`/`cloud:...`) | — |
| **提供者** | tier 內 `provider` (`claude`/`cloud`) | — | — | — | `_who()` 回傳中文標籤 | — | `reasons` key 前綴 | — |
| **工具清單** | `tool_filter.{original,kept,stage,names}` | entry 中工具名 | `effective_tools` | `allowed_tools`/`effective_tools` | `tool` 欄位 | — | — | `ladder()` 回傳 `kept` (names) |
| **預算/上限** | — | — | `effective_budget` | `budget.{requested,effective}` | — | — | — | — |
| **延遲/速度** | `jiezi.latency_s`, `jiezi.tps`, tier 內 `tps` | — | — | — | `t_s` | `tps` | — | — |
| **資源/成本** | `jiezi.cloud.{tokens,cost}` | — | — | — | — | — | — | — |
| **敏感內容遮罩** | `training_use`、`injection.suspected` | `row.pop("content")` | `suspected` | `_scrub()` | — | — | — | `_clean_text()` |
| **契約** | `rec["agent"].contract` | — | `contract` | 正規化輸出 | — | — | — | `contract_tools` 參數 |

### 4.2 關鍵不一致 / Key Inconsistencies

1. **終態命名分歧**：`trajectory.status` (`ok`/`agent_error`/`cancelled`) vs `agent.loop.info.terminal_state` (`completed`/`failed`/`aborted`) — 同一概念三組值
2. **預算欄位分散**：`contract.budget.{requested,effective}`、`loop.info.effective_budget`、`limits.EFFECTIVE_LIMITS` — 三處定義、兩處複製
3. **工具篩選記錄**：`trajectory.rec.tool_filter` 有 `{original,kept,stage,names}`，但 `tool_filter.ladder()` 回傳 `kept` 為名稱陣列、而 `select()` 回傳 `kept` 為名稱、`dropped` 為計數
4. **時間戳格式**：`at` (ISO 完整) vs `started_at`/`terminal_at` (ISO) vs `t_s` (相對秒數, float) vs `dashboard` 只取日期
5. **轉交原因編碼**：`jiezi.escalation` (單值) vs `stats.reasons` (`claude:policy`/`cloud:verification_failed` 等複合鍵)
6. **缺失 `facts budgets` 對齊**：agent 的 `tools_budget` (token)、`call_timeout_s` (秒) 與 `facts.json` 的 `budgets.cpu.usable_threads`、`budgets.vram.total_mib` 完全無關聯
7. **Process 衍生欄位**：`process.steps()` 產出 `kind`/`label`/`items`，與 trajectory 原始欄位不對應，前端若要對齊需自行映射

---

## 5. 變更範圍 / Scope

### 5.1 需修改的規格 / Specs to Modify (MODIFIED)

| 規格 / Spec | 變更類型 / Change Type |
|------------|----------------------|
| `trajectory` | 統一欄位名稱、新增 `fail_closed` 狀態、對齊 `terminal_state` 值域、補齊 `tool_filter` 結構 |
| `audit` | 統一 agent audit 欄位與 trajectory 對齊、明確敏感內容遮罩規則 |
| `agent` | 統一 `terminal_state` 值域、對齊 `effective_budget` 來源、補齊 `fail_closed` 語意 |
| `gateway` | 回應 `jiezi` 欄位對齊新 trajectory 結構、補齊 `tool_filter` 完整記錄 |
| `escalation` | `escalation` 原因碼標準化、與 `stats.reasons` 對齊 |

### 5.2 需新增的規格 / Specs to Add (ADDED)

| 規格 / Spec | 用途 / Purpose |
|------------|---------------|
| `observability` | 統一觀測欄位表、敏感內容遮罩規則、預算對齊規則、狀態機定義 |
| `dashboard` | 儀表板讀取介面規格、指標計算規則、輸出格式 |
| `process` | 既有 `process.py` 的對外介面規格（供前端/狀態頁用） |

---

## 6. 開放問題 / Open Questions

| 編號 / ID | 問題 / Question | 選項 / Options | 建議 / Recommendation |
|----------|----------------|---------------|----------------------|
| **OQ1** | 是否採用 OpenTelemetry GenAI 語義慣例命名（如 `gen_ai.operation.name`、`gen_ai.usage.output_tokens`）？ | A. 完全遵循 OTel 命名<br>B. 僅參考關鍵欄位，保留現有 `jiezi.*` 命名空間<br>C. 建立對應表，內部用短名、匯出時映射 OTel | **B（依 A8 結論調整）** — 保持現有命名空間；關鍵欄位命名**參考** OTel GenAI（Development 狀態，記版本），不引入 SDK。內部仍用 `jiezi.*`，欄位名語意對齊 gen_ai.*（如 `gen_ai.request.model`→`model`、`gen_ai.usage.input_tokens`→`tokens_input`），未來若需 OTLP 匯出再建對應表。 |
| **OQ2** | `fail_closed` 狀態要細分到哪層？ | A. 僅 trajectory 層級 (`status: "fail_closed"`)<br>B. trajectory + agent loop (`terminal_state: "fail_closed"`) + gateway 回應 (`jiezi.fail_closed: true`)<br>C. 只在健康檢查 `/health` 暴露 | **B** — 三層都要可見，狀態頁才能正確顯示 |
| **OQ3** | `task budget` 對齊 `facts budgets` 的具體規則？ | A. `tools_budget` 依 `facts.budgets.vram` 反推（VRAM 越大 token 越多）<br>B. `call_timeout_s` 依 `facts.budgets.cpu.usable_threads` 調整（核心越多 timeout 越短）<br>C. 只在規格註明「兩者獨立，未來若需聯動再擴充」 | **C** — 目前無明確對應關係，強行綁定反而限制彈性；規格註明獨立、預留擴充點 |
| **OQ4** | `tool_filter` 記錄是否要包含 `dropped` 計數？ | A. 是，完整記錄 `original`/`kept`/`dropped`/`stage`/`names`<br>B. 只記 `original`/`kept`/`stage`/`names`（`dropped = original - kept` 可推導） | **A** — 明確記錄便於審計與除錯 |
| **OQ5** | `process` 規格是否要獨立，還是併入 `trajectory`？ | A. 獨立 `process` spec（前端介面穩定、trajectory 可內部演進）<br>B. 併入 `trajectory`（單一事實來源） | **A** — `process` 是給前端看的衍生視圖，介面應穩定；`trajectory` 是完整記錄 |

---

## 7. 驗收標準 / Acceptance Criteria

1. **欄位統一**：`trajectory`、`audit`、`agent`、`gateway`、`process`、`dashboard`、`stats` 七模組的同一概念使用相同欄位名稱、型別、值域
2. **敏感內容零記錄**：所有寫入 `var/` 的 JSONL/JSON 經過遮罩函數，無檔案內容、金鑰、token、`.env` 內容、使用者機密
3. **預算對齊文檔化**：`observability` spec 明確列出 `task budget` (6 項) 與 `facts budgets` (cpu/vram) 的對應關係（或註明獨立）
4. **Fail-closed 可見**：`/health`、狀態頁、CLI `jiezi status` 皆能看到 `fail_closed` 狀態與觸發原因
5. **狀態頁資訊完整**：agent on/off、最近 N 筆成果、轉交統計、工具使用分布、資源佔用（CPU/VRAM/token）皆可見
6. **規格驗證通過**：`openspec validate add-agent-observability --strict` 與 `--all --strict` 雙通過；`git diff --check` 乾淨

---

## 8. 相依與風險 / Dependencies & Risks

| 風險 / Risk | 緩解 / Mitigation |
|------------|------------------|
| 欄位重命名破壞既有儀表板/前端 | `process` spec 維持穩定介面；`trajectory` 內部欄位變更只影響寫入端，讀取端由 `process` 隔離 |
| 遮罩邏輯遺漏導致敏感外洩 | 集中化遮罩函數 `_scrub_all()`，所有寫入點統一呼叫；紅隊測試驗證 |
| `facts budgets` 讀取失敗導致 agent 啟動失敗 | 預設值回退；`budget_prefix` 已有優雅降級邏輯，沿用相同模式 |
| 既有 trajectory 檔案格式不相容 | 新欄位可選、舊檔讀取時補預設值；不遷移歷史檔案 |

---

## 9. 實作策略 / Implementation Strategy

1. **Phase 1 - 設計文件**：完成 `design.md`（統一欄位表、遮罩規則、狀態機）、`tasks.md`（具體到檔案/函式）
2. **Phase 2 - Spec Delta**：產生 `specs/observability/spec.md` (ADDED)、`specs/trajectory/spec.md` 等 (MODIFIED)
3. **Phase 3 - 核心實作**：
   - `src/jiezi/observability/` 新模組：統一欄位常數、遮罩函數、狀態機
   - 修改 `trajectory.py`、`agent/audit.py`、`agent/loop.py`、`agent/contract.py`、`gateway.py`、`tool_filter.py`、`process.py`、`dashboard.py`、`stats.py`
4. **Phase 4 - 測試與驗證**：單元測試、紅隊測試、規格驗證、全量測試
5. **Phase 5 - 文檔同步**：更新 `docs/dev-plan.md` A8 狀態、寫入 `WORKER_REPORT.md`

---

## 10. 參考 / References

- 開發計畫 §15.5 A8、§15.1 能力矩陣 A9
- 既有規格：`trajectory`、`audit`、`agent`、`gateway`、`escalation`、`tools`
- 既有變更：`add-agent-contract`、`add-agent-hardening`、`add-client-tool-filter`、`add-answer-process`
- web-research.md §A8：OpenTelemetry GenAI semantic conventions、Langfuse、OpenLLMetry 查證結果
## 資安掃描 / Security scan（主控 2026-11-23 補）

- 無新相依、連接埠、服務、模型或權限；不引入 OpenTelemetry SDK、Langfuse、OpenLLMetry（見現成方案）。
- 主要風險是**敏感內容外洩到觀測紀錄或狀態頁**：檔案內容、使用者私人文件、金鑰、本機路徑。對策：Masking Rules 需求（統一欄位表逐欄標記敏感度與遮罩規則）、狀態頁只顯示計數與摘要、稽核維持「不記檔案內容」。
- 次要風險是**讀取端轉換錯誤造成誤判**（例如把 fail_closed 算成 completed）：以 normalize 的對應表測試與舊紀錄回歸測試緩解；寫入端欄位不改名，所以轉換錯誤不會損壞既有資料。
- 結論：ok（2026-11-23）。

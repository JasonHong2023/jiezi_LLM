## 0. 前置 / Prerequisites

- [x] 0.1 使用者決定 OQ1～OQ4（HTTP 框架、雲端轉交、軌跡內容、本機金鑰）/ User decides OQ1–OQ4（2026-11-15：全部依建議 / all as recommended）
- [x] 0.2 依 OQ1 新增相依套件：R23 查證寫入 `stack.md`，鎖在 `uv.lock` / Add dependencies per OQ1 with the R23 record and lock

## 1. 共用引擎 / Shared engine

- [x] 1.1 `LocalEngine` 移到 `jiezi/engine.py`，評測改用共用版本，既有測試不變 / Move `LocalEngine` to a shared module; eval tests unchanged

## 2. supervisor

- [x] 2.1 延遲載入、預算重算與擺放、閒置卸載、`state.json` / Lazy load, budgets and placement, idle unload, `state.json`
- [x] 2.2 健康檢查與有上限的重啟、不可用狀態 / Health checks, bounded restart, unavailable state
- [x] 2.3 夜間評測協調：評測載入前要求卸載並暫停，條件記錄 gateway 狀態 / Night-evaluation coordination and condition records

## 3. gateway

- [x] 3.1 只綁 `127.0.0.1`、金鑰、請求大小與時間上限 / Local binding, key, size and time limits
- [x] 3.2 `/v1/chat/completions`（串流與非串流）、`/v1/models`、`/health`、`/admin/unload`；中斷時取消上游 / Endpoints; cancel upstream on disconnect
- [x] 3.3 `jiezi` 回應欄位 / The `jiezi` response field

## 4. 分層轉交 / Escalation

- [x] 4.1 執行期驗證器：工具呼叫格式與 schema、程式語法（不執行）/ Runtime verifiers (never executing content)
- [x] 4.2 第 0、1、3 層與策略；雲端開關與每日上限 / Tiers 0, 1, 3 and policies; cloud switch and daily cap

## 5. 軌跡 / Trajectories

- [x] 5.1 JSONL 紀錄、關閉開關、保留天數、寫入失敗不影響回應 / Records, off switch, retention, failures do not break responses

## 6. 指令與設定 / Commands and settings

- [x] 6.1 `scripts/jiezi serve`、`scripts/jiezi status`；`.env.example`；依 OQ4 由 bootstrap 產生金鑰 / Commands, settings, key generation

## 7. 驗證 / Verification

- [x] 7.1 單元測試（假引擎、假雲端；全部 288 個通過）：金鑰、綁定、策略、各層轉交、每日上限、中斷取消、閒置卸載、重啟上限、軌跡；`openspec validate add-gateway --strict` / Unit tests with fake engine and cloud; strict validation
- [x] 7.2 實機（使用者同意白天慢速試跑，2026-11-15 15:20 前後）：以 Qwen3-0.6B 啟動 gateway，用 `curl` 測非串流、串流、工具呼叫第 1 層重試、閒置卸載；結果記入討論記錄 / Real run with Qwen3-0.6B: non-streaming, streaming, tier-1 tool retry, idle unload（實測：401、非串流、串流含 `jiezi` 事件、工具呼叫 schema 通過、程式語法通過、閒置 20 秒卸載、評測協調卸載並暫停、SIGINT 乾淨關閉；第 1 層重試只以單元測試驗證，因 0.6B 這次沒有產生錯誤的工具呼叫 / tier-1 retry covered by unit tests only, since the 0.6B produced no faulty call）

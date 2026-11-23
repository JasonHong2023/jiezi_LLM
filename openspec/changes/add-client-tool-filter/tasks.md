## 0. 前置 / Prerequisites

- [x] 0.1 主控離線量測 Hermes／OpenCode 請求組成（`var/trajectories`）：系統提示本身即超過 4,096 token，見 proposal「主控實測補充」/ Offline measurement of request composition
- [x] 0.2 使用者決定 Open Question 0（系統提示處理方式）後，再補對應 tasks 與 `gateway` delta / Add tasks and gateway delta after the user decides OQ0

> 2026-11-23 主控實作註記：0.2 → 使用者授權主控決定，選 OQ0 (C)，不需 gateway delta。1.1 實際函式為 `select()`／`ladder()`（不是 `filter_tools()`）。2.1 實際接在 `gateway.py::_chat()` 的 `_too_large()` 之前（`_filter_tools()`），不是 `_local_body()`，這樣轉交雲端也只帶篩過的工具。3.2 的 `fallback_stages`、`verification_skills` 兩類不放語料，改由 `LadderTests` 與既有 gateway 全套測試涵蓋。4.2／4.3：`verify_tools()` 與技能附加都看篩過的 `body["tools"]`，既有測試全過。7.1 由使用者 2026-11-23 指示取代。

## 1. 工具過濾核心邏輯 / Tool filter core logic

- [x] 1.1 新增 `src/jiezi/runtime/tool_filter.py`，導出 `filter_tools(contract_tools, user_message, all_tools, settings)` / Add `tool_filter.py` exporting `filter_tools()`
- [x] 1.2 實作關鍵字提取：中文 regex 分詞 + 英文單詞、停用詞過濾 / Implement keyword extraction: Chinese regex tokenization + English words, stopword filtering
- [x] 1.3 實作相關性評分：契約工具滿分、白名單滿分、關鍵字命中加分、依分數排序取 top_k / Implement relevance scoring: contract tools max, whitelist max, keyword hits bonus, sort by score take top_k
- [x] 1.4 實作 fallback 階梯：完整 schema → 保留 parameters、截短 description → 只留必留名單 → 依策略轉交或 413（主控更正：不可拿掉 parameters）/ Fallback ladder: full schema → keep parameters, shorten descriptions → keep-list only → escalate or 413 per policy
- [x] 1.5 讀取工具描述時經 `injection.clean()`，防禦 prompt injection / Call `injection.clean()` on tool descriptions to prevent prompt injection
- [x] 1.6 單元測試 `tests/test_tool_filter.py`：契約工具保留、白名單保留、關鍵字匹配、fallback 階梯、注入清理 / Unit tests: contract tools kept, whitelist kept, keyword matching, fallback stages, injection cleaning

## 2. Gateway 整合 / Gateway integration

- [x] 2.1 在 `gateway.py::_local_body()` 的 `fit()` 之前呼叫 `filter_tools()`，取得過濾後的 tools / Call `filter_tools()` before `fit()` in `_local_body()`
- [x] 2.2 傳入 `agent_contract.effective_tools`（若有）、使用者最近訊息、完整 tools 列表、settings / Pass contract tools, user message, all tools, settings
- [x] 2.3 過濾後的 tools 取代原 tools 參數送入 `fit()` / Replace original tools with filtered tools for `fit()`
- [x] 2.4 在 trajectory 記錄 `tool_filter` 欄位：原始數量、過濾後數量、fallback 階段、保留工具名稱 / Record `tool_filter` in trajectory: original count, filtered count, fallback stage, kept tool names
- [x] 2.5 調整 `_too_large()`：優先走過濾與 fallback，只有全部階段嘗試後仍放不下才回 413 / Adjust `_too_large()`: try filter and fallback first, only 413 after all stages exhausted

## 3. 合成語料與回歸測試 / Synthetic corpus and regression tests

- [x] 3.1 建立 `tests/fixtures/tool_filter_cases.json`，含版本、分類與合成案例 / Create corpus with version, categories, synthetic cases
- [x] 3.2 分類：`contract_specified`（契約指定工具）、`keyword_match`（關鍵字匹配）、`fallback_stages`（fallback 階梯）、`whitelist_preserved`（白名單保留）、`injection_clean`（注入清理）、`verification_skills`（驗證與技能不受影響） / Categories: contract_specified, keyword_match, fallback_stages, whitelist_preserved, injection_clean, verification_skills
- [x] 3.3 每筆案例含 `id`、`category`、`input`（contract、user_message、tools）、`expected`（保留工具、fallback 階段）、`synthetic: true` / Each case: id, category, input, expected, synthetic: true
- [x] 3.4 在 `tests/test_tool_filter.py` 載入語料並驗證所有案例 / Load corpus in test file and verify all cases

## 4. 既有測試補強 / Existing test reinforcement

- [x] 4.1 `tests/test_runtime_gateway.py`：新增帶大量工具請求的整合測試，驗證過濾後能正常進入本地模型 / Add integration test with many tools, verify filter allows local model path
- [x] 4.2 驗證過濾不影響 `escalation.py::verify_tools()` schema 驗證 / Verify filter doesn't break tool schema verification
- [x] 4.3 驗證過濾不影響 `_attach_skills()` 技能附加 / Verify filter doesn't break skill attachment

## 5. 重度量測（00:00–07:00） / Heavy measurements (00:00–07:00)

> ⚠️ 以下任務需在夜間時段執行，白天不執行

- [ ] 5.1 取得 Hermes/OpenCode 實際請求樣本（需使用者配合），跑工具過濾實測 / Obtain real Hermes/OpenCode request samples (user cooperation), run filter measurement
- [ ] 5.2 量測指標：過濾前後 token 數、保留工具準確率、fallback 觸發率、端到端延遲增加 / Metrics: tokens before/after, tool retention accuracy, fallback trigger rate, latency overhead
- [ ] 5.3 生成報告 `var/reports/tool-filter-YYYYMMDD.md` 與 JSONL / Generate report and JSONL
- [ ] 5.4 若實測發現 `top_k` 需調整，記錄建議值供後續 change 調整 / Record recommended top_k if measurement suggests adjustment

## 6. 驗證與紀錄 / Validation and records

- [ ] 6.1 執行 `openspec validate add-client-tool-filter --strict`、`openspec validate --all --strict` 與 `GIT_MASTER=1 git diff --check` / Run strict validations and diff check
- [ ] 6.2 執行 `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`，確認不少於現有測試數且全過 / Run full unittest suite, confirm no regression
- [ ] 6.3 依 R19.4 更新 `docs/dev-plan.md` §15.7、`HANDOFF.md` 與 `2026-11-22.md`，記錄結果與殘留風險 / Update dev-plan §15.7, HANDOFF, and daily record with results and residual risks per R19.4

## 7. 核准關卡 / Approval gate

- [x] 7.1 向使用者報告驗證結果並等待「可以實作」；未核准前不 `/opsx-apply` / Report validation results and wait for "ready to implement"; do not `/opsx-apply` before approval
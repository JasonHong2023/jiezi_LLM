> **狀態 / Status**：提案草稿，待使用者審閱（R4）。初稿由 OpenCode worker（nvidia-nemotron-3-ultra）撰寫，主控（Claude Code）2026-11-23 審查更正：加入 Hermes／OpenCode 請求組成實測、統一 fallback 階梯、修正必留名單說法、併入現成方案查證、移除未建立的 gateway delta。/ Draft awaiting review.

## Why / 動機

Hermes 與 OpenCode 等代理程式每次請求都帶上完整工具清單（Hermes 約 55 個工具、OpenCode 類似），總字元數達 ~120k chars，遠超本機模型 4,096 token 上下文槽位。目前 gateway 收到這類請求時，`_too_large()` 偵測到裁不下，依 `gateway.py:1236-1243` 邏輯會嘗試自動轉交雲端（`jiezi` 策略），但若使用者明確指定 `jiezi-local` 或雲端未啟用，直接回 **413 context_too_large**，導致本機無法服務這類代理程式。

依 `docs/dev-plan.md` §15.5 A7 需求：A7 `add-client-tool-filter` 要在 gateway 端根據 **任務契約**（`agent_contract`）與 **使用者訊息**，過濾／壓縮客戶端提供的 `tools`，僅保留相關工具；當過濾後仍放不下時，**改為 fallback 策略**（裁掉最不相關工具、保留核心工具、或只送工具名稱/描述摘要）而非 413，使 Hermes/OpenCode 能在 `jiezi-local` 下本機運行。

實測數據（來自 `HANDOFF.md` 第 93 行）：
- Hermes/OpenCode 走 `jiezi` 可用（會自動轉交雲端）
- 走 `jiezi-local` 回 413，因為它們的請求有數萬 token（工具清單與系統提示本身就超過本機上下文）
- 實測 OpenCode 一次送 58,000 token（`gateway.py:1232-1233` 註解）


**主控實測補充（2026-11-23，Claude Code 從 `var/trajectories/*.jsonl` 離線量測，未跑模型）/ Measured request composition**：本機槽位 `context.py: SLOT_CTX = 4096` token。

| 客戶端 | 工具數 | 系統提示字元 | tools JSON 字元 | 其他訊息字元 |
|---|---|---|---|---|
| Hermes | 55 | 38,286–41,909 | 72,783 | <200 |
| Hermes | 177–179 | 64,907–64,919 | 140,781–144,433 | <100 |
| Hermes（只帶 1 個工具） | 1 | 29,677 | 1,940 | 49 |
| OpenCode | 178 | 61,358–61,370 | 141,562 | 49 |

**結論：只篩工具無法消除 413。** Hermes 只帶 1 個工具時，系統提示仍有約 3 萬字元，遠超 4,096 token。所以本 change 必須同時決定「客戶端系統提示怎麼處理」（見 Open Question 0），否則 Hermes／OpenCode 在 `jiezi-local` 下仍會 413。/ Tool filtering alone cannot remove the 413: Hermes' system prompt alone is ~30k chars even with one tool.

本提案依 `docs/dev-plan.md` §15.5 排在 A6 之後，核准後再施工，不改核心模型、不新增外部能力、不占滿硬體。

## What Changes / 變更內容

- 在 gateway 收到帶 `tools` 的請求時，依 `agent_contract.effective_tools`（若有）與使用者最近一則訊息的語意，計算工具相關性分數，只保留前 N 個或分數超過門檻的工具。
- 新增可配置的過濾策略：`top_k`（預設 12）、`min_score`、依客戶端設定的「必留工具」名單（各客戶端工具名稱不同，例如 OpenCode 的 `read`／`grep`／`bash`；名單含寫入與 shell 工具，**不是唯讀名單**——這些工具由客戶端自己執行，gateway 只轉送 schema）。
- 過濾後仍超過上下文時：改用 **fallback 階梯** 而非 413（與 design.md 決策 4 一致）——(1) top_k＋必留＋契約工具，完整 schema；(2) 同一批工具保留 `parameters`、只截短 description（主控更正：原草稿「只送名稱與描述」會拿掉 parameters，模型無法產生正確參數）；(3) 只留必留名單完整 schema；(4) 仍放不下才依策略處理（`jiezi` 轉交雲端、`jiezi-local` 回 413）。另依 Open Question 0 處理系統提示。
- 新增 `src/jiezi/runtime/tool_filter.py` 作為單一過濾邏輯來源，供 `gateway.py::_local_body()` 在 `fit()` 之前呼叫。
- 保留既有 `_too_large()` 檢查作為最後防線，但優先走過濾與 fallback，減少 413 發生率。
- 相關測試：合成語料覆蓋 contract 指定工具、無 contract 時語意匹配、fallback 階梯、白名單保留、過濾不影響驗證與技能附加。

### Non-Goals / 不做的範圍

- 不新增寫入、shell、網路工具，也不新增 per-action approve、dry-run 或 rollback；那些屬於 `add-agent-approval`。
- 不新增 SKILL、MCP server、相依套件、服務、連接埠、模型或 GPU 負載。
- 不改核心 `qwen3.5-4b-q4_k_m`、P1–P8、D1–D12、G1–G5 或 Phase 0–8 主時程。
- 不在本 change 改寫 dashboard UI；只提供可向後對齊的欄位與測試。
- 不處理工具呼叫執行階段的授權（grant）、稽核、超時、取消；那些在 `add-agent-hardening` 已涵蓋。
- 不實作向量化工具描述的語意搜尋（embedding-based relevance）；本 change 採關鍵字/啟發式匹配，語意搜尋留待後續優化。

## Capabilities / 能力

### New Capabilities / 新增能力

- `client-tool-filter`: 根據任務契約與使用者訊息過濾/壓縮客戶端工具清單，提供階梯式 fallback 避免 413。

### Modified Capabilities / 修改能力

- 無正式 delta（主控更正：原草稿列 `gateway` 修改 delta 但未建立）。gateway 的行為變更由 `client-tool-filter` 新能力描述；若 Open Question 0 選擇改寫系統提示，再補 `gateway` MODIFIED delta。/ None yet; a `gateway` delta is added if OQ0 chooses system-prompt rewriting.

## Impact / 影響

- 程式碼 / Code：新增 `src/jiezi/runtime/tool_filter.py`；修改 `gateway.py::_local_body()`、`gateway.py::_too_large()`、相關常數；必要時微調 `context.py::fit()` 配合過濾後的 tools。
- 測試 / Tests：新增 `tests/test_tool_filter.py`、`tests/fixtures/tool_filter_cases.json`（合成語料），補強既有 `tests/test_runtime_gateway.py`。
- 規格 / Specs：新增 delta `specs/client-tool-filter/spec.md`；（`gateway` delta 視 OQ0 決定再補）。
- 驗證 / Validation：`openspec validate --all --strict`、`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`、`GIT_MASTER=1 git diff --check`；重度模糊測試僅夜間另排。
- 分類 / Classification：**核心／既有模組（core module）**，不是 `SKILL`，也不是 `MCP`。理由：此變更屬於 gateway 核心請求處理管線的一部分，直接操作 OpenAI 相容 API 的 `tools` 參數，不對外暴露新工具、不啟動獨立服務、不引入新傳輸協定。依 `docs/dev-plan.md` §15.2 判定流程：提供工具 → 否；獨立服務 → 否；新傳輸 → 否 → 歸類為核心模組。
- 現成方案搜尋 / Existing-solution search（主控 2026-11-22 上網查證，取代原「待查證」候選）：
  1. **RAG-MCP**（arXiv 2505.03275）：先語意檢索相關工具再交給 LLM；提示 token −50% 以上，工具選擇正確率 13.62% → 43.13%。
  2. **Semantic Tool Discovery**（arXiv 2603.20313）：工具描述向量檢索；121 個工具，工具 token −99.6%，K=3 命中 97.1%，<100 ms。
  3. **ScaleMCP**（arXiv 2505.06416）、**Dynamic ReAct**（arXiv 2509.20386）：按需載入工具；後者指出純向量檢索需較大 top-k 才不漏。
  4. 共同模式是「工具名稱＋描述建索引 → 每次取 top-k → 只注入選中的工具」。查無授權清楚、可直接套用的套件；芥子已有 embedding 引擎（`rag`），故**核心內建、不新增相依**。關鍵字版（本 change）與 embedding 版的取捨見 Open Question 2。
- 資安掃描 / Security scan：
  - **工具描述注入風險**：惡意工具描述可能包含 prompt injection 句式（如 "ignore previous instructions"），過濾邏輯讀取描述時需經 `injection.clean()`。
  - **過濾掉必要工具**：若契約 `effective_tools` 指定的工具被錯誤過濾，會導致代理失效。對策：契約指定工具**永不被過濾**，白名單核心工具**永不被過濾**。
  - **資訊洩露**：工具描述可能含敏感資訊（路徑、API 端點），fallback 只送名稱+一行描述時需清理。
  - 無新相依、連接埠、權限或模型；主要殘留風險是過濾邏輯誤判導致代理能力受損，以合成語料回歸、白名單保護、契約工具優先緩解。

## Open Questions / 未決問題

0. **（最重要）客戶端系統提示怎麼處理？** 實測 Hermes 系統提示約 3–4 萬字元、OpenCode 約 6 萬字元，都超過 4,096 token。選項：
   - (A) 本機路徑以芥子的精簡系統提示取代客戶端的系統提示，只保留其中的身分、工作目錄等關鍵段落（會失去客戶端的部分指示）；
   - (B) 代理客戶端改用較大的上下文槽位（例如 16k，要多占顯示記憶體，需另行量測，且仍須保留 ≥1 GB）；
   - (C) 維持現狀：代理客戶端一律轉交雲端，本 change 只降低工具量以節省雲端 token；
   - (D) A＋工具篩選兩者都做。
   主控建議先選 (C)＋工具篩選作為第一步（風險最低），並把 (A)/(B) 的量測排夜間。**請使用者決定。**

1. **過濾閾值預設值**：`top_k=12` 是否適合所有代理程式？是否需可透過環境變數/設定調整？（建議先定死，實測後再開放配置）
2. **語意匹配演算法**：本 change 採關鍵字/啟發式，若未來要上 embedding-based relevance，是否另開 change？（建議是，本 change 不綁定演算法介面）
3. **Hermes/OpenCode 實測樣本**：需取得實際請求樣本驗證過濾效果，是否在本 change 完成後由使用者配合測試？（建議是，本 change 提供測試框架，實測留待授權後）
4. **fallback 後的模型行為**：完全移除 tools 參數時，模型可能仍嘗試呼叫工具（文字格式），需確認驗證器能正確處理。（現有 `escalation.py::text_calls_to_tool_calls` 已支援文字格式工具呼叫轉換）
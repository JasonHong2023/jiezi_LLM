## Context / 背景

芥子 gateway 已支援三種策略（`jiezi`、`jiezi-local`、`jiezi-cloud`）與分層轉交，但面對 Hermes、OpenCode 等帶大量工具（~55 個、~120k chars）的代理程式請求時，`jiezi-local` 會在 `_too_large()` 檢查失敗後直接回 413（`gateway.py:1236-1243`）。依 `docs/dev-plan.md` §15.5 A7，需在 gateway 端根據任務契約（`agent_contract`）與使用者訊息過濾工具，並提供 fallback 策略避免 413。

本變更依 §15.2 歸類為**核心／既有模組**，不是 `SKILL` 或 `MCP`。現成方案搜尋沿用 §15.3 已查證的官方文件；§15.4 資安準則直接套用。

Constraints / 限制：R1 雙語、R4 核准後施工、R8 小任務、R15 高代價選項先問、R18 資源預算、R19.4 更正不刪除、R21 可攜性、R22 最小權限、R23 禁用高風險技術；無新相依、連接埠、模型或 GPU 負載。

## Goals / Non-Goals / 目標與非目標

**Goals / 目標：**

- 建立單一工具過濾邏輯來源 `src/jiezi/runtime/tool_filter.py`，供 `gateway.py::_local_body()` 在 `fit()` 之前呼叫。
- 依 `agent_contract.effective_tools`（優先）、使用者訊息關鍵字匹配、核心工具白名單，計算工具相關性並保留前 N 個（預設 top_k=12）。
- 過濾後仍超過上下文時，走 fallback 階梯（見決策 4）；客戶端系統提示的處理見 proposal Open Question 0。
- 契約指定工具與白名單核心工具**永不被過濾**。
- 工具描述讀取時經 `injection.clean()` 防禦 prompt injection。
- 合成語料回歸覆蓋 contract 指定、無 contract 語意匹配、fallback 階梯、白名單保留、驗證與技能附加不受影響。

**Non-Goals / 非目標：**

- 不新增寫入、shell、網路工具，不做 per-action approve、preview、dry-run 或 rollback。
- 不新增 `SKILL`、`MCP` server、套件、服務、連接埠、模型或 GPU 工作。
- 不改核心 `qwen3.5-4b-q4_k_m`、P1–P8、D1–D12、G1–G5 或 Phase 0–8 主時程。
- 不改寫 dashboard UI；大量模糊測試留到夜間另行安排。
- 不實作向量化工具描述的語意搜尋；本 change 採關鍵字/啟發式匹配。

## Decisions / 決策

1. **單一過濾來源 / Single filter source**：新增 `src/jiezi/runtime/tool_filter.py`，導出 `filter_tools(contract_tools, user_message, all_tools, settings)`；`gateway.py::_local_body()` 在 `fit()` 前呼叫。替代方案是直接在 `gateway.py` 寫邏輯或分散在 `context.py`；前者違反單一職責，後者 `context.py` 已負責上下文裁剪，不宜再加語意過濾。

2. **契約工具優先 / Contract tools first**：`agent_contract.effective_tools` 若存在，這些工具**永不被過濾**，直接保留。替代方案是契約工具也參與評分；會導致代理宣稱需要的工具被錯誤移除，破壞契約語意。

3. **必留名單 / Keep-list**：依客戶端設定（Hermes、OpenCode 的工具名稱不同），永不被過濾。（主控更正：原草稿把含 `bash`、`write_file`、`edit` 的名單稱為「唯讀基礎工具」是錯的；這些工具由客戶端執行，gateway 只轉送 schema。）替代方案是不設白名單；風險是基礎工具被移除導致所有代理失能。

4. **三階段 Fallback / Three-stage fallback**：
   - 階段 1：保留完整 schema，只過濾數量（top_k + 白名單 + 契約工具）
   - 階段 2：保留 `parameters`，只截短 description（主控更正：移除 parameters 會讓模型無法產生正確參數）
   - 階段 3：只送核心白名單完整 schema
   - 階段 4：仍放不下就依策略處理（`jiezi` 轉交雲端，`jiezi-local` 回 413）；客戶端系統提示的處理見 proposal Open Question 0
   替代方案是直接跳到階段 4；會失去模型結構化呼叫能力。階梯式保留最大能力。

5. **關鍵字匹配演算法 / Keyword matching**：
   - 從使用者最近一則訊息提取關鍵字（中文分詞 + 英文單詞，過濾停用詞）
   - 工具描述與名稱含關鍵字者加分
   - 契約工具、白名單工具直接滿分
   - 依分數排序取前 top_k
   替代方案是 embedding-based；需 embedding 模型、向量索引、額外延遲，本 change 不引入。

6. **注入防護 / Injection guard**：讀取工具描述時呼叫 `injection.clean(description)` 移除零寬字元、偽造標記。替代方案是信任工具描述；風險是惡意 MCP server 回傳含 injection 的描述。

7. **設定參數 / Configuration**：`tool_filter_top_k`（預設 12）、`tool_filter_enabled`（預設 true）、`tool_filter_core_tools`（可覆蓋白名單）。放在 `Settings`，不新增獨立設定檔。

## Risks / Trade-offs / 風險與取捨

- [過濾誤判移除必要工具 / Filter removes required tool] → 契約工具與白名單永不被過濾、合成語料含「契約工具在低分時仍保留」案例、fallback 階段 3 保留白名單完整 schema。
- [工具描述注入 / Tool description injection] → 讀取描述時經 `injection.clean()`、測試含 injection 描述案例驗證清理有效。
- [fallback 後模型行為異常 / Model misbehaves after fallback] → 階段 2 保留 name+description 維持結構化呼叫格式、階段 4 移除 tools 時系提示提醒可用工具、既有 `text_calls_to_tool_calls` 支援文字格式呼叫轉換。
- [Hermes/OpenCode 實際請求差異 / Real request differs from assumptions] → 提供合成語料框架，實測樣本留待授權後由使用者配合驗證、本 change 不綁定特定代理程式格式。
- [效能影響 / Performance overhead] → 關鍵字提取與匹配在單一請求內 <5ms、無外部呼叫、可透過 `tool_filter_enabled=false` 關閉。

## Migration Plan / 遷移計畫

1. R4 核准後才 `/opsx-apply`；依 tasks.md 順序先做過濾邏輯、再做 gateway 整合、fallback、測試、驗證。
2. 無執行期資料遷移、設定檔或連接埠變更；既有 trajectory 格式保持可讀（新增 `tool_filter` 欄位記錄過濾前後數量）。
3. 完成後跑 strict validate、完整 unittest 與 `git diff --check`，再依 R19.4 在 `docs/dev-plan.md` §15.7 補完成紀錄，並更新 HANDOFF 與當日記錄。
4. 回滾策略：回到本 change 前的檔案狀態；不刪既有測試與語料，必要時以新更正取代。

## Open Questions / 未決問題

1. **`top_k=12` 是否為最佳預設？** 實測 Hermes/OpenCode 後再調，或開放 `JIEZI_TOOL_FILTER_TOP_K` 環境變數。
2. **中文分詞庫選擇**：本 change 採簡單 regex + 停用詞表，若需更準確可引入 `jieba`（新相依），留待後續優化 change。
3. **工具描述長度上限**：階段 1 完整 schema 時，單一工具描述是否需硬性截斷？（建議依靠 `fit()` 現有上下文裁剪，不過濾層額外截斷）。
4. **多輪對話中的工具變化**：後續輪次若用戶換主題，是否重新過濾？（本 change 每請求獨立過濾，無狀態保留，符合無狀態 gateway 設計）。
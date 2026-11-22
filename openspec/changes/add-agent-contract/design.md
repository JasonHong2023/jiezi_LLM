## Context / 背景

`芥子` 已有 bounded agent loop、唯讀工具、grant／audit、本機 trajectory，但任務請求目前沒有 first-class contract。`docs/dev-plan.md` §15.5 A1 要求新增 `add-agent-contract`，且不得改變核心模型、硬體占用或既有 P1–P8 / D1–D12 / G1–G5 主線。 / Jiezi already has a bounded loop, read-only tools, grants/audit, and local trajectory, but task requests lack a first-class contract. dev-plan §15.5 A1 requires this change without altering the core model, hardware budgets, or main plan.

現況限制：工具呼叫由既有流程選擇與驗證；trajectory writer 接受任意 `dict`，寫入失敗不影響回答；grant 每次重讀，且目前沒有寫入／shell／網路工具。 / Current constraints: tool calls are selected and validated by the existing flow; the trajectory writer accepts an arbitrary dict and never breaks a response on write failure; grants are re-read per call and no write/shell/network tools exist.

## Goals / Non-Goals

**Goals / 目標：**

- 建立可驗證的 task contract 資料形狀與 normalization。 / Define a verifiable task contract shape and normalization.
- 讓 contract 只作為中繼資料，不成為新的指令通道或授權來源。 / Keep the contract as metadata only, never a new instruction or authorization channel.
- 把 contract 與 `completed` / `failed` / `aborted` 終態寫入 trajectory，供事後重建。 / Record the contract and terminal states in trajectory for later reconstruction.
- 模糊目標或完成條件先要求釐清，不啟動工具。 / Ask for clarification on vague goals or completion criteria before invoking tools.
- `allowed_tools` 只能收斂既有 grant，不得擴權。 / Let `allowed_tools` only narrow existing grants; never widen them.

**Non-Goals / 不做的範圍：**

- 不新增工具、SKILL、MCP server、相依套件、服務或連接埠。 / No new tool, SKILL, MCP server, dependency, service, or port.
- 不新增 per-action 核准、rollback、寫入／shell／網路能力。 / No per-action approval, rollback, or write/shell/network capability.
- 不改 audit 檔案格式，只使用既有可重建欄位。 / Do not change the audit file format; rely on existing reconstructable fields.
- 不改核心模型、gateway 對外 API 或 Phase 0–8 主時程。 / Do not change the core model, public gateway API, or Phase 0–8 schedule.

## Decisions / 決策

### 1. 分類為核心／既有模組 / Classify as core module

Contract validation 與 trajectory 寫入是安全不變量，不是程序知識，也不是跨客戶端工具；因此放在 `src/jiezi/agent/`，不做成 `SKILL` 或 `MCP`。 / Contract validation and trajectory recording are safety invariants, not procedural knowledge or cross-client tools; they belong in `src/jiezi/agent/`, not SKILL or MCP.

替代方案：做成 SKILL 會讓安全規則可被文字覆寫；做成 MCP 會新增不必要的外部協定表面。兩者皆不採。 / Alternatives: SKILL would make safety rules overridable by text; MCP would add an unnecessary protocol surface. Both are rejected.

### 2. Contract 是資料，不是指令 / Contract is data, not instructions

Contract 欄位只由程式驗證與讀取，不進入模型 prompt 的可信指令層；官方網站／文件／記憶／工具回傳仍由既有 injection guard 處理。 / Contract fields are validated and read by code, not injected as trusted instructions; web/docs/memory/tool outputs remain governed by the existing injection guard.

### 3. 只在既有上限內收斂 / Only narrow within existing ceilings

`budget` 與 `allowed_tools` 都只能把既有上限變小。大於既有 loop ceiling 的值會被 cap，未知或未授權工具會被拒絕；不會因此新增 grant。 / Budget and allowed tools may only reduce existing ceilings. Values above loop limits are capped; unknown or ungranted tools are rejected; no grant is added.

### 4. 模糊時不放行 / Fail closed on ambiguity

缺少 `goal` 或 `done_criteria`，或驗證判定無法形成可檢查完成條件時，回傳釐清要求，不呼叫工具；此狀態不是成功的 terminal status。 / Missing goal or done criteria, or an unverifiable completion condition, returns a clarification request and invokes no tool; this is not a successful terminal state.

### 5. 附加欄位向後相容 / Additive fields remain backward compatible

Trajectory 只新增可選欄位；既有 JSONL 不需遷移，舊讀取器忽略未知欄位。寫入失敗維持既有語意：記錄警告但不影響回答。 / Trajectory gains optional fields only; existing JSONL needs no migration and older readers ignore unknown keys. Write failure keeps current semantics: warn, never break the response.

## Risks / Trade-offs / 風險與取捨

- [Contract 內容被當成可信指令] → 只由程式讀取，並保留既有 injection guard。 / [Contract treated as trusted instruction] → code-only consumption; keep existing injection guard.
- [大量 contract 造成 context 膨脹] → 欄位精簡，限制字串長度，沿用 TOOLS_BUDGET／RESULT_CHARS 上限。 / [Large contracts inflate context] → compact fields, string length caps, reuse existing budgets.
- [未知工具名稱造成幻覺] → 驗證時與 grant／工具登錄交集比對，不在白名單就拒絕。 / [Unknown tool names cause hallucination] → intersect with grants/tool registry at validation; reject off-list names.
- [模糊任務被誤判為可執行] → fail closed，要求補 goal 與 done_criteria。 / [Vague task accepted] → fail closed and request goal/done_criteria.
- [軌跡寫入失敗導致審計缺口] → 沿用現有「不影響回答」語意，但把寫入失敗狀態保留在最後錯誤欄位供診斷。 / [Trajectory write failure creates audit gap] → keep current non-breaking semantics while exposing last error for diagnosis.

## Migration Plan / 遷移計畫

1. 先合併本提案與規格，通過 `openspec validate --all --strict`。 / Merge proposal and specs first and pass strict validation.
2. 完成程式與測試；新增測試覆蓋 contract 驗證、工具收斂、模糊提問、trajectory 重建。 / Implement code and tests covering validation, tool narrowing, clarification, and trajectory reconstruction.
3. 執行 `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`；不得少於既有 642 tests OK。 / Run the unit suite; existing 642 tests must remain OK.
4. 回滾方式：還原本次 commit；trajectory 附加欄位不需資料遷移。 / Rollback by reverting the commit; additive trajectory fields need no data migration.

## Open Questions / 待確認問題

無。所有選項皆為局部、可還原，且不改變核心模型或對外協定。 / None. All choices are local, reversible, and do not alter the core model or external protocol.

## Why / 動機

Jiezi already has a bounded agent loop, read-only tools, grants, audit, and local trajectory records, but a task request has no first-class contract that states its goal, constraints, completion criteria, risk, allowed tools, and budget. / 芥子已有有限代理迴圈、唯讀工具、grant、稽核與本機軌跡，但任務請求缺少 first-class contract 來明示目標、限制、完成條件、風險、可用工具與預算。

This change makes those fields explicit and traceable so the agent cannot silently expand scope, and so each run can be reconstructed from its trajectory. / 本變更讓這些欄位明確且可追溯，使代理不能默默擴權，並讓每次執行都能從軌跡重建。

## What Changes / 變更內容

- Add a normalized task contract with `goal`, `constraints`, `done_criteria`, `risk`, `allowed_tools`, and `budget`. / 新增標準化 task contract，欄位為 `goal`、`constraints`、`done_criteria`、`risk`、`allowed_tools`、`budget`。
- Treat the contract as metadata, not as an instruction source; it does not grant tools or authority by itself. / contract 只當作中繼資料，不當作指令來源；它本身不授予工具或權限。
- Record the contract and terminal status (`completed` / `failed` / `aborted`) in trajectory records, without writing file contents or secrets. / 把 contract 與終態（`completed`／`failed`／`aborted`）寫入軌跡記錄，不寫入檔案內容或機密。
- Ask for clarification when the goal or completion criteria are too vague to verify. / 當目標或完成條件模糊到無法驗證時，先問清楚。
- Enforce `allowed_tools` as a subset of existing grants and read-only tools; never widen permissions. / `allowed_tools` 只作為既有 grant 與唯讀工具的子集限制，絕不擴大權限。

### Non-Goals / 不做的範圍

- No new write, shell, or network tools. / 不新增寫入、shell 或網路工具。
- No new model, service, port, dependency, or background process. / 不新增模型、服務、連接埠、相依或背景進程。
- No change to core `qwen3.5-4b-q4_k_m`, P1–P8, D1–D12, G1–G5, or the main Phase 0–8 schedule. / 不改核心 `qwen3.5-4b-q4_k_m`、P1–P8、D1–D12、G1–G5 或 Phase 0–8 主時程。
- No per-action human approval or rollback; those belong to later `add-agent-approval`. / 不做逐動作核准或 rollback；留給後續 `add-agent-approval`。
- No change to audit or trajectory file formats beyond additive optional fields. / 稽核與軌跡檔案格式只做新增可選欄位，不破壞既有讀取。

## Capabilities / 能力

### New Capabilities / 新增能力

- `agent-contract`: defines the task contract shape, validation, clarification behavior, allowed-tools narrowing, and terminal status recording. / 定義 task contract 形狀、驗證、模糊時提問、工具白名單收斂與終態記錄。

### Modified Capabilities / 修改能力

- `agent`: trajectory and agent-loop behavior gain contract metadata and explicit terminal status while preserving bounded-loop and read-only invariants. / `agent` 的軌跡與代理迴圈新增 contract 中繼資料與明確終態，同時保留有限迴圈與唯讀不變量。

## Impact / 影響

- Code / 程式：`src/jiezi/runtime/trajectory.py`, `src/jiezi/agent/loop.py`, related CLI/agent entry points identified during exploration. / 相關 CLI／agent 入口以探索結果為準。
- Specs / 規格：new delta `specs/agent-contract/spec.md`; modified delta `specs/agent/spec.md`. / 新增 `specs/agent-contract/spec.md`；修改 `specs/agent/spec.md`。
- Tests / 測試：new contract validation and trajectory reconstruction tests; existing 642 tests must remain green. / 新增 contract 驗證與軌跡重建測試；既有 642 項測試不得退化。
- Classification / 分類：核心／既有模組（core module），不是 `SKILL`，也不是 `MCP`；此變更是安全不變量與軌跡格式，不對外提供工具。 / Core module, not SKILL or MCP; this is a safety invariant and trajectory format change, not an external tool.
- Existing-solution search / 現成方案搜尋：已在 dev-plan §15.3 查 MCP spec、Anthropic Skills／Building effective agents、OWASP guidance；本變更沿用 bounded loop 與 least privilege，不引入新套件。 / Already searched in dev-plan §15.3; reuse bounded loop and least privilege, no new dependency.
- Security scan / 資安掃描：no new dependency, port, permission, or secret handling; primary residual risk is contract text being treated as trusted instruction, mitigated by metadata-only handling and existing injection guard. / 無新相依、連接埠、權限或機密處理；主要殘留風險是 contract 文字被當成可信指令，以「僅中繼資料」與既有 injection guard 緩解。

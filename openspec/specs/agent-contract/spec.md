# agent-contract Specification

## Purpose
代理任務的契約欄位（工具白名單、預算）只當中繼資料，並只能收斂、不能放寬。
Task contracts are metadata that can only narrow tools and budgets.
## Requirements
### Requirement: Task contract schema / 任務契約欄位

系統 SHALL 接受包含 `goal`、`constraints`、`done_criteria`、`risk`、`allowed_tools`、`budget` 的 task contract；`goal` 與 `done_criteria` SHALL 為必填且非空。 / The system SHALL accept a task contract containing `goal`, `constraints`, `done_criteria`, `risk`, `allowed_tools`, and `budget`; `goal` and `done_criteria` SHALL be required and non-empty.

#### Scenario: 完整 contract 通過驗證 / Valid contract accepted

- **WHEN** 呼叫端提供六個欄位，且 `goal`、`done_criteria` 非空。 / **WHEN** caller provides all six fields with non-empty `goal` and `done_criteria`.
- **THEN** 系統回傳 normalized contract，附 effective budget 與有效工具子集。 / **THEN** system returns a normalized contract with an effective budget and effective tool subset.

#### Scenario: 缺少必要欄位被拒 / Missing required field rejected

- **WHEN** `goal` 或 `done_criteria` 缺失或為空白。 / **WHEN** `goal` 或 `done_criteria` is missing or blank.
- **THEN** 系統回傳釐清要求，且不呼叫任何工具。 / **THEN** system returns a clarification request and invokes no tool.

### Requirement: Contract is metadata only / Contract 僅為中繼資料

系統 SHALL 只以程式讀取 contract 欄位，不得將其注入可信指令層或視為授權來源；既有 injection guard SHALL 持續生效。 / The system SHALL consume contract fields only in code and MUST NOT inject them into the trusted instruction layer or treat them as authorization; the existing injection guard SHALL remain active.

#### Scenario: Contract 含指令式文字 / Contract contains imperative text

- **WHEN** contract 欄位包含「忽略先前規則」之類文字。 / **WHEN** a contract field contains text such as "ignore previous rules".
- **THEN** 系統將其視為資料，既有 injection guard 生效，且不改變 grant。 / **THEN** system treats it as data, the existing injection guard applies, and no grant is changed.

### Requirement: Allowed tools narrowing / 工具白名單收斂

系統 SHALL 將 `allowed_tools` 與目前 grant 允許的唯讀工具取交集；未知或未授權的名稱 SHALL 被拒絕。 / The system SHALL compute the effective tool set as the intersection of `allowed_tools` and currently granted read-only tools; unknown or ungranted names SHALL be rejected.

#### Scenario: 子集工具通過 / Subset accepted

- **WHEN** `allowed_tools` 列出已被 grant 的 `read_file`。 / **WHEN** `allowed_tools` lists granted `read_file`.
- **THEN** effective tools 只包含 `read_file`，其餘工具不可用。 / **THEN** effective tools contain only `read_file` and all other tools are unavailable.

#### Scenario: 未授權工具被拒 / Ungranted tool rejected

- **WHEN** `allowed_tools` 包含未 grant 或未知工具名稱。 / **WHEN** `allowed_tools` contains an ungranted or unknown tool name.
- **THEN** 系統拒絕該 contract，且不產生工具呼叫。 / **THEN** system rejects the contract and produces no tool call.

### Requirement: Budget capping / 預算上限收斂

系統 SHALL 將 contract `budget` 限制在既有 loop ceiling 內，並記錄 effective budget。 / The system SHALL cap contract `budget` within existing loop ceilings and record the effective budget.

#### Scenario: 超過上限被 cap / Above-ceiling value capped

- **WHEN** contract `budget` 的步數超過 `MAX_STEPS`。 / **WHEN** contract `budget` step count exceeds `MAX_STEPS`.
- **THEN** effective budget 等於 `MAX_STEPS`，且 trajectory 記錄原始值與 effective 值。 / **THEN** effective budget equals `MAX_STEPS` and trajectory records both requested and effective values.

#### Scenario: 未提供預算用預設 / Missing budget uses defaults

- **WHEN** contract 未提供 `budget`。 / **WHEN** contract omits `budget`.
- **THEN** 系統使用既有 loop 常數作為 effective budget。 / **THEN** system uses existing loop constants as the effective budget.

### Requirement: Clarification on ambiguity / 模糊時先問

系統 SHALL 在完成條件無法驗證時回傳釐清要求，且不啟動工具。 / The system SHALL return a clarification request when the completion condition cannot be verified and SHALL NOT start tools.

#### Scenario: 模糊完成條件 / Vague completion criteria

- **WHEN** `done_criteria` 僅為「做好即可」等無法檢查的文字。 / **WHEN** `done_criteria` is unverifiable text such as "just do it well".
- **THEN** 系統要求補充可檢查的完成條件，且不呼叫工具。 / **THEN** system requests a verifiable completion condition and invokes no tool.

### Requirement: Terminal status recording / 終態寫入軌跡

系統 SHALL 將 contract 與 `completed` / `failed` / `aborted` 終態寫入 trajectory，且不得寫入檔案內容或機密。 / The system SHALL write the contract and terminal state `completed` / `failed` / `aborted` to trajectory and MUST NOT write file contents or secrets.

#### Scenario: 成功執行後記錄 / Record after success

- **WHEN** 任務以 `completed` 結束。 / **WHEN** a task ends with `completed`.
- **THEN** trajectory 包含 contract、終態與時間欄位，且不含檔案內容。 / **THEN** trajectory contains contract, terminal state, and timestamps, with no file contents.

#### Scenario: 寫入失敗不影響回答 / Write failure does not break response

- **WHEN** trajectory 寫入發生 `OSError`。 / **WHEN** trajectory write raises `OSError`.
- **THEN** 系統保留 warning 與 last error，回答流程不受影響。 / **THEN** system keeps the warning and last error while the response flow remains unaffected.


## ADDED Requirements

### Requirement: Contract-aware agent loop / 感知契約的代理迴圈

代理迴圈 SHALL 在分派任何工具之前驗證 task contract；驗證失敗時 SHALL 停止且不呼叫工具。 / The agent loop SHALL validate the task contract before dispatching any tool; on validation failure it SHALL stop without invoking tools.

#### Scenario: 有效 contract 才進入 bounded loop / Valid contract enters bounded loop

- **WHEN** contract 通過 `agent-contract` 驗證。 / **WHEN** the contract passes `agent-contract` validation.
- **THEN** 迴圈只用 effective budget 與 effective tools 執行 observe → think → act → verify → answer。 / **THEN** the loop executes observe → think → act → verify → answer using only the effective budget and effective tools.

#### Scenario: 驗證失敗不進入工具呼叫 / Validation failure blocks tool calls

- **WHEN** contract 缺少 `goal` 或包含未授權工具。 / **WHEN** the contract lacks `goal` or contains an ungranted tool.
- **THEN** 迴圈回傳釐清或拒絕結果，且 tool call 次數為零。 / **THEN** the loop returns a clarification or rejection result with zero tool calls.

### Requirement: Trajectory reconstructability / 軌跡可重建

trajectory SHALL 附加 contract 與終態欄位，並保留既有本機 JSONL、retention 與寫入失敗不放寬回答的語意。 / Trajectory SHALL add contract and terminal-state fields while preserving local-only JSONL, retention, and non-breaking write failure semantics.

#### Scenario: 單次執行可重建 / Single run reconstructable

- **WHEN** 任務結束並寫入 trajectory。 / **WHEN** a task ends and is written to trajectory.
- **THEN** 該筆記錄包含 contract、effective budget、effective tools、terminal state 與時間欄位。 / **THEN** the record contains contract, effective budget, effective tools, terminal state, and timestamps.

#### Scenario: 舊資料仍可讀 / Existing records remain readable

- **WHEN** 讀取 change 前既有的 trajectory JSONL。 / **WHEN** reading trajectory JSONL written before this change.
- **THEN** 既有欄位維持原義，缺少新欄位不視為錯誤。 / **THEN** existing fields keep their meaning and missing new fields are not an error.

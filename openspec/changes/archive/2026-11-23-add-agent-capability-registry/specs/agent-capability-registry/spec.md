## ADDED Requirements

### Requirement: Capability registry TOML file / 能力登錄表 TOML 檔案

系統 SHALL 在 `docs/capabilities.toml` 提供機器可讀的能力登錄表，格式為 TOML 陣列 `[[capabilities]]`，每筆記錄包含 `id`、`name`、`kind`、`change`、`existing_solutions`、`security_scan`、`version`、`owner`、`removal_condition`、`status` 十個欄位。/ The system SHALL provide a machine-readable capability registry at `docs/capabilities.toml` as a TOML array `[[capabilities]]` with each record containing `id`, `name`, `kind`, `change`, `existing_solutions`, `security_scan`, `version`, `owner`, `removal_condition`, `status`.

#### Scenario: 登錄表可載入且欄位齊全 / Registry loads with all fields

- **WHEN** 呼叫 `capabilities.load("docs/capabilities.toml")`。 / **WHEN** calling `capabilities.load("docs/capabilities.toml")`.
- **THEN** 回傳列表，每筆為含十個必要鍵的字典，且 `kind` ∈ {"skill", "mcp", "core"}、`status` ∈ {"enabled", "disabled", "deprecated"}。 / **THEN** returns a list where each item is a dict with all ten required keys, and `kind` ∈ {"skill", "mcp", "core"}, `status` ∈ {"enabled", "disabled", "deprecated"}.

#### Scenario: 登錄表缺檔拋例外 / Missing registry raises exception

- **WHEN** `docs/capabilities.toml` 不存在。 / **WHEN** `docs/capabilities.toml` does not exist.
- **THEN** `load()` 拋 `FileNotFoundError`。 / **THEN** `load()` raises `FileNotFoundError`.

#### Scenario: 登錄表格式錯誤拋例外 / Malformed registry raises exception

- **WHEN** `docs/capabilities.toml` 內容非合法 TOML。 / **WHEN** `docs/capabilities.toml` contains invalid TOML.
- **THEN** `load()` 拋 `ValueError`（或 `tomllib.TOMLDecodeError`）。 / **THEN** `load()` raises `ValueError` (or `tomllib.TOMLDecodeError`).

### Requirement: Registry validation / 登錄表驗證

`capabilities.validate(records)` SHALL 對每筆記錄執行下列檢查，回傳錯誤訊息列表（空列表 = 全部通過）：/ `capabilities.validate(records)` SHALL perform the following checks on each record and return a list of error messages (empty list = all pass):

1. **必要欄位齊全**：十個欄位皆存在且非 `None`。/ All ten fields present and not `None`.
2. **kind 合法**：值為 "skill"、"mcp" 或 "core"。/ Value is "skill", "mcp", or "core".
3. **existing_solutions 非空或有理由**：若字串去除空白後為空，且不含「無，理由：」或「none, reason:」（不分大小寫）→ 錯誤。/ If string is blank after stripping and does not contain "無，理由：" or "none, reason:" (case-insensitive) → error.
4. **security_scan 含日期與結論**：需可用 regex 擷取 YYYY-MM-DD 日期與 "ok" 或 "issues" 結論；無法擷取 → 錯誤。/ Must be able to extract YYYY-MM-DD date and "ok"/"issues" conclusion via regex; failure to extract → error.
5. **status 與 security_scan 一致性**：若 security_scan 結論為 "issues" 但 status == "enabled" → 錯誤。/ If security_scan conclusion is "issues" but status == "enabled" → error.
6. **id 唯一**：全表 `id` 不重複。/ All `id` values unique across the registry.

#### Scenario: 合法記錄通過驗證 / Valid record passes validation

- **WHEN** 傳入符合上述六條規則的記錄列表。 / **WHEN** passing a record list satisfying all six rules.
- **THEN** `validate()` 回傳空列表。 / **THEN** `validate()` returns an empty list.

#### Scenario: 缺欄位被偵測 / Missing field detected

- **WHEN** 記錄缺少 `removal_condition`。 / **WHEN** a record lacks `removal_condition`.
- **THEN** 回傳列表含「capability 'xxx': missing required field 'removal_condition'」。 / **THEN** returned list contains "capability 'xxx': missing required field 'removal_condition'".

#### Scenario: kind 不合法被偵測 / Invalid kind detected

- **WHEN** 記錄 `kind = "plugin"`。 / **WHEN** a record has `kind = "plugin"`.
- **THEN** 回傳列表含「capability 'xxx': invalid kind 'plugin', must be one of skill,mcp,core」。 / **THEN** returned list contains "capability 'xxx': invalid kind 'plugin', must be one of skill,mcp,core".

#### Scenario: existing_solutions 空且無理由被偵測 / Empty existing_solutions without reason detected

- **WHEN** 記錄 `existing_solutions = ""`。 / **WHEN** a record has `existing_solutions = ""`.
- **THEN** 回傳列表含「capability 'xxx': existing_solutions is empty and no reason provided」。 / **THEN** returned list contains "capability 'xxx': existing_solutions is empty and no reason provided".

#### Scenario: security_scan issues 但 status enabled 被偵測 / Security scan issues with enabled status detected

- **WHEN** 記錄 `security_scan = "2026-11-20 issues (critical vulnerability)"` 且 `status = "enabled"`。 / **WHEN** a record has `security_scan = "2026-11-20 issues (critical vulnerability)"` and `status = "enabled"`.
- **THEN** 回傳列表含「capability 'xxx': security_scan reports issues but status is enabled」。 / **THEN** returned list contains "capability 'xxx': security_scan reports issues but status is enabled".

#### Scenario: 重複 id 被偵測 / Duplicate id detected

- **WHEN** 兩筆記錄 `id = "agent-contract"`。 / **WHEN** two records have `id = "agent-contract"`.
- **THEN** 回傳列表含「duplicate capability id: agent-contract」。 / **THEN** returned list contains "duplicate capability id: agent-contract".

### Requirement: Proposal three-section check / Proposal 三段檢查

`capabilities.check_proposals(root)` SHALL 掃描 `root` 下每個子目錄（排除 `archive/`），讀取各目錄的 `proposal.md`，檢查是否含有三個必要段落（標題不分大小寫，或內文關鍵字）：/ `capabilities.check_proposals(root)` SHALL scan each subdirectory under `root` (excluding `archive/`), read each `proposal.md`, and check for the presence of three required sections (case-insensitive headers or inline keywords):

1. **分類**：標題 `## Classification` 或 `## 分類`，或內文含「分類：」／「Classification:」。/ Header `## Classification` or `## 分類`, or body contains "分類：" / "Classification:".
2. **現成方案**：標題 `## Existing-solution search` 或 `## 現成方案搜尋`，或內文含「現成方案」／「Existing solution」。/ Header `## Existing-solution search` or `## 現成方案搜尋`, or body contains "現成方案" / "Existing solution".
3. **資安掃描**：標題 `## Security scan` 或 `## 資安掃描`，或內文含「資安掃描」／「Security scan」。/ Header `## Security scan` or `## 資安掃描`, or body contains "資安掃描" / "Security scan".

回傳 `{change_name: [missing_section_names]}`，僅包含有缺項的 change；無缺項者不出現在結果中。/ Returns `{change_name: [missing_section_names]}`; only changes with missing sections appear in the result.

#### Scenario: 完整 proposal 通過檢查 / Complete proposal passes check

- **WHEN** `proposal.md` 同時含有上述三段（標題或關鍵字）。 / **WHEN** `proposal.md` contains all three sections (headers or keywords).
- **THEN** 該 change 不出現在回傳字典中。 / **THEN** the change does not appear in the returned dict.

#### Scenario: 缺分類段被偵測 / Missing classification section detected

- **WHEN** `proposal.md` 無「分類」標題或關鍵字。 / **WHEN** `proposal.md` lacks "Classification" header or keyword.
- **THEN** 回傳字典含 `{"change-name": ["Classification"]}`。 / **THEN** returned dict contains `{"change-name": ["Classification"]}`.

#### Scenario: 缺現成方案段被偵測 / Missing existing-solution section detected

- **WHEN** `proposal.md` 無「現成方案」標題或關鍵字。 / **WHEN** `proposal.md` lacks "Existing-solution" header or keyword.
- **THEN** 回傳字典含 `{"change-name": ["Existing-solution search"]}`。 / **THEN** returned dict contains `{"change-name": ["Existing-solution search"]}`.

#### Scenario: 缺資安掃描段被偵測 / Missing security scan section detected

- **WHEN** `proposal.md` 無「資安掃描」標題或關鍵字。 / **WHEN** `proposal.md` lacks "Security scan" header or keyword.
- **THEN** 回傳字典含 `{"change-name": ["Security scan"]}`。 / **THEN** returned dict contains `{"change-name": ["Security scan"]}`.

#### Scenario: archive 目錄被略過 / Archive directory skipped

- **WHEN** `root` 下存在 `archive/` 子目錄。 / **WHEN** `root` contains an `archive/` subdirectory.
- **THEN** `check_proposals()` 不掃描 `archive/` 內的 proposal。 / **THEN** `check_proposals()` does not scan proposals inside `archive/`.

### Requirement: CLI capabilities check command / CLI capabilities check 子命令

系統 SHALL 在 `jiezi` CLI 提供 `capabilities check` 子命令，呼叫 `load()`、`validate()`、`check_proposals()` 並輸出結果。/ The system SHALL provide a `jiezi capabilities check` subcommand that invokes `load()`, `validate()`, `check_proposals()` and prints results.

#### Scenario: CLI 正常輸出 / CLI normal output

- **WHEN** 執行 `jiezi capabilities check` 且登錄表與 proposals 均通過。 / **WHEN** running `jiezi capabilities check` with both registry and proposals passing.
- **THEN** 標準輸出含「Registry validation: OK」、「Proposal three-section check: OK」，退出碼 0。 / **THEN** stdout contains "Registry validation: OK", "Proposal three-section check: OK", exit code 0.

#### Scenario: CLI 偵測到驗證錯誤 / CLI detects validation errors

- **WHEN** 登錄表有驗證錯誤。 / **WHEN** registry has validation errors.
- **THEN** 標準錯誤輸出列出錯誤細節，退出碼 1。 / **THEN** stderr lists error details, exit code 1.

#### Scenario: CLI 偵測到 proposal 缺項 / CLI detects proposal missing sections

- **WHEN** 某 change 的 proposal 缺三段之一。 / **WHEN** a change's proposal misses one of the three sections.
- **THEN** 標準輸出列出缺項清單，退出碼 1。 / **THEN** stdout lists missing sections, exit code 1.

#### Scenario: CLI 支援自訂路徑參數 / CLI supports custom path arguments

- **WHEN** 執行 `jiezi capabilities check --toml custom.toml --changes-root custom/changes`。 / **WHEN** running `jiezi capabilities check --toml custom.toml --changes-root custom/changes`.
- **THEN** 分別載入 `custom.toml` 掃描 `custom/changes`，不讀取預設路徑。 / **THEN** loads `custom.toml` and scans `custom/changes`, not the default paths.
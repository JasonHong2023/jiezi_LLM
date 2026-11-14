## MODIFIED Requirements

### Requirement: Scoring

系統 SHALL 自動評分選擇題（取出 A–D）；Chinese SimpleQA SHALL 同時保留近似比對（標示「近似，非官方評分」）並在評審可用時加上 LLM 評審結果，兩者分開列出；程式、工具呼叫與摘要題 SHALL 由 `verifiers` 能力評分，對應驗證器不可用時 SHALL 標為 `pending_verifier` 並記錄原因。
The system SHALL auto-score multiple choice (extracting A–D); Chinese SimpleQA SHALL keep approximate matching (labeled "approximate, not the official scorer") and add LLM-judge results when the judge is available, listed separately; code, tool-call, and summary items SHALL be scored through the `verifiers` capability, and SHALL be marked `pending_verifier` with the reason recorded when the matching verifier is unavailable.

#### Scenario: 無法解析的選擇題回答 / Unparseable multiple-choice answer

- **WHEN** 回答中找不到獨立的 A–D
  No standalone A–D is found in the response
- **THEN** 該題記為錯誤並標記 `unparsed`，報表列出 `unparsed` 題數
  The item counts as wrong, is flagged `unparsed`, and the report lists the `unparsed` count

#### Scenario: 沙盒不可用 / Sandbox unavailable

- **WHEN** 執行評測時沒有可用的程式沙盒
  No code sandbox is available during a run
- **THEN** 程式題標為 `pending_verifier`，`details.reason` 記錄原因，其他題型照常評分
  Code items are `pending_verifier` with `details.reason`, and other item types are scored as usual

## ADDED Requirements

### Requirement: After-the-Fact Verification

系統 SHALL 提供 `verify <run_id>`，對已完成執行的回答重新評分而不重跑模型；驗證結果 SHALL 寫入獨立檔案，原始回答 SHALL NOT 被修改；報表 SHALL 列出驗證器版本、沙盒設定與評審條件。需要評審或沙盒的驗證屬長時間工作，SHALL 遵守夜間時段。
The system SHALL provide `verify <run_id>` that rescores a finished run's responses without rerunning the model; results SHALL go to a separate file and raw responses SHALL NOT be modified; reports SHALL list verifier versions, sandbox settings, and judge conditions. Verification needing the judge or sandbox is a long job and SHALL obey the night window.

#### Scenario: 白天驗證需評審的執行 / Daytime verification needing the judge

- **WHEN** 在夜間時段外執行需要評審的 `verify`，且沒有 `--now`
  `verify` needing the judge runs outside the night window without `--now`
- **THEN** 系統拒絕並提示改用 `schedule`
  The system refuses and suggests `schedule`

#### Scenario: 原始回答不變 / Raw responses unchanged

- **WHEN** `verify` 完成
  `verify` finishes
- **THEN** `results.jsonl` 的內容與執行前逐位元組相同
  `results.jsonl` is byte-identical to before

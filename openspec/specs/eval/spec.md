# eval Specification

## Purpose
TBD - created by archiving change add-eval-harness. Update Purpose after archive.
## Requirements
### Requirement: Pinned Bank Sources

題庫的每個來源 SHALL 在 `eval/banks/r0.toml` 以鎖定的 revision 或 release 定義，並附下載檔的 SHA-256；下載後雜湊不符時系統 SHALL 停止並說明，不得自動改用新版本。
Every bank source SHALL be defined in `eval/banks/r0.toml` at a pinned revision or release with the SHA-256 of its download; on a hash mismatch the system SHALL stop and explain, never silently switching versions.

#### Scenario: 上游檔案變動 / Upstream file changed

- **WHEN** 下載的來源檔 SHA-256 與定義不符
  A downloaded source file's SHA-256 differs from the definition
- **THEN** 系統停止、刪除該下載並指出來源名稱與兩個雜湊值
  The system stops, deletes the download, and names the source and both hashes

### Requirement: License Gate

每個來源 SHALL 在 `docs/licenses.md` 有登記（來源、授權、是否允許商用、是否允許訓練、查證日期與查證來源），並在定義中以登記鍵引用；未登記的來源 SHALL NOT 被下載（規則 R18.3）。
Every source SHALL be registered in `docs/licenses.md` (source, license, commercial use, training use, check date and evidence) and referenced by registry key; an unregistered source SHALL NOT be downloaded (rule R18.3).

#### Scenario: 未登記的來源 / Unregistered source

- **WHEN** 來源定義引用的登記鍵不在 `docs/licenses.md`
  A source references a registry key missing from `docs/licenses.md`
- **THEN** 系統拒絕下載並指出缺少的登記鍵
  The system refuses to download and names the missing key

### Requirement: Reproducible Bank Lock

系統 SHALL 以固定種子抽題並寫出 `eval/banks/r0.lock.json`，內含每題的來源 ID、正規化內容的 SHA-256 與整份題庫的 `bank_hash`；任何機器依鎖定檔取得的題目 SHALL 與鎖定檔一致。題目內容 SHALL NOT 進版控。
The system SHALL sample with a fixed seed and write `eval/banks/r0.lock.json` with each item's source ID, the SHA-256 of its normalized content, and the whole-bank `bank_hash`; items materialized from the lock on any machine SHALL match it. Item content SHALL NOT be versioned.

#### Scenario: 另一台電腦重建題庫 / Rebuilding the bank elsewhere

- **WHEN** 在另一台電腦依同一份鎖定檔建立題庫
  The bank is materialized from the same lock on another machine
- **THEN** 每題雜湊與 `bank_hash` 都與鎖定檔相同
  Every item hash and the `bank_hash` match the lock

#### Scenario: 題目內容不符 / Item content mismatch

- **WHEN** 某題正規化後的雜湊與鎖定檔不同
  An item's normalized hash differs from the lock
- **THEN** 系統停止並列出不符的題目，不以不同的題目繼續評測
  The system stops and lists the mismatching items instead of evaluating different items

### Requirement: Bank Composition

R0 題庫 SHALL 涵蓋四類任務（中文問答、寫程式、文件摘要、工具呼叫），每類至少 50 題，並以 `group` 欄位區分「知識」與「推理 / 工具」；摘要題 SHALL 取自中文維基百科並以 revision ID 鎖定（使用者 2026-11-14 決定）。
The R0 bank SHALL cover four task types (Chinese QA, coding, document summarization, tool calling) with at least 50 items each, tagging every item with a `group` of "knowledge" or "reasoning / tools"; summary items SHALL come from Chinese Wikipedia pinned by revision ID (user decision 2026-11-14).

#### Scenario: 題數檢查 / Item-count check

- **WHEN** 產生鎖定檔
  The lock file is generated
- **THEN** 每類任務至少 50 題，否則產生失敗並指出不足的類別
  Each task type has at least 50 items, otherwise generation fails naming the short type

### Requirement: Interchangeable Backends

評測 SHALL 能以同一份題庫在本機 llama.cpp 與任何 OpenAI 相容雲端端點上執行，結果格式相同；雲端端點、金鑰與模型名稱 SHALL 只來自 `.env`（規則 R21.3）。
Evaluation SHALL run the same bank against local llama.cpp or any OpenAI-compatible cloud endpoint with identical result formats; the cloud endpoint, key, and model name SHALL come only from `.env` (rule R21.3).

#### Scenario: 未設定雲端 / No cloud configured

- **WHEN** 要求雲端評測但 `.env` 沒有 `JIEZI_CLOUD_BASE_URL`
  A cloud run is requested but `.env` has no `JIEZI_CLOUD_BASE_URL`
- **THEN** 系統拒絕執行並說明需要的變數，本機評測不受影響
  The system refuses and names the needed variables; local runs are unaffected

### Requirement: Baseline Model Guard

基準模式 SHALL 在每個請求帶 `"disable_fallbacks": true`，並核對回應的 `model` 欄位；不符的題目 SHALL 標為作廢且不計分（規則 R17.1）。
Baseline mode SHALL send `"disable_fallbacks": true` with every request and check the response's `model`; mismatching items SHALL be marked void and not scored (rule R17.1).

#### Scenario: 被靜默換模型 / Silently swapped model

- **WHEN** 回應的 `model` 與請求的基準模型不同
  The response's `model` differs from the requested baseline model
- **THEN** 該題標為 `void_model_mismatch`，報表列出作廢題數與實際模型
  The item is marked `void_model_mismatch`, and the report lists the void count and actual models

### Requirement: Local Engine Isolation

框架啟動的 `llama-server` SHALL 只綁定 `127.0.0.1`，port 取自實驗區段（`JIEZI_PORT_BASE + 10` 至 `+ 19`），執行緒數、`nice` 與 CPU 綁定 SHALL 取自 `facts.json` 的 `budgets`；評測結束或中斷時 SHALL 關閉該程序（規則 R6.12、R11、R18）。
The `llama-server` started by the harness SHALL bind only to `127.0.0.1` on a port from the experiment block (`JIEZI_PORT_BASE + 10` to `+ 19`), with threads, `nice`, and CPU pinning taken from `budgets` in `facts.json`; it SHALL be stopped when the run ends or is interrupted (rules R6.12, R11, R18).

#### Scenario: port 被占用 / Port in use

- **WHEN** `JIEZI_PORT_BASE + 10` 已被占用
  `JIEZI_PORT_BASE + 10` is taken
- **THEN** 系統改用區段內下一個空的 port；整段都被占用時停止並說明
  The system uses the next free port in the block, or stops and explains if the whole block is taken

#### Scenario: 中斷 / Interruption

- **WHEN** 評測被 Ctrl-C 或錯誤中斷
  The run is interrupted by Ctrl-C or an error
- **THEN** `llama-server` 被關閉，已完成的結果保留
  `llama-server` is stopped and finished results are kept

### Requirement: Hang and Failure Handling

每個後端請求 SHALL 有逾時；逾時、連線錯誤、HTTP 429 / 5xx SHALL 最多重試 2 次；仍失敗的題目 SHALL 記為錯誤（不計分、不算答錯）並繼續下一題；連續 5 題失敗時 SHALL 暫停整次執行並保存結果；`--resume --retry-errors` SHALL 只補跑失敗的題目（使用者 2026-11-14：免費模型有時會卡住）。
Every backend request SHALL have a timeout; timeouts, connection errors, and HTTP 429 / 5xx SHALL be retried at most twice; items that still fail SHALL be recorded as errors (neither scored nor counted wrong) and the run SHALL continue; five consecutive failures SHALL pause the run with results saved; `--resume --retry-errors` SHALL rerun only the failed items (user, 2026-11-14: free models sometimes hang).

#### Scenario: 雲端模型卡住 / Cloud model hangs

- **WHEN** 某題的請求超過逾時且重試後仍逾時
  An item's request times out, including its retries
- **THEN** 該題記為 `error_timeout`，執行繼續下一題，報表分列失敗題數並標示「不完整」
  The item is recorded as `error_timeout`, the run continues, and the report lists failures and is labeled "incomplete"

#### Scenario: 服務中斷 / Service outage

- **WHEN** 連續 5 題失敗
  Five consecutive items fail
- **THEN** 整次執行暫停並保存結果，提示以 `--resume --retry-errors` 稍後補跑
  The run pauses with results saved and suggests `--resume --retry-errors` later

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

### Requirement: Measurement Conditions

每次執行 SHALL 寫出 `conditions.json`，包含規則 R17.1 的全部條件、提示模板雜湊與 thinking 開關；條件不同的執行 SHALL NOT 以 `--resume` 合併。
Every run SHALL write `conditions.json` with all rule R17.1 conditions, the prompt-template hash, and the thinking switch; runs with different conditions SHALL NOT be merged via `--resume`.

#### Scenario: 條件不同時續跑 / Resuming under different conditions

- **WHEN** 以不同的模型或取樣參數對既有 `run_id` 執行 `--resume`
  `--resume` is used on an existing `run_id` with a different model or sampling parameters
- **THEN** 系統拒絕並列出不同的條件
  The system refuses and lists the differing conditions

### Requirement: Resumable Runs

結果 SHALL 逐題寫入；`--resume <run_id>` SHALL 略過已有結果的題目，從未完成的題目接續。
Results SHALL be written per item; `--resume <run_id>` SHALL skip items that already have results and continue with the rest.

#### Scenario: 中途停止後續跑 / Resume after stopping

- **WHEN** 一次執行完成 80 題後停止，再以 `--resume` 執行
  A run stops after 80 items and is resumed
- **THEN** 只評測剩下的題目，最終報表涵蓋全部題目
  Only the remaining items are evaluated, and the final report covers all items

### Requirement: Night Window

長時間評測 SHALL 只在 `JIEZI_NIGHT_WINDOW`（當地時間，預設 `00:00-07:00`）內啟動新題目；時段外啟動 SHALL 被拒絕，除非使用者明確加上 `--now`；超過時段結尾時 SHALL 不再啟動新題、保存結果並結束（規則 R18.2a）。
Long runs SHALL start new items only inside `JIEZI_NIGHT_WINDOW` (local time, default `00:00-07:00`); starting outside it SHALL be refused unless the user explicitly passes `--now`; past the window end the run SHALL start no new items, save results, and exit (rule R18.2a).

#### Scenario: 白天啟動 / Started in the daytime

- **WHEN** 在時段外執行 `scripts/eval run` 且沒有 `--now`
  `scripts/eval run` is invoked outside the window without `--now`
- **THEN** 系統拒絕並提示使用 `scripts/eval schedule`
  The system refuses and suggests `scripts/eval schedule`

#### Scenario: 跑到早上 / Running into the morning

- **WHEN** 執行中到達時段結尾
  The window end is reached mid-run
- **THEN** 目前這題完成後就停止，提示以 `--resume` 在下一個夜間時段續跑
  The run stops after the current item and suggests resuming in the next night window

### Requirement: Night Scheduling

`scripts/eval schedule` SHALL 建立一次性排程，在下一個夜間時段開始後自動執行指定的評測；一個排程可含多個工作，SHALL 依序執行（前一個失敗也繼續）並逐一記錄結果；有使用者層級 systemd 時用 `systemd-run --user`，否則用與終端機脫離的背景程序；排程內容與狀態 SHALL 寫入 `var/eval/schedule/`，且不需要 sudo。
`scripts/eval schedule` SHALL create a one-shot schedule that runs the given evaluation after the next night window opens; one schedule may hold several jobs, which SHALL run in order (continuing after a failure) with each result recorded; using `systemd-run --user` when user-level systemd exists and a terminal-detached background process otherwise; schedule details and state SHALL be written to `var/eval/schedule/`, without sudo.

#### Scenario: 排程後查看 / Inspecting a schedule

- **WHEN** 使用者執行 `scripts/eval schedule --list`
  The user runs `scripts/eval schedule --list`
- **THEN** 顯示每個排程的預定時間、指令、狀態（等待中、執行中、完成、失敗）
  Each schedule's planned time, command, and state (waiting, running, done, failed) is shown

### Requirement: Reports

`scripts/eval report <run_id>` SHALL 產生 `report.json` 與 `report.md`：知識題與推理 / 工具題分開、貪婪解碼與多樣本執行分開標示、未評分與作廢題數分列，並附 t/s、峰值記憶體（RAM、VRAM）、token 用量與量測條件（規則 R17.5）。
`scripts/eval report <run_id>` SHALL produce `report.json` and `report.md` separating knowledge from reasoning / tool items, labeling greedy versus multi-sample runs, listing unscored and void counts separately, and including t/s, peak memory (RAM, VRAM), token usage, and measurement conditions (rule R17.5).

#### Scenario: 只給總平均 / Only an overall average

- **WHEN** 產生報表
  A report is produced
- **THEN** 報表沒有把知識題與推理 / 工具題合併成單一總分
  The report never merges knowledge and reasoning / tool items into one overall score

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


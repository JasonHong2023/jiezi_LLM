# verifiers Specification

## Purpose
TBD - created by archiving change add-verifiers. Update Purpose after archive.
## Requirements
### Requirement: Sandboxed Code Execution

系統 SHALL 只在 bubblewrap 沙盒內執行模型產生的程式：無網路、系統唯讀、不掛載家目錄與專案目錄、有記憶體 / 行程數 / CPU / 實際時間 / 輸出上限，並綁定資源預算核心。沙盒不可用時 SHALL NOT 在沙盒外執行，程式題 SHALL 維持 `pending_verifier` 並記錄原因。
The system SHALL run model-generated code only inside a bubblewrap sandbox: no network, read-only system, no home or project mounts, memory / process / CPU / wall-clock / output limits, pinned to budget cores. When the sandbox is unavailable it SHALL NOT run code outside it; code items SHALL stay `pending_verifier` with the reason recorded.

#### Scenario: 沙盒自我檢查失敗 / Sandbox self-test fails

- **WHEN** 沙盒內的測試程式能連到 `127.0.0.1` 上的服務或能寫入家目錄
  A probe inside the sandbox can reach a service on `127.0.0.1` or write to home
- **THEN** 程式驗證停用，所有程式題標為 `pending_verifier`，報表寫出原因
  Code verification is disabled, every code item is `pending_verifier`, and the report states the reason

#### Scenario: 失控的候選程式 / Runaway candidate code

- **WHEN** 候選程式無窮迴圈、配置過多記憶體或大量 fork
  Candidate code loops forever, allocates too much memory, or forks repeatedly
- **THEN** 沙盒在上限內終止它，該題記為錯誤並標記 `timeout` 或 `resource_limit`，評測繼續下一題
  The sandbox kills it within the limits, the item counts as wrong flagged `timeout` or `resource_limit`, and evaluation continues

### Requirement: Code Verifier

系統 SHALL 以 evalplus 的方式判定 HumanEval+ / MBPP+：標準解答在沙盒內產生期望輸出，候選程式逐筆比對（浮點數用題目的 `atol`），分別記錄 `base_pass` 與 `plus_pass`，`score` 為 `plus_pass`。
The system SHALL judge HumanEval+ / MBPP+ the evalplus way: the canonical solution produces expected outputs in the sandbox, candidate outputs are compared per input (floats with the item's `atol`), `base_pass` and `plus_pass` are recorded separately, and `score` is `plus_pass`.

#### Scenario: 只通過基本測試 / Passes base tests only

- **WHEN** 候選程式通過所有 base 輸入但有 plus 輸入不符
  The candidate passes every base input but fails a plus input
- **THEN** 記錄 `base_pass = true`、`plus_pass = false`、`score = 0`
  It records `base_pass = true`, `plus_pass = false`, `score = 0`

### Requirement: Tool-Call Verifier

系統 SHALL 以 Python `ast` 解析工具呼叫回答（只接受字面值），SHALL NOT 執行回答內容，並依鎖定 commit 的 ACEBench normal 規則比對 `ground_truth`。
The system SHALL parse tool-call responses with Python `ast` (literals only), SHALL NOT execute response content, and SHALL match against `ground_truth` using the ACEBench normal rules at the pinned commit.

#### Scenario: 回答含運算式 / Response contains an expression

- **WHEN** 回答的參數值是非純數字的運算式或 lambda（例如 `f(x=a+1)`、`f(x=lambda: 0)`）
  An argument value is a non-numeric expression or a lambda
- **THEN** 該題記為錯誤並標記 `unparsed`，不執行任何內容（官方以 eval 計算，列為已知差異）
  The item counts as wrong, flagged `unparsed`, and nothing is executed (upstream evals it; a known difference)

#### Scenario: 回答含名稱或呼叫 / Response contains a name or a call

- **WHEN** 參數值是名稱或呼叫（例如 `f(x=__import__("os"))`）
  An argument value is a name or a call
- **THEN** 依官方規則轉為字串或 `{名稱: {...}}` 結構後比對，**不執行**
  It is converted per upstream rules into a string or a `{name: {...}}` structure and compared, **never executed**

### Requirement: Summary Rule Checks

系統 SHALL 不靠模型檢查每份摘要的字數（去空白後 100–150 字）與是否含只屬簡體的字（以已登記的 OpenCC 表判定），結果與評審分數分開列出。
The system SHALL check each summary without a model for length (100–150 characters excluding whitespace) and simplified-only characters (using the registered OpenCC table), listed apart from judge scores.

#### Scenario: 含簡體字 / Contains simplified characters

- **WHEN** 摘要含有只出現在繁轉簡表值側的字
  The summary contains characters that appear only on the value side of the T→S table
- **THEN** 標記「含簡體字」並列出那些字
  It is flagged "contains simplified characters" with those characters listed

### Requirement: LLM Judge

系統 SHALL 以 LLM 評審判定 Chinese SimpleQA（`correct` / `incorrect` / `not_attempted`）與摘要的忠實度、涵蓋度；評審模型 SHALL 由設定指定且不得與被評模型相同，停用 fallback 並核對實際模型，溫度 0；每次評審 SHALL 以（題目雜湊、回答雜湊、評審模型、提示雜湊）快取，評審條件 SHALL 寫入報表。評審呼叫 SHALL 只在使用者同意後進行。
The system SHALL use an LLM judge for Chinese SimpleQA (`correct` / `incorrect` / `not_attempted`) and summary faithfulness and coverage; the judge model SHALL come from configuration and never equal the model under evaluation, with fallback disabled, the actual model verified, and temperature 0; every judgment SHALL be cached by (item hash, response hash, judge model, prompt hash), and judge conditions SHALL appear in reports. Judge calls SHALL happen only with user consent.

#### Scenario: 評審模型與被評模型相同 / Judge equals the evaluated model

- **WHEN** `JIEZI_JUDGE_MODEL` 與執行紀錄中的模型相同
  `JIEZI_JUDGE_MODEL` equals the model in the run record
- **THEN** 系統拒絕評審並說明原因
  The system refuses to judge and explains why

#### Scenario: 重產報表 / Regenerating a report

- **WHEN** 同一份回答已評審過，再次執行 `verify` 或 `report`
  Responses were already judged and `verify` or `report` runs again
- **THEN** 使用快取，不發出新的評審請求
  The cache is used and no new judge request is sent

#### Scenario: 評審回覆無法解析 / Unparseable judge reply

- **WHEN** 評審回覆重試一次後仍不是規定的 JSON
  The judge reply is still not the required JSON after one retry
- **THEN** 該題標記 `judge_unparsed`，不計分，報表列出題數
  The item is flagged `judge_unparsed`, unscored, and the report lists the count


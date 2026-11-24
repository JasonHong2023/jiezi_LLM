# tools Specification

## Purpose
TBD - created by archiving change add-tools. Update Purpose after archive.
## Requirements
### Requirement: Computed Facts

問題含算式、單位換算或日期計算時，gateway SHALL 由程式算出結果附給模型，並 SHALL 在回答後附上計算結果；計算 SHALL NOT 使用 eval，且 SHALL 不把模型名稱、日期、電話號碼當成算式。
For arithmetic, unit or date questions the gateway SHALL compute the result in code, attach it, and append it after the answer; it SHALL NOT use eval and SHALL NOT treat model names, dates or phone numbers as expressions.

#### Scenario: 算錯的題目 / A wrong claim

- **WHEN** 使用者問「1+3=2 多少?」
  The user asks "1+3=2 多少?"
- **THEN** 模型收到「1+3 = 4（題目寫的 2 不正確）」
  The model receives that 1+3 is 4 and the claim of 2 is wrong

#### Scenario: 模型算錯 / The model errs

- **WHEN** 問「2^10 是多少」，本機模型回答 2048
  The local model answers 2048 to 2^10
- **THEN** 答案查核不通過，本機帶著錯誤說明重答
  The grounded check fails and the model retries

#### Scenario: 不是算式 / Not an expression

- **WHEN** 使用者問「Qwen3.5-2B 是什麼」或提到電話「0912-345-678」
  The user mentions a model name or a phone number
- **THEN** 不附計算結果
  No computed facts are attached

### Requirement: Optional external MCP tool registration / 可選外部 MCP 工具註冊

The tools capability SHALL register an optional external MCP tool only when it is explicitly enabled, passes the capability's policy validation, and appears in the approved allowlist. / tools 能力 SHALL 只有在明確啟用、通過該能力的政策驗證且出現在核准白名單時，才註冊可選外部 MCP 工具。

#### Scenario: External tool not enabled / 外部工具未啟用

- **WHEN** the external MCP capability switch is off. / **WHEN** 外部 MCP 能力開關為 off。
- **THEN** the tools registry contains no tool from that server. / **THEN** 工具登錄不含該伺服器的任何工具。

#### Scenario: Enabled but policy fails / 已啟用但政策失敗

- **WHEN** the capability is enabled but a tool fails URL, allowlist, or dependency-security validation. / **WHEN** 能力已啟用但工具未通過 URL、白名單或相依資安驗證。
- **THEN** the tool is not registered and the rejection reason is recorded. / **THEN** 工具不註冊，並記錄拒絕原因。

#### Scenario: Preferred backend fails over / 首選後端回退（R19.4）

- **WHEN** the preferred `web-fetch` backend is unavailable and the `scrapling` fallback passes the opt-in switch and all policy/security gates. / **WHEN** 首選 `web-fetch` 後端不可用，且 `scrapling` 回退通過 opt-in 開關與所有政策／資安關卡。
- **THEN** the tools registry MAY register the approved `scrapling` subset and SHALL record the fallback decision. / **THEN** 工具登錄 MAY 註冊核准的 `scrapling` 子集，並 SHALL 記錄回退決定。

### Requirement: Schema-Constrained Tool Calls
When a request carries `tools`, the gateway SHALL constrain the local engine's output with a grammar derived from the tools' JSON Schemas, so a local answer is either plain text or calls to listed functions with schema-typed parameters and all required fields; if the grammar cannot be built, it SHALL fall back to unconstrained decoding and record why.

#### Scenario: 格式錯誤不再出現 / No malformed calls
- **WHEN** 工具的參數是物件 `{"category": string}`，本機模型要呼叫它
  A tool takes an object parameter and the local model calls it
- **THEN** 輸出的呼叫可被解析，鍵有引號、型別符合 schema
  The call parses, keys are quoted and types match the schema

#### Scenario: 文法建不起來 / Grammar cannot be built
- **WHEN** 工具 schema 用到文法產生器不支援的寫法
  A tool schema uses a construct the grammar builder does not support
- **THEN** 該請求不加約束照常回答，metadata 記下 `tool_grammar: "skipped: <原因>"`
  The request runs unconstrained and the reason is recorded

### Requirement: Tool Call Value Checks
The gateway SHALL check call values against enum, format and minimum/maximum constraints and give the local model one retry with the error message before escalating.

#### Scenario: 列舉值不對 / Value outside the enum
- **WHEN** 呼叫的 `surveyLength` 是「中」，schema 只允許 short/medium/long
  The value is not in the enum
- **THEN** 錯誤訊息回給模型重答一次；重答仍不合法才走轉交流程
  The model retries once with the error; escalation follows only if it still fails

### Requirement: User Wording In Tool Arguments
When a request carries `tools`, the gateway SHALL tell the local model to copy argument values in the user's own wording and to omit optional parameters the user did not give, and SHALL restore argument values that the model converted to Traditional or variant characters back to the matching span of the user or tool messages; `JIEZI_TOOL_NOTE=off` disables both.

#### Scenario: 簡體參數不被轉成繁體 / Simplified values stay Simplified
- **WHEN** 使用者寫「指标包括阅读量、点赞数」，本機模型呼叫時填了 `["閱讀量", "點讚數"]`
  The user wrote Simplified terms and the local model filled in Traditional ones
- **THEN** 回應裡的參數是 `["阅读量", "点赞数"]`
  The returned arguments use the user's Simplified wording

#### Scenario: 對話裡沒有的值不動 / Values without a source are kept
- **WHEN** 參數值（例如 enum 的 `"celsius"`）不在對話裡，也找不到對應的字串
  An argument value has no matching span in the conversation
- **THEN** 參數值照模型的輸出
  The value is left as the model produced it

### Requirement: Holiday Calendar
When a question asks about Taiwan's public holidays, long weekends or make-up days for a year, the system SHALL compute that year's holidays from the articles of the Memorial Days and Holidays Implementation Act in the local law database — dates, weekdays, lunar festivals converted to the solar calendar, and make-up days estimated by the usual rule and marked as subject to the official announcement — and SHALL attach them as computed facts with the statute articles as the source.

#### Scenario: 2027 年的國定假日 / Holidays in 2027
- **WHEN** 使用者問「台灣2027年的國定假日有哪些?」
  The user asks for 2027's public holidays
- **THEN** 本機依附上的計算結果回答（含除夕 2027-02-05 與春節連假），回答後附【計算】與條例第 4、6、8 條，不請教 Claude
  The local model answers from the computed list with the statute as the source, without consulting Claude


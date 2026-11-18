## ADDED Requirements

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

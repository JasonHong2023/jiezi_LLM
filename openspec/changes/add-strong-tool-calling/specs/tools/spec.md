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

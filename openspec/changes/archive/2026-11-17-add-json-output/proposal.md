## Why

Hermes、OpenCode 與使用者自己的腳本常要求模型「只回 JSON」（OpenAI 的 `response_format`）。芥子原本只是把這個欄位原樣丟給本機引擎，回來的內容不檢查、轉交 Claude 時也不會帶格式要求，gateway 還可能在 JSON 後面加上資料來源附錄而把它弄壞。使用者 2026-11-16 指示把尚未規劃的功能都做起來，這是第一項。
Clients ask for JSON via `response_format`. Jiezi used to pass it through unchecked, did not carry it to Claude, and could append a sources appendix that broke the JSON. The user asked for the unplanned features to be built (2026-11-16); this is the first.

## What Changes

- `src/jiezi/runtime/jsonout.py`：解析 `response_format`（`json_object`、`json_schema`、`text`；也接受 llama-server 的 `{"type":"json_object","schema":…}`），寫錯回 400 `invalid_response_format`；從回答抽出 JSON（整段 → 程式碼框 → 第一個完整的物件或陣列）；JSON Schema 常用子集檢查（type、enum、const、required、properties、additionalProperties、items、長度與大小、anyOf／oneOf／allOf）。
  Parsing of `response_format`, JSON extraction, and a validator for a common JSON Schema subset.
- gateway：JSON 模式和工具呼叫走同一套分層——本機回答先檢查，沒過帶著錯誤訊息重試一次，再沒過就轉交（`jiezi` 策略）或回報 `verification: fail`；可平行取樣（鍵排序後比對多數）；串流時先驗證完再送。回傳的 `content` 只留 JSON 本身（去掉程式碼框與說明文字），不加來源附錄（來源仍在 `jiezi.sources`）。簡轉繁與台灣用語只套用在字串值，鍵不動。記憶的文字捷徑（「記住：…」、更正、相同問題）在 JSON 模式不啟用，答案也不存進記憶。
  JSON mode uses the same tiers as tool calls (check, one retry with the error, then escalate), supports sampling, is verified before streaming, returns bare JSON without the appendix, converts string values only, and bypasses the memory text shortcuts.
- 請教 Claude：Claude Code CLI 沒有結構化輸出，改在提示裡附上格式要求與 schema，回來後一樣抽取與檢查。雲端模型原樣帶 `response_format`，回來後抽取與檢查。
  Claude gets the format and schema in the prompt; cloud models get `response_format`; both answers are extracted and checked.
- CLI：`jiezi ask --schema 檔案.json`、`--json-object`；格式沒過時答案照印、結束碼 5。
  `ask --schema` / `--json-object`; exit code 5 when the check fails.

## Non-Goals

- 完整的 JSON Schema（`$ref`、`pattern`、`format`、`if/then` 等不檢查；本機引擎的文法是否支援由 llama.cpp 決定）。/ Full JSON Schema.
- 保證值的正確性：格式對不代表內容對，所以這類回答**不**列為可當教材的強驗證。/ Correct values; schema-valid answers are not treated as strong verification for training.
- chat 與桌面網頁的 JSON 模式（給程式用的功能，從 API 與 `ask` 使用）。/ JSON mode in chat or the desktop page.
- 轉交後仍不合格時再重試（回報 `verification: fail`，由呼叫端決定）。/ Retrying after a failed escalation.

## Capabilities

### New Capabilities

- `json-output`：`response_format` 的結構化輸出。/ Structured output for `response_format`.

### Modified Capabilities

（無）/ (None)

## Impact

- 無新相依、無新設定。沒有 `response_format`（或 `text`）的請求行為不變。
- 本機引擎對 `json_schema` 的文法限制尚未實測（本機模型保留給 E0）；即使引擎不支援或忽略，gateway 的檢查、重試與轉交仍然有效。

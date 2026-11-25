# json-output Specification

## Purpose
要求 JSON 的回答要依 schema 檢查，內容只有 JSON 本身。
JSON answers are schema-checked and contain only the JSON.
## Requirements
### Requirement: Checked JSON Answers

請求帶 `response_format` 為 `json_object` 或 `json_schema` 時，gateway SHALL 解析回答並依 schema 檢查；本機回答未通過時 SHALL 帶著錯誤訊息重試一次，仍未通過時 `jiezi` 策略 SHALL 轉交、其他策略 SHALL 回報 `verification: fail`；串流請求 SHALL 在驗證後才送出內容。寫錯的 `response_format` SHALL 回 400。沒有 `response_format` 或為 `text` 的請求 SHALL 不受影響。
With `response_format` of `json_object` or `json_schema` the gateway SHALL parse and check the answer, retry a failing local answer once with the error, then escalate under `jiezi` or report `verification: fail`; streaming SHALL be verified first; a malformed `response_format` SHALL get HTTP 400; other requests SHALL be unaffected.

#### Scenario: 少了必要欄位 / A missing required property

- **WHEN** schema 要求 `city` 與 `days`，本機第一次只回 `{"city": "台北"}`
  The schema requires `city` and `days` and the first local answer is `{"city": "台北"}`
- **THEN** gateway 告知缺少 `days` 並重試，第二次通過時回傳第二次的答案
  The gateway retries naming the missing `days` and returns the second answer when it passes

#### Scenario: 格式寫錯 / Malformed format

- **WHEN** `response_format` 是 `{"type": "xml"}`
  `response_format` is `{"type": "xml"}`
- **THEN** 回 400，不呼叫任何模型
  HTTP 400 is returned and no model is called

### Requirement: Bare JSON Content

JSON 模式回傳的 `content` SHALL 只包含 JSON 本身：程式碼框與前後說明 SHALL 被移除，資料來源附錄 SHALL NOT 加在內容後面；簡轉繁與用語轉換 SHALL 只套用在字串值，SHALL NOT 改動鍵名；記憶的文字捷徑 SHALL NOT 取代 JSON 回答。Claude 與雲端的回答 SHALL 經同樣的抽取與檢查。
In JSON mode `content` SHALL be bare JSON: fences and prose removed, no sources appendix, script and phrasing conversion on string values only, and no memory text shortcut; Claude and cloud answers SHALL go through the same extraction and check.

#### Scenario: Claude 用程式碼框回答 / Claude answers in a code fence

- **WHEN** 請教 Claude 的回答是 ```` ```json … ``` ````
  Claude's answer is wrapped in a json code fence
- **THEN** 回傳的 `content` 可以直接被 `json.loads` 解析
  The returned `content` parses directly with `json.loads`


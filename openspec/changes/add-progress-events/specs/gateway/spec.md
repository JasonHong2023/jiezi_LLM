## ADDED Requirements

### Requirement: Progress Events In Streams

串流請求時，gateway SHALL 在回答之前以 `object` 為 `jiezi.progress`、`choices` 為空的事件回報目前階段（載入模型、閱讀文件、查資料、生成中、驗證、轉交）；這些事件 MUST NOT 改變 OpenAI 相容的回答 chunk；設定 `JIEZI_PROGRESS=off` 時 SHALL 不送。
For streamed requests the gateway SHALL report the current stage with `jiezi.progress` events that carry no choices before the answer; these events MUST NOT change the OpenAI-compatible answer chunks, and SHALL be omitted when `JIEZI_PROGRESS=off`.

#### Scenario: Model cold start

- **WHEN** a streamed question arrives while the local model is not loaded
- **THEN** a `loading_model` progress event is sent before any answer chunk

#### Scenario: Generic OpenAI client

- **WHEN** an OpenAI-compatible client reads the stream
- **THEN** every answer chunk is unchanged and the progress events have empty `choices`

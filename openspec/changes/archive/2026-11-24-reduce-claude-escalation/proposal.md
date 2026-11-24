> **狀態 / Status**：2026-11-18 使用者決定（「轉給 Claude 的次數這個一定要降低」；Hermes 類「改轉雲端免費模型」；其他誤判「可以，都做」）。實作完成。/ Decided and implemented.

## Why

11-15～11-18 非評測請求 248 個，46 個轉給 Claude：Hermes 等代理程式的大請求放不下 18（39%）、查核沒過 8、本機說不確定 7、
判斷要上網 7、本機被評測保留 4、使用者指定 2。其中不少是誤判，或可以改用免費的雲端模型。
46 of 248 requests went to Claude; the largest share was agent requests the local model cannot hold.

## What Changes

- 轉交原因 `context_too_large`、`engine_unavailable` 在雲端轉交開著時先走雲端模型（LiteLLM），不用 Claude；使用者 `.env`
  開 `JIEZI_CLOUD_ESCALATION=on`、`JIEZI_ESCALATION_MODELS=gemini-2.5-flash,nvidia-nemotron-3-ultra`。
- 本機說「不確定」但問的是芥子自己（memory.SELF）、或是抱怨／回饋（「又出現簡體中文字」），不轉交。
- 代理程式貼成「User: … Assistant: …」的摘要／下標題請求，不判為要上網。
- 狀態頁與 `/admin/escalations`：最近 7 天每天的題數、Claude／雲端次數與原因。
- 同日另修（各自提交）：自我介紹不附知識庫、創作類不撈知識庫與記憶、知識庫門檻 0.6、策略選單拿掉「直接請教 Claude」。

## Capabilities

### Modified Capabilities

- `escalation`：新增 Escalation Routing By Reason 需求。

## Impact

- 這兩類請求的內容會送到雲端服務商（使用者同意）；雲端每日上限沿用 `JIEZI_CLOUD_DAILY_MAX`（200）。

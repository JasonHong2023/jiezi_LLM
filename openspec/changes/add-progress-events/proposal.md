> **狀態 / Status**：2026-11-18 使用者審閱：OQ1 預設開、OQ2 不顯示字數。已實作。/ Approved (on by default, no token counts); implemented.
>
> **實作差異**：`searching`（查知識庫）沒有做——查資料在檢查請求大小（413）之前，若在那裡就開始串流，413 會變成串流裡的錯誤，違反下面「送出前能判斷的錯誤照回 HTTP 錯誤碼」；另加 `retrying`（答案沒過檢查、本機重答）與 `asking_feedback`（第 2 層請教建議）。處理得比第一個階段事件還快時直接回應、不送階段。
> Not done: `searching` (it runs before the 413 check). Added: `retrying`, `asking_feedback`. Answers faster than the first stage skip stages.

## Why

2026-11-18 chat 與桌面版加上「送出後的狀態」，但 gateway 在第一個字之前不送任何東西，所以第一個階段只能**猜**（看有沒有附文件、用哪個策略），等超過 8 秒就統一說「處理中」[實測：無頭 Chromium 看到「思考中 → 處理中 → 回答中」，其中「處理中」其實是在載入模型]。使用者看不出真正卡在哪一步。
The client-side status can only guess the first phase because the gateway is silent until the first token.

## What Changes

- 串流請求（`stream: true`）時，gateway **一收到請求就開始回 SSE**，在真正的回答之前送出進度事件：
  `data: {"object": "jiezi.progress", "choices": [], "jiezi_progress": {"stage": "<階段>", "detail": "…"}}`
  階段：`loading_model`（載入模型）、`reading_documents`（長文件分段、建段落向量）、`searching`（查知識庫／法規）、`thinking`（本機生成中、尚未出字）、`verifying`（驗證答案）、`asking_claude`、`asking_cloud`（轉交）、`agent_step`（沿用現有代理事件）。
- `choices: []`、`object` 不是 `chat.completion.chunk`：一般 OpenAI 用戶端（Hermes、OpenCode）會略過，不影響相容性；只有 jiezi chat 與桌面版認得。可用 `JIEZI_PROGRESS=off` 關閉。
- chat 與桌面版改用 gateway 回報的階段，不再猜；沒有收到進度事件時（舊版 gateway）維持現在的猜測做法。
- 錯誤處理改變：目前串流開始前的錯誤會回 HTTP 4xx/5xx；改成提早開始串流後，之後發生的錯誤只能在串流裡以 `{"error": …}` 回報（現有用戶端已處理這種格式）。**送出前就能判斷的錯誤（授權、格式、413 太大）仍回 HTTP 錯誤碼。**

## Non-Goals

- 顯示模型的思考內容。/ Showing reasoning text.
- 非串流請求。/ Non-streaming requests.

## Capabilities

### Modified Capabilities

- `gateway`：串流回應的進度事件。/ Progress events in streamed responses.

## Impact

- `gateway.py` 的串流路徑要重構成「先開串流、再做濃縮／取得引擎／轉交」，是這次最大的風險；要有回歸測試確認 Hermes／OpenCode 的串流不受影響。
- 不影響本機效能（只多幾個小事件）。

## Open Questions

- **OQ1 要不要預設開**：建議預設開（只有 jiezi 自己的用戶端會顯示，其他用戶端會略過）。
- **OQ2 `thinking` 階段要不要顯示已等待的 token 數**（例如「思考中… 已產生 120 字」）：建議不顯示，避免看起來像卡住。

> **狀態 / Status**：2026-11-18 使用者審閱：OQ1 **預設開**；OQ2 **文件也一起做**；OQ3 Hermes 等外部 agent **照樣讀**。/ Approved: default on, documents too, external agents too.

## Why

2026-11-18 使用者問 Claude 怎麼看圖：Claude 用 Read 工具讀圖片檔 → 編成 base64 → 圖片和文字一起送進同一個多模態模型直接看。使用者要求**把這個方法教給芥子，也加入 base64**。
The user asked how Claude looks at images (read the file, base64, one multimodal model sees it directly) and wants Jiezi to do the same.

現況：
- `jiezi chat` 已經會：問題裡打圖片路徑（含 Windows 的 `D:\…`）就讀檔、轉成 `data:image/...;base64,...` 附上（`_auto_attach`）。
- **gateway 不會**：桌面版直接打路徑、Hermes／OpenCode／LiteLLM 等用戶端送來的路徑，gateway 只加 `PATH_NOTE` 叫模型說「看不到，請附檔」。
- 芥子的看圖本身原理和 Claude 相同（mmproj 把圖轉成視覺 token 與文字一起處理），缺的是「自己去讀檔」這一步。
Jiezi chat already turns typed image paths into base64; the gateway does not, so other clients only get "I can't see it".

## What Changes

- 文件路徑（PDF、Word、PowerPoint、Excel、純文字等，同 `/file` 支援的格式）：在受限子行程讀成文字，用 `/file` 相同的【文件：…】標記包進問題（之後照長文件、段落召回、injection-guard 處理）；文件合計 ≤ 150 萬字（同 jiezi chat）。（OQ2）
- gateway 在**最後一則使用者訊息**找本機檔案路徑；路徑指向圖片檔時：
  1. 讀檔並檢查：一般檔案、副檔名與檔頭（magic bytes）都是 PNG／JPEG／WebP／GIF、≤ 5 MB（同 `/image`）；
  2. 編成 base64 data URL，以 OpenAI 格式 `image_url` 附在同一則訊息；一題最多 3 張；
  3. 之後照現有看圖流程（vision tools 開著就先跑工具、回答後核對）；
  4. metadata 記 `image_paths: [{path, bytes, ok|why}]`；讀不到或不合格的照舊加 `PATH_NOTE`。
- 只讀**使用者自己打的**路徑：system、assistant、tool 訊息與附件文件裡的路徑一律不讀（防止網頁或工具結果誘導讀取本機檔案，沿用 injection-guard 的精神）。
- `jiezi chat` 已在用戶端附好圖，不受影響；桌面版直接受惠，不用改前端。
- 開關 `JIEZI_IMAGE_PATHS`（預設 on，見 OQ1）。

## Non-Goals

- 用 Claude 的回答訓練芥子（Claude 答案不當訓練資料的規則不變）。
- 截取使用者桌面畫面。

## Capabilities

### Modified Capabilities

- `gateway`：新增 Image Paths 需求。

## Impact

- 只在本機讀檔；圖片只送本機引擎。策略是 jiezi-cloud／jiezi-ask-claude 時才可能隨請求送出（和直接附圖相同）。
- 程式：`src/jiezi/runtime/gateway.py`（取代 `_path_note` 的圖片分支）、`src/jiezi/localpaths.py`（共用 CLI 的判斷）、`settings.py`、`.env.example`、測試。
- 不下載任何東西，白天可做。

## Open Questions

- **OQ1 預設開還是關**：建議**開**。這是補功能不是改答案品質，且只讀使用者自己打的圖片路徑；R20 的量測門檻針對答案品質，這裡用單元測試把關。
- **OQ2 其他檔案類型**：建議這次只做圖片；文件（PDF、Word…）路徑要不要也由 gateway 自動讀，之後另提。
- **OQ3 Hermes 等外部 agent**：它們的「使用者訊息」可能夾帶 agent 自己組的文字。建議照樣讀（仍只限圖片、5 MB），metadata 留紀錄；若你希望只限 jiezi 自己的用戶端，改成依金鑰或標頭判斷。

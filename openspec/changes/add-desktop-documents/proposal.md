## Why

桌面網頁（Phase 8 雛形）只能打字，不能附文件；長文件摘要與追問（add-long-documents、add-document-followup）只有 `jiezi chat`／`ask` 用得到。前端是純瀏覽器程式，自己讀不了 PDF／Word（讀檔在 Python 的受限子行程裡）。使用者 2026-11-16 指示把尚未規劃的功能做起來。
The desktop page could not attach documents; reading PDF/Word lives in the Python child process, which a browser front end cannot reach.

## What Changes

- gateway `POST /v1/documents?name=檔名`（需金鑰；內容是檔案的原始位元組）：存到 `var/runtime/uploads` 的暫存目錄 → 用既有的受限子行程讀成文字 → 清理零寬字元與偽造的文件標記 → 回傳 `name`、`kind`、`chars`、`pages`、`ocr_pages`、`warnings`、`text`；暫存檔讀完（或失敗）就刪。上限 50 MB、一次只讀一份；檔名只取最後一段（不接受路徑）。錯誤：400（格式不支援、沒有檔名、空檔）、413（太大）、422（讀不出來）。
  An authenticated upload endpoint that reads one file in the existing limited child process, returns its cleaned text and deletes the upload.
- 桌面網頁：「附加文件」按鈕（可多選）；附著的文件以標籤顯示、可個別移除；每一題送出時把文件包進最新的問題（和 `jiezi chat` 相同的標記），畫面與歷史只留問題；「清除對話」一併清除；合計上限 150 萬字。防提示注入的警告（add-injection-guard）顯示在回答下方。
  An attach button; attached documents ride with every question as in `jiezi chat`.

## Non-Goals

- 拖放、貼上圖片、圖片附件（視覺要等 G1 選定核心）。/ Drag and drop, images.
- 在 gateway 保存上傳的檔案或文字（文字只在瀏覽器分頁的記憶體，關掉就沒了）。/ Keeping uploads on the gateway.
- 上傳進度條。/ An upload progress bar.

## Capabilities

### New Capabilities

- `desktop-documents`：桌面網頁的文件上傳與附著。/ Document upload and attachment for the desktop page.

### Modified Capabilities

（無）/ (None)

## Impact

- 新端點只綁 127.0.0.1、需要金鑰；跨來源只允許 Tauri 外殼（沿用既有 CORS）。
- 無新相依。前端需重建（`scripts/jiezi ui build`）。

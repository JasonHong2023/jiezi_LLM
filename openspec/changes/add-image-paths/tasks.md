## 1. 實作 / Implementation

- [x] 1.1 `localpaths`：圖片判斷加檔頭檢查與大小上限（`sniff_image`、`image_data_url`）
- [x] 1.2 gateway `_read_paths`：最後一則使用者訊息的圖片路徑轉 base64 附上、文件路徑讀成文字包進問題（OQ2）；不合格的照舊 `PATH_NOTE`；metadata `image_paths`；`JIEZI_IMAGE_PATHS` 預設 on
- [x] 1.3 只讀使用者訊息：system／assistant／tool／附件文件裡的路徑不讀（測試）
- [x] 1.4（`tests/test_localpaths.py` 5 個；全套 591 OK）測試：找不到、過大、副檔名是 .png 但內容不是圖、文件、超過 3 個、開關 off

## 2. 驗證 / Verify

- [ ] 2.1 桌面版與 Hermes 實際打路徑問圖（用 2026-11-18 動物拼貼）
- [ ] 2.2 回報使用者、更新 HANDOFF

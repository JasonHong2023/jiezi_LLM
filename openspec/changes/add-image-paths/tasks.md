## 1. 實作 / Implementation

- [ ] 1.1 `localpaths`：圖片判斷加檔頭檢查與大小上限，CLI 與 gateway 共用
- [ ] 1.2 gateway：最後一則使用者訊息的圖片路徑讀檔轉 base64 附上；不合格的照舊 `PATH_NOTE`；metadata `image_paths`；`JIEZI_IMAGE_PATHS`
- [ ] 1.3 只讀使用者訊息：system／assistant／tool／附件文件裡的路徑不讀（測試）
- [ ] 1.4 測試：Windows 路徑、找不到、過大、副檔名是 .png 但內容不是圖、超過 3 張、開關 off

## 2. 驗證 / Verify

- [ ] 2.1 桌面版與 Hermes 實際打路徑問圖（用 2026-11-18 動物拼貼）
- [ ] 2.2 回報使用者、更新 HANDOFF

## 1. Gateway

- [x] 1.1 串流請求提早開始 SSE，依階段送 `jiezi.progress` 事件；`JIEZI_PROGRESS=off` 關閉；送出前可判斷的錯誤仍回 HTTP 錯誤碼
- [x] 1.2（既有串流測試全數通過＋新測試：冷啟動 loading_model→thinking、一般 chunk 不變、503 照舊、非串流沒有、JIEZI_PROGRESS=off） 回歸測試：OpenAI 相容用戶端看到的 chunk 不變（除了可略過的進度事件）、中斷、錯誤、轉交

## 2. 用戶端 / Clients

- [x] 2.1 chat 與桌面版改用回報的階段；收不到時沿用現在的推測
- [ ] 2.2（2026-11-18 冷啟動實測：0.1 秒 loading_model → 6.2 秒 thinking → 7.3 秒第一個字；附文件、轉交、代理待使用者在 chat 看）實測：附文件、轉交 Claude、代理、模型冷啟動四種情境的階段順序

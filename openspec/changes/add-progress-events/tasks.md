## 1. Gateway

- [ ] 1.1 串流請求提早開始 SSE，依階段送 `jiezi.progress` 事件；`JIEZI_PROGRESS=off` 關閉；送出前可判斷的錯誤仍回 HTTP 錯誤碼
- [ ] 1.2 回歸測試：OpenAI 相容用戶端看到的 chunk 不變（除了可略過的進度事件）、中斷、錯誤、轉交

## 2. 用戶端 / Clients

- [ ] 2.1 chat 與桌面版改用回報的階段；收不到時沿用現在的推測
- [ ] 2.2 實測：附文件、轉交 Claude、代理、模型冷啟動四種情境的階段順序

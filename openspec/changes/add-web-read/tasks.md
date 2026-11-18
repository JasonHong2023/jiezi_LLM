## 1. 實作 / Implementation

- [x] 1.1（`src/jiezi/webread.py`；IP 直接寫的網址直接檢查；伺服器不管 Accept-Encoding 都回 brotli 時換查詢參數重抓，最多 3 次——加 brotli 套件被權限擋下） `webread.fetch`：只 http(s)、拒絕內網（含轉址後）、大小與逾時上限、HTML→文字
- [x] 1.2 gateway：使用者訊息的網址讀取後以文件附上；讀到就不判 needs_web；metadata `web_read`
- [x] 1.3（背景請本機整理 5–12 點重點，存記憶 topics/ 並寫 var/memory/web_memo.json 索引；問題提到網站名稱〔網域、標題英文詞〕就附上；讀不懂的不存）「記住」＋網址：本機摘要存記憶
- [x] 1.4（tests/test_webread.py 5 個；全套 626 OK） 測試（假伺服器、內網拒絕、轉址到內網、過大、逾時）

## 2. 驗證 / Verify

- [ ] 2.1（實測 docs.ubuntu.com：讀取並記住 27.7 秒本機；追問「Ubuntu 官方文件網站有哪些產品」20.5 秒本機、用記憶）使用者確認

## 1. 實作 / Implementation

- [x] 1.1 `src/jiezi/tools.py`：計算、單位、日期、誤判防護 / Tools module
- [x] 1.2 gateway 附結果、`/health`、`JIEZI_TOOLS` / Gateway wiring

## 2. 驗證 / Verification

- [x] 2.1 單元測試（含模型算錯被查核抓到）；`openspec validate add-tools --strict`
- [x] 2.2 重啟 gateway 後確認 `/health` 的 tools 為 on（E0 執行中，本機模型暫停，實際問答待 E0 結束）

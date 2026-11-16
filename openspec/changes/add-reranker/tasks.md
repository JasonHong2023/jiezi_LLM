> 尚未開始；等使用者同意，且排在 G1 之後。/ Not started; after G1 and the user's go-ahead.

- [ ] 1.1 模型登記（授權讀官方檔、SHA-256、鎖定 commit）；`engine-rerank`（埠 36106、延遲啟動、預算擺放）；R11 表與 R12 流程圖 / model registry, engine, port table and flow chart
- [ ] 1.2 檢索流程接入（前 N → 重排序 → 前 k、失敗退回）、`JIEZI_RERANK`、啟動自我檢查、`doctor` / retrieval wiring, switch, self-check
- [ ] 1.3 單元測試（假引擎）；文件；`openspec validate add-reranker --strict` / tests and docs
- [ ] 2.1 量測（與實作分開，R8、R17）：有無重排序的命中率@k 與延遲，GPU 與 CPU 各一組；依 OQ1 門檻決定預設值，結果記入報表 / A/B measurement deciding the default

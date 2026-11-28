## 1. 審閱 / Review

- [x] 1.1（2026-11-28 使用者「1 可以 2 預設先不查 3 好」）使用者審閱提案，決定排除資料夾、超大頁面、轉交時拿掉段落

## 2. 實作 / Implementation

- [x] 2.1 `src/jiezi/wiki_recall.py`：唯讀索引（排除清單、200 KB 上限、private、疑似金鑰、符號連結、簡轉繁、增量）與檢索門檻
- [x] 2.2 gateway 附加資料、不可訓練（private）、轉交雲端／Claude／老師前拿掉、第 2 層不送；設定 `JIEZI_WIKI_RECALL`（預設關）
- [x] 2.3 `scripts/jiezi wiki index|search`、doctor、`/health`
- [x] 2.4 單元測試；全量測試與 openspec 驗證

## 3. 試用與預設 / Try and default

- [ ] 3.1 使用者看 `var/wiki-recall/report.md` 確認疑似金鑰的段落與沒收的大頁面
- [ ] 3.2 實測 5 題（3 題 wiki 有答案、2 題不相干），使用者決定要不要預設開啟
- [x] 3.3（2026-11-28）更新 `docs/clients.md`

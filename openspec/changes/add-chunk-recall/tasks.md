> 2026-11-18 使用者審閱：A、B 都做，量完再定預設；OQ2 保留 2 名、OQ3 8 秒。/ Reviewed: build both, measure, then choose.

- [x] 1.1 `longdoc.select` 支援保留語意前 N 名（做法 A）；HyDE 查詢（做法 B，逾時退回）；`JIEZI_DOC_RECALL` / reserve and HyDE modes, switch
- [x] 1.2 單元測試（保留名額、HyDE 逾時與失敗退回、關閉時行為不變）；`docs/clients.md`、`.env.example`；`openspec validate add-chunk-recall --strict`
- [ ] 2.1 量測：舊 16 題＋新寫 16 題，off／reserve／hyde 的答對數與每題耗時；依結果決定預設值，記入討論記錄

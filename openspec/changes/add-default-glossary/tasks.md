## 1. 詞表 / Glossary data

- [ ] 1.1 整理總統府、五院、行政院所屬部會現行名稱約 40 筆，逐筆以機關英文官網查核，TSV 每列附來源網址
- [ ] 1.2 與資料集 32084 交叉比對，不一致處記入討論記錄；`docs/licenses.md` 標示來源

## 2. 實作 / Implementation

- [ ] 2.1 中翻英自動合併內建詞表（使用者詞表優先、只取原文出現的詞），資訊欄列出套用的詞
- [ ] 2.2 CLI `--no-default-glossary`、HTTP `jiezi_glossary_default: false`
- [ ] 2.3 單元測試；全量測試與 openspec 驗證

## 3. 實測 / Live test

- [ ] 3.1 著作權法第 1–14 條重翻，「經濟部」譯為 Ministry of Economic Affairs；結果記入討論記錄

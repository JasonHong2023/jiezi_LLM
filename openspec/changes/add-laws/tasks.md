## 1. 實作 / Implementation

- [x] 1.1 清單、授權登記 `moj-laws`（訓練：是）/ Manifest and registry
- [x] 1.2 `src/jiezi/laws.py`：建置、條號解析（中文數字、之 N）、簡稱、全文檢索、引用 / Module
- [x] 1.3 gateway、`/health`、`JIEZI_LAWS`、`scripts/jiezi laws build|lookup` / Wiring

## 2. 驗證 / Verification

- [x] 2.1 單元測試；`openspec validate add-laws --strict`
- [x] 2.2 實際建置與查詢：民法第184條、勞基法第三十二條、刑法第185條之3、個資法同意問題正確；「民法第9999條」回報不存在；閒聊不觸發。已知限制：「酒駕會怎麼處罰」用語與條文不同查不到（待向量檢索）

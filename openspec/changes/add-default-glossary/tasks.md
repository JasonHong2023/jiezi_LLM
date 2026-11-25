## 1. 詞表 / Glossary data

- [x] 1.1 整理總統府、五院、行政院所屬部會現行名稱約 40 筆，逐筆以機關英文官網查核，TSV 每列附來源網址（2026-11-25：34 個行政院所屬機關依行政院英文網站「Ministries and Agencies」頁、總統府與五院依各自英文網站；連同簡稱共 54 筆）
- [x] 1.2 與資料集 32084 交叉比對，不一致處記入討論記錄；`docs/licenses.md` 標示來源（不一致：農委會／環保署等改組前名稱、退輔會 Veterans Affairs Commission → Council、錯字；登記鍵 `tw-agency-names`）

## 2. 實作 / Implementation

- [x] 2.1 中翻英自動合併內建詞表（使用者詞表優先、只取原文出現的詞），資訊欄列出套用的詞
- [x] 2.2 CLI `--no-default-glossary`、HTTP `jiezi_glossary_default: false`
- [x] 2.3 單元測試；全量測試與 openspec 驗證

## 3. 實測 / Live test

- [x] 3.1 著作權法第 1–14 條重翻，「經濟部」譯為 Ministry of Economic Affairs；結果記入討論記錄（2026-11-25 直連引擎 2 次：套用 立法院、經濟部，兩處都譯為 Ministry of Economic Affairs，0 失敗 0 重試，18–20 秒；經 gateway 的確認待重啟後）

## 1. 答案查核 / Grounded check

- [x] 1.1 `escalation.verify_grounded`（數字、中文數字換算、引用、略過附錄與清單編號）/ Checker
- [x] 1.2 gateway：記錄附上的資料，非串流重答、串流提醒並請教 / Gateway wiring

## 2. 台灣用語 / Taiwan phrasing

- [x] 2.1 `TWPhrases-jiezi.txt`（`generate_tw_table`）、`to_taiwan`、`TaiwanStream` / Table and converters
- [x] 2.2 gateway 本機輸出（串流與非串流）、`JIEZI_TW_PHRASES` / Gateway and setting

## 3. 驗證 / Verification

- [x] 3.1 單元測試（查核、重答、串流提醒、台灣用語、串流隨機切段）；`openspec validate add-answer-check --strict`
- [x] 3.2 0.6B 實測 8 題（見 design 風險段）/ Live check with the 0.6B

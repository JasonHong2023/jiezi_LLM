## 1. 格式保證 / Guaranteed format

- [ ] 1.1 由工具 JSON Schema 產生 llama.cpp 文法（名稱、參數、型別、必填），請求帶 tools 時對本機引擎啟用；文法產生失敗就退回不約束
- [ ] 1.2 值檢查（enum、format、minimum/maximum）與一次重答；仍失敗走現有 tier
- [ ] 1.3 取樣多數決只讓通過檢查的樣本投票

## 2. 量測 / Measure

- [ ] 2.1 ACEBench-zh 完整 normal 題組；BFCL simple/multiple/parallel/irrelevance 子集（授權查證後）
- [ ] 2.2 夜間：1.1–1.3 前後對比，回報給使用者

## 3. 訓練 / Training（第 2 輪結果之後）

- [ ] 3.1 查證並下載授權允許的工具呼叫資料集，登記 `docs/licenses.md`
- [ ] 3.2 第 3 輪 SFT（工具呼叫＋複習資料），R20 回歸門檻，過了交使用者決定換核心

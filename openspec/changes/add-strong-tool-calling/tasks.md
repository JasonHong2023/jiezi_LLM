## 1. 格式保證 / Guaranteed format

- [x] 1.1（實作前查證：llama.cpp `common/chat-auto-parser-generator.cpp` 已依工具 schema 建 lazy grammar，原生 tools 路徑本來就受約束；11-17 gateway 量測 50 題只有 1 題解析不了，E0 的 9 題是文字格式 `[f(a=1)]` 評測，不是用戶端走的路徑）由工具 JSON Schema 產生 llama.cpp 文法（名稱、參數、型別、必填），請求帶 tools 時對本機引擎啟用；文法產生失敗就退回不約束
- [x] 1.2（帶錯誤訊息重答本來就有：`escalation.retry_messages`；新增巢狀物件、陣列項目、範圍、長度的檢查，沿用 jsonout.validate；toolcheck 43/50 不變，剩下的錯都通過 schema，是語意錯）值檢查（enum、format、minimum/maximum）與一次重答；仍失敗走現有 tier
- [x] 1.3（已存在：add-sampling 的 `_sampled` 就是「通過驗證的多數決」）取樣多數決只讓通過檢查的樣本投票
- [x] 1.4（11-18 新增，依 17 題錯誤分析）帶工具的請求加參數填寫規則 `TOOL_NOTE`，並把被轉成繁體／異體的參數值還原成使用者原文（`runtime/toolargs.py`）；`JIEZI_TOOL_NOTE`。toolcheck（jiezi-local，ACEBench-zh 50 題）32 → 42（只有規則）→ 44／43（加還原）

## 2. 量測 / Measure

- [ ] 2.1 ACEBench-zh 完整 normal 題組；BFCL simple/multiple/parallel/irrelevance 子集（授權查證後）
- [ ] 2.2 夜間：1.1–1.3 前後對比，回報給使用者

## 3. 訓練 / Training（第 2 輪結果之後）

- [ ] 3.1 查證並下載授權允許的工具呼叫資料集，登記 `docs/licenses.md`
- [ ] 3.2 第 3 輪 SFT（工具呼叫＋複習資料），R20 回歸門檻，過了交使用者決定換核心

## 1. 格式保證 / Guaranteed format

- [x] 1.1（實作前查證：llama.cpp `common/chat-auto-parser-generator.cpp` 已依工具 schema 建 lazy grammar，原生 tools 路徑本來就受約束；11-17 gateway 量測 50 題只有 1 題解析不了，E0 的 9 題是文字格式 `[f(a=1)]` 評測，不是用戶端走的路徑）由工具 JSON Schema 產生 llama.cpp 文法（名稱、參數、型別、必填），請求帶 tools 時對本機引擎啟用；文法產生失敗就退回不約束
- [x] 1.2（帶錯誤訊息重答本來就有：`escalation.retry_messages`；新增巢狀物件、陣列項目、範圍、長度的檢查，沿用 jsonout.validate；toolcheck 43/50 不變，剩下的錯都通過 schema，是語意錯）值檢查（enum、format、minimum/maximum）與一次重答；仍失敗走現有 tier
- [x] 1.3（已存在：add-sampling 的 `_sampled` 就是「通過驗證的多數決」）取樣多數決只讓通過檢查的樣本投票
- [x] 1.4（11-18 新增，依 17 題錯誤分析）帶工具的請求加參數填寫規則 `TOOL_NOTE`，並把被轉成繁體／異體的參數值還原成使用者原文（`runtime/toolargs.py`）；`JIEZI_TOOL_NOTE`。toolcheck（jiezi-local，ACEBench-zh 50 題）32 → 42（只有規則）→ 44／43（加還原）

## 2. 量測 / Measure

- [x] 2.1 ACEBench-zh 完整 normal 題組；BFCL simple/multiple/parallel/irrelevance 子集（授權查證後；2026-11-20 `jiezi-local`／`toolcheck --suite all` 實測 1306/1540=84.8%：ACEBench 387/500=77.4%，BFCL 919/1040=88.4%；報告 `var/reports/toolcheck-all-20261120-1802-jiezi-local.md`）
- [x] 2.2（2026-11-20 21:47 回填，使用既有 11-17／11-18 50 題報告與 11-20 夜間 E0 取樣報告；非受控 A/B：1.1 是文字格式評測 vs 原生 tools 路徑、1.2 是相鄰版本連跑、1.3 是同次 N=8 取樣的 pass@1 vs 多數決；詳見 `2026-11-20.md` #10）夜間：1.1–1.3 前後對比，回報給使用者

## 3. 訓練 / Training（第 2 輪結果之後）

- [x] 3.1（2026-11-23 主控：ToolACE、hermes-function-calling-v1 鎖定 revision 下載到 var/datasets/toolcall/，登記 docs/licenses.md〔⚠️ 先下載後登記，違反 R18.3，已註明〕；`src/jiezi/toolcall_data.py` 轉成訓練範例：只取第一個呼叫回合、須過 `verify_tools`、含中日韓文字不收；共 10,833 筆〔toolace 8,753、hermes-fc 2,080〕。`eval_targets` 補上 toolcheck 的 ACEBench／BFCL 1,540 題〔原本漏掉〕，外部資料再加正規化前 48 字比對，重疊 0。xLAM 需 HF 登入，未下載。⚠️ 兩資料集的生成模型未載明，是否用於第 3 輪 SFT 交使用者決定）查證並下載授權允許的工具呼叫資料集，登記 `docs/licenses.md`
- [ ] 3.2（2026-11-23 主控已備妥、未執行：`configs/qwen3.5-4b-r3.json`；夜間腳本只有 `var/train/r3-approved` 存在才跑第 3 輪，內容含 `datasets` 才收外部資料集；SFT 編碼已修正為帶工具定義〔d76cb31〕；⚠️ max_len 768 只留約 37% 的帶工具範例。等使用者決定）第 3 輪 SFT（工具呼叫＋複習資料），R20 回歸門檻，過了交使用者決定換核心

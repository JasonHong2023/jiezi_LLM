## 1. 實作 / Implementation

- [x] 1.1 `LocalEngine(parallel=N)`（`-np N -kvu`，預設 1）；gateway 引擎依 `JIEZI_SAMPLES` 開槽位 / Engine slots
- [x] 1.2 gateway：取樣種類判斷、平行取樣、驗證、多數決、信心度、軌跡 / Gateway sampling
- [x] 1.3 `escalation.CODE_REQUEST`、`answer_key` / Helpers

## 2. 驗證 / Verification

- [x] 2.1 單元測試（多數決與信心度、閒聊不取樣、程式題取樣）；`openspec validate add-sampling --strict`
- [x] 2.2（2026-11-17，核心 qwen3.5-4b-q4_k_m、4 槽位：顯示記憶體 5,111 MiB／6,141 MiB；工具題 4 個樣本一致 3.3 秒、程式題 12.7 秒；自我評測 84/90、工具評測 33/50 都是開著取樣量的。**沒有同一核心關閉取樣的對照組**，「前後比較」未做，留給 E0 夜間取樣設定（5.5）的結果） E0 結束後實測：VRAM 用量、可驗證問題的延遲、自我評測前後比較 / Live check after E0

## 1. 實作 / Implementation

- [x] 1.1 `LocalEngine(parallel=N)`（`-np N -kvu`，預設 1）；gateway 引擎依 `JIEZI_SAMPLES` 開槽位 / Engine slots
- [x] 1.2 gateway：取樣種類判斷、平行取樣、驗證、多數決、信心度、軌跡 / Gateway sampling
- [x] 1.3 `escalation.CODE_REQUEST`、`answer_key` / Helpers

## 2. 驗證 / Verification

- [x] 2.1 單元測試（多數決與信心度、閒聊不取樣、程式題取樣）；`openspec validate add-sampling --strict`
- [ ] 2.2 E0 結束後實測：VRAM 用量、可驗證問題的延遲、自我評測前後比較 / Live check after E0

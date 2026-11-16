## Why

開發計畫 Phase 4.1「平行取樣 + 驗證器評分 + 一致率信心」（關卡 G2）。0.6B 單次回答的工具呼叫常缺參數或亂填；一次取多個、只留通過驗證且最多數一致的，能在不換模型的情況下提高正確率，並得到信心度供轉交與路由使用。
Phase 4.1: sample several answers, keep the verified majority, and report agreement as confidence.

## What Changes

- 工具呼叫與要求寫程式的問題，同時取 `JIEZI_SAMPLES` 個答案（預設 4，溫度 0.7，固定種子 1000+i），逐一驗證（schema／語法／答案查核），從通過的答案中挑最多數一致的一組；`jiezi.confidence` = 該組數量 ÷ N。都沒通過時沿用原本的重答與轉交流程。
  Tool-call and code questions get N concurrent samples; the verified majority wins; confidence is its share.
- 本機引擎開 N 個槽位、共用 KV 快取（`-np N -kvu`，上下文 8192）；`LocalEngine` 的槽位數預設仍為 1，E0 與評測不受影響。
  The chat engine runs N slots with a unified KV cache; evaluation engines keep one slot.
- 這類問題在串流請求時改走驗證流程，答完一次送出。/ Such streaming requests are answered whole.
- 軌跡記錄每個樣本的驗證結果與比對鍵。/ Trajectories record every sample's verification.

## Non-Goals

- 閒聊、知識題取樣（沒有可驗證的標準）。/ Sampling unverifiable questions.
- 執行使用者題目的程式碼測試（沒有測試資料；程式只做語法檢查）。/ Running code without tests.

## Capabilities

### New Capabilities

- `sampling`：可驗證問題的平行取樣與信心度。/ Parallel sampling with confidence.

### Modified Capabilities

（無）/ (None)

## Impact

- 0.6B 的 KV 快取約多 0.9 GB VRAM（在預算內）；可驗證問題的延遲約為單次的 1–2 倍（槽位平行）。

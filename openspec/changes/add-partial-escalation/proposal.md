> **狀態 / Status**：使用者 2026-11-17 審閱並同意。
> Proposal only, **not implemented**; awaiting the user's go-ahead.

## Why

開發計畫 §4.2 是四層轉交，add-gateway 的 v0 只做了三層：第 0 層本機 → 第 1 層依驗證錯誤本機重試 → 第 3 層整題轉交。缺的是**第 2 層「只請強模型給回饋，答案仍由本機產生」**。依據是 Self-Refine 的混合修正實驗：弱模型起草加強模型的回饋，數學從 24.18% 提升到 40.5% [原文，見 `docs/analysis/self-evolution-papers.md` §2]。
The dev plan has four tiers; v0 built three. Missing is tier 2: the stronger model only gives feedback and the local model still writes the answer.

好處：(1) 用付費雲端時，回饋比整題回答短，花費較少；(2) 這類題目留下「本機差一點就答對」的紀錄，是之後路由器與訓練題目的來源。壞處：多一次來回，最後仍失敗時比直接第 3 層更慢。所以值不值得要量。
Benefits: cheaper than a full answer on paid clouds, and it records near-misses. Cost: one more round trip, slower when it still fails. Hence it must be measured.

## What Changes

- 只用在**有驗證器錯誤訊息**的請求：工具呼叫（schema）、JSON 輸出、程式（語法）、短文字翻譯、有附資料的答案查核。閉卷知識題不適用（R6.9）。
  Only for requests with a verifier error: tool calls, JSON output, code syntax, short translations, grounded answers.
- 流程：第 1 層重試後仍未通過 → 把「問題、本機最後的答案、驗證錯誤」交給協助者（依既有順序：Claude → 雲端），**只要求指出錯在哪裡與怎麼改，不要給完整答案**（回饋上限 300 token）→ 本機帶著回饋再答一次 → 通過就以第 2 層回覆；沒通過才走第 3 層。協助者的回饋裡如果直接夾了完整答案，仍只當回饋用。
  After tier 1 fails, the helper sees the question, the last local answer and the error, and is asked only what is wrong and how to fix it (capped at 300 tokens); the local model answers once more; pass → tier 2, otherwise tier 3.
- 回應的 `jiezi.tier` 為 2，並記錄協助者與回饋的 token 數；軌跡保存回饋內容。
- **訓練資料**：第 2 層的答案受協助者影響。協助者是 Claude 時整筆 `training_use=false`（Claude 的內容不當訓練資料）；協助者是其他雲端模型時也先標 false，待 R18.4 逐一確認服務條款後再議。
  Tier-2 answers are shaped by the helper: never trainable with Claude, and not trainable with other clouds until their terms are checked.
- `JIEZI_TIER2`（預設 **off**，量測後再決定，見 OQ1）；每日次數併入既有的請教／雲端上限。
- 串流請求：有驗證的請求原本就是先驗證再送出，第 2 層不改變這一點。

## Non-Goals

- 把第 2 層用在沒有驗證器的自由問答（沒有錯誤訊息可給，也無法判斷重答有沒有變好）。/ Free-form answers without a verifier.
- 多輪回饋（只做一輪）。/ More than one feedback round.
- 用第 2 層的資料訓練模型或路由器（另案，且受上面的訓練限制）。/ Training on tier-2 data.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `escalation`：在第 1 層與第 3 層之間加入第 2 層（規格 `Tiered Escalation v0` 的補充；同步 R12 流程圖——圖上本來就畫了第 2 層）。/ A second tier between tiers 1 and 3.

## Impact

- 無新相依。失敗路徑多一次協助者呼叫與一次本機生成 **[估：Claude 約 5–25 秒 [實測 11-15 的請教耗時]，本機 1–3 秒]**。
- **[推論]** 目前協助者主要是本機的 Claude Code CLI（不另外計費），「省雲端費用」這項好處暫時不明顯；主要價值在留下近失誤紀錄與提高「本機處理率」。這也是建議預設關閉、先量測的原因。

## 已決事項（原 Open Questions）/ Resolved

- **OQ1**：預設關閉，量測後再決定（使用者 2026-11-17 同意）。/ Off by default until measured.
- **OQ2**：進到第 2 層的請求中 ≥ 40% 通過才預設開啟（同意）。/ Default on only at a ≥ 40% tier-2 pass rate.

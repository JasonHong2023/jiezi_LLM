> 尚未開始；等使用者回覆 Open Questions 並同意實作（R4）。/ Not started.

- [ ] 1.1 `escalation.py`：回饋請求的提示（只要指出錯誤與改法、上限 300 token）與帶回饋重答的訊息組裝 / feedback prompt and retry messages
- [ ] 1.2 gateway：第 1 層失敗後的第 2 層（協助者順序、每日上限、`jiezi.tier=2`、軌跡、`training_use=false`、`JIEZI_TIER2`）；R12 流程圖確認 / gateway tier 2
- [ ] 1.3 單元測試（假協助者：回饋後通過、仍失敗轉第 3 層、協助者失敗、關閉時不變）；文件；`openspec validate add-partial-escalation --strict` / tests and docs
- [ ] 2.1 量測（與實作分開）：G1 選定核心後，以 toolcheck 50 題與 JSON 題量第 2 層的進入數、通過率與多花的時間；依 OQ2 決定預設值 / measurement deciding the default

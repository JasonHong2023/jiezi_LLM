## ADDED Requirements

### Requirement: Feedback-Only Tier

第 2 層啟用時，帶有驗證器錯誤的請求在本機重試仍未通過後，gateway SHALL 只向協助者要求回饋（錯在哪裡、如何修正），再由本機模型帶著回饋重答一次；通過驗證時 SHALL 以第 2 層回覆，未通過時 SHALL 繼續第 3 層。沒有驗證器錯誤的請求 SHALL NOT 進入第 2 層。受協助者回饋影響的答案 SHALL 標為不可用於訓練。第 2 層關閉時行為 SHALL 與原本相同。
With tier 2 on, a request with a verifier error that still fails after the local retry SHALL get feedback only from the helper and one more local attempt; passing SHALL answer at tier 2, failing SHALL continue to tier 3. Requests without a verifier error SHALL NOT enter tier 2. Answers shaped by helper feedback SHALL be marked non-trainable. With tier 2 off behaviour SHALL be unchanged.

#### Scenario: 回饋後通過 / Passing after feedback

- **WHEN** 工具呼叫兩次都缺必要參數，協助者指出缺 `city`，本機第三次補上
  A tool call misses a required argument twice, the helper names the missing `city`, and the third local attempt includes it
- **THEN** 回應的 `jiezi.tier` 是 2，答案由本機產生
  The response reports tier 2 and the answer comes from the local model

#### Scenario: 回饋後仍失敗 / Still failing

- **WHEN** 本機帶著回饋重答仍未通過驗證
  The local attempt with feedback still fails verification
- **THEN** 照原本的方式進入第 3 層
  The request proceeds to tier 3 as before

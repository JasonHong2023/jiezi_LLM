## ADDED Requirements

### Requirement: Licensed Dictionary Sources

辭典來源 SHALL 列在 `dictionaries/manifest.toml`，每一筆 SHALL 有鎖定網址、SHA-256、授權、是否可用於訓練與出處文字；`scripts/jiezi dict build` SHALL 只在 SHA-256 吻合時建置，並 SHALL NOT 修改詞條內容或轉換為簡化字。
Dictionary sources SHALL be listed in `dictionaries/manifest.toml`, each with a pinned URL, SHA-256, license, training-use flag and attribution text; `scripts/jiezi dict build` SHALL build only when the SHA-256 matches and SHALL NOT modify entries or convert them to Simplified characters.

#### Scenario: 檔案被改過 / Changed file

- **WHEN** 下載的檔案 SHA-256 與清單不符
  The downloaded file's SHA-256 differs from the manifest
- **THEN** 刪除下載檔並停止建置，既有的辭典檔不變
  The download is deleted and the build stops, leaving any existing dictionary untouched

### Requirement: Dictionary Grounding in Chats

使用者明顯在問詞語時，gateway SHALL 查本機辭典，最多附上 3 筆詞條原文，要求模型依辭典回答並註明出處，並 SHALL 在 `jiezi.sources` 列出用到的詞條；用到不可訓練的來源時，軌跡 SHALL 標 `training_use: false`。一般閒聊 SHALL NOT 觸發查詢。
When the user is clearly asking about words, the gateway SHALL look them up, attach at most three verbatim entries, ask the model to answer from them with the source cited, and SHALL list them in `jiezi.sources`; using a non-trainable source SHALL set `training_use: false`. Small talk SHALL NOT trigger lookups.

#### Scenario: 問成語的意思 / Asking what an idiom means

- **WHEN** 使用者問「『樂不思蜀』是什麼意思？」
  The user asks what 「樂不思蜀」 means
- **THEN** 模型收到該詞條的教育部辭典原文，回應的 `jiezi.sources` 含 `{source: moedict-revised, title: 樂不思蜀}`，軌跡 `training_use` 為 `false`
  The model receives the MOE entry verbatim, `jiezi.sources` contains it, and the trajectory's `training_use` is `false`

#### Scenario: 閒聊 / Small talk

- **WHEN** 使用者說「早安」
  The user says "good morning"
- **THEN** 不查辭典，`jiezi.sources` 為空
  No lookup happens and `jiezi.sources` is empty

# curriculum Specification

## Purpose
TBD - created by archiving change add-curriculum. Update Purpose after archive.
## Requirements
### Requirement: Licensed Curriculum Sources

課綱資料來源 SHALL 列在 `curriculum/manifest.toml`，每個來源 SHALL 有鎖定 commit、每個檔的 SHA-256、授權、是否可用於訓練與出處文字；`scripts/jiezi curriculum build` SHALL 只在 SHA-256 吻合時使用檔案，且 SHALL NOT 執行上游附的程式。
Curriculum sources SHALL be listed in `curriculum/manifest.toml` with a pinned commit, per-file SHA-256, license, training flag and attribution; `build` SHALL use files only when the SHA-256 matches and SHALL NOT run upstream code.

#### Scenario: 檔案被改過 / Changed file

- **WHEN** 下載的檔案 SHA-256 與清單不符
  A downloaded file's SHA-256 differs from the manifest
- **THEN** 刪除下載檔並停止建置
  The download is deleted and the build stops

### Requirement: Curriculum Grounding in Chats

使用者問到課綱代碼、國小學習微主題、某科某年級的學習內容，或國高中課本某冊某版本的章節時，gateway SHALL 附上對應資料給模型，SHALL 在回答後附上原文與實際用到的出處，並 SHALL 在 `jiezi.sources` 列出；一般閒聊 SHALL NOT 觸發。
For curriculum codes, primary-school topics, subject/grade contents or textbook chapters, the gateway SHALL attach the data, append it verbatim with the attributions used, and list it in `jiezi.sources`; small talk SHALL NOT trigger it.

#### Scenario: 問先修 / Asking about prerequisites

- **WHEN** 使用者問「孩子學『同分母分數的比較與加減』之前要先學什麼？」
  The user asks what comes before 「同分母分數的比較與加減」
- **THEN** 模型收到該微主題與由淺到深的完整先修鏈，`jiezi.sources` 含 `{source: tw-taxonomy, topic: 同分母分數的比較與加減}`
  The model receives the topic and its full prerequisite chain, and `jiezi.sources` lists it

#### Scenario: 問課本章節 / Asking about textbook chapters

- **WHEN** 使用者問「國一上數學翰林版教哪些單元？」
  The user asks which units the Hanlin grade-7 first-semester math textbook covers
- **THEN** 模型收到該冊該版本的單元與小節，出處只附 zetria-org/curriculum
  The model receives that volume's units and sections, with only the zetria attribution

#### Scenario: 閒聊 / Small talk

- **WHEN** 使用者說「我今天學到很多」
  The user says "I learned a lot today"
- **THEN** 不查資料，`jiezi.sources` 為空
  No lookup happens


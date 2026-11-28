## ADDED Requirements

### Requirement: Recall From The User's Wiki
When `JIEZI_WIKI_RECALL` is on, the gateway SHALL look up the user's own wiki (`~/wiki` by default) in a read-only local index and attach at most two matching sections as data, with the page paths appended after the answer. The index SHALL leave out `raw/`, `social/`, `boards/`, symlinks, pages over 200 KB, pages marked `private: true`, and sections that look like secrets. Answers using the wiki SHALL be marked untrainable, and wiki passages SHALL be removed before any request is sent to the cloud, Claude, teacher models or tier-2 helpers. The gateway SHALL NOT write to the wiki.

#### Scenario: 問題和 wiki 頁面相關 / A question the wiki covers
- **WHEN** wiki 有「CUDA 執行模型」頁，使用者問「CUDA 的 thread、block、grid 執行緒階層是什麼？」
  The wiki has a CUDA page and the user asks about it
- **THEN** gateway 附上該頁相關段落，回答後附【我的 wiki】出處，這筆紀錄不可訓練（private）
  The matching section is attached, its path is cited and the record is untrainable

#### Scenario: 轉交雲端 / Escalation
- **WHEN** 附上 wiki 段落的請求被轉交雲端或請教 Claude
  A request carrying wiki passages is escalated
- **THEN** 送出去的訊息不含 wiki 段落
  The outgoing messages do not contain the wiki passages

#### Scenario: 不相干或創作請求 / Unrelated or creative requests
- **WHEN** 使用者說「說一個笑話」或問 wiki 沒寫的事
  The user asks for a joke or about something the wiki does not cover
- **THEN** 不附 wiki 段落
  No wiki passage is attached

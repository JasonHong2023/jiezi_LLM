## MODIFIED Requirements

### Requirement: Memory Wiki
芥子 SHALL 把請教 Claude 或雲端得到的答案、使用者要它記住的事與更正，存成 Hermes llm-wiki 格式的 Markdown 頁面（依主題合併），頁面 SHALL 是正本，使用者修改或刪除後 SHALL 立即反映在查詢結果；含 Claude／雲端輸出的頁面 SHALL 標 `training_use: false`。上網／即時、問芥子自己與依賴前文的問題 SHALL NOT 存。
Jiezi SHALL keep consulted answers, notes and corrections as Hermes-format Markdown pages merged by topic; pages SHALL be the source of truth and edits SHALL take effect immediately; pages with Claude or cloud output SHALL be marked not trainable; web/live, self and context-dependent questions SHALL NOT be stored.
寫入答案、更正與「記住」筆記之前 SHALL 經 TrustGate 評估（與 gateway 共用同一個專案的 taint index）；`tainted` 的內容 SHALL NOT 寫入；頁面 SHALL 記錄 `trust_level` 與 provenance。
Writes SHALL go through TrustGate sharing the project's taint index; tainted content SHALL NOT be written; pages SHALL record trust level and provenance.

#### Scenario: 請教後記住 / Remembered after consulting

- **WHEN** 芥子請教 Claude「台灣最高的山是哪一座？」得到「玉山」
  Jiezi consults Claude and gets 玉山
- **THEN** 記憶 wiki 多了這一筆問答，來源標 Claude 與模型名稱
  The memory wiki gains the Q&A with Claude and the model as the source

#### Scenario: 即時問題 / Live question

- **WHEN** 請教「今天有什麼新聞？」
  Jiezi consults about today's news
- **THEN** 不存進記憶
  Nothing is stored

#### Scenario: 被污染的答案 / A tainted answer

- **WHEN** 某段答案文字已在 taint index
  An answer's text is already in the taint index
- **THEN** `save_answer` 不寫入並回傳 None；其他答案照常寫入
  save_answer writes nothing and returns None; other answers are saved as usual

# memory Specification

## Purpose
TBD - created by archiving change add-memory. Update Purpose after archive.
## Requirements
### Requirement: Memory Wiki

芥子 SHALL 把請教 Claude 或雲端得到的答案、使用者要它記住的事與更正，存成 Hermes llm-wiki 格式的 Markdown 頁面（依主題合併），頁面 SHALL 是正本，使用者修改或刪除後 SHALL 立即反映在查詢結果；含 Claude／雲端輸出的頁面 SHALL 標 `training_use: false`。上網／即時、問芥子自己與依賴前文的問題 SHALL NOT 存。
Jiezi SHALL keep consulted answers, notes and corrections as Hermes-format Markdown pages merged by topic; pages SHALL be the source of truth and edits SHALL take effect immediately; pages with Claude or cloud output SHALL be marked not trainable; web/live, self and context-dependent questions SHALL NOT be stored.

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

### Requirement: Recall From Memory

幾乎相同的問題 SHALL 直接以記憶回答並附註日期與來源頁；相關問題 SHALL 把記憶附給模型參考；使用者的更正 SHALL 優先於其他資料；「記住：…」的筆記 SHALL 附在每次對話。
Near-identical questions SHALL be answered from memory with the date and source page; related questions SHALL get the memory as reference; corrections SHALL take priority; notes SHALL join every chat.

#### Scenario: 再問一次 / Asking again

- **WHEN** 記憶裡有「一句話什麼是 LoRA」，使用者問「LoRA 是什麼？」
  Memory holds the LoRA answer and the user asks again
- **THEN** 直接用記憶回答，不載入本機模型、不再請教，軌跡標 `training_use: false`
  It is answered from memory without loading the model or consulting, marked not trainable

#### Scenario: 更正 / Correction

- **WHEN** 芥子回答台北 101 高 500 公尺，使用者說「不對，是 508 公尺」
  The user corrects an answer
- **THEN** 更正存到該主題頁，之後問到類似問題時最先附給模型
  The correction is stored and attached first to similar questions

### Requirement: Chat History

`jiezi chat` SHALL 保存聊天歷史並在重開時接續，`--new` 與 `/clear` SHALL 開始新的對話。
`jiezi chat` SHALL persist and resume history; `--new` and `/clear` SHALL start fresh.

#### Scenario: 重開聊天 / Reopening chat

- **WHEN** 關掉 `jiezi chat` 再打開
  The user reopens the chat
- **THEN** 看到上次的對話，新問題帶著前文送出
  The previous conversation is shown and new questions carry its context


## ADDED Requirements

### Requirement: Follow-up Questions Over an Attached Document

`jiezi chat` 以 `/file` 附上的文件 SHALL 持續附著到使用者取消（`/file clear` 或 `/clear`）為止，之後每一個問題 SHALL 都帶著這些文件送出；對話歷史 SHALL 只保存問題本身，SHALL NOT 重複保存文件全文。gateway SHALL 依每一個問題重新挑選段落，並 SHALL 把上一輪問答當成較低權重的提示；追問時 SHALL 預留空間使上一輪問答留在本機上下文中。
Documents attached with `/file` SHALL stay attached until detached and SHALL ride with every following question, while history SHALL keep only the bare question. The gateway SHALL re-select chunks for each question, using the previous exchange as a lower-weight hint, and SHALL reserve room so that exchange stays in the local context.

#### Scenario: 同一份文件連問兩題 / Two questions over one document

- **WHEN** 使用者 `/file 報告.pdf` 後問「請摘要」，接著再問「第三季營收是多少」
  The user attaches a report, asks for a summary, then asks about third-quarter revenue
- **THEN** 第二題不需要重新附檔，gateway 依第二題挑出相關段落回答
  The second question needs no re-attachment and is answered from chunks chosen for it

#### Scenario: 沒有關鍵字的追問 / A follow-up without keywords

- **WHEN** 上一輪問的是核能那一節，接著問「那相關數據是多少」
  The previous exchange was about the nuclear section and the user asks "what are the figures then"
- **THEN** 挑出的段落包含核能那一節，且上一輪問答仍在送給模型的訊息中
  The chosen chunks include the nuclear section and the previous exchange is still sent to the model

#### Scenario: 取消附著 / Detaching

- **WHEN** 使用者輸入 `/file clear` 後再問問題
  The user types `/file clear` and asks another question
- **THEN** 這一題不帶任何文件
  The question carries no document

### Requirement: Cached Chunk Notes Stay in Memory

gateway SHALL 把長文件各段的重點快取在記憶體中，同一份文件再次要求摘要時 SHALL NOT 重跑各段整理；快取 SHALL 有份數上限，SHALL NOT 寫入磁碟；有任何一段整理失敗時 SHALL NOT 快取。
Per-chunk notes SHALL be cached in memory so a repeated summary does not redo the map step; the cache SHALL be bounded, SHALL NOT be written to disk, and SHALL NOT keep partial results.

#### Scenario: 再摘要一次 / Summarizing again

- **WHEN** 使用者對同一份長文件第二次要求整理重點
  The user asks for the key points of the same long document a second time
- **THEN** 本機模型的呼叫次數少於第一次的分段數
  Fewer local calls are made than there are chunks

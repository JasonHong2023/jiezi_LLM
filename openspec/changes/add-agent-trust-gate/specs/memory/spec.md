## ADDED Requirements

### Requirement: Save Paths Go Through TrustGate / 寫入路徑經過 TrustGate

Both `save_answer()` and `save_correction()` SHALL call `TrustGate.evaluate_trust()` before writing. Content evaluated as `TAINTED` SHALL be rejected (not saved, error returned).

`save_answer()` 和 `save_correction()` 寫入前必須呼叫 `TrustGate.evaluate_trust()`。評估為 `TAINTED` 的內容必須被拒絕（不寫入、回傳錯誤）。

#### Scenario: Tainted Content Rejected from Memory / 污染內容被記憶拒絕

```gherkin
Given malicious content that triggers injection guard
When save_answer() is called with this content
Then TrustGate.evaluate_trust() returns TrustLevel.TAINTED
And the content is not saved to memory
And an error is returned to the caller
```

#### Scenario: Verified Content Saved with Provenance / 已驗證內容帶 Provenance 存入

```gherkin
Given a verified local answer with trust_level=VERIFIED
When save_correction() is called
Then TrustGate.evaluate_trust() returns VERIFIED
And the correction page frontmatter contains trust_level="verified" and full provenance
```

## MODIFIED Requirements

### Requirement: Memory Wiki

芥子 SHALL 把請教 Claude 或雲端得到的答案、使用者要它記住的事與更正，存成 Hermes llm-wiki 格式的 Markdown 頁面（依主題合併），頁面 SHALL 是正本，使用者修改或刪除後 SHALL 立即反映在查詢結果；含 Claude／雲端輸出的頁面 SHALL 標 `training_use: false`。**頁面前言 SHALL 新增 `trust_level`、`source_url`、`source_version`、`content_hash`、`fetched_at` 欄位，由 TrustGate 評估結果自動填入。** 上網／即時、問芥子自己與依賴前文的問題 SHALL NOT 存。

Jiezi SHALL keep consulted answers, notes and corrections as Hermes-format Markdown pages merged by topic; pages SHALL be the source of truth and edits SHALL take effect immediately; pages with Claude or cloud output SHALL be marked not trainable. **Page frontmatter SHALL add `trust_level`, `source_url`, `source_version`, `content_hash`, `fetched_at` fields, auto-populated from TrustGate evaluation.** Web/live, self and context-dependent questions SHALL NOT be stored.

#### Scenario: 請教後記住 / Remembered after consulting

- **WHEN** 芥子請教 Claude「台灣最高的山是哪一座？」得到「玉山」
  Jiezi consults Claude and gets 玉山
- **THEN** 記憶 wiki 多了這一筆問答，來源標 Claude 與模型名稱，**前言含 trust.level="unverified"＋provenance.source_channel="cloud"、provenance、content_hash、fetched_at**
  The memory wiki gains the Q&A with Claude and the model as the source, **frontmatter contains trust.level="unverified"＋provenance.source_channel="cloud", provenance, content_hash, fetched_at**

#### Scenario: 即時問題 / Live question

- **WHEN** 請教「今天有什麼新聞？」
  Jiezi consults about today's news
- **THEN** 不存進記憶
  Nothing is stored

#### Scenario: 網頁內容存入記憶 / Web content saved to memory

- **WHEN** 使用者附上網頁要求摘要，內容經 TrustGate 評估為 UNVERIFIED
  User attaches web page for summary, content evaluated as UNVERIFIED by TrustGate
- **THEN** 頁面前言含 `trust_level="unverified"、source_url=<URL>、content_hash、fetched_at`，可入記憶但不可入技能/訓練
  Page frontmatter contains `trust_level="unverified"`, `source_url=<URL>`, `content_hash`, `fetched_at`; can enter memory but not skills/training

#### Scenario: 污染內容被拒絕 / Tainted content rejected

- **WHEN** 附上含注入攻擊的文件呼叫 save_answer()
  Attached document with injection attack calls save_answer()
- **THEN** TrustGate 回傳 TAINTED，內容不寫入，回傳錯誤
  TrustGate returns TAINTED, content not saved, error returned

---

### Requirement: Recall From Memory

幾乎相同的問題 SHALL 直接以記憶回答並附註日期與來源頁；相關問題 SHALL 把記憶附給模型參考；使用者的更正 SHALL 優先於其他資料；「記住：…」的筆記 SHALL 附在每次對話。**回傳的記憶內容 SHALL 保留 trust_level、provenance 等信任欄位供下游使用。**

Near-identical questions SHALL be answered from memory with the date and source page; related questions SHALL get the memory as reference; corrections SHALL take priority; notes SHALL join every chat. **Returned memory content SHALL retain trust_level, provenance and other trust fields for downstream use.**

#### Scenario: 再問一次 / Asking again

- **WHEN** 記憶裡有「一句話什麼是 LoRA」，使用者問「LoRA 是什麼？」
  Memory holds the LoRA answer and the user asks again
- **THEN** 直接用記憶回答，不載入本機模型、不再請教，軌跡標 `training_use: false`，**回應保留 trust_level 與 provenance**
  It is answered from memory without loading the model or consulting, marked not trainable, **response retains trust_level and provenance**

#### Scenario: 更正 / Correction

- **WHEN** 芥子回答台北 101 高 500 公尺，使用者說「不對，是 508 公尺」
  The user corrects an answer
- **THEN** 更正存到該主題頁，之後問到類似問題時最先附給模型，**更正頁面前言含 trust_level、provenance**
  The correction is stored and attached first to similar questions, **correction page frontmatter contains trust_level, provenance**

---

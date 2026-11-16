## ADDED Requirements

### Requirement: Whole-Document Translation

使用者要求翻譯一份放不進本機上下文的文件時，系統 SHALL 逐段翻譯整份文件並依原文順序接回，SHALL NOT 以摘要或節錄代替；接回的譯文 SHALL 直接回傳，SHALL NOT 再交由模型改寫。翻譯軌跡 SHALL 標為不可用於訓練。
When asked to translate a document that does not fit the local context, the system SHALL translate every chunk and join them in source order, SHALL NOT substitute a summary or excerpt, and SHALL return the joined text without a rewriting pass. Translation trajectories SHALL be marked non-trainable.

#### Scenario: 十萬字的會議記錄 / A 100,000-character document

- **WHEN** 使用者附上 10 萬字的中文會議記錄並要求翻成英文
  The user attaches a 100,000-character Chinese document and asks for English
- **THEN** 每一段都有對應的譯文，段落順序與原文相同
  Every chunk has a translation, in the source order

#### Scenario: 沒有指出目標語言 / No target language named

- **WHEN** 使用者只說「幫我翻譯」並附上英文文件
  The user says only "translate this" with an English document
- **THEN** 譯成繁體中文
  It is translated into Traditional Chinese

### Requirement: Checked Translation Chunks

每一段譯文 SHALL 通過檢查：不是空的、長度與原文的比例在設定範圍內、原文的阿拉伯數字都保留、譯文確實是目標語言、詞彙對照表中的詞使用指定譯法。未通過的段 SHALL 帶著錯誤訊息重翻一次；仍未通過時 SHALL 保留該段原文並明確標記，回應 SHALL 列出失敗的段，SHALL NOT 把未通過的譯文當成成功回傳。
Every translated chunk SHALL pass checks (non-empty, plausible length ratio, Arabic numbers preserved, actually in the target language, glossary terms honoured); a failing chunk SHALL be retried once with the error, and if it still fails its source text SHALL be kept and clearly marked, the response SHALL list it, and a failing translation SHALL NOT be returned as a success.

#### Scenario: 漏掉數字 / A dropped number

- **WHEN** 原文有「營收 1,250 萬元」而譯文沒有 1,250 或 12.5
  The source says revenue was 12.5 million and the translation contains neither figure
- **THEN** 該段重翻；重翻仍缺時保留原文並標記為未能翻譯
  The chunk is retried; if the number is still missing the source is kept and marked untranslated

#### Scenario: 指定譯法 / A required term

- **WHEN** 詞彙表指定「芥子 → Jiezi」而譯文寫成 mustard seed
  The glossary maps 芥子 to Jiezi and the translation says "mustard seed"
- **THEN** 該段未通過檢查
  The chunk fails the check

### Requirement: Script Conversion Without a Model

目標語言是繁體中文而原文是簡體中文時，系統 SHALL 以字表與用語表直接轉換，SHALL NOT 呼叫語言模型，回應 SHALL 標明內容是字詞轉換；轉換結果 SHALL NOT 進入訓練資料。
When the target is Traditional Chinese and the source is Simplified Chinese, the system SHALL convert with its character and phrase tables, SHALL NOT call a language model, SHALL label the result as a conversion, and SHALL NOT let it enter training data.

#### Scenario: 簡體文件轉繁體 / A Simplified document

- **WHEN** 使用者附上簡體中文文件並要求轉成繁體
  The user attaches a Simplified Chinese document and asks for Traditional
- **THEN** 不啟動本機引擎也能完成，「软件」變成「軟體」
  It completes without the local engine and 软件 becomes 軟體

# documents Specification

## Purpose
在沙盒內讀取附件文件，長文件放得進本機上下文，可追問，段落摘要快取留在記憶體。
Read attachments in a sandbox, fit long documents into the local context and support follow-up questions.
## Requirements
### Requirement: Contained Document Reading

文件解析 SHALL 在有記憶體與時間上限的子行程中執行；損壞或惡意的檔案 SHALL 只回報讀取失敗，SHALL NOT 讓 gateway 或 CLI 當掉；含 DTD 的 .docx SHALL 被拒絕。
Parsing SHALL run in a memory- and time-limited child; a broken file SHALL only report a failure; a .docx with a DTD SHALL be refused.

#### Scenario: 損壞的 PDF / A broken PDF

- **WHEN** 使用者附上一個不是 PDF 的 `.pdf` 檔
  The user attaches a `.pdf` that is not a PDF
- **THEN** 回報無法讀取，程式繼續運作
  A read failure is reported and the program keeps running

### Requirement: Long Documents Fit the Local Context

最後一個問題超過本機上下文時，gateway SHALL 先濃縮：要摘要時分段整理重點，問答時只放最相關的段落並標出段落編號；濃縮後的內容 SHALL 放得進本機上下文；濃縮失敗時 SHALL 退回原本的截短。
Long questions SHALL be condensed (map-reduce summaries, or labeled relevant chunks) to fit the local context, falling back to trimming on failure.

#### Scenario: 長報告摘要 / Summarizing a long report

- **WHEN** 使用者附上 5 萬字的報告並要求摘要
  The user attaches a 50,000-character report and asks for a summary
- **THEN** 先逐段整理重點，再依整理後的重點回答
  Chunks are summarized first and the answer is based on those notes

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

### Requirement: Slides and Spreadsheets

文件讀取 SHALL 支援 `.pptx` 與 `.xlsx`：投影片 SHALL 依編號順序輸出並標出張數，備忘稿 SHALL 一併輸出；試算表 SHALL 依工作表輸出每一列並保留空欄位置，日期樣式的數字 SHALL 轉成日期，公式 SHALL 取檔案中儲存的結果；超過張數、工作表或儲存格上限時 SHALL 只讀前面的部分並在警告中註明；解析 SHALL 沿用受限子行程、解壓大小上限並拒絕 DTD。
Reading SHALL support `.pptx` and `.xlsx`: slides in numeric order with their notes; sheets row by row with empty columns kept, date-styled numbers converted to dates and stored formula results used; limits SHALL truncate with a warning; parsing SHALL keep the child-process limits, the decompressed-size cap and the DTD refusal.

#### Scenario: 超過九張的簡報 / A deck with more than nine slides

- **WHEN** 簡報有 11 張投影片
  A deck has 11 slides
- **THEN** 第 10 張排在第 9 張之後，而不是第 1 張之後
  Slide 10 follows slide 9, not slide 1

#### Scenario: 含日期的試算表 / A sheet with dates

- **WHEN** 儲存格是日期樣式、內容為序號 46342
  A date-styled cell holds the serial number 46342
- **THEN** 輸出 `2026-11-16`
  `2026-11-16` is output

#### Scenario: 整張是圖片的簡報 / An image-only deck

- **WHEN** 投影片幾乎沒有文字
  The slides contain almost no text
- **THEN** 讀取成功但附上警告，建議匯出成 PDF
  Reading succeeds with a warning suggesting a PDF export

### Requirement: Legacy Office Formats Through a Sandboxed Converter

文件讀取 SHALL 支援 `.doc`、`.ppt`、`.xls`：先以 LibreOffice 無介面模式轉成新格式再讀取。轉檔 SHALL 只在沒有網路、看不到家目錄與專案目錄的沙盒中執行，SHALL 有時間、記憶體與輸出大小上限；沙盒不可用時 SHALL NOT 在沙盒外轉檔。沒有安裝 LibreOffice 時 SHALL 回報需要安裝並附指令，SHALL NOT 影響其他格式。
Reading SHALL support `.doc`, `.ppt` and `.xls` by converting them with headless LibreOffice first. Conversion SHALL run only in a sandbox without network or access to the home and project directories, with time, memory and output limits, and SHALL NOT run outside the sandbox. Without LibreOffice a message with the install command SHALL be given and other formats SHALL be unaffected.

#### Scenario: 舊版 Word 檔 / A legacy Word file

- **WHEN** 使用者附上 `.doc` 檔並要求摘要，且 LibreOffice 與沙盒都可用
  The user attaches a `.doc` and asks for a summary, with LibreOffice and the sandbox available
- **THEN** 讀出的文字與同一份文件另存成 `.docx` 後讀出的相同
  The text equals what reading the same document saved as `.docx` gives

#### Scenario: 沒有安裝 LibreOffice / LibreOffice missing

- **WHEN** 沒有 LibreOffice 而使用者附上 `.xls`
  LibreOffice is absent and the user attaches an `.xls`
- **THEN** 回報需要 LibreOffice 與安裝指令；`.xlsx` 等其他格式照常可讀
  The message names LibreOffice and the install command; `.xlsx` and other formats still work

#### Scenario: 沙盒不可用 / Sandbox unavailable

- **WHEN** 沙盒自我檢查失敗
  The sandbox self-check fails
- **THEN** 不轉檔，回報無法讀取
  Nothing is converted and a read failure is reported

### Requirement: Semantic Chunk Selection for Document Questions
When a question is asked about an attached long document and the embedding engine is available, the gateway SHALL rank the document's chunks by fusing the lexical rank with an embedding-similarity rank, and SHALL fall back to the lexical rank alone whenever embeddings are unavailable, fail, or are not ready within the configured timeout. Chunk vectors MUST be kept in memory only and MUST NOT be written to disk.

長文件問答在 embedding 引擎可用時，SHALL 以字面名次與語意名次合併挑段落；embedding 不可用、失敗或逾時 SHALL 退回字面排序。段落向量 MUST 只放在記憶體，MUST NOT 寫入磁碟。

#### Scenario: A colloquial question finds a chunk worded differently
- **WHEN** a question shares no key terms with the chunk that answers it but is close to it in embedding similarity
- **THEN** that chunk is among those sent to the model

#### Scenario: Embeddings not ready in time
- **WHEN** the chunk vectors are not ready within the timeout
- **THEN** the answer uses the lexical ranking, the response metadata says so, and the vectors keep building for the next question

#### Scenario: Embedding engine unavailable
- **WHEN** the embedding engine is switched off, missing its model, or returns an error
- **THEN** the lexical ranking is used and the answer is not blocked

#### Scenario: Vectors are never persisted
- **WHEN** chunk vectors are computed for a document
- **THEN** they exist only in the gateway's in-memory cache and disappear when evicted or when the gateway stops

### Requirement: Recall Aids for Document Chunk Selection
When the recall aid is enabled, the gateway SHALL improve chunk selection for questions about an attached long document either by reserving places for the top semantic chunks or by also ranking with a locally drafted hypothetical answer, and SHALL fall back to the existing fused ranking whenever the aid fails or exceeds its time limit.

長文件問答的挑段落 SHALL 可選擇保留語意前幾名的名額，或另用本機模型猜出的答案句排序；失敗或逾時 SHALL 退回現行的合併排序。

#### Scenario: A semantically close chunk is kept
- **WHEN** the reserve mode is on and a chunk is among the top semantic results but ranks low lexically
- **THEN** that chunk is sent to the model

#### Scenario: Drafting the hypothetical answer is too slow
- **WHEN** the hypothetical answer is not ready within the time limit
- **THEN** the existing fused ranking is used and the answer is not blocked


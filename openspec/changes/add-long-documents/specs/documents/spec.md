## ADDED Requirements

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

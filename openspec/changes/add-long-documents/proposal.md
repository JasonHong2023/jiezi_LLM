## Why

「文件摘要」是四類任務之一，但本機模型每個槽位只有 4096 token，報告、會議記錄很容易超過，目前只會從中間截掉；也沒有辦法直接讀 PDF、Word。使用者 2026-11-16 決定先做長文件處理與讀取檔案。
Summarization is a core task, but the local slot holds 4096 tokens and PDF/Word could not be read. The user chose this on 2026-11-16.

## What Changes

- `src/jiezi/documents.py`：讀取 PDF（pypdf 7.1.0；掃描頁用 tesseract `chi_tra+eng` OCR，取圖需 Pillow 13.0.0）、.docx（標準函式庫解 XML，拒絕 DTD、限制解壓大小）、.html（去掉 script、style）、純文字（UTF-8、Big5）。解析在子行程中執行：記憶體上限 1.5 GB、時間上限 10 分鐘、OCR 最多 2 執行緒；檔案上限 50 MB。
  Readers for PDF (with OCR for scanned pages), .docx, .html and text, run in a limited child process.
- `src/jiezi/longdoc.py` 與 gateway：最後一個問題放不進本機上下文時，先用本機模型處理——要摘要就分段整理重點（4 路平行），合起來還太長再整理一輪（最多 3 輪）；要問答就以 IDF 加權雙字詞挑最相關的段落並標段落編號。濃縮後照常走平行取樣、驗證與轉交。濃縮失敗就退回原本的截短。查辭典等外掛資料時只用問題，不用整份文件。`JIEZI_LONGDOC`（預設 on）。
  The gateway condenses long documents with the local model (map-reduce summaries or relevant-chunk selection) before the normal pipeline.
- `jiezi ask --file 路徑`（可重複）、`jiezi chat` 的 `/file 路徑`；管線輸入也包成文件。chat 回答後把歷史中的文件全文換成一行說明，避免每題重送。
  `--file` for ask, `/file` for chat; piped input is wrapped as a document.

## Non-Goals

- 轉交雲端時改送原文（目前取得本機引擎後才濃縮；本機無法使用而直接轉交時，雲端收到的是原文）。/ Sending the original to the cloud after condensing.
- 舊版 .doc、.pptx、試算表。/ Legacy .doc, .pptx, spreadsheets.
- 長文件的追問（目前一份文件對應一題；要再問請重新附檔）。/ Follow-up questions over the same document.

## Capabilities

### New Capabilities

- `documents`：讀取文件與長文件濃縮。/ Document reading and long-document condensing.

### Modified Capabilities

（無）/ (None)

## Impact

- 新相依：pypdf 7.1.0（BSD-3-Clause）、Pillow 13.0.0（MIT-CMU）；tesseract-ocr-chi-tra 為系統套件（Apache-2.0）。
- 實測：Intel 規格書 PDF 63 頁 146,495 字 5.9 秒；使用者的 .docx 會議記錄 100,512 字 0.9 秒（52 段）；PowerPoint 匯出的圖片 PDF 13 頁全部走 OCR，25 秒。

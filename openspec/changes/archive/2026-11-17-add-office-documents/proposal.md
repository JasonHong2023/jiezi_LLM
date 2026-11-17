## Why

add-long-documents 把 .pptx 與試算表列為 Non-Goal；使用者的文件裡簡報與 Excel 很常見。使用者 2026-11-16 指示把尚未規劃的功能做起來。
Slides and spreadsheets were out of scope for add-long-documents but are common among the user's files.

## What Changes

- `documents.py` 新增 `.pptx`、`.xlsx`（只用標準函式庫，無新相依；沿用受限子行程、拒絕 DTD、解壓大小上限）：
  - `.pptx`：依投影片編號順序輸出「〔第 N 張投影片〕」加文字，備忘稿附在後面（頁碼不算）；最多 500 張；幾乎沒有文字時提醒「可能整張是圖片，請匯出成 PDF 以便 OCR」。
  - `.xlsx`：每個工作表輸出「〔工作表：名稱〕」與「欄 | 欄」的列，保留空欄位置；共用字串（不含注音標註）、行內字串、布林、公式的快取值；日期樣式的數字轉成 `YYYY-MM-DD`（含 1904 系統）；上限 50 張工作表、60 欄、20 萬個儲存格，超過時註明。
  `.pptx` (slide text and notes, in order) and `.xlsx` (rows per sheet, dates converted, cached formula values) readers using the standard library only.
- `jiezi ask --file`、chat `/file`、桌面網頁「附加文件」與 `POST /v1/documents` 因共用 `SUPPORTED` 而一併支援。
  All attachment paths pick the new formats up.

## Non-Goals

- 舊版二進位格式 .doc／.ppt／.xls（需要 LibreOffice 或 antiword 之類的系統套件；請先另存成新格式）。/ Legacy binary formats.
  （更正 2026-11-17，R19.4：已由 add-legacy-office 補上，沙盒內以 LibreOffice 轉檔。/ Correction: added by add-legacy-office.）
- 投影片或儲存格裡內嵌圖片的 OCR、圖表、SmartArt 的結構。/ OCR of embedded images, charts.
- 重新計算公式（只取檔案裡存的上次計算結果；從未計算過的公式是空的）。/ Recomputing formulas.
- .ods／.odp／.odt。/ OpenDocument formats.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `documents`：新增 PowerPoint 與 Excel 的讀取需求（`documents` 由尚未歸檔的 add-long-documents 建立，須先歸檔該變更）。/ Adds slide and spreadsheet reading; archive add-long-documents first.

## Impact

- 無新相依。實測使用者電腦上的 3 份 .pptx（0.3–0.4 秒）與 3 份 .xlsx（213 字 0.2 秒、44.7 萬字 0.7 秒、183 萬字 4.3 秒並觸發儲存格上限提醒）皆讀取成功。

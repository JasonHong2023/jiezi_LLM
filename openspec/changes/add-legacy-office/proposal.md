> **狀態 / Status**：使用者 2026-11-17 審閱並同意。LibreOffice 的安裝已由使用者於 2026-11-17 同意。
> Proposal only, **not implemented**; awaiting the user's go-ahead. Installing LibreOffice was approved on 2026-11-17.

## Why

add-long-documents、add-office-documents 都把舊版二進位格式（.doc、.ppt、.xls）列為 Non-Goal：這些格式沒有公開好解析的結構，只用標準函式庫讀不了，現在只能請使用者先另存新檔。使用者 2026-11-17 同意安裝 LibreOffice 來處理。
Legacy binary Office formats cannot be parsed with the standard library; today the user must re-save them first. The user approved installing LibreOffice for this.

## What Changes

- `documents.py` 新增 `.doc`、`.ppt`、`.xls`（以及順帶可得的 `.rtf`、`.odt`、`.odp`、`.ods`，見 OQ1）：先用 LibreOffice 無介面模式轉成 `.docx`／`.pptx`／`.xlsx`，再交給既有的讀取程式。
  Legacy files are converted to the modern format by headless LibreOffice, then read by the existing readers.
- **轉檔只在沙盒裡執行**：沿用程式題驗證用的 bubblewrap 沙盒——沒有網路、系統唯讀、看不到家目錄與專案目錄，只掛入「要轉的那一個檔案」與一個用完即刪的暫存目錄；LibreOffice 的設定檔目錄也放在暫存目錄（不讀寫使用者自己的 LibreOffice 設定）。限制：120 秒、1.5 GB 記憶體、輸出上限 64 MB。沙盒不可用時**不在沙盒外轉檔**，回報無法讀取並建議另存新檔。
  Conversion runs only inside the existing bubblewrap sandbox (no network, read-only system, no home or project directory, one input file and a throw-away work directory, a private LibreOffice profile); time, memory and output are capped. Without the sandbox nothing is converted.
- 沒裝 LibreOffice 時：回報「需要 LibreOffice」與安裝指令，其他格式不受影響。`scripts/jiezi doctor` 多一項檢查；bootstrap 多一個選用步驟 `office`（需要 sudo，照既有的視窗等待方式）。
  Without LibreOffice a clear message with the install command is given; `doctor` gains a check and bootstrap an optional `office` step.
- CLI、chat、桌面網頁與 `POST /v1/documents` 因共用 `SUPPORTED` 一併支援。

## Non-Goals

- 巨集的執行或分析（轉檔不執行巨集；含巨集的檔案只取文字）。/ Running or analysing macros.
- 密碼保護的檔案、WPS／Pages／Keynote 等其他格式。/ Password-protected files and other suites.
- 用 LibreOffice 做 PDF 或圖片輸出、保留版面。/ PDF or image export, layout fidelity.
- 把 LibreOffice 當成必要相依（沒裝時其他功能照常；可攜性 R21）。/ Making LibreOffice mandatory.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `documents`：新增舊版 Office 格式的讀取（須先歸檔 add-long-documents）。/ Legacy Office formats.

## Impact

- **新系統相依（選用）**：`libreoffice-writer-nogui`、`-calc-nogui`、`-impress-nogui`（Ubuntu 24.04 的 4:24.2.7-0ubuntu0.24.04.7，MPL-2.0；59 個套件、下載約 104 MB [本機查證]）。
- **R23 查證 [OSV，2026-11-17]**：該版本有 8 則未修補公告，嚴重度皆為 medium、沒有 High／Critical：Calc 外部資料連結 4 則、連結影音檔交給 GStreamer 1 則、URL 展開環境變數 1 則、dBASE 驅動 1 則、1 則已被撤回。這些都要靠「文件去連外部資源或讀本機其他檔案」才成立——沙盒沒有網路、看不到家目錄與 `.env`，所以攻擊面被擋掉 **[推論：依公告描述判斷，未逐一重現]**。登記到 `stack.md` 與 `security/accepted.toml`。
- 耗時 **[估]**：LibreOffice 冷啟動約 2–5 秒，加上轉檔；每份文件多數秒到十幾秒。

## 已決事項（原 Open Questions）/ Resolved

- **OQ1**：要，一併支援 `.rtf` 與 OpenDocument（`.odt`、`.odp`、`.ods`）（使用者 2026-11-17：「要」）。/ Yes, also `.rtf` and OpenDocument.
- **OQ2**：使用者沒有另外指定；採建議的 (a)——照樣轉檔取文字並加一行提醒（轉檔不執行巨集）。**這一項是我依建議採用的，使用者可更正。** / Not answered separately; the recommended option (convert and warn) is used and can be changed.

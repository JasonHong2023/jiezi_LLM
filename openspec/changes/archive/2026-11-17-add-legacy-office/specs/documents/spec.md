## ADDED Requirements

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

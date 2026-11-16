## ADDED Requirements

### Requirement: Authenticated Document Upload

gateway SHALL 提供需要金鑰的文件上傳端點：只接受支援的格式與不超過上限的檔案，SHALL 在受限的子行程中讀取，SHALL 回傳清理過的文字，SHALL 在讀取結束後刪除上傳的檔案；檔名 SHALL 只取最後一段，SHALL NOT 用來決定儲存路徑；讀不出來的檔案 SHALL 只回報錯誤。
The gateway SHALL offer a key-protected upload endpoint that accepts only supported formats within the size limit, reads in the limited child process, returns cleaned text and deletes the upload afterwards; the file name SHALL be reduced to its last component and SHALL NOT decide where anything is stored; unreadable files SHALL only produce an error.

#### Scenario: 上傳文字檔 / Uploading a text file

- **WHEN** 帶金鑰上傳 `會議.txt`
  `會議.txt` is uploaded with the key
- **THEN** 回傳檔名、字數與文字，暫存目錄裡沒有留下檔案
  The name, length and text are returned and nothing remains in the upload directory

#### Scenario: 沒有金鑰或格式不支援 / No key or unsupported format

- **WHEN** 沒帶金鑰，或上傳 `.exe`
  The key is missing, or an `.exe` is uploaded
- **THEN** 分別回 401 與 400，不讀取內容
  401 and 400 are returned and nothing is read

### Requirement: Attached Documents in the Desktop Page

桌面網頁 SHALL 讓使用者附加文件並顯示目前附著的文件；附著的文件 SHALL 跟著之後每一個問題送出，直到使用者移除或清除對話；送出的文件標記 SHALL 與 `jiezi chat` 相同；畫面上的對話 SHALL 只顯示問題本身。
The desktop page SHALL let the user attach documents and show what is attached; they SHALL ride with every following question until removed or the conversation is cleared, using the same markers as `jiezi chat`; the visible conversation SHALL show only the question.

#### Scenario: 附檔後追問 / Follow-up after attaching

- **WHEN** 使用者附加一份報告，問一題後再問第二題
  The user attaches a report and asks two questions in a row
- **THEN** 兩題送出的訊息都包含這份文件
  Both requests carry the document

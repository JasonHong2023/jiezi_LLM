## ADDED Requirements

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

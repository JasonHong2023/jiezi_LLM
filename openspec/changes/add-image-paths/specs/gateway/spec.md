## ADDED Requirements

### Requirement: Image Paths
When `JIEZI_IMAGE_PATHS` is on and the last user message names local image files, the gateway SHALL read each file that is a regular PNG, JPEG, WebP or GIF file (checked by extension and file header) of at most 5 MB, at most 3 per question, and attach it to that message as a base64 `image_url`; paths in system, assistant or tool messages and in attached documents SHALL NOT be read; files that fail the checks SHALL get the existing path note and the reason SHALL be recorded in metadata `image_paths`.

#### Scenario: 打路徑問圖 / A typed image path
- **WHEN** 使用者在桌面版打「D:\download\animals.jpg 裡有哪些動物」，檔案存在、3 MB
  The user types a Windows path to an existing 3 MB JPEG
- **THEN** gateway 讀檔轉 base64 附上，本機模型看到圖片作答，metadata `image_paths` 記 ok
  The image is attached as base64 and the local model answers from it

#### Scenario: 不是圖的檔案 / Not really an image
- **WHEN** 路徑是 `a.png`，但檔頭不是 PNG
  The file is named .png but its header is not PNG
- **THEN** 不附上，照舊提醒模型看不到，metadata 記原因
  It is not attached; the path note is added and the reason recorded

#### Scenario: 工具結果裡的路徑 / A path inside a tool result
- **WHEN** 工具結果或網頁內容裡出現本機圖片路徑
  A tool result mentions a local image path
- **THEN** gateway 不讀那個檔案
  The gateway does not read it

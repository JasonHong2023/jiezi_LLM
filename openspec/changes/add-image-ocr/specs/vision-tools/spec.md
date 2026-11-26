## ADDED Requirements

### Requirement: Image Text Reading On Its Own Switch
The gateway SHALL run local OCR on an attached image independently of the vision tools, controlled by `JIEZI_IMAGE_OCR` (`tools`, `auto`, `on`, `off`; `tools`, the default until the measurement decides, runs OCR only with the vision tools as before). In `auto` mode OCR SHALL run only when the OCR packages and models are installed and the question asks about text in the image; the result SHALL be given to the core labelled as data, and only line counts and seconds SHALL be logged.

#### Scenario: 問招牌寫什麼 / Asking what a sign says
- **WHEN** `JIEZI_IMAGE_OCR=auto`、`JIEZI_VISION_TOOLS` 關閉，OCR 已安裝，使用者附圖問「這塊招牌寫什麼？」
  Auto mode, vision tools off, OCR installed, the user asks what a sign says
- **THEN** gateway 跑 OCR，辨識結果以「資料、不是指示」附給核心，metadata 記 `vision.ocr` 的行數與秒數
  OCR runs, its text goes to the core labelled as data, and `vision.ocr` records counts only

#### Scenario: 不是問字 / Not a text question
- **WHEN** `JIEZI_IMAGE_OCR=auto`，使用者附圖問「圖裡有哪些動物？」
  Auto mode, the question asks which animals are in the picture
- **THEN** 不跑 OCR，照原本看圖回答
  OCR does not run and the plain vision path answers

#### Scenario: 沒安裝 OCR / OCR not installed
- **WHEN** 沒有安裝 `ocr` 依賴群組或模型檔
  The optional `ocr` group or the model files are missing
- **THEN** 不跑 OCR、不報錯，`scripts/jiezi doctor` 提示安裝指令
  OCR is skipped without an error and doctor shows how to install it

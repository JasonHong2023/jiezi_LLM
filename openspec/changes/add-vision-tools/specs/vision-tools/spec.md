## ADDED Requirements

### Requirement: Local Vision Tools
The gateway SHALL provide local image tools (tagging, detection, open-vocabulary search, OCR) that run on the CPU by default, with time and memory limits, and SHALL fall back to the plain vision path when a tool fails or times out.

#### Scenario: 工具逾時 / A tool times out
- **WHEN** 附圖的問題送進來，偵測工具超過時限
  An image question arrives and the detector exceeds its time limit
- **THEN** 略過工具結果，照原本方式看圖回答，metadata 記下逾時
  The tool output is skipped, the answer uses the plain vision path, and the timeout is recorded

### Requirement: Grounded Image Answers
With vision tools on, tool results SHALL be given to the core as data, not instructions, and every object the answer names SHALL be checked with open-vocabulary detection; objects below the threshold SHALL be removed and listed as unconfirmed.

#### Scenario: 捏造的物體 / An invented object
- **WHEN** 核心模型說圖裡有長頸鹿，但開放詞彙偵測找不到
  The core says there is a giraffe but open-vocabulary detection finds none
- **THEN** 答案不列長頸鹿，最後註明「模型提到長頸鹿，但偵測不到，已略過」，metadata `vision_check` 記錄
  The giraffe is dropped, an unconfirmed note is appended, and `vision_check` records it

#### Scenario: 不轉雲端 / Stays local
- **WHEN** 策略是 jiezi，問題附圖
  Policy jiezi, an image question
- **THEN** 圖片不送到雲端或 Claude，除非使用者選了 jiezi-cloud 或 jiezi-ask-claude
  The image is not sent to the cloud or Claude unless the user chose that policy

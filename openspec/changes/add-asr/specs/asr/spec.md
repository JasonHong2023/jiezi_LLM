## ADDED Requirements

### Requirement: Local Speech Recognition Endpoint / 本機語音辨識端點
gateway SHALL 提供 OpenAI 相容的 `POST /v1/audio/transcriptions`（multipart），以 Breeze-ASR-25 在本機辨識語音。端點 SHALL 只在 `JIEZI_ASR=on` 時啟用（預設關），SHALL 要求 gateway 金鑰；上傳 SHALL 不超過 200 MB 與 2 小時；`response_format` SHALL 為 json、text、srt、vtt 或 verbose_json；輸出文字 SHALL 轉成台灣繁體用字。上傳的音檔 SHALL 在辨識後刪除，紀錄 SHALL 只記音長、耗時與字數。
The gateway SHALL transcribe uploaded audio locally with Breeze-ASR-25, off by default and key-protected, with size limits, subtitle formats, Taiwan Traditional output, and no retained audio.

#### Scenario: 未啟用 / Disabled

- **WHEN** `JIEZI_ASR` 不是 on
  ASR is not enabled
- **THEN** 回 404，不啟動任何行程
  404 and no process is started

#### Scenario: 字幕輸出 / Subtitles

- **WHEN** 上傳 3 分鐘音檔並要求 `srt`
  A three-minute file is uploaded with response_format srt
- **THEN** 回傳帶時間碼的字幕，文字為繁體
  Timed subtitles in Traditional Chinese are returned

### Requirement: Three-Way GPU Turn-Taking / 核心、TTS、ASR 輪流使用顯示卡
核心、TTS 與 ASR SHALL NOT 同時占用 GPU。任一方要使用時 SHALL 等其他方沒有進行中的工作，再請它讓出；核心有進行中的請求時 SHALL 等待（上限 120 秒，逾時回 503）；評測保留 GPU 期間 TTS 與 ASR SHALL 被拒絕。
The core, TTS and ASR SHALL never share the GPU; each takes it only when the others are idle.

#### Scenario: 語音對話一輪 / One voice-chat turn

- **WHEN** 使用者說話後，芥子要辨識、回答再朗讀
  A spoken question is transcribed, answered and read aloud
- **THEN** ASR、核心、TTS 依序取得 GPU，任何時刻只有一方載入
  ASR, the core and TTS take the GPU in turn; only one is loaded at a time

### Requirement: Voice Input In The Desktop And CLI / 桌面與 CLI 的語音輸入
桌面網頁 SHALL 提供「按住說話」：錄音辨識後把文字填入輸入框，SHALL NOT 自動送出；「語音對話」開關開啟時 SHALL 辨識後自動送出，回答完成後自動朗讀。`scripts/jiezi asr <檔案>` SHALL 輸出文字、srt 或 vtt。辨識結果 SHALL NOT 自動成為訓練資料。
The desktop SHALL offer push-to-talk (fills the input, does not send) and a voice-chat mode; the CLI SHALL transcribe files.

#### Scenario: 按住說話 / Push to talk

- **WHEN** 使用者按住按鈕說「明天台北天氣如何」後放開
  The user holds the button, speaks and releases
- **THEN** 輸入框出現辨識文字，等使用者按送出
  The recognized text appears in the input and waits for the user to send it

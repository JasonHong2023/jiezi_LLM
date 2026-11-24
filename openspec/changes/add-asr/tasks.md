# add-asr 任務 / Tasks

## 1. 權重與環境 / Weights

- [ ] 1.1 `docs/licenses.md` 登記 `breeze-asr-25`（程式 MIT、權重 Apache-2.0、revision cffe7ccb）；`docs/capabilities.toml` 登記 `asr`
- [ ] 1.2 `scripts/jiezi asr setup`：只下載 safetensors 與設定檔，逐檔 sha256；不下載 pickle／optimizer
- [ ] 1.3 冒煙測試：GPU fp16 辨識 TTS 產生的兩句與一段 1 分鐘音檔，量 VRAM、耗時、字錯率

## 2. 工作行程與 GPU / Worker and GPU

- [ ] 2.1 `src/jiezi/asr/worker.py`：JSON 行協定、ffmpeg 解碼 16 kHz、30 秒分段＋時間戳、閒置結束
- [ ] 2.2 GPU 三方輪流：`gpu_owner` ∈ None／tts／asr，共用的取得／讓出邏輯（從 tts/manager 抽出）
- [ ] 2.3 測試（假 worker）：三方輪流、核心忙碌、held、worker 失敗

## 3. 端點與介面 / Endpoint and interfaces

- [ ] 3.1 `POST /v1/audio/transcriptions`（multipart）：金鑰、`JIEZI_ASR=on`、200 MB／2 小時上限、json／text／srt／vtt／verbose_json、簡轉台灣用字；`/health` 的 asr
- [ ] 3.2 `scripts/jiezi asr <檔案> [--srt|--vtt|--text] [-o]`
- [ ] 3.3 桌面「按住說話」：錄音 → 辨識 → 填入輸入框（不自動送出）
- [ ] 3.4 桌面「語音對話」：辨識後自動送出、回答後自動朗讀；顯示目前階段（聽寫中／思考中／朗讀中）
- [ ] 3.5 測試：未啟用 404、未授權 401、超大 413、格式、srt／vtt 時間碼、簡轉繁

## 4. 實測與文件 / Live test and docs

- [ ] 4.1 實機：麥克風一句、檔案一段、語音對話一輪；量切換耗時
- [ ] 4.2 Hermes 語音輸入設定實測；`docs/clients.md`；dev-plan、HANDOFF、當日紀錄

## 5. 驗證 / Validation

- [ ] 5.1 `openspec validate add-asr --strict`、`--all --strict`、全量 unittest、`git diff --check`

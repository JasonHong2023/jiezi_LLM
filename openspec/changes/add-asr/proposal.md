# add-asr 提案 / Proposal

> **狀態 / Status**：提案（2026-11-24，主控）。使用者 2026-11-24 要求加入 Breeze-ASR-25；決定 GPU 與核心／TTS 輪流使用，範圍四項全做：API 端點、桌面麥克風、檔案轉逐字稿、語音對話。

## Why / 為什麼

芥子能說（add-tts）但不能聽。Breeze-ASR-25（MediaTek Research）以 Whisper-large-v2 針對台灣華語與中英夾雜微調，中英夾雜 CSZS 的 WER 由 29.5% 降到 13.0%、CommonVoice zh-TW 由 9.8% 降到 8.0%，輸出繁體。加上它，芥子可以聽寫、轉逐字稿，並和 TTS 串成語音對話。

Jiezi can speak but not listen. Breeze-ASR-25 targets Taiwan Mandarin and code-switching.

## 分類、現成方案搜尋、資安掃描 / Classification, existing-solution search, security scan

- 分類 / Classification：**核心模組＋獨立工作行程**（與 add-tts 相同），不是 `SKILL` 也不是 `MCP`：提供 OpenAI 相容的 `/v1/audio/transcriptions`，客戶端照標準 API 呼叫。
- 現成方案搜尋 / Existing-solution search（2026-11-24 主控查證）：
  1. **Breeze-ASR-25**（使用者指定）：程式 MIT（GitHub mtkresearch/Breeze-ASR-25）、權重 Apache-2.0（HF `MediaTek-Research/Breeze-ASR-25`，revision `cffe7ccb`），base Whisper-large-v2，1.55B 參數，`model.safetensors` 2.9 GB。
  2. Whisper-large-v2／v3 原版：中英夾雜明顯較差（同表 WLV3 CSZS 26.4%）。
  3. COOL-Whisper：同表各項多半不如 Breeze-ASR-25。
  4. 芥子現有：無語音辨識。`textconv.simplified_to_taiwan` 可把偶發的簡體輸出轉成台灣用字。
- 資安掃描 / Security scan：只下載 `model.safetensors`（safetensors 格式，不執行程式碼）與 JSON／文字設定檔；**不下載** repo 裡的 `optimizer.bin`、`scheduler.bin`、`random_states_*.pkl`（pickle，可執行任意程式碼）與 `whisper-github/*.pt`。用 `transformers` 的 Whisper 類別載入，不用 `trust_remote_code`。沿用 add-tts 的獨立環境 `var/tts/venv`（已有 torch、transformers 5.24、soundfile），不新增套件；音訊解碼用系統 ffmpeg。上傳的音檔只在記憶體與暫存檔，辨識完即刪。

## What Changes / 變更內容

1. **權重**：`scripts/jiezi asr setup` 下載鎖定 revision 的必要檔案到 `models/breeze-asr-25/`，逐檔核對 sha256。
2. **ASR 工作行程**：`src/jiezi/asr/worker.py` 在 `var/tts/venv` 執行，stdin/stdout JSON 行協定；fp16 上 GPU（約 3.2 GB）；長音檔依 30 秒切段、輸出含時間戳；閒置 120 秒自動結束。
3. **GPU 三方輪流**：把 add-tts 的 `gpu_owner` 一般化為 `None`（核心或閒置）、`"tts"`、`"asr"`；任一方要用 GPU 時，等其他方閒置後請它讓出。核心有進行中的請求時等待（上限 120 秒），評測保留（held）時拒絕。
4. **API**：`POST /v1/audio/transcriptions`（OpenAI 相容，multipart：`file`、`model`、`language`、`response_format` ∈ json／text／srt／vtt／verbose_json），需 gateway 金鑰、`JIEZI_ASR=on`（預設關）；上限 200 MB、2 小時；輸出經 `simplified_to_taiwan` 轉台灣用字。
5. **檔案轉逐字稿**：`scripts/jiezi asr <音檔或影片> [--srt|--vtt|--text] [-o 檔案]`。
6. **桌面麥克風**：輸入框旁「按住說話」按鈕（瀏覽器 MediaRecorder 錄音）→ 轉成文字填入輸入框，使用者確認後再送出。
7. **語音對話**：桌面「語音對話」開關：說話 → 自動送出 → 芥子回答 → 自動朗讀（ASR → 核心 → TTS，每輪要輪流切換 GPU，會慢；開關旁標示預估等待）。
8. **紀錄**：`var/asr/log.jsonl` 只記音長、耗時、字數，不記音檔與辨識文字；辨識文字只在對話裡（照一般軌跡規則）。
9. **文件**：`docs/licenses.md` 登記 `breeze-asr-25`；`docs/capabilities.toml` 登記 `asr`；`docs/clients.md` 說明 Hermes 語音輸入設定。

## Non-Goals / 非目標

- 即時串流辨識（邊說邊出字）：先做錄完再辨識。
- 說話者分離（diarization）、台語／客語辨識。
- 用辨識結果當訓練資料（R20.3：未經驗證不收）。
- 錄音常駐監聽或喚醒詞。

## Impact / 影響

- 新規格 `asr`；修改 supervisor（GPU 三方輪流）、gateway（新端點）、桌面網頁（麥克風、語音對話）。
- 磁碟約 3 GB；不新增 Python 套件。
- 語音對話每輪：ASR 載入（首次數十秒）→ 卸載 → 核心載入 → 卸載 → TTS 載入（約 70 秒）；連續對話時會明顯變慢，之後可量測決定要不要讓 ASR 改走 CPU。

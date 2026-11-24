# add-tts 提案 / Proposal

> **狀態 / Status**：提案（2026-11-24，主控）。使用者 2026-11-24 要求加入 BlueMagpie-TTS；查證後決定 Q1「只自己用」（權重授權不明，限個人研究評估、不商用、不散布）、Q2「和核心輪流用顯示卡」。同日使用者要求四項修改：換預設語者、開放聲音複製、芥子自己會唸回答、放寬字數與輸出格式（本版已納入）；不向作者開 issue；同意白天下載。

## Why / 為什麼

芥子目前沒有語音輸出。Hermes 的 `text_to_speech` 工具與 OpenAI 相容客戶端都能接 `/v1/audio/speech`，但芥子沒有這個端點。BlueMagpie-TTS（OpenFormosa）專為台灣華語與中英夾雜設計，48 kHz 輸出，CER 7.4%，正好補上台灣口音的語音合成。

Jiezi has no speech output. BlueMagpie-TTS targets Taiwan Mandarin and code-switching, which fits the project.

## 查證結果 / Due diligence（AGENTS.md：先查現成方案、再資安掃描）

| 項目 | 結果 |
|---|---|
| 程式授權 | Apache-2.0（BlueMagpie-TTS `210e8a8`、相依 Barbet `e453176`、內含 VoxCPM 程式 Apache-2.0） |
| 權重授權 | ⚠️ HF 標 `license: other`，模型卡寫「for research and evaluation」、未經授權不得散布權重或合成語音；**沒有明確條款** → 登記為「僅個人研究評估、不商用、不散布、不做訓練資料」，並向作者詢問 |
| 資安掃描 | `torch.load` 全部 `weights_only=True`；`pickle.load` 只在 Apple MLX 快取路徑（Linux 不走）；除 HF 下載外沒有網路呼叫；沒有 `trust_remote_code` |
| 雙重用途 | 支援聲音複製（3 秒參考音檔）→ 依使用者要求開放，但**只能由使用者在本機 CLI 登錄**、必須填同意聲明；模型、代理與 API 都不能登錄新聲音 |
| 內附語者 | 只有 `hung_yi_lee`（李宏毅老師，已取得本人授權）與 `female_voice`（通用女聲）→ 預設改為 `female_voice` |
| 複製方式 | 用模型內建的 `reference_wav_path`（CER 8.99%），**不裝 speechbrain**（其 hyperpyyaml 載入時可建立任意物件，風險較高） |
| 資源 | 權重 fp32 7.8 GB＋AudioVAE 0.38 GB；CUDA 上以 bf16 執行約 4 GB；需 Python 3.10–3.12（芥子 venv 為 3.13） |
| 硬體 | RTX 4050 6 GB 已被核心占 5.3 GB → 兩者不能同時在 GPU，依 Q2 輪流使用 |

## What Changes / 變更內容

1. **獨立執行環境**：`scripts/jiezi tts setup` 用 uv 建 `var/tts/venv`（Python 3.11），安裝鎖定 commit 的 BlueMagpie-TTS 與 Barbet、CUDA 版 torch、soundfile；下載鎖定 revision 的權重到 `models/bluemagpie-tts/`，逐檔核對 sha256。芥子主 venv 不動。
2. **TTS 工作行程**：`src/jiezi/tts/worker.py` 在獨立 venv 裡執行，經 stdin/stdout 一行一個 JSON 溝通（不開連接埠）；載入一次、可連續合成，閒置 120 秒自動結束以歸還 GPU。
3. **GPU 輪流使用**：supervisor 增加「GPU 使用者」概念（`core` 或 `tts`）。TTS 請求等核心手上的請求做完（`in_flight == 0`）→ 卸載核心 → 啟動 TTS；之後的聊天請求先結束閒置中的 TTS 再載入核心。同一時間只有一方在 GPU。
4. **OpenAI 相容端點**：`POST /v1/audio/speech`（`model`、`input`、`voice`、`response_format` ∈ wav／mp3／flac／opus，`speed` 0.5–2.0），需 gateway 金鑰；`voice` 只能是內附語者或已登錄的聲音，預設 `female_voice`；`GET /v1/audio/voices` 列出可用聲音。長文依標點分段合成、段間加停頓後接起來，上限 20,000 字。mp3／opus 由系統 ffmpeg 轉檔。
5. **聲音複製（只能在本機登錄）**：`scripts/jiezi tts voice add <名稱> <參考音檔> --consent "<誰、何時同意>"`；音檔需 3–60 秒，轉成 16 kHz 單聲道存 `var/tts/voices/`，登錄表記同意聲明、時間、音檔 sha256；`voice list`／`voice remove`。API 與代理工具**不能**登錄或上傳參考音檔；用複製聲音合成的檔案在軌跡標記 `cloned: true`。
6. **安全與授權限制**：`JIEZI_TTS=on` 才啟用（預設關）；合成的音檔只存在本機 `var/tts/out/`（7 天清除）；軌跡記錄字數、語者、耗時，不記音檔與文字內容；權重、參考音檔與合成音檔都不得進版控或散布；不作訓練資料。
7. **芥子自己唸回答**：桌面網頁每則回答加「朗讀」按鈕（呼叫 `/v1/audio/speech`，瀏覽器播放）；`jiezi chat --speak` 把回答合成後存檔並印出路徑。朗讀前先去掉 Markdown、程式碼區塊與【記憶】等附註。
8. **狀態頁**：`/health` 與狀態頁顯示 TTS 是否啟用、目前 GPU 由誰使用。
9. **文件**：`docs/licenses.md` 登記 `bluemagpie-tts`；`docs/clients.md` 說明 Hermes 如何設定語音輸出。

## Non-Goals / 非目標

- 經 API、代理或網頁上傳參考音檔登錄聲音（只能本機 CLI）。
- 用 speechbrain 抽語者向量（多一個高風險相依；參考音檔路徑已足夠）。
- 邊合成邊播放的串流輸出（先做整段合成；長文分段後一次回傳）。
- 語音辨識（STT）。
- 商用或對外散布合成語音。

## Impact / 影響

- 新規格 `tts`；修改 supervisor（GPU 輪流）與 gateway（新端點）。
- 磁碟：權重約 8.2 GB（使用者同意白天下載）、獨立 venv 約 5–6 GB（CUDA torch）。
- 朗讀期間核心不能回答（請求會等 TTS 閒置結束或改轉交雲端）；切換一次約需數十秒載入。
- 安裝要下載 GB 級的 torch 與權重：依 R18.2a 在 00:00–07:00 進行，或使用者同意白天下載。

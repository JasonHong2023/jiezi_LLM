# add-tts 任務 / Tasks

## 1. 授權與環境 / License and environment

- [ ] 1.1 `docs/licenses.md` 登記 `bluemagpie-tts`（程式 Apache-2.0；權重 HF `license: other`、僅個人研究評估、不商用、不散布、不訓練；查證依據與日期）；使用者 2026-11-24 決定不向作者開 issue
- [ ] 1.2 `scripts/jiezi tts setup`：uv 建 `var/tts/venv`（Python 3.11），安裝鎖定 commit 的 BlueMagpie-TTS／Barbet、torch（CUDA）、soundfile；權重鎖 HF revision `4c2c5bcb…`，逐檔 sha256 核對後放 `models/bluemagpie-tts/`
- [ ] 1.3 冒煙測試：worker 單獨在 GPU 合成一句，量 VRAM 峰值、耗時、RTF

## 2. 工作行程與 GPU 輪流 / Worker and GPU sharing

- [ ] 2.1 `src/jiezi/tts/worker.py`：stdin/stdout JSON 行協定（synthesize／ping／quit），語者為內附 id 或已登錄聲音的本機音檔路徑（由 gateway 解析，worker 不接受任意路徑以外的輸入）；長文分段＋段間停頓；閒置 120 秒自動結束
- [ ] 2.2 `src/jiezi/tts/client.py`：啟動、等待就緒、逾時、當機回報
- [ ] 2.3 supervisor GPU 輪流：TTS 請求等核心 `in_flight == 0` → 卸載核心 → 啟動 worker；聊天請求先結束閒置 worker 再載入核心；評測保留（held）期間 TTS 也拒絕
- [ ] 2.4 測試（假 worker）：輪流順序、核心忙碌時等待、worker 當機、逾時、held 時拒絕

## 3. 端點與安全 / Endpoint and safety

- [ ] 3.0 聲音登錄 CLI：`scripts/jiezi tts voice add|list|remove`，必填 `--consent`，3–60 秒，轉 16 kHz 單聲道存 `var/tts/voices/`，登錄表記同意聲明與 sha256
- [ ] 3.1 `POST /v1/audio/speech`（OpenAI 相容）＋`GET /v1/audio/voices`：金鑰、`JIEZI_TTS=on`、字數上限 20,000、voice 白名單（內附＋已登錄，預設 female_voice）、wav／mp3／flac／opus、speed 0.5–2.0；音檔存 `var/tts/out/`（7 天清除）；軌跡只記中繼資料
- [ ] 3.2 `/health`、狀態頁顯示 TTS 開關與 GPU 使用者
- [ ] 3.3 測試：未啟用回 404／未授權 401／超長 400／未知語者 400／請求帶參考音檔 400／登錄缺同意聲明拒絕／分段與格式轉換
- [ ] 3.4 芥子唸回答：桌面網頁「朗讀」按鈕、`jiezi chat --speak`；朗讀前去掉 Markdown、程式碼區塊與【記憶】附註（含測試）

## 4. 實測與文件 / Live test and docs

- [ ] 4.1 實機：gateway 合成 3 句（純中文、中英夾雜、數字日期）＋一段約 1,000 字長文＋一個使用者自己登錄的聲音，使用者試聽；量切換耗時（核心→TTS→核心）
- [ ] 4.2 Hermes 設定 `text_to_speech` 指向芥子，實測一次
- [ ] 4.3 `docs/clients.md` 語音輸出說明；dev-plan、HANDOFF、當日紀錄

## 5. 驗證 / Validation

- [ ] 5.1 `openspec validate add-tts --strict`、`openspec validate --all --strict`、全量 unittest、`git diff --check`

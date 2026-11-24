# add-sound-effects 工作 / Tasks

## 1. 環境 / Environment

- [ ] 1.1 `scripts/jiezi sfx setup`：uv 建 `var/sfx/venv`（Python 3.11），安裝鎖定 commit `7a7f7c5` 的 earshot 基本相依；重跑時沿用
- [ ] 1.2 `.gitignore` 加 `var/sfx/`（已在 var/ 之下則確認）；`docs/licenses.md` 登記 earshot（MIT、素材 CC0）

## 2. 工作行程與管理 / Worker and manager

- [ ] 2.1 `src/jiezi/sfx/worker.py`：stdin/stdout JSON lines（ping、make、quit）；只寫 `var/sfx/out/` 內的路徑；清除 GEMINI/GOOGLE 金鑰環境變數；閒置自動結束
- [ ] 2.2 `src/jiezi/sfx/manager.py`：啟動與重用工作行程、逾時、錯誤訊息；7 天清除；`var/sfx/log.jsonl` 只記中繼資料
- [ ] 2.3 `src/jiezi/sfx/words.py`：常用中文聲音對照；其他中文描述用本機模型翻成英文；聲音編號直接使用
- [ ] 2.4 假工作行程（tests/fixtures）與單元測試：路徑限制、對照、逾時、閒置結束

## 3. 端點與混音 / Endpoints and mixing

- [ ] 3.1 `POST /v1/audio/sfx`、`GET /v1/audio/sfx/presets`（需金鑰；`JIEZI_SFX=on` 才啟用）
- [ ] 3.2 `/v1/audio/speech` 加 `jiezi_background`、`jiezi_background_volume`：背景依人聲長度產生，淡入淡出、人聲出現時壓低背景（ffmpeg sidechaincompress）
- [ ] 3.3 `/health` 加 `sfx` 欄位；單元測試（端點、混音參數、未啟用時 404）

## 4. 指令列與介面 / CLI and UI

- [ ] 4.1 `scripts/jiezi sfx "<描述>" -o … --duration --n`、`sfx presets`；`tts say --background`
- [ ] 4.2 桌面網頁：設定「朗讀背景音」、音效面板（輸入描述 → 播放／下載）；test_ui 規則通過

## 5. 驗證 / Validation

- [ ] 5.1 實機：中文與英文描述各 10 個音效人工試聽；朗讀加 3 種背景試聽（音量、壓低是否自然）
- [ ] 5.2 `openspec validate add-sound-effects --strict`、`--all --strict`、全量 unittest（看 exit code）、`git diff --check`、`capabilities check`
- [ ] 5.3 `docs/clients.md`、`docs/capabilities.toml`、README 特色更新

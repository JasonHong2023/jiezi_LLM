# add-sound-effects 提案 / Proposal

> **狀態 / Status**：提案（2026-11-25，主控）。使用者 2026-11-24 要求加入 earshot（github.com/Leonxlnx/earshot），三項都要：更多說話聲音、音效工具、朗讀加背景音效。查證後 earshot 是**音效產生器、不會說話**（README Limits：「It makes no speech, singing or melodies」），所以「更多說話聲音」由 add-tts 的聲音複製＋語速／音高處理，本提案只做後兩項。

## Why / 為什麼

芥子現在能說話（add-tts），但沒有音效：做簡報、短片或網頁時要找門聲、雨聲、提示音只能上網找素材，還要查授權。朗讀長文也只有乾乾的人聲。earshot 在 CPU 上即時合成 922 種音效（介面、生活、環境、遊戲、電影），素材全是公有領域，輸出的檔案可任意使用，正好補上這兩項。

Jiezi can speak but has no sound effects. earshot synthesizes 922 effects on the CPU from public-domain material; its output is free to use. It fills the gap for a sound tool and for ambience under read-aloud.

## 查證結果 / Due diligence（AGENTS.md：先查現成方案、再資安掃描）

| 項目 | 結果 |
|---|---|
| 版本 | earshot 1.0.0，commit `7a7f7c5`（2026-11-20），131 個 Python 檔、約 6.4 萬行 |
| 程式授權 | MIT |
| 素材授權 | 學到的聲音來自 CC0／公有領域錄音（BigSoundBank、Kenney、VCSL、VSCO-2 CE、Karoryfer、Freesound CC0），每筆在 `CREDITS.md` 有記錄；**產生的音效屬於產生者，可商用、免標示** |
| 硬體 | 只用 CPU，**不用 GPU** → 不必和核心、TTS、ASR 輪流 |
| 相依 | 基本安裝只有 numpy、scipy、soundfile、soxr、numba（約 350 MB），**不帶模型、合成時不下載任何東西** |
| 不安裝的額外套件 | `listen`（torch＋CLAP／AST 模型，會從 HF 下載）、`llm`（會把資料送到 Google Gemini）、`mcp`、`images` → 都不裝 |
| 能力限制 | 請求用英文描述效果最好；不會說話、唱歌或做旋律；描述心情不如直接說出聲音名稱 |

## 分類、現成方案搜尋、資安掃描 / Classification, existing-solution search, security scan

- 分類 / Classification：**核心模組＋獨立工作行程**，不是 `SKILL`，也不是 `MCP`。理由：要接在 gateway 的端點（音效 API、朗讀混音）與桌面網頁上，客戶端照一般 HTTP 呼叫即可；earshot 自帶的 MCP 伺服器要另裝 `mcp` 套件，而且會開放「聽音檔」等需要模型的工具，本提案不用。earshot 自帶的 Claude skill（`skills/earshot`）是教代理怎麼呼叫 earshot 指令，芥子直接用 Python API，不需要。
- 現成方案搜尋 / Existing-solution search（2026-11-24／25 主控查證）：
  1. **earshot**（使用者指定）：CPU、即時合成、素材 CC0、MIT。
  2. 文字轉音效模型（AudioLDM 2、Stable Audio Open 等）：要 GPU 數 GB、權重授權各有限制（Stable Audio Open 為社群授權），會和核心搶 GPU → 不採用。
  3. 現成音效素材庫（Freesound 等）：要逐筆查授權、要連網 → 不採用。
  4. 芥子現有：無音效功能；TTS 已有 ffmpeg 後處理（語速、音高），混音可沿用。
- 資安掃描 / Security scan（commit `7a7f7c5`）：
  - 網路：基本功能沒有網路呼叫；`requests` 只在 `earshot/llm.py`（Gemini，需環境變數 `GEMINI_API_KEY` 且呼叫者同意才開），不安裝 `llm` 額外套件，工作行程也清除 `GEMINI_API_KEY`／`GOOGLE_API_KEY` 環境變數。
  - 外部程式：`subprocess` 只呼叫 `ffmpeg`／`ffprobe`，用參數清單（不經 shell）。
  - 反序列化：`np.load` 全部 `allow_pickle=False`；沒有 `eval`／`exec`／`pickle.load`。
  - 模型下載：只在 `listen` 額外套件（CLAP、AST）才有，不安裝。
  - 隔離：裝在獨立 venv `var/sfx/venv`，鎖 commit `7a7f7c5`，與芥子主環境分開；工作行程只能把檔案寫進 `var/sfx/out/`。
  - 結論：**無重大問題**，可直接加入。

## What Changes / 變更內容

1. **獨立執行環境**：`scripts/jiezi sfx setup` 用 uv 建 `var/sfx/venv`（Python 3.11），從 GitHub 安裝鎖定 commit `7a7f7c5` 的 earshot（只裝基本相依）。芥子主 venv 不動。
2. **音效工作行程**：`src/jiezi/sfx/worker.py` 在獨立 venv 執行，用 stdin/stdout 一行一個 JSON 溝通（不開連接埠），閒置 120 秒自動結束。只接受 `make` 一種動作，輸出路徑由芥子指定、必須在 `var/sfx/out/` 內。
3. **中文描述**：
   - 常用聲音內建中英對照，例如雨聲、海浪、營火、咖啡廳、森林、敲門、腳步、鍵盤、提示音。
   - 其他中文描述用本機模型翻成簡短英文，再交給 earshot。
   - 也可以直接給 earshot 的聲音編號，例如 `rain/window`。
   - 回應會附上 earshot 選中的聲音和原因，讓使用者知道它理解成什麼。
4. **音效 API**：`POST /v1/audio/sfx`，需要 gateway 金鑰。
   - 參數：`input`（描述）或 `sound`（聲音編號）、`duration`（0.1–60 秒）、`n`（1–4 個版本）、`response_format`（wav／mp3／flac／ogg）。
   - 回傳音檔，標頭附上選中的聲音編號。
   - `GET /v1/audio/sfx/presets` 列出朗讀背景可選的環境聲。
5. **朗讀加背景音效**：`/v1/audio/speech` 多一個選填欄位 `jiezi_background`。
   - 可選：`rain`（雨打窗戶）、`rain_roof`（鐵皮屋頂）、`forest`（森林早晨）、`waves`（沙灘海浪）、`fire`（營火）、`cafe`（咖啡廳）、`warm`（輕柔背景墊）。
   - 另有 `jiezi_background_volume`（預設 -20 dB，可調 -40～-6）。
   - 背景長度依人聲長度產生（earshot 的環境聲可無縫循環），頭尾淡入淡出，人聲出現時自動壓低背景（ffmpeg sidechain）。
   - 不帶這個欄位時，行為和現在一樣。
6. **指令列**：
   - `scripts/jiezi sfx "敲三下門" -o knock.wav [--duration 2] [--n 3]`
   - `scripts/jiezi sfx presets`
   - `scripts/jiezi tts say … --background rain`
7. **桌面網頁**：設定分頁加「朗讀背景音」下拉選單（預設無），朗讀按鈕和語音對話都套用。另加一個小的「音效」面板：輸入描述 → 播放／下載。
8. **紀錄與清理**：輸出存 `var/sfx/out/`，7 天清除；紀錄 `var/sfx/log.jsonl` 只記描述字數、選中的聲音、耗時。`JIEZI_SFX=on` 才啟用（預設關）。
9. **文件**：`docs/licenses.md` 登記 earshot（MIT、素材 CC0）；`docs/clients.md` 加音效與背景音說明；`docs/capabilities.toml` 加 `sfx`。

## Non-Goals / 非目標

- 更多說話聲音（earshot 不會說話；由 add-tts 的聲音複製、語速、音高處理）。
- earshot 的「聽音檔」功能（describe、match、critique；要下載 CLAP／AST 模型）。
- earshot 的 Gemini 評論功能（會把資料送到雲端）。
- earshot 的 MCP 伺服器與 Claude skill。
- 配樂或旋律（earshot 不做音樂，只有 3 個短背景墊）。
- 邊合成邊播放的串流輸出。

## Impact / 影響

- 新規格 `sound-effects`；修改 `tts` 的朗讀端點（加選填背景欄位）。
- 磁碟：獨立 venv 約 350–500 MB；不下載模型。
- CPU：一個音效約 0.1–數秒；背景長度跟人聲一樣，長文朗讀多幾秒混音時間。不占 GPU。
- 中文描述翻譯會用到本機模型一次（短句），若 GPU 正被 TTS／ASR 使用，會照現有輪流規則等待；用內建對照或聲音編號則不需要模型。

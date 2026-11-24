# 芥子 Jiezi

> **芥子納須彌**：一粒芥子容納整座須彌山。以極小的模型，加上系統能力，在一般筆電上做到接近商業模型的事。
>
> *A mustard seed holds Mount Sumeru* — a small local model plus system capabilities, running on laptop-class hardware.

芥子是一套**在自己電腦上跑的繁體中文 AI 助理系統**。核心是一個 4B 參數、4 bit 量化的本機模型（Qwen3.5-4B，經本專案三輪微調），外面包著檢索、驗證、工具、記憶、語音與分層轉交等系統能力；本機答不了的才請教 Claude 或雲端模型，並把常見的轉交逐步變成本機能力。

Jiezi is a **local-first Traditional Chinese AI assistant**. A 4B, 4-bit core model (Qwen3.5-4B fine-tuned in three rounds) is wrapped with retrieval, verification, tools, memory, speech and tiered escalation; only what the local model cannot handle goes to Claude or a cloud model.

---

## 特色 / Highlights

- **本機優先、分層轉交**：先由本機回答，經驗證器檢查；答不出來、檢查沒過才依序請教雲端或 Claude。轉交的原因會統計，常見的轉交再做成本機能力。
- **OpenAI 相容 API**：`/v1/chat/completions`、`/v1/embeddings`、`/v1/audio/speech`、`/v1/audio/transcriptions`。Hermes Agent、OpenCode 等客戶端直接把網址指過來就能用。
- **台灣在地資料**：教育部國語、台語、客語辭典，108 課綱知識圖譜，全國法規資料庫，台灣知識庫，全部在本機查詢。
- **工具呼叫**：計算、單位換算、日期與國定假日由程式算好；客戶端帶幾十上百個工具時自動篩選，放得進本機的上下文。
- **文件與網頁**：PDF、Word、PowerPoint、Excel、網頁讀成文字附上，長文件分段摘要；可疑的提示注入會標示並隔離。
- **語音**：BlueMagpie-TTS 朗讀（台灣口音、中英夾雜）、Breeze-ASR-25 語音辨識與字幕；桌面網頁可以按住說話、語音對話。核心、TTS、ASR 輪流使用顯示卡。
- **代理（Agent）**：唯讀檔案代理（只能讀使用者授權的資料夾）；唯一的寫入工具只能建立新檔，而且每次都要使用者看過內容、回填雜湊值核准。
- **記憶與自我進化**：請教過的答案存成本機記憶；驗證過的資料累積成訓練集，夜間做 LoRA 微調，過了回歸關卡才交由使用者決定換核心。
- **安全與信任**：所有服務只綁 `127.0.0.1`；外部內容與雲端回答帶信任等級，Claude 與雲端的回答一律不進訓練資料；金鑰只放 `.env`。

## 架構 / Architecture

```
 客戶端：jiezi ask / chat（Textual）、桌面網頁（React）、Hermes、OpenCode
            │  OpenAI 相容 API（127.0.0.1:36100）
            ▼
 ┌──────────────────────── gateway ────────────────────────┐
 │ 工具篩選 · 文件／網頁 · 辭典／課綱／法規／知識庫 · 記憶        │
 │ 本機回答 → 驗證器 → 本機階梯（重試、思考、工具） → 轉交        │
 │ 信任把關 · 觀測統計 · 軌跡紀錄 · 代理（唯讀＋核准寫入）        │
 └─────────────┬──────────────────────────┬────────────────┘
               ▼                          ▼
  supervisor：GPU 輪流              轉交：雲端模型（LiteLLM）
  ├ llama.cpp 核心模型                    → Claude（最後手段）
  ├ BlueMagpie-TTS（獨立 venv）
  └ Breeze-ASR-25（獨立 venv）
```

## 目前成果 / Status

開發機目前的核心 `qwen3.5-4b-r3`（第 3 輪 SFT，強化工具呼叫，本機訓練）在 E0 評測（每項 25–50 題、貪婪解碼）：

| 項目 | 原版 Qwen3.5-4B Q4_K_M | 芥子 r3 |
|---|---|---|
| 工具呼叫（ACEBench-zh） | 60% | **66%** |
| 程式（HumanEval+／MBPP+） | 68%／64% | **76%**／60% |
| 中文知識（C-Eval／CMMLU） | 80%／76% | 72%／76% |
| 速度（RTX 4050 Laptop 6 GB） | 43 t/s | 45 t/s |

- 開發機：RTX 4050 Laptop（6 GB）、31 GB RAM、WSL2 Ubuntu。
- 924 個單元測試；規格以 [OpenSpec](https://github.com/Fission-AI/OpenSpec) 管理（`openspec/specs/`）。
- 開發中：看圖工具評測、音效工具（earshot）、更多本機能力取代轉交。

## 快速開始 / Quick start

需求：Linux 或 WSL2、[uv](https://docs.astral.sh/uv/)、git、C/C++ 編譯器。有 NVIDIA 顯示卡會自動使用，沒有也能用純 CPU 跑。

```bash
git clone https://github.com/JasonHong2023/jiezi_LLM.git
cd jiezi_LLM
scripts/bootstrap          # 偵測硬體、建置 llama.cpp、下載冒煙測試用的小模型（Qwen3-0.6B，核對 sha256）、產生 .env 與 gateway 金鑰
scripts/jiezi start        # 背景啟動 gateway（127.0.0.1:36100）
scripts/jiezi ask "台北到高雄高鐵大約多久？"
scripts/jiezi chat         # 全螢幕對話
scripts/jiezi doctor       # 檢查每個元件，告訴你怎麼修
```

bootstrap 預設的核心是 0.6B 小模型，用來確認整套流程能跑。建議改用 4B 核心（約 2.6 GB）：

```bash
curl -L -o models/Qwen3.5-4B-Q4_K_M.gguf \
  https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q4_K_M.gguf
sha256sum models/Qwen3.5-4B-Q4_K_M.gguf   # 應為 00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4
echo "JIEZI_CORE_MODEL=qwen3.5-4b-q4_k_m" >> .env && scripts/jiezi stop && scripts/jiezi start
```

微調過的 `qwen3.5-4b-r3` 是在本機訓練產生的（`scripts/jiezi train`，見 [`docs/training-guide.md`](docs/training-guide.md)），權重沒有公開發佈。

桌面網頁：`scripts/jiezi ui build` 後開 `http://127.0.0.1:36100/ui/`，貼上 `.env` 裡的 `JIEZI_GATEWAY_KEY`。

語音（選用，需下載約 11 GB）：

```bash
scripts/jiezi tts setup    # 獨立 Python 3.11 環境 + BlueMagpie-TTS 權重
scripts/jiezi asr setup    # Breeze-ASR-25 權重
# .env 加 JIEZI_TTS=on、JIEZI_ASR=on，重啟 gateway
scripts/jiezi tts say "你好，我是芥子。" --voice female_voice
scripts/jiezi asr meeting.m4a --srt -o meeting.srt
```

### 策略 / Policies

| 模型名稱 | 行為 |
|---|---|
| `jiezi` | 本機優先，必要時轉交（預設） |
| `jiezi-local` | 只用本機，絕不轉交 |
| `jiezi-ask-claude` | 直接請教 Claude（本機 Claude Code CLI） |

客戶端設定（Hermes、OpenCode）見 [`docs/clients.md`](docs/clients.md)。

## 文件 / Documentation

| 文件 | 內容 |
|---|---|
| [`docs/clients.md`](docs/clients.md) | 使用方式：CLI、桌面網頁、Hermes／OpenCode 設定、各項功能開關 |
| [`docs/dev-plan.md`](docs/dev-plan.md) | 開發計畫、決策、階段與量測紀錄 |
| [`docs/design-principles.md`](docs/design-principles.md) | 設計原則與「向強者學」的老師階梯 |
| [`docs/licenses.md`](docs/licenses.md) | 所有模型、資料集與第三方資料的授權登記 |
| [`docs/training-guide.md`](docs/training-guide.md) | 訓練資料與 LoRA 微調流程 |
| [`openspec/specs/`](openspec/specs/) | 系統行為規格（真實來源） |

## 授權與使用限制 / License and usage

- 本專案目前為**研究與個人用途**，尚未選定開源授權條款。
- 依賴的模型、資料集各有授權，部分**禁止商用**（例如 C-Eval、CMMLU 為 CC BY-NC-SA），BlueMagpie-TTS 的權重授權未明、只限個人研究評估。使用前請看 [`docs/licenses.md`](docs/licenses.md)。
- 模型權重、資料與執行紀錄不放在 repo 裡，由 `scripts/bootstrap` 與各 `setup` 指令依登記的版本與 sha256 下載。
- 聲音複製只能由使用者在本機登錄、並附上當事人的同意聲明；請勿用來模仿未經同意的人。

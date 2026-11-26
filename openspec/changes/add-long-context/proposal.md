# add-long-context：本機長上下文，讓 Hermes 等代理程式由本機回答 / Long local context so agent clients stay local

> **狀態 / Status**：2026-11-26 主控提出，使用者「照擬計畫的進行」→ 已實作（85d7512）；2026-11-27 夜間量測同工具 0.385 未達 OQ1 的 0.60 → 預設關、保留開關。起因：使用者要芥子透過 Hermes 讀 MD 寫入 WIKI，發現 Hermes 每輪都被轉到雲端；使用者：「這就不對 希望還是本機能處理」。
> Proposed 2026-11-26 after the user found every Hermes turn going to the cloud and asked for local handling.

## Why / 為什麼

- 引擎現在是 `-c 16384 -np 4`：4 個槽位各 **4096 token**。gateway 也以 `SLOT_CTX = 4096` 裁切與判斷。
- Hermes（Windows 桌面版）一個請求：系統提示約 1.3 萬字、19 個工具約 3.4 萬字。工具篩選把工具從 19 個篩到 12 個以後，仍約 **19,136 token**。
  - 所以 `context_too_large` 讓**每一輪都轉雲端**（minimax-m3.1-flash）。
  - 2026-11-26 一個任務累積到約 12.9 萬 token，全程沒有一輪是芥子回答的，芥子學不到，還一直用掉雲端額度。
- Hermes 設定 `model.context_length: 200000`，以為芥子能吃 20 萬 token，所以從不壓縮對話。
- 模型本身做得到：Qwen3.5-4B 原生上下文 262,144。它是混合架構，每 4 層才 1 層全注意力，共約 8 層、4 個 KV 頭、維度 256，每 token 的 KV 約 32 KiB（f16），比一般 4B 小很多。
  - 現在 16,384 token 的 KV 約 512 MiB。
  - 改成 q8_0 KV 時，32,768 token 也約 512 MiB，**VRAM 不增加**（目前 5.5／6.1 GB）。
- 速度：本機實測預填約 1,400–2,400 token／秒。19k token 的首輪約 10–15 秒；之後各輪靠 prompt cache 只算新增的部分。

## 分類、現成方案搜尋、資安掃描 / Classification, existing-solution search, security scan

**分類**：既有引擎參數與 gateway 上下文預算的調整；不是新 SKILL 或 MCP，不新增套件、模型或連線。

**現成方案**：llama.cpp 內建 `--kv-unified`（所有槽位共用一個 KV 池，單一請求可用到整個 `-c`）與 `-ctk/-ctv q8_0`（KV 量化，需 flash attention，CUDA 版預設 auto）。這是 b12556（目前鎖定版）已有的功能，不另找方案。Hermes 端只改它自己的 `context_length` 設定，讓它在到達本機上限前自行壓縮對話（Hermes 內建功能）。

**資安掃描**：
- 不新增依賴，不改連線範圍（仍只綁 127.0.0.1）。
- 長上下文代表一次可放更多外部資料，提示注入的面變大。沿用既有【文件】包框、injection-guard 與工具篩選；工具呼叫仍經既有核准（agent-approval）。
- 共用 KV 池在多個長請求同時進來時可能不夠用。gateway 同時只放行 **1 個長請求**（超過 4096 的），其餘排隊或照舊轉雲端，避免引擎把別的槽位擠掉。
- Hermes 的 `config.yaml` 由使用者改，或使用者同意後由主控改（先備份）；主控不碰它的 `.env`。

## What Changes / 變更內容

1. **引擎**：`-c 32768 -np 4 --kv-unified -ctk q8_0 -ctv q8_0`。
   - 4 個槽位共用 32k；一般對話照舊只用少量。
   - 量測若 VRAM 不夠或品質掉，退到 24,576。
2. **gateway 上下文預算分兩級**：
   - 一般對話仍以 4096 裁切（維持速度與既有行為）。
   - 帶工具的代理程式請求（Hermes、OpenCode 等）預算改為 `JIEZI_AGENT_CTX`（預設 30,000，保留回答空間），超過才走既有工具篩選與轉雲端。
   - 同時只放行 1 個長請求。
3. **Hermes 端**：`model.context_length` 從 200000 改成約 30000，讓 Hermes 在接近本機上限時自己壓縮對話，不再一路長到 13 萬。
4. **品質把關**：本機回的工具呼叫若 JSON 壞掉、工具名不在清單、或參數不符 schema，沿用既有階梯先重試一次，再轉雲端（雲端仍是最後手段）。
5. **量測（夜間）**：重放 2026-11-26 的 Hermes 請求（約 100 筆，皆有雲端答案可對照），本機只回不執行，量：
   - 工具呼叫合法率
   - 與雲端選同一個工具的比例
   - 首 token 秒數
   - VRAM 峰值

## Open questions / 待決定

- **OQ1 開啟條件**：提議量測結果工具呼叫合法率 ≥ 85%、與雲端選同工具 ≥ 60%、首輪 ≤ 20 秒，才預設讓代理程式請求走本機；達不到就保留開關，預設維持轉雲端（R20）。
- **OQ2 Hermes 設定**：`context_length` 改 30000，由使用者自己改，或同意後主控改。
- **OQ3 一般對話是否也放寬**：提議**不放寬**。一般問答 4096 已夠，放寬只會變慢，長文件已有 longdoc 分段。

## Non-Goals / 非目標

- 不換核心模型，不改 `-np 4`。
- 不處理 Hermes 自己的 bug，例如它在 Windows 跑 `execute_code` 時路徑錯誤（另見 wiki-ingest 提案）。
- 不保證 4B 在長代理任務上和雲端一樣好；本提案只讓它**先試本機、有把握才用**。

## Impact / 影響

- 程式：`src/jiezi/runtime/__main__.py`（引擎參數）、`context.py`（預算可設定）、`gateway.py`（代理請求預算、長請求一次一個）、`settings.py`（`JIEZI_AGENT_CTX`）、doctor 顯示。
- 規格：gateway 新增需求；client-tool-filter 的「放不下」條件改看代理預算。
- 評測：新增 `src/jiezi/eval/agent_replay.py` 與夜間腳本。
- 文件：`docs/clients.md` Hermes 一節加上 `context_length` 設定建議。

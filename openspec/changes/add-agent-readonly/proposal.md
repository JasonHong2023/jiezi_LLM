> **狀態 / Status**：使用者 2026-11-17 回覆「照建議，可以實作」；已實作，量測 2.1 另記。
> Approved 2026-11-17; implemented.

## Why

開發計畫 Phase 8 要讓芥子「動手」：8.1 是代理執行層（工具呼叫迴圈、權限、稽核），8.2 是唯讀工具。目前芥子只會回答；桌面 App 與 chat 都還不能請它「找出這個資料夾最大的檔案」「讀一下這份檔案再回答」。G5 的判準也要求：所有動作有稽核、一鍵中止 ≤ 1 秒。
Phase 8 lets Jiezi act: 8.1 the agent layer (tool loop, permissions, audit), 8.2 read-only tools. Today it only answers.

這個提案只做**第一步：唯讀的檔案工具**。視窗與畫面讀取、一般操作（開程式、點擊、輸入）留給之後的提案；高風險操作屬 Phase 9（R22.1）。
This proposal is the first step only: read-only file tools. Window and screen reading, ordinary operations and anything high-risk come later.

## What Changes

- **工具伺服器**（`src/jiezi/agent/tools_server.py`）：以 MCP 的 stdio 協定提供四個唯讀工具（R9：操控能力一律做成 MCP server，TUI 與 Desktop 共用，Hermes／OpenCode 也能直接接）：
  - `list_dir(path)`：列出資料夾（名稱、大小、修改時間、是不是資料夾；上限 500 項）
  - `find_files(root, pattern, sort)`：依檔名樣式找檔案，可依大小或時間排序（上限 200 項、深度 8）
  - `read_file(path)`：讀文字或文件（沿用 `documents.read`：PDF、Office、純文字；回傳前經防提示注入的清理，上限 20,000 字，超過就說明被截短）
  - `file_info(path)`：大小、時間、類型
  Four read-only tools over MCP stdio; `read_file` reuses the document readers and the injection cleaning.
- **授權（R22.2 最小權限）**：`var/agent/grants.toml` 列出允許的資料夾（預設**空的**——沒有授權就什麼都讀不到）；每次工具呼叫先把路徑解析成實際路徑（跟隨符號連結後）再比對，授權外一律拒絕；永遠拒絕的清單寫死在程式裡，不能用授權開啟：`.env`、`*.key`、`.ssh`、`.gnupg`、瀏覽器設定檔、專案的 `var/`。指令 `scripts/jiezi agent grant 資料夾`／`revoke`／`grants`。**模型與工具都不能改授權檔**（R22.5）：工具伺服器沒有寫入功能。
  Grants list allowed folders (empty by default); paths are resolved before matching; a hard-coded deny list (secrets, keys, browser profiles, the project's `var/`) cannot be granted; neither the model nor the tools can change grants.
- **代理迴圈**（gateway）：請求帶 `jiezi_agent: true`（chat 的 `/agent on`、桌面網頁的開關）時，gateway 把這四個工具交給模型，模型提出工具呼叫 → gateway 驗證 schema 與授權 → 執行 → 結果當「資料」放回對話（防提示注入照常：結果裡的指示不會被照做，也不能擴大授權，R22.7）→ 再問模型，最多 6 步（見 OQ3）。每一步都即時回報給客戶端（顯示「正在讀取 …」）。
  With `jiezi_agent: true` the gateway offers the tools, validates and authorizes each call, returns results as data, and loops up to six steps, reporting each step to the client.
- **稽核（R22.3）**：每個動作寫入 `var/agent/audit/YYYY-MM-DD.jsonl`（時間、工具、參數、結果摘要與大小、允許或拒絕及原因、軌跡 ID、第幾層）；不存檔案內容本身；桌面網頁的稽核頁與 `scripts/jiezi agent audit` 可查。不進版控。
- **一鍵中止（R22.4）**：客戶端中斷連線（chat 的 Ctrl+C、桌面網頁的 Esc／中止）時，迴圈在下一個檢查點停止並終止進行中的工具（目標 ≤ 1 秒，列入量測）。
- **誰來想**：工具呼叫由本機核心負責（走既有的平行取樣與 schema 驗證）；本機做不到時照既有分層轉交——但**轉交時不把檔案內容送出去**，除非使用者在授權檔對該資料夾標了 `share = true`（見 OQ2）。
- `JIEZI_AGENT`（預設 **off**）。代理請求的軌跡 `training_use=false`（內容是使用者的私人檔案）。

## Non-Goals

- 任何會改變東西的工具：寫檔、刪檔、搬移、開啟程式、點擊、輸入、剪貼簿、執行指令（8.3 與 Phase 9）。/ Any tool that changes anything.
- 視窗與 UI 結構讀取、截圖（8.2 的另一半；Windows 端要另外的元件）。/ Window, UI-tree and screenshot reading.
- Windows 檔案系統的特殊處理：WSL 裡以 `/mnt/c/...` 路徑授權即可讀；不另做 Windows 原生端。/ A native Windows side.
- 網路存取（聯外未開放）。/ Network access.

## Capabilities

### New Capabilities

- `agent`：唯讀工具、授權、代理迴圈、稽核、中止。/ Read-only tools, grants, the loop, audit, stop.

### Modified Capabilities

（無）/ (None)

## Impact

- **相依（見 OQ1）**：MCP 的 stdio 協定是一來一往的 JSON 訊息，唯讀工具只需要三種（初始化、列出工具、呼叫工具）。建議先用標準函式庫自己實作這個子集，不加新套件；之後工具變多再評估官方 `mcp` 套件（引入前依 R23 查證）。
- **[推論]** 能不能用，取決於核心的工具呼叫能力：0.6B 在 ACEBench 只有 34%，多步驟的代理迴圈很可能要等 G1 選定較大的核心才堪用。所以預設關閉，並把 G5 式的固定任務（「找出某資料夾最大的檔案」等 5 題）列為量測。
- 埠：不新增（工具伺服器是 gateway 啟動的子行程，走 stdio）。R12 流程圖要補上代理迴圈。

## Open Questions（需要使用者決定 / for the user）

- **OQ1 MCP 的實作**：(a) 用標準函式庫實作需要的子集、不加套件（建議）；(b) 現在就加官方 `mcp` 套件。
- **OQ2 轉交時的檔案內容**：本機答不出來而轉交 Claude／雲端時，(a) 預設不送檔案內容，只有授權檔標了 `share = true` 的資料夾才送（建議）；(b) 一律不送（代理請求只用本機）；(c) 一律可送。
- **OQ3 步數上限**：一個請求最多幾步工具呼叫？（建議 6。）
- **OQ4 預設授權**：一開始要不要預先授權某個資料夾（例如專案的 `docs/`），還是完全空白、由你自己 `grant`？（建議：空白。）

## 已決事項 / Resolved（使用者 2026-11-17）

- **OQ1**：標準函式庫實作 MCP 子集，不加套件。
- **OQ2**：使用者同意的說法是「轉交 Claude 時，讀到的檔案內容一律不送出，只送摘要」。實作上比原建議 (a) 更嚴：沒有 `share = true` 選項；代理只用本機模型，策略為 `jiezi-cloud`／`jiezi-ask-claude` 時回 400，本機引擎不能用時回 503，不轉交。稽核與回應只帶中繼資料（工具、路徑、字數），不帶內容。
- **OQ3**：每個請求最多 6 步（`JIEZI_AGENT_STEPS`，上限 12）。
- **OQ4**：預設不授權任何資料夾。

## 實作補記（R19.4）

- 授權檔改為 `var/agent/grants.json`（原寫 `grants.toml`）：標準函式庫只能讀 TOML、不能寫，而授權只由命令列寫入。
- 另加 `scripts/jiezi agent server`（MCP stdio 入口，給 Hermes／OpenCode 設定用）與 `GET /v1/agent/audit`（桌面網頁稽核頁用）。
- 禁止授權整個家目錄或它的上層。

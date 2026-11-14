# Project Context — 芥子（Jiezi）

> 芥子納須彌：以極小的模型容納極大的能力。
> A mustard seed holds Mount Sumeru — a tiny model holding vast capability.

## 專案名稱 / Name
芥子（Jiezi），程式代號 `jiezi`，repo `JasonHong2023/jiezi_LLM`。

## 目標 / Goal
在一般筆電等級的硬體上，組合 CPU / GPU / NPU，讓一個極度壓縮的核心模型加上系統能力（平行取樣、驗證器、檢索、技能庫、分層雲端轉交、自我進化），在中文問答、寫程式、文件摘要、工具呼叫四類任務上逼近商業模型。
Combine CPU / GPU / NPU on laptop-class hardware so that a heavily compressed core model plus system capabilities approaches commercial-model quality on Chinese QA, coding, document summarization, and tool calling.

## 權威文件 / Authoritative documents
| 文件 | 範圍 |
| --- | --- |
| `reference/rules_20261114.md` | 專案規則 R1–R23（**所有變更必須遵守**） |
| `openspec/specs/` | 系統行為的真實來源（R3） |
| `docs/dev-plan.md` | 階段、決策關卡、預算、時程（待遷入，R15 Q3） |

## 技術棧 / Stack（詳見規則 R9，鎖定版本見 `openspec/specs/stack.md`）
- 推論引擎：llama.cpp（vendored ggml），版本以 commit 鎖定
- 編排語言：Python（uv 管理）；硬體探測只用標準函式庫
- 建置：cmake + ninja（以 uv 安裝，不需 sudo）
- 客戶端：TUI / CLI = Python + Textual；Desktop = Tauri 2 + React（純前端 SPA）
- 工具介面：MCP
- **禁止**：PHP、任何有未修補重大資安問題的技術（R23）

## 架構原則 / Principles
1. 機器事實一律偵測、不假設；設定與機密放 `.env`（R21）。
2. 純 CPU + 不連雲端的最小路徑必須在每個支援平台跑通（R21）。
3. 資源不可占滿，預算由 `facts.json` 的 `budgets` 推導（R18）。
4. 量測只在條件完全相同時可比較，條件必須記錄（R17）。
5. 本機服務固定 port 區段 36100–36119，只綁 `127.0.0.1`（R11、R6.12）。

## 支援平台 / Support matrix（R21.2）
- 引擎：Linux x86_64（原生）、WSL2 —— 必須支援
- 客戶端：Windows 11 原生、Ubuntu —— 必須支援
- macOS（Apple Silicon）、Linux ARM64 —— 盡量支援

## 慣例 / Conventions
- 程式碼註解與 `openspec/changes/**` 文件：繁體中文 + 英文逐句並列（R1）
- Commit：`<type>(<capability>): <描述>`，中英各一行（R5）
- 機器產物（`facts.json`、`bench.json`、`plan.json`）、模型權重、`.env`、軌跡資料不進版控（R6.4）
- 證據標記：[實測] / [本機查證] / [原文] / [自算] / [推論] / [估] / ⚠️（R19）

## 現行階段 / Current phase
Phase 0（基礎整備）：0.2 CUDA 建置、0.3 三值格式驗證已在前身專案 `hetero-llm` 完成；本 repo 待遷入 hwprobe 並建立可攜性骨架（0.5）。

## 參考環境 / Reference environment（只是開發機，不得寫進程式；R21）
WSL2 Ubuntu 24.04；Intel i7-14700HX（WSL 顯示 14C/28T）；RAM 31 GiB；RTX 4050 Laptop 6 GiB；CUDA toolkit 13.3；llama.cpp `93cf736`。

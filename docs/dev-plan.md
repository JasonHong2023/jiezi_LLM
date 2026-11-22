# 芥子（Jiezi）開發計畫 v1.0：以最小硬體成本打造多功能通用模型系統

> 遷入自 / Migrated from `LLM_discussion/plans/dev-plan.md`（2026-11-15，規則 R15 Q3：複製到 `docs/`，原處保留唯讀）。之後以本檔為準 / This copy is authoritative from now on.

> **芥子納須彌**：一粒芥子容納整座須彌山，以極小的模型容納極大的能力。

| 項目 | 內容 |
| --- | --- |
| 版本 | v1.0（2026-11-14） |
| 專案名稱 | **芥子（Jiezi）**，程式代號 `jiezi`（2026-11-14 定案） |
| 狀態 | 草案，待使用者核准後開工 |
| 實作位置 | **新 repo（`~/projects/` 下另開資料夾 + GitHub，使用者建立中）**；`~/projects/hetero-llm` 的既有成果（hwprobe、budgets、測試、llama.cpp build）需遷入。每個階段對應一個 OpenSpec change，見 §13 |
| 依據文件 | [`littlebit-selfevolve.md`](design-principles.md)（設計原則 P1–P8、老師階梯）、[`hetero-runtime.md`](design/hetero-runtime.md)、[`hw-autoconfig.md`](design/hw-autoconfig.md)、[`../analysis/`](analysis/) 下 5 份分析（共 30 篇論文） |
| 標記 | **[實測]** 本機量測｜**[原文]** 論文數據｜**[推論]** 待驗證的判斷｜**[估]** 估算 |

---

## 1. 目標

**一句話**：在一般筆電等級的硬體上，組合 CPU / GPU / NPU，讓一個極度壓縮的核心模型加上系統能力（平行取樣、驗證器、檢索、技能庫、雲端轉交、自我進化），在指定任務上逼近商業模型的水準。

### 1.1 範圍
- **四類任務**（使用者指定）：中文問答、寫程式、文件摘要、工具呼叫。
- **必要元件**：本機信心不足時轉交雲端。
- **能力提升主軸**：自我進化，主幹是「向強者學」（老師階梯）。

### 1.2 非目標（第一版不做）
- 從頭預訓練基礎模型。
- 多使用者的高併發服務。
- 視覺、語音等多模態（Bonsai 2 系列雖有視覺版，列為後續選項）。
- 商用發佈（多項依賴資產授權禁止商用，見 §10）。

### 1.3 成功指標
基準值在 Phase 1 量測後回填；下表的目標是**初版提案**，Phase 2 結束後依實測修正。

| 指標 | 定義 | Phase 4 目標 | Phase 6 目標 |
| --- | --- | --- | --- |
| **達成率** | 本機系統分數 ÷ 雲端基準分數（四類任務分開算） | 工具呼叫、摘要 ≥ 80%；程式 ≥ 70% | 工具呼叫、摘要 ≥ 90%；程式 ≥ 80%；知識題（含 RAG）≥ 80% |
| **本機處理率** | 不需轉交雲端的請求比例 | ≥ 50% | ≥ 75% |
| **成本倍率** | 全部交給雲端的費用 ÷ 本系統費用 | ≥ 2× | ≥ 4× |
| **互動速度** | 單一請求第 0 層的生成速度 | ≥ 10 t/s | ≥ 15 t/s |
| **資源上限** | 不得超過**該台電腦** `facts.json` 的預算 | 開發機：RAM ≤ 12010 MiB、VRAM ≤ 4896 MiB | 同左 |
| **可攜性** | 在乾淨環境用 `scripts/bootstrap` 重建並通過冒煙測試（規則 R21） | Linux 原生 + WSL2 | + macOS 盡量支援 |

---

## 2. 已確立的決策

| # | 決策 | 日期 |
| --- | --- | --- |
| D1 | 推論引擎以 ggml / llama.cpp 為主；ORT 之後再評估 | 11-12 |
| D2 | 硬體資源不可占盡，保留量由 `facts.json` 的 `budgets` 推導 | 11-12 |
| D3 | 評測任務：中文問答、寫程式、文件摘要、工具呼叫 | 11-14 |
| D4 | 雲端轉交是必要元件 | 11-14 |
| D5 | 自我進化納入計畫；「向強者學」為主幹之一 | 11-14 |
| D6 | **核心壓縮形式由 Phase 2（E0）實測決定**；LittleBit 保留為研究路線 | 本計畫 |
| D7 | 老師階梯中，**用於訓練的老師只採用授權允許蒸餾的模型**；商業 API 只用於推論期轉交、評審與元智能體，除非另有授權 | 本計畫 |
| D8 | **專案必須可攜**：搬到其他電腦也要能運作；機器事實一律偵測、設定放 `.env`、提供一鍵重建（規則 R21） | 2026-11-14 |
| D9 | **TUI / CLI 用 Python + Textual**，必須在 Herdr 與終端機中顯示正常，並實作 Herdr agent 整合（規則 R21.9） | 2026-11-14 |
| D10 | **Desktop App 用 Tauri 2 + React（純前端 SPA）**，以 Win11 與 Ubuntu 為先；**禁止 PHP 與有重大資安問題的技術**（規則 R23） | 2026-11-14 |
| D11 | **作業系統操控依計畫逐步開放**：第一版只做唯讀 + 一般操作，高風險操作留到之後（規則 R22） | 2026-11-14 |
| D12 | **過渡期**：Hermes Agent 或 OpenCode 接上 gateway 對話，並確保在 Herdr 中顯示正常 | 2026-11-14 |

---

## 3. 設計原則（摘要）

完整證據見 `littlebit-selfevolve.md` §1、§5 與三份分析文件。

**硬體事實 [實測 / 原文]**
1. 單一請求的逐層分割無法加總裝置；CPU 解碼約 24 t/s，增加執行緒也不會更快（頻寬約 26 GB/s）。
2. 讓硬體**真正同時工作**的方式只有：平行取樣與批次、投機解碼（draft 與 target 放不同裝置）、MoE 專家分置、多個專精模型同時常駐。

**能力事實 [原文]**
3. 知識容量與「實際儲存的位元」相關：int8 為 2 bit/參數，GPTQ int4 只有 0.7；MoE 只啟用 8.8% 參數時容量僅少 1.3×。
4. 自我進化**補不回知識**，知識要靠 RAG。
5. 超小模型 + 32 條取樣 + 驗證器，可在工具呼叫上達到 32B 水準（ToolRM：0.6B 從 39.5 → 64.4）。

**八條原則 P1–P8**：雲端與大模型當老師／評審／元智能體（P1）、外部驗證優先（P2）、知識靠 RAG（P3）、**向強者學（P4，老師階梯）**、每輪從凍結核心重訓且最多 3 輪（P5）、驗證過的資料用 SFT、評審打分的資料用 DPO（P6）、回歸關卡涵蓋全部任務 + 長度 + 延遲（P7）、自我修改不得觸碰護欄（P8）。

**老師階梯（P4 的具體化）**

| 階 | 老師 → 學生 | 用途 |
| --- | --- | --- |
| 1 | 壓縮前的自己（FP 原版） | 壓縮與校準（AYOT：用自己生成的資料，58.4 vs 用 R1 生成的 31.8） |
| 2 | 同家族大一號的模型（Qwen3-14B/32B） | 壓縮後的能力蒸餾 |
| 3 | 寬鬆授權的開源大模型（Qwen3、DeepSeek-R1、gpt-oss） | 技能庫、驗證器、訓練資料 |
| 4 | 商業雲端模型 | 推論期轉交、評審、元智能體 |

---

## 4. 系統架構

```
                       ┌─────────────────────────────────────────────┐
  請求 ───────────────▶│ gateway（OpenAI 相容，:36100）              │
                       │  ① 路由器（RouteLLM 式，生成前預判）          │
                       └──┬──────────────┬──────────────┬────────────┘
                          │              │              │
          ┌───────────────▼───┐   ┌──────▼──────┐  ┌────▼─────────────┐
          │ 第 0–1 層：本機核心 │   │ 能力外置     │  │ 第 2–3 層：雲端   │
          │ · 核心 × N 條取樣  │   │ · RAG        │  │ · 修正 / 回饋     │
          │ · 投機解碼         │   │ · 技能庫     │  │ · 完整回答        │
          │ · 驗證器評分       │   │ · 工作流程   │  │ · 評審 / 元智能體 │
          └───────┬───────────┘   └──────┬──────┘  └────┬─────────────┘
                  └─────────────┬────────┘              │
                                ▼                       │
                     軌跡記錄器（本機） ◀───────────────┘
                                │
                                ▼
                 自我進化飛輪（老師階梯 → LoRA / 技能 / 路由器）
```

> **Port**：依專案規則 R11，本機服務固定使用 36100–36119（gateway 36100、engine-chat 36101、engine-embed 36102、engine-cpu 36103、verifier 36104、router 36105、engine-rerank 36106），一律綁定 `127.0.0.1`。`hetero-runtime.md` 中的 8000 / 8080–8082 已作廢。

### 4.1 元件與硬體分工

| 元件 | 預設裝置 | 理由 |
| --- | --- | --- |
| 核心模型（N 條取樣） | GPU | 頻寬最高；批次取樣可吃滿算力 |
| 大型 target（超過 VRAM 預算時） | CPU（RAM） | Dovetail 拓撲：`-ngl 0 -devd CUDA0 -ngld 99` |
| draft 模型 | GPU | 低延遲 |
| 驗證器（程式執行、schema、獎勵模型） | CPU | 與 GPU 取樣**同時**進行 |
| RAG 向量化與重排序 | CPU（有 NPU 時改用 NPU） | 無狀態、固定 shape |
| 專精模型（例如三值摘要模型） | 依預算放 GPU 或 CPU | 多個專精模型同時常駐 |
| 路由器、評分、軌跡記錄 | CPU | 輕量 |

### 4.2 四層分層轉交
| 層 | 動作 | 觸發條件 |
| --- | --- | --- |
| 0 | 本機回答 | 驗證通過且 N 條取樣一致 |
| 1 | 依驗證器的錯誤訊息在本機重試 | 驗證失敗但可修正（例如測試失敗、schema 錯誤） |
| 2 | 只請雲端給回饋或修正 | 第 1 層仍失敗 |
| 3 | 雲端完整回答 | 低信心，或路由器預判本機無解 |

**依任務設計的驗證方式 [原文]**
| 任務 | 驗證方式 |
| --- | --- |
| 程式 | 單元測試 / 執行 |
| 工具呼叫 | schema 驗證 + ToolRM 式獎勵模型 |
| 文件摘要、RAG 問答 | 上下文蘊含驗證（AutoMix 式） |
| 閉卷知識題 | **不做自我驗證**：先 RAG，再依路由器決定是否轉交 |

---

## 5. 開發階段

> **進度註記（2026-11-16，R19.4：補記，不改原文）/ Progress note**
> - Phase 0：完成，剩 8.2／8.3 乾淨環境重建（使用者進行）。`scripts/jiezi data build` 與 bootstrap 的 data 步驟讓新電腦一次重建本機資料（R21）。
> - Phase 1：完成並歸檔（add-eval-harness、add-verifiers）；雲端基準知識題 72.3%、工具 76%、程式 87.8%（摘要評審待雲端評審恢復）。
> - Phase 2（E0 → G1）：進行中，生成與評審分開並行；完成後由儀表板（`scripts/jiezi dashboard`）提供 G1 判斷依據。
> - Phase 4（提前）：4.2 分層轉交、4.3 軌跡、4.6 gateway／supervisor、4.8 CLI／TUI 完成；4.1 平行取樣完成（待實測）；4.5 路由器為規則版 v0；4.4 calibrator 待 E0 後。
> - Phase 5（提前）：5.1 RAG 完成（全文＋向量全掃描，知識庫與法規；完整向量待 E0 後以 GPU 建）；另有辭典（國／台／客）、課綱與課本、法規、記憶 wiki、工具層、答案查核。5.2 技能庫、5.3 ADAS 未開始（需工具呼叫軌跡）。
> - Phase 6 前置：訓練資料匯出（R20.3 強驗證、排除不可訓練與評測重疊）完成；訓練本身需 G1、PyTorch 與使用者同意。6.1 是否需要訓練驗證器，待 `scripts/jiezi toolcheck` 結果。
> - R23：`scripts/jiezi audit` 可重複稽核，2026-11-16 補記 bubblewrap 三則公告（皆不受影響）。
>
> **進度註記（2026-11-17，R19.4：補記，不改原文）/ Progress note**
> - 修正上一則的說法：4.2 分層轉交實作的是第 0／1／3 層，**第 2 層（只給回饋）尚未實作**，已另提案 add-partial-escalation（待審閱）。5.1 的**重排序**也尚未實作，已另提案 add-reranker（待審閱，排在 G1 後）。
> - 計畫外、使用者要求新增的功能（皆已實作並有單元測試；本機模型的實測待 E0 結束）：長文件與讀檔（PDF／Word／HTML，11-16）、長文件追問、PowerPoint／Excel 讀取、防提示注入（R22.7）、JSON 格式輸出（`response_format`）、桌面網頁附加文件、翻譯（整份文件逐段翻譯與檢查、簡轉繁）。舊版 .doc／.ppt／.xls 已提案 add-legacy-office（待審閱）。
> - Phase 4.4：calibrator 完成（add-calibrator），實測排在 E0 後；Dovetail／投機解碼拓撲的比較尚未做。4.1 平行取樣、5.2 技能庫 v0（已驗證的工具呼叫範例）完成，待實測。
> - Phase 8（提前）：唯讀雛形完成——桌面網頁（React + Vite）與 Tauri 2 外殼；2026-11-17 00:11 Tauri release 建置成功 [實測：6 分 05 秒，執行檔 6.2 MB，啟動後持續執行 12 秒未當掉；畫面內容待人工檢查]。8.1 代理迴圈、8.2／8.3 操控工具未開始。
> - Phase 2：2026-11-17 00:45 時 18 列中 17 列生成完成，最後一列（Bonsai-27B，CPU）進行中；之後是評審、前 3 名取樣與報告。
>
> **進度註記（2026-11-17 下午，R19.4：補記，不改原文）/ Progress note**
> - **Phase 2 完成、關卡 G1 已決**：E0 18 列全部作答與驗證完成（11:15）[實測：`var/eval/e0/f49c48d3f3ca/report.md`]；取樣設定（5.5）排在 11-18 00:05 續跑。使用者選定核心 **`qwen3.5-4b-q4_k_m`**（推理／工具 63%、知識 71.3%、2,614 MiB、E0 43 t/s）[實測]；規則自動推薦的是 tbonsai2-4b-q2_0（信賴區間內打平、較小較快，但知識題少 32.7 分）。
> - 核心上線後的系統實測 [實測，2026-11-17]：自我評測 84/90、工具評測 33/50、長文件摘要 15,252 字 70 秒、JSON 輸出 4/4、翻譯三份 0 失敗段、看圖 8.4 秒、一鍵中止 ≤ 1 秒。細節與不足之處見討論記錄 2026-11-17 #22–#24。
> - 實測中修正五個問題（上下文截短無限迴圈、Qwen3.5 範本的 system 訊息位置、重答時遺失問題與文件、附文件／圖片時的模糊命中、放不進上下文的請求）。
> - 5.1 重排序已實作（add-reranker）：GPU 上 hit@3 +12.5 分／+0.59 秒，但與核心同放 6 GB 顯示記憶體時保留量不足，本機預設 off。4.2 第 2 層已實作（預設 off），量測結果另記。
> - Hermes Agent 與 OpenCode 的請求（數萬 token 的系統提示與工具）放不進本機 4,096 token 的槽位：走 `jiezi` 直接轉交可用，`jiezi-local` 回 413。
> - 尚未開始：Phase 6 訓練（需先安裝 PyTorch，待使用者同意）、8.1 代理迴圈（add-agent-readonly 提案待審）、Phase 9。

### Phase 0：基礎整備（約 1 週）
| 任務 | 內容 | 驗收 |
| --- | --- | --- |
| 0.1 | 首次 git commit（hwprobe、budgets、測試） | `git log` 有基線 |
| 0.2 | 安裝 CUDA toolkit → `build-cuda`（`-DGGML_CUDA=ON`） | `facts.json` 的 `primary_device = cuda0` |
| 0.3 | 確認 GPU 上 `TQ2_0` / `Q2_0` 可執行 | ✅ 2026-11-14 實測：`Q2_0` CUDA 矩陣乘法 85/85 通過；**`TQ1_0`/`TQ2_0` 在 CUDA 上不支援**（只能在 CPU 上做矩陣乘法） |
| 0.4 | 安裝 PyTorch（CUDA wheel，不需要 `nvcc`）供後續訓練 | `torch.cuda.is_available()` |
| 0.5 | **可攜性骨架**：`.env.example`、`scripts/bootstrap`、`scripts/setup/<platform>/`、模型清單 `models/manifest`；hwprobe 在非 Linux 平台優雅降級 | 在乾淨的 WSL distro 或容器中一鍵重建，純 CPU 冒煙測試通過 |

### Phase 1：評測基礎（約 2 週）
| 任務 | 內容 | 驗收 |
| --- | --- | --- |
| 1.1 R0 題庫 | 四類任務各 ≥ 50 題起步，**知識題與推理 / 工具題分開**：工具呼叫取自 ACEBench `data_zh`；知識取自 Chinese SimpleQA / C-Eval / CMMLU；摘要取自 CNewSum；程式用 HumanEval+ / MBPP+（加中文題述版本） | 題庫版本化、可重現 |
| 1.2 V0 驗證器 | 程式執行沙盒、工具呼叫 schema 驗證 + ACEBench 規則評分、摘要上下文蘊含評分、知識題比對標準答案 | 四類任務都能自動評分 |
| 1.3 評測框架 | 同一份題庫可跑任一後端（llama.cpp / 雲端），輸出分數、t/s、峰值記憶體、成本 | 一行指令產生報表 |
| 1.4 雲端基準 | 以選定的雲端模型跑完 R0 | 得到 100% 基準線 |

### Phase 2：E0 本機同位元組實測（約 1 週，零訓練成本）→ **關卡 G1**
| 組別 | 模型 | 大小（估） |
| --- | --- | --- |
| 三值 | Ternary Bonsai 4B / 8B（`Q2_0`，**可上 GPU**）、BitCPM-CANN 3B / 8B（`TQ2_0`，**目前只能 CPU**）、BitNet b1.58 2B4T（`TQ*`，**目前只能 CPU**） | ~0.5–2 GB |
| 三值 MoE | Maple 20B-A1B（社群 GGUF） | ~5.3 GB |
| int8 | Qwen3-0.6B / 1.7B / 4B Q8_0 | 0.6–4.3 GB |
| int4 | Qwen3-1.7B / 4B / 8B Q4_K_M | 1.1–5 GB |
| int2 | Qwen3-4B / 8B Q2_K | ~1.6–3 GB |

**產出**：兩張帕累托圖（知識題分數 vs 檔案大小；推理 / 工具題分數 vs 檔案大小），並附上 t/s 與記憶體。每個模型都跑「貪婪解碼」與「N=8 取樣 + V0 驗證器」兩種設定。

> **更正（2026-11-15，R19.4；依據：Hugging Face API、GitHub、本機 llama.cpp `93cf736a` 原始碼，詳見 `openspec/changes/add-e0-benchmark/design.md` D1 與 `docs/discussions/2026-11-15.md`）**：上表的候選清單已過時，原文保留。實際執行以 `eval/e0/matrix.toml` 為準（16 個檔案，約 33.2 GiB，使用者 2026-11-15 同意）：
> - 新增 **Qwen3.5** 0.8B / 2B / 4B / 9B（Q8_0、Q4_K_M、IQ2_M）取代 Qwen3 1.7B / 4B / 8B；新增 **Ternary-Bonsai-2** 2B / 4B / 9B（同一批 Qwen3.5 的三值版，可做同基底對照），取代第一代 Ternary Bonsai 4B / 8B（主線 `Q2_0` 為每 64 個一組，第一代預設 g128 檔不相容）。
> - 新增 **1-bit Bonsai** 8B / 27B（`Q1_0`，主線支援，CUDA 有 kernel）。
> - **BitNet b1.58 2B4T 排除**：官方 `hidden_act: relu2`，主線 `bitnet` 架構用 SiLU，會算錯（使用者決定排除，不改引擎）。
> - **Maple 20B-A1B 排除**：沒有約 5.3 GB 的檔案，最小 11,318 MiB，超過 RAM 預算。
> - 「N=8 取樣」改為只對貪婪解碼前 3 名、只跑程式與工具 100 題（使用者 2026-11-15 同意）；pass@8 需要標準答案，只當上限參考。

### Phase 3：核心建置（2–4 週，依 G1 分支）
| 分支 | 條件 | 工作 | 雲端成本 [估] |
| --- | --- | --- | --- |
| **3A 三值** | G1 選三值 | 現成模型直接用；若要 Qwen3 系列，用 ScaleQ/AYOT 自行三值化：**校準資料 = 四類任務的中文題目 + 模型自己生成的回答**（多領域混合，避免專精化） | 8B 約 US$280；14B 約 US$450 |
| **3B 2-bit QAT** | G1 選 2-bit | EfficientQAT 量化 Qwen3；先確認輸出格式能否轉為 llama.cpp 可用的型別 | 8B 推估 < US$50 |
| **3C LittleBit（研究路線）** | 平行進行，或 G1 顯示需要 < 1 bpw | L0：Qwen3-0.6B 縮小版 QAT（本機）→ L1：GGUF 轉換器 + 計算圖 → E1：Qwen3-8B @ 0.55 + LittleBit-2 初始化（`--use_itq`）→ 與 G1 勝出者做同位元組對照 | 約 US$110（調參則約 US$300） |

**共同驗收**：核心通過 R0 回歸、不超過資源預算、達到 §1.3 的速度。

### Phase 4：推論系統（約 3 週）→ **關卡 G2**
| 任務 | 內容 |
| --- | --- |
| 4.1 平行取樣 | N 條取樣（GPU 批次）+ 驗證器評分（CPU 同時進行）+ 一致率信心 |
| 4.2 分層轉交 | 四層實作；門檻先保守（多轉交），再依軌跡資料下修 |
| 4.3 軌跡記錄器 | 記錄問題、N 條本機答案、驗證結果、所在層級、雲端內容、費用（只存本機） |
| 4.4 calibrator | 比較「逐層卸載」與「Dovetail 拓撲」（大 target 在 CPU、draft 在 GPU），結果寫入 `bench.json` |
| 4.5 路由器 v0 | RouteLLM 式（相似度排序或矩陣分解），用軌跡資料訓練；AutoMix 式 POMDP 作為串接備案 |
| 4.6 gateway / supervisor | 依 `hetero-runtime.md` 實作多引擎與健康檢查（port 依規則 R11） |
| **4.7 過渡客戶端** | gateway 一上線就設定 Hermes Agent 與 OpenCode 的 `base_url` 指向 gateway；在 Herdr 中驗證顯示、狀態回報、中文寬字元（D12） |
| **4.8 CLI / TUI**（約 1 週） | `jiezi ask "…"`（單次、可接管線）與 `jiezi chat`（Textual 全螢幕）；每則回答顯示第幾層回答、信心、t/s、雲端費用；實作 Herdr agent 整合（working / idle / blocked、恢復指令、release）；驗收：在 Herdr、Windows Terminal、GNOME Terminal 中顯示正常（D9） |

### Phase 5：能力外置（約 3 週）→ **關卡 G3**
| 任務 | 內容 |
| --- | --- |
| 5.1 RAG | Qwen3-Embedding-0.6B + Reranker-0.6B（需實測 reranker 轉檔問題）；文件庫由使用者提供 |
| 5.2 技能庫 | AWM 離線模式：由老師階梯第 3 階從**驗證過的**軌跡歸納工具呼叫流程（含 placeholder），本機檢索使用 |
| 5.3 ADAS 工作流程搜尋 | 雲端元智能體設計流程、**以本機核心評估**；多目標：準確率、延遲、雲端費用；驗證集 128 題 |

### Phase 6：自我進化（4–6 週，可循環）→ **關卡 G4**
| 任務 | 內容 | 老師階梯 |
| --- | --- | --- |
| 6.1 中文工具呼叫驗證器 | 照 ToolRM 配方：以寬鬆授權的開源模型產生錯誤樣本，訓練 1.5B 等級的中文獎勵模型 | 第 3 階 |
| 6.2 ReST-EM 式蒸餾 → LoRA | 每題取樣 N 條 → 驗證器過濾（每題最多 10 筆）→ 從**凍結核心**重訓 LoRA | 第 2、3 階 |
| 6.3 偏好學習 | 評審打分的資料做 DPO（評審用老師而非核心）；或 SPIN（目標分布 = 老師答案） | 第 2–4 階 |
| 6.4 合併與重新壓縮 | LoRA 累積到一定量後合併回 FP 權重，再重新壓縮（三值重校準 / QAT） | 第 1 階 |
| 6.5 路由器更新 | 用新累積的軌跡重訓路由器 | — |

**每一輪都要通過 P7 回歸關卡；最多 3 輪後重新評估。**

### Phase 8：Desktop App 與作業系統操控（第一版，約 4–6 週）→ **關卡 G5**
前提：Phase 5 的技能庫與 Phase 6 的中文工具呼叫驗證器已就緒（操控系統就是工具呼叫的實戰）。

| 任務 | 內容 |
| --- | --- |
| 8.1 Agent 執行層 | 對話記憶、工具呼叫迴圈、權限與確認、稽核記錄；TUI 與 Desktop 共用 |
| 8.2 唯讀 MCP 工具 | 檔案瀏覽 / 讀取、視窗與 UI 結構讀取（Windows UI Automation、Ubuntu AT-SPI）、截圖 |
| 8.3 一般操作 MCP 工具 | 開啟程式、切換視窗、點擊與輸入、建立新檔、剪貼簿；每個工具逐項授權 |
| 8.4 Desktop App | Tauri 2 + React（Vite 純前端 SPA）；Win11 原生與 Ubuntu；連 WSL2 / Linux 中的 gateway；一鍵中止；稽核回放介面 |
| 8.5 安全稽核 | 依規則 R23：pip-audit / npm audit / cargo audit；Tauri ≥ 2.11.1、CSP 限制、不載入遠端內容；開工前對照 Tauri 官方 advisory（規則 R15 Q8） |

**G5 判準**：唯讀與一般操作在 Win11、Ubuntu 上通過一組固定任務（例如「找出某資料夾最大的檔案」「開啟記事本並輸入一段文字」）；所有動作都有稽核記錄；一鍵中止可在 1 秒內停下；資安稽核沒有 High / Critical 未修補項目。

### Phase 9：高風險操作（G5 通過後再討論）
刪檔、安裝軟體、修改設定、送出表單、寄信等，開放時必須逐次確認（規則 R22.1）。

### Phase 7：延後項目
- NPU 接手 embedding / rerank（需要有 NPU 的機器）。
- Gödel 式自我修改（只在沙盒中，不得觸碰評分器、預算、轉交門檻）。
- 多模態（Bonsai 2 視覺語言模型）。

---

## 6. 決策關卡

| 關卡 | 時點 | 問題 | 判準 | 不通過時 |
| --- | --- | --- | --- | --- |
| **G1** | Phase 2 結束 | 核心用哪種壓縮形式？ | 在 VRAM 預算內，取「推理 / 工具題分數」最高者；若知識題分數差距大，就把知識交給 RAG。LittleBit 只有在同位元組下**勝過勝出者 ≥ 3 分**時才升為主線 | 選次佳者，LittleBit 留在研究路線 |
| **G2** | Phase 4 結束 | 平行取樣 + 分層轉交是否有效？ | 達成率與本機處理率達到 §1.3 的 Phase 4 目標 | 調整 N 值、門檻與驗證器；必要時換更大的核心 |
| **G3** | Phase 5 結束 | 能力外置是否有效？ | 知識題（含 RAG）達成率 ≥ 70%；技能庫讓工具呼叫至少 +5 分 | 擴充文件庫與技能來源 |
| **G4** | Phase 6 每一輪 | 這一輪進化是否保留？ | 目標任務提升，且其他任務退步 ≤ 1 分、回答長度增幅 < 20%、延遲沒有變差 | 回滾；連續兩輪無效就停止該方法 |
| **G5** | Phase 8 結束 | Desktop App 與作業系統操控（唯讀 + 一般操作）是否可用且安全？ | 固定任務在 Win11 與 Ubuntu 通過；全部動作有稽核；一鍵中止 ≤ 1 秒；資安稽核無 High / Critical 未修補項目 | 不開放 Phase 9 高風險操作；先修正 |

---

## 7. 時程（單人開發加 AI 協助）[估]

| Phase | 週數 | 累計 |
| --- | --- | --- |
| 0 基礎整備 | 1 | 1 |
| 1 評測基礎 | 2 | 3 |
| 2 E0 實測 + G1 | 1 | 4 |
| 3 核心建置 | 2–4 | 6–8 |
| 4 推論系統 + G2 | 3 | 9–11 |
| 5 能力外置 + G3 | 3 | 12–14 |
| 6 自我進化（第一輪）+ G4 | 4–6 | 16–20 |
| 4.7–4.8 過渡客戶端 + CLI / TUI | 1 | （併入 Phase 4 之後） |
| 8 Desktop App + 作業系統操控 + G5 | 4–6 | 20–26 |

**可以平行進行的**：0.2 與 1.1；3C（LittleBit 研究路線）與 Phase 4；5.1 與 5.2。

---

## 8. 預算 [估]

| 項目 | 金額（USD） | 依據 |
| --- | --- | --- |
| 核心建置（3A 或 3B） | 0–450 | E0 若直接採用現成模型則為 0 |
| LittleBit 研究路線（3C） | 110–300 | 約 33 H100 小時 × US$3.25；調參 ×3 |
| 中文工具呼叫驗證器（6.1） | 20–100 | 1.5B 獎勵模型；資料由本機或租用 GPU 生成 |
| 自我進化 3 輪（6.2–6.4） | 300–1,350 | 每輪重新壓縮約 US$100–450 |
| 雲端 API（基準、轉交、評審、ADAS） | 300–800 | ADAS 的評估改在本機後，主要成本只剩元智能體 |
| **合計** | **約 730–3,000** | GPU 價格：H100 約 US$3.25/小時、A100 約 US$1.76/小時（2026-09～10 中位數） |

---

## 9. 風險

| 風險 | 機率 | 影響 | 對策 |
| --- | --- | --- | --- |
| 中文能力在極低位元下流失更多（現有論文多以英文評測） | 中高 | 中文問答分數低 | E0 實測中文；BitCPM（中文團隊）列入候選；校準資料用中文（AYOT 原則） |
| 三值 PTQ 造成領域專精化 | 確定（原文） | 通用性下降 | 多領域混合校準；或改走「多個專精模型 + 路由」 |
| E0 的社群 GGUF（Maple）有轉檔問題 | 中 | 該組數據不可信 | 與官方或其他格式交叉驗證 |
| ↳ **更正（2026-11-15）** | Maple 已排除；Qwen3.5 小模型沒有官方 GGUF，改用 unsloth 轉檔（以 SHA-256 鎖定），每個模型先跑 5 題冒煙檢查 | — | — |
| 小核心不適合自我驗證 | 高（原文） | 第 0 層誤判 | 驗證器與核心分離（P2）；閉卷題不做自我驗證 |
| 平行取樣讓延遲變高 | 中 | 互動體驗差 | N 值依任務調整；先回傳第一個通過驗證的答案 |
| 自我進化收益小或造成退步 | 中 | Phase 6 效益低 | 先做不改權重的 Phase 5；G4 回歸關卡 |
| 授權限制（見 §10） | 確定 | 無法商用 | 第一版定位為研究 / 個人用途 |
| WSL2 的 GPU 與 CPU 拓撲是虛擬的 | 確定 | 綁核與量測有誤差 | 以實測為準；在 facts 中註記 |

---

## 10. 授權與合規

| 資產 | 授權 | 限制 |
| --- | --- | --- |
| LittleBit / LittleBit-2 程式碼 | CC BY-NC 4.0 | 禁止商用 |
| C-Eval、CMMLU、Chinese SimpleQA 資料 | CC BY-NC-SA 4.0 | 只能內部評測 |
| Qwen3、DeepSeek-R1、gpt-oss、Maple | Apache 2.0 / MIT ⚠️ | 老師階梯第 2、3 階可用；**使用前讀官方授權檔** |
| 商業 API（Anthropic、OpenAI、xAI 等） | 服務條款 | 未經授權不得用輸出訓練模型 → 只用於推論期轉交、評審、元智能體 |
| Ternary Bonsai、BitCPM-CANN、ACEBench、CNewSum | ⚠️ 未查 | Phase 2 / Phase 1 開始前確認 |
| ↳ **更正（2026-11-15）** | Ternary-Bonsai-2、Bonsai 1-bit、BitCPM-CANN、Qwen3.5：Apache-2.0（已讀官方 LICENSE，見 `docs/licenses.md`）；ACEBench：MIT（2026-11-14 已查）；CNewSum：未採用（摘要改用中文維基自建） | — |

---

## 11. 量測與儀表板

| 類別 | 指標 |
| --- | --- |
| 品質 | 四類任務的達成率（知識與推理 / 工具分開）、回答長度 |
| 成本 | 各層比例、每 1000 個請求的雲端費用、成本倍率 |
| 效能 | 第 0 層 t/s、首 token 延遲、峰值 RAM / VRAM、各裝置使用率（驗證硬體是否真的同時工作） |
| 進化 | 每輪 G4 的增減、軌跡累積量、驗證器準確率 |
| 路由 | APGR、CPT(50%)、CPT(80%)（RouteLLM 指標）、IBC（AutoMix 指標） |

---

## 12. 待驗證假設

| # | 假設 | 驗證於 |
| --- | --- | --- |
| H1 | 相同位元組數下，Q8 小模型的知識題分數高於 Q4 大模型 | Phase 2 |
| H2 | 三值模型在推理 / 工具題的「分數 / GB」高於 int4 | Phase 2 |
| H3 | 中文能力在三值化後的流失比英文多 | Phase 2 |
| H4 | 核心 + N 條取樣 + 驗證器，在工具呼叫上可達雲端 80% 以上 | Phase 2（初步）、Phase 4 |
| H5 | 大 target 放 CPU、draft 放 GPU，比逐層卸載更快 | Phase 4（calibrator） |
| H6 | 由「壓縮前的自己」轉譯的教材，優於直接使用大老師的教材 | Phase 6 |
| H7 | LittleBit 在同位元組下能勝過三值或 2-bit | Phase 3C（E1） |

---

## 13. 與 OpenSpec 的對應（芥子新 repo）

| Phase | OpenSpec change |
| --- | --- |
| 0 | `add-hwprobe`（已完成，待歸檔）、`add-cuda-build` |
| 1 | `add-eval-harness`、`add-verifiers` |
| 2 | `add-e0-benchmark`（2026-11-15 提案並實作，夜間執行中）|
| 3 | `add-core-ternary` / `add-core-qat2bit` / `add-littlebit-research` |
| 4 | `add-parallel-sampling`、`add-tiered-escalation`、`add-trajectory-logger`、`add-calibrator`、`add-router` |
| 5 | `add-rag`、`add-skill-library`、`add-workflow-search` |
| 6 | `add-tool-verifier-zh`、`add-self-evolution-loop` |

每個 change 依 Propose → Apply → Archive 流程進行，規格使用 SHALL / MUST。

---

## 14. 參考文件

| 文件 | 內容 |
| --- | --- |
| [`../analysis/ggml-vs-onnxruntime.md`](analysis/ggml-vs-onnxruntime.md) | 引擎選型、GGUF 與量化格式 |
| [`../analysis/self-evolution-papers.md`](analysis/self-evolution-papers.md) | 9 篇自我進化論文全文分析 |
| [`../analysis/deep-read-round3.md`](analysis/deep-read-round3.md) | 10 篇：三值、知識容量、路由、異質硬體、驗證器 |
| [`../analysis/related-resources.md`](analysis/related-resources.md) | 可用資源、模型、題庫、授權、預算 |
| [`littlebit-selfevolve.md`](design-principles.md) | 設計原則 P1–P8 與老師階梯 |
| [`hetero-runtime.md`](design/hetero-runtime.md)、[`hw-autoconfig.md`](design/hw-autoconfig.md) | 多引擎編排、硬體探測與參數決策 |
| [`../2026-11-12.md`](discussions/2026-11-12.md)、[`../2026-11-14.md`](discussions/2026-11-14.md) | 討論記錄 |

---

## 15. Agent 基本能力與最小硬體開發子計畫（2026-11-19 新增）

> 本節是依 R19.4「更正不刪除」新增的**附加子計畫**，不覆蓋原有 P1–P8、D1–D12、G1–G5、時程、預算與核心模型決策。`Anget` 視為 `Agent` 誤繕。核心仍為 `qwen3.5-4b-q4_k_m`；本子計畫的目標是把能力放在外圍系統（工具、驗證器、記憶、技能、流程、稽核），**不是換更大的模型，也不是把硬體占滿**。
>
> 本節只是開發計畫。任何新功能仍依 R4 先提 OpenSpec proposal 並經使用者確認；每個功能都要先判定 `SKILL`／`MCP`／核心內建，先查現成方案，再做資安掃描。每項任務的狀態、預期產出與回填位置記錄在 `~/projects/tmp/LLM_discussion/HANDOFF.md` §3 與 `~/projects/tmp/LLM_discussion/2026-11-19.md` #8。

### 15.1 基本能力矩陣與芥子現況

判定：`IMPLEMENTED`＝已有可驗證實作；`PARTIAL`＝有基礎但還沒完整驗收或覆蓋；`MISSING`＝尚未具備，需先提案。

| # | 基本能力 | 必備行為 | 芥子現況 | 判定 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| A1 | 任務契約 | 明確目標、限制、完成條件、風險等級；模糊時先問，不自行擴權 | 使用者規則與 gateway 已有脈絡，但沒有 first-class task contract 欄位 | PARTIAL | 先提案 `add-agent-contract`；把目標／限制／完成條件寫入軌跡 |
| A2 | 有限代理迴圈 | observe → think → act → verify → answer；步數、呼叫數、輸出字數、超時都要有上限 | `src/jiezi/agent/loop.py`：`MAX_STEPS=6`、`MAX_CALLS_PER_STEP=3`、`RESULT_CHARS=2500`、`OLD_RESULT_CHARS=400`、`TOOLS_BUDGET=2600`、`CALL_TIMEOUT_S=120`；取消會殺 process group；工具結果視為資料不是指示 | IMPLEMENTED | 補極限、逾時、重複呼叫、取消的回歸測試 |
| A3 | 工具呼叫 | schema 明確；參數型別檢查；不捏造工具；結果可追溯；失敗可重試但不無限重試 | `src/jiezi/agent/tools.py` 提供 `list_dir`／`find_files`／`read_file`／`file_info`；`runtime/escalation.py` 驗證 `tool_calls` 或 `[f(a=1)]` 文字格式；`toolcheck` 已從 33/50 提升到 43–44/50 [實測] | PARTIAL | 續做 `add-strong-tool-calling`；ACEBench／BFCL 完整評測排夜間 |
| A4 | 唯讀檔案與最小權限 | 逐次檢查 grant；解析 symlink；拒絕 `.env`、金鑰、憑證與家目錄敏感區；可撤銷 | `agent/grants.py`：`var/agent/grants.json`、拒絕 `DENY_NAMES`／`DENY_HOME`；每次呼叫重讀 grant；`agent/tools.py` 無寫入／執行／網路 | IMPLEMENTED | 加 path traversal、symlink、revoke-after-grant 的紅隊測試 |
| A5 | 外部能力介面（MCP） | 外部進程／資源要有 schema、授權、稽核、生命週期；本機先走 stdio，不主動開 HTTP | `agent/server.py` 支援 MCP stdio 子集：`initialize`、`notifications/initialized`、`ping`、`tools/list`、`tools/call`；沒有改 grant 的方法；尚未做 resources／prompts／sampling／HTTP | PARTIAL | 維持本地子集；若要 HTTP，依官方 spec 處理授權與信任，先另提提案 |
| A6 | 外部驗證與分層轉交 | 驗證器在核心外；不用模型自己當唯一裁判；本機不足再分層升級；每日上限與成本可控 | `runtime/escalation.py` 驗證後重試，不執行模型輸出；`RETRY_PROMPT`；`gateway` 有 tier、policy、cloud、sources；第 2 層預設關閉；轉交統計已有 | PARTIAL | 補中文工具驗證器與「何時不該轉」的對照題；延續 `add-strong-tool-calling`、`reduce-claude-escalation` |
| A7 | 記憶與檢索 | 知識靠 RAG／外部來源；回答標來源；記憶可查可糾正；外部與雲端內容不得直接進訓練 | `memory.py` 的 `var/memory/wiki/` Markdown wiki 為正本、SQLite 為索引；Claude／雲端回答 `training_use=false`；RAG、法規 DB、網頁讀取、長文件已可用 | PARTIAL | 來源信任、版本與註記統一；冷門事實「沒資料時不猜」繼續驗證 |
| A8 | 技能形成與重用 | 只從驗證成功的工具呼叫提煉；要有信心門檻、來源、沿用次數與淘汰 | `skills.py` v0：`var/skills/skills.jsonl`；只收 schema 驗證且 `confidence >= 0.75` 的成功呼叫；`MIN_SIMILARITY=0.3`、`MAX_EXAMPLES=2`；目前真實樣本不足 | PARTIAL | 延續 `add-skills-v0`；訂定最小樣本數、去重、過期與人工核准 |
| A9 | 可觀測與稽核 | 每次工具呼叫有 audit；回答有 process／sources；可重建事件順序；留存不無限成長 | `agent/audit.py` 寫 `var/agent/audit/YYYY-MM-DD.jsonl` 且不記檔案內容；`runtime/trajectory.py` 本機 JSONL、寫入失敗不影響回答、有 retention prune；`gateway` 有 `/health`、`/v1/documents`、`/admin/unload` | IMPLEMENTED | 統一 audit／trajectory／dashboard 的欄位與保存政策 |
| A10 | 人在迴圈與高風險操作 | 寫入、外部連線、安裝、金鑰、破壞性操作要 preview、明確核准、可撤銷、可回溯 | 目前只有 grant／revoke CLI 與唯讀工具；沒有 per-action approve／dry-run／rollback | MISSING | 先提案 `add-agent-approval`；未核准前不新增寫入／shell／網路工具 |
| A11 | 多客戶端可用 | CLI／TUI／desktop／Hermes／OpenCode 都能用，且工具清單不炸上下文 | gateway 可為多客戶端提供服務；Hermes 帶約 55 個工具、數萬 token，走 `jiezi-local` 回 413 [實測] | PARTIAL | 工具依任務篩選與精簡描述；先修 413 再談全面開放 |
| A12 | 提示注入與輸出安全 | 外部內容永遠是資料；拒絕間接注入；工具描述不當成可信指令；輸出經過驗證 | `injection.py` 預設開啟；loop 明確標示工具結果是資料；grant deny；一鍵中止 ≤ 1 秒 [實測] | PARTIAL | 建立固定注入語料與回歸關卡；覆蓋網頁／文件／記憶／技能四種來源 |
| A13 | 資源守門 | 不占滿硬體；VRAM 至少留 1 GB；agent 控制面不載入額外模型；重度工作 00:00–07:00 | `facts.json` budgets、服務僅綁 `127.0.0.1`、連接埠 36100–36119、`JIEZI_AGENT` 預設關閉、重排序與第 2 層預設關閉 | PARTIAL | 把 agent 的 token／tool／time budget 與 budget dashboard 對齊 |
| A14 | 停止、恢復與責任界線 | 可停止、可查最後狀態、可從譜系重建；失敗不靜默吞掉；不跨信任邊界自動委派 | 取消會殺 process group；trajectory 本機記錄；但「恢復到哪一步」與多代理信任模型未定義 | PARTIAL | 定義 pause／resume／abort 語意；多代理與 sandbox 留到 G5 之後 |

### 15.2 `SKILL`／`MCP`／核心內建的判定

| 類型 | 用在哪裡 | 必備條件 | 不該用在 |
| --- | --- | --- | --- |
| `SKILL` | 程序性知識、模板、檢查清單、可重複流程、可重用的工具呼叫範例 | 可用 Markdown／模板／小型腳本表達；不新增外部權限；不長期持有憑證；可版本化、可審查、可移除；放在本機技能庫並記錄來源 | 需要獨立生命週期、跨客戶端協定、外部系統寫入、敏感授權、不能在日誌暴露的資料 |
| `MCP` | 外部工具／資源／服務，需要 schema、權限邊界、稽核，或要給 Hermes／OpenCode 等多客戶端重用 | 先查有無現成 server；最小工具集；input schema 驗證；逐次授權；stdio 優先；不把 tool description 當可信指令；日誌不記敏感內容 | 純文字知識、只要 prompt 就能完成的事、還沒通過 R4 的寫入／shell／網路操作 |
| 核心／既有模組 | 不可外包的安全與 invariant：迴圈上限、grant、verifier、escalation、audit、trajectory、cancellation、gateway budget | 放在 `src/jiezi/`；有單元測試與紅隊測試；不改核心模型；可被 audit 驗證 | 為了「看起來有 Agent 功能」而新增一層抽象；假借 SKILL／MCP 名稱逃避審查 |

判定守則：先問「它會改變外部世界嗎？」、「它需要新的權限嗎？」、「它要被不同客戶端重用嗎？」；任一為是，優先考慮 `MCP` 並做資安掃描。只是「怎麼做」的知識才用 `SKILL`。若不是新功能、只是既有核心的強化，標記為「核心／既有模組」，仍走 R4；不得用「核心」當作模糊地帶來規避 SKILL／MCP 判定。每個新功能都要在 proposal 寫下：分類、現成方案搜尋結果、引用來源、資安掃描結論；若發現重大問題，先提出原因與影響交使用者決策，不直接加入。

### 15.3 現成方案搜尋與取捨

本輪背景 `librarian` 任務超時失敗，已改用前景查證官方文件；不重啟背景任務，也不重複大範圍搜尋。查證日期：2026-11-19。

| 來源 | 重點 | 芥子取捨 |
| --- | --- | --- |
| [MCP Specification 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18) | tools/resources/prompts；user consent and control、data privacy、tool safety（arbitrary code execution、description 可能不可信）、LLM sampling controls；implementation guidelines 要求 authorization、access control、privacy | 沿用 stdio 子集與嚴格 schema；工具結果只當資料；不主動開 HTTP／OAuth 表面；若要 HTTP 必須先做完整威脅模型與提案 |
| [Anthropic Agent Skills overview](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) | Skills 是 filesystem-based、按需載入的可重用能力，封裝 instructions／metadata／scripts／templates | 適合 SKILL：程序、模板、工具呼叫範例；不把權限寫進 SKILL 文字；技能來源與版本要可稽核 |
| [Building effective agents（Anthropic）](https://www.anthropic.com/engineering/building-effective-agents) | 先用簡單、可組合的模式；workflows 與 agents 分開；只有在有 ground truth 與 stopping conditions 時才增加自主性 | 保持 bounded loop、明確停止條件、外部驗證；不做無目標自主代理；不為「像 agent」而增加自主權 |
| [OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/download/43299/) | `LLM01:2025 Prompt Injection`；RAG／fine-tuning 無法完全緩解注入 | 一律假設網頁、文件、記憶、工具描述可能帶注入；輸入／輸出分層檢查；高風險動作要人在迴圈 |
| [OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html) | Tool Security & Least Privilege、Input Validation、Memory & Context Security；避免 over-permissioned MCP tool；用 scoped allowlist 與 authorization middleware | grant 逐次重讀、deny list、audit 不記內容、工具白名單、來源標記；新增工具前逐項勾稽 |

### 15.4 資安掃描結果與準則

本節本身只新增文件，未新增套件、服務、連接埠或權限，故本次變更的 OSV／相依掃描結果為「無新增相依」。未來每個 Agent 功能必須重做下表；出現重大問題即停止並交使用者決策。

| 風險 | 現有控制 | 殘留風險 | 準則／行動 |
| --- | --- | --- | --- |
| 間接提示注入（網頁／文件／記憶／工具回傳） | `injection.py` 預設開；工具結果標為資料；回答附來源 | Long context 與多來源交叉注入 | 固定注入語料回歸；來源分層；高風險動作需核准 |
| Tool poisoning／schema 說謊 | tools 用固定 schema；grant 白名單；每次呼叫重讀 grant | 第三方 MCP server 可能描述與行為不一致 | 只用可信 server；最小工具集；wire log 只記必要欄位；新 server 先隔離測試 |
| 幻覺工具呼叫／參數錯型 | `runtime/escalation.py` 驗證 tool_calls 與 JSON 型別；失敗重試；不執行模型輸出文字 | 巢狀參數、long-tail API 仍可能錯 | 延續 `add-strong-tool-calling`；ACEBench／BFCL 夜間完整評測 |
| Excessive agency | `JIEZI_AGENT` 預設關；目前唯讀；grant／revoke CLI | 未來加入寫入／shell／網路時權限過大 | 分階段 proposal；per-action preview、dry-run、rollback、HITL；未核准不做 |
| Path traversal／secret 外洩 | symlink 解析；`DENY_NAMES`／`DENY_HOME`；audit 不記檔案內容 | 新路徑型態或罕見編碼 | 紅隊測試 `.env`、key、pem、facts.json、家目錄敏感路徑、符號連結 |
| 記憶／技能污染 | 雲端輸出 `training_use=false`；技能只收驗證成功且信心足夠的呼叫 | 質量門檻仍低、樣本不足 | 來源／時間／驗證證據入欄位；人工核准後才推廣；惡意意圖樣本要隔離 |
| 資源耗盡 | loop 上限、timeout、字數上限；VRAM 保留 ≥1 GB；facts budgets；重活夜間 | 多客戶端同時觸發、工具輸出超大 | task-level budget 與 dashboard 對齊；超出就 fail closed；預設不開全部工具 |
| 供應鏈 | 新相依要查 OSV、寫 `docs/licenses.md`、`scripts/jiezi audit` 未接受漏洞 0 | Python／Node 間接相依 | 不新增相依為首選；不可避免時先掃描再提案 |
| 多客戶端上下文爆炸 | gateway 可服務 Hermes／OpenCode | Hermes 帶約 55 工具造成 413 [實測] | 工具依任務篩選、縮減描述；修好前不視為「多客戶端完成」 |

### 15.5 開發順序（A1–A8 皆需先提案，目標是最小硬體；A0 已完成）

| 順序 | 提案／change | 詳細任務 | 驗收 | 資源 |
| --- | --- | --- | --- | --- |
| A0 | 本節與紀錄（已完成於 2026-11-19） | 現況盤點；外部官方文件查證；能力矩陣；SKILL／MCP 判定；資安準則；任務寫入 HANDOFF §3 與當日 #8 | 兩份紀錄可追溯到 T1–T5；本節不改核心與既有原則 | 僅文件；無新進程／連接埠／相依 |
| A1 | `add-agent-contract` | 定義 task contract 欄位：goal、constraints、done criteria、risk、allowed tools、budget；寫入 trajectory；模糊時先問；完成／失敗都要記錄狀態 | contract 測試通過；不產生未經授權的工具呼叫；稽核可重建 | 僅 CPU／Python；不載入額外模型 |
| A2 | `add-agent-hardening` | 補 A2/A4/A12/A13 回歸：步數、呼叫數、字數、timeout、cancel、symlink、secret deny、revoke after grant、injection corpus | 642 現有測試不降；唯讀代理 6/6 [現有基線]；中止 ≤1 秒 [現有基線]；紅隊案例全過 | 白天可跑短測試；大量模糊測試／紅隊夜間 |
| A3 | `add-strong-tool-calling`（續） | 巢狀參數、JSON 還原、ACEBench／BFCL 完整評測、工具篩選；修正 Hermes／OpenCode 413 | 工具呼叫不低於目前 43–44/50 [實測]；正式目標等夜間完整評測後回填；多客戶端不再 413 | 完整評測僅夜間；不占滿 GPU；VRAM ≥1 GB 保留 |
| A4 | `add-agent-capability-registry` | 每個新功能填分類表：SKILL／MCP／核心；現成方案連結；資安掃描；版本／責任人／移除條件；技能庫門檻與淘汰 | 任意新功能都能在 proposal 找到三項證據；無現成方案要寫理由；重大問題先停下 | 文件與小程式；無新外部服務 |
| A5 | `add-agent-trust-gate` | 來源信任、技能／記憶 provenance、版本、checksum 或等價驗證、污染隔離、雲端輸出禁止訓練標記 | 外部內容不可直接變成技能／訓練；來源可查；注入語料回歸通過 | 僅 CPU／文字處理；不新增 embedding 模型 |
| A6 | `add-agent-approval`（高風險，最後做） | per-action approve、preview、dry-run、rollback、audit reason、revoke；先只做單一可逆寫入工具 | R4 核准後才施工；未核准任何寫入／shell／網路工具；每次高風險動作都有明確核准 | 仍以本機優先；連接埠不超出 36100–36119 |
| A7 | `add-client-tool-filter` | 工具依 task contract 篩選；描述壓縮；Hermes／OpenCode smoke test；失敗降級而不是 413 | 兩客戶端在真實工具清單下可對話；gateway 不超出上下文 | 白天短測；避免 systemd 重啟打斷請求 |
| A8 | `add-agent-observability` | 統一 audit／trajectory／process／dashboard 欄位；task budget 與 facts budgets 對齊；fail-closed 狀態 | 狀態頁可看到 agent on/off、成果、轉交、工具、資源；不記敏感內容 | 不開新連接埠；不得占滿硬體 |

### 15.6 本子計畫的驗收關卡

1. **方向不變**：不改 P1–P8、D1–D12、G1–G5、核心 `qwen3.5-4b-q4_k_m`、Phase 0–8 主時程；所有能力都走外圍系統。
2. **安全優先**：每個 Agent 功能都有 R4 proposal、SKILL／MCP／核心判定、現成方案搜尋、資安掃描；重大風險先交使用者決策。
3. **最小硬體**：agent 控制面不載入額外模型；VRAM 至少留 1 GB；硬體資源不可全部占盡；服務只綁 `127.0.0.1`、連接埠 36100–36119；重度評測 00:00–07:00。
4. **回歸不降**：`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` 不少於現有 642 tests OK；`openspec validate --all --strict` 通過；行為變更需 red/green 對照。
5. **唯讀基線**：唯讀代理 6/6、中止 ≤1 秒、secret deny、grant revoke 都通過；HITL 未做好前不開寫入／shell／網路。
6. **工具品質**：工具呼叫以目前 43–44/50 [實測] 為下限；完整 ACEBench／BFCL 夜間回填正式基線；不捏造工具、不直接執行模型輸出文字。
7. **資料邊界**：Claude／雲端回答一律 `training_use=false`；外部內容永遠是資料；來源、時間、驗證證據可追溯。
8. **客戶端**：Hermes／OpenCode 的工具清單問題修正前，不宣告多客戶端 Agent 完成。
9. **紀律**：每項任務都記錄在 HANDOFF §3 與當日討論紀錄；完成一項回填一項；本輪不 push，除非使用者再次授權。

### 15.7 A1 完成補記（2026-11-19 13:59，R19.4）

> 保留 §15.1／§15.5 原本的 `PARTIAL` 與代辦說法；本節是完成後的更正，不覆蓋原紀錄。

- **狀態**：A1 `add-agent-contract` 已於 13:59 closed；A2–A8 仍待各自 R4 提案與核准。
- **實作**：新增 `src/jiezi/agent/contract.py`；`loop.py` 工具分派前驗證 contract 並使用 effective tools／budget；`gateway.py` 從 request 移除 `agent_contract` 後才寫 trajectory，於 response meta 與 JSONL 附加 contract、budget、tools、terminal state、時間欄位。
- **安全**：contract 只是中繼資料、不進引擎 prompt、不擴大 grant、不新增 SKILL／MCP／相依／連接埠；未知欄位忽略、secret scrub、未知或未授權工具拒絕、超額 budget cap、模糊 done criteria 零工具呼叫。
- **驗證**：`TestContract` 5/5、`TestLoop` 7/7、`TestGatewayAgent` 6/6；全量 654/654 OK（原 642 + 新增 12）；`openspec validate --all --strict` 44/44；`git diff --check` 乾淨。
- **殘留風險**：尚未 live smoke／重啟 gateway；`aborted` 終態在串流取消路徑已實作但未被新測試直接覆蓋；basedpyright 未安裝（使用者先前拒絕），Python LSP 未跑；ResourceWarning 為既有；未 stage／commit／push。
- **14:05 最終重跑補記（R19.4，保留 13:59 結果）**：`openspec validate --all --strict` 44/44；`openspec status --change add-agent-contract --json` artifacts 全 done／`isComplete: true`；全量 unittest 654/654 OK（74.465 秒）；`GIT_MASTER=1 git diff --check` 無輸出；他人 `add-sft-round2/tasks.md` 未動。未 stage／commit／push。
- **14:08 最終確認（R19.4，保留前述結果）**：文件回填後再跑 `openspec validate --all --strict` 44/44、`GIT_MASTER=1 git diff --check` 無輸出；全量 unittest 654/654 OK（74.321 秒）。未 stage／commit／push。

### 15.8 A2 完成補記（2026-11-20，R19.4）

> 保留 §15.7 的 A1 原文與上方所有歷史紀錄；本節是 A2 `add-agent-hardening` 施工完成後的更正，不覆蓋原紀錄。tasks.md 6.3 原寫「§15.7」，因 R19.4 改新增本節。

- **核准**：使用者已於施工前明確授權（question 工具回覆「授權施工 add-agent-hardening (Recommended)」）；T36 closed，T37／T38 closed；7.1 的「等待可以實作」關卡在施工前已滿足，無須再次請求。
- **狀態**：A2 已施工完成，change/tasks.md 18/18 勾選；`openspec status --change add-agent-hardening --json` → `isComplete: true`、四件 artifacts 全 `done`。
- **實作**：新增 `src/jiezi/agent/limits.py` 做六個上限的不可變單一來源；`loop.py`／`contract.py` 改讀取它並保留舊常數名稱；`loop.py`  tool call timeout 改 fail closed 並標明秒數。新增 `tests/fixtures/agent_redteam/manifest.json`（21 案例、6 分類：loop_limits／cancellation／grants／injection／budget_alignment／user_text）與 `tests/test_agent_hardening.py`（5 tests，含真實子行程取消 gate）；`tests/test_agent.py` 加回歸 gate 註解；`tests/test_injection.py` 加 3 項多來源注入回歸。
- **安全**：合成語料、無真實機密；寫入 grant、symlink 逃逸、secret deny、revoke、稽核無內容、budget 對齊都有測試；Claude／雲端輸出不進訓練。無新套件、服務、連接埠、模型或 GPU 工作。
- **驗證**：`PYTHONPATH=src:tests .venv/bin/python -m unittest -v tests.test_agent_hardening` → 5/5 OK（0.631 秒；先前 12 tests 是 top-level `TestLoop` 重複收集，已改為函式內 import 修正）；`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` → `Ran 719 tests in 73.939s`、`OK`（原 711 + 新增 8；ResourceWarning 為既有）；`openspec validate add-agent-hardening --strict` valid；`openspec validate --all --strict` 46 passed／0 failed；`GIT_MASTER=1 git diff --check` 無輸出；繁體掃描無真簡體；未 stage／commit／push。
- **殘留風險**：語料過擬合與真實機密誤入仍需內容審查；大量 fuzz／夜間紅隊排除在本 change 外；未 live smoke 或重啟 gateway；basedpyright 未安裝（使用者先前拒絕），Python LSP 未跑；ResourceWarning 為既有。

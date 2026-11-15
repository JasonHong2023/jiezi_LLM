## Context

- 已有的元件：`eval/engine.py` 的 `LocalEngine`（llama-server 的啟動、健康檢查、峰值記憶體取樣、預算核心綁定），`eval/client.py` 的 `ChatClient`（OpenAI 相容呼叫、基準模式的模型核對），`verify/tool_call.py` 的解析器（不執行回答內容），`config.port_base()`（R11 的 36100 區段）。
  Existing pieces: `LocalEngine` (llama-server start, health, peak-memory sampling, budget-core pinning), `ChatClient` (OpenAI-compatible calls, baseline model check), the tool-call parser (never executes responses), `config.port_base()` (the R11 36100 block).
- R11 已分配：gateway 36100、engine-chat 36101、engine-cpu 36103。
  R11 assigns gateway 36100, engine-chat 36101, engine-cpu 36103.
- 使用情境：同一台筆電上的 Hermes Agent、OpenCode、之後的 `jiezi ask / chat` 與 Desktop App；單一使用者，同時只有少數請求。
  Usage: Hermes Agent, OpenCode, later `jiezi ask / chat` and the Desktop App on the same laptop; a single user with few concurrent requests.

## Goals / Non-Goals

**Goals：**
- 客戶端只要把 `base_url` 指向 gateway，就能使用本機核心與雲端轉交，不必知道背後有幾個引擎。
  A client only points `base_url` at the gateway to use the local core and cloud escalation, unaware of the engines behind it.
- 每個回答都說得出「是哪一層、哪個模型、驗證結果如何、花了多少」。
  Every answer can say which tier, which model, what the verification found, and what it cost.
- 不占滿資源（R18）、不影響夜間量測（R17）、只綁本機（R6.12）。
  Never exhaust resources (R18), never disturb night measurements (R17), local binding only (R6.12).

**Non-Goals：** 見 proposal。 / See the proposal.

## Decisions

### D1 — 模組 / Modules

`src/jiezi/runtime/`：`supervisor.py`（引擎生命週期）、`gateway.py`（HTTP）、`escalation.py`（分層與執行期驗證器）、`trajectory.py`（記錄）、`settings.py`（從 `.env` 讀設定）。`LocalEngine` 從 `eval/engine.py` 移到共用位置（`jiezi/engine.py`），評測與 runtime 共用，不複製程式。
`src/jiezi/runtime/`: `supervisor.py` (engine lifecycle), `gateway.py` (HTTP), `escalation.py` (tiers and runtime verifiers), `trajectory.py` (records), `settings.py` (reads `.env`). `LocalEngine` moves from `eval/engine.py` to a shared place (`jiezi/engine.py`) used by both evaluation and runtime, without copying code.

### D2 — HTTP 框架（R23）/ HTTP framework (R23)

選項（2026-11-15 以 OSV 查證，下列最新版都沒有已知漏洞）：
Options (checked with OSV on 2026-11-15; none of these latest versions has known vulnerabilities):

| 選項 / Option | 套件 / Packages | 歷史公告數 / Past advisories | 評估 / Assessment |
|---|---|---|---|
| (a) Starlette + uvicorn + httpx | starlette 1.10.0、uvicorn 0.54.0（h11 0.16.0）、httpx 0.28.1、anyio 4.16.0 | starlette 20 | 非同步串流、客戶端中斷可取消上游請求；HTTP 解析交給 h11；套件小，沒有 FastAPI 的額外層 / async streaming with upstream cancellation on disconnect; h11 parses HTTP; small, without FastAPI's extra layer |
| (b) aiohttp（伺服器與客戶端同一套）/ aiohttp (server and client in one) | aiohttp 3.14.5 與其相依 / and its deps | 101（最近一批 2026-10-20）/ 101 (latest batch 2026-10-20) | 套件數少，但漏洞歷史多 / few packages, long vulnerability history |
| (c) 只用標準函式庫 / standard library only | `http.server` + `urllib` | — | 零相依；但 Python 文件註明 `http.server` 只有基本安全檢查、不建議用於正式環境，客戶端中斷時也難以取消上游生成 / zero dependencies, but the Python docs say `http.server` has only basic security checks and is not for production; cancelling upstream generation on disconnect is awkward |

**建議 (a)**：版本鎖在 `uv.lock`，`stack.md` 記錄 R23 查證；之後每次升級重新查 OSV。
**Recommend (a)**: versions pinned in `uv.lock`, the R23 check recorded in `stack.md`, OSV rechecked on every upgrade.

### D3 — gateway 介面 / Gateway interface

- 只綁 `127.0.0.1:36100`（`JIEZI_PORT_BASE` 可改區段起點）；設定成其他位址時拒絕啟動（R6.12）。
  Binds only `127.0.0.1:36100` (`JIEZI_PORT_BASE` moves the block); refuses to start if configured for any other address (R6.12).
- 需要 `Authorization: Bearer <JIEZI_GATEWAY_KEY>`。金鑰由 bootstrap 隨機產生並寫進 `.env`（不進版控）；沒有金鑰時拒絕啟動。這樣同一台電腦上的其他程式或網頁無法隨意使用。
  Requires `Authorization: Bearer <JIEZI_GATEWAY_KEY>`. Bootstrap generates a random key into `.env` (never committed); without a key the gateway refuses to start. Other programs or web pages on the same machine cannot use it freely.
- 模型名稱代表策略：`jiezi`（自動：本機優先，依 D5 轉交）、`jiezi-local`（只用本機，不轉交）、`jiezi-cloud`（直接第 3 層）。
  Model names select the policy: `jiezi` (auto: local first, escalate per D5), `jiezi-local` (local only), `jiezi-cloud` (tier 3 directly).
- 回應附上 `jiezi` 欄位（非串流在 JSON 內；串流在最後一個事件）：層級、實際模型、驗證結果、延遲、雲端 token 與費用、軌跡 ID。
  Responses carry a `jiezi` field (inside the JSON, or in the last streamed event): tier, actual model, verification, latency, cloud tokens and cost, trajectory ID.
- 請求大小上限（預設 1 MiB），以及每個請求的總時間上限；客戶端中斷時取消上游請求，llama-server 隨即停止生成。
  Request size limit (1 MiB default) and a per-request deadline; when the client disconnects, the upstream request is cancelled and llama-server stops generating.

### D4 — supervisor

- 引擎：v0 只有 `engine-chat`（36101）。核心模型由 `.env` 的 `JIEZI_CORE_MODEL` 指定，填模型清單中的名稱，預設 `qwen3-0.6b-q8_0`；擺放沿用 E0 的規則（整個放 GPU，否則純 CPU，放不下就拒絕）。
  Engines: v0 has `engine-chat` (36101) only. `JIEZI_CORE_MODEL` (a manifest name, default `qwen3-0.6b-q8_0`) picks the core; placement reuses the E0 rule (whole GPU, else CPU only, else refuse).
- 延遲載入：第一個請求才載入；閒置 `JIEZI_IDLE_UNLOAD_S`（預設 900 秒）後卸載，把 GPU 和 RAM 還給系統。每次載入前重算預算（R18.1）。
  Lazy load on the first request; unload after `JIEZI_IDLE_UNLOAD_S` idle seconds (default 900) to return GPU and RAM. Budgets are recomputed before every load (R18.1).
- 健康檢查每 5 秒一次；引擎異常結束時重啟，60 秒內最多 3 次，超過就標記為不可用。不可用時，`jiezi` 模式改走雲端（雲端有開啟的話），`jiezi-local` 回 503 並附原因。
  Health checks every 5 s; on a crash the engine restarts at most 3 times per 60 s, then is marked unavailable. While unavailable, `jiezi` goes to the cloud (if enabled) and `jiezi-local` returns 503 with the reason.
- **與夜間評測協調**：supervisor 在 `var/runtime/state.json` 寫出目前狀態（是否載入、PID、VRAM）。評測載入模型前讀這個檔：引擎有載入時，透過 gateway 的本機管理端點 `POST /admin/unload` 要求卸載，並在之後 `JIEZI_EVAL_HOLD_S`（預設到夜間時段結束）內暫停載入。gateway 狀態寫進評測條件（R17）。
  **Night-evaluation coordination**: the supervisor writes `var/runtime/state.json` (loaded, PID, VRAM). Before loading a model, an evaluation reads it; if the engine is loaded, it calls the gateway's local admin endpoint `POST /admin/unload` and holds loading until the window ends. The gateway state goes into the run conditions (R17).

### D5 — 分層轉交 v0 / Tiered escalation v0

| 層 / Tier | 做法 / Action | 何時 / When |
|---|---|---|
| 0 | 本機回答 / local answer | 預設 / default |
| 1 | 把驗證器的錯誤訊息附在對話後，本機重試一次 / retry locally once with the verifier's error appended | 第 0 層的驗證失敗 / tier-0 verification failed |
| 3 | 雲端完整回答 / full cloud answer | 第 1 層仍失敗、本機引擎不可用，或模型名稱是 `jiezi-cloud` / tier 1 still fails, local engine unavailable, or model `jiezi-cloud` |

執行期驗證器（不需要標準答案）/ Runtime verifiers (no ground truth needed)：
- **工具呼叫**：請求帶有 `tools` 時，回答必須是 OpenAI `tool_calls`，或可用 `verify/tool_call.parse_calls` 解析的呼叫；函式名稱在 `tools` 內，必填參數齊全，型別符合 JSON Schema。
  **Tool calls**: when the request has `tools`, the answer must be OpenAI `tool_calls` or calls parseable by `parse_calls`; names exist in `tools`, required parameters are present, types match the JSON Schema.
- **程式**：回答中的 Python 程式區塊必須能以 `ast.parse` 解析（只解析，不執行）。
  **Code**: Python code blocks in the answer must pass `ast.parse` (parsed only, never run).
- 其他回答（一般問答、摘要）沒有執行期驗證，第 0 層直接回傳；它們之後由路由器（`add-router`）與 RAG 處理。這和計畫 §4.2「閉卷知識題不做自我驗證」一致。
  Other answers (general QA, summaries) have no runtime verification and return at tier 0; the router (`add-router`) and RAG handle them later, consistent with plan §4.2 (no self-verification for closed-book knowledge).

### D6 — 雲端轉交的開關與上限 / Cloud escalation switch and caps

`JIEZI_CLOUD_ESCALATION=off`（預設）。開啟後使用 `.env` 的端點與 `JIEZI_ESCALATION_MODEL`，每日上限 `JIEZI_CLOUD_DAILY_MAX`（預設 200 次）。達到上限時，第 3 層改為回傳本機最佳答案，並在 `jiezi` 欄位註明。費用以 LiteLLM 回報的值為準，沒有回報就記為未知。
`JIEZI_CLOUD_ESCALATION=off` by default. When on, it uses the `.env` endpoint and `JIEZI_ESCALATION_MODEL`, capped by `JIEZI_CLOUD_DAILY_MAX` (200 per day by default). At the cap, tier 3 returns the best local answer instead and says so in the `jiezi` field. Cost is what LiteLLM reports, otherwise unknown.

### D7 — 軌跡 / Trajectories

`var/trajectories/YYYY-MM-DD.jsonl`，每個請求一行：`id`、時間、模型名稱（策略）、請求訊息、每一層的答案、驗證結果、最後層級、實際模型、延遲、token、費用。只存在本機，`var/` 不進版控（R6.4）。`JIEZI_TRAJECTORY=off` 可完全關閉；`JIEZI_TRAJECTORY_RETENTION_DAYS`（預設 0，表示不自動刪除）可設定保留天數。
`var/trajectories/YYYY-MM-DD.jsonl`, one line per request: `id`, time, model name (policy), request messages, each tier's answer, verification, final tier, actual model, latency, tokens, cost. Local only; `var/` is never committed (R6.4). `JIEZI_TRAJECTORY=off` disables it; `JIEZI_TRAJECTORY_RETENTION_DAYS` (default 0 = keep) sets retention.

### D8 — 實作時的補充 / Additions during implementation

- 串流的取捨：請求帶 `tools` 時先完整取得、驗證後再以串流格式送出；沒有 `tools` 時直接轉送本機串流，驗證只事後記錄（`escalation: not_retried_in_streaming`），不重試。
  Streaming: with `tools`, fetch and verify first, then emit in stream format; without `tools`, relay directly and only record verification afterwards (`escalation: not_retried_in_streaming`).
- 雲端失敗時，若已有本機答案就回本機答案（`escalation: cloud_failed`）。
  On cloud failure, return the local answer if there is one (`escalation: cloud_failed`).
- 引擎以 `--alias <核心名稱>` 啟動，回應中的模型名稱不洩漏本機檔案路徑（實測時發現）。
  The engine starts with `--alias <core name>`, so responses never leak the local file path (found in the live test).
- `LocalEngine` 移到 `jiezi/engine.py`，`fresh_facts` 移到 `jiezi/facts.py`；`EvalError` 與共用的 `JieziError` 是同一個類別。
  `LocalEngine` moved to `jiezi/engine.py`, `fresh_facts` to `jiezi/facts.py`; `EvalError` is the same class as the shared `JieziError`.
- Starlette 1.10 對 `starlette.testclient` 搭配 httpx 發出棄用警告（建議改用 `httpx2`）；只影響測試，執行期不受影響，之後升級時再評估。
  Starlette 1.10 warns that `starlette.testclient` with httpx is deprecated (suggesting `httpx2`); tests only, revisit on upgrade.

### D9 — 向 Claude 請教 / Consulting Claude（使用者 2026-11-15 要求 / requested by the user）

- 新策略 `jiezi-ask-claude`：直接請教。
  A new policy `jiezi-ask-claude`: consults directly.
- **自動請教（使用者 2026-11-15 追加：「他自己覺得有需要時不用我同意」）**：`JIEZI_CONSULT_AUTO`（預設開啟）時，`jiezi` 策略在下列情況自行請教 Claude：第 1 層後驗證仍失敗、本機引擎不可用、本機答案是空的、被長度截斷，或開頭 200 字內表示不確定或不知道（`escalation.needs_help`）。本機自己表示不會時不做本機重試。順序：Claude → 雲端（若開啟）→ 本機答案。沒有帶工具的串流已經即時送出，事後才發現需要求助時只記錄、不轉交。
  **Automatic consultation (added by the user on 2026-11-15: "when it thinks it needs to, without my approval")**: with `JIEZI_CONSULT_AUTO` on (default), the `jiezi` policy consults Claude when tier-1 verification still fails, the engine is unavailable, or the local answer is empty, truncated, or says within its first 200 characters that it is unsure or does not know. No local retry for self-reported uncertainty. Order: Claude → cloud (if on) → local answer. A tool-less stream is already sent, so a need found afterwards is only recorded.
- 途徑：本機已登入的 Claude Code CLI 無頭模式（`claude -p --output-format json`），使用者自己的帳號與用量額度，不需另外的 API 金鑰（使用者決定）。實測（2026-11-15）：模型 `claude-opus-5-5`，約 1.7 秒。
  Route: the locally logged-in Claude Code CLI in headless mode, with the user's own account and usage allowance, no extra API key (user decision). Measured on 2026-11-15: model `claude-opus-5-5`, about 1.7 s.
- 安全：`--tools ""`（關閉所有工具）、`--strict-mcp-config` 搭配空的 MCP 設定、`--setting-sources ""`、`--no-session-persistence`，在 `var/runtime/consult-cwd/` 空目錄執行；同時只請教一個問題；逾時 300 秒。
  Safety: all tools off, no MCP, no settings, no session persistence, an empty working directory; one consultation at a time; 300 s timeout.
- 次數：使用者選擇不限（`JIEZI_CONSULT_DAILY_MAX=0`）；額度用完時 CLI 回報錯誤，gateway 回 503 並說明，不重試。
  Volume: unlimited by user choice; when the allowance runs out the CLI errors and the gateway answers 503 with the reason, without retrying.
- **訓練限制**：Anthropic 條款限制用 Claude 的輸出開發或訓練 AI 模型。請教的回答與整筆軌跡標記 `training_use: false`，授權表登記 `claude-consult-output`（訓練：否）；Phase 6 的自我進化必須排除這些紀錄（R18.3、R20）。其他軌跡的 `training_use` 為 `null`，訓練前依授權表判斷。
  **Training restriction**: Anthropic's terms restrict using Claude's outputs to develop or train AI models. Consultation answers and their trajectories carry `training_use: false`, the registry lists `claude-consult-output` (training: no), and Phase 6 self-evolution must exclude them (R18.3, R20). Other trajectories carry `training_use: null`, decided against the registry before training.

## Risks / Trade-offs

- **0.6B 暫代核心的品質很低**：第 1 層重試與雲端轉交會很常觸發。→ 這正好是驗證骨架的好情境；軌跡也會記錄轉交率，作為 G2 的基準。
  **The 0.6B stand-in is weak**: tier-1 retries and escalations will be frequent. → A good stress test of the skeleton; trajectories record the escalation rate as a G2 baseline.
- **軌跡含有使用者的對話內容**：→ 只存本機，可以關閉，也可以設定保留天數；之後如果要用於訓練，依 R20 另行討論。
  **Trajectories hold user conversations**: → local only, can be disabled, retention configurable; any training use is discussed separately under R20.
- **gateway 與夜間評測搶資源**：→ D4 的協調與條件記錄；評測不會在 gateway 載入模型時悄悄改用 CPU。
  **Gateway versus night evaluations**: → D4 coordination and condition records; an evaluation never silently falls back to CPU because the gateway holds the GPU.
- **新增執行期相依套件**：→ R23 查證、`uv.lock` 鎖版本；選項 (c) 可避免相依，但犧牲中斷取消與 HTTP 解析的穩健性。
  **New runtime dependencies**: → R23 checks and `uv.lock` pins; option (c) avoids them at the cost of disconnect cancellation and robust HTTP parsing.

## Decisions on Open Questions（使用者 2026-11-15 / user, 2026-11-15）

- OQ1：Starlette + uvicorn + httpx。/ Starlette + uvicorn + httpx.
- OQ2：雲端轉交預設關閉；開啟時用 `nvidia-nemotron-3-ultra`，每日上限 200 次。/ Off by default; `nvidia-nemotron-3-ultra` when on; 200 per day.
- OQ3：完整保存對話，預設不自動刪除；用於訓練前依 R20 另行討論。/ Full conversations, no automatic deletion; training use discussed under R20 first.
- OQ4：bootstrap 自動產生 `JIEZI_GATEWAY_KEY`。/ Bootstrap generates `JIEZI_GATEWAY_KEY`.

## Open Questions（已決定，保留原文 / decided, kept for the record）

- **OQ1 HTTP 框架**：(a) Starlette + uvicorn + httpx（建議）／(b) aiohttp／(c) 只用標準函式庫。
  **HTTP framework**: (a) Starlette + uvicorn + httpx (recommended) / (b) aiohttp / (c) standard library only.
- **OQ2 雲端轉交**：預設關閉，每日上限 200 次；開啟後用哪個雲端模型（建議 `nvidia-nemotron-3-ultra`，今天可用）？
  **Cloud escalation**: off by default, 200 per day; which cloud model when on (recommend `nvidia-nemotron-3-ultra`, working today)?
- **OQ3 軌跡內容**：完整保存對話內容（之後學習需要），預設不自動刪除；或改成只存雜湊與統計。
  **Trajectory content**: keep full conversations (needed for later learning), no automatic deletion by default; or store hashes and statistics only.
- **OQ4 本機金鑰**：bootstrap 自動產生 `JIEZI_GATEWAY_KEY` 寫進 `.env`（建議），或由使用者自己設定。
  **Local key**: bootstrap generates `JIEZI_GATEWAY_KEY` into `.env` (recommended), or the user sets it.

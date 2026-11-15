## Why

到目前為止，芥子只有評測工具。開發計畫 Phase 4 的平行取樣、分層轉交、路由器，Phase 5 的 RAG 與技能庫，以及 Phase 6 的自我進化，都要掛在同一個「本機入口」上：客戶端送進一個請求，系統決定由本機核心回答還是轉交雲端，並把整個過程記成軌跡。這個骨架和最後選哪個核心模型（G1）無關，可以先做；核心模型確定之前，先用 Qwen3-0.6B 暫代。
So far Jiezi only has evaluation tooling. Phase 4 (parallel sampling, tiered escalation, router), Phase 5 (RAG, skill library) and Phase 6 (self-evolution) all hang off one local entry point: a client sends a request, the system decides whether the local core answers or the cloud takes over, and records the whole exchange as a trajectory. This skeleton does not depend on which core G1 picks, so it can be built now with Qwen3-0.6B as a stand-in core.

## What Changes

- **supervisor**：依資源預算啟動並監控本機引擎（`engine-chat` 36101）；健康檢查、失敗時有上限地重啟；閒置一段時間自動卸載模型，有請求時再載入，避免一直占用 GPU 與 RAM。
  **supervisor**: starts and watches the local engine (`engine-chat` on 36101) within budgets; health checks and bounded restarts; unloads the model after an idle period and reloads on demand, so it does not hold GPU and RAM all the time.
- **gateway**（36100，只綁 `127.0.0.1`）：OpenAI 相容的 `/v1/chat/completions`（含串流）、`/v1/models`、`/health`；需要本機金鑰；客戶端中斷時停止生成。
  **gateway** (36100, `127.0.0.1` only): OpenAI-compatible `/v1/chat/completions` (streaming included), `/v1/models`, `/health`; requires a local key; generation stops when the client disconnects.
- **分層轉交 v0**：開發計畫 §4.2 的四層先實作三層：第 0 層本機回答；第 1 層依執行期驗證器的錯誤訊息在本機重試一次；第 3 層雲端完整回答。第 2 層（只請雲端給回饋）留到之後。執行期驗證器只用**不需要標準答案**的檢查：工具呼叫的格式與 schema（函式存在、必填參數、型別），以及程式碼的語法。
  **Tiered escalation v0**: three of the four tiers in plan §4.2: tier 0 local answer; tier 1 one local retry using the runtime verifier's error message; tier 3 full cloud answer. Tier 2 (cloud feedback only) comes later. Runtime verifiers use only checks **that need no ground truth**: tool-call format and schema (function exists, required parameters, types) and code syntax.
- **軌跡記錄器**：每個請求的問題、本機答案、驗證結果、所在層級、雲端答案、延遲與費用，寫到 `var/trajectories/`（只存本機、不進版控）。這是之後路由器、技能庫與自我進化的資料來源。
  **Trajectory logger**: per request, the question, local answers, verification, tier, cloud answer, latency and cost, written to `var/trajectories/` (local only, never committed). It feeds the later router, skill library and self-evolution.
- 新增 `scripts/jiezi serve`（前景執行，Ctrl-C 會關閉所有引擎）與 `scripts/jiezi status`。
  Add `scripts/jiezi serve` (foreground; Ctrl-C stops every engine) and `scripts/jiezi status`.
- 夜間評測與 gateway 共存：評測開始時，如果 gateway 的引擎還載著模型，評測會先請 gateway 卸載，並把 gateway 的狀態記進執行條件（R17）。
  Night evaluations coexist with the gateway: when an evaluation starts while the gateway's engine holds a model, it asks the gateway to unload first and records the gateway state in the run conditions (R17).

## Non-Goals

- N 條平行取樣與一致率（`add-parallel-sampling`）、學習式路由器（`add-router`）、calibrator（`add-calibrator`）。
  N-way parallel sampling and agreement (`add-parallel-sampling`), the learned router (`add-router`), the calibrator (`add-calibrator`).
- 第 2 層（雲端回饋）、摘要的蘊含驗證（需要本機 NLI 模型或雲端評審）。
  Tier 2 (cloud feedback) and entailment checks for summaries (need a local NLI model or a cloud judge).
- `engine-embed`、RAG（Phase 5）；`jiezi ask / chat` 介面（另一個變更 `add-cli`）。
  `engine-embed`, RAG (Phase 5); the `jiezi ask / chat` interfaces (a separate change, `add-cli`).
- 對外開放：維持只綁 `127.0.0.1`（R6.12）。
  Exposure beyond `127.0.0.1` (R6.12).

## Capabilities

### New Capabilities

- `gateway`：OpenAI 相容的本機入口、驗證、串流、中斷處理。/ The OpenAI-compatible local entry point, auth, streaming, disconnect handling.
- `supervisor`：引擎的啟動、健康檢查、重啟、閒置卸載、與夜間評測的協調。/ Engine start, health, restart, idle unload, and coordination with night evaluations.
- `escalation`：分層轉交 v0 與執行期驗證器。/ Tiered escalation v0 and runtime verifiers.
- `trajectory`：軌跡記錄的格式、保存位置與保留期限。/ Trajectory record format, location and retention.

### Modified Capabilities

（無；評測端的協調寫在 `supervisor`，評測規格不變。）
(None; evaluation-side coordination lives in `supervisor`, the eval spec is unchanged.)

## Impact

- 新增執行期相依套件（design D2；R23 查證；需使用者同意）。目前 `dependencies = []`。
  New runtime dependencies (design D2; R23-checked; needs user approval). Today `dependencies = []`.
- 新檔案：`src/jiezi/runtime/`、`scripts/jiezi`、`tests/test_runtime_*.py`；`.env.example` 增加 gateway 相關設定。
  New files: `src/jiezi/runtime/`, `scripts/jiezi`, `tests/test_runtime_*.py`; `.env.example` gains gateway settings.
- 雲端轉交只有在使用者於 `.env` 開啟時才會呼叫雲端，並有每日上限（design D6）。
  Cloud escalation calls the cloud only when the user enables it in `.env`, with a daily cap (design D6).

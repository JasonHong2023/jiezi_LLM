## Why

芥子之後的每個決策關卡（G1 選核心形式、G2 推論系統、G3 能力外置、G4 自我進化）都要靠同一套題庫與評測框架給出可比較的分數；沒有它，Phase 2 的 E0 實測無從開始。
Every later decision gate (G1 core form, G2 inference system, G3 externalized capabilities, G4 self-evolution) depends on one shared question bank and harness producing comparable scores; without it, the Phase 2 E0 benchmark cannot start.

使用者另於 2026-11-14 指示：長時間的測試一律排在 00:00 之後執行（R18.2a），評測框架必須內建這項排程。
The user also instructed on 2026-11-14 that long test runs happen only after 00:00 (R18.2a), so the harness must build this scheduling in.

## What Changes

- 新增 R0 題庫定義：四類任務（中文問答、寫程式、文件摘要、工具呼叫）各 ≥ 50 題，知識題與推理 / 工具題分開；以鎖定版本的官方來源、固定亂數種子抽題，產生可驗證的鎖定檔。
  Add the R0 bank definition: ≥ 50 items for each of four task types (Chinese QA, coding, document summarization, tool calling), with knowledge items separate from reasoning / tool items; items are drawn with a fixed seed from version-pinned official sources and recorded in a verifiable lock file.
- 摘要題改用**中文維基百科典範條目**自建（使用者 2026-11-14 決定；CNewSum 查不到資料授權），以 revision ID 鎖定內容。
  Summarization items are built from **Chinese Wikipedia featured articles** (user decision 2026-11-14; CNewSum's data license could not be found), pinned by revision ID.
- 新增 `docs/licenses.md` 授權登記表（R18.3），題庫的每個來源都要先讀官方授權檔並登記。
  Add the `docs/licenses.md` license registry (R18.3); every bank source must have its official license read and registered first.
- 新增評測框架：同一份題庫可跑本機 llama.cpp（`llama-server`，只綁 `127.0.0.1`）或任何 OpenAI 相容的雲端端點；輸出分數、t/s、峰值記憶體、token 用量與完整量測條件（R17.1）。
  Add the evaluation harness: the same bank runs against local llama.cpp (`llama-server`, bound to `127.0.0.1` only) or any OpenAI-compatible cloud endpoint, reporting scores, t/s, peak memory, token usage, and full measurement conditions (R17.1).
- 本變更內建兩種評分：選擇題（C-Eval、CMMLU）與知識短答（Chinese SimpleQA，近似比對）；程式、工具呼叫、摘要的評分留給下一個變更 `add-verifiers`，本變更先標為「待驗證器」。
  This change ships two scorers: multiple choice (C-Eval, CMMLU) and short knowledge answers (Chinese SimpleQA, approximate matching); scoring for code, tool calls, and summaries is left to the next change, `add-verifiers`, and is marked "pending verifier" here.
- 新增夜間排程：長時間評測只在夜間時段內啟動新題目，可排程到下一個 00:00 之後自動執行，可中斷後續跑。
  Add night scheduling: long runs start new items only inside the night window, can be scheduled to start automatically after the next 00:00, and resume after interruption.
- 雲端請求有逾時、有限重試與連續失敗暫停機制（使用者指出免費模型有時會卡住），失敗題目可單獨補跑。
  Cloud requests have timeouts, bounded retries, and a pause after consecutive failures (the user noted free models sometimes hang); failed items can be rerun alone.
- 一行指令產生報表：知識題與推理 / 工具題分開、貪婪解碼與多次取樣分開標示（R17.5）。
  Produce a report with one command, separating knowledge from reasoning / tool items and greedy decoding from multi-sample runs (R17.5).

## Non-Goals

- 程式執行沙盒（bubblewrap，使用者 2026-11-14 已選定）、工具呼叫的 ACEBench 規則評分、摘要的蘊含評分：屬於 `add-verifiers`。
  The code-execution sandbox (bubblewrap, chosen by the user on 2026-11-14), ACEBench rule scoring for tool calls, and entailment scoring for summaries belong to `add-verifiers`.
- HumanEval+ / MBPP+ 的中文題述版本：之後另外處理。
  Chinese-language versions of HumanEval+ / MBPP+ come later.
- 完整的雲端 100% 基準線（Phase 1.4）：需要驗證器先完成；本變更只跑已能評分的題型。
  The full cloud 100% baseline (Phase 1.4) needs the verifiers first; this change only runs the item types it can already score.
- 依驗證器挑選最佳樣本（N 條取樣 + 驗證器）：本變更只記錄多個樣本，挑選屬 Phase 4 `sampling`。
  Picking the best sample with verifiers (N samples + verifier): this change only records multiple samples; selection belongs to Phase 4 `sampling`.
- 讓其他電腦連入任何服務：維持只綁 `127.0.0.1`（R6.12；使用者 2026-11-14：「聯外先暫時不開」）。
  Letting other computers connect to any service: everything stays bound to `127.0.0.1` (R6.12; user, 2026-11-14: keep external access closed for now).
- 題目內容進版控：多數來源為 CC BY-NC-SA，只版控來源定義、抽題結果的 ID 與雜湊，題目本身在執行時下載。
  Committing item content: most sources are CC BY-NC-SA, so only source definitions and selected IDs / hashes are versioned; items are downloaded at run time.

## Capabilities

### New Capabilities

- `eval`：R0 題庫（來源、抽題、鎖定檔）、評測後端（本機 llama.cpp、OpenAI 相容雲端）、評分、量測條件記錄、報表、夜間排程。
  `eval`: the R0 bank (sources, sampling, lock file), evaluation backends (local llama.cpp, OpenAI-compatible cloud), scoring, measurement-condition records, reports, and night scheduling.

### Modified Capabilities

（無 / None）

## Impact

- 新增程式 / New code：`src/jiezi/eval/`（Python 標準函式庫，不新增依賴）、`scripts/eval`（bash 入口）。
  `src/jiezi/eval/` (Python stdlib only, no new dependency) and `scripts/eval` (bash entry).
- 新增資料定義 / New data definitions：`eval/banks/r0.toml`、`eval/banks/r0.lock.json`；`docs/licenses.md`。
- 執行期產物 / Run-time outputs：`var/eval/`（題目快取、每次執行的結果與報表，不進版控）；權威基準報表另存 `docs/benchmarks/`（R17.6）。
  `var/eval/` (item cache, per-run results and reports, unversioned); authoritative baseline reports go to `docs/benchmarks/` (R17.6).
- 本機服務 / Local service：評測時啟動的 `llama-server` 使用實驗區段 port（`JIEZI_PORT_BASE + 10`，預設 36110），只綁 `127.0.0.1`。
  The `llama-server` started for evaluation uses the experiment port block (`JIEZI_PORT_BASE + 10`, default 36110), bound to `127.0.0.1` only.
- 新增 `.env` 變數 / New `.env` variable：`JIEZI_NIGHT_WINDOW`（夜間時段，預設 `00:00-07:00`，使用者 2026-11-14 決定）。
  `JIEZI_NIGHT_WINDOW` (night window, default `00:00-07:00`, user decision 2026-11-14).
- 雲端呼叫 / Cloud calls：只在使用者同意的評測中進行（R4、R18.5）；基準量測一律停用 fallback 並核對實際模型（R17.1）。
  Cloud calls happen only in runs the user approves (R4, R18.5); baseline runs always disable fallback and verify the actual model (R17.1).

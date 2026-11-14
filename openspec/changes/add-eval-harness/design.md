## Context

開發計畫 Phase 1 要求：四類任務各 ≥ 50 題的 R0 題庫、同一份題庫可跑任一後端的評測框架、一行指令產生報表（dev-plan §5 Phase 1）。題庫來源的授權已於 2026-11-14 查證（見下表）；摘要題由使用者決定改用中文維基百科自建；程式沙盒選定 bubblewrap（屬 `add-verifiers`）。
Dev-plan Phase 1 calls for an R0 bank of ≥ 50 items per task type, a harness that runs the same bank against any backend, and one-command reports. Source licenses were checked on 2026-11-14 (table below); the user chose self-built Chinese Wikipedia summaries; bubblewrap was chosen for the code sandbox (in `add-verifiers`).

| 來源 / Source | 用途 / Use | 取得位置（鎖定）/ Pinned location | 授權 / License（查證來源）|
|---|---|---|---|
| Chinese SimpleQA | 知識短答 / knowledge short answer | HF `OpenStellarTeam/Chinese-SimpleQA` `chinese_simpleqa.jsonl` @ `336305fc5f1d…` | CC BY-NC-SA 4.0（HF 標籤 ⚠️，實作時讀官方說明） |
| C-Eval（val） | 選擇題 / multiple choice | HF `ceval/ceval-exam` `ceval-exam.zip` @ `3923b519fd180e689d0961bf3a032ece929742f3` | CC BY-NC-SA 4.0（官方 GitHub README） |
| CMMLU | 選擇題 / multiple choice | HF `lmlmcat/cmmlu` `cmmlu_v1_0_1.zip` @ `efcc940752ea…` | CC BY-NC-SA 4.0（官方 GitHub README；HF 標籤寫 BY-NC，以官方為準） |
| HumanEval+ | 程式 / code | GitHub `evalplus/humanevalplus_release` v0.1.10 `HumanEvalPlus.jsonl.gz` | Apache-2.0（`evalplus/evalplus` repo 授權欄位） |
| MBPP+ | 程式 / code | GitHub `evalplus/mbppplus_release` v0.2.0 `MbppPlus.jsonl.gz` | Apache-2.0（同上） |
| ACEBench `data_zh` | 工具呼叫 / tool calls | GitHub `chenchen0103/ACEBench` @ `56dd66cf6439b0d9655ee1b353e4cd745c6f664e` | MIT（repo 授權欄位） |
| 中文維基百科典範條目 / zh Wikipedia featured articles | 摘要 / summarization | 以 revision ID 鎖定 / pinned by revision ID | CC BY-SA 4.0 |

R18.7：C-Eval、CMMLU、Chinese SimpleQA 禁止商用；本專案第一版為研究 / 個人用途。
R18.7: C-Eval, CMMLU, and Chinese SimpleQA forbid commercial use; the first version is research / personal use.

## Goals / Non-Goals

**Goals：**
- 題庫可重現：任何機器以同一份 `r0.lock.json` 取得完全相同的題目（以 SHA-256 驗證）。
  Reproducible bank: any machine gets byte-identical items from the same `r0.lock.json` (verified by SHA-256).
- 後端可替換：本機與雲端走同一個 OpenAI 相容客戶端，結果格式一致。
  Swappable backends: local and cloud share one OpenAI-compatible client and one result format.
- 量測可比較：每次執行都記錄 R17.1 的全部條件。
  Comparable measurements: every run records all R17.1 conditions.
- 不打擾使用者：長時間執行只在夜間時段啟動新題目（R18.2a），且可續跑。
  Never disturb the user: long runs start new items only in the night window (R18.2a) and can resume.

**Non-Goals：** 見 proposal。 / See the proposal.

## Decisions

### D1 — 程式放在 `src/jiezi/`，只用標準函式庫 / Code in `src/jiezi/`, stdlib only

評測程式是產品的一部分（之後的 gateway、router 也會放這裡），所以放在 `src/jiezi/eval/`，由 `scripts/eval` 設定 `PYTHONPATH` 後以 `uv run python -m jiezi.eval` 執行；`scripts/` 保留給建置與安裝工具。資料格式（ZIP 內的 CSV、JSONL、`jsonl.gz`、JSON、HTML）全部用標準函式庫處理。
The harness is part of the product (gateway and router will live here too), so it goes in `src/jiezi/eval/`, run via `scripts/eval` setting `PYTHONPATH` and calling `uv run python -m jiezi.eval`; `scripts/` stays for build and setup tools. All data formats (CSV in ZIP, JSONL, `jsonl.gz`, JSON, HTML) are handled with the stdlib.

- 理由：不新增依賴（R9、R23 查證成本）；已確認所有來源都有非 Parquet 的官方版本。
  Rationale: no new dependency (R9, R23 vetting cost); every source has an official non-Parquet version.
- 替代方案：HF `datasets` 套件（大量傳遞依賴）；`pyarrow` 讀 Parquet（新依賴，且 C-Eval 的官方 ZIP 仍可用鎖定 revision 取得）。
  Alternatives: the HF `datasets` package (many transitive deps); `pyarrow` for Parquet (new dependency, while C-Eval's official ZIP is still available at a pinned revision).

### D2 — 題庫 = 來源定義 + 鎖定檔，題目不進版控 / Bank = source definitions + lock file; items not versioned

`eval/banks/r0.toml` 定義每個來源（網址、鎖定 revision、下載檔 SHA-256、授權登記鍵、題型、知識或推理分組、抽題數）。`scripts/eval bank lock` 依固定種子抽題，寫出 `eval/banks/r0.lock.json`：每題的來源 ID 與正規化後內容的 SHA-256，以及整份題庫的雜湊（`bank_hash`，報表引用）。題目內容快取於 `var/eval/banks/`。
`eval/banks/r0.toml` defines each source (URL, pinned revision, download SHA-256, license-registry key, task type, knowledge vs reasoning group, item count). `scripts/eval bank lock` samples with a fixed seed and writes `eval/banks/r0.lock.json`: each item's source ID and the SHA-256 of its normalized content, plus the whole-bank `bank_hash` cited by reports. Item content is cached in `var/eval/banks/`.

- 理由：多數來源為 CC BY-NC-SA，不在公開 repo 散布內容；ID 與雜湊足以重現並偵測上游變動。
  Rationale: most sources are CC BY-NC-SA, so content is not redistributed in a public repo; IDs and hashes suffice to reproduce and to detect upstream changes.
- 抽題 / Sampling：種子 `20261114`；選擇題依科目分層、平均抽取，避免集中在少數科目。
  Seed `20261114`; multiple-choice items are stratified evenly across subjects.

### D3 — R0 題數 / R0 composition

| 分組 / Group | 來源 / Source | 題數 / Items | 本變更可評分 / Scored here |
|---|---|---|---|
| 知識 / knowledge | Chinese SimpleQA | 50 | ✅ 近似比對 / approximate |
| 知識 / knowledge | C-Eval val | 50 | ✅ 選擇題 / multiple choice |
| 知識 / knowledge | CMMLU | 50 | ✅ 選擇題 / multiple choice |
| 推理・程式 / reasoning · code | HumanEval+ 25、MBPP+ 25 | 50 | ⏳ `add-verifiers` |
| 推理・工具 / reasoning · tools | ACEBench `data_zh`（單輪單函式、單輪平行、atom 類） | 50 | ⏳ `add-verifiers` |
| 推理・摘要 / reasoning · summary | 中文維基典範條目 / zh Wikipedia featured | 50 | ⏳ `add-verifiers` |

C-Eval 的 test 分割沒有公開答案，因此用 val；C-Eval 在 2025 年改為 Parquet 後重新上傳過 val，鎖定的 ZIP 可能沒有那次修正（已知限制，記入報表條件）。
C-Eval's test split has no public answers, so val is used; val was re-uploaded after the 2025 Parquet conversion and the pinned ZIP may lack that fix (known limitation, recorded in report conditions).

### D4 — 中文維基摘要題 / Chinese Wikipedia summary items

以固定 revision 的「典範條目」列表頁為母體，依種子抽 50 篇；每篇以 REST API 取得指定 revision 的 HTML（`zh-tw` 字詞轉換），用 `html.parser` 去除表格、參考文獻、資訊框後取前段落，截斷在約 2,000 字以內的段落邊界。鎖定檔記錄 `revid` 與正規化文字的 SHA-256。參考摘要不在本變更產生；評分以「摘要是否被原文支持」為主（`add-verifiers`）。
The population is the featured-articles list page at a fixed revision; 50 articles are drawn by seed. Each is fetched as HTML at a pinned revision via the REST API (`zh-tw` variant), stripped of tables, references, and infoboxes with `html.parser`, and cut at a paragraph boundary within about 2,000 characters. The lock records `revid` and the SHA-256 of the normalized text. Reference summaries are not produced here; scoring is mainly "is the summary supported by the source" (`add-verifiers`).

- 授權：CC BY-SA 4.0；報表與快取保留條目名稱與 revision 連結作為姓名標示。
  License CC BY-SA 4.0; reports and cache keep the article title and revision link for attribution.

### D5 — 一個 OpenAI 相容客戶端 / One OpenAI-compatible client

本機（`llama-server` 的 `/v1/chat/completions`）與雲端都用同一個 `urllib` 客戶端。雲端端點、金鑰、模型名稱只來自 `.env`（R21.3）。基準模式（`--baseline`）一律帶 `"disable_fallbacks": true`，並在每題核對回應的 `model` 欄位；不符就把該題標為作廢（R17.1）。記錄 `usage`（token 數）與回應時間；本機另讀 `timings.predicted_per_second`。
Local (`llama-server` `/v1/chat/completions`) and cloud share one `urllib` client. Endpoint, key, and model name come only from `.env` (R21.3). Baseline mode (`--baseline`) always sends `"disable_fallbacks": true` and checks each response's `model`; a mismatch voids that item (R17.1). `usage` (tokens) and latency are recorded; locally `timings.predicted_per_second` is also read.

### D6 — 本機引擎管理 / Local engine management

評測時由框架啟動 `llama-server`：`--host 127.0.0.1`、port 為 `JIEZI_PORT_BASE + 10`（被占用就往後找，最多到 `+19`）、`-t` 取 `budgets.cpu.usable_threads`、`nice` 與 `taskset`（沿用 bootstrap 的 `budget_prefix`）、`-ngl` 依參數（預設 0 = 純 CPU）、`--ctx-size` 預設 4096。等待 `/health` 後開始；結束或中斷時一定關閉。每秒取樣 `/proc/<pid>/status` 的 `VmHWM` 與（有 GPU 時）`nvidia-smi` 的程序 VRAM，記錄峰值。
The harness starts `llama-server` with `--host 127.0.0.1`, port `JIEZI_PORT_BASE + 10` (next free up to `+19`), `-t` from `budgets.cpu.usable_threads`, `nice` and `taskset` (reusing bootstrap's `budget_prefix`), `-ngl` from a flag (default 0 = CPU-only), and `--ctx-size` 4096 by default. It waits for `/health`, and always stops the server on exit or interruption. Peak memory comes from sampling `VmHWM` in `/proc/<pid>/status` and, with a GPU, per-process VRAM from `nvidia-smi`, once per second.

### D7 — 評分 / Scoring

- 選擇題：固定提示要求只回答一個字母；從回答中取第一個獨立的 A–D（容許「答案：B」「(B)」等格式）；取不到記為錯並標記 `unparsed`。
  Multiple choice: a fixed prompt asks for a single letter; the first standalone A–D is extracted (allowing forms like 「答案：B」 or "(B)"); none found counts as wrong and is flagged `unparsed`.
- Chinese SimpleQA：官方以 LLM 評審；本變更先用**近似比對**（全半形、標點、空白、繁簡正規化後，標準答案是否出現在回答中），報表明確標示「近似，非官方評分」（R17.5）。LLM 評審留待 `add-verifiers`。
  Chinese SimpleQA: the official scorer is an LLM judge; this change uses **approximate matching** (after width, punctuation, whitespace, and Traditional/Simplified normalization, does the gold answer appear in the response), and reports label it "approximate, not the official scorer" (R17.5). The LLM judge waits for `add-verifiers`.
- 繁簡正規化只用一份隨程式提供的常用字對照表（標準函式庫無此功能）；對照表來源與授權記入 `docs/licenses.md`。
  Traditional/Simplified normalization uses a small bundled character table (the stdlib has none); its source and license go in `docs/licenses.md`.
- 程式、工具、摘要：記錄回答，評分欄位為 `pending_verifier`，報表另列「未評分」數量。
  Code, tools, summaries: responses are recorded with score `pending_verifier`; reports list the unscored count separately.

### D8 — 執行紀錄與續跑 / Run records and resumption

每次執行有一個 `run_id`（時間戳 + 短雜湊），目錄 `var/eval/runs/<run_id>/`：`conditions.json`（R17.1：llama.cpp commit、建置紀錄中的旗標、模型 SHA-256 與量化型別、執行緒與 `affinity_hint`、ctx / batch、取樣參數、`bank_hash`、`budgets` 摘要、日期、雲端實際模型、thinking 開關）、`results.jsonl`（每題一行，逐題 append）、`report.json` 與 `report.md`。`--resume <run_id>` 會略過已有結果的題目；條件不同時拒絕續跑。
Each run has a `run_id` (timestamp + short hash) and directory `var/eval/runs/<run_id>/` holding `conditions.json` (all R17.1 fields, cloud actual model, thinking switch), `results.jsonl` (one line per item, appended as it goes), and `report.json` / `report.md`. `--resume <run_id>` skips items that already have results and refuses to resume under different conditions.

### D9 — 夜間時段與排程 / Night window and scheduling

`JIEZI_NIGHT_WINDOW`（預設 `00:00-07:00`，使用者 2026-11-14 決定，當地時間）定義可啟動新題目的時段。`scripts/eval run` 在時段外拒絕開始（`--now` 可覆寫，僅限使用者明確要求時使用）；執行中超過時段結尾就不再啟動新題，寫好已完成的結果後結束，並提示以 `--resume` 續跑。`scripts/eval schedule <run 參數>` 以 `systemd-run --user --on-calendar=<下一個時段起點 + 5 分>` 建立一次性排程；沒有使用者層級 systemd 時，改用與終端機脫離的背景程序等待到時間再執行。排程與狀態寫入 `var/eval/schedule/`。
`JIEZI_NIGHT_WINDOW` (default `00:00-07:00`, user decision 2026-11-14, local time) defines when new items may start. `scripts/eval run` refuses to start outside it (`--now` overrides, only when the user explicitly asks); once past the window end it starts no new items, writes finished results, exits, and suggests `--resume`. `scripts/eval schedule <run args>` creates a one-shot `systemd-run --user --on-calendar=<next window start + 5 min>` timer; without user-level systemd it falls back to a detached process that sleeps until then. Schedules and state live in `var/eval/schedule/`.

- 限制：電腦關機或 WSL 被關閉時排程不會執行；早上回報時要確認是否真的跑了。
  Limitation: nothing runs if the computer is off or WSL is shut down; the morning report must confirm it actually ran.

### D10 — 提示與模板 / Prompts and templates

每種題型一個固定的中文提示模板，存於 `src/jiezi/eval/prompts.py`，模板內容的雜湊納入 `conditions.json`。訊息以 chat 格式送出，由各後端套用自己的 chat template。
One fixed Chinese prompt template per item type in `src/jiezi/eval/prompts.py`; the template hash is part of `conditions.json`. Messages are sent in chat format and each backend applies its own chat template.

## Risks / Trade-offs

- [近似比對高估或低估 SimpleQA 分數] → 報表明確標示，`add-verifiers` 之後改用 LLM 評審並重算；兩者不得放同一張比較表而不加註（R17）。
  [Approximate matching mis-scores SimpleQA] → clearly labeled; recomputed with an LLM judge after `add-verifiers`; never mixed in one comparison table without annotation (R17).
- [上游來源被刪除或改版] → 以 revision / release 鎖定，下載檔驗 SHA-256；不符就停止並說明，不自動更新。
  [Upstream sources deleted or changed] → pinned by revision / release and SHA-256-verified; on mismatch the tool stops and explains, never auto-updates.
- [維基 HTML 結構改變導致清理結果不同] → 鎖定檔存正規化文字的雜湊，不同就停止；清理規則改動屬題庫改版，需重新產生鎖定檔並記錄。
  [Wikipedia HTML structure changes alter cleaning] → the lock stores the normalized text hash and stops on mismatch; changing cleaning rules is a bank revision that needs a new lock and a record.
- [夜間無人看管時出錯] → 每題結果即時寫入，錯誤寫入 `errors.jsonl`，可續跑；引擎異常結束時整次執行停止而不是無限重試。
  [Failures while nobody is watching] → results are written per item, errors go to `errors.jsonl`, runs resume; if the engine dies the run stops instead of retrying forever.

## Migration Plan

新功能，沒有既有資料需要遷移。回退方式：移除 `src/jiezi/eval/`、`scripts/eval`、`eval/` 與 `var/eval/`。
New capability with nothing to migrate. Rollback: remove `src/jiezi/eval/`, `scripts/eval`, `eval/`, and `var/eval/`.

## Open Questions

（全部已決，見下 / All resolved, see below）

### 已決 OQ1 — 夜間時段 / Resolved OQ1 — Night window

使用者 2026-11-14：暫定 `00:00-07:00`。`JIEZI_NIGHT_WINDOW` 預設值即為此；超過結束時間不再啟動新題，進行中的題目跑完。
User, 2026-11-14: provisionally `00:00-07:00`, which is the `JIEZI_NIGHT_WINDOW` default; no new item starts after the end, the item in progress finishes.

### 已決 OQ2 — Qwen3 思考模式 / Resolved OQ2 — Qwen3 thinking mode

使用者 2026-11-14：照建議，預設關閉（`enable_thinking: false`），`--thinking` 可開啟，並記入 `conditions.json`。
User, 2026-11-14: as proposed, off by default (`enable_thinking: false`), `--thinking` turns it on, recorded in `conditions.json`.

### 已決 OQ3 — 雲端評測 / Resolved OQ3 — Cloud evaluation

使用者 2026-11-14：同意於夜間以雲端基準模型跑 150 題知識題，但「免費模型有時會卡住」→ 依 D11 處理。
User, 2026-11-14: approved running the 150 knowledge items on the cloud baseline at night, noting that "free models sometimes hang" → handled by D11.

### D11 — 卡住與失敗的處理 / Handling hangs and failures

使用者指出免費雲端模型有時會卡住，因此：
Because the user noted that free cloud models sometimes hang:

- 每個請求都有逾時（雲端預設 120 秒，本機預設 600 秒，可用參數調整）；串流以外的請求不會無限等待。
  Every request has a timeout (cloud 120 s, local 600 s by default, adjustable); no request waits forever.
- 逾時、連線錯誤、HTTP 429 / 5xx 時重試，最多 2 次，間隔 10 秒、30 秒（429 若有 `Retry-After` 則照辦，上限 120 秒）。
  Timeouts, connection errors, and HTTP 429 / 5xx are retried at most twice, after 10 s and 30 s (a 429 `Retry-After` is honored up to 120 s).
- 仍失敗就把該題記為 `error_timeout` 或 `error_http`（寫入 `errors.jsonl`），**不計入分數也不算答錯**，繼續下一題。
  If it still fails the item is recorded as `error_timeout` or `error_http` (in `errors.jsonl`), **neither scored nor counted wrong**, and the run moves on.
- 連續 5 題失敗就暫停整次執行（視為服務中斷），保存結果並結束；之後以 `--resume --retry-errors` 只補跑失敗的題目。
  Five consecutive failures pause the run (treated as an outage), saving results and exiting; `--resume --retry-errors` later reruns only the failed items.
- 報表分列失敗題數；失敗題數不為 0 的執行，報表標示「不完整」，不作為權威基準（R17.6）。
  Reports list failed items separately; a run with any failures is labeled "incomplete" and is not an authoritative baseline (R17.6).

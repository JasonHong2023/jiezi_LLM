## Why

`add-eval-harness` 只能評分選擇題與 SimpleQA 近似比對；R0 另一半（程式 50、工具呼叫 50、摘要 50）都標為 `pending_verifier`，推理 / 工具組沒有分數，Phase 1.4 的雲端 100% 基準線與 Phase 2 的 E0 都無法完成。驗證器同時也是 Phase 4「N 條取樣 + 驗證器」的基礎，所以要做成評測以外也能重用的模組。
`add-eval-harness` scores only multiple choice and approximate SimpleQA; the other half of R0 (50 code, 50 tool-call, 50 summary items) stays `pending_verifier`, so the reasoning / tool group has no score and neither the Phase 1.4 cloud 100% baseline nor Phase 2 E0 can finish. Verifiers are also the base of Phase 4 "N samples + verifier", so they must be a module reusable outside evaluation.

## What Changes

- 新增程式沙盒（使用者 2026-11-14 選定 bubblewrap）：無網路、唯讀系統、獨立暫存目錄、記憶體 / 行程數 / 時間上限、遵守資源預算；沙盒不可用時程式題維持 `pending_verifier`，**絕不在沙盒外執行模型產生的程式**。
  Add a code sandbox (bubblewrap, chosen by the user on 2026-11-14): no network, read-only system, private scratch directory, memory / process / time limits, resource budgets respected; when the sandbox is unavailable, code items stay `pending_verifier` — **model-generated code never runs outside the sandbox**.
- 新增程式驗證器：HumanEval+ / MBPP+ 依 evalplus 的判定方式（標準解答在同一沙盒產生期望輸出，再比對候選程式的輸出），基本測試與 plus 測試分開記錄。
  Add the code verifier: HumanEval+ / MBPP+ judged the evalplus way (expected outputs come from the canonical solution in the same sandbox, then candidate outputs are compared), base and plus tests recorded separately.
- 新增工具呼叫驗證器：移植 ACEBench（鎖定 commit）`normal` 類別的規則判定；以 Python `ast` 解析回答，**不執行**回答內容。
  Add the tool-call verifier: a port of ACEBench's rule checker for the `normal` categories (pinned commit); responses are parsed with Python `ast`, **never executed**.
- 新增 LLM 評審：Chinese SimpleQA 官方評審方式（正確 / 錯誤 / 未作答），以及摘要的忠實度（逐句是否有原文支持）與涵蓋度；評審模型、提示雜湊與回覆都記錄並快取，評審結果與近似比對分開列。
  Add the LLM judge: the official Chinese SimpleQA grading (correct / incorrect / not attempted) and summary faithfulness (each sentence supported by the article or not) and coverage; judge model, prompt hash and replies are recorded and cached, and judged results are listed apart from approximate matching.
- 摘要另有不需模型的規則檢查：字數是否在 100–150 字、是否為繁體中文。
  Summaries also get model-free rule checks: length within 100–150 characters, and written in Traditional Chinese.
- 新增 `scripts/eval verify <run_id>`：對已完成的執行**事後**評分，不必重跑模型；所以 2026-11-15 夜間那次本機執行的回答可以直接補評分。驗證屬長時間工作時一樣遵守夜間時段（R18.2a）。
  Add `scripts/eval verify <run_id>`: scores a finished run **after the fact** without rerunning the model, so the answers from the 2026-11-15 night run can be scored directly. Long verification obeys the night window like any long job (R18.2a).

## Non-Goals

- 用驗證器挑選最佳樣本、自我修正迴圈：Phase 4 `sampling`。
  Picking the best sample with verifiers, self-repair loops: Phase 4 `sampling`.
- 本機的評審模型（例如 NLI 小模型）：需要 PyTorch，延到 Phase 3。本變更的評審只用雲端（需使用者同意）。
  A local judge model (e.g. a small NLI model): needs PyTorch, deferred to Phase 3. Judging here uses the cloud only (with user consent).
- ACEBench 的 `special`（無法回答 / 缺參數）與 `agent`（多輪模擬）類別：R0 沒有抽這些題。
  ACEBench `special` (unanswerable / missing parameters) and `agent` (multi-turn simulation) categories: R0 does not include them.
- 對外開放任何服務：維持只綁 `127.0.0.1`（R6.12）。
  Exposing any service: everything stays bound to `127.0.0.1` (R6.12).

## Capabilities

### New Capabilities

- `verifiers`：程式沙盒、程式 / 工具呼叫 / 摘要規則驗證器、LLM 評審（含快取與條件記錄）；評測與之後的取樣都可呼叫。
  `verifiers`: the code sandbox, code / tool-call / summary rule verifiers, and the LLM judge (with caching and condition records); callable from evaluation and later sampling.

### Modified Capabilities

- `eval`：`Scoring` 需求改為由驗證器評分程式、工具與摘要題，並新增事後評分（`verify`）與報表中的評審條件。依賴 `add-eval-harness` 先歸檔。
  `eval`: the `Scoring` requirement now scores code, tool and summary items through the verifiers, and adds after-the-fact scoring (`verify`) and judge conditions in reports. Requires `add-eval-harness` to be archived first.

## Impact

- 新增程式 / New code：`src/jiezi/verify/`（標準函式庫，不新增 Python 依賴）；`src/jiezi/eval/` 接上驗證器。
  `src/jiezi/verify/` (stdlib, no new Python dependency); `src/jiezi/eval/` wired to the verifiers.
- 新增系統元件 / New system component：bubblewrap（取得方式待使用者決定，見 design OQ1——Ubuntu 24.04 套件目前帶有未修正的 CVE-2026-87766）。bootstrap 的 prereqs 檢查加入 `bwrap`（選用；缺少時只停用程式驗證）。
  bubblewrap (how to obtain it is for the user to decide, design OQ1 — the Ubuntu 24.04 package currently carries the unfixed CVE-2026-87766). The bootstrap prereqs check gains `bwrap` (optional; missing only disables code verification).
- 授權 / Licenses：移植 evalplus（Apache-2.0）與 ACEBench（MIT，保留版權行）程式邏輯、引用 Chinese SimpleQA 評審提示前，都要讀官方授權並登記於 `docs/licenses.md`（R18.3）。
  Before porting evalplus (Apache-2.0) and ACEBench (MIT, keeping the copyright line) logic or reusing the Chinese SimpleQA judge prompt, read the official licenses and register them in `docs/licenses.md` (R18.3).
- 雲端呼叫 / Cloud calls：LLM 評審約 100 題 × 每次執行（SimpleQA 50 + 摘要 50），只在使用者同意後、夜間進行（R4、R18.5）。
  The LLM judge makes about 100 calls per run (50 SimpleQA + 50 summaries), only with user consent and at night (R4, R18.5).

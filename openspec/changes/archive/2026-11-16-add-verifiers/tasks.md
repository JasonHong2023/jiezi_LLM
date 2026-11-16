## 0. 前置 / Prerequisites

- [x] 0.1 `add-eval-harness` 的 6.2 / 6.3 完成並歸檔（本變更修改 `eval` 規格）/ `add-eval-harness` 6.2 / 6.3 done and archived (this change modifies the `eval` spec)
- [x] 0.2 使用者決定 OQ1（bubblewrap 取得方式）與 OQ2（評審模型、呼叫量）/ User decides OQ1 (bubblewrap source) and OQ2 (judge model, call volume)

## 1. 授權登記 / License registry

- [x] 1.1 讀 evalplus（v0.3.1）、ACEBench（`56dd66cf…`）的官方授權與判定原始碼，Chinese SimpleQA 評審提示的授權；登記或更新 `docs/licenses.md`；bubblewrap（查證為 LGPL-2.1-or-later）登記 / Read official licenses and judging sources; register in `docs/licenses.md`

## 2. 沙盒 / Sandbox

- [x] 2.1 依 OQ1 取得 bubblewrap（(a) 透過彈出 sudo 視窗安裝；(b) `scripts/setup` 從鎖定 tag 建置到 `var/tools/`）；bootstrap prereqs 加入選用的 `bwrap` 檢查 / Obtain bubblewrap per OQ1; add an optional `bwrap` prereq check
- [x] 2.2 `src/jiezi/verify/sandbox.py`：bwrap 參數、cgroup 或 rlimit 上限、實際時間上限、輸出上限、預算核心；自我檢查（不能連網、不能寫家目錄）；測試逾時、記憶體爆量、fork 炸彈、連網與寫入被擋 / Sandbox with limits and self-test; test timeout, memory blow-up, fork bomb, blocked network and writes

## 3. 驗證器 / Verifiers

- [x] 3.1 `verify/code.py`：程式碼擷取、標準解答期望輸出（快取）、逐筆比對（`atol`）、`base_pass` / `plus_pass`；以官方範例對照測試 / evalplus-style code judging; cross-check with official samples（以標準解答當候選驗證全部通過；在本機執行上游程式做逐題對照被自動權限模式擋下 / canonical solutions pass as candidates; running upstream code locally for side-by-side checks was blocked by the auto-permission mode）
- [x] 3.2 `verify/tool_call.py`：`ast` 解析（只接受字面值）、ACEBench normal 規則；以 ACEBench repo 的範例回答對照測試 / ACEBench normal rules; cross-check with repo samples（手寫案例；另經使用者 2026-11-15 同意，`scripts/eval xcheck-tool` 在沙盒內執行官方判定程式（鎖定 commit 與 SHA-256），逐題對照 29 個手寫案例與本機執行的回答，結果待夜間 / hand-written cases; with user consent on 2026-11-15, `scripts/eval xcheck-tool` runs the official checker inside the sandbox (pinned commit and SHA-256) side by side on 29 hand-written cases and the run's responses, results pending tonight）
- [x] 3.3 `verify/summary_rules.py`：字數與簡體字檢查；測試邊界值 / Length and simplified-character checks; test edges
- [x] 3.4 `verify/judge.py`：SimpleQA 與摘要評審、JSON 解析與重試、模型核對、快取、D11 逾時與暫停；以本機假伺服器測試 / LLM judge with caching and D11 handling; test with a local fake server

## 4. 評測整合 / Harness integration

- [x] 4.1 驗證器一律經 `scripts/eval verify <run_id>` 事後評分（執行期仍記為 `pending_verifier`，避免沙盒與評審干擾量測）（`verifications.jsonl`、`--only`、夜間時段規則）；`.env.example` 加 `JIEZI_JUDGE_MODEL` / Dispatch to verifiers; add `verify`; add `JIEZI_JUDGE_MODEL`
- [x] 4.2 報表：程式（base / plus）、工具（含 `unparsed`）、摘要（忠實度、涵蓋度、字數、簡體字分開）、SimpleQA（官方評審與近似比對並列）、驗證器版本、沙盒設定、評審條件、已知差異 / Report sections and conditions

## 5. 驗證 / Verification（長時間工作一律 00:00 之後）

- [x] 5.1 單元測試全部通過（231 個）；`openspec validate add-verifiers --strict` / Unit tests and strict validation
- [x] 5.2 立即執行（秒級）：對 2026-11-15 本機執行做工具呼叫與摘要規則評分 / Immediate (second-scale): tool-call and summary-rule scoring of the 2026-11-15 local run（工具 17/50；摘要字數合格 0/50、無簡體字 33/50 / tool 17/50; summary length 0/50, no simplified 33/50）
- [x] 5.3 排程到 00:00 之後：本機執行的程式題沙盒評分；ACEBench 官方對照（`disagree` 須為 0 或已修正）；經同意後的評審（本機執行 + 雲端基準的 SimpleQA）；人工複核 10 題評審結果 / After 00:00: sandboxed code scoring; judge runs with consent; hand-check 10 judged items

  - 5.3（2026-11-16）：本機程式題沙盒評分完成；ACEBench 官方對照 0 不一致（手寫 29 題：agree 26、known_crash 1、upstream_limit 1、known_eval 1）；評審：本機執行以 Nemotron、雲端知識基準以 deepseek（雲端推理基準用 Nemotron 會被自我偏好保護拒絕，改 deepseek）。
    人工複核 10 題 SimpleQA 評審（本機 0.6B，種子 20261116 抽樣）：10/10 與人工判斷一致（8 incorrect、1 correct「LD50」、1 not_attempted「抗微生物藥」對「喹諾酮類」——過於籠統但不矛盾，依 SimpleQA 規則屬未作答）。
    Hand-check: 10/10 judge verdicts agree with manual review.

## Context

`add-eval-harness` 會把每一題的回答寫進 `var/eval/runs/<run_id>/results.jsonl`。程式、工具、摘要題的狀態是 `pending_verifier`，SimpleQA 只做了近似比對。題目資料已保留驗證需要的欄位：evalplus 有完整紀錄，ACEBench 有 `ground_truth`，維基題有條目全文。
`add-eval-harness` writes every response to `var/eval/runs/<run_id>/results.jsonl`; code, tool and summary items are `pending_verifier`, and SimpleQA has approximate matching only. Item data already keeps what verification needs (full evalplus records, ACEBench `ground_truth`, article text).

執行環境（2026-11-15 查證）：WSL2 核心可建立非特權 user namespace（`unshare -Ur` 成功）。核心沒有 AppArmor 的 userns 限制。使用者層 cgroup 已委派 `cpu memory pids` 三個控制器。
Environment (checked 2026-11-15): the WSL2 kernel allows unprivileged user namespaces (`unshare -Ur` works), has no AppArmor userns restriction, and the user cgroup delegates `cpu memory pids`.

## Goals / Non-Goals

**Goals：**
- 模型產生的程式只在沙盒內執行：沙盒沒有網路，不能寫入家目錄與專案目錄。
  Model-generated code runs only inside the sandbox: no network, no write access to home or the project.
- 判定方式忠於官方：evalplus 和 ACEBench 的邏輯盡量逐行移植，有差異就寫進報表。
  Judging stays faithful to the official tools: evalplus and ACEBench logic is ported as closely as possible, and any difference is written into the report.
- 可事後評分且可重現：同一份回答加上同一版驗證器，一定得到同一個分數（LLM 評審除外，它以快取保證重現）。
  After-the-fact and reproducible: the same responses plus the same verifier version give the same score (the LLM judge excepted, which is made reproducible by caching).

**Non-Goals：** 見 proposal。 / See the proposal.

## Decisions

### D1 — 模組位置：`src/jiezi/verify/` / Module location

`sandbox.py`、`code.py`（evalplus）、`tool_call.py`（ACEBench）、`summary_rules.py`、`judge.py`。每個驗證器的輸入都是題目和回答，輸出統一為 `{"status", "score", "details", "verifier": "<名稱>@<版本>"}`。`eval/scoring.py` 依 `scorer` 欄位分派到對應的驗證器。
`sandbox.py`, `code.py` (evalplus), `tool_call.py` (ACEBench), `summary_rules.py`, `judge.py`. Every verifier takes `(item, response)` and returns `{"status", "score", "details", "verifier": "<name>@<version>"}`; `eval/scoring.py` dispatches on `scorer`.

- 理由：Phase 4 的取樣器會直接呼叫同一套驗證器，不經過評測框架。
  Rationale: the Phase 4 sampler calls the same verifiers directly, without the harness.

### D2 — 沙盒 / Sandbox

每次執行建立一個獨立的暫存目錄 `work/`，然後以下列參數啟動 `bwrap`：
Per execution: create a fresh scratch `work/`, then run `bwrap` with:

```
--unshare-all --die-with-parent --new-session --clearenv
--ro-bind /usr /usr  (+ /lib /lib64 /bin 的符號連結 / symlinks)
--ro-bind <python 前綴 / prefix> <同路徑 / same path>   # sys.base_prefix，由 uv 管理 / uv-managed
--proc /proc --dev /dev --tmpfs /tmp
--bind <work> /work --chdir /work
--setenv PATH /usr/bin:/bin --setenv PYTHONDONTWRITEBYTECODE 1
python3 -I -S /work/run.py
```

- 不掛載家目錄、專案目錄、`/etc/resolv.conf`，也沒有網路命名空間以外的介面。
  Home, the project and `/etc/resolv.conf` are not mounted, and there are no network interfaces beyond the empty namespace.
- 資源上限：如果有 `systemd-run --user --scope`，就加上 `-p MemoryMax=1G -p TasksMax=64 -p CPUQuota=100%` 由 cgroup 強制。沒有 systemd 時改用 `RLIMIT_AS`（1 GiB）、`RLIMIT_CPU` 和 `RLIMIT_FSIZE`（16 MiB）。不使用 `RLIMIT_NPROC`，因為在 user namespace 裡它仍以真實 UID 計數，會被使用者自己的其他程序影響。外層一律另設實際時間上限，標準輸出最多讀 1 MiB。程序再透過 `budget_prefix` 綁到預算核心並設定 `nice`（R18.2）。
  Limits: with `systemd-run --user --scope` available, `-p MemoryMax=1G -p TasksMax=64 -p CPUQuota=100%` enforced by cgroups; otherwise `RLIMIT_AS` (1 GiB), `RLIMIT_CPU`, `RLIMIT_FSIZE` (16 MiB). `RLIMIT_NPROC` is not used: inside a user namespace it still counts the real UID and would be skewed by the user's other processes. An outer wall-clock limit always applies, stdout is capped at 1 MiB, and `budget_prefix` pins to budget cores with `nice` (R18.2).
- 啟動前自我檢查：在沙盒內嘗試連線 `127.0.0.1:<LiteLLM port>`，並嘗試寫入家目錄。兩者都必須失敗，否則停用程式驗證並在報表說明原因。
  Self-test before use: inside the sandbox, try connecting to `127.0.0.1:<LiteLLM port>` and writing to home; both must fail, otherwise code verification is disabled with the reason reported.
- 沙盒不可用（沒有 `bwrap`、自我檢查失敗）：程式題標為 `pending_verifier`，`details.reason` 記錄原因。沒有不經沙盒的後備路徑。
  Sandbox unavailable (no `bwrap`, failed self-test): code items stay `pending_verifier` with `details.reason`; there is no unsandboxed fallback.
- 替代方案：只用 `unshare`（util-linux，已安裝）加上手動掛載。這要自行處理 pivot_root，等於重寫 bwrap，容易出錯。Docker/podman 需要常駐服務或較重的依賴，也違背使用者的選擇。
  Alternatives: `unshare` (util-linux, present) with manual mounts means hand-rolling pivot_root, effectively rewriting bwrap; Docker/podman needs a daemon or heavier dependencies and contradicts the user's choice.

### D3 — 程式判定（evalplus）/ Code judging

依 evalplus 的做法：在沙盒內先以 `canonical_solution` 對 `base_input` 和 `plus_input` 產生期望輸出，再執行候選程式並逐筆比對。浮點數比對使用題目資料的 `atol`。每筆輸入有獨立的時間上限，候選程式的時間上限是標準解答耗時 × 係數，並有最低值。係數和最低值以 evalplus 原始碼為準，實作時讀鎖定版本。程式碼從回答中的 ```python 區塊擷取；沒有區塊就把整段回答當作程式碼，並在 `details` 標記。
Following evalplus: inside the sandbox, the `canonical_solution` produces expected outputs for `base_input` and `plus_input`, then the candidate runs and outputs are compared per input, floats with the item's `atol`. Each input has its own time limit (canonical time × factor, with a floor; factor and floor taken from the pinned evalplus source). Code is extracted from the ```python block in the response, or the whole response with a `details` flag when there is none.

- 結果記錄 `base_pass`、`plus_pass`。`score` 等於 `plus_pass`（plus 測試包含 base 測試，也就是 evalplus 的「+」分數）。
  Records `base_pass` and `plus_pass`; `score` = `plus_pass` (plus includes base, the evalplus "+" score).
- 期望輸出以題目雜湊為鍵快取在 `var/verify/expected/`，每題只需產生一次。
  Expected outputs are cached in `var/verify/expected/` keyed by item hash, so each is produced once.

### D4 — 工具呼叫判定（ACEBench）/ Tool-call judging

回答以 `ast.parse` 解析成 `[函式(參數=值, …)]` 清單，只接受字面值（`ast.literal_eval` 的範圍），任何其他節點都視為無法解析。比對規則移植自 ACEBench 鎖定 commit 的 normal 類別檢查器：函式名稱、必要參數、型別和值，以及並行呼叫的順序規則。字串的正規化方式依原始碼。狀態分為 `correct`、`wrong`、`unparsed`。
The response is parsed with `ast.parse` into a `[func(arg=value, …)]` list accepting only literals (the `ast.literal_eval` subset); any other node is unparseable. Matching rules are ported from the normal-category checker at the pinned ACEBench commit (function name, required args, types and values, order rules for parallel calls; string normalization per the source). Statuses: `correct`, `wrong`, `unparsed`.

- 理由：回答內容永遠不執行，所以這類題目不需要沙盒。
  Rationale: the response is never executed, so no sandbox is needed.

### D5 — LLM 評審 / LLM judge

- SimpleQA：使用官方評審提示，判定為 `correct`、`incorrect` 或 `not_attempted`，報表依官方算出 correct、not attempted 比例與 F-score。前提是授權允許；不允許就自寫提示，並在報表標示「非官方」。
  SimpleQA: the official judge prompt (if its license allows; otherwise our own prompt labeled "unofficial"), verdicts `correct` / `incorrect` / `not_attempted`, reporting correct, not-attempted rate and F-score as officially defined.
- 摘要：評審先把摘要拆成句子，逐句判斷是否有原文支持，得到**忠實度**（被支持的句數 ÷ 總句數）。再判斷摘要是否涵蓋原文開頭導言的主要事實，得到**涵蓋度**（0–2 分）。兩個分數分開列出，不合併。
  Summaries: the judge splits the summary into sentences and marks each as supported by the article or not → **faithfulness** (supported ÷ total); then judges whether the main facts of the article's lead section are covered → **coverage** (0–2). Listed separately, never merged.
- 評審的輸出格式固定為 JSON。解析失敗就重試一次，仍失敗則標為 `judge_unparsed`，不計分。
  Judge output is fixed-format JSON; one retry on parse failure, then `judge_unparsed` (not scored).
- 評審模型由 `JIEZI_JUDGE_MODEL` 指定，不得與被評的模型相同，以避免模型偏好自己的回答。評審請求同樣停用 fallback 並核對實際模型。溫度為 0。
  Judge model from `JIEZI_JUDGE_MODEL`, never the model under evaluation (self-preference); fallback disabled and the actual model verified like baseline runs; temperature 0.
- 快取鍵為（題目雜湊、回答雜湊、評審模型、提示雜湊），同一組只呼叫一次，重跑報表不會再呼叫。
  Cache keyed by (item hash, response hash, judge model, prompt hash); each combination is called once and rerunning reports does not call again.
- 逾時、重試和連續失敗暫停沿用 eval D11。
  Timeouts, retries and the consecutive-failure pause reuse eval D11.

### D6 — 摘要規則檢查 / Summary rule checks

- 字數：去除空白後計算字數，100–150 字為合格，報表列出分布。
  Length: characters excluding whitespace; 100–150 passes, distribution reported.
- 繁體：使用已登記的 OpenCC 表。如果有字出現在繁轉簡表的「值」側、卻不在「鍵」側（也就是只屬於簡體的字），就判定為「含簡體字」，並列出這些字。
  Traditional script: with the registered OpenCC table, characters that appear only on the value side of the T→S table (simplified-only) mark the summary as "contains simplified characters", listing them.

### D7 — 事後評分 `verify` / After-the-fact `verify`

`scripts/eval verify <run_id> [--only code|tool|summary|simpleqa] [--now]` 讀取 `results.jsonl`，把驗證結果寫入獨立的 `verifications.jsonl`，原始回答不改動。報表合併兩者，並列出驗證器版本、沙盒設定與評審條件。需要評審或程式題數量多時，`verify` 屬於長時間工作，遵守夜間時段，也可以排入 `schedule --job`。只做工具呼叫和摘要規則檢查屬秒級，可以立即執行。
Reads `results.jsonl`, appends results to a separate `verifications.jsonl` (raw responses untouched); reports merge both and list verifier versions, sandbox settings and judge conditions. With judging or many code items, `verify` is a long job, obeys the night window and can be queued with `schedule --job`; tool-call and summary-rule-only verification is second-scale and may run immediately.

## Risks / Trade-offs

- [bubblewrap CVE-2026-87766] Ubuntu 24.04 的套件在 USN-8779-2 撤回了修正，目前仍有漏洞。這個漏洞發生在沙盒建立階段：可控制掛載路徑的人能透過符號連結在沙盒外建立檔案。我方的 bwrap 參數是固定的，模型程式在建立完成後才執行，因此**推論**模型程式無法利用它；但官方頁面沒有明說攻擊前提。→ OQ1 交給使用者決定。
  The Ubuntu 24.04 package reverted the fix (USN-8779-2) and is vulnerable. The flaw is in sandbox setup (whoever controls mount paths can create files outside via symlinks). Our bwrap arguments are fixed and model code runs after setup, so we **infer** model code cannot exploit it, but the official pages do not state the precondition. → OQ1 for the user.
- [評審偏差 / Judge bias] 免費雲端模型當評審本身就有誤差。→ 評審模型、提示雜湊與每題理由全部記錄；R0 抽 10 題人工複核，列入報表。
  Free cloud judges are imperfect. → Record judge model, prompt hash and per-item rationale; hand-check 10 items of R0 and list them in the report.
- [免費模型卡住 / Free models hanging] 沿用 eval D11，失敗的題目不計分，可補跑。
  Reuses eval D11; failures are unscored and can be rerun.
- [移植偏差 / Porting drift] 移植的判定邏輯可能和官方不同。→ 用官方 repo 的範例回答做對照測試，有差異就寫入報表的「已知差異」。
  Ported judging may differ from upstream. → Cross-check with sample answers from the official repos; differences go into a "known differences" report section.

## Decisions on Open Questions（2026-11-15，使用者）

- **OQ1 → 從上游原始碼建置**。使用者選 (b)；後續查到上游已有 v0.13.1（2026-10-14，同樣含修正），經使用者同意改鎖定 v0.13.1（commit `362936ae`）。系統前置 `libcap-dev`、`pkgconf` 經同意以 sudo 視窗安裝；meson 1.12.1 由 uv 管理。R23 查證見 `openspec/specs/stack.md` §4。
  OQ1 → build from upstream source; with the user's consent pinned to v0.13.1 (also fixed); `libcap-dev` and `pkgconf` installed via the sudo window with consent.
- **OQ2 → `nvidia-deepseek-v4.1-flash`**（使用者從候選中選定；與基準模型 Nemotron 不同家族）。評審在夜間進行。
  OQ2 → `nvidia-deepseek-v4.1-flash` (chosen by the user; a different family from the Nemotron baseline). Judging runs at night.
- 實作時的補充 / Implementation notes：
  - 摘要的簡體字判定改用 OpenCC `STCharacters.txt`：簡轉繁候選不含自己的字才算簡體（「后、台、干、表、里、面」也是正體字，用繁轉簡表會誤判）。
    The simplified-character check uses OpenCC `STCharacters.txt` (a character is simplified-only when its S→T candidates exclude itself); the T→S table misflags shared forms.
  - 期望輸出以不透明位元組保存，主程式從不 unpickle 沙盒產生的資料。
    Expected outputs are kept as opaque bytes; the host never unpickles sandbox output.
  - 移植版與官方程式的逐題對照（在本機執行上游程式）被自動權限模式擋下，改以照官方邏輯手寫的測試案例驗證。
    Running the upstream checkers locally for a side-by-side comparison was blocked by the auto-permission mode; hand-written cases that follow the upstream logic are used instead.

## Open Questions（原始問題 / as originally asked）

- **OQ1（需使用者決定）bubblewrap 的取得方式 / How to obtain bubblewrap：**
  - (a) `sudo apt install bubblewrap`：取得 0.9.0-1ubuntu0.3。這版有 CVE-2026-87766，但以我方的使用方式推論無法被模型程式利用。Ubuntu 釋出完整修正後由 `apt upgrade` 自動更新。
    Gets 0.9.0-1ubuntu0.3, which carries CVE-2026-87766; for our usage we infer model code cannot exploit it, and `apt upgrade` picks up Ubuntu's complete fix when it ships.
  - (b) 從上游原始碼建置已修正的 0.12.0，鎖定 tag 與 SHA，安裝到專案的 `var/tools/`（非 setuid）。需要 `sudo apt install libcap-dev`；meson 和 ninja 可以用 uv 安裝。R23 合規最乾淨，換到別台電腦也一致，代價是多一個建置步驟要維護。
    Build the fixed 0.12.0 from upstream source, pinned by tag and SHA, into the project's `var/tools/` (not setuid). Needs `sudo apt install libcap-dev`; meson/ninja come via uv. Cleanest for R23 and portable; costs one more build step to maintain.
  - 建議 (b)：R23 寫明「禁止目前有重大資安問題的技術」，(a) 的 CVSS 是 8.8。
    Recommend (b): R23 forbids technologies with current major security issues, and (a) is CVSS 8.8.
- **OQ2（需使用者同意）評審模型與呼叫量 / Judge model and call volume：** 每次執行約 100 次評審呼叫，夜間進行。評審模型建議用 LiteLLM 上與基準模型不同家族的免費模型，實作時列出候選讓使用者選。
  About 100 judge calls per run, at night; suggest a free LiteLLM model from a different family than the baseline, with candidates listed at implementation for the user to choose.

## Context / 背景

Jiezi already has an `add-web-read` capability and an MCP tool interface, but it has no JavaScript rendering, adaptive selector recovery, or anti-bot inspection path. / 芥子已有 `add-web-read` 能力與 MCP 工具介面，但沒有 JavaScript 渲染、自適應 selector 修復或反爬檢查路徑。

Scrapling `0.5.1` is an existing Python scraping framework with an official MCP server and Agent Skill. PyPI shows Python `>=3.10` and `BSD-3-Clause`. OSV has no advisory for Scrapling itself; direct dependencies have advisories at the declared minimums, with fixed versions available (`anyio>=4.14.2`, `mcp>=2.2.0`). A third-party static audit of v0.4.15 reports 17 severity-labelled findings; the visible excerpt includes a scalar-XPath crash, and the full findings are not verified. / Scrapling `0.5.1` 是現成 Python 爬蟲框架，官方附 MCP server 與 Agent Skill；PyPI 顯示 Python `>=3.10`、`BSD-3-Clause`。OSV 對本體無通報，但直接相依在宣告的最低版有通報，已有修復版（`anyio>=4.14.2`、`mcp>=2.2.0`）。第三方 v0.4.15 靜態稽核有 17 項 severity 標記，可見摘錄含純量 XPath crash，完整 findings 未查證。

This change is a **planning artifact only**; it does not install Scrapling, start a server, or modify runtime code. / 本變更**只是規劃產物**；不安裝 Scrapling、不啟動服務、不改執行期程式。

## Goals / Non-Goals

**Goals / 目標：**

- Classify the integration as MCP and document why SKILL and core integration are rejected. / 將整合分類為 MCP，並記錄為何拒絕 SKILL 與核心整合。
- Define a disabled-by-default tool registration path with a minimal allowlist. / 定義預設關閉的工具註冊路徑與最小白名單。
- Define URL, content, resource, and audit guardrails before any real fetch is allowed. / 在允許任何真實抓取前定義 URL、內容、資源與稽核護欄。
- Record dependency/security gates and explicit removal conditions. / 記錄相依／資安關卡與明確移除條件。

**Non-Goals / 不做的範圍：**

- No installation, PoC execution, or runtime code change in this change. / 本變更不安裝、不執行 PoC、不改執行期程式。
- No login, session persistence, CAPTCHA solving, paywall bypass, or proxy rotation for evasion. / 不做登入、session 保存、CAPTCHA 破解、付費牆繞過或規避用的代理輪替。
- No new listening port, cloud dependency, core-model change, or Phase 0–8 schedule change. / 不新增監聽連接埠、雲端相依、核心模型變更或 Phase 0–8 時程變更。

## Decisions / 決策

### 1. Classify as MCP / 分類為 MCP

Scrapling's browser/stealth engine is an external capability with its own process lifecycle and tool protocol; Jiezi SHALL consume its official MCP server over stdio. / Scrapling 的瀏覽器／stealth 引擎是有獨立行程生命週期與工具協定的外部能力；芥子 SHALL 透過 stdio 使用其官方 MCP server。

Alternatives considered: / 已考量替代方案：

- **SKILL** — rejected: skill text is procedural knowledge and can be overridden by injected content; it cannot provide the browser engine by itself. / **SKILL** — 不採：技能文字是程序知識，可能被注入內容覆寫，且本身不提供瀏覽器引擎。
- **Core module** — rejected: it would add a heavy optional dependency and browser binaries to the tiny core and blur the existing no-network-tool boundary. / **核心模組** — 不採：會把重型可選相依與瀏覽器二進位帶進極小核心，並模糊既有「無網路工具」邊界。
- **Reimplement fetcher** — rejected: an official maintained MCP server already exists; reimplementation wastes effort and forks security responsibility. / **重寫抓取器** — 不採：官方已有維護中的 MCP server，重寫會浪費心力並分叉資安責任。

### 2. Opt-in and stdio only / 明確啟用且只用 stdio

The adapter SHALL be disabled unless the user explicitly enables it in local configuration. Transport SHALL be stdio; no TCP/UDP listener and no port outside R11. / 除非使用者在本機設定明確啟用，adapter SHALL 保持關閉。transport SHALL 只有 stdio；不開 TCP/UDP listener，也不使用 R11 以外的連接埠。

### 3. Minimal allowlist / 最小工具白名單

Only tool names that pass the PoC and policy tests SHALL be registered. The other official tools SHALL remain unavailable even if the MCP server advertises them. / 只有通過 PoC 與政策測試的工具名稱 SHALL 被註冊。即使 MCP server 廣播其他工具，也 SHALL 保持不可用。

### 4. Fetch as untrusted data / 抓取結果視為不可信資料

Fetched text SHALL pass through the existing injection guard and be length-capped before reaching the model or memory. No fetched content SHALL become a skill, grant, or training datum. / 抓取文字 SHALL 先通過既有 injection guard 並做長度上限才進入模型或記憶。抓取內容 SHALL NOT 成為技能、grant 或訓練資料。

### 5. Conditional security gate / 附條件資安關卡

Adoption is blocked until fixed versions are pinned and OSV/`pip-audit`/license checks pass. The visible third-party audit is treated as a risk signal, not proof of current 0.5.1 defect. / 在鎖定修復版並通過 OSV／`pip-audit`／授權檢查前不得採用。可見的第三方稽核視為風險訊號，不當作 0.5.1 現存缺陷的證明。

## Risks / Trade-offs / 風險與取捨

- [Known advisories in minimum dependency versions] → pin `anyio>=4.14.2`, `mcp>=2.2.0`, re-run OSV and `pip-audit`; block adoption on High/Critical unfixed findings (R23.2). / [最低相依版有已知通報] → 鎖定修復版、重跑 OSV 與 `pip-audit`；未修復 High/Critical 即阻斷採用（R23.2）。
- [Third-party audit incomplete] → do not claim full clearance; require manual review of the full findings before enabling stealth/browser tools. / [第三方稽核不完整] → 不宣稱全面通過；啟用 stealth／瀏覽器工具前須人工讀完完整 findings。
- [Browser process consumes RAM/CPU] → keep the adapter opt-in, cap concurrency and response size, and never start it in unit tests. / [瀏覽器行程吃 RAM/CPU] → 保持明確啟用、限制並行與回應大小，單元測試不啟動。
- [Fetched pages carry prompt injection] → existing injection guard, data-only handling, no skill/training promotion. / [抓取頁面帶提示注入] → 既有 injection guard、僅資料處理、不升格為技能或訓練資料。
- [Site policy and privacy] → public `http`/`https` only, no login or evasion features; document that users must obey site terms. / [網站政策與隱私] → 只用公用 `http`／`https`，不做登入或規避功能；文件提醒使用者遵守網站條款。
- [MCP tool surface too broad] → allowlist and audit every call; unlisted tools never reach the agent. / [MCP 工具表面過大] → 白名單並稽核每次呼叫；未列工具不進代理。

## Migration Plan / 遷移計畫

1. Review and approve this proposal, design, specs, and tasks. / 審閱並核准本提案、設計、規格與任務。
2. Implement only the policy/adapter scaffolding and unit tests; no network in tests. / 只實作政策／adapter 骨架與單元測試；測試不連網路。
3. Run an isolated PoC in a disposable venv with fixed dependency pins and only authorized practice sites. / 在可拋棄 venv 以固定修復版相依、只打授權練習站執行隔離 PoC。
4. Re-run OSV, `pip-audit`, license check, OpenSpec strict validation, and the full unit suite. / 重跑 OSV、`pip-audit`、授權檢查、OpenSpec strict 驗證與全量單元測試。
5. Rollback by leaving the switch off and removing the optional adapter/dependency group; no data migration. / 關閉開關並移除可選 adapter／相依群組即可回滾；無資料遷移。

## Open Questions / 待確認問題

- Should the PoC allow the stealth/JS tool in the allowlist, or validate only the static fetch tool first? / PoC 要允許 stealth／JS 工具進白名單，還是先只驗證靜態抓取工具？（R15：代價不同，交使用者決定）
- Should the optional dependency group be named `scrapling` or `web-fetch`? / 可選相依群組要叫 `scrapling` 還是 `web-fetch`？（命名與未來替換空間取捨）
- If the full third-party audit contains unresolved High/Critical findings, should the whole change be dropped or limited to static fetch only? / 若完整第三方稽核仍有未解 High/Critical，整案放棄還是縮到靜態抓取？（R15）

### R19.4 決策更新（2026-11-19 15:43；上方 Open Questions 保留作歷史）

1. **Stealth／JS 納入 PoC allowlist / stealth/JS in PoC allowlist** — 使用者選擇「也允許 stealth／JS」。通過 URL、allowlist、輸出上限與稽核政策後，stealth／JS 工具 SHALL 可在隔離 PoC 註冊與量測；login state、CAPTCHA、paywall、proxy rotation 仍為 Non-Goals。/ Stealth/JS SHALL be registrable in the isolated PoC after policy checks; evasion features remain excluded.
2. **雙可選群組與回退 / dual optional groups and fallback** — 使用者選擇兩個群組都存在，`web-fetch` 首選、`scrapling` 回退。`web-fetch` 沿用既有 `httpx==0.28.1` 做靜態抓取，不新增重型相依；`scrapling` 承擔 JS／stealth 與 `web-fetch` 不可用時的回退。選擇順序：`web-fetch` → `scrapling`（需通過相同政策與 R23.2 關卡）。/ Selection order SHALL be `web-fetch` then `scrapling`, with identical policy and security gates.
3. **未解 High／Critical 不放棄抓取 / unresolved findings do not end the fetch goal** — 使用者選擇「盡可能找出方法抓取不放棄」。這是目標導向，不是安全豁免：受影響後端 SHALL 保持關閉，直到修補版、上游修正、替代合規 MCP、隔離 venv 內有限 PoC 或既有 `add-web-read` 靜態路徑可行；所有替代方案 SHALL 回報使用者，且不得 silent bypass R23.2。/ This is goal-preserving, not a security waiver.
4. 更新後的 migration plan：先宣告雙群組與後端選擇，再進行 PoC；PoC 同時量測靜態、JS／stealth 與 `web-fetch` 失效回退；最後才決定是否預設啟用。/ The migration plan is updated accordingly.

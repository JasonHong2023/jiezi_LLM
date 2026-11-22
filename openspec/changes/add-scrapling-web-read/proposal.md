## Why / 動機

Jiezi can read ordinary web pages today, but JavaScript-heavy pages, changed selectors, and anti-bot checks still leave gaps in the existing `add-web-read` path. / 芥子目前能讀一般網頁，但 JavaScript 渲染頁面、selector 改版與反爬檢查仍讓既有 `add-web-read` 路徑有缺口。

Scrapling is an existing Python framework with an official MCP server and Agent Skill; this change classifies it and defines the guardrails before any adoption, as required by the Agent-feature rule and R4. / Scrapling 是現成的 Python 框架，官方已提供 MCP server 與 Agent Skill；本變更依 Agent 功能開發規則與 R4，先完成分類與護欄定義，再談採用。

## What Changes / 變更內容

- **Classification: MCP, not SKILL and not core.** / **分類：MCP，不是 SKILL，也不是核心模組。**
  - An external browser/stealth stack belongs in an isolated MCP process, not in the tiny core or in overridable skill text. / 外部瀏覽器與 stealth  Stack 應放在隔離的 MCP 行程，不進極小核心，也不放進可被文字覆寫的技能內容。
  - Scrapling already ships an MCP server and Agent Skill; Jiezi SHALL consume the existing MCP server instead of reimplementing it. / Scrapling 已有官方 MCP server 與 Agent Skill；芥子 SHALL 使用現成 MCP server，不重新實作。
- Add an **opt-in, disabled-by-default** MCP tool registration for Scrapling. / 新增 **預設關閉、需明確啟用** 的 Scrapling MCP 工具註冊。
  - No new listening port; transport SHALL be stdio only. / 不新增監聽連接埠；連線 SHALL 只用 stdio。
  - Only the minimal tool subset validated by the PoC SHALL be registered; the remaining official tools SHALL stay unregistered. / 只註冊 PoC 驗證過的最小工具子集；其餘官方工具 SHALL 不註冊。
- Add URL and response policy for every fetch call. / 為每次抓取加入 URL 與回應政策。
  - Allow only `http`/`https` public hosts; SHALL reject private/loopback/link-local addresses, credentials in URLs, and non-HTTP schemes. / 只允許 `http`／`https` 公用主機；SHALL 拒絕私人／loopback／link-local 位址、URL 內憑證與非 HTTP schema。
  - SHALL NOT save login state, solve or bypass CAPTCHAs, bypass paywalls, or rotate proxies to evade site policy. / SHALL NOT 保存登入態、解或繞過 CAPTCHA、繞過付費牆，也不 SHALL 用代理輪替規避網站政策。
  - Fetch results SHALL be treated as untrusted data and passed through the existing injection guard; response size and timeout SHALL be capped. / 抓取結果 SHALL 當作不可信資料並通過既有 injection guard；回應大小與逾時 SHALL 有上限。
- Add dependency and security gates before adoption. / 在採用前加入相依與資安關卡。
  - Pin `anyio>=4.14.2` and `mcp>=2.2.0`; re-run OSV, `pip-audit`, and licensing checks in the PoC. / 鎖定 `anyio>=4.14.2` 與 `mcp>=2.2.0`；PoC 時重跑 OSV、`pip-audit` 與授權檢查。
  - Record an explicit removal condition and a kill switch. / 記錄明確的移除條件與關閉開關。
- Add documentation and tests that do not require network, GPU, browser binaries, or cloud keys. / 新增不需網路、GPU、瀏覽器二進位或雲端金鑰的文件與測試。

### Non-Goals / 不做的範圍

- No Scrapling dependency in the default install, core process, or systemd gateway unit. / 不把 Scrapling 相依放進預設安裝、核心行程或 systemd gateway 單元。
- No write, shell, or general network tool beyond the approved fetch tool. / 不新增寫入、shell 或一般網路工具，只保留核准後的抓取工具。
- No login, session persistence, proxy rotation, CAPTCHA solving, or paywall bypass. / 不做登入、session 保存、代理輪替、CAPTCHA 破解或付費牆繞過。
- No new port, no remote bind, and no change to R11 port allocation. / 不新增連接埠、不對外綁定，也不改 R11 連接埠配置。
- No change to `qwen3.5-4b-q4_k_m`, P1–P8, D1–D12, G1–G5, or the Phase 0–8 schedule. / 不改 `qwen3.5-4b-q4_k_m`、P1–P8、D1–D12、G1–G5 或 Phase 0–8 主時程。
- No SKILL as the primary integration; a SKILL may only document how a human invokes the approved MCP tool. / 不以 SKILL 作為主要整合方式；SKILL 最多只文件化人工如何呼叫已核准的 MCP 工具。

## Capabilities / 能力

### New Capabilities / 新增能力

- `scrapling-mcp`: an optional, opt-in external MCP fetch capability with tool allowlist, URL policy, untrusted-output handling, audit fields, and explicit removal criteria. / 可選、需明確啟用的外部 MCP 抓取能力，含工具白名單、URL 政策、不可信輸出處理、稽核欄位與明確移除條件。

### Modified Capabilities / 修改能力

- `tools`: add the requirement that an optional external MCP tool is registered only when explicitly enabled, policy-checked, and limited to an allowlisted subset. / 新增要求：可選外部 MCP 工具只有在明確啟用、通過政策檢查且限於白名單子集時才註冊。

## Impact / 影響

- Evidence / 證據：[本機查證] PyPI 2026-11-19：Scrapling `0.5.1`，`requires_python >=3.10`，`BSD-3-Clause`。OSV 對 `scrapling` 本體查詢為空。
- Evidence / 證據：[本機查證] OSV 對 Scrapling 直接相依查詢：`lxml 6.1.1`、`orjson 3.11.8`、`curl_cffi 0.16.3`、`protego 0.7.0`、`markdownify 1.2.0` 無命中；`anyio 4.14.0` 命中 High（GHSA-82r6-8w77-94w6，修復於 `4.14.2`），`mcp 2.0.0` 命中 High（GHSA-5h93-6whr-6q8j、GHSA-w4fh-qvv9-3v23，修復於 `2.2.0`）。因此最低版本 SHALL 提升為修復版。
- Evidence / 證據：[本機查證] CISA KEV 目前 1,786 筆；上述三個 GHSA 的 CVE 對應查無 KEV 命中。
- Evidence / 證據：[原文] 第三方靜態稽核樣本為 v0.4.15／commit `196c81a`（2026-09-02），有 17 項 severity 標記；可見摘錄指出 `Selector.xpath()` 對純量 XPath 會 crash，完整 findings 未查證。
- Code / 程式：新增可選 MCP adapter 與政策模組（預計 `src/jiezi/tools/`），新增設定開關（`.env.example`）與文件；不改核心模型路徑與 gateway 對外 API。/ Add an optional MCP adapter and policy module (expected under `src/jiezi/tools/`), a config switch in `.env.example`, and docs; do not change the core model path or gateway public API.
- Tests / 測試：政策單元測試（URL、白名單、輸出大小、注入字串）不需網路；真實抓取只放在人工執行的隔離 PoC。/ Policy unit tests (URL, allowlist, response cap, injection strings) need no network; real fetching stays in a manual isolated PoC.
- Security classification / 資安分類：符合 R23.2 的附條件通過——必須鎖定修復版並在 PoC 重跑 OSV／`pip-audit`；未通過則不得啟用。/ Conditional R23.2 pass only after pinning fixed versions and re-running OSV/`pip-audit` in the PoC; otherwise the tool SHALL stay disabled.
- Removal / 移除：關閉開關後移除 adapter、可選相依群組與文件章節即可；無資料遷移，無 port 或 model 狀態需要清理。/ Disable the switch, then remove the adapter, optional dependency group, and docs; no data migration, port, or model state cleanup.

### R19.4 決策更新（2026-11-19 15:43；保留上方原文）

- **Q1 — PoC allowlist / PoC 白名單**：使用者決定「也允許 stealth／JS」。PoC allowlist SHALL 包含已通過政策檢查的 stealth／JS 工具；但仍不做登入態保存、CAPTCHA 破解、付費牆繞過或代理輪替規避，且只打公開頁面與授權練習站／challenge demo。/ The PoC allowlist SHALL include policy-approved stealth/JS tools; login state, CAPTCHA, paywall, and proxy-rotation evasion remain prohibited.
- **Q2 — 相依群組 / dependency groups**：使用者決定「兩個都存在，`web-fetch` 無法使用時切換到 `scrapling`」。因此 SHALL 宣告 `web-fetch` 與 `scrapling` 兩個可選群組；`web-fetch` 為首選靜態抓取後端，沿用既有 `httpx==0.28.1`，不新增重型套件；`scrapling` 為回退與 JS／stealth 後端，兩個群組都不進預設安裝。/ Both optional groups SHALL exist; `web-fetch` is the preferred static backend and `scrapling` is the fallback/JS backend.
- **Q3 — 未解 High／Critical / unresolved findings**：使用者決定「盡可能找出方法抓取不放棄」。這不授予繞過 R23.2 的權限：若完整稽核仍有未修補 High／Critical，受影響後端 SHALL 保持關閉，但專案 SHALL 繼續尋找合規替代路徑（修補版、上游修正、隔離 venv 內有限 PoC、其他合規 MCP、既有 `add-web-read` 靜態路徑或人工授權抓取），並把選項回報使用者；不得直接放棄抓取目標，也不得 silent bypass。/ The project SHALL keep seeking a compliant fetch path and SHALL NOT bypass R23.2 or abandon the fetch objective.
- Impact / 影響：新增後端選擇與回退邏輯、更新政策 allowlist、更新 PoC 量測與文件；不改分類（仍為 MCP）、不改核心模型、不新增 port、不允許寫入／shell／一般網路工具。/ Add backend selection/fallback, policy allowlist, PoC measurements, and docs; classification, model, ports, and tool boundaries are unchanged.

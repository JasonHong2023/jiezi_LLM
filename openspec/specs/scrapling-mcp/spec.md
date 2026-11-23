# scrapling-mcp Specification

## Purpose
TBD - created by archiving change add-scrapling-web-read. Update Purpose after archive.
## Requirements
### Requirement: Opt-in MCP registration / 明確啟用才註冊 MCP

The system SHALL NOT register any Scrapling MCP tool unless the user explicitly enables the capability in local configuration. / 除非使用者在本機設定明確啟用該能力，系統 SHALL NOT 註冊任何 Scrapling MCP 工具。

#### Scenario: Disabled by default / 預設關閉

- **WHEN** the capability switch is absent or false. / **WHEN** 能力開關不存在或為 false。
- **THEN** no Scrapling tool appears in the tool registry and no MCP process is started. / **THEN** 工具登錄中不出現 Scrapling 工具，也不啟動 MCP 行程。

#### Scenario: Explicitly enabled / 明確啟用

- **WHEN** the user sets the capability switch to true. / **WHEN** 使用者把能力開關設為 true。
- **THEN** the adapter registers only tools that pass policy validation and the allowlist. / **THEN** adapter 只註冊通過政策驗證與白名單的工具。

### Requirement: stdio-only transport / 只用 stdio transport

The Scrapling MCP connection SHALL use stdio only and SHALL NOT open a TCP or UDP listener. / Scrapling MCP 連線 SHALL 只用 stdio，SHALL NOT 開啟 TCP 或 UDP listener。

#### Scenario: No port allocation / 不配置連接埠

- **WHEN** the adapter starts. / **WHEN** adapter 啟動時。
- **THEN** it uses stdin/stdout for MCP frames and allocates no port outside R11. / **THEN** 使用 stdin/stdout 傳 MCP 訊框，不配置 R11 以外的連接埠。

### Requirement: Minimal tool allowlist / 最小工具白名單

The adapter SHALL register only the validated tool subset and SHALL NOT expose other tools advertised by the MCP server. / adapter SHALL 只註冊通過驗證的工具子集，SHALL NOT 暴露 MCP server 廣播的其他工具。

#### Scenario: Unlisted tool ignored / 未列工具被忽略

- **WHEN** the MCP server advertises a tool outside the allowlist. / **WHEN** MCP server 廣播白名單以外的工具。
- **THEN** the tool is not registered and cannot be called by the agent. / **THEN** 該工具不註冊，代理無法呼叫。

### Requirement: Public URL policy / 公用 URL 政策

Every fetch call SHALL allow only public `http`/`https` hosts and SHALL reject private, loopback, link-local, non-HTTP schemes, and credentials embedded in the URL. / 每次抓取 SHALL 只允許公用 `http`／`https` 主機，SHALL 拒絕私人、loopback、link-local、非 HTTP scheme 與 URL 內嵌憑證。

#### Scenario: Loopback URL rejected / loopback URL 被拒

- **WHEN** a fetch request targets `http://127.0.0.1/` or another private address. / **WHEN** 抓取請求指向 `http://127.0.0.1/` 或其他私人位址。
- **THEN** the adapter rejects the call before starting the MCP fetch and records a policy denial. / **THEN** adapter 在啟動 MCP 抓取前拒絕呼叫，並記錄政策拒絕。

#### Scenario: Credentials in URL rejected / URL 內憑證被拒

- **WHEN** a fetch URL contains `user:password@host`. / **WHEN** 抓取 URL 含 `user:password@host`。
- **THEN** the adapter rejects the call and does not forward the URL. / **THEN** adapter 拒絕呼叫，不轉送該 URL。

### Requirement: No evasion or session persistence / 不做規避或 session 保存

The adapter SHALL NOT expose or enable login-state saving, CAPTCHA solving, paywall bypass, or proxy rotation for evading site policy. / adapter SHALL NOT 暴露或啟用登入態保存、CAPTCHA 破解、付費牆繞過或為規避網站政策的代理輪替。

#### Scenario: Evasion capability advertised / 規避能力被廣播

- **WHEN** the MCP server advertises a stealth, login-state, or proxy-rotation tool. / **WHEN** MCP server 廣播 stealth、登入態或代理輪替工具。
- **THEN** the adapter leaves it unregistered and logs that it was filtered. / **THEN** adapter 保持不註冊，並記錄已過濾。

### Requirement: Untrusted output handling / 不可信輸出處理

Fetched content SHALL be treated as untrusted data, passed through the existing injection guard, length-capped, and timeout-bounded before reaching the model or memory. / 抓取內容 SHALL 當作不可信資料，通過既有 injection guard、長度上限與逾時限制後才進入模型或記憶。

#### Scenario: Injection text in page / 頁面含注入文字

- **WHEN** a fetched page contains "ignore previous rules". / **WHEN** 抓取頁面含「忽略先前規則」。
- **THEN** the text is sanitized as data, no grant or skill is changed, and the existing injection guard remains active. / **THEN** 文字以資料形式淨化，不改變 grant 或技能，既有 injection guard 保持生效。

#### Scenario: Oversized response / 回應過大

- **WHEN** a fetch response exceeds the configured byte cap or timeout. / **WHEN** 抓取回應超過設定位元組上限或逾時。
- **THEN** the adapter truncates or aborts the fetch and records the limit in the audit entry. / **THEN** adapter 截斷或中止抓取，並在稽核紀錄記載限制。

### Requirement: Dependency security gate / 相依資安關卡

The capability SHALL remain disabled unless fixed dependency versions are pinned and OSV, `pip-audit`, and license checks pass. / 除非鎖定修復版相依且 OSV、`pip-audit` 與授權檢查通過，該能力 SHALL 保持關閉。

#### Scenario: Unfixed High advisory / 未修復 High 通報

- **WHEN** OSV or `pip-audit` reports an unfixed High or Critical advisory in a required dependency. / **WHEN** OSV 或 `pip-audit` 回報必要相依有未修復 High 或 Critical 通報。
- **THEN** the capability stays disabled and the finding is reported for user decision. / **THEN** 能力保持關閉，並回報該 finding 交使用者決策。

### Requirement: Audit without content / 稽核但不記內容

Each fetch call SHALL write an audit entry containing tool name, host, policy decision, status, byte count, and timestamps, and SHALL NOT write fetched page content or secrets. / 每次抓取 SHALL 寫入含工具名稱、主機、政策決定、狀態、位元組數與時間的稽核紀錄，SHALL NOT 寫入抓取頁面內容或機密。

#### Scenario: Successful fetch audited / 成功抓取被稽核

- **WHEN** a fetch completes successfully. / **WHEN** 抓取成功完成。
- **THEN** the audit entry contains the required fields and no page body. / **THEN** 稽核紀錄含必要欄位且不含頁面本文。

### Requirement: Kill switch and removal / 關閉開關與移除

The system SHALL provide a configuration switch that disables registration and startup without code changes, and removal SHALL NOT require data migration. / 系統 SHALL 提供設定開關，免改程式即可停用註冊與啟動；移除 SHALL NOT 需要資料遷移。

#### Scenario: Switch turned off / 開關關閉

- **WHEN** the user disables the switch after a previous enablement. / **WHEN** 使用者在先前啟用後關閉開關。
- **THEN** no Scrapling tool is registered on the next start and existing audit records remain readable. / **THEN** 下次啟動不註冊 Scrapling 工具，既有稽核紀錄仍可讀。

### Requirement: Preferred backend and fallback / 首選後端與回退（R19.4）

The system SHALL declare both `web-fetch` and `scrapling` optional dependency groups. / 系統 SHALL 宣告 `web-fetch` 與 `scrapling` 兩個可選相依群組。

- `web-fetch` SHALL be the preferred static backend and SHALL reuse the existing `httpx==0.28.1` runtime dependency without adding a heavy package. / `web-fetch` SHALL 是首選靜態後端，並 SHALL 重用既有 `httpx==0.28.1`，不新增重型套件。
- `scrapling` SHALL be the fallback backend when `web-fetch` is unavailable or when a policy-approved JS/stealth fetch is required. / `scrapling` SHALL 是回退後端，用於 `web-fetch` 不可用或需要政策核准的 JS／stealth 抓取。
- Both backends SHALL pass the same URL, allowlist, untrusted-output, audit, and dependency-security policies. / 兩個後端 SHALL 通過相同的 URL、白名單、不可信輸出、稽核與相依資安政策。

#### Scenario: Preferred backend available / 首選後端可用

- **WHEN** `web-fetch` is available and the page is a public static page. / **WHEN** `web-fetch` 可用且頁面是公用靜態頁面。
- **THEN** the system uses `web-fetch` and starts no Scrapling MCP process. / **THEN** 系統使用 `web-fetch`，不啟動 Scrapling MCP 行程。

#### Scenario: Preferred backend unavailable / 首選後端不可用

- **WHEN** `web-fetch` cannot start or cannot fetch a public page. / **WHEN** `web-fetch` 無法啟動或無法抓取公用頁面。
- **THEN** the system falls back to `scrapling` only if the opt-in switch is on and the Scrapling policy/security gates pass. / **THEN** 只有在 opt-in 開關開啟且 Scrapling 政策／資安關卡通過時，系統才回退到 `scrapling`。

#### Scenario: JS or stealth required / 需要 JS 或 stealth

- **WHEN** a public page requires JavaScript rendering or stealth/JS to return content. / **WHEN** 公用頁面需要 JavaScript 渲染或 stealth／JS 才有內容。
- **THEN** `scrapling` SHALL be selectable for the PoC after passing the same policy and audit requirements. / **THEN** `scrapling` SHALL 可在通過相同政策與稽核要求後用於 PoC。

### Requirement: Stealth/JS PoC allowance / PoC 允許 stealth/JS（R19.4，優先於前述過濾情境）

Notwithstanding the earlier filtered-evasion scenario, the policy-approved stealth/JS tool SHALL be included in the PoC allowlist after the explicit user decision. / 雖有前述過濾情境，依使用者明確決策，通過政策檢查的 stealth／JS 工具 SHALL 納入 PoC 白名單。

#### Scenario: Stealth/JS tool registered / stealth/JS 工具被註冊

- **WHEN** the MCP server advertises a stealth or JavaScript-rendering tool and it passes URL, allowlist, output-cap, and audit checks. / **WHEN** MCP server 廣播 stealth 或 JavaScript 渲染工具，且通過 URL、白名單、輸出上限與稽核檢查。
- **THEN** the tool is registered for the isolated PoC and recorded in the audit entry. / **THEN** 工具註冊供隔離 PoC 使用，並寫入稽核紀錄。

#### Scenario: Evasion features still rejected / 規避功能仍被拒

- **WHEN** a tool is for login-state saving, CAPTCHA solving, paywall bypass, or proxy rotation to evade site policy. / **WHEN** 工具用於登入態保存、CAPTCHA 破解、付費牆繞過或規避代理輪替。
- **THEN** it remains unregistered even when stealth/JS is allowed. / **THEN** 即使允許 stealth／JS，該工具仍不註冊。

### Requirement: Unresolved advisory response / 未解通報處理（R19.4）

When a backend has an unfixed High/Critical advisory, that backend SHALL stay disabled. / 當後端有未修補 High／Critical 通報時，該後端 SHALL 保持關閉。

#### Scenario: Keep fetching goal without bypass / 不放棄抓取且不繞過

- **WHEN** `scrapling` is blocked by an unfixed High/Critical advisory. / **WHEN** `scrapling` 被未修補 High／Critical 通報擋下。
- **THEN** the system SHALL keep the `web-fetch` path available, evaluate compliant alternatives, report options to the user, and SHALL NOT bypass R23.2 or abandon the web-read objective. / **THEN** 系統 SHALL 保留 `web-fetch` 路徑、評估合規替代、回報選項給使用者，SHALL NOT 繞過 R23.2，也不放棄 Web 讀取目標。

#### Scenario: Compliant fix found / 找到合規修正

- **WHEN** a patched version, upstream fix, or compliant alternate MCP passes OSV, `pip-audit`, and license checks. / **WHEN** 修補版、上游修正或合規替代 MCP 通過 OSV、`pip-audit` 與授權檢查。
- **THEN** the backend SHALL be re-evaluated for enablement under the same allowlist and audit policy. / **THEN** 該後端 SHALL 在相同白名單與稽核政策下重新評估是否啟用。


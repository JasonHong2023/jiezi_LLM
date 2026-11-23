# add-agent-approval 提案 / Proposal

> **狀態 / Status**：提案（2026-11-23，OpenCode worker W7 初稿，主控審查更正）。使用者 2026-11-23 指示「我不管規則想辦法開發完成」，主控依建議定案 Q1–Q7（Q5 改為顯示完整內容並以 sha256 綁定核准 token）。A6 為高風險，排在 A5／A8 之後實作；實作只含「在已授權資料夾內建立新檔案」一個寫入工具。

## Why / 為什麼

目前系統僅有唯讀工具（`list_dir`、`find_files`、`read_file`、`file_info`）與授權機制（`grants.py`），缺乏 **per-action 核准** 能力。依開發計畫 §15.5 A6：

- **R4 核准後才施工**：任何寫入／shell／網路工具必須在使用者明確核准後才能執行
- **未核准任何寫入／shell／網路工具**：預設全部拒絕
- **每次高風險動作都有明確核准**：preview、dry-run、rollback、audit reason、revoke 完整鏈路

此提案為 **高風險項目**，採保守策略：先只實作 **單一可逆寫入工具**（在已授權資料夾內建立新檔案，不可覆寫、不可刪除），其餘寫入／shell／網路功能列為 Non-Goals，待後續提案逐步開放。

The system currently has only read-only tools and a grant mechanism, but lacks **per-action approval**. Per §15.5 A6 of the dev plan:
- **R4 approval before implementation**: Any write/shell/network tool must execute only after explicit user approval
- **No write/shell/network tools without approval**: Default deny all
- **Every high-risk action has explicit approval**: Full chain of preview, dry-run, rollback, audit reason, revoke

This is a **high-risk item** requiring a conservative approach: implement only **one reversible write tool** (create new file in granted folder, no overwrite, no delete), with all other write/shell/network capabilities as Non-Goals for future proposals.

---

## What Changes / 變更內容

1. **核准狀態機**：`proposed → previewed → approved/denied/expired → applied → rolled_back`
2. **核准請求持久化**：JSONL 格式，含 `id`、`tool`、`arguments`、`reason`、`status`、`token`、`expires_at`、`created_at`、`applied_at`、`rolled_back_at`、`backup_path`
3. **一次性核准 token**：UUID v4，單次使用後失效，防重放
4. **逾時機制**：預設 5 分鐘，可配置；逾時自動轉 `expired`
5. **Rollback 備份**：寫入前自動備份（新檔案無需備份，刪除/覆寫時需備份），保留 7 天（可配置），存放於 `var/agent/approvals/backups/`
6. **稽核欄位擴充**：`reason`（核准/拒絕理由）、`approval_id`、 `token_used`、 `outcome`
7. **單一可逆寫入工具**：`write_file`（僅限已授權資料夾、僅建立新檔、不可覆寫、不可刪除）
8. **CLI/Web 核准介面**：`scripts/jiezi agent approve <id> --allow|--deny --reason "..."`，並預留桌面網頁介面端點

---

## Non-Goals / 非目標

| 項目 | 說明 |
|------|------|
| 覆寫既有檔案 | 需另提案，風險更高 |
| 刪除檔案/資料夾 | 需另提案，不可逆 |
| Shell 指令執行 | 需另提案，攻擊面極大 |
| 網路請求工具 | 需另提案，涉外部連線 |
| 批次核准 | 先做單次，再考慮批次 |
| 自動核准規則 | 違反「明確核准」原則 |
| 多工具單一核准 | 先一對一，再考慮群組 |

---

## Capabilities / 能力分類判定

| 能力 | 分類 | 理由 |
|------|------|------|
| 核准狀態機、持久化、token、逾時、rollback | **核心/既有模組** | 不可外包的安全 invariant，涉及 grant、audit、trajectory，需單元測試與紅隊測試 |
| 單一可逆寫入工具 (`write_file`) | **核心/既有模組** | 同屬工具伺服器，受 grant 控制，需嚴格 schema 驗證 |
| CLI 核准介面 (`scripts/jiezi agent approve`) | **核心/既有模組** | CLI 為第一使用者介面，與 grant/revoke 一致 |
| 桌面網頁核准端點 (`POST /v1/agent/approvals/{id}`) | **MCP** | 供外部客戶端（Desktop App）重用，需 schema、授權、稽核 |

---

## Impact / 影響範圍

| 檔案/模組 | 變更類型 |
|-----------|----------|
| `src/jiezi/agent/grants.py` | 擴充：新增 `check_write`、`check_delete`（預設拒絕） |
| `src/jiezi/agent/tools.py` | 新增：`write_file`、擴充 `call`、`SCHEMAS`、`NAMES` |
| `src/jiezi/agent/server.py` | 新增：核准檢查邏輯、`tools/call` 擴充 |
| `src/jiezi/agent/audit.py` | 擴充：稽核欄位含 `reason`、`approval_id`、`token_used`、`outcome` |
| `src/jiezi/agent/approval.py` | **新檔**：核准狀態機、持久化、token、rollback 備份 |
| `src/jiezi/runtime/gateway.py` | 新增：`GET/POST /v1/agent/approvals` 端點 |
| `scripts/jiezi` | 新增：`agent approve` 子命令 |
| `tests/` | 新增：單元測試、紅隊測試、回歸測試 |

---

## 現成方案 / Existing Solutions (from web-research.md A6 段)

| 來源 | 重點 | 芥子取捨 |
|------|------|----------|
| [MCP Specification 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18) | user consent and control、data privacy、tool safety、authorization、access control | 沿用 stdio 子集與嚴格 schema；工具結果只當資料；不主動開 HTTP/OAuth 表面；若要 HTTP 必須先做完整威脅模型與提案 |
| [Anthropic Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) | Skills 是 filesystem-based、按需載入、可重用能力 | 適合 SKILL：程序、模板、工具呼叫範例；不把權限寫進 SKILL 文字；技能來源與版本要可稽核 |
| [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | 先用簡單、可組合模式；workflows 與 agents 分開 | 保持 bounded loop、明確停止條件、外部驗證；不做無目標自主代理 |
| [OWASP Top 10 for LLM 2025](https://genai.owasp.org/download/43299/) | LLM01:2025 Prompt Injection | 一律假設外部內容可能帶注入；輸入/輸出分層檢查；高風險動作要人在迴圈 |
| [OWASP AI Agent Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html) | Tool Security & Least Privilege、scoped allowlist、authorization middleware | grant 逐次重讀、deny list、audit 不記內容、工具白名單、來源標記 |

| [LangChain human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) | `interrupt_on` 決定哪些工具呼叫暫停；每個待審呼叫含工具名與完整參數；可 per-call；暫停需持久化 checkpoint | 採 per-call 核准；核准請求寫入 `var/agent/approvals.jsonl`，重啟不丟 |
| [MCP elicitation（協定 2026-07-28）](https://docs.langchain.com/langsmith/server-mcp-elicitation) | 表單不可收密碼／金鑰／token／付款資料；建議「工具回 input-required＋request state，客戶端帶答案重試」，不把核准綁在長連線 | 核准不走對話長連線：`write_file` 回 pending＋approval_id，核准後由使用者重送；不經表單收任何秘密 |
| [Cloudflare Agents HITL](https://developers.cloudflare.com/agents/guides/human-in-the-loop) | 比較 workflow 核准關卡、MCP elicitation、Code Mode 核准 | 芥子屬「workflow 核准關卡」型：可持久、單步 |

> 主控更正（2026-11-23）：原註記稱上表「照抄自 web-research.md A6 段」不正確——前五列來自 dev-plan §15.3 的既有查證；A6 段的三個來源（LangChain HITL、MCP elicitation、Cloudflare）為本次補上。dry-run／rollback 查無現成套件，故自行設計（見 design）。核心內建、不新增相依。

---

## 資安掃描 / Security Scan

| 風險 | 現有控制 | 殘留風險 | 準則/行動 |
|------|----------|----------|-----------|
| **路徑跳脫** | symlink 解析、DENY_NAMES/DENY_HOME、grant 白名單 | 新路徑型態、罕見編碼 | 紅隊測試 `.env`、key、pem、facts.json、家目錄敏感路徑、符號連結；`write_file` 只允許在 grant 內建立新檔、不可跟隨 symlink 寫入目標 |
| **Symlink 攻擊** | `grants.py` 解析 symlink 後比對 | TOCTOU：檢查與寫入間隙 | 寫入時用 `os.open(O_EXCL|O_CREAT)` 原子建立；不跟隨 symlink；拒絕目標為 symlink 的路徑 |
| **覆寫既有檔案** | 新工具預設禁止覆寫 | 模型嘗試同名檔 | `write_file` 檢查 `not path.exists()`，存在即拒絕；覆寫需另提案 |
| **核准 token 重放** | 一次性 UUID v4、單次使用後失效、逾時 | token 洩漏在有效期內 | token 只在 server 記憶體與持久化存儲；HTTPS 傳輸；用後即銷；逾時 5 分鐘 |
| **核准請求偽造** | Bearer token 驗證、HMAC 簽章 | API key 洩漏 | gateway 端點需授權；CLI 走本機檔案系統權限 |
| **提示注入誘導核准** | injection guard、工具結果標為資料、高風險動作需人在迴圈 | 長上下文交叉注入 | 核准請求只含工具名、參數摘要、風險等級，不含完整檔案內容；使用者核准時只看摘要 |
| **磁碟寫滿** | `facts.json` budgets、VRAM/RAM 保留 | 大量小檔案填滿 inode | 單檔上限 10 MB、單目錄檔案數上限 10,000、寫入前檢查可用空間 > 100 MB |

---

## Open Questions / 待確認事項

| # | 問題 | 選項 | 建議 |
|---|------|------|------|
| Q1 | 核准介面放桌面網頁或 CLI？ | A) 只 CLI B) CLI + 桌面網頁端點 C) 只桌面網頁 | **B**：CLI 為主力，網頁端點預留給 Desktop App |
| Q2 | 核准逾時長度？ | A) 1 分鐘 B) 5 分鐘 C) 10 分鐘 D) 可配置 | **D (預設 5 分鐘)**：平衡使用者反應時間與安全 |
| Q3 | Rollback 保留天數？ | A) 1 天 B) 7 天 C) 30 天 D) 可配置 | **D (預設 7 天)**：足夠發現問題，不佔過多空間 |
| Q4 | 單檔大小上限？ | A) 1 MB B) 10 MB C) 100 MB | **B (10 MB)**：一般文字/程式檔足夠，避免大檔攻擊 |
| Q5 | 是否支援「預覽 diff」？ | A) 是（顯示將寫入內容） B) 否（只顯示路徑） | **A，且顯示完整內容**（主控更正：原建議「只回傳前 200 字」會讓使用者核准沒看過的內容，惡意內容可藏在 200 字後；新檔上限 10 MB，CLI 以分頁器顯示全文，網頁端點回傳全文與 sha256，核准 token 綁定該 sha256，內容一變就失效） |
| Q6 | `write_file` 是否允許建立子資料夾？ | A) 自動建立父目錄 B) 父目錄必須存在 | **B**：父目錄必須存在且在 grant 內，避免目錄遍佈 |
| Q7 | 核准記錄是否加密？ | A) 明文 JSONL B) 加密存儲 | **A**：本機檔案，受 OS 權限保護；敏感值（token）不寫入稽核 |
## 不做的範圍補充 / Non-goals detail（主控 2026-11-23 由 spec 移入）

以下明確不在本變更範圍，需另提案：

| 項目 | 理由 |
|------|------|
| 覆寫既有檔案工具 | 風險更高，需完整 diff preview 與備份驗證 |
| 刪除檔案/資料夾工具 | 不可逆，需更嚴格核准鏈路 |
| Shell 指令執行工具 | 攻擊面極大，需沙箱與網路隔離 |
| 網路請求工具 | 涉外部連線，需 DNS/SSL/速率限制 |
| 批次核准 | 違反單次明確核准原則 |
| 自動核准規則 | 違反人在迴圈原則 |
| 多工具單一核准 | 先驗證一對一模型 |
| 核准記錄加密 | 本機檔案受 OS 權限保護，token 僅存 hash |

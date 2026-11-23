## ADDED Requirements

### Requirement: Per-Action Approval State Machine / 每動作核准狀態機

系統 SHALL 為每個高風險工具呼叫建立核准請求，並在以下七態間流轉：`proposed` → `previewed` → `approved`/`denied`/`expired` → `applied` → `rolled_back`。狀態轉移 SHALL 為單向且不可逆，每次轉移 SHALL 寫入持久化記錄。

The system SHALL create an approval request for each high-risk tool call and transition through seven states: `proposed` → `previewed` → `approved`/`denied`/`expired` → `applied` → `rolled_back`. State transitions SHALL be unidirectional and irreversible; each transition SHALL be persisted.

#### Scenario: 核准請求建立與 Preview / Approval request created and previewed

- **WHEN** 模型呼叫 `write_file` 工具。 / **WHEN** the model calls the `write_file` tool.
- **THEN** 伺服器建立 `proposed` 狀態請求，產生一次性 token，轉為 `previewed`，回傳 `approval_id`、`token`、`summary`、`expires_at`，不執行實際寫入。 / **THEN** the server creates a `proposed` request, generates a one-time token, transitions to `previewed`, returns `approval_id`, `token`, `summary`, `expires_at`, and does not perform the actual write.

#### Scenario: 使用者核准 / User approves

- **WHEN** 使用者攜帶有效 token、理由呼叫核准端點 `action=allow`。 / **WHEN** the user calls the approval endpoint with a valid token, reason, and `action=allow`.
- **THEN** 狀態轉 `approved` → `applied`，執行原子寫入，寫入稽核含 `approval_id`、`token_used`、`reason`、`outcome: success`。 / **THEN** state transitions to `approved` → `applied`, performs atomic write, writes audit with `approval_id`, `token_used`, `reason`, `outcome: success`.

#### Scenario: 使用者拒絕 / User denies

- **WHEN** 使用者呼叫核准端點 `action=deny` 附理由。 / **WHEN** the user calls the approval endpoint with `action=deny` and a reason.
- **THEN** 狀態轉 `denied`，不執行寫入，寫入稽核 `outcome: denied`。 / **THEN** state transitions to `denied`, no write performed, audit records `outcome: denied`.

#### Scenario: 逾時自動失效 / Automatic expiry on timeout

- **WHEN** `previewed` 狀態超過逾時時間（預設 5 分鐘，可配置 `JIEZI_APPROVAL_TIMEOUT_S`）。 / **WHEN** `previewed` state exceeds the timeout (default 5 minutes, configurable via `JIEZI_APPROVAL_TIMEOUT_S`).
- **THEN** 狀態轉 `expired`，token 失效，後續核准回傳 410 Gone。 / **THEN** state transitions to `expired`, token invalidated, subsequent approvals return 410 Gone.

#### Scenario: Rollback 還原 / Rollback restores

- **WHEN** 使用者對 `applied` 狀態請求呼叫 `action=rollback` 附理由。 / **WHEN** the user calls `action=rollback` on an `applied` request with a reason.
- **THEN** 從備份還原（新檔案 = 刪除），狀態轉 `rolled_back`，寫入稽核 `outcome: rolled_back`。 / **THEN** restore from backup (new file = delete), state transitions to `rolled_back`, audit records `outcome: rolled_back`.

---

### Requirement: One-Time Approval Token / 一次性核准 Token

核准請求 SHALL 產生 UUID v4 token，以 URL-safe base64 編碼，僅在 `previewed` 狀態存在；核准成功後 SHALL 立即清空 token 與 `token_hash`（SHA-256），防止重放；逾時後 token 自動失效。

An approval request SHALL generate a UUID v4 token encoded as URL-safe base64, present only in `previewed` state; upon successful approval the token and `token_hash` (SHA-256) SHALL be cleared immediately to prevent replay; token auto-invalidates on expiry.

#### Scenario: Token 重放被拒 / Token replay rejected

- **WHEN** 同一 token 嘗試核准第二次。 / **WHEN** the same token is used to approve a second time.
- **THEN** 伺服器比對 `token_hash` 失敗（已清空），回傳錯誤。 / **THEN** the server fails to match `token_hash` (already cleared) and returns an error.

#### Scenario: 逾時 Token 無效 / Expired token invalid

- **WHEN** 逾時後使用舊 token 核准。 / **WHEN** an expired token is used to approve after timeout.
- **THEN** 狀態已為 `expired`，回傳 410 Gone。 / **THEN** state is already `expired`, returns 410 Gone.

---

### Requirement: Approval Request Persistence / 核准請求持久化

核准請求 SHALL 以 JSONL 格式按天儲存於 `var/agent/approvals/YYYY-MM-DD.jsonl`，欄位包含：`id`、`tool`、`arguments`、`summary`、`risk`、`reason`、`status`、`token`、`token_hash`、`expires_at`、`created_at`、`previewed_at`、`approved_at`、`denied_at`、`applied_at`、`rolled_back_at`、`backup_path`、`outcome`、`trajectory_id`、`step`、`source`。

Approval requests SHALL be persisted as JSONL per day at `var/agent/approvals/YYYY-MM-DD.jsonl` with fields: `id`, `tool`, `arguments`, `summary`, `risk`, `reason`, `status`, `token`, `token_hash`, `expires_at`, `created_at`, `previewed_at`, `approved_at`, `denied_at`, `applied_at`, `rolled_back_at`, `backup_path`, `outcome`, `trajectory_id`, `step`, `source`.

#### Scenario: 持久化可讀取 / Persistence is readable

- **WHEN** 伺服器重啟後讀取前一天 JSONL。 / **WHEN** the server restarts and reads the previous day's JSONL.
- **THEN** 所有請求狀態完整還原，`previewed` 者可繼續核准或自動轉 `expired`。 / **THEN** all request states are fully restored; `previewed` ones can continue approval or auto-transition to `expired`.

---

### Requirement: Rollback Backup Management / Rollback 備份管理

覆寫或刪除操作 SHALL 在執行前建立備份於 `var/agent/approvals/backups/<approval_id>_<timestamp>_<filename>`；新建檔案無需備份（rollback = 刪除新檔）；備份保留期限預設 7 天，可配置 `JIEZI_APPROVAL_BACKUP_DAYS`；啟動時與每日 00:00 清理過期備份。

Overwrite or delete operations SHALL create a backup at `var/agent/approvals/backups/<approval_id>_<timestamp>_<filename>` before execution; new file creation requires no backup (rollback = delete new file); backup retention defaults to 7 days, configurable via `JIEZI_APPROVAL_BACKUP_DAYS`; cleanup runs at startup and daily at 00:00.

#### Scenario: 備份建立與還原 / Backup created and restored

- **WHEN** 未來支援覆寫工具執行前。 / **WHEN** a future overwrite tool executes.
- **THEN** `shutil.copy2(src, backup_path)` 完成，rollback 時 `restore(backup_path, dest_path)` 成功。 / **THEN** `shutil.copy2(src, backup_path)` completes; rollback calls `restore(backup_path, dest_path)` successfully.

---

### Requirement: Audit Field Extensions / 稽核欄位擴充

稽核記錄 SHALL 新增欄位：`approval_id`（關聯核准請求）、`token_used`（使用的 token 前 8 字元）、`reason`（使用者理由）、`outcome`（`success`/`failed`/`skipped`/`denied`/`expired`/`rolled_back`）；舊記錄讀取不受影響。

Audit records SHALL include new fields: `approval_id` (linked approval request), `token_used` (first 8 chars of token), `reason` (user reason), `outcome` (`success`/`failed`/`skipped`/`denied`/`expired`/`rolled_back`); reading old records SHALL remain unaffected.

#### Scenario: 高風險工具稽核含核准資訊 / High-risk tool audit contains approval info

- **WHEN** `write_file` 核准並執行成功。 / **WHEN** `write_file` is approved and executes successfully.
- **THEN** 稽核行含 `approval_id`、`token_used: "eyJhbGci..."`、`reason: "需要記錄會議筆記"`、`outcome: "success"`。 / **THEN** the audit line contains `approval_id`, `token_used: "eyJhbGci..."`, `reason: "需要記錄會議筆記"`, `outcome: "success"`.

---

### Requirement: Single Reversible Write Tool write_file / 單一可逆寫入工具 write_file

系統 SHALL 提供 `write_file` 工具，功能限於：在已授權資料夾內建立新檔案，不可覆寫、不可刪除、不可建立子資料夾（父目錄必須預先存在），內容上限 10 MB，磁碟可用空間需 > 100 MB；路徑必須解析 symlink 後落在授權內且非機密位置。

The system SHALL provide a `write_file` tool limited to: creating a new file inside a granted folder, no overwrite, no delete, no mkdir (parent must exist), content ≤ 10 MB, free disk space > 100 MB; path must resolve symlinks and fall inside a grant and not a secret location.

#### Scenario: 建立新檔成功 / Create new file succeeds

- **WHEN** 使用者核准 `write_file`，路徑在授權資料夾、父目錄存在、檔案不存在、內容 123 字元。 / **WHEN** user approves `write_file`, path in granted folder, parent exists, file doesn't exist, content 123 chars.
- **THEN** 原子建立檔案（`O_EXCL|O_CREAT`），回傳成功，稽核 `outcome: success`。 / **THEN** atomically creates file (`O_EXCL|O_CREAT`), returns success, audit `outcome: success`.

#### Scenario: 既有檔案拒絕 / Existing file refused

- **WHEN** 目標路徑已存在檔案。 / **WHEN** target path already has a file.
- **THEN** 拒絕，理由 `refused: file already exists (no overwrite)`，稽核 `outcome: denied`。 / **THEN** refused with reason `refused: file already exists (no overwrite)`, audit `outcome: denied`.

#### Scenario: 父目錄不存在拒絕 / Missing parent directory refused

- **WHEN** 父目錄不存在。 / **WHEN** parent directory does not exist.
- **THEN** 拒絕，理由 `refused: parent directory does not exist`。 / **THEN** refused with reason `refused: parent directory does not exist`.

#### Scenario: 符號連結拒絕 / Symlink refused

- **WHEN** 目標路徑為符號連結或解析後指向符號連結。 / **WHEN** target path is a symlink or resolves to a symlink.
- **THEN** 拒絕，理由 `refused: symlink not allowed`。 / **THEN** refused with reason `refused: symlink not allowed`.

#### Scenario: 機密路徑拒絕 / Secret path refused

- **WHEN** 解析後路徑落在 `.env`、金鑰、`.ssh`、`.gnupg`、瀏覽器設定檔、專案 `var/`。 / **WHEN** resolved path falls in `.env`, keys, `.ssh`, `.gnupg`, browser profiles, project `var/`.
- **THEN** 拒絕，理由 `refused: secret location`。 / **THEN** refused with reason `refused: secret location`.

#### Scenario: 未授權資料夾拒絕 / Ungranted folder refused

- **WHEN** 路徑不在任何授權資料夾內。 / **WHEN** path is not inside any granted folder.
- **THEN** 拒絕，理由 `refused: outside the granted folders`。 / **THEN** refused with reason `refused: outside the granted folders`.

#### Scenario: 內容過大拒絕 / Content too large refused

- **WHEN** 內容超過 10 MB。 / **WHEN** content exceeds 10 MB.
- **THEN** 拒絕，理由 `refused: content too large`。 / **THEN** refused with reason `refused: content too large`.

#### Scenario: 磁碟空間不足拒絕 / Insufficient disk space refused

- **WHEN** 可用磁碟空間 < 100 MB。 / **WHEN** free disk space < 100 MB.
- **THEN** 拒絕，理由 `refused: insufficient disk space`。 / **THEN** refused with reason `refused: insufficient disk space`.

---

### Requirement: Grant Write Check / 授權寫入檢查

`grants.py` SHALL 提供 `check_write(path)`，驗證：路徑解析 symlink 後在授權資料夾內、非機密位置、父目錄存在且在授權內、目標非既有檔/資料夾/符號連結；拒絕理由 SHALL 與 `check()` 一致風格。

`grants.py` SHALL provide `check_write(path)` verifying: resolved path inside granted folder, not a secret location, parent exists and is granted, target is not an existing file/dir/symlink; refusal reasons SHALL match `check()` style.

#### Scenario: 授權內新檔通過 / New file in grant passes

- **WHEN** `check_write("/home/user/granted/new.txt")`，`/home/user/granted` 已授權。 / **WHEN** `check_write("/home/user/granted/new.txt")` with `/home/user/granted` granted.
- **THEN** 回傳 `(real_path, None)`。 / **THEN** returns `(real_path, None)`.

#### Scenario: 撤銷後立即生效 / Revocation takes effect immediately

- **WHEN** 授權資料夾被撤銷後呼叫 `check_write()`。 / **WHEN** `check_write()` called after grant folder revoked.
- **THEN** 立即回傳拒絕，無需重啟。 / **THEN** immediately returns refusal, no restart needed.

---

### Requirement: CLI Approval Interface / CLI 核准介面

`scripts/jiezi agent approve` SHALL 提供子命令：`list`、`show`、`allow`、`deny`、`rollback`，直接讀寫 `var/agent/approvals/` JSONL，不經 gateway。

`scripts/jiezi agent approve` SHALL provide subcommands: `list`, `show`, `allow`, `deny`, `rollback`, directly reading/writing `var/agent/approvals/` JSONL without gateway.

#### Scenario: CLI 列出待核准 / CLI lists pending approvals

- **WHEN** 執行 `jiezi agent approve list --days 1`。 / **WHEN** run `jiezi agent approve list --days 1`.
- **THEN** 輸出 JSON 陣列，含 `id`、`tool`、`summary`、`status`、`expires_at`。 / **THEN** outputs JSON array with `id`, `tool`, `summary`, `status`, `expires_at`.

#### Scenario: CLI 核准 / CLI approves

- **WHEN** 執行 `jiezi agent approve allow <id> --reason "理由" --token <token>`。 / **WHEN** run `jiezi agent approve allow <id> --reason "理由" --token <token>`.
- **THEN** 驗證 token、更新狀態、執行寫入、輸出結果。 / **THEN** verifies token, updates state, executes write, outputs result.

---

### Requirement: Gateway Approval Endpoints / Gateway 核准端點

Gateway SHALL 暴露：`GET /v1/agent/approvals`（列表）、`GET /v1/agent/approvals/{id}`（詳情含將寫入的完整內容與其 sha256；核准 token 綁定該 sha256）、`POST /v1/agent/approvals/{id}`（核准/拒絕/rollback，需 Bearer token、JSON body：`action`、`reason`、`token`）。

Gateway SHALL expose: `GET /v1/agent/approvals` (list), `GET /v1/agent/approvals/{id}` (detail with the full content to be written and its sha256; the approval token is bound to that sha256), `POST /v1/agent/approvals/{id}` (decide with Bearer token, JSON body: `action`, `reason`, `token`).

#### Scenario: Gateway 列表需授權 / Gateway list requires auth

- **WHEN** 無 Bearer token 呼叫 `GET /v1/agent/approvals`。 / **WHEN** call `GET /v1/agent/approvals` without Bearer token.
- **THEN** 回傳 401 Unauthorized。 / **THEN** returns 401 Unauthorized.

#### Scenario: Gateway 核准成功 / Gateway approval succeeds

- **WHEN** 攜帶有效 token、`action=allow`、`reason` 呼叫 `POST /v1/agent/approvals/{id}`。 / **WHEN** call `POST /v1/agent/approvals/{id}` with valid token, `action=allow`, `reason`.
- **THEN** 回傳 200，狀態轉 `applied`，稽核寫入。 / **THEN** returns 200, state transitions to `applied`, audit written.

---

### Requirement: Periodic Cleanup / 定期清理

Gateway 啟動時與每分鐘 SHALL 呼叫 `ApprovalStore.cleanup_expired()` 將逾時 `previewed` 轉 `expired`；啟動時與每日 00:00 SHALL 呼叫 `BackupManager.cleanup()` 刪除超過保留期限的備份。

Gateway at startup and every minute SHALL call `ApprovalStore.cleanup_expired()` to transition expired `previewed` to `expired`; at startup and daily 00:00 SHALL call `BackupManager.cleanup()` to delete backups exceeding retention.

#### Scenario: 逾時自動清理 / Expired auto-cleanup

- **WHEN** 有 `previewed` 請求逾時 5 分鐘，下一分鐘清理任務執行。 / **WHEN** a `previewed` request expires after 5 minutes, next minute cleanup runs.
- **THEN** 該請求狀態轉 `expired`，token 失效。 / **THEN** that request state transitions to `expired`, token invalidated.

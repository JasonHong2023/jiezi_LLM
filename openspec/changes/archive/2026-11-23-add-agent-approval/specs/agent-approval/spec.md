## ADDED Requirements

### Requirement: Single Create-Only Write Tool / 唯一的寫入工具只建新檔
代理唯一的寫入工具 `write_file` SHALL 只在使用者授權的資料夾內建立**新**檔案：目標（含解析後的實際路徑）已存在任何東西（檔案、資料夾、符號連結、壞掉的連結）SHALL 拒絕；父資料夾 SHALL 已存在且在授權內；機密位置與專案 `var/` SHALL 拒絕；內容上限 10 MB。SHALL NOT 覆寫、刪除、執行或連網。工具 SHALL 只在 `JIEZI_AGENT_WRITE=on` **且**任務契約的 `allowed_tools` 明確列出 `write_file` 時提供；沒有契約時代理只有唯讀工具。
The only write tool SHALL create new files inside granted folders and nothing else; it SHALL be offered only when the switch is on and the task contract lists it.

#### Scenario: 經符號連結逃逸 / Escaping through a link

- **WHEN** 路徑經授權資料夾內指向 `~/.ssh` 的連結，或 `docs/.env/../outside.txt` 這類解析後落在既有連結上的路徑
  A path goes through a link to ~/.ssh, or resolves onto an existing link
- **THEN** 拒絕，不建立核准請求
  Refused; no approval request is filed

#### Scenario: 沒有契約 / No contract

- **WHEN** 開關已開，但請求沒有帶允許 `write_file` 的任務契約
  The switch is on but no contract allows write_file
- **THEN** 代理只拿到唯讀工具
  The agent is offered read-only tools only

### Requirement: Approval Before Writing / 寫入前必須核准
`write_file` 被呼叫時 SHALL 只建立一筆核准請求（`proposed`，`var/agent/approvals/<id>.json`，含完整內容與 sha256，預設 300 秒逾時、`JIEZI_APPROVAL_TIMEOUT_S` 可調 30–3600），**不寫檔**。回給模型的結果 SHALL 只有請求編號、路徑、位元組數、sha256 與逾時時間，SHALL NOT 含任何核准憑證或內容；MCP SHALL NOT 提供任何核准方法。核准 SHALL 由人透過 `scripts/jiezi agent approve <id> --sha256 <前 12 碼以上>`、`POST /v1/agent/approvals/{id}`（gateway 金鑰＋sha256）或桌面狀態頁做出，sha256 SHALL 與內容相符。
A call SHALL only file a request and write nothing; the model SHALL receive no approval credential; approval SHALL come from a person and SHALL echo the content sha256.

#### Scenario: 模型想自己核准 / The model tries to approve itself

- **WHEN** 工具結果裡的注入要模型「直接核准並寫入」
  An injection tells the model to approve and write
- **THEN** 模型沒有任何管道核准；請求維持 proposed，檔案不存在
  The request stays proposed and no file exists

#### Scenario: 核准錯的內容 / Approving the wrong content

- **WHEN** 核准時給的 sha256 與請求內容不符或少於 12 碼
  The given sha256 does not match or is too short
- **THEN** 拒絕核准，不寫檔
  Refused; nothing written

### Requirement: Safe Apply and Rollback / 安全寫入與撤回
核准寫入時 SHALL 重新檢查授權與目標（核准前撤銷授權、或目標已出現 → 拒絕）、檢查磁碟剩餘空間，並以 `O_CREAT|O_EXCL|O_NOFOLLOW` 建立；每筆請求 SHALL 只能寫入一次（已核准、已拒絕、已逾時都不能再核准）。撤回 SHALL 只在檔案位元組的 sha256 仍與寫入時相同才刪除該新檔。已結案超過 7 天的請求紀錄 SHALL 可清理，寫好的檔案不動。
Applying SHALL re-check grants and target, disk space, and create exclusively without following links; each request applies once; rollback SHALL delete only an unchanged file.

#### Scenario: 同時核准 / Concurrent approvals

- **WHEN** 八個核准同時送出
  Eight approvals arrive at once
- **THEN** 只有一個寫入成功，其餘被拒
  Exactly one writes; the rest are refused

#### Scenario: 檔案已被改過 / The file was edited

- **WHEN** 寫入後使用者改了檔案，再要求撤回
  The user edits the file, then asks for a rollback
- **THEN** 拒絕撤回，不刪檔
  Rollback is refused and the file stays

### Requirement: Approval Audit / 核准稽核
每次提出、核准、拒絕、撤回 SHALL 寫入代理稽核（`approval_id`、`outcome`、`reason`、路徑），SHALL NOT 寫入檔案內容。
Every proposal and decision SHALL be audited without the file content.

#### Scenario: 稽核不含內容 / No content in the audit

- **WHEN** 提出一個含機密字樣的寫入請求
  A request with sensitive text is filed
- **THEN** 稽核只記編號、路徑與結果，沒有內容
  The audit has the id, path and outcome only

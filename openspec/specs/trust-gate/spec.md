# trust-gate Specification

## Purpose
TBD - created by archiving change add-agent-trust-gate. Update Purpose after archive.
## Requirements
### Requirement: Trust Levels / 信任等級
系統 SHALL 以四級 `TrustLevel` 決定外部內容能進入哪裡：`tainted`（都不行）、`unverified`（只能進記憶）、`verified`（記憶與技能）、`trusted`（記憶、技能、訓練）。雲端或 Claude 的內容 SHALL NOT 自成一級：它們是 `unverified`，來源記在 provenance 的 `source_channel="cloud"`。
A four-level TrustLevel SHALL decide where content may go; cloud content SHALL NOT be a level of its own but `unverified` with `source_channel="cloud"` in its provenance.

#### Scenario: 雲端答案存進記憶 / A cloud answer saved to memory

- **WHEN** 請教 Claude 得到的答案存進記憶 wiki
  A consulted answer is saved to the memory wiki
- **THEN** 頁面記錄 `trust_level: unverified` 與 `provenance_source_channel: cloud`；不進技能庫或訓練資料
  The page records unverified with a cloud source; it never enters skills or training data

### Requirement: Provenance / 來源紀錄
每次信任評估 SHALL 產生 provenance：`source_channel`、`source_id`、`content_hash`（sha256）、`fetched_at`（UTC），可選 `version`、`retrieval_method`、`extra`。讀取缺欄位的舊紀錄 SHALL 不出錯，視為 `unverified`。
Each evaluation SHALL produce provenance with channel, id, sha256 and UTC time; records missing these fields SHALL read as unverified without errors.

#### Scenario: 舊頁面 / Old pages

- **WHEN** 讀取本功能之前寫入的記憶頁面
  Memory pages written before this change are read
- **THEN** 照常讀取，信任等級視為 unverified
  They load as before and count as unverified

### Requirement: Taint Index / 污染索引
`injection.guard()` 判定可疑的每一段內容 SHALL 各自登記 sha256 到 taint index；之後同一段內容不論從哪個管道（記憶、技能、訓練資料、MCP）進來 SHALL 被判為 `tainted` 並拒絕寫入。索引 SHALL 依專案根目錄持久化在 `var/trust/taint_index.jsonl`，超過 30 天的紀錄 SHALL 在載入時丟棄，壞掉的一行 SHALL 只略過該行。
Each suspicious item SHALL be registered by sha256; the same content from any channel SHALL then be tainted and refused. The index SHALL persist per project root, drop records older than 30 days on load, and skip only a corrupt line.

#### Scenario: 跨管道攔截 / Blocked across channels

- **WHEN** 工具結果裡的一段注入文字被偵測到，之後同一段文字要存進記憶
  An injected tool result is detected and the same text is later saved to memory
- **THEN** 記憶寫入被拒，訓練資料匯出也排除含這段文字的答案
  The memory write is refused and the export drops answers containing it

### Requirement: Single Untrainable Marking / 不可訓練的單一標記點
gateway 把軌跡標為不可訓練時 SHALL 一律經 `TrustGate.mark_untrainable(rec, reason, model)`：設 `training_use=false`，並寫 `rec["trust"]={level, reason, provenance}`；原因 SHALL 保留具體值（license、private、unverifiable、memory、injection、cloud、cloud_hint、helper、consultation），雲端相關原因的來源 SHALL 為 cloud，`injection` 的等級 SHALL 為 tainted。
The gateway SHALL mark trajectories untrainable only through mark_untrainable, keeping the concrete reason; cloud reasons get a cloud source and injection is tainted.

#### Scenario: 網頁內容 / Web content

- **WHEN** 回答用到授權不明的網頁內容
  An answer uses web content of unknown licence
- **THEN** 軌跡 `training_use=false`、`trust.reason="license"`、來源 local
  The trajectory is untrainable with reason license and a local source

### Requirement: MCP Tool Result Trust / MCP 工具結果的信任
芥子 MCP server 的工具結果 SHALL 在 `result._meta["jiezi/trust"]` 附信任評估，SHALL NOT 改動 `structuredContent`。預設 SHALL 為 `unverified`；用 `scripts/jiezi agent trust-mcp <name>` 標記受信任後 SHALL 為 `verified`，`--remove` 取消；設定存在 `var/agent/trusted_mcp.json`，每次呼叫重讀。
Tool results SHALL carry a trust assessment in `_meta` without changing structuredContent; unverified by default, verified once the server is marked with `trust-mcp`.

#### Scenario: 標記受信任 / Marking a server trusted

- **WHEN** 執行 `scripts/jiezi agent trust-mcp jiezi-readonly-files` 後再讀檔
  The server is marked trusted, then a file is read
- **THEN** 工具結果的信任等級為 verified；取消標記後回到 unverified
  The result is verified; after removal it is unverified again


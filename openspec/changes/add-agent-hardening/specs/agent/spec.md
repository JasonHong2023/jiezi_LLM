## ADDED Requirements

### Requirement: Enforced loop limits from one source / 從單一來源執行迴圈上限

代理迴圈 SHALL 從 `limits.EFFECTIVE_LIMITS` 取得步數、每步呼叫數、結果字數、舊結果字數、工具預算與呼叫超時上限；SHALL NOT 使用與契約上限不同的數值。 / The agent loop SHALL take step, per-step call, result-character, old-result-character, tool-budget, and call-timeout ceilings from `limits.EFFECTIVE_LIMITS` and SHALL NOT use values that differ from the contract ceilings.

超過每步呼叫上限的呼叫 SHALL 被略過且不派送到 MCP；過長的工具結果 SHALL 被截斷；較舊的工具結果 SHALL 在預算不足時縮短；無效參數或超時 SHALL 以錯誤結果 fail closed，SHALL NOT 讓逸圈崩潰。 / Calls beyond the per-step cap SHALL be skipped without MCP dispatch; oversized tool results SHALL be truncated; older results SHALL be shortened when the budget is tight; invalid arguments and timeouts SHALL fail closed with an error result and SHALL NOT crash the loop.

#### Scenario: 重複呼叫被略過 / Repeated calls are skipped

- **WHEN** 模型在單一步驟產生超過 `max_calls_per_step` 的工具呼叫。 / **WHEN** the model emits more tool calls than `max_calls_per_step` in one step.
- **THEN** 多出的呼叫不被執行且回傳略過訊息，MCP 呼叫次數不高於上限。 / **THEN** the extra calls are not executed and return a skipped message, with MCP dispatches no greater than the cap.

#### Scenario: 逾時 fail closed / Timeout fails closed

- **WHEN** 工具呼叫超過 `call_timeout_s`。 / **WHEN** a tool call exceeds `call_timeout_s`.
- **THEN** 迴圈記錄錯誤結果並繼續或結束，不讓子行程無限等待。 / **THEN** the loop records an error result and continues or ends without waiting forever on the child process.

#### Scenario: 結果與舊結果被限縮 / Results and old results are capped

- **WHEN** 工具回傳超過 `result_chars` 的文字，且對話超過 `tools_budget`。 / **WHEN** a tool returns text longer than `result_chars` and the conversation exceeds `tools_budget`.
- **THEN** 新結果被截斷，較舊結果被縮短，兩者都不超過對應上限。 / **THEN** the new result is truncated and older results are shortened, neither exceeding its ceiling.

### Requirement: Immediate grant revocation and resolved-path denial / 撤銷立即生效與解析後路徑拒絕

工具伺服器 SHALL 在每次呼叫前重新讀取授權檔；撤銷後的下一次呼叫 SHALL 立即被拒，不需重啟伺服器或迴圈。 / The tool server SHALL re-read the grant file before every call; the next call after revocation SHALL be refused immediately without restarting the server or loop.

所有路徑 SHALL 先解析符號連結再比對授權與機密清單；`.env`、金鑰、`.ssh`、`.gnupg`、瀏覽器設定檔與專案 `var/` SHALL 永遠拒絕，即使路徑看似位於授權資料夾。 / All paths SHALL be resolved through symlinks before grant and secret-list matching; `.env`, keys, `.ssh`, `.gnupg`, browser profiles, and project `var/` SHALL always be refused even if the path appears inside a granted folder.

#### Scenario: 撤銷後下一次呼叫 / Next call after revocation

- **WHEN** 第一次工具呼叫成功後撤銷該資料夾，再發出第二次呼叫。 / **WHEN** a folder is revoked after a successful first call and a second call follows.
- **THEN** 第二次呼叫被拒絕，拒絕原因寫入稽核，且不需重啟。 / **THEN** the second call is refused, the reason is audited, and no restart is needed.

#### Scenario: 符號連結指向機密位置 / Symlink points to a secret location

- **WHEN** 授權資料夾內的符號連結指向 `~/.ssh/id_rsa` 或 `.env`。 / **WHEN** a symlink inside a granted folder points to `~/.ssh/id_rsa` or `.env`.
- **THEN** 依解析後的實際路徑拒絕，且不讀取內容。 / **THEN** the resolved real path is refused and no content is read.

### Requirement: Stoppable loop with process-group termination / 可中止迴圈與行程群組終止

客戶端中斷或取消 SHALL 終止 MCP 子行程的整個行程群組，且 SHALL NOT 再發出新的工具呼叫；真實子行程的中止時間 SHALL ≤ 1 秒。 / Client interruption or cancellation SHALL terminate the MCP child's whole process group and SHALL NOT issue further tool calls; stopping a real child SHALL take ≤ 1 second.

#### Scenario: 取消正在進行的工具 / Cancel a running tool

- **WHEN** 使用者在工具執行中按中止。 / **WHEN** the user presses stop while a tool is running.
- **THEN** 子行程群組在 1 秒內終止，後續步驟不再呼叫工具。 / **THEN** the child process group terminates within 1 second and later steps issue no tool call.

### Requirement: Content-free audit under red-team fixtures / 紅隊語料下稽核不記內容

稽核紀錄 SHALL 只記錄工具名稱、參數、允許與否、摘要、步驟與原因，SHALL NOT 記錄檔案內容、注入句型文字或機密值。 / Audit records SHALL contain only tool name, arguments, allow/deny, summary, step, and reason; they SHALL NOT contain file contents, injection text, or secret values.

#### Scenario: 可疑檔案與拒絕路徑進入稽核 / Suspicious file and refused path are audited

- **WHEN** 紅隊案例讀到含注入句子的檔案，並嘗試讀取被拒的機密路徑。 / **WHEN** a red-team case reads a file with injection text and attempts a refused secret path.
- **THEN** 稽核有拒絕與摘要，但找不到注入句子或機密內容。 / **THEN** the audit has the refusal and summary but contains neither the injection sentence nor secret content.

## ADDED Requirements

### Requirement: One-Shot Ask

`jiezi ask` SHALL 把參數當成問題送到 gateway；stdin 不是終端機時 SHALL 把 stdin 內容附在問題之前。stdout 是終端機時 SHALL 串流顯示答案，並在最後顯示層級、實際模型、t/s 與雲端費用；stdout 不是終端機時 SHALL 只輸出答案。結束碼 SHALL 區分成功、gateway 無法連線與 gateway 錯誤。
`jiezi ask` SHALL send its argument to the gateway as the question; when stdin is not a terminal, it SHALL attach stdin content before the question. When stdout is a terminal it SHALL stream the answer and finish with tier, actual model, t/s and cloud cost; otherwise it SHALL print only the answer. Exit codes SHALL distinguish success, gateway unreachable and gateway error.

#### Scenario: 接管線 / Piped

- **WHEN** 使用者執行 `cat 報告.md | jiezi ask "摘要" > 摘要.txt`
  The user runs `cat report.md | jiezi ask "summarize" > summary.txt`
- **THEN** 報告內容附在問題前送出，`摘要.txt` 只包含答案本身，沒有狀態行或控制字元
  The report is attached before the question, and `summary.txt` contains only the answer, with no status line or control characters

#### Scenario: gateway 沒有啟動 / Gateway not running

- **WHEN** gateway 無法連線
  The gateway cannot be reached
- **THEN** 顯示「gateway 未啟動，請執行 `scripts/jiezi serve`」，結束碼為 2
  It prints that the gateway is not running and how to start it, and exits with code 2

### Requirement: Interactive Chat

`jiezi chat` SHALL 提供多輪對話、串流顯示，以及每則回答的層級、模型、t/s、費用與驗證結果。Ctrl-C SHALL 中斷目前的生成而不離開程式。介面 SHALL 在 Herdr、Windows Terminal 與 GNOME Terminal 中正確顯示中文寬字元。
`jiezi chat` SHALL provide multi-turn chat, streaming, and each answer's tier, model, t/s, cost and verification. Ctrl-C SHALL stop the current generation without quitting. The interface SHALL display CJK width correctly in Herdr, Windows Terminal and GNOME Terminal.

#### Scenario: 中斷生成 / Stop generation

- **WHEN** 回答串流到一半，使用者按 Ctrl-C
  The user presses Ctrl-C mid-stream
- **THEN** 串流停止、gateway 取消上游請求，已收到的部分保留並標為「已中斷」，可以繼續輸入下一句
  Streaming stops, the gateway cancels upstream, the partial answer stays marked "stopped", and the user can type the next message

### Requirement: Herdr Agent Reporting

在 Herdr pane 內（`HERDR_ENV=1` 且有 `HERDR_PANE_ID`）執行時，`jiezi chat` SHALL 以 `herdr pane report-agent` 回報 `working`、`idle`、`blocked`，並提供恢復指令。回報失敗 SHALL NOT 影響對話。不在 Herdr 內 SHALL NOT 呼叫 `herdr`。
Inside a Herdr pane (`HERDR_ENV=1` with `HERDR_PANE_ID`), `jiezi chat` SHALL report `working`, `idle` and `blocked` via `herdr pane report-agent` with a resume command. Reporting failures SHALL NOT affect the chat. Outside Herdr it SHALL NOT call `herdr`.

#### Scenario: 回答期間 / While answering

- **WHEN** 使用者在 Herdr 內送出問題
  The user sends a question inside Herdr
- **THEN** pane 狀態變成 `working`；回答完成後變成 `idle`
  The pane shows `working`, then `idle` when the answer completes

### Requirement: Read-Only Client Check

`scripts/jiezi check-clients` SHALL 只做讀取檢查（gateway 可連線、金鑰有效、`/v1/models` 列出三種策略），SHALL NOT 修改使用者的 Hermes Agent 或 OpenCode 設定。
`scripts/jiezi check-clients` SHALL only read (gateway reachable, key valid, `/v1/models` lists the three policies) and SHALL NOT modify the user's Hermes Agent or OpenCode settings.

#### Scenario: 檢查通過 / Check passes

- **WHEN** gateway 正在執行且金鑰正確
  The gateway runs and the key is correct
- **THEN** 列出三種策略與 Hermes / OpenCode 的建議設定值，不寫入任何設定檔
  It lists the three policies and the suggested Hermes / OpenCode settings without writing any config file

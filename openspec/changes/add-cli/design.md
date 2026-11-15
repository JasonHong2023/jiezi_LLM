## Context

- gateway（`add-gateway`）提供 OpenAI 相容 API、`jiezi` 回應欄位（層級、模型、驗證、延遲、費用、軌跡 ID）與本機金鑰。
  The gateway (`add-gateway`) offers the OpenAI-compatible API, the `jiezi` response field (tier, model, verification, latency, cost, trajectory ID) and a local key.
- Herdr 0.9.3（本機）：`herdr pane report-agent <pane_id> --source ID --agent LABEL --state idle|working|blocked|unknown [--message TEXT] [--seq N] [-- <恢復指令>]`；在 pane 內有 `HERDR_ENV=1` 與 `HERDR_PANE_ID`。Herdr 原生支援 OpenCode 的狀態回報與 Hermes Agent。[本機查證：`herdr pane report-agent --help`、`~/projects/herdr` 原始碼]
  Herdr 0.9.3 (local): `herdr pane report-agent …`; inside a pane, `HERDR_ENV=1` and `HERDR_PANE_ID` are set. Herdr natively supports OpenCode state reporting and Hermes Agent. [Checked locally]
- 2026-11-14 使用者決定：TUI 用 Python + Textual，只要在 Herdr 和終端機中顯示正常；過渡期可用 Hermes Agent 或 OpenCode 接 gateway，但 Herdr 顯示也要正常。
  User decisions of 2026-11-14: Python + Textual for the TUI, provided it displays correctly in Herdr and terminals; Hermes Agent or OpenCode may connect to the gateway in the meantime, also displaying correctly in Herdr.

## Goals / Non-Goals

**Goals：** 單次與互動兩種用法；任何時候都看得到「這個答案從哪裡來、花了多少」；在三種終端機中正確顯示中文寬字元；Windows 11 原生可用。
**Goals:** one-shot and interactive use; always showing where an answer came from and what it cost; correct CJK width in the three terminals; native Windows 11 support.

**Non-Goals：** 見 proposal。 / See the proposal.

## Decisions

### D1 — 結構 / Structure

`src/jiezi/cli/`：`client.py`（gateway 的 HTTP 客戶端與串流解析，`ask` 與 `chat` 共用）、`ask.py`、`chat.py`（Textual App）、`herdr.py`（狀態回報）。`scripts/jiezi ask|chat`；Windows 上以 `uv run python -m jiezi.cli` 執行，不依賴 bash。
`src/jiezi/cli/`: `client.py` (the gateway HTTP client and stream parsing, shared by `ask` and `chat`), `ask.py`, `chat.py` (the Textual app), `herdr.py` (state reporting). `scripts/jiezi ask|chat`; on Windows `uv run python -m jiezi.cli`, no bash needed.

### D2 — 連線設定 / Connection settings

`JIEZI_GATEWAY_URL`（預設 `http://127.0.0.1:36100`）與 `JIEZI_GATEWAY_KEY` 從 `.env` 或環境變數讀取。Windows 客戶端連 WSL 內的 gateway 時，使用 WSL2 的 localhost 轉送，所以仍是 `127.0.0.1`，不需要對外開放（R6.12）。
`JIEZI_GATEWAY_URL` (default `http://127.0.0.1:36100`) and `JIEZI_GATEWAY_KEY` come from `.env` or the environment. A Windows client reaches the gateway inside WSL through WSL2 localhost forwarding, so it is still `127.0.0.1` and nothing is exposed (R6.12).

### D3 — `jiezi ask`

- 參數是問題；stdin 不是終端機時，把 stdin 內容當成附加的文件，放在問題之前。
  The argument is the question; when stdin is not a terminal, its content is attached as a document before the question.
- stdout 是終端機時：串流顯示答案，最後一行以暗色顯示 `[第 N 層 · 模型 · t/s · 費用]`。stdout 不是終端機時：只輸出答案。`--json` 輸出完整回應（含 `jiezi` 欄位）。
  When stdout is a terminal: stream the answer and end with a dim `[tier N · model · t/s · cost]` line. Otherwise: answer only. `--json` prints the full response (with the `jiezi` field).
- `--local` / `--cloud` 對應 `jiezi-local` / `jiezi-cloud`。結束碼：0 成功、2 gateway 無法連線、3 gateway 回錯誤。
  `--local` / `--cloud` map to `jiezi-local` / `jiezi-cloud`. Exit codes: 0 success, 2 gateway unreachable, 3 gateway error.

### D4 — `jiezi chat`（Textual）

- 版面：上方對話區（Markdown 顯示，程式區塊語法上色）、下方輸入框、底部狀態列（策略、連線狀態、本次對話累計雲端費用）。
  Layout: a conversation area (Markdown, highlighted code blocks), an input box, a bottom status bar (policy, connection, session cloud cost).
- 每則回答下方一行小字：層級、實際模型、t/s、費用、驗證結果。
  Under each answer, a small line: tier, actual model, t/s, cost, verification.
- 按鍵：Enter 送出、Shift+Enter 換行、Ctrl-C 中斷生成（不離開）、Ctrl-Q 離開、F2 切換策略。按鍵在 Herdr 的 Kitty 鍵盤協定下也要正確。
  Keys: Enter sends, Shift+Enter newline, Ctrl-C stops generation (without quitting), Ctrl-Q quits, F2 switches policy. Keys must also work under Herdr's Kitty keyboard protocol.
- 對話只在記憶體中；`/save` 可存成 Markdown 到使用者指定的位置。
  Conversations live in memory; `/save` writes Markdown to a user-chosen path.

### D5 — Herdr 狀態回報 / Herdr state reporting

只在 `HERDR_ENV=1` 且有 `HERDR_PANE_ID` 時啟用：送出請求時回報 `working`，回答完成回報 `idle`，等待使用者確認（之後的工具操作）時回報 `blocked`。恢復指令是 `jiezi chat`。回報以非同步子行程執行，失敗只記錄、不影響對話；`--seq` 遞增，避免順序錯亂。
Enabled only when `HERDR_ENV=1` and `HERDR_PANE_ID` exist: `working` on send, `idle` when the answer completes, `blocked` while waiting for user confirmation (later tool actions). The resume command is `jiezi chat`. Reports run as background subprocesses; failures are logged without affecting the chat; `--seq` increases to keep ordering.

### D6 — 終端機相容性驗證 / Terminal compatibility checks

自動化：Textual 的 `App.run_test()` 跑按鍵與版面測試，固定寬度下檢查中文、全形標點與 emoji 的寬度不會造成錯位。人工：在 Herdr、Windows Terminal、GNOME Terminal 各跑一份檢查清單（版面、中文換行、顏色、按鍵、調整視窗大小），結果記入討論記錄。GNOME Terminal 與 Windows Terminal 的人工檢查需要使用者協助。
Automated: Textual's `App.run_test()` for key and layout tests, checking at fixed widths that CJK, full-width punctuation and emoji widths do not misalign. Manual: a checklist (layout, CJK wrapping, colors, keys, resizing) in Herdr, Windows Terminal and GNOME Terminal, results in the discussion log. The GNOME Terminal and Windows Terminal checks need the user's help.

### D7 — 過渡客戶端 / Transitional clients

`docs/clients.md` 寫明 Hermes Agent（`hermes config set model.base_url http://127.0.0.1:36100/v1`、金鑰）與 OpenCode 的設定步驟；`scripts/jiezi check-clients` 只做讀取檢查（gateway 可連線、金鑰有效、`/v1/models` 列出三個策略），**不改動**使用者的 Hermes 或 OpenCode 設定。要不要真的切換由使用者決定，因為這會改變使用者日常工具的行為。
`docs/clients.md` documents the Hermes Agent and OpenCode setup; `scripts/jiezi check-clients` only reads (gateway reachable, key valid, `/v1/models` lists the three policies) and **never changes** the user's Hermes or OpenCode settings. Whether to switch is the user's call, since it changes their everyday tools.

## Risks / Trade-offs

- **Kitty 鍵盤協定與 Shift+Enter**：部分終端機無法分辨 Shift+Enter。→ 同時提供 Ctrl+J 換行。
  **Kitty keyboard protocol and Shift+Enter**: some terminals cannot tell Shift+Enter apart. → Ctrl+J also inserts a newline.
- **中文寬度**：不同終端機對 emoji 和部分符號寬度判斷不同。→ 狀態列只用 ASCII 與常用中文，不用 emoji。
  **CJK width**: terminals disagree on emoji and some symbols. → The status bar uses ASCII and common CJK only, no emoji.
- **0.6B 暫代核心**：回答品質低，但介面要測的是顯示與流程。
  **The 0.6B stand-in**: weak answers, but the interface tests display and flow.

## Open Questions

- **OQ1**：Textual 8.2.8 與 Rich 15.0.0 作為新的執行期套件，是否同意？（R23 查證：OSV 沒有任何公告）
  Approve Textual 8.2.8 and Rich 15.0.0 as runtime packages? (R23: no advisories on OSV.)
- **OQ2**：完成後要不要把你的 Hermes Agent 預設 `base_url` 改成 gateway？（建議先不改，用 `check-clients` 驗證後再由你決定）
  After completion, switch your Hermes Agent's default `base_url` to the gateway? (Recommend not yet: verify with `check-clients`, then you decide.)

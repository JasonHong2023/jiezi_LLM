## Why

gateway（`add-gateway`）上線後，需要讓人直接使用芥子的介面。開發計畫 4.7、4.8 與決策 D9、D12 要求：過渡期先讓 Hermes Agent 和 OpenCode 接上 gateway；之後提供 `jiezi ask`（單次、可接管線）與 `jiezi chat`（Textual 全螢幕）。每則回答都要顯示第幾層回答、t/s 與雲端費用，並且在 Herdr、Windows Terminal、GNOME Terminal 中顯示正常（R21.9），還要實作 Herdr 的 agent 狀態回報。
Once the gateway (`add-gateway`) is up, people need an interface to Jiezi. Plan items 4.7 and 4.8 and decisions D9 and D12 require: first, Hermes Agent and OpenCode connect to the gateway; then `jiezi ask` (one-shot, pipeable) and `jiezi chat` (Textual full screen). Each answer shows its tier, t/s and cloud cost; everything displays correctly in Herdr, Windows Terminal and GNOME Terminal (R21.9); Herdr agent state reporting is implemented.

## What Changes

- **過渡客戶端**（設定與驗證，不寫新程式）：說明文件與檢查腳本，把 Hermes Agent 與 OpenCode 的 `base_url` 指向 gateway；在 Herdr 中確認顯示、狀態回報與中文寬字元。
  **Transitional clients** (configuration and checks, no new program): a guide and a check script pointing Hermes Agent and OpenCode at the gateway; verified in Herdr for display, state reporting and CJK width.
- **`jiezi ask "問題"`**：單次問答；可以從 stdin 讀入內容（例如 `cat 檔案 | jiezi ask "摘要這份文件"`）；預設串流輸出；最後一行（或 `--json`）顯示層級、實際模型、t/s、雲端費用。stdout 不是終端機時只輸出答案本身，方便接管線。
  **`jiezi ask "question"`**: one-shot; reads stdin when piped (for example `cat file | jiezi ask "summarize"`); streams by default; a final line (or `--json`) shows tier, actual model, t/s and cloud cost. When stdout is not a terminal, it prints only the answer, so it pipes cleanly.
- **`jiezi chat`**：Textual 全螢幕對話：多輪對話、串流、每則回答下方的狀態列（層級、模型、t/s、費用、驗證結果）、`jiezi` / `jiezi-local` / `jiezi-cloud` 策略切換、Ctrl-C 中斷生成而不離開。
  **`jiezi chat`**: Textual full-screen chat: multi-turn, streaming, a status line under each answer (tier, model, t/s, cost, verification), switching among `jiezi` / `jiezi-local` / `jiezi-cloud`, Ctrl-C stops generation without quitting.
- **Herdr 整合**：在 Herdr pane 內（`HERDR_ENV=1`）執行時，`jiezi chat` 以 `herdr pane report-agent` 回報 `working` / `idle` / `blocked`，並提供恢復指令；不在 Herdr 內就不做任何事。
  **Herdr integration**: inside a Herdr pane (`HERDR_ENV=1`), `jiezi chat` reports `working` / `idle` / `blocked` through `herdr pane report-agent` with a resume command; outside Herdr it does nothing.
- **跨平台客戶端**：`ask` 與 `chat` 只透過 HTTP 連 gateway，不依賴引擎所在的機器，所以 Windows 11 原生也能執行（R21.2 的客戶端支援矩陣）。
  **Cross-platform clients**: `ask` and `chat` talk to the gateway over HTTP only, independent of the engine host, so they also run natively on Windows 11 (the R21.2 client matrix).

## Non-Goals

- Desktop App（Tauri 2）與作業系統操控（Phase 8，R22）。
  The Desktop App (Tauri 2) and OS control (Phase 8, R22).
- 對話歷史的同步或雲端備份：對話只在本機，gateway 的軌跡已經記錄。
  Syncing or cloud backup of chats: chats stay local, and gateway trajectories already record them.
- 「信心」數值：要等 `add-parallel-sampling` 的一致率才有意義，這裡先不顯示。
  A "confidence" number: meaningful only with `add-parallel-sampling` agreement rates, so not shown yet.

## Capabilities

### New Capabilities

- `cli`：`jiezi ask`、`jiezi chat`、終端機相容性、Herdr 狀態回報、過渡客戶端的設定與檢查。
  `cli`: `jiezi ask`, `jiezi chat`, terminal compatibility, Herdr state reporting, transitional client setup and checks.

### Modified Capabilities

（無）/ (None)

## Impact

- 依賴：`add-gateway` 先完成。新增執行期套件 Textual 8.2.8（MIT；相依 Rich 15.0.0，MIT）。2026-11-15 查 OSV：兩者這一版都沒有已知漏洞，歷來也沒有任何公告。HTTP 客戶端沿用 `add-gateway` 選定的套件。
  Depends on `add-gateway`. Adds Textual 8.2.8 (MIT; depends on Rich 15.0.0, MIT). OSV on 2026-11-15: no known vulnerabilities in these versions and no advisories ever. The HTTP client reuses whatever `add-gateway` picks.
- 新檔案：`src/jiezi/cli/`、`scripts/jiezi` 增加子指令、`docs/clients.md`、`tests/test_cli_*.py`。
  New files: `src/jiezi/cli/`, new `scripts/jiezi` subcommands, `docs/clients.md`, `tests/test_cli_*.py`.

## 0. 前置 / Prerequisites

- [x] 0.1 `add-gateway` 完成 / `add-gateway` done（實作與實測完成，尚未歸檔 / implemented and live-tested, not yet archived）
- [x] 0.2 使用者決定 OQ1（Textual / Rich）、OQ2（是否切換 Hermes 預設）/ User decides OQ1 and OQ2（2026-11-15：同意 Textual；Hermes 暫不改 / Textual approved; Hermes unchanged）

## 1. 共用客戶端 / Shared client

- [x] 1.1 `cli/client.py`：連線設定、串流解析、`jiezi` 欄位、錯誤與結束碼 / Settings, stream parsing, the `jiezi` field, errors and exit codes

## 2. `jiezi ask`

- [x] 2.1 問題、stdin 附件、終端機與管線兩種輸出、`--json`、`--local` / `--cloud` / Question, stdin attachment, terminal vs pipe output, flags

## 3. `jiezi chat`

- [x] 3.1 Textual 版面、串流、每則回答狀態行、策略切換、Ctrl-C 中斷、`/save` / Layout, streaming, per-answer status, policy switch, Ctrl-C, `/save`
- [x] 3.2 Herdr 狀態回報（`working` / `idle` / `blocked`、恢復指令、`--seq`）/ Herdr reporting

## 4. 過渡客戶端 / Transitional clients

- [x] 4.1 `docs/clients.md`（Hermes Agent、OpenCode 設定）；`scripts/jiezi check-clients`（唯讀）/ Guide and read-only check

## 5. 驗證 / Verification

- [x] 5.1 單元測試（11 個；另以 run_test 對真的 gateway 跑多輪對話、F2 切換到 Claude）：假 gateway 下的 `ask` 輸出與結束碼、`chat` 的 `run_test()` 按鍵與版面、中文寬度、Herdr 回報（假 `herdr`）；`openspec validate add-cli --strict` / Unit tests
- [ ] 5.2 人工檢查清單：Herdr（Claude 可在 Herdr pane 內執行）、Windows Terminal 與 GNOME Terminal（需使用者協助）；結果記入討論記錄 / Manual checklist in the three terminals（待：Herdr、Windows Terminal、GNOME Terminal 人工檢查需使用者協助 / pending: manual checks need the user）

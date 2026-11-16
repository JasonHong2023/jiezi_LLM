## Why

開發計畫 Phase 8.4 Desktop App。使用者 2026-11-16 決定「先做唯讀版雛形」。開發計畫指定前端為 Vite 純前端 SPA（Tauri 2 只是外殼），所以先完成前端並由 gateway 在本機提供，Windows 瀏覽器即可使用；Tauri 外殼與作業系統操控工具之後再加。
Phase 8.4: the user chose a read-only prototype first. The Vite SPA is built and served by the gateway; the Tauri shell and OS-control tools come later.

## What Changes

- `ui/`：React 19 + Vite 8（純 JavaScript，4 個直接相依、鎖定版本，`npm audit` 0 漏洞）。三個頁面：對話（串流、策略切換、Esc 或「中止」立刻停止）、稽核紀錄（時間、策略、由誰回答、引用資料、可否訓練）、狀態（doctor 與 /health）。
  React + Vite front end: chat with one-key stop, audit log, status.
- gateway：`/ui/` 提供建好的檔案，帶嚴格 CSP（只允許 'self'、禁止 iframe、無遠端內容）、nosniff、no-referrer；`GET /admin/trajectories`、`GET /admin/doctor`（需金鑰，只讀）。
  Strict-CSP static serving and two read-only, key-protected admin endpoints.
- 金鑰只存在瀏覽器分頁的 sessionStorage。`scripts/jiezi ui build`（npm ci → npm audit → build）。
  The key lives in sessionStorage only; a build command with an audit step.

## Non-Goals

- 作業系統操控工具（8.2、8.3，前提是技能庫與工具呼叫驗證器）。/ OS-control tools.
- Tauri 外殼（需要 Rust 與 Linux WebKit 系統套件，下一步）。/ The Tauri shell, next.

## Capabilities

### New Capabilities

- `desktop`：桌面前端雛形。/ Desktop front-end prototype.

### Modified Capabilities

（無）/ (None)

## Impact

- 建置後 JS 227 KB（gzip 72 KB）；`ui/node_modules`、`ui/dist` 不進版控。

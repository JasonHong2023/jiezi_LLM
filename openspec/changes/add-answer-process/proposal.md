> **狀態 / Status**：2026-11-18 使用者同意（「內心推理先不用 開始這樣做」）。/ Approved; model reasoning out of scope.

## Why

使用者 2026-11-18：「他思考和請教的過程可以摺疊起來我要看再展開，最終給我看回答的結果和參考資料」。現在網頁只顯示最後的回答，
附錄（【參考資料】【計算】【辭典原文】…）混在回答本文後面；本機草稿、檢查結果、請教 Claude 的經過只記在本機紀錄檔，畫面看不到。
The user wants the process (local draft, checks, consultations) folded away, and the answer and references shown cleanly.

## What Changes

- gateway 回應的 `jiezi.process`：依序列出這題的步驟——讀檔、查資料、看圖工具、每一層作答（誰答、模型、草稿、檢查結果、
  失敗原因、完成時間）。只在本機傳給用戶端；草稿最多 3000 字。
- 網頁版／桌面 App：
  - 回答下方的附錄從本文拆出，放在「參考資料」區（一直顯示）；
  - 「過程」用 `<details>` 預設收合，摘要一行（例：本機作答 → 檢查沒過 → 請教 Claude，共 85 秒），展開看每一步；
    之前層的草稿再收一層；唯讀代理的步驟答完後也收進「過程」；
  - 回答中的即時狀態照舊。
- `jiezi chat`、Hermes 等用戶端不變（多一個它們不讀的欄位）。

## Non-Goals

- 模型的內心推理（思考模式預設關，使用者 2026-11-18：先不用）。

## Capabilities

### Modified Capabilities

- `gateway`：新增 Answer Process 需求。

## Impact

- `src/jiezi/runtime/process.py`（新）、`gateway.py` 的 `_meta`；`ui/src/api.js`、`App.jsx`、`style.css`；測試。

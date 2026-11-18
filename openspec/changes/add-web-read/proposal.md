> **狀態 / Status**：2026-11-18 提案，等使用者審閱。/ Proposed, awaiting review.

## Why

2026-11-18 使用者問「仔細閱讀這個網址的內容並記憶起來 https://docs.python.org/3/」：本機沒有讀網頁的能力，`needs_web` 直接轉給
Claude（Claude 用 WebFetch 讀）；使用者明說要記憶，記憶卻因 `web_or_live` 不存。使用者原則：請教 Claude 是最後手段。
Local cannot read web pages, so URLs go to Claude, and an explicit "memorize" was not stored.

## What Changes

- gateway 讀使用者訊息裡的網址（http／https，一題最多 3 個）：本機直接 GET，只收 HTML／純文字、≤ 5 MB、15 秒逾時、
  跟隨轉址最多 5 次；**拒絕**本機與內網位址（127.0.0.0/8、10/8、172.16/12、192.168/16、169.254/16、::1 等，轉址後也檢查）；
  不帶 cookie、不送使用者資料。用現有的文件讀取器把 HTML 轉成文字，以【文件：網址】附進問題，之後照長文件、
  injection-guard（網頁內容一律當資料）處理。
- 讀到網頁的題目不再判為 `needs_web`；讀不到才照舊轉交。真正的即時查詢（「今天天氣」「最新新聞」，沒附網址）仍走原路。
- 「記住／記憶起來／背下來」＋網址：本機讀完把重點存進記憶 wiki（`notes/`，標明網址與讀取日期，Obsidian 可改），
  之後問相關問題會附上。
- metadata `web_read: [{url, bytes, ok|why}]`；過程顯示「讀取網頁」。

## Non-Goals

- 搜尋引擎（沒有網址的「幫我查」）——另案（例：自架 SearXNG）。
- 執行網頁的 JavaScript（只讀伺服器回的 HTML）。

## Capabilities

### Modified Capabilities

- `gateway`：新增 Typed URLs 需求。

## Impact

- 這台電腦會連到使用者給的網址（只 GET）；內容不出本機。JS 動態網頁可能讀不到內容。

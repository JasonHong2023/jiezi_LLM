## Why

add-long-documents 把「長文件的追問」列為 Non-Goal：chat 回答完就把歷史中的文件全文換成一行，要再問同一份文件得重新 `/file`。使用者 2026-11-16 同意依建議順序在防提示注入之後補上追問。
add-long-documents left follow-up questions out: after one answer the document was dropped and had to be attached again. The user approved adding follow-ups next (2026-11-16).

## What Changes

- `jiezi chat`：`/file 路徑` 附上的文件會**一直附著**，之後每一題送出時重新包進最新的問題（歷史只存問題本身，不重複存全文）；狀態列顯示目前附著的文件；`/file clear` 取消，`/clear` 一併清除；同名文件視為更新；合計上限 150 萬字。
  Documents stay attached in chat and ride with each new question; history keeps the bare question. `/file clear` detaches.
- gateway／`longdoc.py`：
  - 每一題都依「這一題」重新挑段落；挑段落時把上一輪問答當提示（權重 0.5），「那相關數據是多少」這類沒有關鍵字的追問也找得到段落。
  - 追問時預留最多 600 token 給上一輪問答，濃縮的額度相應縮小，上一輪對話不會被上下文把關裁掉。
  - 問答的分段從 1800 token 改為 600 token：原本額度內只放得下一段，等於沒有在挑；改小後可放多段、挑得更準。摘要的分段不變。
  - 段落評分只計文件裡出現過的雙字詞（文件沒有的字不再稀釋分數），問題與提示的分數才可相比。
  - 各段重點（map 階段）放在 gateway 的記憶體快取（最近 8 份、不寫入磁碟、有任何一段失敗就不快取）；同一份文件再要摘要時不重跑。
  Chunks are re-selected per question with the previous exchange as a half-weight hint; room is reserved for that exchange; QA chunks shrink to 600 tokens; per-chunk notes are cached in memory.
- 更正（R19.4）：add-long-documents 的「chat 回答後把歷史中的文件全文換成一行說明」由本變更取代——歷史從一開始就只存問題。
  Correction: the "shrink after answering" step of add-long-documents is replaced; history never holds the document.

## Non-Goals

- 重開 chat 後自動恢復附著的文件（要重新 `/file`；文件全文不寫進歷史檔）。/ Restoring attachments after restarting chat.
- 桌面網頁與 `jiezi ask` 的追問（ask 是一次一題；桌面網頁還沒有附檔功能）。/ Follow-ups in the desktop page or `ask`.
- 用語意向量挑段落、跨文件比對。/ Embedding-based selection, cross-document comparison.
- 策略為 `jiezi-ask-claude`／`jiezi-cloud`，或本機無法使用而轉交時，每一題都會把整份原文送給 Claude／雲端（沿用 add-long-documents 的限制）。/ Escalated requests still carry the whole document each turn.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `documents`：新增追問的需求（`documents` 由尚未歸檔的 add-long-documents 建立，須先歸檔該變更）。/ Adds follow-up requirements; archive add-long-documents first.

## Impact

- chat 每一題都把文件送到本機 gateway（127.0.0.1，10 萬字約 300 KB），gateway 重新分段與評分（毫秒級）。
- 無新相依、無新設定。

## Why

使用者 2026-11-15：「不只是請教他要會記憶」「記憶模組可以用 HERMES 的 WIKI 方式嗎?」。缺口報告顯示同一題反覆出現時芥子每次都從頭來；請教 Claude 得到的答案、使用者的更正都沒有留下。
Jiezi forgot everything between questions; consulted answers and the user's corrections were lost.

## What Changes

- 記憶 wiki（Hermes llm-wiki 格式，Markdown 為正本）：`var/memory/wiki/` 下 `topics/<主題>.md`（問答、使用者更正、相關連結，依主題合併）、`notes/使用者要我記住的事.md`、`index.md`、`log.md`；可用 Obsidian 或 Hermes dashboard 瀏覽修改，索引自動重建。
  A Markdown memory wiki in the Hermes llm-wiki format, browsable and editable; the index follows edits.
- 自動記住：請教 Claude 或雲端的答案（上網／即時類、問芥子自己、依賴前文的追問不存；180 天後不再使用）。
  Consulted answers are saved automatically (web/live, self and context-dependent questions excluded; 180-day use).
- 「記住：…」存成筆記，每次對話都附上；「不對，…」連同前一題存成更正，問到類似問題時最優先附上。
  "記住：…" notes join every chat; "不對，…" corrections are attached first to similar questions.
- 幾乎相同的問題（去掉提問用語後雙字相似度 ≥ 0.85）直接用記憶回答，不載入模型也不再請教；相似度 ≥ 0.35 時當參考資料附給模型。
  Near-identical questions are served from memory; related ones get the memory as reference data.
- `jiezi chat` 保存聊天歷史（`var/chat/history.json`），重開時接續；`--new` 開新對話、`/clear` 清除；送給 gateway 的上下文限最近 12 則。
  Chat history persists and resumes; context sent is capped at 12 messages.
- `scripts/jiezi memory list|search|forget|path`。

## Non-Goals

- 用記憶訓練模型：含 Claude／雲端輸出的頁面標 `training_use: false`，自我進化必須排除（Anthropic 條款）。
  Training on memory: pages with Claude or cloud output are not trainable.
- 寫進使用者的 `~/wiki`：它會自動備份到公開的 GitHub repo，使用者選擇芥子自己的 wiki。
  Writing into ~/wiki, which is backed up to a public repository.
- 用 0.6B 改寫或摘要記憶（改寫會出錯）；主題歸類只用文字相似度。/ No 0.6B rewriting; topics by text similarity.

## Capabilities

### New Capabilities

- `memory`：記憶 wiki、記住與更正、從記憶回答、聊天歷史。/ Memory wiki, notes, corrections, recall, chat history.

### Modified Capabilities

（無）/ (None)

## Impact

- 只用標準函式庫；設定 `JIEZI_MEMORY`（預設 on）。檔案都在 `var/`，不進版控。

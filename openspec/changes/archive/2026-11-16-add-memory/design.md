## Decisions

### D1 — Markdown 為正本 / Markdown is the source of truth
格式比照使用者的 Hermes llm-wiki（`~/.hermes/hermes-agent/plugins/llm-wiki`）：YAML frontmatter（title、type、created、updated、tags、confidence，另加 `training_use: false`）、`[[wikilinks]]`、`index.md`、`log.md` 表格。使用者可直接用 Obsidian 修改或刪除；每次查詢前比對檔案修改時間，有變就重新解析。位置 `var/memory/wiki/`（使用者選擇；`~/wiki` 會自動推到公開的 GitHub repo）。
Hermes llm-wiki format; pages re-parsed when their mtimes change; kept under var/.

### D2 — 主題合併 / Topic merging
Karpathy 式「編譯」：新問題若 (a) 某主題標題的雙字有 60% 以上出現在問題裡，或 (b) 已有相似度 ≥ 0.35 的問題，就加進那一頁；否則以「去掉提問用語的問題」當標題開新頁。同一題只留最新答案。答案中的 Markdown 標題改成粗體以免打亂頁面結構。「相關」段列出問題或答案中出現的其他主題標題。
New questions join a topic whose title they mostly contain or that holds a similar question; else a new page.

### D3 — 相似度 / Similarity
去掉提問用語（什麼是、一句話、請問、怎麼…）後比較中文雙字的 Jaccard；內容完全相同為 1.0。≥ 0.85 直接用記憶回答（`jiezi`、`jiezi-local`），≥ 0.35 當參考附給模型；直接請教（`jiezi-ask-claude`）一律重新請教。
Bigram Jaccard after dropping question wording; ≥0.85 served directly, ≥0.35 attached as reference.

### D4 — 何時不存 / What is not stored
上網／即時（網址、新聞、今天、天氣…）、問芥子自己（名字、作者…）、多輪對話中依賴前文的追問（那、它、剛才…或少於 8 字）。答案 180 天後不再使用（頁面保留）。
Web/live, self and context-dependent questions; answers older than 180 days are not used.

### D5 — 記住與更正 / Notes and corrections
「記住：X」「請記得 X」→ 筆記頁，最近 20 條附在每次對話的系統提示之後（本機與請教都有）。「不對，X」「錯了，X」「更正 X」且前面有問答 → 存到前一題所屬主題的「使用者更正」，直接回覆確認，不呼叫模型。查詢時更正排在最前面；有更正的問題不直接用記憶答案，改交給模型參考。
Notes join every chat; corrections attach to the previous question's topic and take priority.

### D6 — 訓練與授權 / Training and terms
Claude／雲端答案只用來查（`claude-consult-output` 已登記訓練：否）；從記憶回答時軌跡標 `training_use: false`。只有使用者自己的更正與筆記的請求不改標記。
Lookup only; serving remembered Claude text marks the trajectory not trainable.

### D7 — 聊天歷史 / Chat history
`var/chat/history.json` 保留最近 200 則，重開顯示最近 20 則並接續；送給 gateway 的上下文限最近 12 則（核心引擎上下文 4096）。
Keeps 200 messages, shows 20 on resume, sends the last 12.

## Risks / Trade-offs
- 雙字相似度會把字面相近但意思不同的問題當成同一題 → 直接回答門檻設在 0.85，且附註日期與來源連結，使用者可用「不對，…」更正或刪除頁面。
  Lexically similar but different questions → high direct threshold, visible source note, easy correction.
- 記憶中的答案可能過時 → 180 天上限、即時類不存。/ Stale answers → 180 days, live topics excluded.

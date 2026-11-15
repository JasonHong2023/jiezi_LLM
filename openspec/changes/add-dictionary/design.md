## Context

g0v/moedict-data 的 `dict-revised.json.xz` 是教育部《重編國語辭典修訂本》的 JSON：每筆有 `title`、`heteronyms`（注音、拼音、`definitions`：`def`、`type`、`example`、`quote`、`synonyms`、`antonyms`）。教育部的公眾授權使用說明：可重製散布（含商業），須標示出處，詞目、音讀、釋義不得修改、不得轉為簡化字；教育部解釋格式轉換不屬改作。
The g0v JSON carries title, heteronyms (bopomofo, pinyin, definitions). The MOE license notes allow redistribution with attribution, forbid changing entries or converting to Simplified characters, and treat format conversion as not an adaptation.

## Decisions

### D1 — 儲存 / Storage
`var/dict/dict.sqlite`：`entries(source, title, data)`，`title` 建索引；`data` 是原始 JSON（不改內容）。建置時核對 SHA-256 與筆數；`dict_meta` 記錄來源、版本、筆數、建置時間。
SQLite with the original JSON per entry, indexed by title; SHA-256 and entry count checked at build time.

### D2 — 何時查 / When to look up
只在問題明顯是在問詞語時查：(1) 「」或『』或引號標出的詞；或 (2) 訊息含「意思、意義、解釋、定義、注音、拼音、讀音、怎麼念、怎麼讀、成語、造句、同義、反義、出處、典故」等字樣時，從最後一則使用者訊息中找出辭典裡有的詞（長的優先、不重疊、至少 2 字、最多 3 個）。一般閒聊不查，避免把無關詞條塞進對話。
Look up only when the question is clearly about words: a quoted term, or wording such as "meaning / definition / pronunciation / idiom / example sentence / synonym / origin", taking up to three longest non-overlapping dictionary titles (2+ characters) from the last user message.

### D3 — 引用 / Citation
詞條以原文附在一則 system 訊息中（每筆最多約 600 字，書證最多 2 則），並要求「以辭典資料為準，回答末尾註明：資料來源：教育部《重編國語辭典修訂本》」。回應的 `jiezi.sources` 列出 `{source, title}`。用到「禁止改作」來源時，軌跡 `training_use` 設為 `false`。
Entries go verbatim into a system message (about 600 characters each, at most two quotations), with an instruction to answer from them and cite the MOE dictionary; `jiezi.sources` lists them; no-derivatives sources set `training_use: false`.

### D4 — 開關 / Switch
`JIEZI_DICTIONARY=on`（預設）；辭典檔不存在時跳過並在 `/health` 顯示。夜間評測不經過 gateway，不受影響。
On by default; skipped with a `/health` note when not built. Night evaluations bypass the gateway.

### D5 — 實測後的補強（2026-11-15，使用者「有問題就修正」）/ After live testing

- 0.6B 依辭典轉述時仍會說錯（例如把樂不思蜀解釋成「樂於某事，不記得來」）。改由 gateway 在回答後直接附上「【辭典原文】」與出處，不經模型轉述；給模型的指示改為「依辭典簡短回答、不必另註出處」。
  The 0.6B still misparaphrased entries; the gateway now appends the verbatim entry and attribution itself, and the model is told to answer briefly without adding its own citation.
- 監控發現本機輸出含簡體字（「禪」寫成「禅」）。新增 `jiezi/textconv.py`：只把 OpenCC 表中「候選不含自己」的純簡體字換成第一個候選，本身也是正體字的字（后、台）不動；只用於本機模型輸出。
  Monitoring caught Simplified characters (禅 for 禪); `jiezi/textconv.py` now replaces Simplified-only characters in local model output, leaving characters that are also Traditional untouched.
- 實測：重編國語辭典 161,194 筆、建置 7.6 秒、約 79 MB；「早安」不觸發；成語、造句、同義詞問題正確觸發並標 `training_use: false`。
  Measured: 161,194 entries, built in 7.6 s, about 79 MB; small talk does not trigger; idiom, sentence and synonym questions do.

## Risks / Trade-offs
- 0.6B 可能沒有照辭典改寫或漏掉出處 → 之後可由驗證器檢查出處字樣；先記錄於軌跡觀察。
  The 0.6B may paraphrase loosely or omit the citation → observe in trajectories; a verifier can check later.
- 誤判查詢時機 → 只在明確的詞語問題觸發，並限制 3 筆。/ Over-triggering → explicit cues only, at most three entries.

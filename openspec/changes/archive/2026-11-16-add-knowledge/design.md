## Context

taiwan-md（commit `f4c39783`）：`knowledge/<分類>/<主題>.md` 為繁中原文（frontmatter 有 title、category、lastHumanReview），另有 12 種語言翻譯。1163 篇原文中 196 篇經人工審核。授權寫在 README（CC BY-SA 4.0），沒有 LICENSE 檔。
The zh-TW originals carry frontmatter; 196 of 1163 are human-reviewed. CC BY-SA 4.0 per the README; no LICENSE file.

## Decisions

### D1 — 鎖定與核對 / Pinning
lock 檔列出每篇的路徑與 git blob 雜湊（一次 tree API 取得）；`build` 從 raw.githubusercontent 依 commit 下載，逐檔核對，不符就停止（不建索引）；並行 4 條連線。
A lock file with per-file git blob hashes; downloads are verified one by one, four at a time.

### D2 — 索引 / Index
去掉 frontmatter、圖片、註腳與連結網址後，依 `## ` 切段；「延伸閱讀、參考資料」等連結清單段不收。每段以「文章名＋標題＋內文」的中文雙字（英數字詞整個）寫進 FTS5，所以兩字詞也找得到。解析前先把純簡體字改正體（CC BY-SA 允許改作）。
Sections split on `## `, link-list sections skipped, indexed as Chinese bigrams in FTS5; Simplified-only characters fixed first.

### D3 — 何時查 / When to look up
1. 問題提到某篇文章的主題名稱（長的優先，最多 2 篇）→ 附該篇開頭（概覽），問題還有其他字詞且只點名一篇時，再加最相關的一段。
2. 否則全文檢索：命中的雙字至少 3 個且佔問題的 30% 以上，而且文章名或段落標題與問題至少有 2 個共同雙字（避免「寫 Python 函式」配到提到 Python 的文章）。
Named articles first (overview plus the best section); otherwise full-text hits with thresholds and a name/heading overlap of at least two bigrams.

### D4 — 引用與訓練 / Citation and training
每段最多 1200 字、最多 2 段給模型，提醒「可能有錯、沒提到的不要編造」；回答後附「【參考資料】」標題、GitHub 連結（鎖定 commit）、出處，未審核文章註明「未經人工審核」。使用者 2026-11-15 決定全部可訓練（衍生物適用相同方式分享）。
At most two sections of 1200 characters; the appendix lists titles, pinned links and attribution, marking unreviewed articles. All trainable per the user (share-alike applies).

### D5 — 簡轉繁修正 / Conversion fix
OpenCC 的簡轉繁表會把正體字換成異體字（群→羣、峰→峯）。`textconv` 改為只換不在 Big5（cp950）裡的字；Big5 收的是正體字形，真正的簡體字（双、湾、禅、内）都不在裡面。
Only characters outside Big5 are converted.

## Risks / Trade-offs
- 雙字比對沒有語意，仍可能誤觸發或漏查 → 門檻保守；之後可換向量檢索。/ Bigram matching has no semantics → conservative thresholds; vectors later.
- 多數文章未經人工審核 → 提示模型可能有錯，出處註明。/ Mostly unreviewed → the model is warned and the appendix marks it.

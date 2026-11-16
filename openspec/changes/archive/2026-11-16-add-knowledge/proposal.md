## Why

使用者希望芥子學會 Taiwan.md 的台灣知識（2026-11-15）。小模型對台灣的人物、歷史、飲食常會編造；本機全文檢索、回答前先查，換核心模型也不用重做。
The user wants jiezi to know the Taiwan.md knowledge base. Local retrieval before answering reduces invented facts and survives a core change.

## What Changes

- `knowledge/manifest.toml` 與 `knowledge/taiwan-md.lock.json`：鎖定 commit，逐檔記錄 git blob 雜湊（1163 篇繁中原文，排除翻譯與目錄頁）。
  Manifest and lock file pinned to one commit with per-file git blob hashes.
- `scripts/jiezi knowledge build|search`：下載、逐檔核對、建 SQLite FTS5（中文雙字切詞）索引；`search` 顯示會查到的段落。
  Download, verify, build an FTS5 bigram index; `search` shows what would be retrieved.
- gateway 對台灣主題問題附上 1–2 段原文給模型，回答後附文章標題、連結、CC BY-SA 出處，未經人工審核的文章會註明。
  The gateway grounds Taiwan questions with one or two sections and appends titles, links and attribution, marking unreviewed articles.
- 簡轉繁修正：只換不在 Big5 的字，正體異體字（群、峰、床）不再被改成羣、峯、牀（影響本機模型輸出與所有資料來源）。
  Conversion fix: only characters outside Big5 are replaced, so 群/峰/床 are no longer turned into variants.

## Non-Goals

- 向量檢索（之後的 RAG 階段）。/ Vector retrieval (later RAG phase).
- 12 種語言的翻譯版。/ The translations.

## Capabilities

### New Capabilities

- `knowledge`：台灣知識庫的來源、建置、檢索與對話引用。/ Taiwan knowledge base: sources, build, retrieval and chat grounding.

### Modified Capabilities

（無）/ (None)

## Impact

- 下載約 22 MB，索引約 68 MB（`var/`，不進版控）；建置約 2 分鐘（網路為主）。只用標準函式庫。設定 `JIEZI_KNOWLEDGE`（預設 on）。
  About 22 MB downloaded and a 68 MB index under `var/`; about two minutes to build. Standard library only.

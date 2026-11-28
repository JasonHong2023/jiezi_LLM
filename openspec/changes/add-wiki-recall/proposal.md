# add-wiki-recall：回答時查使用者自己的 ~/wiki / Recall from the user's own ~/wiki

> **狀態 / Status**：2026-11-27 提案（`~/projects/tmp/LLM_discussion/wiki-recall-proposal-2026-11-27.md`）；2026-11-28 使用者
> 回覆「1 可以 2 預設先不查 3 好」：排除 `social/`、`boards/`；超過 200 KB 的頁面預設不收；轉交雲端時拿掉 wiki 段落。
> Proposed 2026-11-27; on 2026-11-28 the user accepted the exclusions, leaving oversized pages out and stripping wiki
> passages before escalation.

## Why / 為什麼

芥子只讀自己的記憶 wiki（`var/memory/wiki`），完全不讀使用者的知識庫 `~/wiki`（376 頁，用 wiki-ingest 持續整理進去）。
回答時用不到使用者自己整理過的內容。
Jiezi reads only its own memory wiki, never the user's curated `~/wiki`.

## 分類、現成方案搜尋、資安掃描 / Classification, existing-solution search, security scan

**分類**：芥子內建（gateway 附加資料），沿用台灣知識庫的 FTS5 中文雙字索引；不是 SKILL 也不是 MCP——4B 模型常常
不會主動查，gateway 直接查、直接附上比較穩。
Classification: core gateway grounding reusing the knowledge base's FTS5 bigram index; no SKILL or MCP.

**現成方案**：[tobi/qmd](https://github.com/tobi/qmd)（markdown 的 BM25＋向量＋LLM 重排，要 Node／Bun 與另一套模型）
只借設計；[basic-memory](https://pypi.org/project/basic-memory/)（AGPL-3.0 MCP，自己的筆記格式、可寫入）不採用；
芥子既有 `knowledge.py` 採用，不新增套件。
Existing: qmd (design only), basic-memory (not used); the in-house knowledge index is reused.

**資安掃描**：
- 唯讀：不寫 `~/wiki`、不動它的 git；索引在 `var/wiki-recall/`（不進 git）。
- 不收：`raw/`、`social/`、`boards/`、`.git/`、`.tools/`、`.obsidian/`、`images/`、符號連結、超過 200 KB 的頁面、
  `private: true` 的頁面；可用 `JIEZI_WIKI_RECALL_EXCLUDE` 加。
- 看起來像金鑰的段落（`sk-…`、`ghp_…`、`AKIA…`、私鑰、`password: …`、大小寫數字混合的長亂數串）整段不收，報告只列位置。
- 段落當資料、走 injection guard；回答標成不可訓練（`private`），雲端、Claude、老師模型與第 2 層協助者都看不到 wiki 段落。
- 不新增套件、不連網；預設關閉（`JIEZI_WIKI_RECALL=on` 才開）。
Security: read-only; exclusions; secret-looking sections skipped; data under the injection guard; untrainable; never
sent to cloud, Claude, teachers or tier-2 helpers; no dependency; off by default.

## What Changes / 變更內容

- `scripts/jiezi wiki index`：讀 `~/wiki`（`JIEZI_WIKI_RECALL_PATH` 可改），依 `## ` 切段，簡體轉繁體後建索引；
  只重做 sha256 變了的頁面，刪掉已不存在頁面的索引；報告列出太大、private、疑似金鑰而沒收的位置。
  `scripts/jiezi wiki search <問題>` 查看會附上哪些段落。
- gateway：記憶之後查 wiki，門檻和台灣知識庫沒點名文章時一樣（命中雙字夠多，且頁名或段落標題有兩個以上共同雙字）；
  問題直接提到頁名時附那一頁。最多 2 段，回答後附【我的 wiki】出處。創作類、看圖、附文件的請求不查。
- 轉交雲端／請教 Claude／老師模型前拿掉 wiki 段落；本機答案用到 wiki 時不走第 2 層回饋。
- `doctor` 與 `/health` 顯示開關與頁數。

## Non-Goals / 非目標

- 寫入 `~/wiki`（wiki-ingest 負責）、讀 `raw/` 原文、向量檢索（之後量測需要再加）、包成 MCP。

## Impact / 影響

- 程式：`src/jiezi/wiki_recall.py`（新）、`runtime/gateway.py`、`runtime/settings.py`、`runtime/__main__.py`、`runtime/doctor.py`。
- 測試：`tests/test_wiki_recall.py`。
- 文件：`docs/clients.md`、`docs/capabilities.toml`。

## Why

使用者希望芥子「學習使用」tw-taxonomy（108 課綱國小學習知識圖譜）與 zetria-org/curriculum 的國高中各版本課本章節對照（2026-11-15）。小模型對課綱代碼、先修關係與各版本課本章節幾乎一定會編造；放在本機、回答前先查，能立刻改善，換核心模型也不用重做。
The user wants jiezi to use tw-taxonomy (a 108-curriculum primary-school knowledge graph) and the zetria-org/curriculum textbook chapter comparison. Small models invent curriculum codes, prerequisites and chapters; a local lookup before answering fixes that and survives a core change.

## What Changes

- `curriculum/manifest.toml`：兩個來源，鎖定 commit 與每個檔的 SHA-256、授權、是否可訓練、出處文字。`scripts/jiezi curriculum build` 下載並核對到 `var/curriculum/`。
  Two sources pinned by commit and per-file SHA-256 with license, training flag and attribution; `build` downloads and verifies into `var/curriculum/`.
- `scripts/jiezi curriculum lookup|path|plan|textbook`：查微主題或課綱代碼、列出完整先修鏈、依先修關係排出某科某年級的教學順序、查課本某冊某版本的單元或某單元在哪些版本。
  Commands to look up topics or codes, list prerequisite chains, order a subject/grade by prerequisites, and look up textbook chapters.
- gateway 偵測課綱、國小學習與課本章節問題，把資料原文附給模型，並在回答後附上原文與出處；`jiezi.sources` 列出用到的資料。
  The gateway grounds curriculum, primary-learning and textbook questions, appends the verbatim data with attribution, and lists it in `jiezi.sources`.

## Non-Goals

- 執行上游附的腳本（排課序由芥子自行實作）。/ Running upstream scripts.
- 訓練進權重（Phase 6）；本變更只標記可訓練。/ Training into weights; this change only flags the data as trainable.
- 上游空白的檔案（高中必修除生物外、國中國文）。/ Empty upstream files.

## Capabilities

### New Capabilities

- `curriculum`：課綱知識圖譜與課本章節的來源、建置、查詢與對話引用。/ Curriculum graph and textbook chapters: sources, build, lookup, chat grounding.

### Modified Capabilities

（無）/ (None)

## Impact

- 下載約 1.3 MB（JSON 與 Markdown），不進版控；只用標準函式庫。設定 `JIEZI_CURRICULUM`（預設 on）。
  About 1.3 MB downloaded, not committed; standard library only. Setting `JIEZI_CURRICULUM` (default on).

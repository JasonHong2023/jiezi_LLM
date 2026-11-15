## Context

tw-taxonomy（commit `512492c6`）：569 微主題、717 先修關係（DAG，hard 510／soft 207）、1840 條國小課綱學習重點、103 則家長摘要；上游 manifest 的 SHA-256 與下載檔相符；全為正體中文。授權：資料庫與自撰文字 CC BY 4.0；課綱條文 © 教育部，依著作權法第 50 條與政府開放宣告收錄，需保留「非教育部官方產品」聲明。
zetria-org/curriculum（commit `4ed07c9d`，MIT）：國中 7 科（國文為空檔）與高中必修生物的各版本課本章節（`## 科目 冊別`、`### 版本`、`- 單元`、`  - 小節`），共 102 冊次版本；有 1 個純簡體字（内）。

## Decisions

### D1 — 儲存 / Storage
資料小（約 1.3 MB），下載檔核對 SHA-256 後放在 `var/curriculum/`，gateway 啟動時載入記憶體；不另建 SQLite。載入時檢查先修關係都指向存在的微主題、且無環。
Small data: verified files under `var/curriculum/`, loaded into memory at gateway start; references and acyclicity are checked on load.

### D2 — 何時查 / When to look up
- 課綱代碼（`N-3-9`、`math:n-Ⅱ-6`，羅馬數字正規化為 ASCII；沒寫科目就比對所有科目）一律查。
- 有課綱用語（課綱、先修、年級、教學、評量、孩子……）時，找出提到的微主題名稱（長的優先、最多 3 個）；問先修時附完整先修鏈。
- 有課綱用語、問「學什麼／內容」且提到國小科目與年級（或低中高年級）時，附該年級依先修排序的微主題與領域摘要。
- 提到國中、高中（國一、七年級、高一……）時不套用國小規則。
- 課本：有課本用語（課本、版本、章節、單元、翰林、康軒……）時，科目＋冊別（7上、國一上、八年級下、高一上）→ 各版本單元；否則找提到的單元名稱 → 列出所在冊別與版本。
Lookups trigger on codes, on curriculum cues with topic names or subject+grade, and on textbook cues with subject+volume or a unit title; secondary-school wording skips primary rules.

### D3 — 引用 / Citation
資料以 system 訊息給模型（每個微主題約 900 字以內、課本合計 2500 字以內），要求不得編造代碼、先修或章節；gateway 在回答後附「【課綱資料原文】」與實際用到的來源出處（與 add-dictionary D5 相同，不經模型轉述）。
Data goes in a system message with size caps; the gateway appends the verbatim block and only the attributions actually used.

### D4 — 訓練標記 / Training flag
使用者 2026-11-15 決定：tw-taxonomy 全部（含課綱條文）可訓練；zetria 為 MIT，可訓練。因此引用這些資料不把軌跡改成 `training_use: false`。
User decision: all of tw-taxonomy (including curriculum text) is trainable; zetria is MIT. Grounding with them leaves `training_use` unchanged.

### D5 — 課本資料正規化 / Textbook normalization
MIT 允許修改：解析時把純簡體字換成正體（使用者：不要有簡體中文），但 `群` 這類本身是正體的字不換成異體 `羣`；上游「全華板」改為「全華版」。
MIT allows changes: Simplified-only characters become Traditional (群 is kept), and the upstream typo 全華板 becomes 全華版.

## Risks / Trade-offs
- 微主題名稱很短（如「速度」）時可能誤觸發 → 需同時有課綱用語。/ Short names over-trigger → a curriculum cue is also required.
- 課本資料只涵蓋部分科目與版本 → 查不到時不附資料，由模型照常回答。/ Partial coverage → no grounding when not found.

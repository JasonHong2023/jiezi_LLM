# add-notebooks 提案 / Proposal

> **狀態 / Status**：提案（2026-11-24，主控）。使用者 2026-11-24 問能否做類似 Gemini／NotebookLM 的筆記本，決定先做「筆記本＋引用問答」，並要求**結合長期記憶**。同日決定：一般對話自動查筆記本（召回預設開）；筆記本問答**每題自動存進記憶，但存之前要查證，有錯誤或不清楚的地方要提出來**；來源找不到時明說找不到。語音摘要 Podcast、心智圖、測驗留待之後的 change。

## Why / 為什麼

現在附加文件只對單次對話有效：每一題都要重送整份文件，段落向量只在記憶體，gateway 重啟就沒了；回答只在最後列「參考資料」，看不出哪一句出自哪裡。使用者想要像 NotebookLM 一樣：把一批資料收進一本筆記本、隨時回來問、每句話都能點回原文，而且筆記本裡學到的東西要進入芥子的長期記憶。

Attached documents live for one conversation only and answers cite sources only at the end. Users want persistent notebooks with sentence-level citations, tied into long-term memory.

## 分類、現成方案搜尋、資安掃描 / Classification, existing-solution search, security scan

- 分類 / Classification：**核心模組**，不是 `SKILL` 也不是 `MCP`：重用 gateway 的文件讀取、檢索、驗證器、信任把關、記憶與轉交管線，以 gateway 端點與桌面頁面提供。
- 現成方案搜尋 / Existing-solution search（2026-11-24 主控查證）：
  1. **Open Notebook**（lfnovo/open-notebook，MIT，★4.2 萬）：LangChain＋LangGraph＋SurrealDB＋Next.js 的獨立系統。
  2. **SurfSense**（MODSetter/SurfSense，Apache-2.0，★1.7 萬）、**Kotaemon**（Cinnamon/kotaemon，Apache-2.0，★2.6 萬）：同樣是獨立服務。
  3. 不採用、改為內建，理由：都是完整的獨立系統，無法使用芥子的驗證器、信任分級、長期記憶與分層轉交；預設大上下文模型，芥子核心每槽只有 4,096 token；會引入 LangChain 等大量相依（R23 審查負擔）。參考它們的設計：來源／筆記本兩層、引用編號對應段落、一鍵產生摘要類筆記。
- 資安掃描 / Security scan：**不新增任何套件**（文件讀取用既有 `documents`、網頁用既有 `webread`、音檔用 add-asr、向量用既有 embedding 引擎與 SQLite）。來源全部存在本機 `var/notebooks/`（不進版控）；每份來源經提示注入掃描與信任把關（網頁＝unverified、使用者上傳的檔案＝依內容掃描結果），被標記的來源在回答中照樣可引用但會警示，且不得進訓練資料。所有端點需 gateway 金鑰、只綁 127.0.0.1。

## What Changes / 變更內容

1. **筆記本與來源**：`var/notebooks/<id>/`：`notebook.json`（名稱、說明、建立時間）、`sources/<sid>.json`（標題、種類 file／url／text／audio、原始檔名或網址、sha256、加入時間、信任等級、全文）、`index.sqlite`（段落：來源、序號、起訖字元位置、文字；雙字詞索引；段落向量）。段落約 350 token、相鄰重疊 15%，保留字元位置供引用定位。
2. **加入來源**：檔案（PDF、Word、PowerPoint、Excel、網頁、純文字、圖片 OCR）、網址（web-read）、貼上的文字、音檔／影片（add-asr 轉逐字稿，附時間碼）。同一份內容（sha256 相同）不重複加入。
3. **引用問答**：聊天請求帶 `jiezi_notebook: <id>`（OpenAI 相容的擴充欄位）即在該筆記本內回答，沿用一般管線（本機優先、驗證、需要時轉交）。檢索＝雙字詞＋向量＋RRF（沿用 longdoc.fuse），取能放進上下文的前幾段，每段編號 [1]…[n]。
   - 指示模型每句事實後標 [n]；**引用檢查器**：編號必須存在，且該句與被引段落的字詞重疊達門檻，否則把該引用移除並標「（未找到出處）」；全部來源都找不到相關段落時，回答「這本筆記本的來源裡找不到」，不靠一般知識亂答（可在請求加 `jiezi_notebook_general: true` 允許補充一般知識，並明確標示哪些不是出自來源）。
   - 回答的 meta 帶 `citations`：[{n, source_id, title, chunk, start, end, quote}]。
4. **一鍵筆記**：摘要、常見問答、學習指南三種範本；逐來源分段摘要（map）再彙整（reduce），每點附引用；產生的筆記存成筆記本裡的「筆記」，可再當來源被引用。
5. **結合長期記憶**（使用者要求）：
   - **記憶進筆記本**：筆記本問答也附上「使用者要我記住的事」與相關的「使用者更正」（不附舊的請教答案，避免和來源衝突）。
   - **筆記本進記憶**：每本筆記本在記憶 wiki 有一頁 `notebooks/<名稱>.md`（來源清單、各來源一段摘要、建立／更新時間），Obsidian／Hermes 可以瀏覽；一般對話（不在筆記本內）問到相關主題時，芥子會先查這些摘要頁，命中時從該筆記本取段落回答並引用（`JIEZI_NOTEBOOK_RECALL`，預設開，使用者 2026-11-24 決定）。
   - **答案自動存進記憶，先查證**（使用者 2026-11-24）：每則筆記本回答完成後自動查證，全部通過才寫進記憶主題頁（種類 `notebook`、provenance 記筆記本與來源段落）。查證項目：
     a. 每句事實都有通過引用檢查的出處（沒有被移除的引用、沒有「未找到出處」的句子）；
     b. 被引用的來源之間沒有互相矛盾（同一數字、日期、名稱在不同來源說法不同）；
     c. 與記憶裡既有的使用者更正、先前存過的筆記本答案沒有衝突；
     d. 被引用的來源沒有被提示注入掃描標記，也不是 tainted；
     e. 回答沒有「可能」「不確定」「來源沒有說明」之類的不確定語句，問題本身也不含糊（例如沒有指明是哪一份文件、哪一年）。
     沒通過時**不存**，並在回答下方列出「查證發現」：哪一句、哪個問題（例如「第 2 句沒有出處」「來源 A 說 2 個月、來源 B 說 3 個月」「與你 11-20 的更正不同」），並提供「仍要存」「我來更正」兩個選項；使用者選「仍要存」才寫入並註明查證結果。查證結果記在軌跡與 observability。
   - **更正**：在筆記本裡說「不對，…」照現有規則存成使用者更正，並記錄是哪本筆記本。
   - 訓練：使用者的私人資料預設**不進**訓練資料（`training_use: false`），除非之後另行同意。
6. **API**：`GET/POST /v1/notebooks`、`GET/PATCH/DELETE /v1/notebooks/{id}`、`POST /v1/notebooks/{id}/sources`（multipart 檔案、或 JSON 的 url／text）、`GET/DELETE /v1/notebooks/{id}/sources/{sid}`（含全文供跳轉）、`POST /v1/notebooks/{id}/notes`（一鍵筆記）、`POST /v1/notebooks/{id}/remember`（查證沒過時「仍要存」）。
7. **桌面網頁**：新分頁「筆記本」：左側筆記本與來源清單（加入檔案／網址／文字／音檔、刪除）、中間問答（引用 [n] 可點）、右側原文檢視（點引用捲到該段並標亮）；一鍵筆記按鈕；每則回答顯示查證結果（已存進記憶，或「查證發現」＋「仍要存」「我來更正」）。
8. **CLI**：`scripts/jiezi notebook new|list|add|ask|note|rm`。
9. **紀錄與統計**：軌跡記 notebook id、引用數、被移除的引用數；`/admin/observability` 加引用檢查結果。

## Non-Goals / 非目標

- 語音摘要（雙主持人 Podcast）、心智圖、測驗與單字卡、影片摘要（之後另開 change）。
- 多人共用、雲端同步、分享連結。
- 把筆記本內容送進訓練資料（需另外同意）。
- 自動抓取整個網站或定期更新網址來源。

## Impact / 影響

- 新規格 `notebooks`；修改 gateway（端點、聊天擴充欄位、記憶召回）、memory（notebook 種類與摘要頁）、桌面網頁。
- 不新增套件。磁碟依來源大小（全文＋向量；每 1 萬字約 0.2 MB）。
- 一鍵筆記與大型來源的建索引是長時間工作：在背景執行並顯示進度；超過 50 萬字的筆記本整理排到夜間。
- 4B 核心一次只能看約 5 段，跨很多來源的綜合問題品質有限；需要時照一般規則轉交（雲端／Claude 看到的仍是同一批編號段落，引用格式不變）。

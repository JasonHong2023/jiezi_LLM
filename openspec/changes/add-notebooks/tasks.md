# add-notebooks 任務 / Tasks

## 1. 儲存與來源 / Storage and sources

- [x] 1.1 `src/jiezi/notebooks/store.py`：筆記本、來源、段落（字元位置、重疊）、SQLite 索引（雙字詞＋向量）；sha256 去重；刪除來源同步刪段落
- [x] 1.2（上傳檔走既有沙盒 documents.read；音檔走 add-asr；網址 webread.fetch） 加入來源：檔案（documents）、網址（webread）、文字、音檔／影片（add-asr，時間碼）；提示注入掃描＋信任等級
- [x] 1.3 測試：去重、刪除、字元位置對得回原文、注入來源標記

## 2. 引用問答 / Cited answers

- [x] 2.1 檢索：雙字詞＋向量＋RRF，依上下文預算取段落、編號
- [x] 2.2（筆記本模式不走即時串流，先檢查再送） 聊天擴充欄位 `jiezi_notebook`（＋`jiezi_notebook_general`）接進現有管線；提示詞要求逐句 [n]
- [x] 2.3 引用檢查器：編號存在、句段重疊門檻、移除不實引用並標示；找不到相關段落時明說
- [x] 2.4（meta.notebook；軌跡 notebook_check） meta.citations；軌跡與 observability 記引用統計
- [x] 2.5 測試：正確引用保留、編造引用被移除、找不到時不亂答、轉交時引用格式不變

## 3. 一鍵筆記 / Generated notes

- [x] 3.1（notes.py；同步請求、一次一份；段落超過 40 段平均取樣並註明；引用檢查對照「原文＋該段重點」） 摘要、常見問答、學習指南：map（逐來源分段）→ reduce，每點附引用；背景執行＋進度
- [x] 3.2（舊筆記不再被整理） 筆記可再當來源；測試

## 4. 長期記憶 / Long-term memory

- [x] 4.1 筆記本問答附「使用者要我記住的事」與相關更正（不附舊請教答案）
- [x] 4.2（摘要用前幾句，不呼叫模型） 記憶 wiki `notebooks/<名稱>.md` 摘要頁（來源清單、各來源摘要），來源變動時更新
- [x] 4.3 一般對話的筆記本召回（`JIEZI_NOTEBOOK_RECALL`，預設開）：命中摘要頁 → 取段落回答並引用
- [x] 4.4 每題自動查證後存進記憶（a 出處完整、b 來源互不矛盾、c 不與記憶衝突、d 來源未被標記、e 無不確定語句與含糊問題）；通過才寫入（kind=notebook、provenance、training_use=false）；沒過列出「查證發現」，`remember` 端點供「仍要存」
- [x] 4.4a（另修：數字比對誤把引用編號 [1] 當數字） 測試：每個查證項目各一個不通過案例、通過案例自動寫入、「仍要存」寫入並註明
- [x] 4.5 筆記本裡的更正存成使用者更正並記筆記本；測試 4.1–4.5

## 5. 介面 / Interfaces

- [x] 5.1 API 端點（見提案 6）＋金鑰＋大小上限；測試
- [x] 5.2（ui/src/Notebooks.jsx） 桌面「筆記本」分頁：來源管理、問答、可點引用、原文檢視標亮、一鍵筆記、存到記憶
- [x] 5.3（另加 show、remember） CLI `scripts/jiezi notebook new|list|add|ask|note|rm`

## 6. 實測與文件 / Live test and docs

- [x] 6.1（2026-11-24 一鍵摘要實測 18 秒、6 點都附正確出處；發現總覽句沒標編號 → 引用檢查補編號或標示。混合筆記本（虛構請假規定 PDF、TTS 唸的虛構會議錄音、維基「國立故宮博物院」）20 題：15 題正確附出處、2 題正確回答找不到、3 題誤答找不到（重問 2 題答對；院長題因沒標編號且自動補引用門檻 0.5 太嚴 → 改 0.4）；修正編號寫在句號後、摘要取樣漏掉整份來源（改成每份來源至少一段）、網頁選單／語言清單／導覽框混入來源。記憶召回：一般對話 2 題都取到、天氣題沒誤抓）實機：一本含 PDF、網頁、音檔的筆記本，20 題問答人工檢查引用正確率；一鍵摘要；記憶召回
- [x] 6.2（clients.md §5.6、README、capabilities.toml；無新資產不需 licenses） `docs/clients.md` 筆記本段落、README、licenses（無新資產則註明）、capabilities.toml、dev-plan、HANDOFF

## 7. 驗證 / Validation

- [ ] 7.1 `openspec validate add-notebooks --strict`、`--all --strict`、全量 unittest、`git diff --check`

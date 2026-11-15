## 1. 記憶 wiki / Memory wiki

- [x] 1.1 `src/jiezi/memory.py`：Hermes 格式頁面、主題合併、筆記、更正、索引自動重建、忘記 / Wiki module
- [x] 1.2 `scripts/jiezi memory list|search|forget|path`

## 2. Gateway

- [x] 2.1 請教／雲端答案自動存（串流與非串流）/ Save consulted answers
- [x] 2.2 「記住」「不對」直接處理；幾乎相同的問題直接用記憶回答；相關記憶與筆記附給模型 / Recall paths
- [x] 2.3 `/health` 的 memory、`JIEZI_MEMORY`

## 3. 聊天歷史 / Chat history

- [x] 3.1 `var/chat/history.json`、接續、`--new`、`/clear`、上下文限 12 則

## 4. 驗證 / Verification

- [x] 4.1 單元測試；`openspec validate add-memory --strict`
- [x] 4.2 重啟 gateway 實測：請教「知識蒸餾」後再問，改由本機依記憶回答；「記住」「不對」直接處理；芥子的更正會直接照答。實測發現並修正：知識庫檢索先去掉提問用語（「是知」誤配）、「芥子」一詞不再被當成問助手本身、相似更正直接回答、答完才補「我不確定」不算答不出來。測試資料已清除。

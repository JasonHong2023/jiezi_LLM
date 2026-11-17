> **狀態 / Status**：提案，**尚未實作**，待使用者審閱（R4）。Proposal only, not implemented; awaiting review.

## Why

長文件問答要先從幾十段裡挑出放得進上下文的幾段。目前只用字面的雙字詞比對（add-document-followup），口語問法和文件用字不同時挑不到對的段落。
Long-document Q&A first picks the few chunks that fit the context. Selection is lexical only, so a colloquial question worded unlike the document misses the right chunk.

2026-11-17 實測（勞動基準法全文 15,252 字、30 段；核心 qwen3.5-4b-q4_k_m）[實測]：
- 「加班費怎麼算？」→ 模型回答「文件沒有提到」。文件第 24 條有，但寫的是「延長工作時間之工資」。
- 「女性員工懷孕或生小孩時有什麼保障？」→ 只找到第 30-1 條，漏掉第 50、51 條（用字是「分娩」「妊娠」）。

同一天用現有的 embedding 引擎（Qwen3-Embedding-0.6B，add-rag）離線比對正確段落的名次 [實測]：

| 問題 | 正確段落 | 字面排序（現行） | 語意排序 |
|---|---|---|---|
| 加班費怎麼算？ | 第 24 條 | 第 9 名 | 第 1 名 |
| 女性員工懷孕或生小孩時有什麼保障？ | 第 50 條 | 第 19 名 | 第 2 名 |
| 被公司資遣可以拿多少錢？ | 第 17 條 | 第 1 名 | 第 1 名 |
| 小孩幾歲才可以打工？ | 第 44 條 | 第 17 名 | 第 2 名 |

代價 [實測]：30 段在 CPU 上建向量 72.9 秒（一份文件只做一次），每個問題建向量 0.2–0.3 秒。
Cost: 72.9 s on CPU to embed 30 chunks (once per document); 0.2–0.3 s per question.

## What Changes

- `longdoc.py`：問答挑段落改成「字面名次＋語意名次」合併（倒數排名融合，RRF；兩邊各自排名後相加，不必調分數的比例）。上一輪問答的提示照舊計入字面分數。
  Chunk selection for Q&A fuses lexical and embedding ranks (reciprocal rank fusion); the previous-exchange hint still feeds the lexical side.
- 段落向量放在 gateway 的記憶體快取，和各段重點同一個快取、同樣的規則：最近 8 份、**不寫入磁碟**、任何一段失敗就不快取。
  Chunk vectors live in the same in-memory cache as chunk notes: eight documents, never on disk.
- 第一次問某份文件時要等段落向量建好（約每段 2–3 秒，CPU）。超過 `JIEZI_DOC_EMBED_TIMEOUT`（預設 20 秒）就先用字面排序回答，向量在背景繼續建，下一題就用得到；狀態回報「這一題只用字面比對」。
  The first question waits for chunk vectors up to a timeout (default 20 s); past it the answer uses lexical ranking and the vectors finish in the background for the next question.
- embedding 引擎不可用、沒有模型檔、`JIEZI_RAG=off` 或任何錯誤：退回現行的字面排序，不影響回答。
  Any embedding failure falls back to today's lexical ranking.
- 摘要（map-reduce）不變；只影響「問答」的挑段落。/ Summaries are unchanged.
- 開關 `JIEZI_DOC_SEMANTIC`（預設值見 OQ1）。

## Non-Goals

- 重排序模型用在文件段落（本機預設 off，見 add-reranker 的量測）。/ Reranking document chunks.
- 跨文件比對、把文件向量寫入磁碟或知識庫。/ Cross-document comparison; persisting document vectors.
- 轉交 Claude／雲端時的行為（照舊送原文）。/ Escalated requests.
- 改用 GPU 建段落向量（embedding 引擎預設在 CPU，不和核心搶顯示記憶體）。/ Embedding on GPU.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `documents`：追問的挑段落需求加上語意排序與退回規則。/ Follow-up chunk selection gains semantic ranking and fallbacks.

## Impact

- 無新相依、無新模型（沿用 add-rag 的 embedding 模型與 36102 埠）。/ No new dependencies or models.
- 第一次問一份 30 段的文件，多等最多 20 秒（或背景建完前只用字面）；之後每題多 0.2–0.3 秒 [實測]。
- 記憶體：每段一個 1024 維向量（4 KB），100 段約 0.4 MB，隨快取淘汰。
- 隱私：文件內容只送到本機的 embedding 引擎（127.0.0.1），不落地。

## Open Questions

- **OQ1 預設開或關？** 建議：**開**（有 embedding 模型且 `JIEZI_RAG` 開著時）。理由：上表四題中三題從挑不到變成前兩名；失敗會自動退回。但依 R8 要先用 2.1 的量測確認回答正確率真的提升，再把預設改成開。
- **OQ2 逾時要等多久？** 建議 20 秒：30 段的文件第一題約等 70 秒太久；20 秒內建不完就先用字面排序回答。也可以選「一律等到建完」。
- **OQ3 附文件當下就先建向量？** 建議：chat 的 `/file` 與桌面網頁上傳後就在背景開始建，使用者打第一個問題時多半已建好。代價是附了沒問也會用 CPU。

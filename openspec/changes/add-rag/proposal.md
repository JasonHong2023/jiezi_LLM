## Why

開發計畫 Phase 5.1 RAG。台灣知識庫只用雙字全文比對時，問題沒提到文章名稱就容易查不到或查錯（缺口報告：「台灣最高的山」沒查到玉山）。加上語意向量重排可補足。
Full-text bigram matching misses questions that do not name the article; semantic vectors fix that.

## What Changes

- 新增 Qwen3-Embedding-0.6B Q8_0（Apache-2.0 ⚠️ 依模型卡）作為 embedding 模型，跑在 R11 的 engine-embed 埠（36102），預設 CPU、第一次用到才啟動、閒置後關閉。
  Qwen3-Embedding-0.6B on the engine-embed port, CPU by default, lazy start, idle stop.
- `scripts/jiezi knowledge embed [--gpu]`：為 9,659 段建向量（`var/knowledge/vectors.sqlite`，可續跑；換模型自動重建）。
  Build resumable section vectors.
- 檢索：點名文章時照舊；否則以全文索引取最多 200 個候選，用向量相似度重排，≥ `JIEZI_RAG_MIN`（預設 0.5）才採用；向量判定沒有相關段落就不附資料；向量出錯時退回原本的全文門檻。
  Hybrid retrieval with a similarity threshold and a full-text fallback on errors.
- 不加 numpy（只對候選計算），查資料改在執行緒執行，不阻塞其他請求。
  No numpy; grounding runs off the event loop.

## Non-Goals

- Reranker 模型（之後依自我評測結果決定）。/ A reranker model.
- 辭典、課綱的向量化（它們用精確比對就夠了）。/ Vectors for dictionaries and curriculum.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `knowledge`：新增向量重排。/ Adds vector reranking.

## Impact

- 向量約 40 MB；embedding 引擎約 0.7 GB RAM（CPU）。實測（5 段樣本）：「台灣最高的山」→ 玉山 0.69，無關問題 ≤ 0.22。

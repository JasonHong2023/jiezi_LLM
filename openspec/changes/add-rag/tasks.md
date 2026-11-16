## 1. 實作 / Implementation

- [x] 1.1 模型清單與授權登記 `qwen3-embedding-gguf`；下載並核對 SHA-256 / Manifest, registry, download
- [x] 1.2 `src/jiezi/rag.py`：Embedder（延遲啟動、閒置關閉）、VectorStore、可續跑建置、HybridRetriever / Module
- [x] 1.3 `LocalEngine(extra=…)`；knowledge `candidates` 與 `retrieve(hybrid)`；gateway 接上、`/health` 的 rag / Wiring
- [x] 1.4 `scripts/jiezi knowledge embed [--gpu]`

## 2. 驗證 / Verification

- [x] 2.1 單元測試；CPU 小樣本實測相似度（玉山 0.69、無關 ≤ 0.22，門檻 0.5）
- [x] 2.2 改為全掃描並加入法規向量（`scripts/jiezi laws embed`）；94 條法規樣本實測正確
- [ ] 2.3 E0 結束後以 GPU 建完整向量（知識庫、法規），自我評測前後比較 / Full builds and self-test after E0

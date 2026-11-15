## 1. 來源與建置 / Sources and build

- [x] 1.1 `knowledge/manifest.toml`、lock 檔、授權登記 `taiwan-md` / Manifest, lock, registry
- [x] 1.2 `src/jiezi/knowledge.py`：下載與核對、解析、雙字 FTS5 索引、檢索 / Fetch, parse, index, retrieval
- [x] 1.3 `scripts/jiezi knowledge build|search` / Commands

## 2. 對話整合 / Chat integration

- [x] 2.1 gateway 共用 `_ground`；`/health`；`.env.example` 的 `JIEZI_KNOWLEDGE` / Grounding, health, setting
- [x] 2.2 `textconv` 只換不在 Big5 的字（D5）/ Conversion fix

## 3. 驗證 / Verification

- [x] 3.1 單元測試；`openspec validate add-knowledge --strict` / Unit tests and validation
- [x] 3.2 重啟 gateway，以 0.6B 實測（刈包、健保：檢索與出處正確；0.6B 仍會加入原文沒有的說法） / Live check with the 0.6B

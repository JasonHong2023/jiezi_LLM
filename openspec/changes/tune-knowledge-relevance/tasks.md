## 1. 量測集 / Question set

- [x] 1.1（61 題，去掉路徑、Hermes 長提示、文件題） 從 trajectory 抽真實問題（不重複、無工具、非評測、≤200 字），去個資
- [x] 1.2（`src/jiezi/eval/data/relevance.jsonl` 211 題：真實 61、該附 90、不該附 60；3 題標 unsure 不計分；12 題該附的問法含文章名，走點名路徑） 寫「該附」與「不該附」題目；逐題標註應附文章或 none，列出不確定的
- [ ] 1.3 使用者抽查 20 題

## 2. 量測 / Measure

- [ ] 2.1（向量部分完成 2026-11-18：`var/eval/relevance/relevance-20261118-223449.json`；重排序版本待夜間）`scripts/jiezi rag relevance`：門檻掃描 × 重排序開關，輸出表格與 JSON
- [ ] 2.2 `sources` 帶向量分數
- [x] 2.3（2026-11-18 使用者選 0.6：該附有附到 80.2% → 71.7%，不該附卻附了 34.3% → 3.9%；法規分出 JIEZI_LAWS_RAG_MIN 維持 0.5，尚未量測）選門檻、回報；使用者同意後改預設
- [ ] 2.4 夜間端到端：新舊門檻比轉交率、unsupported_claims、延遲

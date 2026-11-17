## ADDED Requirements

### Requirement: Vector Reranking

有段落向量時，問題沒有點名文章的情況下，gateway SHALL 以全文索引取候選、以 embedding 相似度重排，只採用相似度達門檻的段落；沒有段落達門檻時 SHALL NOT 附知識庫資料；向量檢索出錯時 SHALL 退回全文檢索。
With section vectors, unnamed questions SHALL be answered from full-text candidates reranked by embedding similarity above a threshold; none above it means no knowledge is attached; errors SHALL fall back to full text.

#### Scenario: 沒點名的問題 / An unnamed question

- **WHEN** 使用者問「台灣最高的山是哪一座？」
  The user asks for Taiwan's highest mountain
- **THEN** 附上〈玉山〉的段落
  The 玉山 section is attached

#### Scenario: 無關問題 / Unrelated question

- **WHEN** 使用者說「用 Python 讀 CSV 檔」
  The user asks about reading a CSV in Python
- **THEN** 不附知識庫資料
  No knowledge is attached

## ADDED Requirements

### Requirement: Semantic Chunk Selection for Document Questions
When a question is asked about an attached long document and the embedding engine is available, the gateway SHALL rank the document's chunks by fusing the lexical rank with an embedding-similarity rank, and SHALL fall back to the lexical rank alone whenever embeddings are unavailable, fail, or are not ready within the configured timeout. Chunk vectors MUST be kept in memory only and MUST NOT be written to disk.

長文件問答在 embedding 引擎可用時，SHALL 以字面名次與語意名次合併挑段落；embedding 不可用、失敗或逾時 SHALL 退回字面排序。段落向量 MUST 只放在記憶體，MUST NOT 寫入磁碟。

#### Scenario: A colloquial question finds a chunk worded differently
- **WHEN** a question shares no key terms with the chunk that answers it but is close to it in embedding similarity
- **THEN** that chunk is among those sent to the model

#### Scenario: Embeddings not ready in time
- **WHEN** the chunk vectors are not ready within the timeout
- **THEN** the answer uses the lexical ranking, the response metadata says so, and the vectors keep building for the next question

#### Scenario: Embedding engine unavailable
- **WHEN** the embedding engine is switched off, missing its model, or returns an error
- **THEN** the lexical ranking is used and the answer is not blocked

#### Scenario: Vectors are never persisted
- **WHEN** chunk vectors are computed for a document
- **THEN** they exist only in the gateway's in-memory cache and disappear when evicted or when the gateway stops

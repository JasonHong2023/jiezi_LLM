# knowledge Specification

## Purpose
TBD - created by archiving change add-knowledge. Update Purpose after archive.
## Requirements
### Requirement: Pinned Knowledge Source

台灣知識庫來源 SHALL 鎖定 commit，並以 lock 檔逐檔記錄 git blob 雜湊；`scripts/jiezi knowledge build` SHALL 逐檔核對，任何一檔不符 SHALL 停止建置且不取代既有索引。
The source SHALL be pinned to a commit with per-file git blob hashes; the build SHALL verify every file and stop on any mismatch without replacing an existing index.

#### Scenario: 上游檔案改過 / Changed upstream file

- **WHEN** 下載的文章雜湊與 lock 檔不符
  A downloaded article's hash differs from the lock file
- **THEN** 建置停止，索引不變
  The build stops and the index is unchanged

### Requirement: Knowledge Grounding in Chats

問題提到台灣知識庫的主題或與某段內容高度相關時，gateway SHALL 附上最多 2 段給模型，SHALL 在回答後附文章標題、連結與出處並註明未經人工審核的文章，並 SHALL 在 `jiezi.sources` 列出；無關的問題（閒聊、寫程式、翻譯）SHALL NOT 觸發。
For Taiwan topics or closely matching sections, the gateway SHALL attach at most two sections, append titles, links and attribution (marking unreviewed articles), and list them in `jiezi.sources`; unrelated questions SHALL NOT trigger it.

#### Scenario: 問台灣小吃 / Asking about a Taiwanese food

- **WHEN** 使用者問「刈包是什麼？」
  The user asks what 刈包 is
- **THEN** 模型收到〈刈包〉的開頭段落，回答後附該文標題、連結與「未經人工審核」註記
  The model receives the article's opening section, and the answer ends with its title, link and the unreviewed note

#### Scenario: 寫程式 / Coding

- **WHEN** 使用者說「寫一個 Python 排序函式」
  The user asks for a Python sort function
- **THEN** 不附知識庫內容
  No knowledge is attached

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


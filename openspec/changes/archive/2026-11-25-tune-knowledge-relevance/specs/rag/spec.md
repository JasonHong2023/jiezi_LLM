## ADDED Requirements

### Requirement: Relevance Threshold Measurement
The project SHALL keep a labelled relevance question set (real questions, on-topic questions that do not name the article, and off-topic questions) and a retrieval-only command that reports, for each candidate similarity threshold with the reranker on and off, the share of on-topic questions that get the expected article, the share of off-topic questions that get any section, and the time per question; the default threshold SHALL change only after the user approves the measured choice.

#### Scenario: 不該附的題目 / An off-topic question
- **WHEN** 量測集裡「說一個笑話」標為不該附，某個門檻下附了〈台灣科技說故事〉
  An off-topic question gets a section at some threshold
- **THEN** 這一格的「不該附卻附了」比例計入這題
  It counts toward that threshold's false-attach rate

#### Scenario: 改預設 / Changing the default
- **WHEN** 量測選出新門檻
  The measurement picks a new threshold
- **THEN** 先回報使用者，同意後才改 `JIEZI_RAG_MIN` 的預設
  The user is told first and the default changes only after approval

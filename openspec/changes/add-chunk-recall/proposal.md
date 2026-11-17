> **狀態 / Status**：提案，**尚未實作**，待使用者審閱（R4）。Proposal only, not implemented; awaiting review.

## Why

add-semantic-chunks 上線後，16 題口語問題答對 12 題 [實測，2026-11-17]。剩下 4 題全都是「正確段落沒被選進上下文」：語意排序其實已經把它排在前面，但字面排序把它排得很後面，合併後被擠掉。
After add-semantic-chunks, 12 of 16 colloquial questions were answered. In all four misses the right chunk ranked high semantically but low lexically and was dropped after fusion.

| 問題 | 正確段落 | 字面名次 | 語意名次（問題） | 語意名次（用「理想答案句」查）| 這題放得下幾段 |
|---|---|---|---|---|---|
| 公司可以叫我連續上班超過六天嗎？ | 勞基法第 36 條 | 18 | 3 | 1 | 6 |
| 老闆可以叫女生上大夜班嗎？ | 第 49 條 | 18 | 4 | 1 | 5 |
| 最低薪資是誰決定的？ | 第 21 條 | 15 | 2 | 1 | 5 |
| 哪些人其實沒被健保照顧到？ | 健保長文「99.6% 的盲區」 | 12 | 4 | 1 | 5 |

（「理想答案句」是我從原文抄的答案句，只用來說明「用像答案的句子去查會更準」，不是實際可用的做法。）

## What Changes（兩個做法，請選一個或都要）

- **做法 A：保留語意前幾名的名額**（便宜、確定）。挑段落時先放語意排序的前 2 名，剩下的名額再依合併排序。上表 4 題中，「最低薪資」（語意第 2）會被救回；另外 3 題在第 3、4 名，要保留前 4 名才救得回，但那會擠掉字面排序的段落（點名條號的問題靠字面）。
  Reserve slots for the top semantic chunks, then fill by fused rank.
- **做法 B：先讓本機模型猜一句答案再查**（HyDE；多花一次本機生成，約 2–5 秒 [估]）。用猜出來的答案句和問題各查一次語意排序再合併。上表顯示「像答案的句子」能把正確段落排到第 1，但模型猜的句子不一定像原文——要量了才知道。
  Let the local model draft a hypothetical answer, embed it too, and fuse; costs one extra local generation.
- 兩者都只影響「長文件問答的挑段落」；失敗就退回現行做法；開關 `JIEZI_DOC_RECALL`（`off`／`reserve`／`hyde`）。

## Non-Goals

- 重排序模型（本機預設 off，見 add-reranker 的量測）。/ Rerankers.
- 改變摘要流程。/ Summaries.

## Capabilities

### Modified Capabilities

- `documents`：長文件問答挑段落的規則。/ Chunk selection for document questions.

## Impact

- 做法 A：沒有額外耗時。做法 B：每題多一次本機生成（約 2–5 秒 [估]）。
- 量測（與實作分開，R8、R17）：沿用 add-semantic-chunks 的 16 題，**另外再寫 16 題新題目**（避免只對已知題目調好），比較 off／reserve／hyde 的答對數與耗時。

## Open Questions

- **OQ1 做法**：A、B、或兩個都做再量（建議：**兩個都做、量了再決定預設**）。
- **OQ2 做法 A 保留幾名**：建議 2（只保留最有把握的；保留更多會擠掉點名條號的字面命中）。
- **OQ3 做法 B 的耗時上限**：猜答案超過幾秒就放棄、直接用現行做法？建議 8 秒。

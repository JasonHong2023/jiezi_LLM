> **狀態 / Status**：2026-11-18 提案，等使用者審閱。/ Proposed, awaiting review.

## Why

2026-11-18 實測：一般問題常被附上不相干的 Taiwan.md 段落（「台灣的國花是什麼」附了〈台灣花布〉〈水果王國〉；「說一個笑話」附了
〈台灣科技說故事〉），本機照資料回答後查核失敗，轉給 Claude。過去 3 天 93 個不重複的真實問題裡 29 個附了 Taiwan.md，
其中 6 個因 unsupported_claims 轉交。現行向量門檻 `JIEZI_RAG_MIN=0.5` 是 add-rag 時的預設，沒有用真實問題量過。
Unrelated knowledge-base sections are attached, the check then fails and the question goes to Claude; the 0.5 threshold was never measured on real questions.

## What Changes

- 量測集 `src/jiezi/eval/data/relevance.jsonl`（約 240 題，每題標「應附的文章」或「不該附」）：
  1. 真實問題約 90 題（trajectory 裡不重複、無工具、非評測的短問題；去掉個人資訊）；
  2. 應該附的台灣主題約 90 題（Taiwan.md 有對應文章，問法不含文章標題，才測得到向量檢索）；
  3. 不該附的約 60 題（數學、程式、閒聊、創作、問芥子自己、非台灣的常識）。
  標註由我先標、列出不確定的，請使用者抽查 20 題；這是評測資料，不進訓練。
- `scripts/jiezi rag relevance`：只跑檢索（不生成回答，幾分鐘），門檻 0.40–0.80 每 0.025 一格，重排序開／關，
  量「該附的有附到對的文章」比例、「不該附卻附了」比例、每題秒數，輸出 `var/eval/relevance/*.json` 與表格。
- 選門檻：「不該附卻附了」≤ 10% 之下，「該附的附到」最高的那一格；回報使用者，**同意後**才改預設（R20）。
- 夜間端到端：真實 90 題用新舊門檻各跑一次，比轉交率、unsupported_claims 次數、延遲。
- 回應的 `sources` 加上向量分數，之後可以從紀錄繼續調。

## Non-Goals

- 換 embedding 模型、改切段方式（量完再看要不要）。
- 法規（laws）的門檻（同一個量測工具之後可以套用）。

## Capabilities

### Modified Capabilities

- `rag`：新增 Relevance Threshold Measurement 需求。

## Impact

- 檢索量測白天可跑（只做 embedding，數分鐘）；端到端放夜間。
- 新檔：量測集、`rag.relevance()`、CLI 子指令、測試。

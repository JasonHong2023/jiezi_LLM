## Why

Phase 6（自我進化）需要 SFT 教材。規則 R20.3 要求教材先過驗證器；R18.3 要求只用可訓練的授權；評測題不能進訓練集。先把匯出管線與把關做好，訓練本身等 G1 與使用者同意。
Phase 6 needs SFT material that is verified (R20.3), trainable (R18.3) and free of evaluation overlap.

## What Changes

- `scripts/jiezi dataset export [--limit]` 寫 `var/training/sft-YYYY-MM-DD.jsonl` 與 `.manifest.json`（筆數、來源、授權、各排除原因）。
  Writes the dataset and a manifest of counts, sources, licenses and exclusions.
- 軌跡：只收 `jiezi`／`jiezi-local` 的本機回答（第 0、1 層），驗證通過且含「強」檢查（工具呼叫 schema）；答案查核（只看數字、引號）與程式語法檢查不足以證明答案正確，不收。被標為不可訓練（含 Claude 輸出）、用到不可訓練來源（教育部辭典 ND、寫作連結、HackMD）一律排除；去掉 gateway 附錄。
  Trajectories: local answers with a strong verified check only; non-trainable material excluded; appendix removed.
- 範本：法規條文、課綱先修、課本單元、Taiwan.md 開頭段落，答案直接取自原文（固定種子）。
  Templates over trainable data with verbatim answers.
- 評測重疊：與自我評測、R0 題庫相同的題目，以及問到評測「目標」（同一冊課本、課綱主題、法條、文章）的題目，都剔除。
  Evaluation questions and their targets are removed.

## Non-Goals

- 訓練本身（Phase 6，需 G1、PyTorch 與使用者同意）。/ Training itself.

## Capabilities

### New Capabilities

- `training-data`：可追溯、已把關的訓練資料匯出。/ Traceable, gated training-data export.

### Modified Capabilities

（無）/ (None)

## Impact

- 2026-11-16 實際匯出 3,500 筆（法規 1,929、Taiwan.md 1,071、課綱 407、課本 92、軌跡 1）；排除：評測重疊 30、弱驗證 12、未通過 45、不可訓練 13。

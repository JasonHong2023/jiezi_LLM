## Why

開發計畫 5.2 技能庫（AWM 離線模式）。Hermes 與 OpenCode 已能選用芥子（4.7），驗證過的工具呼叫軌跡會開始累積；先做不需要老師模型的 v0：把成功的工具呼叫當範例，回答相似問題時附給模型示範。另外修正評測污染：selftest、toolcheck 的流量會被技能庫與記憶學走，下次評測分數灌水。
Dev plan 5.2: verified tool calls become retrieved demonstrations; evaluation traffic is kept from feeding skills and memory.

## What Changes

- `src/jiezi/skills.py`、`scripts/jiezi skills build|list`：從軌跡收集通過 schema 驗證（有取樣時信心 ≥ 0.75）的工具呼叫；gateway 在工具呼叫請求前附上最相似（≥ 0.3）、用到的函式都在本次清單中的最多 2 個範例；本機成功的呼叫立即加入。`JIEZI_SKILLS`（預設 on）。
  Verified examples are collected, retrieved and learned online.
- 評測流量：`X-Jiezi-Eval: 1`（selftest、toolcheck 自動帶上）→ 軌跡標 `eval`，不學技能、不存記憶、不進訓練資料。
  Evaluation traffic is marked and never learned from.

## Non-Goals

- 由老師模型歸納含 placeholder 的工作流程（AWM 完整版，資料足夠後再做）。/ Teacher-induced workflows.
- 技能進訓練資料。/ Skills in training data.

## Capabilities

### New Capabilities

- `skills`：技能庫 v0。/ Skill library v0.

### Modified Capabilities

（無）/ (None)

## Impact

- 目前軌跡中 1 則合格範例；隨日常使用累積。

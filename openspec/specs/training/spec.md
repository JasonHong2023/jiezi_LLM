# training Specification

## Purpose
TBD - created by archiving change add-sft-training. Update Purpose after archive.
## Requirements
### Requirement: Gated LoRA Training

訓練 SHALL 每輪從鎖定的凍結核心與全新 LoRA 開始，SHALL 只對助手回答計算損失，SHALL 拒絕未標為可訓練的資料；訓練後的模型 SHALL 通過回歸關卡（目標提升、其他退步 ≤ 1 分、長度增幅 < 20%、延遲不變差、轉交不增加）才保留。
Training SHALL start each round from the frozen pinned core with a fresh LoRA, SHALL compute loss on answers only, SHALL reject non-trainable data, and the result SHALL be kept only if it passes the regression gate.

#### Scenario: 靠變長得分 / Gains from longer answers

- **WHEN** 訓練後目標任務提升，但平均回答長度增加 25%
  The target improves but answers grow 25% longer
- **THEN** 關卡不通過，回滾
  The gate fails and the round is rolled back

#### Scenario: 重用 run 名稱 / Reusing a run name

- **WHEN** 以已存在的 run 名稱開始訓練
  Training starts with an existing run name
- **THEN** 拒絕，要求新的 LoRA
  It is refused; a fresh LoRA is required


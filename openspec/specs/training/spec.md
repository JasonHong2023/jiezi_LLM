# training Specification

## Purpose
有關卡的 LoRA 訓練：複習資料混合、顯示記憶體上限與回歸評測。
Gated LoRA training with replay mixing, a VRAM ceiling and regression checks.
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

### Requirement: Replay Mix And VRAM Ceiling

訓練資料 SHALL 混入凍結核心自己通過驗證的回答（replay），比例記在資料 manifest；replay 題目 MUST NOT 與評測題重疊；訓練的顯示記憶體峰值 SHALL 與設定上限（5,500 MiB）比對並在超過時標示，超過長度的樣本 SHALL 排除並計數而非截斷。
Training data SHALL include verified replay answers from the frozen core at a recorded ratio; replay prompts MUST NOT overlap evaluation items; peak training VRAM SHALL be recorded against the configured ceiling and flagged when over it, and over-long examples SHALL be dropped and counted.

#### Scenario: 與評測重疊 / Overlapping evaluation

- **WHEN** replay 題目和評測題正規化後相同
  A replay prompt matches an evaluation item after normalization
- **THEN** 該題被排除並計入 `overlaps_evaluation`
  It is excluded and counted under `overlaps_evaluation`

#### Scenario: 太長的樣本 / Over-long example

- **WHEN** 樣本的 token 數超過 `max_len`
  An example exceeds `max_len` tokens
- **THEN** 該樣本被排除並計數，不截斷
  It is dropped and counted, not truncated


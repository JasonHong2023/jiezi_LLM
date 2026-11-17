## ADDED Requirements

### Requirement: Replay Mix And VRAM Ceiling

訓練資料 SHALL 混入凍結核心自己通過驗證的回答（replay），比例記在資料 manifest；replay 題目 MUST NOT 與評測題重疊；訓練的顯示記憶體峰值 SHALL 不超過設定上限（預設 5,500 MiB），超過長度的樣本 SHALL 排除而非截斷。
Training data SHALL include verified replay answers from the frozen core at a recorded ratio; replay prompts MUST NOT overlap evaluation items; peak training VRAM SHALL stay under the configured ceiling, dropping over-long examples.

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

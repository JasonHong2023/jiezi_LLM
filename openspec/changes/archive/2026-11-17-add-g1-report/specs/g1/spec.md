## ADDED Requirements

### Requirement: G1 Recommendation

G1 報告 SHALL 只納入驗證完成且速度 ≥ 10 t/s 的候選；與最高推理／工具分數在 95% 信賴區間內打平者 SHALL 選檔案較小者；報告 SHALL NOT 自動更改核心設定。
Only verified candidates at ≥ 10 t/s SHALL be ranked; CI ties SHALL go to the smaller file; the report SHALL NOT change the core.

#### Scenario: 打平 / A tie

- **WHEN** 較小模型的推理分數不低於最高分的信賴區間下限
  A smaller model scores at or above the top model's lower CI bound
- **THEN** 推薦較小模型
  The smaller model is recommended

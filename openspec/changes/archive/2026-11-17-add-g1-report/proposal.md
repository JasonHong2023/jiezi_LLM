## Why

E0 結束後要依開發計畫 §6 的 G1 判準選核心。把判準寫成程式，避免人工挑表格出錯；結果只是推薦，由使用者決定（R4）。
Turn the G1 criterion into code; the result is a recommendation and the user decides.

## What Changes

- `scripts/jiezi g1` → `var/reports/g1-recommendation.md`：只列已驗證完的列；速度 ≥ 10 t/s；推理／工具題最高者，與其 95% 信賴區間打平時選較小、較快的；列出知識題差距（交給外掛資料補）。
  Verified rows only, ≥ 10 t/s, best reasoning/tool score with CI ties going to smaller, faster models.

## Capabilities

### New Capabilities

- `g1`：G1 推薦報告。/ G1 recommendation report.

### Modified Capabilities

（無）/ (None)

## Impact

- 不改任何設定；選定核心仍要使用者確認後才修改 `models/manifest.toml`。

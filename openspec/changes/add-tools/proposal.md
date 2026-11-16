## Why

使用者 2026-11-15 選的第 3 項「給他工具」；缺口報告也有「1+3=2 多少?」答不好的紀錄。0.6B 算數、換算、推日期都很容易錯；交給程式算，再讓模型照著回答。
The 0.6B gets arithmetic, conversions and dates wrong; code computes them and the model answers from the result.

## What Changes

- 計算：加減乘除、次方、括號、百分比、開根號（含「乘以、除以、加、減」等中文運算詞），以語法樹白名單與分數精確計算，不使用 eval；題目附了錯的答案（`1+3=2`）時指出。
  Arithmetic via an AST whitelist with exact fractions; wrong claimed answers are pointed out.
- 單位換算：長度、重量（含台斤、台兩）、面積（含坪、甲、公頃）、體積、速度、溫度。
  Unit conversion including Taiwanese units.
- 日期：今天日期與星期、民國／西元換算、某日星期幾、兩日相差幾天、N 天前後。
  Dates: today, ROC/AD years, weekday, differences, offsets.
- gateway 把結果當資料附給模型（答案查核會比對這些數字），回答後附「【計算】」。`JIEZI_TOOLS`（預設 on）。
  Results are attached as data (checked by the grounded check) and appended after the answer.

## Non-Goals

- 農曆：需要年表，正確性要另外驗證，之後再做。/ Lunar calendar, later.
- 讓模型自己發出工具呼叫（0.6B 的工具呼叫不可靠）。/ Model-initiated tool calls.

## Capabilities

### New Capabilities

- `tools`：內建計算、單位換算、日期。/ Built-in arithmetic, units and dates.

### Modified Capabilities

（無）/ (None)

## Impact

- 只用標準函式庫。/ Standard library only.

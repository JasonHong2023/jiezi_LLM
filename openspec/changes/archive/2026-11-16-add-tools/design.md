## Decisions

### D1 — 計算 / Arithmetic
先把全形、×÷^√、夾在兩個數字之間的中文運算詞換成符號，再找算式；用 `ast` 白名單（數字、正負號、+ - * / // % **、sqrt）以 `Fraction` 求值。次方限整數且 ≤ 200，結果最多 60 位數。誤判防護：緊鄰英文字母的（Qwen3.5-2B）、日期格式、以 0 開頭且只有減號的（電話）不算；只有減號又沒有提問用語的也不算。
AST whitelist with Fraction; guards against model names, dates and phone numbers.

### D2 — 單位 / Units
表格式：每個單位有維度與換成基本單位的倍數（台斤 0.6 kg、台兩 37.5 g、坪 400/121 ㎡、甲 9699.17 ㎡）。需要「數字＋單位A」與後面同維度的「單位B」，且有換算用語。英文縮寫要整個單字比對。溫度另外換算。
Table-driven with dimension checks; Latin abbreviations matched as whole words.

### D3 — 日期 / Dates
支援 `YYYY年M月D日`、`YYYY-M-D`、`YYYY/M/D`、`民國YYY年…`、`M月D日`（今年；問「還有幾天」且已過時算明年）。今天的日期取 gateway 所在電腦的本機時間。
Common date formats; "today" from the gateway host clock.

### D4 — 交給模型 / Hand-off
結果放在 system 訊息（「程式計算的結果，是正確的，直接採用」），回答後由 gateway 附「【計算】」原文；答案查核（add-answer-check）會比對回答中的數字，算錯就重答。
Attached as data, appended verbatim, and enforced by the grounded check.

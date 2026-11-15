## Why

實測時 0.6B 會在有附資料的情況下加入原文沒有的說法（刈包「2026 年被選為全球餐桌代表」），也常用大陸用語（视频、默认、软件）。使用者 2026-11-15 決定先做「答案查核」與「台灣用語」。
With data attached the 0.6B still adds claims the data lacks, and it uses mainland phrasing. The user chose these two first.

## What Changes

- 答案查核（`grounded`）：有附辭典、課綱或知識庫資料時，回答中的數字（10 以上或含小數）與「」『』引用必須出現在資料或使用者的話裡；中文數字（七十、一九二七）會換算後比對。不通過時：非串流 → 本機帶錯誤說明重答一次，仍不過則 `jiezi` 策略自動請教；串流 → 在回答後附「［查核：…找不到］」提醒，`jiezi` 策略接著請教。
  Grounded check: numbers and quoted terms must appear in the attached data or the user's words; failures trigger a local retry or, when streaming, a visible warning, then consultation under `jiezi`.
- 台灣用語：本機輸出在簡轉繁之後，依篩選過的 OpenCC TWPhrases 把大陸用語換成台灣用語（视频→影片、默认→預設）；程式碼區塊不換；串流時詞不會被切在兩段之間。`JIEZI_TW_PHRASES`（預設 on）。
  Taiwan phrasing for local output from a filtered OpenCC TWPhrases table; code fences untouched; stream-safe.

## Non-Goals

- 檢查沒有數字或引號的編造（例如把刈包說成四川菜）——需要語意比對，之後再做。/ Fabrications without numbers or quotes need semantic checks; later.
- 「种、于、几、里」這類同時是正體字的簡體用法（需要詞語上下文）。/ Characters that are both Simplified usage and valid Traditional.

## Capabilities

### New Capabilities

- `answer-check`：有附資料時的答案查核與本機輸出的台灣用語。/ Grounded answer check and Taiwan phrasing.

### Modified Capabilities

（無）/ (None)

## Impact

- `escalation.verify` 多一項 `grounded` 檢查；`textconv` 多 `to_taiwan`、`TaiwanStream`；對照表 `src/jiezi/eval/data/TWPhrases-jiezi.txt`（731 筆，Apache-2.0）。

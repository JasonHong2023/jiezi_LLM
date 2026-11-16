## Why

使用者 2026-11-15 選的第 5 項：要能量測芥子整套系統（查資料＋回答）在台灣相關問題上的表現，並在改進前後比較。
Measure the whole system on Taiwan-specific questions and compare before and after changes.

## What Changes

- `scripts/jiezi selftest`：由程式從已收錄的資料出題（計算、單位、日期、國語辭典注音、台語台羅、課綱先修、課本單元、台灣知識庫），每類 10 題、固定種子，經 gateway 回答後自動判分；報告寫到 `var/reports/selftest-*.md`。
  Generated, seeded questions over the bundled data, answered through the gateway and scored automatically.
- 判分只看模型自己寫的部分（gateway 附錄不算）；知識庫題只看是否查到正確文章。
  Scoring ignores the appended source block; knowledge items check retrieval.
- `--dry`：不跑模型，只量 gateway 附上的資料是否含答案（觸發與檢索的上限）；`--list` 列出題目。
  `--dry` measures data coverage without the model; `--list` prints the questions.

## Non-Goals

- Claude 出題（標準答案全部來自資料本身）。/ Claude-written questions.

## Capabilities

### New Capabilities

- `selftest`：系統自我評測。/ System self-test.

### Modified Capabilities

（無）/ (None)

## Impact

- 實際評測需要本機模型（E0 執行中暫停，結束後再跑）；`--dry` 目前 80/80。
  A real run needs the local model (after E0); `--dry` is 80/80 now.

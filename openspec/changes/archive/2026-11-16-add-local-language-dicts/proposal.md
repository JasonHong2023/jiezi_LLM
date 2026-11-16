## Why

使用者 2026-11-15 同意的第 4 項「更多開放資料」：芥子目前只有《重編國語辭典修訂本》，問台語、客語詞彙時沒有依據。
Only the Mandarin dictionary was available; Taiwanese and Hakka questions had no grounding.

## What Changes

- 新增教育部《臺灣閩南語常用詞辭典》（14,489 筆）與《臺灣客家語常用詞辭典》（14,712 筆），g0v 整理的 JSON，CC BY-ND 3.0 TW，不可訓練。
  Add the MOE Taiwanese Southern Min and Hakka dictionaries (CC BY-ND, not trainable).
- 辭典格式新增 `moedict_json`（未壓縮）；顯示台羅讀音；例句的對照標記（原文／讀音／華語）只轉成可讀格式，不改內容。
  New plain-JSON format, Tâi-lô readings, interlinear markers rendered without changing content.
- 問題提到台語／閩南語／台灣話時先查台語辭典，提到客語時先查客語辭典；觸發用語加上這些語言名稱。
  Language-named questions prefer that dictionary.

## Non-Goals

- 華語→台語／客語的反查（g0v 的「華語對照表」不在教育部授權範圍，未收）。/ Mandarin-to-Taigi lookup.
- 成語典：g0v 沒有整理好的資料檔，之後另找來源。/ The idiom dictionary, pending a source.

## Capabilities

### New Capabilities

（無）/ (None)

### Modified Capabilities

- `dictionary`：新增語言優先規則。/ Adds language preference.

## Impact

- 下載約 17 MB，辭典檔建置約 10 秒。/ About 17 MB more; builds in about 10 s.

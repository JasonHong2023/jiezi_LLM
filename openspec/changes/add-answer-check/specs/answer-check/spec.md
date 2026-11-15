## ADDED Requirements

### Requirement: Grounded Answer Check

gateway 附上資料時，SHALL 檢查本機回答中的數字（10 以上或含小數）與「」『』引用是否出現在資料或使用者的話裡；不通過時 SHALL 讓本機帶著錯誤說明重答一次（串流時改為附上提醒），在 `jiezi` 策略下仍不通過 SHALL 自動請教。
When data is attached, the gateway SHALL check numbers and quoted terms in local answers against the data and the user's words; on failure it SHALL retry locally with the error (or warn when streaming) and, under `jiezi`, SHALL consult when it still fails.

#### Scenario: 編造的年份 / Invented year

- **WHEN** 附了〈刈包〉資料，本機回答「刈包在 2026 年紅遍全球」
  With the 刈包 article attached, the local answer says 2026
- **THEN** 查核不通過，本機被告知「2026 在提供的資料裡找不到」並重答
  The check fails and the local model retries, told that 2026 is not in the data

#### Scenario: 中文數字 / Chinese numerals

- **WHEN** 資料寫「距今超過七十年」，回答寫「70 多年」
  The data says 七十, the answer says 70
- **THEN** 查核通過
  The check passes

### Requirement: Taiwan Phrasing

本機模型的輸出 SHALL 在簡轉繁之後把篩選過的大陸用語換成台灣用語，程式碼區塊 SHALL NOT 更動，串流與非串流 SHALL 得到相同結果；`JIEZI_TW_PHRASES=off` SHALL 關閉此功能。
Local output SHALL get Taiwan phrasing after character conversion, leave code fences unchanged, and match between streaming and non-streaming; `JIEZI_TW_PHRASES=off` SHALL disable it.

#### Scenario: 大陸用語 / Mainland phrasing

- **WHEN** 本機輸出「这个视频的默认设置」
  The local output says 这个视频的默认设置
- **THEN** 使用者看到「這個影片的預設設置」
  The user sees 這個影片的預設設置

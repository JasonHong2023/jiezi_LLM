## Decisions

### D1 — 查什麼 / What is checked
只在 gateway 附了資料（辭典、課綱、課本、知識庫）時查。依據 = 附上的資料 + 使用者說過的話。回答的 `---` 之後（系統附的原文）不查；清單編號與 10 以下的整數不算。資料中的中文數字換算成阿拉伯數字（「一九二七」→1927、「七十」→70、「一百五十」→150）。
Only when data was attached; the basis is the data plus the user's words; appendix, list numbers and small integers are skipped; Chinese numerals in the data are converted.

### D2 — 不通過怎麼辦 / On failure
沿用既有的驗證流程：非串流時本機帶「哪些內容找不到」重答一次（tier 1），仍不過時 `jiezi` 策略自動請教 Claude、`jiezi-local` 照樣回答並標 `verify fail`。串流已送出無法重答，所以在原文附錄前加上「［查核：… 在附上的資料裡找不到，請小心］」，`jiezi` 策略接著附上請教結果。
Reuses the verification flow; streaming adds a warning before the appendix and consults under `jiezi`.

### D3 — 台灣用語表 / Phrase table
OpenCC `TWPhrases.txt`（commit `fae2a0a9`）中候選不含原詞的項目，取第一個候選；再用 Taiwan.md 當台灣寫作參照，原詞在其中少於 3 次、或台灣用語次數超過原詞兩倍才收。851 筆中收 731 筆；「保存、參數、設備、項目」這類台灣也常用的詞不換。由 `textconv.generate_tw_table` 產生。
Entries whose candidates exclude the key; kept when the key is rare in Taiwan.md or the Taiwan phrase is more than twice as common. 731 of 851 kept.

### D4 — 串流 / Streaming
`TaiwanStream` 只在後面的字數足以判斷最長詞（15 字）時才送出，結束時送出剩餘；``` 之間不換詞。串流的結果與整段轉換逐字相同（隨機切段測試）。
Text is released only with enough lookahead for the longest phrase; output equals whole-text conversion.

## Risks / Trade-offs
- 由資料推算出的數字（2026−1955=71）會被判不通過 → 只會多重答一次或請教，不會擋下回答。/ Derived numbers fail → only an extra retry or consultation.
- 實測（2026-11-15，0.6B）：8 題中 1 題抓到錯（「國民健康保險署」，正確為中央健康保險署）；刈包被說成四川菜沒有被抓到（沒有數字或引號）。
  Live: caught one wrong agency name in 8 questions; a fabrication without numbers or quotes was not caught.

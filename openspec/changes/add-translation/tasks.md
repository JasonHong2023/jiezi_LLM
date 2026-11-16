> 尚未開始；等使用者回覆 Open Questions 並同意實作（R4）。/ Not started; awaiting the user's answers and go-ahead.

- [ ] 1.1 `translate.py`：意圖與目標語言辨識、語言偵測（中／英／日的字元比例）、分段（依段落、上限約 900 token）、每段提示（前段結尾、詞彙表）/ intent, language detection, chunking, prompts
- [ ] 1.2 `translate.py`：每段檢查（空、長度比例、數字、語言、詞彙表）與重試一次；失敗段保留原文並標記 / per-chunk checks, one retry, marked fallbacks
- [ ] 1.3 gateway：長文件的翻譯模式（平行、依序接回、直接回傳、`jiezi.translation`、`training_use=false`）；短文字加檢查；`JIEZI_TRANSLATE` / gateway wiring
- [ ] 1.4 簡體 → 繁體的直接轉換路徑（不呼叫模型，標明來源，不進訓練資料）/ direct script conversion
- [ ] 1.5 CLI `jiezi translate`（`--to`、`--out`、`--glossary`、`--bilingual`、預估時間、可續跑）；`ask`／chat 走同一路徑 / CLI
- [ ] 1.6 單元測試（假引擎）；`docs/clients.md`、`.env.example`；`openspec validate add-translation --strict` / tests and docs
- [ ] 2.1 量測（與實作分開，R8）：G1 選定核心後，以 3 份真實文件（中→英、英→中、簡→繁）實測耗時、失敗段比例，並由使用者抽查 10 段品質；結果記入討論記錄 / measurement after G1, with the user spot-checking ten chunks

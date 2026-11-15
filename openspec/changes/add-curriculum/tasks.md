## 1. 來源與建置 / Sources and build

- [x] 1.1 `curriculum/manifest.toml`、授權登記 `docs/licenses.md`（`tw-taxonomy`、`zetria-textbooks`）/ Manifest and license registry
- [x] 1.2 `src/jiezi/curriculum.py`：下載與 SHA-256、載入檢查、查詢、先修鏈、排序、課本解析 / Fetch, checks, lookup, chains, ordering, textbook parsing
- [x] 1.3 `scripts/jiezi curriculum build|lookup|path|plan|textbook` / Commands

## 2. 對話整合 / Chat integration

- [x] 2.1 gateway：與辭典共用 `_ground`，附原文與出處、`jiezi.sources` / Grounding shared with the dictionary
- [x] 2.2 `.env.example`：`JIEZI_CURRICULUM`；`/health` 顯示狀態 / Setting and health

## 3. 驗證 / Verification

- [x] 3.1 單元測試（SHA-256、缺授權欄位、羅馬數字、先修鏈與排序、有環、觸發與不觸發、課本解析與冊別、gateway）；`openspec validate add-curriculum --strict` / Unit tests and validation
- [x] 3.2 重啟 gateway，以 0.6B 實際問幾題課綱與課本問題 / Live check with the 0.6B
  實測（2026-11-15）：先修題答對並附完整先修鏈；「國一上數學翰林版」0.6B 只答出第一單元的小節，後面附的原文完整；「早安」不觸發。/ Live: the prerequisite answer was right; the 0.6B listed only unit 1 for the textbook question, the appended data was complete; small talk did not trigger.

## 4. 寫作教學連結 / Writing-lesson links（D6）

- [x] 4.1 `src/jiezi/writing_refs.py`、`scripts/jiezi writing-refs build|search`、授權登記 `rocknovels-teachlist`（訓練：否）/ Index, commands, registry
- [x] 4.2 gateway：寫作問題附延伸閱讀連結；請教 Claude 時加上網參考提示；`JIEZI_WRITING_REFS` / Links and consult hint
- [x] 4.3 單元測試 / Unit tests
- [x] 4.4 請教提示表 `consult_hints.py`（化學 → HackMD）、授權登記 `hackmd-chemistry`（訓練：否）（D7）/ Consultation hints

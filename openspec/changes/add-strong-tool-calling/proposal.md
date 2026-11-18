> **狀態 / Status**：草案，待使用者審閱（2026-11-18）。/ Draft, awaiting review.

## Why

使用者 2026-11-18：「這模型的調用工具的能力我希望是特強」。現況（E0，Qwen3.5-4B Q4_K_M，ACEBench-zh normal 50 題）：**答對 30/50（60%）**，其中 **9 題（18%）根本解析不了**——都是**格式錯**，不是不會：
The core scores 60% on ACEBench-zh; 9/50 answers are unparseable, all of them format errors:

- 字典的鍵沒加引號：`factCriteria={category: "生物学", …}`
- 字典裡用 `=`：`audio_preferences={sound_type="ocean", duration_minutes=25}`
- 少了外層 `[ ]`：`FinancialDocumentTranslator(document_text=…)`

另外參數型別錯（`guest_count="8"` 應為整數）、漏必填參數也是常見錯誤。這些都可以**由程式保證**，不必靠模型「學會」。
Type errors and missing required parameters are also common; all of these can be guaranteed by code.

## What Changes

分四層，從最便宜、最確定的開始：
Four layers, cheapest and most certain first:

1. **語法約束解碼（grammar）**：請求帶 `tools` 時，gateway 依工具的 JSON Schema 產生 llama.cpp 文法，讓本機模型**只能**輸出「合法的工具呼叫或一般文字」——函式名稱只能是清單裡的、參數名稱與型別符合 schema、必填參數一定有。沿用 add-json-output 已有的文法機制。預期把「無法解析」從 18% 降到 0。
   Grammar-constrained decoding built from the tools' JSON Schemas: only valid calls (known names, typed parameters, required fields) or plain text.
2. **檢查與修正一次**：呼叫雖合法但值有問題（列舉值不在 enum、日期格式錯、數值超出 min/max）時，把錯誤訊息回給模型重答一次；仍失敗才轉交（現有 tier 流程）。
   Validate values (enum, format, range) and give the model one retry with the error before escalating.
3. **取樣多數決加強**：工具呼叫現在已平行取樣 4 個（add-sampling）；改成「通過 schema 檢查的才投票」，並把一致的參數值合併。
   Majority voting only among schema-valid samples.
4. **工具呼叫專門訓練（第 3 輪 SFT，夜間）**：等第 2 輪結果出來、確認訓練流程不傷其他能力後，用授權允許的工具呼叫資料集（候選：Salesforce xLAM function-calling-60k（CC BY 4.0 ⚠️待查證）、NousResearch hermes-function-calling-v1（Apache-2.0 ⚠️）、Glaive function-calling v2（Apache-2.0 ⚠️））＋ 複習資料，lr、比例沿用第 2 輪的結論。**只有通過 R20 回歸門檻才換核心。**
   Round-3 SFT on licensed tool-calling data plus replay, only after round 2 shows training is safe; core swaps only if the R20 gate passes.

評測擴大：ACEBench-zh 從 50 題擴到完整 normal 題組，並加 **BFCL**（Berkeley Function Calling Leaderboard，Apache-2.0 ⚠️待查證）的 simple / multiple / parallel / irrelevance 子集（英文，含「不該呼叫工具」的題），讓「特強」有數字可看。
Evaluation grows to the full ACEBench-zh normal set plus BFCL subsets (including irrelevance), so "very strong" is measurable.

## Non-Goals

- 實際執行使用者提供的任意工具（gateway 只產生呼叫，執行仍在用戶端；唯讀代理與視覺工具是例外，各有規格）。
- 用 Claude 的回答當訓練資料（R18.4）。

## Capabilities

### Modified Capabilities

- `tools`：工具呼叫的文法約束、值檢查與重答。
- `sampling`：只讓通過檢查的樣本投票。
- `eval`：ACEBench 完整題組、BFCL 子集。

## Impact

- 文法約束會讓第一個字稍慢（文法編譯，預估 < 0.2 秒，量測後回報）。
- 第 1–3 層白天可做（單元測試、短量測）；完整評測與第 4 層訓練在夜間。
- 第 4 層要下載資料集，下載前登記授權（R18.3）。

## Open Questions

- **OQ1 第 4 層要不要做**：建議做，但排在第 2 輪訓練結果出來之後；如果第 2 輪又沒過門檻，先查原因再說。
- **OQ2 BFCL 要不要加**：建議加（英文、含「不該呼叫」的題，ACEBench-zh 沒有這類）。
- **OQ3 文法約束要不要對所有用戶端（Hermes、OpenCode）都開**：建議開，因為只影響本機模型的輸出格式，不改 API。

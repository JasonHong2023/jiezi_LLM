## 1. 實作 / Implementation

- [x] 1.1 `JIEZI_TEACHER_MODELS`（多位）／`JIEZI_TEACHER_DAILY_MAX`；請求關 fallback、核對實際模型；OpenRouter 固定 DeepSeek 供應商並核對
- [x] 1.2（`src/jiezi/teacher.py`：關鍵事實〔數字、粗體／引號名稱，扣掉題目本身的〕重疊 ≥0.5 或文字相似 ≥0.3） 轉交後背景問老師；查核通過、與交付答案或另一位老師關鍵事實一致才存 `var/training/teacher.jsonl`
- [x] 1.3（tests/test_teacher.py 4 個；全套 630 OK） dataset export 加入 teacher 來源；測試

## 2. 驗證 / Verify

- [x] 2.1（2026-11-23 15:0x，jiezi-cloud 10 題事實題、8 位老師：第一次全數失敗——`teacher.take()` 多執行緒讀寫用量檔競爭〔3c0acbb 修正〕；重跑後 80 份答案收 68 份〔85%〕，全部「和交付答案一致」。不收 12 份：cloudflare-gpt-oss-120b 10 份〔當日免費額度用完〕、muse-glimmer 1 份逾時、agnes 1 份。**發現把關漏洞**：10 題中 9 題由 minimax 交付、minimax 也是老師 → 自己跟自己一致也被收；已改為同一模型不能用「和交付答案一致」〔只能靠另一位老師〕，事後把 9 筆標 training_use=false〔不刪〕，可用 62 筆）實測 10 題：老師答案收與不收的比例、原因；回報使用者

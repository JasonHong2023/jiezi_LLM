## 1. 實作 / Implementation

- [x] 1.1 `JIEZI_TEACHER_MODELS`（多位）／`JIEZI_TEACHER_DAILY_MAX`；請求關 fallback、核對實際模型；OpenRouter 固定 DeepSeek 供應商並核對
- [x] 1.2（`src/jiezi/teacher.py`：關鍵事實〔數字、粗體／引號名稱，扣掉題目本身的〕重疊 ≥0.5 或文字相似 ≥0.3） 轉交後背景問老師；查核通過、與交付答案或另一位老師關鍵事實一致才存 `var/training/teacher.jsonl`
- [x] 1.3（tests/test_teacher.py 4 個；全套 630 OK） dataset export 加入 teacher 來源；測試

## 2. 驗證 / Verify

- [ ] 2.1 實測 10 題：老師答案收與不收的比例、原因；回報使用者

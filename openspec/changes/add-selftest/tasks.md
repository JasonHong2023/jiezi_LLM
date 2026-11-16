## 1. 實作 / Implementation

- [x] 1.1 `src/jiezi/selftest.py`：出題、判分、執行、報告、`--dry` 覆蓋率 / Module
- [x] 1.2 `scripts/jiezi selftest [--policy] [--limit] [--list] [--dry]`

## 2. 驗證 / Verification

- [x] 2.1 單元測試；`openspec validate add-selftest --strict`
- [x] 2.2 `--dry` 資料覆蓋 80/80（順便修正：「38-8-43」被誤當成日期）
- [ ] 2.3 E0 結束後以 jiezi-local 實際跑一次並記錄分數 / Real run after E0

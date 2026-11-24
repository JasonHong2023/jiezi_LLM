## 1. 資料 / Data

- [x] 1.1（程式 `train/replay.py`、`scripts/jiezi train replay`；MBPP @f82046ba sha256 鎖定，只取非 test；參考解答 30/30 在沙盒通過、錯誤答案 0/5；實際產生排在夜間）replay 資料產生（凍結核心作答 → 驗證器 → 只收通過的），排除評測重疊；manifest 記錄來源與授權
- [x] 1.2（`dataset export --limit 800 --replay … --replay-ratio 0.5`；試匯出新資料 2,006 筆）`training_data.export` 支援每源上限與 replay 比例；單元測試

## 2. 訓練 / Training

- [x] 2.1（lr 5e-5、max_len 768、`extra.vram_ceiling_mib` 5500：超過會在紀錄標 over_ceiling；超長樣本排除並計數）`qwen3.5-4b-r2.json`（lr、max_len、資料檔）；`train plan` 估計峰值 ≤ 5,500 MiB
- [x] 2.2（2026-11-19：前兩次失敗〔老師樣本兩則 system；殘留空 run 資料夾〕，第三次 00:57 起訓練 250 步 rc=0 → 匯出 → E0 → 驗證完成 → 關卡**沒過**：qa 64.0 → 64.0 沒提升〔tool +4、code +2、summary +7，無退步〕→ 不換核心〔保留 qwen3.5-4b-q4_k_m〕，使用者 2026-11-19 決定**維持原本的核心**）夜間排程改跑 r2：訓練 → 匯出 → E0 條件評測 → 驗證 → 關卡 → 保留或回滾

## 1. 資料 / Data

- [ ] 1.1 replay 資料產生（凍結核心作答 → 驗證器 → 只收通過的），排除評測重疊；manifest 記錄來源與授權
- [ ] 1.2 `training_data.export` 支援每源上限與 replay 比例；單元測試

## 2. 訓練 / Training

- [ ] 2.1 `qwen3.5-4b-r2.json`（lr、max_len、資料檔）；`train plan` 估計峰值 ≤ 5,500 MiB
- [ ] 2.2 夜間排程改跑 r2：訓練 → 匯出 → E0 條件評測 → 驗證 → 關卡 → 保留或回滾

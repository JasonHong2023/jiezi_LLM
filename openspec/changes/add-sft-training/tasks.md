## 1. 程式 / Code

- [x] 1.1 `train/config.py`、`gate.py`、`sft.py`、`export.py`；`scripts/jiezi train plan|sft|export|gate`
- [x] 1.2 單元測試（不需 PyTorch）；`openspec validate add-sft-training --strict`

## 2. 執行（G1 後，使用者同意）/ Running (after G1, with consent)

- [x] 2.1（2026-11-17 使用者同意；`uv add --group train`：torch 2.15.0+cu132、transformers 5.23.0、peft 0.21.3、bitsandbytes 0.50.2，GPU 可用；audit 143 項未接受漏洞 0；授權登記於 docs/licenses.md）使用者安裝 torch、transformers、peft（必要時 bitsandbytes），`scripts/jiezi audit` 無未接受漏洞
- [x] 2.2（2026-11-17：基底 Qwen/Qwen3.5-4B @ 851bf6e8（與 manifest 授權登記同一 commit）已下載到 HF 快取；設定 `src/jiezi/train/configs/qwen3.5-4b-r1.json`（4-bit、max_len 1024、1 輪） 登記 G1 核心的 HF 基底權重（R18.3），寫訓練設定
- [ ] 2.3（**2026-11-17 冒煙測試：這台 6 GB 顯卡上不可行**——4-bit QLoRA 訓練時顯示記憶體峰值約 6.4 GB，超過實體 6 GB、溢出到共用系統記憶體，每筆約 14 秒，3,499 筆一輪約 13.5 小時，也違反保留顯示記憶體的規則；只算回答位置的 logits、加 fla 核心都沒有改善。待使用者決定做法，見討論記錄 #31） 第一輪訓練 → 匯出 GGUF → E0 格式評測 → 回歸關卡 → 保留或回滾

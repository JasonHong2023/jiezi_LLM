## 1. 程式 / Code

- [x] 1.1 `train/config.py`、`gate.py`、`sft.py`、`export.py`；`scripts/jiezi train plan|sft|export|gate`
- [x] 1.2 單元測試（不需 PyTorch）；`openspec validate add-sft-training --strict`

## 2. 執行（G1 後，使用者同意）/ Running (after G1, with consent)

- [ ] 2.1 使用者安裝 torch、transformers、peft（必要時 bitsandbytes），`scripts/jiezi audit` 無未接受漏洞
- [ ] 2.2 登記 G1 核心的 HF 基底權重（R18.3），寫訓練設定
- [ ] 2.3 第一輪訓練 → 匯出 GGUF → E0 格式評測 → 回歸關卡 → 保留或回滾

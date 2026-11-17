## 1. 程式 / Code

- [x] 1.1 `train/config.py`、`gate.py`、`sft.py`、`export.py`；`scripts/jiezi train plan|sft|export|gate`
- [x] 1.2 單元測試（不需 PyTorch）；`openspec validate add-sft-training --strict`

## 2. 執行（G1 後，使用者同意）/ Running (after G1, with consent)

- [x] 2.1（2026-11-17 使用者同意；`uv add --group train`：torch 2.15.0+cu132、transformers 5.23.0、peft 0.21.3、bitsandbytes 0.50.2，GPU 可用；audit 143 項未接受漏洞 0；授權登記於 docs/licenses.md）使用者安裝 torch、transformers、peft（必要時 bitsandbytes），`scripts/jiezi audit` 無未接受漏洞
- [ ] 2.2 登記 G1 核心的 HF 基底權重（R18.3），寫訓練設定
- [ ] 2.3 第一輪訓練 → 匯出 GGUF → E0 格式評測 → 回歸關卡 → 保留或回滾

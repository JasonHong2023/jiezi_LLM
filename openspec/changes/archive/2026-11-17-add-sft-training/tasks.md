## 1. 程式 / Code

- [x] 1.1 `train/config.py`、`gate.py`、`sft.py`、`export.py`；`scripts/jiezi train plan|sft|export|gate`
- [x] 1.2 單元測試（不需 PyTorch）；`openspec validate add-sft-training --strict`

## 2. 執行（G1 後，使用者同意）/ Running (after G1, with consent)

- [x] 2.1（2026-11-17 使用者同意；`uv add --group train`：torch 2.15.0+cu132、transformers 5.23.0、peft 0.21.3、bitsandbytes 0.50.2，GPU 可用；audit 143 項未接受漏洞 0；授權登記於 docs/licenses.md）使用者安裝 torch、transformers、peft（必要時 bitsandbytes），`scripts/jiezi audit` 無未接受漏洞
- [x] 2.2（2026-11-17：基底 Qwen/Qwen3.5-4B @ 851bf6e8（與 manifest 授權登記同一 commit）已下載到 HF 快取；設定 `src/jiezi/train/configs/qwen3.5-4b-r1.json`（4-bit、max_len 1024、1 輪） 登記 G1 核心的 HF 基底權重（R18.3），寫訓練設定
- [x] 2.3（**2026-11-18 第一輪結果：回滾（不換核心）**。夜間 00:05 開跑，218 步／3,488 筆／6,058 秒，訓練峰值 6,367 MiB（略超過 6,141 MiB 實體，有少量溢出但速度正常，約 1.7 秒／筆）；匯出 Q4_K_M 2.71 GB（sha256 b897b17a…）；E0 條件評測＋雲端驗證完成。回歸關卡 `train gate --target qa` 不通過：qa 64.0→61.3、tool 60→56、code 66→54（summary judge +9.2）。原因推測：訓練資料 3,500 筆中 98% 是法規與台灣條目（moj-laws 1,929、taiwan-md 1,071、tw-taxonomy 407），沒有程式／工具題，lr 2e-4 對 4B 模型偏高，造成遺忘。產物留在 `var/train/qwen3.5-4b-r1/`，未登記 manifest。下一輪要改資料配比與學習率，另案提出。以下為原紀錄：）**2026-11-17 冒煙測試：這台 6 GB 顯卡上不可行**——4-bit QLoRA 訓練時顯示記憶體峰值約 6.4 GB，超過實體 6 GB、溢出到共用系統記憶體，每筆約 14 秒，3,499 筆一輪約 13.5 小時，也違反保留顯示記憶體的規則；只算回答位置的 logits、加 fla 核心都沒有改善。使用者選「拆成多晚」，見討論記錄 #31、#32。**更正（同日 19:05）**：真正原因是 peft 的 `prepare_model_for_kbit_training` 把 24.8 萬字的詞嵌入轉成 fp32；改成只凍結基底後，訓練峰值 5,125 MiB、每筆約 1.5 秒，一輪約 1.5 小時。夜間排程 `jiezi-night-train` 每晚 00:05 執行、可接續，完成後自動匯出 GGUF） 第一輪訓練 → 匯出 GGUF → E0 格式評測 → 回歸關卡 → 保留或回滾

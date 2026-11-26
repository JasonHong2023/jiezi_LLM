## 1. 審閱 / Review

- [x] 1.1（2026-11-26 使用者「照原計畫進行」，採提議）使用者審閱提案，決定 OQ1（量測圖片）與 OQ2（預設值條件）

## 2. 實作 / Implementation

- [x] 2.1（量測前預設 `tools`）`JIEZI_IMAGE_OCR`（auto／on／off）；OCR 載入與觸發條件從 `JIEZI_VISION_TOOLS` 拆出；看圖工具開時照舊每張都跑
- [x] 2.2 doctor 顯示 OCR 可用與否、目前模式與安裝指令
- [x] 2.3 單元測試（auto 只在問字時跑、未安裝不跑、off 不跑、看圖工具開時照舊）；全量測試與 openspec 驗證

## 3. 量測與預設 / Measure and default

- [x] 3.1（2026-11-26：`src/jiezi/eval/vision_text.py`，自製 20 張：法規告示 4、招牌 4、菜單 4、罰鍰告示 4、單欄直排 2、多欄直排 2；字元召回率〔最長共同子序列〕＋數字命中率；`scripts/night/vision-text-eval.sh` 排 11-27 00:05。使用者問直排能否辨識 → 實測單欄直排字都對但會拆段、多欄直排順序變成由左而右 → `vertical_order` 改為由右而左並接回同欄片段；限制：直排「〇」漏偵測）依 OQ1 建立圖中文字評測集與正解
- [ ] 3.2 夜間 OCR 關／auto 各跑一次，比字元正確率與秒數；依 OQ2 決定預設（R20），結果記入討論紀錄
- [ ] 3.3 更新 `docs/clients.md`、README

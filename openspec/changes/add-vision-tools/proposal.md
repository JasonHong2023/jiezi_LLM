> **狀態 / Status**：2026-11-18 使用者審閱：OQ1 寬鬆授權工具（RAM++、OWLv2、Florence-2／D-FINE），OQ2 不用 YOLO，OQ3 核對不過的**保留但標「不確定」**。/ Approved: permissive tools, no YOLO, unconfirmed objects kept and marked uncertain.
>
> **2026-11-25 待決定 OQ4：OCR 改用哪一個**（主控查證，尚未實作）：Florence-2 的 OCR 以英文為主、繁體中文很弱，照原計畫做出來用處不大。建議改用 **RapidOCR＋PP-OCRv5 中文辨識模型**——PP-OCRv5 官方支援簡體、繁體、拼音、英文、日文（PaddleOCR 3.0 技術報告 arXiv 2507.05595）；RapidOCR 用 onnxruntime 在 CPU 執行，不需要 PaddlePaddle 框架；模型為 Apache-2.0。需要新增 `rapidocr`、`onnxruntime` 兩個套件與約 10–90 MB 的模型檔（mobile／server 版），並照慣例做資安掃描與授權登記。另一選項是維持 Florence-2（只對英文有用），或不做 OCR、繼續靠核心模型看圖讀字。
> OQ4 (open): Florence-2 OCR is weak on Traditional Chinese; proposed RapidOCR with the PP-OCRv5 Chinese recognizer (covers Traditional Chinese, CPU via onnxruntime, Apache-2.0). Needs two new packages; awaiting the user's choice.
> **2026-11-25 使用者決定 OQ4：改用 RapidOCR＋PP-OCRv5**（已實作：`src/jiezi/vision_ocr.py`，選用依賴群組 `ocr`，mobile 模型；server 版 32 秒太慢不用）。
> OQ4 decided 2026-11-25: RapidOCR with PP-OCRv5 (implemented, mobile models).

## Why

2026-11-18 使用者附一張動物拼貼圖問「有哪些動物」，本機 Qwen3.5-4B（含 mmproj）花 52.8 秒，答對白老虎、馬、北極熊、狗、貓、猴子；**漏掉**斑馬、鳥；**認錯**紅毛猩猩（說成長臂猿）；**憑空說有**長頸鹿、熊貓、河馬、豬、老鼠。使用者決定：**圖片題不要預設交給雲端或 Claude，要讓本機盡量認得多，可以啟用 YOLO 之類的工具**。
The local 4B VLM missed, confused and invented animals. The user wants images to stay local, helped by detector tools.

小模型看圖的主要問題是**憑空捏造**，不是完全看不到。專用的辨識模型（物件偵測、標籤、文字辨識）又小又準，還能給出信心分數與位置，適合當「眼睛」，再讓語言模型組織回答；同時用開放詞彙偵測去**核對**語言模型說出口的每個東西，沒被偵測到的就刪掉或標「不確定」。
Small VLMs mostly hallucinate. Small specialist models give labels, scores and boxes; an open-vocabulary detector can check every object the VLM names.

## What Changes

- 新增**視覺工具**，在 CPU 上跑（GPU 已被核心用到約 5.5/6.1 GB，依「不可占盡資源」原則不搶）：
  | 工具 | 用途 | 候選模型（授權下載前逐一查證，R18.3） |
  |---|---|---|
  | `image_tags` | 整張圖有哪些東西（數千類，含中文標籤） | RAM++（Recognize Anything Plus，Apache-2.0 ⚠️待查證） |
  | `detect` | 物件位置、數量、信心 | Florence-2-large（MIT ⚠️）或 D-FINE / RT-DETRv2（Apache-2.0 ⚠️，Objects365 365 類） |
  | `find` | 開放詞彙：「圖裡有沒有長頸鹿？」 | OWLv2（Apache-2.0 ⚠️） |
  | `ocr` | 圖中文字（含繁中） | Florence-2 OCR 或 PaddleOCR（Apache-2.0 ⚠️） |
- **為什麼不用 Ultralytics YOLO**：YOLOv8/11 是 **AGPL-3.0**，程式與權重一起散布或做成服務都要開源整個專案，跟 R18 有衝突；而且只認 COCO 80 類（沒有老虎、北極熊、紅毛猩猩）。上表的 D-FINE/RT-DETR 是同等速度、授權寬鬆的即時偵測器。若你仍想用 YOLO，可以列為「使用者自行安裝的選用外掛」，不隨專案散布。
- **看圖流程**（`JIEZI_VISION_TOOLS=on`）：
  1. 附圖時先跑 `image_tags` + `detect`，結果（標籤、數量、信心）當**資料**附給核心模型（不當指令，沿用 injection-guard）；
  2. 核心模型看圖＋看工具結果作答；也可以在回答中途**自己呼叫** `find`／`ocr`／`detect` 追問細節（走 strong-tool-calling 的工具迴圈）；
  3. **核對**：答案裡提到的物體名稱逐一用 `find` 核對，信心低於門檻的**保留但標「（不確定）」**（使用者 2026-11-18），回應 metadata 記下 `vision_check`。
- 新增**看圖評測**：用授權允許的已標註圖片（候選 Open Images V7 驗證集子集，標註 CC BY 4.0、圖片 CC BY 2.0 ⚠️待查證），量「說出的物體」的精確率（有沒有捏造）與召回率（有沒有漏），先量現況，再量加工具後；精確率沒有提升就不預設開（R20）。

## Non-Goals

- 圖片題預設轉雲端／Claude（使用者 2026-11-18 明確不要）。
- 影片、即時鏡頭。
- 訓練視覺模型。

## Capabilities

### New Capabilities

- `vision-tools`：本機視覺工具、看圖流程與核對。

### Modified Capabilities

- `gateway`：Image Input 在有視覺工具時先跑工具。

## Impact

- 新依賴：`onnxruntime`（CPU）或 `transformers`（已有）；模型檔共約 1–3 GB，放 `models/`，寫入 manifest 與 `docs/licenses.md`。
- 延遲：CPU 上每張圖預估 +2～8 秒（量測後回報）；核對步驟每個物體約 0.3–1 秒。
- 下載與評測在夜間（00:00–07:00）做。

## Open Questions

- **OQ1 偵測器選哪個**：建議 RAM++（標籤廣）＋ OWLv2（核對）先做；Florence-2 兼做 OCR 與描述，第二步再加。
- **OQ2 YOLO**：建議不隨專案散布（AGPL），用 D-FINE/RT-DETR 替代；要的話做成選用外掛。
- **OQ3 核對不過的東西**：建議**刪掉並在最後註明**「另外模型提到 X，但偵測不到，已略過」，而不是靜默刪除。

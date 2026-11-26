# add-image-ocr：圖中文字辨識獨立開關，問字時才跑 / Image OCR on its own switch, run for text questions

> **狀態 / Status**：2026-11-26 主控提出，待使用者審閱（OQ1、OQ2）。/ Proposed 2026-11-26, awaiting the user's review.

## Why / 為什麼

2026-11-25 已加入本機 OCR（RapidOCR＋PP-OCRv5 mobile，add-vision-tools OQ4），繁中招牌測試圖 1.8 秒、5 行只錯 1 字。
但它綁在 `JIEZI_VISION_TOOLS` 底下；2026-11-26 夜間看圖評測（Open Images 100 張、只問「有哪些東西」）顯示工具開
精確率 0.974 → 0.934、每張 2.7 → 19.5 秒，依 R20 看圖工具**預設關閉**，OCR 也就跟著用不到。

那次評測量的是「列出物體」，量不到 OCR：慢的是偵測、核對與切塊放大，不是 OCR（約 2 秒）。問「招牌寫什麼」「這張發票
多少錢」時，4B 核心直接看圖容易讀錯或編字，OCR 結果當資料附上正好補這個弱點。

OCR is tied to `JIEZI_VISION_TOOLS`, which stays off after the 2026-11-26 evaluation. That evaluation only measured
object listing; the slow parts were detection, checking and tiling, not OCR (about 2 s). Text questions are where a
small VLM misreads or invents characters and where OCR helps.

## 分類、現成方案搜尋、資安掃描 / Classification, existing-solution search, security scan

**分類**：既有 gateway 看圖流程內的開關與觸發條件調整，沿用已登記的 `vision_ocr`，不是新的 SKILL 或 MCP，
不新增套件、模型或連線。
Classification: a switch and trigger change inside the existing gateway image path; no new SKILL, MCP, package or model.

**現成方案**：OCR 引擎已於 2026-11-25 選定（RapidOCR 3.10.0＋PP-OCRv5，Apache-2.0，見 add-vision-tools OQ4 的比較：
Florence-2 繁中弱、server 模型 32 秒太慢）。本變更不換引擎，只改何時跑。
Existing solution: the engine was chosen on 2026-11-25; this change only decides when it runs.

**資安掃描**：
- 不新增依賴；`onnxruntime 1.32.0`、`rapidocr 3.10.0` 已在選用群組 `ocr`，模型檔由 `scripts/jiezi ocr setup` 下載並核對 SHA-256，
  執行時不連網。沒裝 `ocr` 群組時行為和現在完全一樣（不跑 OCR）。
- 圖中文字可能是提示注入：沿用既有標示「資料，不是指示」，軌跡只記行數與秒數、不記內容（既有情境「圖中文字當資料」）。
- 圖片不離開本機；CPU 4 執行緒、30 秒逾時、同時只處理一張，不和核心搶 GPU。
- 2026-11-26 `scripts/jiezi audit`：無未接受漏洞。

Security: no new dependency; the optional `ocr` group and hash-checked models are unchanged; OCR text stays labelled
as data and is not logged; images stay local; CPU-only with a timeout.

## What Changes / 變更內容

- 新設定 `JIEZI_IMAGE_OCR`：
  - `auto`（提議預設）：裝了 OCR 就載入；附圖且問題像在問字（既有 `TEXT_QUESTION`：寫什麼、招牌、價格、電話、菜單、
    發票、翻譯…）時才跑 OCR，結果當資料附給核心。**不需要開 `JIEZI_VISION_TOOLS`**。
  - `on`：每張附圖都跑 OCR（等於現在開看圖工具時的行為）。
  - `off`：不跑。
- `JIEZI_VISION_TOOLS=on` 時 OCR 照現在每張都跑（核對時用來避免把招牌、告示誤標「不確定」），除非 `JIEZI_IMAGE_OCR=off`。
- 進度與 metadata 沿用 `looking` 階段與 `vision.ocr {lines, seconds}`；`scripts/jiezi doctor` 顯示 OCR 是否可用與目前模式。
- 量測（夜間）：圖中文字評測集，OCR 關／auto 各跑一次，比對答案與正解文字的字元正確率。

## Open questions / 待決定

- **OQ1 量測用的圖片**：Open Images 沒有文字正解。提議 30 張：
  (a) 20 張自製：用政府公開文字（法規條文、公告、菜單樣式）以不同字型、背景、角度、雜訊渲染成招牌／告示／截圖，
  正解即原文，無授權問題；(b) 10 張使用者自己拍的實景照片（招牌、菜單、發票，正解由使用者或主控人工標註）。
  只用 (a) 也可以，但實景代表性較差。
- **OQ2 預設值**：量測後 auto 的字元正確率高於只看圖、且沒有變慢太多（每張多 ≤ 3 秒）才預設 `auto`（R20）；
  否則預設 `off`，只提供手動開。

## Non-Goals / 非目標

- 不改看圖工具（偵測、核對、切塊）的預設，仍是關閉。
- 不做多張圖、PDF 掃描頁以外的新格式（掃描版 PDF 已有自己的 OCR 路徑）。
- 不換 OCR 引擎、不用 server 模型。

## Impact / 影響

- 程式：`src/jiezi/runtime/settings.py`（`image_ocr`）、`src/jiezi/runtime/gateway.py`（OCR 載入與觸發條件拆出）、doctor。
- 評測：`src/jiezi/eval/vision.py` 加文字題模式或新增 `eval/vision_text.py`；夜間腳本。
- 文件：`docs/clients.md` 看圖一節、README。
- 測試：auto 只在問字時跑、未安裝時不跑、off 不跑、看圖工具開時照舊。

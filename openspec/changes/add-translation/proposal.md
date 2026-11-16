> **狀態 / Status**：使用者 2026-11-16 審閱後回覆「可以實作」，Open Questions 已決（見文末）。
> Approved for implementation by the user on 2026-11-16; open questions resolved (see the end).

## Why

使用者 2026-11-16 把「翻譯」列入要做的功能。短句現在就能請芥子翻，但有三個缺口：
The user listed translation among the features to build (2026-11-16). Short sentences already work, with three gaps:

1. **長文件翻不了**：本機每個槽位只有 4096 token。add-long-documents 對長文件只會「摘要」或「挑段落回答」，要求翻譯整份文件時，模型拿到的是幾段節錄，譯文必然殘缺。
   Long documents cannot be translated: the long-document path only summarizes or selects chunks, so a full translation comes back incomplete.
2. **沒有任何檢查**：小模型翻譯常見的錯是漏譯、數字或專有名詞譯錯、整段沒翻。目前沒有驗證，也不會重試。
   Nothing is checked: omissions, wrong numbers and untranslated passages go through unnoticed.
3. **簡體轉繁體不需要模型**：這是字與用語的轉換，芥子已有 OpenCC 對照表，直接轉換又快又不會改意思；現在卻會交給模型重寫一遍。
   Simplified-to-Traditional conversion needs no model; Jiezi already has the tables, yet today the model rewrites the text.

## What Changes

- **翻譯意圖辨識**（`src/jiezi/translate.py`）：問題含「翻譯／翻成／譯成／translate … into …」且指出目標語言時視為翻譯請求；目標語言以代碼表示（初版 `zh-TW`、`en`）。沒指出目標語言時，中文原文預設譯成英文，其他語言預設譯成繁體中文。
  Translation intent: a request naming translation and a target language (`zh-TW` and `en` initially). Without a target, Chinese goes to English and anything else to Traditional Chinese.
- **整份翻譯（長文件）**：有附文件且放不進本機上下文時，改走「逐段翻譯」而不是摘要：依段落切成較小的段（輸出與輸入差不多長，所以每段上限約 900 token）→ 每段各自翻譯（引擎的 4 個槽位平行）→ 依原文順序接回。每段的提示附上「前一段原文的結尾」當上下文（只供理解、不翻），以及使用者給的詞彙對照表。接回的譯文**直接回傳**，不再交給模型重寫（重寫會放不進上下文，也可能改動內容）。
  Whole-document translation: paragraph-aligned chunks (about 900 tokens, since output is as long as input) are translated in parallel across the engine's slots and joined in source order. Each prompt carries the tail of the previous source chunk as context and the user's glossary. The joined text is returned as is, never rewritten by the model.
- **每段檢查與重試**：不是空的；長度與原文的比例在合理範圍（依語言對設定上下限）；原文的阿拉伯數字都出現在譯文；目標是中文時譯文不能大半仍是原文語言（反之亦然）；詞彙對照表中出現的詞必須用指定譯法。沒過的段帶著錯誤訊息重翻一次；仍沒過就保留原文並標出「〔第 N 段未能翻譯〕」，回應的 `jiezi.translation` 列出失敗的段。
  Per-chunk checks with one retry: non-empty, plausible length ratio, every Arabic number preserved, the output actually in the target language, glossary terms honoured. A chunk that still fails keeps its source text, clearly marked, and is listed in `jiezi.translation`.
- **短文字**：放得進上下文的翻譯照原本的流程由模型回答，但加上同一組檢查（數字、語言、詞彙表），沒過就依既有分層重試或轉交。
  Short texts keep the normal path, with the same checks feeding the existing retry and escalation tiers.
- **簡體 → 繁體**：目標是 `zh-TW` 而原文是簡體中文時，不呼叫模型，直接用既有的 OpenCC 字表與台灣用語表轉換，回應標明「字詞轉換，未經模型」。**轉換後的內容仍是簡體來源的資料，不進訓練資料**（使用者規定不收簡體中文資料）。
  Simplified to Traditional is done by the existing conversion tables with no model call, labeled as such, and never enters training data.
- **CLI**：`scripts/jiezi translate 檔案 --to en [--out 譯文.md] [--glossary 詞彙.tsv] [--plain] [--yes]`；`ask --file` 與 chat `/file` 加上「翻譯成…」的問題也走同一條路。預設輸出「原文一段、譯文一段」對照，`--plain` 只輸出譯文。支援的輸入格式與附加文件相同（PDF、.docx、.pptx、.xlsx、.html、純文字）；輸出是純文字或 Markdown。
  `jiezi translate FILE --to LANG`, plus the same path from `ask --file` and chat; Output interleaves source and translation by default; `--plain` gives the translation alone. Input formats are those of attachments; output is text or Markdown.
- **設定**：`JIEZI_TRANSLATE`（預設 on）；關閉時翻譯請求照一般問題處理。
- **訓練資料**：翻譯軌跡一律 `training_use=false`（譯文正不正確無法由程式證明；且原文多為使用者的私人文件）。

## Non-Goals

- 保留原檔版面（Word 樣式、PowerPoint 版型、Excel 儲存格位置）或輸出回原格式；輸出只有文字。/ Preserving layout or writing back to the original format.
- 翻譯品質評分（BLEU、COMET 等需要參考譯文與新相依）；初版只做結構檢查，品質靠 2.1 的人工抽查。/ Automatic quality scores.
- 即時口譯、語音、圖片中的文字（掃描 PDF 仍走既有 OCR）。/ Speech, live interpreting, text inside images.
- `zh-TW`、`en` 以外的目標語言（含日文；模型可能會，但不檢查、不承諾）。/ Target languages other than `zh-TW` and `en`.
- 繁體 → 簡體（使用者不收簡體中文資料；需要時再提）。/ Traditional to Simplified.

## Capabilities

### New Capabilities

- `translation`：翻譯意圖、整份文件逐段翻譯、譯文檢查、簡轉繁。/ Intent, chunked whole-document translation, checks, script conversion.

### Modified Capabilities

- `documents`：長文件多一種處理方式（逐段翻譯），與摘要、問答並列（`documents` 由尚未歸檔的 add-long-documents 建立）。/ A third long-document mode beside summary and QA.

## Impact

- 無新相依。**[估]** 耗時：輸出與輸入等長，10 萬字文件約 110 段；以開發機目前核心（Qwen3-0.6B，GPU 約 110 t/s [實測 11-14]）、4 槽平行推估約 10–20 分鐘，換成較大的核心會更久。屬長時間工作：預估超過 5 分鐘時先顯示預估時間並等確認，並可中斷後續跑（已翻的段寫入 `var/translate/`，R8）。
  No new dependencies. A 100,000-character document is roughly 110 chunks; estimated 10–20 minutes on the current small core, longer on a bigger one, so long jobs show an estimate first and can resume.
- **[推論]** 小模型的翻譯品質未知：0.6B 連一般問答都常出錯，翻譯很可能要等 G1 選定較大的核心才堪用；結構檢查抓得到漏譯與數字錯，抓不到「意思翻錯」。這點會寫進 `docs/clients.md`。
  Quality on a small core is unknown; the checks catch omissions and wrong numbers, not wrong meaning.
- 隱私：失敗的段不外送。已翻好的段暫存在 `var/translate/`（只在本機、不進版控）供中斷後續跑。注意：`jiezi` 策略在本機引擎不可用時，仍會照既有的文件處理方式把整個請求轉交 Claude；不想外送請用 `--local`。

## 實作時的更正（2026-11-16，R19.4）/ Correction during implementation

- **原說法**：簡體 → 繁體「直接用既有的 OpenCC 字表與台灣用語表轉換」。
- **更正**：既有的只有單字表，「后、发、干、里、只」這類字要依詞決定（后台→後臺、皇后→皇后、头发→頭髮、干净→乾淨），只用單字表會轉錯。實作時從**同一個已登記、同一個鎖定 commit** 的 OpenCC（Apache-2.0）多取了兩個資料檔：`STPhrases.txt`（詞語對照，約 1 MB）與 `TWVariants.txt`（台灣異體字），照 OpenCC 的 s2twp 流程轉換。不是新相依（沒有新套件、沒有新授權），但資料檔比提案多了兩個，已登記在 `docs/licenses.md`。**[實測]** 182 萬字 12.1 秒。
  The existing table is character-level only, which mis-converts context-dependent characters. Two more data files from the same registered, pinned OpenCC commit were added (`STPhrases.txt`, `TWVariants.txt`); no new package or license.
- 另：檢查規則補了一條——中翻英時「11 月」會變成 November，月份數字不算漏掉（日與年仍要在）。
  Also: month numbers may become month names in English and are not counted as missing.

## 已決事項（原 Open Questions；使用者 2026-11-16 回覆並同意實作）/ Resolved (user, 2026-11-16)

- **OQ1 目標語言**：只做 `zh-TW` 與 `en`；日文不在初版。/ `zh-TW` and `en` only; no Japanese in the first version.
- **OQ2 失敗的段**：保留原文並標記，**不外送**。/ Keep the source and mark it; nothing is sent out.
- **OQ3 預設輸出**：**原文／譯文對照**；只要譯文時加 `--plain`。/ Bilingual by default; `--plain` for the translation alone.
- **OQ4 長時間門檻**：預估超過 5 分鐘先顯示預估並等確認（`translate` 指令的 `--yes` 可略過）；確認後白天也可以跑。聊天中遇到超過門檻的翻譯，gateway 不開始翻，改回覆預估時間並請使用者改用 `translate` 指令。/ Over an estimated 5 minutes the command asks first (`--yes` skips); in chat the gateway answers with the estimate and points to the command instead of starting.

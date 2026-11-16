## Why

芥子會讀使用者附的文件（PDF、Word、網頁）、工具回傳的結果，以及自己查到的資料。這些內容裡可能藏著「忽略以上指示」「把金鑰貼出來」之類的句子（提示注入）；小模型特別容易照做。使用者 2026-11-16 同意依建議順序先做這項。
Jiezi reads attached documents, tool results and retrieved data, any of which can carry injected instructions that a small model tends to obey. The user approved doing this first (2026-11-16).

## What Changes

- `src/jiezi/injection.py`：
  - `clean`：移除零寬與方向控制字元（藏指令用），把文件內偽造的 `【文件：…】`、`【文件結束】` 換成 `〔…〕`，文件無法「提早結束」跳出資料區。`documents.attach` 與 gateway 對工具結果都會呼叫。
  - `scan`：中英文常見注入句型六類（忽略指示、改變身分、洩漏系統提示、偽造系統訊息、外傳機密、命令呼叫工具）。
  - `guard`：只檢查「資料」——使用者訊息中的文件區塊、`tool` 訊息、gateway 自己附加的資料；使用者本人的話與客戶端（Hermes、OpenCode）的系統提示不檢查。
  - `add_reminder`：加一則安全規則系統訊息，說明資料不是指示。
  Cleaning, heuristic detection over data only (never the user's own words or the client's system prompt), and a safety note.
- gateway（`chat`，在查資料與附技能範例之後）：
  - 有使用者文件或工具結果 → 一律加安全規則；gateway 自己查到的資料（辭典、法規、知識庫、記憶、技能範例）只有偵測到可疑句型才加，一般請求與評測流量因此一字不改。
  - 偵測到可疑句型 → 軌跡記 `injection`、`training_use=false`；不學技能、不存記憶；回應的 `jiezi.injection` 帶 `suspected`、`where`、`warning`。回答本身照常產生，不擋、不改內容。
  - `JIEZI_INJECTION_GUARD`（預設 on）。
  Documents and tool results always get the note; flagged requests are excluded from skills, memory and training and carry a warning in `jiezi.injection`. The answer itself is never blocked or rewritten.
- 訓練資料匯出：`injection.suspected` 非空的軌跡排除（原因 `suspected_injection`）。
- 客戶端：`jiezi chat`／`ask` 的狀態行多一行警告（管線輸出時寫到 stderr）；桌面網頁在回答下方顯示警告。

## Non-Goals

- 保證抓到所有注入：偵測是啟發式（關鍵句型），換個說法、用其他語言或拆成多段就抓不到。真正的保護是「外部內容不能觸發有副作用的動作」——目前芥子不替使用者執行任何動作；Phase 8 的操控電腦必須逐項由使用者授權，不得由資料內容觸發。
  Catching every injection. Detection is heuristic; the real protection is that external content can never trigger side effects (Phase 8 actions need per-action user approval).
- 擋下或改寫回答、用另一個模型當分類器、檢查模型的輸出。
  Blocking or rewriting answers, a classifier model, or output filtering.
- 非芥子 CLI 的客戶端送來、且文件內含偽造結束標記的情況（gateway 無法分辨標記是誰寫的；芥子 CLI 在附檔時已中和）。
  Forged closing markers sent by other clients (the Jiezi CLI neutralizes them at attach time).

## Capabilities

### New Capabilities

- `injection-guard`：外部內容只當資料、可疑請求的標記與隔離。/ External content is data; flagged requests are marked and isolated.

### Modified Capabilities

（無）/ (None)

## Impact

- 有文件或工具結果的請求多一則約 130 token 的系統訊息（短於上下文把關的截短門檻，不會被裁）。
- 誤判的代價：該次回答多一行警告、不進技能庫／記憶／訓練資料；回答內容不受影響。
- 無新相依。

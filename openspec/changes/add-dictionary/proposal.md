## Why

使用者希望 jiezi「學會」繁體中文詞彙（2026-11-15：「都放進去讓他學習吸收」）。0.6B 會編造詞義，也常回簡體字；把教育部辭典放在本機、回答前先查，能立刻改善，而且換核心模型也不用重做。真正訓練進權重要等 Phase 6，且需要允許 AI 訓練的授權（臺灣主權 AI 訓練語料庫，需使用者申請）。
The user wants jiezi to "learn" Traditional Chinese vocabulary. The 0.6B invents meanings and often answers in Simplified Chinese; a local Ministry of Education dictionary consulted before answering helps immediately and survives a core change. Training into weights waits for Phase 6 and a license that allows AI training (the TAIC corpus, which the user must apply for).

## What Changes

- 新增 `dictionaries/manifest.toml`（來源、鎖定網址、SHA-256、授權、是否可訓練、出處文字）與 `scripts/jiezi dict build`：下載、核對 SHA-256、建成 `var/dict/dict.sqlite`。第一個來源：g0v 整理的《重編國語辭典修訂本》（161,194 筆，CC BY-ND 3.0 TW）。
  Add `dictionaries/manifest.toml` and `scripts/jiezi dict build` (download, verify SHA-256, build `var/dict/dict.sqlite`). First source: the g0v JSON of the MOE Revised Mandarin Dictionary (161,194 entries, CC BY-ND 3.0 TW).
- gateway 在問題是在問詞語（意思、解釋、注音、成語、造句等，或用「」標出的詞）時，查辭典並把**原文**附給模型，要求依辭典回答並註明出處；回應的 `jiezi.sources` 列出用到的詞條。
  When a question asks about words (meaning, pronunciation, idioms, example sentences, or a term in 「」), the gateway looks them up and gives the model the **verbatim** entries, asking it to answer from them and cite the source; `jiezi.sources` lists the entries used.
- 用到「禁止改作」辭典的對話，軌跡標 `training_use: false`。
  Conversations that used a no-derivatives dictionary carry `training_use: false`.
- `scripts/jiezi dict lookup 詞` 可直接查詢。/ `scripts/jiezi dict lookup <word>` for direct lookups.

## Non-Goals

- 訓練進模型權重（Phase 6，需 TAIC 授權）。/ Training into weights (Phase 6, needs the TAIC license).
- 國語辭典簡編本（官方網站目前無回應）、TBCL 詞語表（授權未確認）：之後各自加入清單。
  The Concise dictionary (official site unresponsive) and the TBCL word list (license unconfirmed): added later.
- 修改辭典內容或轉成簡化字（授權禁止）。/ Modifying entries or converting to Simplified characters (forbidden by the license).

## Capabilities

### New Capabilities

- `dictionary`：本機辭典的來源清單、建置、查詢與對話中的引用。/ Local dictionary sources, build, lookup and citation in chats.

### Modified Capabilities

（無）/ (None)

## Impact

- 下載約 14 MB，建置後約 100 MB 以內的 SQLite（`var/`，不進版控）。只用標準函式庫（`sqlite3`、`lzma`）。
  About 14 MB download, an SQLite file of up to about 100 MB under `var/` (not committed). Standard library only.

> **狀態 / Status**：2026-11-18 提案，等使用者審閱。/ Proposed, awaiting review.

## Why

使用者 2026-11-18：請教 Claude 就是要芥子「記憶和當訓練資料」，訓練資料來源「兩種都用」：本機在階梯中自己答對的答案（已做，
commit ec44c5d）＋條款允許的開源老師模型。Claude 的輸出依 Anthropic 條款與 R6.8 不能當訓練資料。
查證（docs/licenses.md `teacher-gpt-oss-120b-cloudflare`）：gpt-oss-120b 權重 Apache-2.0、使用政策只要求守法；
Cloudflare Developer Platform 條款把輸出列為客戶內容。NVIDIA API 條款讀不到，暫不用。
Training data comes from the local model's own solved answers and from a teacher whose terms allow it.

## What Changes

- 老師模型：LiteLLM 的 `cloudflare-gpt-oss-120b`（`JIEZI_TEACHER_MODEL`，預設空＝關；使用者同意後設定）。
  請求帶 `disable_fallbacks`，並核對回應的 `model`，**確定是 gpt-oss** 才收（避免 LiteLLM 換成條款未查的模型）。
- 何時問老師：每次轉交（Claude 或雲端回答了使用者）後，在背景把同一題問老師；老師的答案通過現有查核（工具 schema、
  程式語法、依附上資料）才存成訓練候選 `var/training/teacher.jsonl`（license 欄記 gpt-oss Apache-2.0 / Cloudflare），
  不影響使用者看到的回答。
- 和 Claude 的答案比對：關鍵數字、名稱不一致就標 `disagree`，不收（Claude 只用來把關，內容不進訓練集）。
- `scripts/jiezi dataset export` 加入 teacher 來源，照現有規則（評測重疊排除、每來源上限）。
- 每天上限（`JIEZI_TEACHER_DAILY_MAX`，預設 100），用量計入雲端統計。

## Non-Goals

- 用 Claude 的輸出訓練（條款不允許）。
- 用條款未查證的模型當老師。

## Capabilities

### Modified Capabilities

- `training-data`：新增 Teacher Answers 需求。

## Impact

- 題目會送到 Cloudflare（使用者已同意雲端轉交）。訓練候選要等下一輪訓練才會用到；R20 回歸門檻照舊。

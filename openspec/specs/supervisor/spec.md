# supervisor Specification

## Purpose
在資源預算內延遲載入本機引擎，限次重啟，與夜間評測協調 GPU，並依量測做部分卸載。
Load the local engine lazily within budget, restart boundedly, share the GPU with night jobs and offload by measurement.
## Requirements
### Requirement: Budgeted Lazy Engine

supervisor SHALL 在第一個需要本機的請求時才載入核心模型（`JIEZI_CORE_MODEL`，模型清單中的名稱），載入前 SHALL 重算資源預算，並沿用 E0 的擺放規則（整個放 GPU，否則純 CPU）。放不下時 SHALL 拒絕載入並說明原因。閒置超過 `JIEZI_IDLE_UNLOAD_S` 後 SHALL 卸載模型。
The supervisor SHALL load the core model (`JIEZI_CORE_MODEL`, a manifest name) only on the first request that needs it, SHALL recompute budgets before loading, and SHALL reuse the E0 placement rule (whole GPU, else CPU only). If it does not fit, it SHALL refuse with the reason. After `JIEZI_IDLE_UNLOAD_S` idle seconds it SHALL unload the model.

#### Scenario: 閒置卸載 / Idle unload

- **WHEN** 引擎閒置超過設定的秒數
  The engine stays idle longer than the configured seconds
- **THEN** 引擎被關閉，`var/runtime/state.json` 記為未載入；下一個請求會重新載入
  The engine is stopped and `var/runtime/state.json` says unloaded; the next request reloads it

### Requirement: Bounded Restart

引擎異常結束時，supervisor SHALL 重啟，60 秒內最多 3 次；超過後 SHALL 標記為不可用，並在 `/health` 與 `state.json` 說明原因。
When the engine dies, the supervisor SHALL restart it at most 3 times within 60 seconds; beyond that it SHALL mark the engine unavailable and state the reason in `/health` and `state.json`.

#### Scenario: 反覆當機 / Repeated crashes

- **WHEN** 引擎在 60 秒內第 4 次異常結束
  The engine dies for the 4th time within 60 seconds
- **THEN** 不再重啟，引擎標為不可用，`jiezi` 請求改走雲端（若已開啟），`jiezi-local` 回 503
  No more restarts; the engine is marked unavailable, `jiezi` requests go to the cloud (if enabled), `jiezi-local` gets 503

### Requirement: Night Evaluation Coordination

supervisor SHALL 在 `var/runtime/state.json` 寫出引擎狀態，並提供只限本機、需要金鑰的卸載端點。夜間評測載入模型前 SHALL 讀取此狀態；引擎有載入時 SHALL 先要求卸載並暫停 gateway 載入到夜間時段結束，並把 gateway 狀態記入執行條件。
The supervisor SHALL write engine state to `var/runtime/state.json` and offer a local, key-protected unload endpoint. Before loading a model, a night evaluation SHALL read this state; if the engine is loaded, it SHALL request an unload, hold gateway loading until the window ends, and record the gateway state in the run conditions.

#### Scenario: 評測開始時 gateway 載著模型 / Gateway holds a model when an evaluation starts

- **WHEN** 夜間評測要載入模型，而 gateway 的引擎正占用 GPU
  A night evaluation is about to load a model while the gateway's engine holds the GPU
- **THEN** gateway 卸載模型並暫停載入，評測在完整預算下載入，條件記錄 `gateway: unloaded_for_eval`
  The gateway unloads and holds, the evaluation loads under full budgets, and conditions record `gateway: unloaded_for_eval`

### Requirement: Measured Partial Offload

核心模型依預算判定為純 CPU、且 `bench.json` 有同一檔案（SHA-256 相同）的實測最佳 GPU 層數時，supervisor SHALL 以該層數載入；檔案不同時 SHALL NOT 採用。
A CPU-placed core with a measured best layer count for the same file SHALL load with it; a different file SHALL NOT use it.

#### Scenario: 換了檔案 / A different file

- **WHEN** bench.json 的 SHA-256 與核心檔案不同
  The recorded SHA-256 differs from the core file
- **THEN** 不採用實測值，照預算擺放
  The measurement is ignored


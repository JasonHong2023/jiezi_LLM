## 1. 契約模型與驗證 / Contract model and validation

- [x] 1.1 在 `src/jiezi/agent/contract.py` 新增 TaskContract 資料結構與 normalization，欄位包含 `goal`、`constraints`、`done_criteria`、`risk`、`allowed_tools`、`budget`，且 `goal`／`done_criteria` 必填非空。 / Add TaskContract data structure and normalization in `src/jiezi/agent/contract.py` with the six required fields; `goal` and `done_criteria` MUST be non-empty.
- [x] 1.2 為 contract.py 新增單元測試，覆蓋完整 contract 通過、缺少 goal、空白 done_criteria、未知欄位不產生授權。 / Add unit tests for contract.py covering valid input, missing goal, blank done_criteria, and unknown fields never granting authority.

## 2. 工具與預算收斂 / Tool and budget narrowing

- [x] 2.1 實作 `allowed_tools` 與目前 grant／唯讀工具登錄的交集，未知或未授權名稱視為驗證失敗。 / Implement intersection of `allowed_tools` with current grants/read-only tool registry; reject unknown or ungranted names.
- [x] 2.2 實作 `budget` 對既有 loop ceiling 的 cap，記錄 requested 與 effective 值，缺少 budget 時使用既有常數。 / Cap `budget` to existing loop ceilings, record requested and effective values, and fall back to existing constants when omitted.
- [x] 2.3 新增測試覆蓋授權子集、未授權工具拒絕、超額 budget cap、缺少 budget 預設。 / Add tests for granted subset, ungranted rejection, over-ceiling cap, and missing-budget defaults.

## 3. 代理迴圈接入 / Agent loop integration

- [x] 3.1 修改 `src/jiezi/agent/loop.py`：工具分派前先驗證 contract；驗證失敗時回傳釐清／拒絕且不呼叫工具。 / Update `src/jiezi/agent/loop.py` to validate contract before tool dispatch; on failure return clarification/rejection with zero tool calls.
- [x] 3.2 讓 bounded loop 只使用 effective budget 與 effective tools，且不改變既有取消、timeout、工具結果視為資料的語意。 / Make the bounded loop use only effective budget/tools while preserving cancellation, timeout, and tool-result-as-data semantics.
- [x] 3.3 新增測試覆蓋有效 contract 進入迴圈、模糊 contract 零工具呼叫、有效工具清單限制。 / Add tests for valid contract entering the loop, vague contract producing zero tool calls, and effective tool restriction.

## 4. 軌跡終態與重建 / Trajectory state and reconstruction

- [x] 4.1 擴充 `src/jiezi/runtime/trajectory.py` 或代理寫入路徑，附加 contract、effective budget、effective tools、`completed`／`failed`／`aborted` 終態與時間欄位。 / Extend `src/jiezi/runtime/trajectory.py` or the agent write path with contract, effective budget/tools, `completed`/`failed`/`aborted` terminal state, and timestamps.
- [x] 4.2 確保寫入失敗仍只 warning、不影響回答，且 `last_error` 可供診斷。 / Ensure write failures still warn only, never break responses, and expose `last_error` for diagnosis.
- [x] 4.3 新增測試覆蓋單次執行可重建、舊 JSONL 向後相容、寫入失敗不中斷回答。 / Add tests for single-run reconstruction, backward compatibility with old JSONL, and non-breaking write failures.

## 5. 驗證與紀錄 / Verification and records

- [x] 5.1 執行 `openspec validate --all --strict`、`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`、`GIT_MASTER=1 git diff --check`，並確認既有 642 項測試不退化。 / Run strict OpenSpec validation, the unit suite, and git diff check; confirm the existing 642 tests do not regress.
- [x] 5.2 更新 `HANDOFF.md` 與 `2026-11-19.md`，記錄 A1 狀態、覆蓋範圍、驗證結果與殘留風險。 / Update `HANDOFF.md` and `2026-11-19.md` with A1 status, coverage, verification results, and residual risks.

## 完成紀錄（2026-11-19 13:59 CST）

- 1.1–5.2 全數完成；contract 為 metadata only，不轉送 engine、不擴大 grant、不新增 SKILL／MCP，既有 API 向後相容。
- 驗證：targeted `TestContract` 5/5、`TestLoop` 7/7、`TestGatewayAgent` 6/6；全量 `PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` 654/654 OK（原 642 + 新增 12；ResourceWarning 為既有）。
- `openspec validate --all --strict` 44 passed／0 failed；`openspec status --change add-agent-contract --json` artifacts 全 done；`GIT_MASTER=1 git diff --check` 無輸出。
- 未 stage／commit／push；未重啟 systemd gateway、未做 live smoke；A2–A8 仍待各自 R4 提案與核准。
- **14:05 最終重跑補記（R19.4，保留 13:59 結果）**：`openspec validate --all --strict` 44/44；全量 unittest 654/654 OK（74.465 秒）；`GIT_MASTER=1 git diff --check` 無輸出；`git status --short` 仍有他人 `add-sft-round2/tasks.md`。未 stage／commit／push。
- **14:08 最終確認（R19.4，保留前述結果）**：文件回填後再跑 `openspec validate --all --strict` 44/44、`GIT_MASTER=1 git diff --check` 無輸出；全量 unittest 654/654 OK（74.321 秒）。git status 仍只見本變更與他人 `add-sft-round2/tasks.md`。未 stage／commit／push。

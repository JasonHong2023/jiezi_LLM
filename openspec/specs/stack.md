# 技術棧鎖定 / Tech Stack Lock

> 依規則 R9 建立；未經 R4 討論不得引入新依賴或變更以下版本。
> Created per rule R9; no new dependency or version change without an R4 discussion.
> 每次變更需同時更新「資安查證」段落（R23.2）。
> Every change must also update the security-check section (R23.2).

| 項目 / Item | 鎖定值 / Pinned value |
|---|---|
| 建立日期 / Created | 2026-11-14 |
| 最後更新 / Last updated | 2026-11-14 |

## 1. 跨機器一律鎖定 / Locked on every machine

| 層次 / Layer | 技術 / Technology | 版本 / Version | 來源 / Source |
|---|---|---|---|
| 推論引擎 / Inference engine | llama.cpp（vendored ggml 0.29.0） | commit `93cf736a8d1d46aa922e27eb64aa712bcd5ebc30`（2026-11-12） | `https://github.com/ggml-org/llama.cpp` |
| Python | CPython | 3.13（`.python-version`；`requires-python >=3.13,<3.14`） | uv 管理 / managed by uv |
| 套件管理 / Package manager | uv | ≥ 0.11（開發機 0.11.21） | 官方安裝方式 / official installer |
| 建置 / Build | cmake（PyPI） | 4.4.4（`uv.lock`） | `pyproject.toml` dev 群組 |
| 建置 / Build | ninja（PyPI） | 1.13.2（`uv.lock`） | `pyproject.toml` dev 群組 |
| 執行期 Python 依賴 / Runtime Python deps | 無（只用標準函式庫） / none (stdlib only) | — | R9、R23 |
| 規格工具 / Spec tooling | OpenSpec | 1.4.1 | — |
| 冒煙測試模型 / Smoke-test model | `Qwen3-0.6B-Q8_0.gguf` | HF repo commit `23749fefcc72300e3a2ad315e1317431b06b590a`，SHA-256 `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` | `models/manifest.toml` |

## 2. 依機器偵測決定（不鎖定）/ Decided per machine by detection (not pinned)

| 項目 / Item | 決定方式 / How decided |
|---|---|
| CUDA toolkit | 依驅動支援的 CUDA 版本挑選不超過上限的最新版；WSL2 用 `wsl-ubuntu` 套件庫，原生 Ubuntu 用對應版本的套件庫（design D8） |
| C/C++ 編譯器 / Compiler | 系統提供；須為 CUDA toolkit 支援的版本 |
| 建置的後端 / Backends built | 依 `facts.json` 的 `backends.buildable`；CPU 一律建置 |
| CUDA 架構 / CUDA architectures | `-DCMAKE_CUDA_ARCHITECTURES=native` |

開發機參考值（不得寫進程式，R21）：CUDA toolkit 13.3（`nvcc` V13.3.73）、gcc 13.3。
Dev-box reference values (never in code, R21): CUDA toolkit 13.3 (`nvcc` V13.3.73), gcc 13.3.

## 3. 強制建置旗標 / Mandatory build flags

| 旗標 / Flag | 值 / Value | 理由 / Reason |
|---|---|---|
| `GGML_RPC` | **`OFF`（明確指定，不依賴預設值）** | 見 §4 的 CVE-2026-34159；本專案不需要 RPC 後端 |
| `GGML_NATIVE` | `ON` | 由編譯器偵測 CPU 指令集，不寫死型號 |
| `CMAKE_BUILD_TYPE` | `Release` | — |

**禁止 / Prohibited**：建置或執行 `rpc-server`；將任何 llama.cpp 服務綁定 `127.0.0.1` 以外的位址（R6.12）。
Building or running `rpc-server`; binding any llama.cpp service to anything other than `127.0.0.1` (R6.12).

## 4. 資安查證（R23.2）/ Security check (R23.2)

查證日期 / Checked: 2026-11-14

| 項目 / Item | 來源 / Source | 結果 / Result |
|---|---|---|
| cmake 4.4.4（PyPI） | OSV API | 0 個已知漏洞 [實測查詢] |
| ninja 1.13.2（PyPI） | OSV API | 0 個已知漏洞 [實測查詢] |
| llama.cpp | GitHub Security Advisories（`ggml-org/llama.cpp`） | 13 則公告；除下列一則外，受影響範圍都早於鎖定的 commit（2026-11-12） |
| **llama.cpp RPC 後端** | **GHSA-j8rj-fmpv-wcxw / CVE-2026-34159（Critical）** | 未授權遠端執行程式碼（RPC `deserialize_tensor()` 在 `buffer == 0` 時跳過邊界檢查）。公告範圍 `<= b7991`、未列修正版本。**[本機查證]** 鎖定 commit 的 `ggml/src/ggml-rpc/ggml-rpc.cpp` 中，`buffer == 0` 時仍直接採用遠端傳入的 `data`，此函式內未見修正；是否在其他位置修正無法確認。**緩解：`GGML_RPC=OFF` 且不執行 `rpc-server`（§3）** |
| Python 3.13 | — | 由 uv 取得官方版本；每次決策關卡以 `pip-audit` 複查（R23.5） |

## 5. 已選定、尚未鎖定版本 / Chosen but not yet pinned

| 項目 / Item | 選定技術 / Choice | 何時鎖定 / Pin when |
|---|---|---|
| TUI / CLI | Python + Textual | Phase 4.8 |
| Desktop App | Tauri 2（≥ 2.11.1）+ React（純前端 SPA，≥ 19.0.3 / 19.1.4 / 19.2.3） | Phase 8 |
| 工具介面 / Tool interface | MCP | Phase 8 |
| 訓練 / Training | PyTorch（CUDA wheel） | Phase 0.4 / Phase 3 |

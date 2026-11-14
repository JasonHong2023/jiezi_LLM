## Context

前身專案 `~/projects/hetero-llm` 已完成並驗證：`scripts/hwprobe.py`（622 行，只用標準函式庫）、21 個單元測試、`add-hwprobe` 變更（6 條 requirement，未歸檔），以及 CPU 與 CUDA 兩種 llama.cpp 建置（commit `93cf736a8d1d46aa922e27eb64aa712bcd5ebc30`）。
The predecessor `~/projects/hetero-llm` has a validated `scripts/hwprobe.py` (622 lines, stdlib only), 21 unit tests, the unarchived `add-hwprobe` change (6 requirements), and both CPU and CUDA llama.cpp builds (commit `93cf736a8d1d46aa922e27eb64aa712bcd5ebc30`).

這些成果都是在開發機上手動完成的：cmake / ninja 以 `uv pip` 裝在 `.venv`，CUDA toolkit 13.3 由使用者在新視窗輸入 sudo 密碼安裝，llama.cpp 以 `--depth 1` clone。
All of it was done by hand on the dev box: cmake / ninja installed into `.venv` via `uv pip`, CUDA toolkit 13.3 installed by the user typing a sudo password in a new window, and llama.cpp cloned with `--depth 1`.

規則 R21 要求同樣的結果能在任何支援的電腦上一鍵重現。
Rule R21 requires the same result to be reproducible with one command on any supported machine.

## Goals / Non-Goals

**Goals:**
- 原樣遷入 hwprobe 與測試，再以獨立 commit 修正兩個可攜性缺陷並加入機器指紋。
  Migrate hwprobe and its tests verbatim, then fix the two portability defects and add a machine fingerprint in separate commits.
- 讓「乾淨的 Linux / WSL2 → clone → `scripts/bootstrap` → 冒煙測試通過」成立。
  Make "clean Linux / WSL2 → clone → `scripts/bootstrap` → smoke test passes" true.
- 所有單元測試在沒有 GPU、網路、雲端金鑰的電腦上通過（R21.7）。
  All unit tests pass on a machine with no GPU, network, or cloud keys (R21.7).

**Non-Goals:**
- 不遷移 `LLM_discussion` 的研究文件（R15 Q3），另開一個只含文件的變更處理。
  Research documents from `LLM_discussion` are not migrated here (R15 Q3); a separate docs-only change will handle them.
- 不重構 hwprobe 的模組結構（目前單檔），除非修正需要。
  hwprobe's single-file structure is not refactored unless a fix requires it.
- 其餘見 proposal 的 Non-Goals。
  See the proposal for the remaining non-goals.

## Decisions

### D1 — bootstrap 由「薄 bash 入口 + Python 標準函式庫實作」構成 / Thin bash entry + stdlib Python implementation

`scripts/bootstrap` 是 bash 腳本，只做兩件事：檢查 `uv` 是否存在、呼叫 `uv run python -m jiezi_bootstrap`（實作放在 `scripts/` 或 `src/` 下的 Python 模組）。
`scripts/bootstrap` is a bash script that only checks for `uv` and then calls `uv run python -m jiezi_bootstrap` (implemented as a Python module).

- 理由：步驟邏輯（狀態判斷、SHA-256 驗證、TOML 解析、從 facts 決定後端）需要單元測試；bash 難以測試。
  Rationale: the step logic (state checks, SHA-256, TOML parsing, backend selection from facts) needs unit tests, which bash makes hard.
- 替代方案：純 bash（難測試、難跨平台）；Makefile（錯誤處理與續跑較弱）；引入 invoke / nox 等工具（違反「不新增依賴」與 R23 的查證成本）。
  Alternatives: pure bash (hard to test and port); Makefile (weak error handling and resumption); invoke / nox (new dependency plus R23 vetting cost).

### D2 — Python 環境以 `pyproject.toml` + uv 管理 / Python environment via `pyproject.toml` + uv

`.python-version` 鎖定 3.13；`pyproject.toml` 的**執行期依賴為空**，`cmake`、`ninja` 列為開發依賴（dependency group），由 `uv sync` 安裝到 `.venv`。
`.python-version` pins 3.13; `pyproject.toml` has **no runtime dependencies**, while `cmake` and `ninja` are a dev dependency group installed into `.venv` by `uv sync`.

- 理由：沿用已驗證的「不需 sudo 取得 cmake / ninja」做法，並由 `uv.lock` 鎖定版本。
  Rationale: keeps the proven "cmake / ninja without sudo" approach, with versions locked by `uv.lock`.

### D3 — llama.cpp 以完整 commit hash 取得 / Fetch llama.cpp by full commit hash

`stack.md` 記錄完整 hash `93cf736a8d1d46aa922e27eb64aa712bcd5ebc30` 與來源 `https://github.com/ggml-org/llama.cpp`。取得方式：`git init` → `git fetch --depth 1 origin <hash>` → `git checkout FETCH_HEAD`，最後驗證 `HEAD`。
`stack.md` records the full hash and the source URL. Fetch via `git init` → `git fetch --depth 1 origin <hash>` → `git checkout FETCH_HEAD`, then verify `HEAD`.

- 理由：`--depth 1` clone 取得的是當下的 `master`，不同時間 clone 會不一致；以 hash 取得才可重現。
  Rationale: a `--depth 1` clone gets whatever `master` is at that moment; fetching by hash is reproducible.
- 替代方案：git submodule（會讓 repo 依賴子模組狀態，且 `vendor/` 已約定不進版控）。
  Alternative: a git submodule (couples the repo to submodule state, and `vendor/` is agreed to stay unversioned).

### D4 — `nvcc` 偵測順序 / `nvcc` discovery order

`PATH` → `CUDA_HOME/bin` → `CUDA_PATH/bin` → `/usr/local/cuda/bin` → `/usr/local/cuda-*/bin`（依版本號排序取最高）。紀錄 `{path, version, found_via}`，`found_via ∈ {path, cuda_home, cuda_path, standard_location}`。
Record `{path, version, found_via}`.

- 理由：涵蓋 NVIDIA 官方套件庫（裝在 `/usr/local/cuda-X.Y` 且不改 PATH）與使用者自訂安裝；版本由 `nvcc --version` 解析。
  Rationale: covers NVIDIA's repository layout (installed to `/usr/local/cuda-X.Y` without touching PATH) and custom installs; version parsed from `nvcc --version`.

### D5 — 專案根目錄與輸出位置 / Project root and output locations

專案根目錄 = `Path(__file__).resolve().parent.parent`，可由 `JIEZI_HOME` 覆寫。`facts.json` 預設寫在專案根目錄；建置紀錄與 bootstrap 狀態寫在 `var/`（不進版控）。
Project root = `Path(__file__).resolve().parent.parent`, overridable by `JIEZI_HOME`. `facts.json` defaults to the project root; build records and bootstrap state go in `var/` (unversioned).

### D6 — 機器指紋 / Machine fingerprint

只取**靜態**欄位：CPU 型號、實體核數、邏輯核數、RAM 總量（四捨五入到 GiB，避免核心保留記憶體的小幅浮動）、各 GPU 名稱與 VRAM 總量、平台（`linux` / `wsl2` / `darwin`）、GPU 驅動版本。以排序後的 JSON 計算 SHA-256，取前 16 個十六進位字元作為 `fingerprint.id`。
Only **static** fields are used: CPU model, physical and logical core counts, total RAM (rounded to GiB to absorb small kernel-reserved fluctuations), GPU names and total VRAM, platform (`linux` / `wsl2` / `darwin`), and GPU driver version. `fingerprint.id` is the first 16 hex characters of the SHA-256 of the sorted JSON.

- 取捨：驅動版本納入指紋，所以升級驅動會讓校準失效——這是刻意的，因為驅動會影響效能（R17）。
  Trade-off: the driver version is part of the fingerprint, so a driver upgrade invalidates calibration — intentionally, since drivers affect performance (R17).

### D7 — 模型清單用 TOML / Model manifest in TOML

`models/manifest.toml` 以標準函式庫 `tomllib` 解析；模型存放於 `JIEZI_MODELS_DIR`（預設 `<專案根目錄>/models/`，不進版控）。每筆有 `smoke_test = true/false`；冒煙測試用標記為 `true` 的最小模型。
Parsed with stdlib `tomllib`; models live in `JIEZI_MODELS_DIR` (default `<project root>/models/`, unversioned). Each entry has `smoke_test = true/false`; the smoke test uses the smallest entry marked `true`.

### D8 — sudo 步驟的等待視窗 / Waiting window for sudo steps

沿用 Phase 0.2 已驗證的做法，並依平台選擇開視窗方式：WSL2 → `wt.exe`（不存在時改用 `cmd.exe /c start`）；原生 Ubuntu 有圖形介面時 → `x-terminal-emulator` / `gnome-terminal`；無圖形介面 → 在目前終端機直接執行。所有方式都是「等使用者按 Enter → `sudo -v`，失敗就回到等待」，沒有時間限制；完成後寫狀態檔，主程式等待狀態檔。
Reuses the approach proven in Phase 0.2, choosing the window by platform: WSL2 → `wt.exe` (fallback `cmd.exe /c start`); native Ubuntu with a GUI → `x-terminal-emulator` / `gnome-terminal`; headless → run in the current terminal. Every variant is "wait for Enter → `sudo -v`, loop on failure" with no time limit, then writes a status file the main process waits on.

- CUDA toolkit 版本：解析 `nvidia-smi` 標頭的 CUDA 版本（驅動支援上限），從 NVIDIA 套件庫索引挑「不超過上限的最新版」。
  CUDA toolkit version: parse the CUDA version in the `nvidia-smi` header (the driver's ceiling) and pick the newest toolkit not above it from the NVIDIA repository index.

### D9 — 可攜性守門以單元測試實作 / Portability guard as a unit test

`tests/test_portability.py` 掃描 `git ls-files` 的檔案。要比對的值**在測試執行時動態取得**：目前使用者的家目錄路徑、`WSL_DISTRO_NAME`（若有）。另外檢查 `*.php` 與常見金鑰樣式（例如 `sk-` 開頭的長字串、`AIza…`、`nvapi-…`）。
`tests/test_portability.py` scans `git ls-files`. The values to match are **obtained at test time**: the current user's home path and `WSL_DISTRO_NAME` (if set). It also checks for `*.php` and common key patterns.

- 理由：測試本身不寫死任何使用者名稱，換到任何電腦都能用（否則守門程式自己就違反 R6.13）。
  Rationale: the test hardcodes no username, so it works on any machine (otherwise the guard itself would violate R6.13).

## Risks / Trade-offs

- [GitHub 不允許以 hash 淺層 fetch] → 失敗時退回完整 fetch 再 checkout，並記錄耗時。
  [GitHub refuses a shallow fetch by hash] → fall back to a full fetch then checkout, recording the time cost.
- [CUDA 建置耗時（開發機約 13 分鐘）] → 背景執行並依預算限制資源；bootstrap 可續跑，不必重頭來。
  [CUDA builds are slow (~13 min on the dev box)] → run in the background within budget; bootstrap resumes rather than restarting.
- [NVIDIA 套件庫結構改變] → 套件庫網址與選版邏輯集中在 `scripts/setup/<platform>/` 一處；失敗時退回純 CPU 並說明。
  [NVIDIA repository layout changes] → URLs and version selection live in one place under `scripts/setup/<platform>/`; on failure fall back to CPU-only with an explanation.
- [冒煙測試模型的下載網址或授權變動] → 清單中的 SHA-256 與授權欄位是守門；不符就停止。
  [Smoke-model URL or license changes] → the manifest's SHA-256 and license fields act as gates; mismatches stop the run.
- [hwprobe 單檔持續變大] → 本變更不重構；超過可維護範圍時另開變更拆模組。
  [hwprobe keeps growing as one file] → not refactored here; a separate change will split it when needed.

## Migration Plan

1. 從 `hetero-llm` **原樣複製** `scripts/hwprobe.py` 與 `tests/`，單獨 commit（確保遷入本身不改行為，21 個測試照樣通過）。
   Copy `scripts/hwprobe.py` and `tests/` from `hetero-llm` **verbatim** in their own commit (the migration itself changes no behaviour; all 21 tests still pass).
2. 依 tasks 逐項修正與新增，每個 task 一個 commit（R5）。
   Apply fixes and additions task by task, one commit each (R5).
3. 在開發機以外的乾淨環境（新的 WSL distro 或容器）執行 `scripts/bootstrap` 驗證（R21.8）。
   Verify with `scripts/bootstrap` in a clean environment other than the dev box (a fresh WSL distro or a container) (R21.8).
4. 回滾：任何一步都可以 `git revert`；`hetero-llm` 保持不動，隨時可以對照。
   Rollback: every step can be `git revert`ed; `hetero-llm` stays untouched for comparison.

## Open Questions

（無未決事項；以下兩項已於 2026-11-14 由使用者決定。 / No open items; both were decided by the user on 2026-11-14.）

### 已決 OQ1 — 冒煙測試模型 / Resolved OQ1 — Smoke-test model

採用官方 `Qwen/Qwen3-0.6B-GGUF` 的 `Qwen3-0.6B-Q8_0.gguf`。 / Use `Qwen3-0.6B-Q8_0.gguf` from the official `Qwen/Qwen3-0.6B-GGUF`.

| 欄位 / Field | 值 / Value |
| --- | --- |
| 下載網址 / URL | `https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/23749fefcc72300e3a2ad315e1317431b06b590a/Qwen3-0.6B-Q8_0.gguf`（以 repo commit 鎖定 / pinned by repo commit） |
| 大小 / Size | 639,446,688 bytes |
| SHA-256 | `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` |
| 授權 / License | Apache 2.0（Hugging Face 標籤；實作時依 R18.3 讀官方 LICENSE 檔確認 / HF tag; confirm against the official LICENSE file per R18.3） |

開發機現有的 `Qwen3-1.7B-Q4_K_M.gguf` 不列入清單（沒有來源紀錄）。 / The dev box's existing `Qwen3-1.7B-Q4_K_M.gguf` is not listed (no recorded source).

### 已決 OQ2 — 乾淨環境驗證 / Resolved OQ2 — Clean-environment verification

使用者決定：「換一台乾淨的電腦也能重建」的驗證環境**必須是 Ubuntu**。 / The user decided the clean-rebuild verification environment **must be Ubuntu**.

- **做法（使用者 2026-11-14 修訂）**：Claude **不建立** WSL distro。先在目前的開發環境驗證（含另外 clone 一份 repo 從零執行 bootstrap）；乾淨的 Ubuntu 24.04 WSL 環境由使用者自行建立，只裝 git、編譯器與 OpenSSL 標頭後 clone repo 執行 `scripts/bootstrap`。環境名稱不寫進 repo（R6.13）。
  **Approach (revised by the user, 2026-11-14)**: Claude does **not** create a WSL distro. Verification first runs in the current dev environment (including bootstrap from a fresh clone); the user builds the clean Ubuntu 24.04 WSL environment, installs only git, a compiler, and the OpenSSL headers, then clones and runs `scripts/bootstrap`. Environment names are never committed (R6.13).
- **原生 Ubuntu 為必做**（使用者 2026-11-14 確認）：WSL distro 只驗證 `wsl2` 平台路徑；**原生 Ubuntu**（實體機或虛擬機）的 `ubuntu` 平台路徑**也必須驗證通過**，本變更才可歸檔。結果記入討論記錄（R21.8）。
  **Native Ubuntu is mandatory** (user-confirmed 2026-11-14): a WSL distro only verifies the `wsl2` path; the **native Ubuntu** (bare metal or VM) `ubuntu` path **must also pass** before this change can be archived; the user also prepares that environment. Results are logged (R21.8).

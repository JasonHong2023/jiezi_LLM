## Why

芥子 repo 目前只有規則檔，前身專案 `hetero-llm` 裡已驗證的硬體探測（hwprobe、21 個測試、6 條 requirement）還沒遷入。
The Jiezi repo currently holds only the rules file; the hardware probe already validated in the predecessor project `hetero-llm` (hwprobe, 21 tests, 6 requirements) has not been migrated.

使用者要求專案必須能搬到其他電腦運作（規則 R21），但現有 hwprobe 有兩個可攜性缺陷：只在 `PATH` 中找 `nvcc`（CUDA 裝在 `/usr/local/cuda-13.3` 時誤報「缺 nvcc」），以及以「目前工作目錄」而非專案根目錄尋找 `.venv/bin/cmake`。
The user requires the project to run on other machines (rule R21), yet hwprobe has two portability defects: it looks for `nvcc` only on `PATH` (falsely reporting "nvcc missing" when CUDA lives in `/usr/local/cuda-13.3`), and it resolves `.venv/bin/cmake` against the current working directory instead of the project root.

此外還沒有任何「在乾淨電腦上一鍵重建」的機制，所有環境都靠手動在開發機上設定。
There is also no "one-command rebuild on a clean machine"; every environment has been set up by hand on the development box.

這是 Phase 0（開發計畫 0.1、0.5）的最後一塊，後續所有階段（評測、E0 實測、gateway）都建立在它之上。
This is the last piece of Phase 0 (dev plan 0.1 and 0.5); every later phase (evaluation, E0 benchmarks, gateway) builds on it.

## What Changes

- 遷入 `hwprobe`（`scripts/hwprobe.py` 與 `tests/`），保留既有行為與 21 個測試。
  Migrate `hwprobe` (`scripts/hwprobe.py` and `tests/`), preserving existing behaviour and all 21 tests.
- 修正 `nvcc` 偵測：除了 `PATH`，也依序檢查 `CUDA_HOME` / `CUDA_PATH` 與常見安裝位置。
  Fix `nvcc` detection: besides `PATH`, also check `CUDA_HOME` / `CUDA_PATH` and common install locations.
- 修正工具鏈偵測：`cmake` / `ninja` 改以專案根目錄定位 `.venv`，不再依賴目前工作目錄。
  Fix toolchain discovery: locate `.venv` from the project root for `cmake` / `ninja`, no longer relying on the working directory.
- 在 `facts.json` 加入**機器指紋**，供量測結果標示來源機器（R21.6）。
  Add a **machine fingerprint** to `facts.json` so measurements can record their source machine (R21.6).
- 新增可攜性骨架：`pyproject.toml`（uv）、`.env.example`、`.gitignore`、`scripts/bootstrap`、`scripts/setup/<platform>/`、`models/manifest.toml`、`openspec/specs/stack.md`。
  Add the portability skeleton: `pyproject.toml` (uv), `.env.example`, `.gitignore`, `scripts/bootstrap`, `scripts/setup/<platform>/`, `models/manifest.toml`, and `openspec/specs/stack.md`.
- `scripts/bootstrap` 在乾淨的 Linux / WSL2 上依序：建 Python 環境 → 依鎖定 commit 取得 llama.cpp → 執行 hwprobe → **依偵測結果**建置後端 → 依清單下載並驗證模型 → 純 CPU 冒煙測試。
  On a clean Linux / WSL2 machine, `scripts/bootstrap` runs in order: Python env → llama.cpp at the pinned commit → hwprobe → build backends **based on what was detected** → download and verify models from the manifest → CPU-only smoke test.
- 需要 sudo 的平台步驟（例如安裝 CUDA toolkit）只在使用者同意後執行，並以開新視窗、沒有時間限制的方式等待輸入（規則 R15 C11、R21.4）。
  Platform steps that need sudo (e.g. installing the CUDA toolkit) run only with the user's consent, waiting for input in a new window with no time limit (rules R15 C11, R21.4).

## Capabilities

### New Capabilities

- `hwprobe`：唯讀硬體探測與資源預算，輸出 `facts.json`（自 `hetero-llm` 的 `add-hwprobe` 遷入，並加入可攜性修正與機器指紋）。
  `hwprobe`: read-only hardware probing and resource budgets producing `facts.json` (migrated from `hetero-llm`'s `add-hwprobe`, with portability fixes and a machine fingerprint).
- `build`：依鎖定 commit 取得 llama.cpp，並依 `facts.json` 決定要建置哪些後端（CPU 一律建置）。
  `build`: fetch llama.cpp at the pinned commit and decide which backends to build from `facts.json` (CPU is always built).
- `bootstrap`：在乾淨電腦上一鍵重建環境，含 `.env` 設定、平台專用安裝步驟、模型清單與冒煙測試。
  `bootstrap`: one-command environment rebuild on a clean machine, covering `.env` configuration, platform-specific setup steps, the model manifest, and the smoke test.

### Modified Capabilities

（無；`openspec/specs/` 目前是空的。）
(None; `openspec/specs/` is currently empty.)

## Non-Goals

- 不實作 gateway、評測框架、E0 實測、核心壓縮或任何客戶端（TUI / Desktop）。
  No gateway, evaluation harness, E0 benchmarks, core compression, or clients (TUI / Desktop).
- 不支援在 Windows 原生環境執行**引擎**或 bootstrap（R21.2：引擎只支援 Linux 與 WSL2）。
  No running the **engine** or bootstrap natively on Windows (R21.2: the engine supports Linux and WSL2 only).
- macOS 與 Linux ARM64 只求純 CPU 路徑不中斷，不保證 bootstrap 完整驗證。
  macOS and Linux ARM64 only need the CPU-only path not to break; full bootstrap verification is not guaranteed.
- 不自動安裝 Ubuntu 以外發行版的 CUDA toolkit；其他發行版只輸出說明。
  No automatic CUDA toolkit installation on distributions other than Ubuntu; others get instructions only.
- 不修改 `vendor/llama.cpp` 原始碼（R6.2）。
  No modifications to the `vendor/llama.cpp` sources (R6.2).

## Impact

- **新增程式 / New code**：`scripts/hwprobe.py`、`scripts/bootstrap`、`scripts/setup/{ubuntu,wsl2}/`、`tests/`。
- **新增設定 / New config**：`pyproject.toml`、`.python-version`、`.env.example`、`.gitignore`、`models/manifest.toml`。
- **新增規格 / New specs**：`openspec/specs/{hwprobe,build,bootstrap}/spec.md`（歸檔後）、`openspec/specs/stack.md`（R9 技術棧鎖定）。
- **規則連動 / Rules follow-up**：R5 能力表需新增 `bootstrap`（R14 要求同步），於本變更歸檔時一併更新。
  The R5 capability table must gain `bootstrap` (R14 sync), updated when this change is archived.
- **依賴 / Dependencies**：Python 執行期只用標準函式庫（hwprobe）；開發工具 `cmake`、`ninja` 以 uv 安裝；不引入其他新依賴（R9、R23）。
  Runtime Python uses the standard library only (hwprobe); dev tools `cmake` and `ninja` are installed via uv; no other new dependencies (R9, R23).
- **前身專案 / Predecessor**：`~/projects/hetero-llm` 保留不動，作為對照。
  `~/projects/hetero-llm` is left untouched for reference.

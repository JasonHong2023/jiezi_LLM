## 1. 專案骨架 / Project skeleton

- [ ] 1.1 建立 `.gitignore`（`.venv/`、`.env`、`facts.json`、`var/`、`vendor/`、`build-*/`、`models/*.gguf`、`__pycache__/`）與 `.python-version`（3.13） / Add `.gitignore` and `.python-version` (3.13)
- [ ] 1.2 建立 `pyproject.toml`：執行期依賴為空，`cmake`、`ninja` 列為 dev dependency group；執行 `uv sync` 產生 `uv.lock` / Add `pyproject.toml` (no runtime deps; `cmake`, `ninja` as a dev group) and generate `uv.lock` with `uv sync`
- [ ] 1.3 建立 `.env.example`：列出 R21.3 的所有 `JIEZI_*` 變數、用途與範例值，不含真實金鑰 / Add `.env.example` listing every `JIEZI_*` variable from R21.3 with purpose and example values, no real keys
- [ ] 1.4 建立 `openspec/specs/stack.md`：鎖定 llama.cpp 完整 hash `93cf736a8d1d46aa922e27eb64aa712bcd5ebc30`、Python 3.13、uv、cmake、ninja 版本，並記錄 R23 的資安查證結果 / Add `openspec/specs/stack.md` pinning versions and recording the R23 security check

## 2. 遷入 hwprobe（不改行為） / Migrate hwprobe (no behaviour change)

- [ ] 2.1 從 `hetero-llm` 原樣複製 `scripts/hwprobe.py` 與 `tests/test_budgets.py`、`tests/test_backend_parse.py`，單獨 commit / Copy hwprobe and tests verbatim from `hetero-llm` in their own commit
- [ ] 2.2 執行 `uv run python -m unittest discover -s tests`，確認 21 個測試全部通過並記錄結果 / Run the test suite and confirm all 21 tests pass

## 3. hwprobe 可攜性修正 / hwprobe portability fixes

- [ ] 3.1 專案根目錄改由腳本位置推得（可由 `JIEZI_HOME` 覆寫），`.venv`、`build-*`、預設輸出位置都相對於根目錄；新增「從其他目錄執行」的測試 / Derive the project root from the script location (overridable by `JIEZI_HOME`); add a run-from-elsewhere test
- [ ] 3.2 依 design D4 實作 `nvcc` 偵測順序與 `backends.toolchain.nvcc`（路徑、版本、`found_via`）；以假檔案系統測試「不在 PATH」與「完全沒有」兩種情境 / Implement the D4 `nvcc` discovery order; test "not on PATH" and "absent" with a fake filesystem
- [ ] 3.3 依 design D6 新增 `fingerprint` 區塊與 `fingerprint.id`；測試「動態數值改變時 id 不變」與「硬體不同時 id 改變」 / Add the D6 `fingerprint` block; test id stability and change
- [ ] 3.4 確認非 Linux 平台的優雅降級：以模擬「沒有 `/proc/cpuinfo`」的測試驗證 JSON 結構完整、exit code 為 0 / Verify graceful degradation off Linux with a simulated missing `/proc/cpuinfo`

## 4. 可攜性守門 / Portability guard

- [ ] 4.1 新增 `tests/test_portability.py`（design D9）：掃描 `git ls-files`，動態比對目前使用者家目錄路徑與 `WSL_DISTRO_NAME`，並檢查 `*.php` 與金鑰樣式 / Add the D9 portability test using values obtained at test time
- [ ] 4.2 對現有所有版控檔案執行守門測試，修正發現的問題 / Run the guard on all versioned files and fix any findings

## 5. llama.cpp 建置 / llama.cpp build

- [ ] 5.1 實作取得原始碼：依 `stack.md` 的 hash 以 `git fetch --depth 1` 取得（失敗時退回完整 fetch），驗證 `HEAD`；commit 不符或有未提交改動時停止 / Implement pinned fetch with fallback and the stop conditions
- [ ] 5.2 實作後端選擇：依 `facts.json` 的 `backends.buildable` 決定建置 CPU（一律）與其他後端；以假 facts 測試「有 CUDA」與「沒有 GPU」 / Implement facts-driven backend selection; test with fake facts
- [ ] 5.3 實作受預算限制的建置與建置紀錄（`var/`）：`-j` 取 `usable_threads`、`nice`、`taskset`（`affinity_hint` 可得時）、旗標不含硬體型號 / Implement budget-bounded builds and the build record

## 6. 平台安裝步驟 / Platform setup

- [ ] 6.1 抽出共用的「開新視窗、沒有時間限制等待 sudo」機制（design D8），依平台選擇 `wt.exe` / 終端機模擬器 / 目前終端機 / Extract the shared no-time-limit sudo window mechanism (D8)
- [ ] 6.2 `scripts/setup/wsl2/install_cuda`：依驅動支援的 CUDA 版本選擇 toolkit，使用 `wsl-ubuntu` 套件庫，不安裝驅動 / WSL2 CUDA toolkit installer
- [ ] 6.3 `scripts/setup/ubuntu/install_cuda`：使用對應 Ubuntu 版本的 NVIDIA 套件庫，其餘同 6.2 / Native Ubuntu CUDA toolkit installer

## 7. 模型清單與 bootstrap / Model manifest and bootstrap

- [ ] 7.1 建立 `models/manifest.toml`（冒煙測試模型：`Qwen3-0.6B-Q8_0.gguf`，網址、SHA-256、大小依 design 已決 OQ1；先讀官方 LICENSE 確認 Apache 2.0），實作解析、授權欄位檢查、下載與 SHA-256 驗證；以本機假檔案測試「SHA 不符」與「缺授權欄位」 / Add the manifest and its loader with license and SHA-256 checks; test failure cases offline
- [ ] 7.2 實作 `scripts/bootstrap`（bash 入口）與 Python 步驟模組：前置條件檢查、`.env` 建立、各步驟狀態記錄與續跑 / Implement the bash entry and the Python step module with prerequisite checks, `.env` creation, and resumable state
- [ ] 7.3 實作冒煙測試：純 CPU、不連雲端，輸出 build、模型、執行緒數與 t/s / Implement the CPU-only, no-cloud smoke test

## 8. 驗證（量測與實作分開） / Verification (separate from implementation)

- [ ] 8.1 在開發機上執行 `scripts/bootstrap`，確認重複執行時會略過已完成的步驟，並記錄結果（R17 條件） / Run bootstrap on the dev box, confirm skip-on-rerun, and record results with R17 conditions
- [ ] 8.2 經使用者同意後，建立全新的 Ubuntu 24.04 WSL distro，只裝 git 與編譯器，clone 後執行 `scripts/bootstrap` 並通過冒煙測試（R21.8，design 已決 OQ2），結果記入討論記錄 / With consent, create a fresh Ubuntu 24.04 WSL distro, install only git and a compiler, run bootstrap, and pass the smoke test
- [ ] 8.3 **必做**：在原生 Ubuntu（實體機或虛擬機）上重複 8.2，驗證 `ubuntu` 平台路徑；通過後本變更才可歸檔 / **Mandatory**: repeat 8.2 on native Ubuntu (bare metal or VM) for the `ubuntu` platform path; required before archiving
- [ ] 8.4 執行 `openspec validate add-portable-foundation --strict` 與完整單元測試；更新 R5 能力表加入 `bootstrap`（R14） / Validate the change, run all tests, and add `bootstrap` to the R5 capability table (R14)

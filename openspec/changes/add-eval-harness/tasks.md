## 1. 授權登記 / License registry

- [x] 1.1 建立 `docs/licenses.md`：逐一讀官方授權檔（C-Eval、CMMLU、Chinese SimpleQA、evalplus、ACEBench、中文維基、繁簡對照表來源、既有的 Qwen3-0.6B），登記來源、授權、商用、訓練、查證日期與來源；二手資料標 ⚠️ / Create `docs/licenses.md` from official license files

## 2. 題庫 / Question bank

- [x] 2.1 建立 `eval/banks/r0.toml`（各來源網址、鎖定 revision、下載檔 SHA-256、登記鍵、題型、分組、題數、種子）與解析器 `src/jiezi/eval/bank.py`（含授權閘門）；測試缺登記鍵、SHA 不符 / Add the bank definition and parser with the license gate; test missing key and SHA mismatch
- [x] 2.2 `src/jiezi/eval/sources.py`：下載（驗 SHA-256）與各格式解析（ZIP 內 CSV、JSONL、`jsonl.gz`、JSON）為統一題目格式；以本機迷你樣本檔測試 / Download and parse each format into one item schema; test with local mini fixtures
- [x] 2.3 `src/jiezi/eval/wiki.py`：典範條目列表與指定 revision 的條目 HTML，清理、截斷、正規化；以本機 HTML 樣本測試 / Wikipedia featured list and pinned-revision article cleaning; test with local HTML fixtures
- [x] 2.4 `src/jiezi/eval/lock.py`：固定種子分層抽題、寫出與驗證 `r0.lock.json`、`bank_hash`、題數檢查；測試重現性與不符時停止 / Seeded stratified sampling, lock write/verify, count check; test reproducibility and mismatch stop

## 3. 後端 / Backends

- [x] 3.1 `src/jiezi/eval/client.py`：OpenAI 相容客戶端（`urllib`），基準模式帶 `disable_fallbacks` 並核對 `model`，記錄 usage、延遲、`timings`；逾時與有限重試（D11）；以本機假伺服器測試（含卡住、429、5xx） / OpenAI-compatible client with the baseline guard, timeouts and bounded retries (D11); test hangs, 429 and 5xx against a local fake server
- [x] 3.2 `src/jiezi/eval/engine.py`：啟動與關閉 `llama-server`（`127.0.0.1`、實驗區段 port、預算執行緒、`nice` / `taskset`、`-ngl`、ctx），等待 `/health`，取樣峰值 RAM / VRAM；以假執行檔測試 port 被占用與中斷 / Local engine lifecycle and peak-memory sampling; test port conflicts and interruption with a fake binary

## 4. 評分、執行、報表 / Scoring, runs, reports

- [x] 4.1 `src/jiezi/eval/prompts.py` 與 `scoring.py`：各題型提示模板（含雜湊）、選擇題字母擷取、SimpleQA 近似比對（含繁簡正規化）、`pending_verifier`；測試各種回答格式 / Prompt templates, MC extraction, approximate SimpleQA matching; test answer formats
- [x] 4.2 `src/jiezi/eval/runner.py`：逐題執行與寫入、`conditions.json`（R17.1）、`--resume` 與條件比對、`errors.jsonl`、連續 5 題失敗暫停、`--retry-errors`、`--samples N`；以假後端測試續跑、條件不符與暫停 / Per-item runner with conditions, resume, failure pause and `--retry-errors`; test with a fake backend
- [x] 4.3 `src/jiezi/eval/report.py`：`report.json` / `report.md`，分組、貪婪與多樣本分開、未評分與作廢分列、t/s、峰值記憶體、token；測試不會產生單一總分 / Reports with R17.5 grouping; test that no single overall score is produced

## 5. 夜間時段與 CLI / Night window and CLI

- [x] 5.1 `src/jiezi/eval/night.py`：解析 `JIEZI_NIGHT_WINDOW`（含跨午夜）、判斷是否在時段內、計算下一個開始時間、`systemd-run --user` 一次性排程與背景程序後備、`var/eval/schedule/` 狀態；以注入的時鐘與假 `systemd-run` 測試 / Night window and scheduling; test with an injected clock and a fake `systemd-run`
- [x] 5.2 `scripts/eval` 與 `src/jiezi/eval/__main__.py`：`bank fetch|lock|verify`、`run`（時段檢查、`--now`、時段結尾停止）、`report`、`schedule [--list]`；`.env.example` 加入 `JIEZI_NIGHT_WINDOW` / CLI entry and subcommands; add `JIEZI_NIGHT_WINDOW` to `.env.example`

## 6. 驗證（量測與實作分開；長時間工作一律 00:00 之後）/ Verification (measurement separate; long jobs after 00:00)

- [ ] 6.1 下載來源並產生 `r0.lock.json`（只下載約 20 MB 資料，非長時間工作），確認各類 ≥ 50 題後 commit 鎖定檔 / Fetch sources, generate and commit the lock (small download, not a long job)
- [ ] 6.2 以 `scripts/eval schedule` 排程到 00:00 之後：本機 Qwen3-0.6B-Q8_0、純 CPU、貪婪解碼跑完整 R0；隔天確認排程確實執行並記錄結果（R17 條件） / Schedule a full local R0 run after 00:00 and record results next day
- [ ] 6.3 經使用者同意後（OQ3），排程到 00:00 之後以雲端基準模型跑 150 題知識題（基準模式），記錄作廢題數、失敗題數與實際模型；有失敗時隔夜以 `--retry-errors` 補跑 / With consent (OQ3), schedule the 150 knowledge items on the cloud baseline after 00:00
- [ ] 6.4 執行 `openspec validate add-eval-harness --strict` 與完整單元測試，結果記入討論記錄 / Validate the change and run all unit tests; log results

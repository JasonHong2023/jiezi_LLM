## 0. 前置 / Prerequisites

- [ ] 0.1 使用者決定 OQ1～OQ4（BitNet、候選清單與下載量、取樣範圍、評審用量與模型）/ User decides OQ1–OQ4
- [ ] 0.2 `add-verifiers` 歸檔（E0 的推理 / 工具分數依賴驗證器）/ `add-verifiers` archived (E0 reasoning / tool scores depend on verifiers)

## 1. 模型清單 / Manifest

- [ ] 1.1 逐一讀候選模型官方 LICENSE 檔，登記 `docs/licenses.md`；`models/manifest.toml` 加入候選（鎖定 commit、SHA-256、大小、授權欄位）/ Read each official LICENSE, register licenses, add candidates to the manifest
- [ ] 1.2 `eval/e0/matrix.toml`：分組、基底、預設擺放；載入時檢查清單欄位齊全 / The matrix, with a completeness check against the manifest

## 2. 規劃與冒煙 / Plan and smoke

- [ ] 2.1 `scripts/eval e0 plan`：依預算判斷擺放（整個 GPU 或純 CPU）、排除超過 RAM 的模型、依實測 t/s 估算時間 / Placement, budget exclusions, time estimate
- [ ] 2.2 `scripts/eval e0 smoke`：固定 5 題、思考外洩偵測、可解析題數門檻；`excluded_smoke` / The 5-item smoke check
- [ ] 2.3 單元測試：擺放規則、預算排除、冒煙判定、狀態檔續跑 / Unit tests

## 3. 執行 / Runs

- [ ] 3.1 `scripts/eval e0 run`：依矩陣順序、固定執行代號、狀態檔、夜間時段停止與續跑；完成後呼叫 `verify` / Matrix-ordered resumable runs, then verify
- [ ] 3.2 取樣設定：前 3 名、N=8、溫度 0.7；pass@1、多數決、pass@8 / Sampled setting and its three metrics

## 4. 報表 / Report

- [ ] 4.1 `scripts/eval e0 report`：報表、兩張 SVG 帕累托圖、同基底對照表、95% 信賴區間、排除清單 / Report, SVG Pareto charts, same-base table, confidence intervals, exclusions

## 5. 驗證 / Verification（長時間工作一律 00:00 之後）

- [ ] 5.1 單元測試全部通過；`openspec validate add-e0-benchmark --strict` / Unit tests and strict validation
- [ ] 5.2 夜間：下載候選並核對 SHA-256 / Night: download candidates and verify SHA-256
- [ ] 5.3 夜間：冒煙檢查；Qwen3.5-2B Q4_K_M 在 GPU 與 CPU 各跑一次（擺放對照）/ Night: smoke checks; GPU-vs-CPU placement check
- [ ] 5.4 夜間（約 3 晚）：全部候選的貪婪解碼評測與驗證 / Night (about 3 nights): greedy runs and verification for all candidates
- [ ] 5.5 夜間（約 2～3 晚）：取樣設定 / Night (about 2–3 nights): sampled setting
- [ ] 5.6 產生 E0 報表，交給使用者做 G1 判斷 / Produce the E0 report for the user's G1 decision

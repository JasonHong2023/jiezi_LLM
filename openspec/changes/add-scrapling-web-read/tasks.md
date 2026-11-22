## 1. 開關與可選相依 / Switch and optional dependency

- [x] 1.1 在 `.env.example` 與既有設定模組新增 `JIEZI_SCRAPLING_MCP`（預設 `false`）、allowlist、timeout 與 byte cap；開關關閉時不啟動任何行程。 / Add the opt-in switch and limits to `.env.example` and the settings module; no process starts when the switch is off.
  - 進度（2026-11-19 apply）：`.env.example` 已補五個變數與雙語說明；既有設定模組串接尚未完成，故此項未勾選。
  - 完成（18:15，R19.4，保留上方舊進度）：`src/jiezi/runtime/settings.py` 新增 `Settings.scrapling: PolicyConfig`、`_scrapling(env)`，`load_settings()` 回傳 `scrapling=_scrapling(env)`；空白 timeout／byte cap 用 15／1,000,000 預設，無效值拋 `JieziError`。延遲工廠在開關關閉時不建立 transport、不啟動行程。
- [x] 1.2 在 `pyproject.toml` 新增可選相依群組 `scrapling`，鎖定 `scrapling==0.5.1`、`anyio>=4.14.2`、`mcp>=2.2.0`；不加入預設安裝。 / Add an optional `scrapling` dependency group with fixed lower bounds; do not add it to the default install.
  - 完成（2026-11-19 apply）：另外新增 `web-fetch = ["httpx==0.28.1"]`；`[tool.uv] default-groups = ["dev"]` 不變。

## 2. 政策模組 / Policy module

- [x] 2.1 新增 `src/jiezi/tools/scrapling_policy.py`：實作公用 `http`/`https` URL 驗證、私人／loopback／link-local／內嵌憑證拒絕、allowlist 比對、回應大小與逾時上限、evasion 工具過濾。 / Add a single-file policy module for public URL checks, allowlist matching, response caps, and evasion filtering.
  - 完成（路徑偏差，R19.4）：因 `src/jiezi/tools.py` 是模組而非 package，實際檔案為 `src/jiezi/scrapling_policy.py`。
- [x] 2.2 新增 `tests/test_scrapling_policy.py`：覆蓋 loopback、私人 IP、內嵌憑證、非 HTTP scheme、未列工具、evasion 廣播、過大回應與逾時；測試不連網路。 / Add offline unit tests for all policy denial paths.
  - 完成（2026-11-19 apply）：34 tests OK。

## 3. Adapter 與工具註冊 / Adapter and tool registration

- [x] 3.1 新增 `src/jiezi/tools/scrapling_mcp.py`：stdio-only MCP adapter，只註冊通過政策的工具、過濾未列工具、稽核不記頁面內容。 / Add a stdio-only adapter that registers only policy-approved tools and audits without page content.
  - 完成（路徑偏差，R19.4）：實際檔案為 `src/jiezi/scrapling_mcp.py`。
- [x] 3.2 新增 `tests/test_scrapling_mcp.py`：mock MCP server，覆蓋開關關閉不註冊、明確啟用只註冊子集、未列工具忽略、注入字串通過既有 guard、稽核欄位完整；不啟動真實行程。 / Add mocked adapter tests with no real process or network.
  - 完成（2026-11-19 apply）：15 tests OK；與政策測試合計 49 tests OK。
- [x] 3.3 修改既有工具登錄入口（預計 `src/jiezi/tools/__init__.py` 或現有 registry）呼叫 adapter；開關關閉時 tool 數與 process 數皆為零。 / Wire the adapter into the existing tool registry; when disabled, both tool count and process count are zero.
  - 進行中：等待既有整合點盤點結果，再串接 registry／settings。
  - 完成（18:15，R19.4，保留上方舊進度）：既有 `src/jiezi/tools.py` 是模組、無 registry；依最小變更原則不改 `SCHEMAS`／`NAMES`，改由 `src/jiezi/runtime/gateway.py::_scrapling_page()` 以延遲工廠呼叫 adapter。開關關閉時 `policy=None` 直接回 `None`，不註冊工具、不建立 transport、不啟動行程；`tests/test_runtime_gateway.py::TestScraplingFallback` 4 tests 驗證。

## 4. 稽核與文件 / Audit and documentation

- [x] 4.1 確認稽核寫入器接受 `tool`、`host`、`decision`、`status`、`byte_count`、時間欄位且不寫入頁面本文；如需改動只限稽核模組與其測試。 / Ensure the audit writer accepts the new fields and never stores page bodies.
  - 進行中：adapter 已產生中繼資料欄位；audit writer 串接待整合。
  - 完成（18:15，R19.4，保留上方舊進度）：`src/jiezi/agent/audit.py::write()` 接受中繼資料 dict，既有 `read()` 仍會 `row.pop("content", None)`；adapter 只產 `tool`、`host`、`decision`、`status`、`byte_count`、`timestamp`、`backend`，gateway fallback 稽核另帶 `decision="fallback"`、`status="selected"`、`why`（截斷 200 字）。adapter mock 與 gateway fallback tests 驗證無頁面本文，未改稽核模組。
- [x] 4.2 更新 `docs/clients.md` 與 `docs/licenses.md`：啟用方式、僅限授權網站、移除條件、`BSD-3-Clause`、OSV／`pip-audit` 查證結果；不收簡體中文。 / Update user and license docs with enablement, authorized-site limits, removal, license, and scan results.
  - 完成（2026-11-19 apply）：文件已補雙語說明、授權站點限制、移除條件、授權登記與查證結果；本機無 `pip-audit`，已如實註記改用 PyPI／OSV／GHSA／NVD／CISA KEV，第三方稽核 17 項未全部查證故不作放行依據。新增內容使用繁體中文。

## 5. 隔離 PoC 量測（與實作分開） / Isolated PoC measurement

- [x] 5.1 在可拋棄 venv 安裝可選群組，執行 `pip-audit`、OSV query 與授權檢查；記錄任何未修復 High／Critical 並交使用者決策。 / Run dependency security and license checks in a disposable venv and report findings.
  - 完成（16:46）：`/tmp/opencode/scrapling-resolve` 裝 48 套件；`pip-audit 2.10.1` exit 0／`No known vulnerabilities found`；OSV querybatch 74 套件 0 hits；授權盤點已記於當日 #15，高等／臨界通報 0 項。
- [x] 5.2 只對授權練習站（`quotes.toscrape.com`、`books.toscrape.com`）做單次靜態抓取量測，記錄秒數、bytes 與 injection guard 結果；不測登入、CAPTCHA 或付費牆。 / Measure static fetching once on authorized practice sites only.
  - 完成（16:46）：`https://quotes.toscrape.com/`；web-fetch 1.13 秒／11,064 bytes，scrapling fallback 2.106 秒／3,261 bytes；兩者 `status=ok`，guard 移除 0 字元，稽核未記頁面本文。
- [x] 5.3 只有在設計文件 Open Question 獲使用者選擇「允許 stealth／JS」時，才對 Cloudflare challenge demo 做單次量測；未選擇則跳過並標記。 / Run the optional stealth/JS measurement only after explicit user choice.
   - 完成（16:52，R19.4）：使用者已選「也允許 stealth／JS」。未下載／安裝 browser；改用既有快取 `~/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`，只把 `--executable-path` 放在 MCP server 的 stdio 啟動命令，`browser_fetch_once` 的 arguments 仍只有 `url`：靜態頁 5.21 秒／3,261 bytes／3,218 chars；JS 頁 `https://quotes.toscrape.com/js/` 4.956 秒／1,811 bytes／1,768 chars，渲染出的 quote 存在，guard 移除 0 字元。Cloudflare 公開 demo `https://nopecha.com/demo/cloudflare` 單次量測 3.926 秒／571 bytes，回傳 HTTP 403 interstitial（`Performing security verification`）；**沒有**使用 `solve_cloudflare`、CAPTCHA 破解、登入或付費牆，也不視為成功繞過。稽核事件只記 tool、host、decision、status、byte_count、timestamp、backend，未記頁面本文。

## 6. 驗證與紀錄 / Verification and records

- [x] 6.1 執行 `openspec validate add-scrapling-web-read --strict`、`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests`、`GIT_MASTER=1 git diff --check`；全量測試不得少於 654 項。 / Run strict OpenSpec validation, the full unit suite, and the diff check.
  - 期中完成（16:24）：strict valid；`openspec validate --all --strict` 45 passed／0 failed；全量 703 tests OK（原 654 + 新增 49，74.862 秒；ResourceWarning 為既有）；`GIT_MASTER=1 git diff --check` 無輸出。整合與 PoC 後須重跑，見 6.2／T28。
- [x] 6.2 更新 `HANDOFF.md` 與當日討論記錄，回填 PoC 數據、資安結果、殘留風險與是否建議啟用；未經核准不 commit／push。 / Update handoff records with PoC data and residual risks; do not commit or push without approval.
   - 進度（16:24）：已回填 apply 進度、殘留風險與全域 80% 記錄規則；PoC 數據與最終建議待 T26 完成後補。
   - 進度（16:52，R19.4）：PoC 數據與資安結果已回填 5.1–5.3；最終「是否建議啟用」待既有系統串接與最終全量驗證後補。未 commit／push。
   - 16:53 更正（R19.4，保留上方 16:52 進度）：strict／all／diff check 已重跑且通過；既有系統串接尚未完成、最終全量 unittest 仍須重跑，故 6.2 保持未勾選、不建議正式啟用。
   - 完成（18:15，R19.4，保留上方舊進度）：`HANDOFF.md` §2–4 與當日 #17 回填整合完成、最終建議（不建議正式啟用、維持預設關閉）、Oracle 審查待收集；重跑 strict valid、all 45 passed／0 failed、全量 711 tests OK、diff check 無輸出。未 stage／commit／push。

## 7. R19.4 決策更新（2026-11-19 15:43；原任務保留，新增更正如下）

- [x] 7.1 在 `pyproject.toml` 同時宣告 `web-fetch` 與 `scrapling` 兩個可選相依群組；`web-fetch` 沿用既有 `httpx==0.28.1`，`scrapling` 含 `scrapling==0.5.1`、`anyio>=4.14.2`、`mcp>=2.2.0`；都不進預設安裝。 / Declare both optional groups; neither is installed by default.
- [x] 7.2 實作後端選擇與回退：`web-fetch` 首選；不可用或需政策核准的 JS／stealth 時才選 `scrapling`；政策、稽核與 R23.2 關卡不變。 / Implement backend selection and fallback without weakening policy or security gates.
  - 部分完成：adapter 內 `select_backend()` 與 mock 測試已做；既有 `webread` 串接待整合。
  - 完成（18:15，R19.4，保留上方舊進度）：`gateway.py::_read_urls()` 先呼叫 `webread.fetch()`；只有 `WebError` 才 `await anyio.to_thread.run_sync(self._scrapling_page, url, str(exc))`。成功 log 帶 `backend=Backend.SCRAPLING`、`fallback_from="web-fetch"`、`why`；失敗保留原錯誤且不阻斷回答。政策、注入清理、byte cap、allowlist 與 R23.2 關卡都在 adapter／policy 中維持不變。
- [x] 7.3 更新政策 allowlist：將通過檢查的 stealth／JS 工具納入 PoC；login state、CAPTCHA、paywall、proxy rotation 仍拒絕。 / Add policy-approved stealth/JS to the PoC allowlist while keeping evasion features blocked.
  - 完成：`browser_fetch_once` 受 `JIEZI_SCRAPLING_ALLOW_JS_STEALTH` 控制；evasion markers 永遠拒絕。
- [x] 7.4 更新 PoC 量測：靜態、`web-fetch` 失效回退、JS／stealth 與 Cloudflare challenge demo 都做單次量測；仍只打授權練習站。 / Measure static, fallback, JS/stealth, and challenge-demo paths once on authorized sites.
   - 完成（16:52，R19.4）：四類單次量測已做。靜態見 5.2；JS／stealth 與 challenge demo 見 5.3；`quotes.toscrape.com/js/` 的渲染結果含預期 quote。Cloudflare demo 回 HTTP 403 interstitial，如實記錄且未破解。只打授權練習站與使用者核准的公開 challenge demo；未碰登入、CAPTCHA 破解或付費牆。稽核只記中繼資料。
- [x] 7.5 若完整稽核仍有未解 High／Critical：受影響後端保持關閉，評估修補版／上游修正／替代合規 MCP／隔離 venv／既有 `add-web-read` 路徑，並回報使用者；不得 silent bypass R23.2，也不放棄抓取目標。 / Keep the fetch goal without bypassing R23.2; evaluate and report compliant alternatives.
   - 已做替代查證；第三方稽核尚未全部查證，後端仍維持預設關閉。
   - 更新（16:52，R19.4）：`pip-audit` 0 findings、OSV 74 套件 0 hits、R23.2 下限皆滿足；第三方稽核 17 項未全部查證，故仍不建議正式啟用，但不放棄抓取目標。
   - 完成（18:15，R19.4，保留上方舊進度）：查證後沒有已證實的未修補 High／Critical，但第三方稽核 17 項未全部查證，故後端維持預設關閉、不建議正式啟用。已評估修補版下限、上游修正、合規替代 MCP、隔離 venv 與既有 `add-web-read` 靜態路徑，並已回報使用者；未 silent bypass，也未放棄抓取目標。
- [x] 7.6 更新 `docs/clients.md`、`docs/licenses.md` 與紀錄文件，說明雙群組、回退順序、stealth／JS PoC 範圍與未解通報處理；重新執行 strict 驗證與 diff check。 / Update docs and records, then re-run strict validation and diff check.
   - 文件已更新；紀錄回填與重新驗證待完成。
   - 進度（16:52，R19.4）：文件、本 tasks、當日 #16 與 HANDOFF 已回填 PoC；整合與最終全量驗證後仍須重跑 strict／all／diff check 才能勾選。
   - 完成（16:53，R19.4，保留上方舊進度）：strict／all／diff check 已重跑且通過（valid／45 passed／無輸出）；最終全量 unittest 仍待既有系統串接完成後重跑，見 6.2／T28。

## 8. 2026-11-19 apply 進度註記（R19.4，保留原任務不覆蓋）

- 目標測試：`PYTHONPATH=src:tests .venv/bin/python -m unittest tests.test_scrapling_policy tests.test_scrapling_mcp -v` → 49 tests OK。
- 新增檔案：`src/jiezi/scrapling_policy.py`、`src/jiezi/scrapling_mcp.py`、`tests/test_scrapling_policy.py`、`tests/test_scrapling_mcp.py`。
- 修改檔案：`pyproject.toml`、`.env.example`、`docs/clients.md`、`docs/licenses.md`、本 `tasks.md`。
- 路徑偏差：`tools/` 原為模組，政策與 adapter 改放 `src/jiezi/` 根目錄，已於 2.1／3.1 註記。
- 尚未完成：既有 registry／settings／audit／injection／webread 串接、隔離 PoC、全量驗證、每日與交接紀錄最終回填。
- 補充驗證（16:24）：`StdioMcpTransport` 以假 MCP server 做真 subprocess／stdio 握手，`initialize` → `notifications/initialized` → `tools/list` → `tools/call` → `close` 實際可跑；結果 `TOOLS ('make_request', 'browser_fetch_once')`、`BODY fake:make_request`、`CLOSED True`。不連網路、不下載相依、不啟動 Scrapling，故不替代 5.1–5.3 真實 PoC；見當日 #14。
- 16:52 更正（R19.4，保留上方 16:24 舊註記）：真實 PoC 已補齊。未安裝 browser；stealth／JS 用既有 `chromium-1228` 可執行檔， `--executable-path` 只放在 MCP server 啟動命令，`browser_fetch_once` arguments 仍只有 `url`。`quotes.toscrape.com` 靜態 5.21 秒／3,261 bytes，`quotes.toscrape.com/js/` 4.956 秒／1,811 bytes 且渲染出預期 quote，guard 移除 0 字元；`nopecha.com/demo/cloudflare` 3.926 秒／571 bytes、HTTP 403 interstitial，未破解、不視為成功。稽核事件只記中繼資料，`backend=scrapling`。
- 目前狀態（16:52）：T26 已 closed；T24 背景整合點盤點仍 in_progress，收到通知前不輪詢、不重啟；T25／T28 仍 pending。未 stage／commit／push。
- 16:53 更正（R19.4，保留上方 16:52 狀態）：T28 已由 pending 改為 in_progress；strict／all／diff check 已重跑通過（valid／45 passed／無輸出），最終全量 unittest 仍待既有串接後重跑。T24 仍 in_progress、T25 仍 pending；未 stage／commit／push。
- 18:15 整合完成（R19.4，保留上方 16:53 舊註記）：既有整合已直接完成——`settings.py` 新增 `scrapling: PolicyConfig`；`gateway.py::_read_urls()` 先走 web-fetch，`WebError` 時才呼叫 `_scrapling_page()`；audit 只記中繼資料；`tests/test_runtime_gateway.py` 新增 4 個 fallback tests。T24 原背景盤點因 timeout 未回，已直接讀取已知檔案完成同等盤點，不重啟、不輪詢；T25 closed、T26 closed、T27 期中 closed；T28 待最終重跑。Oracle 審查 `bg_c0b723cb`／session `ses_e0cb80c48ffe6PhbfQLEGPgcwU` in_progress，收到通知前不輪詢、不重啟。未 stage／commit／push。
- 18:15 繁體檢查（R19.4）：以 `STPhrases.txt`＋`STCharacters.txt` 做 s2t 新增行比對，`ADDED_LINES=1975`、`CONVERT_HIT_LINES=89`；大部分是 OpenCC 一對多／台灣用法假陽性（`群`/`羣`、`稽核`/`稽覈`、`核准`/`覈准`、`占`/`佔`、`制面`/`製麪`、`才`/`纔`、`吃`/`喫`、`游`/`遊`、`只`/`隻`、`站台`/`站臺`）。唯一真簡體出現在 `proposal.md:46`，已改為繁體「查詢」；最終重掃見 18:20 紀錄。
- 18:15 最終建議（R19.4）：`pip-audit` 0 findings、OSV 74 套件 0 hits、R23.2 下限滿足，沒有已證實的未修補 High／Critical；但第三方稽核 17 項未全部查證、Cloudflare demo 未突破，故**不建議正式啟用**，後端維持預設關閉。抓取目標不放棄；可繼續用既有 `add-web-read` 靜態路徑，或在取得更多查證／核准後再決定是否啟用。未 stage／commit／push。
- 18:24 最終驗證與狀態（R19.4，保留上方 18:15 註記）：`openspec validate add-scrapling-web-read --strict` → valid；`openspec validate --all --strict` → 45 passed／0 failed；`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` → 711 tests in 72.839s、OK（ResourceWarning 為既有）；`GIT_MASTER=1 git diff --check` 無輸出。繁體重掃 `ADDED_LINES=1984`、`CONVERT_HIT_LINES=92`，mapping 只有 `准`/`準`、`制面`/`製麪`、`占`/`佔`、`只`/`隻`、`台`/`臺`、`吃`/`喫`、`才`/`纔`、`核`/`覈`、`核准`/`覈準`、`游`/`遊`、`群`/`羣` 等 OpenCC 一對多／台灣用法假陽性，沒有真簡體。T24 closed（原背景盤點 timeout，已直接盤點已知檔案，不重啟）、T25 closed、T26 closed、T27 final closed、T28 closed；T29 Oracle 審查 in_progress（收到通知前不輪詢、不重啟）。未 stage／commit／push。
- 18:30 回填後最終確認（R19.4，保留上方 18:24 註記）：文件回填完成後再跑 `openspec validate add-scrapling-web-read --strict` → valid、`openspec validate --all --strict` → 45 passed／0 failed、`PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests` → 711 tests in 72.529s、OK（ResourceWarning 為既有）、`GIT_MASTER=1 git diff --check` 無輸出。繁體 scan：`REPO_ADDED_LINES=1985`、`REPO_CONVERT_HIT_LINES=93`，mapping 仍只有 `准`/`準`、`制面`/`製麪`、`占`/`佔`、`只`/`隻`、`台`/`臺`、`吃`/`喫`、`才`/`纔`、`核`/`覈`、`核准`/`覈準`、`游`/`遊`、`群`/`羣` 等假陽性；HANDOFF／當日新增行標記檢查亦只有同類假陽性，沒有真簡體。工作樹 11 modified／7 untracked（其他 agent／change 的修改不混入）；T29 Oracle 審查仍 in_progress（不輪詢、不重啟）。未 stage／commit／push。
- 18:43 全部紀錄回填後最終驗證（R19.4，保留上方 18:30 註記）：strict valid、all 45 passed／0 failed、全量 unittest 711 tests in 72.433s OK、`GIT_MASTER=1 git diff --check` 無輸出，工作樹仍 11 modified／7 untracked。繁體 scan（本註記寫入前）以本輪腳本只計本 change 相關新增行：`OURS_ADDED_LINES=1988`、`OURS_CONVERT_HIT_LINES=94`、`OURS_UNKNOWN_HIT_LINES=0`，命中皆為既有 OpenCC 一對多／台灣用法假陽性；全工作樹 scan 為 `REPO_ADDED_LINES=2662`、`REPO_CONVERT_HIT_LINES=103`，其中 2 行真簡體（U+4F1A、U+7EDD）位於其他 agent 的 `openspec/changes/add-agent-contract/design.md` 與 `proposal.md`，非本 change、未修改。T29 Oracle 審查仍 in_progress（收到通知前不輪詢、不重啟）；未 stage／commit／push。
- 18:51 回填後最終確認（R19.4，保留上方 18:43 註記）：strict valid、all 45 passed／0 failed、全量 unittest 711 tests in 72.109s OK、`GIT_MASTER=1 git diff --check` 無輸出，工作樹仍 11 modified／7 untracked。繁體 scan（本註記寫入前）：本 change `OURS_ADDED_LINES=1989`／`OURS_CONVERT_HIT_LINES=95`／`OURS_UNKNOWN_HIT_LINES=0`；全工作樹 `REPO_ADDED_LINES=2663`／`REPO_CONVERT_HIT_LINES=104`，未知 2 行仍在其他 agent 的 `openspec/changes/add-agent-contract/design.md` 與 `proposal.md`（U+4F1A、U+7EDD），非本 change、未修改。HANDOFF／當日標記行掃描分別 12 行／2 命中與 4 行／1 命中，皆為已知假陽性。T29 Oracle 仍 in_progress（收到通知前不輪詢、不重啟）；未 stage／commit／push。
- 18:58 HANDOFF 回填後再確認（R19.4，保留上方 18:51 註記；僅紀錄回填，無 repo 程式／spec 更動）：strict valid、all 45 passed／0 failed、`GIT_MASTER=1 git diff --check` 無輸出，工作樹仍 11 modified／7 untracked；全量 unittest 711 tests in 73.464s OK（ResourceWarning 為既有）。繁體 scan（本註記寫入前）：本 change `OURS_ADDED_LINES=1990`／`OURS_CONVERT_HIT_LINES=95`／`OURS_UNKNOWN_HIT_LINES=0`；全工作樹 `REPO_ADDED_LINES=2664`／`REPO_CONVERT_HIT_LINES=104`，未知 2 行仍在其他 agent 的 add-agent-contract 兩檔（U+4F1A、U+7EDD），非本 change、未修改。HANDOFF／當日標記行掃描 15 行／2 命中與 5 行／1 命中，皆為已知假陽性。T29 Oracle 仍 in_progress（收到通知前不輪詢、不重啟）；未 stage／commit／push。
- 21:10 回填（R19.4，保留上方 18:58 註記）：Oracle `bg_c0b723cb`／session `ses_e0cb80c48ffe6PhbfQLEGPgcwU` 為 `Status: error`（無 findings），RESUME 與新 session 皆 timeout、`claude -p` 替代 failed；已直接唯讀審查 `scrapling_policy.py`／`scrapling_mcp.py`／`settings.py`／`gateway.py`／`webread.py`。結論無阻斷：off 不註冊工具／不建 process、web-fetch 首選且僅 `WebError` 單次 fallback、allowlist 空值拒絕全部、工具白名單＋evasion markers、byte cap／timeout／`injection.clean`、稽核只記中繼資料。4 項中低度殘留：(1) scrapling `validate_url()` 未做 DNS 解析後私人 IP 複查；(2) `PolicyConfig.from_env()` 無載入時正值驗證；(3) stdio 一行一個 JSON-RPC response 假設且 stderr 丟棄；(4) MCP 回應先全部接收再 byte cap。T21–T29 全數 closed（T29 為直接審查替代，Oracle 本身未回 findings）。21:08 重跑 strict valid、all 45 passed／0 failed、`GIT_MASTER=1 git diff --check` 無輸出；繁體 scan（本註記寫入前）本 change `OURS_ADDED_LINES=1991`／`OURS_CONVERT_HIT_LINES=95`／`OURS_UNKNOWN_HIT_LINES=0`，全工作樹 `REPO_ADDED_LINES=2665`／`REPO_CONVERT_HIT_LINES=104`／`UNKNOWN_HIT_LINES=2`（其他 agent 兩檔，未修改）。仍**不建議正式啟用**、後端維持預設關閉；抓取目標不放棄，可續用既有 `add-web-read` 靜態路徑。未 stage／commit／push。
- 21:12 回填後最終確認（R19.4，保留上方 21:10 註記）：回填後 strict valid、all 45 passed／0 failed、`GIT_MASTER=1 git diff --check` 無輸出，工作樹仍 11 modified／7 untracked。繁體 scan（本註記寫入前）本 change `OURS_ADDED_LINES=1992`／`OURS_CONVERT_HIT_LINES=96`／`OURS_UNKNOWN_HIT_LINES=0`，全工作樹 `REPO_ADDED_LINES=2666`／`REPO_CONVERT_HIT_LINES=105`／`UNKNOWN_HIT_LINES=2`（其他 agent 兩檔，未修改）。T21–T29 全數 closed；後端維持預設關閉、不建議正式啟用；未 stage／commit／push。
- 21:14 最終收尾確認（R19.4，保留上方 21:12 註記）：回填後 strict valid、all 45 passed／0 failed、`GIT_MASTER=1 git diff --check` 無輸出，工作樹仍 11 modified／7 untracked；scan（本註記寫入前）本 change `OURS_ADDED_LINES=1993`／`OURS_CONVERT_HIT_LINES=96`／`OURS_UNKNOWN_HIT_LINES=0`，全工作樹 `REPO_ADDED_LINES=2667`／`REPO_CONVERT_HIT_LINES=105`／`UNKNOWN_HIT_LINES=2`（其他 agent 兩檔未修改）。`.md` LSP 無 server 非檔案錯誤，temp scripts 已清理。本註記寫入後 strict／all／diff 再跑全過。T21–T29 全數 closed；後端維持預設關閉；未 stage／commit／push。

## 9. 2026-11-23 殘留 (3)(4) 修正 / Residual (3)(4) fixes

- [x] 9.1 修正 `StdioMcpTransport._read_line`：新增 `max_bytes` 參數，讀取時即檢查單行長度與累積總量，超過即拋 `BackendUnavailable`；舊碼只在事後用 `enforce_byte_cap` 截斷，大回應會先佔用大量記憶體。/ Fix `_read_line` to enforce per-line and cumulative byte limits during reading; old code only capped after full receipt.
- [x] 9.2 修正 `StdioMcpTransport._request_raw`：改為循環讀取並解析，略過 notification（無 id）、非 JSON 行、id mismatch 的回應，直到拿到預期 id 或逾時；舊碼假設 stdout 每行都是對應的 JSON-RPC response，遇到 notification 或 log 行會解析失敗或 id mismatch。/ Loop reading and parsing, skipping notifications, non-JSON lines, and id mismatches until expected id or timeout.
- [x] 9.3 在 `tests/test_scrapling_mcp.py` 新增 5 條離線單元測試（`StdioTransportResidual3Tests`、`StdioTransportResidual4Tests`），用假 MCP server 子行程驗證：notification 略過、非 JSON 行略過、id mismatch 略過、單行超限中止、累積超限中止；先確認舊碼紅燈，修正後綠燈。/ Add 5 offline unit tests with fake MCP subprocess verifying the fixes; confirmed red on old code, green after fix.
- [x] 9.4 全量 unittest 740 測試全過（原 735 + 新增 5）。/ Full suite 740 tests pass.
- [x] 9.5 修改檔案：`src/jiezi/scrapling_mcp.py`、`tests/test_scrapling_mcp.py`。/ Modified files.
- [x] 9.6 主控審查更正（2026-11-22，Claude Code；R19.4 保留上方 9.1–9.5 原文）：W1 版本有 4 個問題已修正——(a) 累計位元組數只在啟動行程時歸零，transport 重用後累計滿 1 MB 就永遠失敗 → 改為每個請求歸零；(b) 單行檢查發生在 `readline()` 已整行讀入之後，沒有真正限制記憶體 → `readline(剩餘額度+1)`；(c) 略過 notification 的迴圈沒有整體期限 → 單一 deadline；(d) 原始 stdio 上限等於內容上限，沒留 JSON 外框空間 → adapter 給 `max_bytes×2+64 KiB`，內容仍由 `enforce_byte_cap` 截斷。原「累積超限」測試是依 (a) 的錯誤語意寫的，已改為「略過行也計入同一請求上限」「上限按請求計」「無盡 notification 會逾時」「adapter 留外框空間」4 條；舊程式碼下 7 條失敗。9.4 的 740 為 W1 當時數字；9.5 漏列本檔。openspec CLI 實際已安裝（W1 環境 PATH 未含 nvm）。/ Reviewer fixes: per-request byte budget, bounded readline, overall deadline, envelope allowance; tests rewritten accordingly.

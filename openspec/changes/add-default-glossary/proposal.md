# add-default-glossary：中翻英內建台灣機關英文名 / Built-in English names of Taiwan agencies

## Why / 為什麼

2026-11-17 與 2026-11-25 兩次實測，著作權法第 2 條的「經濟部」都被本機核心譯成
Ministry of Economic Development（正式英文名為 Ministry of Economic Affairs）。機關、院、部會的英文名
是固定的專有名詞，模型猜錯時結構檢查（數字、長度、語言）抓不到。翻譯已支援使用者自備詞彙表
（`--glossary`），但使用者不會每次都準備。

Twice in live tests 經濟部 was translated as "Ministry of Economic Development". Agency names are fixed
proper nouns the structural checks cannot catch; a built-in glossary fixes them without the user supplying one.

## 分類、現成方案搜尋、資安掃描 / Classification, existing-solution search, security scan

**分類**：既有翻譯功能內的資料檔與合併邏輯，不是新的 SKILL 或 MCP（不新增工具、不新增連線）。
Classification: a data file plus merge logic inside the existing translator; neither a SKILL nor an MCP.

**現成方案**：
- 數位發展部「機關名錄雙語詞彙」（data.gov.tw 資料集 32084，CSV `https://www.gov.tw/govenorgan.csv`，
  政府資料開放授權條款第 1 版，可商用、須標示出處）。2026-11-25 下載檢查：100 筆，含「經濟部 → Ministry of
  Economic Affairs」，但資料集頁面寫明「因網站專區已下架，故不再更新」：
  - 停在 2023 年組織改造前（仍是行政院農業委員會、行政院環境保護署，沒有農業部、環境部、數位發展部、勞動部、
    衛生福利部）；
  - 有錯字與非正式寫法（Public Construction Commisssion、Ylan／E-Land County、Nation Audit Office、
    「The Legislative Yuan (Branch)」）。
  → 不能直接整份當預設詞表。
- 國家教育研究院「中央機關一般職稱雙語詞彙」（資料集 6320，同授權）：是職稱不是機關名，這次不用。

Existing: the MODA bilingual agency directory (data.gov.tw 32084, Open Government Data License 1.0) has the
right entry for 經濟部 but is no longer updated (pre-2023 reorganization) and contains typos, so it cannot be used
as-is.

**做法（2026-11-25 使用者同意實作）**：只收「總統府、五院、行政院所屬部會（2023 年改組後現行名稱）」約 40 筆，每筆以該機關英文官網
頁面查核，詞表檔每列附來源網址；資料集 32084 只當起點與交叉比對。之後要加地方政府、法院再逐筆查核。

Proposal: about 40 entries (Presidential Office, the five Yuan, current Executive Yuan ministries and councils),
each checked against the agency's own English website, with the source URL stored per row.

**資安掃描**：
- 只是一份隨 repo 發佈的 TSV 資料檔，執行時不連網、不下載、不執行任何外部程式碼。
- 唯一風險是詞表錯誤造成誤譯：每筆附來源網址、使用者的 `--glossary` 優先於內建詞表、可用 `--no-default-glossary` 關閉。
- 授權：自行查核整理，若引用資料集 32084 的內容，在 `docs/licenses.md` 標示來源（政府資料開放授權條款第 1 版要求標示）。
- 不含個人資料。

Security: a static TSV shipped with the repo; no network, no code execution. Wrong entries are the only risk:
each row carries its source, the user's glossary wins, and the built-in list can be turned off.

## What Changes / 變更內容

- 新增 `src/jiezi/data/tw-agencies.tsv`（中文、英文、來源網址；54 筆，含常用簡稱）。
- 整份文件中翻英時自動合併內建詞表（只取原文裡出現的詞，長詞先比；沿用既有提示與檢查）；使用者詞表同詞時以使用者為準。短文字的一般對話翻譯不套用（那條路徑的提示不帶詞表，只做檢查，套用會造成誤判）。
- CLI `--no-default-glossary`；HTTP 選項 `jiezi_translate.default_glossary: false`。
- 譯文結果的資訊欄列出這次套用了哪些內建詞。

## Non-Goals / 非目標

- 英翻中不套用（英文機關名翻回中文的需求較少，之後再看）。
- 不收地方機關、法院、學校、職稱。
- 不在執行時下載或更新資料集。

## Impact / 影響

- 程式：`src/jiezi/translate.py`、`src/jiezi/runtime/gateway.py`（選項）、CLI。
- 資料：`src/jiezi/data/tw-agencies.tsv`；`docs/licenses.md` 登記鍵 `tw-agency-names`。
- 測試：合併優先順序、關閉選項、只套用原文出現的詞、「經濟部」實例。

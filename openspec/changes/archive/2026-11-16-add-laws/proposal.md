## Why

使用者 2026-11-15 同意的第 4 項「更多開放資料」：台灣法律問題常見，小模型會編造條號與內容。全國法規資料庫是政府開放資料，法律條文不受著作權保護，可查詢也可訓練。
Small models invent statute numbers and text; the MOJ database is open and statutes are not copyrightable.

## What Changes

- `laws/manifest.toml`：data.gov.tw 資料集 18289 的官方分發檔（`sendlaw.moj.gov.tw`），鎖定 SHA-256 與資料日期；`scripts/jiezi laws build` 建 `var/laws/laws.sqlite`（1,351 部法律、47,377 條，約 7 秒）。
  Pinned official distribution; build in about 7 s.
- 條文查詢：問題指名現行法律（含簡稱：勞基法、個資法、刑法、道交條例…）與條號（阿拉伯或中文數字、「第 N 條之 M」）時附上原文；條號不存在時明說；只指名法律時在該法內全文找；沒指名但有法律用語時以嚴格門檻全文找；已廢止的法律不當作現行法。
  Article lookup with aliases and Chinese numerals; missing articles are stated; abolished laws are excluded.
- 回答後附【法規原文】、全國法規資料庫連結、資料日期與「不構成法律意見」聲明。
  Appended verbatim text, links, data date and a not-legal-advice note.
- `scripts/jiezi laws lookup`、`JIEZI_LAWS`（預設 on）。

## Non-Goals

- 命令（行政規則）資料檔、司法判決。/ Regulations and court decisions.
- 爬 law.moj.gov.tw（robots.txt 禁止）；只用平台公告的分發檔，每月最多下載一次。/ Crawling the site.

## Capabilities

### New Capabilities

- `laws`：法規查詢與引用。/ Law lookup and citation.

### Modified Capabilities

（無）/ (None)

## Impact

- 下載約 6 MB；資料庫約數十 MB；只用標準函式庫。

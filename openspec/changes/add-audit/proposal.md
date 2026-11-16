## Why

規則 R23 要求不用有重大未修補漏洞的技術，並在每個決策關卡複查；過去是人工查表（`stack.md`）。改成可重複執行的稽核，避免漏查。第一次執行就找到 `stack.md` 沒記錄的 3 則 bubblewrap 公告。
Rule R23 audits were manual; a repeatable audit found three bubblewrap advisories missing from stack.md on its first run.

## What Changes

- `scripts/jiezi audit`：以 OSV 查 `uv.lock` 的每個 PyPI 鎖定版本與 llama.cpp、bubblewrap 的鎖定 commit；另查兩者的 GitHub 安全公告（OSV 不一定收錄 llama.cpp 的 git 範圍）。只查詢、不安裝。
  OSV for PyPI pins and git commits, plus GitHub advisories for the source-built components; queries only.
- `security/accepted.toml`：已評估且有緩解或已修正的漏洞，每則要寫理由；清單以外的漏洞讓稽核以結束碼 1 失敗。
  Assessed vulnerabilities with reasons; anything else fails the audit.
- `stack.md` 資安表補記 bubblewrap 三則（R19.4 補記，不刪原文）。/ stack.md gains the bubblewrap rows.

## Non-Goals

- 系統套件（OpenSSL 等）的自動稽核：仍依 `stack.md` 人工查 Ubuntu OSV。/ System packages stay manual.
- 自動升級相依套件。/ Automatic upgrades.

## Capabilities

### New Capabilities

- `audit`：相依套件安全稽核。/ Dependency audit.

### Modified Capabilities

（無）/ (None)

## Impact

- 2026-11-16：23 個元件，llama.cpp 13 則與 bubblewrap 3 則公告皆已評估接受，未接受 0。

# audit Specification

## Purpose
TBD - created by archiving change add-audit. Update Purpose after archive.
## Requirements
### Requirement: Repeatable Dependency Audit

`scripts/jiezi audit` SHALL 查詢所有鎖定的 PyPI 套件與從原始碼建置元件的鎖定 commit 及其 GitHub 安全公告，SHALL 不安裝任何東西；不在 `security/accepted.toml`（每則附理由）中的漏洞 SHALL 讓稽核以非零結束碼失敗。
The audit SHALL query every pinned PyPI package and the source-built components' commits and GitHub advisories without installing anything; vulnerabilities not accepted with a reason SHALL fail it.

#### Scenario: 新公告 / A new advisory

- **WHEN** llama.cpp 出現一則不在已接受清單中的公告
  llama.cpp publishes an advisory not in the accepted list
- **THEN** 稽核失敗並在報告中標示「需處理」
  The audit fails and marks it for action


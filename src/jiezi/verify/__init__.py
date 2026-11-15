"""驗證器（規格 verifiers；add-verifiers design D1）：評測與之後的取樣共用。
Verifiers (spec verifiers; add-verifiers design D1), shared by evaluation and later sampling.

每個驗證器回傳 / Every verifier returns:
    {"status", "score", "details", "verifier": "<名稱>@<版本> / <name>@<version>"}"""

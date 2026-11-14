"""可攜性守門測試（規格：bootstrap / Portability Guard；規則 R6.13、R21.5、R23.1）。
Portability guard (spec: bootstrap / Portability Guard; rules R6.13, R21.5, R23.1).

比對值全部在執行時動態取得，本檔不寫死任何使用者名稱或 distro 名稱，
因此換到任何電腦都能執行（否則守門程式本身就違反 R6.13）。
Values to match are all obtained at run time; this file hardcodes no username
or distro name, so it works on any machine (otherwise the guard itself would violate R6.13).
"""

import getpass
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 常見金鑰樣式 / Common secret patterns
SECRET_PATTERNS = {
    "openai-style key": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    "google api key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "nvidia api key": re.compile(r"\bnvapi-[A-Za-z0-9_\-]{20,}"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


def versioned_files() -> list[Path]:
    """取得版控中的檔案；不在 git repo 中時回傳空清單。
    Return versioned files, or an empty list outside a git repo."""
    if shutil.which("git") is None:
        return []
    r = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, text=True
    )
    if r.returncode != 0:
        return []
    return [ROOT / p for p in r.stdout.split("\0") if p]


def read_text_or_none(path: Path) -> str | None:
    # 二進位檔或無法讀取的檔案略過 / Skip binary or unreadable files
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def machine_specific_needles() -> dict[str, re.Pattern]:
    """本機特有、不得出現在版控檔案中的字串 / Machine-specific strings that must not be versioned."""
    needles: dict[str, re.Pattern] = {}
    home = str(Path.home())
    if home not in ("/", "/root", ""):
        needles["home directory path"] = re.compile(re.escape(home) + r"(/|\b)")
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - 取不到使用者名稱時只略過這一項 / skip only this check
        user = ""
    if user and user not in ("root",) and len(user) >= 3:
        needles["username"] = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(user) + r"(?![A-Za-z0-9_])")
    distro = os.environ.get("WSL_DISTRO_NAME", "").strip()
    if distro:
        needles["WSL distro name"] = re.compile(re.escape(distro))
    return needles


class TestPortabilityGuard(unittest.TestCase):
    def setUp(self):
        self.files = versioned_files()
        if not self.files:
            self.skipTest("not a git checkout / 不是 git 工作目錄")

    def scan(self, patterns: dict[str, re.Pattern]) -> list[str]:
        findings = []
        for path in self.files:
            text = read_text_or_none(path)
            if text is None:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for label, pat in patterns.items():
                    if pat.search(line):
                        findings.append(f"{path.relative_to(ROOT)}:{lineno}: {label}")
        return findings

    def test_no_machine_specific_strings(self):
        findings = self.scan(machine_specific_needles())
        self.assertEqual(findings, [], "machine-specific strings found (R6.13, R21.5):\n" + "\n".join(findings))

    def test_no_secrets(self):
        findings = self.scan(SECRET_PATTERNS)
        self.assertEqual(findings, [], "likely secrets found (R6.4):\n" + "\n".join(findings))

    def test_no_php(self):
        php = [str(p.relative_to(ROOT)) for p in self.files if p.suffix.lower() == ".php"]
        self.assertEqual(php, [], "PHP is banned (R23.1)")


if __name__ == "__main__":
    unittest.main(verbosity=2)

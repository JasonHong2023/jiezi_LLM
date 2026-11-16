"""相依套件安全稽核（規則 R23）：查 OSV 資料庫，只查詢、不安裝。
Dependency security audit (rule R23): queries the OSV database; never installs anything.

- PyPI：`uv.lock` 鎖定的每個套件版本 / every package version pinned in uv.lock
- git：從原始碼建置的元件（llama.cpp、bubblewrap）的鎖定 commit / pinned commits of source-built components
- `security/accepted.toml`：已評估且有緩解措施的漏洞，必須寫理由；清單以外的漏洞讓稽核失敗。
  Assessed vulnerabilities with mitigations must carry a reason; anything else fails the audit."""

from __future__ import annotations

import json
import re
import tomllib
import urllib.request
from datetime import date
from pathlib import Path

OSV = "https://api.osv.dev/v1"
GIT_COMPONENTS = {"llama.cpp": "https://github.com/ggml-org/llama.cpp",
                  "bubblewrap": "https://github.com/containers/bubblewrap"}


def _post(url: str, body: dict, timeout: float = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "jiezi-audit"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def pypi_packages(root: Path) -> list[tuple[str, str]]:
    d = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    return sorted((p["name"], p["version"]) for p in d.get("package", []) if (p.get("source") or {}).get("registry"))


def git_pins(root: Path) -> dict[str, str]:
    """從 stack.md 讀鎖定的 commit。 / Pinned commits from stack.md."""
    text = (root / "openspec" / "specs" / "stack.md").read_text(encoding="utf-8")
    out = {}
    for name in GIT_COMPONENTS:
        m = re.search(rf"^\|.*?{re.escape(name)}.*?commit `([0-9a-f]{{40}})`", text, flags=re.M | re.I)
        if m:
            out[name] = m.group(1)
    return out


def _get(url: str, timeout: float = 60):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "jiezi-audit"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def github_advisories(get=_get) -> list[dict]:
    """GitHub 上的安全公告（OSV 不一定收錄 llama.cpp 的 git 範圍，所以另外查）。
    GitHub advisories, because OSV may not index llama.cpp's git ranges."""
    out = []
    for name, url in GIT_COMPONENTS.items():
        repo = url.removeprefix("https://github.com/")
        try:
            for a in get(f"https://api.github.com/repos/{repo}/security-advisories?per_page=100"):
                out.append({"component": name, "id": a["ghsa_id"], "severity": a.get("severity"),
                            "summary": (a.get("summary") or "")[:80]})
        except Exception as exc:  # noqa: BLE001 - 查不到就記下來 / record lookup failures
            out.append({"component": name, "id": f"lookup-failed:{type(exc).__name__}", "severity": None,
                        "summary": str(exc)[:80]})
    return out


def accepted(root: Path) -> dict[str, str]:
    p = root / "security" / "accepted.toml"
    if not p.exists():
        return {}
    return {a["id"]: a["reason"] for a in tomllib.loads(p.read_text(encoding="utf-8")).get("accepted", [])}


def query(root: Path, post=_post) -> list[dict]:
    """回傳 [{component, version, ids}]，只列有漏洞的。 / Components with vulnerabilities."""
    pk = pypi_packages(root)
    queries = [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in pk]
    pins = git_pins(root)
    queries += [{"commit": c} for c in pins.values()]
    res = post(f"{OSV}/querybatch", {"queries": queries}).get("results", [])
    labels = [f"{n}=={v}" for n, v in pk] + [f"{n}@{c[:12]}" for n, c in pins.items()]
    out = []
    for label, r in zip(labels, res):
        ids = sorted(v["id"] for v in (r or {}).get("vulns") or [])
        if ids:
            out.append({"component": label, "ids": ids})
    return out


def run(root: Path, post=_post, get=_get) -> tuple[Path, dict]:
    found = query(root, post)
    by_comp: dict[str, list[str]] = {}
    for a in github_advisories(get):
        by_comp.setdefault(f"{a['component']} (GitHub advisory)", []).append(a["id"])
    found += [{"component": c, "ids": sorted(ids)} for c, ids in by_comp.items()]
    ok = accepted(root)
    new = [{"component": f["component"], "ids": [i for i in f["ids"] if i not in ok]} for f in found]
    new = [f for f in new if f["ids"]]
    checked = len(pypi_packages(root)) + len(git_pins(root))
    md = [f"# 相依套件安全稽核 / Dependency audit（{date.today().isoformat()}）", "",
          f"- 檢查 {checked} 個元件（PyPI 鎖定版本＋llama.cpp、bubblewrap 的鎖定 commit），資料來源 OSV；"
          "llama.cpp、bubblewrap 另查 GitHub 安全公告。",
          f"- 有漏洞紀錄的元件：{len(found)}；未接受（需處理）：{len(new)}", ""]
    if found:
        md += ["| 元件 | 漏洞 | 狀態 |", "|---|---|---|"]
        for f in found:
            for i in f["ids"]:
                md.append(f"| {f['component']} | {i} | {'已接受：' + ok[i] if i in ok else '**需處理**'} |")
    out = root / "var" / "reports" / f"audit-{date.today().isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    return out, {"checked": checked, "with_vulns": len(found), "unaccepted": new}

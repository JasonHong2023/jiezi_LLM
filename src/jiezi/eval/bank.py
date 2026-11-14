"""題庫定義解析與授權閘門（規格 eval：Pinned Bank Sources、License Gate、Bank Composition；design D2、D3）。
Bank-definition parsing and the license gate (spec eval: Pinned Bank Sources, License Gate,
Bank Composition; design D2, D3)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from jiezi.config import project_root

from . import EvalError

TASKS = ("qa", "code", "summary", "tool")
GROUPS = ("knowledge", "reasoning")
SCORERS = ("multiple_choice", "simpleqa_approx", "pending_verifier")
MIN_PER_TASK = 50

_REGISTRY_ROW = re.compile(r"^\|\s*`([a-z0-9][a-z0-9._-]*)`\s*\|", re.M)
_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SourceFile:
    name: str
    url: str
    sha256: str


@dataclass(frozen=True)
class Source:
    key: str
    license_key: str
    task: str
    group: str
    scorer: str
    format: str
    count: int
    stratify: str | None = None
    files: tuple[SourceFile, ...] = ()
    options: dict = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class Bank:
    name: str
    version: int
    seed: int
    sources: tuple[Source, ...]


def registry_keys(licenses_md: Path) -> set[str]:
    """讀出 docs/licenses.md 主表的登記鍵（「已排除」表之前）。
    Read the registry keys from the main table of docs/licenses.md (before the "Excluded" table)."""
    text = licenses_md.read_text(encoding="utf-8")
    main = text.split("## 已排除", 1)[0]
    return set(_REGISTRY_ROW.findall(main))


def _require(entry: dict, keys: tuple[str, ...], where: str) -> None:
    missing = [k for k in keys if entry.get(k) in (None, "")]
    if missing:
        raise EvalError(f"{where}: missing {', '.join(missing)}")


def load_bank(path: Path | None = None, licenses_md: Path | None = None) -> Bank:
    """解析題庫定義；欄位不合法、授權未登記或題數不足時停止。
    Parse a bank definition; stop on invalid fields, unregistered licenses, or too few items."""
    root = project_root()
    path = path or root / "eval" / "banks" / "r0.toml"
    licenses_md = licenses_md or root / "docs" / "licenses.md"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise EvalError(f"{path}: {exc}") from exc
    _require(data, ("name", "version", "seed"), str(path))
    registered = registry_keys(licenses_md)

    sources = []
    seen = set()
    for i, s in enumerate(data.get("source") or []):
        where = f"{path}: source {s.get('key') or f'#{i + 1}'}"
        _require(s, ("key", "license_key", "task", "group", "scorer", "format", "count"), where)
        if s["key"] in seen:
            raise EvalError(f"{where}: duplicate key")
        seen.add(s["key"])
        for name, value, allowed in (("task", s["task"], TASKS), ("group", s["group"], GROUPS),
                                     ("scorer", s["scorer"], SCORERS)):
            if value not in allowed:
                raise EvalError(f"{where}: {name} must be one of {', '.join(allowed)}")
        if s["license_key"] not in registered:
            raise EvalError(f"{where}: license_key {s['license_key']!r} is not registered in {licenses_md} "
                            "(rule R18.3: register before downloading)")
        files = []
        for f in s.get("file") or []:
            _require(f, ("name", "url", "sha256"), f"{where} file")
            if not _SHA.match(f["sha256"]):
                raise EvalError(f"{where}: file {f['name']} has an invalid sha256")
            if not f["url"].startswith("https://"):
                raise EvalError(f"{where}: file {f['name']} must use https")
            files.append(SourceFile(f["name"], f["url"], f["sha256"]))
        known = {"key", "license_key", "task", "group", "scorer", "format", "count", "stratify", "file"}
        sources.append(Source(
            key=s["key"], license_key=s["license_key"], task=s["task"], group=s["group"],
            scorer=s["scorer"], format=s["format"], count=int(s["count"]), stratify=s.get("stratify"),
            files=tuple(files), options={k: v for k, v in s.items() if k not in known},
        ))
    if not sources:
        raise EvalError(f"{path}: no [[source]] entries")

    per_task = {t: sum(s.count for s in sources if s.task == t) for t in TASKS}
    short = [f"{t}={n}" for t, n in per_task.items() if n < MIN_PER_TASK]
    if short:
        raise EvalError(f"{path}: every task type needs at least {MIN_PER_TASK} items; short: {', '.join(short)}")
    return Bank(name=data["name"], version=int(data["version"]), seed=int(data["seed"]), sources=tuple(sources))

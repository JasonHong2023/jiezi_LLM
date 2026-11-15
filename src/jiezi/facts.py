"""最新的機器事實（`facts.json`）；評測與 runtime 共用（規則 R18.1）。
Fresh machine facts (`facts.json`), shared by evaluation and runtime (rule R18.1)."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .errors import JieziError

FACTS_MAX_AGE_S = 60  # 規則 R18.1 / rule R18.1


def fresh_facts(root: Path) -> dict:
    """facts.json 超過 60 秒就重新探測。 / Re-probe when facts.json is older than 60 s."""
    f = root / "facts.json"
    if not f.exists() or time.time() - f.stat().st_mtime > FACTS_MAX_AGE_S:
        p = subprocess.run([sys.executable, str(root / "scripts" / "hwprobe.py"), "--out", str(f)],
                           capture_output=True, text=True)
        if p.returncode != 0 or not f.exists():
            raise JieziError(f"hwprobe failed: {p.stderr.strip()}")
    return json.loads(f.read_text(encoding="utf-8"))

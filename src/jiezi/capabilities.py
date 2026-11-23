"""
Agent Capability Registry - Core module for loading, validating, and checking capabilities.

This module provides:
- load(): Load capabilities from TOML file
- validate(): Validate capability records against rules
- check_proposals(): Check proposal.md files for required sections
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = (
    "id",
    "name",
    "kind",
    "change",
    "existing_solutions",
    "security_scan",
    "version",
    "owner",
    "removal_condition",
    "status",
)

VALID_KINDS = {"skill", "mcp", "core"}
VALID_STATUSES = {"enabled", "disabled", "deprecated"}

# Regex to extract date and conclusion from security_scan
SECURITY_SCAN_PATTERN = re.compile(
    r"(\d{4}-\d{2}-\d{2})\s+(ok|issues)\b", re.IGNORECASE
)

# Keywords for proposal sections (case-insensitive)
PROPOSAL_SECTIONS = {
    "Classification": [r"分類", r"Classification"],
    "Existing-solution search": [r"現成方案", r"Existing[- ]solution"],
    "Security scan": [r"資安掃描", r"Security scan"],
}


def load(path: str | Path = "docs/capabilities.toml") -> list[dict[str, Any]]:
    """
    Load capabilities from a TOML file.

    Args:
        path: Path to the TOML file (default: "docs/capabilities.toml")

    Returns:
        List of capability records as dictionaries.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file contains invalid TOML.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Capabilities file not found: {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)

    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list):
        raise ValueError("Expected 'capabilities' to be a list of tables")

    return capabilities


def validate(capabilities: list[dict[str, Any]]) -> list[str]:
    """
    Validate a list of capability records.

    Args:
        capabilities: List of capability dictionaries from load().

    Returns:
        List of error messages. Empty list means all valid.
    """
    errors: list[str] = []
    seen_ids: set[str] = set()

    for idx, cap in enumerate(capabilities):
        cap_id = cap.get("id", f"<index {idx}>")

        # 1. Required fields
        for field in REQUIRED_FIELDS:
            if field not in cap or cap[field] is None:
                errors.append(f"capability '{cap_id}': missing required field '{field}'")

        # 2. Valid kind
        kind = cap.get("kind")
        if kind not in VALID_KINDS:
            errors.append(
                f"capability '{cap_id}': invalid kind '{kind}', must be one of {', '.join(sorted(VALID_KINDS))}"
            )

        # 3. Valid status
        status = cap.get("status")
        if status not in VALID_STATUSES:
            errors.append(
                f"capability '{cap_id}': invalid status '{status}', must be one of {', '.join(sorted(VALID_STATUSES))}"
            )

        # 4. existing_solutions not empty without reason
        existing = cap.get("existing_solutions", "")
        if isinstance(existing, str):
            stripped = existing.strip()
            if not stripped:
                errors.append(
                    f"capability '{cap_id}': existing_solutions is empty and no reason provided"
                )
            else:
                # Check if it contains a reason pattern when effectively empty
                lower = stripped.lower()
                if not lower or (lower in ("none", "n/a", "na") and "reason" not in lower):
                    # Only error if truly empty or "none" without reason
                    if lower in ("none", "n/a", "na"):
                        errors.append(
                            f"capability '{cap_id}': existing_solutions is empty and no reason provided"
                        )

        # 5. security_scan has date and conclusion
        security_scan = cap.get("security_scan", "")
        if isinstance(security_scan, str):
            match = SECURITY_SCAN_PATTERN.search(security_scan)
            if not match:
                errors.append(
                    f"capability '{cap_id}': security_scan must contain date (YYYY-MM-DD) and conclusion (ok/issues)"
                )
            else:
                conclusion = match.group(2).lower()
                # 6. status vs security_scan consistency
                if conclusion == "issues" and status == "enabled":
                    errors.append(
                        f"capability '{cap_id}': security_scan reports issues but status is enabled"
                    )

        # 7. Duplicate id check
        if cap_id in seen_ids:
            errors.append(f"duplicate capability id: {cap_id}")
        seen_ids.add(cap_id)

    return errors


def legacy_changes(path: str | Path) -> set[str]:
    """規則（2026-11-19）生效前就有的 change，不要求三段證據。 / Changes predating the rule are exempt."""
    with Path(path).open("rb") as f:
        return set(tomllib.load(f).get("legacy_changes", []))


def check_proposals(root: str | Path = "openspec/changes", skip: set[str] | frozenset = frozenset()) -> dict[str, list[str]]:
    """
    Check each change's proposal.md for required three sections.

    Args:
        root: Root directory containing change subdirectories (default: "openspec/changes").

    Returns:
        Dictionary mapping change name to list of missing section names.
        Only changes with missing sections are included.
    """
    root = Path(root)
    missing: dict[str, list[str]] = {}

    if not root.exists() or not root.is_dir():
        return missing

    for change_dir in root.iterdir():
        if not change_dir.is_dir():
            continue
        if change_dir.name == "archive" or change_dir.name in skip:
            continue

        proposal_path = change_dir / "proposal.md"
        if not proposal_path.exists():
            # No proposal.md - all three sections missing
            missing[change_dir.name] = ["Classification", "Existing-solution search", "Security scan"]
            continue

        content = proposal_path.read_text(encoding="utf-8")
        missing_sections = []

        for section_name, patterns in PROPOSAL_SECTIONS.items():
            found = False
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE | re.MULTILINE):
                    found = True
                    break
            if not found:
                missing_sections.append(section_name)

        if missing_sections:
            missing[change_dir.name] = missing_sections

    return missing



"""
CLI subcommand: jiezi capabilities check

Provides validation of the capabilities registry and proposal three-section check.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from jiezi.capabilities import check_proposals, legacy_changes, load, validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jiezi capabilities",
        description="Capabilities registry validation and proposal checking",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    check_parser = subparsers.add_parser(
        "check",
        help="Validate capabilities.toml and check proposals for required sections",
    )
    check_parser.add_argument(
        "--toml",
        default="docs/capabilities.toml",
        help="Path to capabilities.toml (default: docs/capabilities.toml)",
    )
    check_parser.add_argument(
        "--changes-root",
        default="openspec/changes",
        help="Root directory for changes (default: openspec/changes)",
    )
    check_parser.set_defaults(func=cmd_check)

    return parser


def cmd_check(args: argparse.Namespace) -> int:
    """Execute the check subcommand."""
    # Load and validate registry
    try:
        caps = load(args.toml)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error parsing TOML: {e}", file=sys.stderr)
        return 1

    errors = validate(caps)
    registry_ok = True
    if errors:
        print("Registry validation failed:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        registry_ok = False
    else:
        print("Registry validation: OK")

    # Check proposals
    missing = check_proposals(args.changes_root, legacy_changes(args.toml))
    proposals_ok = True
    if missing:
        print("Proposal three-section check failed:", file=sys.stderr)
        for change, sections in missing.items():
            print(f"  {change}: missing {', '.join(sections)}", file=sys.stderr)
        proposals_ok = False
    else:
        print("Proposal three-section check: OK")

    return 0 if (registry_ok and proposals_ok) else 1


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the capabilities CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
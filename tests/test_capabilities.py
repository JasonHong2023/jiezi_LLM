"""
Unit tests for jiezi.capabilities module.

Covers load(), validate(), check_proposals(), and CLI behavior.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from jiezi.capabilities import check_proposals, load, validate, legacy_changes


class TestLoad(unittest.TestCase):
    """Tests for load() function."""

    def test_load_valid_toml(self) -> None:
        """Loading a valid TOML returns list of capability records."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("""
[[capabilities]]
id = "test-cap"
name = "Test Capability"
kind = "core"
change = "add-test"
existing_solutions = "Some existing solution"
security_scan = "2026-11-20 ok (no issues)"
version = "1.0.0"
owner = "Tester"
removal_condition = "When no longer needed"
status = "enabled"
""")
            path = f.name

        try:
            caps = load(path)
            self.assertEqual(len(caps), 1)
            self.assertEqual(caps[0]["id"], "test-cap")
            self.assertEqual(caps[0]["kind"], "core")
        finally:
            Path(path).unlink()

    def test_load_missing_file_raises(self) -> None:
        """Loading a non-existent file raises FileNotFoundError."""
        with self.assertRaises(FileNotFoundError):
            load("nonexistent.toml")

    def test_load_invalid_toml_raises(self) -> None:
        """Loading invalid TOML raises ValueError."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("invalid toml [[[")
            path = f.name

        try:
            with self.assertRaises(ValueError):
                load(path)
        finally:
            Path(path).unlink()

    def test_load_missing_capabilities_key_returns_empty(self) -> None:
        """TOML without capabilities key returns empty list."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("other_key = 'value'")
            path = f.name

        try:
            caps = load(path)
            self.assertEqual(caps, [])
        finally:
            Path(path).unlink()


class TestValidate(unittest.TestCase):
    """Tests for validate() function."""

    def make_valid_cap(self, **overrides) -> dict:
        """Create a valid capability record with optional overrides."""
        base = {
            "id": "test-cap",
            "name": "Test Capability",
            "kind": "core",
            "change": "add-test",
            "existing_solutions": "Some existing solution with reason",
            "security_scan": "2026-11-20 ok (no issues)",
            "version": "1.0.0",
            "owner": "Tester",
            "removal_condition": "When no longer needed",
            "status": "enabled",
        }
        base.update(overrides)
        return base

    def test_valid_record_passes(self) -> None:
        """A fully valid record passes validation with no errors."""
        caps = [self.make_valid_cap()]
        errors = validate(caps)
        self.assertEqual(errors, [])

    def test_missing_required_field(self) -> None:
        """Missing any required field produces an error."""
        for field in ("id", "name", "kind", "change", "existing_solutions",
                      "security_scan", "version", "owner", "removal_condition", "status"):
            cap = self.make_valid_cap()
            del cap[field]
            errors = validate([cap])
            self.assertTrue(any(f"missing required field '{field}'" in e for e in errors),
                          f"Expected error for missing {field}, got: {errors}")

    def test_invalid_kind(self) -> None:
        """Invalid kind value produces an error."""
        cap = self.make_valid_cap(kind="plugin")
        errors = validate([cap])
        self.assertTrue(any("invalid kind 'plugin'" in e for e in errors))

    def test_valid_kinds(self) -> None:
        """All three valid kinds pass."""
        for kind in ("skill", "mcp", "core"):
            cap = self.make_valid_cap(kind=kind)
            errors = validate([cap])
            self.assertEqual(errors, [], f"kind={kind} should be valid")

    def test_invalid_status(self) -> None:
        """Invalid status value produces an error."""
        cap = self.make_valid_cap(status="active")
        errors = validate([cap])
        self.assertTrue(any("invalid status 'active'" in e for e in errors))

    def test_valid_statuses(self) -> None:
        """All three valid statuses pass."""
        for status in ("enabled", "disabled", "deprecated"):
            cap = self.make_valid_cap(status=status)
            errors = validate([cap])
            self.assertEqual(errors, [], f"status={status} should be valid")

    def test_empty_existing_solutions_without_reason(self) -> None:
        """Empty existing_solutions without reason produces error."""
        cap = self.make_valid_cap(existing_solutions="")
        errors = validate([cap])
        self.assertTrue(any("existing_solutions is empty and no reason provided" in e for e in errors))

    def test_existing_solutions_with_reason_passes(self) -> None:
        """existing_solutions with '無，理由：' or 'none, reason:' passes."""
        for sol in ("無，理由：沒有現成方案", "none, reason: no existing solution",
                    "None, Reason: custom reason"):
            cap = self.make_valid_cap(existing_solutions=sol)
            errors = validate([cap])
            self.assertEqual(errors, [], f"Should pass with: {sol}")

    def test_security_scan_missing_date_or_conclusion(self) -> None:
        """security_scan without proper date/conclusion format produces error."""
        for scan in ("no date here", "2026-11-20", "ok only", "issues only"):
            cap = self.make_valid_cap(security_scan=scan)
            errors = validate([cap])
            self.assertTrue(any("security_scan must contain date" in e for e in errors),
                          f"Should fail for: {scan}")

    def test_security_scan_ok_with_enabled_passes(self) -> None:
        """security_scan 'ok' with status 'enabled' passes."""
        cap = self.make_valid_cap(security_scan="2026-11-20 ok (all good)", status="enabled")
        errors = validate([cap])
        self.assertEqual(errors, [])

    def test_security_scan_issues_with_disabled_passes(self) -> None:
        """security_scan 'issues' with status 'disabled' passes."""
        cap = self.make_valid_cap(security_scan="2026-11-20 issues (critical)", status="disabled")
        errors = validate([cap])
        self.assertEqual(errors, [])

    def test_security_scan_issues_with_enabled_fails(self) -> None:
        """security_scan 'issues' with status 'enabled' produces error."""
        cap = self.make_valid_cap(security_scan="2026-11-20 issues (critical)", status="enabled")
        errors = validate([cap])
        self.assertTrue(any("security_scan reports issues but status is enabled" in e for e in errors))

    def test_duplicate_id(self) -> None:
        """Duplicate id across records produces error."""
        cap1 = self.make_valid_cap(id="dup")
        cap2 = self.make_valid_cap(id="dup")
        errors = validate([cap1, cap2])
        self.assertTrue(any("duplicate capability id: dup" in e for e in errors))

    def test_multiple_errors_reported(self) -> None:
        """Multiple validation errors are all reported."""
        cap = {
            "id": "bad",
            "name": "Bad",
            "kind": "invalid",
            "change": "x",
            "existing_solutions": "",
            "security_scan": "bad",
            "version": "1",
            "owner": "o",
            "removal_condition": "r",
            "status": "enabled",
        }
        errors = validate([cap])
        # Should have errors for: kind, existing_solutions, security_scan, status consistency
        self.assertGreaterEqual(len(errors), 3)


class TestCheckProposals(unittest.TestCase):
    """Tests for check_proposals() function."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_proposal(self, change_name: str, content: str) -> Path:
        """Write a proposal.md file for a change."""
        change_dir = self.temp_dir / change_name
        change_dir.mkdir(parents=True)
        proposal = change_dir / "proposal.md"
        proposal.write_text(content, encoding="utf-8")
        return proposal

    def test_complete_proposal_passes(self) -> None:
        """Proposal with all three sections passes (not in missing dict)."""
        content = """
# Proposal

## Classification
This is a core module.

## Existing-solution search
Found some existing solutions.

## Security scan
2026-11-20 ok (no issues)
"""
        self.write_proposal("add-test", content)
        missing = check_proposals(self.temp_dir)
        self.assertNotIn("add-test", missing)

    def test_missing_classification(self) -> None:
        """Proposal missing Classification section is reported."""
        content = """
## Existing-solution search
Found some.

## Security scan
2026-11-20 ok
"""
        self.write_proposal("add-test", content)
        missing = check_proposals(self.temp_dir)
        self.assertIn("add-test", missing)
        self.assertIn("Classification", missing["add-test"])

    def test_missing_existing_solution(self) -> None:
        """Proposal missing Existing-solution section is reported."""
        content = """
## Classification
Core module.

## Security scan
2026-11-20 ok
"""
        self.write_proposal("add-test", content)
        missing = check_proposals(self.temp_dir)
        self.assertIn("add-test", missing)
        self.assertIn("Existing-solution search", missing["add-test"])

    def test_missing_security_scan(self) -> None:
        """Proposal missing Security scan section is reported."""
        content = """
## Classification
Core module.

## Existing-solution search
Found some.
"""
        self.write_proposal("add-test", content)
        missing = check_proposals(self.temp_dir)
        self.assertIn("add-test", missing)
        self.assertIn("Security scan", missing["add-test"])

    def test_multiple_missing_sections(self) -> None:
        """Proposal missing multiple sections reports all."""
        content = "# Just a title"
        self.write_proposal("add-test", content)
        missing = check_proposals(self.temp_dir)
        self.assertIn("add-test", missing)
        self.assertEqual(len(missing["add-test"]), 3)

    def test_chinese_headers(self) -> None:
        """Chinese section headers are recognized."""
        content = """
## 分類
核心模組

## 現成方案搜尋
找到方案

## 資安掃描
2026-11-20 ok
"""
        self.write_proposal("add-test", content)
        missing = check_proposals(self.temp_dir)
        self.assertNotIn("add-test", missing)

    def test_inline_keywords(self) -> None:
        """Inline keywords (not headers) are recognized."""
        content = """
This proposal has 分類： core module.
Also 現成方案: found something.
And 資安掃描: 2026-11-20 ok.
"""
        self.write_proposal("add-test", content)
        missing = check_proposals(self.temp_dir)
        self.assertNotIn("add-test", missing)

    def test_archive_directory_skipped(self) -> None:
        """archive/ directory is not scanned."""
        archive_dir = self.temp_dir / "archive"
        archive_dir.mkdir()
        (archive_dir / "proposal.md").write_text("# No sections here", encoding="utf-8")

        # Also add a normal change
        self.write_proposal("add-normal", """
## Classification
Core

## Existing-solution search
Found

## Security scan
2026-11-20 ok
""")

        missing = check_proposals(self.temp_dir)
        self.assertNotIn("archive", missing)
        self.assertNotIn("add-normal", missing)

    def test_missing_proposal_file(self) -> None:
        """Change directory without proposal.md reports all three missing."""
        (self.temp_dir / "add-no-proposal").mkdir()
        missing = check_proposals(self.temp_dir)
        self.assertIn("add-no-proposal", missing)
        self.assertEqual(set(missing["add-no-proposal"]),
                        {"Classification", "Existing-solution search", "Security scan"})

    def test_non_directory_entries_ignored(self) -> None:
        """Files (not directories) in changes root are ignored."""
        (self.temp_dir / "not-a-dir.txt").write_text("hello", encoding="utf-8")
        self.write_proposal("add-test", """
## Classification
X
## Existing-solution search
Y
## Security scan
2026-11-20 ok
""")
        missing = check_proposals(self.temp_dir)
        self.assertNotIn("add-test", missing)


class TestCLI(unittest.TestCase):
    """Tests for CLI behavior via main()."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def write_toml(self, content: str) -> Path:
        toml = self.temp_dir / "capabilities.toml"
        toml.write_text(content, encoding="utf-8")
        return toml

    def write_proposal(self, change_name: str, content: str) -> None:
        change_dir = self.temp_dir / change_name
        change_dir.mkdir(parents=True)
        (change_dir / "proposal.md").write_text(content, encoding="utf-8")

    def test_cli_success(self) -> None:
        """CLI returns 0 when everything passes."""
        toml = self.write_toml("""
[[capabilities]]
id = "test"
name = "Test"
kind = "core"
change = "add-test"
existing_solutions = "Some solution"
security_scan = "2026-11-20 ok"
version = "1"
owner = "Me"
removal_condition = "Never"
status = "enabled"
""")
        self.write_proposal("add-test", """
## Classification
Core
## Existing-solution search
Found
## Security scan
2026-11-20 ok
""")

        from jiezi.cli.capabilities import main
        rc = main(["check", "--toml", str(toml), "--changes-root", str(self.temp_dir)])
        self.assertEqual(rc, 0)

    def test_cli_validation_failure(self) -> None:
        """CLI returns 1 when validation fails."""
        toml = self.write_toml("""
[[capabilities]]
id = "test"
name = "Test"
kind = "invalid"
change = "add-test"
existing_solutions = ""
security_scan = "bad"
version = "1"
owner = "Me"
removal_condition = "Never"
status = "enabled"
""")
        self.write_proposal("add-test", """
## Classification
Core
## Existing-solution search
Found
## Security scan
2026-11-20 ok
""")

        from jiezi.cli.capabilities import main
        rc = main(["check", "--toml", str(toml), "--changes-root", str(self.temp_dir)])
        self.assertEqual(rc, 1)

    def test_cli_proposal_failure(self) -> None:
        """CLI returns 1 when proposal check fails."""
        toml = self.write_toml("""
[[capabilities]]
id = "test"
name = "Test"
kind = "core"
change = "add-test"
existing_solutions = "Some solution"
security_scan = "2026-11-20 ok"
version = "1"
owner = "Me"
removal_condition = "Never"
status = "enabled"
""")
        self.write_proposal("add-test", "# Only title")

        from jiezi.cli.capabilities import main
        rc = main(["check", "--toml", str(toml), "--changes-root", str(self.temp_dir)])
        self.assertEqual(rc, 1)


ROOT = Path(__file__).resolve().parents[1]


class TestIntegrationWithRealFiles(unittest.TestCase):
    """Integration tests using the actual project files."""

    def test_real_capabilities_toml_loads(self) -> None:
        """The real docs/capabilities.toml loads without error."""
        caps = load(ROOT / "docs" / "capabilities.toml")
        self.assertGreaterEqual(len(caps), 5)  # At least the 5 pre-populated

    def test_real_capabilities_toml_validates(self) -> None:
        """The real docs/capabilities.toml passes validation."""
        caps = load(ROOT / "docs" / "capabilities.toml")
        errors = validate(caps)
        self.assertEqual(errors, [], f"Real capabilities.toml has validation errors: {errors}")

    def test_real_proposals_check(self) -> None:
        """Real proposals in openspec/changes/ are checked."""
        # 規則生效後的 change 都要有三段證據；舊的列在 legacy_changes / post-rule changes must pass
        missing = check_proposals(ROOT / "openspec" / "changes", legacy_changes(ROOT / "docs" / "capabilities.toml"))
        self.assertEqual(missing, {})


if __name__ == "__main__":
    unittest.main()
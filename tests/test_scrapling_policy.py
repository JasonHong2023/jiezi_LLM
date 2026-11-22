from __future__ import annotations

import unittest

from jiezi.scrapling_policy import (
    CappedContent,
    DenialReason,
    PolicyConfig,
    PolicyError,
    ToolStatus,
    classify_tool,
    clamp_timeout,
    enforce_byte_cap,
    filter_tools,
    is_allowed_host,
    is_public_host,
    validate_url,
)


class UrlPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = PolicyConfig(
            enabled=True,
            allowed_hosts=frozenset({"quotes.toscrape.com", "books.toscrape.com", ".example.org"}),
        )

    def assert_denied(self, url: str, reason: DenialReason, config: PolicyConfig | None = None) -> None:
        with self.assertRaises(PolicyError) as caught:
            validate_url(url, config or self.config)
        self.assertEqual(caught.exception.reason, reason)

    def test_disabled_by_default(self) -> None:
        self.assertFalse(PolicyConfig().enabled)
        self.assert_denied("https://quotes.toscrape.com/", DenialReason.DISABLED, PolicyConfig())

    def test_allows_exact_public_host(self) -> None:
        url = "https://quotes.toscrape.com/tag/humor/"
        self.assertEqual(validate_url(url, self.config), url)

    def test_allows_ipv4_literal_allowlisted(self) -> None:
        config = PolicyConfig(enabled=True, allowed_hosts=frozenset({"93.184.216.34"}))
        self.assertEqual(validate_url("http://93.184.216.34/", config), "http://93.184.216.34/")

    def test_allows_subdomain_when_allowlist_entry_has_leading_dot(self) -> None:
        self.assertEqual(
            validate_url("https://www.example.org/page", self.config),
            "https://www.example.org/page",
        )

    def test_leading_dot_entry_does_not_match_apex(self) -> None:
        self.assertFalse(is_allowed_host("example.org", frozenset({".example.org"})))

    def test_rejects_loopback_ipv4(self) -> None:
        self.assert_denied("http://127.0.0.1/", DenialReason.PRIVATE_ADDRESS)

    def test_rejects_loopback_ipv6(self) -> None:
        self.assert_denied("http://[::1]/", DenialReason.PRIVATE_ADDRESS)

    def test_rejects_private_ipv4(self) -> None:
        self.assert_denied("http://10.0.0.1/", DenialReason.PRIVATE_ADDRESS)

    def test_rejects_private_ipv6(self) -> None:
        self.assert_denied("http://[fd00::1]/", DenialReason.PRIVATE_ADDRESS)

    def test_rejects_link_local_ipv4(self) -> None:
        self.assert_denied("http://169.254.169.254/latest/meta-data/", DenialReason.PRIVATE_ADDRESS)

    def test_rejects_link_local_ipv6(self) -> None:
        self.assert_denied("http://[fe80::1]/", DenialReason.PRIVATE_ADDRESS)

    def test_rejects_reserved_ipv4(self) -> None:
        self.assert_denied("http://240.0.0.1/", DenialReason.PRIVATE_ADDRESS)

    def test_rejects_localhost_name(self) -> None:
        self.assert_denied("http://localhost/", DenialReason.LOCAL_NAME)

    def test_rejects_dot_local_name(self) -> None:
        self.assert_denied("http://printer.local/", DenialReason.LOCAL_NAME)

    def test_rejects_dot_internal_name(self) -> None:
        self.assert_denied("http://wiki.internal/", DenialReason.LOCAL_NAME)

    def test_rejects_credentials_in_url(self) -> None:
        self.assert_denied("http://user:pass@quotes.toscrape.com/", DenialReason.CREDENTIALS)

    def test_rejects_credentials_without_password(self) -> None:
        self.assert_denied("http://user@quotes.toscrape.com/", DenialReason.CREDENTIALS)

    def test_rejects_non_http_scheme(self) -> None:
        self.assert_denied("ftp://quotes.toscrape.com/", DenialReason.UNSAFE_SCHEME)

    def test_rejects_file_scheme(self) -> None:
        self.assert_denied("file:///etc/passwd", DenialReason.UNSAFE_SCHEME)

    def test_rejects_missing_host(self) -> None:
        self.assert_denied("http:///path", DenialReason.MISSING_HOST)

    def test_rejects_host_not_in_allowlist(self) -> None:
        self.assert_denied("https://example.com/", DenialReason.HOST_NOT_ALLOWED)

    def test_empty_allowlist_denies_every_host(self) -> None:
        config = PolicyConfig(enabled=True)
        self.assert_denied("https://quotes.toscrape.com/", DenialReason.HOST_NOT_ALLOWED, config)

    def test_public_host_helpers(self) -> None:
        self.assertTrue(is_public_host("quotes.toscrape.com."))
        self.assertFalse(is_public_host("127.0.0.1"))
        self.assertFalse(is_public_host("localhost"))


class ToolPolicyTests(unittest.TestCase):
    def test_filters_unlisted_tools(self) -> None:
        result = filter_tools(
            ["make_request", "browser_open", "list_sessions"],
            PolicyConfig(approved_tools=frozenset({"make_request"})),
        )
        self.assertEqual(result.approved, ("make_request",))
        self.assertEqual(result.filtered[0][1], ToolStatus.UNLISTED)
        self.assertEqual(result.filtered[1][1], ToolStatus.EVASION)

    def test_approves_stealth_only_when_enabled(self) -> None:
        disabled = PolicyConfig(approved_tools=frozenset({"make_request"}))
        enabled = PolicyConfig(
            allow_js_stealth=True,
            approved_tools=frozenset({"make_request", "browser_fetch_once"}),
        )
        self.assertEqual(classify_tool("browser_fetch_once", disabled), ToolStatus.UNLISTED)
        self.assertEqual(classify_tool("browser_fetch_once", enabled), ToolStatus.APPROVED)

    def test_rejects_evasion_tools_even_when_allow_js_is_true(self) -> None:
        config = PolicyConfig(
            allow_js_stealth=True,
            approved_tools=frozenset({"make_request", "browser_fetch_once"}),
        )
        names = (
            "browser_save_state",
            "browser_load_state",
            "open_request_session",
            "session_make_request",
            "browser_screenshot",
            "browser_evaluate",
            "browser_network_requests",
            "solve_captcha",
            "bypass_paywall",
            "rotate_proxy",
            "login_state_export",
            "bulk_get",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(classify_tool(name, config), ToolStatus.EVASION)

    def test_filter_reports_approved_and_filtered_in_order(self) -> None:
        result = filter_tools(
            ["browser_fetch_once", "make_request", "browser_open", "get"],
            PolicyConfig(
                allow_js_stealth=True,
                approved_tools=frozenset({"make_request", "browser_fetch_once"}),
            ),
        )
        self.assertEqual(result.approved, ("browser_fetch_once", "make_request"))
        self.assertEqual([name for name, _ in result.filtered], ["browser_open", "get"])


class LimitTests(unittest.TestCase):
    def test_clamp_timeout_to_cap(self) -> None:
        config = PolicyConfig(timeout_seconds=15.0)
        self.assertEqual(clamp_timeout(5.0, config), 5.0)
        self.assertEqual(clamp_timeout(30.0, config), 15.0)

    def test_reject_non_positive_timeout(self) -> None:
        with self.assertRaises(ValueError):
            clamp_timeout(0.0, PolicyConfig())

    def test_byte_cap_leaves_small_body_unchanged(self) -> None:
        result = enforce_byte_cap(b"abc", PolicyConfig(max_bytes=10))
        self.assertEqual(result, CappedContent(b"abc", False, 3))

    def test_byte_cap_truncates_large_body(self) -> None:
        result = enforce_byte_cap(b"abcdefgh", PolicyConfig(max_bytes=4))
        self.assertEqual(result, CappedContent(b"abcd", True, 4))

    def test_reject_negative_byte_cap(self) -> None:
        with self.assertRaises(ValueError):
            enforce_byte_cap(b"abc", PolicyConfig(max_bytes=-1))


class EnvConfigTests(unittest.TestCase):
    def test_from_env_defaults_to_disabled(self) -> None:
        config = PolicyConfig.from_env({})
        self.assertFalse(config.enabled)
        self.assertFalse(config.allow_js_stealth)
        self.assertEqual(config.approved_tools, frozenset({"make_request"}))
        self.assertEqual(config.timeout_seconds, 15.0)
        self.assertEqual(config.max_bytes, 1_000_000)

    def test_from_env_reads_opt_in_and_limits(self) -> None:
        config = PolicyConfig.from_env(
            {
                "JIEZI_SCRAPLING_MCP": "true",
                "JIEZI_SCRAPLING_ALLOWED_HOSTS": "quotes.toscrape.com, books.toscrape.com, .example.org",
                "JIEZI_SCRAPLING_TIMEOUT_SECONDS": "9.5",
                "JIEZI_SCRAPLING_MAX_BYTES": "2048",
                "JIEZI_SCRAPLING_ALLOW_JS_STEALTH": "yes",
            }
        )
        self.assertTrue(config.enabled)
        self.assertTrue(config.allow_js_stealth)
        self.assertEqual(
            config.allowed_hosts,
            frozenset({"quotes.toscrape.com", "books.toscrape.com", ".example.org"}),
        )
        self.assertEqual(config.timeout_seconds, 9.5)
        self.assertEqual(config.max_bytes, 2048)
        self.assertEqual(config.approved_tools, frozenset({"make_request", "browser_fetch_once"}))


if __name__ == "__main__":
    unittest.main()

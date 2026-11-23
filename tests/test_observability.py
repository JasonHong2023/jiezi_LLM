"""add-agent-observability 第 1 階段：統一欄位是讀取端檢視（不改原紀錄、不改寫入欄位），值域取自實際軌跡。"""

import copy
import unittest

from jiezi import observability as O


def traj(**kw):
    rec = {"id": "t1", "at": "2026-11-23T10:00:00+08:00", "policy": "jiezi", "status": "ok", "final_tier": 0,
           "training_use": None, "jiezi": {"model": "qwen3.5-4b", "latency_s": 1.2, "verification": "pass"},
           "tiers": [{"tier": 0, "answer": {"content": "x"}}]}
    rec.update(kw)
    return rec


class TestNormalizeTrajectory(unittest.TestCase):
    def test_plain_local_answer(self):
        out = O.normalize(traj(), "trajectory")
        self.assertEqual((out["trace_id"], out["tier"], out["terminal_state"], out["provider"], out["escalation_reason"]),
                         ("t1", 0, "completed", "local", "none"))
        self.assertFalse(out["fail_closed"])

    def test_original_record_untouched(self):
        rec = traj(tool_filter={"original": 178, "kept": 9, "stage": "full", "names": ["read"]})
        before = copy.deepcopy(rec)
        out = O.normalize(rec, "trajectory")
        self.assertEqual(rec, before)
        self.assertEqual(out["tool_filter"]["dropped"], 169)

    def test_real_status_values(self):
        for status, state in (("ok", "completed"), ("cancelled", "aborted"), ("client_disconnected", "aborted"),
                              ("engine_unavailable", "failed"), ("engine_error", "failed"),
                              ("consult_failed", "failed"), ("context_too_large", "failed")):
            with self.subTest(status=status):
                self.assertEqual(O.normalize(traj(status=status), "trajectory")["terminal_state"], state)
                self.assertIn(state, O.TERMINAL_STATES)

    def test_non_numeric_tiers_kept(self):
        for t in ("memory", "consult", "convert", 3):
            self.assertEqual(O.normalize(traj(final_tier=t), "trajectory")["tier"], t)

    def test_escalation_reasons_from_real_values(self):
        cases = {"context_too_large": "context_too_large", "needs_web": "needs_web",
                 "unsupported_claims": "verification_failed", "self_reported_unsure": "self_reported_unsure",
                 "engine_unavailable": "local_unavailable", "policy": "policy", "feedback": "verification_failed",
                 "not_retried_in_streaming": "other", "local_only_policy": "policy"}
        for raw, code in cases.items():
            with self.subTest(raw=raw):
                rec = traj(final_tier=3, tiers=[{"tier": 0}, {"tier": 3, "provider": "claude", "reason": raw}])
                out = O.normalize(rec, "trajectory")
                self.assertEqual((out["escalation_reason"], out["escalation_reason_raw"], out["provider"]),
                                 (code, raw, "claude"))
                self.assertIn(code, O.ESCALATION_REASONS)

    def test_agent_terminal_state_wins(self):
        out = O.normalize(traj(agent={"terminal_state": "cancelled"}), "trajectory")
        self.assertEqual(out["terminal_state"], "aborted")
        out = O.normalize(traj(agent={"terminal_state": "fail_closed", "terminal_reason": "budget_exceeded"}), "trajectory")
        self.assertEqual((out["terminal_state"], out["fail_closed"], out["fail_closed_reason"]),
                         ("fail_closed", True, "budget_exceeded"))

    def test_trust_and_old_records(self):
        out = O.normalize(traj(trust={"level": "unverified", "reason": "cloud"}), "trajectory")
        self.assertEqual(out["trust_level"], "unverified")
        self.assertEqual(O.normalize({}, "trajectory"), {"escalation_reason": "none", "fail_closed": False})
        self.assertEqual(O.normalize("not a dict", "trajectory"), {})
        with self.assertRaises(ValueError):
            O.normalize({}, "dashboard")


class TestOtherKinds(unittest.TestCase):
    def test_audit(self):
        row = {"at": "t", "source": "mcp", "tool": "write_file", "allowed": True, "approval_id": "a1",
               "outcome": "pending_approval", "trajectory_id": "t1"}
        out = O.normalize(row, "audit")
        self.assertEqual((out["tool_name"], out["outcome"], out["trace_id"]), ("write_file", "pending_approval", "t1"))

    def test_stats_reason_key(self):
        self.assertEqual(O.normalize("claude:needs_web", "stats_reason"),
                         {"provider": "claude", "escalation_reason": "needs_web", "escalation_reason_raw": "needs_web"})
        self.assertEqual(O.normalize("cloud:weird", "stats_reason")["escalation_reason"], "other")


class TestSummary(unittest.TestCase):
    def test_counts_only(self):
        recs = [traj(), traj(status="cancelled"),
                traj(final_tier=3, tiers=[{"tier": 0}, {"tier": 3, "provider": "cloud", "reason": "context_too_large"}],
                     tool_filter={"original": 100, "kept": 10, "stage": "exhausted", "names": ["bash"]},
                     trust={"level": "unverified", "reason": "cloud"}),
                traj(agent={"terminal_state": "fail_closed", "terminal_reason": "injection_detected"}),
                traj(policy="jiezi-local", jiezi={"escalation": "local_only_policy"})]          # 沒轉交 / not escalated
        recs[0]["tiers"][0]["answer"]["content"] = "答案內文不可外流"
        out = O.summary(recs)
        self.assertEqual(out["requests"], 5)
        self.assertEqual(out["terminal_states"], {"completed": 3, "aborted": 1, "fail_closed": 1})
        self.assertEqual((out["escalation_reasons"], out["escalated_to"]), ({"context_too_large": 1}, {"cloud": 1}))
        self.assertEqual(out["fail_closed"], {"injection_detected": 1})
        self.assertEqual(out["tool_filter"], {"requests": 1, "avg_original": 100.0, "avg_kept": 10.0})
        self.assertEqual(out["untrainable_reasons"], {"cloud": 1})
        self.assertNotIn("答案內文", str(out))                               # 沒有內容 / no content


class TestScrub(unittest.TestCase):
    def test_well_formed_secrets_redacted(self):
        fake = "sk-" + "a" * 24                                   # 執行時組字串 / built at run time
        pem = "-----BEGIN " + "RSA PRIVATE KEY-----\nabc\n-----END " + "RSA PRIVATE KEY-----"
        text = f"key {fake} and nvapi-{'b' * 24}\n{pem}"
        out = O.scrub_text(text)
        self.assertNotIn(fake, out)
        self.assertNotIn("abc", out)
        self.assertEqual(out.count(O.REDACTED), 3)

    def test_ordinary_text_kept(self):
        for text in ("os.environ['X']", "commit " + "a1b2c3d4e5" * 4, "sha256 " + "f" * 64, "/home/u/docs/a.txt"):
            self.assertEqual(O.scrub_text(text), text)

    def test_nested_and_non_strings(self):
        fake = "ghp_" + "c" * 36
        data = {"a": [fake, 3, None], "b": {"c": fake}}
        out = O.scrub(data)
        self.assertEqual(out, {"a": [O.REDACTED, 3, None], "b": {"c": O.REDACTED}})
        self.assertEqual(data["a"][0], fake)                        # 原物件不動 / original untouched


if __name__ == "__main__":
    unittest.main()

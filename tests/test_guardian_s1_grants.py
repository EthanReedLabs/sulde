"""S1 native grant diagnostics and recovery authority regression tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from decision_kernel import (grant_transaction_context, prepare_human_grant,
                             prepare_effect_risk_grant, claim_human_grant,
                             observe_grant_prompt)
from grant_broker import GrantBrokerError
from intent_guardian import (normalize_hook_event, GuardianSession, load_contract,
                             native_decision_context, execute_native_decision,
                             native_decision_description)
import intervention as effects
from intent_guardian_parts.policy import evaluate_event
from intent_guardian_parts.state import default_contract, write_contract


class GrantFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "intent.json"
        self.contract = default_contract(
            intent_id="s1-grants", objective="review exact writes",
            acceptance_criteria=["native card matches current operation"],
            workspace=self.root, mode="enforce",
            confirmed_by="human-readable-proposal-approval",
        )
        write_contract(self.path, self.contract)

    def event(self, suffix="one", session="session-one"):
        return normalize_hook_event({
            "client": "codex", "session_id": session,
            "cwd": str(self.root), "call_id": "call-" + suffix,
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://reviewed/" + suffix, "content": "v1"},
        }, phase="started", provider="codex")

    def prepare(self, suffix="one", session="session-one", at=None):
        event = self.event(suffix, session)
        return prepare_human_grant(
            self.path, self.contract, event, evaluate_event(self.contract, event),
            current_time=at,
        )

    def context(self, target="current"):
        return grant_transaction_context(
            self.path, target=target, provider="codex", session_id="session-one",
            task_epoch=self.contract["task_epoch"],
        )

class GrantContextDiagnosticsTests(GrantFixture, unittest.TestCase):
    def test_normal_exact_current_card(self):
        tx = self.prepare()
        self.assertEqual(self.context()["transaction_id"], tx["transaction_id"])

    def test_missing_card_is_not_reported_as_ambiguous(self):
        with self.assertRaisesRegex(GrantBrokerError, "grant_transaction_missing"):
            self.context()

    def test_two_current_cards_require_explicit_selection(self):
        first = self.prepare()
        self.prepare("two")
        with self.assertRaisesRegex(GrantBrokerError, "grant_transaction_ambiguous"):
            self.context()
        self.assertEqual(self.context(first["transaction_id"])["transaction_id"],
                         first["transaction_id"])

    def test_cross_session_card_is_not_current_authority(self):
        tx = self.prepare(session="other-session")
        with self.assertRaisesRegex(GrantBrokerError, "grant_transaction_identity_mismatch"):
            self.context(tx["transaction_id"])

    def test_expired_card_is_not_rendered_as_actionable(self):
        self.prepare(at=datetime.now(timezone.utc) - timedelta(hours=1))
        with self.assertRaisesRegex(GrantBrokerError, "grant_transaction_expired"):
            self.context()

    def test_expired_card_can_be_reprepared_without_reusing_old_authority(self):
        old = self.prepare(at=datetime.now(timezone.utc) - timedelta(hours=1))
        fresh = self.prepare()
        self.assertNotEqual(old["transaction_id"], fresh["transaction_id"])
        self.assertEqual(self.context()["transaction_id"], fresh["transaction_id"])


class RecoveryGrantJourneyTests(GrantFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from unittest import mock
        self.environment = mock.patch.dict("os.environ", {
            "SULDE_KB_HOME": str(self.root / "kb"), "SULDE_NOTIFY": "off",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def remote(self, call="new-call", remote_path="/opt/app"):
        command = ("ssh -F /dev/null -o BatchMode=yes -o PermitLocalCommand=no "
                   "-o StrictHostKeyChecking=yes -o UpdateHostKeys=no ops@192.0.2.10 "
                   f"'/bin/mkdir -p -- {remote_path}'")
        return normalize_hook_event({
            "client": "codex", "session_id": "session-one", "cwd": str(self.root),
            "call_id": call, "tool_name": "Bash", "tool_input": {"command": command},
        }, phase="started", provider="codex")

    def debt(self, suffix="old"):
        target = "[command:" + suffix + "]"
        attempt = effects.begin_attempt(
            self.path, intent_id="s1-grants", intent_revision=1,
            fingerprint="a" * 64, source_event_id=suffix, capability="tool:Bash",
            target=target, resource_key=effects.canonical_resource_key(target, kind="opaque"),
            resource_context={"schema": "exact", "value": target}, effect="external_write",
            provider="codex", session_id="historical", idempotency_key=suffix,
            verification_kind="unsupported",
        )
        effects.mark_attempt_result(self.path, attempt["attempt_id"], success=True)
        intervention = effects.mark_attempt_unknown(self.path, attempt["attempt_id"], reason="missing verifier")
        effects.resolve_intervention(self.path, intervention["intervention_id"],
                                     decision="abort", evidence="stop previous retry")
        return attempt["attempt_id"]

    def risk_question(self):
        event = self.remote("first-denied")
        session = GuardianSession(self.path, provider="codex", session_id="session-one", hot_path=True)
        denied = session.observe(event)
        self.assertEqual(denied.reason_code, "effect_barrier_denied", denied.reason)
        self.assertFalse(denied.awaiting_human)
        tx = prepare_effect_risk_grant(self.path, session.contract, event, denied)
        self.assertIsNotNone(tx)
        self.assertIn("历史效果", tx["spec"]["readable_card"])
        self.assertIsNone(prepare_human_grant(self.path, session.contract, event, denied))
        return tx

    def native(self, tx, outcome="allow"):
        context = native_decision_context(self.path, kind="grant", decision=outcome,
            target=tx["transaction_id"], provider="codex", session_id="session-one")
        description = native_decision_description(context)
        self.assertIn("历史效果", description)
        self.assertIn("unknown", description)
        self.assertIn("mkdir -p", description)
        observe_grant_prompt(self.path, tx)
        result = execute_native_decision(self.path, kind="grant", decision=outcome,
            target=context["target"], provider="codex", session_id="session-one")
        self.assertEqual(result["status"], "grant_recorded")

    def test_native_allow_executes_once_and_keeps_old_unknown(self):
        old = self.debt()
        historical = effects.event_store_path(self.path).read_bytes()
        tx = self.risk_question()
        self.native(tx)
        event = self.remote("accepted-call")
        dispatch = claim_human_grant(self.path, load_contract(self.path), event)
        self.assertIsNotNone(dispatch)
        decision = GuardianSession(self.path, provider="codex", session_id="session-one",
            hot_path=True).observe({**event, "human_grant_dispatch": dispatch})
        self.assertEqual(decision.action, "allow", decision.reason)
        self.assertTrue(decision.verification_required)
        self.assertEqual(effects.load_projection(self.path)["attempts"][old]["state"], "unknown")
        self.assertTrue(effects.event_store_path(self.path).read_bytes().startswith(historical))
        self.assertIsNone(claim_human_grant(self.path, load_contract(self.path), self.remote("third-call")))

    def test_deny_and_unanswered_card_do_not_authorize(self):
        self.debt()
        tx = self.risk_question()
        self.assertIsNone(claim_human_grant(self.path, load_contract(self.path), self.remote()))
        self.native(tx, "deny")
        self.assertIsNone(claim_human_grant(self.path, load_contract(self.path), self.remote()))

    def test_additional_debt_after_allow_invalidates_exact_review(self):
        self.debt()
        tx = self.risk_question()
        self.native(tx)
        self.debt("second")
        self.assertIsNone(claim_human_grant(self.path, load_contract(self.path), self.remote()))

    def test_explicit_write_deny_never_prepares_risk_exception(self):
        self.debt()
        contract = load_contract(self.path)
        contract["permissions"]["external_write"] = "deny"
        write_contract(self.path, contract)
        event = self.remote()
        session = GuardianSession(self.path, provider="codex", session_id="session-one", hot_path=True)
        denied = session.observe(event)
        self.assertIsNone(prepare_effect_risk_grant(self.path, session.contract, event, denied))

    def test_long_scope_cannot_hide_risk_or_target_in_native_prompt(self):
        self.debt()
        remote_path = "/" + "/".join(["x" * 200] * 8) + "/end"
        event = self.remote(remote_path=remote_path)
        session = GuardianSession(self.path, provider="codex", session_id="session-one", hot_path=True)
        denied = session.observe(event)
        tx = prepare_effect_risk_grant(self.path, session.contract, event, denied)
        self.assertIsNotNone(tx)
        for outcome in ("allow", "deny"):
            context = native_decision_context(self.path, kind="grant", decision=outcome,
                target=tx["transaction_id"], provider="codex", session_id="session-one")
            description = native_decision_description(context)
            self.assertIn(remote_path, description)
            self.assertIn("历史效果", description)
            self.assertIn("仍未验证", description)
            self.assertIn("独立验证", description)
            if outcome == "allow":
                self.assertIn("接受所述冲突风险", description)

    def test_actual_hook_process_risk_journey_without_remote_execution(self):
        # Actual Hook processes; the isolated native receipt is protocol evidence,
        # not a real user approval or an executed remote mkdir.
        old = self.debt()
        command = ("ssh -F /dev/null -o BatchMode=yes -o PermitLocalCommand=no "
                   "-o StrictHostKeyChecking=yes -o UpdateHostKeys=no ops@192.0.2.10 "
                   "'/bin/mkdir -p -- /opt/app'")
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("SULDE_", "CODEX_", "CLAUDE_"))}
        environment.update(SULDE_KB_HOME=str(self.root / "kb"),
                           SULDE_HOME=str(self.root / "home"), SULDE_NOTIFY="off",
                           PYTHONDONTWRITEBYTECODE="1")

        def hook(call):
            payload = {"client": "codex", "session_id": "session-one",
                       "cwd": str(self.root), "call_id": call,
                       "intent_contract": str(self.path), "tool_name": "Bash",
                       "tool_input": {"command": command}}
            result = subprocess.run([sys.executable, "-B", str(ROOT / "hooks/pre_tool_use.py")],
                input=json.dumps(payload), capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                cwd=self.root, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result

        first = hook("hook-denied")
        first_output = json.loads(first.stdout)["hookSpecificOutput"]
        self.assertEqual(first_output["permissionDecision"], "deny")
        self.assertIn("此动作需要一次当前会话确认", first_output["permissionDecisionReason"])
        tx = self.context()
        from grant_broker import transaction
        self.native(transaction(self.path, tx["transaction_id"]))
        second = hook("hook-allowed")
        self.assertEqual(second.stdout.strip(), "", second.stdout + second.stderr)
        projection = effects.load_projection(self.path)
        self.assertEqual(projection["attempts"][old]["state"], "unknown")
        new = [row for key, row in projection["attempts"].items() if key != old]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["state"], "dispatched")
        self.assertEqual(new[0]["effect"], "external_write")
        self.assertEqual(new[0]["verification_kind"], "unsupported")


if __name__ == "__main__":
    unittest.main()

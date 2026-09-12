from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from approval_timeout_policy import (  # noqa: E402
    ApprovalTimeoutPolicyError,
    agent_policy_eligibility,
    approval_deadlines,
    consume_human_decision,
    new_human_request,
    normalize_unattended_policy,
    parse_timestamp,
    pre_prompt_route,
    reassess_request,
    request_phase,
    timeout_disposition,
)


class MagicProbe:
    def __init__(self) -> None:
        self.calls = 0

    def _called(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("untrusted magic method was invoked")

    __str__ = _called
    __int__ = _called
    __float__ = _called
    __bool__ = _called
    __iter__ = _called
    __eq__ = _called
    __deepcopy__ = _called


class DictSubclass(dict):
    pass


class ListSubclass(list):
    pass


class ApprovalTimeoutPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.wall = datetime(2026, 8, 18, 5, 0, tzinfo=timezone.utc)
        self.monotonic = 10_000.0
        self.binding = {
            "card_sha256": "card-v1",
            "provider": "codex",
            "session_id": "session-a",
            "lane_sha256": "lane-a",
            "target_sha256": "target-a",
            "revision": 7,
            "journal_sha256": "journal-v1",
            "effect_sha256": "effect-v1",
            "world_state_sha256": "world-v1",
        }

    def request(self, **overrides: object) -> dict:
        value = new_human_request(
            request_id="apr-new",
            current_binding=self.binding,
            now=self.wall,
            monotonic_now=self.monotonic,
        )
        value.update(overrides)
        return value

    def decision(self, *, outcome: str = "allow", **overrides: object) -> dict:
        value = {
            "request_id": "apr-new",
            "receipt_id": "receipt-new",
            "outcome": outcome,
            **self.binding,
        }
        value.update(overrides)
        return value

    def legacy_request(self, **overrides: object) -> dict:
        value = {
            "request_id": "apr-legacy",
            "intent_id_sha256": "intent-a",
            "intent_revision": 7,
            "kind": "proposal",
            "target_sha256": "target-a",
            "card_sha256": "card-v1",
            "workspace_sha256": "workspace-a",
            "proposal_sha256": "proposal-a",
            "route": "human",
            "expires_at": (self.wall + timedelta(hours=24)).isoformat(),
            "reassess_at": (self.wall + timedelta(minutes=5)).isoformat(),
            "provider": "codex",
            "lane_sha256": "lane-a",
            "source": "proposal",
            "status": "asked",
            "outcome": None,
            "asked_at": self.wall.isoformat(),
            "decided_at": None,
            "decision_provider": None,
            "decision_lane_sha256": None,
            "receipt_sha256": None,
        }
        value.update(overrides)
        return value

    def test_deadlines_separate_five_minutes_from_twenty_four_hours(self) -> None:
        reassess_at, expires_at = approval_deadlines(now=self.wall)
        self.assertEqual(
            datetime.fromisoformat(reassess_at) - self.wall,
            timedelta(minutes=5),
        )
        self.assertEqual(
            datetime.fromisoformat(expires_at) - self.wall,
            timedelta(hours=24),
        )

    def test_five_minute_boundary_only_projects_reassessment(self) -> None:
        request = self.request()
        self.assertEqual(
            request_phase(
                request,
                now=self.wall + timedelta(seconds=299),
                monotonic_now=self.monotonic + 299,
            ),
            "fresh",
        )
        result = reassess_request(
            request,
            current_binding=self.binding,
            now=self.wall + timedelta(seconds=300),
            monotonic_now=self.monotonic + 300,
        )
        self.assertEqual(result["action"], "remind_and_wait")
        self.assertEqual(result["request"]["status"], "reassess_due")
        self.assertEqual(result["receipt_delta"], 0)
        self.assertFalse(result["request"]["execution_authorized"])

    def test_twenty_four_hour_boundary_is_the_real_expiry(self) -> None:
        request = self.request()
        valid = request_phase(
            request,
            now=self.wall + timedelta(hours=24) - timedelta(microseconds=1),
            monotonic_now=self.monotonic + 86_400 - 0.001,
        )
        expired = request_phase(
            request,
            now=self.wall + timedelta(hours=24),
            monotonic_now=self.monotonic + 86_400,
        )
        self.assertEqual(valid, "reassess_due")
        self.assertEqual(expired, "expired")

    def test_monotonic_clock_survives_wall_clock_rollback(self) -> None:
        request = self.request()
        result = reassess_request(
            request,
            current_binding=self.binding,
            now=self.wall - timedelta(hours=2),
            monotonic_now=self.monotonic + 300,
        )
        self.assertEqual(result["action"], "remind_and_wait")
        self.assertFalse(result["request"]["execution_authorized"])

    def test_forward_wall_drift_fails_closed_at_expiry(self) -> None:
        result = reassess_request(
            self.request(),
            current_binding=self.binding,
            now=self.wall + timedelta(days=2),
            monotonic_now=self.monotonic + 1,
        )
        self.assertEqual(result["action"], "expired")
        self.assertEqual(result["request"]["status"], "expired")

    def test_repeated_tick_is_idempotent_and_mints_no_receipt(self) -> None:
        first = reassess_request(
            self.request(),
            current_binding=self.binding,
            now=self.wall + timedelta(minutes=5),
            monotonic_now=self.monotonic + 300,
        )
        second = reassess_request(
            first["request"],
            current_binding=self.binding,
            now=self.wall + timedelta(minutes=6),
            monotonic_now=self.monotonic + 360,
        )
        self.assertEqual(first["request"]["reminder_count"], 1)
        self.assertEqual(second["request"]["reminder_count"], 1)
        self.assertEqual(second["request"]["receipts"], [])
        self.assertEqual(second["receipt_delta"], 0)

    def test_silence_never_creates_permission_or_transfers_authority(self) -> None:
        values = {
            "phase": "reassess_due",
            "kind": "proposal",
            "unattended_policy": "agent-if-eligible",
            "eligible": True,
            "world_current": True,
            "host_timeout_observed": True,
        }
        self.assertEqual(timeout_disposition(**values), "remind_and_wait")
        self.assertNotIn(
            timeout_disposition(**values), {"allow", "approved", "agent"}
        )

    def test_card_or_world_drift_cancels_and_requires_rerender(self) -> None:
        current = {**self.binding, "world_state_sha256": "world-v2"}
        result = reassess_request(
            self.request(),
            current_binding=current,
            now=self.wall + timedelta(minutes=5),
            monotonic_now=self.monotonic + 300,
        )
        self.assertEqual(result["action"], "cancel_and_rerender")
        self.assertEqual(result["request"]["status"], "superseded")
        self.assertTrue(result["request"]["rerender_required"])
        self.assertEqual(result["receipt_delta"], 0)

    def test_agent_gate_routes_complete_low_risk_action_before_prompt(self) -> None:
        action = {
            "kind": "local-edit",
            "contains_secret": False,
            "external_write": False,
            "incurs_cost": False,
            "reversible": True,
            "risk": "low",
            "evidence_complete": True,
            "allowlisted": True,
        }
        eligible, reasons = agent_policy_eligibility(action)
        route = pre_prompt_route(
            action,
            unattended_policy="agent-if-eligible",
            prompt_shown=False,
        )
        self.assertTrue(eligible)
        self.assertEqual(reasons, ())
        self.assertEqual(route["route"], "agent_before_prompt")
        self.assertFalse(route["execution_authorized"])

    def test_presented_prompt_can_never_be_transferred_to_agent(self) -> None:
        action = {
            "kind": "local-edit",
            "contains_secret": False,
            "external_write": False,
            "incurs_cost": False,
            "reversible": True,
            "risk": "low",
            "evidence_complete": True,
            "allowlisted": True,
        }
        route = pre_prompt_route(
            action,
            unattended_policy="agent-if-eligible",
            prompt_shown=True,
        )
        self.assertEqual(route["route"], "human")
        self.assertEqual(route["decision_owner"], "human")

    def test_wait_policy_is_always_human_owned(self) -> None:
        action = {
            "kind": "local-edit",
            "contains_secret": False,
            "external_write": False,
            "incurs_cost": False,
            "reversible": True,
            "risk": "low",
            "evidence_complete": True,
            "allowlisted": True,
        }
        route = pre_prompt_route(
            action,
            unattended_policy="wait",
            prompt_shown=False,
        )
        self.assertEqual(route["route"], "human")
        self.assertEqual(route["decision_owner"], "human")

    def test_high_impact_unknown_or_incomplete_actions_fail_agent_gate(self) -> None:
        base = {
            "kind": "local-edit",
            "contains_secret": False,
            "external_write": False,
            "incurs_cost": False,
            "reversible": True,
            "risk": "low",
            "evidence_complete": True,
            "allowlisted": True,
        }
        changes = (
            {"kind": "install"},
            {"kind": "publish"},
            {"kind": "delete"},
            {"kind": "credential"},
            {"kind": "credentials"},
            {"kind": "payment"},
            {"kind": "permission-change"},
            {"kind": "permission_change"},
            {"reversible": False},
            {"risk": "high"},
            {"evidence_complete": False},
            {"allowlisted": False},
            {"contains_secret": True},
            {"external_write": True},
            {"incurs_cost": True},
        )
        for changed in changes:
            with self.subTest(changed=changed):
                eligible, reasons = agent_policy_eligibility(
                    {**base, **changed}
                )
                self.assertFalse(eligible)
                self.assertTrue(reasons)

    def test_unknown_policy_fails_closed_to_human(self) -> None:
        with self.assertRaises(ApprovalTimeoutPolicyError):
            normalize_unattended_policy("approve-on-timeout")
        route = pre_prompt_route(
            {}, unattended_policy="mystery", prompt_shown=False
        )
        self.assertEqual(route["route"], "human")
        self.assertIn("policy_unknown", route["ineligible_reasons"])

    def test_f05_005_none_uses_only_a_valid_exact_default(self) -> None:
        self.assertEqual(
            normalize_unattended_policy(None, default="wait"),
            "wait",
        )
        for value in (False, 0, [], {}, MagicProbe()):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    normalize_unattended_policy(value, default="wait")
        for default in (None, False, "approve-on-timeout", " WAIT "):
            with self.subTest(default=default):
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    normalize_unattended_policy(None, default=default)

    def test_f05_005_exact_legacy_projection_is_timing_only(self) -> None:
        row = self.legacy_request()
        before = repr(row)
        self.assertEqual(
            request_phase(row, now=self.wall + timedelta(minutes=4)),
            "fresh",
        )
        self.assertEqual(
            request_phase(row, now=self.wall + timedelta(minutes=5)),
            "reassess_due",
        )
        self.assertEqual(
            request_phase(row, now=self.wall + timedelta(hours=24)),
            "expired",
        )
        self.assertEqual(repr(row), before)

        for malformed in (
            {**row, "extra_authority": True},
            {key: value for key, value in row.items() if key != "request_id"},
            {**row, "request_id": 7},
            {**row, "reassess_at": 7},
        ):
            with self.subTest(keys=sorted(malformed)):
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    request_phase(malformed, now=self.wall)

    def test_f05_006_late_allow_or_deny_is_only_a_pending_cas_plan(self) -> None:
        for outcome in ("allow", "deny"):
            with self.subTest(outcome=outcome):
                request = self.request()
                decision = self.decision(outcome=outcome)
                request_before = repr(request)
                decision_before = repr(decision)
                result = consume_human_decision(
                    request,
                    decision,
                    current_binding=self.binding,
                    authoritative_request=request,
                    pending_plan=None,
                    now=self.wall + timedelta(hours=23),
                    monotonic_now=self.monotonic + 82_800,
                )
                self.assertEqual(result["type"], "validated_pending_cas")
                self.assertEqual(result["status"], "validated_pending_cas")
                self.assertEqual(result["outcome"], outcome)
                self.assertTrue(result["authoritative_cas_required"])
                self.assertFalse(result["execution_authorized"])
                self.assertFalse(result["execute_once"])
                self.assertEqual(result["receipt_delta"], 0)
                self.assertEqual(repr(request), request_before)
                self.assertEqual(repr(decision), decision_before)

    def test_f05_006_replay_stale_and_different_receipt_get_no_second_plan(self) -> None:
        request = self.request()
        first = consume_human_decision(
            request,
            self.decision(),
            current_binding=self.binding,
            authoritative_request=request,
            pending_plan=None,
            now=self.wall + timedelta(minutes=6),
            monotonic_now=self.monotonic + 360,
        )
        stale_authoritative = self.request(
            status="decided",
            outcome="allow",
            receipts=[
                {
                    "receipt_id": "receipt-new",
                    "request_id": "apr-new",
                    "outcome": "allow",
                }
            ],
        )
        cases = (
            ("repeated", self.decision(), request, first),
            (
                "different-receipt",
                self.decision(receipt_id="receipt-other"),
                request,
                first,
            ),
            ("stale-copy", self.decision(), stale_authoritative, None),
        )
        for label, decision, authoritative, pending in cases:
            with self.subTest(label=label):
                request_before = repr(request)
                decision_before = repr(decision)
                authoritative_before = repr(authoritative)
                pending_before = repr(pending)
                result = consume_human_decision(
                    request,
                    decision,
                    current_binding=self.binding,
                    authoritative_request=authoritative,
                    pending_plan=pending,
                    now=self.wall + timedelta(minutes=6),
                    monotonic_now=self.monotonic + 360,
                )
                self.assertEqual(result["type"], "decision_rejected")
                self.assertFalse(result["authoritative_cas_required"])
                self.assertFalse(result["execution_authorized"])
                self.assertFalse(result["execute_once"])
                self.assertEqual(result["receipt_delta"], 0)
                self.assertEqual(repr(request), request_before)
                self.assertEqual(repr(decision), decision_before)
                self.assertEqual(repr(authoritative), authoritative_before)
                self.assertEqual(repr(pending), pending_before)

    def test_f05_006_existing_receipt_or_terminal_outcome_gets_no_plan(self) -> None:
        receipt = {
            "receipt_id": "receipt-old",
            "request_id": "apr-new",
            "outcome": "deny",
        }
        cases = (
            self.request(receipts=[receipt]),
            self.request(status="decided", outcome="deny", receipts=[receipt]),
            self.request(status="cancelled"),
            self.request(status="superseded"),
            self.request(status="expired"),
            self.request(outcome="allow"),
        )
        for request in cases:
            with self.subTest(status=request["status"], outcome=request.get("outcome")):
                before = repr(request)
                result = consume_human_decision(
                    request,
                    self.decision(),
                    current_binding=self.binding,
                    authoritative_request=request,
                    pending_plan=None,
                    now=self.wall + timedelta(minutes=6),
                    monotonic_now=self.monotonic + 360,
                )
                self.assertEqual(result["type"], "decision_rejected")
                self.assertFalse(result["execute_once"])
                self.assertEqual(result["receipt_delta"], 0)
                self.assertEqual(repr(request), before)

    def test_expired_late_decision_is_rejected(self) -> None:
        result = consume_human_decision(
            self.request(),
            self.decision(),
            current_binding=self.binding,
            now=self.wall + timedelta(hours=24),
            monotonic_now=self.monotonic + 86_400,
        )
        self.assertEqual(result["status"], "approval_expired")
        self.assertFalse(result["execute_once"])
        self.assertEqual(result["receipt_delta"], 0)

    def test_old_request_receipt_cannot_authorize_new_request(self) -> None:
        result = consume_human_decision(
            self.request(),
            self.decision(request_id="apr-old", receipt_id="receipt-old"),
            current_binding=self.binding,
            now=self.wall + timedelta(minutes=6),
            monotonic_now=self.monotonic + 360,
        )
        self.assertEqual(result["status"], "cas_mismatch")
        self.assertEqual(result["cas_mismatches"], ("request_id",))
        self.assertFalse(result["execute_once"])

    def test_cross_session_or_provider_receipt_fails_cas(self) -> None:
        for changed in (
            {"session_id": "session-b"},
            {"provider": "claude"},
        ):
            with self.subTest(changed=changed):
                result = consume_human_decision(
                    self.request(),
                    self.decision(**changed),
                    current_binding=self.binding,
                    now=self.wall + timedelta(minutes=6),
                    monotonic_now=self.monotonic + 360,
                )
                self.assertEqual(result["status"], "cas_mismatch")
                self.assertFalse(result["execute_once"])

    def test_task_journal_effect_or_world_drift_fails_cas(self) -> None:
        for field in (
            "card_sha256",
            "lane_sha256",
            "target_sha256",
            "revision",
            "journal_sha256",
            "effect_sha256",
            "world_state_sha256",
        ):
            with self.subTest(field=field):
                changed = 8 if field == "revision" else f"changed-{field}"
                current = {**self.binding, field: changed}
                result = consume_human_decision(
                    self.request(),
                    self.decision(),
                    current_binding=current,
                    now=self.wall + timedelta(minutes=6),
                    monotonic_now=self.monotonic + 360,
                )
                self.assertEqual(result["status"], "cas_mismatch")
                self.assertIn(f"current.{field}", result["cas_mismatches"])
                self.assertFalse(result["execute_once"])

    def test_agent_before_prompt_completion_rejects_late_human_decision(self) -> None:
        request = self.request(status="agent_decided", prompt_shown=False)
        result = consume_human_decision(
            request,
            self.decision(),
            current_binding=self.binding,
            now=self.wall + timedelta(minutes=6),
            monotonic_now=self.monotonic + 360,
        )
        self.assertEqual(result["status"], "already_agent_decided")
        self.assertFalse(result["execute_once"])

    def test_f05_007_only_exact_displayed_human_open_state_gets_a_plan(self) -> None:
        contradictions = (
            self.request(prompt_shown=False),
            self.request(prompt_shown=1),
            self.request(decision_owner="agent"),
            self.request(decision_owner="Human"),
            self.request(status="agent_decided", prompt_shown=False),
            self.request(status="decided", outcome="allow"),
            self.request(status="mystery"),
            self.request(outcome="deny"),
            self.request(execution_authorized=True),
        )
        for request in contradictions:
            with self.subTest(
                status=request["status"],
                owner=request["decision_owner"],
                prompt=request["prompt_shown"],
            ):
                before = repr(request)
                result = consume_human_decision(
                    request,
                    self.decision(),
                    current_binding=self.binding,
                    authoritative_request=request,
                    pending_plan=None,
                    now=self.wall + timedelta(minutes=6),
                    monotonic_now=self.monotonic + 360,
                )
                self.assertEqual(result["type"], "decision_rejected")
                self.assertFalse(result["authoritative_cas_required"])
                self.assertFalse(result["execution_authorized"])
                self.assertFalse(result["execute_once"])
                self.assertEqual(result["receipt_delta"], 0)
                self.assertEqual(repr(request), before)

        for malformed in (
            self.request(binding={**self.binding, "card_sha256": ""}),
            self.request(binding={key: value for key, value in self.binding.items() if key != "card_sha256"}),
        ):
            with self.subTest(binding=malformed["binding"]):
                before = repr(malformed)
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    consume_human_decision(
                        malformed,
                        self.decision(),
                        current_binding=self.binding,
                        authoritative_request=malformed,
                        pending_plan=None,
                        now=self.wall + timedelta(minutes=6),
                        monotonic_now=self.monotonic + 360,
                    )
                self.assertEqual(repr(malformed), before)

    def test_replacement_requires_terminal_predecessor_and_fresh_binding(self) -> None:
        previous = self.request(request_id="apr-old", status="expired")
        with self.assertRaises(ApprovalTimeoutPolicyError):
            new_human_request(
                request_id="apr-old",
                current_binding={**self.binding, "card_sha256": "card-v2"},
                now=self.wall,
                monotonic_now=self.monotonic,
                previous=previous,
            )
        with self.assertRaises(ApprovalTimeoutPolicyError):
            new_human_request(
                request_id="apr-new-2",
                current_binding=self.binding,
                now=self.wall,
                monotonic_now=self.monotonic,
                previous=previous,
            )

        replacement = new_human_request(
            request_id="apr-new-2",
            current_binding={**self.binding, "card_sha256": "card-v2"},
            now=self.wall,
            monotonic_now=self.monotonic,
            previous=previous,
        )
        self.assertEqual(replacement["status"], "asked")
        self.assertEqual(replacement["request_id"], "apr-new-2")
        self.assertEqual(replacement["receipts"], [])
        self.assertFalse(replacement["execution_authorized"])

    def test_open_request_cannot_be_replaced(self) -> None:
        with self.assertRaises(ApprovalTimeoutPolicyError):
            new_human_request(
                request_id="apr-new-2",
                current_binding={**self.binding, "card_sha256": "card-v2"},
                now=self.wall,
                monotonic_now=self.monotonic,
                previous=self.request(),
            )

    def test_invalid_or_inverted_timing_fails_closed(self) -> None:
        with self.assertRaises(ApprovalTimeoutPolicyError):
            approval_deadlines(
                now=self.wall,
                reassess_after_seconds=300,
                ttl_seconds=300,
            )
        with self.assertRaises(ApprovalTimeoutPolicyError):
            approval_deadlines(
                now=self.wall,
                reassess_after_seconds=300,
                ttl_seconds=86_401,
            )
        malformed = self.request(expires_at="not-a-time")
        self.assertEqual(
            request_phase(
                malformed,
                now=self.wall,
                monotonic_now=self.monotonic,
            ),
            "expired",
        )

    def test_f05_003_exact_json_boundary_and_invalid_state_are_closed(self) -> None:
        for field, value in (
            ("reassess_after_seconds", True),
            ("ttl_seconds", False),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    approval_deadlines(now=self.wall, **{field: value})

        with self.assertRaises(ApprovalTimeoutPolicyError):
            new_human_request(
                request_id=123,
                current_binding=self.binding,
                now=self.wall,
                monotonic_now=self.monotonic,
            )
        for timestamp in (123, ""):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    parse_timestamp(timestamp)
        for value in (float("nan"), float("inf"), float("-inf"), True):
            with self.subTest(monotonic=value):
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    new_human_request(
                        request_id="apr-finite",
                        current_binding=self.binding,
                        now=self.wall,
                        monotonic_now=value,
                    )

        malformed_requests = (
            self.request(receipts="bad"),
            self.request(receipts=ListSubclass()),
            self.request(receipts=["not-a-row"]),
            self.request(
                receipts=[
                    {
                        "receipt_id": "",
                        "request_id": "apr-new",
                        "outcome": "deny",
                    }
                ]
            ),
            self.request(
                receipts=[
                    {
                        "receipt_id": "receipt-old",
                        "request_id": "apr-new",
                        "outcome": "deny",
                    },
                    {
                        "receipt_id": "receipt-old",
                        "request_id": "apr-new",
                        "outcome": "deny",
                    },
                ]
            ),
            self.request(binding=DictSubclass(self.binding)),
        )
        for malformed in malformed_requests:
            with self.subTest(receipts=type(malformed.get("receipts"))):
                before = repr(malformed)
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    consume_human_decision(
                        malformed,
                        self.decision(),
                        current_binding=self.binding,
                        now=self.wall + timedelta(minutes=6),
                        monotonic_now=self.monotonic + 360,
                    )
                self.assertEqual(repr(malformed), before)

        unknown = self.request(status="mystery")
        self.assertEqual(
            request_phase(unknown, now=self.wall, monotonic_now=self.monotonic),
            "invalid",
        )
        tick = reassess_request(
            unknown,
            current_binding=self.binding,
            now=self.wall,
            monotonic_now=self.monotonic,
        )
        replay = consume_human_decision(
            unknown,
            self.decision(),
            current_binding=self.binding,
            now=self.wall,
            monotonic_now=self.monotonic,
        )
        self.assertEqual(tick["action"], "invalid_request")
        self.assertEqual(replay["status"], "invalid_request")
        self.assertEqual(tick["receipt_delta"], 0)
        self.assertEqual(replay["receipt_delta"], 0)
        self.assertFalse(replay["execute_once"])
        invalid_replay = self.request(
            status="mystery",
            receipts=[
                {
                    "receipt_id": "receipt-new",
                    "request_id": "apr-new",
                    "outcome": "deny",
                }
            ],
        )
        invalid_before = repr(invalid_replay)
        replay_again = consume_human_decision(
            invalid_replay,
            self.decision(),
            current_binding=self.binding,
            now=self.wall,
            monotonic_now=self.monotonic,
        )
        self.assertEqual(replay_again["status"], "invalid_request")
        self.assertEqual(replay_again["receipt_delta"], 0)
        self.assertFalse(replay_again["execute_once"])
        self.assertEqual(repr(invalid_replay), invalid_before)
        with self.assertRaises(ApprovalTimeoutPolicyError):
            new_human_request(
                request_id="apr-replacement",
                current_binding={**self.binding, "card_sha256": "card-v2"},
                now=self.wall,
                monotonic_now=self.monotonic,
                previous=unknown,
            )
        numeric_status = self.request(status=7)
        self.assertEqual(
            request_phase(
                numeric_status,
                now=self.wall,
                monotonic_now=self.monotonic,
            ),
            "invalid",
        )
        with self.assertRaises(ApprovalTimeoutPolicyError):
            reassess_request(
                numeric_status,
                current_binding=self.binding,
                now=self.wall,
                monotonic_now=self.monotonic,
            )
        with self.assertRaises(ApprovalTimeoutPolicyError):
            request_phase(
                self.request(),
                now=self.wall,
                monotonic_now=float("nan"),
            )

        for malformed_binding in (
            {key: value for key, value in self.binding.items() if key != "provider"},
            {**self.binding, "extra_authority": "bad"},
            DictSubclass(self.binding),
        ):
            with self.subTest(binding=malformed_binding):
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    new_human_request(
                        request_id="apr-binding",
                        current_binding=malformed_binding,
                        now=self.wall,
                        monotonic_now=self.monotonic,
                    )

        for target, changed in (
            ("decision", {"revision": True}),
            ("decision", {"provider": 7}),
            ("decision", {"outcome": 1}),
            ("current", {"revision": "7"}),
            ("current", {"session_id": False}),
        ):
            with self.subTest(target=target, changed=changed):
                decision = self.decision()
                current = dict(self.binding)
                (decision if target == "decision" else current).update(changed)
                request = self.request()
                with self.assertRaises(ApprovalTimeoutPolicyError):
                    consume_human_decision(
                        request,
                        decision,
                        current_binding=current,
                        now=self.wall + timedelta(minutes=6),
                        monotonic_now=self.monotonic + 360,
                    )
                self.assertEqual(request["receipts"], [])

    def test_f05_003_magic_objects_never_receive_callbacks_in_public_apis(self) -> None:
        def rejected(callable_: object) -> None:
            probe = MagicProbe()
            with self.assertRaises(ApprovalTimeoutPolicyError):
                callable_(probe)  # type: ignore[operator]
            self.assertEqual(probe.calls, 0)

        rejected(parse_timestamp)
        rejected(normalize_unattended_policy)
        rejected(lambda value: approval_deadlines(reassess_after_seconds=value))
        rejected(lambda value: request_phase(value))
        rejected(
            lambda value: reassess_request(
                value, current_binding=self.binding, now=self.wall
            )
        )
        action_probe = MagicProbe()
        eligible, reasons = agent_policy_eligibility(action_probe)
        self.assertFalse(eligible)
        self.assertTrue(reasons)
        self.assertEqual(action_probe.calls, 0)

        prompt_probe = MagicProbe()
        route = pre_prompt_route(
            self.agent_action(),
            unattended_policy="agent-if-eligible",
            prompt_shown=prompt_probe,
        )
        self.assertEqual(route["route"], "human")
        self.assertEqual(prompt_probe.calls, 0)

        rejected(
            lambda value: timeout_disposition(
                phase=value,
                kind="local-edit",
                unattended_policy="wait",
                eligible=False,
                world_current=True,
                host_timeout_observed=True,
            )
        )
        rejected(
            lambda value: new_human_request(
                request_id=value,
                current_binding=self.binding,
                now=self.wall,
                monotonic_now=self.monotonic,
            )
        )
        rejected(
            lambda value: consume_human_decision(
                value,
                self.decision(),
                current_binding=self.binding,
                now=self.wall,
            )
        )

    def agent_action(self, **overrides: object) -> dict:
        action = {
            "kind": "local-edit",
            "contains_secret": False,
            "external_write": False,
            "incurs_cost": False,
            "reversible": True,
            "risk": "low",
            "evidence_complete": True,
            "allowlisted": True,
        }
        action.update(overrides)
        return action

    def test_f05_004_pre_prompt_authority_requires_exact_types(self) -> None:
        for prompt_shown in (0, "false"):
            with self.subTest(prompt_shown=prompt_shown):
                route = pre_prompt_route(
                    self.agent_action(),
                    unattended_policy="agent-if-eligible",
                    prompt_shown=prompt_shown,
                )
                self.assertEqual(route["route"], "human")
                self.assertEqual(route["decision_owner"], "human")

        for action in (
            self.agent_action(kind=123),
            self.agent_action(kind=""),
            self.agent_action(kind="unknown-local-action"),
            self.agent_action(risk="unknown"),
            self.agent_action(allowlisted=1),
            self.agent_action(reversible="yes"),
            self.agent_action(delete=True),
            self.agent_action(metadata=ListSubclass()),
        ):
            with self.subTest(action=action):
                eligible, reasons = agent_policy_eligibility(action)
                route = pre_prompt_route(
                    action,
                    unattended_policy="agent-if-eligible",
                    prompt_shown=False,
                )
                self.assertFalse(eligible)
                self.assertTrue(reasons)
                self.assertEqual(route["route"], "human")
                self.assertFalse(route["execution_authorized"])

        for agent_already_decided in (1, "false"):
            route = pre_prompt_route(
                self.agent_action(),
                unattended_policy="agent-if-eligible",
                prompt_shown=False,
                agent_already_decided=agent_already_decided,
            )
            self.assertEqual(route["route"], "human")
            self.assertEqual(route["decision_owner"], "human")

        contradictory = pre_prompt_route(
            self.agent_action(),
            unattended_policy="agent-if-eligible",
            prompt_shown=True,
            agent_already_decided=True,
        )
        self.assertEqual(contradictory["route"], "human")
        self.assertEqual(contradictory["decision_owner"], "human")


if __name__ == "__main__":
    unittest.main()

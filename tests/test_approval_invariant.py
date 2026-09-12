from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

from approval_invariant import (  # noqa: E402
    ApprovalInvariantError,
    authoritative_store_bytes,
    ask_approval,
    cancel_request,
    cancel_open_requests,
    decide_approval,
    decided_request_receipt,
    decide_typed_approval,
    event_store_path,
    load_projection,
    open_requests,
    observe_typed_prompt,
    replace_typed_approval,
    request_binding_receipt,
    restore_authoritative_store,
    request_phase,
    summary,
    typed_receipts,
    verify_request_binding_receipt,
    ask_typed_approval,
)
from intent_guardian import (  # noqa: E402
    GuardianSession,
    IntentGuardianError,
    active_contract_path,
    create_revision_proposal,
    decide_proposal_as_agent,
    decision_request_context,
    default_contract,
    execute_native_decision,
    load_contract,
    native_decision_preview,
    normalize_hook_event,
    observe_native_permission_request,
    observe_user_prompt,
    write_contract,
)
import intent_guardian_parts.recovery as guardian_recovery_module  # noqa: E402
from native_decision_journal import (  # noqa: E402
    load_projection as load_native_projection,
)


class ApprovalPairStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.contract = self.root / "intent.json"
        self.contract.write_text("{}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ask(self, target: str = "a" * 64, **overrides: object) -> dict:
        values = {
            "intent_id": "private-intent",
            "intent_revision": 2,
            "kind": "event",
            "target": target,
            "provider": "codex",
            "session_id": "private-session",
            "source": "guardian_pre_action",
        }
        values.update(overrides)
        return ask_approval(self.contract, **values)

    def test_question_and_decision_pair_once_without_raw_lane_or_target(self) -> None:
        asked = self.ask()
        decided = decide_approval(
            self.contract,
            kind="event",
            target="a" * 64,
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="user-prompt:codex",
            receipt_id="receipt-private",
        )

        self.assertEqual(asked["request_id"], decided["request_id"])
        self.assertEqual(decided["status"], "decided")
        self.assertEqual(decided["outcome"], "approved")
        self.assertEqual(summary(self.contract)["open"], 0)
        raw = event_store_path(self.contract).read_text()
        self.assertNotIn("private-session", raw)
        self.assertNotIn("private-intent", raw)
        self.assertNotIn("receipt-private", raw)
        self.assertNotIn("a" * 64, raw)

    def test_decision_without_question_and_conflicting_duplicate_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ApprovalInvariantError, "exactly one open question"
        ):
            decide_approval(
                self.contract,
                kind="event",
                target="a" * 64,
                outcome="approved",
                provider="codex",
                session_id="private-session",
                actor="human",
            )
        self.ask()
        first = decide_approval(
            self.contract,
            kind="event",
            target="a" * 64,
            outcome="rejected",
            provider="codex",
            session_id="private-session",
            actor="human",
        )
        repeated = decide_approval(
            self.contract,
            kind="event",
            target="a" * 64,
            outcome="rejected",
            provider="codex",
            session_id="private-session",
            actor="human",
        )
        self.assertEqual(first["request_id"], repeated["request_id"])
        self.assertTrue(repeated["idempotent"])
        with self.assertRaisesRegex(
            ApprovalInvariantError, "exactly one open question"
        ):
            decide_approval(
                self.contract,
                kind="event",
                target="a" * 64,
                outcome="approved",
                provider="codex",
                session_id="private-session",
                actor="human",
            )

    def test_request_binds_card_workspace_route_and_expiry(self) -> None:
        workspace = self.root / "project-a"
        workspace.mkdir()
        card = {"目标": "修复控制面", "选择": ["批准", "拒绝"]}
        asked = self.ask(
            kind="intent-confirmation",
            target="intent-card-v1",
            provider="unknown",
            session_id="",
            source="intent_confirmation",
            card=card,
            workspace=workspace,
            route="human",
            ttl_seconds=600,
        )

        self.assertRegex(asked["card_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(asked["workspace_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(asked["route"], "human")
        self.assertTrue(asked["expires_at"])
        self.assertEqual(
            len(open_requests(self.contract, workspace=workspace, route="human")),
            1,
        )
        with self.assertRaisesRegex(
            ApprovalInvariantError, "exactly one open question"
        ):
            decide_approval(
                self.contract,
                kind="intent-confirmation",
                target="intent-card-v1",
                outcome="approved",
                provider="codex",
                session_id="new-session",
                actor="user-prompt:codex",
                card=card,
                workspace=self.root / "project-b",
                route="human",
            )

        decided = decide_approval(
            self.contract,
            kind="intent-confirmation",
            target="intent-card-v1",
            outcome="approved",
            provider="codex",
            session_id="new-session",
            actor="user-prompt:codex",
            card=card,
            workspace=workspace,
            route="human",
        )
        self.assertEqual(decided["outcome"], "approved")

    def test_expired_request_is_not_open_or_decidable(self) -> None:
        self.ask(target="expiry-target", ttl_seconds=60)
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[0]["expires_at"] = "2000-01-01T00:00:00+00:00"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

        self.assertEqual(open_requests(self.contract), [])
        self.assertEqual(summary(self.contract)["expired"], 1)
        with self.assertRaisesRegex(
            ApprovalInvariantError, "exactly one open question"
        ):
            decide_approval(
                self.contract,
                kind="event",
                target="expiry-target",
                outcome="approved",
                provider="codex",
                session_id="private-session",
                actor="human",
            )

    def test_reassessment_clock_does_not_expire_durable_question(self) -> None:
        asked = self.ask(
            target="dual-clock",
            ttl_seconds=3600,
            reassess_after_seconds=300,
        )
        self.assertTrue(asked["reassess_at"])
        self.assertTrue(asked["expires_at"])
        self.assertEqual(request_phase(asked), "fresh")
        self.assertEqual(len(open_requests(self.contract)), 1)

        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[0]["reassess_at"] = "2000-01-01T00:00:00+00:00"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        due = load_projection(self.contract)["requests"][asked["request_id"]]
        self.assertEqual(request_phase(due), "reassess_due")
        self.assertEqual(summary(self.contract)["reassess_due"], 1)
        self.assertEqual(len(open_requests(self.contract)), 1)

    def test_exact_cancellation_is_idempotent_and_never_approves(self) -> None:
        asked = self.ask(target="cancel-one")
        first = cancel_request(
            self.contract,
            asked["request_id"],
            actor="timeout-liveness-cleanup",
        )
        second = cancel_request(
            self.contract,
            asked["request_id"],
            actor="timeout-liveness-cleanup",
        )
        self.assertEqual(first["outcome"], "cancelled")
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        self.assertEqual(summary(self.contract)["by_outcome"]["approved"], 0)

    def test_proposal_supersession_closes_old_question(self) -> None:
        first = self.ask(
            target="a" * 64,
            kind="proposal",
            provider="unknown",
            session_id="",
            source="proposal_review",
        )
        second = self.ask(
            target="b" * 64,
            kind="proposal",
            provider="unknown",
            session_id="",
            source="proposal_review",
        )
        projection = load_projection(self.contract)
        self.assertEqual(
            projection["requests"][first["request_id"]]["outcome"],
            "cancelled",
        )
        self.assertEqual(
            projection["requests"][second["request_id"]]["status"],
            "asked",
        )
        self.assertEqual(summary(self.contract)["open"], 1)

    def test_proposal_supersedes_initial_intent_confirmation(self) -> None:
        initial = self.ask(
            target="intent-card-v1",
            kind="intent-confirmation",
            provider="unknown",
            session_id="",
            source="intent_confirmation",
        )
        proposal = self.ask(
            target="b" * 64,
            kind="proposal",
            provider="unknown",
            session_id="",
            source="proposal_review",
        )
        projection = load_projection(self.contract)
        self.assertEqual(
            projection["requests"][initial["request_id"]]["outcome"],
            "cancelled",
        )
        self.assertEqual(
            projection["requests"][proposal["request_id"]]["status"],
            "asked",
        )

    def test_wrong_host_lane_cannot_answer_bound_question(self) -> None:
        self.ask()
        with self.assertRaisesRegex(
            ApprovalInvariantError, "exactly one open question"
        ):
            decide_approval(
                self.contract,
                kind="event",
                target="a" * 64,
                outcome="approved",
                provider="claude",
                session_id="other-session",
                actor="user-prompt:claude",
            )

    def test_question_source_is_part_of_the_authority_binding(self) -> None:
        card = {"本次选择": "批准同一目标"}
        prompt = self.ask(
            target="same-target",
            source="user_prompt_submit",
            card=card,
        )
        native = self.ask(
            target="same-target",
            source="codex_permission_request",
            card=card,
        )
        self.assertNotEqual(prompt["request_id"], native["request_id"])

        decided = decide_approval(
            self.contract,
            kind="event",
            target="same-target",
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="permission-request:codex",
            card=card,
            source="codex_permission_request",
        )
        self.assertEqual(decided["request_id"], native["request_id"])
        projection = load_projection(self.contract)
        self.assertEqual(
            projection["requests"][prompt["request_id"]]["status"], "asked"
        )
        self.assertEqual(
            projection["requests"][native["request_id"]]["status"], "decided"
        )

    def test_authoritative_prefix_can_be_restored_after_invalid_append(self) -> None:
        self.ask()
        accepted = authoritative_store_bytes(self.contract)
        store = event_store_path(self.contract)
        store.write_bytes(accepted + b'{"forged":true}\n')

        with self.assertRaises(ApprovalInvariantError):
            load_projection(self.contract)
        restore_authoritative_store(self.contract, accepted)

        self.assertEqual(store.read_bytes(), accepted)
        self.assertEqual(summary(self.contract)["open"], 1)

    def test_current_v2_request_receipts_are_closed_read_only_and_decidable(
        self,
    ) -> None:
        card = {"operation_id": "intent", "decision_id": "confirm"}
        asked = self.ask(
            target="receipt-target",
            kind="intent-confirmation",
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        self.assertEqual(rows[-1]["schema"], "sulde-approval-pair-event-v2")
        self.assertNotIn("typed", rows[-1])

        before = store.read_bytes()
        receipt = request_binding_receipt(self.contract, asked["request_id"])
        request = verify_request_binding_receipt(self.contract, receipt)
        self.assertEqual(store.read_bytes(), before)
        self.assertEqual(request["request_id"], asked["request_id"])
        self.assertEqual(
            set(receipt),
            {
                "schema", "contract_sha256", "request_id",
                "intent_id_sha256", "intent_revision", "kind",
                "target_sha256", "card_sha256", "workspace_sha256",
                "proposal_sha256", "route", "provider", "lane_sha256",
                "source", "asked_at", "expires_at", "reassess_at",
                "binding_sha256",
            },
        )

        decide_approval(
            self.contract,
            kind="intent-confirmation",
            target="receipt-target",
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="permission-request:codex",
            card=card,
            workspace=self.root,
            route="human",
            source="codex_permission_request",
        )
        before = store.read_bytes()
        decision = decided_request_receipt(
            self.contract,
            receipt,
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="permission-request:codex",
        )
        self.assertEqual(store.read_bytes(), before)
        self.assertEqual(
            set(decision),
            {
                "schema", "contract_sha256", "request_id",
                "binding_sha256", "outcome", "provider", "lane_sha256",
                "actor", "decided_at", "receipt_sha256", "decision_sha256",
            },
        )
        self.assertEqual(decision["binding_sha256"], receipt["binding_sha256"])

    def test_unrelated_typed_suffix_cannot_change_v2_request_receipts(self) -> None:
        asked = self.ask(
            target="sealed-current-wire",
            source="codex_permission_request",
        )
        receipt = request_binding_receipt(self.contract, asked["request_id"])
        decide_approval(
            self.contract,
            kind="event",
            target="sealed-current-wire",
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="permission-request:codex",
            source="codex_permission_request",
        )
        decision = decided_request_receipt(
            self.contract,
            receipt,
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="permission-request:codex",
        )
        snapshot = {
            "card_sha256": "1" * 64,
            "provider": "codex",
            "session_id": "typed-suffix",
            "lane_sha256": hashlib.sha256(
                b"codex\0typed-suffix"
            ).hexdigest(),
            "target_sha256": "2" * 64,
            "revision": 8,
            "journal_sha256": "3" * 64,
            "effect_sha256": "4" * 64,
            "world_state_sha256": "5" * 64,
        }
        ask_typed_approval(
            self.contract,
            snapshot=snapshot,
            kind="effect-intervention",
            source="codex_permission_request",
        )
        suffix_bytes = event_store_path(self.contract).read_bytes()

        self.assertEqual(
            request_binding_receipt(self.contract, asked["request_id"]),
            receipt,
        )
        self.assertEqual(
            decided_request_receipt(
                self.contract,
                receipt,
                outcome="approved",
                provider="codex",
                session_id="private-session",
                actor="permission-request:codex",
            ),
            decision,
        )
        self.assertEqual(event_store_path(self.contract).read_bytes(), suffix_bytes)

    def test_receipt_schema_types_and_target_prefix_fail_closed(self) -> None:
        asked = self.ask(
            target="tamper-target",
            source="codex_permission_request",
        )
        receipt = request_binding_receipt(self.contract, asked["request_id"])
        store = event_store_path(self.contract)
        accepted = store.read_bytes()

        cases = {
            "open-key": dict(receipt, extra=False),
            "bool-as-int": dict(receipt, intent_revision=True),
            "digest": dict(receipt, target_sha256="0" * 64),
        }
        for label, changed in cases.items():
            with self.subTest(receipt=label):
                with self.assertRaises(ApprovalInvariantError):
                    verify_request_binding_receipt(self.contract, changed)
                self.assertEqual(store.read_bytes(), accepted)

        class ReceiptSubclass(dict):
            pass

        with self.assertRaises(ApprovalInvariantError):
            verify_request_binding_receipt(
                self.contract, ReceiptSubclass(receipt)
            )

        rows = [json.loads(line) for line in accepted.decode().splitlines()]
        mutations = {
            "unknown-schema": {"schema": "sulde-approval-pair-event-v999"},
            "bool-sequence": {"sequence": True},
            "field-substitution": {"target_sha256": "0" * 64},
        }
        for label, change in mutations.items():
            with self.subTest(prefix=label):
                tampered = deepcopy(rows)
                tampered[0].update(change)
                store.write_text(
                    "".join(
                        json.dumps(row, sort_keys=True) + "\n"
                        for row in tampered
                    ),
                    encoding="utf-8",
                )
                with self.assertRaises(ApprovalInvariantError):
                    verify_request_binding_receipt(self.contract, receipt)
                store.write_bytes(accepted)

        store.write_bytes(accepted[:-1])
        with self.assertRaisesRegex(ApprovalInvariantError, "incomplete"):
            verify_request_binding_receipt(self.contract, receipt)
        store.write_bytes(accepted)

    def test_decision_receipt_rejects_open_expired_agent_and_actor_states(
        self,
    ) -> None:
        open_request = self.ask(
            target="still-open",
            source="codex_permission_request",
        )
        open_receipt = request_binding_receipt(
            self.contract, open_request["request_id"]
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "still open"):
            decided_request_receipt(
                self.contract,
                open_receipt,
                outcome="approved",
                provider="codex",
                session_id="private-session",
                actor="permission-request:codex",
            )

        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[-1]["expires_at"] = "2000-01-01T00:00:00+00:00"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        expired_receipt = request_binding_receipt(
            self.contract, open_request["request_id"]
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "expired"):
            decided_request_receipt(
                self.contract,
                expired_receipt,
                outcome="approved",
                provider="codex",
                session_id="private-session",
                actor="permission-request:codex",
            )

        agent = self.ask(
            target="agent-owned",
            route="agent",
            source="codex_permission_request",
        )
        agent_receipt = request_binding_receipt(self.contract, agent["request_id"])
        decide_approval(
            self.contract,
            kind="event",
            target="agent-owned",
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="codex",
            route="agent",
            source="codex_permission_request",
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "binding mismatch"):
            decided_request_receipt(
                self.contract,
                agent_receipt,
                outcome="approved",
                provider="codex",
                session_id="private-session",
                actor="permission-request:codex",
            )

        self_signed = self.ask(
            target="self-signed",
            source="codex_permission_request",
        )
        self_signed_receipt = request_binding_receipt(
            self.contract, self_signed["request_id"]
        )
        decide_approval(
            self.contract,
            kind="event",
            target="self-signed",
            outcome="approved",
            provider="codex",
            session_id="private-session",
            actor="codex",
            route="human",
            source="codex_permission_request",
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "binding mismatch"):
            decided_request_receipt(
                self.contract,
                self_signed_receipt,
                outcome="approved",
                provider="codex",
                session_id="private-session",
                actor="permission-request:codex",
            )


class ApprovalTypedCASLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.contract = Path(self.temporary.name) / "intent.json"
        self.contract.write_text("{}\n", encoding="utf-8")
        session_id = "session-a"
        lane = hashlib.sha256(
            f"codex\0{session_id}".encode("utf-8")
        ).hexdigest()
        self.snapshot = {
            "card_sha256": "card-v1",
            "provider": "codex",
            "session_id": session_id,
            "lane_sha256": lane,
            "target_sha256": "target-v1",
            "revision": 7,
            "journal_sha256": "journal-v1",
            "effect_sha256": "effect-v1",
            "world_state_sha256": "world-v1",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def ask(self, **overrides: object) -> dict:
        values = {
            "snapshot": self.snapshot,
            "kind": "effect-intervention",
            "source": "codex_permission_request",
        }
        values.update(overrides)
        return ask_typed_approval(self.contract, **values)

    def show(self, request: dict, **overrides: object) -> dict:
        values = {
            "request_id": request["request_id"],
            "snapshot": request["snapshot"],
            "provider": "codex",
            "session_id": "session-a",
            "prompt_shown": True,
            "decision_owner": "human",
        }
        values.update(overrides)
        return observe_typed_prompt(self.contract, **values)

    def decide(self, request: dict, **overrides: object) -> dict:
        values = {
            "request_id": request["request_id"],
            "receipt_id": "receipt-1",
            "outcome": "allow",
            "snapshot": request["snapshot"],
            "current_snapshot": request["snapshot"],
            "provider": "codex",
            "session_id": "session-a",
            "decision_owner": "human",
            "actor": "native-human",
        }
        values.update(overrides)
        return decide_typed_approval(self.contract, **values)

    def test_replaced_request_cannot_produce_a_decision_receipt(self) -> None:
        request = self.ask()
        receipt = request_binding_receipt(
            self.contract, request["request_id"]
        )
        fresh = dict(
            self.snapshot,
            card_sha256="card-v2",
            world_state_sha256="world-v2",
        )
        replace_typed_approval(
            self.contract,
            previous_request_id=request["request_id"],
            snapshot=fresh,
            kind="effect-intervention",
            source="codex_permission_request",
        )

        with self.assertRaisesRegex(ApprovalInvariantError, "replaced"):
            decided_request_receipt(
                self.contract,
                receipt,
                outcome="allow",
                provider="codex",
                session_id="session-a",
                actor="native-human",
            )

    def legacy_rows(self, total: int) -> list[dict]:
        contract_sha256 = hashlib.sha256(
            str(self.contract.resolve()).encode("utf-8")
        ).hexdigest()
        rows: list[dict] = []
        request_number = 0
        while len(rows) < total:
            request_number += 1
            request_id = f"apr-{request_number:024x}"
            target_sha256 = f"{request_number:064x}"
            rows.append({
                "schema": "sulde-approval-pair-event-v1",
                "contract_sha256": contract_sha256,
                "sequence": len(rows) + 1,
                "at": "2026-01-01T00:00:00+00:00",
                "type": "approval.asked",
                "request_id": request_id,
                "intent_id_sha256": "1" * 64,
                "intent_revision": 1,
                "kind": "event",
                "target_sha256": target_sha256,
                "card_sha256": "",
                "workspace_sha256": "",
                "proposal_sha256": "",
                "route": "human",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "reassess_at": "",
                "provider": "unknown",
                "lane_sha256": "",
                "source": "live-shaped-legacy-fixture",
            })
            if len(rows) < total:
                rows.append({
                    "schema": "sulde-approval-pair-event-v1",
                    "contract_sha256": contract_sha256,
                    "sequence": len(rows) + 1,
                    "at": "2026-01-01T00:00:01+00:00",
                    "type": "approval.decided",
                    "request_id": request_id,
                    "outcome": "approved",
                    "provider": "unknown",
                    "lane_sha256": "",
                    "receipt_sha256": "",
                    "actor": "legacy-human",
                })
        return rows

    def write_rows(self, rows: list[dict]) -> None:
        event_store_path(self.contract).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_large_live_shaped_v1_history_replays_without_rewrite(self) -> None:
        rows = self.legacy_rows(449)
        self.write_rows(rows)
        before = authoritative_store_bytes(self.contract)

        projection = load_projection(self.contract)

        self.assertEqual(projection["sequence"], 449)
        self.assertEqual(len(projection["requests"]), 225)
        self.assertEqual(summary(self.contract)["open"], 1)
        self.assertEqual(summary(self.contract)["by_outcome"]["approved"], 224)
        self.assertEqual(authoritative_store_bytes(self.contract), before)

    def test_historical_v1_request_binding_receipt_is_read_only_compatible(
        self,
    ) -> None:
        self.write_rows(self.legacy_rows(1))
        request_id = "apr-000000000000000000000001"
        before = authoritative_store_bytes(self.contract)

        receipt = request_binding_receipt(self.contract, request_id)
        request = verify_request_binding_receipt(self.contract, receipt)

        self.assertEqual(request["request_id"], request_id)
        self.assertEqual(receipt["schema"], "sulde-approval-request-binding-receipt-v1")
        self.assertEqual(authoritative_store_bytes(self.contract), before)

    def test_v1_prefix_accepts_v2_typed_replay_and_append(self) -> None:
        self.write_rows(self.legacy_rows(2))

        request = self.ask()
        self.show(request)
        receipt = self.decide(request)
        rows = [
            json.loads(line)
            for line in event_store_path(self.contract).read_text().splitlines()
        ]

        self.assertEqual(
            [row["schema"] for row in rows],
            ["sulde-approval-pair-event-v1"] * 2
            + ["sulde-approval-pair-event-v2"] * 3,
        )
        self.assertEqual(load_projection(self.contract)["sequence"], 5)
        self.assertEqual(typed_receipts(self.contract), [receipt])

    def test_v1_typed_authority_marker_injection_fails_closed(self) -> None:
        markers = {
            "typed": True,
            "snapshot": {},
            "snapshot_identity": "sha256:forged",
            "request_identity": "sha256:forged",
            "replacement_identity": "sha256:forged",
            "replaced_request_id": "apr-ffffffffffffffffffffffff",
            "replacement_request_id": "apr-eeeeeeeeeeeeeeeeeeeeeeee",
            "superseded_by_identity": "sha256:forged",
            "prompt_shown": False,
            "prompt_observations": 0,
            "decision_owner": "human",
            "typed_receipt": {},
            "decision_identity": "sha256:forged",
            "execution_authorized": False,
        }
        for field, value in markers.items():
            with self.subTest(field=field):
                row = deepcopy(self.legacy_rows(1)[0])
                row[field] = value
                self.write_rows([row])
                with self.assertRaisesRegex(
                    ApprovalInvariantError, "typed authority markers"
                ):
                    load_projection(self.contract)

    def test_wrong_schema_event_combinations_fail_closed(self) -> None:
        cases: dict[str, list[dict]] = {}
        for event_type in ("approval.prompt-observed", "approval.replaced"):
            row = self.legacy_rows(1)[0]
            row["type"] = event_type
            cases[f"v1-{event_type}"] = [row]

        typed_outcome = self.legacy_rows(2)
        typed_outcome[1]["outcome"] = "allow"
        cases["v1-typed-outcome"] = typed_outcome

        unsupported = self.legacy_rows(1)
        unsupported[0]["schema"] = "sulde-approval-pair-event-v3"
        cases["unknown-generation"] = unsupported

        missing_typed_marker = self.legacy_rows(1)
        missing_typed_marker[0]["schema"] = "sulde-approval-pair-event-v2"
        missing_typed_marker[0]["type"] = "approval.prompt-observed"
        cases["v2-typed-event-without-marker"] = missing_typed_marker

        for label, rows in cases.items():
            with self.subTest(case=label):
                self.write_rows(rows)
                with self.assertRaises(ApprovalInvariantError):
                    load_projection(self.contract)

    def test_v1_audit_row_after_typed_lifecycle_replays_without_rewrite(self) -> None:
        request = self.ask()
        self.show(request)
        self.decide(request)
        rows = [
            json.loads(line)
            for line in event_store_path(self.contract).read_text().splitlines()
        ]
        legacy = self.legacy_rows(1)[0]
        legacy["sequence"] = len(rows) + 1
        rows.append(legacy)
        self.write_rows(rows)
        before = authoritative_store_bytes(self.contract)

        projection = load_projection(self.contract)

        self.assertEqual(projection["sequence"], 4)
        self.assertEqual(len(typed_receipts(self.contract)), 1)
        self.assertEqual(authoritative_store_bytes(self.contract), before)

    def test_request_card_and_prompt_share_one_non_authoritative_snapshot(self) -> None:
        request = self.ask()
        self.assertTrue(request["typed"])
        self.assertEqual(request["snapshot"], self.snapshot)
        self.assertFalse(request["prompt_shown"])
        self.assertFalse(request["execution_authorized"])
        self.assertEqual(typed_receipts(self.contract), [])
        sequence = summary(self.contract)["sequence"]
        same = self.ask(request_id="apr-111111111111111111111111")
        self.assertEqual(same["request_id"], request["request_id"])
        self.assertEqual(summary(self.contract)["sequence"], sequence)
        self.assertEqual(
            event_store_path(self.contract).stat().st_mode & 0o777,
            0o600,
        )

        unshown = self.show(request, prompt_shown=False)
        shown = self.show(request)
        self.assertFalse(unshown["prompt_shown"])
        self.assertTrue(shown["prompt_shown"])
        self.assertEqual(shown["prompt_observations"], 1)
        self.assertEqual(typed_receipts(self.contract), [])
        self.assertEqual(summary(self.contract)["execution_authorized"], 0)

    def test_unshown_nonhuman_and_foreign_lane_decisions_fail_closed(self) -> None:
        request = self.ask()
        with self.assertRaisesRegex(ApprovalInvariantError, "not shown"):
            self.decide(request)
        with self.assertRaisesRegex(ApprovalInvariantError, "owner"):
            self.show(request, decision_owner="agent")
        with self.assertRaisesRegex(ApprovalInvariantError, "provider/session/lane"):
            self.show(request, session_id="other-session")
        with self.assertRaisesRegex(ApprovalInvariantError, "provider/session/lane"):
            self.show(request, lane_sha256="other-lane")
        self.show(request)
        with self.assertRaisesRegex(ApprovalInvariantError, "owner"):
            self.decide(request, decision_owner="agent")
        with self.assertRaisesRegex(ApprovalInvariantError, "provider/session/lane"):
            self.decide(request, provider="claude")
        self.assertEqual(typed_receipts(self.contract), [])

    def test_explicit_independent_lane_identity_is_supported_and_checked(self) -> None:
        snapshot = {**self.snapshot, "lane_sha256": "native-lane-a"}
        request = self.ask(snapshot=snapshot)
        shown = self.show(
            request,
            snapshot=snapshot,
            lane_sha256="native-lane-a",
        )
        receipt = self.decide(
            shown,
            snapshot=snapshot,
            current_snapshot=snapshot,
            lane_sha256="native-lane-a",
        )
        self.assertEqual(receipt["snapshot"]["lane_sha256"], "native-lane-a")

    def test_one_shot_receipt_rejects_same_and_different_duplicates(self) -> None:
        request = self.ask()
        self.show(request)
        receipt = self.decide(request)
        self.assertEqual(receipt["outcome"], "allow")
        self.assertFalse(receipt["execution_authorized"])
        self.assertEqual(receipt["snapshot"], self.snapshot)
        self.assertEqual(typed_receipts(self.contract), [receipt])

        for receipt_id, outcome in (
            ("receipt-1", "allow"),
            ("receipt-2", "allow"),
            ("receipt-3", "deny"),
        ):
            with self.subTest(receipt_id=receipt_id, outcome=outcome):
                with self.assertRaisesRegex(
                    ApprovalInvariantError, "already decided"
                ):
                    self.decide(
                        request,
                        receipt_id=receipt_id,
                        outcome=outcome,
                    )
        self.assertEqual(len(typed_receipts(self.contract)), 1)

    def test_stale_world_and_expired_late_decisions_fail_closed(self) -> None:
        request = self.ask()
        self.show(request)
        with self.assertRaisesRegex(ApprovalInvariantError, "world_state_sha256"):
            self.decide(
                request,
                current_snapshot={
                    **self.snapshot,
                    "world_state_sha256": "world-v2",
                },
            )

        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[0]["expires_at"] = "2000-01-01T00:00:00+00:00"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        expired = load_projection(self.contract)["requests"][request["request_id"]]
        self.assertEqual(request_phase(expired), "expired")
        with self.assertRaisesRegex(ApprovalInvariantError, "expired"):
            self.decide(request)
        self.assertEqual(typed_receipts(self.contract), [])

    def test_reassess_due_is_liveness_only_and_late_human_decision_survives(self) -> None:
        request = self.ask()
        self.show(request)
        future = datetime.now(timezone.utc) + timedelta(minutes=10)
        self.assertEqual(request_phase(request, now=future), "reassess_due")
        receipt = self.decide(request, outcome="deny")
        self.assertEqual(receipt["outcome"], "deny")
        self.assertFalse(receipt["execution_authorized"])

    def test_fresh_replacement_is_lineaged_and_cannot_overwrite_decision(self) -> None:
        previous = self.ask()
        replacement_snapshot = {
            **self.snapshot,
            "card_sha256": "card-v2",
            "world_state_sha256": "world-v2",
        }
        replacement = replace_typed_approval(
            self.contract,
            previous_request_id=previous["request_id"],
            snapshot=replacement_snapshot,
            kind="effect-intervention",
            source="codex_permission_request",
        )
        projected_previous = load_projection(self.contract)["requests"][
            previous["request_id"]
        ]
        self.assertEqual(projected_previous["status"], "replaced")
        self.assertEqual(
            replacement["replaced_request_id"], previous["request_id"]
        )
        self.assertTrue(replacement["replacement_identity"].startswith("sha256:"))
        self.assertFalse(replacement["prompt_shown"])
        with self.assertRaisesRegex(ApprovalInvariantError, "already decided"):
            self.decide(previous)

        self.show(
            replacement,
            snapshot=replacement_snapshot,
        )
        receipt = self.decide(
            replacement,
            snapshot=replacement_snapshot,
            current_snapshot=replacement_snapshot,
        )
        self.assertEqual(
            receipt["replacement_identity"],
            replacement["replacement_identity"],
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "already decided"):
            cancel_request(
                self.contract,
                replacement["request_id"],
                actor="cleanup-race-loser",
            )
        newer = {
            **replacement_snapshot,
            "card_sha256": "card-v3",
            "world_state_sha256": "world-v3",
        }
        with self.assertRaisesRegex(ApprovalInvariantError, "overwrite"):
            replace_typed_approval(
                self.contract,
                previous_request_id=replacement["request_id"],
                snapshot=newer,
                kind="effect-intervention",
                source="codex_permission_request",
            )

    def test_same_snapshot_timeout_refresh_requires_expiry_and_new_authority(
        self,
    ) -> None:
        previous = self.ask()
        before = authoritative_store_bytes(self.contract)
        with self.assertRaisesRegex(
            ApprovalInvariantError, "predecessor is not expired"
        ):
            replace_typed_approval(
                self.contract,
                previous_request_id=previous["request_id"],
                snapshot=self.snapshot,
                kind="effect-intervention",
                source="codex_permission_request",
            )
        self.assertEqual(authoritative_store_bytes(self.contract), before)

        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[0]["expires_at"] = "2000-01-01T00:00:00+00:00"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        expired_before = authoritative_store_bytes(self.contract)
        with self.assertRaisesRegex(
            ApprovalInvariantError, "must use a new request id"
        ):
            replace_typed_approval(
                self.contract,
                previous_request_id=previous["request_id"],
                request_id=previous["request_id"],
                snapshot=self.snapshot,
                kind="effect-intervention",
                source="codex_permission_request",
            )
        self.assertEqual(
            authoritative_store_bytes(self.contract), expired_before
        )
        old_binding = request_binding_receipt(
            self.contract, previous["request_id"]
        )
        refreshed = replace_typed_approval(
            self.contract,
            previous_request_id=previous["request_id"],
            snapshot=self.snapshot,
            kind="effect-intervention",
            source="codex_permission_request",
        )

        projection = load_projection(self.contract)
        projected_previous = projection["requests"][previous["request_id"]]
        self.assertNotEqual(refreshed["request_id"], previous["request_id"])
        self.assertEqual(refreshed["snapshot"], previous["snapshot"])
        self.assertEqual(projected_previous["status"], "replaced")
        self.assertTrue(
            refreshed["replacement_identity"].startswith("sha256:")
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "replaced"):
            decided_request_receipt(
                self.contract,
                old_binding,
                outcome="allow",
                provider="codex",
                session_id="session-a",
                actor="native-human",
            )

        self.show(refreshed)
        receipt = self.decide(
            refreshed,
            receipt_id="receipt-refresh",
        )
        self.assertEqual(receipt["request_id"], refreshed["request_id"])
        self.assertEqual(typed_receipts(self.contract), [receipt])

    def test_truncated_tail_is_rejected_after_complete_v2_prefix(self) -> None:
        self.ask()
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        store.write_text(
            json.dumps(rows[0], sort_keys=True) + "\n{" ,
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "incomplete tail"):
            load_projection(self.contract)

    def test_typed_receipt_is_revalidated_during_independent_replay(self) -> None:
        request = self.ask()
        self.show(request)
        self.decide(request)
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[-1]["typed_receipt"]["receipt_id"] = "forged-receipt"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "receipt"):
            typed_receipts(self.contract)

    def test_complete_prefix_crash_between_replacement_rows_fails_closed(self) -> None:
        previous = self.ask()
        replacement_snapshot = {
            **self.snapshot,
            "card_sha256": "card-v2",
            "world_state_sha256": "world-v2",
        }
        replace_typed_approval(
            self.contract,
            previous_request_id=previous["request_id"],
            snapshot=replacement_snapshot,
            kind="effect-intervention",
            source="codex_permission_request",
        )
        store = event_store_path(self.contract)
        rows = store.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 3)
        # Simulate a crash after the replacement tombstone reached disk but
        # before the fresh request row did.  The durable prefix is safe: it
        # contains no receipt, no open request, and no execution authority.
        store.write_text("\n".join(rows[:2]) + "\n", encoding="utf-8")
        projection = load_projection(self.contract)
        self.assertEqual(
            projection["requests"][previous["request_id"]]["status"],
            "replaced",
        )
        self.assertEqual(open_requests(self.contract), [])
        self.assertEqual(typed_receipts(self.contract), [])
        self.assertEqual(summary(self.contract)["execution_authorized"], 0)

    def test_legacy_idempotency_rejects_a_different_receipt(self) -> None:
        ask_approval(
            self.contract,
            intent_id="legacy",
            intent_revision=1,
            kind="event",
            target="legacy-target",
            provider="codex",
            session_id="session-a",
            source="codex_permission_request",
        )
        decide_approval(
            self.contract,
            kind="event",
            target="legacy-target",
            outcome="approved",
            provider="codex",
            session_id="session-a",
            actor="human",
            receipt_id="legacy-1",
        )
        with self.assertRaisesRegex(ApprovalInvariantError, "exactly one"):
            decide_approval(
                self.contract,
                kind="event",
                target="legacy-target",
                outcome="approved",
                provider="codex",
                session_id="session-a",
                actor="human",
                receipt_id="legacy-2",
            )


class ApprovalPairJourneyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.stream_owner = mock.patch.dict(
            os.environ,
            {
                "SULDE_GUARDIAN_STREAM_OWNER": "0",
                "SULDE_KB_HOME": str(Path(self.temporary.name) / "kb-home"),
            },
        )
        self.stream_owner.start()
        self.addCleanup(self.stream_owner.stop)
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.contract = Path(self.temporary.name) / "intent.json"
        write_contract(
            self.contract,
            default_contract(
                intent_id="resume-edit",
                objective="修改简历",
                acceptance_criteria=["事实不变"],
                workspace=self.root,
                mode="enforce",
                allowed_paths=["resume.md"],
                confirmed_by="human",
            ),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_non_native_text_keeps_human_proposal_question_pending(self) -> None:
        _proposal, digest = create_revision_proposal(
            self.contract,
            objective="按本人表达修改简历",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        self.assertEqual(summary(self.contract)["open"], 1)

        context = observe_user_prompt(
            {
                "client": "claude",
                "session_id": "human-review",
                "cwd": str(self.root),
                "intent_contract": str(self.contract),
                "prompt": "批准当前方案",
                "sulde_observation_source": "live_host_hook",
            },
            provider="claude",
        )

        self.assertIn("NATIVE_DECISION_REQUIRED", context)
        self.assertIn("decision remains pending", context)
        self.assertNotIn("CONTROL_RECORDED", context)
        report = summary(self.contract)
        self.assertEqual(report["open"], 1)
        self.assertEqual(report["by_outcome"].get("approved", 0), 0)
        self.assertNotIn(
            digest,
            load_contract(self.contract)["runtime"]["approved_proposal_digests"],
        )

    def test_repeated_non_native_text_never_creates_authority(self) -> None:
        _proposal, digest = create_revision_proposal(
            self.contract,
            objective="按本人表达修改简历",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        payload = {
            "client": "claude",
            "session_id": "human-review",
            "cwd": str(self.root),
            "intent_contract": str(self.contract),
            "prompt": "批准当前方案",
            "sulde_observation_source": "live_host_hook",
        }
        first = observe_user_prompt(payload, provider="claude")
        second = observe_user_prompt(payload, provider="claude")

        self.assertIn("NATIVE_DECISION_REQUIRED", first)
        self.assertIn("NATIVE_DECISION_REQUIRED", second)
        contract = load_contract(self.contract)
        matching = [
            row
            for row in contract["runtime"]["approval_receipts"]
            if row["action"] == "approve-proposal" and row["target"] == digest
        ]
        decisions = [
            row
            for row in contract["runtime"]["proposal_decisions"]
            if row["proposal_digest"] == digest
        ]
        self.assertEqual(matching, [])
        self.assertEqual(decisions, [])
        self.assertEqual(summary(self.contract)["open"], 1)

    def test_missing_proposal_question_is_restored_without_auto_authority(self) -> None:
        _proposal, digest = create_revision_proposal(
            self.contract,
            objective="按本人表达修改简历",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        event_store_path(self.contract).unlink()
        payload = {
            "client": "claude",
            "session_id": "restored-review",
            "cwd": str(self.root),
            "intent_contract": str(self.contract),
            "prompt": "批准当前方案",
            "sulde_observation_source": "live_host_hook",
        }

        first = observe_user_prompt(payload, provider="claude")
        self.assertIn("NATIVE_DECISION_REQUIRED", first)
        self.assertEqual(summary(self.contract)["open"], 1)
        self.assertNotIn(
            digest,
            load_contract(self.contract)["runtime"]["approved_proposal_digests"],
        )

        context = observe_user_prompt(payload, provider="claude")
        self.assertIn("NATIVE_DECISION_REQUIRED", context)
        self.assertNotIn("CONTROL_RECORDED", context)

    def test_initial_intent_card_can_be_confirmed_in_a_later_session(self) -> None:
        write_contract(
            self.contract,
            default_contract(
                intent_id="initial-intent",
                objective="按本人表达修改简历",
                acceptance_criteria=["事实不变"],
                workspace=self.root,
                mode="shadow",
                allowed_paths=["resume.md"],
                confirmed_by="unconfirmed",
                confirmation_required=True,
            ),
        )
        observe_user_prompt(
            {
                "client": "codex",
                "session_id": "question-session",
                "cwd": str(self.root),
                "intent_contract": str(self.contract),
                "prompt": "先核对当前任务边界",
                "sulde_observation_source": "live_host_hook",
            },
            provider="codex",
        )
        self.assertEqual(summary(self.contract)["open"], 1)

        preview = native_decision_preview(
            self.contract,
            kind="intent",
            decision="confirm",
            target="current",
            provider="codex",
            session_id="answer-session",
        )
        observed = observe_native_permission_request(
            {
                "client": "codex",
                "session_id": "answer-session",
                "cwd": str(self.root),
                "intent_contract": str(self.contract),
                "permission_mode": "default",
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(preview["command_argv"]),
                    "description": preview["description"],
                },
            },
            provider="codex",
        )
        result = execute_native_decision(
            self.contract,
            kind="intent",
            decision="confirm",
            target=preview["target"],
            provider="codex",
            session_id="answer-session",
        )

        self.assertEqual(observed["action"], "defer")
        self.assertEqual(result["status"], "recorded")
        confirmed = load_contract(self.contract)
        self.assertFalse(confirmed["confirmation"]["required"])
        self.assertEqual(confirmed["mode"], "enforce")
        self.assertEqual(
            confirmed["confirmed_by"],
            "codex-native-permission",
        )
        approval_summary = summary(self.contract)
        self.assertEqual(approval_summary["open"], 0)
        self.assertEqual(approval_summary["by_outcome"]["allow"], 1)
        self.assertEqual(approval_summary["by_outcome"]["cancelled"], 1)

    def test_session_start_restores_same_readable_request_without_authority(self) -> None:
        home = Path(self.temporary.name) / "kb-home"
        active = active_contract_path(home, self.root)
        write_contract(active, load_contract(self.contract))
        _proposal, _digest = create_revision_proposal(
            active,
            objective="按本人表达修改简历",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )

        old_context = decision_request_context(
            home,
            self.root,
            provider="codex",
            session_id="old-session",
        )
        new_context = decision_request_context(
            home,
            self.root,
            provider="codex",
            session_id="new-session",
        )

        self.assertIn("当前方案确认卡", new_context)
        self.assertIn("authority_transferred=false", new_context)
        self.assertIn("Codex 原生 Allow/Deny", old_context)
        self.assertIn("Codex 原生 Allow/Deny", new_context)
        self.assertNotIn("request=apr-", old_context)
        self.assertNotIn("request=apr-", new_context)
        self.assertEqual(summary(active)["open"], 1)

    def test_codex_proposal_uses_one_typed_lifecycle_and_applies_once(self) -> None:
        _proposal, digest = create_revision_proposal(
            self.contract,
            objective="按本人表达修改简历",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
            provider="codex",
        )
        store = event_store_path(self.contract)
        self.assertFalse(store.exists())

        preview = native_decision_preview(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="typed-only-session",
        )
        observed = observe_native_permission_request(
            {
                "client": "codex",
                "session_id": "typed-only-session",
                "cwd": str(self.root),
                "intent_contract": str(self.contract),
                "permission_mode": "default",
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(preview["command_argv"]),
                    "description": preview["description"],
                },
            },
            provider="codex",
        )
        self.assertEqual(observed["action"], "defer")
        result = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="typed-only-session",
        )
        repeated = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="typed-only-session",
        )

        rows = [json.loads(line) for line in store.read_text().splitlines()]
        self.assertEqual(
            [row["type"] for row in rows],
            [
                "approval.asked",
                "approval.prompt-observed",
                "approval.decided",
            ],
        )
        self.assertTrue(all(row.get("typed") is True for row in rows))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(repeated["status"], "already_decided")
        applied = load_contract(self.contract)
        self.assertEqual(applied["revision"], 2)
        self.assertEqual(applied["applied_proposal_digest"], digest)

    def test_expired_codex_request_refreshes_and_native_apply_is_exactly_once(
        self,
    ) -> None:
        _proposal, digest = create_revision_proposal(
            self.contract,
            objective="按本人表达修改简历",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
            provider="codex",
        )
        preview = native_decision_preview(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="timeout-refresh-session",
        )
        payload = {
            "client": "codex",
            "session_id": "timeout-refresh-session",
            "cwd": str(self.root),
            "intent_contract": str(self.contract),
            "permission_mode": "default",
            "tool_name": "Bash",
            "tool_input": {
                "command": shlex.join(preview["command_argv"]),
                "description": preview["description"],
            },
        }
        original = observe_native_permission_request(payload, provider="codex")
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[0]["expires_at"] = "2000-01-01T00:00:00+00:00"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

        expired = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="timeout-refresh-session",
        )
        refreshed = observe_native_permission_request(payload, provider="codex")
        applied = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="timeout-refresh-session",
        )
        repeated = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="timeout-refresh-session",
        )

        self.assertEqual(expired["status"], "approval_expired")
        self.assertNotEqual(refreshed["request_id"], original["request_id"])
        projection = load_projection(self.contract)
        self.assertEqual(
            projection["requests"][original["request_id"]]["status"],
            "replaced",
        )
        self.assertTrue(
            projection["requests"][refreshed["request_id"]]["prompt_shown"]
        )
        self.assertEqual(applied["status"], "applied")
        self.assertEqual(repeated["status"], "already_decided")
        self.assertEqual(len(typed_receipts(self.contract)), 1)
        self.assertEqual(
            typed_receipts(self.contract)[0]["request_id"],
            refreshed["request_id"],
        )
        self.assertEqual(load_contract(self.contract)["revision"], 2)

    def test_v4_task_epoch_drift_supersedes_before_apply(self) -> None:
        _proposal, digest = create_revision_proposal(
            self.contract,
            objective="按本人表达修改简历",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
            provider="codex",
        )
        preview = native_decision_preview(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="epoch-drift-session",
        )
        observe_native_permission_request(
            {
                "client": "codex",
                "session_id": "epoch-drift-session",
                "cwd": str(self.root),
                "intent_contract": str(self.contract),
                "permission_mode": "default",
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(preview["command_argv"]),
                    "description": preview["description"],
                },
            },
            provider="codex",
        )
        injected = False

        def drift(stage: str) -> None:
            nonlocal injected
            if stage != "after_prepared" or injected:
                return
            injected = True
            document = json.loads(self.contract.read_text())
            document["objective"] = "并发任务已经改变"
            material = (
                f"{document['intent_id']}\0{document['revision']}\0"
                f"{document['objective']}"
            ).encode("utf-8")
            document["task_epoch"] = hashlib.sha256(material).hexdigest()[:24]
            self.contract.write_text(
                json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        with mock.patch.object(
            guardian_recovery_module,
            "_native_decision_failpoint",
            side_effect=drift,
        ):
            with self.assertRaisesRegex(IntentGuardianError, "superseded"):
                execute_native_decision(
                    self.contract,
                    kind="proposal",
                    decision="approve",
                    target=digest,
                    provider="codex",
                    session_id="epoch-drift-session",
                )

        projection = load_native_projection(self.contract)
        transaction = next(iter(projection["transactions"].values()))
        self.assertEqual(transaction["binding"]["schema"], "sulde-native-transaction-binding-v5")
        self.assertEqual(transaction["stage"], "superseded")
        self.assertNotEqual(load_contract(self.contract).get("applied_proposal_digest"), digest)

    def test_after_prepared_crash_recovers_same_typed_request_exactly_once(self) -> None:
        _proposal, digest = create_revision_proposal(
            self.contract,
            objective="按本人表达修改简历",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
            provider="codex",
        )
        preview = native_decision_preview(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="prepared-crash-session",
        )
        observe_native_permission_request(
            {
                "client": "codex",
                "session_id": "prepared-crash-session",
                "cwd": str(self.root),
                "intent_contract": str(self.contract),
                "permission_mode": "default",
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(preview["command_argv"]),
                    "description": preview["description"],
                },
            },
            provider="codex",
        )

        def crash(stage: str) -> None:
            if stage == "after_prepared":
                raise RuntimeError("injected crash after prepared")

        with mock.patch.object(
            guardian_recovery_module,
            "_native_decision_failpoint",
            side_effect=crash,
        ):
            with self.assertRaisesRegex(RuntimeError, "after prepared"):
                execute_native_decision(
                    self.contract,
                    kind="proposal",
                    decision="approve",
                    target=digest,
                    provider="codex",
                    session_id="prepared-crash-session",
                )

        pending_projection = load_native_projection(self.contract)
        transaction = next(iter(pending_projection["transactions"].values()))
        self.assertEqual(transaction["stage"], "prepared")
        recovered = execute_native_decision(
            self.contract,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="prepared-crash-session",
        )

        rows = [
            json.loads(line)
            for line in event_store_path(self.contract).read_text().splitlines()
        ]
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.get("typed") is True for row in rows))
        final_projection = load_native_projection(self.contract)
        final = next(iter(final_projection["transactions"].values()))
        self.assertEqual(final["stage"], "committed")
        self.assertEqual(len(final_projection["transactions"]), 1)
        self.assertEqual(recovered["status"], "applied")
        self.assertEqual(load_contract(self.contract)["revision"], 2)

    def test_codex_agent_api_rejects_unbound_session_before_authority_write(self) -> None:
        _proposal, digest = create_revision_proposal(
            self.contract,
            objective="格式化确定的本地文件",
            acceptance_criteria=["只改变空白"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="agent",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="撤销未提交差异",
            provider="codex",
        )
        before_contract = self.contract.read_bytes()
        store = event_store_path(self.contract)
        before_store = store.read_bytes() if store.is_file() else None
        cases = (
            ("", {}, "non-empty session_id"),
            ("x" * 201, {}, "up to 200"),
            (
                "provided-session",
                {"CODEX_THREAD_ID": "observed-session"},
                "does not match CODEX_THREAD_ID",
            ),
        )
        for session_id, environment, message in cases:
            with self.subTest(session_id=session_id[:20], environment=environment):
                with mock.patch.dict(os.environ, environment, clear=False):
                    with self.assertRaisesRegex(IntentGuardianError, message):
                        decide_proposal_as_agent(
                            self.contract,
                            digest,
                            rationale="受限 Agent 门已满足",
                            evidence=["单文件且无外部效果"],
                            provider="codex",
                            session_id=session_id,
                        )
                self.assertEqual(self.contract.read_bytes(), before_contract)
                self.assertEqual(
                    store.read_bytes() if store.is_file() else None,
                    before_store,
                )

    def test_external_write_uses_readable_scope_and_never_opens_event_question(self) -> None:
        session = GuardianSession(self.contract, provider="codex")
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "event-review",
                "tool_name": "mcp__github__create_comment",
                "tool_input": {
                    "repo": "example/project",
                    "body": "public text",
                },
            },
            phase="started",
            provider="codex",
        )
        denied = session.observe(event)
        self.assertEqual(denied.action, "deny")
        self.assertFalse(denied.awaiting_human)
        self.assertEqual(summary(self.contract)["open"], 0)

        context = observe_user_prompt(
            {
                "client": "codex",
                "session_id": "event-review",
                "cwd": str(self.root),
                "intent_contract": str(self.contract),
                "prompt": "批准事件 " + denied.fingerprint,
                "sulde_observation_source": "live_host_hook",
            },
            provider="codex",
        )

        self.assertIn("LEGACY_TEXT_CONTROL_IGNORED", context)
        self.assertEqual(summary(self.contract)["open"], 0)
        self.assertEqual(load_contract(self.contract)["approved_event_fingerprints"], [])

    def test_legacy_event_questions_are_cancelled_without_granting_authority(self) -> None:
        fingerprint = "c" * 64
        ask_approval(
            self.contract,
            intent_id="legacy-intent",
            intent_revision=1,
            kind="event",
            target=fingerprint,
            provider="codex",
            session_id="event-review",
            source="legacy-fixture",
        )
        self.assertEqual(summary(self.contract)["open"], 1)
        self.assertEqual(
            cancel_open_requests(
                self.contract,
                kinds={"event"},
                actor="event-fingerprint-approval-retirement",
            ),
            1,
        )
        self.assertEqual(summary(self.contract)["open"], 0)
        self.assertNotIn(
            fingerprint,
            load_contract(self.contract)["approved_event_fingerprints"],
        )


if __name__ == "__main__":
    unittest.main()

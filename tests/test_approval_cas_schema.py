from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from approval_cas_schema import (  # noqa: E402
    ApprovalCASSchemaError,
    approval_decision_identity,
    approval_request_identity,
    canonical_identity,
    fresh_replacement_identity,
    snapshot_identity,
)


class MagicProbe:
    def __init__(self) -> None:
        self.calls = 0

    def _called(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("untrusted magic method was invoked")

    __str__ = _called
    __int__ = _called
    __bool__ = _called
    __iter__ = _called
    __eq__ = _called
    __hash__ = _called


class DictSubclass(dict):
    pass


class ApprovalCASSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = {
            "card_sha256": "card-v2",
            "provider": "codex",
            "session_id": "session-a",
            "lane_sha256": "lane-a",
            "target_sha256": "target-a",
            "revision": 7,
            "journal_sha256": "journal-v1",
            "effect_sha256": "effect-v1",
            "world_state_sha256": "world-v1",
        }
        self.request = {
            "request_id": "apr-new",
            "snapshot": deepcopy(self.snapshot),
        }
        self.decision = {
            "request_id": "apr-new",
            "receipt_id": "receipt-new",
            "outcome": "allow",
            "snapshot": deepcopy(self.snapshot),
        }
        self.previous = {
            "request_id": "apr-old",
            "snapshot": {**self.snapshot, "card_sha256": "card-v1"},
        }

    def test_snapshot_identity_is_order_independent_and_type_tagged(self) -> None:
        reverse = dict(reversed(tuple(self.snapshot.items())))
        first = snapshot_identity(self.snapshot)
        second = snapshot_identity(reverse)
        self.assertEqual(first, second)
        self.assertRegex(first, r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(first, canonical_identity("opaque", self.snapshot))

    def test_request_and_decision_have_stable_distinct_identities(self) -> None:
        request_id = approval_request_identity(self.request)
        decision_id = approval_decision_identity(
            self.decision,
            request=self.request,
            current_snapshot=self.snapshot,
        )
        self.assertEqual(request_id, approval_request_identity(deepcopy(self.request)))
        self.assertNotEqual(request_id, decision_id)

    def test_identity_does_not_mutate_inputs(self) -> None:
        request_before = deepcopy(self.request)
        decision_before = deepcopy(self.decision)
        approval_decision_identity(
            self.decision,
            request=self.request,
            current_snapshot=self.snapshot,
        )
        self.assertEqual(self.request, request_before)
        self.assertEqual(self.decision, decision_before)

    def test_snapshot_rejects_missing_and_extra_fields(self) -> None:
        for malformed in (
            {key: value for key, value in self.snapshot.items() if key != "provider"},
            {**self.snapshot, "extra": "authority"},
        ):
            with self.subTest(fields=tuple(malformed)):
                with self.assertRaises(ApprovalCASSchemaError):
                    snapshot_identity(malformed)

    def test_snapshot_rejects_bool_string_and_negative_revision(self) -> None:
        for revision in (True, "7", -1):
            with self.subTest(revision=revision):
                with self.assertRaises(ApprovalCASSchemaError):
                    snapshot_identity({**self.snapshot, "revision": revision})

    def test_snapshot_rejects_non_string_authority_fields(self) -> None:
        for value in (7, False, ""):
            with self.subTest(value=value):
                with self.assertRaises(ApprovalCASSchemaError):
                    snapshot_identity({**self.snapshot, "provider": value})

    def test_plain_container_boundary_is_exact(self) -> None:
        with self.assertRaises(ApprovalCASSchemaError):
            snapshot_identity(DictSubclass(self.snapshot))
        with self.assertRaises(ApprovalCASSchemaError):
            approval_request_identity(DictSubclass(self.request))

    def test_magic_objects_are_rejected_without_callbacks(self) -> None:
        probe = MagicProbe()
        with self.assertRaises(ApprovalCASSchemaError):
            snapshot_identity(probe)
        self.assertEqual(probe.calls, 0)

    def test_request_rejects_missing_extra_or_coerced_id(self) -> None:
        malformed = (
            {"snapshot": self.snapshot},
            {**self.request, "status": "asked"},
            {**self.request, "request_id": 7},
            {**self.request, "request_id": ""},
        )
        for value in malformed:
            with self.subTest(value=value):
                with self.assertRaises(ApprovalCASSchemaError):
                    approval_request_identity(value)

    def test_decision_rejects_missing_extra_and_invalid_outcome(self) -> None:
        malformed = (
            {key: value for key, value in self.decision.items() if key != "receipt_id"},
            {**self.decision, "extra": "field"},
            {**self.decision, "outcome": "approve"},
            {**self.decision, "receipt_id": 9},
        )
        for value in malformed:
            with self.subTest(value=value):
                with self.assertRaises(ApprovalCASSchemaError):
                    approval_decision_identity(
                        value,
                        request=self.request,
                        current_snapshot=self.snapshot,
                    )

    def test_decision_rejects_different_request(self) -> None:
        with self.assertRaisesRegex(ApprovalCASSchemaError, "request_id"):
            approval_decision_identity(
                {**self.decision, "request_id": "apr-other"},
                request=self.request,
                current_snapshot=self.snapshot,
            )

    def test_decision_rejects_old_card(self) -> None:
        with self.assertRaisesRegex(ApprovalCASSchemaError, "card_sha256"):
            approval_decision_identity(
                {
                    **self.decision,
                    "snapshot": {**self.snapshot, "card_sha256": "card-v1"},
                },
                request=self.request,
                current_snapshot=self.snapshot,
            )

    def test_decision_rejects_stale_world(self) -> None:
        with self.assertRaisesRegex(ApprovalCASSchemaError, "world_state_sha256"):
            approval_decision_identity(
                self.decision,
                request=self.request,
                current_snapshot={
                    **self.snapshot,
                    "world_state_sha256": "world-v2",
                },
            )

    def test_decision_rejects_any_snapshot_drift(self) -> None:
        for field in self.snapshot:
            changed = 8 if field == "revision" else f"changed-{field}"
            with self.subTest(field=field):
                with self.assertRaisesRegex(ApprovalCASSchemaError, field):
                    approval_decision_identity(
                        self.decision,
                        request=self.request,
                        current_snapshot={**self.snapshot, field: changed},
                    )

    def test_fresh_replacement_has_a_stable_identity(self) -> None:
        replacement = fresh_replacement_identity(
            self.previous,
            self.request,
            current_snapshot=self.snapshot,
        )
        self.assertEqual(
            replacement,
            fresh_replacement_identity(
                deepcopy(self.previous),
                deepcopy(self.request),
                current_snapshot=deepcopy(self.snapshot),
            ),
        )
        self.assertNotEqual(replacement, approval_request_identity(self.request))

    def test_replacement_requires_new_request_and_new_card(self) -> None:
        with self.assertRaisesRegex(ApprovalCASSchemaError, "request_id"):
            fresh_replacement_identity(
                self.previous,
                {**self.request, "request_id": "apr-old"},
                current_snapshot=self.snapshot,
            )
        with self.assertRaisesRegex(ApprovalCASSchemaError, "card_sha256"):
            fresh_replacement_identity(
                self.previous,
                {
                    **self.request,
                    "snapshot": {**self.snapshot, "card_sha256": "card-v1"},
                },
                current_snapshot={**self.snapshot, "card_sha256": "card-v1"},
            )

    def test_replacement_rejects_stale_world_and_noncanonical_previous(self) -> None:
        with self.assertRaisesRegex(ApprovalCASSchemaError, "world_state_sha256"):
            fresh_replacement_identity(
                self.previous,
                self.request,
                current_snapshot={
                    **self.snapshot,
                    "world_state_sha256": "world-v2",
                },
            )
        with self.assertRaises(ApprovalCASSchemaError):
            fresh_replacement_identity(
                {**self.previous, "status": "expired"},
                self.request,
                current_snapshot=self.snapshot,
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from human_grant import (  # noqa: E402
    HUMAN_CARD_SCHEMA,
    HUMAN_RECEIPT_SCHEMA,
    HUMAN_REQUEST_SCHEMA,
    HumanGrantError,
    RISK_EXTERNAL_OR_DESTRUCTIVE,
    RISK_INTEGRITY_UNKNOWN,
    RISK_READ,
    RISK_REVERSIBLE_LOCAL,
    canonical_digest,
    classify_risk,
    consume_human_grant,
    consumption_identity,
    create_human_grant,
    grant_binding_identity,
)


class DictSubclass(dict):
    pass


class MagicProbe:
    def __init__(self) -> None:
        self.calls = 0

    def called(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("untrusted callback invoked")

    __str__ = called
    __bool__ = called
    __iter__ = called
    __eq__ = called
    __deepcopy__ = called


class HumanGrantV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = {
            "provider": "codex",
            "session_id": "managed:l3:r2-h01-human-grant-v2",
            "task_epoch": "0123456789abcdef01234567",
            "subject": {
                "kind": "agent",
                "id": "guardian-r2-worker-h01",
            },
            "capability": {
                "name": "workspace.edit",
                "risk_class": RISK_REVERSIBLE_LOCAL,
                "risk_facts": self.risk_facts(),
            },
            "effect": {
                "operation": "replace",
                "resource": "scripts/kb/human_grant.py",
                "after_sha256": self.sha("after"),
            },
            "constraints": {
                "owned_paths": ["scripts/kb/human_grant.py"],
                "max_uses": 1,
            },
            "world_state": {
                "resource": {
                    "sha256": self.sha("before"),
                    "revision": 7,
                },
                "task": "H01",
            },
            "expires_at": "2026-08-27T10:00:00+00:00",
            "verifier": {
                "kind": "native-human",
                "id": "reviewer-1",
            },
        }
        self.material = self.make_material()

    @staticmethod
    def sha(label: str) -> str:
        return canonical_digest("fixture", {"label": label})

    @staticmethod
    def risk_facts(**changes: object) -> dict:
        value = {
            "operation": "write",
            "local_effect": True,
            "reversible": True,
            "external_effect": False,
            "destructive": False,
            "integrity_verified": True,
        }
        value.update(changes)
        return value

    def make_material(self) -> dict:
        binding_sha256 = grant_binding_identity(self.binding)
        return {
            **deepcopy(self.binding),
            "card": {
                "schema": HUMAN_CARD_SCHEMA,
                "card_id": "card-h01-1",
                "binding_sha256": binding_sha256,
                "display_sha256": self.sha("display"),
            },
            "request": {
                "schema": HUMAN_REQUEST_SCHEMA,
                "request_id": "request-h01-1",
                "card_id": "card-h01-1",
                "binding_sha256": binding_sha256,
                "requested_at": "2026-08-26T08:00:00+00:00",
            },
            "receipt": {
                "schema": HUMAN_RECEIPT_SCHEMA,
                "receipt_id": "receipt-h01-1",
                "request_id": "request-h01-1",
                "binding_sha256": binding_sha256,
                "outcome": "allow",
                "provider": "codex",
                "session_id": "managed:l3:r2-h01-human-grant-v2",
                "task_epoch": "0123456789abcdef01234567",
                "verifier": {
                    "kind": "native-human",
                    "id": "reviewer-1",
                },
                "decided_at": "2026-08-26T08:01:00+00:00",
                "authority": "human",
                "channel": "native_typed_receipt",
            },
        }

    def current(self, **changes: object) -> dict:
        value = {
            key: deepcopy(self.binding[key])
            for key in (
                "provider",
                "session_id",
                "task_epoch",
                "subject",
                "capability",
                "effect",
                "constraints",
                "world_state",
                "verifier",
            )
        }
        value.update(changes)
        return value

    def test_closed_risk_taxonomy_covers_all_four_classes(self) -> None:
        cases = (
            (
                self.risk_facts(
                    operation="read",
                    local_effect=False,
                    reversible=False,
                ),
                RISK_READ,
            ),
            (self.risk_facts(), RISK_REVERSIBLE_LOCAL),
            (
                self.risk_facts(external_effect=True),
                RISK_EXTERNAL_OR_DESTRUCTIVE,
            ),
            (
                self.risk_facts(integrity_verified=False),
                RISK_INTEGRITY_UNKNOWN,
            ),
        )
        for facts, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(classify_risk(facts), expected)

    def test_read_requires_internally_consistent_no_effect_facts(
        self,
    ) -> None:
        for contradictory_field in ("local_effect", "reversible"):
            facts = self.risk_facts(
                operation="read",
                local_effect=False,
                reversible=False,
            )
            facts[contradictory_field] = True
            with self.subTest(contradictory_field=contradictory_field):
                self.assertEqual(
                    classify_risk(facts), RISK_INTEGRITY_UNKNOWN
                )

    def test_unknown_or_malformed_risk_facts_never_become_safer(self) -> None:
        cases = (
            {},
            {
                key: value
                for key, value in self.risk_facts().items()
                if key != "destructive"
            },
            {**self.risk_facts(), "unknown": False},
            {**self.risk_facts(), "reversible": 1},
            {**self.risk_facts(), "operation": "rename-later"},
            DictSubclass(self.risk_facts()),
            MagicProbe(),
        )
        for facts in cases:
            with self.subTest(kind=type(facts).__name__):
                self.assertEqual(
                    classify_risk(facts), RISK_INTEGRITY_UNKNOWN
                )
        probe = cases[-1]
        self.assertEqual(probe.calls, 0)

    def test_external_or_destructive_is_closed_over_both_facts(self) -> None:
        self.assertEqual(
            classify_risk(
                self.risk_facts(operation="read", destructive=True)
            ),
            RISK_EXTERNAL_OR_DESTRUCTIVE,
        )
        self.assertEqual(
            classify_risk(
                self.risk_facts(operation="read", external_effect=True)
            ),
            RISK_EXTERNAL_OR_DESTRUCTIVE,
        )

    def test_canonical_identity_is_order_independent_and_domain_separated(
        self,
    ) -> None:
        left = {"é": [1, True, None], "a": {"z": 2}}
        right = {"a": {"z": 2}, "é": [1, True, None]}
        self.assertEqual(
            canonical_digest("same", left),
            canonical_digest("same", right),
        )
        self.assertNotEqual(
            canonical_digest("same", left),
            canonical_digest("other", left),
        )

    def test_grant_creation_binds_every_authority_domain_without_mutation(
        self,
    ) -> None:
        before = deepcopy(self.material)
        grant = create_human_grant(self.material)
        self.assertEqual(self.material, before)
        for field in (
            "provider",
            "session_id",
            "task_epoch",
            "subject",
            "capability",
            "effect",
            "constraints",
            "card",
            "request",
            "receipt",
            "world_state",
            "expires_at",
            "verifier",
        ):
            self.assertEqual(grant[field], self.material[field])
        self.assertEqual(grant["consumption"]["state"], "available")
        self.assertEqual(
            grant["binding_sha256"],
            grant_binding_identity(
                {
                    key: self.material[key]
                    for key in self.binding
                }
            ),
        )

    def test_created_grant_does_not_alias_mutable_inputs(self) -> None:
        grant = create_human_grant(self.material)
        self.material["effect"]["resource"] = "replacement"
        self.material["world_state"]["resource"]["revision"] = 99
        self.assertEqual(
            grant["effect"]["resource"],
            "scripts/kb/human_grant.py",
        )
        self.assertEqual(
            grant["world_state"]["resource"]["revision"], 7
        )

    def test_unchanged_grant_consumes_once_into_direct_execution_authority(
        self,
    ) -> None:
        grant = create_human_grant(self.material)
        available = consumption_identity(grant["consumption"])
        result = consume_human_grant(
            grant,
            current=self.current(),
            expected_consumption_sha256=available,
            now="2026-08-26T09:00:00+00:00",
        )
        self.assertEqual(result["status"], "authorized")
        self.assertTrue(result["execution_authorized"])
        self.assertFalse(
            result["default_policy_recheck_required"]
        )
        self.assertTrue(
            result["authority"]["execution_authorized"]
        )
        self.assertEqual(
            result["authority"]["effect"], self.binding["effect"]
        )
        self.assertEqual(
            result["grant"]["consumption"]["state"], "consumed"
        )
        self.assertEqual(
            result["cas"]["expected_consumption_sha256"],
            available,
        )
        self.assertNotEqual(
            result["cas"]["next_consumption_sha256"], available
        )
        self.assertEqual(
            grant["consumption"]["state"], "available"
        )

    def test_duplicate_consumption_of_committed_projection_is_rejected(
        self,
    ) -> None:
        grant = create_human_grant(self.material)
        first = consume_human_grant(
            grant,
            current=self.current(),
            expected_consumption_sha256=consumption_identity(
                grant["consumption"]
            ),
            now="2026-08-26T09:00:00+00:00",
        )
        with self.assertRaisesRegex(
            HumanGrantError, "already consumed"
        ):
            consume_human_grant(
                first["grant"],
                current=self.current(),
                expected_consumption_sha256=first["cas"][
                    "next_consumption_sha256"
                ],
                now="2026-08-26T09:01:00+00:00",
            )

    def test_concurrent_projections_share_one_cas_precondition_and_transition(
        self,
    ) -> None:
        grant = create_human_grant(self.material)
        expected = consumption_identity(grant["consumption"])
        first = consume_human_grant(
            grant,
            current=self.current(),
            expected_consumption_sha256=expected,
            now="2026-08-26T09:00:00+00:00",
        )
        second = consume_human_grant(
            deepcopy(grant),
            current=self.current(),
            expected_consumption_sha256=expected,
            now="2026-08-26T09:00:00+00:00",
        )
        self.assertEqual(first, second)
        self.assertEqual(first["cas"]["expected_version"], 0)
        self.assertEqual(first["cas"]["next_version"], 1)
        with self.assertRaisesRegex(HumanGrantError, "CAS mismatch"):
            consume_human_grant(
                grant,
                current=self.current(),
                expected_consumption_sha256=first["cas"][
                    "next_consumption_sha256"
                ],
                now="2026-08-26T09:00:00+00:00",
            )

    def test_world_drift_returns_stable_readable_diff_and_does_not_mutate(
        self,
    ) -> None:
        grant = create_human_grant(self.material)
        before = deepcopy(grant)
        drifted = self.current(
            world_state={
                "resource": {"revision": 8, "etag": "new"},
                "task": "H02",
            }
        )
        first = consume_human_grant(
            grant,
            current=drifted,
            expected_consumption_sha256=consumption_identity(
                grant["consumption"]
            ),
            now="2026-08-26T09:00:00+00:00",
        )
        second = consume_human_grant(
            deepcopy(grant),
            current=deepcopy(drifted),
            expected_consumption_sha256=consumption_identity(
                grant["consumption"]
            ),
            now="2026-08-26T09:00:00+00:00",
        )
        self.assertEqual(first, second)
        self.assertEqual(
            first["status"], "fresh_decision_required"
        )
        self.assertFalse(first["execution_authorized"])
        self.assertTrue(first["fresh_decision_required"])
        self.assertIsNone(first["cas"])
        self.assertEqual(
            [row["path"] for row in first["world_diff"]],
            [
                "/resource/etag",
                "/resource/revision",
                "/resource/sha256",
                "/task",
            ],
        )
        self.assertEqual(grant, before)
        self.assertEqual(first["grant"], before)

    def test_text_or_copied_digest_without_typed_receipt_is_rejected(
        self,
    ) -> None:
        for receipt in (
            "approved",
            {
                "binding_sha256": self.material["receipt"][
                    "binding_sha256"
                ]
            },
        ):
            candidate = deepcopy(self.material)
            candidate["receipt"] = receipt
            with self.subTest(receipt=receipt):
                with self.assertRaises(HumanGrantError):
                    create_human_grant(candidate)

    def test_timeout_display_silence_and_chat_are_never_authority(
        self,
    ) -> None:
        for channel in ("timeout", "display", "silence", "chat"):
            candidate = deepcopy(self.material)
            candidate["receipt"]["channel"] = channel
            with self.subTest(channel=channel):
                with self.assertRaisesRegex(
                    HumanGrantError, "not execution authority"
                ):
                    create_human_grant(candidate)

    def test_receipt_rejects_old_or_mismatched_provider_session_and_epoch(
        self,
    ) -> None:
        for field, value in (
            ("provider", "claude"),
            ("session_id", "old-session"),
            ("task_epoch", "f" * 24),
        ):
            candidate = deepcopy(self.material)
            candidate["receipt"][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(HumanGrantError, field):
                    create_human_grant(candidate)

    def test_current_provider_session_and_epoch_mismatch_are_rejected(
        self,
    ) -> None:
        grant = create_human_grant(self.material)
        expected = consumption_identity(grant["consumption"])
        for field, value in (
            ("provider", "claude"),
            ("session_id", "old-session"),
            ("task_epoch", "f" * 24),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(HumanGrantError, field):
                    consume_human_grant(
                        grant,
                        current=self.current(**{field: value}),
                        expected_consumption_sha256=expected,
                        now="2026-08-26T09:00:00+00:00",
                    )

    def test_expiry_boundary_is_fail_closed(self) -> None:
        grant = create_human_grant(self.material)
        with self.assertRaisesRegex(HumanGrantError, "expired"):
            consume_human_grant(
                grant,
                current=self.current(),
                expected_consumption_sha256=consumption_identity(
                    grant["consumption"]
                ),
                now=self.binding["expires_at"],
            )

    def test_tampering_any_bound_grant_domain_is_rejected(
        self,
    ) -> None:
        original = create_human_grant(self.material)
        changes = {
            "subject": {"kind": "agent", "id": "other"},
            "capability": {
                **original["capability"],
                "name": "other",
            },
            "constraints": {"max_uses": 2},
            "world_state": {"resource": {"revision": 9}},
            "expires_at": "2026-08-28T10:00:00+00:00",
            "verifier": {
                "kind": "native-human",
                "id": "other",
            },
        }
        for field, value in changes.items():
            grant = deepcopy(original)
            grant[field] = value
            with self.subTest(field=field):
                with self.assertRaises(HumanGrantError):
                    consume_human_grant(
                        grant,
                        current=self.current(),
                        expected_consumption_sha256=consumption_identity(
                            original["consumption"]
                        ),
                        now="2026-08-26T09:00:00+00:00",
                    )

    def test_resource_replacement_is_rejected_not_reclassified_as_world_drift(
        self,
    ) -> None:
        grant = create_human_grant(self.material)
        replacement = {
            **self.binding["effect"],
            "resource": "scripts/kb/other.py",
        }
        with self.assertRaisesRegex(
            HumanGrantError, "current.effect"
        ):
            consume_human_grant(
                grant,
                current=self.current(effect=replacement),
                expected_consumption_sha256=consumption_identity(
                    grant["consumption"]
                ),
                now="2026-08-26T09:00:00+00:00",
            )

    def test_card_request_receipt_binding_tampering_and_deny_are_rejected(
        self,
    ) -> None:
        cases = []
        for section, field, value in (
            ("card", "binding_sha256", self.sha("copied")),
            ("request", "card_id", "other-card"),
            ("request", "binding_sha256", self.sha("copied")),
            ("receipt", "request_id", "other-request"),
            ("receipt", "binding_sha256", self.sha("copied")),
            ("receipt", "outcome", "deny"),
            ("receipt", "authority", "agent"),
        ):
            candidate = deepcopy(self.material)
            candidate[section][field] = value
            cases.append((section, field, candidate))
        for section, field, candidate in cases:
            with self.subTest(section=section, field=field):
                with self.assertRaises(HumanGrantError):
                    create_human_grant(candidate)

    def test_non_plain_json_and_extra_or_missing_fields_are_rejected(
        self,
    ) -> None:
        cases = (
            DictSubclass(self.material),
            {**self.material, "extra": "authority"},
            {
                key: value
                for key, value in self.material.items()
                if key != "provider"
            },
            {
                **self.material,
                "constraints": {"limit": float("nan")},
            },
            {
                **self.material,
                "effect": {"probe": MagicProbe()},
            },
        )
        for candidate in cases:
            with self.subTest(kind=type(candidate).__name__):
                with self.assertRaises(HumanGrantError):
                    create_human_grant(candidate)
        probe = cases[-1]["effect"]["probe"]
        self.assertEqual(probe.calls, 0)

    def test_current_non_plain_json_and_wrong_consumption_digest_fail_closed(
        self,
    ) -> None:
        grant = create_human_grant(self.material)
        expected = consumption_identity(grant["consumption"])
        with self.assertRaises(HumanGrantError):
            consume_human_grant(
                grant,
                current=DictSubclass(self.current()),
                expected_consumption_sha256=expected,
                now="2026-08-26T09:00:00+00:00",
            )
        with self.assertRaisesRegex(HumanGrantError, "CAS mismatch"):
            consume_human_grant(
                grant,
                current=self.current(),
                expected_consumption_sha256=self.sha(
                    "foreign-state"
                ),
                now="2026-08-26T09:00:00+00:00",
            )

    def test_receipt_timing_and_timezone_are_strict(self) -> None:
        for value in (
            "2026-08-26T08:02:00+00:00",
            "2026-08-26T08:00:00",
        ):
            candidate = deepcopy(self.material)
            candidate["request"]["requested_at"] = value
            with self.subTest(value=value):
                with self.assertRaises(HumanGrantError):
                    create_human_grant(candidate)
        candidate = deepcopy(self.material)
        candidate["receipt"][
            "decided_at"
        ] = self.binding["expires_at"]
        with self.assertRaisesRegex(HumanGrantError, "expiry"):
            create_human_grant(candidate)

        grant = create_human_grant(self.material)
        with self.assertRaisesRegex(HumanGrantError, "future"):
            consume_human_grant(
                grant,
                current=self.current(),
                expected_consumption_sha256=consumption_identity(
                    grant["consumption"]
                ),
                now="2026-08-26T08:00:30+00:00",
            )

    def test_risk_claim_must_equal_complete_derived_taxonomy(
        self,
    ) -> None:
        for claimed in (
            RISK_READ,
            RISK_EXTERNAL_OR_DESTRUCTIVE,
            "low",
            "",
        ):
            candidate = deepcopy(self.material)
            candidate["capability"]["risk_class"] = claimed
            with self.subTest(claimed=claimed):
                with self.assertRaises(HumanGrantError):
                    create_human_grant(candidate)


if __name__ == "__main__":
    unittest.main()

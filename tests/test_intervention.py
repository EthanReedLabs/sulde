from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unicodedata
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
import sys

sys.path.insert(0, str(SCRIPT_DIR))

from intervention import (  # noqa: E402
    InterventionError,
    LEGACY_READ_DEBT_ACTOR,
    LEGACY_READ_DEBT_EVIDENCE,
    LEGACY_GIT_CONTROL_DEBT_ACTOR,
    LEGACY_GIT_CONTROL_DEBT_EVIDENCE,
    archive_store,
    authorize_system_retry,
    begin_attempt,
    blocking_attempts,
    readiness_blocking_attempts,
    terminal_quarantined_attempts,
    canonical_resource_key,
    effect_operation_fingerprint,
    event_store_path,
    git_ref_verification_digest,
    inventory,
    load_projection,
    mark_attempt_result,
    mark_attempt_unknown,
    material_event_blocker,
    projection_path,
    reconcile_legacy_git_control_debt,
    resolve_attempt_target,
    resolve_intervention,
    settle_legacy_read_only_debt,
    restore_authoritative_store,
    retry_grant_for_event,
    summary,
    verifier_matches,
    verify_from_read,
)


class InterventionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "kb"
        self.contract = self.home / "intent" / "workspaces" / "one.active.json"
        self.contract.parent.mkdir(parents=True)
        self.contract.write_text("{}\n", encoding="utf-8")
        self.environment = mock.patch.dict(
            os.environ,
            {
                "SULDE_KB_HOME": str(self.home),
                "SULDE_NOTIFY": "off",
                "SULDE_GUARDIAN_STREAM_OWNER": "0",
            },
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def begin(
        self,
        key: str = "dispatch-1",
        *,
        fingerprint: str = "f" * 64,
        verification_kind: str = "existence",
        verification_sha256: str = "",
    ) -> dict:
        return begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint=fingerprint,
            source_event_id=f"event-{key}",
            capability="mcp:docs:update_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key=key,
            verification_kind=verification_kind,
            verification_sha256=verification_sha256,
        )

    def test_bash_maintenance_uses_only_explicit_machine_verifiers(self) -> None:
        for capability in (
            "tool:codex_plugin_install_verify",
            "tool:codex_plugin_cachebuster_verify",
            "tool:sulde_scheduler_reconcile_verify",
            "tool:sulde_launcher_refresh_verify",
        ):
            with self.subTest(capability=capability):
                self.assertTrue(verifier_matches("tool:Bash", capability))
        for capability in (
            "tool:Read",
            "tool:sulde_scheduler_reconcile",
            "tool:sulde_launcher_refresh",
        ):
            with self.subTest(capability=capability):
                self.assertFalse(verifier_matches("tool:Bash", capability))

    def test_scheduler_and_launcher_machine_verifiers_settle_exact_bash_attempts(self) -> None:
        cases = (
            (
                "scheduler",
                "[host-local:sulde-scheduler]",
                "tool:sulde_scheduler_reconcile_verify",
            ),
            (
                "launcher",
                "[host-local:sulde-launchers]",
                "tool:sulde_launcher_refresh_verify",
            ),
        )
        for index, (name, target, verifier) in enumerate(cases, start=1):
            with self.subTest(name=name):
                expected = hashlib.sha256(f"{name}-postcondition".encode()).hexdigest()
                arguments_digest = hashlib.sha256(f"{name}-command".encode()).hexdigest()
                resource_key = canonical_resource_key(target, kind="opaque")
                resource_context = {"schema": "exact", "value": target}
                attempt = begin_attempt(
                    self.contract,
                    intent_id="intent-one",
                    intent_revision=1,
                    fingerprint=f"{index}" * 64,
                    operation_fingerprint=effect_operation_fingerprint(
                        provider="codex",
                        capability="tool:Bash",
                        target=target,
                        resource_key=resource_key,
                        effect="external_write",
                        arguments_digest=arguments_digest,
                    ),
                    operation_arguments_digest=arguments_digest,
                    source_event_id=f"{name}-maintenance",
                    capability="tool:Bash",
                    target=target,
                    resource_key=resource_key,
                    resource_context=resource_context,
                    effect="external_write",
                    provider="codex",
                    session_id="thread-one",
                    idempotency_key=f"{name}-maintenance",
                    verification_kind="content",
                    verification_sha256=expected,
                )
                mark_attempt_result(
                    self.contract,
                    attempt["attempt_id"],
                    success=True,
                )
                self.assertEqual(
                    verify_from_read(
                        self.contract,
                        provider="codex",
                        session_id="thread-one",
                        capability="tool:Read",
                        target=target,
                        resource_key=resource_key,
                        resource_context=resource_context,
                        verification_event_id=f"wrong-{name}-verifier",
                        explicit_attempt_id=attempt["attempt_id"],
                        evidence={"content": [expected]},
                    ),
                    [],
                )
                verified = verify_from_read(
                    self.contract,
                    provider="codex",
                    session_id="thread-one",
                    capability=verifier,
                    target=target,
                    resource_key=resource_key,
                    resource_context=resource_context,
                    verification_event_id=f"matching-{name}-verifier",
                    explicit_attempt_id=attempt["attempt_id"],
                    evidence={"content": [expected]},
                )
                self.assertEqual(
                    [row["attempt_id"] for row in verified],
                    [attempt["attempt_id"]],
                )
                self.assertEqual(
                    load_projection(self.contract)["attempts"][attempt["attempt_id"]][
                        "state"
                    ],
                    "system_verified",
                )

    def test_system_settles_only_typed_legacy_read_debt_with_fixed_abort(self) -> None:
        target = "doc://read-only-debt"
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="1" * 64,
            source_event_id="legacy-read-only-debt",
            capability="mcp:docs:get_document",
            target=target,
            resource_key=canonical_resource_key(target, kind="uri"),
            effect="read",
            provider="codex",
            session_id="thread-one",
            idempotency_key="legacy-read-only-debt",
        )
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="legacy runtime escalated an interrupted read",
        )

        resolved = settle_legacy_read_only_debt(
            self.contract,
            intervention["intervention_id"],
        )
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["decision"], "abort")
        self.assertEqual(resolved["actor"], LEGACY_READ_DEBT_ACTOR)
        self.assertEqual(resolved["evidence"], LEGACY_READ_DEBT_EVIDENCE)
        self.assertIsNone(resolved["takeover_provider"])
        self.assertIsNone(resolved["takeover_session_id"])
        self.assertIsNone(resolved["retry_consumed_by"])
        self.assertIsNone(resolved["reprobe_consumed_by"])
        self.assertEqual(
            settle_legacy_read_only_debt(
                self.contract,
                intervention["intervention_id"],
            ),
            resolved,
        )
        projection = load_projection(self.contract)
        self.assertIn(attempt["attempt_id"], projection["attempts"])
        self.assertEqual(blocking_attempts(projection), [])
        self.assertEqual(readiness_blocking_attempts(projection), [])
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    "phase": "started",
                    "effect": "local_write",
                    "kind": "file_change",
                    "provider": "codex",
                    "session_id": "thread-two",
                    "fingerprint": "2" * 64,
                    "target": "unrelated.md",
                },
            )
        )
        with self.assertRaises(TypeError):
            settle_legacy_read_only_debt(  # type: ignore[call-arg]
                self.contract,
                intervention["intervention_id"],
                decision="retry_authorized",
            )

    def test_system_read_debt_settlement_rejects_material_unknown_and_keyless(self) -> None:
        cases = (
            ("external_write", "doc://material-debt", True),
            ("unknown", "doc://unknown-debt", True),
            ("read", "doc://keyless-read-debt", False),
        )
        for index, (effect, target, typed) in enumerate(cases):
            with self.subTest(effect=effect, typed=typed):
                case_contract = self.contract.with_name(
                    f"rejected-read-debt-{index}.active.json"
                )
                case_contract.write_text("{}\n", encoding="utf-8")
                attempt = begin_attempt(
                    case_contract,
                    intent_id="intent-one",
                    intent_revision=1,
                    fingerprint=str(index + 2) * 64,
                    source_event_id=f"rejected-read-debt-{index}",
                    capability="mcp:docs:get_document",
                    target=target,
                    resource_key=(
                        canonical_resource_key(target, kind="uri") if typed else ""
                    ),
                    effect=effect,
                    provider="codex",
                    session_id="thread-one",
                    idempotency_key=f"rejected-read-debt-{index}",
                )
                intervention = mark_attempt_unknown(
                    case_contract,
                    attempt["attempt_id"],
                    reason="synthetic rejected debt",
                )
                with self.assertRaises(InterventionError):
                    settle_legacy_read_only_debt(
                        case_contract,
                        intervention["intervention_id"],
                    )
                replayed = load_projection(case_contract)
                self.assertIn(
                    replayed["interventions"][intervention["intervention_id"]][
                        "status"
                    ],
                    {"open", "acknowledged"},
                )

    @staticmethod
    def existence(target: str = "doc://one") -> dict[str, list[str]]:
        return {
            "existence": [
                hashlib.sha256(target.encode("utf-8")).hexdigest()
            ]
        }

    def rewrite_first_attempt_resource_key(self, contract: Path, resource_key: str) -> None:
        store = event_store_path(contract)
        rows = [
            json.loads(line)
            for line in store.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows[0]["resource_key"] = resource_key
        rows[0]["resource_sha256"] = hashlib.sha256(resource_key.encode()).hexdigest()
        rows[0]["schema"] = "sulde-intervention-event-v1"
        rows[0]["operation_fingerprint"] = hashlib.sha256(
            "\0".join(
                (
                    rows[0]["provider"],
                    rows[0]["capability"],
                    resource_key or rows[0]["target"],
                    rows[0]["effect"],
                    rows[0]["operation_arguments_digest"],
                )
            ).encode()
        ).hexdigest()
        rows[0].pop("event_id", None)
        rows[0]["event_id"] = hashlib.sha256(
            json.dumps(
                rows[0],
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        restore_authoritative_store(
            contract,
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode(),
        )

    @staticmethod
    def reseal(row: dict) -> dict:
        sealed = dict(row)
        sealed.pop("event_id", None)
        sealed["event_id"] = hashlib.sha256(
            json.dumps(
                sealed,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return sealed

    def restore_rows(self, rows: list[dict]) -> None:
        restore_authoritative_store(
            self.contract,
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ).encode(),
        )

    def authoritative_rows(self) -> list[dict]:
        return [
            json.loads(line)
            for line in event_store_path(self.contract)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]

    @classmethod
    def legacy_keyless_rows(cls, rows: list[dict]) -> list[dict]:
        legacy: list[dict] = []
        for original in rows:
            row = json.loads(json.dumps(original))
            row["schema"] = "sulde-intervention-event-v1"
            for field in (
                "resource_key",
                "resource_sha256",
                "resource_base",
                "resource_context",
                "operation_fingerprint",
                "operation_arguments_digest",
            ):
                row.pop(field, None)
            legacy.append(cls.reseal(row))
        return legacy

    def test_v1_keyless_terminal_history_replays_without_becoming_authority(self) -> None:
        attempt = self.begin("legacy-terminal")
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="legacy completion callback was unavailable",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="human_attested_success",
            evidence="historical operator evidence",
        )
        rows = self.legacy_keyless_rows(self.authoritative_rows())
        empty_target_sha256 = hashlib.sha256(b"").hexdigest()
        rows[0]["target"] = ""
        for row in rows:
            row["target_sha256"] = empty_target_sha256
            row.update(self.reseal(row))
        self.restore_rows(rows)

        projection = load_projection(self.contract)
        replayed = projection["attempts"][attempt["attempt_id"]]
        self.assertEqual(replayed["state"], "human_attested_success")
        self.assertTrue(replayed["legacy_terminal_replayed"])
        self.assertFalse(replayed["replay_authoritative"])
        self.assertEqual(blocking_attempts(projection), [])
        self.assertIsNone(
            retry_grant_for_event(
                self.contract,
                fingerprint="f" * 64,
                provider="codex",
                session_id="thread-one",
            )
        )

    def test_v1_terminal_history_rejects_resealed_binding_changes(self) -> None:
        attempt = self.begin("legacy-tamper")
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="legacy callback gap",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="human_attested_success",
            evidence="historical operator evidence",
        )
        rows = self.legacy_keyless_rows(self.authoritative_rows())
        terminal_index = next(
            index
            for index, row in enumerate(rows)
            if row.get("state") == "human_attested_success"
        )
        resolution_index = next(
            index
            for index, row in enumerate(rows)
            if row.get("type") == "intent.intervention_resolved"
        )
        mutations = (
            (
                terminal_index,
                lambda row: row.__setitem__("provider", "other-provider"),
            ),
            (
                terminal_index,
                lambda row: row.__setitem__("state_source", "system"),
            ),
            (
                resolution_index,
                lambda row: row.__setitem__("actor", "system-verifier"),
            ),
            (
                resolution_index,
                lambda row: row.__setitem__("evidence", "different evidence"),
            ),
        )
        for index, mutate in mutations:
            with self.subTest(index=index, mutation=mutate):
                changed = json.loads(json.dumps(rows))
                mutate(changed[index])
                changed[index] = self.reseal(changed[index])
                with self.assertRaisesRegex(
                    InterventionError, "replay authority|binding"
                ):
                    self.restore_rows(changed)

    def test_v1_retry_predecessor_retires_only_after_terminal_replacement(self) -> None:
        first = self.begin("legacy-retry", fingerprint="a" * 64)
        intervention = mark_attempt_unknown(
            self.contract,
            first["attempt_id"],
            reason="legacy retry callback gap",
        )
        authorize_system_retry(
            self.contract,
            intervention["intervention_id"],
            fingerprint="a" * 64,
            provider="codex",
            session_id="thread-one",
            target="doc://one",
            evidence="sealed historical continuation",
        )
        replacement = self.begin("legacy-replacement", fingerprint="a" * 64)
        mark_attempt_result(
            self.contract,
            replacement["attempt_id"],
            success=True,
        )
        verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="legacy-replacement-read",
            explicit_attempt_id=replacement["attempt_id"],
            evidence=self.existence(),
        )
        rows = self.legacy_keyless_rows(self.authoritative_rows())
        self.restore_rows(rows)
        projection = load_projection(self.contract)
        self.assertEqual(blocking_attempts(projection), [])
        self.assertFalse(
            projection["attempts"][first["attempt_id"]]["replay_authoritative"]
        )

        terminal_index = next(
            index
            for index, row in enumerate(rows)
            if row.get("attempt_id") == replacement["attempt_id"]
            and row.get("state") == "system_verified"
        )
        unsettled = json.loads(json.dumps(rows))
        unsettled[terminal_index]["state"] = "unknown"
        unsettled[terminal_index]["state_source"] = "system"
        unsettled[terminal_index].pop("verification_event_id", None)
        unsettled[terminal_index].pop("verification_capability", None)
        unsettled[terminal_index] = self.reseal(unsettled[terminal_index])
        self.restore_rows(unsettled)
        blocked_ids = {
            row["attempt_id"] for row in blocking_attempts(load_projection(self.contract))
        }
        self.assertIn(first["attempt_id"], blocked_ids)
        self.assertIn(replacement["attempt_id"], blocked_ids)

    def test_success_is_provisional_until_an_independent_matching_read(self) -> None:
        attempt = self.begin()
        self.assertEqual(attempt["state"], "dispatched")
        result = mark_attempt_result(self.contract, attempt["attempt_id"], success=True)
        self.assertEqual(result["state"], "verifying")
        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="read-one",
            evidence=self.existence(),
        )
        self.assertEqual([row["attempt_id"] for row in verified], [attempt["attempt_id"]])
        projection = load_projection(self.contract)
        self.assertEqual(projection["attempts"][attempt["attempt_id"]]["state"], "system_verified")

    def test_begin_persists_dispatch_as_one_authority_event(self) -> None:
        attempt = self.begin()

        rows = [
            json.loads(line)
            for line in event_store_path(self.contract).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

        self.assertEqual(attempt["state"], "dispatched")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "effect.attempt_created")
        self.assertEqual(rows[0]["state"], "dispatched")

    def test_content_read_must_match_the_expected_postcondition_digest(self) -> None:
        expected = hashlib.sha256(json.dumps("new").encode("utf-8")).hexdigest()
        attempt = self.begin(
            verification_kind="content",
            verification_sha256=expected,
        )
        mark_attempt_result(self.contract, attempt["attempt_id"], success=True)
        mismatch = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="old-content",
            evidence={
                "content": [
                    hashlib.sha256(json.dumps("old").encode("utf-8")).hexdigest()
                ]
            },
        )
        self.assertEqual(mismatch, [])
        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="new-content",
            evidence={"content": [expected]},
        )
        self.assertEqual([row["attempt_id"] for row in verified], [attempt["attempt_id"]])

    def test_same_target_second_dispatch_is_blocked_before_ambiguity(self) -> None:
        first = self.begin("dispatch-1", fingerprint="1" * 64)
        with self.assertRaisesRegex(InterventionError, "blocker|debt"):
            self.begin("dispatch-2", fingerprint="2" * 64)
        mark_attempt_result(self.contract, first["attempt_id"], success=True)
        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="ambiguous-read",
            evidence=self.existence(),
        )
        self.assertEqual([row["attempt_id"] for row in verified], [first["attempt_id"]])

    def test_idempotency_key_cannot_be_reused_for_different_effect_semantics(self) -> None:
        self.begin("same-key")
        with self.assertRaisesRegex(InterventionError, "different semantics"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=1,
                fingerprint="9" * 64,
                source_event_id="different-event",
                capability="mcp:docs:update_document",
                target="doc://different",
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="same-key",
                verification_kind="existence",
            )

    def test_unknown_blocks_same_effect_target_across_sessions(self) -> None:
        attempt = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="completion callback was lost",
        )
        self.assertEqual(intervention["status"], "open")
        inbox = self.home / "interventions" / "inbox.jsonl"
        self.assertTrue(inbox.is_file())
        self.assertEqual(json.loads(inbox.read_text())["intervention_id"], intervention["intervention_id"])
        material = {
            "phase": "started",
            "effect": "external_write",
            "kind": "mcp",
            "provider": "codex",
            "session_id": "thread-one",
            "fingerprint": "x" * 64,
            "target": "doc://one",
        }
        self.assertEqual(
            material_event_blocker(self.contract, material)["intervention_id"],
            intervention["intervention_id"],
        )
        self.assertIsNone(material_event_blocker(self.contract, {**material, "effect": "read"}))
        cross_session = material_event_blocker(
            self.contract,
            {**material, "session_id": "thread-two"},
        )
        self.assertEqual(cross_session["attempt_id"], attempt["attempt_id"])
        different_keyless = material_event_blocker(
            self.contract,
            {**material, "target": "doc://two"},
        )
        self.assertEqual(different_keyless["attempt_id"], attempt["attempt_id"])

    def test_nonterminal_unknown_interventions_still_block_readiness(self) -> None:
        attempt_ids = ("unhandled", "open", "acknowledged", "retry", "reprobe")
        attempts = {
            attempt_id: {
                "attempt_id": attempt_id,
                "state": "unknown",
                "replay_authoritative": True,
            }
            for attempt_id in attempt_ids
        }
        interventions = {
            "open": {
                "attempt_id": "open",
                "status": "open",
                "decision": None,
            },
            "acknowledged": {
                "attempt_id": "acknowledged",
                "status": "acknowledged",
                "decision": None,
            },
            "retry": {
                "attempt_id": "retry",
                "status": "resolved",
                "decision": "retry_authorized",
                "retry_consumed_by": None,
            },
            "reprobe": {
                "attempt_id": "reprobe",
                "status": "resolved",
                "decision": "reprobe_authorized",
            },
        }
        projection = {"attempts": attempts, "interventions": interventions}
        self.assertEqual(
            {row["attempt_id"] for row in readiness_blocking_attempts(projection)},
            set(attempt_ids),
        )
        self.assertEqual(terminal_quarantined_attempts(projection), [])

    def test_aborted_unknown_is_quarantined_but_still_blocks_same_resource(self) -> None:
        attempt = self.begin("aborted-debt")
        intervention = mark_attempt_unknown(
            self.contract, attempt["attempt_id"], reason="completion callback was lost"
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="abort",
            evidence="operator ended intervention without external settlement",
        )

        projection = load_projection(self.contract)
        self.assertEqual(
            [row["attempt_id"] for row in blocking_attempts(projection)],
            [attempt["attempt_id"]],
        )
        self.assertEqual(readiness_blocking_attempts(projection), [])
        self.assertEqual(
            [row["attempt_id"] for row in terminal_quarantined_attempts(projection)],
            [attempt["attempt_id"]],
        )
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "codex",
                "session_id": "thread-two",
                "fingerprint": "2" * 64,
                "target": "doc://one",
            },
        )
        self.assertIsNotNone(blocker)
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])

    def test_terminal_keyless_figma_debt_releases_distinct_independent_operations(self) -> None:
        attempt = begin_attempt(
            self.contract,
            intent_id="synthetic-application-brand-visual-grammar-v1",
            intent_revision=3,
            fingerprint="f" * 64,
            source_event_id="legacy-codex-apps-use-figma",
            capability="mcp:codex_apps:figma__use_figma",
            target="",
            effect="unknown",
            provider="codex",
            session_id="legacy-figma-thread",
            idempotency_key="legacy-keyless-figma-write",
            verification_kind="unsupported",
        )
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="host turn ended before independent verification completed",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="abort",
            evidence="operator ended intervention without external settlement",
        )
        before_local_dispatch = event_store_path(self.contract).read_bytes()

        workspace = Path(self.temporary.name) / "synthetic-application"
        workspace.mkdir()
        local_target = workspace / "Proofline.md"
        local_target.write_text("baseline\n", encoding="utf-8")
        local_key = canonical_resource_key(
            str(local_target), kind="path", base=workspace
        )
        local_event = {
            "phase": "started",
            "effect": "local_write",
            "kind": "tool",
            "provider": "codex",
            "session_id": "current-thread",
            "fingerprint": "1" * 64,
            "target": str(local_target),
            "effect_resource_key": local_key,
            "effect_resource_base": str(workspace),
        }
        self.assertIsNone(material_event_blocker(self.contract, local_event))
        local_attempt = begin_attempt(
            self.contract,
            intent_id="synthetic-application-brand-visual-grammar-v1",
            intent_revision=8,
            fingerprint="2" * 64,
            source_event_id="typed-local-write",
            capability="tool:apply_patch",
            target=str(local_target),
            resource_key=local_key,
            resource_base=workspace,
            effect="local_write",
            provider="codex",
            session_id="current-thread",
            idempotency_key="typed-local-write",
            verification_kind="existence",
        )
        self.assertEqual(local_attempt["state"], "dispatched")
        self.assertTrue(
            event_store_path(self.contract).read_bytes().startswith(
                before_local_dispatch
            )
        )

        figma_target = "File_123:12:34"
        figma_context = {
            "server": "figma",
            "resource_kind": "figma",
            "identifier": figma_target,
        }
        figma_key = canonical_resource_key(
            ("figma", "figma", figma_target), kind="mcp"
        )
        figma_arguments = "3" * 64
        figma_operation = effect_operation_fingerprint(
            provider="codex",
            capability="mcp:figma:use_figma",
            target=figma_target,
            resource_key=figma_key,
            effect="external_write",
            arguments_digest=figma_arguments,
        )
        figma_event = {
            "phase": "started",
            "effect": "external_write",
            "kind": "mcp",
            "provider": "codex",
            "session_id": "current-thread",
            "fingerprint": "3" * 64,
            "intent_id": "synthetic-application-brand-visual-grammar-v1",
            "intent_revision": 8,
            "capability": "mcp:figma:use_figma",
            "effect_operation_fingerprint": figma_operation,
            "target": figma_target,
            "effect_resource_key": figma_key,
            "effect_resource_context": figma_context,
        }
        same_revision_event = {
            **figma_event,
            "intent_revision": 3,
            "fingerprint": "5" * 64,
        }
        self.assertIsNone(material_event_blocker(self.contract, same_revision_event))
        self.assertIsNone(material_event_blocker(self.contract, figma_event))
        figma_attempt = begin_attempt(
            self.contract,
            intent_id="synthetic-application-brand-visual-grammar-v1",
            intent_revision=8,
            fingerprint="4" * 64,
            source_event_id="typed-independent-figma",
            capability="mcp:figma:use_figma",
            target=figma_target,
            resource_key=figma_key,
            resource_context=figma_context,
            effect="external_write",
            provider="codex",
            session_id="current-thread",
            idempotency_key="typed-independent-figma",
            operation_arguments_digest=figma_arguments,
            verification_kind="unsupported",
        )
        self.assertEqual(figma_attempt["state"], "dispatched")
        dependency_blocker = material_event_blocker(
            self.contract,
            {**local_event, "depends_on_attempt_id": attempt["attempt_id"]},
        )
        self.assertIsNone(dependency_blocker)
        replayed = load_projection(self.contract)["attempts"][attempt["attempt_id"]]
        self.assertEqual(replayed["state"], "unknown")
        self.assertFalse(replayed["replay_authoritative"])
        replayed_intervention = load_projection(self.contract)["interventions"][
            intervention["intervention_id"]
        ]
        self.assertEqual(replayed_intervention["status"], "resolved")
        self.assertEqual(replayed_intervention["decision"], "abort")
        self.assertIn(
            attempt["attempt_id"],
            {
                row["attempt_id"]
                for row in terminal_quarantined_attempts(load_projection(self.contract))
            },
        )

    def test_terminal_synthetic_figma_placeholder_releases_new_operation(self) -> None:
        unresolved_target = "[unresolved-figma-target]"
        unresolved_context = {
            "server": "figma",
            "resource_kind": "use_figma",
            "identifier": unresolved_target,
        }
        unresolved_key = canonical_resource_key(
            ("figma", "use_figma", unresolved_target), kind="mcp"
        )
        historical = begin_attempt(
            self.contract,
            intent_id="figma-intent",
            intent_revision=12,
            fingerprint="a" * 64,
            source_event_id="synthetic-unresolved-figma",
            capability="mcp:figma:use_figma",
            target=unresolved_target,
            resource_key=unresolved_key,
            resource_context=unresolved_context,
            effect="external_write",
            provider="codex",
            session_id="old-thread",
            idempotency_key="synthetic-unresolved-figma",
            operation_arguments_digest="b" * 64,
            verification_kind="unsupported",
        )
        intervention = mark_attempt_unknown(
            self.contract, historical["attempt_id"], reason="callback lost"
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="abort",
            evidence="operator ended the unresolved operation",
        )
        new_arguments = "c" * 64
        new_operation = effect_operation_fingerprint(
            provider="codex",
            capability="mcp:figma:use_figma",
            target=unresolved_target,
            resource_key=unresolved_key,
            effect="external_write",
            arguments_digest=new_arguments,
        )
        event = {
            "phase": "started",
            "effect": "external_write",
            "kind": "mcp",
            "provider": "codex",
            "session_id": "new-thread",
            "fingerprint": "d" * 64,
            "intent_id": "figma-intent",
            "intent_revision": 15,
            "capability": "mcp:figma:use_figma",
            "effect_operation_fingerprint": new_operation,
            "target": unresolved_target,
            "effect_resource_key": unresolved_key,
            "effect_resource_context": unresolved_context,
        }
        missing_operation = dict(event)
        missing_operation.pop("effect_operation_fingerprint")
        missing_blocker = material_event_blocker(self.contract, missing_operation)
        self.assertIsNone(missing_blocker)
        repeated_operation = {
            **event,
            "effect_operation_fingerprint": historical["operation_fingerprint"],
        }
        repeated_blocker = material_event_blocker(self.contract, repeated_operation)
        self.assertIsNone(repeated_blocker)
        self.assertIsNone(material_event_blocker(self.contract, event))
        dispatched = begin_attempt(
            self.contract,
            intent_id="figma-intent",
            intent_revision=15,
            fingerprint="e" * 64,
            source_event_id="new-unresolved-figma-operation",
            capability="mcp:figma:use_figma",
            target=unresolved_target,
            resource_key=unresolved_key,
            resource_context=unresolved_context,
            effect="external_write",
            provider="codex",
            session_id="new-thread",
            idempotency_key="new-unresolved-figma-operation",
            operation_arguments_digest=new_arguments,
            verification_kind="unsupported",
        )
        self.assertEqual(dispatched["state"], "dispatched")
        replayed = load_projection(self.contract)["attempts"][historical["attempt_id"]]
        self.assertEqual(replayed["state"], "unknown")
        self.assertTrue(replayed["replay_authoritative"])
        self.assertIn(
            historical["attempt_id"],
            {
                row["attempt_id"]
                for row in terminal_quarantined_attempts(load_projection(self.contract))
            },
        )

    def test_nonterminal_keyless_figma_debt_is_audit_only(self) -> None:
        attempt = begin_attempt(
            self.contract,
            intent_id="figma-intent",
            intent_revision=1,
            fingerprint="1" * 64,
            source_event_id="open-keyless-figma",
            capability="mcp:codex_apps:figma__use_figma",
            target="",
            effect="unknown",
            provider="codex",
            session_id="old-thread",
            idempotency_key="open-keyless-figma",
            verification_kind="unsupported",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost")
        figma_target = "File_456:78:90"
        figma_context = {
            "server": "figma",
            "resource_kind": "figma",
            "identifier": figma_target,
        }
        figma_key = canonical_resource_key(
            ("figma", "figma", figma_target), kind="mcp"
        )
        operation = effect_operation_fingerprint(
            provider="codex",
            capability="mcp:figma:use_figma",
            target=figma_target,
            resource_key=figma_key,
            effect="external_write",
            arguments_digest="8" * 64,
        )
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "codex",
                "session_id": "new-thread",
                "fingerprint": "9" * 64,
                "intent_id": "figma-intent",
                "intent_revision": 2,
                "capability": "mcp:figma:use_figma",
                "effect_operation_fingerprint": operation,
                "target": figma_target,
                "effect_resource_key": figma_key,
                "effect_resource_context": figma_context,
            },
        )
        self.assertIsNone(blocker)
        replayed = load_projection(self.contract)["attempts"][attempt["attempt_id"]]
        self.assertEqual(replayed["state"], "unknown")

    def test_unknown_keyless_domain_still_blocks_typed_local_path(self) -> None:
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="5" * 64,
            source_event_id="legacy-unknown-domain",
            capability="mcp:codex_apps:unknown__mutate",
            target="",
            effect="unknown",
            provider="codex",
            session_id="legacy-thread",
            idempotency_key="legacy-unknown-domain",
            verification_kind="unsupported",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost")
        workspace = Path(self.temporary.name) / "unknown-domain"
        workspace.mkdir()
        local_target = workspace / "local.md"
        local_target.write_text("baseline\n", encoding="utf-8")
        local_key = canonical_resource_key(
            str(local_target), kind="path", base=workspace
        )
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "local_write",
                "kind": "tool",
                "provider": "codex",
                "session_id": "current-thread",
                "fingerprint": "6" * 64,
                "target": str(local_target),
                "effect_resource_key": local_key,
                "effect_resource_base": str(workspace),
            },
        )
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])

    def test_path_aliases_and_symlink_share_one_cross_session_effect_debt(self) -> None:
        workspace = Path(self.temporary.name) / "workspace"
        real = workspace / "real"
        real.mkdir(parents=True)
        target = real / "item.txt"
        target.write_text("present\n", encoding="utf-8")
        alias = workspace / "alias"
        alias.symlink_to(real, target_is_directory=True)
        relative = "./real/item.txt"
        resource_key = canonical_resource_key(
            relative,
            kind="path",
            base=workspace,
        )
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="a" * 64,
            source_event_id="relative-write",
            capability="mcp:files:update_document",
            target=relative,
            resource_key=resource_key,
            resource_base=workspace,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="relative-write",
            verification_kind="existence",
        )
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="completion callback was lost",
        )

        for candidate in (
            str(target),
            "real/./item.txt",
            "alias/item.txt",
        ):
            with self.subTest(candidate=candidate):
                blocker = material_event_blocker(
                    self.contract,
                    {
                        "phase": "started",
                        "effect": "external_write",
                        "kind": "mcp",
                        "provider": "codex",
                        "session_id": "thread-two",
                        "fingerprint": "b" * 64,
                        "target": candidate,
                        "effect_resource_key": canonical_resource_key(
                            candidate,
                            kind="path",
                            base=workspace,
                        ),
                        "effect_resource_base": str(workspace),
                    },
                )
                self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])

        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="reprobe_authorized",
            evidence="operator selected the recovery session",
            takeover_provider="codex",
            takeover_session_id="thread-two",
        )
        proof_target = "alias/item.txt"
        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-two",
            capability="mcp:files:read_document",
            target=proof_target,
            resource_key=canonical_resource_key(
                proof_target,
                kind="path",
                base=workspace,
            ),
            resource_base=workspace,
            verification_event_id="alias-reprobe",
            explicit_attempt_id=attempt["attempt_id"],
            evidence=self.existence(proof_target),
        )
        self.assertEqual([row["attempt_id"] for row in verified], [attempt["attempt_id"]])

    def test_typed_resource_identity_precedes_equal_raw_target_everywhere(self) -> None:
        first_workspace = Path(self.temporary.name) / "first-workspace"
        second_workspace = Path(self.temporary.name) / "second-workspace"
        first_workspace.mkdir()
        second_workspace.mkdir()
        for workspace in (first_workspace, second_workspace):
            (workspace / "same.txt").write_text("present\n", encoding="utf-8")
        raw_target = "same.txt"
        first_key = canonical_resource_key(
            raw_target, kind="path", base=first_workspace
        )
        second_key = canonical_resource_key(
            raw_target, kind="path", base=second_workspace
        )
        self.assertNotEqual(first_key, second_key)
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="7" * 64,
            source_event_id="first-workspace-write",
            capability="mcp:files:update_document",
            target=raw_target,
            resource_key=first_key,
            resource_base=first_workspace,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="first-workspace-write",
            verification_kind="existence",
        )
        mark_attempt_result(self.contract, attempt["attempt_id"], success=True)

        self.assertEqual(
            verify_from_read(
                self.contract,
                provider="codex",
                session_id="thread-one",
                capability="mcp:files:read_document",
                target=raw_target,
                resource_key=second_key,
                resource_base=second_workspace,
                verification_event_id="wrong-base-read",
                explicit_attempt_id=attempt["attempt_id"],
                evidence=self.existence(raw_target),
            ),
            [],
        )
        mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="the correct workspace was not independently verified",
        )
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    "phase": "started",
                    "effect": "external_write",
                    "kind": "tool",
                    "provider": "codex",
                    "session_id": "thread-two",
                    "fingerprint": "8" * 64,
                    "target": raw_target,
                    "effect_resource_key": second_key,
                    "effect_resource_base": str(second_workspace),
                },
            )
        )
        with self.assertRaisesRegex(InterventionError, "same-resource proof"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=2,
                fingerprint="9" * 64,
                source_event_id="wrong-base-compensation",
                capability="mcp:files:update_document",
                target=raw_target,
                resource_key=second_key,
                resource_base=second_workspace,
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="wrong-base-compensation",
                verification_kind="existence",
                compensates_attempt_id=attempt["attempt_id"],
            )
        with self.assertRaisesRegex(InterventionError, "target.*context"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=2,
                fingerprint="0" * 64,
                source_event_id="substituted-path-context",
                capability="mcp:files:update_document",
                target=raw_target,
                resource_key=first_key,
                resource_base=second_workspace,
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="substituted-path-context",
                verification_kind="existence",
            )

        database_key = canonical_resource_key(
            ("docs", "database", "record:42"), kind="mcp"
        )
        document_key = canonical_resource_key(
            ("docs", "document", "record:42"), kind="mcp"
        )
        mcp_attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=3,
            fingerprint="a" * 64,
            source_event_id="database-write",
            capability="mcp:docs:update_record",
            target="record:42",
            resource_key=database_key,
            resource_context={
                "server": "docs",
                "resource_kind": "database",
                "identifier": "record:42",
            },
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="database-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(
            self.contract, mcp_attempt["attempt_id"], reason="database reply lost"
        )
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    "phase": "started",
                    "effect": "external_write",
                    "kind": "mcp",
                    "provider": "codex",
                    "session_id": "thread-two",
                    "fingerprint": "b" * 64,
                    "target": "record:42",
                    "effect_resource_key": document_key,
                    "effect_resource_context": {
                        "server": "docs",
                        "resource_kind": "document",
                        "identifier": "record:42",
                    },
                },
            )
        )

    def test_path_v2_uses_object_or_parent_identity_and_rejects_raw_path_keys(self) -> None:
        workspace = Path(self.temporary.name) / "path-v2-workspace"
        first_parent = workspace / "first"
        second_parent = workspace / "second"
        first_parent.mkdir(parents=True)
        second_parent.mkdir()
        existing = first_parent / "Café.txt"
        existing.write_text("present\n", encoding="utf-8")
        hardlink = first_parent / "hardlink.txt"
        os.link(existing, hardlink)
        self.assertEqual(
            canonical_resource_key(existing, kind="path", base=workspace),
            canonical_resource_key(hardlink, kind="path", base=workspace),
        )
        self.assertNotEqual(
            canonical_resource_key("first/pending.txt", kind="path", base=workspace),
            canonical_resource_key("second/pending.txt", kind="path", base=workspace),
        )

        if sys.platform == "darwin":
            aliases = (
                first_parent / "CAFÉ.TXT",
                first_parent / "Cafe\N{COMBINING ACUTE ACCENT}.txt",
            )
            for alias in aliases:
                if alias.exists() and os.path.samefile(existing, alias):
                    with self.subTest(alias=alias):
                        self.assertEqual(
                            canonical_resource_key(existing, kind="path", base=workspace),
                            canonical_resource_key(alias, kind="path", base=workspace),
                        )

        with self.assertRaisesRegex(InterventionError, "canonical|version"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=1,
                fingerprint="c" * 64,
                source_event_id="raw-dot-path-key",
                capability="tool:Write",
                target="first/./Café.txt",
                resource_key=f"path:{first_parent}/./Café.txt",
                resource_base=workspace,
                effect="local_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="raw-dot-path-key",
                verification_kind="existence",
            )
        parent_status = first_parent.stat()
        noncanonical_pending_key = "v2:path:" + json.dumps(
            [
                "pending",
                parent_status.st_dev,
                parent_status.st_ino,
                ["..", "escaped.txt"],
            ],
            separators=(",", ":"),
        )
        with self.assertRaisesRegex(InterventionError, "canonical identity"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=1,
                fingerprint="d" * 64,
                source_event_id="dotdot-v2-path-key",
                capability="tool:Write",
                target="first/../escaped.txt",
                resource_key=noncanonical_pending_key,
                resource_base=workspace,
                effect="local_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="dotdot-v2-path-key",
                verification_kind="existence",
            )

    def test_legacy_raw_target_is_dual_matched_without_rewriting_history(self) -> None:
        workspace = Path(self.temporary.name) / "legacy-workspace"
        target = workspace / "docs" / "item.txt"
        target.parent.mkdir(parents=True)
        target.write_text("present\n", encoding="utf-8")
        raw_target = "docs/./item.txt"
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="c" * 64,
            source_event_id="legacy-relative-write",
            capability="mcp:files:update_document",
            target=raw_target,
            resource_key=canonical_resource_key(
                raw_target,
                kind="path",
                base=workspace,
            ),
            resource_base=workspace,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="legacy-relative-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="legacy completion callback was lost",
        )
        store = event_store_path(self.contract)
        rows = [
            json.loads(line)
            for line in store.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        for field in ("resource_key", "resource_sha256", "resource_base"):
            rows[0].pop(field, None)
        rows[0].pop("event_id", None)
        canonical = json.dumps(
            rows[0],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        rows[0]["event_id"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        store.write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )

        alias = str(target.resolve())
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "codex",
                "session_id": "thread-two",
                "fingerprint": "d" * 64,
                "target": alias,
                "effect_resource_key": canonical_resource_key(
                    alias,
                    kind="path",
                    base=workspace,
                ),
                "effect_resource_base": str(workspace),
            },
        )
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])

        # Legacy idempotency replay keeps exact raw semantics and must not fail
        # merely because current code can now derive a resource key.
        replayed = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="c" * 64,
            source_event_id="legacy-relative-write",
            capability="mcp:files:update_document",
            target=raw_target,
            resource_key=canonical_resource_key(
                raw_target,
                kind="path",
                base=workspace,
            ),
            resource_base=workspace,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="legacy-relative-write",
            verification_kind="existence",
        )
        self.assertEqual(replayed["attempt_id"], attempt["attempt_id"])

    def test_comma_in_filename_remains_one_path_resource(self) -> None:
        workspace = Path(self.temporary.name) / "comma-workspace"
        workspace.mkdir()
        relative = "part,one.txt"
        target = workspace / relative
        target.write_text("present\n", encoding="utf-8")
        resource_key = canonical_resource_key(
            relative,
            kind="path",
            base=workspace,
        )
        self.assertTrue(resource_key.startswith("v2:path:"))
        self.assertNotEqual(
            resource_key,
            canonical_resource_key("part", kind="path", base=workspace),
        )

        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="e" * 64,
            source_event_id="comma-write",
            capability="mcp:files:update_document",
            target=relative,
            resource_key=resource_key,
            resource_base=workspace,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="comma-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="comma target completion was lost",
        )
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "codex",
                "session_id": "thread-two",
                "fingerprint": "f" * 64,
                "target": str(target),
                "effect_resource_key": canonical_resource_key(
                    target,
                    kind="path",
                    base=workspace,
                ),
                "effect_resource_base": str(workspace),
            },
        )
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])

    def test_uri_identity_normalizes_only_proven_equivalences(self) -> None:
        first = canonical_resource_key(
            "HTTPS://Example.COM:443/a/./b/../%7euser?x=%41&y=%2f#first",
            kind="uri",
        )
        second = canonical_resource_key(
            "https://example.com/a/~user?x=A&y=%2F#second",
            kind="uri",
        )
        self.assertEqual(first, second)
        self.assertEqual(
            canonical_resource_key("https://EXAMPLE.com:443", kind="uri"),
            canonical_resource_key("https://example.com/", kind="uri"),
        )
        self.assertEqual(
            canonical_resource_key("https://%65xample.com.:443/a", kind="uri"),
            canonical_resource_key("https://example.com/a", kind="uri"),
        )
        self.assertNotEqual(
            canonical_resource_key("https://example.com/", kind="uri"),
            canonical_resource_key("https://example.com/?", kind="uri"),
        )
        for different in (
            "https://example.com/a/~user?y=%2F&x=A",
            "https://example.com/a/~user?x=a&y=%2F",
            "https://example.com/a/~user?x=A+y&y=%2F",
            "https://example.com/a/~user?x=A%20y&y=%2F",
            "https://example.com/a/~user?",
        ):
            with self.subTest(different=different):
                self.assertNotEqual(first, canonical_resource_key(different, kind="uri"))
        with self.assertRaisesRegex(InterventionError, "invalid percent escape"):
            canonical_resource_key("https://example.com/%zz", kind="uri")
        with self.assertRaises(InterventionError):
            canonical_resource_key("https://example.com../a", kind="uri")
        for different_host in (
            "https://%2Fexample.com/a",
            "https://example.com:444/a",
        ):
            with self.subTest(different_host=different_host):
                self.assertNotEqual(
                    canonical_resource_key("https://example.com/a", kind="uri"),
                    canonical_resource_key(different_host, kind="uri"),
                )

    def test_resource_key_version_is_explicit_and_unknown_versions_fail_closed(self) -> None:
        current_key = canonical_resource_key(
            "https://example.com/docs/one", kind="uri"
        )
        legacy_raw = "https://example.com./docs/one"
        self.assertTrue(current_key.startswith("v2:uri:"))
        with self.assertRaisesRegex(InterventionError, "version"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=1,
                fingerprint="d" * 64,
                source_event_id="unknown-resource-version",
                capability="mcp:docs:update_document",
                target="https://example.com/docs/one",
                resource_key="v99:uri:https://example.com/docs/one",
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="unknown-resource-version",
                verification_kind="existence",
            )

        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="e" * 64,
            source_event_id="versioned-uri-write",
            capability="mcp:docs:update_document",
            target=legacy_raw,
            resource_key=current_key,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="versioned-uri-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost reply")
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
        legacy_key = "uri:https://example.com./docs/one"
        rows[0]["resource_key"] = legacy_key
        rows[0]["resource_sha256"] = hashlib.sha256(legacy_key.encode()).hexdigest()
        rows[0]["schema"] = "sulde-intervention-event-v1"
        rows[0]["operation_fingerprint"] = hashlib.sha256(
            "\0".join(
                (
                    rows[0]["provider"],
                    rows[0]["capability"],
                    legacy_key,
                    rows[0]["effect"],
                    rows[0]["operation_arguments_digest"],
                )
            ).encode()
        ).hexdigest()
        rows[0].pop("event_id")
        rows[0]["event_id"] = hashlib.sha256(
            json.dumps(
                rows[0],
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        restore_authoritative_store(
            self.contract,
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode(),
        )
        before_replay = event_store_path(self.contract).read_bytes()
        load_projection(self.contract)
        self.assertEqual(event_store_path(self.contract).read_bytes(), before_replay)
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    "phase": "started",
                    "effect": "external_write",
                    "kind": "mcp",
                    "provider": "codex",
                    "session_id": "thread-two",
                    "fingerprint": "0" * 64,
                    "target": "https://example.com/docs/two",
                    "effect_resource_key": canonical_resource_key(
                        "https://example.com/docs/two", kind="uri"
                    ),
                },
            )
        )
        blocker = material_event_blocker(
                self.contract,
                {
                    "phase": "started",
                    "effect": "external_write",
                    "kind": "mcp",
                    "provider": "codex",
                    "session_id": "thread-two",
                    "fingerprint": "f" * 64,
                    "target": "https://example.com/docs/one",
                    "effect_resource_key": current_key,
                },
            )
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])

        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:read_document",
            target="https://example.com/docs/one",
            resource_key=current_key,
            verification_event_id="v1-to-v2-uri-read",
            explicit_attempt_id=attempt["attempt_id"],
            evidence=self.existence("https://example.com/docs/one"),
        )
        self.assertEqual(verified[0]["state"], "system_verified")

    def test_v1_path_debt_migrates_only_with_the_same_frozen_base_identity(self) -> None:
        first = Path(self.temporary.name) / "legacy-path-first"
        second = Path(self.temporary.name) / "legacy-path-second"
        first.mkdir()
        second.mkdir()
        for workspace in (first, second):
            (workspace / "same.txt").write_text("present\n", encoding="utf-8")
        current_key = canonical_resource_key("same.txt", kind="path", base=first)
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="1" * 64,
            source_event_id="v1-path-write",
            capability="tool:Write",
            target="same.txt",
            resource_key=current_key,
            resource_base=first,
            effect="local_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="v1-path-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost reply")
        self.rewrite_first_attempt_resource_key(
            self.contract,
            "path:" + os.path.normcase(str((first / "same.txt").resolve())),
        )
        same_event = {
            "phase": "started",
            "effect": "local_write",
            "kind": "tool",
            "provider": "codex",
            "session_id": "thread-two",
            "fingerprint": "2" * 64,
            "target": "same.txt",
            "effect_resource_key": current_key,
            "effect_resource_base": str(first),
        }
        self.assertEqual(
            material_event_blocker(self.contract, same_event)["attempt_id"],
            attempt["attempt_id"],
        )
        different_key = canonical_resource_key("same.txt", kind="path", base=second)
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    **same_event,
                    "effect_resource_key": different_key,
                    "effect_resource_base": str(second),
                },
            )
        )

    def test_v1_mcp_debt_migrates_only_with_same_server_kind_identifier(self) -> None:
        key = canonical_resource_key(("docs", "database", "record:42"), kind="mcp")
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="3" * 64,
            source_event_id="v1-mcp-write",
            capability="mcp:docs:update_record",
            target="record:42",
            resource_key=key,
            resource_context={
                "server": "docs",
                "resource_kind": "database",
                "identifier": "record:42",
            },
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="v1-mcp-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost reply")
        self.rewrite_first_attempt_resource_key(self.contract, key.removeprefix("v2:"))
        event = {
            "phase": "started",
            "effect": "external_write",
            "kind": "mcp",
            "provider": "codex",
            "session_id": "thread-two",
            "fingerprint": "4" * 64,
            "target": "record:42",
            "effect_resource_key": key,
            "effect_resource_context": {
                "server": "docs",
                "resource_kind": "database",
                "identifier": "record:42",
            },
        }
        self.assertEqual(
            material_event_blocker(self.contract, event)["attempt_id"],
            attempt["attempt_id"],
        )
        different_key = canonical_resource_key(
            ("docs", "document", "record:42"), kind="mcp"
        )
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    **event,
                    "effect_resource_key": different_key,
                    "effect_resource_context": {
                        "server": "docs",
                        "resource_kind": "document",
                        "identifier": "record:42",
                    },
                },
            )
        )

    def test_v1_git_debt_never_blocks_the_retired_control_domain(self) -> None:
        oid = "a" * 40
        context = {
            "remote": "https://git.example.com/team/repo.git",
            "ref": "refs/heads/main",
            "oid": oid,
        }
        key = canonical_resource_key(context, kind="git")
        relation = git_ref_verification_digest(**context)
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="5" * 64,
            source_event_id="v1-git-write",
            capability="tool:Bash",
            target="git push origin HEAD:refs/heads/main",
            resource_key=key,
            resource_context=context,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="v1-git-write",
            verification_kind="relation",
            verification_sha256=relation,
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost reply")
        legacy_remote = canonical_resource_key(
            context["remote"], kind="uri"
        ).removeprefix("v2:")
        legacy_key = "git:" + json.dumps(
            [legacy_remote, context["ref"]],
            separators=(",", ":"),
        )
        self.rewrite_first_attempt_resource_key(self.contract, legacy_key)
        event = {
            "phase": "started",
            "effect": "external_write",
            "kind": "tool",
            "provider": "codex",
            "session_id": "thread-two",
            "fingerprint": "6" * 64,
            "target": "git push origin HEAD:refs/heads/main",
            "effect_resource_key": key,
            "effect_resource_context": context,
        }
        self.assertIsNone(material_event_blocker(self.contract, event))
        different_context = {**context, "ref": "refs/heads/release"}
        different_key = canonical_resource_key(different_context, kind="git")
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    **event,
                    "effect_resource_key": different_key,
                    "effect_resource_context": different_context,
                },
            )
        )

    def test_all_external_typed_keys_reject_target_or_context_substitution(self) -> None:
        git_context = {
            "remote": "https://git.example.com/team/a.git",
            "ref": "refs/heads/main",
            "oid": "a" * 40,
        }
        cases = (
            (
                "uri",
                "https://example.com/a",
                canonical_resource_key("https://example.com/b", kind="uri"),
                None,
                "existence",
                "",
                self.existence("https://example.com/a"),
            ),
            (
                "mcp",
                "record:42",
                canonical_resource_key(("other", "database", "record:42"), kind="mcp"),
                {
                    "server": "docs",
                    "resource_kind": "database",
                    "identifier": "record:42",
                },
                "existence",
                "",
                self.existence("record:42"),
            ),
            (
                "git",
                "git push origin HEAD:refs/heads/main",
                canonical_resource_key(
                    {"remote": "https://git.example.com/team/b.git", "ref": "refs/heads/main"},
                    kind="git",
                ),
                git_context,
                "relation",
                git_ref_verification_digest(**git_context),
                {"relation": [git_ref_verification_digest(**git_context)]},
            ),
            (
                "opaque",
                "provider-record:A",
                canonical_resource_key("provider-record:B", kind="opaque"),
                {"schema": "exact", "value": "provider-record:A"},
                "existence",
                "",
                self.existence("provider-record:A"),
            ),
        )
        for name, target, key, context, verification_kind, verification_sha, evidence in cases:
            with self.subTest(entry="begin", kind=name):
                with self.assertRaisesRegex(InterventionError, "does not match"):
                    begin_attempt(
                        self.contract,
                        intent_id="intent-one",
                        intent_revision=1,
                        fingerprint=name[0] * 64,
                        source_event_id=f"substituted-{name}-begin",
                        capability="tool:Bash" if name == "git" else "mcp:docs:update_record",
                        target=target,
                        resource_key=key,
                        resource_context=context,
                        effect="external_write",
                        provider="codex",
                        session_id="thread-one",
                        idempotency_key=f"substituted-{name}-begin",
                        verification_kind=verification_kind,
                        verification_sha256=verification_sha,
                    )
            with self.subTest(entry="event", kind=name):
                with self.assertRaisesRegex(InterventionError, "does not match"):
                    material_event_blocker(
                        self.contract,
                        {
                            "phase": "started",
                            "effect": "external_write",
                            "kind": "tool" if name == "git" else "mcp",
                            "provider": "codex",
                            "session_id": "thread-two",
                            "fingerprint": "e" * 64,
                            "target": target,
                            "effect_resource_key": key,
                            "effect_resource_context": context,
                        },
                    )
            with self.subTest(entry="verification-reprobe", kind=name):
                with self.assertRaisesRegex(InterventionError, "does not match"):
                    verify_from_read(
                        self.contract,
                        provider="codex",
                        session_id="thread-two",
                        capability="tool:Bash" if name == "git" else "mcp:docs:read_record",
                        target=target,
                        resource_key=key,
                        resource_context=context,
                        verification_event_id=f"substituted-{name}-read",
                        explicit_attempt_id="att-" + "1" * 24,
                        evidence=evidence,
                    )

        mcp_key = canonical_resource_key(("docs", "database", "record:42"), kind="mcp")
        with self.assertRaisesRegex(InterventionError, "exact context fields"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=1,
                fingerprint="7" * 64,
                source_event_id="missing-mcp-context",
                capability="mcp:docs:update_record",
                target="record:42",
                resource_key=mcp_key,
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="missing-mcp-context",
                verification_kind="existence",
            )
        with self.assertRaisesRegex(InterventionError, "version"):
            material_event_blocker(
                self.contract,
                {
                    "phase": "started",
                    "effect": "external_write",
                    "kind": "mcp",
                    "target": "record:42",
                    "effect_resource_key": "v99:mcp:[]",
                },
            )

    def test_retry_reprobe_and_compensation_validate_binding_before_authority(self) -> None:
        target = "https://example.com/a"
        substituted = canonical_resource_key("https://example.com/b", kind="uri")
        common = {
            "intent_id": "intent-one",
            "intent_revision": 2,
            "fingerprint": "8" * 64,
            "capability": "mcp:docs:update_document",
            "target": target,
            "resource_key": substituted,
            "effect": "external_write",
            "provider": "codex",
            "session_id": "thread-two",
            "verification_kind": "existence",
        }
        with self.assertRaisesRegex(InterventionError, "does not match"):
            begin_attempt(
                self.contract,
                source_event_id="substituted-retry",
                idempotency_key="substituted-retry",
                semantic_retry_intervention_id="int-" + "1" * 24,
                **common,
            )
        with self.assertRaisesRegex(InterventionError, "does not match"):
            begin_attempt(
                self.contract,
                source_event_id="substituted-compensation",
                idempotency_key="substituted-compensation",
                compensates_attempt_id="att-" + "2" * 24,
                **common,
            )
        with self.assertRaisesRegex(InterventionError, "does not match"):
            verify_from_read(
                self.contract,
                provider="codex",
                session_id="thread-two",
                capability="mcp:docs:read_document",
                target=target,
                resource_key=substituted,
                verification_event_id="substituted-reprobe",
                explicit_attempt_id="att-" + "3" * 24,
                evidence=self.existence(target),
            )

    def test_uri_alias_and_legacy_opaque_row_block_across_provider_and_session(self) -> None:
        raw = "HTTPS://Example.COM:443/docs/./item%7e?view=full"
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="1" * 64,
            source_event_id="legacy-uri-write",
            capability="mcp:docs:update_document",
            target=raw,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="legacy-uri-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="legacy URI callback was lost",
        )
        alias = "https://example.com/docs/item~?view=full"
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "another-provider",
                "session_id": "another-session",
                "fingerprint": "2" * 64,
                "target": alias,
                "effect_resource_key": canonical_resource_key(alias, kind="uri"),
            },
        )
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])

    def test_legacy_event_without_resource_key_derives_uri_or_fails_closed(self) -> None:
        target = "https://example.com/a/b"
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="1" * 64,
            source_event_id="typed-uri-write",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=canonical_resource_key(target, kind="uri"),
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="typed-uri-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="typed URI completion callback was lost",
        )
        legacy_event = {
            "phase": "started",
            "effect": "external_write",
            "kind": "mcp",
            "provider": "another-provider",
            "session_id": "another-session",
            "fingerprint": "2" * 64,
            "context": {"resource_kind": "uri"},
        }

        alias_blocker = material_event_blocker(
            self.contract,
            {
                **legacy_event,
                "target": "HTTPS://Example.COM:443/a/./b",
            },
        )
        self.assertEqual(alias_blocker["attempt_id"], attempt["attempt_id"])

        unresolved_identity_blocker = material_event_blocker(
            self.contract,
            {**legacy_event, "target": "legacy target without a safe namespace"},
        )
        self.assertEqual(
            unresolved_identity_blocker["attempt_id"], attempt["attempt_id"]
        )

    def test_mcp_identity_seals_server_kind_and_identifier_namespace(self) -> None:
        resource = canonical_resource_key(
            {
                "server": "Docs_Server",
                "resource_kind": "Data_Base",
                "identifier": "record:42",
            },
            kind="mcp",
        )
        self.assertEqual(
            resource,
            canonical_resource_key(
                ("docs-server", "data-base", "record:42"), kind="mcp"
            ),
        )
        self.assertNotEqual(
            resource,
            canonical_resource_key(
                ("other-server", "data-base", "record:42"), kind="mcp"
            ),
        )
        self.assertNotEqual(
            resource,
            canonical_resource_key(
                ("docs-server", "document", "record:42"), kind="mcp"
            ),
        )
        self.assertNotEqual(
            resource,
            canonical_resource_key(
                ("docs-server", "data-base", "record:43"), kind="mcp"
            ),
        )
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="3" * 64,
            source_event_id="mcp-write",
            capability="mcp:docs_server:update_record",
            target="record:42",
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="mcp-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost reply")
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "other-provider",
                "session_id": "thread-two",
                "fingerprint": "4" * 64,
                "target": "record:42",
                "effect_resource_key": canonical_resource_key(
                    ("docs-server", "data-base", "record:42"), kind="mcp"
                ),
                "effect_resource_context": {
                    "server": "docs-server",
                    "resource_kind": "data-base",
                    "identifier": "record:42",
                },
            },
        )
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])

        rolling = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=2,
            fingerprint="a" * 64,
            source_event_id="structured-mcp-write",
            capability="mcp:docs_server:update_record",
            target="record:43",
            resource_key=canonical_resource_key(
                ("docs-server", "data-base", "record:43"), kind="mcp"
            ),
            resource_context={
                "server": "docs-server",
                "resource_kind": "data-base",
                "identifier": "record:43",
            },
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="structured-mcp-write",
            verification_kind="existence",
        )
        mark_attempt_unknown(
            self.contract, rolling["attempt_id"], reason="rolling caller lost reply"
        )
        opaque_caller_blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "other-provider",
                "session_id": "thread-three",
                "fingerprint": "b" * 64,
                "target": "record:43",
            },
        )
        self.assertEqual(
            opaque_caller_blocker["attempt_id"], rolling["attempt_id"]
        )

    def test_human_retry_can_explicitly_transfer_one_attempt_to_new_session(self) -> None:
        first = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            first["attempt_id"],
            reason="the original session lost its completion callback",
        )
        resolved = resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="operator approved one exact retry in the recovery session",
            takeover_provider="codex",
            takeover_session_id="thread-two",
        )
        self.assertEqual(resolved["takeover_provider"], "codex")
        self.assertEqual(resolved["takeover_session_id"], "thread-two")
        self.assertIsNone(
            retry_grant_for_event(
                self.contract,
                fingerprint="f" * 64,
                operation_fingerprint=first["operation_fingerprint"],
                provider="codex",
                session_id="thread-one",
            )
        )
        grant = retry_grant_for_event(
            self.contract,
            fingerprint="f" * 64,
            operation_fingerprint=first["operation_fingerprint"],
            provider="codex",
            session_id="thread-two",
        )
        self.assertEqual(grant["intervention_id"], intervention["intervention_id"])

        retry = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=2,
            fingerprint="f" * 64,
            source_event_id="cross-session-retry",
            capability="mcp:docs:update_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            effect="external_write",
            provider="codex",
            session_id="thread-two",
            idempotency_key="cross-session-retry",
            verification_kind="existence",
        )
        self.assertEqual(retry["predecessor_attempt_id"], first["attempt_id"])
        projection = load_projection(self.contract)
        self.assertEqual(
            projection["interventions"][intervention["intervention_id"]][
                "retry_consumed_by"
            ],
            retry["attempt_id"],
        )

    def test_stored_path_retry_replays_after_target_inode_is_replaced(self) -> None:
        workspace = Path(self.temporary.name) / "workspace"
        workspace.mkdir()
        target = workspace / "manifest.json"
        target.write_text('{"version":"one"}\n', encoding="utf-8")
        resource_key = canonical_resource_key(
            target.name,
            kind="path",
            base=workspace,
        )
        first = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="6" * 64,
            source_event_id="path-write-before-replacement",
            capability="tool:apply_patch",
            target=target.name,
            resource_key=resource_key,
            resource_base=workspace,
            effect="local_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="path-write-before-replacement",
            verification_kind="existence",
        )
        intervention = mark_attempt_unknown(
            self.contract,
            first["attempt_id"],
            reason="the original completion callback was lost",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="operator authorized one exact retry",
        )
        retry = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=2,
            fingerprint="6" * 64,
            source_event_id="path-write-retry-before-replacement",
            capability="tool:apply_patch",
            target=target.name,
            resource_key=resource_key,
            resource_base=workspace,
            effect="local_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="path-write-retry-before-replacement",
            verification_kind="existence",
        )
        replacement = workspace / "replacement.json"
        replacement.write_text('{"version":"two"}\n', encoding="utf-8")
        replacement.replace(target)

        projection = load_projection(self.contract)
        self.assertEqual(
            projection["attempts"][retry["attempt_id"]]["predecessor_attempt_id"],
            first["attempt_id"],
        )
        self.assertNotEqual(
            canonical_resource_key(target.name, kind="path", base=workspace),
            resource_key,
        )

        original_rows = self.authoritative_rows()
        rows = json.loads(json.dumps(original_rows))
        retry_row = next(
            row
            for row in rows
            if row.get("attempt_id") == retry["attempt_id"]
            and row.get("type") == "effect.attempt_created"
        )
        retry_row["resource_sha256"] = "0" * 64
        rows[rows.index(retry_row)] = self.reseal(retry_row)
        with self.assertRaisesRegex(InterventionError, "resource identity"):
            self.restore_rows(rows)

        forged_rows = json.loads(json.dumps(original_rows))
        forged_retry = next(
            row
            for row in forged_rows
            if row.get("attempt_id") == retry["attempt_id"]
            and row.get("type") == "effect.attempt_created"
        )
        current_key = canonical_resource_key(
            target.name,
            kind="path",
            base=workspace,
        )
        forged_retry["resource_key"] = current_key
        forged_retry["resource_sha256"] = hashlib.sha256(
            current_key.encode()
        ).hexdigest()
        forged_retry["operation_fingerprint"] = effect_operation_fingerprint(
            provider=forged_retry["provider"],
            capability=forged_retry["capability"],
            target=forged_retry["target"],
            resource_key=current_key,
            effect=forged_retry["effect"],
            arguments_digest=forged_retry["operation_arguments_digest"],
        )
        forged_rows[forged_rows.index(forged_retry)] = self.reseal(forged_retry)
        with self.assertRaisesRegex(InterventionError, "explicit takeover authority"):
            self.restore_rows(forged_rows)

    def test_takeover_requires_the_sealed_operation_and_is_consumed_once(self) -> None:
        target = "https://example.com/docs/one"
        resource_key = canonical_resource_key(target, kind="uri")
        operation = effect_operation_fingerprint(
            provider="codex",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=resource_key,
            effect="external_write",
            arguments_digest="a" * 64,
        )
        first = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="5" * 64,
            operation_fingerprint=operation,
            operation_arguments_digest="a" * 64,
            source_event_id="sealed-write",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=resource_key,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="sealed-write",
            verification_kind="existence",
        )
        intervention = mark_attempt_unknown(
            self.contract, first["attempt_id"], reason="completion was lost"
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="operator approved the sealed recovery operation",
            takeover_provider="codex",
            takeover_session_id="thread-two",
        )
        wrong_operation = "0" * 64
        self.assertIsNone(
            retry_grant_for_event(
                self.contract,
                fingerprint="5" * 64,
                operation_fingerprint=wrong_operation,
                provider="codex",
                session_id="thread-two",
            )
        )
        event = {
            "phase": "started",
            "effect": "external_write",
            "kind": "mcp",
            "provider": "codex",
            "session_id": "thread-two",
            "fingerprint": "5" * 64,
            "target": "https://EXAMPLE.com:443/docs/./one",
            "effect_resource_key": resource_key,
        }
        self.assertIsNotNone(
            material_event_blocker(
                self.contract,
                {**event, "effect_operation_fingerprint": wrong_operation},
            )
        )
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {**event, "effect_operation_fingerprint": operation},
            )
        )
        retry = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=2,
            fingerprint="6" * 64,
            operation_fingerprint=operation,
            operation_arguments_digest="a" * 64,
            source_event_id="sealed-retry",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=resource_key,
            effect="external_write",
            provider="codex",
            session_id="thread-two",
            idempotency_key="sealed-retry",
            verification_kind="existence",
        )
        self.assertEqual(retry["predecessor_attempt_id"], first["attempt_id"])
        self.assertIsNotNone(
            material_event_blocker(
                self.contract,
                {**event, "effect_operation_fingerprint": operation},
            )
        )

    def test_replay_rejects_fingerprint_fallback_for_sealed_operation(self) -> None:
        target = "https://example.com/docs/sealed"
        resource_key = canonical_resource_key(target, kind="uri")
        operation = effect_operation_fingerprint(
            provider="codex",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=resource_key,
            effect="external_write",
            arguments_digest="a" * 64,
        )
        first = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="5" * 64,
            operation_fingerprint=operation,
            operation_arguments_digest="a" * 64,
            source_event_id="sealed-original",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=resource_key,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="sealed-original",
            verification_kind="existence",
        )
        intervention = mark_attempt_unknown(
            self.contract,
            first["attempt_id"],
            reason="sealed completion callback was lost",
        )
        resolved = resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="operator authorized only the sealed operation",
            takeover_provider="codex",
            takeover_session_id="thread-two",
        )

        # Inject the obsolete selector result so replay, the final append-only
        # integrity boundary, must independently reject the wrong operation.
        with mock.patch("intervention._matching_retry", return_value=resolved):
            wrong_operation = effect_operation_fingerprint(
                provider="codex",
                capability="mcp:docs:update_document",
                target=target,
                resource_key=resource_key,
                effect="external_write",
                arguments_digest="b" * 64,
            )
            with self.assertRaisesRegex(
                InterventionError,
                "retry attempt does not match its explicit takeover authority",
            ):
                begin_attempt(
                    self.contract,
                    intent_id="intent-one",
                    intent_revision=2,
                    fingerprint="5" * 64,
                    operation_fingerprint=wrong_operation,
                    operation_arguments_digest="b" * 64,
                    source_event_id="wrong-sealed-retry",
                    capability="mcp:docs:update_document",
                    target=target,
                    resource_key=resource_key,
                    effect="external_write",
                    provider="codex",
                    session_id="thread-two",
                    idempotency_key="wrong-sealed-retry",
                    verification_kind="existence",
                )

    def test_reprobe_takeover_allows_only_explicit_new_session_to_verify(self) -> None:
        attempt = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="the original session cannot perform the independent read",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="reprobe_authorized",
            evidence="operator selected one recovery session for the read",
            takeover_provider="codex",
            takeover_session_id="thread-two",
        )
        denied = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-three",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="wrong-recovery-lane",
            explicit_attempt_id=attempt["attempt_id"],
            evidence=self.existence(),
        )
        self.assertEqual(denied, [])
        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-two",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="authorized-recovery-lane",
            explicit_attempt_id=attempt["attempt_id"],
            evidence=self.existence(),
        )
        self.assertEqual(verified[0]["state"], "system_verified")

    def test_inconclusive_takeover_reprobe_is_consumed_before_retry(self) -> None:
        attempt = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="the original session cannot perform the read",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="reprobe_authorized",
            evidence="operator selected one recovery read",
            takeover_provider="codex",
            takeover_session_id="thread-two",
        )
        inconclusive = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-two",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="inconclusive-takeover-read",
            explicit_attempt_id=attempt["attempt_id"],
            evidence={"existence": ["0" * 64]},
        )
        self.assertEqual(inconclusive, [])
        consumed = load_projection(self.contract)["interventions"][
            intervention["intervention_id"]
        ]
        self.assertEqual(
            consumed["reprobe_consumed_by"], "inconclusive-takeover-read"
        )
        replay = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-two",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="reused-takeover-read",
            explicit_attempt_id=attempt["attempt_id"],
            evidence=self.existence(),
        )
        self.assertEqual(replay, [])

    def test_git_push_settles_only_after_matching_remote_ref_and_oid_read(self) -> None:
        expected_oid = "a" * 40
        wrong_oid = "b" * 40
        resource = canonical_resource_key(
            {
                "remote": "HTTPS://Git.Example.COM:443/team/repo.git",
                "ref": "refs/heads/main",
                "oid": expected_oid,
            },
            kind="git",
        )
        self.assertEqual(
            resource,
            canonical_resource_key(
                {
                    "remote": "https://git.example.com/team/repo.git",
                    "ref": "refs/heads/main",
                    "oid": wrong_oid,
                },
                kind="git",
            ),
        )
        expected_relation = git_ref_verification_digest(
            remote="https://git.example.com/team/repo.git",
            ref="refs/heads/main",
            oid=expected_oid,
        )
        wrong_relation = git_ref_verification_digest(
            remote="https://git.example.com/team/repo.git",
            ref="refs/heads/main",
            oid=wrong_oid,
        )
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="7" * 64,
            source_event_id="git-push",
            capability="tool:Bash",
            target="git push origin HEAD:refs/heads/main",
            resource_key=resource,
            resource_context={
                "remote": "https://git.example.com/team/repo.git",
                "ref": "refs/heads/main",
                "oid": expected_oid,
            },
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="git-push",
            verification_kind="relation",
            verification_sha256=expected_relation,
        )
        mark_attempt_result(self.contract, attempt["attempt_id"], success=True)
        mismatch = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="tool:Bash",
            target="git ls-remote origin refs/heads/main",
            resource_key=canonical_resource_key(
                {
                    "remote": "https://git.example.com:443/team/./repo.git",
                    "ref": "refs/heads/main",
                },
                kind="git",
            ),
            resource_context={
                "remote": "https://git.example.com:443/team/./repo.git",
                "ref": "refs/heads/main",
                "oid": wrong_oid,
            },
            verification_event_id="wrong-git-oid-read",
            explicit_attempt_id=attempt["attempt_id"],
            evidence={"relation": [wrong_relation]},
        )
        self.assertEqual(mismatch, [])
        self.assertEqual(
            load_projection(self.contract)["attempts"][attempt["attempt_id"]]["state"],
            "verifying",
        )
        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="tool:Bash",
            target="git ls-remote origin refs/heads/main",
            resource_key=resource,
            resource_context={
                "remote": "https://git.example.com/team/repo.git",
                "ref": "refs/heads/main",
                "oid": expected_oid,
            },
            verification_event_id="matching-git-oid-read",
            explicit_attempt_id=attempt["attempt_id"],
            evidence={"relation": [expected_relation]},
        )
        self.assertEqual(verified[0]["state"], "system_verified")
        with self.assertRaisesRegex(InterventionError, "full SHA-1 or SHA-256"):
            git_ref_verification_digest(
                remote="https://git.example.com/team/repo.git",
                ref="refs/heads/main",
                oid="abc123",
            )
        with self.assertRaisesRegex(InterventionError, "relation verification"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=1,
                fingerprint="8" * 64,
                source_event_id="unverifiable-git-push",
                capability="tool:Bash",
                target="git push origin HEAD:refs/heads/main",
                resource_key=resource,
                resource_context={
                    "remote": "https://git.example.com/team/repo.git",
                    "ref": "refs/heads/main",
                    "oid": expected_oid,
                },
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="unverifiable-git-push",
                verification_kind="existence",
            )

        legacy_remote_digest = "c" * 64
        legacy_target = (
            f"git-ref:{legacy_remote_digest}:refs/heads/release"
        )
        legacy = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="9" * 64,
            source_event_id="legacy-git-push",
            capability="tool:Bash",
            target=legacy_target,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="legacy-git-push",
            verification_kind="relation",
            verification_sha256="d" * 64,
        )
        mark_attempt_unknown(
            self.contract, legacy["attempt_id"], reason="legacy push reply was lost"
        )
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "tool",
                "provider": "other-provider",
                "session_id": "thread-two",
                "fingerprint": "e" * 64,
                "target": "git push mirror HEAD:refs/heads/release",
                "effect_resource_key": canonical_resource_key(
                    {
                        "remote": legacy_remote_digest,
                        "ref": "refs/heads/release",
                    },
                    kind="git",
                ),
                "effect_resource_context": {
                    "remote": legacy_remote_digest,
                    "ref": "refs/heads/release",
                    "oid": "e" * 40,
                },
            },
        )
        self.assertIsNone(blocker)

    def test_legacy_git_debt_is_append_only_quarantined_and_idempotent(self) -> None:
        context = {
            "remote": "https://git.example.com/team/repo.git",
            "ref": "refs/heads/dev",
            "oid": "a" * 40,
        }
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="a" * 64,
            source_event_id="legacy-git-control",
            capability="tool:Bash",
            target="git-ref:" + "b" * 64 + ":refs/heads/dev",
            resource_key=canonical_resource_key(context, kind="git"),
            resource_context=context,
            effect="external_write",
            provider="codex",
            session_id="old-thread",
            idempotency_key="legacy-git-control",
            verification_kind="relation",
            verification_sha256=git_ref_verification_digest(**context),
        )
        opened = mark_attempt_unknown(
            self.contract, attempt["attempt_id"], reason="old Git callback missing"
        )
        before = event_store_path(self.contract).read_bytes()
        self.assertEqual(
            reconcile_legacy_git_control_debt(self.contract),
            [attempt["attempt_id"]],
        )
        after = event_store_path(self.contract).read_bytes()
        self.assertTrue(after.startswith(before))
        resolved = load_projection(self.contract)["interventions"][
            opened["intervention_id"]
        ]
        self.assertEqual(resolved["decision"], "abort")
        self.assertEqual(resolved["actor"], LEGACY_GIT_CONTROL_DEBT_ACTOR)
        self.assertEqual(resolved["evidence"], LEGACY_GIT_CONTROL_DEBT_EVIDENCE)
        self.assertEqual(blocking_attempts(load_projection(self.contract)), [])
        once = event_store_path(self.contract).read_bytes()
        self.assertEqual(
            reconcile_legacy_git_control_debt(self.contract),
            [attempt["attempt_id"]],
        )
        self.assertEqual(event_store_path(self.contract).read_bytes(), once)

    def test_human_attestation_remains_distinct_from_system_verification(self) -> None:
        attempt = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="remote reply did not prove the final state",
        )
        resolved = resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="human_attested_success",
            evidence="operator inspected remote record 42",
        )
        self.assertEqual(resolved["decision"], "human_attested_success")
        state = load_projection(self.contract)["attempts"][attempt["attempt_id"]]
        self.assertEqual(state["state"], "human_attested_success")
        self.assertEqual(state["state_source"], "human_attestation")
        self.assertNotEqual(state["state"], "system_verified")

    def test_retry_authorization_creates_a_new_linked_attempt_and_is_one_shot(self) -> None:
        first = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            first["attempt_id"],
            reason="network ended after dispatch",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="remote system proves no record exists",
        )
        grant = retry_grant_for_event(
            self.contract,
            fingerprint="f" * 64,
            operation_fingerprint=first["operation_fingerprint"],
            provider="codex",
            session_id="thread-one",
        )
        self.assertEqual(grant["intervention_id"], intervention["intervention_id"])
        retry_event = {
            "phase": "started",
            "effect": "external_write",
            "kind": "mcp",
            "provider": "codex",
            "session_id": "thread-one",
            "fingerprint": "f" * 64,
            "target": "doc://one",
            "effect_resource_key": canonical_resource_key(
                "doc://one", kind="uri"
            ),
            "effect_operation_fingerprint": first["operation_fingerprint"],
        }
        self.assertIsNone(material_event_blocker(self.contract, retry_event))
        second = self.begin("dispatch-2")
        self.assertEqual(second["predecessor_attempt_id"], first["attempt_id"])
        self.assertEqual(second["retry_intervention_id"], intervention["intervention_id"])
        self.assertIsNone(
            retry_grant_for_event(
                self.contract,
                fingerprint="f" * 64,
                operation_fingerprint=first["operation_fingerprint"],
                provider="codex",
                session_id="thread-one",
            )
        )
        self.assertIsNotNone(material_event_blocker(self.contract, retry_event))
        mark_attempt_result(self.contract, second["attempt_id"], success=True)
        verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="retry-read",
            explicit_attempt_id=second["attempt_id"],
            evidence=self.existence(),
        )
        self.assertIsNone(material_event_blocker(self.contract, retry_event))

    def test_retry_attempt_consumes_grant_in_one_authority_row_at_every_cut(self) -> None:
        for preconsumed in (False, True):
            with self.subTest(preconsumed=preconsumed):
                contract = self.contract.with_name(
                    f"atomic-{int(preconsumed)}.active.json"
                )
                contract.write_text("{}\n", encoding="utf-8")
                resource_key = canonical_resource_key("doc://one", kind="uri")

                def dispatch(idempotency_key: str) -> dict:
                    return begin_attempt(
                        contract,
                        intent_id="intent-one",
                        intent_revision=2,
                        fingerprint="f" * 64,
                        source_event_id=f"event-{idempotency_key}",
                        capability="mcp:docs:update_document",
                        target="doc://one",
                        resource_key=resource_key,
                        effect="external_write",
                        provider="codex",
                        session_id="thread-one",
                        idempotency_key=idempotency_key,
                        verification_kind="existence",
                    )

                first = dispatch("original")
                intervention = mark_attempt_unknown(
                    contract,
                    first["attempt_id"],
                    reason="network ended after dispatch",
                )
                resolve_intervention(
                    contract,
                    intervention["intervention_id"],
                    decision="retry_authorized",
                    evidence="operator authorized exactly one retry",
                )
                if preconsumed:
                    before = load_projection(contract)["sequence"]
                    dispatch("preconsumed-retry")
                    self.assertEqual(load_projection(contract)["sequence"], before + 1)

                successes = 0
                for suffix in ("first", "second"):
                    try:
                        dispatch(f"candidate-{suffix}")
                    except InterventionError:
                        pass
                    else:
                        successes += 1
                self.assertEqual(successes, 0 if preconsumed else 1)
                projection = load_projection(contract)
                linked = [
                    attempt
                    for attempt in projection["attempts"].values()
                    if attempt.get("retry_intervention_id")
                    == intervention["intervention_id"]
                ]
                self.assertEqual(len(linked), 1)

    def test_system_retry_preserves_unknown_and_is_exactly_bound(self) -> None:
        first = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            first["attempt_id"],
            reason="old Hook lost the installation completion callback",
        )
        resolved = authorize_system_retry(
            self.contract,
            intervention["intervention_id"],
            fingerprint="f" * 64,
            provider="codex",
            session_id="thread-one",
            target="doc://one",
            evidence='{"grant_id":"sealed-install","schema":"system-retry"}',
        )

        projection = load_projection(self.contract)
        self.assertEqual(resolved["decision"], "retry_authorized")
        self.assertEqual(resolved["actor"], "system-continuation-grant")
        self.assertEqual(projection["attempts"][first["attempt_id"]]["state"], "unknown")
        grant = retry_grant_for_event(
            self.contract,
            fingerprint="f" * 64,
            operation_fingerprint=first["operation_fingerprint"],
            provider="codex",
            session_id="thread-one",
        )
        self.assertEqual(grant["intervention_id"], intervention["intervention_id"])

    def test_system_retry_rejects_cross_identity_substitution(self) -> None:
        first = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            first["attempt_id"],
            reason="old operation remains unknown",
        )
        mismatches = (
            {"fingerprint": "e" * 64},
            {"provider": "claude"},
            {"session_id": "thread-two"},
            {"target": "doc://two"},
        )
        base = {
            "fingerprint": "f" * 64,
            "provider": "codex",
            "session_id": "thread-one",
            "target": "doc://one",
            "evidence": "sealed continuation grant",
        }
        for mismatch in mismatches:
            with self.subTest(mismatch=mismatch):
                with self.assertRaisesRegex(InterventionError, "identity does not match"):
                    authorize_system_retry(
                        self.contract,
                        intervention["intervention_id"],
                        **{**base, **mismatch},
                    )
        current = load_projection(self.contract)["interventions"][
            intervention["intervention_id"]
        ]
        self.assertEqual(current["status"], "open")
        self.assertIsNone(current["decision"])

    def test_semantic_retry_is_exactly_bound_and_consumed_once(self) -> None:
        first = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            first["attempt_id"],
            reason="a hot-updated launcher changed only the observable command spelling",
        )
        authorize_system_retry(
            self.contract,
            intervention["intervention_id"],
            fingerprint="f" * 64,
            provider="codex",
            session_id="thread-one",
            target="doc://one",
            evidence="sealed continuation grant",
        )

        mismatches = (
            {"provider": "claude"},
            {"session_id": "thread-two"},
            {"capability": "mcp:docs:delete_document"},
            {"target": "doc://two"},
            {"effect": "destructive"},
        )
        base = {
            "intent_id": "intent-one",
            "intent_revision": 2,
            "fingerprint": "e" * 64,
            "operation_arguments_digest": "f" * 64,
            "source_event_id": "semantic-retry",
            "capability": "mcp:docs:update_document",
            "target": "doc://one",
            "resource_key": canonical_resource_key("doc://one", kind="uri"),
            "effect": "external_write",
            "provider": "codex",
            "session_id": "thread-one",
            "verification_kind": "existence",
            "semantic_retry_intervention_id": intervention["intervention_id"],
        }
        for index, mismatch in enumerate(mismatches):
            with self.subTest(mismatch=mismatch):
                candidate = {**base, **mismatch}
                if "target" in mismatch:
                    candidate["resource_key"] = canonical_resource_key(
                        mismatch["target"], kind="uri"
                    )
                with self.assertRaisesRegex(
                    InterventionError,
                    "semantic retry authority does not match",
                ):
                    begin_attempt(
                        self.contract,
                        idempotency_key=f"semantic-mismatch-{index}",
                        **candidate,
                    )

        second = begin_attempt(
            self.contract,
            idempotency_key="semantic-retry-valid",
            **base,
        )
        self.assertEqual(second["predecessor_attempt_id"], first["attempt_id"])
        self.assertEqual(
            second["retry_intervention_id"],
            intervention["intervention_id"],
        )
        projection = load_projection(self.contract)
        consumed = projection["interventions"][intervention["intervention_id"]]
        self.assertEqual(consumed["retry_consumed_by"], second["attempt_id"])
        self.assertEqual(projection["attempts"][first["attempt_id"]]["state"], "unknown")

        with self.assertRaisesRegex(
            InterventionError,
            "semantic retry authority does not match",
        ):
            begin_attempt(
                self.contract,
                idempotency_key="semantic-retry-second-use",
                **{**base, "fingerprint": "d" * 64},
            )

    def test_verified_compensation_resolves_dependency_without_rewriting_old_unknown(self) -> None:
        old_digest = "a" * 64
        new_digest = "b" * 64
        old = self.begin(
            "old-install",
            verification_kind="content",
            verification_sha256=old_digest,
        )
        old_intervention = mark_attempt_unknown(
            self.contract,
            old["attempt_id"],
            reason="old installation changed part of the target before proof was lost",
        )
        compensation = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=2,
            fingerprint="c" * 64,
            source_event_id="compensating-install",
            capability="mcp:docs:update_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="compensating-install",
            verification_kind="content",
            verification_sha256=new_digest,
            compensates_attempt_id=old["attempt_id"],
        )
        mark_attempt_result(
            self.contract,
            compensation["attempt_id"],
            success=True,
        )

        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:get_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="independent-compensation-read",
            explicit_attempt_id=compensation["attempt_id"],
            evidence={"content": [new_digest]},
        )

        self.assertEqual([row["attempt_id"] for row in verified], [compensation["attempt_id"]])
        projection = load_projection(self.contract)
        self.assertEqual(projection["attempts"][old["attempt_id"]]["state"], "unknown")
        self.assertEqual(
            projection["attempts"][compensation["attempt_id"]]["state"],
            "system_verified",
        )
        resolved = projection["interventions"][old_intervention["intervention_id"]]
        self.assertEqual(resolved["decision"], "system_compensated")
        self.assertEqual(
            resolved["compensated_by_attempt_id"],
            compensation["attempt_id"],
        )
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    "phase": "started",
                    "effect": "external_write",
                    "kind": "mcp",
                    "provider": "codex",
                    "session_id": "thread-one",
                    "fingerprint": "d" * 64,
                    "target": "doc://one",
                },
            )
        )

    def test_failed_compensation_keeps_both_unknown_debts_open(self) -> None:
        old = self.begin("old-install")
        mark_attempt_unknown(
            self.contract,
            old["attempt_id"],
            reason="old installation is unknown",
        )
        compensation = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=2,
            fingerprint="c" * 64,
            source_event_id="failed-compensation",
            capability="mcp:docs:update_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="failed-compensation",
            verification_kind="existence",
            compensates_attempt_id=old["attempt_id"],
        )
        mark_attempt_result(
            self.contract,
            compensation["attempt_id"],
            success=False,
            reason="compensation returned failure without proving rollback",
        )

        projection = load_projection(self.contract)
        self.assertEqual(projection["attempts"][old["attempt_id"]]["state"], "unknown")
        self.assertEqual(
            projection["attempts"][compensation["attempt_id"]]["state"],
            "unknown",
        )
        self.assertEqual(
            sum(
                1
                for row in projection["interventions"].values()
                if row["status"] in {"open", "acknowledged"}
            ),
            2,
        )

    def test_compensation_requires_same_target_open_unknown_predecessor(self) -> None:
        old = self.begin("old-install")
        mark_attempt_unknown(
            self.contract,
            old["attempt_id"],
            reason="old installation is unknown",
        )
        with self.assertRaisesRegex(InterventionError, "same-resource proof"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=2,
                fingerprint="c" * 64,
                source_event_id="wrong-target-compensation",
                capability="mcp:docs:update_document",
                target="doc://two",
                resource_key=canonical_resource_key("doc://two", kind="uri"),
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="wrong-target-compensation",
                verification_kind="existence",
                compensates_attempt_id=old["attempt_id"],
            )

    def test_late_system_verification_revokes_an_unconsumed_retry_grant(self) -> None:
        attempt = self.begin()
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="network ended after dispatch",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="initial lookup was inconclusive",
        )
        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-one",
            capability="mcp:docs:read_document",
            target="doc://one",
            resource_key=canonical_resource_key("doc://one", kind="uri"),
            verification_event_id="late-read",
            explicit_attempt_id=attempt["attempt_id"],
            evidence=self.existence(),
        )
        self.assertEqual(verified[0]["state"], "system_verified")
        self.assertIsNone(
            retry_grant_for_event(
                self.contract,
                fingerprint="f" * 64,
                operation_fingerprint=attempt["operation_fingerprint"],
                provider="codex",
                session_id="thread-one",
            )
        )

    def test_inconclusive_reprobe_opens_a_new_intervention_round(self) -> None:
        attempt = self.begin()
        first = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="first probe was inconclusive",
        )
        resolve_intervention(
            self.contract,
            first["intervention_id"],
            decision="reprobe_authorized",
            evidence="operator authorized one additional read-only probe",
        )
        second = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="the authorized reprobe was still inconclusive",
        )
        self.assertNotEqual(first["intervention_id"], second["intervention_id"])
        projection = load_projection(self.contract)
        self.assertEqual(len(projection["interventions"]), 2)
        self.assertEqual(projection["interventions"][first["intervention_id"]]["status"], "resolved")
        self.assertEqual(projection["interventions"][second["intervention_id"]]["status"], "open")

    def test_projection_is_rebuilt_from_append_only_log(self) -> None:
        attempt = self.begin()
        projection_path(self.contract).write_text('{"corrupt":true}\n', encoding="utf-8")
        rebuilt = load_projection(self.contract)
        self.assertIn(attempt["attempt_id"], rebuilt["attempts"])
        rows = event_store_path(self.contract).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)

    def test_resolution_requires_evidence_and_is_immutable(self) -> None:
        attempt = self.begin()
        intervention = mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="unknown")
        with self.assertRaisesRegex(InterventionError, "non-empty evidence"):
            resolve_intervention(
                self.contract,
                intervention["intervention_id"],
                decision="confirmed_failed",
                evidence="",
            )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="confirmed_failed",
            evidence="remote query returned a stable absent result",
        )
        with self.assertRaisesRegex(InterventionError, "already resolved"):
            resolve_intervention(
                self.contract,
                intervention["intervention_id"],
                decision="retry_authorized",
                evidence="changed my mind",
            )

    def test_inventory_counts_interactive_truth(self) -> None:
        attempt = self.begin()
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="unknown")
        values = inventory(self.home)
        self.assertEqual(values["intervention_stores"], 1)
        self.assertEqual(values["effect_unknown"], 1)
        self.assertEqual(values["interventions_open"], 1)
        self.assertEqual(summary(self.contract)["interventions_open"], 1)

    def test_inventory_replays_archived_truth_without_double_counting_live_store(self) -> None:
        attempt = self.begin()
        intervention = mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="unknown")
        archive_store(
            self.contract,
            self.home / "interventions" / "archive",
            slug="task-one",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="abort",
            evidence="operator abandoned the operation and authorized no retry",
        )
        manifest = archive_store(
            self.contract,
            self.home / "interventions" / "archive",
            slug="task-one",
        )
        self.assertIsNotNone(manifest)
        self.assertEqual(inventory(self.home)["intervention_stores"], 1)
        event_store_path(self.contract).unlink()
        projection_path(self.contract).unlink()
        values = inventory(self.home)
        self.assertEqual(values["intervention_stores"], 1)
        self.assertEqual(values["effect_unknown"], 1)
        self.assertEqual(values["effect_blocking"], 1)
        self.assertEqual(values["effect_readiness_blocking"], 0)
        self.assertEqual(values["effect_quarantined"], 1)
        self.assertEqual(values["interventions_open"], 0)
        self.assertEqual(values["interventions_resolved"], 1)

    def test_managed_agent_process_cannot_claim_a_human_intervention_decision(self) -> None:
        attempt = self.begin()
        intervention = mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="unknown")
        environment = dict(os.environ)
        environment.update(
            {
                "SULDE_KB_HOME": str(self.home),
                "SULDE_GUARDIAN_STREAM_OWNER": "1",
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "intervention-resolve",
                intervention["intervention_id"],
                "--decision",
                "abort",
                "--evidence",
                "agent tried to impersonate a human",
                "--contract",
                str(self.contract),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("paired host-native decision path", completed.stderr)
        self.assertEqual(
            load_projection(self.contract)["interventions"][intervention["intervention_id"]]["status"],
            "open",
        )
        with mock.patch.dict(
            os.environ,
            {"SULDE_GUARDIAN_STREAM_OWNER": "1"},
        ):
            with self.assertRaisesRegex(InterventionError, "cannot mutate authoritative"):
                resolve_intervention(
                    self.contract,
                    intervention["intervention_id"],
                    decision="abort",
                    evidence="direct library impersonation",
                )

    def test_replay_rederives_uri_target_even_after_event_id_is_resealed(self) -> None:
        target = "https://example.com/docs/one"
        key = canonical_resource_key(target, kind="uri")
        begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="1" * 64,
            source_event_id="uri-authority",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=key,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="uri-authority",
            verification_kind="existence",
        )
        rows = self.authoritative_rows()
        rows[0]["target"] = "https://example.com/docs/two"
        rows[0]["target_sha256"] = hashlib.sha256(
            rows[0]["target"].encode()
        ).hexdigest()
        rows[0] = self.reseal(rows[0])
        with self.assertRaisesRegex(InterventionError, "target|resource"):
            self.restore_rows(rows)

    def test_replay_rederives_mcp_identifier_server_and_kind(self) -> None:
        target = "record:42"
        context = {
            "server": "crm-server",
            "resource_kind": "record",
            "identifier": target,
        }
        key = canonical_resource_key(context, kind="mcp")
        begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="2" * 64,
            source_event_id="mcp-authority",
            capability="mcp:crm:update_record",
            target=target,
            resource_key=key,
            resource_context=context,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="mcp-authority",
            verification_kind="existence",
        )
        original = self.authoritative_rows()[0]
        for field, replacement in (
            ("identifier", "record:43"),
            ("server", "other-server"),
            ("resource_kind", "contact"),
        ):
            with self.subTest(field=field):
                changed = json.loads(json.dumps(original))
                changed["resource_context"][field] = replacement
                if field == "identifier":
                    changed["target"] = replacement
                    changed["target_sha256"] = hashlib.sha256(
                        replacement.encode()
                    ).hexdigest()
                changed = self.reseal(changed)
                with self.assertRaisesRegex(InterventionError, "MCP|resource"):
                    self.restore_rows([changed])

    def test_replay_rederives_git_relation_target_and_operation(self) -> None:
        context = {
            "remote": "https://git.example.com/team/repo.git",
            "ref": "refs/heads/main",
            "oid": "a" * 40,
        }
        target = "git push origin HEAD:refs/heads/main"
        key = canonical_resource_key(context, kind="git")
        relation = git_ref_verification_digest(**context)
        operation = effect_operation_fingerprint(
            provider="codex",
            capability="tool:Bash",
            target=target,
            resource_key=key,
            effect="external_write",
            arguments_digest="3" * 64,
        )
        begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="3" * 64,
            operation_fingerprint=operation,
            source_event_id="git-authority",
            capability="tool:Bash",
            target=target,
            resource_key=key,
            resource_context=context,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="git-authority",
            verification_kind="relation",
            verification_sha256=relation,
        )
        original = self.authoritative_rows()[0]
        changes = (
            {"target": "git push origin HEAD:refs/heads/release"},
            {"verification_sha256": "b" * 64},
            {"operation_fingerprint": "c" * 64},
        )
        for fields in changes:
            with self.subTest(fields=fields):
                changed = {**original, **fields}
                if "target" in fields:
                    changed["target_sha256"] = hashlib.sha256(
                        changed["target"].encode()
                    ).hexdigest()
                changed = self.reseal(changed)
                with self.assertRaisesRegex(
                    InterventionError, "Git|relation|operation|resource"
                ):
                    self.restore_rows([changed])

    def test_keyless_identity_can_block_but_cannot_settle_typed_or_reverse(self) -> None:
        target = "doc://one"
        key = canonical_resource_key(target, kind="uri")
        typed = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="4" * 64,
            source_event_id="typed-write",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=key,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="typed-write",
            verification_kind="existence",
        )
        mark_attempt_result(self.contract, typed["attempt_id"], success=True)
        self.assertEqual(
            verify_from_read(
                self.contract,
                provider="codex",
                session_id="thread-one",
                capability="mcp:docs:read_document",
                target=target,
                verification_event_id="keyless-read",
                explicit_attempt_id=typed["attempt_id"],
                evidence=self.existence(target),
            ),
            [],
        )

        legacy_contract = self.contract.with_name("keyless.active.json")
        legacy_contract.write_text("{}\n", encoding="utf-8")
        legacy = begin_attempt(
            legacy_contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="5" * 64,
            source_event_id="keyless-write",
            capability="mcp:docs:update_document",
            target=target,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="keyless-write",
            verification_kind="existence",
        )
        mark_attempt_result(legacy_contract, legacy["attempt_id"], success=True)
        self.assertEqual(
            verify_from_read(
                legacy_contract,
                provider="codex",
                session_id="thread-one",
                capability="mcp:docs:read_document",
                target=target,
                resource_key=key,
                verification_event_id="typed-read",
                explicit_attempt_id=legacy["attempt_id"],
                evidence=self.existence(target),
            ),
            [],
        )

    def test_keyless_identity_cannot_authorize_compensation_in_either_direction(self) -> None:
        target = "doc://one"
        key = canonical_resource_key(target, kind="uri")
        typed = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="6" * 64,
            source_event_id="typed-unknown",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=key,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="typed-unknown",
            verification_kind="existence",
        )
        mark_attempt_unknown(self.contract, typed["attempt_id"], reason="lost")
        with self.assertRaisesRegex(InterventionError, "compensation|proof|typed"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=2,
                fingerprint="7" * 64,
                source_event_id="keyless-compensation",
                capability="mcp:docs:update_document",
                target=target,
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="keyless-compensation",
                verification_kind="existence",
                compensates_attempt_id=typed["attempt_id"],
            )

        other_contract = self.contract.with_name("two.active.json")
        other_contract.write_text("{}\n", encoding="utf-8")
        keyless = begin_attempt(
            other_contract,
            intent_id="intent-two",
            intent_revision=1,
            fingerprint="8" * 64,
            source_event_id="keyless-unknown",
            capability="mcp:docs:update_document",
            target=target,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="keyless-unknown",
            verification_kind="existence",
        )
        mark_attempt_unknown(other_contract, keyless["attempt_id"], reason="lost")
        with self.assertRaisesRegex(InterventionError, "compensation|proof|typed"):
            begin_attempt(
                other_contract,
                intent_id="intent-two",
                intent_revision=2,
                fingerprint="9" * 64,
                source_event_id="typed-compensation",
                capability="mcp:docs:update_document",
                target=target,
                resource_key=key,
                effect="external_write",
                provider="codex",
                session_id="thread-one",
                idempotency_key="typed-compensation",
                verification_kind="existence",
                compensates_attempt_id=keyless["attempt_id"],
            )

    def test_keyless_current_identity_blocks_typed_debt_at_both_dispatch_entries(self) -> None:
        target = "provider-record:A"
        key = canonical_resource_key(target, kind="opaque")
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="1" * 64,
            source_event_id="typed-opaque-debt",
            capability="mcp:records:update",
            target=target,
            resource_key=key,
            resource_context={"schema": "exact", "value": target},
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="typed-opaque-debt",
            verification_kind="existence",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost")
        keyless_target = "provider-record:B"
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "codex",
                "session_id": "thread-two",
                "fingerprint": "2" * 64,
                "target": keyless_target,
            },
        )
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])
        with self.assertRaisesRegex(InterventionError, "blocker|debt"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=2,
                fingerprint="3" * 64,
                source_event_id="keyless-unresolved-dispatch",
                capability="mcp:records:update",
                target=keyless_target,
                effect="external_write",
                provider="codex",
                session_id="thread-two",
                idempotency_key="keyless-unresolved-dispatch",
                verification_kind="existence",
            )

    def test_keyless_history_cannot_prove_typed_opaque_is_different(self) -> None:
        target = "provider-record:A"
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="4" * 64,
            source_event_id="keyless-opaque-debt",
            capability="mcp:records:update",
            target=target,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="keyless-opaque-debt",
            verification_kind="existence",
        )
        mark_attempt_unknown(self.contract, attempt["attempt_id"], reason="lost")
        typed_target = "provider-record:B"
        typed_key = canonical_resource_key(typed_target, kind="opaque")
        context = {"schema": "exact", "value": typed_target}
        blocker = material_event_blocker(
            self.contract,
            {
                "phase": "started",
                "effect": "external_write",
                "kind": "mcp",
                "provider": "codex",
                "session_id": "thread-two",
                "fingerprint": "5" * 64,
                "target": typed_target,
                "effect_resource_key": typed_key,
                "effect_resource_context": context,
            },
        )
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])
        with self.assertRaisesRegex(InterventionError, "blocker|debt"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=2,
                fingerprint="6" * 64,
                source_event_id="typed-opaque-dispatch",
                capability="mcp:records:update",
                target=typed_target,
                resource_key=typed_key,
                resource_context=context,
                effect="external_write",
                provider="codex",
                session_id="thread-two",
                idempotency_key="typed-opaque-dispatch",
                verification_kind="existence",
            )

    def test_retarget_history_blocks_old_alias_at_both_dispatch_entries(self) -> None:
        old_target = "https://example.com/docs/old"
        old_key = canonical_resource_key(old_target, kind="uri")
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="7" * 64,
            source_event_id="alias-source",
            capability="mcp:docs:update_document",
            target=old_target,
            resource_key=old_key,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="alias-source",
            verification_kind="existence",
        )
        new_target = "https://example.com/docs/current"
        new_key = canonical_resource_key(new_target, kind="uri")
        arguments_digest = "8" * 64
        rebound = resolve_attempt_target(
            self.contract,
            attempt["attempt_id"],
            target=new_target,
            resource_key=new_key,
            operation_fingerprint=effect_operation_fingerprint(
                provider="codex",
                capability="mcp:docs:update_document",
                target=new_target,
                resource_key=new_key,
                effect="external_write",
                arguments_digest=arguments_digest,
            ),
            operation_arguments_digest=arguments_digest,
            verification_kind="existence",
            expected_target_sha256=attempt["target_sha256"],
            expected_resource_sha256=attempt["resource_sha256"],
            expected_operation_fingerprint=attempt["operation_fingerprint"],
        )
        projection_path(self.contract).unlink(missing_ok=True)
        old_event = {
            "phase": "started",
            "effect": "external_write",
            "kind": "mcp",
            "provider": "codex",
            "session_id": "thread-two",
            "fingerprint": "9" * 64,
            "target": old_target,
            "effect_resource_key": old_key,
        }
        blocker = material_event_blocker(self.contract, old_event)
        self.assertEqual(blocker["attempt_id"], attempt["attempt_id"])
        with self.assertRaisesRegex(InterventionError, "blocker|debt"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=2,
                fingerprint="a" * 64,
                source_event_id="old-alias-dispatch",
                capability="mcp:docs:update_document",
                target=old_target,
                resource_key=old_key,
                effect="external_write",
                provider="codex",
                session_id="thread-two",
                idempotency_key="old-alias-dispatch",
                verification_kind="existence",
            )

        unrelated_target = "https://example.com/docs/unrelated"
        unrelated_key = canonical_resource_key(unrelated_target, kind="uri")
        self.assertIsNone(
            material_event_blocker(
                self.contract,
                {
                    **old_event,
                    "target": unrelated_target,
                    "effect_resource_key": unrelated_key,
                },
            )
        )
        unrelated = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=2,
            fingerprint="b" * 64,
            source_event_id="unrelated-dispatch",
            capability="mcp:docs:update_document",
            target=unrelated_target,
            resource_key=unrelated_key,
            effect="external_write",
            provider="codex",
            session_id="thread-two",
            idempotency_key="unrelated-dispatch",
            verification_kind="existence",
        )
        self.assertEqual(unrelated["state"], "dispatched")
        self.assertEqual(rebound["resource_key"], new_key)

    def test_retarget_old_alias_cannot_verify_reprobe_or_compensate(self) -> None:
        old_target = "https://example.com/docs/old-settlement"
        old_key = canonical_resource_key(old_target, kind="uri")
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="c" * 64,
            source_event_id="settlement-alias-source",
            capability="mcp:docs:update_document",
            target=old_target,
            resource_key=old_key,
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="settlement-alias-source",
            verification_kind="existence",
        )
        current_target = "https://example.com/docs/current-settlement"
        current_key = canonical_resource_key(current_target, kind="uri")
        arguments_digest = "d" * 64
        resolve_attempt_target(
            self.contract,
            attempt["attempt_id"],
            target=current_target,
            resource_key=current_key,
            operation_fingerprint=effect_operation_fingerprint(
                provider="codex",
                capability="mcp:docs:update_document",
                target=current_target,
                resource_key=current_key,
                effect="external_write",
                arguments_digest=arguments_digest,
            ),
            operation_arguments_digest=arguments_digest,
            verification_kind="existence",
            expected_target_sha256=attempt["target_sha256"],
            expected_resource_sha256=attempt["resource_sha256"],
            expected_operation_fingerprint=attempt["operation_fingerprint"],
        )
        intervention = mark_attempt_unknown(
            self.contract,
            attempt["attempt_id"],
            reason="retarget completion was lost",
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="reprobe_authorized",
            evidence="operator authorized a read of the current identity",
            takeover_provider="codex",
            takeover_session_id="thread-two",
        )
        self.assertEqual(
            verify_from_read(
                self.contract,
                provider="codex",
                session_id="thread-two",
                capability="mcp:docs:read_document",
                target=old_target,
                resource_key=old_key,
                verification_event_id="old-alias-reprobe",
                explicit_attempt_id=attempt["attempt_id"],
                evidence=self.existence(old_target),
            ),
            [],
        )
        self.assertIsNone(
            load_projection(self.contract)["interventions"][
                intervention["intervention_id"]
            ]["reprobe_consumed_by"]
        )
        with self.assertRaisesRegex(InterventionError, "compensation|proof|typed"):
            begin_attempt(
                self.contract,
                intent_id="intent-one",
                intent_revision=2,
                fingerprint="e" * 64,
                source_event_id="old-alias-compensation",
                capability="mcp:docs:update_document",
                target=old_target,
                resource_key=old_key,
                effect="external_write",
                provider="codex",
                session_id="thread-two",
                idempotency_key="old-alias-compensation",
                verification_kind="existence",
                compensates_attempt_id=attempt["attempt_id"],
            )
        verified = verify_from_read(
            self.contract,
            provider="codex",
            session_id="thread-two",
            capability="mcp:docs:read_document",
            target=current_target,
            resource_key=current_key,
            verification_event_id="current-identity-reprobe",
            explicit_attempt_id=attempt["attempt_id"],
            evidence=self.existence(current_target),
        )
        self.assertEqual(verified[0]["state"], "system_verified")

    def test_typed_attempt_cannot_be_retargeted_by_changing_only_raw_target(self) -> None:
        target = "https://example.com/docs/one"
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="a" * 64,
            source_event_id="typed-retarget",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=canonical_resource_key(target, kind="uri"),
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="typed-retarget",
            verification_kind="existence",
        )
        with self.assertRaisesRegex(InterventionError, "rebind|typed|identity"):
            resolve_attempt_target(
                self.contract,
                attempt["attempt_id"],
                target="https://example.com/docs/two",
            )

    def test_typed_attempt_full_cas_rebind_replays_and_keeps_identity_history(self) -> None:
        old_target = "https://example.com/docs/one"
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="a" * 64,
            source_event_id="typed-cas-source",
            capability="mcp:docs:update_document",
            target=old_target,
            resource_key=canonical_resource_key(old_target, kind="uri"),
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="typed-cas-source",
            verification_kind="existence",
        )
        new_target = "https://example.com/docs/two"
        new_key = canonical_resource_key(new_target, kind="uri")
        arguments_digest = "d" * 64
        new_operation = effect_operation_fingerprint(
            provider="codex",
            capability="mcp:docs:update_document",
            target=new_target,
            resource_key=new_key,
            effect="external_write",
            arguments_digest=arguments_digest,
        )
        rebound = resolve_attempt_target(
            self.contract,
            attempt["attempt_id"],
            target=new_target,
            resource_key=new_key,
            operation_fingerprint=new_operation,
            operation_arguments_digest=arguments_digest,
            verification_kind="existence",
            expected_target_sha256=attempt["target_sha256"],
            expected_resource_sha256=attempt["resource_sha256"],
            expected_operation_fingerprint=attempt["operation_fingerprint"],
        )
        self.assertEqual(rebound["target"], new_target)
        self.assertEqual(rebound["resource_key"], new_key)
        self.assertEqual(rebound["identity_history"][0]["target"], old_target)
        rows = self.authoritative_rows()
        self.assertEqual([row["target"] for row in rows], [old_target, new_target])
        self.assertEqual(
            [identity["target"] for identity in rows[1]["identity_history"]],
            [old_target],
        )
        self.assertEqual(
            load_projection(self.contract)["attempts"][attempt["attempt_id"]][
                "operation_fingerprint"
            ],
            new_operation,
        )

        tampered = json.loads(json.dumps(rows))
        tampered[1]["expected_old_identity"]["target"] = new_target
        tampered[1] = self.reseal(tampered[1])
        with self.assertRaisesRegex(InterventionError, "old identity|CAS"):
            self.restore_rows(tampered)

        third_target = "https://example.com/docs/three"
        third_key = canonical_resource_key(third_target, kind="uri")
        third_arguments = "e" * 64
        resolve_attempt_target(
            self.contract,
            attempt["attempt_id"],
            target=third_target,
            resource_key=third_key,
            operation_fingerprint=effect_operation_fingerprint(
                provider="codex",
                capability="mcp:docs:update_document",
                target=third_target,
                resource_key=third_key,
                effect="external_write",
                arguments_digest=third_arguments,
            ),
            operation_arguments_digest=third_arguments,
            verification_kind="existence",
            expected_target_sha256=rebound["target_sha256"],
            expected_resource_sha256=rebound["resource_sha256"],
            expected_operation_fingerprint=rebound["operation_fingerprint"],
        )
        rows = self.authoritative_rows()
        self.assertEqual(
            [identity["target"] for identity in rows[2]["identity_history"]],
            [old_target, new_target],
        )
        mutations = (
            ("deleted", lambda row: row["identity_history"].pop(0)),
            (
                "changed-version",
                lambda row: row["identity_history"][0].__setitem__(
                    "resource_key",
                    row["identity_history"][0]["resource_key"].removeprefix("v2:"),
                ),
            ),
            (
                "changed-context",
                lambda row: row["identity_history"][0].__setitem__(
                    "resource_context", {"schema": "forged"}
                ),
            ),
            (
                "forged",
                lambda row: row["identity_history"].append(
                    dict(row["identity_history"][-1])
                ),
            ),
        )
        for name, mutate in mutations:
            with self.subTest(history=name):
                changed = json.loads(json.dumps(rows))
                mutate(changed[2])
                changed[2] = self.reseal(changed[2])
                with self.assertRaisesRegex(
                    InterventionError, "identity history|append-only"
                ):
                    self.restore_rows(changed)

        caller_authored = json.loads(json.dumps(rows))
        caller_authored[0]["identity_history"] = []
        caller_authored[0] = self.reseal(caller_authored[0])
        with self.assertRaisesRegex(InterventionError, "caller-authored"):
            self.restore_rows(caller_authored)

    def test_replay_rederives_attempt_id_resource_digest_and_legacy_authority(self) -> None:
        target = "https://example.com/docs/authority"
        attempt = begin_attempt(
            self.contract,
            intent_id="intent-one",
            intent_revision=1,
            fingerprint="e" * 64,
            source_event_id="authority-fields",
            capability="mcp:docs:update_document",
            target=target,
            resource_key=canonical_resource_key(target, kind="uri"),
            effect="external_write",
            provider="codex",
            session_id="thread-one",
            idempotency_key="authority-fields",
            verification_kind="existence",
        )
        original = self.authoritative_rows()[0]
        for fields in (
            {"idempotency_key": "resealed-idempotency"},
            {"resource_sha256": "0" * 64},
        ):
            with self.subTest(fields=fields):
                changed = self.reseal({**original, **fields})
                with self.assertRaisesRegex(
                    InterventionError, "idempotency|resource identity"
                ):
                    self.restore_rows([changed])

        historical = dict(original)
        historical["schema"] = "sulde-intervention-event-v1"
        historical.pop("operation_arguments_digest")
        historical = self.reseal(historical)
        self.restore_rows([historical])
        replayed = load_projection(self.contract)["attempts"][attempt["attempt_id"]]
        self.assertFalse(replayed["replay_authoritative"])
        intervention = mark_attempt_unknown(
            self.contract, attempt["attempt_id"], reason="historical input gap"
        )
        with self.assertRaisesRegex(InterventionError, "replay authority"):
            resolve_intervention(
                self.contract,
                intervention["intervention_id"],
                decision="retry_authorized",
                evidence="must not promote a self-sealed history row",
            )
        resolved = resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="abort",
            evidence="operator terminates the historical unknown without replay",
        )
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["decision"], "abort")
        self.assertEqual(
            load_projection(self.contract)["attempts"][attempt["attempt_id"]]["state"],
            "unknown",
        )

    def test_two_threads_cannot_dispatch_from_the_same_retry_grant(self) -> None:
        first = self.begin("concurrent-original", fingerprint="b" * 64)
        intervention = mark_attempt_unknown(
            self.contract, first["attempt_id"], reason="lost"
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="one replacement only",
        )
        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, str]] = []
        outcomes_lock = threading.Lock()

        def dispatch(suffix: str) -> None:
            barrier.wait()
            try:
                attempt = self.begin(
                    f"concurrent-{suffix}", fingerprint="b" * 64
                )
                outcome = ("ok", attempt["attempt_id"])
            except InterventionError as error:
                outcome = ("error", str(error))
            with outcomes_lock:
                outcomes.append(outcome)

        threads = [
            threading.Thread(target=dispatch, args=(suffix,))
            for suffix in ("one", "two")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(sorted(kind for kind, _ in outcomes), ["error", "ok"])

    def test_retry_append_crash_and_torn_tail_never_reopen_the_grant(self) -> None:
        first = self.begin("crash-original", fingerprint="c" * 64)
        intervention = mark_attempt_unknown(
            self.contract, first["attempt_id"], reason="lost"
        )
        resolve_intervention(
            self.contract,
            intervention["intervention_id"],
            decision="retry_authorized",
            evidence="one replacement only",
        )
        store = event_store_path(self.contract)
        pre_retry_bytes = store.read_bytes()
        real_fsync = os.fsync
        calls = 0

        def crash_after_flush(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected crash after append flush")
            real_fsync(descriptor)

        with mock.patch("intervention.os.fsync", side_effect=crash_after_flush):
            with self.assertRaisesRegex(OSError, "injected crash"):
                self.begin("crashing-retry", fingerprint="c" * 64)
        projection = load_projection(self.contract)
        self.assertIsNotNone(
            projection["interventions"][intervention["intervention_id"]][
                "retry_consumed_by"
            ]
        )
        with self.assertRaisesRegex(InterventionError, "block|grant|debt|retry"):
            self.begin("after-crash", fingerprint="c" * 64)
        consumed_bytes = store.read_bytes()
        with self.assertRaisesRegex(InterventionError, "truncate|append-only"):
            restore_authoritative_store(self.contract, pre_retry_bytes)
        self.assertEqual(store.read_bytes(), consumed_bytes)

        with store.open("ab") as handle:
            handle.write(b'{"schema":"torn')
            handle.flush()
            os.fsync(handle.fileno())
        damaged = store.read_bytes()
        with self.assertRaisesRegex(InterventionError, "JSONL|integrity|UTF-8"):
            self.begin("after-torn-tail", fingerprint="c" * 64)
        self.assertEqual(store.read_bytes(), damaged)

    @unittest.skipUnless(sys.platform == "darwin", "macOS namespace semantics")
    def test_pending_path_uses_macos_case_and_unicode_namespace_semantics(self) -> None:
        parent = Path(self.temporary.name)
        composed = parent / "Résumé.txt"
        alias = parent / unicodedata.normalize("NFD", "RÉSUMÉ.TXT")
        self.assertFalse(composed.exists())
        self.assertFalse(alias.exists())
        self.assertEqual(
            canonical_resource_key(composed, kind="path"),
            canonical_resource_key(alias, kind="path"),
        )

    def test_pending_path_keeps_distinct_names_on_proved_case_sensitive_volume(self) -> None:
        parent = Path(self.temporary.name)
        with mock.patch(
            "intervention._pending_path_semantics",
            return_value=("case-sensitive", "unicode-exact"),
        ):
            upper = canonical_resource_key(parent / "Report.txt", kind="path")
            lower = canonical_resource_key(parent / "report.txt", kind="path")
        self.assertNotEqual(upper, lower)

    def test_pending_path_fails_closed_for_unknown_volume_unicode_semantics(self) -> None:
        parent = Path(self.temporary.name)
        with mock.patch(
            "intervention._pending_path_filesystem_type",
            return_value="mysteryfs",
        ):
            with self.assertRaisesRegex(InterventionError, "Unicode namespace"):
                canonical_resource_key(parent / "Résumé.txt", kind="path")


if __name__ == "__main__":
    unittest.main()

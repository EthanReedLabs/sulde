from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

from intent_guardian_parts.state import default_contract  # noqa: E402
import native_decision_journal  # noqa: E402
from sulde_projection import (  # noqa: E402
    LegacyCutChanged,
    adapt_legacy_projection,
    assess_cutover,
    collect_legacy_cut,
)
from sulde_projection import legacy_adapter  # noqa: E402
from sulde_config import ConfigLayer, ConfigLayerKind, resolve_config  # noqa: E402
from sulde_effects import DEFAULT_EFFECT_ROUTER  # noqa: E402
from sulde_execution import TaskBudgets, TaskEpochContext  # noqa: E402
from sulde_protocol import Provider  # noqa: E402
from sulde_state_machine import initial_state  # noqa: E402


LEGACY_GENERATION = "a" * 64
TARGET_GENERATION = "c" * 64


class SuldeProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        self.root.mkdir()
        self.contract_path = Path(self.temporary.name) / "intent.active.json"
        self.contract = default_contract(
            intent_id="legacy-intent",
            objective="migrate one quiescent workspace",
            acceptance_criteria=["projection equality"],
            workspace=self.root,
            mode="enforce",
            confirmed_by="human",
        )
        self.write_contract()

    def write_contract(self) -> None:
        self.contract_path.write_text(
            json.dumps(
                self.contract,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def empty_effect_projection(self) -> dict[str, object]:
        return {"attempts": {}, "interventions": {}}

    def test_quiescent_cut_binds_all_legacy_sources_without_writing(self) -> None:
        before = self.contract_path.stat()
        cut = collect_legacy_cut(
            self.contract_path,
            runtime_generation=LEGACY_GENERATION,
        )
        after = self.contract_path.stat()

        self.assertTrue(cut.projection.quiescent)
        self.assertEqual(len(cut.sources), 7)
        self.assertEqual(
            [source.label for source in cut.sources],
            [
                "approvals",
                "contract",
                "effects",
                "native_anchor",
                "native_decisions",
                "native_pending",
                "observations",
            ],
        )
        self.assertEqual(
            (before.st_ino, before.st_size, before.st_mtime_ns),
            (after.st_ino, after.st_size, after.st_mtime_ns),
        )
        contract_source = next(
            source for source in cut.sources if source.label == "contract"
        )
        self.assertTrue(contract_source.exists)
        self.assertGreater(contract_source.byte_count, 0)

        target = initial_state(
            workspace_id=cut.projection.workspace_id,
            task_epoch=cut.projection.task_epoch,
            runtime_generation=TARGET_GENERATION,
        )
        assessment = assess_cutover(
            cut,
            target,
            expected_cut_id=cut.cut_id,
            expected_legacy_generation=LEGACY_GENERATION,
            expected_target_generation=TARGET_GENERATION,
        )
        self.assertTrue(assessment.ready)
        self.assertRegex(assessment.binding_id, r"^[0-9a-f]{64}$")
        self.assertFalse(assessment.authority_transferred)

    def test_each_open_legacy_control_dimension_blocks_cutover(self) -> None:
        runtime = self.contract["runtime"]
        runtime["open_events"] = [{"event_id": "event-one"}]
        runtime["pending_verifications"] = [{"event_id": "event-two"}]
        runtime["active_skills"] = ["skill-one"]
        runtime["task_lanes"] = [
            {
                "task_epoch": self.contract["task_epoch"],
                "state": "paused",
            }
        ]
        runtime["integrity_breaches"] = [{"reason": "tamper"}]
        runtime["pending_proposal_digest"] = "d" * 64
        self.contract["status"] = "paused"
        self.contract["confirmation"]["required"] = True
        effect_projection = {
            "attempts": {
                "att-one": {
                    "attempt_id": "att-one",
                    "effect": "external_write",
                    "state": "unknown",
                    "replay_authoritative": True,
                }
            },
            "interventions": {
                "int-one": {
                    "intervention_id": "int-one",
                    "attempt_id": "att-one",
                    "status": "open",
                }
            },
        }

        projection = adapt_legacy_projection(
            self.contract,
            runtime_generation=LEGACY_GENERATION,
            intervention_projection=effect_projection,
            approval_summary={"open": 1, "expired": 2},
            pending_native_transactions=[{"transaction_id": "tx-one"}],
        )

        self.assertFalse(projection.quiescent)
        self.assertEqual(projection.expired_approval_requests, 2)
        expected = {
            "contract_paused",
            "open_events:1",
            "pending_verifications:1",
            "active_skills:1",
            "paused_lanes:1",
            "open_approval_requests:1",
            "pending_native_transactions:1",
            "blocking_effect_attempts:1",
            "open_interventions:1",
            "integrity_breaches:1",
            "pending_proposal",
            "confirmation_required",
        }
        self.assertEqual(set(projection.blockers), expected)

    def test_historical_read_attempt_is_not_material_cutover_debt(self) -> None:
        projection = adapt_legacy_projection(
            self.contract,
            runtime_generation=LEGACY_GENERATION,
            intervention_projection={
                "attempts": {
                    "att-read": {
                        "attempt_id": "att-read",
                        "effect": "read",
                        "state": "unknown",
                        "replay_authoritative": False,
                    }
                },
                "interventions": {},
            },
            approval_summary={"open": 0, "expired": 0},
            pending_native_transactions=[],
        )

        self.assertTrue(projection.quiescent)
        self.assertEqual(projection.blocking_effect_attempts, 0)

    def test_unsealed_legacy_prepared_is_an_audited_diagnostic_not_authority(self) -> None:
        binding = {
            "request_id": "apr-legacy-prepared",
            "kind": "proposal",
            "decision": "approve",
            "target": "historical-proposal",
            "action": "approve-proposal",
            "approval_kind": "proposal",
            "intent_id": self.contract["intent_id"],
            "intent_revision": self.contract["revision"],
            "workspace": str(self.root.resolve()),
            "provider": "codex",
            "session_id": "historical-session",
            "card_sha256": "a" * 64,
        }
        transaction_id = native_decision_journal.transaction_id(binding)
        row = {
            "schema": native_decision_journal.EVENT_SCHEMA,
            "contract_sha256": native_decision_journal._contract_digest(
                self.contract_path
            ),
            "sequence": 1,
            "at": "2026-08-01T00:00:00+00:00",
            "previous_event_id": "",
            "event": "prepared",
            "transaction_id": transaction_id,
            "binding": binding,
            "expected_seal_event_id": None,
            "details": {},
        }
        row["event_id"] = hashlib.sha256(
            native_decision_journal._canonical(row).encode("utf-8")
        ).hexdigest()
        journal = native_decision_journal.journal_path(self.contract_path)
        journal.write_text(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        before = journal.read_bytes()

        cut = collect_legacy_cut(
            self.contract_path,
            runtime_generation=LEGACY_GENERATION,
        )

        self.assertEqual(journal.read_bytes(), before)
        self.assertTrue(cut.projection.quiescent, cut.projection.blockers)
        self.assertEqual(cut.to_dict()["schema"], "sulde-legacy-control-cut-v2")
        self.assertEqual(
            cut.projection.to_dict()["schema"],
            "sulde-legacy-semantic-projection-v2",
        )
        self.assertEqual(cut.projection.pending_native_transactions, 0)
        self.assertEqual(cut.projection.historical_unsealed_native_transactions, 1)
        self.assertNotIn("pending_native_transactions:1", cut.projection.blockers)

    def test_sealed_or_unrecognized_active_transaction_still_blocks_cutover(self) -> None:
        projection = adapt_legacy_projection(
            self.contract,
            runtime_generation=LEGACY_GENERATION,
            intervention_projection=self.empty_effect_projection(),
            approval_summary={"open": 0, "expired": 0},
            pending_native_transactions=[
                {
                    "transaction_id": "ndt-sealed",
                    "status": "active",
                    "stage": "prepared",
                    "sealed": True,
                    "operation": "proposal",
                },
                {"transaction_id": "ndt-unrecognized"},
            ],
        )

        self.assertFalse(projection.quiescent)
        self.assertEqual(projection.pending_native_transactions, 2)
        self.assertEqual(projection.historical_unsealed_native_transactions, 0)
        self.assertIn("pending_native_transactions:2", projection.blockers)

    def test_changed_source_invalidates_the_optimistic_cut(self) -> None:
        frozen = legacy_adapter._fingerprint_sources(self.contract_path)
        changed = list(frozen)
        contract_index = next(
            index for index, source in enumerate(changed) if source.label == "contract"
        )
        changed[contract_index] = replace(
            changed[contract_index],
            modified_ns=changed[contract_index].modified_ns + 1,
        )
        with mock.patch.object(
            legacy_adapter,
            "_fingerprint_sources",
            side_effect=[frozen, tuple(changed)],
        ):
            with self.assertRaises(LegacyCutChanged):
                collect_legacy_cut(
                    self.contract_path,
                    runtime_generation=LEGACY_GENERATION,
                )

    def test_audit_tail_does_not_self_invalidate_material_cut(self) -> None:
        observations = self.contract_path.with_name("intent.active.events.jsonl")
        observations.write_text('{"sequence":1}\n', encoding="utf-8")
        first = collect_legacy_cut(
            self.contract_path,
            runtime_generation=LEGACY_GENERATION,
        )
        with observations.open("a", encoding="utf-8") as handle:
            handle.write('{"sequence":2}\n')
        second = collect_legacy_cut(
            self.contract_path,
            runtime_generation=LEGACY_GENERATION,
        )

        self.assertEqual(first.cut_id, second.cut_id)
        self.assertNotEqual(first.sources, second.sources)

        self.contract["constraints"]["preserve"] = ["material boundary"]
        self.write_contract()
        changed = collect_legacy_cut(
            self.contract_path,
            runtime_generation=LEGACY_GENERATION,
        )
        self.assertNotEqual(second.cut_id, changed.cut_id)

    def test_cutover_rejects_stale_cut_or_nonempty_target(self) -> None:
        cut = collect_legacy_cut(
            self.contract_path,
            runtime_generation=LEGACY_GENERATION,
        )
        target = initial_state(
            workspace_id=cut.projection.workspace_id,
            task_epoch=cut.projection.task_epoch,
            runtime_generation=TARGET_GENERATION,
        )
        nonempty = replace(target, sequence=1, last_event_id="f" * 64)

        assessment = assess_cutover(
            cut,
            nonempty,
            expected_cut_id="0" * 64,
            expected_legacy_generation=LEGACY_GENERATION,
            expected_target_generation=TARGET_GENERATION,
        )

        self.assertFalse(assessment.ready)
        self.assertEqual(assessment.binding_id, "")
        self.assertIn("legacy_cut_changed", assessment.blockers)
        self.assertIn("target_supervisor_not_empty", assessment.blockers)

    def test_cutover_binds_the_exact_frozen_task_context(self) -> None:
        cut = collect_legacy_cut(
            self.contract_path,
            runtime_generation=LEGACY_GENERATION,
        )
        config = resolve_config(
            (
                ConfigLayer.build(
                    name="task",
                    kind=ConfigLayerKind.TASK,
                    values={"limits.events": 100},
                ),
            )
        )
        context = TaskEpochContext.build(
            workspace_id=cut.projection.workspace_id,
            intent_id=cut.projection.intent_id,
            intent_revision=cut.projection.intent_revision,
            task_epoch=cut.projection.task_epoch,
            provider=Provider.CODEX,
            native_session_id="session-one",
            task_definition_sha256="1" * 64,
            owned_paths=("scripts/kb", "tests"),
            policy_sha256=cut.projection.contract_material_digest,
            config_snapshot=config,
            effect_router=DEFAULT_EFFECT_ROUTER,
            tool_registry_sha256="2" * 64,
            runtime_generation=TARGET_GENERATION,
            legacy_cut_id=cut.cut_id,
            budgets=TaskBudgets(100, 8000, 20, 3600),
        )
        target = initial_state(
            workspace_id=cut.projection.workspace_id,
            task_epoch=cut.projection.task_epoch,
            runtime_generation=TARGET_GENERATION,
            task_epoch_context_id=context.context_id,
        )

        assessment = assess_cutover(
            cut,
            target,
            expected_cut_id=cut.cut_id,
            expected_legacy_generation=LEGACY_GENERATION,
            expected_target_generation=TARGET_GENERATION,
            task_context=context,
        )
        self.assertTrue(assessment.ready, assessment.blockers)

        without_context = assess_cutover(
            cut,
            target,
            expected_cut_id=cut.cut_id,
            expected_legacy_generation=LEGACY_GENERATION,
            expected_target_generation=TARGET_GENERATION,
        )
        self.assertEqual(without_context.blockers, ("task_context_missing",))


if __name__ == "__main__":
    unittest.main()

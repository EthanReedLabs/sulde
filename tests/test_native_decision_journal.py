from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from typing import get_type_hints
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

from approval_invariant import (  # noqa: E402
    ask_approval,
    decide_approval,
    event_store_path,
    load_projection as load_approval_projection,
    request_binding_receipt,
)
import native_decision_journal as journal_module  # noqa: E402
from native_decision_journal import (  # noqa: E402
    APPROVAL_CAS_EVENT_SCHEMA,
    APPROVAL_CAS_RECEIPT_SCHEMA,
    AUTHORITY_ADVANCEMENT_RESULT_SCHEMA,
    AuthorityAdvancementResult,
    InternalRecoveryStep,
    JournalHeadProof,
    NativeAuthorityReaders,
    NativeContractReceipt,
    NativeDecisionAdvancementInterrupted,
    NativeDecisionJournalError,
    NativeEffectReceipt,
    NativeExternalHeadReceipt,
    advance,
    advance_with_authority,
    approval_authority_store_path,
    contract_receipt_store_path,
    effect_authority_store_path,
    effect_receipt_store_path,
    external_head_receipt_store_path,
    head_anchor_path,
    head_pending_path,
    head_proof,
    internal_recovery_result,
    journal_path,
    grant_broker_projection,
    load_projection,
    load_projection_read_only,
    pending,
    pending_grant_broker_transactions,
    prepare,
    produce_contract_receipt,
    produce_effect_receipt,
    produce_external_head_receipt,
    replay,
    recover_effect,
    recover_intent,
    recover_observation_export,
    recover_proposal,
    recover_resume,
    recovery_plan,
    seal_binding as _seal_binding,
    supersede,
    transaction_id,
    verify_contract_receipt,
    verify_effect_receipt,
    verify_external_head_receipt,
    verify_recorded_external_head_receipt,
)


TASK_EPOCH = "e" * 24


def seal_binding(*args, **kwargs):
    """Keep focused fixtures explicit about the frozen v5 identities."""
    kwargs.setdefault("task_epoch", TASK_EPOCH)
    if type(kwargs.get("operation")) is str and kwargs["operation"] == "effect":
        target = str(kwargs.get("target") or "")
        kwargs.setdefault(
            "effect_attempt_id",
            "att-" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:24],
        )
        kwargs.setdefault(
            "effect_subject_intent_revision",
            int(kwargs.get("intent_revision") or 0),
        )
    else:
        kwargs.setdefault("effect_attempt_id", "")
        kwargs.setdefault("effect_subject_intent_revision", 0)
    return _seal_binding(*args, **kwargs)


OPERATIONS = {
    "proposal": ("proposal", "approve", "approve-proposal", recover_proposal),
    "resume": ("intent-confirmation", "resume", "resume", recover_resume),
    "effect": (
        "effect-intervention",
        "retry_authorized",
        "intervention-resolve",
        recover_effect,
    ),
    "intent": ("intent-confirmation", "confirm", "confirm-intent", recover_intent),
    "observation-export": (
        "observation-export",
        "approve",
        "approve-observation-export",
        recover_observation_export,
    ),
}


def golden_canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def golden_t11_identity(kind: str, document: object) -> str:
    envelope = {
        "document": document,
        "kind": kind,
        "schema": "sulde-approval-cas-identity-v1",
    }
    return "sha256:" + hashlib.sha256(
        golden_canonical(envelope).encode("utf-8")
    ).hexdigest()


def repair2_identity(namespace: str, document: object) -> str:
    material = f"{namespace}\0{golden_canonical(document)}"
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class MagicValue:
    def __init__(self) -> None:
        self.calls = 0

    def _called(self) -> None:
        self.calls += 1
        raise AssertionError("magic method executed")

    def __str__(self) -> str:
        self._called()

    def __int__(self) -> int:
        self._called()

    def __bool__(self) -> bool:
        self._called()

    def __fspath__(self) -> str:
        self._called()

    def __iter__(self):
        self._called()

    def __eq__(self, _other: object) -> bool:
        self._called()

    def __hash__(self) -> int:
        self._called()

    def __repr__(self) -> str:
        self._called()


class NativeDecisionJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        )
        self.root = Path(self.temporary.name) / "workspace"
        self.root.mkdir()
        self.contract = Path(self.temporary.name) / "intent.json"
        self.contract.write_text("{}\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_read_only_projection_never_creates_a_lock_or_repairs_pending_state(self) -> None:
        transaction = self.transaction("proposal", suffix="read-only")
        store = journal_path(self.contract)
        anchor = head_anchor_path(self.contract)
        lock = store.with_name(f".{store.name}.lock")
        before = {
            "store": (store.read_bytes(), store.stat().st_mtime_ns),
            "anchor": (anchor.read_bytes(), anchor.stat().st_mtime_ns),
            "lock_exists": lock.exists(),
        }

        projection = load_projection_read_only(self.contract)

        self.assertIn(transaction["transaction_id"], projection["transactions"])
        self.assertEqual(
            before,
            {
                "store": (store.read_bytes(), store.stat().st_mtime_ns),
                "anchor": (anchor.read_bytes(), anchor.stat().st_mtime_ns),
                "lock_exists": lock.exists(),
            },
        )
        pending_sidecar = head_pending_path(self.contract)
        pending_sidecar.write_text("{}\n", encoding="utf-8")
        pending_before = pending_sidecar.read_bytes()
        with self.assertRaisesRegex(NativeDecisionJournalError, "requiring recovery"):
            load_projection_read_only(self.contract)
        self.assertEqual(pending_sidecar.read_bytes(), pending_before)

    def test_grant_broker_adapter_is_versioned_and_never_reinterprets_legacy_rows(
        self,
    ) -> None:
        legacy_before = load_projection_read_only(self.contract)
        legacy_store_exists = journal_path(self.contract).exists()

        adapted = grant_broker_projection(self.contract)

        self.assertEqual(adapted["schema"], "sulde-native-grant-broker-adapter-v1")
        self.assertEqual(adapted["protocol"], "sulde-grant-broker-v1")
        self.assertFalse(adapted["legacy_journal_reinterpreted"])
        self.assertEqual(adapted["projection"]["transactions"], {})
        self.assertEqual(pending_grant_broker_transactions(self.contract), [])
        self.assertEqual(load_projection_read_only(self.contract), legacy_before)
        self.assertEqual(journal_path(self.contract).exists(), legacy_store_exists)
        self.assertFalse(
            self.contract.with_name(".intent.grant-broker.jsonl").exists()
        )

    def choice_card(
        self,
        operation: str,
        decision: str,
        action: str,
        target: str,
    ) -> dict:
        return {
            "operation_id": operation,
            "decision_id": decision,
            "action": action,
            "本次选择": action,
            "目标": target,
        }

    def transaction(
        self,
        operation: str,
        *,
        suffix: str = "one",
        effect_subject_intent_revision: int | None = None,
    ) -> dict:
        approval_kind, decision, action, _recover = OPERATIONS[operation]
        target = f"{operation}-target-{suffix}"
        session_id = f"native-{operation}-{suffix}"
        card = self.choice_card(operation, decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.root,
            route="human",
        )
        receipt = request_binding_receipt(self.contract, asked["request_id"])
        subject_arguments = (
            {"effect_subject_intent_revision": effect_subject_intent_revision}
            if effect_subject_intent_revision is not None
            else {}
        )
        binding = seal_binding(
            self.contract,
            operation=operation,
            decision=decision,
            target=target,
            action=action,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            workspace=self.root,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            request_id=asked["request_id"],
            receipt=receipt,
            **subject_arguments,
        )
        transaction = prepare(self.contract, binding)
        decide_approval(
            self.contract,
            kind=approval_kind,
            target=target,
            outcome="approved",
            provider="codex",
            session_id=session_id,
            actor="permission-request:codex",
            card=card,
            workspace=self.root,
            route="human",
            source="codex_permission_request",
        )
        return transaction

    def steps(
        self,
        transaction: dict,
        operation: str,
        suffix: str,
        counts: dict[str, int],
    ) -> tuple[InternalRecoveryStep, InternalRecoveryStep]:
        plan = recovery_plan(
            self.contract,
            transaction["transaction_id"],
            operation=operation,
        )

        def make(label: str, stage: str) -> InternalRecoveryStep:
            marker = Path(self.temporary.name) / f"{suffix}-{label}.json"
            if not marker.is_file():
                counts[label] = counts.get(label, 0) + 1
                marker.write_text(
                    json.dumps({"projection": label, "suffix": suffix}) + "\n",
                    encoding="utf-8",
                )
            observed = json.loads(marker.read_text(encoding="utf-8"))
            return internal_recovery_result(
                plan,
                stage=stage,
                adapter=f"t06:test-{label}",
                adapter_contract_sha256="a" * 64,
                observation={"marker_exists": True},
                result=observed,
            )

        return make("effect", "effect_applied"), make(
            "contract", "contract_applied"
        )

    def inert_step(self) -> InternalRecoveryStep:
        return InternalRecoveryStep(
            schema="invalid",
            plan={},
            stage="invalid",
            adapter="t06:invalid",
            adapter_contract_sha256="0" * 64,
            observation={},
            result={},
            proof_sha256="0" * 64,
        )

    def legacy_binding(self, *, suffix: str = "fixture") -> dict:
        return {
            "request_id": f"apr-legacy-{suffix}",
            "kind": "resume",
            "decision": "resume",
            "target": f"legacy-pause-{suffix}",
            "action": "resume",
            "approval_kind": "intent-confirmation",
            "intent_id": f"legacy-intent-{suffix}",
            "intent_revision": 1,
            "workspace": str(self.root),
            "provider": "codex",
            "session_id": f"legacy-session-{suffix}",
            "card_sha256": "z" * 64,
        }

    def seed_historical_legacy_prepared(
        self,
        *,
        suffix: str = "fixture",
        stage: str = "prepared",
        terminal: bool = False,
    ) -> dict:
        """Persist the exact pre-seal, pre-anchor event shape as a fixture."""
        if terminal:
            stage = "committed"
        if stage not in journal_module.STAGES:
            raise ValueError(f"unsupported historical fixture stage: {stage}")
        binding = self.legacy_binding(suffix=suffix)
        tx_id = transaction_id(binding)
        rows: list[dict] = []

        def append(spec: dict) -> None:
            row = {
                "schema": journal_module.EVENT_SCHEMA,
                "contract_sha256": journal_module._contract_digest(self.contract),
                "sequence": len(rows) + 1,
                "at": f"2025-01-01T00:00:0{len(rows)}+00:00",
                "previous_event_id": rows[-1]["event_id"] if rows else "",
                **spec,
            }
            row["event_id"] = hashlib.sha256(
                journal_module._canonical(row).encode("utf-8")
            ).hexdigest()
            rows.append(row)

        append(
            {
                "event": "prepared",
                "transaction_id": tx_id,
                "binding": binding,
                "details": {"historical_fixture": True},
            }
        )
        if stage != "prepared":
            prior = "prepared"
            for next_stage in (
                "approval_decided",
                "effect_applied",
                "contract_applied",
                "committed",
            ):
                append(
                    {
                        "event": "advanced",
                        "transaction_id": tx_id,
                        "expected_stage": prior,
                        "stage": next_stage,
                        "details": {"historical_fixture": True},
                    }
                )
                prior = next_stage
                if next_stage == stage:
                    break
        journal_path(self.contract).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        return dict(load_projection(self.contract)["transactions"][tx_id])

    def journal_snapshot(self) -> dict:
        store = journal_path(self.contract)
        anchor = head_anchor_path(self.contract)
        pending_anchor = journal_module._head_pending_path(self.contract)
        payload = store.read_bytes() if store.is_file() else b""
        return {
            "journal_bytes": payload,
            "event_count": len(payload.splitlines()),
            "head_proof": head_proof(self.contract),
            "pending": pending(self.contract),
            "anchor": anchor.read_bytes() if anchor.is_file() else None,
            "pending_anchor": (
                pending_anchor.read_bytes() if pending_anchor.is_file() else None
            ),
        }

    def authority_readers(self) -> NativeAuthorityReaders:
        return NativeAuthorityReaders(
            approval=Path(self.temporary.name) / "approval-authority.json",
            effect=Path(self.temporary.name) / "effect-authority.json",
            contract=Path(self.temporary.name) / "contract-authority.json",
            head_anchor=Path(self.temporary.name) / "head-authority.json",
        )

    def append_t12_source_row(
        self,
        readers: NativeAuthorityReaders,
        transaction: dict,
        stage: str,
        **changes: object,
    ) -> dict:
        if stage != "approval_decided":
            raise ValueError("the accepted T12 producer fixture only decides approval")

        binding = transaction["binding"]
        proof = head_proof(self.contract)
        snapshot = {
            "card_sha256": binding["card_sha256"],
            "provider": binding["provider"],
            "session_id": binding["session_id"],
            "lane_sha256": journal_module._lane_digest(
                binding["provider"], binding["session_id"]
            ),
            "target_sha256": hashlib.sha256(
                binding["target"].encode("utf-8")
            ).hexdigest(),
            "revision": binding["intent_revision"],
            "journal_sha256": proof["journal_sha256"],
            "effect_sha256": hashlib.sha256(
                binding["action"].encode("utf-8")
            ).hexdigest(),
            "world_state_sha256": journal_module._authority_world_sha256(
                self.contract, transaction, binding
            ),
        }
        snapshot.update(changes.pop("snapshot", {}))
        snapshot_identity = golden_t11_identity("approval-snapshot", snapshot)
        request_id = changes.pop(
            "typed_request_id",
            "apr-" + hashlib.sha256(
                (binding["request_id"] + ":typed-reauthorization").encode("utf-8")
            ).hexdigest()[:24],
        )
        request_identity = golden_t11_identity(
            "approval-request",
            {
                "request_id": request_id,
                "snapshot": snapshot,
            },
        )
        receipt = {
            "schema": APPROVAL_CAS_RECEIPT_SCHEMA,
            "request_id": request_id,
            "receipt_id": "receipt-" + hashlib.sha256(
                request_id.encode("utf-8")
            ).hexdigest()[:24],
            "outcome": "allow",
            "snapshot": snapshot,
            "snapshot_identity": snapshot_identity,
            "request_identity": request_identity,
            "decision_identity": "",
            "replacement_identity": None,
            "execution_authorized": False,
        }
        receipt.update(changes.pop("receipt", {}))
        receipt["decision_identity"] = golden_t11_identity(
            "approval-decision",
            {
                "request_id": receipt["request_id"],
                "receipt_id": receipt["receipt_id"],
                "outcome": receipt["outcome"],
                "snapshot": receipt["snapshot"],
            },
        )
        receipt.update(changes.pop("identity", {}))
        destination = approval_authority_store_path(self.contract)
        rows = [
            json.loads(line)
            for line in destination.read_text(encoding="utf-8").splitlines()
        ]
        envelope = {
            "schema": APPROVAL_CAS_EVENT_SCHEMA,
            "contract_sha256": journal_module._contract_digest(self.contract),
            "typed": True,
            "request_id": request_id,
        }
        typed_rows = [
            {
                **envelope,
                "sequence": len(rows) + 1,
                "at": "2026-08-20T00:00:00+00:00",
                "type": "approval.asked",
                "card_sha256": snapshot["card_sha256"],
                "expires_at": "2026-08-20T00:10:00+00:00",
                "intent_id_sha256": hashlib.sha256(
                    binding["intent_id"].encode("utf-8")
                ).hexdigest(),
                "intent_revision": binding["intent_revision"],
                "kind": OPERATIONS[binding["operation"]][0],
                "lane_sha256": snapshot["lane_sha256"],
                "proposal_sha256": (
                    snapshot["target_sha256"]
                    if binding["operation"] == "proposal"
                    else ""
                ),
                "provider": binding["provider"],
                "reassess_at": "",
                "replaced_request_id": "",
                "replacement_identity": "",
                "snapshot": snapshot,
                "snapshot_identity": snapshot_identity,
                "request_identity": request_identity,
                "route": "human",
                "decision_owner": "human",
                "prompt_shown": False,
                "source": binding["source"],
                "target_sha256": snapshot["target_sha256"],
                "workspace_sha256": journal_module._workspace_digest(
                    binding["workspace"]
                ),
            },
            {
                **envelope,
                "sequence": len(rows) + 2,
                "at": "2026-08-20T00:00:01+00:00",
                "type": "approval.prompt-observed",
                "provider": binding["provider"],
                "lane_sha256": snapshot["lane_sha256"],
                "snapshot_identity": snapshot_identity,
                "prompt_shown": True,
                "decision_owner": "human",
            },
            {
                **envelope,
                "sequence": len(rows) + 3,
                "at": "2026-08-20T00:00:02+00:00",
                "type": "approval.decided",
                "provider": binding["provider"],
                "lane_sha256": snapshot["lane_sha256"],
                "outcome": "allow",
                "actor": "permission-request:human",
                "decision_owner": "human",
                "typed_receipt": receipt,
                "receipt_sha256": hashlib.sha256(
                    receipt["receipt_id"].encode("utf-8")
                ).hexdigest(),
            },
        ]
        typed_rows[0].update(changes.pop("asked", {}))
        typed_rows[1].update(changes.pop("prompt", {}))
        typed_rows[-1].update(changes.pop("row", {}))
        if changes:
            raise ValueError(f"unsupported accepted T12 fixture changes: {changes}")
        with destination.open("a", encoding="utf-8") as handle:
            for row in typed_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return receipt

    def advance_from_t12_fixture(
        self,
        readers: NativeAuthorityReaders,
        transaction: dict,
        stage: str,
        **changes: object,
    ) -> AuthorityAdvancementResult:
        self.append_t12_source_row(readers, transaction, stage, **changes)
        return advance_with_authority(
            self.contract,
            transaction["transaction_id"],
            readers=readers,
        )

    def write_t10_dispatch(self, transaction: dict, **changes: object) -> Path:
        current = load_projection(self.contract)["transactions"][
            transaction["transaction_id"]
        ]
        binding = current["binding"]
        approval = current["stage_details"]["approval_decided"]
        seal = load_projection(self.contract)["seals"][binding["seal_id"]]
        resources = [f"opaque:{binding['target']}"]
        arguments_digest = hashlib.sha256(
            json.dumps(
                seal["card"],
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        prepared = {
            "schema": journal_module.T10_BATCH_EVENT_SCHEMA,
            "contract_sha256": journal_module._contract_digest(self.contract),
            "sequence": 1,
            "at": "2026-08-20T00:00:01+00:00",
            "type": "effect.batch_prepared",
            "batch_id": "batch-" + "a" * 24,
            "call_id": "call-" + "b" * 24,
            "idempotency_key": "idempotency:test-t13",
            "intent_id": binding["intent_id"],
            "intent_revision": binding["intent_revision"],
            "fingerprint": hashlib.sha256(
                "\0".join(
                    (
                        binding["provider"],
                        binding["action"],
                        resources[0],
                        "external_write",
                        arguments_digest,
                    )
                ).encode("utf-8")
            ).hexdigest(),
            "source_event_id": approval["source_event_id"],
            "capability": binding["action"],
            "effect": "external_write",
            "provider": binding["provider"],
            "session_id": binding["session_id"],
            "task_id": transaction["transaction_id"],
            "operation_arguments_digest": arguments_digest,
            "resources": resources,
            "resource_set_sha256": hashlib.sha256(
                golden_canonical(resources).encode("utf-8")
            ).hexdigest(),
            "batch_semantics_sha256": "",
        }
        semantics = {
            key: prepared[key]
            for key in (
                "batch_id",
                "call_id",
                "idempotency_key",
                "intent_id",
                "intent_revision",
                "fingerprint",
                "source_event_id",
                "capability",
                "effect",
                "provider",
                "session_id",
                "task_id",
                "operation_arguments_digest",
                "resources",
            )
        }
        prepared["batch_semantics_sha256"] = hashlib.sha256(
            golden_canonical(semantics).encode("utf-8")
        ).hexdigest()
        prepared.update(changes.pop("prepared", {}))
        prepared["event_id"] = journal_module._source_event_digest(prepared)
        dispatched = {
            "schema": journal_module.T10_BATCH_EVENT_SCHEMA,
            "contract_sha256": journal_module._contract_digest(self.contract),
            "sequence": 2,
            "at": "2026-08-20T00:00:02+00:00",
            "type": "effect.batch_dispatched",
            "batch_id": prepared["batch_id"],
            "call_id": prepared["call_id"],
            "idempotency_key": prepared["idempotency_key"],
            "prepared_event_id": prepared["event_id"],
            "resource_set_sha256": prepared["resource_set_sha256"],
            "batch_semantics_sha256": prepared["batch_semantics_sha256"],
        }
        dispatched.update(changes.pop("dispatched", {}))
        if changes:
            raise ValueError(f"unsupported accepted T10 fixture changes: {changes}")
        dispatched["event_id"] = journal_module._source_event_digest(dispatched)
        destination = effect_authority_store_path(self.contract)
        destination.write_text(
            "".join(
                json.dumps(row, sort_keys=True) + "\n"
                for row in (prepared, dispatched)
            ),
            encoding="utf-8",
        )
        return destination

    def write_formal_native_postcondition(
        self,
        transaction: dict,
        *,
        effect_attempt_id: str = "",
        effect_subject_intent_revision: int | None = None,
    ) -> None:
        binding = transaction["binding"]
        receipt_id = hashlib.sha256(
            (binding["request_id"] + ":contract-receipt").encode("utf-8")
        ).hexdigest()
        receipt = {
            "schema": "sulde-decision-receipt-v2",
            "receipt_id": receipt_id,
            "action": binding["action"],
            "target": binding["target"],
            "intent_id": binding["intent_id"],
            "intent_revision": binding["intent_revision"],
            "workspace_root": binding["workspace"],
            "provider": binding["provider"],
            "session_id": binding["session_id"],
            "channel": "codex-native-permission",
            "observation_source": "live_host_hook",
            "actor": "permission-request:codex",
            "decision": (
                binding["decision"] if binding["operation"] == "effect" else ""
            ),
            "evidence_sha256": "e" * 64,
            "approval_request_id": binding["request_id"],
            "recorded_at": "2026-08-20T00:00:03+00:00",
            "consumed_at": "2026-08-20T00:00:04+00:00",
            "consumed_by": "native-permission-control-executor",
        }
        runtime = {
            "approval_receipts": [receipt],
            "proposal_decisions": [],
            "pending_proposal_digest": "",
            "task_lanes": [],
        }
        document = {
            "schema": "sulde-intent-contract-v1",
            "intent_id": binding["intent_id"],
            "revision": binding["intent_revision"],
            "task_epoch": "epoch-" + binding["request_id"],
            "status": "active",
            "workspace_root": binding["workspace"],
            "runtime": runtime,
        }
        if binding["operation"] == "proposal":
            verdict = "approve" if binding["decision"] == "approve" else "reject"
            runtime["proposal_decisions"] = [{
                "schema": "sulde-intent-proposal-decision-v1",
                "decision_id": hashlib.sha256(
                    (binding["target"] + verdict).encode("utf-8")
                ).hexdigest(),
                "proposal_digest": binding["target"],
                "authority": "human",
                "verdict": verdict,
                "provider": binding["provider"],
                "session_id": binding["session_id"],
                "receipt_id": receipt_id,
            }]
            if verdict == "approve":
                document["applied_proposal_digest"] = binding["target"]
                document["revision"] += 1
        elif binding["operation"] == "resume":
            runtime["task_lanes"] = [{
                "provider": binding["provider"],
                "session_id": binding["session_id"],
                "state": "bound",
            }]
            document["resumed_lane"] = {
                "provider": binding["provider"],
                "session_id": binding["session_id"],
                "task_epoch": document["task_epoch"],
            }
        elif binding["operation"] == "effect":
            row = {
                "schema": journal_module.T10_BATCH_EVENT_SCHEMA,
                "contract_sha256": journal_module._contract_digest(self.contract),
                "sequence": 1,
                "at": "2026-08-20T00:00:03+00:00",
                "type": "intent.intervention_resolved",
                "intervention_id": binding["target"],
                "attempt_id": (
                    effect_attempt_id
                    or binding.get("effect_attempt_id")
                    or "att-"
                    + hashlib.sha256(binding["target"].encode("utf-8")).hexdigest()[:24]
                ),
                "intent_id": binding["intent_id"],
                "intent_revision": (
                    effect_subject_intent_revision
                    if effect_subject_intent_revision is not None
                    else binding.get(
                        "effect_subject_intent_revision",
                        binding["intent_revision"],
                    )
                ),
                "provider": binding["provider"],
                "session_id": binding["session_id"],
                "task_id": transaction["transaction_id"],
                "capability": binding["action"],
                "effect": "external_write",
                "target_sha256": hashlib.sha256(
                    binding["target"].encode("utf-8")
                ).hexdigest(),
                "decision": binding["decision"],
                "evidence": "independently replayed intervention resolution",
                "actor": "permission-request:codex",
                "takeover_provider": (
                    binding["provider"] if binding["decision"] != "abort" else ""
                ),
                "takeover_session_id": (
                    binding["session_id"] if binding["decision"] != "abort" else ""
                ),
            }
            row["event_id"] = journal_module._source_event_digest(row)
            effect_authority_store_path(self.contract).write_text(
                json.dumps(row, sort_keys=True) + "\n", encoding="utf-8"
            )
        self.contract.write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def advance_all_authority_stages(self, transaction: dict) -> list[dict]:
        readers = self.authority_readers()
        approval_store = approval_authority_store_path(self.contract)
        approval_prefix = approval_store.read_bytes()
        self.advance_from_t12_fixture(readers, transaction, "approval_decided")
        approval_store.write_bytes(approval_prefix)
        self.write_formal_native_postcondition(transaction)
        results = []
        produce_effect_receipt(self.contract, transaction["transaction_id"])
        results.append(advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        ))
        produce_contract_receipt(self.contract, transaction["transaction_id"])
        results.append(advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        ))
        produce_external_head_receipt(self.contract, transaction["transaction_id"])
        results.append(advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        ))
        self.contract.write_text("{}\n", encoding="utf-8")
        return results

    def test_all_five_operations_produce_plans_without_advancing(self) -> None:
        for index, (operation, values) in enumerate(OPERATIONS.items(), 1):
            with self.subTest(operation=operation):
                transaction = self.transaction(operation, suffix=str(index))
                recover = values[3]
                plan = recover(self.contract, transaction["transaction_id"])
                repeated = recover(self.contract, transaction["transaction_id"])
                self.assertEqual(plan, repeated)
                self.assertEqual(plan["operation"], operation)
                self.assertEqual(plan["authority_status"], "authority_unverified")
                self.assertEqual(plan["journal_state"], "pending")
                self.assertTrue(plan["local_consistency_verified"])
                self.assertFalse(plan["external_authority_verified"])
                self.assertEqual(
                    plan["external_authority_status"],
                    "external_authority_unverified",
                )
                self.assertEqual(
                    plan["journal_head_proof"]["proof_sha256"],
                    plan["journal_head_proof_sha256"],
                )
                self.assertEqual(
                    plan["required_postconditions"]["effect"]["journal_verifier"],
                    "verify_effect_receipt",
                )
                self.assertEqual(
                    plan["required_postconditions"]["contract"]["journal_verifier"],
                    "verify_contract_receipt",
                )
                current = load_projection(self.contract)["transactions"][
                    transaction["transaction_id"]
                ]
                self.assertEqual(current["stage"], "prepared")
                self.assertEqual(current["status"], "active")

        native = [
            row
            for row in load_approval_projection(self.contract)["requests"].values()
            if row["source"] == "codex_permission_request"
        ]
        self.assertEqual(len(native), len(OPERATIONS))
        self.assertTrue(all(row["status"] == "decided" for row in native))
        if os.name != "nt":
            self.assertEqual(journal_path(self.contract).stat().st_mode & 0o777, 0o600)

    def test_caller_claims_and_failure_tokens_never_advance_pending_state(self) -> None:
        transaction = self.transaction("intent", suffix="authority-claims")
        plan = recovery_plan(
            self.contract,
            transaction["transaction_id"],
            operation="intent",
        )
        claims = [
            internal_recovery_result(
                plan,
                stage="effect_applied",
                adapter="t06:forged",
                adapter_contract_sha256="0" * 64,
                observation={},
                result={},
            ),
            internal_recovery_result(
                plan,
                stage="effect_applied",
                adapter="t06:self-asserted-success",
                adapter_contract_sha256="a" * 64,
                observation={"success": True},
                result={"success": True, "receipt": "forged"},
            ),
        ]
        for claim in claims:
            with self.subTest(adapter=claim.adapter):
                self.assertEqual(claim.authority_status, "authority_unverified")
                with self.assertRaisesRegex(
                    NativeDecisionJournalError, "authority_unverified"
                ):
                    recover_intent(
                        self.contract,
                        transaction["transaction_id"],
                        effect=claim,
                        contract=claim,
                    )
                current = load_projection(self.contract)["transactions"][
                    transaction["transaction_id"]
                ]
                self.assertEqual(current["stage"], "prepared")
                self.assertEqual(current["status"], "active")

        with self.assertRaisesRegex(
            NativeDecisionJournalError, "authority_unverified"
        ):
            recover_intent(
                self.contract,
                transaction["transaction_id"],
                effect="t06:forged",  # type: ignore[arg-type]
                contract=object(),  # type: ignore[arg-type]
                failpoint="contract_applied->committed:before_cas",
            )
        self.assertEqual(
            load_projection(self.contract)["transactions"][
                transaction["transaction_id"]
            ]["stage"],
            "prepared",
        )

    def test_incomplete_tail_and_hash_tamper_fail_closed(self) -> None:
        transaction = self.transaction("resume", suffix="tail")
        store = journal_path(self.contract)
        accepted = store.read_bytes()
        store.write_bytes(accepted + b'{"broken"')
        with self.assertRaisesRegex(NativeDecisionJournalError, "incomplete tail"):
            load_projection(self.contract)

        store.write_bytes(accepted)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[0]["binding"]["target"] = "substituted-target"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(NativeDecisionJournalError, "digest mismatch"):
            load_projection(self.contract)
        self.assertTrue(transaction["sealed"])

    def test_committed_recovery_rechecks_sealed_decision_receipt(self) -> None:
        transaction = self.transaction("intent", suffix="decision-receipt")
        # Seed a historical v2 terminal row directly.  The public T03 seam
        # cannot create this state after F03-008, but replay must still verify
        # receipts produced by the earlier verification epoch.
        binding = transaction["binding"]
        decision_receipt = journal_module._verify_sealed_approval(
            self.contract, binding
        )
        authority_sha256 = journal_module._authority_sha256(
            binding, decision_receipt
        )
        journal_module._advance_event(
            self.contract,
            transaction["transaction_id"],
            stage="approval_decided",
            details={
                "decision_sha256": decision_receipt["decision_sha256"],
                "authority_sha256": authority_sha256,
            },
            allow_sealed=True,
        )
        for stage in ("effect_applied", "contract_applied", "committed"):
            journal_module._advance_event(
                self.contract,
                transaction["transaction_id"],
                stage=stage,
                details={
                    "decision_sha256": decision_receipt["decision_sha256"],
                    "authority_sha256": authority_sha256,
                    "historical_fixture": True,
                },
                allow_sealed=True,
            )

        terminal = recover_intent(
            self.contract,
            transaction["transaction_id"],
        )
        self.assertTrue(terminal["historical_terminal_seen"])
        self.assertEqual(terminal["historical_stage"], "committed")
        self.assertEqual(terminal["historical_status"], "committed")
        self.assertTrue(terminal["local_consistency_verified"])
        self.assertFalse(terminal["external_authority_verified"])
        self.assertEqual(terminal["journal_state"], "pending")
        self.assertNotEqual(terminal.get("status"), "committed")

        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[-1]["at"] = "2099-01-01T00:00:00+00:00"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            NativeDecisionJournalError, "decision receipt was substituted"
        ):
            recover_intent(
                self.contract,
                transaction["transaction_id"],
            )

    def test_old_request_receipt_cannot_substitute_for_new_request(self) -> None:
        first = self.transaction("effect", suffix="old")
        first_binding = first["binding"]
        old_receipt = request_binding_receipt(
            self.contract, first_binding["request_id"]
        )

        approval_kind, decision, action, _recover = OPERATIONS["effect"]
        target = "effect-target-new"
        card = self.choice_card("effect", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id="native-effect-new",
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        with self.assertRaisesRegex(
            NativeDecisionJournalError, "binding mismatch"
        ):
            seal_binding(
                self.contract,
                operation="effect",
                decision=decision,
                target=target,
                action=action,
                intent_id="l3:test-native-journal",
                intent_revision=7,
                workspace=self.root,
                provider="codex",
                session_id="native-effect-new",
                source="codex_permission_request",
                card=card,
                request_id=asked["request_id"],
                receipt=old_receipt,
            )

    def test_seal_rejects_every_semantic_binding_substitution(self) -> None:
        transaction = self.transaction("intent", suffix="binding")
        binding = transaction["binding"]
        card = self.choice_card(
            "intent", binding["decision"], binding["action"], binding["target"]
        )
        receipt = request_binding_receipt(self.contract, binding["request_id"])
        base = {
            "operation": "intent",
            "decision": binding["decision"],
            "target": binding["target"],
            "action": binding["action"],
            "intent_id": binding["intent_id"],
            "intent_revision": binding["intent_revision"],
            "workspace": self.root,
            "provider": "codex",
            "session_id": binding["session_id"],
            "source": binding["source"],
            "card": card,
            "request_id": binding["request_id"],
            "receipt": receipt,
        }
        substitutions = {
            "request_id": "apr-ffffffffffffffffffffffff",
            "target": "other-target",
            "intent_id": "other-intent",
            "intent_revision": 8,
            "workspace": self.root / "other",
            "session_id": "other-session",
            "source": "session_start_restore",
            "card": {"本次选择": "confirm-intent", "目标": "other-target"},
            "decision": "reject",
        }
        for field, value in substitutions.items():
            with self.subTest(field=field):
                changed = dict(base, **{field: value})
                with self.assertRaises(NativeDecisionJournalError):
                    seal_binding(self.contract, **changed)

    def test_effect_choice_requires_one_exact_machine_semantic(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["effect"]
        bad_cards = {
            "missing": {
                "action": action,
                "本次选择": action,
                "目标": "effect-choice-missing",
            },
            "multi": {
                "operation_id": "effect",
                "decision_id": [decision, "abort"],
                "action": action,
                "本次选择": action,
                "目标": "effect-choice-multi",
            },
            "duplicate": {
                "operation_id": "effect",
                "decision_id": decision,
                "action": action,
                "machine_copy": {"decision_id": decision},
                "本次选择": action,
                "目标": "effect-choice-duplicate",
            },
            "prose-mismatch": {
                "operation_id": "effect",
                "decision_id": decision,
                "action": action,
                "本次选择": "abort",
                "目标": "effect-choice-prose-mismatch",
            },
        }
        for suffix, card in bad_cards.items():
            with self.subTest(case=suffix):
                target = str(card["目标"])
                session_id = f"native-effect-choice-{suffix}"
                asked = ask_approval(
                    self.contract,
                    intent_id="l3:test-native-journal",
                    intent_revision=7,
                    kind=approval_kind,
                    target=target,
                    provider="codex",
                    session_id=session_id,
                    source="codex_permission_request",
                    card=card,
                    workspace=self.root,
                )
                with self.assertRaisesRegex(
                    NativeDecisionJournalError, "machine|semantic|card"
                ):
                    seal_binding(
                        self.contract,
                        operation="effect",
                        decision=decision,
                        target=target,
                        action=action,
                        intent_id="l3:test-native-journal",
                        intent_revision=7,
                        workspace=self.root,
                        provider="codex",
                        session_id=session_id,
                        source="codex_permission_request",
                        card=card,
                        request_id=asked["request_id"],
                    )

    def test_nested_continuation_action_prose_is_not_a_machine_alias(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["proposal"]
        target = "proposal-with-continuation-steps"
        session_id = "native-proposal-nested-actions"
        card = self.choice_card("proposal", decision, action, target)
        card["决策内容"] = {
            "自动续行动作": [
                {"动作": "生成唯一 cachebuster", "目标": "plugin.json"},
                {"动作": "事务化重装插件", "目标": "host-local"},
            ]
        }
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        sealed = seal_binding(
            self.contract,
            operation="proposal",
            decision=decision,
            target=target,
            action=action,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            workspace=self.root,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            request_id=asked["request_id"],
        )
        self.assertEqual(sealed["action"], action)
        self.assertEqual(len(sealed["card_sha256"]), 64)

    def test_retry_card_cannot_be_rebound_to_abort_seal(self) -> None:
        transaction = self.transaction("effect", suffix="retry-to-abort")
        binding = transaction["binding"]
        card = self.choice_card(
            "effect",
            "retry_authorized",
            "intervention-resolve",
            binding["target"],
        )
        with self.assertRaisesRegex(NativeDecisionJournalError, "decision|semantic"):
            seal_binding(
                self.contract,
                operation="effect",
                decision="abort",
                target=binding["target"],
                action="intervention-resolve",
                intent_id=binding["intent_id"],
                intent_revision=binding["intent_revision"],
                workspace=self.root,
                provider="codex",
                session_id=binding["session_id"],
                source=binding["source"],
                card=card,
                request_id=binding["request_id"],
                receipt=request_binding_receipt(
                    self.contract, binding["request_id"]
                ),
            )

    def test_prepare_reloads_durable_seal_and_rejects_copied_mutations(self) -> None:
        cases = (
            ("effect", {"decision": "abort"}),
            ("resume", {"operation": "intent", "kind": "intent"}),
            ("intent", {"seal_event_id": "f" * 64}),
        )
        for operation, changes in cases:
            with self.subTest(operation=operation):
                approval_kind, decision, action, _recover = OPERATIONS[operation]
                target = f"{operation}-durable-origin"
                session_id = f"native-{operation}-durable-origin"
                card = self.choice_card(operation, decision, action, target)
                asked = ask_approval(
                    self.contract,
                    intent_id="l3:test-native-journal",
                    intent_revision=7,
                    kind=approval_kind,
                    target=target,
                    provider="codex",
                    session_id=session_id,
                    source="codex_permission_request",
                    card=card,
                    workspace=self.root,
                )
                binding = seal_binding(
                    self.contract,
                    operation=operation,
                    decision=decision,
                    target=target,
                    action=action,
                    intent_id="l3:test-native-journal",
                    intent_revision=7,
                    workspace=self.root,
                    provider="codex",
                    session_id=session_id,
                    source="codex_permission_request",
                    card=card,
                    request_id=asked["request_id"],
                )
                forged = dict(binding, **changes)
                with self.assertRaisesRegex(
                    NativeDecisionJournalError, "durable seal|seal binding"
                ):
                    prepare(self.contract, forged)
                self.assertEqual(load_projection(self.contract)["transactions"], {})

    def test_same_request_has_one_idempotent_durable_seal(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["proposal"]
        target = "proposal-one-durable-seal"
        session_id = "native-proposal-one-durable-seal"
        card = self.choice_card("proposal", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        arguments = {
            "operation": "proposal",
            "decision": decision,
            "target": target,
            "action": action,
            "intent_id": "l3:test-native-journal",
            "intent_revision": 7,
            "workspace": self.root,
            "provider": "codex",
            "session_id": session_id,
            "source": "codex_permission_request",
            "card": card,
            "request_id": asked["request_id"],
        }
        first = seal_binding(self.contract, **arguments)
        second = seal_binding(self.contract, **arguments)
        self.assertEqual(first, second)
        rows = [json.loads(line) for line in journal_path(self.contract).read_text().splitlines()]
        self.assertEqual([row["event"] for row in rows], ["sealed"])

    def test_seal_append_crash_recovers_one_origin_without_second_transaction(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["resume"]
        target = "resume-seal-crash"
        session_id = "native-resume-seal-crash"
        card = self.choice_card("resume", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        arguments = {
            "operation": "resume",
            "decision": decision,
            "target": target,
            "action": action,
            "intent_id": "l3:test-native-journal",
            "intent_revision": 7,
            "workspace": self.root,
            "provider": "codex",
            "session_id": session_id,
            "source": "codex_permission_request",
            "card": card,
            "request_id": asked["request_id"],
        }
        real_write = journal_module._atomic_write_json
        anchor_writes = 0

        def crash_after_append(path: Path, value: dict) -> None:
            nonlocal anchor_writes
            if path == head_anchor_path(self.contract):
                anchor_writes += 1
                if anchor_writes == 2:
                    raise RuntimeError("seal anchor update interrupted")
            real_write(path, value)

        with mock.patch.object(
            journal_module, "_atomic_write_json", side_effect=crash_after_append
        ):
            with self.assertRaisesRegex(RuntimeError, "seal anchor update interrupted"):
                seal_binding(self.contract, **arguments)

        binding = seal_binding(self.contract, **arguments)
        first = prepare(self.contract, binding)
        second = prepare(self.contract, binding)
        self.assertEqual(first, second)
        self.assertEqual(len(load_projection(self.contract)["transactions"]), 1)

    def test_prepare_crash_before_append_is_retryable_and_consumes_seal_once(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["intent"]
        target = "intent-prepare-before-append"
        session_id = "native-intent-prepare-before-append"
        card = self.choice_card("intent", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        binding = seal_binding(
            self.contract,
            operation="intent",
            decision=decision,
            target=target,
            action=action,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            workspace=self.root,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            request_id=asked["request_id"],
        )
        real_write = journal_module._atomic_write_json

        def crash_before_append(path: Path, value: dict) -> None:
            if path == head_anchor_path(self.contract):
                raise RuntimeError("prepare append interrupted")
            real_write(path, value)

        with mock.patch.object(
            journal_module, "_atomic_write_json", side_effect=crash_before_append
        ):
            with self.assertRaisesRegex(RuntimeError, "prepare append interrupted"):
                prepare(self.contract, binding)

        prepared = prepare(self.contract, binding)
        self.assertEqual(prepare(self.contract, binding), prepared)
        rows = [json.loads(line) for line in journal_path(self.contract).read_text().splitlines()]
        self.assertEqual([row["event"] for row in rows], ["sealed", "prepared"])

    def test_replay_reproves_durable_original_request_receipt(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["resume"]
        target = "resume-replay-request-reproof"
        session_id = "native-resume-replay-request-reproof"
        card = self.choice_card("resume", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        seal_binding(
            self.contract,
            operation="resume",
            decision=decision,
            target=target,
            action=action,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            workspace=self.root,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            request_id=asked["request_id"],
        )
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[0]["card_sha256"] = "b" * 64
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            NativeDecisionJournalError, "receipt was substituted|durable native approval seal"
        ):
            load_projection(self.contract)

    def test_magic_values_are_rejected_without_implicit_execution(self) -> None:
        transaction = self.transaction("intent", suffix="zero-implicit")
        plan = recovery_plan(
            self.contract, transaction["transaction_id"], operation="intent"
        )
        attacks = []

        for field in ("stage", "adapter", "adapter_contract_sha256"):
            magic = MagicValue()
            values = {
                "stage": "effect_applied",
                "adapter": "t06:test",
                "adapter_contract_sha256": "a" * 64,
                "observation": {},
                "result": {},
            }
            values[field] = magic
            attacks.append((magic, lambda values=values: internal_recovery_result(plan, **values)))
        for field in ("observation", "result"):
            magic = MagicValue()
            values = {
                "stage": "effect_applied",
                "adapter": "t06:test",
                "adapter_contract_sha256": "a" * 64,
                "observation": {},
                "result": {},
            }
            values[field] = {"payload": magic}
            attacks.append((magic, lambda values=values: internal_recovery_result(plan, **values)))

        for magic, attack in attacks:
            with self.subTest(attack=len(attacks)):
                with self.assertRaises(NativeDecisionJournalError):
                    attack()
                self.assertEqual(magic.calls, 0)

        binding = transaction["binding"]
        card = self.choice_card(
            "intent", binding["decision"], binding["action"], binding["target"]
        )
        seal_values = {
            "operation": "intent",
            "decision": binding["decision"],
            "target": binding["target"],
            "action": binding["action"],
            "intent_id": binding["intent_id"],
            "intent_revision": binding["intent_revision"],
            "workspace": self.root,
            "provider": binding["provider"],
            "session_id": binding["session_id"],
            "source": binding["source"],
            "card": card,
            "request_id": binding["request_id"],
        }
        for field in ("operation", "intent_revision", "workspace", "card"):
            magic = MagicValue()
            changed = dict(seal_values)
            changed[field] = {"payload": magic} if field == "card" else magic
            with self.subTest(seal_field=field):
                with self.assertRaises(NativeDecisionJournalError):
                    seal_binding(self.contract, **changed)
                self.assertEqual(magic.calls, 0)

        for field in ("binding", "stage"):
            magic = MagicValue()
            with self.subTest(field=field):
                with self.assertRaises(NativeDecisionJournalError):
                    if field == "binding":
                        prepare(self.contract, magic)  # type: ignore[arg-type]
                    else:
                        journal_module._advance_event(
                            self.contract,
                            transaction["transaction_id"],
                            stage=magic,  # type: ignore[arg-type]
                            allow_sealed=True,
                        )
                self.assertEqual(magic.calls, 0)

    def test_machine_choice_is_identical_in_request_prepare_and_plan(self) -> None:
        transaction = self.transaction("effect", suffix="three-way-choice")
        binding = transaction["binding"]
        receipt = request_binding_receipt(self.contract, binding["request_id"])
        plan = recovery_plan(
            self.contract,
            transaction["transaction_id"],
            operation="effect",
        )
        self.assertEqual(
            (binding["operation"], binding["decision"], binding["action"]),
            ("effect", "retry_authorized", "intervention-resolve"),
        )
        self.assertEqual(binding["card_sha256"], receipt["card_sha256"])
        self.assertEqual(
            binding["request_binding_sha256"], receipt["binding_sha256"]
        )
        self.assertEqual(
            plan["binding_sha256"], journal_module._binding_sha256(binding)
        )
        self.assertEqual(
            plan["request_binding_sha256"], receipt["binding_sha256"]
        )

    def test_current_producer_wire_composes_through_seal_prepare_and_verify(
        self,
    ) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["intent"]
        target = "intent-current-producer-composition"
        session_id = "native-current-producer-composition"
        card = self.choice_card("intent", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.root,
            route="human",
        )
        receipt = request_binding_receipt(self.contract, asked["request_id"])
        binding = seal_binding(
            self.contract,
            operation="intent",
            decision=decision,
            target=target,
            action=action,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            workspace=self.root,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            request_id=asked["request_id"],
            receipt=receipt,
        )
        transaction = prepare(self.contract, binding)
        decide_approval(
            self.contract,
            kind=approval_kind,
            target=target,
            outcome="approved",
            provider="codex",
            session_id=session_id,
            actor="permission-request:codex",
            card=card,
            workspace=self.root,
            route="human",
            source="codex_permission_request",
        )
        decision_receipt = journal_module._verify_sealed_approval(
            self.contract, binding
        )
        current_rows = [
            json.loads(line)
            for line in event_store_path(self.contract).read_text().splitlines()
        ]
        self.assertEqual(
            [row["schema"] for row in current_rows],
            [APPROVAL_CAS_EVENT_SCHEMA, APPROVAL_CAS_EVENT_SCHEMA],
        )
        self.assertTrue(all(row.get("typed") is not True for row in current_rows))
        self.assertEqual(decision_receipt["request_id"], asked["request_id"])

        readers = self.authority_readers()
        self.append_t12_source_row(
            readers, transaction, "approval_decided"
        )
        advanced = advance_with_authority(
            self.contract,
            transaction["transaction_id"],
            readers=readers,
        )
        self.assertTrue(advanced["advanced"])
        self.assertEqual(advanced["stage"], "approval_decided")

    def test_missing_receipt_apis_fail_closed_without_writing(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["resume"]
        target = "resume-missing-receipt-api"
        session_id = "native-missing-receipt-api"
        card = self.choice_card("resume", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        receipt = request_binding_receipt(self.contract, asked["request_id"])
        values = {
            "operation": "resume",
            "decision": decision,
            "target": target,
            "action": action,
            "intent_id": "l3:test-native-journal",
            "intent_revision": 7,
            "workspace": self.root,
            "provider": "codex",
            "session_id": session_id,
            "source": "codex_permission_request",
            "card": card,
            "request_id": asked["request_id"],
        }
        for api_name, supplied_receipt in (
            ("request_binding_receipt", None),
            ("verify_request_binding_receipt", receipt),
        ):
            with self.subTest(api=api_name):
                before = self.journal_snapshot()
                with mock.patch.object(journal_module, api_name, None):
                    with self.assertRaises(NativeDecisionJournalError):
                        seal_binding(
                            self.contract,
                            **values,
                            receipt=supplied_receipt,
                        )
                self.assertEqual(self.journal_snapshot(), before)

        transaction = self.transaction("intent", suffix="missing-decided-api")
        before = self.journal_snapshot()
        with mock.patch.object(
            journal_module, "decided_request_receipt", None
        ):
            with self.assertRaisesRegex(
                NativeDecisionJournalError, "not durably decided"
            ):
                recover_intent(
                    self.contract, transaction["transaction_id"]
                )
        self.assertEqual(self.journal_snapshot(), before)

    def test_open_request_is_never_promoted_to_approval_by_recovery(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["resume"]
        target = "resume-still-open"
        card = self.choice_card("resume", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id="native-resume-open",
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        binding = seal_binding(
            self.contract,
            operation="resume",
            decision=decision,
            target=target,
            action=action,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            workspace=self.root,
            provider="codex",
            session_id="native-resume-open",
            source="codex_permission_request",
            card=card,
            request_id=asked["request_id"],
        )
        transaction = prepare(self.contract, binding)
        noop = self.inert_step()
        with self.assertRaisesRegex(
            NativeDecisionJournalError, "not durably decided"
        ):
            recover_resume(
                self.contract,
                transaction["transaction_id"],
                effect=noop,
                contract=noop,
            )
        projection = load_approval_projection(self.contract)
        self.assertEqual(len(projection["requests"]), 1)
        self.assertEqual(projection["requests"][asked["request_id"]]["status"], "asked")
        self.assertEqual(
            load_projection(self.contract)["transactions"][transaction["transaction_id"]][
                "stage"
            ],
            "prepared",
        )

    def test_public_prepare_rejects_caller_created_or_copied_legacy_binding(self) -> None:
        binding = self.legacy_binding(suffix="caller-created")
        before = journal_path(self.contract).read_bytes() if journal_path(self.contract).exists() else b""
        for candidate in (binding, dict(binding)):
            with self.subTest(candidate=id(candidate)):
                with self.assertRaisesRegex(
                    NativeDecisionJournalError, "legacy.*read-only|durable.*seal"
                ):
                    prepare(self.contract, candidate)
                after = journal_path(self.contract).read_bytes() if journal_path(self.contract).exists() else b""
                self.assertEqual(after, before)

    def test_historical_legacy_prepared_replays_but_every_public_advance_fails_closed(self) -> None:
        transaction = self.seed_historical_legacy_prepared(suffix="public-advance")
        self.assertFalse(transaction["sealed"])
        accepted = journal_path(self.contract).read_bytes()
        event_count = len(accepted.splitlines())
        for stage in (
            "approval_decided",
            "effect_applied",
            "contract_applied",
            "committed",
        ):
            with self.subTest(stage=stage):
                with self.assertRaisesRegex(
                    NativeDecisionJournalError,
                    "legacy|unsealed|read-only|external_authority_unverified|public.*unavailable",
                ):
                    advance(
                        self.contract,
                        transaction["transaction_id"],
                        stage=stage,
                        details={"caller_claim": True},
                    )
                self.assertEqual(journal_path(self.contract).read_bytes(), accepted)
                self.assertEqual(
                    len(journal_path(self.contract).read_text().splitlines()),
                    event_count,
                )

        noop = self.inert_step()
        with self.assertRaisesRegex(NativeDecisionJournalError, "legacy.*unsealed"):
            recover_resume(
                self.contract,
                transaction["transaction_id"],
                effect=noop,
                contract=noop,
            )
        unchanged = load_projection(self.contract)["transactions"][
            transaction["transaction_id"]
        ]
        self.assertEqual(unchanged["stage"], "prepared")
        self.assertFalse(unchanged["historical_terminal_seen"])
        self.assertFalse(unchanged["external_authority_verified"])

    def test_every_legacy_stage_rejects_every_transaction_mutation_zero_write(self) -> None:
        for stage in journal_module.STAGES:
            with self.subTest(stage=stage):
                transaction = self.seed_historical_legacy_prepared(
                    suffix=f"mutation-{stage}",
                    stage=stage,
                )
                tx_id = transaction["transaction_id"]
                binding = transaction["binding"]

                mutations = (
                    lambda: prepare(self.contract, binding),
                    lambda: advance(
                        self.contract,
                        tx_id,
                        stage="approval_decided",
                        details={"caller_claim": True},
                    ),
                    lambda: journal_module._advance_event(
                        self.contract,
                        tx_id,
                        stage="approval_decided",
                        details={"caller_claim": True},
                        allow_sealed=True,
                    ),
                )
                for mutation in mutations:
                    before = self.journal_snapshot()
                    with self.assertRaisesRegex(
                        NativeDecisionJournalError,
                        "legacy|unsealed|durable.*seal|read-only",
                    ):
                        mutation()
                    self.assertEqual(self.journal_snapshot(), before)

                reason = MagicValue()
                before = self.journal_snapshot()
                with mock.patch.object(
                    journal_module,
                    "_verify_sealed_approval",
                    side_effect=AssertionError("approval receipt lookup executed"),
                ) as receipt_lookup:
                    with self.assertRaisesRegex(
                        NativeDecisionJournalError,
                        "legacy|unsealed|durable.*seal|read-only",
                    ):
                        supersede(self.contract, tx_id, reason=reason)  # type: ignore[arg-type]
                receipt_lookup.assert_not_called()
                self.assertEqual(reason.calls, 0)
                self.assertEqual(self.journal_snapshot(), before)

    def test_public_advance_rejects_sealed_stage_skips_without_writing(self) -> None:
        transaction = self.transaction("proposal", suffix="cas")
        accepted = journal_path(self.contract).read_bytes()
        with self.assertRaisesRegex(
            NativeDecisionJournalError,
            "external_authority_unverified|public.*unavailable",
        ):
            advance(
                self.contract,
                transaction["transaction_id"],
                stage="effect_applied",
            )
        self.assertEqual(journal_path(self.contract).read_bytes(), accepted)

    def test_public_advance_cannot_commit_a_sealed_open_request(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["resume"]
        target = "resume-public-advance-open"
        card = self.choice_card("resume", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id="native-resume-public-open",
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        binding = seal_binding(
            self.contract,
            operation="resume",
            decision=decision,
            target=target,
            action=action,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            workspace=self.root,
            provider="codex",
            session_id="native-resume-public-open",
            source="codex_permission_request",
            card=card,
            request_id=asked["request_id"],
        )
        transaction = prepare(self.contract, binding)

        accepted = journal_path(self.contract).read_bytes()
        for stage in (
            "approval_decided",
            "effect_applied",
            "contract_applied",
            "committed",
        ):
            with self.subTest(stage=stage):
                with self.assertRaisesRegex(
                    NativeDecisionJournalError,
                    "external_authority_unverified|public.*unavailable",
                ):
                    advance(
                        self.contract,
                        transaction["transaction_id"],
                        stage=stage,
                    )
                self.assertEqual(journal_path(self.contract).read_bytes(), accepted)
        self.assertEqual(len(pending(self.contract)), 1)

    def test_historical_legacy_terminal_is_diagnostic_and_never_authority(self) -> None:
        transaction = self.seed_historical_legacy_prepared(
            suffix="terminal", terminal=True
        )

        diagnostic = recover_resume(
            self.contract,
            transaction["transaction_id"],
        )
        self.assertTrue(diagnostic["historical_terminal_seen"])
        self.assertEqual(diagnostic["historical_status"], "committed")
        self.assertEqual(diagnostic["legacy_authority"], "read-only")
        self.assertFalse(diagnostic["local_consistency_verified"])
        self.assertFalse(diagnostic["external_authority_verified"])
        self.assertEqual(diagnostic["journal_state"], "pending")
        self.assertNotEqual(diagnostic.get("status"), "committed")

        rows = [
            json.loads(line)
            for line in journal_path(self.contract).read_text(encoding="utf-8").splitlines()
        ]
        replayed = replay(self.contract, rows)["transactions"][
            transaction["transaction_id"]
        ]
        self.assertTrue(replayed["historical_terminal_seen"])
        self.assertEqual(replayed["historical_status"], "committed")
        self.assertFalse(replayed["local_consistency_verified"])
        self.assertFalse(replayed["external_authority_verified"])
        self.assertNotEqual(replayed["status"], "committed")

    def test_one_request_cannot_prepare_conflicting_semantic_transactions(self) -> None:
        transaction = self.transaction("proposal", suffix="semantic-conflict")
        approved = transaction["binding"]
        card = self.choice_card(
            "proposal",
            approved["decision"],
            approved["action"],
            approved["target"],
        )
        receipt = request_binding_receipt(self.contract, approved["request_id"])
        with self.assertRaisesRegex(
            NativeDecisionJournalError, "card|unique|conflict"
        ):
            conflicting = seal_binding(
                self.contract,
                operation="proposal",
                decision="reject",
                target=approved["target"],
                action="reject-proposal",
                intent_id=approved["intent_id"],
                intent_revision=approved["intent_revision"],
                workspace=self.root,
                provider="codex",
                session_id=approved["session_id"],
                source=approved["source"],
                card=card,
                request_id=approved["request_id"],
                receipt=receipt,
            )
            prepare(self.contract, conflicting)

    def test_recovery_api_never_invokes_caller_supplied_callbacks(self) -> None:
        transaction = self.transaction("intent", suffix="callback-boundary")
        called: list[str] = []

        def side_effect(_value: object = None) -> None:
            called.append("executed")

        counts: dict[str, int] = {}
        effect, contract = self.steps(
            transaction, "intent", "callback-boundary", counts
        )
        with self.assertRaises(NativeDecisionJournalError):
            recover_intent(
                self.contract,
                transaction["transaction_id"],
                effect=effect,
                contract=contract,
                failpoint=side_effect,  # type: ignore[arg-type]
            )
        self.assertEqual(called, [])

        malicious = InternalRecoveryStep(
            schema=effect.schema,
            plan=effect.plan,
            stage=effect.stage,
            adapter=effect.adapter,
            adapter_contract_sha256=effect.adapter_contract_sha256,
            observation={"callback": side_effect},
            result=effect.result,
            proof_sha256=effect.proof_sha256,
        )
        with self.assertRaisesRegex(
            NativeDecisionJournalError, "authority_unverified"
        ):
            recover_intent(
                self.contract,
                transaction["transaction_id"],
                effect=malicious,
                contract=contract,
            )
        self.assertEqual(called, [])

    def test_complete_line_truncation_is_detected(self) -> None:
        self.transaction("resume", suffix="complete-line-truncation")
        store = journal_path(self.contract)
        accepted = store.read_bytes()
        self.assertTrue(accepted.endswith(b"\n"))
        store.write_bytes(b"")
        with self.assertRaisesRegex(NativeDecisionJournalError, "anchor|head"):
            load_projection(self.contract)

    def test_pending_head_recovers_log_fsync_before_anchor_update(self) -> None:
        approval_kind, decision, action, _recover = OPERATIONS["resume"]
        target = "resume-pending-head"
        card = self.choice_card("resume", decision, action, target)
        asked = ask_approval(
            self.contract,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            kind=approval_kind,
            target=target,
            provider="codex",
            session_id="native-resume-pending-head",
            source="codex_permission_request",
            card=card,
            workspace=self.root,
        )
        binding = seal_binding(
            self.contract,
            operation="resume",
            decision=decision,
            target=target,
            action=action,
            intent_id="l3:test-native-journal",
            intent_revision=7,
            workspace=self.root,
            provider="codex",
            session_id="native-resume-pending-head",
            source="codex_permission_request",
            card=card,
            request_id=asked["request_id"],
        )
        real_write = journal_module._atomic_write_json
        anchor_writes = 0

        def crash_before_anchor(path: Path, value: dict) -> None:
            nonlocal anchor_writes
            if path == head_anchor_path(self.contract):
                anchor_writes += 1
                if anchor_writes == 2:
                    raise RuntimeError("anchor update interrupted")
            real_write(path, value)

        with mock.patch.object(
            journal_module, "_atomic_write_json", side_effect=crash_before_anchor
        ):
            with self.assertRaisesRegex(RuntimeError, "anchor update interrupted"):
                prepare(self.contract, binding)

        projection = load_projection(self.contract)
        self.assertEqual(len(projection["transactions"]), 1)
        self.assertTrue(head_anchor_path(self.contract).is_file())

    def test_stale_anchor_and_old_valid_prefix_replacement_are_detected(self) -> None:
        self.transaction("intent", suffix="old-prefix")
        old_prefix = journal_path(self.contract).read_bytes()
        old_anchor = head_anchor_path(self.contract).read_bytes()
        self.transaction("resume", suffix="new-prefix")
        latest_anchor = head_anchor_path(self.contract).read_bytes()

        head_anchor_path(self.contract).write_bytes(old_anchor)
        with self.assertRaisesRegex(NativeDecisionJournalError, "anchor mismatch"):
            load_projection(self.contract)

        head_anchor_path(self.contract).write_bytes(latest_anchor)
        journal_path(self.contract).write_bytes(old_prefix)
        with self.assertRaisesRegex(NativeDecisionJournalError, "anchor mismatch"):
            load_projection(self.contract)

    def test_head_proof_is_typed_and_declares_external_authority_boundary(self) -> None:
        self.transaction("effect", suffix="head-proof")
        proof = head_proof(self.contract)
        self.assertIs(get_type_hints(head_proof)["return"], JournalHeadProof)
        self.assertEqual(set(proof), set(JournalHeadProof.__required_keys__))
        self.assertTrue(proof["local_consistency_verified"])
        self.assertFalse(proof["external_authority_verified"])
        self.assertEqual(
            proof["external_authority_status"],
            "external_authority_unverified",
        )
        self.assertEqual(proof["recovery_status"], "pending")
        self.assertTrue(proof["external_anchor_required"])
        self.assertIn("T06", proof["external_anchor_boundary"])
        self.assertIn("rollback", proof["external_anchor_boundary"])
        self.assertIs(type(proof["generation"]), int)
        self.assertIs(type(proof["sequence"]), int)
        self.assertEqual(proof["event_id"], proof["event_sha256"])
        self.assertRegex(proof["anchor_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(proof["proof_sha256"], r"^[0-9a-f]{64}$")

    def test_synchronized_journal_and_anchor_rollback_remains_externally_unverified(self) -> None:
        self.transaction("intent", suffix="rollback-old")
        old_journal = journal_path(self.contract).read_bytes()
        old_anchor = head_anchor_path(self.contract).read_bytes()
        old_proof = head_proof(self.contract)
        self.transaction("resume", suffix="rollback-new")
        new_proof = head_proof(self.contract)
        self.assertGreater(new_proof["generation"], old_proof["generation"])

        journal_path(self.contract).write_bytes(old_journal)
        head_anchor_path(self.contract).write_bytes(old_anchor)
        rolled_back = head_proof(self.contract)
        self.assertEqual(rolled_back["proof_sha256"], old_proof["proof_sha256"])
        self.assertTrue(rolled_back["local_consistency_verified"])
        self.assertFalse(rolled_back["external_authority_verified"])
        self.assertEqual(
            rolled_back["external_authority_status"],
            "external_authority_unverified",
        )
        self.assertEqual(rolled_back["recovery_status"], "pending")
        self.assertNotIn("anchored_locally", rolled_back)

    def test_canonical_t12_advances_only_approval_and_wrappers_cannot_advance_effect(self) -> None:
        transaction = self.transaction("intent", suffix="typed-authority")
        readers = self.authority_readers()
        result = self.advance_from_t12_fixture(readers, transaction, "approval_decided")
        self.assertIs(
            get_type_hints(advance_with_authority)["return"],
            AuthorityAdvancementResult,
        )
        self.assertEqual(set(result), set(AuthorityAdvancementResult.__required_keys__))
        self.assertEqual(result["schema"], AUTHORITY_ADVANCEMENT_RESULT_SCHEMA)
        self.assertEqual(result["prior_stage"], "prepared")
        self.assertEqual(result["stage"], "approval_decided")
        self.assertTrue(result["advanced"])
        self.assertEqual(result["receipt_schema"], APPROVAL_CAS_RECEIPT_SCHEMA)

        accepted = self.journal_snapshot()
        blocked = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(blocked["status"], "pending")
        self.assertFalse(blocked["advanced"])
        self.assertEqual(self.journal_snapshot(), accepted)

        projection = load_projection(self.contract)
        approval_details = projection["transactions"][transaction["transaction_id"]][
            "stage_details"
        ]["approval_decided"]
        self.assertNotEqual(
            approval_details["typed_request_id"], transaction["binding"]["request_id"]
        )
        self.assertRegex(approval_details["source_event_id"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            projection["transactions"][transaction["transaction_id"]]["stage"],
            "approval_decided",
        )
        approval_rows = [
            json.loads(line)
            for line in approval_authority_store_path(self.contract).read_text().splitlines()
        ]
        self.assertEqual(
            len(
                [
                    row
                    for row in approval_rows
                    if row["schema"] == APPROVAL_CAS_EVENT_SCHEMA
                    and row.get("typed") is not True
                    and row["type"] == "approval.asked"
                ]
            ),
            1,
        )
        rows = [json.loads(line) for line in journal_path(self.contract).read_text().splitlines()]
        self.assertEqual(
            [row["event"] for row in rows],
            ["sealed", "prepared", "advanced"],
        )

    def test_bare_claims_classes_callbacks_and_self_hashes_are_data_only_pending(self) -> None:
        transaction = self.transaction("resume", suffix="typed-attacks")
        readers = self.authority_readers()
        forged = {"schema": APPROVAL_CAS_RECEIPT_SCHEMA}
        forged["receipt_sha256"] = hashlib.sha256(
            journal_module._canonical(forged).encode("utf-8")
        ).hexdigest()
        assert readers.approval is not None
        readers.approval.write_text(json.dumps(forged) + "\n", encoding="utf-8")
        callback_calls = 0

        def callback(*_args: object) -> dict:
            nonlocal callback_calls
            callback_calls += 1
            return forged

        attacks = (
            forged,
            dict(forged),
            NativeAuthorityReaders,
            callback,
            "t06:authority-reader",
            self.inert_step(),
        )
        accepted = self.journal_snapshot()
        for attack in attacks:
            with self.subTest(attack=type(attack).__name__):
                result = advance_with_authority(
                    self.contract,
                    transaction["transaction_id"],
                    readers=attack,  # type: ignore[arg-type]
                )
                self.assertEqual(result["status"], "pending")
                self.assertFalse(result["advanced"])
                self.assertEqual(self.journal_snapshot(), accepted)
        self.assertEqual(callback_calls, 0)

        magic = MagicValue()
        result = advance_with_authority(
            self.contract,
            transaction["transaction_id"],
            readers=NativeAuthorityReaders(
                approval=magic,  # type: ignore[arg-type]
                effect=None,
                contract=None,
                head_anchor=None,
            ),
        )
        self.assertEqual(result["status"], "pending")
        self.assertEqual(magic.calls, 0)
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_no_store_self_hash_and_hardlinked_wrapper_never_write(self) -> None:
        transaction = self.transaction("resume", suffix="wrapper-hardlink")
        readers = self.authority_readers()
        wrapper = Path(self.temporary.name) / "standalone.json"
        alias = Path(self.temporary.name) / "standalone-hardlink.json"
        claim = {"schema": APPROVAL_CAS_RECEIPT_SCHEMA, "decision": "allow"}
        claim["receipt_sha256"] = hashlib.sha256(
            journal_module._canonical(claim).encode("utf-8")
        ).hexdigest()
        wrapper.write_text(json.dumps(claim) + "\n", encoding="utf-8")
        os.link(wrapper, alias)
        readers = NativeAuthorityReaders(alias, None, None, None)
        accepted = self.journal_snapshot()
        result = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(result["status"], "pending")
        self.assertFalse(result["advanced"])
        self.assertIn("canonical store", result["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_canonical_source_rejects_hardlink_symlink_and_rename_race(self) -> None:
        transaction = self.transaction("intent", suffix="source-controls")
        readers = self.authority_readers()
        self.append_t12_source_row(readers, transaction, "approval_decided")
        source = approval_authority_store_path(self.contract)
        accepted = self.journal_snapshot()

        hardlink = source.with_name("approval-hardlink.jsonl")
        os.link(source, hardlink)
        hardlinked = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(hardlinked["status"], "pending")
        self.assertIn("exactly one link", hardlinked["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)
        hardlink.unlink()

        real_source = source.with_name("approval-real.jsonl")
        source.replace(real_source)
        source.symlink_to(real_source.name)
        symlinked = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(symlinked["status"], "pending")
        self.assertIn("nofollow leaf open", symlinked["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)
        source.unlink()
        real_source.replace(source)

        alias_parent = Path(self.temporary.name) / "contract-parent-link"
        alias_parent.symlink_to(Path(self.temporary.name), target_is_directory=True)
        ancestor = advance_with_authority(
            alias_parent / self.contract.name,
            transaction["transaction_id"],
            readers=readers,
        )
        self.assertEqual(ancestor["status"], "pending")
        self.assertIn("symlink or non-directory ancestor", ancestor["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

        original_read = journal_module.os.read
        raced = False
        replaced = source.with_name("approval-raced.jsonl")

        def rename_after_first_read(descriptor: int, size: int) -> bytes:
            nonlocal raced
            chunk = original_read(descriptor, size)
            if chunk and not raced:
                raced = True
                payload = source.read_bytes()
                source.replace(replaced)
                source.write_bytes(payload)
            return chunk

        with mock.patch.object(journal_module.os, "read", side_effect=rename_after_first_read):
            renamed = advance_with_authority(
                self.contract, transaction["transaction_id"], readers=readers
            )
        self.assertEqual(renamed["status"], "pending")
        self.assertIn("changed during stable read", renamed["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)
        source.unlink()
        replaced.replace(source)

        payload = source.read_bytes()
        truncated_once = False

        def truncate_after_first_read(descriptor: int, size: int) -> bytes:
            nonlocal truncated_once
            chunk = original_read(descriptor, size)
            if chunk and not truncated_once:
                truncated_once = True
                source.write_bytes(payload[:-1])
            return chunk

        with mock.patch.object(journal_module.os, "read", side_effect=truncate_after_first_read):
            truncated = advance_with_authority(
                self.contract, transaction["transaction_id"], readers=readers
            )
        source.write_bytes(payload)
        self.assertEqual(truncated["status"], "pending")
        self.assertIn("changed during stable read", truncated["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_accepted_producer_envelopes_have_golden_fields_and_paths(self) -> None:
        transaction = self.transaction("effect", suffix="producer-golden")
        readers = self.authority_readers()
        self.append_t12_source_row(readers, transaction, "approval_decided")
        approval_path = approval_authority_store_path(self.contract)
        approval_rows = [
            json.loads(line) for line in approval_path.read_text().splitlines()
        ]
        typed = [row for row in approval_rows if row.get("typed") is True]
        self.assertEqual(
            approval_path,
            self.contract.with_name("intent.approvals.jsonl"),
        )
        self.assertEqual(
            [row["type"] for row in typed],
            ["approval.asked", "approval.prompt-observed", "approval.decided"],
        )
        self.assertEqual(
            set(typed[0]),
            {
                "at", "card_sha256", "contract_sha256", "decision_owner",
                "expires_at", "intent_id_sha256", "intent_revision", "kind",
                "lane_sha256", "prompt_shown", "proposal_sha256", "provider",
                "reassess_at", "replaced_request_id", "replacement_identity",
                "request_id", "request_identity", "route", "schema", "sequence",
                "snapshot", "snapshot_identity", "source", "target_sha256",
                "type", "typed", "workspace_sha256",
            },
        )
        self.assertEqual(
            set(typed[1]),
            {
                "schema", "contract_sha256", "sequence", "at", "type",
                "typed", "request_id", "provider", "lane_sha256",
                "snapshot_identity", "prompt_shown", "decision_owner",
            },
        )
        self.assertEqual(
            set(typed[2]),
            {
                "schema", "contract_sha256", "sequence", "at", "type",
                "typed", "request_id", "provider", "lane_sha256", "outcome",
                "actor", "decision_owner", "typed_receipt", "receipt_sha256",
            },
        )
        self.assertNotIn("event_id", typed[2])
        self.assertNotIn("request_identity", typed[1])
        self.assertEqual(
            set(typed[2]["typed_receipt"]),
            {
                "schema", "request_id", "receipt_id", "outcome", "snapshot",
                "snapshot_identity", "request_identity", "decision_identity",
                "replacement_identity", "execution_authorized",
            },
        )
        self.assertEqual(
            set(typed[2]["typed_receipt"]["snapshot"]),
            {
                "card_sha256", "provider", "session_id", "lane_sha256",
                "target_sha256", "revision", "journal_sha256", "effect_sha256",
                "world_state_sha256",
            },
        )
        receipt = typed[2]["typed_receipt"]
        self.assertNotEqual(receipt["request_id"], transaction["binding"]["request_id"])
        self.assertEqual(
            receipt["snapshot_identity"],
            golden_t11_identity("approval-snapshot", receipt["snapshot"]),
        )
        self.assertEqual(
            receipt["request_identity"],
            golden_t11_identity(
                "approval-request",
                {"request_id": receipt["request_id"], "snapshot": receipt["snapshot"]},
            ),
        )
        self.assertEqual(
            receipt["decision_identity"],
            golden_t11_identity(
                "approval-decision",
                {
                    "request_id": receipt["request_id"],
                    "receipt_id": receipt["receipt_id"],
                    "outcome": receipt["outcome"],
                    "snapshot": receipt["snapshot"],
                },
            ),
        )
        self.assertNotEqual(
            receipt["snapshot_identity"],
            repair2_identity("sulde-approval-cas-snapshot-v1", receipt["snapshot"]),
        )

        advanced = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertTrue(advanced["advanced"])
        effect_path = self.write_t10_dispatch(transaction)
        effect_rows = [json.loads(line) for line in effect_path.read_text().splitlines()]
        self.assertEqual(
            effect_path,
            self.contract.with_name("intent.interventions.jsonl"),
        )
        self.assertEqual(
            set(effect_rows[0]),
            {
                "schema", "contract_sha256", "sequence", "at", "type", "event_id",
                "batch_id", "call_id", "idempotency_key", "intent_id",
                "intent_revision", "fingerprint", "source_event_id", "capability",
                "effect", "provider", "session_id", "task_id",
                "operation_arguments_digest", "resources", "resource_set_sha256",
                "batch_semantics_sha256",
            },
        )
        self.assertEqual(
            set(effect_rows[1]),
            {
                "schema", "contract_sha256", "sequence", "at", "type", "event_id",
                "batch_id", "call_id", "idempotency_key", "prepared_event_id",
                "resource_set_sha256", "batch_semantics_sha256",
            },
        )
        prepared = effect_rows[0]
        self.assertEqual(
            prepared["resource_set_sha256"],
            hashlib.sha256(
                golden_canonical(prepared["resources"]).encode("utf-8")
            ).hexdigest(),
        )
        semantics = {
            key: prepared[key]
            for key in (
                "batch_id", "call_id", "idempotency_key", "intent_id",
                "intent_revision", "fingerprint", "source_event_id",
                "capability", "effect", "provider", "session_id", "task_id",
                "operation_arguments_digest", "resources",
            )
        }
        self.assertEqual(
            prepared["batch_semantics_sha256"],
            hashlib.sha256(golden_canonical(semantics).encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(
            prepared["resource_set_sha256"],
            repair2_identity(
                "sulde-intervention-resource-set-v1", prepared["resources"]
            ),
        )

    def test_unknown_t12_schema_is_pending_with_zero_write(self) -> None:
        transaction = self.transaction("intent", suffix="unknown-t12")
        readers = self.authority_readers()
        self.append_t12_source_row(readers, transaction, "approval_decided")
        source = approval_authority_store_path(self.contract)
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        rows[-1]["schema"] = "sulde-approval-pair-event-v999"
        source.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        accepted = self.journal_snapshot()
        result = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(result["status"], "pending")
        self.assertIn("schema is unknown", result["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_accepted_t12_wire_bytes_omit_prompt_request_identity_and_advance_once(
        self,
    ) -> None:
        transaction = self.transaction("intent", suffix="accepted-wire-bytes")
        readers = self.authority_readers()
        source = approval_authority_store_path(self.contract)
        legacy_prefix = source.read_bytes()
        self.append_t12_source_row(readers, transaction, "approval_decided")
        payload = source.read_bytes()
        typed_lines = payload[len(legacy_prefix):].splitlines(keepends=True)
        self.assertEqual(len(typed_lines), 3)
        typed_rows = [json.loads(line) for line in typed_lines]
        self.assertEqual(typed_rows[0]["replacement_identity"], "")
        self.assertIsNone(
            typed_rows[-1]["typed_receipt"]["replacement_identity"]
        )
        expected_wire = b"".join(
            (
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode("utf-8")
            for row in typed_rows
        )
        self.assertEqual(payload, legacy_prefix + expected_wire)
        self.assertNotIn(b'"request_identity"', typed_lines[1])
        self.assertEqual(
            set(typed_rows[1]),
            {
                "at", "contract_sha256", "decision_owner", "lane_sha256",
                "prompt_shown", "provider", "request_id", "schema", "sequence",
                "snapshot_identity", "type", "typed",
            },
        )

        before = self.journal_snapshot()
        first = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        after = self.journal_snapshot()
        second = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertTrue(first["advanced"])
        self.assertFalse(second["advanced"])
        self.assertEqual(after["event_count"], before["event_count"] + 1)
        self.assertEqual(self.journal_snapshot(), after)

    def test_nonreplacement_receipt_empty_lineage_is_pending_with_zero_write(
        self,
    ) -> None:
        transaction = self.transaction("intent", suffix="empty-receipt-lineage")
        readers = self.authority_readers()
        self.append_t12_source_row(
            readers,
            transaction,
            "approval_decided",
            receipt={"replacement_identity": ""},
        )
        accepted = self.journal_snapshot()
        result = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(result["status"], "pending")
        self.assertFalse(result["advanced"])
        self.assertIn("decision correlation is invalid", result["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_malformed_duplicate_and_nonhuman_t12_rows_are_pending(self) -> None:
        cases = (
            "malformed",
            "missing-asked-field",
            "extra-prompt-field",
            "duplicate",
            "system-owner",
            "empty-actor",
        )
        for index, case in enumerate(cases, 1):
            with self.subTest(case=case):
                transaction = self.transaction("intent", suffix=f"typed-{index}")
                readers = self.authority_readers()
                source = approval_authority_store_path(self.contract)
                producer_prefix = source.read_bytes()
                self.append_t12_source_row(
                    readers, transaction, "approval_decided"
                )
                rows = [json.loads(line) for line in source.read_text().splitlines()]
                if case == "malformed":
                    rows[-3]["typed"] = False
                elif case == "missing-asked-field":
                    del rows[-3]["expires_at"]
                elif case == "extra-prompt-field":
                    rows[-2]["request_identity"] = rows[-3]["request_identity"]
                elif case == "duplicate":
                    rows.append(dict(rows[-1], sequence=len(rows) + 1))
                elif case == "system-owner":
                    rows[-1]["decision_owner"] = "system"
                else:
                    rows[-1]["actor"] = ""
                source.write_text(
                    "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8",
                )
                accepted = self.journal_snapshot()
                result = advance_with_authority(
                    self.contract, transaction["transaction_id"], readers=readers
                )
                self.assertEqual(result["status"], "pending")
                self.assertFalse(result["advanced"])
                self.assertEqual(self.journal_snapshot(), accepted)
                source.write_bytes(producer_prefix)

    def test_orphan_and_decided_before_prompt_are_pending_with_zero_write(self) -> None:
        for index, case in enumerate(("orphan", "before-prompt"), 1):
            with self.subTest(case=case):
                transaction = self.transaction("intent", suffix=f"lifecycle-{index}")
                readers = self.authority_readers()
                source = approval_authority_store_path(self.contract)
                producer_prefix = source.read_bytes()
                self.append_t12_source_row(readers, transaction, "approval_decided")
                rows = [json.loads(line) for line in source.read_text().splitlines()]
                prefix = [row for row in rows if row.get("typed") is not True]
                typed = [row for row in rows if row.get("typed") is True]
                if case == "orphan":
                    typed = [typed[-1]]
                else:
                    typed = [typed[-3], typed[-1], typed[-2]]
                rows = prefix + typed
                for sequence, row in enumerate(rows, 1):
                    row["sequence"] = sequence
                source.write_text(
                    "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8",
                )
                accepted = self.journal_snapshot()
                result = advance_with_authority(
                    self.contract, transaction["transaction_id"], readers=readers
                )
                self.assertEqual(result["status"], "pending")
                self.assertFalse(result["advanced"])
                self.assertEqual(self.journal_snapshot(), accepted)
                source.write_bytes(producer_prefix)

    def test_duplicate_matching_typed_receipts_are_pending_with_zero_write(self) -> None:
        transaction = self.transaction("intent", suffix="duplicate-match")
        readers = self.authority_readers()
        self.append_t12_source_row(readers, transaction, "approval_decided")
        alternate = "apr-" + "e" * 24
        self.append_t12_source_row(
            readers,
            transaction,
            "approval_decided",
            typed_request_id=alternate,
        )
        accepted = self.journal_snapshot()
        result = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(result["status"], "pending")
        self.assertIn("no unique current T12 receipt", result["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_replacement_terminalizes_old_request_and_fresh_request_is_reachable(self) -> None:
        transaction = self.transaction("intent", suffix="replacement")
        readers = self.authority_readers()
        self.append_t12_source_row(
            readers,
            transaction,
            "approval_decided",
            snapshot={"card_sha256": "1" * 64},
        )
        source = approval_authority_store_path(self.contract)
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        prefix = [row for row in rows if row.get("typed") is not True]
        old_asked, old_prompt, old_decided = [
            row for row in rows if row.get("typed") is True
        ]
        old_id = old_asked["request_id"]
        fresh_id = "apr-" + "d" * 24
        snapshot = journal_module._t11_snapshot(
            self.contract,
            transaction,
            transaction["binding"],
            head_proof(self.contract),
        )
        fresh_request_identity = golden_t11_identity(
            "approval-request", {"request_id": fresh_id, "snapshot": snapshot}
        )
        fresh_replacement_identity = golden_t11_identity(
            "approval-fresh-replacement",
            {
                "previous_request_identity": old_asked["request_identity"],
                "replacement_request_identity": fresh_request_identity,
            },
        )
        replaced = {
            "schema": APPROVAL_CAS_EVENT_SCHEMA,
            "contract_sha256": old_asked["contract_sha256"],
            "at": "2026-08-20T00:00:02+00:00",
            "type": "approval.replaced",
            "typed": True,
            "request_id": old_id,
            "replacement_request_id": fresh_id,
            "replacement_identity": fresh_replacement_identity,
        }
        fresh_asked = dict(
            old_asked,
            request_id=fresh_id,
            card_sha256=snapshot["card_sha256"],
            target_sha256=snapshot["target_sha256"],
            request_identity=fresh_request_identity,
            snapshot=snapshot,
            snapshot_identity=golden_t11_identity("approval-snapshot", snapshot),
            replaced_request_id=old_id,
            replacement_identity=fresh_replacement_identity,
        )
        fresh_prompt = dict(
            old_prompt,
            request_id=fresh_id,
            snapshot_identity=fresh_asked["snapshot_identity"],
        )
        fresh_receipt_id = "receipt-" + hashlib.sha256(
            fresh_id.encode("utf-8")
        ).hexdigest()[:24]
        fresh_receipt = dict(
            old_decided["typed_receipt"],
            request_id=fresh_id,
            receipt_id=fresh_receipt_id,
            snapshot=snapshot,
            snapshot_identity=fresh_asked["snapshot_identity"],
            request_identity=fresh_request_identity,
            replacement_identity=fresh_replacement_identity,
        )
        fresh_receipt["decision_identity"] = golden_t11_identity(
            "approval-decision",
            {
                "request_id": fresh_id,
                "receipt_id": fresh_receipt_id,
                "outcome": "allow",
                "snapshot": snapshot,
            },
        )
        fresh_decided = dict(
            old_decided,
            request_id=fresh_id,
            typed_receipt=fresh_receipt,
            receipt_sha256=hashlib.sha256(
                fresh_receipt_id.encode("utf-8")
            ).hexdigest(),
        )
        rows = prefix + [
            old_asked,
            old_prompt,
            replaced,
            fresh_asked,
            fresh_prompt,
            fresh_decided,
        ]
        for sequence, row in enumerate(rows, 1):
            row["sequence"] = sequence
        source.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        result = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertTrue(result["advanced"])
        self.assertNotIn("provider", replaced)
        self.assertNotIn("lane_sha256", replaced)
        self.assertNotIn("request_identity", fresh_prompt)
        self.assertEqual(fresh_asked["replaced_request_id"], old_id)
        details = load_projection(self.contract)["transactions"][
            transaction["transaction_id"]
        ]["stage_details"]["approval_decided"]
        self.assertEqual(details["typed_request_id"], fresh_id)
        self.assertNotEqual(details["typed_request_id"], old_id)
        self.assertEqual(
            details["authority_receipt"]["replacement_identity"],
            fresh_replacement_identity,
        )

    def test_v1_typed_injection_is_not_t12_authority(self) -> None:
        transaction = self.transaction("intent", suffix="v1-injection")
        source = approval_authority_store_path(self.contract)
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        row = {
            "schema": "sulde-approval-pair-event-v1",
            "contract_sha256": journal_module._contract_digest(self.contract),
            "sequence": len(rows) + 1,
            "at": "2026-08-20T00:00:00+00:00",
            "type": "approval.decided",
            "request_id": transaction["binding"]["request_id"],
            "receipt": {
                "schema": APPROVAL_CAS_RECEIPT_SCHEMA,
                "decision": "allow",
            },
        }
        with source.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        accepted = self.journal_snapshot()
        result = advance_with_authority(
            self.contract,
            transaction["transaction_id"],
            readers=self.authority_readers(),
        )
        self.assertEqual(result["status"], "pending")
        self.assertIn("no unique current T12 receipt", result["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_receipt_cas_rejects_wrong_t11_domains_and_decision_ownership(self) -> None:
        cases = (
            ("contract_sha256", {"row": {"contract_sha256": "0" * 64}}),
            ("request_id", {"receipt": {"request_id": "apr-" + "f" * 24}}),
            ("card_sha256", {"snapshot": {"card_sha256": "1" * 64}}),
            ("target_sha256", {"snapshot": {"target_sha256": "2" * 64}}),
            ("revision", {"snapshot": {"revision": 999_999}}),
            ("journal_sha256", {"snapshot": {"journal_sha256": "3" * 64}}),
            ("effect_sha256", {"snapshot": {"effect_sha256": "4" * 64}}),
            ("world_state_sha256", {"snapshot": {"world_state_sha256": "5" * 64}}),
            ("session_id", {"snapshot": {"session_id": "substituted"}}),
            ("provider", {"row": {"provider": "claude"}}),
            ("lane_sha256", {"row": {"lane_sha256": "6" * 64}}),
            ("decision_owner", {"row": {"decision_owner": "agent"}}),
            ("outcome", {"receipt": {"outcome": "deny"}, "row": {"outcome": "deny"}}),
            ("replacement", {"receipt": {"replacement_identity": "sha256:" + "7" * 64}}),
            ("execution_authorized", {"receipt": {"execution_authorized": True}}),
        )
        for index, (field, changes) in enumerate(cases, 1):
            with self.subTest(field=field):
                transaction = self.transaction("intent", suffix=f"cas-{index}")
                readers = self.authority_readers()
                source = approval_authority_store_path(self.contract)
                producer_prefix = source.read_bytes()
                self.append_t12_source_row(
                    readers,
                    transaction,
                    "approval_decided",
                    **changes,
                )
                accepted = self.journal_snapshot()
                result = advance_with_authority(
                    self.contract,
                    transaction["transaction_id"],
                    readers=readers,
                )
                self.assertEqual(result["status"], "pending")
                self.assertEqual(self.journal_snapshot(), accepted)
                source.write_bytes(producer_prefix)

    def test_repair2_namespaced_t11_identities_are_rejected(self) -> None:
        transaction = self.transaction("intent", suffix="old-t11")
        readers = self.authority_readers()
        self.append_t12_source_row(readers, transaction, "approval_decided")
        source = approval_authority_store_path(self.contract)
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        asked, prompt, decided = [
            row for row in rows if row.get("typed") is True
        ]
        receipt = decided["typed_receipt"]
        old_snapshot = repair2_identity(
            "sulde-approval-cas-snapshot-v1", receipt["snapshot"]
        )
        old_request = repair2_identity(
            "sulde-approval-cas-request-v1",
            {
                "request_id": receipt["request_id"],
                "snapshot_identity": old_snapshot,
            },
        )
        old_decision = repair2_identity(
            "sulde-approval-cas-decision-v1",
            {
                "outcome": receipt["outcome"],
                "replacement_identity": receipt["replacement_identity"],
                "request_identity": old_request,
            },
        )
        asked.update(snapshot_identity=old_snapshot, request_identity=old_request)
        prompt.update(snapshot_identity=old_snapshot)
        receipt.update(
            snapshot_identity=old_snapshot,
            request_identity=old_request,
            decision_identity=old_decision,
        )
        source.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        accepted = self.journal_snapshot()
        result = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(result["status"], "pending")
        self.assertIn("asked lifecycle payload is invalid", result["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_generation_is_rechecked_inside_journal_mutation_lock(self) -> None:
        transaction = self.transaction("intent", suffix="generation-race")
        competing = self.transaction("resume", suffix="generation-race-other")
        readers = self.authority_readers()
        self.append_t12_source_row(readers, transaction, "approval_decided")
        real_mutate = journal_module._mutate
        injected = False

        def race(contract_path: Path, mutation):
            nonlocal injected
            if not injected:
                injected = True
                real_mutate(
                    self.contract,
                    lambda _projection: ([{
                        "event": "superseded",
                        "transaction_id": competing["transaction_id"],
                        "reason": "generation race injection",
                        "details": {"race_fixture": True},
                    }], competing["transaction_id"]),
                )
            return real_mutate(contract_path, mutation)

        with mock.patch.object(journal_module, "_mutate", side_effect=race):
            result = advance_with_authority(
                self.contract,
                transaction["transaction_id"],
                readers=readers,
            )
        self.assertEqual(result["status"], "pending")
        self.assertIn("generation", result["reason"])
        projection = load_projection(self.contract)
        self.assertEqual(
            projection["transactions"][transaction["transaction_id"]]["stage"],
            "prepared",
        )
        self.assertEqual(
            projection["transactions"][competing["transaction_id"]]["stage"],
            "superseded",
        )
        rows = [json.loads(line) for line in journal_path(self.contract).read_text().splitlines()]
        self.assertFalse(
            any(
                row.get("event") == "advanced"
                and row.get("transaction_id") == transaction["transaction_id"]
                for row in rows
            )
        )

    def test_effect_completion_and_classification_are_orthogonal(self) -> None:
        transaction = self.transaction("effect", suffix="ap-0242")
        readers = self.authority_readers()
        self.assertEqual(
            self.advance_from_t12_fixture(readers, transaction, "approval_decided")["stage"],
            "approval_decided",
        )
        source = self.write_t10_dispatch(transaction)
        accepted = self.journal_snapshot()
        dispatched = advance_with_authority(
            self.contract,
            transaction["transaction_id"],
            readers=readers,
        )
        self.assertEqual(dispatched["status"], "pending")
        self.assertFalse(dispatched["advanced"])
        self.assertIn("original T10 resources and operation arguments", dispatched["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

        rows = [json.loads(line) for line in source.read_text().splitlines()]
        rows.append(dict(rows[-1], sequence=3))
        rows[-1]["event_id"] = journal_module._source_event_digest(rows[-1])
        source.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        duplicate = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(duplicate["status"], "pending")
        self.assertIn("one exact", duplicate["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_t10_dispatch_rejects_call_resource_and_batch_cas_substitution(self) -> None:
        transaction = self.transaction("effect", suffix="t10-cas")
        readers = self.authority_readers()
        self.assertTrue(
            self.advance_from_t12_fixture(readers, transaction, "approval_decided")["advanced"]
        )
        accepted = self.journal_snapshot()
        cases = (
            {"prepared": {"capability": "other"}},
            {"prepared": {"source_event_id": "0" * 64}},
            {"prepared": {"resource_set_sha256": "1" * 64}},
            {"prepared": {"batch_semantics_sha256": "2" * 64}},
            {"dispatched": {"prepared_event_id": "0" * 64}},
            {"dispatched": {"call_id": "call-substituted"}},
            {"dispatched": {"idempotency_key": "idempotency:substituted"}},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.write_t10_dispatch(transaction, **changes)
                result = advance_with_authority(
                    self.contract, transaction["transaction_id"], readers=readers
                )
                self.assertEqual(result["status"], "pending")
                self.assertFalse(result["advanced"])
                self.assertEqual(self.journal_snapshot(), accepted)

    def test_repair2_namespaced_t10_hashes_are_rejected(self) -> None:
        transaction = self.transaction("effect", suffix="old-t10")
        readers = self.authority_readers()
        self.assertTrue(
            self.advance_from_t12_fixture(
                readers, transaction, "approval_decided"
            )["advanced"]
        )
        source = self.write_t10_dispatch(transaction)
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        prepared, dispatched = rows
        prepared["resource_set_sha256"] = repair2_identity(
            "sulde-intervention-resource-set-v1", prepared["resources"]
        )
        old_semantics = {
            key: prepared[key]
            for key in (
                "intent_id", "intent_revision", "fingerprint", "source_event_id",
                "capability", "effect", "provider", "session_id", "task_id",
                "operation_arguments_digest", "resources", "resource_set_sha256",
            )
        }
        prepared["batch_semantics_sha256"] = repair2_identity(
            "sulde-intervention-batch-semantics-v1", old_semantics
        )
        prepared["event_id"] = journal_module._source_event_digest(prepared)
        dispatched.update(
            prepared_event_id=prepared["event_id"],
            resource_set_sha256=prepared["resource_set_sha256"],
            batch_semantics_sha256=prepared["batch_semantics_sha256"],
        )
        dispatched["event_id"] = journal_module._source_event_digest(dispatched)
        source.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        accepted = self.journal_snapshot()
        result = advance_with_authority(
            self.contract, transaction["transaction_id"], readers=readers
        )
        self.assertEqual(result["status"], "pending")
        self.assertIn("call/resource/batch dispatch CAS is invalid", result["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_legacy_stale_and_missing_authority_never_write(self) -> None:
        legacy = self.seed_historical_legacy_prepared(suffix="typed-legacy")
        empty = NativeAuthorityReaders(None, None, None, None)
        accepted = self.journal_snapshot()
        result = advance_with_authority(
            self.contract, legacy["transaction_id"], readers=empty
        )
        self.assertEqual(result["status"], "pending")
        self.assertIn("legacy", result["reason"])
        self.assertEqual(self.journal_snapshot(), accepted)

    def test_authority_crash_boundaries_resume_without_second_request_or_external_write(self) -> None:
        transaction = self.transaction("observation-export", suffix="crash-cas")
        readers = self.authority_readers()
        tx_id = transaction["transaction_id"]
        with self.assertRaisesRegex(
            NativeDecisionAdvancementInterrupted, "after_prepared"
        ):
            advance_with_authority(
                self.contract,
                tx_id,
                readers=readers,
                failpoint="after_prepared",
            )
        self.assertEqual(load_projection(self.contract)["transactions"][tx_id]["stage"], "prepared")

        self.append_t12_source_row(readers, transaction, "approval_decided")
        source = approval_authority_store_path(self.contract)
        source_bytes = source.read_bytes()
        with self.assertRaisesRegex(
            NativeDecisionAdvancementInterrupted, "after_approval"
        ):
            advance_with_authority(
                self.contract,
                tx_id,
                readers=readers,
                failpoint="after_approval",
            )
        self.assertEqual(
            load_projection(self.contract)["transactions"][tx_id]["stage"],
            "prepared",
        )
        self.assertEqual(source.read_bytes(), source_bytes)
        recovered = advance_with_authority(self.contract, tx_id, readers=readers)
        self.assertEqual(recovered["stage"], "approval_decided")
        self.assertEqual(source.read_bytes(), source_bytes)

        self.write_t10_dispatch(transaction)
        accepted = self.journal_snapshot()
        for failpoint in ("after_effect", "after_contract", "after_anchor"):
            with self.subTest(failpoint=failpoint):
                blocked = advance_with_authority(
                    self.contract, tx_id, readers=readers, failpoint=failpoint
                )
                self.assertEqual(blocked["status"], "pending")
                self.assertFalse(blocked["advanced"])
                self.assertEqual(self.journal_snapshot(), accepted)

        approval_rows = [
            json.loads(line)
            for line in approval_authority_store_path(self.contract).read_text().splitlines()
        ]
        self.assertEqual(
            len(
                [
                    row
                    for row in approval_rows
                    if row["schema"] == APPROVAL_CAS_EVENT_SCHEMA
                    and row.get("typed") is not True
                    and row["type"] == "approval.asked"
                ]
            ),
            1,
        )
        self.assertEqual(
            [row["event"] for row in map(json.loads, journal_path(self.contract).read_text().splitlines())].count("prepared"),
            1,
        )

    def test_untyped_rows_after_typed_authority_are_ignored_without_rewrite(self) -> None:
        transaction = self.transaction("intent", suffix="interleaved-untyped")
        readers = self.authority_readers()
        self.append_t12_source_row(readers, transaction, "approval_decided")
        source = approval_authority_store_path(self.contract)
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        audit_id = "apr-eeeeeeeeeeeeeeeeeeeeeeee"
        rows.extend(
            [
                {
                    "schema": APPROVAL_CAS_EVENT_SCHEMA,
                    "contract_sha256": journal_module._contract_digest(self.contract),
                    "sequence": len(rows) + 1,
                    "at": "2026-08-20T00:00:03+00:00",
                    "type": "approval.asked",
                    "request_id": audit_id,
                    "intent_id_sha256": "1" * 64,
                    "intent_revision": 7,
                    "kind": "event",
                    "target_sha256": "2" * 64,
                    "card_sha256": "",
                    "workspace_sha256": "",
                    "proposal_sha256": "",
                    "route": "human",
                    "expires_at": "2099-01-01T00:00:00+00:00",
                    "reassess_at": "",
                    "provider": "unknown",
                    "lane_sha256": "",
                    "source": "proposal_review",
                },
                {
                    "schema": APPROVAL_CAS_EVENT_SCHEMA,
                    "contract_sha256": journal_module._contract_digest(self.contract),
                    "sequence": len(rows) + 2,
                    "at": "2026-08-20T00:00:04+00:00",
                    "type": "approval.decided",
                    "request_id": audit_id,
                    "outcome": "approved",
                    "provider": "unknown",
                    "lane_sha256": "",
                    "receipt_sha256": "",
                    "actor": "historical-presentation",
                },
            ]
        )
        source.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        before = source.read_bytes()

        advanced = advance_with_authority(
            self.contract,
            transaction["transaction_id"],
            readers=readers,
        )

        self.assertEqual(advanced["stage"], "approval_decided")
        self.assertEqual(source.read_bytes(), before)

    def test_v3_prepared_history_can_only_append_idempotent_supersession(self) -> None:
        current = self.transaction("resume", suffix="v3-history")
        store = journal_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        sealed, prepared = rows

        core = dict(sealed["binding"])
        core.pop("task_epoch")
        core.pop("effect_attempt_id")
        core.pop("effect_subject_intent_revision")
        core["schema"] = journal_module.BINDING_SCHEMA_V3
        core["seal_id"] = journal_module._seal_id(
            {key: value for key, value in core.items() if key != "seal_id"},
            sealed["card"],
            sealed["request_receipt"],
        )
        sealed["seal_id"] = core["seal_id"]
        sealed["binding"] = core
        sealed["event_id"] = hashlib.sha256(
            journal_module._canonical(
                {key: value for key, value in sealed.items() if key != "event_id"}
            ).encode("utf-8")
        ).hexdigest()

        binding = dict(prepared["binding"])
        binding.pop("task_epoch")
        binding.pop("effect_attempt_id")
        binding.pop("effect_subject_intent_revision")
        binding["schema"] = journal_module.BINDING_SCHEMA_V3
        binding["seal_id"] = core["seal_id"]
        binding["seal_event_id"] = sealed["event_id"]
        old_tx_id = current["transaction_id"]
        tx_id = transaction_id(binding)
        prepared["transaction_id"] = tx_id
        prepared["binding"] = binding
        prepared["expected_seal_event_id"] = sealed["event_id"]
        prepared["previous_event_id"] = sealed["event_id"]
        prepared["event_id"] = hashlib.sha256(
            journal_module._canonical(
                {key: value for key, value in prepared.items() if key != "event_id"}
            ).encode("utf-8")
        ).hexdigest()
        self.assertNotEqual(tx_id, old_tx_id)

        payload = "".join(
            json.dumps(row, sort_keys=True) + "\n" for row in (sealed, prepared)
        ).encode("utf-8")
        store.write_bytes(payload)
        journal_module._atomic_write_json(
            head_anchor_path(self.contract),
            journal_module._head_value(self.contract, payload, [sealed, prepared]),
        )

        historical = load_projection(self.contract)["transactions"][tx_id]
        self.assertEqual(historical["binding"]["schema"], journal_module.BINDING_SCHEMA_V3)
        first = supersede(self.contract, tx_id, reason="obsolete v3 prepared transaction")
        second = supersede(self.contract, tx_id, reason="obsolete v3 prepared transaction")
        self.assertEqual(first["stage"], "superseded")
        self.assertEqual(second["stage"], "superseded")
        events = [json.loads(line)["event"] for line in store.read_text().splitlines()]
        self.assertEqual(events, ["sealed", "prepared", "superseded"])

    def test_v4_effect_history_accepts_one_unique_cross_revision_resolution(self) -> None:
        current = self.transaction("effect", suffix="v4-cross-revision")
        store = journal_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        sealed, prepared = rows

        core = dict(sealed["binding"])
        core.pop("effect_attempt_id")
        core.pop("effect_subject_intent_revision")
        core["schema"] = journal_module.BINDING_SCHEMA_V4
        core["seal_id"] = journal_module._seal_id(
            {key: value for key, value in core.items() if key != "seal_id"},
            sealed["card"],
            sealed["request_receipt"],
        )
        sealed["seal_id"] = core["seal_id"]
        sealed["binding"] = core
        sealed["event_id"] = journal_module._source_event_digest(sealed)

        binding = dict(prepared["binding"])
        binding.pop("effect_attempt_id")
        binding.pop("effect_subject_intent_revision")
        binding["schema"] = journal_module.BINDING_SCHEMA_V4
        binding["seal_id"] = core["seal_id"]
        binding["seal_event_id"] = sealed["event_id"]
        tx_id = transaction_id(binding)
        self.assertNotEqual(tx_id, current["transaction_id"])
        prepared["transaction_id"] = tx_id
        prepared["binding"] = binding
        prepared["expected_seal_event_id"] = sealed["event_id"]
        prepared["previous_event_id"] = sealed["event_id"]
        prepared["event_id"] = journal_module._source_event_digest(prepared)

        payload = "".join(
            json.dumps(row, sort_keys=True) + "\n" for row in (sealed, prepared)
        ).encode("utf-8")
        store.write_bytes(payload)
        journal_module._atomic_write_json(
            head_anchor_path(self.contract),
            journal_module._head_value(self.contract, payload, [sealed, prepared]),
        )
        historical = load_projection(self.contract)["transactions"][tx_id]
        self.assertEqual(
            historical["binding"]["schema"],
            journal_module.BINDING_SCHEMA_V4,
        )

        readers = self.authority_readers()
        approval_store = approval_authority_store_path(self.contract)
        approval_prefix = approval_store.read_bytes()
        self.advance_from_t12_fixture(readers, historical, "approval_decided")
        approval_store.write_bytes(approval_prefix)
        historical_attempt_id = "att-" + "3" * 24
        self.write_formal_native_postcondition(
            historical,
            effect_attempt_id=historical_attempt_id,
            effect_subject_intent_revision=3,
        )

        receipt = produce_effect_receipt(self.contract, tx_id)

        self.assertEqual(receipt, verify_effect_receipt(self.contract, tx_id))
        self.assertEqual(receipt["postcondition"]["attempt_id"], historical_attempt_id)
        self.assertEqual(receipt["postcondition"]["subject_intent_revision"], 3)

    def test_operation_specific_receipts_advance_one_stage_for_required_paths(self) -> None:
        cases = (
            ("proposal", "approve"),
            ("proposal", "reject"),
            ("resume", "resume"),
            ("effect", "retry_authorized"),
        )
        for index, (operation, decision) in enumerate(cases, 1):
            with self.subTest(operation=operation, decision=decision):
                transaction = self.transaction(operation, suffix=f"receipt-{index}")
                if transaction["binding"]["decision"] != decision:
                    binding = transaction["binding"]
                    self.assertEqual(operation, "proposal")
                    self.assertEqual(decision, "reject")
                    # A second sealed fixture supplies the proposal-reject machine choice.
                    target = f"proposal-target-reject-{index}"
                    card = self.choice_card(
                        "proposal", "reject", "reject-proposal", target
                    )
                    asked = ask_approval(
                        self.contract,
                        intent_id=binding["intent_id"],
                        intent_revision=binding["intent_revision"],
                        kind="proposal",
                        target=target,
                        provider="codex",
                        session_id=f"native-proposal-reject-{index}",
                        source="codex_permission_request",
                        card=card,
                        workspace=self.root,
                        route="human",
                    )
                    sealed = seal_binding(
                        self.contract,
                        operation="proposal",
                        decision="reject",
                        target=target,
                        action="reject-proposal",
                        intent_id=binding["intent_id"],
                        intent_revision=binding["intent_revision"],
                        workspace=self.root,
                        provider="codex",
                        session_id=f"native-proposal-reject-{index}",
                        source="codex_permission_request",
                        card=card,
                        request_id=asked["request_id"],
                        receipt=request_binding_receipt(
                            self.contract, asked["request_id"]
                        ),
                    )
                    transaction = prepare(self.contract, sealed)
                    decide_approval(
                        self.contract,
                        kind="proposal",
                        target=target,
                        outcome="approved",
                        provider="codex",
                        session_id=sealed["session_id"],
                        actor="permission-request:codex",
                        card=card,
                        workspace=self.root,
                        route="human",
                        source="codex_permission_request",
                    )
                results = self.advance_all_authority_stages(transaction)
                self.assertEqual(
                    [row["stage"] for row in results],
                    ["effect_applied", "contract_applied", "committed"],
                )
                self.assertTrue(all(row["advanced"] for row in results))
                self.assertFalse(results[0]["external_authority_verified"])
                self.assertFalse(results[1]["external_authority_verified"])
                self.assertTrue(results[2]["external_authority_verified"])
                self.assertEqual(
                    load_projection(self.contract)["transactions"][
                        transaction["transaction_id"]
                    ]["stage"],
                    "committed",
                )

    def test_cross_revision_effect_receipt_uses_sealed_attempt_subject(self) -> None:
        transaction = self.transaction(
            "effect",
            suffix="historical-subject",
            effect_subject_intent_revision=3,
        )
        binding = transaction["binding"]
        self.assertEqual(binding["intent_revision"], 7)
        self.assertEqual(binding["effect_subject_intent_revision"], 3)

        readers = self.authority_readers()
        approval_store = approval_authority_store_path(self.contract)
        approval_prefix = approval_store.read_bytes()
        self.advance_from_t12_fixture(readers, transaction, "approval_decided")
        approval_store.write_bytes(approval_prefix)
        self.write_formal_native_postcondition(transaction)

        effect_receipt = produce_effect_receipt(
            self.contract,
            transaction["transaction_id"],
        )
        self.assertEqual(
            effect_receipt,
            verify_effect_receipt(self.contract, transaction["transaction_id"]),
        )
        results = [
            advance_with_authority(
                self.contract, transaction["transaction_id"], readers=readers
            )
        ]
        produce_contract_receipt(self.contract, transaction["transaction_id"])
        results.append(
            advance_with_authority(
                self.contract, transaction["transaction_id"], readers=readers
            )
        )
        produce_external_head_receipt(self.contract, transaction["transaction_id"])
        results.append(
            advance_with_authority(
                self.contract, transaction["transaction_id"], readers=readers
            )
        )

        self.assertEqual(
            [result["stage"] for result in results],
            ["effect_applied", "contract_applied", "committed"],
        )
        self.assertEqual(
            effect_receipt["postcondition"]["attempt_id"],
            binding["effect_attempt_id"],
        )
        self.assertEqual(
            effect_receipt["postcondition"]["subject_intent_revision"],
            3,
        )

    def test_public_receipt_types_fixed_paths_and_idempotent_producers(self) -> None:
        transaction = self.transaction("resume", suffix="typed-producer")
        readers = self.authority_readers()
        approval_store = approval_authority_store_path(self.contract)
        approval_prefix = approval_store.read_bytes()
        self.advance_from_t12_fixture(readers, transaction, "approval_decided")
        approval_store.write_bytes(approval_prefix)
        self.write_formal_native_postcondition(transaction)
        tx_id = transaction["transaction_id"]

        effect = produce_effect_receipt(self.contract, tx_id)
        self.assertEqual(effect, produce_effect_receipt(self.contract, tx_id))
        self.assertEqual(effect, verify_effect_receipt(self.contract, tx_id))
        self.assertIs(get_type_hints(produce_effect_receipt)["return"], NativeEffectReceipt)
        self.assertEqual(len(effect_receipt_store_path(self.contract).read_text().splitlines()), 1)
        advance_with_authority(self.contract, tx_id, readers=readers)

        contract = produce_contract_receipt(self.contract, tx_id)
        self.assertEqual(contract, verify_contract_receipt(self.contract, tx_id))
        self.assertIs(
            get_type_hints(produce_contract_receipt)["return"],
            NativeContractReceipt,
        )
        self.assertEqual(len(contract_receipt_store_path(self.contract).read_text().splitlines()), 1)
        advance_with_authority(self.contract, tx_id, readers=readers)

        head = produce_external_head_receipt(self.contract, tx_id)
        self.assertEqual(head, verify_external_head_receipt(self.contract, tx_id))
        self.assertIs(
            get_type_hints(produce_external_head_receipt)["return"],
            NativeExternalHeadReceipt,
        )
        self.assertNotEqual(
            external_head_receipt_store_path(self.contract),
            head_anchor_path(self.contract),
        )
        committed = advance_with_authority(self.contract, tx_id, readers=readers)
        self.assertEqual(committed["stage"], "committed")
        self.assertEqual(
            head,
            verify_recorded_external_head_receipt(self.contract, tx_id),
        )
        replayed = advance_with_authority(self.contract, tx_id, readers=readers)
        self.assertEqual(replayed["status"], "already_advanced")
        self.assertFalse(replayed["advanced"])
        self.assertTrue(replayed["external_authority_verified"])

    def test_receipt_tamper_duplicate_truncation_and_old_generation_fail_closed(self) -> None:
        cases = ("tamper", "duplicate", "truncated", "old-generation")
        for index, case in enumerate(cases, 1):
            with self.subTest(case=case):
                transaction = self.transaction("resume", suffix=f"receipt-bad-{index}")
                readers = self.authority_readers()
                approval_store = approval_authority_store_path(self.contract)
                approval_prefix = approval_store.read_bytes()
                self.advance_from_t12_fixture(readers, transaction, "approval_decided")
                approval_store.write_bytes(approval_prefix)
                self.write_formal_native_postcondition(transaction)
                tx_id = transaction["transaction_id"]
                receipt_store = effect_receipt_store_path(self.contract)
                receipt_prefix = (
                    receipt_store.read_bytes() if receipt_store.is_file() else b""
                )
                produce_effect_receipt(self.contract, tx_id)
                store = receipt_store
                rows = [json.loads(line) for line in store.read_text().splitlines()]
                if case == "tamper":
                    rows[0]["receipt"]["operation"] = "proposal"
                    store.write_text(json.dumps(rows[0], sort_keys=True) + "\n")
                elif case == "duplicate":
                    duplicate = dict(rows[0], sequence=2, previous_event_id=rows[0]["event_id"])
                    duplicate["event_id"] = journal_module._source_event_digest(duplicate)
                    store.write_text(
                        "".join(json.dumps(row, sort_keys=True) + "\n" for row in (rows[0], duplicate))
                    )
                elif case == "truncated":
                    store.write_bytes(store.read_bytes()[:-1])
                else:
                    competing = self.transaction("intent", suffix=f"receipt-race-{index}")
                    supersede(
                        self.contract,
                        competing["transaction_id"],
                        reason="generation changed after receipt",
                    )
                accepted = self.journal_snapshot()
                result = advance_with_authority(self.contract, tx_id, readers=readers)
                self.assertEqual(result["status"], "pending")
                self.assertFalse(result["advanced"])
                self.assertEqual(self.journal_snapshot(), accepted)
                store.write_bytes(receipt_prefix)
                self.contract.write_text("{}\n", encoding="utf-8")

    def test_receipt_before_cas_crash_reuses_same_source_without_external_replay(self) -> None:
        transaction = self.transaction("effect", suffix="receipt-crash")
        readers = self.authority_readers()
        approval_store = approval_authority_store_path(self.contract)
        approval_prefix = approval_store.read_bytes()
        self.advance_from_t12_fixture(readers, transaction, "approval_decided")
        approval_store.write_bytes(approval_prefix)
        self.write_formal_native_postcondition(transaction)
        tx_id = transaction["transaction_id"]
        receipt = produce_effect_receipt(self.contract, tx_id)
        source_before = effect_authority_store_path(self.contract).read_bytes()
        receipt_before = effect_receipt_store_path(self.contract).read_bytes()
        with self.assertRaisesRegex(
            NativeDecisionAdvancementInterrupted, "after_effect"
        ):
            advance_with_authority(
                self.contract, tx_id, readers=readers, failpoint="after_effect"
            )
        self.assertEqual(
            load_projection(self.contract)["transactions"][tx_id]["stage"],
            "approval_decided",
        )
        self.assertEqual(produce_effect_receipt(self.contract, tx_id), receipt)
        recovered = advance_with_authority(self.contract, tx_id, readers=readers)
        self.assertEqual(recovered["stage"], "effect_applied")
        self.assertEqual(effect_authority_store_path(self.contract).read_bytes(), source_before)
        self.assertEqual(effect_receipt_store_path(self.contract).read_bytes(), receipt_before)

    def test_later_producer_reverifies_consumed_upstream_postcondition(self) -> None:
        transaction = self.transaction("resume", suffix="upstream-drift")
        readers = self.authority_readers()
        approval_store = approval_authority_store_path(self.contract)
        approval_prefix = approval_store.read_bytes()
        self.advance_from_t12_fixture(readers, transaction, "approval_decided")
        approval_store.write_bytes(approval_prefix)
        self.write_formal_native_postcondition(transaction)
        tx_id = transaction["transaction_id"]
        produce_effect_receipt(self.contract, tx_id)
        advanced = advance_with_authority(self.contract, tx_id, readers=readers)
        self.assertEqual(advanced["stage"], "effect_applied")

        document = json.loads(self.contract.read_text())
        document["resumed_lane"]["session_id"] = "substituted-session"
        self.contract.write_text(json.dumps(document, sort_keys=True) + "\n")
        accepted = self.journal_snapshot()
        with self.assertRaisesRegex(
            NativeDecisionJournalError, "postcondition|sealed lane"
        ):
            produce_contract_receipt(self.contract, tx_id)
        self.assertEqual(self.journal_snapshot(), accepted)
        self.assertFalse(contract_receipt_store_path(self.contract).is_file())

    def test_superseded_recovery_rechecks_recorded_decision_receipt(self) -> None:
        transaction = self.transaction("intent", suffix="superseded-receipt")
        supersede(
            self.contract,
            transaction["transaction_id"],
            reason="obsolete revision",
        )
        store = event_store_path(self.contract)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        rows[-1]["at"] = "2099-01-01T00:00:00+00:00"
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        noop = self.inert_step()
        with self.assertRaisesRegex(
            NativeDecisionJournalError, "decision receipt was substituted"
        ):
            recover_intent(
                self.contract,
                transaction["transaction_id"],
                effect=noop,
                contract=noop,
            )


if __name__ == "__main__":
    unittest.main()

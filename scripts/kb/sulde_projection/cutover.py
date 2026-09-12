"""Pure comparison gate between a frozen legacy cut and an empty supervisor."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from sulde_protocol import (
    ApprovalState,
    ContractState,
    EffectState,
    InterventionState,
    SupervisorState,
    TaskLifecycleState,
)
from sulde_execution import TaskEpochContext
from sulde_state_machine import GuardianState
from sulde_supervisor.codec import state_to_dict

from .models import LegacyControlCut, LegacyProjectionError


CUTOVER_BINDING_SCHEMA = "sulde-guardian-cutover-binding-v2"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CutoverAssessment:
    ready: bool
    cut_id: str
    binding_id: str
    blockers: tuple[str, ...]
    authority_transferred: bool = False


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def assess_cutover(
    cut: LegacyControlCut,
    target: GuardianState,
    *,
    expected_cut_id: str,
    expected_legacy_generation: str,
    expected_target_generation: str,
    task_context: TaskEpochContext | None = None,
) -> CutoverAssessment:
    """Return a data-only binding; this function never starts or authorizes a writer."""
    if type(cut) is not LegacyControlCut or type(target) is not GuardianState:
        raise LegacyProjectionError("cutover inputs are not typed")
    for label, value in (
        ("cut", expected_cut_id),
        ("legacy generation", expected_legacy_generation),
        ("target generation", expected_target_generation),
    ):
        if type(value) is not str or _HEX_64.fullmatch(value) is None:
            raise LegacyProjectionError(f"expected {label} digest is invalid")
    blockers = list(cut.projection.blockers)
    if cut.cut_id != expected_cut_id:
        blockers.append("legacy_cut_changed")
    if cut.projection.runtime_generation != expected_legacy_generation:
        blockers.append("legacy_generation_changed")
    if target.runtime_generation != expected_target_generation:
        blockers.append("target_generation_changed")
    if target.workspace_id != cut.projection.workspace_id:
        blockers.append("workspace_mismatch")
    if target.task_epoch != cut.projection.task_epoch:
        blockers.append("task_epoch_mismatch")
    if target.task_epoch_context_id:
        if type(task_context) is not TaskEpochContext:
            blockers.append("task_context_missing")
        else:
            if task_context.context_id != target.task_epoch_context_id:
                blockers.append("task_context_mismatch")
            if task_context.workspace_id != cut.projection.workspace_id:
                blockers.append("task_context_workspace_mismatch")
            if task_context.intent_id != cut.projection.intent_id:
                blockers.append("task_context_intent_mismatch")
            if task_context.intent_revision != cut.projection.intent_revision:
                blockers.append("task_context_revision_mismatch")
            if task_context.task_epoch != cut.projection.task_epoch:
                blockers.append("task_context_epoch_mismatch")
            if task_context.runtime_generation != expected_target_generation:
                blockers.append("task_context_generation_mismatch")
            if task_context.legacy_cut_id != cut.cut_id:
                blockers.append("task_context_cut_mismatch")
            if (
                task_context.policy_sha256
                != cut.projection.contract_material_digest
            ):
                blockers.append("task_context_policy_mismatch")
    elif task_context is not None:
        blockers.append("target_task_context_missing")
    expected_empty = (
        target.sequence == 0
        and not target.last_event_id
        and target.contract is ContractState.ACTIVE
        and target.task is TaskLifecycleState.NONE
        and target.approval is ApprovalState.NONE
        and target.effect is EffectState.NONE
        and target.intervention is InterventionState.NONE
        and target.supervisor is SupervisorState.STARTING
        and not target.approval_request_id
        and not target.effect_attempt_id
        and not target.intervention_id
        and not target.terminal_event_id
    )
    if not expected_empty:
        blockers.append("target_supervisor_not_empty")
    unique_blockers = tuple(dict.fromkeys(blockers))
    binding_id = ""
    if not unique_blockers:
        material = {
            "schema": CUTOVER_BINDING_SCHEMA,
            "legacy_cut_id": cut.cut_id,
            "legacy_generation": expected_legacy_generation,
            "target_generation": expected_target_generation,
            "target_state": state_to_dict(target),
            "authority_transferred": False,
        }
        binding_id = hashlib.sha256(
            _canonical(material).encode("utf-8")
        ).hexdigest()
    return CutoverAssessment(
        ready=not unique_blockers,
        cut_id=cut.cut_id,
        binding_id=binding_id,
        blockers=unique_blockers,
        authority_transferred=False,
    )

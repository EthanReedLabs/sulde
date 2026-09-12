"""Strict JSON codec for the reducer projection."""

from __future__ import annotations

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
from sulde_state_machine import GuardianState, initial_state

from .models import StoreCorruption


STATE_SCHEMA = "sulde-guardian-state-v1"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")


def state_to_dict(state: GuardianState) -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "workspace_id": state.workspace_id,
        "task_epoch": state.task_epoch,
        "runtime_generation": state.runtime_generation,
        "task_epoch_context_id": state.task_epoch_context_id,
        "sequence": state.sequence,
        "last_event_id": state.last_event_id,
        "contract": state.contract.value,
        "task": state.task.value,
        "approval": state.approval.value,
        "effect": state.effect.value,
        "intervention": state.intervention.value,
        "supervisor": state.supervisor.value,
        "approval_request_id": state.approval_request_id,
        "effect_attempt_id": state.effect_attempt_id,
        "intervention_id": state.intervention_id,
        "terminal_event_id": state.terminal_event_id,
    }


def state_to_json(state: GuardianState) -> str:
    return json.dumps(
        state_to_dict(state),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _bounded_id(value: Any, label: str, *, optional: bool = True) -> str:
    if type(value) is not str:
        raise StoreCorruption(f"projection {label} must be a string")
    if optional and value == "":
        return value
    if _SAFE_ID.fullmatch(value) is None:
        raise StoreCorruption(f"projection {label} is invalid")
    return value


def _event_id(value: Any, label: str, *, optional: bool = True) -> str:
    if type(value) is not str or (
        value != "" and _HEX_64.fullmatch(value) is None
    ):
        raise StoreCorruption(f"projection {label} is invalid")
    if not optional and not value:
        raise StoreCorruption(f"projection {label} is required")
    return value


def state_from_dict(value: Any) -> GuardianState:
    fields = {
        "schema",
        "workspace_id",
        "task_epoch",
        "runtime_generation",
        "task_epoch_context_id",
        "sequence",
        "last_event_id",
        "contract",
        "task",
        "approval",
        "effect",
        "intervention",
        "supervisor",
        "approval_request_id",
        "effect_attempt_id",
        "intervention_id",
        "terminal_event_id",
    }
    if type(value) is not dict or set(value) != fields:
        raise StoreCorruption("projection fields are invalid")
    if value.get("schema") != STATE_SCHEMA:
        raise StoreCorruption("projection schema is invalid")
    try:
        probe = initial_state(
            workspace_id=value["workspace_id"],
            task_epoch=value["task_epoch"],
            runtime_generation=value["runtime_generation"],
            task_epoch_context_id=value["task_epoch_context_id"],
        )
        contract = ContractState(value["contract"])
        task = TaskLifecycleState(value["task"])
        approval = ApprovalState(value["approval"])
        effect = EffectState(value["effect"])
        intervention = InterventionState(value["intervention"])
        supervisor = SupervisorState(value["supervisor"])
    except (KeyError, TypeError, ValueError) as error:
        raise StoreCorruption("projection typed state is invalid") from error
    sequence = value["sequence"]
    if type(sequence) is not int or type(sequence) is bool or sequence < 0:
        raise StoreCorruption("projection sequence is invalid")
    last_event_id = _event_id(value["last_event_id"], "last_event_id")
    if (sequence == 0) != (last_event_id == ""):
        raise StoreCorruption("projection sequence/head invariant failed")
    approval_request_id = _bounded_id(
        value["approval_request_id"], "approval_request_id"
    )
    effect_attempt_id = _bounded_id(
        value["effect_attempt_id"], "effect_attempt_id"
    )
    intervention_id = _bounded_id(value["intervention_id"], "intervention_id")
    terminal_event_id = _event_id(value["terminal_event_id"], "terminal_event_id")
    task_epoch_context_id = _event_id(
        value["task_epoch_context_id"], "task_epoch_context_id"
    )
    if (approval is ApprovalState.NONE) != (approval_request_id == ""):
        raise StoreCorruption("projection approval identity invariant failed")
    if (effect is EffectState.NONE) != (effect_attempt_id == ""):
        raise StoreCorruption("projection effect identity invariant failed")
    if (intervention is InterventionState.NONE) != (intervention_id == ""):
        raise StoreCorruption("projection intervention identity invariant failed")
    terminal = task in {
        TaskLifecycleState.SUCCEEDED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.INCONCLUSIVE,
    }
    if terminal != bool(terminal_event_id):
        raise StoreCorruption("projection terminal identity invariant failed")
    return GuardianState(
        workspace_id=probe.workspace_id,
        task_epoch=probe.task_epoch,
        runtime_generation=probe.runtime_generation,
        task_epoch_context_id=task_epoch_context_id,
        sequence=sequence,
        last_event_id=last_event_id,
        contract=contract,
        task=task,
        approval=approval,
        effect=effect,
        intervention=intervention,
        supervisor=supervisor,
        approval_request_id=approval_request_id,
        effect_attempt_id=effect_attempt_id,
        intervention_id=intervention_id,
        terminal_event_id=terminal_event_id,
    )


def state_from_json(value: str) -> GuardianState:
    if type(value) is not str:
        raise StoreCorruption("projection JSON must be text")
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise StoreCorruption("projection JSON is invalid") from error
    state = state_from_dict(payload)
    if state_to_json(state) != value:
        raise StoreCorruption("projection JSON is not canonical")
    return state

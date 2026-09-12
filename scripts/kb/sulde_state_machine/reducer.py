"""Deterministic, side-effect-free Guardian reducer.

This module deliberately imports no filesystem, subprocess, host, Hook, or CLI
adapter.  A writer may persist the returned state, but the reducer itself can
only validate and transform immutable protocol values.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from sulde_protocol import (
    ApprovalState,
    ContractState,
    EffectState,
    EventCorrelation,
    EventEnvelope,
    EventType,
    InterventionState,
    Provider,
    SupervisorState,
    TaskLifecycleState,
)


class TransitionError(ValueError):
    """An event violates the authoritative state machine."""


@dataclass(frozen=True)
class GuardianState:
    workspace_id: str
    task_epoch: str
    runtime_generation: str
    task_epoch_context_id: str = ""
    sequence: int = 0
    last_event_id: str = ""
    contract: ContractState = ContractState.ACTIVE
    task: TaskLifecycleState = TaskLifecycleState.NONE
    approval: ApprovalState = ApprovalState.NONE
    effect: EffectState = EffectState.NONE
    intervention: InterventionState = InterventionState.NONE
    supervisor: SupervisorState = SupervisorState.STARTING
    approval_request_id: str = ""
    effect_attempt_id: str = ""
    intervention_id: str = ""
    terminal_event_id: str = ""


@dataclass(frozen=True)
class TransitionResult:
    state: GuardianState
    event_id: str
    changed: bool


def initial_state(
    *,
    workspace_id: str,
    task_epoch: str,
    runtime_generation: str,
    task_epoch_context_id: str = "",
) -> GuardianState:
    # Reuse the protocol validator without manufacturing authority.
    probe = EventEnvelope.build(
        sequence=1,
        previous_event_id="",
        workspace_id=workspace_id,
        runtime_generation=runtime_generation,
        event_type=EventType.INTENT_ACTIVATED,
        provider=Provider.SYSTEM,
        actor="state-validator",
        occurred_at="1970-01-01T00:00:00Z",
        correlation=EventCorrelation(
            intent_id="state-validator",
            intent_revision=1,
            task_epoch=task_epoch,
            task_epoch_context_id=task_epoch_context_id,
        ),
    )
    return GuardianState(
        workspace_id=probe.workspace_id,
        task_epoch=probe.correlation.task_epoch,
        runtime_generation=probe.runtime_generation,
        task_epoch_context_id=probe.correlation.task_epoch_context_id,
    )


def _next(state: GuardianState, event: EventEnvelope, **changes: object) -> GuardianState:
    return replace(
        state,
        sequence=event.sequence,
        last_event_id=event.event_id,
        **changes,
    )


def _require_transition(current: object, allowed: set[object], label: str) -> None:
    if current not in allowed:
        rendered = getattr(current, "value", str(current))
        raise TransitionError(f"{label} cannot transition from {rendered}")


def _transition_intent(state: GuardianState, event: EventEnvelope) -> GuardianState:
    if event.event_type is EventType.INTENT_ACTIVATED:
        _require_transition(state.contract, {ContractState.ACTIVE}, "intent activation")
        return _next(state, event, contract=ContractState.ACTIVE)
    if event.event_type is EventType.INTENT_PAUSED:
        _require_transition(state.contract, {ContractState.ACTIVE}, "intent pause")
        return _next(state, event, contract=ContractState.PAUSED)
    if event.event_type is EventType.INTENT_RESUMED:
        _require_transition(state.contract, {ContractState.PAUSED}, "intent resume")
        return _next(state, event, contract=ContractState.ACTIVE)
    if event.event_type is EventType.INTENT_CLOSED:
        _require_transition(
            state.contract,
            {ContractState.ACTIVE, ContractState.PAUSED},
            "intent close",
        )
        return _next(state, event, contract=ContractState.CLOSED)
    raise TransitionError("unsupported intent event")


_TASK_TRANSITIONS = {
    EventType.TASK_CREATED: ({TaskLifecycleState.NONE}, TaskLifecycleState.CREATED),
    EventType.TASK_BOUND: ({TaskLifecycleState.CREATED}, TaskLifecycleState.BOUND),
    EventType.TASK_STARTED: (
        {TaskLifecycleState.BOUND, TaskLifecycleState.AWAITING_HUMAN},
        TaskLifecycleState.RUNNING,
    ),
    EventType.TASK_AWAITING_HUMAN: (
        {TaskLifecycleState.RUNNING},
        TaskLifecycleState.AWAITING_HUMAN,
    ),
    EventType.TASK_VERIFYING: (
        {TaskLifecycleState.RUNNING, TaskLifecycleState.AWAITING_HUMAN},
        TaskLifecycleState.VERIFYING,
    ),
    EventType.TASK_SUCCEEDED: (
        {TaskLifecycleState.RUNNING, TaskLifecycleState.VERIFYING},
        TaskLifecycleState.SUCCEEDED,
    ),
    EventType.TASK_FAILED: (
        {
            TaskLifecycleState.CREATED,
            TaskLifecycleState.BOUND,
            TaskLifecycleState.RUNNING,
            TaskLifecycleState.AWAITING_HUMAN,
            TaskLifecycleState.VERIFYING,
        },
        TaskLifecycleState.FAILED,
    ),
    EventType.TASK_INCONCLUSIVE: (
        {
            TaskLifecycleState.CREATED,
            TaskLifecycleState.BOUND,
            TaskLifecycleState.RUNNING,
            TaskLifecycleState.AWAITING_HUMAN,
            TaskLifecycleState.VERIFYING,
        },
        TaskLifecycleState.INCONCLUSIVE,
    ),
}


def _transition_task(state: GuardianState, event: EventEnvelope) -> GuardianState:
    allowed, target = _TASK_TRANSITIONS[event.event_type]
    _require_transition(state.task, allowed, event.event_type.value)
    terminal = target in {
        TaskLifecycleState.SUCCEEDED,
        TaskLifecycleState.FAILED,
        TaskLifecycleState.INCONCLUSIVE,
    }
    if terminal and state.terminal_event_id:
        raise TransitionError("task already has one terminal result")
    if target is TaskLifecycleState.SUCCEEDED and state.effect not in {
        EffectState.NONE,
        EffectState.VERIFIED,
    }:
        raise TransitionError("task cannot succeed while an effect is unverified")
    return _next(
        state,
        event,
        task=target,
        terminal_event_id=event.event_id if terminal else state.terminal_event_id,
    )


def _transition_approval(state: GuardianState, event: EventEnvelope) -> GuardianState:
    request_id = event.correlation.approval_request_id
    if not request_id:
        raise TransitionError("approval event requires approval_request_id")
    if event.event_type is EventType.APPROVAL_ASKED:
        _require_transition(
            state.approval,
            {ApprovalState.NONE, ApprovalState.DECIDED, ApprovalState.EXPIRED},
            "approval ask",
        )
        return _next(
            state,
            event,
            approval=ApprovalState.ASKED,
            approval_request_id=request_id,
        )
    if request_id != state.approval_request_id:
        raise TransitionError("approval event targets another request")
    if event.event_type is EventType.APPROVAL_REASSESSMENT_DUE:
        _require_transition(state.approval, {ApprovalState.ASKED}, "approval reassess")
        return _next(state, event, approval=ApprovalState.REASSESSMENT_DUE)
    if event.event_type is EventType.APPROVAL_DECIDED:
        _require_transition(
            state.approval,
            {ApprovalState.ASKED, ApprovalState.REASSESSMENT_DUE},
            "approval decision",
        )
        return _next(state, event, approval=ApprovalState.DECIDED)
    if event.event_type is EventType.APPROVAL_EXPIRED:
        _require_transition(
            state.approval,
            {ApprovalState.ASKED, ApprovalState.REASSESSMENT_DUE},
            "approval expiration",
        )
        return _next(state, event, approval=ApprovalState.EXPIRED)
    raise TransitionError("unsupported approval event")


_EFFECT_TRANSITIONS = {
    EventType.EFFECT_PREPARED: (
        {EffectState.NONE, EffectState.VERIFIED, EffectState.ABORTED},
        EffectState.PREPARED,
    ),
    EventType.EFFECT_DISPATCHED: ({EffectState.PREPARED}, EffectState.DISPATCHED),
    EventType.EFFECT_VERIFYING: (
        {EffectState.DISPATCHED},
        EffectState.VERIFYING,
    ),
    EventType.EFFECT_VERIFIED: (
        {EffectState.DISPATCHED, EffectState.VERIFYING},
        EffectState.VERIFIED,
    ),
    EventType.EFFECT_UNKNOWN: (
        {EffectState.DISPATCHED, EffectState.VERIFYING},
        EffectState.UNKNOWN,
    ),
    EventType.EFFECT_ABORTED: ({EffectState.UNKNOWN}, EffectState.ABORTED),
}


def _transition_effect(state: GuardianState, event: EventEnvelope) -> GuardianState:
    attempt_id = event.correlation.attempt_id
    if not attempt_id:
        raise TransitionError("effect event requires attempt_id")
    allowed, target = _EFFECT_TRANSITIONS[event.event_type]
    _require_transition(state.effect, allowed, event.event_type.value)
    if event.event_type is not EventType.EFFECT_PREPARED and (
        attempt_id != state.effect_attempt_id
    ):
        raise TransitionError("effect event targets another attempt")
    return _next(
        state,
        event,
        effect=target,
        effect_attempt_id=attempt_id,
        intervention=(
            InterventionState.NONE
            if event.event_type is EventType.EFFECT_PREPARED
            else state.intervention
        ),
        intervention_id=(
            "" if event.event_type is EventType.EFFECT_PREPARED else state.intervention_id
        ),
    )


def _transition_intervention(
    state: GuardianState, event: EventEnvelope
) -> GuardianState:
    intervention_id = event.correlation.intervention_id
    attempt_id = event.correlation.attempt_id
    if not intervention_id or attempt_id != state.effect_attempt_id:
        raise TransitionError("intervention must bind the current effect attempt")
    if event.event_type is EventType.INTERVENTION_OPENED:
        if state.effect is not EffectState.UNKNOWN:
            raise TransitionError("intervention opens only for an unknown effect")
        _require_transition(
            state.intervention,
            {InterventionState.NONE, InterventionState.RESOLVED},
            "intervention open",
        )
        return _next(
            state,
            event,
            intervention=InterventionState.OPEN,
            intervention_id=intervention_id,
        )
    if intervention_id != state.intervention_id:
        raise TransitionError("intervention event targets another intervention")
    if event.event_type is EventType.INTERVENTION_ACKNOWLEDGED:
        _require_transition(
            state.intervention,
            {InterventionState.OPEN},
            "intervention acknowledge",
        )
        return _next(state, event, intervention=InterventionState.ACKNOWLEDGED)
    if event.event_type is EventType.INTERVENTION_RESOLVED:
        _require_transition(
            state.intervention,
            {InterventionState.OPEN, InterventionState.ACKNOWLEDGED},
            "intervention resolve",
        )
        return _next(state, event, intervention=InterventionState.RESOLVED)
    raise TransitionError("unsupported intervention event")


def _transition_supervisor(state: GuardianState, event: EventEnvelope) -> GuardianState:
    if event.event_type is EventType.SUPERVISOR_GENERATION_ACTIVATED:
        _require_transition(
            state.supervisor,
            {SupervisorState.STARTING, SupervisorState.STOPPED},
            "supervisor generation activation",
        )
        return _next(
            state,
            event,
            runtime_generation=event.runtime_generation,
            supervisor=SupervisorState.STARTING,
        )
    targets = {
        EventType.SUPERVISOR_READY: (
            {SupervisorState.STARTING, SupervisorState.DEGRADED},
            SupervisorState.READY,
        ),
        EventType.SUPERVISOR_DEGRADED: (
            {SupervisorState.STARTING, SupervisorState.READY},
            SupervisorState.DEGRADED,
        ),
        EventType.SUPERVISOR_BLOCKED: (
            {
                SupervisorState.STARTING,
                SupervisorState.READY,
                SupervisorState.DEGRADED,
            },
            SupervisorState.BLOCKED,
        ),
        EventType.SUPERVISOR_STOPPED: (
            {
                SupervisorState.STARTING,
                SupervisorState.READY,
                SupervisorState.DEGRADED,
                SupervisorState.BLOCKED,
            },
            SupervisorState.STOPPED,
        ),
    }
    allowed, target = targets[event.event_type]
    _require_transition(state.supervisor, allowed, event.event_type.value)
    return _next(state, event, supervisor=target)


_HANDLERS = {
    "intent": _transition_intent,
    "task": _transition_task,
    "approval": _transition_approval,
    "effect": _transition_effect,
    "intervention": _transition_intervention,
    "supervisor": _transition_supervisor,
}


def transition(state: GuardianState, event: EventEnvelope) -> TransitionResult:
    if event.workspace_id != state.workspace_id:
        raise TransitionError("event belongs to another workspace")
    if event.event_id == state.last_event_id:
        return TransitionResult(state=state, event_id=event.event_id, changed=False)
    if event.sequence != state.sequence + 1:
        raise TransitionError("event sequence is not contiguous")
    if event.previous_event_id != state.last_event_id:
        raise TransitionError("event chain does not extend the current head")
    if event.correlation.task_epoch != state.task_epoch:
        raise TransitionError("event belongs to another task epoch")
    if event.correlation.task_epoch_context_id != state.task_epoch_context_id:
        raise TransitionError("event belongs to another task epoch context")
    if (
        state.task_epoch_context_id
        and event.event_type is EventType.SUPERVISOR_GENERATION_ACTIVATED
        and event.runtime_generation != state.runtime_generation
    ):
        raise TransitionError(
            "runtime generation changes require a new task epoch context"
        )
    if (
        event.event_type is not EventType.SUPERVISOR_GENERATION_ACTIVATED
        and event.runtime_generation != state.runtime_generation
    ):
        raise TransitionError("event belongs to another runtime generation")
    handler = _HANDLERS[event.domain.value]
    updated = handler(state, event)
    return TransitionResult(state=updated, event_id=event.event_id, changed=True)


def replay(initial: GuardianState, events: Iterable[EventEnvelope]) -> GuardianState:
    state = initial
    for event in events:
        state = transition(state, event).state
    return state

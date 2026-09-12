#!/usr/bin/env python3
"""Deterministic, bounded RecoverySupervisor policy engine.

All host facts enter as typed observations.  The supervisor can derive local
recommendations, seal a narrowly bounded local authorization, and record a
synthetic adapter receipt.  None of those stages creates human, provider,
verifier, path, merge, Git, signal, deletion, or external-effect authority.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import combinations
import math
from pathlib import PurePosixPath
import re
from typing import Any, Callable

from supervisor_state import (
    SupervisorState,
    SupervisorStateError,
    canonical_digest,
    exact_object,
    exact_text,
    require_plain_json,
)


PROTOCOL_SCHEMA = "sulde-recovery-supervisor-v1"
ACTOR_SCHEMA = "sulde-recovery-supervisor-actor-v1"
PROCESS_SCHEMA = "sulde-process-identity-v1"
BINDING_SCHEMA = "sulde-recovery-binding-v1"
PROGRESS_SCHEMA = "sulde-progress-cursor-v1"
RESOURCE_SCHEMA = "sulde-resource-identity-v1"
SCHEDULER_SCHEMA = "sulde-scheduler-observation-v1"
HEARTBEAT_SCHEMA = "sulde-supervisor-heartbeat-v1"
PROCESS_PROBE_SCHEMA = "sulde-process-probe-v1"
PROCESS_RECEIPT_SCHEMA = "sulde-process-observation-receipt-v1"
LEASE_SCHEMA = "sulde-lock-lease-v1"
EXIT_SCHEMA = "sulde-process-terminal-v1"
CANCELLATION_SCHEMA = "sulde-cancellation-v1"
BUSINESS_SCHEMA = "sulde-business-terminal-v1"
VERIFIER_SCHEMA = "sulde-supervisor-verifier-receipt-v1"
SCAN_SCHEMA = "sulde-supervisor-scan-v1"
STATUS_CARD_SCHEMA = "sulde-supervisor-status-card-v1"
RECOMMENDATION_SCHEMA = "sulde-recovery-recommendation-v1"
AUTHORIZATION_SCHEMA = "sulde-local-mechanical-authorization-v1"
START_SCHEMA = "sulde-local-intervention-start-v1"
ADAPTER_RESULT_SCHEMA = "sulde-local-adapter-result-v1"
INTERVENTION_PREPARE_SCHEMA = "sulde-local-intervention-prepare-v1"
INTERVENTION_VERIFY_SCHEMA = "sulde-local-intervention-verifier-receipt-v1"
INTERVENTION_RECEIPT_SCHEMA = "sulde-local-intervention-receipt-v1"
EXHAUSTED_SCHEMA = "sulde-restart-budget-exhausted-v1"
PROJECTION_SCHEMA = "sulde-recovery-supervisor-projection-v1"
RECEIPT_FIELDS = frozenset({"supervisor_received_wall", "supervisor_received_mono"})
PROCESS_RECEIPT_FIELDS = frozenset({"receipt_schema", "receipt_id"})

SILENT_CARD_SECONDS = 5.0
PROGRESS_WINDOW_SECONDS = 30.0
RECLAIM_DEADLINE_SECONDS = 10.0
_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
_EPOCH = re.compile(r"^[0-9a-f]{24}$")

PROCESS_FIELDS = frozenset({"schema", "pid", "start_token"})
BINDING_FIELDS = frozenset(
    {
        "schema", "provider", "task_epoch", "generation", "allowed_paths",
        "command_identity", "verifier_identity",
    }
)
ACTOR_FIELDS = frozenset(
    {
        "schema", "actor_id", "task_id", "worker_id", "provider",
        "task_epoch", "generation", "lane", "allowed_paths",
        "command_identity", "process_identity", "retry_budget",
        "verifier_identity", "probe_authority", "registered_wall", "registered_mono",
    }
)
HEARTBEAT_FIELDS = frozenset(
    {
        "schema", "callback_id", "heartbeat_kind", "actor_id", "worker_id", "binding",
        "process_identity", "progress_cursor", "resources",
        "scheduler_state", "observed_wall", "observed_mono",
    }
)
PROBE_FIELDS = frozenset(
    {
        "schema", "probe_id", "actor_id", "probe_authority",
        "source_event_identity", "subject_process_identity",
        "status", "observed_process_identity", "observed_wall",
        "observed_mono",
    }
)
LEASE_FIELDS = frozenset(
    {
        "schema", "lease_id", "lock", "owner_actor_id",
        "owner_process_identity", "lease_epoch", "expires_wall",
        "observed_wall", "observed_mono",
    }
)
EXIT_FIELDS = frozenset(
    {
        "schema", "callback_id", "actor_id", "binding", "process_identity",
        "status", "exit_code", "observed_wall", "observed_mono",
    }
)
CANCEL_FIELDS = frozenset(
    {
        "schema", "callback_id", "actor_id", "binding", "reason",
        "observed_wall", "observed_mono",
    }
)
BUSINESS_FIELDS = frozenset(
    {
        "schema", "callback_id", "actor_id", "binding", "status",
        "verifier_receipt", "result", "observed_wall", "observed_mono",
    }
)
VERIFIER_FIELDS = frozenset(
    {
        "schema", "receipt_id", "business_callback_id", "actor_id",
        "provider", "task_epoch", "generation", "verifier_identity",
        "status", "evidence",
    }
)
ADAPTER_RESULT_FIELDS = frozenset({
    "schema", "intervention_id", "effect_id", "adapter_identity",
    "status", "result",
})
INTERVENTION_VERIFY_FIELDS = frozenset({
    "schema", "receipt_id", "verifier_identity", "intervention_id",
    "adapter_identity", "effect_id", "subject_identity",
    "world_state_digest", "result_identity", "status", "evidence",
})


class RecoverySupervisorError(SupervisorStateError):
    """An input or transition is outside the closed recovery protocol."""


def _number(value: Any, name: str) -> float:
    if type(value) not in {int, float} or type(value) is bool:
        raise RecoverySupervisorError(f"{name} must be an exact finite number")
    selected = float(value)
    if not math.isfinite(selected) or selected < 0:
        raise RecoverySupervisorError(f"{name} must be finite and non-negative")
    return selected


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise RecoverySupervisorError(f"{name} must be an integer >= {minimum}")
    return value


def _sha(value: Any, name: str) -> str:
    selected = exact_text(value, name=name)
    if _SHA.fullmatch(selected) is None:
        raise RecoverySupervisorError(f"{name} must be a canonical sha256 identity")
    return selected


def _time_fields(value: dict[str, Any], name: str) -> None:
    _number(value["observed_wall"], f"{name}.observed_wall")
    _number(value["observed_mono"], f"{name}.observed_mono")


def validate_process(value: Any, name: str = "process_identity") -> dict[str, Any]:
    selected = exact_object(value, name=name, fields=PROCESS_FIELDS)
    if selected["schema"] != PROCESS_SCHEMA:
        raise RecoverySupervisorError(f"{name}.schema is invalid")
    _integer(selected["pid"], f"{name}.pid", minimum=1)
    _sha(selected["start_token"], f"{name}.start_token")
    return deepcopy(selected)


def _paths(value: Any, name: str) -> list[str]:
    require_plain_json(value, name=name)
    if type(value) is not list:
        raise RecoverySupervisorError(f"{name} must be an exact list")
    selected: list[str] = []
    for index, item in enumerate(value):
        path = exact_text(item, name=f"{name}[{index}]")
        parsed = PurePosixPath(path)
        if parsed.is_absolute() or path != parsed.as_posix() or ".." in parsed.parts:
            raise RecoverySupervisorError(f"{name}[{index}] is not canonical relative")
        selected.append(path)
    if not selected or selected != sorted(set(selected)):
        raise RecoverySupervisorError(f"{name} must be non-empty, unique, and sorted")
    return selected


def validate_binding(value: Any, name: str = "binding") -> dict[str, Any]:
    selected = exact_object(value, name=name, fields=BINDING_FIELDS)
    if selected["schema"] != BINDING_SCHEMA:
        raise RecoverySupervisorError(f"{name}.schema is invalid")
    exact_text(selected["provider"], name=f"{name}.provider")
    if type(selected["task_epoch"]) is not str or _EPOCH.fullmatch(selected["task_epoch"]) is None:
        raise RecoverySupervisorError(f"{name}.task_epoch must be 24 lowercase hex")
    _integer(selected["generation"], f"{name}.generation")
    _paths(selected["allowed_paths"], f"{name}.allowed_paths")
    _sha(selected["command_identity"], f"{name}.command_identity")
    _sha(selected["verifier_identity"], f"{name}.verifier_identity")
    return deepcopy(selected)


def binding_from_actor(actor: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": BINDING_SCHEMA,
        "provider": actor["provider"],
        "task_epoch": actor["task_epoch"],
        "generation": actor["generation"],
        "allowed_paths": deepcopy(actor["allowed_paths"]),
        "command_identity": actor["command_identity"],
        "verifier_identity": actor["verifier_identity"],
    }


def validate_resource(value: Any, name: str = "resource") -> dict[str, Any]:
    fields = frozenset({"schema", "kind", "canonical_id", "ownership_token"})
    selected = exact_object(value, name=name, fields=fields)
    if selected["schema"] != RESOURCE_SCHEMA:
        raise RecoverySupervisorError(f"{name}.schema is invalid")
    exact_text(selected["kind"], name=f"{name}.kind")
    exact_text(selected["canonical_id"], name=f"{name}.canonical_id")
    _sha(selected["ownership_token"], f"{name}.ownership_token")
    return deepcopy(selected)


def _resource_key(resource: dict[str, Any]) -> str:
    return f"{resource['kind']}:{resource['canonical_id']}"


def validate_progress(value: Any, name: str = "progress_cursor") -> dict[str, Any]:
    fields = frozenset({"schema", "sequence", "state_identity"})
    selected = exact_object(value, name=name, fields=fields)
    if selected["schema"] != PROGRESS_SCHEMA:
        raise RecoverySupervisorError(f"{name}.schema is invalid")
    _integer(selected["sequence"], f"{name}.sequence")
    _sha(selected["state_identity"], f"{name}.state_identity")
    return deepcopy(selected)


def validate_scheduler(value: Any, name: str = "scheduler_state") -> dict[str, Any]:
    fields = frozenset({"schema", "status", "reason"})
    selected = exact_object(value, name=name, fields=fields)
    if selected["schema"] != SCHEDULER_SCHEMA:
        raise RecoverySupervisorError(f"{name}.schema is invalid")
    if selected["status"] not in {"healthy", "degraded", "unknown", "paused"}:
        raise RecoverySupervisorError(f"{name}.status is invalid")
    if selected["reason"] is not None:
        exact_text(selected["reason"], name=f"{name}.reason")
    return deepcopy(selected)


def validate_actor(value: Any) -> dict[str, Any]:
    actor = exact_object(value, name="actor", fields=ACTOR_FIELDS)
    if actor["schema"] != ACTOR_SCHEMA:
        raise RecoverySupervisorError("actor.schema is invalid")
    for field in ("actor_id", "task_id", "worker_id", "provider"):
        exact_text(actor[field], name=f"actor.{field}")
    if type(actor["task_epoch"]) is not str or _EPOCH.fullmatch(actor["task_epoch"]) is None:
        raise RecoverySupervisorError("actor.task_epoch must be 24 lowercase hex")
    _integer(actor["generation"], "actor.generation")
    lane = exact_text(actor["lane"], name="actor.lane")
    if not lane.startswith("task:") or lane in {"task:workspace", "task:global"}:
        raise RecoverySupervisorError("actor.lane must be a task-scoped lane")
    _paths(actor["allowed_paths"], "actor.allowed_paths")
    _sha(actor["command_identity"], "actor.command_identity")
    _sha(actor["verifier_identity"], "actor.verifier_identity")
    _sha(actor["probe_authority"], "actor.probe_authority")
    validate_process(actor["process_identity"], "actor.process_identity")
    retry = exact_object(
        actor["retry_budget"], name="actor.retry_budget",
        fields=frozenset({"max_attempts", "backoff_seconds"}),
    )
    maximum = _integer(retry["max_attempts"], "retry_budget.max_attempts", minimum=1)
    if maximum > 10 or type(retry["backoff_seconds"]) is not list:
        raise RecoverySupervisorError("retry budget is outside the closed bounds")
    if len(retry["backoff_seconds"]) != maximum:
        raise RecoverySupervisorError("retry backoff must bind every allowed attempt")
    previous = -1.0
    for index, delay in enumerate(retry["backoff_seconds"]):
        selected = _number(delay, f"retry_budget.backoff_seconds[{index}]")
        if selected < previous:
            raise RecoverySupervisorError("retry backoff must be deterministic nondecreasing")
        previous = selected
    _number(actor["registered_wall"], "actor.registered_wall")
    _number(actor["registered_mono"], "actor.registered_mono")
    return deepcopy(actor)


def validate_heartbeat(value: Any) -> dict[str, Any]:
    item = exact_object(value, name="heartbeat", fields=HEARTBEAT_FIELDS)
    if item["schema"] != HEARTBEAT_SCHEMA:
        raise RecoverySupervisorError("heartbeat.schema is invalid")
    for field in ("callback_id", "actor_id", "worker_id"):
        exact_text(item[field], name=f"heartbeat.{field}")
    if item["heartbeat_kind"] not in {"task", "worker"}:
        raise RecoverySupervisorError("heartbeat.heartbeat_kind is invalid")
    validate_binding(item["binding"], "heartbeat.binding")
    validate_process(item["process_identity"], "heartbeat.process_identity")
    validate_progress(item["progress_cursor"])
    if type(item["resources"]) is not list:
        raise RecoverySupervisorError("heartbeat.resources must be an exact list")
    resources = [validate_resource(resource, f"heartbeat.resources[{index}]")
                 for index, resource in enumerate(item["resources"])]
    keys = [_resource_key(resource) for resource in resources]
    if keys != sorted(set(keys)):
        raise RecoverySupervisorError("heartbeat.resources must be unique and sorted")
    validate_scheduler(item["scheduler_state"])
    _time_fields(item, "heartbeat")
    return deepcopy(item)


def validate_probe(value: Any) -> dict[str, Any]:
    item = exact_object(value, name="process_probe", fields=PROBE_FIELDS)
    if item["schema"] != PROCESS_PROBE_SCHEMA:
        raise RecoverySupervisorError("process_probe.schema is invalid")
    for field in ("probe_id", "actor_id"):
        exact_text(item[field], name=f"process_probe.{field}")
    _sha(item["probe_authority"], "process_probe.probe_authority")
    _sha(item["source_event_identity"], "process_probe.source_event_identity")
    subject = validate_process(item["subject_process_identity"], "probe.subject")
    status = item["status"]
    if status not in {"alive", "dead", "unknown", "access_denied", "stale_identity"}:
        raise RecoverySupervisorError("process_probe.status is invalid")
    observed = item["observed_process_identity"]
    if observed is not None:
        observed = validate_process(observed, "probe.observed_process_identity")
    if status == "dead" and observed is not None:
        raise RecoverySupervisorError("authoritative dead probe cannot observe a process")
    if status == "alive" and observed != subject:
        raise RecoverySupervisorError("alive probe must match the full process identity")
    if status == "stale_identity" and (observed is None or observed == subject):
        raise RecoverySupervisorError("stale identity probe requires a different full identity")
    _time_fields(item, "process_probe")
    return deepcopy(item)


def _with_receipt(payload: dict[str, Any], wall: float, mono: float) -> dict[str, Any]:
    return {
        **deepcopy(payload),
        "supervisor_received_wall": wall,
        "supervisor_received_mono": mono,
    }


def _without_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    stripped = RECEIPT_FIELDS
    if payload.get("receipt_schema") == PROCESS_RECEIPT_SCHEMA:
        stripped |= PROCESS_RECEIPT_FIELDS
    return {key: deepcopy(value) for key, value in payload.items()
            if key not in stripped}


def _validate_received(
    payload: Any, validator: Callable[[Any], dict[str, Any]], name: str,
) -> dict[str, Any]:
    selected = exact_object(payload, name=name)
    if not RECEIPT_FIELDS.issubset(selected):
        raise RecoverySupervisorError(f"{name} lacks supervisor receipt time")
    _number(selected["supervisor_received_wall"], f"{name}.supervisor_received_wall")
    _number(selected["supervisor_received_mono"], f"{name}.supervisor_received_mono")
    validator(_without_receipt(selected))
    return deepcopy(selected)


def _source_clock_reason(payload: dict[str, Any]) -> str | None:
    source_wall = float(payload.get("observed_wall", payload.get("registered_wall", 0.0)))
    source_mono = float(payload.get("observed_mono", payload.get("registered_mono", 0.0)))
    receipt_wall = float(payload["supervisor_received_wall"])
    receipt_mono = float(payload["supervisor_received_mono"])
    if source_wall > receipt_wall or source_mono > receipt_mono:
        return "future_source_clock"
    wall_age = receipt_wall - source_wall
    mono_age = receipt_mono - source_mono
    if abs(wall_age - mono_age) > 0.001:
        return "impossible_source_clock"
    return None


def validate_lease(value: Any) -> dict[str, Any]:
    item = exact_object(value, name="lock_lease", fields=LEASE_FIELDS)
    if item["schema"] != LEASE_SCHEMA:
        raise RecoverySupervisorError("lock_lease.schema is invalid")
    exact_text(item["lease_id"], name="lock_lease.lease_id")
    validate_resource(item["lock"], "lock_lease.lock")
    exact_text(item["owner_actor_id"], name="lock_lease.owner_actor_id")
    validate_process(item["owner_process_identity"], "lock_lease.owner_process_identity")
    _integer(item["lease_epoch"], "lock_lease.lease_epoch")
    _number(item["expires_wall"], "lock_lease.expires_wall")
    _time_fields(item, "lock_lease")
    return deepcopy(item)


def validate_exit(value: Any) -> dict[str, Any]:
    item = exact_object(value, name="process_terminal", fields=EXIT_FIELDS)
    if item["schema"] != EXIT_SCHEMA:
        raise RecoverySupervisorError("process_terminal.schema is invalid")
    for field in ("callback_id", "actor_id"):
        exact_text(item[field], name=f"process_terminal.{field}")
    validate_binding(item["binding"], "process_terminal.binding")
    validate_process(item["process_identity"], "process_terminal.process_identity")
    if item["status"] not in {"early_exit", "normal_exit", "transport_lost"}:
        raise RecoverySupervisorError("process_terminal.status is invalid")
    if item["exit_code"] is not None and type(item["exit_code"]) is not int:
        raise RecoverySupervisorError("process_terminal.exit_code must be int or null")
    _time_fields(item, "process_terminal")
    return deepcopy(item)


def validate_cancellation(value: Any) -> dict[str, Any]:
    item = exact_object(value, name="cancellation", fields=CANCEL_FIELDS)
    if item["schema"] != CANCELLATION_SCHEMA:
        raise RecoverySupervisorError("cancellation.schema is invalid")
    for field in ("callback_id", "actor_id", "reason"):
        exact_text(item[field], name=f"cancellation.{field}")
    validate_binding(item["binding"], "cancellation.binding")
    _time_fields(item, "cancellation")
    return deepcopy(item)


def validate_verifier(value: Any) -> dict[str, Any]:
    item = exact_object(value, name="verifier_receipt", fields=VERIFIER_FIELDS)
    if item["schema"] != VERIFIER_SCHEMA:
        raise RecoverySupervisorError("verifier_receipt.schema is invalid")
    for field in ("receipt_id", "business_callback_id", "actor_id", "provider"):
        exact_text(item[field], name=f"verifier_receipt.{field}")
    if type(item["task_epoch"]) is not str or _EPOCH.fullmatch(item["task_epoch"]) is None:
        raise RecoverySupervisorError("verifier_receipt.task_epoch is invalid")
    _integer(item["generation"], "verifier_receipt.generation")
    _sha(item["verifier_identity"], "verifier_receipt.verifier_identity")
    if item["status"] not in {"passed", "failed", "unknown", "contradictory"}:
        raise RecoverySupervisorError("verifier_receipt.status is invalid")
    exact_object(item["evidence"], name="verifier_receipt.evidence")
    return deepcopy(item)


def validate_business(value: Any) -> dict[str, Any]:
    item = exact_object(value, name="business_terminal", fields=BUSINESS_FIELDS)
    if item["schema"] != BUSINESS_SCHEMA:
        raise RecoverySupervisorError("business_terminal.schema is invalid")
    for field in ("callback_id", "actor_id"):
        exact_text(item[field], name=f"business_terminal.{field}")
    validate_binding(item["binding"], "business_terminal.binding")
    if item["status"] not in {"succeeded", "failed", "await_verification", "unknown"}:
        raise RecoverySupervisorError("business_terminal.status is invalid")
    if item["verifier_receipt"] is not None:
        exact_object(item["verifier_receipt"], name="business_terminal.verifier_receipt")
    exact_object(item["result"], name="business_terminal.result")
    _time_fields(item, "business_terminal")
    return deepcopy(item)


def validate_adapter_result(value: Any) -> dict[str, Any]:
    item = exact_object(value, name="adapter_result", fields=ADAPTER_RESULT_FIELDS)
    if item["schema"] != ADAPTER_RESULT_SCHEMA:
        raise RecoverySupervisorError("adapter_result.schema is invalid")
    for field in ("intervention_id", "effect_id", "adapter_identity"):
        _sha(item[field], f"adapter_result.{field}")
    if item["status"] not in {"completed", "failed", "unknown"}:
        raise RecoverySupervisorError("adapter_result.status is invalid")
    exact_object(item["result"], name="adapter_result.result")
    return deepcopy(item)


def validate_intervention_verifier(value: Any) -> dict[str, Any]:
    item = exact_object(
        value, name="intervention_verifier", fields=INTERVENTION_VERIFY_FIELDS
    )
    if item["schema"] != INTERVENTION_VERIFY_SCHEMA:
        raise RecoverySupervisorError("intervention verifier schema is invalid")
    for field in (
        "receipt_id", "verifier_identity", "intervention_id",
        "adapter_identity", "effect_id", "subject_identity",
        "world_state_digest", "result_identity",
    ):
        _sha(item[field], f"intervention_verifier.{field}")
    if item["status"] not in {"passed", "failed", "unknown", "contradictory"}:
        raise RecoverySupervisorError("intervention verifier status is invalid")
    exact_object(item["evidence"], name="intervention_verifier.evidence")
    return deepcopy(item)


def _event_sort(item: dict[str, Any]) -> tuple[float, int, str]:
    return (
        float(item["payload"].get("supervisor_received_mono", 0.0)),
        int(item.get("journal_sequence", 0)),
        item["event_identity"],
    )


def _matches(actor: dict[str, Any], event: dict[str, Any], *, process: bool = False) -> bool:
    if event.get("binding") != binding_from_actor(actor):
        return False
    if process and event.get("process_identity") != actor["process_identity"]:
        return False
    return True


def _verifier_matches(actor: dict[str, Any], callback_id: str, receipt: dict[str, Any]) -> bool:
    try:
        receipt = validate_verifier(_without_receipt(receipt))
    except SupervisorStateError:
        return False
    return (
        receipt["business_callback_id"] == callback_id
        and receipt["actor_id"] == actor["actor_id"]
        and receipt["provider"] == actor["provider"]
        and receipt["task_epoch"] == actor["task_epoch"]
        and receipt["generation"] == actor["generation"]
        and receipt["verifier_identity"] == actor["verifier_identity"]
        and receipt["status"] == "passed"
    )


def _sealed_recommendation(
    *, kind: str, binding: dict[str, Any], relevant_event_ids: list[str],
    created_wall: float, created_mono: float, execute_by_mono: float | None,
    reason: str, actor_snapshots: list[dict[str, Any]], affected_lanes: list[str],
) -> dict[str, Any]:
    relevant_head = canonical_digest(
        "relevant-journal-head", sorted(set(relevant_event_ids))
    )
    eligibility = canonical_digest("recovery-eligibility", {
        "kind": kind, "binding": binding, "relevant_journal_head": relevant_head,
    })
    recommendation_id = canonical_digest("recovery-recommendation", {
        "kind": kind, "binding": binding, "eligibility_digest": eligibility,
    })
    return {
        "schema": RECOMMENDATION_SCHEMA,
        "recommendation_id": recommendation_id,
        "kind": kind,
        "created_wall": created_wall,
        "created_mono": created_mono,
        "execute_by_mono": execute_by_mono,
        "binding": deepcopy(binding),
        "reason": reason,
        "actor_snapshots": deepcopy(actor_snapshots),
        "affected_lanes": deepcopy(affected_lanes),
        "eligibility_digest": eligibility,
        "relevant_journal_head": relevant_head,
    }


class RecoverySupervisor:
    """Replayable policy over a strict durable :class:`SupervisorState`."""

    def __init__(
        self, state_path: str, *, wall_clock: Callable[[], float],
        monotonic_clock: Callable[[], float], failpoint: Callable[[str], None] | None = None,
        state_failpoint: Callable[[str], None] | None = None,
        trusted_probe_authorities: frozenset[str] | None = None,
        process_observation_max_age: float = 30.0,
        trusted_adapter: Any = None, adapter_identity: str | None = None,
        trusted_intervention_verifier: Any = None,
        intervention_verifier_identity: str | None = None,
    ) -> None:
        self.state = SupervisorState(state_path, failpoint=state_failpoint)
        self.wall_clock = wall_clock
        self.monotonic_clock = monotonic_clock
        self._failpoint = failpoint or (lambda _boundary: None)
        self.trusted_probe_authorities = frozenset(trusted_probe_authorities or ())
        for identity in self.trusted_probe_authorities:
            _sha(identity, "trusted_probe_authority")
        self.process_observation_max_age = _number(
            process_observation_max_age, "process_observation_max_age"
        )
        self.trusted_adapter = trusted_adapter
        self.adapter_identity = (
            _sha(adapter_identity, "adapter_identity")
            if adapter_identity is not None else None
        )
        self.trusted_intervention_verifier = trusted_intervention_verifier
        self.intervention_verifier_identity = (
            _sha(intervention_verifier_identity, "intervention_verifier_identity")
            if intervention_verifier_identity is not None else None
        )

    def _append(
        self, event_type: str, payload: dict[str, Any],
        *, unique_fields: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        return self.state.append(event_type, payload, unique_fields=unique_fields)

    def _append_received(
        self, event_type: str, source: dict[str, Any], *,
        unique_fields: tuple[str, ...],
    ) -> dict[str, Any]:
        def derive(snapshot: dict[str, Any]) -> dict[str, Any]:
            existing = [
                event["payload"] for event in snapshot["events"]
                if event["event_type"] == event_type
                and all(event["payload"].get(field) == source[field]
                        for field in unique_fields)
            ]
            if existing and _without_receipt(existing[0]) == source:
                return deepcopy(existing[0])
            wall, mono = self._receipt_clock()
            return _with_receipt(source, wall, mono)

        return self.state.append_derived(
            event_type, derive, unique_fields=unique_fields
        )

    def register_actor(self, actor: Any) -> dict[str, Any]:
        selected = validate_actor(actor)
        return self._append_received(
            "actor_registered", selected,
            unique_fields=("actor_id",),
        )

    def record_heartbeat(self, heartbeat: Any) -> dict[str, Any]:
        return self._append_received(
            "heartbeat_observed", validate_heartbeat(heartbeat),
            unique_fields=("actor_id", "callback_id"),
        )

    def record_process_probe(self, probe: Any) -> dict[str, Any]:
        require_plain_json(probe, name="process_probe")
        try:
            selected = validate_probe(probe)
        except SupervisorStateError as error:
            wall, mono = self._receipt_clock()
            if type(probe) is not dict:
                raise
            rejected = {
                "schema": PROCESS_RECEIPT_SCHEMA,
                "rejection_id": canonical_digest("rejected-process-observation", probe),
                "actor_id": probe.get("actor_id") if type(probe.get("actor_id")) is str else None,
                "reason": "invalid_or_pid_only_process_fact",
                "source_event": deepcopy(probe),
                "supervisor_received_wall": wall,
                "supervisor_received_mono": mono,
                "detail": str(error),
            }
            return self._append(
                "process_probe_rejected", rejected, unique_fields=("rejection_id",)
            )
        def derive(snapshot: dict[str, Any]) -> dict[str, Any]:
            existing = [
                event["payload"] for event in snapshot["events"]
                if event["event_type"] == "process_probe_observed"
                and event["payload"]["source_event_identity"]
                == selected["source_event_identity"]
            ]
            if existing and _without_receipt(existing[0]) == selected:
                return deepcopy(existing[0])
            wall, mono = self._receipt_clock()
            receipt_material = {
                "probe_id": selected["probe_id"],
                "source_event_identity": selected["source_event_identity"],
                "probe_authority": selected["probe_authority"],
                "subject_process_identity": selected["subject_process_identity"],
                "status": selected["status"],
                "supervisor_received_wall": wall,
                "supervisor_received_mono": mono,
            }
            return {
                **_with_receipt(selected, wall, mono),
                "receipt_schema": PROCESS_RECEIPT_SCHEMA,
                "receipt_id": canonical_digest(
                    "process-observation-receipt", receipt_material
                ),
            }

        return self.state.append_derived(
            "process_probe_observed", derive,
            unique_fields=("source_event_identity",),
        )

    def record_lock_lease(self, lease: Any) -> dict[str, Any]:
        return self._append_received(
            "lock_lease_observed", validate_lease(lease),
            unique_fields=("lease_id",)
        )

    def record_exit(self, event: Any) -> dict[str, Any]:
        return self._append_received(
            "process_terminal_observed", validate_exit(event),
            unique_fields=("actor_id", "callback_id"),
        )

    def record_cancellation(self, event: Any) -> dict[str, Any]:
        return self._append_received(
            "cancellation_observed", validate_cancellation(event),
            unique_fields=("actor_id", "callback_id"),
        )

    def record_business_terminal(self, event: Any) -> dict[str, Any]:
        return self._append_received(
            "business_terminal_observed", validate_business(event),
            unique_fields=("actor_id",),
        )

    def record_verifier_receipt(self, receipt: Any) -> dict[str, Any]:
        return self._append_received(
            "verifier_receipt_observed", validate_verifier(receipt),
            unique_fields=("actor_id", "receipt_id"),
        )

    def _receipt_clock(self) -> tuple[float, float]:
        return (
            _number(self.wall_clock(), "wall_clock"),
            _number(self.monotonic_clock(), "monotonic_clock"),
        )

    def _clock_sample(
        self, snapshot: dict[str, Any] | None = None,
    ) -> tuple[float, float]:
        wall, mono = self._receipt_clock()
        selected_snapshot = snapshot or self.state.snapshot()
        prior = [event["payload"] for event in selected_snapshot["events"]
                 if event["event_type"] == "scan_observed"]
        if prior:
            latest = max(prior, key=lambda item: item["scan_sequence"])
            if wall < latest["observed_wall"] or mono < latest["observed_mono"]:
                raise RecoverySupervisorError("wall or monotonic clock regression")
        return wall, mono

    def scan(self) -> dict[str, Any]:
        def derive_scan(snapshot: dict[str, Any]) -> dict[str, Any]:
            wall, mono = self._clock_sample(snapshot)
            scans = [event["payload"] for event in snapshot["events"]
                     if event["event_type"] == "scan_observed"]
            return {
                "schema": SCAN_SCHEMA,
                "scan_sequence": max(
                    (item["scan_sequence"] for item in scans), default=0
                ) + 1,
                "baseline_sequence": snapshot["sequence"],
                "baseline_head_sha256": snapshot["head_sha256"],
                "observed_wall": wall,
                "observed_mono": mono,
            }

        committed = self.state.append_derived(
            "scan_observed", derive_scan, unique_fields=("scan_sequence",)
        )
        scan = committed["row"]["payload"]
        wall, mono = scan["observed_wall"], scan["observed_mono"]
        projection = self.projection(now_wall=wall, now_mono=mono)
        for card in projection["pending_status_cards"]:
            self._append("status_card_projected", card, unique_fields=("card_id",))
        for recommendation in projection["pending_recommendations"]:
            self._append(
                "recommendation_projected", recommendation,
                unique_fields=("recommendation_id",),
            )
        for receipt in projection["pending_exhausted_receipts"]:
            self._append(
                "restart_budget_exhausted", receipt, unique_fields=("actor_id",)
            )
        return self.projection(now_wall=wall, now_mono=mono)

    def _raw_events(
        self, snapshot: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        events = (snapshot or self.state.snapshot())["events"]
        validators = {
            "actor_registered": validate_actor,
            "heartbeat_observed": validate_heartbeat,
            "process_probe_observed": validate_probe,
            "lock_lease_observed": validate_lease,
            "process_terminal_observed": validate_exit,
            "cancellation_observed": validate_cancellation,
            "business_terminal_observed": validate_business,
            "verifier_receipt_observed": validate_verifier,
        }
        for event in events:
            validator = validators.get(event["event_type"])
            if validator is not None:
                _validate_received(event["payload"], validator, event["event_type"])
                if event["event_type"] == "process_probe_observed":
                    payload = event["payload"]
                    if payload.get("receipt_schema") != PROCESS_RECEIPT_SCHEMA:
                        raise RecoverySupervisorError("process receipt schema is invalid")
                    _sha(payload.get("receipt_id"), "process receipt identity")
            elif event["event_type"] not in {
                "scan_observed", "status_card_projected", "recommendation_projected",
                "intervention_authorized", "intervention_started",
                "intervention_prepared", "intervention_dispatch_observed",
                "intervention_reprobe_observed", "intervention_verifier_observed",
                "intervention_receipt_recorded", "restart_budget_exhausted",
                "process_probe_rejected", "recommendation_retired",
            }:
                raise RecoverySupervisorError("durable state contains an unknown event type")
        return events

    def projection(
        self, *, now_wall: float | None = None, now_mono: float | None = None,
        _snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        events = self._raw_events(_snapshot)
        scans = [event["payload"] for event in events if event["event_type"] == "scan_observed"]
        if now_wall is None or now_mono is None:
            if scans:
                latest_scan = max(scans, key=lambda item: item["scan_sequence"])
                now_wall = latest_scan["observed_wall"]
                now_mono = latest_scan["observed_mono"]
            else:
                now_wall = now_mono = 0.0
        now_wall = _number(now_wall, "projection.now_wall")
        now_mono = _number(now_mono, "projection.now_mono")

        registrations: dict[str, dict[str, Any]] = {}
        registration_ids: dict[str, str] = {}
        rejected: list[dict[str, Any]] = []
        for event in events:
            if event["event_type"] != "actor_registered":
                continue
            actor = event["payload"]
            existing = registrations.get(actor["actor_id"])
            if existing is not None and existing != actor:
                raise RecoverySupervisorError("actor immutable registration identity changed")
            registrations[actor["actor_id"]] = actor
            registration_ids[actor["actor_id"]] = event["event_identity"]

        grouped: dict[str, list[dict[str, Any]]] = {key: [] for key in registrations}
        for event in events:
            actor_id = event["payload"].get("actor_id")
            if event["event_type"] != "actor_registered" and type(actor_id) is str:
                if actor_id in grouped:
                    grouped[actor_id].append(event)

        receipts = [event["payload"] for event in events
                    if event["event_type"] == "intervention_receipt_recorded"]
        restart_receipts: dict[str, int] = {}
        for receipt in receipts:
            if receipt["kind"] == "restart" and receipt["status"] == "completed":
                actor_id = receipt["binding"]["actor_id"]
                restart_receipts[actor_id] = restart_receipts.get(actor_id, 0) + 1

        actor_states: dict[str, dict[str, Any]] = {}
        pending_cards: list[dict[str, Any]] = []
        pending_recommendations: list[dict[str, Any]] = []
        eligible_recommendations: list[dict[str, Any]] = []
        pending_exhausted: list[dict[str, Any]] = []
        existing_cards = {event["payload"]["card_id"] for event in events
                          if event["event_type"] == "status_card_projected"}
        existing_recommendations = {
            event["payload"]["recommendation_id"] for event in events
            if event["event_type"] == "recommendation_projected"
        }
        exhausted_actors = {event["payload"]["actor_id"] for event in events
                            if event["event_type"] == "restart_budget_exhausted"}

        for actor_id, actor in sorted(registrations.items()):
            actor_events = sorted(grouped[actor_id], key=_event_sort)
            heartbeats: list[dict[str, Any]] = []
            exits: list[dict[str, Any]] = []
            cancellations: list[dict[str, Any]] = []
            business: list[dict[str, Any]] = []
            verifier_receipts: list[dict[str, Any]] = []
            latest_source_mono: dict[str, float] = {}
            for event in actor_events:
                payload = event["payload"]
                kind = event["event_type"]
                if kind in {
                    "heartbeat_observed", "process_terminal_observed",
                    "cancellation_observed", "business_terminal_observed",
                }:
                    clock_reason = _source_clock_reason(payload)
                    source_mono = float(payload["observed_mono"])
                    if clock_reason is None and source_mono < latest_source_mono.get(
                        kind, -1.0
                    ):
                        clock_reason = "regressive_source_clock"
                    if clock_reason is not None:
                        rejected.append({
                            "event_identity": event["event_identity"],
                            "actor_id": actor_id,
                            "reason": clock_reason,
                        })
                        continue
                    latest_source_mono[kind] = source_mono
                binding_required = kind in {
                    "heartbeat_observed", "process_terminal_observed",
                    "cancellation_observed", "business_terminal_observed",
                }
                process_required = kind in {"heartbeat_observed", "process_terminal_observed"}
                if binding_required and not _matches(actor, payload, process=process_required):
                    rejected.append({
                        "event_identity": event["event_identity"],
                        "actor_id": actor_id,
                        "reason": "immutable_binding_mismatch",
                    })
                    continue
                if kind == "heartbeat_observed":
                    if payload["worker_id"] != actor["worker_id"]:
                        rejected.append({
                            "event_identity": event["event_identity"],
                            "actor_id": actor_id,
                            "reason": "worker_identity_mismatch",
                        })
                        continue
                    heartbeats.append(payload)
                elif kind == "process_terminal_observed":
                    exits.append(payload)
                elif kind == "cancellation_observed":
                    cancellations.append(payload)
                elif kind == "business_terminal_observed":
                    business.append(payload)
                elif kind == "verifier_receipt_observed":
                    verifier_receipts.append(payload)

            cursor: dict[str, Any] | None = None
            last_progress = float(actor["supervisor_received_mono"])
            latest_snapshot: dict[str, Any] = {
                "actor": deepcopy(actor), "heartbeat": None,
            }
            progress_anomalies: list[str] = []
            for heartbeat in heartbeats:
                candidate = heartbeat["progress_cursor"]
                if cursor is None or candidate["sequence"] > cursor["sequence"]:
                    cursor = deepcopy(candidate)
                    last_progress = float(heartbeat["supervisor_received_mono"])
                elif candidate["sequence"] == cursor["sequence"]:
                    if candidate["state_identity"] != cursor["state_identity"]:
                        progress_anomalies.append("same_sequence_identity_changed")
                else:
                    progress_anomalies.append("progress_cursor_regressed")
                latest_snapshot = {"actor": deepcopy(actor), "heartbeat": deepcopy(heartbeat)}

            business_fact = business[0] if business else None
            cancellation_fact = cancellations[0] if cancellations else None
            business_status = None
            if business_fact is not None:
                business_status = business_fact["status"]
                receipt_candidates: list[dict[str, Any]] = []
                if business_fact["verifier_receipt"] is not None:
                    receipt_candidates.append(business_fact["verifier_receipt"])
                receipt_candidates.extend(verifier_receipts)
                verified = any(
                    _verifier_matches(actor, business_fact["callback_id"], receipt)
                    for receipt in receipt_candidates
                )
                if business_status == "succeeded" and not verified:
                    business_status = "await_verification"
                elif business_status == "await_verification" and verified:
                    business_status = "succeeded"
                elif business_status == "unknown":
                    business_status = "unknown_terminal"
            terminal = business_fact is not None or cancellation_fact is not None
            visible_after = last_progress + SILENT_CARD_SECONDS
            elapsed = max(0.0, now_mono - last_progress)
            if not terminal and elapsed >= SILENT_CARD_SECONDS:
                card_material = {
                    "actor_id": actor_id,
                    "progress_identity": canonical_digest("progress", cursor),
                    "threshold": "silent_5s",
                }
                card_id = canonical_digest("status-card", card_material)
                if card_id not in existing_cards:
                    pending_cards.append({
                        "schema": STATUS_CARD_SCHEMA, "card_id": card_id,
                        "actor_id": actor_id, "kind": "visible_no_progress",
                        "projected_mono": visible_after,
                        "detail": {"last_progress_mono": last_progress},
                    })
            window = int(elapsed // PROGRESS_WINDOW_SECONDS)
            if not terminal and window >= 1:
                reason_material = {
                    "actor_id": actor_id,
                    "progress_identity": canonical_digest("progress", cursor),
                    "threshold": "progress_30s", "window": window,
                }
                card_id = canonical_digest("status-card", reason_material)
                if card_id not in existing_cards:
                    scheduler = latest_snapshot["heartbeat"]["scheduler_state"] if latest_snapshot["heartbeat"] else None
                    reason = "scheduler_degraded" if scheduler and scheduler["status"] == "degraded" else "stalled_no_progress"
                    pending_cards.append({
                        "schema": STATUS_CARD_SCHEMA, "card_id": card_id,
                        "actor_id": actor_id, "kind": "typed_reason",
                        "projected_mono": last_progress + window * PROGRESS_WINDOW_SECONDS,
                        "detail": {"reason": reason, "window": window},
                    })

            completed_attempts = restart_receipts.get(actor_id, 0)
            eligible_exits = [event for event in exits if event["status"] == "early_exit"]
            if not terminal and len(eligible_exits) > completed_attempts:
                attempt = completed_attempts + 1
                maximum = actor["retry_budget"]["max_attempts"]
                if attempt <= maximum:
                    source_exit = eligible_exits[completed_attempts]
                    delay = actor["retry_budget"]["backoff_seconds"][attempt - 1]
                    not_before = source_exit["supervisor_received_mono"] + delay
                    material = {
                        "kind": "restart", "actor_id": actor_id, "attempt": attempt,
                        "source_callback_id": source_exit["callback_id"],
                        "binding": binding_from_actor(actor),
                        "process_identity": actor["process_identity"],
                    }
                    relevant = [registration_ids[actor_id]]
                    relevant.extend(
                        event["event_identity"] for event in actor_events
                        if event["event_type"] in {
                            "process_terminal_observed", "business_terminal_observed",
                            "cancellation_observed",
                        }
                    )
                    recommendation = _sealed_recommendation(
                        kind="restart", binding=material,
                        relevant_event_ids=relevant,
                        created_wall=source_exit["supervisor_received_wall"] + delay,
                        created_mono=not_before, execute_by_mono=None,
                        reason="bounded_early_exit",
                        actor_snapshots=[latest_snapshot],
                        affected_lanes=[actor["lane"]],
                    )
                    if now_mono >= not_before:
                        eligible_recommendations.append(recommendation)
                        if recommendation["recommendation_id"] not in existing_recommendations:
                            pending_recommendations.append(recommendation)
                elif actor_id not in exhausted_actors:
                    pending_exhausted.append({
                        "schema": EXHAUSTED_SCHEMA,
                        "receipt_id": canonical_digest("restart-exhausted", {
                            "actor_id": actor_id, "attempts": completed_attempts,
                            "binding": binding_from_actor(actor),
                        }),
                        "actor_id": actor_id, "attempts": completed_attempts,
                        "status": "restart_budget_exhausted",
                        "binding": binding_from_actor(actor),
                    })

            actor_states[actor_id] = {
                "actor_id": actor_id, "snapshot": latest_snapshot,
                "last_heartbeat_mono": heartbeats[-1]["supervisor_received_mono"]
                if heartbeats else None,
                "last_progress_mono": last_progress, "progress_cursor": cursor,
                "progress_anomalies": sorted(set(progress_anomalies)),
                "business_terminal": deepcopy(business_fact),
                "business_status": business_status,
                "process_terminals": deepcopy(exits),
                "cancellation": deepcopy(cancellation_fact),
                "restart_attempts_completed": completed_attempts,
                "terminal": terminal or actor_id in exhausted_actors,
            }

        latest_leases: dict[str, dict[str, Any]] = {}
        probes = [event for event in events
                  if event["event_type"] == "process_probe_observed"]
        for event in events:
            if event["event_type"] == "process_probe_rejected":
                rejected.append({
                    "event_identity": event["event_identity"],
                    "actor_id": event["payload"].get("actor_id"),
                    "reason": event["payload"]["reason"],
                })
        for event in events:
            if event["event_type"] != "lock_lease_observed":
                continue
            lease = event["payload"]
            clock_reason = _source_clock_reason(lease)
            if clock_reason is not None:
                rejected.append({
                    "event_identity": event["event_identity"],
                    "actor_id": lease["owner_actor_id"],
                    "reason": clock_reason,
                })
                continue
            key = _resource_key(lease["lock"])
            previous = latest_leases.get(key)
            if (
                previous is not None
                and lease["observed_mono"] < previous["observed_mono"]
            ):
                rejected.append({
                    "event_identity": event["event_identity"],
                    "actor_id": lease["owner_actor_id"],
                    "reason": "regressive_source_clock",
                })
                continue
            if previous is None or (
                lease["lease_epoch"], lease["supervisor_received_mono"],
                event["journal_sequence"],
            ) > (
                previous["lease_epoch"], previous["supervisor_received_mono"],
                previous["_sequence"],
            ):
                latest_leases[key] = {
                    **deepcopy(lease),
                    "_identity": event["event_identity"],
                    "_sequence": event["journal_sequence"],
                }
        lock_states: dict[str, dict[str, Any]] = {}
        for key, lease in sorted(latest_leases.items()):
            actor = registrations.get(lease["owner_actor_id"])
            valid_probes: list[dict[str, Any]] = []
            probe_ambiguities: list[str] = []
            latest_probe_source = -1.0
            for event in probes:
                probe = event["payload"]
                if probe["actor_id"] != lease["owner_actor_id"]:
                    continue
                reason = None
                if probe["subject_process_identity"] != lease["owner_process_identity"]:
                    reason = "foreign_process_subject"
                elif actor is None:
                    reason = "unknown_probe_actor"
                elif not (
                    probe["probe_authority"] == actor["probe_authority"]
                    or probe["probe_authority"] in self.trusted_probe_authorities
                ):
                    reason = "untrusted_probe_authority"
                else:
                    reason = _source_clock_reason(probe)
                    age = (
                        float(probe["supervisor_received_mono"])
                        - float(probe["observed_mono"])
                    )
                    if reason is None and age > self.process_observation_max_age:
                        reason = "stale_process_observation"
                    if (
                        reason is None
                        and float(probe["observed_mono"]) < latest_probe_source
                    ):
                        reason = "regressive_source_clock"
                if reason is not None:
                    probe_ambiguities.append(reason)
                    rejected.append({
                        "event_identity": event["event_identity"],
                        "actor_id": lease["owner_actor_id"],
                        "reason": reason,
                    })
                    continue
                valid_probes.append(event)
                latest_probe_source = max(
                    latest_probe_source, float(probe["observed_mono"])
                )
            latest_group: list[dict[str, Any]] = []
            if valid_probes:
                latest_source = max(
                    float(event["payload"]["observed_mono"])
                    for event in valid_probes
                )
                latest_group = [
                    event for event in valid_probes
                    if float(event["payload"]["observed_mono"]) == latest_source
                ]
            outcomes = {event["payload"]["status"] for event in latest_group}
            if len(outcomes) > 1:
                probe_ambiguities.append("contradictory_equal_time_process_observations")
            if outcomes and outcomes != {"dead"} and outcomes != {"alive"}:
                probe_ambiguities.append("non_authoritative_process_outcome")
            owner_terminal = bool(
                actor_states.get(lease["owner_actor_id"], {}).get("terminal")
            )
            dead = outcomes == {"dead"} and len(latest_group) >= 1 and not owner_terminal
            latest_probe = deepcopy(latest_group[0]["payload"]) if len(latest_group) == 1 else None
            expiry_mono = lease["supervisor_received_mono"] + max(
                0.0, lease["expires_wall"] - lease["observed_wall"]
            )
            expired = now_mono >= expiry_mono
            death_receipt_mono = max(
                (event["payload"]["supervisor_received_mono"] for event in latest_group),
                default=math.inf,
            )
            eligible_mono = max(expiry_mono, death_receipt_mono)
            lock_states[key] = {
                "lease": {field: value for field, value in lease.items()
                          if not field.startswith("_")},
                "latest_exact_probe": latest_probe,
                "process_observation_ambiguities": sorted(set(probe_ambiguities)),
                "owner_dead": dead,
                "lease_expired": expired, "eligible_mono": eligible_mono if dead else None,
            }
            if dead and expired and now_mono >= eligible_mono:
                material = {
                    "kind": "reclaim_lock", "lock": lease["lock"],
                    "lease_id": lease["lease_id"], "lease_epoch": lease["lease_epoch"],
                    "owner_actor_id": lease["owner_actor_id"],
                    "owner_process_identity": lease["owner_process_identity"],
                }
                snapshot = actor_states.get(lease["owner_actor_id"], {}).get("snapshot")
                relevant = [lease["_identity"]]
                relevant.extend(event["event_identity"] for event in latest_group)
                if lease["owner_actor_id"] in registration_ids:
                    relevant.append(registration_ids[lease["owner_actor_id"]])
                recommendation = _sealed_recommendation(
                    kind="reclaim_lock", binding=material,
                    relevant_event_ids=relevant,
                    created_wall=lease["supervisor_received_wall"],
                    created_mono=eligible_mono,
                    execute_by_mono=eligible_mono + RECLAIM_DEADLINE_SECONDS,
                    reason="trusted_exact_owner_dead_and_exact_lease_expired",
                    actor_snapshots=[snapshot] if snapshot else [],
                    affected_lanes=[registrations[lease["owner_actor_id"]]["lane"]]
                    if lease["owner_actor_id"] in registrations else [],
                )
                eligible_recommendations.append(recommendation)
                if recommendation["recommendation_id"] not in existing_recommendations:
                    pending_recommendations.append(recommendation)

        snapshots = [state["snapshot"] for state in actor_states.values()
                     if state["snapshot"]["heartbeat"] is not None
                     and not state["terminal"]]
        conflicts: list[dict[str, Any]] = []
        for left, right in combinations(sorted(snapshots, key=lambda item: item["actor"]["actor_id"]), 2):
            left_resources = {_resource_key(item): item for item in left["heartbeat"]["resources"]}
            right_resources = {_resource_key(item): item for item in right["heartbeat"]["resources"]}
            overlap = sorted(set(left_resources) & set(right_resources))
            if not overlap:
                continue
            lanes = sorted({left["actor"]["lane"], right["actor"]["lane"]})
            material = {
                "kind": "pause_conflict", "actors": sorted([
                    left["actor"]["actor_id"], right["actor"]["actor_id"]
                ]), "resources": overlap, "affected_lanes": lanes,
                "snapshot_identities": sorted([
                    canonical_digest("actor-snapshot", left),
                    canonical_digest("actor-snapshot", right),
                ]),
            }
            actor_ids = {left["actor"]["actor_id"], right["actor"]["actor_id"]}
            relevant = [
                event["event_identity"] for event in events
                if event["event_type"] in {
                    "actor_registered", "heartbeat_observed",
                    "business_terminal_observed", "cancellation_observed",
                } and event["payload"].get("actor_id") in actor_ids
            ]
            created_mono = max(
                left["heartbeat"]["supervisor_received_mono"],
                right["heartbeat"]["supervisor_received_mono"],
            )
            created_wall = max(
                left["heartbeat"]["supervisor_received_wall"],
                right["heartbeat"]["supervisor_received_wall"],
            )
            recommendation = _sealed_recommendation(
                kind="pause_conflict", binding=material,
                relevant_event_ids=relevant,
                created_wall=created_wall, created_mono=created_mono,
                execute_by_mono=None,
                reason="concurrent_exact_resource_overlap",
                actor_snapshots=[left, right], affected_lanes=lanes,
            )
            conflict = {
                "recommendation_id": recommendation["recommendation_id"],
                **material, "actor_snapshots": [deepcopy(left), deepcopy(right)],
            }
            conflicts.append(conflict)
            eligible_recommendations.append(recommendation)
            if recommendation["recommendation_id"] not in existing_recommendations:
                pending_recommendations.append(recommendation)

        recommendations = [event["payload"] for event in events
                           if event["event_type"] == "recommendation_projected"]
        authorizations = [event["payload"] for event in events
                          if event["event_type"] == "intervention_authorized"]
        active_ids = {
            item["recommendation_id"] for item in eligible_recommendations
        }
        retired_recommendations = [
            item for item in recommendations
            if item["recommendation_id"] not in active_ids
        ]
        return {
            "schema": PROJECTION_SCHEMA,
            "actors": actor_states, "locks": lock_states,
            "conflicts": conflicts, "rejected_observations": rejected,
            "status_cards": [event["payload"] for event in events
                             if event["event_type"] == "status_card_projected"],
            "recommendations": recommendations,
            "eligible_recommendations": sorted(
                eligible_recommendations, key=lambda item: item["recommendation_id"]
            ),
            "retired_recommendations": retired_recommendations,
            "authorizations": authorizations, "terminal_receipts": receipts,
            "exhausted_receipts": [event["payload"] for event in events
                                   if event["event_type"] == "restart_budget_exhausted"],
            "pending_status_cards": sorted(pending_cards, key=lambda item: item["card_id"]),
            "pending_recommendations": sorted(
                pending_recommendations, key=lambda item: item["recommendation_id"]
            ),
            "pending_exhausted_receipts": sorted(
                pending_exhausted, key=lambda item: item["receipt_id"]
            ),
            "authority": {
                "human_grant_minted": False, "effect_success_minted": False,
                "verifier_success_minted": False, "paths_expanded": False,
                "provider_authority_minted": False, "merge_authority_minted": False,
                "real_signal": False, "deletion": False, "git_write": False,
                "external_effect": False,
            },
        }

    def authorize(self, recommendation_id: Any) -> dict[str, Any]:
        selected_id = _sha(recommendation_id, "recommendation_id")
        if (
            self.trusted_adapter is None or self.adapter_identity is None
            or self.trusted_intervention_verifier is None
            or self.intervention_verifier_identity is None
        ):
            raise RecoverySupervisorError(
                "trusted adapter and intervention verifier must be configured"
            )

        def derive(snapshot: dict[str, Any]) -> dict[str, Any]:
            wall, mono = self._clock_sample(snapshot)
            projection = self.projection(
                now_wall=wall, now_mono=mono, _snapshot=snapshot
            )
            durable = [
                item for item in projection["recommendations"]
                if item["recommendation_id"] == selected_id
            ]
            active = [
                item for item in projection["eligible_recommendations"]
                if item["recommendation_id"] == selected_id
            ]
            if len(durable) != 1 or len(active) != 1 or durable[0] != active[0]:
                raise RecoverySupervisorError(
                    "recommendation is stale or no longer eligible"
                )
            recommendation = active[0]
            if (
                recommendation["execute_by_mono"] is not None
                and mono > recommendation["execute_by_mono"]
            ):
                raise RecoverySupervisorError("bounded intervention deadline was missed")
            existing = [
                event["payload"] for event in snapshot["events"]
                if event["event_type"] == "intervention_authorized"
                and event["payload"]["recommendation_id"] == selected_id
            ]
            if existing:
                if len(existing) != 1:
                    raise RecoverySupervisorError(
                        "recommendation has ambiguous authorizations"
                    )
                return deepcopy(existing[0])
            capability = {
                "reclaim_lock": "synthetic_reclaim_lock",
                "pause_conflict": "synthetic_pause_task_lanes",
                "restart": "synthetic_restart_same_binding",
            }[recommendation["kind"]]
            material = {
                "recommendation_id": selected_id,
                "kind": recommendation["kind"],
                "binding": deepcopy(recommendation["binding"]),
                "capability": capability,
                "adapter_identity": self.adapter_identity,
                "verifier_identity": self.intervention_verifier_identity,
                "eligibility_digest": recommendation["eligibility_digest"],
                "relevant_journal_head": recommendation["relevant_journal_head"],
                "subject_identity": canonical_digest(
                    "intervention-subject", recommendation["binding"]
                ),
            }
            return {
                "schema": AUTHORIZATION_SCHEMA,
                "intervention_id": canonical_digest("local-intervention", material),
                **material,
                "authority": "bounded_local_policy",
                "authorized_wall": wall,
                "authorized_mono": mono,
                "local_only": True,
                "external_effect": False,
            }

        self._failpoint("before_authorization")
        committed = self.state.append_derived(
            "intervention_authorized", derive,
            unique_fields=("intervention_id",),
        )
        self._failpoint("after_authorization")
        return deepcopy(committed["row"]["payload"])

    def execute(self, intervention_id: Any, adapter: Any) -> dict[str, Any]:
        selected_id = _sha(intervention_id, "intervention_id")
        events = self._raw_events()
        existing = [event["payload"] for event in events
                    if event["event_type"] == "intervention_receipt_recorded"
                    and event["payload"]["intervention_id"] == selected_id]
        if existing:
            if len(existing) != 1:
                raise RecoverySupervisorError("intervention has ambiguous terminal receipts")
            return deepcopy(existing[0])
        if adapter is not self.trusted_adapter:
            raise RecoverySupervisorError("adapter object is not supervisor-trusted")

        def derive_prepare(snapshot: dict[str, Any]) -> dict[str, Any]:
            matches = [
                event["payload"] for event in snapshot["events"]
                if event["event_type"] == "intervention_authorized"
                and event["payload"]["intervention_id"] == selected_id
            ]
            if len(matches) != 1:
                raise RecoverySupervisorError(
                    "intervention authorization is not uniquely durable"
                )
            authorization = matches[0]
            if (
                authorization["adapter_identity"] != self.adapter_identity
                or authorization["verifier_identity"]
                != self.intervention_verifier_identity
            ):
                raise RecoverySupervisorError("authorization adapter boundary changed")
            wall, mono = self._clock_sample(snapshot)
            projection = self.projection(
                now_wall=wall, now_mono=mono, _snapshot=snapshot
            )
            active = [
                item for item in projection["eligible_recommendations"]
                if item["recommendation_id"] == authorization["recommendation_id"]
                and item["eligibility_digest"] == authorization["eligibility_digest"]
                and item["relevant_journal_head"]
                == authorization["relevant_journal_head"]
            ]
            if len(active) != 1:
                raise RecoverySupervisorError(
                    "authorization retired by world-state drift before dispatch"
                )
            prepared = [
                event["payload"] for event in snapshot["events"]
                if event["event_type"] == "intervention_prepared"
                and event["payload"]["intervention_id"] == selected_id
            ]
            if prepared:
                if len(prepared) != 1:
                    raise RecoverySupervisorError(
                        "intervention has ambiguous prepare identities"
                    )
                return deepcopy(prepared[0])
            effect_material = {
                "intervention_id": selected_id,
                "adapter_identity": authorization["adapter_identity"],
                "capability": authorization["capability"],
                "subject_identity": authorization["subject_identity"],
                "world_state_digest": authorization["eligibility_digest"],
            }
            return {
                "schema": INTERVENTION_PREPARE_SCHEMA,
                "intervention_id": selected_id,
                "authorization_identity": canonical_digest(
                    "authorization", authorization
                ),
                "effect_id": canonical_digest("local-effect", effect_material),
                "adapter_identity": authorization["adapter_identity"],
                "capability": authorization["capability"],
                "subject_identity": authorization["subject_identity"],
                "world_state_digest": authorization["eligibility_digest"],
                "prepared_wall": wall,
                "prepared_mono": mono,
            }

        self._failpoint("before_intervention_start")
        self._failpoint("before_prepare")
        prepared_commit = self.state.append_derived(
            "intervention_prepared", derive_prepare,
            unique_fields=("intervention_id",),
        )
        prepare = prepared_commit["row"]["payload"]
        first_dispatch = prepared_commit["status"] == "appended"
        self._failpoint("after_prepare")
        self._failpoint("after_intervention_start")
        request = deepcopy(prepare)
        if first_dispatch:
            self._failpoint("before_apply")
            result = adapter.apply(request)
            self._failpoint("after_apply")
            observation_type = "intervention_dispatch_observed"
        else:
            if not callable(getattr(adapter, "reprobe", None)):
                raise RecoverySupervisorError("adapter lacks mandatory reprobe")
            self._failpoint("before_reprobe")
            result = adapter.reprobe(request)
            self._failpoint("after_reprobe")
            observation_type = "intervention_reprobe_observed"
        result = validate_adapter_result(result)
        if (
            result["intervention_id"] != selected_id
            or result["effect_id"] != prepare["effect_id"]
            or result["adapter_identity"] != prepare["adapter_identity"]
        ):
            raise RecoverySupervisorError("adapter result binding is invalid")
        wall, mono = self._receipt_clock()
        observation = {
            **result,
            "observation_id": canonical_digest(observation_type, result),
            "supervisor_received_wall": wall,
            "supervisor_received_mono": mono,
        }
        self._failpoint("before_dispatch_receipt")
        self._append(
            observation_type, observation, unique_fields=("observation_id",)
        )
        self._failpoint("after_dispatch_receipt")
        if result["status"] != "completed":
            return {
                "schema": INTERVENTION_RECEIPT_SCHEMA,
                "intervention_id": selected_id,
                "recommendation_id": None,
                "kind": None,
                "status": "awaiting_verification",
                "verified": False,
                "effect_id": prepare["effect_id"],
            }

        verifier = self.trusted_intervention_verifier
        if verifier is None or not callable(getattr(verifier, "verify", None)):
            raise RecoverySupervisorError("trusted intervention verifier is unavailable")
        result_identity = canonical_digest("adapter-result", result)
        verify_request = {
            "intervention_id": selected_id,
            "adapter_identity": prepare["adapter_identity"],
            "effect_id": prepare["effect_id"],
            "subject_identity": prepare["subject_identity"],
            "world_state_digest": prepare["world_state_digest"],
            "result_identity": result_identity,
            "result": deepcopy(result["result"]),
        }
        self._failpoint("before_verifier")
        verification = validate_intervention_verifier(
            verifier.verify(deepcopy(verify_request))
        )
        self._failpoint("after_verifier")
        expected_verification = {
            "verifier_identity": self.intervention_verifier_identity,
            "intervention_id": selected_id,
            "adapter_identity": prepare["adapter_identity"],
            "effect_id": prepare["effect_id"],
            "subject_identity": prepare["subject_identity"],
            "world_state_digest": prepare["world_state_digest"],
            "result_identity": result_identity,
        }
        if any(verification[field] != value
               for field, value in expected_verification.items()):
            raise RecoverySupervisorError("intervention verifier binding is invalid")
        self._failpoint("before_verifier_receipt")
        self._append(
            "intervention_verifier_observed", verification,
            unique_fields=("receipt_id",),
        )
        self._failpoint("after_verifier_receipt")
        if verification["status"] != "passed":
            return {
                "schema": INTERVENTION_RECEIPT_SCHEMA,
                "intervention_id": selected_id,
                "recommendation_id": None,
                "kind": None,
                "status": "awaiting_verification",
                "verified": False,
                "effect_id": prepare["effect_id"],
            }
        authorization = next(
            event["payload"] for event in events
            if event["event_type"] == "intervention_authorized"
            and event["payload"]["intervention_id"] == selected_id
        )
        receipt = {
            "schema": INTERVENTION_RECEIPT_SCHEMA,
            "receipt_id": canonical_digest("intervention-receipt", {
                "verification": verification,
                "authorization": authorization,
            }),
            "intervention_id": selected_id,
            "recommendation_id": authorization["recommendation_id"],
            "kind": authorization["kind"], "binding": deepcopy(authorization["binding"]),
            "status": "completed", "verified": True,
            "verifier_receipt_id": verification["receipt_id"],
            "adapter_identity": prepare["adapter_identity"],
            "effect_id": prepare["effect_id"],
            "subject_identity": prepare["subject_identity"],
            "world_state_digest": prepare["world_state_digest"],
            "local_only": True, "external_effect": False,
            "result": deepcopy(result["result"]),
        }
        self._failpoint("before_intervention_receipt")
        self._append(
            "intervention_receipt_recorded", receipt,
            unique_fields=("intervention_id",),
        )
        self._failpoint("after_intervention_receipt")
        return deepcopy(receipt)

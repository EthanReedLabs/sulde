"""Immutable event envelope for authoritative Guardian state transitions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any, Mapping


EVENT_SCHEMA = "sulde-guardian-event-v1"
SUBMISSION_SCHEMA = "sulde-guardian-submission-v1"
_HEX_24 = re.compile(r"^[0-9a-f]{24}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,255}$")
_MAX_PAYLOAD_BYTES = 64 * 1024
_MAX_JSON_DEPTH = 12


class EventProtocolError(ValueError):
    """An event cannot be represented by the authoritative protocol."""


class Provider(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    SYSTEM = "system"
    IMPORT = "import"
    UNKNOWN = "unknown"


class EventDomain(str, Enum):
    INTENT = "intent"
    TASK = "task"
    APPROVAL = "approval"
    EFFECT = "effect"
    INTERVENTION = "intervention"
    SUPERVISOR = "supervisor"


class EventType(str, Enum):
    INTENT_ACTIVATED = "intent.activated"
    INTENT_PAUSED = "intent.paused"
    INTENT_RESUMED = "intent.resumed"
    INTENT_CLOSED = "intent.closed"

    TASK_CREATED = "task.created"
    TASK_BOUND = "task.bound"
    TASK_STARTED = "task.started"
    TASK_AWAITING_HUMAN = "task.awaiting_human"
    TASK_VERIFYING = "task.verifying"
    TASK_SUCCEEDED = "task.succeeded"
    TASK_FAILED = "task.failed"
    TASK_INCONCLUSIVE = "task.inconclusive"

    APPROVAL_ASKED = "approval.asked"
    APPROVAL_REASSESSMENT_DUE = "approval.reassessment_due"
    APPROVAL_DECIDED = "approval.decided"
    APPROVAL_EXPIRED = "approval.expired"

    EFFECT_PREPARED = "effect.prepared"
    EFFECT_DISPATCHED = "effect.dispatched"
    EFFECT_VERIFYING = "effect.verifying"
    EFFECT_VERIFIED = "effect.verified"
    EFFECT_UNKNOWN = "effect.unknown"
    EFFECT_ABORTED = "effect.aborted"

    INTERVENTION_OPENED = "intervention.opened"
    INTERVENTION_ACKNOWLEDGED = "intervention.acknowledged"
    INTERVENTION_RESOLVED = "intervention.resolved"

    SUPERVISOR_GENERATION_ACTIVATED = "supervisor.generation_activated"
    SUPERVISOR_READY = "supervisor.ready"
    SUPERVISOR_DEGRADED = "supervisor.degraded"
    SUPERVISOR_BLOCKED = "supervisor.blocked"
    SUPERVISOR_STOPPED = "supervisor.stopped"


EVENT_DOMAINS = {
    event_type: EventDomain(event_type.value.split(".", 1)[0])
    for event_type in EventType
}


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise EventProtocolError(f"event value is not lossless JSON: {error}") from error


def _plain_json(value: Any, *, depth: int = 0) -> bool:
    if depth > _MAX_JSON_DEPTH:
        return False
    if value is None or type(value) in {str, int, bool}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if type(value) is list:
        return all(_plain_json(item, depth=depth + 1) for item in value)
    if type(value) is dict:
        return all(
            type(key) is str and _plain_json(item, depth=depth + 1)
            for key, item in value.items()
        )
    return False


def _safe_id(value: Any, label: str, *, optional: bool = False) -> str:
    if type(value) is not str:
        raise EventProtocolError(f"{label} must be a string")
    rendered = value.strip()
    if rendered != value:
        raise EventProtocolError(f"{label} must use canonical whitespace")
    if optional and not rendered:
        return ""
    if _SAFE_ID.fullmatch(rendered) is None:
        raise EventProtocolError(f"{label} is not a bounded identifier")
    return rendered


def _timestamp(value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise EventProtocolError("occurred_at must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError) as error:
        raise EventProtocolError("occurred_at is not ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EventProtocolError("occurred_at must include a timezone")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class EventCorrelation:
    intent_id: str
    intent_revision: int
    task_epoch: str
    session_id: str = ""
    task_id: str = ""
    attempt_id: str = ""
    approval_request_id: str = ""
    intervention_id: str = ""
    task_epoch_context_id: str = ""

    def __post_init__(self) -> None:
        _safe_id(self.intent_id, "correlation.intent_id")
        if (
            type(self.intent_revision) is not int
            or type(self.intent_revision) is bool
            or self.intent_revision <= 0
        ):
            raise EventProtocolError(
                "correlation.intent_revision must be a positive integer"
            )
        if type(self.task_epoch) is not str or _HEX_24.fullmatch(self.task_epoch) is None:
            raise EventProtocolError("correlation.task_epoch must be 24 lowercase hex")
        for name in (
            "session_id",
            "task_id",
            "attempt_id",
            "approval_request_id",
            "intervention_id",
        ):
            _safe_id(getattr(self, name), f"correlation.{name}", optional=True)
        if self.task_epoch_context_id and (
            type(self.task_epoch_context_id) is not str
            or _HEX_64.fullmatch(self.task_epoch_context_id) is None
        ):
            raise EventProtocolError(
                "correlation.task_epoch_context_id must be empty or lowercase sha256"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": self.intent_id,
            "intent_revision": self.intent_revision,
            "task_epoch": self.task_epoch,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "approval_request_id": self.approval_request_id,
            "intervention_id": self.intervention_id,
            "task_epoch_context_id": self.task_epoch_context_id,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "EventCorrelation":
        fields = {
            "intent_id",
            "intent_revision",
            "task_epoch",
            "session_id",
            "task_id",
            "attempt_id",
            "approval_request_id",
            "intervention_id",
            "task_epoch_context_id",
        }
        if type(value) is not dict or set(value) != fields:
            raise EventProtocolError("event correlation fields are invalid")
        return cls(**value)


@dataclass(frozen=True)
class EventEnvelope:
    sequence: int
    event_id: str
    previous_event_id: str
    workspace_id: str
    runtime_generation: str
    event_type: EventType
    provider: Provider
    actor: str
    occurred_at: str
    correlation: EventCorrelation
    payload_json: str

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or type(self.sequence) is bool or self.sequence < 1:
            raise EventProtocolError("event sequence must be a positive integer")
        if type(self.event_id) is not str or _HEX_64.fullmatch(self.event_id) is None:
            raise EventProtocolError("event_id must be lowercase sha256")
        if self.previous_event_id and (
            type(self.previous_event_id) is not str
            or _HEX_64.fullmatch(self.previous_event_id) is None
        ):
            raise EventProtocolError("previous_event_id must be empty or lowercase sha256")
        if type(self.workspace_id) is not str or _HEX_64.fullmatch(self.workspace_id) is None:
            raise EventProtocolError("workspace_id must be lowercase sha256")
        if (
            type(self.runtime_generation) is not str
            or _HEX_64.fullmatch(self.runtime_generation) is None
        ):
            raise EventProtocolError("runtime_generation must be lowercase sha256")
        if type(self.event_type) is not EventType or type(self.provider) is not Provider:
            raise EventProtocolError("event enum types are invalid")
        if type(self.correlation) is not EventCorrelation:
            raise EventProtocolError("event correlation must be typed")
        _safe_id(self.actor, "actor")
        normalized_timestamp = _timestamp(self.occurred_at)
        if normalized_timestamp != self.occurred_at:
            raise EventProtocolError("occurred_at must use canonical UTC form")
        try:
            payload = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise EventProtocolError("payload_json is invalid") from error
        if type(payload) is not dict or not _plain_json(payload):
            raise EventProtocolError("event payload must be a bounded plain JSON object")
        canonical_payload = _canonical(payload)
        if canonical_payload != self.payload_json:
            raise EventProtocolError("payload_json must be canonical")
        if len(canonical_payload.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise EventProtocolError("event payload exceeds 64 KiB")
        expected = hashlib.sha256(_canonical(self._core_dict()).encode("utf-8")).hexdigest()
        if self.event_id != expected:
            raise EventProtocolError("event_id does not match the immutable envelope")

    @property
    def domain(self) -> EventDomain:
        return EVENT_DOMAINS[self.event_type]

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    def _core_dict(self) -> dict[str, Any]:
        return {
            "schema": EVENT_SCHEMA,
            "sequence": self.sequence,
            "previous_event_id": self.previous_event_id,
            "workspace_id": self.workspace_id,
            "runtime_generation": self.runtime_generation,
            "domain": self.domain.value,
            "type": self.event_type.value,
            "provider": self.provider.value,
            "actor": self.actor,
            "occurred_at": self.occurred_at,
            "correlation": self.correlation.to_dict(),
            "payload": self.payload,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, **self._core_dict()}

    @classmethod
    def build(
        cls,
        *,
        sequence: int,
        previous_event_id: str,
        workspace_id: str,
        runtime_generation: str,
        event_type: EventType,
        provider: Provider,
        actor: str,
        occurred_at: str,
        correlation: EventCorrelation,
        payload: Mapping[str, Any] | None = None,
    ) -> "EventEnvelope":
        if type(event_type) is not EventType or type(provider) is not Provider:
            raise EventProtocolError("event enum types are invalid")
        if type(correlation) is not EventCorrelation:
            raise EventProtocolError("event correlation must be typed")
        if payload is not None and type(payload) is not dict:
            raise EventProtocolError("event payload must be a plain dict")
        payload_json = _canonical(payload or {})
        provisional = cls.__new__(cls)
        values = {
            "sequence": sequence,
            "previous_event_id": previous_event_id,
            "workspace_id": workspace_id,
            "runtime_generation": runtime_generation,
            "event_type": event_type,
            "provider": provider,
            "actor": actor,
            "occurred_at": _timestamp(occurred_at),
            "correlation": correlation,
            "payload_json": payload_json,
        }
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        event_id = hashlib.sha256(
            _canonical(provisional._core_dict()).encode("utf-8")
        ).hexdigest()
        return cls(event_id=event_id, **values)

    @classmethod
    def from_dict(cls, value: Any) -> "EventEnvelope":
        fields = {
            "schema",
            "sequence",
            "event_id",
            "previous_event_id",
            "workspace_id",
            "runtime_generation",
            "domain",
            "type",
            "provider",
            "actor",
            "occurred_at",
            "correlation",
            "payload",
        }
        if type(value) is not dict or set(value) != fields:
            raise EventProtocolError("event envelope fields are invalid")
        if value.get("schema") != EVENT_SCHEMA:
            raise EventProtocolError("event envelope schema is invalid")
        try:
            event_type = EventType(value["type"])
            provider = Provider(value["provider"])
            domain = EventDomain(value["domain"])
        except (TypeError, ValueError) as error:
            raise EventProtocolError("event envelope enum value is invalid") from error
        if EVENT_DOMAINS[event_type] is not domain:
            raise EventProtocolError("event type belongs to another domain")
        return cls(
            sequence=value["sequence"],
            event_id=value["event_id"],
            previous_event_id=value["previous_event_id"],
            workspace_id=value["workspace_id"],
            runtime_generation=value["runtime_generation"],
            event_type=event_type,
            provider=provider,
            actor=value["actor"],
            occurred_at=value["occurred_at"],
            correlation=EventCorrelation.from_dict(value["correlation"]),
            payload_json=_canonical(value["payload"]),
        )


@dataclass(frozen=True)
class EventSubmission:
    """A producer request whose sequence and ledger head belong to the writer."""

    submission_id: str
    workspace_id: str
    runtime_generation: str
    event_type: EventType
    provider: Provider
    actor: str
    occurred_at: str
    correlation: EventCorrelation
    payload_json: str

    def __post_init__(self) -> None:
        if type(self.submission_id) is not str or _HEX_64.fullmatch(
            self.submission_id
        ) is None:
            raise EventProtocolError("submission_id must be lowercase sha256")
        try:
            payload = json.loads(self.payload_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise EventProtocolError("submission payload JSON is invalid") from error
        probe = EventEnvelope.build(
            sequence=1,
            previous_event_id="",
            workspace_id=self.workspace_id,
            runtime_generation=self.runtime_generation,
            event_type=self.event_type,
            provider=self.provider,
            actor=self.actor,
            occurred_at=self.occurred_at,
            correlation=self.correlation,
            payload=payload,
        )
        if (
            probe.occurred_at != self.occurred_at
            or probe.payload_json != self.payload_json
        ):
            raise EventProtocolError("submission fields must use canonical encoding")
        expected = hashlib.sha256(
            _canonical(self._core_dict()).encode("utf-8")
        ).hexdigest()
        if self.submission_id != expected:
            raise EventProtocolError(
                "submission_id does not match the immutable submission"
            )

    @property
    def domain(self) -> EventDomain:
        return EVENT_DOMAINS[self.event_type]

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    def _core_dict(self) -> dict[str, Any]:
        return {
            "schema": SUBMISSION_SCHEMA,
            "workspace_id": self.workspace_id,
            "runtime_generation": self.runtime_generation,
            "domain": self.domain.value,
            "type": self.event_type.value,
            "provider": self.provider.value,
            "actor": self.actor,
            "occurred_at": self.occurred_at,
            "correlation": self.correlation.to_dict(),
            "payload": self.payload,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"submission_id": self.submission_id, **self._core_dict()}

    def to_envelope(
        self, *, sequence: int, previous_event_id: str
    ) -> EventEnvelope:
        return EventEnvelope.build(
            sequence=sequence,
            previous_event_id=previous_event_id,
            workspace_id=self.workspace_id,
            runtime_generation=self.runtime_generation,
            event_type=self.event_type,
            provider=self.provider,
            actor=self.actor,
            occurred_at=self.occurred_at,
            correlation=self.correlation,
            payload=self.payload,
        )

    @classmethod
    def build(
        cls,
        *,
        workspace_id: str,
        runtime_generation: str,
        event_type: EventType,
        provider: Provider,
        actor: str,
        occurred_at: str,
        correlation: EventCorrelation,
        payload: Mapping[str, Any] | None = None,
    ) -> "EventSubmission":
        probe = EventEnvelope.build(
            sequence=1,
            previous_event_id="",
            workspace_id=workspace_id,
            runtime_generation=runtime_generation,
            event_type=event_type,
            provider=provider,
            actor=actor,
            occurred_at=occurred_at,
            correlation=correlation,
            payload=payload,
        )
        provisional = cls.__new__(cls)
        values = {
            "workspace_id": probe.workspace_id,
            "runtime_generation": probe.runtime_generation,
            "event_type": probe.event_type,
            "provider": probe.provider,
            "actor": probe.actor,
            "occurred_at": probe.occurred_at,
            "correlation": probe.correlation,
            "payload_json": probe.payload_json,
        }
        for name, value in values.items():
            object.__setattr__(provisional, name, value)
        submission_id = hashlib.sha256(
            _canonical(provisional._core_dict()).encode("utf-8")
        ).hexdigest()
        return cls(submission_id=submission_id, **values)

    @classmethod
    def from_dict(cls, value: Any) -> "EventSubmission":
        fields = {
            "schema",
            "submission_id",
            "workspace_id",
            "runtime_generation",
            "domain",
            "type",
            "provider",
            "actor",
            "occurred_at",
            "correlation",
            "payload",
        }
        if type(value) is not dict or set(value) != fields:
            raise EventProtocolError("event submission fields are invalid")
        if value.get("schema") != SUBMISSION_SCHEMA:
            raise EventProtocolError("event submission schema is invalid")
        try:
            event_type = EventType(value["type"])
            provider = Provider(value["provider"])
            domain = EventDomain(value["domain"])
        except (TypeError, ValueError) as error:
            raise EventProtocolError("event submission enum value is invalid") from error
        if EVENT_DOMAINS[event_type] is not domain:
            raise EventProtocolError("event submission type belongs to another domain")
        return cls(
            submission_id=value["submission_id"],
            workspace_id=value["workspace_id"],
            runtime_generation=value["runtime_generation"],
            event_type=event_type,
            provider=provider,
            actor=value["actor"],
            occurred_at=value["occurred_at"],
            correlation=EventCorrelation.from_dict(value["correlation"]),
            payload_json=_canonical(value["payload"]),
        )

"""Read-only adapters and projections for Sulde's existing event logs."""

from __future__ import annotations

import json
import hashlib
import re
import runpy
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Protocol, Sequence


_contract = SimpleNamespace(
    **runpy.run_path(str(Path(__file__).resolve().with_name("event_contract.py")))
)
_projection_cache = SimpleNamespace(
    **runpy.run_path(
        str(Path(__file__).resolve().with_name("event_projection_cache.py"))
    )
)
_privacy = SimpleNamespace(
    **runpy.run_path(
        str(Path(__file__).resolve().with_name("observation_privacy.py"))
    )
)
CORRELATION_KEYS = _contract.CORRELATION_KEYS
DOMAINS = _contract.DOMAINS
EVENT_SCHEMA = _contract.EVENT_SCHEMA
SNAPSHOT_SCHEMA = _contract.SNAPSHOT_SCHEMA
EventContractError = _contract.EventContractError
make_event = _contract.make_event
safe_correlation = _contract.safe_correlation
text_digest = _contract.text_digest
value_digest = _contract.value_digest
validate_event = _contract.validate_event
workspace_identifier = _contract.workspace_identifier
PROJECTION_STATE_VERSION = _projection_cache.STATE_VERSION
ObservationPrivacyError = _privacy.ObservationPrivacyError


class UnsupportedRow(EventContractError):
    """A syntactically valid row does not match a supported legacy shape."""


class RowAdapter(Protocol):
    def __call__(
        self, row: Mapping[str, Any], source: "EventSource", line: int
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class EventSource:
    root: Path
    path: Path
    logical_name: str
    kind: str
    adapter: RowAdapter
    format: str = "jsonl"


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _timestamp(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row[key]
    raise EventContractError("source row is missing its timestamp")


def _phase(value: Any, default: str = "observed") -> str:
    rendered = str(value or "").strip().lower()
    aliases = {
        "start": "started",
        "started": "started",
        "complete": "completed",
        "completed": "completed",
        "decision": "decision",
        "snapshot": "snapshot",
        "finalize": "finalized",
        "finalized": "finalized",
        "observed": "observed",
    }
    return aliases.get(rendered, default)


def _actor(value: Any, default: str = "system") -> str:
    rendered = str(value or "").strip().lower()
    aliases = {
        "claude": "claude",
        "codex": "codex",
        "human": "human",
        "operator": "human",
        "user": "human",
        "system": "system",
    }
    return aliases.get(rendered, default)


def _outcome(value: Any, default: str = "unknown") -> str:
    rendered = str(value or "").strip().lower()
    return rendered or default


def _present_digest(value: Any) -> tuple[bool, str | None]:
    digest = text_digest(value)
    return digest is not None, digest


def _emit(
    source: EventSource,
    line: int,
    row: Mapping[str, Any],
    *,
    domain: str,
    event_type: str,
    occurred_at: Any,
    phase: str = "observed",
    outcome: Any = "unknown",
    provider: Any = "system",
    actor: Any = "system",
    correlation: Mapping[str, Any] | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return make_event(
        domain=domain,
        event_type=event_type,
        occurred_at=occurred_at,
        phase=phase,
        outcome=outcome,
        provider=provider,
        actor=actor,
        correlation=correlation,
        source_kind=source.kind,
        source_name=source.logical_name,
        source_line=line,
        raw_row=row,
        attributes=attributes,
    )


def adapt_intent(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    event = _as_mapping(row.get("event"))
    if event:
        decision = _as_mapping(row.get("decision"))
        contract = _as_mapping(row.get("contract"))
        target_present, target_sha256 = _present_digest(event.get("target"))
        result_present, result_sha256 = _present_digest(event.get("result_target"))
        parent_skills = _as_list(event.get("parent_skills"))
        provider = event.get("provider") or "unknown"
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.observation",
            occurred_at=_timestamp(event, "at"),
            phase=_phase(event.get("phase")),
            outcome=decision.get("action") or decision.get("would_action") or "observed",
            provider=provider,
            actor=provider if provider in {"claude", "codex"} else "agent",
            correlation={
                "intent_id": event.get("intent_id") or contract.get("intent_id"),
                "intent_revision": event.get("intent_revision") or contract.get("revision"),
                "session_id": event.get("session_id"),
            },
            attributes={
                "action_name": str(event.get("action") or "unknown")[:256],
                "arguments_sha256": event.get("arguments_digest"),
                "awaiting_human": decision.get("awaiting_human"),
                "capability_name": str(event.get("capability") or "unknown")[:256],
                "decision_action": decision.get("action"),
                "effect": event.get("effect"),
                "event_kind": event.get("kind"),
                "observation_source": event.get("observation_source"),
                "parent_skill_count": len(parent_skills),
                "result_target_present": result_present,
                "result_target_sha256": result_sha256,
                "severity": decision.get("severity"),
                "source_event_id_sha256": text_digest(event.get("event_id")),
                "success": event.get("success"),
                "target_present": target_present,
                "target_sha256": target_sha256,
                "verification_required": decision.get("verification_required"),
                "would_action": decision.get("would_action"),
            },
        )

    schema = str(row.get("schema") or "")
    correlation = {
        "intent_id": row.get("intent_id"),
        "intent_revision": row.get("intent_revision") or row.get("revision"),
        "session_id": row.get("session_id"),
    }
    if schema == "sulde-continuation-event-v1":
        action = str(row.get("action") or "observed")
        phase = {
            "created": "started",
            "loaded": "observed",
            "acknowledged": "completed",
        }.get(action, "observed")
        return _emit(
            source,
            line,
            row,
            domain="context",
            event_type="context.continuation",
            occurred_at=_timestamp(row, "at"),
            phase=phase,
            outcome=action,
            provider=row.get("provider"),
            actor="intent-guardian",
            correlation=correlation,
            attributes={
                "action_name": action,
                "authority_transferred": row.get("authority_transferred"),
                "capsule_id_sha256": text_digest(row.get("capsule_id")),
                "context_chars": row.get("context_chars"),
                "proposal_digest_sha256": text_digest(row.get("proposal_digest")),
                "source_provider": row.get("source_provider"),
                "source_session_id_present": row.get("source_session_id_present"),
            },
        )
    if schema == "sulde-intent-control-event-v1":
        detail_present, detail_sha256 = _present_digest(row.get("detail"))
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.control",
            occurred_at=_timestamp(row, "at"),
            phase="decision",
            outcome=row.get("action") or "control",
            actor=_actor(row.get("actor")),
            correlation=correlation,
            attributes={
                "action_name": row.get("action"),
                "detail_present": detail_present,
                "detail_sha256": detail_sha256,
                "receipt_id_sha256": text_digest(row.get("receipt_id")),
            },
        )
    if schema == "sulde-correction-pause-v1":
        intervention_ids = [
            str(value)
            for value in _as_list(row.get("intervention_ids"))
            if str(value).strip()
        ]
        if not intervention_ids:
            raise EventContractError(
                "managed correction pause has no intervention identity"
            )
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.correction_pause",
            occurred_at=_timestamp(row, "at"),
            phase="decision",
            outcome="paused",
            actor="intent-guardian",
            correlation=correlation,
            attributes={
                "action_name": row.get("action"),
                "intervention_count": len(intervention_ids),
                "interventions_sha256": value_digest(intervention_ids),
            },
        )
    if schema == "sulde-intent-critic-event-v1":
        result = _as_mapping(row.get("result"))
        evidence = _as_list(result.get("evidence"))
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.critic",
            occurred_at=_timestamp(row, "at"),
            phase="decision",
            outcome=row.get("action") or result.get("verdict") or "observed",
            actor="intent-critic",
            correlation=correlation,
            attributes={
                "action_name": row.get("action"),
                "confidence": result.get("confidence"),
                "evidence_count": len(evidence),
                "result_sha256": value_digest(result),
                "source_event_id_sha256": text_digest(row.get("event_id")),
                "verdict": result.get("verdict"),
            },
        )
    if schema == "sulde-guardian-integrity-breach-v1":
        reason_present, reason_sha256 = _present_digest(row.get("reason"))
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.integrity",
            occurred_at=_timestamp(row, "at"),
            phase="decision",
            outcome="paused",
            actor="intent-guardian",
            correlation=correlation,
            attributes={
                "action_name": row.get("action"),
                "reason_present": reason_present,
                "reason_sha256": reason_sha256,
            },
        )
    if schema == "sulde-guardian-turn-finalize-v1":
        interrupted = _as_list(row.get("interrupted_events"))
        closed_skills = _as_list(row.get("closed_skills"))
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.turn_finalize",
            occurred_at=_timestamp(row, "at"),
            phase="finalized",
            outcome=row.get("outcome") or "inconclusive",
            provider=row.get("provider"),
            actor="intent-guardian",
            correlation=correlation,
            attributes={
                "closed_skill_count": len(closed_skills),
                "interrupted_event_count": len(interrupted),
                "intervention_count": len(_as_list(row.get("intervention_ids"))),
            },
        )
    raise UnsupportedRow("intent audit schema is missing or unsupported")


def adapt_intervention(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    schema = row.get("schema")
    if schema not in {
        "sulde-intervention-event-v1",
        "sulde-intervention-event-v2",
    }:
        raise UnsupportedRow("external-effect intervention schema is unsupported")
    source_type = str(row.get("type") or "")
    correlation = {
        "intent_id": row.get("intent_id"),
        "intent_revision": row.get("intent_revision"),
        "session_id": row.get("session_id"),
        "task_id": row.get("task_id"),
    }
    common = {
        "attempt_id_sha256": text_digest(row.get("attempt_id")),
        "intervention_id_sha256": text_digest(row.get("intervention_id")),
        "capability_name": row.get("capability"),
        "effect": row.get("effect"),
        "target_sha256": row.get("target_sha256"),
        "verification_kind": row.get("verification_kind"),
        "verification_sha256": row.get("verification_sha256"),
    }
    if source_type in {"effect.batch_prepared", "effect.batch_dispatched"}:
        if schema != "sulde-intervention-event-v2":
            raise UnsupportedRow("effect batch observation requires intervention v2")
        prepared = source_type == "effect.batch_prepared"
        resources = _as_list(row.get("resources")) if prepared else []
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.effect_batch",
            occurred_at=_timestamp(row, "at"),
            phase="started" if prepared else "completed",
            outcome="prepared" if prepared else "dispatched",
            provider=row.get("provider"),
            actor="intent-guardian",
            correlation=correlation,
            attributes={
                "batch_sha256": text_digest(row.get("batch_id")),
                "batch_semantics_sha256": row.get("batch_semantics_sha256"),
                "call_sha256": text_digest(row.get("call_id")),
                "capability_name": row.get("capability"),
                "effect": row.get("effect"),
                "prepared_event_sha256": text_digest(row.get("prepared_event_id")),
                "resource_count": len(resources) if prepared else None,
                "resource_set_sha256": row.get("resource_set_sha256"),
            },
        )
    if source_type == "effect.attempt_created":
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.effect_attempt",
            occurred_at=_timestamp(row, "at"),
            phase="started",
            outcome=row.get("state") or "authorized",
            provider=row.get("provider"),
            actor="intent-guardian",
            correlation=correlation,
            attributes={
                **common,
                "predecessor_attempt_sha256": text_digest(row.get("predecessor_attempt_id")),
                "state_source": row.get("state_source"),
            },
        )
    if source_type == "effect.attempt_transitioned":
        terminal = row.get("state") in {
            "system_verified",
            "human_attested_success",
            "confirmed_failed",
        }
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.effect_attempt",
            occurred_at=_timestamp(row, "at"),
            phase="completed" if terminal else "observed",
            outcome=row.get("state") or "unknown",
            provider=row.get("provider"),
            actor=str(row.get("state_source") or "effect-intervention"),
            correlation=correlation,
            attributes={
                **common,
                "evidence_sha256": row.get("evidence_sha256"),
                "verification_event_sha256": text_digest(row.get("verification_event_id")),
                "verification_capability": row.get("verification_capability"),
            },
        )
    if source_type == "effect.attempt_target_resolved":
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.effect_target",
            occurred_at=_timestamp(row, "at"),
            outcome="resolved",
            provider=row.get("provider"),
            actor="intent-guardian",
            correlation=correlation,
            attributes=common,
        )
    if source_type.startswith("intent.intervention_"):
        decision = row.get("decision")
        phase = "decision" if source_type.endswith(("resolved", "acknowledged")) else "started"
        return _emit(
            source,
            line,
            row,
            domain="intent",
            event_type="intent.intervention",
            occurred_at=_timestamp(row, "at"),
            phase=phase,
            outcome=decision or source_type.removeprefix("intent.intervention_"),
            provider=row.get("provider"),
            actor=str(row.get("actor") or "effect-intervention"),
            correlation=correlation,
            attributes={
                **common,
                "decision_name": decision,
                "evidence_sha256": text_digest(row.get("evidence")),
                "retry_attempt_sha256": text_digest(row.get("retry_attempt_id")),
            },
        )
    if source_type == "notification.intervention_requested":
        return _emit(
            source,
            line,
            row,
            domain="notification",
            event_type="notification.intervention",
            occurred_at=_timestamp(row, "at"),
            outcome="requested",
            provider=row.get("provider"),
            actor="effect-intervention",
            correlation=correlation,
            attributes=common,
        )
    raise UnsupportedRow(f"unsupported external-effect event type: {source_type}")


def adapt_correction_intervention(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if row.get("schema") != "sulde-correction-intervention-event-v1":
        raise UnsupportedRow("correction intervention schema is unsupported")
    source_type = str(row.get("type") or "")
    if source_type == "correction.intervention_proposed":
        phase = "started"
        outcome = "proposed"
    elif source_type == "correction.intervention_transitioned":
        outcome = str(row.get("state") or "unknown")
        phase = "completed" if outcome in {
            "applied",
            "rejected",
            "unsupported",
            "cancelled",
        } else "decision"
    else:
        raise UnsupportedRow(
            f"unsupported correction intervention type: {source_type}"
        )
    intent_digest = str(row.get("intent_id_sha256") or "")
    lane_digest = str(row.get("lane_sha256") or "")
    return _emit(
        source,
        line,
        row,
        domain="intent",
        event_type="intent.correction_intervention",
        occurred_at=_timestamp(row, "at"),
        phase=phase,
        outcome=outcome,
        provider=row.get("provider"),
        actor=str(row.get("actor") or "correction-intervention"),
        correlation={
            "intent_id": f"sha256:{intent_digest[:24]}" if intent_digest else None,
            "intent_revision": row.get("intent_revision"),
            "session_id": f"sha256:{lane_digest[:24]}" if lane_digest else None,
        },
        attributes={
            "boundary": row.get("boundary"),
            "correction_sha256": row.get("correction_sha256"),
            "event_name": source_type,
            "intervention_sha256": text_digest(row.get("intervention_id")),
            "reason_code": row.get("reason_code"),
            "semantic_acceptance": "unknown",
            "source_name": row.get("source"),
        },
    )


def adapt_approval_pair(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    schema = row.get("schema")
    if schema not in {
        "sulde-approval-pair-event-v1",
        "sulde-approval-pair-event-v2",
    }:
        raise UnsupportedRow("approval pair schema is unsupported")
    event_type = str(row.get("type") or "")
    if event_type == "approval.asked":
        phase = "started"
        outcome = "asked"
    elif event_type == "approval.prompt-observed" and schema == "sulde-approval-pair-event-v2":
        phase = "observed"
        outcome = "observed"
    elif event_type == "approval.replaced" and schema == "sulde-approval-pair-event-v2":
        phase = "completed"
        outcome = "replaced"
    elif event_type == "approval.decided":
        phase = "decision"
        outcome = str(row.get("outcome") or "unknown")
    else:
        raise UnsupportedRow(f"unsupported approval pair type: {event_type}")
    intent_digest = str(row.get("intent_id_sha256") or "")
    lane_digest = str(row.get("lane_sha256") or "")
    return _emit(
        source,
        line,
        row,
        domain="approval",
        event_type="approval.intent",
        occurred_at=_timestamp(row, "at"),
        phase=phase,
        outcome=outcome,
        provider=row.get("provider"),
        actor=_actor(row.get("actor"), "intent-guardian"),
        correlation={
            "intent_id": f"sha256:{intent_digest[:24]}" if intent_digest else None,
            "intent_revision": row.get("intent_revision"),
            "session_id": f"sha256:{lane_digest[:24]}" if lane_digest else None,
        },
        attributes={
            "approval_kind": row.get("kind"),
            "event_name": event_type,
            "receipt_sha256": row.get("receipt_sha256"),
            "request_sha256": text_digest(row.get("request_id")),
            "source_name": row.get("source"),
            "target_sha256": row.get("target_sha256"),
            "card_sha256": row.get("card_sha256"),
            "workspace_sha256": row.get("workspace_sha256"),
            "proposal_sha256": row.get("proposal_sha256"),
            "decision_route": row.get("route"),
            "expires_at": row.get("expires_at"),
        },
    )


def _self_repair_authority_debt(row: Mapping[str, Any]) -> bool:
    effect = str(row.get("effect") or row.get("effect_class") or "").lower()
    if effect in {"external", "external_write", "destructive", "unknown"}:
        return True
    if row.get("unknown_effect") is True or row.get("awaiting_human") is True:
        return True
    for key in (
        "open_events", "open_event_ids", "pending_attempts", "attempt_ids",
        "grants", "grant_ids", "pending_verifications", "verification_ids",
        "intervention_ids",
    ):
        value = row.get(key)
        if isinstance(value, (list, dict)) and bool(value):
            return True
        if isinstance(value, str) and value.strip():
            return True
    return str(row.get("status") or "") in {"awaiting_human", "paused", "executing"}


def _self_repair_has_evidence(row: Mapping[str, Any]) -> bool:
    direct = any(
        str(row.get(key) or "").strip()
        for key in (
            "resolution_evidence", "evidence_sha256", "verification_sha256",
            "terminal_evidence_sha256",
        )
    )
    checks = _as_list(row.get("checks"))
    return direct or bool(checks) and all(
        isinstance(check, dict) and check.get("passed") is True for check in checks
    )


def _self_repair_state(row: Mapping[str, Any]) -> str:
    if _self_repair_authority_debt(row):
        return "unresolved"
    explicit = str(row.get("closure_status") or "")
    if explicit in {"inconclusive", "verified", "unresolved", "superseded", "expired"}:
        if explicit == "verified" and not _self_repair_has_evidence(row):
            return "inconclusive"
        return explicit
    status = str(row.get("status") or "unknown")
    if status in {"failed", "timeout", "aborted"}:
        return "unresolved"
    if status in {"rejected", "superseded"}:
        return "superseded"
    if status in {"resolved", "executed", "success", "verified"}:
        return "verified" if _self_repair_has_evidence(row) else "inconclusive"
    return "inconclusive"


def adapt_self_repair_queue(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if not row.get("slug") or not row.get("status"):
        raise UnsupportedRow("self-repair queue row is missing slug/status")
    occurred_at = _timestamp(
        row,
        "last_seen_at",
        "resolved_at",
        "executed_at",
        "diagnosed_at",
        "failed_at",
        "awaiting_human_at",
        "paused_at",
        "decided_at",
        "drafted_at",
        "draft_error_at",
        "first_seen_at",
        "at",
    )
    closure = _self_repair_state(row)
    return _emit(
        source,
        line,
        row,
        domain="lifecycle",
        event_type="lifecycle.self_repair_queue",
        occurred_at=occurred_at,
        phase="finalized" if closure in {"verified", "superseded", "expired"} else "observed",
        outcome=closure,
        provider=row.get("provider"),
        actor="self-repair",
        correlation={
            "project_id": row.get("project_id") or row.get("workspace_id"),
            "session_id": row.get("session_id"),
            "lane_id": row.get("lane_id"),
            "task_id": row.get("slug"),
            "task_instance_id": row.get("task_instance_id") or row.get("task_epoch") or row.get("slug"),
        },
        attributes={
            "attempt_count": row.get("attempts", 0),
            "authority_debt": _self_repair_authority_debt(row),
            "fingerprint_sha256": (
                row.get("fingerprint")
                if re.fullmatch(r"[0-9a-f]{64}", str(row.get("fingerprint") or ""))
                else value_digest(
                    {
                        "source": row.get("source"),
                        "severity": row.get("severity"),
                        "title": row.get("title"),
                        "experiment_id": row.get("experiment_id"),
                    }
                )
            ),
            "legacy_status": row.get("status"),
            "task_type": row.get("task_type"),
        },
    )


def adapt_evolution_snapshot(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if not row.get("id") or not row.get("status"):
        raise UnsupportedRow("evolution item is missing id/status")
    observations = _as_list(row.get("observations"))
    latest_observation = observations[-1] if observations and isinstance(observations[-1], dict) else {}
    return _emit(
        source,
        line,
        row,
        domain="lifecycle",
        event_type="lifecycle.evolution",
        occurred_at=_timestamp(
            row, "decided_at", "last_observed_at", "observation_started_at",
            "generated_at", "created_at",
        ),
        phase="finalized" if row.get("status") in {"retained", "rolled_back", "inconclusive", "rejected"} else "observed",
        outcome=row.get("status"),
        actor="organ-evolution",
        correlation={
            "experiment_id": row.get("id"),
            "task_id": row.get("task_slug"),
        },
        attributes={
            "metric_name": row.get("metric"),
            "observation_count": len(observations),
            "latest_value": latest_observation.get("value"),
            "organ_name": row.get("organ"),
        },
    )


def adapt_life_snapshot(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if row.get("schema") not in {"sulde-life-cycle-v1", "sulde-life-cycle-v2"}:
        raise UnsupportedRow("life state schema is unsupported")
    closed = _as_mapping(row.get("closed_loop"))
    dimensions = _as_mapping(closed.get("dimensions"))
    return _emit(
        source,
        line,
        row,
        domain="lifecycle",
        event_type="lifecycle.closed_loop",
        occurred_at=_timestamp(row, "generated_at"),
        phase="snapshot",
        outcome=row.get("status") or "degraded",
        actor="life-cycle",
        correlation={},
        attributes={
            "act_ready": bool(dimensions.get("act", closed.get("act_within_boundary"))),
            "decide_ready": bool(dimensions.get("decide", closed.get("decide"))),
            "human_gates_ready": bool(
                _as_mapping(closed.get("human_gates")).get(
                    "preserved", closed.get("human_gates_preserved")
                )
            ),
            "identity_resume_ready": bool(
                _as_mapping(closed.get("identity_resume")).get(
                    "guarded", closed.get("identity_guarded_resume")
                )
            ),
            "overall_ready": bool(closed.get("overall_ready", row.get("status") == "ready")),
            "persist_ready": bool(dimensions.get("persist", closed.get("persist"))),
            "sense_ready": bool(dimensions.get("sense", closed.get("sense"))),
            "verify_ready": bool(dimensions.get("verify", closed.get("verify"))),
        },
    )


def adapt_agent_experience(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if row.get("schema") != "sulde-agent-experience-v1":
        raise UnsupportedRow("agent experience schema is unsupported")
    evidence = _as_list(row.get("evidence"))
    return _emit(
        source,
        line,
        row,
        domain="knowledge",
        event_type="knowledge.agent_experience",
        occurred_at=_timestamp(row, "occurred_at"),
        phase="finalized",
        outcome=row.get("outcome"),
        actor="managed-agent",
        correlation={},
        attributes={
            "evidence_count": len(evidence),
            "experience_sha256": row.get("experience_id"),
            "problem_type_sha256": text_digest(row.get("problem_type")),
            "recommended_test_count": len(_as_list(row.get("recommended_tests"))),
        },
    )


def adapt_test_evidence(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if row.get("schema") not in {"sulde-test-evidence-v1", "sulde-test-evidence-v2"}:
        raise UnsupportedRow("test evidence schema is unsupported")
    return _emit(
        source,
        line,
        row,
        domain="execution",
        event_type="execution.test_evidence",
        occurred_at=_timestamp(row, "ended_at", "started_at"),
        phase="finalized",
        outcome=row.get("status") or "unknown",
        actor="test-evidence",
        correlation={"run_id": row.get("run_id")},
        attributes={
            "command_sha256": row.get("command_sha256"),
            "duration_seconds": row.get("duration_seconds"),
            "exit_code": row.get("exit_code"),
            "risk": row.get("risk"),
            "suite_name": row.get("suite"),
            "test_count": len(_as_list(row.get("tests"))),
        },
    )


def adapt_projection_settlement(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if row.get("schema") != "sulde-observation-settlement-v1":
        raise UnsupportedRow("observation settlement schema is unsupported")
    outcome = str(row.get("outcome") or "")
    if outcome not in {"inconclusive", "superseded"}:
        raise EventContractError("observation settlement cannot assert success")
    target = str(row.get("target_fingerprint") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", target):
        raise EventContractError("observation settlement target fingerprint is invalid")
    return _emit(
        source,
        line,
        row,
        domain="lifecycle",
        event_type="lifecycle.event_settlement",
        occurred_at=_timestamp(row, "at"),
        phase="finalized",
        outcome=outcome,
        actor=str(row.get("actor") or "observer"),
        correlation={},
        attributes={
            "original_category": row.get("original_category"),
            "target_fingerprint": target,
        },
    )


def adapt_self_repair_approval(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if not row.get("slug") or not row.get("decision"):
        raise UnsupportedRow("self-repair approval row is missing slug/decision")
    reason_present, reason_sha256 = _present_digest(row.get("reason"))
    return _emit(
        source,
        line,
        row,
        domain="approval",
        event_type="approval.self_repair",
        occurred_at=_timestamp(row, "at"),
        phase="decision",
        outcome=row.get("decision"),
        actor=_actor(row.get("by"), "human"),
        correlation={
            "project_id": row.get("project_id") or row.get("workspace_id"),
            "session_id": row.get("session_id"),
            "lane_id": row.get("lane_id"),
            "task_id": row.get("slug"),
            "task_instance_id": row.get("task_instance_id") or row.get("task_epoch") or row.get("slug"),
        },
        attributes={
            "reason_present": reason_present,
            "reason_sha256": reason_sha256,
            "task_type": row.get("task_type"),
        },
    )


def adapt_self_repair_execution(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if not row.get("slug") or not row.get("status"):
        raise UnsupportedRow("self-repair execution row is missing slug/status")
    checks = _as_list(row.get("checks"))
    passed = sum(
        1 for check in checks if isinstance(check, dict) and check.get("passed") is True
    )
    reason_present, reason_sha256 = _present_digest(row.get("reason"))
    evidence_present, evidence_sha256 = _present_digest(row.get("evidence"))
    return _emit(
        source,
        line,
        row,
        domain="execution",
        event_type="execution.self_repair",
        occurred_at=_timestamp(row, "at"),
        phase="finalized",
        outcome=row.get("status"),
        actor=_actor(row.get("by")),
        correlation={
            "project_id": row.get("project_id") or row.get("workspace_id"),
            "session_id": row.get("session_id"),
            "lane_id": row.get("lane_id"),
            "task_id": row.get("slug"),
            "task_instance_id": row.get("task_instance_id") or row.get("task_epoch") or row.get("slug"),
        },
        attributes={
            "check_count": len(checks),
            "diagnostic_outcome": row.get("diagnostic_outcome"),
            "evidence_present": evidence_present,
            "evidence_sha256": evidence_sha256,
            "passed_check_count": passed,
            "reason_present": reason_present,
            "reason_sha256": reason_sha256,
            "report_sha256": text_digest(row.get("report")),
            "verify_root_sha256": text_digest(row.get("verify_root")),
            "verify_scope": row.get("verify_scope"),
        },
    )


def adapt_recall(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    injected = _as_list(row.get("injected"))
    scores = _as_list(row.get("top_scores"))
    recall_source = str(row.get("source") or "kb").lower()
    if recall_source not in {"kb", "mem"}:
        raise UnsupportedRow("recall source is unsupported")
    domain = "memory" if recall_source == "mem" else "knowledge"
    provider = row.get("source_host") or row.get("channel") or "unknown"
    return _emit(
        source,
        line,
        row,
        domain=domain,
        event_type=f"{domain}.recall",
        occurred_at=_timestamp(row, "ts"),
        outcome="injected" if injected else "empty",
        provider=provider,
        actor="recall-hook",
        correlation={
            "opportunity_id": row.get("opportunity_id"),
            "session_id": row.get("session_id"),
            "workspace_id": workspace_identifier(row.get("cwd")),
        },
        attributes={
            "cli_detail_sha256": text_digest(row.get("cli_detail")),
            "cli_status": row.get("cli_status"),
            "injected_count": len(injected),
            "platform": row.get("platform"),
            "query_head_sha256": text_digest(row.get("query_head")),
            "score_count": len(scores),
        },
    )


def adapt_memory_adoption(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if row.get("verdict") not in {"adopted", "ignored"}:
        raise UnsupportedRow("memory adoption row has an unsupported verdict")
    return _emit(
        source,
        line,
        row,
        domain="memory",
        event_type="memory.adoption",
        occurred_at=_timestamp(row, "ts"),
        outcome=row.get("verdict"),
        provider=row.get("channel") or "unknown",
        actor="mem-capture",
        correlation={
            "opportunity_id": row.get("opportunity_id"),
            "session_id": row.get("session_id"),
        },
        attributes={
            "entry_id_sha256": value_digest(row.get("entry_id")),
            "matched_by": row.get("matched_by"),
        },
    )


def adapt_memory_adoption_health(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    status = str(row.get("status") or "").strip().lower()
    if status not in {"classified", "skipped", "write_failed"}:
        raise UnsupportedRow("memory adoption health row has an unsupported status")
    skip_reason = str(row.get("skip_reason") or "").strip().lower()
    if skip_reason not in {
        "",
        "empty_or_invalid_injected",
        "invalid_injected_ids",
    }:
        raise UnsupportedRow("memory adoption health row has an unsupported skip reason")
    error_kind = str(row.get("error") or "").strip()
    if error_kind and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error_kind) is None:
        raise EventContractError("memory adoption health error must be an exception type")
    event_count = row.get("event_count")
    if event_count is not None and (
        isinstance(event_count, bool)
        or not isinstance(event_count, int)
        or event_count < 0
    ):
        raise EventContractError("memory adoption health event_count must be non-negative")
    return _emit(
        source,
        line,
        row,
        domain="memory",
        event_type="memory.adoption_health",
        occurred_at=_timestamp(row, "ts"),
        outcome=status,
        provider="system",
        actor="mem-capture",
        correlation={
            "opportunity_id": row.get("opportunity_id"),
            "session_id": row.get("session_id"),
        },
        attributes={
            "error_kind": error_kind or None,
            "event_count": event_count,
            "skip_reason": skip_reason or None,
        },
    )


def adapt_sediment_decision(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    decision = _as_mapping(row.get("decision"))
    if not decision or not decision.get("action"):
        raise UnsupportedRow("sedimentation row is missing its decision")
    run_match = re.search(r"decisions-(\d{8}-\d{6})\.jsonl$", source.logical_name)
    return _emit(
        source,
        line,
        row,
        domain="sedimentation",
        event_type="sedimentation.decision",
        occurred_at=_timestamp(row, "ts"),
        phase="decision",
        outcome=decision.get("action"),
        actor="sedimentation-router",
        correlation={"run_id": run_match.group(1) if run_match else None},
        attributes={
            "candidate_line_index": row.get("candidate_line_index"),
            "container_name": decision.get("container"),
            "context_sha256": row.get("context_sha256"),
            "decision_sha256": value_digest(decision),
            "doc_id_sha256": text_digest(decision.get("doc_id")),
            "lesson_sha256": text_digest(row.get("lesson")),
            "target_doc_id_sha256": text_digest(decision.get("target_doc_id")),
        },
    )


def adapt_governance_history(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    values = _as_mapping(row.get("values"))
    if not row.get("period") or not values:
        raise UnsupportedRow("governance history row is missing period/values")
    return _emit(
        source,
        line,
        row,
        domain="governance",
        event_type="governance.snapshot",
        occurred_at=_timestamp(row, "collected_at"),
        phase="snapshot",
        outcome="collected",
        actor="governance-weekly",
        correlation={"run_id": row.get("period")},
        attributes={
            "metric_count": len(values),
            "values_sha256": value_digest(values),
        },
    )


def adapt_evolution_decision(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if not row.get("experiment_id") or not row.get("decision"):
        raise UnsupportedRow("evolution decision is missing experiment_id/decision")
    evidence_present, evidence_sha256 = _present_digest(row.get("evidence"))
    return _emit(
        source,
        line,
        row,
        domain="lifecycle",
        event_type="lifecycle.evolution_decision",
        occurred_at=_timestamp(row, "decided_at"),
        phase="decision",
        outcome=row.get("decision"),
        actor="human",
        correlation={"experiment_id": row.get("experiment_id")},
        attributes={
            "evidence_present": evidence_present,
            "evidence_sha256": evidence_sha256,
        },
    )


def adapt_golden_review(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    decisions = _as_list(row.get("decisions"))
    if not row.get("event_id") or not decisions:
        raise UnsupportedRow("golden review is missing event_id/decisions")
    actions = Counter(
        str(item.get("action") or "unknown")
        for item in decisions
        if isinstance(item, dict)
    )
    return _emit(
        source,
        line,
        row,
        domain="approval",
        event_type="approval.golden_review",
        occurred_at=_timestamp(row, "reviewed_at"),
        phase="decision",
        outcome="reviewed",
        actor="human",
        correlation={"review_id": row.get("event_id")},
        attributes={
            "accepted_count": actions.get("accept", 0),
            "decision_count": len(decisions),
            "decisions_sha256": value_digest(decisions),
            "rejected_count": actions.get("reject", 0),
            "remaining_count": row.get("remaining"),
        },
    )


def adapt_feedback(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if not row.get("event") or not row.get("session_id"):
        raise UnsupportedRow("feedback row is missing event/session_id")
    return _emit(
        source,
        line,
        row,
        domain="knowledge",
        event_type="knowledge.feedback",
        occurred_at=_timestamp(row, "ts"),
        outcome=row.get("event"),
        actor="feedback-hook",
        correlation={"session_id": row.get("session_id")},
        attributes={"doc_id_sha256": text_digest(row.get("doc_id"))},
    )


def adapt_notification(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    message = row.get("message")
    if not isinstance(message, str):
        raise UnsupportedRow("notification row is missing message")
    return _emit(
        source,
        line,
        row,
        domain="notification",
        event_type="notification.emit",
        occurred_at=_timestamp(row, "ts"),
        outcome="emitted",
        actor="notification-hook",
        correlation={"workspace_id": workspace_identifier(row.get("cwd"))},
        attributes={
            "message_length": len(message),
            "message_sha256": text_digest(message),
        },
    )


def adapt_host_capability(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if row.get("schema") != "sulde-host-capability-observation-v1":
        raise UnsupportedRow("host capability observation schema is unsupported")
    if row.get("outcome") != "observed":
        raise EventContractError("host capability observation outcome must be observed")
    return _emit(
        source,
        line,
        row,
        domain="lifecycle",
        event_type="lifecycle.host_capability",
        occurred_at=_timestamp(row, "at"),
        phase="observed",
        outcome="observed",
        provider=row.get("provider"),
        actor=row.get("provider") or "system",
        correlation={
            "session_id": row.get("session_id"),
            "workspace_id": row.get("workspace_id"),
        },
        attributes={
            "capability_name": row.get("capability_id"),
            "contract_version": row.get("contract_version"),
            "hook_event": row.get("hook_event"),
            "observation_source": row.get("source"),
            "runtime_sha256": row.get("runtime_sha256"),
            "source_event_id_sha256": text_digest(row.get("event_id")),
        },
    )


def adapt_run_event(
    row: Mapping[str, Any], source: EventSource, line: int
) -> dict[str, Any]:
    if row.get("schema") != "sulde-run-event-v1":
        raise UnsupportedRow("managed run event schema is unsupported")
    event_type = str(row.get("type") or "")
    phase = {
        "execution.requested": "started",
        "execution.started": "started",
        "execution.interrupt_requested": "decision",
        "execution.recovery_blocked": "observed",
        "execution.result": "completed",
        "execution.disposed": "finalized",
        "execution.start_failed": "completed",
    }.get(event_type)
    if phase is None:
        raise UnsupportedRow("managed run event type is unsupported")
    outcome = (
        row.get("stop_reason")
        if event_type == "execution.result"
        else "quiescent"
        if event_type == "execution.disposed" and row.get("quiescent") is True
        else "cleanup_failed"
        if event_type == "execution.disposed"
        else "failed"
        if event_type == "execution.start_failed"
        else "requested"
        if event_type == "execution.interrupt_requested"
        else "unknown"
        if event_type == "execution.recovery_blocked"
        else "observed"
    )
    return _emit(
        source,
        line,
        row,
        domain="execution",
        event_type="execution.run",
        occurred_at=_timestamp(row, "at"),
        phase=phase,
        outcome=outcome,
        provider=row.get("provider"),
        actor="execution-backend",
        correlation={
            "continuation_id": (
                row.get("continuation_id")
                if row.get("continuation_kind") == "formal"
                and row.get("authority_transferred") is False
                else None
            ),
            "lane_id": row.get("lane_id"),
            "project_id": row.get("project_id") or row.get("workspace_id"),
            "run_id": row.get("run_id"),
            "session_id": row.get("session_id"),
            "task_id": row.get("task_id"),
            "task_instance_id": row.get("task_instance_id") or row.get("task_epoch"),
            "workspace_id": row.get("workspace_id"),
        },
        attributes={
            "command_sha256": row.get("command_sha256"),
            "error_count": row.get("error_count"),
            "errors_sha256": row.get("errors_sha256"),
            "event_name": event_type,
            "output_present": row.get("output_present"),
            "output_sha256": row.get("output_sha256"),
            "pid_present": row.get("pid") is not None,
            "returncode": row.get("returncode"),
            "stop_reason": row.get("stop_reason"),
            "tree_scope": row.get("tree_scope"),
            "reason_code": row.get("reason_code"),
            "recovered_from_crash": row.get("recovered_from_crash"),
        },
    )


_HOME_EXACT_SOURCES: tuple[tuple[str, str, RowAdapter], ...] = (
    ("host-capabilities.jsonl", "host-capability", adapt_host_capability),
    ("self-repair/approvals.jsonl", "self-repair-approval", adapt_self_repair_approval),
    ("self-repair/executed.jsonl", "self-repair-execution", adapt_self_repair_execution),
    ("experience/agent.jsonl", "agent-experience", adapt_agent_experience),
    ("projections/event-settlements.jsonl", "observation-settlement", adapt_projection_settlement),
    ("recall-log.jsonl", "recall", adapt_recall),
    ("mem-adoption-log.jsonl", "memory-adoption", adapt_memory_adoption),
    (
        "mem-adoption-health.jsonl",
        "memory-adoption-health",
        adapt_memory_adoption_health,
    ),
    ("governance/history.jsonl", "governance-history", adapt_governance_history),
    ("evolution/decisions.jsonl", "evolution-decision", adapt_evolution_decision),
    ("golden-review-decisions.jsonl", "golden-review", adapt_golden_review),
    ("feedback-log.jsonl", "knowledge-feedback", adapt_feedback),
    ("notify-log.jsonl", "notification", adapt_notification),
)

_HOME_DOCUMENT_SOURCES: tuple[tuple[str, str, RowAdapter], ...] = (
    ("self-repair/pending.json", "self-repair-queue", adapt_self_repair_queue),
    ("evolution/registry.json", "evolution-snapshot", adapt_evolution_snapshot),
    ("life/state.json", "life-snapshot", adapt_life_snapshot),
)


def _source(
    root: Path,
    path: Path,
    prefix: str,
    kind: str,
    adapter: RowAdapter,
) -> EventSource:
    relative = path.relative_to(root).as_posix()
    return EventSource(root, path, f"{prefix}:{relative}", kind, adapter)


def _document_source(
    root: Path,
    path: Path,
    prefix: str,
    kind: str,
    adapter: RowAdapter,
) -> EventSource:
    relative = path.relative_to(root).as_posix()
    return EventSource(root, path, f"{prefix}:{relative}", kind, adapter, "json")


def _intervention_source(root: Path, path: Path) -> EventSource:
    """Give live and archived copies one stable logical observation identity."""
    contract_identity = ""
    try:
        relative = path.relative_to(root)
        current = root
        safe_to_peek = True
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                safe_to_peek = False
                break
        if safe_to_peek:
            with path.open("r", encoding="utf-8") as handle:
                for raw in handle:
                    if not raw.strip():
                        continue
                    row = json.loads(raw)
                    candidate = row.get("contract_sha256") if isinstance(row, dict) else None
                    if isinstance(candidate, str) and re.fullmatch(r"[0-9a-f]{64}", candidate):
                        contract_identity = candidate
                    break
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    if not contract_identity:
        contract_identity = text_digest(path.name) or "unknown"
    return EventSource(
        root,
        path,
        f"effect-intervention:{contract_identity[:32]}",
        "effect-intervention",
        adapt_intervention,
    )


def discover_sources(
    home: Path, workspaces: Sequence[Path] = ()
) -> list[EventSource]:
    """Discover only declared sources; backups and replicated memory are excluded."""
    sources: list[EventSource] = []
    seen: dict[str, int] = {}

    def add(source: EventSource) -> None:
        identity = (
            f"{source.kind}:{source.logical_name}"
            if source.kind == "effect-intervention"
            else str(source.path.absolute())
        )
        existing_index = seen.get(identity)
        if existing_index is None:
            seen[identity] = len(sources)
            sources.append(source)
            return
        if source.kind == "effect-intervention":
            existing = sources[existing_index]
            try:
                if source.path.stat().st_size > existing.path.stat().st_size:
                    sources[existing_index] = source
            except OSError:
                pass

    for relative, kind, adapter in _HOME_EXACT_SOURCES:
        path = home / relative
        if path.exists() or path.is_symlink():
            add(_source(home, path, "kb", kind, adapter))
    for relative, kind, adapter in _HOME_DOCUMENT_SOURCES:
        path = home / relative
        if path.exists() or path.is_symlink():
            add(_document_source(home, path, "kb", kind, adapter))
    evidence_root = home.parent / "test-evidence"
    if evidence_root.is_dir() and not evidence_root.is_symlink():
        for path in sorted(evidence_root.glob("*.json")):
            if path.name != "gc-state.json":
                add(
                    _document_source(
                        evidence_root,
                        path,
                        "test-evidence",
                        "test-evidence",
                        adapt_test_evidence,
                    )
                )
    intent_root = home / "intent"
    if intent_root.is_dir():
        for path in sorted(intent_root.glob("**/*.events.jsonl")):
            add(_source(home, path, "kb", "intent-audit", adapt_intent))
        for path in sorted(intent_root.glob("**/*.interventions.jsonl")):
            add(_intervention_source(home, path))
        for path in sorted(intent_root.glob("**/*.corrections.jsonl")):
            add(
                _source(
                    home,
                    path,
                    "kb",
                    "correction-intervention",
                    adapt_correction_intervention,
                )
            )
        for path in sorted(intent_root.glob("**/*.approvals.jsonl")):
            add(
                _source(
                    home,
                    path,
                    "kb",
                    "approval-pair",
                    adapt_approval_pair,
                )
            )
    archive_root = home / "interventions" / "archive"
    if archive_root.is_dir():
        for path in sorted(archive_root.glob("*/events.jsonl")):
            add(_intervention_source(home, path))
    sediment_root = home / "sediment-runs"
    if sediment_root.is_dir():
        for path in sorted(sediment_root.glob("decisions-*.jsonl")):
            add(
                _source(
                    home,
                    path,
                    "kb",
                    "sedimentation-decision",
                    adapt_sediment_decision,
                )
            )

    for workspace in workspaces:
        root = workspace.expanduser().absolute()
        state = root / ".codex-agent"
        if not state.is_dir():
            continue
        workspace_id = workspace_identifier(root)
        prefix = f"workspace-{workspace_id or 'unknown'}"
        for path in sorted(state.glob("*.intent.events.jsonl")):
            filename_digest = text_digest(path.name)
            logical_name = (
                f"{prefix}:.codex-agent/intent-"
                f"{(filename_digest or 'unknown')[:24]}.events.jsonl"
            )
            add(EventSource(root, path, logical_name, "intent-audit", adapt_intent))
        for path in sorted(state.glob("*.intent.interventions.jsonl")):
            add(_intervention_source(root, path))
        for path in sorted(state.glob("*.intent.corrections.jsonl")):
            filename_digest = text_digest(path.name)
            logical_name = (
                f"{prefix}:.codex-agent/correction-"
                f"{(filename_digest or 'unknown')[:24]}.jsonl"
            )
            add(
                EventSource(
                    root,
                    path,
                    logical_name,
                    "correction-intervention",
                    adapt_correction_intervention,
                )
            )
        for path in sorted(state.glob("*.intent.approvals.jsonl")):
            filename_digest = text_digest(path.name)
            logical_name = (
                f"{prefix}:.codex-agent/approval-"
                f"{(filename_digest or 'unknown')[:24]}.jsonl"
            )
            add(
                EventSource(
                    root,
                    path,
                    logical_name,
                    "approval-pair",
                    adapt_approval_pair,
                )
            )
        for path in sorted(state.glob("*.run.jsonl")):
            filename_digest = text_digest(path.name)
            logical_name = (
                f"{prefix}:.codex-agent/run-"
                f"{(filename_digest or 'unknown')[:24]}.jsonl"
            )
            add(EventSource(root, path, logical_name, "managed-run", adapt_run_event))
    return sorted(sources, key=lambda item: item.logical_name)


def _source_report(source: EventSource) -> dict[str, Any]:
    return {
        "name": source.logical_name,
        "kind": source.kind,
        "status": "healthy",
        "rows": 0,
        "events": 0,
        "invalid_rows": 0,
        "unsupported_rows": 0,
        "issues": [],
        "violation_fingerprints": [],
    }


def _read_source_payload(
    source: EventSource,
) -> tuple[bytes | None, dict[str, Any]]:
    report = _source_report(source)
    try:
        relative = source.path.relative_to(source.root)
        current = source.root
        escaped = False
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                escaped = True
                break
        if not escaped:
            source.path.resolve(strict=True).relative_to(source.root.resolve(strict=True))
    except (OSError, ValueError):
        escaped = True
    if escaped:
        report.update(status="unreadable", invalid_rows=1)
        report["issues"].append(
            {
                "line": None,
                "category": "unsafe_source",
                "detail": "source uses a symlink or escapes its declared root",
            }
        )
        return None, report
    try:
        return source.path.read_bytes(), report
    except OSError as error:
        report["status"] = "unreadable"
        report["invalid_rows"] += 1
        report["issues"].append(
            {
                "line": None,
                "category": "unreadable",
                "detail": type(error).__name__,
            }
        )
        return None, report


def _violation_fingerprint(
    source: EventSource,
    line: int | None,
    category: str,
    raw_sha256: str,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "kind": source.kind,
                "name": source.logical_name,
                "line": line,
                "category": category,
                "raw_sha256": raw_sha256,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _parse_document_payload(
    source: EventSource, payload: bytes
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    report = _source_report(source)
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raw_sha256 = hashlib.sha256(payload).hexdigest()
        report.update(status="violations", rows=1, invalid_rows=1)
        report["violation_fingerprints"].append(
            _violation_fingerprint(source, 1, "invalid", raw_sha256)
        )
        report["issues"].append(
            {
                "line": 1,
                "category": "invalid",
                "detail": f"{type(error).__name__}: invalid JSON document"[:240],
                "fingerprint": _violation_fingerprint(
                    source, 1, "invalid", raw_sha256
                ),
            }
        )
        return [], report, 1
    if source.kind == "self-repair-queue":
        rows = value if isinstance(value, list) else None
    elif source.kind == "evolution-snapshot":
        rows = value.get("items") if isinstance(value, dict) else None
        if isinstance(rows, list):
            rows = [
                {**row, "generated_at": value.get("generated_at")}
                if isinstance(row, dict)
                else row
                for row in rows
            ]
    else:
        rows = [value] if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raw_sha256 = hashlib.sha256(payload).hexdigest()
        report.update(status="violations", rows=1, invalid_rows=1)
        report["violation_fingerprints"].append(
            _violation_fingerprint(source, 1, "invalid", raw_sha256)
        )
        report["issues"].append(
            {
                "line": 1,
                "category": "invalid",
                "detail": "document root does not match the declared source",
                "fingerprint": _violation_fingerprint(
                    source, 1, "invalid", raw_sha256
                ),
            }
        )
        return [], report, 1
    events: list[dict[str, Any]] = []
    for line, row in enumerate(rows, 1):
        report["rows"] += 1
        raw_sha256 = value_digest(row) if isinstance(row, dict) else value_digest({"value": row})
        try:
            if not isinstance(row, dict):
                raise EventContractError("source row must be a JSON object")
            events.append(source.adapter(row, source, line))
        except UnsupportedRow as error:
            report["unsupported_rows"] += 1
            report["violation_fingerprints"].append(
                _violation_fingerprint(source, line, "unsupported", raw_sha256)
            )
            report["issues"].append(
                {
                    "line": line,
                    "category": "unsupported",
                    "detail": str(error)[:240],
                    "fingerprint": _violation_fingerprint(
                        source, line, "unsupported", raw_sha256
                    ),
                }
            )
        except EventContractError as error:
            report["invalid_rows"] += 1
            report["violation_fingerprints"].append(
                _violation_fingerprint(source, line, "invalid", raw_sha256)
            )
            report["issues"].append(
                {
                    "line": line,
                    "category": "invalid",
                    "detail": f"{type(error).__name__}: {error}"[:240],
                    "fingerprint": _violation_fingerprint(
                        source, line, "invalid", raw_sha256
                    ),
                }
            )
    report["issues"] = report["issues"][:5]
    report["events"] = len(events)
    if report["invalid_rows"] or report["unsupported_rows"]:
        report["status"] = "violations"
    return events, report, len(rows)


def _parse_source_text(
    source: EventSource,
    text: str,
    *,
    start_line: int = 1,
    initial_events: Sequence[dict[str, Any]] = (),
    initial_report: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    events = [dict(event) for event in initial_events]
    if initial_report is None:
        report = _source_report(source)
    else:
        report = dict(initial_report)
        report["issues"] = list(initial_report.get("issues", []))
        report["violation_fingerprints"] = list(
            initial_report.get("violation_fingerprints", [])
        )
    lines = text.splitlines()
    for line_number, raw in enumerate(lines, start_line):
        if not raw.strip():
            continue
        report["rows"] = int(report["rows"]) + 1
        row: Any = None
        raw_sha256 = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
        try:
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise EventContractError("source row must be a JSON object")
            raw_sha256 = value_digest(row)
            events.append(source.adapter(row, source, line_number))
        except UnsupportedRow as error:
            report["unsupported_rows"] = int(report["unsupported_rows"]) + 1
            report["violation_fingerprints"].append(
                _violation_fingerprint(source, line_number, "unsupported", raw_sha256)
            )
            if len(report["issues"]) < 5:
                report["issues"].append(
                    {
                        "line": line_number,
                        "category": "unsupported",
                        "detail": str(error)[:240],
                        "fingerprint": _violation_fingerprint(
                            source, line_number, "unsupported", raw_sha256
                        ),
                    }
                )
        except (json.JSONDecodeError, EventContractError) as error:
            report["invalid_rows"] = int(report["invalid_rows"]) + 1
            report["violation_fingerprints"].append(
                _violation_fingerprint(source, line_number, "invalid", raw_sha256)
            )
            if len(report["issues"]) < 5:
                report["issues"].append(
                    {
                        "line": line_number,
                        "category": "invalid",
                        "detail": f"{type(error).__name__}: {error}"[:240],
                        "fingerprint": _violation_fingerprint(
                            source, line_number, "invalid", raw_sha256
                        ),
                    }
                )
    report["events"] = len(events)
    if report["status"] == "healthy" and (
        report["invalid_rows"] or report["unsupported_rows"]
    ):
        report["status"] = "violations"
    return events, report, start_line - 1 + len(lines)


def _read_source_from_payload(
    source: EventSource,
    payload: bytes,
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    if source.format == "json":
        return _parse_document_payload(source, payload)
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeError as error:
        report = _source_report(source)
        report.update(status="unreadable", invalid_rows=1)
        report["issues"].append(
            {
                "line": None,
                "category": "unreadable",
                "detail": type(error).__name__,
            }
        )
        return [], report, 0
    return _parse_source_text(source, text)


def _read_source(source: EventSource) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    payload, report = _read_source_payload(source)
    if payload is None:
        return [], report
    events, parsed, _line_count = _read_source_from_payload(source, payload)
    return events, parsed


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _validated_cache_entry(
    source: EventSource,
    payload: bytes,
    value: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any], int, int] | None:
    if source.format != "jsonl":
        return None
    if not isinstance(value, dict) or value.get("stateVersion") != PROJECTION_STATE_VERSION:
        return None
    if value.get("kind") != source.kind or value.get("logicalName") != source.logical_name:
        return None
    byte_offset = _nonnegative_int(value.get("byteOffset"))
    line_count = _nonnegative_int(value.get("lineCount"))
    row_count = _nonnegative_int(value.get("rows"))
    if byte_offset is None or line_count is None or row_count is None:
        return None
    if byte_offset > len(payload):
        return None
    prefix = payload[:byte_offset]
    if prefix and not prefix.endswith(b"\n"):
        return None
    if value.get("prefixSha256") != hashlib.sha256(prefix).hexdigest():
        return None
    events = value.get("events")
    report = value.get("report")
    if not isinstance(events, list) or not isinstance(report, dict):
        return None
    expected_report_fields = {
        "name",
        "kind",
        "status",
        "rows",
        "events",
        "invalid_rows",
        "unsupported_rows",
        "issues",
        "violation_fingerprints",
    }
    if set(report) != expected_report_fields:
        return None
    if (
        report.get("name") != source.logical_name
        or report.get("kind") != source.kind
        or report.get("status") != "healthy"
        or report.get("rows") != row_count
        or report.get("events") != len(events)
        or report.get("invalid_rows") != 0
        or report.get("unsupported_rows") != 0
        or report.get("issues") != []
        or report.get("violation_fingerprints") != []
        or row_count != len(events)
    ):
        return None
    previous_line = 0
    validated: list[dict[str, Any]] = []
    try:
        for event in events:
            validate_event(event)
            line = event["source"]["line"]
            if (
                event["source"]["kind"] != source.kind
                or event["source"]["name"] != source.logical_name
                or line <= previous_line
                or line > line_count
            ):
                return None
            previous_line = line
            validated.append(dict(event))
    except (EventContractError, KeyError, TypeError):
        return None
    return validated, dict(report), line_count, byte_offset


def _cache_entry(
    source: EventSource,
    payload: bytes,
    events: Sequence[dict[str, Any]],
    report: Mapping[str, Any],
    line_count: int,
) -> dict[str, Any] | None:
    if source.format != "jsonl":
        return None
    if report.get("status") != "healthy" or (payload and not payload.endswith(b"\n")):
        return None
    return {
        "stateVersion": PROJECTION_STATE_VERSION,
        "kind": source.kind,
        "logicalName": source.logical_name,
        "byteOffset": len(payload),
        "prefixSha256": hashlib.sha256(payload).hexdigest(),
        "lineCount": line_count,
        "rows": int(report["rows"]),
        "events": list(events),
        "report": dict(report),
    }


def _summary(events: Iterable[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, Any]:
    selected = list(events)
    by_domain = Counter(str(event["domain"]) for event in selected)
    by_type = Counter(str(event["type"]) for event in selected)
    by_outcome = Counter(str(event["outcome"]) for event in selected)
    by_provider = Counter(str(event["provider"]) for event in selected)
    invalid = sum(int(source["invalid_rows"]) for source in sources)
    unsupported = sum(int(source["unsupported_rows"]) for source in sources)
    unreadable = sum(source["status"] == "unreadable" for source in sources)
    violations = invalid + unsupported
    settlement_targets = {
        str(event.get("attributes", {}).get("target_fingerprint") or "")
        for event in selected
        if event.get("type") == "lifecycle.event_settlement"
        and event.get("outcome") in {"inconclusive", "superseded"}
    }
    settled = sum(
        1
        for source in sources
        for fingerprint in source.get("violation_fingerprints", [])
        if fingerprint in settlement_targets
    )
    open_violations = max(0, violations - settled)
    timestamps = [str(event["occurred_at"]) for event in selected]
    return {
        "event_schema": EVENT_SCHEMA,
        "sources_discovered": len(sources),
        "sources_healthy": sum(source["status"] == "healthy" for source in sources),
        "sources_unreadable": unreadable,
        "rows_total": sum(int(source["rows"]) for source in sources),
        "events_total": len(selected),
        "invalid_rows": invalid,
        "unsupported_rows": unsupported,
        "contract_violations": open_violations,
        "historical_contract_violations": violations,
        "settled_contract_violations": settled,
        "contract_healthy": open_violations == 0,
        "correlated_events": sum(bool(event["correlation"]) for event in selected),
        "latest_at": max(timestamps) if timestamps else None,
        "by_domain": dict(sorted(by_domain.items())),
        "by_type": dict(sorted(by_type.items())),
        "by_outcome": dict(sorted(by_outcome.items())),
        "by_provider": dict(sorted(by_provider.items())),
    }


def _disabled_snapshot(
    policy: Mapping[str, Any], *, include_events: bool
) -> dict[str, Any]:
    """Return explicit unavailable truth without discovering authoritative sources."""
    snapshot: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "stateVersion": PROJECTION_STATE_VERSION,
        "asOfSeq": -1,
        "sourceRevision": None,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "read_only": True,
        "authoritative_sources_unchanged": True,
        "privacy": _privacy.privacy_envelope(policy),
        "projectionCache": {
            "status": "privacy_disabled",
            "readStatus": "disabled",
            "writeStatus": "disabled",
            "sourcesReused": 0,
            "sourcesTailReplayed": 0,
            "sourcesRebuilt": 0,
            "entriesDiscarded": 0,
            "entriesOrphaned": 0,
        },
        "summary": {
            "event_schema": EVENT_SCHEMA,
            "sources_discovered": None,
            "sources_healthy": None,
            "sources_unreadable": None,
            "rows_total": None,
            "events_total": None,
            "invalid_rows": None,
            "unsupported_rows": None,
            "contract_violations": None,
            "historical_contract_violations": None,
            "settled_contract_violations": None,
            "contract_healthy": None,
            "correlated_events": None,
            "latest_at": None,
            "by_domain": {},
            "by_type": {},
            "by_outcome": {},
            "by_provider": {},
        },
        "sources": [],
    }
    if include_events:
        snapshot["events"] = []
        snapshot["summary"]["events_returned"] = 0
    return snapshot


def collect_snapshot(
    home: Path,
    *,
    workspaces: Sequence[Path] = (),
    domains: Sequence[str] = (),
    providers: Sequence[str] = (),
    correlations: Mapping[str, str] | None = None,
    limit: int | None = None,
    include_events: bool = True,
    use_cache: bool = True,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """Project declared logs; an optional derived cache never mutates source truth."""
    policy = _privacy.load_policy(home)
    privacy = _privacy.privacy_envelope(policy)
    if privacy["observationEnabled"] is not True:
        return _disabled_snapshot(policy, include_events=include_events)
    source_reports: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    sources = discover_sources(home, workspaces)
    cached_sources: Mapping[str, Any] = {}
    cache_read_status = "disabled"
    cache_target: Path | None = None
    if use_cache:
        cache_root = (home / "projections").expanduser().absolute()
        cache_target = (
            cache_path.expanduser().absolute()
            if cache_path is not None
            else _projection_cache.default_cache_path(home).expanduser().absolute()
        )
        if not cache_target.is_relative_to(cache_root):
            raise EventContractError(
                "event projection cache must stay inside the KB projections directory"
            )
        relative_cache = cache_target.relative_to(cache_root)
        current_cache_part = cache_root
        unsafe_cache_path = current_cache_part.is_symlink()
        for part in relative_cache.parts:
            current_cache_part = current_cache_part / part
            if current_cache_part.is_symlink():
                unsafe_cache_path = True
                break
        if unsafe_cache_path:
            cache_target = None
            cache_read_status = "unsafe_path"
        else:
            cache_value, cache_read_status = _projection_cache.load_cache(
                cache_target
            )
            if isinstance(cache_value.get("sources"), dict):
                cached_sources = cache_value["sources"]

    cache_entries: dict[str, dict[str, Any]] = {}
    source_cuts: list[dict[str, Any]] = []
    seen_cache_keys: set[str] = set()
    sources_reused = 0
    sources_tail_replayed = 0
    sources_rebuilt = 0
    discarded_entries = 0

    for source in sources:
        key = _projection_cache.source_key(source.kind, source.logical_name)
        seen_cache_keys.add(key)
        payload, unreadable_report = _read_source_payload(source)
        cached_value = cached_sources.get(key)
        cached = (
            _validated_cache_entry(source, payload, cached_value)
            if payload is not None
            else None
        )
        if cached_value is not None and cached is None:
            discarded_entries += 1
        previous_entry: dict[str, Any] | None = None
        if cached is not None and isinstance(cached_value, dict):
            previous_entry = dict(cached_value)

        line_count = 0
        if payload is None:
            projected = []
            report = unreadable_report
            sources_rebuilt += 1
            source_sha256 = None
            source_bytes = None
        elif cached is None:
            projected, report, line_count = _read_source_from_payload(
                source, payload
            )
            sources_rebuilt += 1
            source_sha256 = hashlib.sha256(payload).hexdigest()
            source_bytes = len(payload)
        else:
            cached_events, cached_report, line_count, byte_offset = cached
            tail = payload[byte_offset:]
            if not tail:
                projected = cached_events
                report = cached_report
                sources_reused += 1
            else:
                try:
                    tail_text = tail.decode("utf-8", errors="strict")
                except UnicodeError:
                    projected, report, line_count = _read_source_from_payload(
                        source, payload
                    )
                    sources_rebuilt += 1
                    previous_entry = None
                else:
                    projected, report, line_count = _parse_source_text(
                        source,
                        tail_text,
                        start_line=line_count + 1,
                        initial_events=cached_events,
                        initial_report=cached_report,
                    )
                    sources_tail_replayed += 1
            source_sha256 = hashlib.sha256(payload).hexdigest()
            source_bytes = len(payload)

        source_reports.append(report)
        events.extend(projected)
        source_cuts.append(
            {
                "key": key,
                "kind": source.kind,
                "logicalName": source.logical_name,
                "bytes": source_bytes,
                "sha256": source_sha256,
                "status": report["status"],
            }
        )
        if payload is not None:
            entry = _cache_entry(
                source, payload, projected, report, line_count
            )
            if entry is not None:
                cache_entries[key] = entry
            elif previous_entry is not None:
                # A torn/invalid new tail must not destroy a still-correct
                # checkpoint of the authoritative prefix.
                cache_entries[key] = previous_entry

    events.sort(key=lambda event: (event["occurred_at"], event["event_id"]))
    domain_filter = set(domains)
    provider_filter = set(providers)
    correlations = safe_correlation(correlations or {})
    matched = [
        event
        for event in events
        if (not domain_filter or event["domain"] in domain_filter)
        and (not provider_filter or event["provider"] in provider_filter)
        and all(event["correlation"].get(key) == value for key, value in correlations.items())
    ]
    filtered = matched
    if limit is not None:
        if limit < 1:
            raise EventContractError("limit must be positive")
        filtered = filtered[-limit:]
    as_of_seq = sum(int(report["rows"]) for report in source_reports) - 1
    source_revision = value_digest(source_cuts)
    cache_write_status = "disabled"
    if use_cache and cache_target is not None:
        cache_write_status = _projection_cache.write_cache(
            cache_target,
            sources=cache_entries,
            as_of_seq=as_of_seq,
            source_revision=source_revision,
        )
    if not use_cache:
        cache_status = "disabled"
    elif cache_target is None:
        cache_status = "unsafe_path_disabled"
    elif not sources:
        cache_status = "empty"
    elif sources_rebuilt == 0 and sources_tail_replayed == 0:
        cache_status = "hit"
    elif sources_rebuilt == 0:
        cache_status = "tail_replay"
    elif sources_reused or sources_tail_replayed:
        cache_status = "mixed"
    else:
        cache_status = "full_rebuild"
    snapshot: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "stateVersion": PROJECTION_STATE_VERSION,
        "asOfSeq": as_of_seq,
        "sourceRevision": source_revision,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "read_only": True,
        "authoritative_sources_unchanged": True,
        "privacy": privacy,
        "projectionCache": {
            "status": cache_status,
            "readStatus": cache_read_status,
            "writeStatus": cache_write_status,
            "sourcesReused": sources_reused,
            "sourcesTailReplayed": sources_tail_replayed,
            "sourcesRebuilt": sources_rebuilt,
            "entriesDiscarded": discarded_entries,
            "entriesOrphaned": len(set(cached_sources) - seen_cache_keys),
        },
        "summary": _summary(matched, source_reports),
        "sources": source_reports,
    }
    if include_events:
        snapshot["events"] = filtered
        snapshot["summary"]["events_returned"] = len(filtered)
    return snapshot


def status_projection(home: Path) -> dict[str, Any]:
    """Small field set consumed by sulde-status and weekly governance."""
    snapshot = collect_snapshot(home, include_events=False)
    summary = snapshot["summary"]
    return {
        "event_observation_privacy_mode": snapshot["privacy"]["mode"],
        "event_observation_privacy_healthy": snapshot["privacy"]["policyHealthy"],
        "event_observation_enabled": snapshot["privacy"]["observationEnabled"],
        "event_observation_export_enabled": snapshot["privacy"]["portableExportEnabled"],
        "event_projection_state_version": snapshot["stateVersion"],
        "event_projection_as_of_seq": snapshot["asOfSeq"],
        "event_projection_source_revision": snapshot["sourceRevision"],
        "event_contract_schema": summary["event_schema"],
        "event_contract_healthy": summary["contract_healthy"],
        "event_contract_violations": summary["contract_violations"],
        "event_contract_historical_violations": summary["historical_contract_violations"],
        "event_contract_settled_violations": summary["settled_contract_violations"],
        "event_invalid_rows": summary["invalid_rows"],
        "event_unsupported_rows": summary["unsupported_rows"],
        "event_sources_discovered": summary["sources_discovered"],
        "event_sources_healthy": summary["sources_healthy"],
        "event_sources_unreadable": summary["sources_unreadable"],
        "event_rows_total": summary["rows_total"],
        "event_observations_total": summary["events_total"],
        "event_correlated_total": summary["correlated_events"],
        "event_observation_latest_at": summary["latest_at"],
        "event_observations_by_domain": summary["by_domain"],
    }

#!/usr/bin/env python3
"""Pure policy for durable, human-owned PermissionRequest decisions.

``reassess_at`` is a liveness boundary.  ``expires_at`` is the latest point at
which a human receipt can still be considered.  Neither clock grants authority.
The helpers in this module return projections and CAS results; they never invoke
a host, synthesize a click, or execute the protected effect.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from typing import Any


REASSESS_AFTER_SECONDS = 300
NATIVE_HUMAN_TTL_SECONDS = 86_400
UNATTENDED_AGENT_IF_ELIGIBLE = "agent-if-eligible"
UNATTENDED_WAIT = "wait"
UNATTENDED_POLICIES = {
    UNATTENDED_AGENT_IF_ELIGIBLE,
    UNATTENDED_WAIT,
}

OPEN_REQUEST_STATUSES = {"asked", "reassess_due"}
REPLACEABLE_REQUEST_STATUSES = {"expired", "cancelled", "superseded"}

# These values bind both a displayed card and any later native receipt to the
# exact decision/effect world which existed when the card was rendered.
CAS_BINDING_FIELDS = (
    "card_sha256",
    "provider",
    "session_id",
    "lane_sha256",
    "target_sha256",
    "revision",
    "journal_sha256",
    "effect_sha256",
    "world_state_sha256",
)
REASSESS_BINDING_FIELDS = (
    "card_sha256",
    "lane_sha256",
    "revision",
    "world_state_sha256",
)

# The positive list is intentionally narrower than a forbidden-kind list:
# unknown kinds must never become eligible by omission.
AGENT_ALLOWED_KINDS = {"local-edit"}
AGENT_RISK_LEVELS = {"low", "medium", "high", "critical"}
AGENT_BOOLEAN_FIELDS = (
    "contains_secret",
    "external_write",
    "incurs_cost",
    "reversible",
    "evidence_complete",
    "allowlisted",
)
AGENT_ACTION_FIELDS = {"kind", "risk", *AGENT_BOOLEAN_FIELDS}
RECEIPT_FIELDS = {"receipt_id", "request_id", "outcome"}
REQUEST_REQUIRED_FIELDS = {
    "request_id",
    "status",
    "binding",
    "created_at",
    "created_monotonic",
    "reassess_at",
    "expires_at",
    "reassess_after_seconds",
    "ttl_seconds",
    "prompt_shown",
    "decision_owner",
    "receipts",
    "reminder_count",
    "execution_authorized",
}
REQUEST_OPTIONAL_FIELDS = {
    "last_reassessed_at",
    "reminder_pending",
    "rerender_required",
    "outcome",
}

# Exact field sets emitted by approval_invariant._apply.  This adapter exists
# only so the older durable timing projection can be classified by this module;
# it deliberately projects no route, outcome, receipt, or execution authority.
LEGACY_REQUEST_FIELDS = {
    "request_id",
    "intent_id_sha256",
    "intent_revision",
    "kind",
    "target_sha256",
    "card_sha256",
    "workspace_sha256",
    "proposal_sha256",
    "route",
    "expires_at",
    "reassess_at",
    "provider",
    "lane_sha256",
    "source",
    "status",
    "outcome",
    "asked_at",
    "decided_at",
    "decision_provider",
    "decision_lane_sha256",
    "receipt_sha256",
}
LEGACY_DECIDED_REQUEST_FIELDS = LEGACY_REQUEST_FIELDS | {"decision_actor"}


class ApprovalTimeoutPolicyError(ValueError):
    """The approval timing, binding, or unattended policy is malformed."""


def _error(message: str) -> ApprovalTimeoutPolicyError:
    return ApprovalTimeoutPolicyError(message)


def _require_plain_json(value: Any, *, name: str) -> None:
    """Reject non-plain JSON without invoking application-defined methods."""
    value_type = type(value)
    if value_type in {type(None), str, int, bool}:
        return
    if value_type is float:
        if not math.isfinite(value):
            raise _error(f"{name} contains a non-finite number")
        return
    if value_type is list:
        for index in range(len(value)):
            _require_plain_json(value[index], name=f"{name}[{index}]")
        return
    if value_type is dict:
        for key in value.keys():
            if type(key) is not str:
                raise _error(f"{name} contains a non-string object key")
            _require_plain_json(value[key], name=f"{name}.{key}")
        return
    raise _error(f"{name} must contain only exact plain JSON types")


def _require_exact_string(value: Any, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise _error(f"{name} must be an exact non-empty string")
    return value


def _require_exact_bool(value: Any, *, name: str) -> bool:
    if type(value) is not bool:
        raise _error(f"{name} must be an exact bool")
    return value


def _require_exact_int(value: Any, *, name: str) -> int:
    if type(value) is not int:
        raise _error(f"{name} must be an exact int")
    return value


def _require_finite_number(value: Any, *, name: str) -> int | float:
    if type(value) not in {int, float}:
        raise _error(f"{name} must be an exact int or float, not bool")
    if type(value) is float and not math.isfinite(value):
        raise _error(f"{name} must be finite")
    return value


def _require_now(value: Any, *, name: str = "now") -> datetime | None:
    if value is not None and type(value) is not datetime:
        raise _error(f"{name} must be an exact datetime or None")
    if (
        value is not None
        and value.tzinfo is not None
        and type(value.tzinfo) is not timezone
    ):
        raise _error(f"{name}.tzinfo must be an exact timezone or None")
    return value


def _validate_durations(reassess_after_seconds: Any, ttl_seconds: Any) -> None:
    grace = _require_exact_int(
        reassess_after_seconds, name="reassess_after_seconds"
    )
    ttl = _require_exact_int(ttl_seconds, name="ttl_seconds")
    if grace <= 0:
        raise _error("approval reassessment delay must be positive")
    if ttl <= grace:
        raise _error("approval durable ttl must exceed its reassessment delay")
    if ttl > NATIVE_HUMAN_TTL_SECONDS:
        raise _error("approval durable ttl must not exceed 24 hours")


def _validate_binding(value: Any, *, name: str) -> dict[str, Any]:
    _require_plain_json(value, name=name)
    if type(value) is not dict:
        raise _error(f"{name} must be an exact dict")
    expected = set(CAS_BINDING_FIELDS)
    actual = set(value.keys())
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if extra:
            detail.append("extra=" + ",".join(extra))
        raise _error(f"{name} authority fields are invalid: {'; '.join(detail)}")
    for field in CAS_BINDING_FIELDS:
        if field == "revision":
            revision = _require_exact_int(value[field], name=f"{name}.{field}")
            if revision < 0:
                raise _error(f"{name}.{field} must not be negative")
        else:
            _require_exact_string(value[field], name=f"{name}.{field}")
    return value


def _validate_receipts(value: Any, *, request_id: str) -> list[dict[str, Any]]:
    _require_plain_json(value, name="request.receipts")
    if type(value) is not list:
        raise _error("request.receipts must be an exact list")
    receipt_ids: set[str] = set()
    for index in range(len(value)):
        row = value[index]
        if type(row) is not dict:
            raise _error(f"request.receipts[{index}] must be an exact dict")
        if set(row.keys()) != RECEIPT_FIELDS:
            raise _error(f"request.receipts[{index}] has an invalid schema")
        receipt_id = _require_exact_string(
            row["receipt_id"], name=f"request.receipts[{index}].receipt_id"
        )
        row_request_id = _require_exact_string(
            row["request_id"], name=f"request.receipts[{index}].request_id"
        )
        outcome = _require_exact_string(
            row["outcome"], name=f"request.receipts[{index}].outcome"
        )
        if receipt_id in receipt_ids:
            raise _error("request.receipts contains a duplicate receipt id")
        if row_request_id != request_id:
            raise _error("request.receipts contains a foreign request id")
        if outcome not in {"allow", "deny"}:
            raise _error("request.receipts contains an invalid outcome")
        receipt_ids.add(receipt_id)
    return value


def _validate_request(value: Any) -> dict[str, Any]:
    _require_plain_json(value, name="request")
    if type(value) is not dict:
        raise _error("request must be an exact dict")
    actual = set(value.keys())
    missing = REQUEST_REQUIRED_FIELDS - actual
    extra = actual - REQUEST_REQUIRED_FIELDS - REQUEST_OPTIONAL_FIELDS
    if missing or extra:
        raise _error("request has an invalid schema")
    request_id = _require_exact_string(value["request_id"], name="request.request_id")
    _require_exact_string(value["status"], name="request.status")
    _validate_binding(value["binding"], name="request.binding")
    for field in ("created_at", "reassess_at", "expires_at"):
        _require_exact_string(value[field], name=f"request.{field}")
    _require_finite_number(
        value["created_monotonic"], name="request.created_monotonic"
    )
    _validate_durations(
        value["reassess_after_seconds"], value["ttl_seconds"]
    )
    _require_exact_bool(value["prompt_shown"], name="request.prompt_shown")
    owner = _require_exact_string(
        value["decision_owner"], name="request.decision_owner"
    )
    if owner not in {"human", "agent"}:
        raise _error("request.decision_owner is invalid")
    reminder_count = _require_exact_int(
        value["reminder_count"], name="request.reminder_count"
    )
    if reminder_count < 0:
        raise _error("request.reminder_count must not be negative")
    _require_exact_bool(
        value["execution_authorized"], name="request.execution_authorized"
    )
    _validate_receipts(value["receipts"], request_id=request_id)
    for field in ("reminder_pending", "rerender_required"):
        if field in value:
            _require_exact_bool(value[field], name=f"request.{field}")
    if "last_reassessed_at" in value:
        _require_exact_string(
            value["last_reassessed_at"], name="request.last_reassessed_at"
        )
    if "outcome" in value:
        outcome = _require_exact_string(value["outcome"], name="request.outcome")
        if outcome not in {"allow", "deny"}:
            raise _error("request.outcome is invalid")
    return value


def _validate_decision(value: Any) -> dict[str, Any]:
    _require_plain_json(value, name="decision")
    if type(value) is not dict:
        raise _error("decision must be an exact dict")
    expected = set(CAS_BINDING_FIELDS) | RECEIPT_FIELDS
    if set(value.keys()) != expected:
        raise _error("decision has an invalid schema")
    _require_exact_string(value["request_id"], name="decision.request_id")
    _require_exact_string(value["receipt_id"], name="decision.receipt_id")
    _require_exact_string(value["outcome"], name="decision.outcome")
    binding = {field: value[field] for field in CAS_BINDING_FIELDS}
    _validate_binding(binding, name="decision.binding")
    return value


def parse_timestamp(value: Any) -> datetime | None:
    raw = _require_exact_string(value, name="timestamp")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _utc(value: datetime | None) -> datetime:
    _require_now(value)
    current = datetime.now(timezone.utc) if value is None else value
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def normalize_unattended_policy(
    value: Any,
    *,
    default: str = UNATTENDED_WAIT,
) -> str:
    selected_default = _require_exact_string(
        default, name="default unattended approval policy"
    )
    if selected_default not in UNATTENDED_POLICIES:
        raise ApprovalTimeoutPolicyError(
            f"unsupported default unattended approval policy: {selected_default!r}"
        )
    selected = (
        selected_default
        if value is None
        else _require_exact_string(value, name="unattended approval policy")
    )
    if selected not in UNATTENDED_POLICIES:
        raise ApprovalTimeoutPolicyError(
            f"unsupported unattended approval policy: {selected!r}"
        )
    return selected


def approval_deadlines(
    *,
    now: datetime | None = None,
    reassess_after_seconds: int = REASSESS_AFTER_SECONDS,
    ttl_seconds: int = NATIVE_HUMAN_TTL_SECONDS,
) -> tuple[str, str]:
    _require_now(now)
    _validate_durations(reassess_after_seconds, ttl_seconds)
    grace = reassess_after_seconds
    ttl = ttl_seconds
    current = _utc(now)
    return (
        (current + timedelta(seconds=grace)).isoformat(),
        (current + timedelta(seconds=ttl)).isoformat(),
    )


def _elapsed_boundary_reached(
    request: dict[str, Any],
    *,
    wall_key: str,
    duration_key: str,
    now: datetime,
    monotonic_now: float | None,
) -> bool:
    """Use either clock reaching its boundary; neither clock grants authority.

    The durable wall deadline survives restarts.  A valid monotonic anchor keeps
    a wall-clock rollback from extending a live request beyond its configured
    duration.  A monotonic reset (current < anchor) is ignored safely.
    """
    wall_deadline = parse_timestamp(request[wall_key])
    wall_due = wall_deadline is not None and now >= wall_deadline
    anchor = request["created_monotonic"]
    duration = request[duration_key]
    monotonic_due = False
    if monotonic_now is not None:
        elapsed = monotonic_now - anchor
        monotonic_due = elapsed >= 0 and elapsed >= duration
    return wall_due or monotonic_due


def _legacy_request_phase_projection(
    request: dict[str, Any],
) -> dict[str, str | None] | None:
    """Return the exact legacy identity/timestamp subset, or no projection."""
    actual = set(request.keys())
    if actual != LEGACY_REQUEST_FIELDS and actual != LEGACY_DECIDED_REQUEST_FIELDS:
        return None

    request_id = _require_exact_string(
        request["request_id"], name="legacy request.request_id"
    )
    status = _require_exact_string(
        request["status"], name="legacy request.status"
    )
    if status not in {"asked", "decided"}:
        raise _error("legacy request.status is invalid")
    if status == "asked" and actual != LEGACY_REQUEST_FIELDS:
        raise _error("asked legacy request has a decided-only schema")
    if status == "decided" and actual != LEGACY_DECIDED_REQUEST_FIELDS:
        raise _error("decided legacy request is missing its decision actor")

    timestamps: dict[str, str | None] = {}
    for field in ("asked_at", "reassess_at", "expires_at", "decided_at"):
        value = request[field]
        if value is None and field == "decided_at" and status == "asked":
            timestamps[field] = None
            continue
        if type(value) is not str:
            raise _error(f"legacy request.{field} must be an exact string")
        if not value:
            if field in {"reassess_at", "expires_at"}:
                timestamps[field] = ""
                continue
            raise _error(f"legacy request.{field} must not be empty")
        if parse_timestamp(value) is None:
            raise _error(f"legacy request.{field} is invalid")
        timestamps[field] = value

    return {
        "request_id": request_id,
        "status": status,
        **timestamps,
    }


def _legacy_request_phase(
    projection: dict[str, str | None], *, now: datetime
) -> str:
    if projection["status"] != "asked":
        return "decided"
    expires_at = projection["expires_at"]
    if expires_at and parse_timestamp(expires_at) <= now:
        return "expired"
    reassess_at = projection["reassess_at"]
    if not reassess_at:
        return "not_scheduled"
    return "reassess_due" if parse_timestamp(reassess_at) <= now else "fresh"


def request_phase(
    request: dict[str, Any],
    *,
    now: datetime | None = None,
    monotonic_now: float | None = None,
) -> str:
    """Project one durable request without mutating it or granting authority."""
    _require_plain_json(request, name="request")
    if type(request) is not dict:
        raise _error("request must be an exact dict")
    raw_status = request.get("status")
    if type(raw_status) is not str or not raw_status.strip():
        return "invalid"
    _require_now(now)
    if monotonic_now is not None:
        _require_finite_number(monotonic_now, name="monotonic_now")
    current = _utc(now)
    legacy = _legacy_request_phase_projection(request)
    if legacy is not None:
        return _legacy_request_phase(legacy, now=current)

    _validate_request(request)
    status = raw_status
    if status in REPLACEABLE_REQUEST_STATUSES or status in {
        "decided",
        "agent_decided",
    }:
        return status
    if status not in OPEN_REQUEST_STATUSES:
        return "invalid"

    if parse_timestamp(request["expires_at"]) is None:
        # A malformed durable deadline must not create an immortal question.
        return "expired"
    if _elapsed_boundary_reached(
        request,
        wall_key="expires_at",
        duration_key="ttl_seconds",
        now=current,
        monotonic_now=monotonic_now,
    ):
        return "expired"
    if status == "reassess_due":
        return "reassess_due"
    if parse_timestamp(request["reassess_at"]) is None:
        return "not_scheduled"
    if _elapsed_boundary_reached(
        request,
        wall_key="reassess_at",
        duration_key="reassess_after_seconds",
        now=current,
        monotonic_now=monotonic_now,
    ):
        return "reassess_due"
    return "fresh"


def _binding_mismatches(
    expected: dict[str, Any],
    observed: dict[str, Any],
    fields: tuple[str, ...],
) -> list[str]:
    return [
        field
        for field in fields
        if expected[field] != observed[field]
    ]


def reassess_request(
    request: dict[str, Any],
    *,
    current_binding: dict[str, Any],
    now: datetime | None = None,
    monotonic_now: float | None = None,
) -> dict[str, Any]:
    """Run an idempotent liveness tick over one displayed human question."""
    _validate_request(request)
    _validate_binding(current_binding, name="current_binding")
    _require_now(now)
    if monotonic_now is not None:
        _require_finite_number(monotonic_now, name="monotonic_now")
    projected = deepcopy(request)
    phase = request_phase(projected, now=now, monotonic_now=monotonic_now)
    receipt_count = len(projected["receipts"])

    if phase == "invalid":
        projected["execution_authorized"] = False
        action = "invalid_request"
        mismatches = []
    elif phase == "expired":
        projected["status"] = "expired"
        action = "expired"
        mismatches: list[str] = []
    elif phase == "reassess_due":
        mismatches = _binding_mismatches(
            projected["binding"], current_binding, REASSESS_BINDING_FIELDS
        )
        if mismatches:
            projected["status"] = "superseded"
            projected["rerender_required"] = True
            action = "cancel_and_rerender"
        else:
            if projected["status"] != "reassess_due":
                projected["status"] = "reassess_due"
                projected["reminder_count"] += 1
                projected["last_reassessed_at"] = _utc(now).isoformat()
            projected["reminder_pending"] = True
            action = "remind_and_wait"
    else:
        mismatches = []
        action = "continue_waiting"

    # Ticks only project liveness/validity and can never mint or consume a
    # receipt, even when called repeatedly or after a clock adjustment.
    if len(projected["receipts"]) != receipt_count:
        raise AssertionError("approval reassessment changed receipt count")
    projected["execution_authorized"] = False
    return {
        "action": action,
        "request": projected,
        "binding_mismatches": mismatches,
        "authority_transferred": False,
        "receipt_delta": 0,
    }


def agent_policy_eligibility(action: Any) -> tuple[bool, tuple[str, ...]]:
    """Apply the complete, fail-closed gate used *before* native presentation."""
    try:
        _require_plain_json(action, name="action")
    except ApprovalTimeoutPolicyError:
        return False, ("action_not_plain_json",)
    if type(action) is not dict:
        return False, ("action_not_exact_dict",)

    reasons: list[str] = []
    if set(action.keys()) != AGENT_ACTION_FIELDS:
        reasons.append("action_schema_invalid")
    raw_kind = action.get("kind")
    if type(raw_kind) is str and raw_kind.strip():
        kind = raw_kind
    else:
        kind = ""
    if kind not in AGENT_ALLOWED_KINDS:
        reasons.append("kind_not_agent_eligible")

    for field in AGENT_BOOLEAN_FIELDS:
        if field not in action or type(action[field]) is not bool:
            reasons.append(f"{field}_not_exact_bool")

    raw_risk = action.get("risk")
    if type(raw_risk) is not str or raw_risk not in AGENT_RISK_LEVELS:
        reasons.append("risk_not_allowlisted_enum")
        risk = ""
    else:
        risk = raw_risk
    checks = (
        (action.get("contains_secret") is False, "secret_or_unknown"),
        (action.get("external_write") is False, "external_write_or_unknown"),
        (action.get("incurs_cost") is False, "cost_or_unknown"),
        (action.get("reversible") is True, "irreversible_or_unknown"),
        (risk == "low", "risk_not_low"),
        (action.get("evidence_complete") is True, "evidence_incomplete"),
        (action.get("allowlisted") is True, "not_explicitly_allowlisted"),
    )
    reasons.extend(reason for passed, reason in checks if not passed)
    return not reasons, tuple(reasons)


def pre_prompt_route(
    action: Any,
    *,
    unattended_policy: Any,
    prompt_shown: bool,
    agent_already_decided: bool = False,
) -> dict[str, Any]:
    """Select the decision owner before presentation, never after silence."""
    if type(prompt_shown) is not bool:
        return _human_route(("prompt_shown_not_exact_bool",))
    if type(agent_already_decided) is not bool:
        return _human_route(("agent_already_decided_not_exact_bool",))
    eligible, reasons = agent_policy_eligibility(action)
    try:
        policy = normalize_unattended_policy(unattended_policy)
    except ApprovalTimeoutPolicyError:
        policy = "unknown"
        reasons = (*reasons, "policy_unknown")
    if prompt_shown:
        return _human_route((*reasons, "prompt_already_shown"))
    if (
        agent_already_decided
        and policy == UNATTENDED_AGENT_IF_ELIGIBLE
        and eligible
    ):
        return {
            "route": "already_agent_decided",
            "decision_owner": "agent",
            "execution_authorized": False,
        }
    if (
        policy == UNATTENDED_AGENT_IF_ELIGIBLE
        and eligible
    ):
        return {
            "route": "agent_before_prompt",
            "decision_owner": "agent",
            "execution_authorized": False,
            "ineligible_reasons": (),
        }
    return _human_route(reasons)


def _human_route(reasons: tuple[str, ...]) -> dict[str, Any]:
    return {
        "route": "human",
        "decision_owner": "human",
        "execution_authorized": False,
        "ineligible_reasons": reasons,
    }


def timeout_disposition(
    *,
    phase: str,
    kind: str,
    unattended_policy: str,
    eligible: bool,
    world_current: bool,
    host_timeout_observed: bool,
) -> str:
    """Compatibility projection for callers which have already shown a prompt.

    ``kind``, eligibility, policy and a host timeout observation are accepted so
    existing adapters can migrate independently.  None can transfer authority
    after presentation.
    """
    _require_exact_string(phase, name="phase")
    _require_exact_string(kind, name="kind")
    _require_exact_bool(eligible, name="eligible")
    _require_exact_bool(world_current, name="world_current")
    _require_exact_bool(
        host_timeout_observed, name="host_timeout_observed"
    )
    del kind, eligible, host_timeout_observed
    try:
        normalize_unattended_policy(unattended_policy)
    except ApprovalTimeoutPolicyError:
        pass  # Unknown policy remains human-owned and fail-closed.
    if phase == "expired":
        return "expired"
    if phase != "reassess_due":
        return "not_due"
    if not world_current:
        return "cancel_and_rerender"
    return "remind_and_wait"


def new_human_request(
    *,
    request_id: str,
    current_binding: dict[str, Any],
    now: datetime,
    monotonic_now: float,
    previous: dict[str, Any] | None = None,
    reassess_after_seconds: int = REASSESS_AFTER_SECONDS,
    ttl_seconds: int = NATIVE_HUMAN_TTL_SECONDS,
) -> dict[str, Any]:
    """Create a fresh, non-authoritative, one-shot card binding."""
    clean_id = _require_exact_string(request_id, name="request_id")
    _validate_binding(current_binding, name="current_binding")
    _require_now(now)
    monotonic = _require_finite_number(monotonic_now, name="monotonic_now")
    _validate_durations(reassess_after_seconds, ttl_seconds)
    if previous is not None:
        _validate_request(previous)
        previous_status = previous["status"]
        if previous_status not in REPLACEABLE_REQUEST_STATUSES:
            raise ApprovalTimeoutPolicyError(
                "an open or decided request cannot be silently replaced"
            )
        if clean_id == previous["request_id"]:
            raise ApprovalTimeoutPolicyError("replacement request id must be new")
        if current_binding["card_sha256"] == previous["binding"]["card_sha256"]:
            raise ApprovalTimeoutPolicyError(
                "replacement request must use a fresh card binding"
            )
    reassess_at, expires_at = approval_deadlines(
        now=now,
        reassess_after_seconds=reassess_after_seconds,
        ttl_seconds=ttl_seconds,
    )
    return {
        "request_id": clean_id,
        "status": "asked",
        "binding": dict(current_binding),
        "created_at": _utc(now).isoformat(),
        "created_monotonic": monotonic,
        "reassess_at": reassess_at,
        "expires_at": expires_at,
        "reassess_after_seconds": reassess_after_seconds,
        "ttl_seconds": ttl_seconds,
        "prompt_shown": True,
        "decision_owner": "human",
        "receipts": [],
        "reminder_count": 0,
        "execution_authorized": False,
    }


def consume_human_decision(
    request: dict[str, Any],
    decision: dict[str, Any],
    *,
    current_binding: dict[str, Any],
    authoritative_request: dict[str, Any] | None = None,
    pending_plan: dict[str, Any] | None = None,
    now: datetime,
    monotonic_now: float | None = None,
) -> dict[str, Any]:
    """Validate a late native decision into a non-authoritative CAS plan.

    This pure helper neither appends a receipt nor changes approval state.  A
    caller must pass the current authoritative snapshot and any already-pending
    plan; T06 owns the eventual approval-store/native-journal transaction.
    """
    _require_plain_json(request, name="request")
    if type(request) is not dict:
        raise _error("request must be an exact dict")
    _require_now(now)
    if monotonic_now is not None:
        _require_finite_number(monotonic_now, name="monotonic_now")

    status = request.get("status")
    if type(status) is not str or not status.strip():
        return _decision_result("invalid_request", request)
    if status == "agent_decided":
        return _decision_result("already_agent_decided", request)
    if status in {"cancelled", "superseded", "expired"}:
        return _decision_result(f"approval_{status}", request)
    if status == "decided":
        return _decision_result("already_decided", request)
    if status not in OPEN_REQUEST_STATUSES:
        return _decision_result("invalid_request", request)
    if request.get("prompt_shown") is not True:
        return _decision_result("prompt_not_shown", request)
    if request.get("decision_owner") != "human" or type(
        request.get("decision_owner")
    ) is not str:
        return _decision_result("decision_owner_not_human", request)
    if "outcome" in request:
        return _decision_result("terminal_outcome_present", request)
    if request.get("execution_authorized") is not False:
        return _decision_result("execution_authority_present", request)
    receipts = request.get("receipts")
    if type(receipts) is list and receipts:
        request_id = _require_exact_string(
            request.get("request_id"), name="request.request_id"
        )
        _validate_receipts(receipts, request_id=request_id)
        return _decision_result("receipt_already_exists", request)

    _validate_request(request)
    _validate_decision(decision)
    _validate_binding(current_binding, name="current_binding")

    authoritative = request if authoritative_request is None else authoritative_request
    _validate_request(authoritative)
    if authoritative != request:
        return _decision_result("stale_request", request)

    if pending_plan is not None:
        if type(pending_plan) is not dict:
            raise _error("pending_plan must be an exact dict or None")
        if (
            type(pending_plan.get("type")) is not str
            or pending_plan.get("type") != "validated_pending_cas"
            or type(pending_plan.get("request_id")) is not str
        ):
            raise _error("pending_plan is not a validated_pending_cas plan")
        if pending_plan["request_id"] != request["request_id"]:
            return _decision_result("foreign_pending_plan", request)
        return _decision_result("decision_plan_already_pending", request)

    phase = request_phase(
        request, now=now, monotonic_now=monotonic_now
    )
    if phase == "invalid":
        return _decision_result("invalid_request", request)
    if phase == "expired":
        return _decision_result("approval_expired", request)

    if decision["request_id"] != request["request_id"]:
        return _decision_result(
            "cas_mismatch", request, mismatches=("request_id",)
        )

    expected = request["binding"]
    decision_mismatches = _binding_mismatches(
        expected, decision, CAS_BINDING_FIELDS
    )
    current_mismatches = _binding_mismatches(
        expected, current_binding, CAS_BINDING_FIELDS
    )
    mismatches = tuple(
        dict.fromkeys(
            [f"decision.{field}" for field in decision_mismatches]
            + [f"current.{field}" for field in current_mismatches]
        )
    )
    if mismatches:
        return _decision_result(
            "cas_mismatch", request, mismatches=mismatches
        )

    outcome = decision["outcome"]
    if outcome not in {"allow", "deny"}:
        return _decision_result("invalid_outcome", request)
    projected = deepcopy(request)
    projected["execution_authorized"] = False
    return {
        "type": "validated_pending_cas",
        "status": "validated_pending_cas",
        "request_id": request["request_id"],
        "receipt_id": decision["receipt_id"],
        "outcome": outcome,
        "request": projected,
        "expected_binding": deepcopy(expected),
        "authoritative_cas_required": True,
        "execution_authorized": False,
        "execute_once": False,
        "receipt_delta": 0,
        "cas_mismatches": (),
    }


def _decision_result(
    status: str,
    request: dict[str, Any],
    *,
    mismatches: tuple[str, ...] = (),
) -> dict[str, Any]:
    projected = deepcopy(request)
    projected["execution_authorized"] = False
    return {
        "type": "decision_rejected",
        "status": status,
        "request": projected,
        "authoritative_cas_required": False,
        "execution_authorized": False,
        "execute_once": False,
        "receipt_delta": 0,
        "cas_mismatches": mismatches,
    }

#!/usr/bin/env python3
"""Pure HumanGrantV2 authority and one-shot consumption protocol.

This leaf performs no file, network, host, or policy I/O. It accepts only exact
plain-JSON documents, seals immutable-by-value grant material with canonical
SHA-256 identities, and returns deterministic CAS transitions for a caller to
commit. Display, chat, silence, and timeout observations are deliberately not
receipt authorities.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any, TypedDict


HUMAN_GRANT_SCHEMA = "sulde-human-grant-v2"
HUMAN_RECEIPT_SCHEMA = "sulde-human-grant-receipt-v2"
HUMAN_CARD_SCHEMA = "sulde-human-grant-card-v2"
HUMAN_REQUEST_SCHEMA = "sulde-human-grant-request-v2"
EXECUTION_AUTHORITY_SCHEMA = "sulde-human-grant-execution-authority-v2"
IDENTITY_SCHEMA = "sulde-human-grant-identity-v1"

RISK_READ = "read"
RISK_REVERSIBLE_LOCAL = "reversible_local"
RISK_EXTERNAL_OR_DESTRUCTIVE = "external_or_destructive"
RISK_INTEGRITY_UNKNOWN = "integrity_unknown"
RISK_CLASSES = frozenset(
    {
        RISK_READ,
        RISK_REVERSIBLE_LOCAL,
        RISK_EXTERNAL_OR_DESTRUCTIVE,
        RISK_INTEGRITY_UNKNOWN,
    }
)

RISK_FACT_FIELDS = frozenset(
    {
        "operation",
        "local_effect",
        "reversible",
        "external_effect",
        "destructive",
        "integrity_verified",
    }
)
BINDING_FIELDS = (
    "provider",
    "session_id",
    "task_epoch",
    "subject",
    "capability",
    "effect",
    "constraints",
    "world_state",
    "expires_at",
    "verifier",
)
BINDING_FIELD_SET = frozenset(BINDING_FIELDS)
MATERIAL_FIELDS = BINDING_FIELD_SET | frozenset({"card", "request", "receipt"})
GRANT_FIELDS = MATERIAL_FIELDS | frozenset(
    {"schema", "binding_sha256", "grant_sha256", "consumption"}
)
CURRENT_FIELDS = frozenset(
    {
        "provider",
        "session_id",
        "task_epoch",
        "subject",
        "capability",
        "effect",
        "constraints",
        "world_state",
        "verifier",
    }
)
CARD_FIELDS = frozenset(
    {"schema", "card_id", "binding_sha256", "display_sha256"}
)
REQUEST_FIELDS = frozenset(
    {
        "schema",
        "request_id",
        "card_id",
        "binding_sha256",
        "requested_at",
    }
)
RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "receipt_id",
        "request_id",
        "binding_sha256",
        "outcome",
        "provider",
        "session_id",
        "task_epoch",
        "verifier",
        "decided_at",
        "authority",
        "channel",
    }
)
CONSUMPTION_FIELDS = frozenset(
    {"state", "version", "previous_sha256", "authority_sha256"}
)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_TASK_EPOCH_RE = re.compile(r"^[0-9a-f]{24}$")
_MISSING = {"missing": True}


class HumanGrantV2(TypedDict):
    """Runtime representation of a sealed grant; values remain plain JSON."""

    schema: str
    provider: str
    session_id: str
    task_epoch: str
    subject: dict[str, Any]
    capability: dict[str, Any]
    effect: dict[str, Any]
    constraints: dict[str, Any]
    card: dict[str, Any]
    request: dict[str, Any]
    receipt: dict[str, Any]
    world_state: dict[str, Any]
    expires_at: str
    verifier: dict[str, Any]
    binding_sha256: str
    grant_sha256: str
    consumption: dict[str, Any]


class HumanGrantError(ValueError):
    """A grant, receipt, binding, clock, or consumption CAS is invalid."""


def _error(message: str) -> HumanGrantError:
    return HumanGrantError(message)


def _require_plain_json(value: Any, *, name: str) -> None:
    """Reject subclasses and magic objects without invoking their callbacks."""
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


def _exact_dict(
    value: Any,
    *,
    name: str,
    fields: frozenset[str] | None = None,
    nonempty: bool = False,
) -> dict[str, Any]:
    _require_plain_json(value, name=name)
    if type(value) is not dict:
        raise _error(f"{name} must be an exact dict")
    if nonempty and not value:
        raise _error(f"{name} must not be empty")
    if fields is not None and frozenset(value.keys()) != fields:
        missing = sorted(fields - frozenset(value.keys()))
        extra = sorted(frozenset(value.keys()) - fields)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise _error(f"{name} fields are invalid: {'; '.join(details)}")
    return value


def _exact_string(value: Any, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise _error(f"{name} must be an exact non-empty string")
    return value


def _digest_string(value: Any, *, name: str) -> str:
    selected = _exact_string(value, name=name)
    if _SHA256_RE.fullmatch(selected) is None:
        raise _error(f"{name} must be a canonical sha256 identity")
    return selected


def _parse_time(value: Any, *, name: str) -> datetime:
    raw = _exact_string(value, name=name)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as error:
        raise _error(f"{name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise _error(f"{name} must include a timezone")
    try:
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as error:
        raise _error(f"{name} is outside the supported timestamp range") from error


def canonical_digest(kind: Any, document: Any) -> str:
    """Return a domain-separated identity for one exact plain-JSON value."""
    namespace = _exact_string(kind, name="kind")
    _require_plain_json(document, name="document")
    envelope = {
        "document": document,
        "kind": namespace,
        "schema": IDENTITY_SCHEMA,
    }
    encoded = json.dumps(
        envelope,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def classify_risk(facts: Any) -> str:
    """Classify a complete fact set; every malformed/unknown case fails closed."""
    try:
        facts_dict = _exact_dict(
            facts, name="risk_facts", fields=RISK_FACT_FIELDS
        )
    except HumanGrantError:
        return RISK_INTEGRITY_UNKNOWN
    operation = facts_dict["operation"]
    booleans = (
        "local_effect",
        "reversible",
        "external_effect",
        "destructive",
        "integrity_verified",
    )
    if type(operation) is not str or not operation.strip():
        return RISK_INTEGRITY_UNKNOWN
    if any(type(facts_dict[field]) is not bool for field in booleans):
        return RISK_INTEGRITY_UNKNOWN
    if facts_dict["integrity_verified"] is not True:
        return RISK_INTEGRITY_UNKNOWN
    if facts_dict["external_effect"] or facts_dict["destructive"]:
        return RISK_EXTERNAL_OR_DESTRUCTIVE
    if operation == "read":
        if (
            facts_dict["local_effect"] is False
            and facts_dict["reversible"] is False
        ):
            return RISK_READ
        return RISK_INTEGRITY_UNKNOWN
    if (
        operation in {"write", "execute"}
        and facts_dict["local_effect"] is True
        and facts_dict["reversible"] is True
    ):
        return RISK_REVERSIBLE_LOCAL
    return RISK_INTEGRITY_UNKNOWN


def _validate_capability(value: Any, *, name: str) -> dict[str, Any]:
    capability = _exact_dict(
        value,
        name=name,
        fields=frozenset({"name", "risk_class", "risk_facts"}),
    )
    _exact_string(capability["name"], name=f"{name}.name")
    risk_class = _exact_string(
        capability["risk_class"], name=f"{name}.risk_class"
    )
    if risk_class not in RISK_CLASSES:
        raise _error(f"{name}.risk_class is outside the closed taxonomy")
    derived = classify_risk(capability["risk_facts"])
    if risk_class != derived:
        raise _error(f"{name}.risk_class does not match complete risk facts")
    return capability


def _validate_binding(value: Any, *, name: str) -> dict[str, Any]:
    binding = _exact_dict(value, name=name, fields=BINDING_FIELD_SET)
    _exact_string(binding["provider"], name=f"{name}.provider")
    session_id = _exact_string(
        binding["session_id"], name=f"{name}.session_id"
    )
    if len(session_id) > 256:
        raise _error(f"{name}.session_id is too long")
    task_epoch = _exact_string(
        binding["task_epoch"], name=f"{name}.task_epoch"
    )
    if _TASK_EPOCH_RE.fullmatch(task_epoch) is None:
        raise _error(f"{name}.task_epoch must be 24 lowercase hex")
    _exact_dict(binding["subject"], name=f"{name}.subject", nonempty=True)
    _validate_capability(
        binding["capability"], name=f"{name}.capability"
    )
    _exact_dict(binding["effect"], name=f"{name}.effect", nonempty=True)
    _exact_dict(binding["constraints"], name=f"{name}.constraints")
    _exact_dict(binding["world_state"], name=f"{name}.world_state")
    _parse_time(binding["expires_at"], name=f"{name}.expires_at")
    _exact_dict(binding["verifier"], name=f"{name}.verifier", nonempty=True)
    return binding


def grant_binding_identity(binding: Any) -> str:
    """Validate and identify the exact authority facts shown to the human."""
    validated = _validate_binding(binding, name="binding")
    document = {field: validated[field] for field in BINDING_FIELDS}
    return canonical_digest("human-grant-binding", document)


def _validate_material(value: Any) -> dict[str, Any]:
    material = _exact_dict(value, name="material", fields=MATERIAL_FIELDS)
    binding = {field: material[field] for field in BINDING_FIELDS}
    _validate_binding(binding, name="material.binding")
    binding_sha256 = grant_binding_identity(binding)

    card = _exact_dict(
        material["card"], name="material.card", fields=CARD_FIELDS
    )
    if card["schema"] != HUMAN_CARD_SCHEMA:
        raise _error("material.card.schema is invalid")
    card_id = _exact_string(
        card["card_id"], name="material.card.card_id"
    )
    _digest_string(
        card["display_sha256"], name="material.card.display_sha256"
    )
    if card["binding_sha256"] != binding_sha256:
        raise _error(
            "material.card.binding_sha256 does not match authority binding"
        )

    request = _exact_dict(
        material["request"], name="material.request", fields=REQUEST_FIELDS
    )
    if request["schema"] != HUMAN_REQUEST_SCHEMA:
        raise _error("material.request.schema is invalid")
    request_id = _exact_string(
        request["request_id"], name="material.request.request_id"
    )
    if request["card_id"] != card_id or type(request["card_id"]) is not str:
        raise _error("material.request.card_id does not match card")
    if request["binding_sha256"] != binding_sha256:
        raise _error(
            "material.request.binding_sha256 does not match authority binding"
        )
    requested_at = _parse_time(
        request["requested_at"], name="material.request.requested_at"
    )

    receipt = _exact_dict(
        material["receipt"], name="material.receipt", fields=RECEIPT_FIELDS
    )
    if receipt["schema"] != HUMAN_RECEIPT_SCHEMA:
        raise _error(
            "material.receipt must be a typed HumanGrantV2 receipt"
        )
    _exact_string(
        receipt["receipt_id"], name="material.receipt.receipt_id"
    )
    if (
        receipt["request_id"] != request_id
        or type(receipt["request_id"]) is not str
    ):
        raise _error("material.receipt.request_id does not match request")
    if receipt["binding_sha256"] != binding_sha256:
        raise _error(
            "material.receipt.binding_sha256 does not match authority binding"
        )
    if (
        receipt["outcome"] != "allow"
        or type(receipt["outcome"]) is not str
    ):
        raise _error("material.receipt.outcome must be allow")
    for field in ("provider", "session_id", "task_epoch", "verifier"):
        if (
            receipt[field] != material[field]
            or type(receipt[field]) is not type(material[field])
        ):
            raise _error(
                f"material.receipt.{field} does not match material.{field}"
            )
    if (
        receipt["authority"] != "human"
        or type(receipt["authority"]) is not str
    ):
        raise _error("material.receipt.authority must be human")
    if (
        receipt["channel"] != "native_typed_receipt"
        or type(receipt["channel"]) is not str
    ):
        raise _error(
            "material.receipt.channel is not execution authority"
        )
    decided_at = _parse_time(
        receipt["decided_at"], name="material.receipt.decided_at"
    )
    expires_at = _parse_time(
        material["expires_at"], name="material.expires_at"
    )
    if decided_at < requested_at:
        raise _error("material.receipt predates its request")
    if decided_at >= expires_at:
        raise _error("material.receipt was decided at or after expiry")
    return material


def _available_consumption() -> dict[str, Any]:
    return {
        "state": "available",
        "version": 0,
        "previous_sha256": None,
        "authority_sha256": None,
    }


def consumption_identity(consumption: Any) -> str:
    """Identify one exact consumption state for external compare-and-swap."""
    value = _exact_dict(
        consumption, name="consumption", fields=CONSUMPTION_FIELDS
    )
    state = _exact_string(value["state"], name="consumption.state")
    version = value["version"]
    if type(version) is not int or version < 0:
        raise _error(
            "consumption.version must be an exact non-negative int"
        )
    if state == "available":
        if (
            version != 0
            or value["previous_sha256"] is not None
            or value["authority_sha256"] is not None
        ):
            raise _error("available consumption state is malformed")
    elif state == "consumed":
        if version != 1:
            raise _error("consumed state must have version 1")
        _digest_string(
            value["previous_sha256"],
            name="consumption.previous_sha256",
        )
        _digest_string(
            value["authority_sha256"],
            name="consumption.authority_sha256",
        )
    else:
        raise _error("consumption.state must be available or consumed")
    return canonical_digest("human-grant-consumption", value)


def create_human_grant(material: Any) -> HumanGrantV2:
    """Validate one typed allow receipt and return a sealed, available grant."""
    validated = _validate_material(material)
    binding = {field: validated[field] for field in BINDING_FIELDS}
    binding_sha256 = grant_binding_identity(binding)
    immutable_material = {
        key: deepcopy(validated[key]) for key in sorted(MATERIAL_FIELDS)
    }
    grant_sha256 = canonical_digest(
        "human-grant-v2", immutable_material
    )
    grant: HumanGrantV2 = {
        "schema": HUMAN_GRANT_SCHEMA,
        **immutable_material,
        "binding_sha256": binding_sha256,
        "grant_sha256": grant_sha256,
        "consumption": _available_consumption(),
    }
    return grant


def _validate_grant(value: Any) -> dict[str, Any]:
    grant = _exact_dict(value, name="grant", fields=GRANT_FIELDS)
    if grant["schema"] != HUMAN_GRANT_SCHEMA:
        raise _error("grant.schema is invalid")
    material = {key: grant[key] for key in MATERIAL_FIELDS}
    _validate_material(material)
    binding = {field: grant[field] for field in BINDING_FIELDS}
    expected_binding = grant_binding_identity(binding)
    if grant["binding_sha256"] != expected_binding:
        raise _error("grant.binding_sha256 was tampered")
    immutable_material = {
        key: grant[key] for key in sorted(MATERIAL_FIELDS)
    }
    expected_grant = canonical_digest(
        "human-grant-v2", immutable_material
    )
    if grant["grant_sha256"] != expected_grant:
        raise _error("grant.grant_sha256 was tampered")
    consumption_identity(grant["consumption"])
    if grant["consumption"]["state"] == "consumed":
        available_sha256 = consumption_identity(
            _available_consumption()
        )
        if (
            grant["consumption"]["previous_sha256"]
            != available_sha256
        ):
            raise _error(
                "grant consumed state has a foreign predecessor"
            )
        expected_authority = canonical_digest(
            "human-grant-authority-claim",
            {
                "grant_sha256": expected_grant,
                "previous_sha256": available_sha256,
            },
        )
        if (
            grant["consumption"]["authority_sha256"]
            != expected_authority
        ):
            raise _error(
                "grant consumed state has a foreign authority claim"
            )
    return grant


def _validate_current(value: Any) -> dict[str, Any]:
    current = _exact_dict(
        value, name="current", fields=CURRENT_FIELDS
    )
    binding_probe = {
        **current,
        "expires_at": "9999-12-31T23:59:59+00:00",
    }
    _validate_binding(binding_probe, name="current.binding")
    return current


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _world_diff(
    expected: Any, observed: Any, *, path: str = ""
) -> list[dict[str, Any]]:
    if type(expected) is dict and type(observed) is dict:
        rows: list[dict[str, Any]] = []
        for key in sorted(set(expected) | set(observed)):
            child = path + "/" + _pointer_token(key)
            if key not in expected:
                rows.append(
                    {
                        "path": child,
                        "expected": deepcopy(_MISSING),
                        "observed": deepcopy(observed[key]),
                    }
                )
            elif key not in observed:
                rows.append(
                    {
                        "path": child,
                        "expected": deepcopy(expected[key]),
                        "observed": deepcopy(_MISSING),
                    }
                )
            else:
                rows.extend(
                    _world_diff(
                        expected[key], observed[key], path=child
                    )
                )
        return rows
    if type(expected) is list and type(observed) is list:
        rows = []
        for index in range(max(len(expected), len(observed))):
            child = path + "/" + str(index)
            if index >= len(expected):
                rows.append(
                    {
                        "path": child,
                        "expected": deepcopy(_MISSING),
                        "observed": deepcopy(observed[index]),
                    }
                )
            elif index >= len(observed):
                rows.append(
                    {
                        "path": child,
                        "expected": deepcopy(expected[index]),
                        "observed": deepcopy(_MISSING),
                    }
                )
            else:
                rows.extend(
                    _world_diff(
                        expected[index], observed[index], path=child
                    )
                )
        return rows
    if type(expected) is not type(observed) or expected != observed:
        return [
            {
                "path": path or "/",
                "expected": deepcopy(expected),
                "observed": deepcopy(observed),
            }
        ]
    return []


def consume_human_grant(
    grant: Any,
    *,
    current: Any,
    expected_consumption_sha256: Any,
    now: Any,
) -> dict[str, Any]:
    """Project one executable authority and an exactly-once CAS transition.

    The caller must atomically replace expected_consumption_sha256 with the
    returned next_consumption_sha256. Two concurrent projections from the same
    available value are identical; only one compare-and-swap may commit.
    """
    validated = _validate_grant(grant)
    current_value = _validate_current(current)
    expected_cas = _digest_string(
        expected_consumption_sha256,
        name="expected_consumption_sha256",
    )
    current_cas = consumption_identity(validated["consumption"])
    if expected_cas != current_cas:
        raise _error("consumption CAS mismatch")
    if validated["consumption"]["state"] != "available":
        raise _error("grant was already consumed")
    current_time = _parse_time(now, name="now")
    if current_time < _parse_time(
        validated["receipt"]["decided_at"],
        name="grant.receipt.decided_at",
    ):
        raise _error("grant receipt decision is in the future")
    if current_time >= _parse_time(
        validated["expires_at"], name="grant.expires_at"
    ):
        raise _error("grant is expired")

    for field in (
        "provider",
        "session_id",
        "task_epoch",
        "subject",
        "capability",
        "effect",
        "constraints",
        "verifier",
    ):
        if (
            type(current_value[field]) is not type(validated[field])
            or current_value[field] != validated[field]
        ):
            raise _error(
                f"current.{field} does not match grant.{field}"
            )

    diff = _world_diff(
        validated["world_state"], current_value["world_state"]
    )
    if diff:
        return {
            "status": "fresh_decision_required",
            "execution_authorized": False,
            "default_policy_recheck_required": False,
            "fresh_decision_required": True,
            "world_diff": diff,
            "grant": deepcopy(validated),
            "cas": None,
            "authority": None,
        }

    authority_sha256 = canonical_digest(
        "human-grant-authority-claim",
        {
            "grant_sha256": validated["grant_sha256"],
            "previous_sha256": current_cas,
        },
    )
    consumed = {
        "state": "consumed",
        "version": 1,
        "previous_sha256": current_cas,
        "authority_sha256": authority_sha256,
    }
    next_cas = consumption_identity(consumed)
    updated = deepcopy(validated)
    updated["consumption"] = consumed
    authority = {
        "schema": EXECUTION_AUTHORITY_SCHEMA,
        "grant_sha256": validated["grant_sha256"],
        "binding_sha256": validated["binding_sha256"],
        "authority_sha256": authority_sha256,
        "provider": validated["provider"],
        "session_id": validated["session_id"],
        "task_epoch": validated["task_epoch"],
        "subject": deepcopy(validated["subject"]),
        "capability": deepcopy(validated["capability"]),
        "effect": deepcopy(validated["effect"]),
        "constraints": deepcopy(validated["constraints"]),
        "world_state": deepcopy(validated["world_state"]),
        "expires_at": validated["expires_at"],
        "verifier": deepcopy(validated["verifier"]),
        "receipt_id": validated["receipt"]["receipt_id"],
        "execution_authorized": True,
        "default_policy_recheck_required": False,
    }
    return {
        "status": "authorized",
        "execution_authorized": True,
        "default_policy_recheck_required": False,
        "fresh_decision_required": False,
        "world_diff": [],
        "grant": updated,
        "cas": {
            "expected_consumption_sha256": current_cas,
            "next_consumption_sha256": next_cas,
            "expected_version": 0,
            "next_version": 1,
        },
        "authority": authority,
    }

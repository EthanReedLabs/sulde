#!/usr/bin/env python3
"""Canonical, data-only identities for durable approval CAS records.

This leaf deliberately knows nothing about ledgers, host permission prompts, or
protected effects.  T12 may persist the returned identities as immutable keys;
T13 may recompute them immediately before its own transaction.  A successful
validation is evidence of identity equality only and never execution authority.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any


SNAPSHOT_FIELDS = (
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
SNAPSHOT_FIELD_SET = frozenset(SNAPSHOT_FIELDS)
REQUEST_FIELDS = frozenset({"request_id", "snapshot"})
DECISION_FIELDS = frozenset(
    {"request_id", "receipt_id", "outcome", "snapshot"}
)
DECISION_OUTCOMES = frozenset({"allow", "deny"})
IDENTITY_SCHEMA = "sulde-approval-cas-identity-v1"


class ApprovalCASSchemaError(ValueError):
    """An approval identity document is malformed or fails its CAS binding."""


def _error(message: str) -> ApprovalCASSchemaError:
    return ApprovalCASSchemaError(message)


def _require_plain_json(value: Any, *, name: str) -> None:
    """Reject application objects without invoking their magic methods."""
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


def _require_exact_dict(
    value: Any,
    *,
    name: str,
    fields: frozenset[str],
) -> dict[str, Any]:
    _require_plain_json(value, name=name)
    if type(value) is not dict:
        raise _error(f"{name} must be an exact dict")
    actual = frozenset(value.keys())
    if actual != fields:
        missing = sorted(fields - actual)
        extra = sorted(actual - fields)
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise _error(f"{name} fields are invalid: {'; '.join(details)}")
    return value


def _require_exact_string(value: Any, *, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise _error(f"{name} must be an exact non-empty string")
    return value


def _canonical_snapshot(value: Any, *, name: str) -> dict[str, str | int]:
    snapshot = _require_exact_dict(
        value,
        name=name,
        fields=SNAPSHOT_FIELD_SET,
    )
    canonical: dict[str, str | int] = {}
    for field in SNAPSHOT_FIELDS:
        field_value = snapshot[field]
        if field == "revision":
            if type(field_value) is not int:
                raise _error(f"{name}.revision must be an exact int, not bool")
            if field_value < 0:
                raise _error(f"{name}.revision must not be negative")
            canonical[field] = field_value
        else:
            canonical[field] = _require_exact_string(
                field_value,
                name=f"{name}.{field}",
            )
    return canonical


def _canonical_request(value: Any, *, name: str) -> dict[str, Any]:
    request = _require_exact_dict(value, name=name, fields=REQUEST_FIELDS)
    return {
        "request_id": _require_exact_string(
            request["request_id"], name=f"{name}.request_id"
        ),
        "snapshot": _canonical_snapshot(
            request["snapshot"], name=f"{name}.snapshot"
        ),
    }


def _canonical_decision(value: Any, *, name: str) -> dict[str, Any]:
    decision = _require_exact_dict(value, name=name, fields=DECISION_FIELDS)
    outcome = _require_exact_string(
        decision["outcome"], name=f"{name}.outcome"
    )
    if outcome not in DECISION_OUTCOMES:
        raise _error(f"{name}.outcome must be allow or deny")
    return {
        "request_id": _require_exact_string(
            decision["request_id"], name=f"{name}.request_id"
        ),
        "receipt_id": _require_exact_string(
            decision["receipt_id"], name=f"{name}.receipt_id"
        ),
        "outcome": outcome,
        "snapshot": _canonical_snapshot(
            decision["snapshot"], name=f"{name}.snapshot"
        ),
    }


def _require_same_snapshot(
    expected: dict[str, str | int],
    observed: dict[str, str | int],
    *,
    expected_name: str,
    observed_name: str,
) -> None:
    for field in SNAPSHOT_FIELDS:
        if expected[field] != observed[field]:
            raise _error(
                f"{observed_name}.{field} does not match "
                f"{expected_name}.{field}"
            )


def canonical_identity(namespace: Any, document: Any) -> str:
    """Return a domain-separated SHA-256 identity for exact plain JSON.

    ``namespace`` is part of the hashed envelope, so structurally identical
    snapshots, requests, decisions, and replacements cannot share identities.
    """
    identity_namespace = _require_exact_string(namespace, name="namespace")
    _require_plain_json(document, name="document")
    envelope = {
        "document": document,
        "kind": identity_namespace,
        "schema": IDENTITY_SCHEMA,
    }
    encoded = json.dumps(
        envelope,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def snapshot_identity(snapshot: Any) -> str:
    """Validate and identify one exact nine-domain authority snapshot."""
    return canonical_identity(
        "approval-snapshot",
        _canonical_snapshot(snapshot, name="snapshot"),
    )


def approval_request_identity(request: Any) -> str:
    """Validate and identify ``request_id`` plus its immutable snapshot."""
    return canonical_identity(
        "approval-request",
        _canonical_request(request, name="request"),
    )


def approval_decision_identity(
    decision: Any,
    *,
    request: Any,
    current_snapshot: Any,
) -> str:
    """Identify a decision after exact request and current-world CAS checks.

    The result remains data-only: it is not an execution token or receipt write.
    """
    canonical_request = _canonical_request(request, name="request")
    canonical_decision = _canonical_decision(decision, name="decision")
    canonical_current = _canonical_snapshot(
        current_snapshot, name="current_snapshot"
    )
    if canonical_decision["request_id"] != canonical_request["request_id"]:
        raise _error("decision.request_id does not match request.request_id")
    _require_same_snapshot(
        canonical_request["snapshot"],
        canonical_decision["snapshot"],
        expected_name="request.snapshot",
        observed_name="decision.snapshot",
    )
    _require_same_snapshot(
        canonical_request["snapshot"],
        canonical_current,
        expected_name="request.snapshot",
        observed_name="current_snapshot",
    )
    return canonical_identity("approval-decision", canonical_decision)


def fresh_replacement_identity(
    previous_request: Any,
    replacement_request: Any,
    *,
    current_snapshot: Any,
) -> str:
    """Identify a replacement bound to a new request, card, and current world.

    Terminal-state eligibility remains the timing policy's responsibility.  This
    leaf freezes only the identity relation which T12/T13 may persist/recheck.
    """
    previous = _canonical_request(previous_request, name="previous_request")
    replacement = _canonical_request(
        replacement_request, name="replacement_request"
    )
    current = _canonical_snapshot(current_snapshot, name="current_snapshot")
    if replacement["request_id"] == previous["request_id"]:
        raise _error(
            "replacement_request.request_id must differ from "
            "previous_request.request_id"
        )
    if (
        replacement["snapshot"]["card_sha256"]
        == previous["snapshot"]["card_sha256"]
    ):
        raise _error(
            "replacement_request.snapshot.card_sha256 must differ from "
            "previous_request.snapshot.card_sha256"
        )
    _require_same_snapshot(
        replacement["snapshot"],
        current,
        expected_name="replacement_request.snapshot",
        observed_name="current_snapshot",
    )
    document = {
        "previous_request_identity": canonical_identity(
            "approval-request", previous
        ),
        "replacement_request_identity": canonical_identity(
            "approval-request", replacement
        ),
    }
    return canonical_identity("approval-fresh-replacement", document)

"""Exact completion pairing and append-only recovery for authorized effects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from grant_broker import (
    EFFECT_RECEIPT_SCHEMA,
    VERIFIER_RECEIPT_SCHEMA,
    GrantBrokerError,
    effect_receipt_identity,
    record_effect_receipt,
    record_verifier_receipt,
    settle as settle_grant_transaction,
    transaction as grant_transaction,
)
from intervention import (
    InterventionError,
    load_projection as load_intervention_projection,
    mark_attempt_result,
    verify_from_read,
)

from .events import _completion_open_event_index
from .state import audit_path, now_iso


_TRUSTED_VERIFIERS = frozenset(
    {
        ("mcp:sulde_kb:memory_graph", "local_memory_db_read"),
        ("tool:codex_plugin_install_verify", "local_codex_install_read"),
        ("tool:codex_plugin_cachebuster_verify", "local_codex_cachebuster_read"),
        ("tool:git_worktree_lifecycle_verify", "local_git_worktree_lifecycle_read"),
    }
)


def matching_authorized_completion(
    open_events: list[Any],
    event: dict[str, Any],
    *,
    fingerprint: str,
) -> dict[str, Any] | None:
    """Return one exact material dispatch paired to this completion callback."""
    if event.get("phase") != "completed":
        return None
    index = _completion_open_event_index(
        open_events,
        event,
        fingerprint=fingerprint,
    )
    if index is None:
        return None
    opened = open_events[index]
    if not isinstance(opened, dict) or not str(opened.get("attempt_id") or ""):
        return None
    return opened


def _trusted_independent(event: dict[str, Any]) -> dict[str, Any] | None:
    independent = event.get("independent_verification")
    if not isinstance(independent, dict) or (
        str(independent.get("capability") or ""),
        str(independent.get("source") or ""),
    ) not in _TRUSTED_VERIFIERS:
        return None
    evidence = independent.get("evidence")
    return independent if isinstance(evidence, dict) else None


def _matching_grant_transaction(
    path: Path,
    attempt: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any] | None:
    source_event_id = str(attempt.get("source_event_id") or "")
    candidates: list[dict[str, Any]] = []
    for row in _audit_rows(path):
        started = row.get("event")
        human = started.get("human_grant_dispatch") if isinstance(started, dict) else None
        dispatch = human.get("dispatch") if isinstance(human, dict) else None
        tx_id = str(human.get("transaction_id") or "") if isinstance(human, dict) else ""
        if not (
            isinstance(started, dict)
            and started.get("phase") == "started"
            and started.get("event_id") == source_event_id
            and isinstance(dispatch, dict)
            and tx_id
        ):
            continue
        try:
            item = grant_transaction(path, tx_id)
        except (GrantBrokerError, OSError, UnicodeError, ValueError):
            continue
        spec = item.get("spec")
        effect = dispatch.get("effect")
        if not (
            isinstance(spec, dict)
            and isinstance(effect, dict)
            and item.get("settlement") is None
            and dispatch.get("transaction_id") == tx_id == item.get("transaction_id")
            and str(dispatch.get("consumer_id") or "") == source_event_id
            and spec.get("provider") == attempt.get("provider") == event.get("provider")
            and spec.get("session_id")
            == attempt.get("session_id")
            == event.get("session_id")
            and spec.get("task_epoch") == event.get("task_epoch")
            and effect.get("target") == attempt.get("target") == event.get("target")
            and effect.get("capability")
            == attempt.get("capability")
            == event.get("capability")
            and effect.get("effect") == attempt.get("effect") == event.get("effect")
            and effect.get("arguments_digest")
            == attempt.get("operation_arguments_digest")
            == event.get("arguments_digest")
            and effect.get("event_fingerprint")
            == attempt.get("fingerprint")
            == event.get("fingerprint")
        ):
            continue
        candidates.append(
            {
                "transaction": item,
                "transaction_id": tx_id,
                "dispatch": dispatch,
                "started_event": started,
            }
        )
    return candidates[0] if len(candidates) == 1 else None


def settle_matching_human_grant(
    path: Path,
    attempt: dict[str, Any],
    event: dict[str, Any],
    *,
    verification_passed: bool,
) -> dict[str, Any] | None:
    """Record effect/verifier receipts for one exact broker-owned dispatch."""
    selected = _matching_grant_transaction(path, attempt, event)
    if selected is None:
        return None
    tx_id = str(selected["transaction_id"])
    dispatch = selected["dispatch"]
    transaction = selected["transaction"]
    spec = transaction["spec"]
    effect_status = "failed" if event.get("success") is False else "succeeded"
    effect_receipt = {
        "schema": EFFECT_RECEIPT_SCHEMA,
        "transaction_id": tx_id,
        "dispatch_id": dispatch["dispatch_id"],
        "receipt_id": f"effect-{tx_id}-{event['event_id']}",
        "provider": spec["provider"],
        "session_id": spec["session_id"],
        "task_epoch": spec["task_epoch"],
        "authority_sha256": dispatch["authority_sha256"],
        "status": effect_status,
        "observed_at": str(event.get("at") or now_iso()),
        "result": {
            "attempt_id": str(attempt.get("attempt_id") or ""),
            "event_id": str(event.get("event_id") or ""),
            "verification_sha256": str(attempt.get("verification_sha256") or ""),
        },
    }
    try:
        record_effect_receipt(path, effect_receipt)
        independent = _trusted_independent(event)
        if (
            effect_status == "succeeded"
            and verification_passed
            and independent is not None
        ):
            record_verifier_receipt(
                path,
                {
                    "schema": VERIFIER_RECEIPT_SCHEMA,
                    "transaction_id": tx_id,
                    "effect_receipt_sha256": effect_receipt_identity(effect_receipt),
                    "receipt_id": f"verify-{tx_id}-{event['event_id']}",
                    "verifier": {
                        "kind": "independent-effect-readback",
                        "resource": str(attempt.get("target") or ""),
                    },
                    "status": "passed",
                    "verified_at": str(event.get("at") or now_iso()),
                    "evidence": {
                        "attempt_id": str(attempt.get("attempt_id") or ""),
                        "event_id": str(event.get("event_id") or ""),
                        "capability": independent["capability"],
                        "source": independent["source"],
                        "readback": independent["evidence"],
                    },
                },
            )
        return settle_grant_transaction(path, tx_id, now=now_iso())
    except (GrantBrokerError, OSError, UnicodeError, ValueError, KeyError, TypeError):
        return None


def _audit_rows(path: Path) -> list[dict[str, Any]]:
    target = audit_path(path)
    if not target.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    except (OSError, UnicodeError, ValueError):
        return []
    return rows


def _completion_matches_attempt(
    row: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any] | None:
    event = row.get("event")
    contract = row.get("contract")
    independent = _trusted_independent(event) if isinstance(event, dict) else None
    if not (
        isinstance(event, dict)
        and isinstance(contract, dict)
        and event.get("phase") == "completed"
        and event.get("success") is not False
        and independent is not None
        and contract.get("intent_id") == attempt.get("intent_id")
        and contract.get("revision") == attempt.get("intent_revision")
        and event.get("event_id") == attempt.get("source_event_id")
        and event.get("fingerprint") == attempt.get("fingerprint")
        and event.get("provider") == attempt.get("provider")
        and event.get("session_id") == attempt.get("session_id")
        and event.get("capability") == attempt.get("capability")
        and event.get("effect") == attempt.get("effect")
        and event.get("target") == attempt.get("target")
        and event.get("effect_resource_key") == attempt.get("resource_key")
        and event.get("effect_operation_fingerprint")
        == attempt.get("operation_fingerprint")
        and event.get("arguments_digest")
        == attempt.get("operation_arguments_digest")
        and event.get("verification_sha256")
        == attempt.get("verification_sha256")
    ):
        return None
    kind = str(attempt.get("verification_kind") or "")
    evidence = independent["evidence"]
    return event if attempt.get("verification_sha256") in evidence.get(kind, []) else None


def _safe_boundary_unknown(
    projection: dict[str, Any],
    attempt: dict[str, Any],
) -> bool:
    """Recognize only the system-opened unknown state created at turn finalization.

    A Stop callback may run before the explicit reconciler and conservatively
    move an orphaned dispatched attempt to ``unknown``.  That ordering must not
    erase an already-recorded exact completion and independent verifier.  It
    also must not revive an aborted or otherwise resolved intervention.
    """
    if attempt.get("state") != "unknown":
        return False
    matches = [
        row
        for row in projection.get("interventions", {}).values()
        if isinstance(row, dict)
        and row.get("attempt_id") == attempt.get("attempt_id")
        and row.get("status") in {"open", "acknowledged"}
        and row.get("actor") == "system"
        and str(row.get("reason") or "").startswith(
            "safe-boundary recovery found an active effect attempt"
        )
    ]
    return len(matches) == 1


def recover_completed_audit_verifications(path: Path) -> list[dict[str, Any]]:
    """Settle exact orphan completions from Hook evidence without replaying effects."""
    try:
        projection = load_intervention_projection(path)
    except (InterventionError, OSError, UnicodeError):
        return []
    rows = _audit_rows(path)
    recovered: list[dict[str, Any]] = []
    for attempt in projection.get("attempts", {}).values():
        if not (
            isinstance(attempt, dict)
            and attempt.get("replay_authoritative") is True
            and (
                attempt.get("state") == "dispatched"
                or _safe_boundary_unknown(projection, attempt)
            )
        ):
            continue
        matches = [
            event
            for row in rows
            for event in [_completion_matches_attempt(row, attempt)]
            if event is not None
        ]
        if len(matches) != 1:
            continue
        event = matches[0]
        independent = _trusted_independent(event)
        broker_dispatch = _matching_grant_transaction(path, attempt, event)
        if (
            any(
                isinstance(row.get("event"), dict)
                and row["event"].get("event_id") == attempt.get("source_event_id")
                and isinstance(row["event"].get("human_grant_dispatch"), dict)
                for row in rows
            )
            and broker_dispatch is None
        ):
            continue
        try:
            verifying = (
                mark_attempt_result(
                    path,
                    str(attempt["attempt_id"]),
                    success=event.get("success"),
                    reason="exact completed Hook callback recovered from append-only audit",
                )
                if attempt.get("state") == "dispatched"
                else attempt
            )
            verified = verify_from_read(
                path,
                provider=str(attempt["provider"]),
                session_id=str(attempt["session_id"]),
                capability=str(independent["capability"]),
                target=str(attempt["target"]),
                resource_key=str(attempt.get("resource_key") or ""),
                resource_base=str(attempt.get("resource_base") or "") or None,
                resource_context=(
                    attempt.get("resource_context")
                    if isinstance(attempt.get("resource_context"), dict)
                    else None
                ),
                verification_event_id=str(event["event_id"]),
                explicit_attempt_id=str(attempt["attempt_id"]),
                evidence=independent["evidence"],
            )
        except (InterventionError, OSError, UnicodeError, KeyError, TypeError):
            continue
        if not verified:
            continue
        broker = settle_matching_human_grant(
            path,
            verifying,
            event,
            verification_passed=True,
        )
        recovered.append(
            {
                "attempt_id": str(attempt["attempt_id"]),
                "write_fingerprint": str(attempt.get("fingerprint") or ""),
                "write_capability": str(attempt.get("capability") or ""),
                "target": str(attempt.get("target") or ""),
                "verified_by_event": str(event["event_id"]),
                "verified_by_capability": str(independent["capability"]),
                "verified_at": now_iso(),
                "verification_source": "append_only_hook_recovery",
                "evidence_source": str(independent["source"]),
                "grant_broker_status": str((broker or {}).get("status") or "not_applicable"),
                "compensates_attempt_id": str(
                    verified[0].get("compensates_attempt_id") or ""
                ),
            }
        )
    return recovered

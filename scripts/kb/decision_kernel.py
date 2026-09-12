#!/usr/bin/env python3
"""Production composition for HumanGrantV2 and ordinary Guardian policy.

The R2 authority components are deliberately independent.  This module is the
small production seam that composes them in the required order:

    immutable exclusions -> typed HumanGrant claim -> ordinary policy

It never turns chat, prompt display, timeout, or a copied identifier into
authority.  Only a GrantBroker transaction carrying a native typed human
receipt can be consumed, and the resulting dispatch has one CAS winner.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from grant_broker import (
    DECISION_SCHEMA,
    OBSERVATION_SCHEMA,
    PROTOCOL_SCHEMA,
    GrantBrokerError,
    claim_dispatch,
    consume_allow,
    create_transaction,
    journal_path,
    pending,
    publish_question,
    record_human_decision,
    record_observation,
    settle,
    transaction,
)
from intent_guardian_parts.state import event_fingerprint, now_iso, policy_digest


GRANT_REASON_CODES = frozenset({
    "task_scope_denied",
    "external_effect_not_authorized",
})


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _targets(event: dict[str, Any]) -> list[str]:
    values = event.get("write_targets")
    if isinstance(values, list) and all(isinstance(item, str) and item for item in values):
        return list(values)
    target = str(event.get("target") or "")
    return [target] if target else []


def _risk_capability(event: dict[str, Any]) -> dict[str, Any]:
    effect = str(event.get("effect") or "unknown")
    operation = "write" if effect == "local_write" else "execute"
    external = effect == "external_write"
    return {
        "name": str(event.get("capability") or "unknown"),
        "risk_class": "external_or_destructive" if external else "reversible_local",
        "risk_facts": {
            "operation": operation,
            "local_effect": not external,
            "reversible": not external,
            "external_effect": external,
            "destructive": False,
            "integrity_verified": True,
        },
    }


def event_effect(event: dict[str, Any]) -> dict[str, Any]:
    """Return the exact tool facts bound to a one-shot grant."""
    return {
        "operation": str(event.get("action") or "unknown"),
        "target": str(event.get("target") or "unknown"),
        "capability": str(event.get("capability") or "unknown"),
        "effect": str(event.get("effect") or "unknown"),
        "arguments_digest": str(event.get("arguments_digest") or ""),
        "event_fingerprint": str(event.get("fingerprint") or event_fingerprint(event)),
    }


def _constraints(event: dict[str, Any]) -> dict[str, Any]:
    return {"one_shot": True, "targets": _targets(event)}


def _world_state(contract: dict[str, Any]) -> dict[str, Any]:
    runtime = contract.get("runtime") if isinstance(contract.get("runtime"), dict) else {}
    return {
        "intent_revision": int(contract.get("revision") or 0),
        "policy_digest": policy_digest(contract),
        "material_sequence": int(runtime.get("material_sequence") or 0),
        "status": str(contract.get("status") or "unknown"),
    }


def _verifier(event: dict[str, Any]) -> dict[str, Any]:
    effect = str(event.get("effect") or "unknown")
    return {
        "kind": "guardian-post-tool-readback" if effect == "local_write" else "independent-effect-readback",
        "resource": str(event.get("effect_resource_key") or event.get("target") or "unknown"),
    }


def event_binding(contract: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": str(event.get("provider") or "unknown"),
        "session_id": str(event.get("session_id") or ""),
        "task_epoch": str(contract.get("task_epoch") or ""),
        "subject": {
            "intent_id": str(contract.get("intent_id") or "unknown"),
            "revision": int(contract.get("revision") or 0),
        },
        "capability": _risk_capability(event),
        "effect": event_effect(event),
        "constraints": _constraints(event),
        "world_state": _world_state(contract),
        "verifier": _verifier(event),
    }


def grant_eligible(
    contract: dict[str, Any], event: dict[str, Any], decision: Any
) -> bool:
    """Keep immutable safety exclusions ahead of the human grant route."""
    effect = str(event.get("effect") or "")
    if effect == "local_write" and contract.get("permissions", {}).get("local_write") is not True:
        return False
    if effect == "external_write" and contract.get("permissions", {}).get("external_write") == "deny":
        return False
    if effect == "local_write":
        from intent_guardian_parts.events import _paths_frozen

        if _paths_frozen(_targets(event), contract):
            return False
    return bool(
        str(event.get("phase") or "") == "started"
        and str(event.get("provider") or "").lower() == "codex"
        and str(event.get("session_id") or "")
        and effect in {"local_write", "external_write"}
        and not event.get("sensitive_input")
        and not event.get("destructive_local_operation")
        and not event.get("control_plane")
        and not event.get("blocked_by_attempt_id")
        and event.get("supervision_domain") != "execution_passthrough"
        and str(contract.get("status") or "") == "active"
        and not contract.get("confirmation", {}).get("required")
        and not contract.get("runtime", {}).get("pending_proposal_digest")
        and getattr(decision, "dispatch", "deny") == "deny"
        and getattr(decision, "lifecycle", "pause") == "continue"
        and getattr(decision, "reason_code", "") in GRANT_REASON_CODES
    )


def _readable_card(event: dict[str, Any]) -> dict[str, Any]:
    targets = _targets(event)
    return {
        "操作": str(event.get("action") or event.get("capability") or "当前动作"),
        "范围": targets or [str(event.get("target") or "unknown")],
        "Allow": "仅执行这一个精确动作一次",
        "Deny": "保持当前状态，不执行该动作",
        "风险": str(event.get("effect") or "unknown"),
    }


def prepare_human_grant(
    contract_path: Path,
    contract: dict[str, Any],
    event: dict[str, Any],
    decision: Any,
    *,
    current_time: datetime | None = None,
) -> dict[str, Any] | None:
    """Create or reuse one exact question for an eligible ordinary denial."""
    if not grant_eligible(contract, event, decision):
        return None
    binding = event_binding(contract, event)
    try:
        if journal_path(contract_path).is_file():
            matches = [
                item for item in pending(contract_path)
                if item.get("decision") is None
                and all(item.get("spec", {}).get(field) == binding[field] for field in binding)
            ]
            if len(matches) == 1 and matches[0].get("question") is not None:
                return matches[0]
            if len(matches) > 1:
                return None
        requested = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
        spec = {
            "schema": PROTOCOL_SCHEMA,
            "provider": binding["provider"],
            "session_id": binding["session_id"],
            "task_epoch": binding["task_epoch"],
            "lane": f"{binding['provider']}:{binding['session_id']}",
            "subject": binding["subject"],
            "capability": binding["capability"],
            "effect": binding["effect"],
            "constraints": binding["constraints"],
            "world_state": binding["world_state"],
            "verifier": binding["verifier"],
            "readable_card": _readable_card(event),
            "requested_at": _iso(requested),
            "reassess_at": _iso(requested + timedelta(minutes=5)),
            "expires_at": _iso(requested + timedelta(minutes=30)),
        }
        created = create_transaction(contract_path, spec)
        publish_question(contract_path, created["transaction_id"])
        return transaction(contract_path, created["transaction_id"])
    except (GrantBrokerError, OSError, UnicodeError, ValueError):
        return None


def confirmation_reason(event: dict[str, Any]) -> str:
    card = _readable_card(event)
    scope = "、".join(str(item) for item in card["范围"])
    return (
        f"此动作需要一次当前会话确认。操作：{card['操作']}。范围：{scope}。"
        "Allow 仅执行一次；Deny 不执行。"
    )


def claim_human_grant(
    contract_path: Path,
    contract: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any] | None:
    """Consume an exact native Allow before ordinary policy evaluates again."""
    if str(event.get("phase") or "") != "started" or not journal_path(contract_path).is_file():
        return None
    binding = event_binding(contract, event)
    static_fields = tuple(field for field in binding if field != "world_state")
    try:
        candidates: list[dict[str, Any]] = []
        for item in pending(contract_path):
            if not isinstance(item, dict):
                continue
            decision = item.get("decision")
            spec = item.get("spec")
            # An active transaction normally carries ``decision: null`` until
            # the native host records Allow/Deny.  Missing and explicit-null
            # decisions are both non-authorizing and must never crash the
            # ordinary PreTool path.
            if not isinstance(decision, dict) or decision.get("outcome") != "allow":
                continue
            if not isinstance(spec, dict):
                continue
            if all(spec.get(field) == binding[field] for field in static_fields):
                candidates.append(item)
        if len(candidates) != 1:
            return None
        selected = candidates[0]
        tx_id = str(selected["transaction_id"])
        consumed = consume_allow(
            contract_path,
            tx_id,
            current=deepcopy(binding),
            now=now_iso(),
        )
        if consumed.get("status") not in {"consumed", "already_consumed"}:
            return None
        consumer = str(event.get("event_id") or event.get("call_id") or event_fingerprint(event))
        claimed = claim_dispatch(contract_path, tx_id, consumer_id=consumer)
        if claimed.get("status") != "claimed":
            return None
        return {
            "schema": "sulde-decision-kernel-human-dispatch-v1",
            "transaction_id": tx_id,
            "dispatch": claimed["dispatch"],
            "ordinary_pretool_policy_required": False,
        }
    except (GrantBrokerError, OSError, UnicodeError, ValueError, KeyError, TypeError):
        return None


def grant_transaction_context(
    contract_path: Path,
    *,
    target: str,
    provider: str,
    session_id: str,
    task_epoch: str,
) -> dict[str, Any]:
    """Resolve one current native grant card without transferring authority."""
    candidates = [
        item for item in pending(contract_path)
        if item.get("spec", {}).get("provider") == provider
        and item.get("spec", {}).get("session_id") == session_id
        and item.get("spec", {}).get("task_epoch") == task_epoch
        and item.get("question") is not None
        and item.get("decision") is None
    ]
    if target != "current":
        candidates = [item for item in candidates if item.get("transaction_id") == target]
    if len(candidates) != 1:
        raise GrantBrokerError("current grant transaction is missing or ambiguous")
    return candidates[0]


def observe_grant_prompt(
    contract_path: Path,
    tx: dict[str, Any],
    *,
    observed_at: str | None = None,
) -> dict[str, Any]:
    spec, question = tx["spec"], tx["question"]
    return record_observation(contract_path, {
        "schema": OBSERVATION_SCHEMA,
        "transaction_id": tx["transaction_id"],
        "request_id": question["request_id"],
        "provider": spec["provider"],
        "session_id": spec["session_id"],
        "task_epoch": spec["task_epoch"],
        "kind": "displayed",
        "observed_at": observed_at or now_iso(),
        "detail": {"surface": "codex_permission_request"},
    })


def record_grant_decision(
    contract_path: Path,
    tx: dict[str, Any],
    *,
    outcome: str,
    decided_at: str | None = None,
) -> dict[str, Any]:
    spec, question = tx["spec"], tx["question"]
    timestamp = decided_at or now_iso()
    result = record_human_decision(contract_path, {
        "schema": DECISION_SCHEMA,
        "transaction_id": tx["transaction_id"],
        "request_id": question["request_id"],
        "receipt_id": f"native-{question['request_id']}-{outcome}",
        "provider": spec["provider"],
        "session_id": spec["session_id"],
        "task_epoch": spec["task_epoch"],
        "outcome": outcome,
        "decided_at": timestamp,
        "authority": "human",
        "channel": "native_typed_receipt",
        "question_sha256": question["question_sha256"],
    })
    if outcome == "deny" and result.get("status") in {"decided", "duplicate"}:
        settle(contract_path, tx["transaction_id"], now=timestamp)
    return result

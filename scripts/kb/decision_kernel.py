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
from intent_guardian_parts.decision_types import Decision


GRANT_REASON_CODES = frozenset({
    "task_scope_denied",
    "external_effect_not_authorized",
})


def consumed_grant_decision(event: dict[str, Any], fingerprint: str,
                            blocker_description: str = "") -> Decision:
    """Render the already-claimed grant outcome; never create authority here.

    Policy retains the barrier/freshness checks and effect admission independently
    authenticates the broker receipt. Keeping this pure projection in the kernel
    avoids growing the policy orchestrator with another copy of grant outcomes.
    """
    if blocker_description:
        return Decision(
            dispatch="deny", would_dispatch="deny", lifecycle="continue",
            authority="none", verification="none", evidence_state="observed",
            severity="critical", reason=blocker_description + "；一次性授权未被执行",
            fingerprint=fingerprint, reason_code="effect_barrier_denied",
            decision_stage="safety",
        )
    return Decision(
        dispatch="allow", would_dispatch="allow", lifecycle="continue",
        authority="human_grant",
        verification="required" if event.get("effect") in {"external_write", "unknown"} else "none",
        evidence_state="observed", severity="info",
        reason="当前会话原生 Allow 已按精确绑定消费一次", fingerprint=fingerprint,
        reason_code="human_grant_consumed", decision_stage="authority",
        secondary_reasons=("default_policy_recheck:false",),
    )


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


def event_binding(
    contract: dict[str, Any], event: dict[str, Any],
    *, effect_risk_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    constraints = _constraints(event)
    if effect_risk_review is not None:
        constraints["effect_risk_review"] = deepcopy(effect_risk_review)
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
        "constraints": constraints,
        "world_state": _world_state(contract),
        "verifier": _verifier(event),
    }


def _grant_safety_eligible(contract: dict[str, Any], event: dict[str, Any]) -> bool:
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
        and event.get("supervision_domain") != "execution_passthrough"
        and str(contract.get("status") or "") == "active"
        and not contract.get("confirmation", {}).get("required")
        and not contract.get("runtime", {}).get("pending_proposal_digest")
    )


def grant_eligible(
    contract: dict[str, Any], event: dict[str, Any], decision: Any
) -> bool:
    return bool(
        _grant_safety_eligible(contract, event)
        and not event.get("blocked_by_attempt_id")
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
    return _prepare_bound_question(contract_path, binding, _readable_card(event), current_time)


def _prepare_bound_question(
    contract_path: Path, binding: dict[str, Any], card: dict[str, Any],
    current_time: datetime | None,
) -> dict[str, Any] | None:
    try:
        requested = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
        if journal_path(contract_path).is_file():
            matches = [
                item for item in pending(contract_path)
                if item.get("decision") is None
                and datetime.fromisoformat(item["spec"]["expires_at"]) > requested
                and all(item.get("spec", {}).get(field) == binding[field] for field in binding)
            ]
            if len(matches) == 1 and matches[0].get("question") is not None:
                return matches[0]
            if len(matches) > 1:
                return None
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
            "readable_card": card,
            "requested_at": _iso(requested),
            "reassess_at": _iso(requested + timedelta(minutes=5)),
            "expires_at": _iso(requested + timedelta(minutes=30)),
        }
        created = create_transaction(contract_path, spec)
        publish_question(contract_path, created["transaction_id"])
        return transaction(contract_path, created["transaction_id"])
    except (GrantBrokerError, OSError, UnicodeError, ValueError, KeyError, TypeError):
        return None


def prepare_effect_risk_grant(
    contract_path: Path, contract: dict[str, Any], event: dict[str, Any], decision: Any,
) -> dict[str, Any] | None:
    """Separate human review of one precise action despite an unknown old effect.

    This does not settle history or weaken ordinary grant eligibility. The
    normal native broker seals the entire residual-risk card and consumes once.
    """
    if (getattr(decision, "reason_code", "") != "effect_barrier_denied"
            or getattr(decision, "lifecycle", "pause") != "continue"
            or event.get("effect") != "external_write"
            or not _grant_safety_eligible(contract, event)):
        return None
    from intervention import InterventionError, effect_risk_review_context
    from intent_guardian_parts.state import contract_lock, load_contract

    try:
        with contract_lock(contract_path):
            current = load_contract(contract_path)
            if not _grant_safety_eligible(current, event):
                return None
            review = effect_risk_review_context(contract_path, event)
            card = {
                **_readable_card(event),
                "操作": "在限定 SSH 目标创建目录（mkdir -p，已有目录保留）",
                "历史效果": "仍未验证；本次决定不把旧操作标记为成功或失败",
                "历史尝试": review.get("attempt_ids", [review["attempt_id"]]),
                "历史数量": len(review.get("attempt_ids", [review["attempt_id"]])),
                "资源限制": "当前目标有精确字面范围，但未证明与历史目标相同或不同",
                "Allow": "接受与卡片列明的历史未知效果可能冲突的风险，仅执行本次精确动作一次",
                "后续": "旧记录保持 unknown；新操作仍需独立验证，后续操作不继承授权",
            }
            return _prepare_bound_question(
                contract_path, event_binding(current, event, effect_risk_review=review), card, None,
            )
    except (InterventionError, OSError, ValueError, TypeError, KeyError):
        return None


def confirmation_reason(event: dict[str, Any], prepared: dict[str, Any] | None = None) -> str:
    card = _readable_card(event)
    scope = "、".join(str(item) for item in card["范围"])
    risk = (prepared or {}).get("spec", {}).get("constraints", {}).get("effect_risk_review")
    risk_count = len(risk.get("attempt_ids", [risk["attempt_id"]])) if risk else 0
    return (
        f"此动作需要一次当前会话确认。操作：{card['操作']}。范围：{scope}。"
        + (f"本次确认接受与 {risk_count} 笔历史未知效果可能冲突的风险，不结算旧效果。" if risk else "")
        +
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
            review = spec.get("constraints", {}).get("effect_risk_review")
            candidate_binding = binding
            if review is not None:
                from intervention import effect_risk_acceptance_matches

                if not effect_risk_acceptance_matches(contract_path, event, review):
                    continue
                candidate_binding = event_binding(contract, event, effect_risk_review=review)
            if all(spec.get(field) == candidate_binding[field] for field in static_fields):
                candidates.append(item)
        if len(candidates) != 1:
            return None
        selected = candidates[0]
        review = selected["spec"]["constraints"].get("effect_risk_review")
        if review is not None:
            binding = event_binding(contract, event, effect_risk_review=review)
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
        result = {
            "schema": "sulde-decision-kernel-human-dispatch-v1",
            "transaction_id": tx_id,
            "dispatch": claimed["dispatch"],
            "ordinary_pretool_policy_required": False,
        }
        if review is not None:
            result["effect_risk_review"] = deepcopy(review)
        return result
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
    available = pending(contract_path)
    if target != "current":
        available = [item for item in available if item.get("transaction_id") == target]
    if not available:
        raise GrantBrokerError(
            "grant_transaction_missing: no pending card exists for this operation; "
            "inspect the denial reason and use its recovery route, not a repeated approval"
        )
    candidates = [
        item for item in available
        if item.get("spec", {}).get("provider") == provider
        and item.get("spec", {}).get("session_id") == session_id
        and item.get("spec", {}).get("task_epoch") == task_epoch
        and item.get("question") is not None
        and item.get("decision") is None
    ]
    if not candidates:
        raise GrantBrokerError(
            "grant_transaction_identity_mismatch: no undecided displayed card "
            "belongs to the current provider/session/task epoch"
        )
    now = datetime.now(timezone.utc)
    current = []
    for item in candidates:
        try:
            expires = datetime.fromisoformat(item["spec"]["expires_at"])
            if expires.tzinfo is None:
                raise ValueError("missing timezone")
        except (KeyError, TypeError, ValueError) as error:
            raise GrantBrokerError("grant_transaction_invalid_expiry") from error
        if expires > now:
            current.append(item)
    if not current:
        raise GrantBrokerError(
            "grant_transaction_expired: render a fresh scope-bound decision; "
            "the old card cannot grant authority"
        )
    if len(current) != 1:
        raise GrantBrokerError(
            "grant_transaction_ambiguous: select the exact pending operation; "
            "multiple current-session cards must not be chosen implicitly"
        )
    return current[0]


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

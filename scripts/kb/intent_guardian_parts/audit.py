"""Intent Guardian audit domain component."""

from __future__ import annotations

from contextlib import contextmanager

from dataclasses import dataclass, replace

from datetime import datetime, timezone

import fnmatch

import hashlib

import json

import os

from pathlib import Path

import re

import shutil

import sqlite3

import stat

import subprocess

import sys

import tempfile

import time

from typing import Any, Callable, Iterable, Iterator

from command_template import (
    has_unquoted_shell_control as _has_unquoted_shell_control,
    is_read_only_command as _is_read_only_command,
    literal_git_add_paths as _literal_git_add_paths,
    read_pipeline_segments as _read_pipeline_segments,
    split_command_template,
)

from file_lock import lock_exclusive_nonblocking, unlock

from human_control import parse_human_control, text_control_requires_native

from decision_kernel import (
    claim_human_grant,
    confirmation_reason,
    prepare_human_grant,
)
from production_recovery import route_production_recovery

from host_capabilities import (
    HostCapabilityError,
    readiness_projection as host_readiness_projection,
)

from launcher_contract import (
    classify_trusted_script_command,
    identify_trusted_script_command,
    verify_installation as verify_launcher_installation,
)
from sulde_paths import launcher_home

from local_file_operations import (
    LocalFileOperationError,
    has_destructive_operation,
    operation_targets,
    parse_apply_patch_operations,
)

from resource_adapters import (
    ResourceAdapterError as ResourceVerificationError,
    verify_git_worktree_lifecycle,
)

from approval_invariant import (
    ApprovalInvariantError,
    authoritative_store_bytes as approval_authoritative_store_bytes,
    ask_approval,
    cancel_request as cancel_approval_request,
    cancel_open_requests as cancel_open_approval_requests,
    decide_approval,
    load_projection as load_approval_projection,
    open_requests as approval_open_requests,
    request_by_id as approval_request_by_id,
    request_for_binding as approval_request_for_binding,
    request_phase as approval_request_phase,
    restore_authoritative_store as restore_approval_authoritative_store,
    summary as approval_pair_summary,
)

from approval_timeout_policy import (
    ApprovalTimeoutPolicyError,
    NATIVE_HUMAN_TTL_SECONDS,
    REASSESS_AFTER_SECONDS,
    UNATTENDED_AGENT_IF_ELIGIBLE,
    UNATTENDED_WAIT,
    normalize_unattended_policy,
    timeout_disposition,
)

from correction_intervention import (
    CorrectionInterventionError,
    apply_queued_corrections,
    event_store_path as correction_event_store_path,
    propose_correction,
    summary as correction_intervention_summary,
    transition_correction,
)

from intervention import (
    InterventionError,
    acknowledge_intervention as acknowledge_effect_intervention_store,
    authorize_system_retry as authorize_effect_system_retry,
    authoritative_store_bytes,
    begin_attempt,
    blocking_attempts,
    canonical_resource_key,
    effect_operation_fingerprint,
    git_ref_verification_digest,
    load_projection as load_intervention_projection,
    mark_attempt_result,
    mark_attempt_unknown,
    material_event_blocker,
    open_interventions,
    resolve_intervention as resolve_effect_intervention_store,
    resolve_attempt_target,
    restore_authoritative_store,
    retry_grant_for_event,
    summary as intervention_summary,
    verify_from_read,
)

from session_continuity import (
    CONTINUATION_EVENT_SCHEMA,
    ContinuationError,
    build_capsule,
    capsule_summary,
    continuation_path,
    load_capsule,
    locate_codex_rollout,
    recent_dialogue,
    render_context as render_continuation_context,
)

from observation_privacy import (
    ObservationPrivacyError,
    current_export_proposal,
    decide_current_export,
)

from native_decision_journal import (
    NativeDecisionJournalError,
    advance as advance_native_transaction,
    pending as pending_native_transactions,
    prepare as prepare_native_transaction,
    supersede as supersede_native_transaction,
)

from operational_readiness import project as operational_readiness_projection

from task_ownership import (
    CriticCheckpointError,
    TaskOwnershipError,
    blocks_material as _task_lane_blocks_material,
    claim_critic_lane_batch,
    critic_claim_identity_present,
    critic_claim_world_is_current,
    critic_event_for_claim,
    normalize_critic_batches,
    normalize_task_lanes,
    observe_prompt_lane as _observe_prompt_lane_locked,
    record_critic_local_write,
    settle_critic_claim,
    task_lane as _task_lane,
    upsert_task_lane as _upsert_task_lane_locked,
)

from .approvals import (
    _consume_approval_receipt_locked,
    _current_effect_intervention,
    _effect_intervention_card,
    _invalidate_stale_approval_receipts_locked,
    _record_approval_receipt_locked,
    _record_proposal_decision_locked,
    _validate_proposal_for_approval,
    acknowledge_continuation,
    proposal_review_for_digest,
)

from .policy import (
    GuardianSession,
    _finalize_lane,
    evaluate_event,
    run_semantic_critic_checkpoint,
)

from .events import (
    _completion_open_event_index,
)

from .recovery import (
    _approve_proposal_locked,
    _resolve_effect_intervention_locked,
    decision_request_context,
    reassess_unattended_proposal,
    reconcile_obsolete_approval_requests,
    recover_native_decisions,
)

from .resources import (
    normalize_hook_event,
    resolve_contract_path,
)
from .session_workspace import (
    bind_session_workspace,
    resolve_session_contract,
    seed_session_workspace_hint,
)

from .state import (
    CORRECTION_PATTERNS,
    Decision,
    IntentGuardianError,
    SUBJECTIVE_INTENT_PATTERN,
    _append_jsonl,
    _append_observation_jsonl,
    _append_control_event,
    _ensure_intent_confirmation_request,
    _intent_confirmation_card,
    _intent_confirmation_target,
    _pause_global_locked,
    _pause_lane_locked,
    _pause_state,
    _resume_contract_locked,
    _write_contract_unlocked,
    active_contract_path,
    contract_lock,
    default_contract,
    event_fingerprint,
    kb_home,
    load_contract,
    now_iso,
    session_contract_path,
    workspace_key,
    workspace_root,
)


_LOCK_FREE_READ_CAPABILITIES = frozenset(
    {
        f"mcp:sulde_kb:{action}"
        for action in (
            "kb_status",
            "kb_search",
            "kb_get",
            "kb_related",
            "memory_search",
            "memory_graph",
            "event_observe",
        )
    }
)


def _lock_free_read(event: dict[str, Any]) -> bool:
    """Keep host diagnostics re-entrant without bypassing effect verification.

    Ordinary tool reads never participate in external-effect reconciliation.
    Only the exact Sulde diagnostic MCP surface shares that property.  Other
    MCP reads must still reach GuardianSession because they can independently
    verify a preceding external write.
    """
    return bool(
        event.get("effect") == "read"
        and not event.get("control_plane")
        and not event.get("sensitive_input")
        and (
            event.get("kind") == "tool"
            or event.get("capability") in _LOCK_FREE_READ_CAPABILITIES
        )
    )


def _prepare_git_worktree_completion_verification(
    event: dict[str, Any], contract: dict[str, Any],
) -> None:
    """Read back one completed lifecycle call against its sealed PreTool state."""
    typed = event.get("typed_resource")
    if not (
        event.get("phase") == "completed"
        and isinstance(typed, dict)
        and typed.get("kind") == "git_worktree_lifecycle"
        and typed.get("status") == "completion"
    ):
        return
    open_events = contract.get("runtime", {}).get("open_events", [])
    if not isinstance(open_events, list):
        return
    call_id = str(event.get("call_id") or "")
    fingerprint = event_fingerprint(event)
    candidates = [
        row
        for row in open_events
        if isinstance(row, dict)
        and row.get("provider") == event.get("provider")
        and row.get("session_id") == event.get("session_id")
        and row.get("capability") == event.get("capability")
        and row.get("effect") == event.get("effect")
        and row.get("target") == event.get("target")
        and (
            (call_id and str(row.get("call_id") or "") == call_id)
            or (not call_id and row.get("fingerprint") == fingerprint)
        )
    ]
    if len(candidates) != 1:
        return
    opened = candidates[0]
    event["verification_kind"] = str(
        opened.get("verification_kind") or "unsupported"
    )
    event["verification_sha256"] = str(
        opened.get("verification_sha256") or ""
    )
    matching_index = _completion_open_event_index(
        open_events,
        event,
        fingerprint=event_fingerprint(event),
    )
    if matching_index is None or open_events[matching_index] is not opened:
        return
    opened_typed = opened.get("typed_resource")
    sealed = (
        opened_typed.get("resource")
        if isinstance(opened_typed, dict)
        else None
    )
    if not isinstance(sealed, dict):
        return
    if event.get("success") is False:
        return
    try:
        receipt = verify_git_worktree_lifecycle(sealed)
    except (ResourceVerificationError, OSError, RuntimeError, ValueError):
        return
    resource_id = str(sealed.get("resource_id") or "")
    expected_digest = resource_id.removeprefix("sha256:")
    event["independent_verification"] = {
        "capability": "tool:git_worktree_lifecycle_verify",
        "source": "local_git_worktree_lifecycle_read",
        "dispatch_event_id": str(opened.get("event_id") or ""),
        "resource_id": resource_id,
        "receipt": receipt,
        "evidence": {
            "relation": [expected_digest]
            if receipt.get("status") == "passed"
            else []
        },
    }

def process_hook(payload: dict[str, Any], *, phase: str, provider: str | None = None) -> tuple[Decision | None, Path | None]:
    if os.environ.get("SULDE_GUARDIAN_STREAM_OWNER") == "1":
        return None, None
    selected_provider = provider or str(payload.get("client") or "unknown")
    selected_session = str(
        payload.get("session_id") or payload.get("sessionId") or ""
    ).strip()
    # Production recovery must remain reachable even when the durable session
    # route points at a removed worktree or contract.  This hint deliberately
    # avoids session mapping resolution; recovery_pre_state treats a missing or
    # invalid contract as bounded input rather than entering ordinary policy.
    explicit_hint = str(
        payload.get("intent_contract")
        or os.environ.get("SULDE_INTENT_CONTRACT")
        or ""
    ).strip()
    recovery_path = (
        Path(explicit_hint).expanduser()
        if explicit_hint
        else active_contract_path(
            kb_home(),
            workspace_root(Path(str(payload.get("cwd") or os.getcwd()))),
        )
    )
    recovery_decision = route_production_recovery(
        payload, contract_path=recovery_path,
    )
    if recovery_decision is not None:
        return recovery_decision, recovery_path
    event = normalize_hook_event(payload, phase=phase, provider=provider)
    if not event["session_id"]:
        event["session_id"] = selected_session or (
            f"workspace:{workspace_key(Path(payload.get('cwd') or os.getcwd()))}"
        )
    payload["_sulde_normalized_event"] = event

    execution_passthrough = event.get("supervision_domain") == "execution_passthrough"
    if execution_passthrough:
        execution_domain = str(event.get("execution_domain") or "host")
        # Git and Figma authority belong entirely to their execution hosts.
        # Contract/session lookup is telemetry only and must never become a
        # prerequisite or a re-entrant ledger lock for either domain.
        return (
            Decision(
                dispatch="allow", would_dispatch="allow",
                lifecycle="continue", authority="none",
                verification="none", evidence_state="observed",
                severity="info", reason=f"{execution_domain} 属于宿主执行域",
                fingerprint=event_fingerprint(event),
                reason_code=f"{execution_domain}_execution_passthrough",
                decision_stage="execution_domain",
            ),
            None,
        )

    try:
        path = resolve_contract_path(payload)
    except IntentGuardianError:
        diagnostic_read = bool(
            event.get("effect") == "read"
            and not event.get("control_plane")
            and not event.get("sensitive_input")
        )
        if not diagnostic_read:
            raise
        return (
            Decision(
                dispatch="allow", would_dispatch="allow",
                lifecycle="continue", authority="none",
                verification="none", evidence_state="observed",
                severity="warning",
                reason="会话路由不可用；只读诊断保持可达",
                fingerprint=event_fingerprint(event),
                reason_code="read_diagnostic_fallback",
                decision_stage="hot_path",
            ),
            None,
        )
    if path is None:
        return None, None

    fast_read = bool(
        _lock_free_read(event)
        and not correction_event_store_path(path).is_file()
    )
    if fast_read:
        try:
            _append_observation_jsonl(
                path.with_name(f".{path.stem}.hot-path.jsonl"),
                {
                    "schema": "sulde-guardian-hot-path-observation-v1",
                    "at": now_iso(),
                    "provider": event.get("provider"),
                    "session_id": event.get("session_id"),
                    "phase": event.get("phase"),
                    "capability": event.get("capability"),
                    "effect": event.get("effect"),
                    "fingerprint": event_fingerprint(event),
                    "route": "read",
                },
            )
        except (OSError, UnicodeError, ValueError):
            # Read and Git authority belong to the host. Telemetry failure must
            # not turn the control plane into their execution authority.
            pass
        return (
            Decision(
                dispatch="allow", would_dispatch="allow",
                lifecycle="continue", authority="none",
                verification="none", evidence_state="observed",
                severity="info",
                reason="只读动作走轻量热路径",
                fingerprint=event_fingerprint(event),
                reason_code="read_hot_path",
                decision_stage="hot_path",
            ),
            path,
        )
    session = GuardianSession(
        path,
        provider=selected_provider,
        session_id=selected_session,
        hot_path=True,
    )
    control_plane = event.get("control_plane") is True
    if (
        not control_plane
        and event.get("supervision_domain") != "execution_passthrough"
    ):
        _prepare_git_worktree_completion_verification(event, session.contract)
    live_observed = payload.get("_sulde_live_hook_observed") is True
    event["supervision_status"] = "live_verified" if live_observed else "unobserved"
    event["supervision_mode"] = "enforce" if live_observed else "degraded_observe"
    if not control_plane:
        human_dispatch = claim_human_grant(path, session.contract, event)
        if human_dispatch is not None:
            event["human_grant_dispatch"] = human_dispatch
    if phase == "started" and not control_plane:
        corrections = session.contract.get("runtime", {}).get("corrections", [])
        if corrections:
            try:
                apply_queued_corrections(
                    path,
                    provider=selected_provider,
                    session_id=str(event["session_id"]),
                    boundary="pre_tool",
                    reason_code="host_reached_pre_tool",
                )
            except CorrectionInterventionError as error:
                raise IntentGuardianError(
                    f"cannot reconcile correction interventions: {error}"
                ) from error
    decision = session.observe(event)
    prepared = (
        None
        if control_plane
        else prepare_human_grant(path, session.contract, event, decision)
    )
    if prepared is not None:
        decision = replace(decision, reason=confirmation_reason(event))
    return decision, path

def finalize_host_turn(
    payload: dict[str, Any],
    *,
    provider: str | None = None,
    critic_runner: Callable[..., dict[str, Any]] | None = None,
) -> str:
    """Reconcile one host turn without injecting control text into its dialogue."""
    if os.environ.get("SULDE_GUARDIAN_STREAM_OWNER") == "1":
        return ""
    path = resolve_contract_path(payload)
    if path is None:
        return ""
    host = provider or str(payload.get("client") or "unknown")
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    _finalize_lane(path, host=host, session_id=session_id)
    critic = run_semantic_critic_checkpoint(
        path,
        host=host,
        session_id=session_id,
        critic_runner=critic_runner,
    )
    contract = load_contract(path)
    lane = session_id or f"workspace:{workspace_key(Path(contract['workspace_root']))}"
    try:
        applied = apply_queued_corrections(
            path,
            provider=host,
            session_id=lane,
            boundary="turn_stop",
            reason_code="host_turn_reached_stop",
        )
    except CorrectionInterventionError as error:
        raise IntentGuardianError(
            f"cannot reconcile correction interventions: {error}"
        ) from error
    context: list[str] = []
    if critic.get("paused"):
        context.append(
            "[sulde intent] PAUSED current lane after semantic batch checkpoint."
        )
    if applied:
        identifiers = ",".join(str(row["intervention_id"]) for row in applied)
        context.append(
            f"[sulde intent] CORRECTION_APPLIED ids={identifiers} "
            "boundary=turn_stop semantic_acceptance=unknown."
        )
    return "\n".join(context)

def record_skill_event(
    path: Path,
    *,
    name: str,
    phase: str,
    provider: str,
    session_id: str = "",
    skill_path: Path | None = None,
) -> Decision:
    """Record a host-explicit Skill boundary (used when no native event exists)."""
    if phase not in {"started", "completed"}:
        raise IntentGuardianError("skill phase must be started or completed")
    clean_name = name.strip()
    if not clean_name:
        raise IntentGuardianError("skill name must be non-empty")
    if skill_path is None:
        raise IntentGuardianError("explicit skill registration requires --skill-path to SKILL.md")
    resolved_skill = skill_path.expanduser().resolve()
    if resolved_skill.name != "SKILL.md" or not resolved_skill.is_file():
        raise IntentGuardianError(f"skill path must be a readable SKILL.md: {resolved_skill}")
    lane = session_id.strip()
    if not lane:
        contract = load_contract(path)
        lane = f"workspace:{workspace_key(Path(contract['workspace_root']))}"
    payload = {
        "client": provider,
        "session_id": lane,
        "tool_name": "Skill",
        "tool_input": {
            "skill": clean_name,
            "skill_path": str(resolved_skill),
        },
        "observation_source": "explicit_skill_registration",
        "success": True if phase == "completed" else None,
    }
    event = normalize_hook_event(payload, phase=phase, provider=provider)
    if os.environ.get("SULDE_GUARDIAN_STREAM_OWNER") == "1":
        expected = os.environ.get("SULDE_GUARDIAN_STREAM_PROVIDER", "").strip().lower()
        if expected and provider.strip().lower() != expected:
            raise IntentGuardianError(
                f"skill registration provider mismatch: expected {expected}, got {provider}"
            )
        # In managed L3 the parent process owns the authoritative mutable
        # contract.  The provider command is observed from its JSON stream and
        # adjudicated there; the child command only previews the same policy.
        return evaluate_event(load_contract(path), event)
    return GuardianSession(
        path,
        provider=provider,
        session_id=lane,
    ).observe(event)

def observe_user_prompt(payload: dict[str, Any], *, provider: str | None = None) -> str:
    if os.environ.get("SULDE_GUARDIAN_STREAM_OWNER") == "1":
        return ""
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return ""
    host = provider or str(payload.get("client") or "unknown")
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
    root = workspace_root(Path(str(payload.get("cwd") or os.getcwd())))
    home = kb_home()
    mapped_path = (
        resolve_session_contract(home, host, session_id)
        if host.strip().lower() in {"claude", "codex"} and session_id
        else None
    )
    path = mapped_path or resolve_contract_path(payload)
    if path is None:
        path = active_contract_path(home, root)
    # A readable contract path is only a discovery hint. Session ownership is
    # resolved from the durable mapping or isolated below.
    task_instance_id = str(
        payload.get("task_instance_id")
        or payload.get("taskInstanceId")
        or ""
    ).strip()
    task_continuation_token = str(
        payload.get("task_continuation_token")
        or payload.get("continuation_token")
        or ""
    ).strip()
    task_transition = str(
        payload.get("sulde_task_transition")
        or payload.get("task_transition")
        or ""
    ).strip().lower()
    explicit_new_task = task_transition == "new"
    # A workspace contract is a discovery anchor, not a shared task container.
    # The second native session in one checkout receives its own objective,
    # task epoch, approval/grant state and effect ledger.  Only an explicit
    # continuation or workspace handoff may publish a route to an old task.
    if mapped_path is None and path.is_file() and session_id:
        discovered = load_contract(path)
        lanes = [
            row
            for row in discovered.get("runtime", {}).get("task_lanes", [])
            if isinstance(row, dict)
        ]
        same_lane = any(
            str(row.get("provider") or "").lower() == host.lower()
            and str(row.get("session_id") or "") == session_id
            for row in lanes
        )
        other_lane = any(
            str(row.get("session_id") or "")
            and not (
                str(row.get("provider") or "").lower() == host.lower()
                and str(row.get("session_id") or "") == session_id
            )
            for row in lanes
        )
        if other_lane and not same_lane and not task_continuation_token:
            path = session_contract_path(home, host, session_id)
    contract_preexisting = path.is_file()
    if contract_preexisting:
        recovered = recover_native_decisions(path, provider=host, session_id=session_id)
        if recovered and session_id:
            path = resolve_session_contract(home, host, session_id) or path
        reconcile_obsolete_approval_requests(path)
        reassess_unattended_proposal(
            path,
            provider=host,
            session_id=session_id,
        )
        try:
            cancel_open_approval_requests(
                path,
                kinds={"event"},
                actor="event-fingerprint-approval-retirement",
            )
        except (ApprovalInvariantError, OSError, UnicodeError) as error:
            raise IntentGuardianError(
                f"cannot migrate retired event approval questions: {error}"
            ) from error
    parsed_control = parse_human_control(prompt)
    native_text_control = (
        parsed_control
        if text_control_requires_native(parsed_control)
        else None
    )
    # Authority belongs to a verified host-native decision surface. Keep
    # parsing legacy text so it can be suppressed from memory/skill routing,
    # but never let it enter the receipt or state-transition branches below.
    control = None if native_text_control is not None else parsed_control
    controls: list[tuple[str, str, str]] = []
    control_receipt: dict[str, Any] | None = None
    correction_intervention: dict[str, Any] | None = None
    confirmation_request_preexisting = False
    proposal_request_preexisting = False
    proposal_control_target = ""
    intervention_request_preexisting = False
    intervention_control_id = ""
    intervention_control_card: dict[str, Any] | None = None
    if (
        control
        and control.action in {"approve-proposal", "reject-proposal"}
        and path.is_file()
    ):
        snapshot = load_contract(path)
        proposal_control_target = (
            snapshot["runtime"]["pending_proposal_digest"]
            if control.target == "current"
            else control.target
        )
        if proposal_control_target:
            proposal_review_snapshot = proposal_review_for_digest(
                path,
                proposal_control_target,
            )
            prior_request_ids = {
                row["request_id"]
                for row in approval_open_requests(
                    path,
                    kind="proposal",
                    workspace=snapshot["workspace_root"],
                    route="human",
                )
            }
            restored_request = ask_approval(
                path,
                intent_id=snapshot["intent_id"],
                intent_revision=snapshot["revision"],
                kind="proposal",
                target=proposal_control_target,
                source="user_prompt_restore",
                card=proposal_review_snapshot["decision_card"],
                workspace=snapshot["workspace_root"],
                route="human",
                reuse_decided=True,
            )
            proposal_request_preexisting = (
                restored_request["request_id"] in prior_request_ids
                or restored_request["status"] == "decided"
            )
    if control and control.action == "intervention-resolve" and path.is_file():
        snapshot = load_contract(path)
        current_intervention = _current_effect_intervention(
            path,
            provider=host,
        )
        if current_intervention is not None:
            intervention, attempt = current_intervention
            intervention_control_id = str(intervention["intervention_id"])
            intervention_control_card = _effect_intervention_card(
                intervention,
                attempt,
            )
            prior_request_ids = {
                row["request_id"]
                for row in approval_open_requests(
                    path,
                    kind="effect-intervention",
                    workspace=snapshot["workspace_root"],
                    route="human",
                )
            }
            restored_request = ask_approval(
                path,
                intent_id=snapshot["intent_id"],
                intent_revision=snapshot["revision"],
                kind="effect-intervention",
                target=intervention_control_id,
                provider=host,
                session_id=session_id,
                source="user_prompt_restore",
                card=intervention_control_card,
                workspace=snapshot["workspace_root"],
                route="human",
            )
            intervention_request_preexisting = (
                restored_request["request_id"] in prior_request_ids
                or restored_request["status"] == "decided"
            )
    with contract_lock(path):
        if not path.is_file():
            provisional = default_contract(
                intent_id=f"interactive:{workspace_key(root)}",
                objective=prompt[:2_000],
                acceptance_criteria=["在发生实质修改前复述意图、保护项、拒绝项与验收方式"],
                workspace=Path(str(payload.get("cwd") or os.getcwd())),
                mode="shadow",
                rationale="首轮提示自动建立的影子契约；需经意图镜像确认后升级为 enforce",
                confirmed_by="unconfirmed",
                confirmation_required=bool(SUBJECTIVE_INTENT_PATTERN.search(prompt)),
            )
            _write_contract_unlocked(path, provisional)
        contract = load_contract(path)
        _invalidate_stale_approval_receipts_locked(contract)
        runtime = contract["runtime"]
        applied_receipt_id = str(
            contract.get("applied_approval_receipt_id") or ""
        )
        applied_revision_lane = any(
            isinstance(row, dict)
            and row.get("receipt_id") == applied_receipt_id
            and str(row.get("provider") or "").lower() == host.lower()
            and row.get("session_id") == session_id
            for row in runtime.get("approval_receipts", [])
        )
        lane_binding, task_identity_status = _observe_prompt_lane_locked(
            contract,
            provider=host,
            session_id=session_id,
            source="workspace_discovery",
            prompt_sha256=hashlib.sha256(
                prompt.encode("utf-8", errors="replace")
            ).hexdigest(),
            task_instance_id=task_instance_id,
            continuation_token=task_continuation_token,
            explicit_new_task=explicit_new_task,
            contract_preexisting=contract_preexisting,
            applied_revision_lane=applied_revision_lane,
            control_prompt=parsed_control is not None,
        )
        task_lane_state = (
            str(lane_binding.get("state") or "review_required")
            if lane_binding is not None
            else "bound"
        )
        if (
            contract["confirmation"]["required"]
            and not runtime["pending_proposal_digest"]
        ):
            prior_request_ids = {
                row["request_id"]
                for row in approval_open_requests(
                    path,
                    kind="intent-confirmation",
                    workspace=contract["workspace_root"],
                    route="human",
                )
            }
            confirmation_request = _ensure_intent_confirmation_request(path, contract)
            confirmation_request_preexisting = bool(
                confirmation_request
                and (
                    confirmation_request["request_id"] in prior_request_ids
                    or confirmation_request["status"] == "decided"
                )
            )
        observation_source = str(
            payload.get("sulde_observation_source") or "unclassified"
        )[:100]
        observation = {
            "event": "user_prompt_submit",
            "provider": host,
            "session_id": session_id,
            "source": observation_source,
            "status": (
                "native_control_required"
                if native_text_control is not None
                else "control_received"
                if control
                else "task_review_required"
                if task_lane_state == "review_required"
                else "task_lane_paused"
                if task_lane_state == "paused"
                else "observed"
            ),
            "control_action": (
                native_text_control.action
                if native_text_control is not None
                else control.action
                if control
                else ""
            ),
            "control_target": (
                native_text_control.target
                if native_text_control is not None
                else control.target
                if control
                else ""
            ),
            "task_identity": task_identity_status,
            "task_instance_id": task_instance_id[:200],
            "receipt_id": "",
            "at": now_iso(),
        }
        runtime["host_observations"].append(observation)
        runtime["host_observations"] = runtime["host_observations"][-100:]

        if control and control.action in {"confirm-intent", "reject-intent"}:
            if runtime["pending_proposal_digest"]:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                review_surface = (
                    "the current-session Codex PermissionRequest"
                    if host.strip().lower() == "codex"
                    else "a verified host-native decision surface"
                )
                raise IntentGuardianError(
                    "workspace has a current proposal; review it with " + review_surface
                )
            if not contract["confirmation"]["required"]:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError(
                    "current intent is already confirmed; no open intent question remains"
                )
            intent_target = _intent_confirmation_target(contract)
            intent_card = _intent_confirmation_card(contract)
            if not confirmation_request_preexisting:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError(
                    "intent confirmation question was restored but had not yet been shown; "
                    "review the returned card and reply once more"
                )
            control_receipt = _record_approval_receipt_locked(
                contract,
                action=control.action,
                target=intent_target,
                actor=f"user-prompt:{host}",
                provider=host,
                session_id=session_id,
                channel="user-prompt",
                observation_source=observation_source,
            )
            outcome = "approved" if control.action == "confirm-intent" else "rejected"
            try:
                decide_approval(
                    path,
                    kind="intent-confirmation",
                    target=intent_target,
                    outcome=outcome,
                    provider=host,
                    session_id=session_id,
                    actor=f"user-prompt:{host}",
                    receipt_id=control_receipt["receipt_id"],
                    card=intent_card,
                    workspace=contract["workspace_root"],
                    route="human",
                    source="user_prompt_restore",
                )
            except (ApprovalInvariantError, OSError, UnicodeError) as error:
                observation["status"] = "control_rejected"
                raise IntentGuardianError(
                    f"intent decision has no paired question: {error}"
                ) from error
            if outcome == "approved":
                contract["confirmation"]["required"] = False
                contract["confirmation"]["reason"] = ""
                contract["confirmed_by"] = "human-readable-intent-confirmation"
                if contract["mode"] == "shadow":
                    contract["mode"] = "enforce"
            else:
                contract["confirmed_by"] = "human-readable-intent-rejection"
                _pause_global_locked(
                    contract,
                    reason="用户拒绝当前意图；需要提出新的可读方案",
                    pause_class="semantic",
                    requires_revision=True,
                )
            _consume_approval_receipt_locked(
                control_receipt,
                consumer="guardian-control-executor",
            )
            controls.append(
                (control.action, intent_target, control_receipt["receipt_id"])
            )
        elif control and control.action == "intervention-resolve":
            if not intervention_control_id or intervention_control_card is None:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError(
                    "workspace has no open external-effect intervention to resolve"
                )
            if not intervention_request_preexisting:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError(
                    "effect intervention question was restored but had not yet been shown; "
                    "review the returned card and reply once more"
                )
            intervention_decision = str(getattr(control, "decision", "") or "")
            intervention_evidence = str(getattr(control, "evidence", "") or "").strip()
            evidence_sha256 = hashlib.sha256(
                intervention_evidence.encode("utf-8", errors="replace")
            ).hexdigest()
            control_receipt = _record_approval_receipt_locked(
                contract,
                action="intervention-resolve",
                target=intervention_control_id,
                actor=f"user-prompt:{host}",
                provider=host,
                session_id=session_id,
                channel="user-prompt",
                observation_source=observation_source,
                decision=intervention_decision,
                evidence_sha256=evidence_sha256,
            )
            try:
                decide_approval(
                    path,
                    kind="effect-intervention",
                    target=intervention_control_id,
                    outcome="approved",
                    provider=host,
                    session_id=session_id,
                    actor=f"user-prompt:{host}",
                    receipt_id=control_receipt["receipt_id"],
                    card=intervention_control_card,
                    workspace=contract["workspace_root"],
                    route="human",
                    source="user_prompt_restore",
                )
            except (ApprovalInvariantError, OSError, UnicodeError) as error:
                observation["status"] = "control_rejected"
                raise IntentGuardianError(
                    f"intervention decision has no paired question: {error}"
                ) from error
            _resolve_effect_intervention_locked(
                contract,
                path,
                intervention_control_id,
                decision=intervention_decision,
                evidence=intervention_evidence,
                actor=f"user-prompt:{host}",
                takeover_provider=host,
                takeover_session_id=session_id,
            )
            _consume_approval_receipt_locked(
                control_receipt,
                consumer="guardian-control-executor",
            )
            controls.append(
                (
                    "intervention-resolve",
                    intervention_control_id,
                    control_receipt["receipt_id"],
                )
            )
        elif control and control.action == "approve-event":
            raise IntentGuardianError(
                "event fingerprint approval is retired; the supervisor now decides from the "
                "readable task scope and independent effect evidence"
            )
        elif control and control.action in {
            "retired-event-approval",
            "reject-opaque-proposal-approval",
        }:
            # Old copied commands may survive in a resumed conversation.  Do
            # not turn them into authority and do not block the user's actual
            # task; record a visible migration notice instead.
            observation["status"] = "legacy_control_ignored"
        elif control and control.action == "approve-proposal":
            proposal_target = control.target
            if proposal_target == "current":
                proposal_target = runtime["pending_proposal_digest"]
                if not proposal_target:
                    observation["status"] = "control_rejected"
                    _write_contract_unlocked(path, contract)
                    raise IntentGuardianError("workspace has no current proposal to approve")
            try:
                _validate_proposal_for_approval(path, contract, proposal_target)
            except IntentGuardianError:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise
            if (
                proposal_target == proposal_control_target
                and not proposal_request_preexisting
            ):
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError(
                    "proposal decision request was restored but had not yet been shown; "
                    "review the returned card and reply once more"
                )
            control_receipt = _approve_proposal_locked(
                contract,
                proposal_target,
                actor=f"user-prompt:{host}",
                provider=host,
                session_id=session_id,
                channel="user-prompt",
                observation_source=observation_source,
            )
            try:
                decide_approval(
                    path,
                    kind="proposal",
                    target=proposal_target,
                    outcome="approved",
                    provider=host,
                    session_id=session_id,
                    actor=f"user-prompt:{host}",
                    receipt_id=control_receipt["receipt_id"],
                    workspace=contract["workspace_root"],
                    route="human",
                    source="user_prompt_restore",
                )
            except (ApprovalInvariantError, OSError, UnicodeError) as error:
                observation["status"] = "control_rejected"
                raise IntentGuardianError(
                    f"approval decision has no paired question: {error}"
                ) from error
            _record_proposal_decision_locked(
                contract,
                digest=proposal_target,
                authority="human",
                verdict="approve",
                rationale="用户通过自然语言选择批准工作区当前方案",
                evidence=["live UserPromptSubmit", "current proposal binding"],
                provider=host,
                session_id=session_id,
                receipt_id=control_receipt["receipt_id"],
            )
            controls.append(
                ("approve-proposal", proposal_target, control_receipt["receipt_id"])
            )
        elif control and control.action == "reject-proposal":
            proposal_target = runtime["pending_proposal_digest"]
            if not proposal_target:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError("workspace has no current proposal to reject")
            _validate_proposal_for_approval(path, contract, proposal_target)
            if (
                proposal_target == proposal_control_target
                and not proposal_request_preexisting
            ):
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError(
                    "proposal decision request was restored but had not yet been shown; "
                    "review the returned card and reply once more"
                )
            control_receipt = _record_approval_receipt_locked(
                contract,
                action="reject-proposal",
                target=proposal_target,
                actor=f"user-prompt:{host}",
                provider=host,
                session_id=session_id,
                channel="user-prompt",
                observation_source=observation_source,
            )
            try:
                decide_approval(
                    path,
                    kind="proposal",
                    target=proposal_target,
                    outcome="rejected",
                    provider=host,
                    session_id=session_id,
                    actor=f"user-prompt:{host}",
                    receipt_id=control_receipt["receipt_id"],
                    workspace=contract["workspace_root"],
                    route="human",
                    source="user_prompt_restore",
                )
            except (ApprovalInvariantError, OSError, UnicodeError) as error:
                observation["status"] = "control_rejected"
                raise IntentGuardianError(
                    f"approval decision has no paired question: {error}"
                ) from error
            _record_proposal_decision_locked(
                contract,
                digest=proposal_target,
                authority="human",
                verdict="reject",
                rationale="用户拒绝当前自然语言决策卡",
                evidence=["live UserPromptSubmit", "current proposal binding"],
                provider=host,
                session_id=session_id,
                receipt_id=control_receipt["receipt_id"],
            )
            runtime["approved_proposal_digests"] = [
                item for item in runtime["approved_proposal_digests"]
                if item != proposal_target
            ]
            runtime["pending_proposal_digest"] = ""
            _consume_approval_receipt_locked(
                control_receipt,
                consumer="guardian-control-executor",
            )
            controls.append(
                ("reject-proposal", proposal_target, control_receipt["receipt_id"])
            )
        elif control and control.action in {
            "approve-observation-export",
            "reject-observation-export",
        }:
            try:
                export_proposal = current_export_proposal(kb_home(), path)
            except ObservationPrivacyError as error:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError(str(error)) from error
            export_target = str(export_proposal["proposalDigest"])
            control_receipt = _record_approval_receipt_locked(
                contract,
                action=control.action,
                target=export_target,
                actor=f"user-prompt:{host}",
                provider=host,
                session_id=session_id,
                channel="user-prompt",
                observation_source=observation_source,
            )
            outcome = (
                "approved"
                if control.action == "approve-observation-export"
                else "rejected"
            )
            try:
                decide_current_export(
                    kb_home(),
                    path,
                    outcome=outcome,
                    provider=host,
                    session_id=session_id,
                    actor=f"user-prompt:{host}",
                    receipt_id=control_receipt["receipt_id"],
                )
            except ObservationPrivacyError as error:
                observation["status"] = "control_rejected"
                raise IntentGuardianError(
                    f"cannot persist observation export decision: {error}"
                ) from error
            controls.append(
                (control.action, export_target, control_receipt["receipt_id"])
            )
        explicit_pause = bool(control and control.action == "pause")
        explicit_resume = bool(control and control.action == "resume")
        correction = bool(
            parsed_control is None
            and any(
                re.search(pattern, prompt, re.IGNORECASE)
                for pattern in CORRECTION_PATTERNS
            )
        )
        lane = session_id or f"workspace:{workspace_key(Path(contract['workspace_root']))}"
        if correction:
            request_id = str(
                payload.get("prompt_id")
                or payload.get("message_id")
                or payload.get("hook_event_id")
                or ""
            )
            try:
                correction_intervention = propose_correction(
                    path,
                    intent_id=contract["intent_id"],
                    intent_revision=contract["revision"],
                    provider=host,
                    session_id=lane,
                    correction=prompt,
                    actor="human",
                    source="user_prompt",
                    request_id=request_id,
                )
            except CorrectionInterventionError as error:
                raise IntentGuardianError(
                    f"cannot persist correction intervention: {error}"
                ) from error
        if correction or explicit_pause:
            runtime["corrections"].append(
                {
                    "at": now_iso(),
                    "digest": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:24],
                    "provider": host,
                    "session_id": session_id,
                    "task_epoch": contract["task_epoch"],
                }
            )
            runtime["corrections"] = runtime["corrections"][-10:]
        lane_corrections = [
            row
            for row in runtime["corrections"]
            if isinstance(row, dict)
            and str(row.get("provider") or "") == host
            and str(row.get("session_id") or "") == session_id
            and str(row.get("task_epoch") or "") == contract["task_epoch"]
        ]
        limit_hit = len(lane_corrections) >= contract["correction_limit"]
        if explicit_pause or (limit_hit and contract["mode"] == "enforce"):
            pause_reason = (
                "用户明确暂停"
                if explicit_pause
                else "连续纠正达到阈值，需要重建共同理解"
            )
            if session_id:
                _pause_lane_locked(
                    contract,
                    provider=host,
                    session_id=session_id,
                    reason=pause_reason,
                    pause_class="user" if explicit_pause else "semantic",
                    requires_revision=limit_hit,
                    source="user_prompt",
                )
            else:
                _pause_global_locked(
                    contract,
                    reason=pause_reason,
                    pause_class="user" if explicit_pause else "semantic",
                    requires_revision=limit_hit,
                )
            if explicit_pause:
                control_receipt = _record_approval_receipt_locked(
                    contract,
                    action="pause",
                    target=pause_reason,
                    actor=f"user-prompt:{host}",
                    provider=host,
                    session_id=session_id,
                    channel="user-prompt",
                    observation_source=observation_source,
                )
                _consume_approval_receipt_locked(
                    control_receipt,
                    consumer="guardian-control-executor",
                )
                controls.append(
                    ("pause", pause_reason, control_receipt["receipt_id"])
                )
            else:
                controls.append(("pause", pause_reason, ""))
        elif explicit_resume and _pause_state(
            contract,
            provider=host,
            session_id=session_id,
        ) is not None:
            applicable_pause = _pause_state(
                contract,
                provider=host,
                session_id=session_id,
            )
            if applicable_pause and applicable_pause["requires_revision"]:
                observation["status"] = "control_rejected"
                _write_contract_unlocked(path, contract)
                raise IntentGuardianError("暂停要求先批准并应用新的意图提案")
            else:
                _resume_contract_locked(
                    contract,
                    "用户在宿主提示中确认意图并恢复",
                    actor=f"user-prompt:{host}",
                    provider=host,
                    session_id=session_id,
                )
                control_receipt = _record_approval_receipt_locked(
                    contract,
                    action="resume",
                    target="用户在宿主提示中确认意图并恢复",
                    actor=f"user-prompt:{host}",
                    provider=host,
                    session_id=session_id,
                    channel="user-prompt",
                    observation_source=observation_source,
                )
                _consume_approval_receipt_locked(
                    control_receipt,
                    consumer="guardian-control-executor",
                )
                controls.append(
                    (
                        "resume",
                        "用户在宿主提示中确认意图并恢复",
                        control_receipt["receipt_id"],
                    )
                )
        elif explicit_resume:
            observation["status"] = "control_rejected"
            _write_contract_unlocked(path, contract)
            raise IntentGuardianError("intent contract is not paused")
        if control_receipt is not None:
            observation["status"] = "control_recorded"
            observation["control_action"] = control_receipt["action"]
            observation["control_target"] = control_receipt["target"]
            observation["receipt_id"] = control_receipt["receipt_id"]
        _write_contract_unlocked(path, contract)
    if path.parent == (home / "intent" / "sessions") and path.is_file():
        bind_session_workspace(
            home,
            provider=host,
            session_id=session_id,
            contract_path=path,
        )
    if (Path(contract["workspace_root"]) / ".git").exists():
        seed_session_workspace_hint(
            kb_home(),
            provider=host,
            session_id=session_id,
            contract_path=path,
        )
    if (
        correction_intervention is not None
        and correction_intervention.get("state") == "queued"
        and _pause_state(
            contract,
            provider=host,
            session_id=session_id,
        )
        is not None
    ):
        try:
            correction_intervention = transition_correction(
                path,
                str(correction_intervention["intervention_id"]),
                state="applied",
                boundary="policy_pause",
                reason_code="policy_pause_persisted",
            )
        except CorrectionInterventionError as error:
            raise IntentGuardianError(
                f"cannot apply correction intervention: {error}"
            ) from error
    for control_action, control_detail, receipt_id in controls:
        _append_control_event(
            path,
            control_action,
            actor=f"user-prompt:{host}",
            detail=control_detail,
            receipt_id=receipt_id,
        )
        if (
            control_action in {"approve-proposal", "reject-proposal"}
            and re.fullmatch(r"[0-9a-f]{64}", control_detail)
        ):
            acknowledge_continuation(
                path,
                proposal_digest_value=control_detail,
                provider=host,
                session_id=session_id,
            )

    request_context = decision_request_context(
        kb_home(),
        root,
        provider=host,
        session_id=session_id,
    )
    request_suffix = f"\n{request_context}" if request_context else ""
    lineage = "Skill → MCP/tool → side effect → evidence must retain this intent_id."
    if host.lower() == "codex":
        launcher = launcher_home(kb_home()) / "bin" / "intent-guardian"
        registration_session = session_id or f"workspace:{workspace_key(Path(contract['workspace_root']))}"
        lineage += (
            " Codex Skill boundaries require explicit registration: run "
            f"{json.dumps(str(launcher))} skill-start <skill-name> --skill-path <absolute-SKILL.md> "
            f"--contract {json.dumps(str(path))} "
            f"--provider codex --session-id {json.dumps(registration_session)} before using it, "
            "and skill-end with the same arguments after use."
        )
    control_context = ""
    if native_text_control is not None:
        native_decision = str(
            getattr(native_text_control, "decision", "") or ""
        )
        decision_detail = f" decision={native_decision}" if native_decision else ""
        native_route = (
            "The Agent must use the current-session native Allow/Deny decision card."
            if host.strip().lower() == "codex"
            else "No verified native decision surface is available; the decision remains pending."
        )
        control_context = (
            f"[sulde intent] NATIVE_DECISION_REQUIRED action={native_text_control.action} "
            f"target={native_text_control.target}{decision_detail}. "
            f"UserPromptSubmit text is non-authorizing on every provider. {native_route}\n"
        )
    elif control_receipt is not None:
        control_context = (
            f"[sulde intent] CONTROL_RECORDED action={control_receipt['action']} "
            f"target={control_receipt['target']} receipt={control_receipt['receipt_id']} "
            f"provider={control_receipt['provider']} session={control_receipt['session_id']}.\n"
        )
    elif control and control.action in {
        "retired-event-approval",
        "reject-opaque-proposal-approval",
    }:
        control_context = (
            "[sulde intent] LEGACY_TEXT_CONTROL_IGNORED "
            "technical digests no longer grant authority; use the readable current-session "
            "decision surface when a real choice remains.\n"
        )
    correction_context = ""
    if correction_intervention is not None:
        state = str(correction_intervention["state"])
        label = {
            "queued": "CORRECTION_QUEUED",
            "applied": "CORRECTION_APPLIED",
            "unsupported": "CORRECTION_UNSUPPORTED",
        }.get(state, "CORRECTION_RECORDED")
        correction_context = (
            f"[sulde intent] {label} id={correction_intervention['intervention_id']} "
            f"state={state} semantic_acceptance=unknown.\n"
        )
    identity_context = f" task_identity={task_identity_status}."
    if lane_binding is not None and lane_binding.get("continuation_token"):
        identity_context += (
            " host_continuation_token="
            f"{lane_binding['continuation_token']}."
        )
    applicable_pause = _pause_state(
        contract,
        provider=host,
        session_id=session_id,
    )
    if applicable_pause is not None:
        return control_context + correction_context + (
            f"[sulde intent] PAUSED intent={contract['intent_id']} r{contract['revision']}。"
            f"scope={applicable_pause['scope']}。"
            f"原因：{applicable_pause['reason']}。contract={path}。"
            f"只允许读取和澄清；先更新意图契约，再由人恢复。 {lineage}"
            f"{identity_context}{request_suffix}"
        )
    if limit_hit:
        return control_context + correction_context + (
            f"[sulde intent] SHADOW correction-storm intent={contract['intent_id']}："
            "连续纠正已达阈值。建议停止修改，列出已确认/已拒绝/当前误解，只问一个高区分度问题。"
            f" {lineage}{identity_context}{request_suffix}"
        )
    if task_lane_state == "review_required":
        return control_context + correction_context + (
            f"[sulde intent] TASK_REVIEW_REQUIRED intent={contract['intent_id']} "
            f"r{contract['revision']} task_epoch={contract['task_epoch']}. "
            "The host exposed a new lane or an explicit task-instance boundary. "
            "It has read-only review access and does not automatically inherit the previous "
            "task or material authority. For the same task, the Agent may present the native "
            "task-continuation Allow/Deny card; for a new task, apply an explicit revision. "
            f"Material work remains denied until one route completes. contract={path} "
            f"{lineage}{identity_context}{request_suffix}"
        )
    return control_context + correction_context + (
        f"[sulde intent] ACTIVE intent={contract['intent_id']} r{contract['revision']} "
        f"mode={contract['mode']} confirmed_by={contract['confirmed_by']} "
        f"contract={path} objective={contract['objective'][:300]}. {lineage}"
        f"{identity_context}{request_suffix}"
    )

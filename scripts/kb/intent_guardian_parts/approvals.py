"""Intent Guardian approvals domain component."""

from __future__ import annotations

from . import memory_scope

from contextlib import contextmanager

from dataclasses import dataclass

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

from grant_broker import verify_control_route

from decision_kernel import (
    grant_transaction_context,
    observe_grant_prompt,
)

from human_control import codex_text_control_requires_native, parse_human_control

from host_capabilities import (
    HostCapabilityError,
    readiness_projection as host_readiness_projection,
)

from launcher_contract import (
    classify_trusted_script_command,
    identify_trusted_script_command,
    verify_installation as verify_launcher_installation,
)

from local_file_operations import (
    LocalFileOperationError,
    has_destructive_operation,
    operation_targets,
    parse_apply_patch_operations,
)

from approval_invariant import (
    ApprovalInvariantError,
    authoritative_store_bytes as approval_authoritative_store_bytes,
    ask_approval,
    ask_typed_approval,
    cancel_request as cancel_approval_request,
    cancel_open_requests as cancel_open_approval_requests,
    decide_approval,
    load_projection as load_approval_projection,
    open_requests as approval_open_requests,
    observe_typed_prompt,
    request_by_id as approval_request_by_id,
    request_binding_receipt,
    request_for_binding as approval_request_for_binding,
    request_phase as approval_request_phase,
    replace_typed_approval,
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
    head_proof as native_journal_head_proof,
    pending as pending_native_transactions,
    prepare as prepare_native_transaction,
    seal_binding as seal_native_binding,
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

from .resources import (
    _continuation_candidate_from_grant,
    _guardian_invocation,
    parse_native_decision_command,
    resolve_contract_path,
)
from . import selected_task
from .session_workspace import (
    bind_session_workspace,
    resolve_session_contract,
    workspace_handoff_context,
)

from .state import (
    AGENT_DECISION_SENSITIVE_PATHS,
    BOOTSTRAP_RETRY_BINDING_FIELDS,
    COMPENSATION_CONTINUATION_PROFILES,
    CONTINUATION_GRANT_SCHEMA,
    COST_INTENT_PATTERN,
    DECISION_RECEIPT_SCHEMA,
    DESTRUCTIVE_INTENT_PATTERN,
    EXTERNAL_INTENT_PATTERN,
    IntentGuardianError,
    NATIVE_DECISIONS,
    NATIVE_PERMISSION_MODES,
    NATIVE_PERMISSION_SOURCE,
    PROPOSAL_DECISION_SCHEMA,
    PROPOSAL_REVIEW_SCHEMA,
    SUBJECTIVE_INTENT_PATTERN,
    TASK_CONTINUATION_SCHEMA,
    _agent_continuation_eligibility,
    _append_control_event,
    _append_jsonl,
    _ensure_intent_confirmation_request,
    _exclusive_path_lock,
    _has_unnegated_signal,
    _intent_confirmation_card,
    _intent_confirmation_target,
    _normalize_effects,
    _pause_state,
    _resume_decision_card,
    _resume_decision_target,
    _write_contract_unlocked,
    active_contract_path,
    atomic_write,
    audit_path,
    build_continuation_grants,
    contract_lock,
    default_contract,
    implicit_continuation_grant_specs,
    kb_home,
    load_contract,
    now_iso,
    policy_digest,
    proposal_digest,
    proposal_digest_payload,
    session_contract_path,
    validate_contract,
    workspace_key,
    workspace_root,
)

from .continuation_audit import _append_continuation_event_once

from .stale_events import (
    proposal_open_event_blockers,
    reconcile_stale_local_write_events as _reconcile_stale_local_write_events,
    reconcile_stale_local_write_events_locked,
)

def _pending_verifications_are_one_sealed_compensation(
    current: dict[str, Any],
    proposal: dict[str, Any],
) -> bool:
    """Recognize the one historic install debt a sealed replacement may repair.

    General pending effect truth always blocks Agent authority.  The only
    exception is the already-supported bootstrap bridge: one Codex plugin
    installation whose outcome is unknown may be followed by one distinct,
    digest-bound installation grant for the same host/runtime boundary.  The
    authoritative intervention ledger is checked again when the proposal is
    applied; this predicate only avoids unnecessarily routing that exact
    recoverable shape to a person.
    """
    pending = current.get("runtime", {}).get("pending_verifications", [])
    if not isinstance(pending, list) or len(pending) != 1:
        return False
    row = pending[0]
    if not isinstance(row, dict):
        return False
    old_grant = row.get("continuation_grant")
    old_binding = old_grant.get("binding") if isinstance(old_grant, dict) else None
    if (
        row.get("outcome_unknown") is not True
        or row.get("provider") != "codex"
        or not str(row.get("session_id") or "")
        or not str(row.get("attempt_id") or "")
        or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("fingerprint") or "").lower())
        or not isinstance(old_grant, dict)
        or old_grant.get("schema") != CONTINUATION_GRANT_SCHEMA
        or old_grant.get("profile_id") not in COMPENSATION_CONTINUATION_PROFILES
        or old_grant.get("effect") != "external_write"
        or old_grant.get("target") != "[host-local:codex-plugin]"
        or old_grant.get("verification_kind") != "content"
        or not isinstance(old_binding, dict)
    ):
        return False
    try:
        if row.get("verification_sha256") != _continuation_candidate_from_grant(
            old_grant
        )["verification_sha256"]:
            return False
    except (KeyError, TypeError, ValueError):
        return False

    matching: list[dict[str, Any]] = []
    for grant in proposal.get("continuation", {}).get("grants", []):
        if not isinstance(grant, dict):
            continue
        new_binding = grant.get("binding")
        if (
            grant.get("schema") != CONTINUATION_GRANT_SCHEMA
            or grant.get("profile_id") != old_grant.get("profile_id")
            or grant.get("effect") != old_grant.get("effect")
            or grant.get("capability") != old_grant.get("capability")
            or grant.get("target") != old_grant.get("target")
            or grant.get("verification_kind") != old_grant.get("verification_kind")
            or int(grant.get("max_uses") or 0) != 1
            or grant.get("grant_id") == old_grant.get("grant_id")
            or not isinstance(new_binding, dict)
            or any(
                old_binding.get(field) != new_binding.get(field)
                for field in BOOTSTRAP_RETRY_BINDING_FIELDS
            )
        ):
            continue
        matching.append(grant)
    return len(matching) == 1

def agent_decision_eligibility(
    current: dict[str, Any],
    proposal: dict[str, Any],
    *,
    open_events_blocking: bool | None = None,
    contract_path: Path | None = None,
) -> tuple[bool, list[str]]:
    """Return whether Agent authority is safe for this exact proposal.

    The Agent may choose within a pre-declared, deterministic low-risk lane.
    It may not classify an external, destructive, subjective, costly or
    unresolved task into that lane merely by claiming confidence.
    """
    decision = proposal.get("decision")
    if not isinstance(decision, dict):
        return False, ["提案缺少结构化决断边界"]
    reasons: list[str] = []
    effects = set(decision.get("effects") or [])
    semantic_surface = "\n".join(
        [
            proposal["objective"],
            proposal["rationale"],
            *proposal["acceptance_criteria"],
        ]
    )
    if decision.get("intent_kind") != "deterministic":
        reasons.append("任务不是已声明的确定性任务")
    if _has_unnegated_signal(SUBJECTIVE_INTENT_PATTERN, semantic_surface):
        reasons.append("提案内容命中主观表达或高歧义边界")
    if _has_unnegated_signal(EXTERNAL_INTENT_PATTERN, semantic_surface):
        reasons.append("提案内容命中外部写入或公开传播边界")
    if _has_unnegated_signal(DESTRUCTIVE_INTENT_PATTERN, semantic_surface):
        reasons.append("提案内容命中删除或其他破坏性边界")
    if _has_unnegated_signal(COST_INTENT_PATTERN, semantic_surface):
        reasons.append("提案内容命中费用或持续自动化边界")
    continuation_eligible, continuation_reasons, continuation_effects = (
        _agent_continuation_eligibility(proposal)
    )
    material_effects = effects - {"read"}
    sealed_material_lane = bool(
        continuation_eligible
        and material_effects
        and material_effects.issubset(continuation_effects)
    )
    if decision.get("risk") != "low" and not (
        decision.get("risk") == "medium" and sealed_material_lane
    ):
        reasons.append("风险不是 low，且未完全落入已密封的宿主本地续行通道")
    if not effects or not (
        effects.issubset({"read", "local_write"}) or sealed_material_lane
    ):
        reasons.append("预计动作包含本地读取/写入之外且未被专用 verifier 覆盖的效果")
    if effects == {"read"} and proposal["permissions"]["local_write"]:
        reasons.append("只读提案仍保留本地写权限")
    if "local_write" in effects and not proposal["permissions"]["local_write"]:
        reasons.append("提案声明本地写入但契约没有本地写权限")
    if "local_write" in effects and not proposal["constraints"]["allowed_paths"]:
        reasons.append("本地写入没有明确路径范围")
    if "local_write" in effects:
        for raw_path in proposal["constraints"]["allowed_paths"]:
            normalized_path = raw_path.replace("\\", "/").strip()
            path_parts = Path(normalized_path).parts
            if (
                not normalized_path
                or Path(normalized_path).is_absolute()
                or ".." in path_parts
                or normalized_path in {".", "*", "**", "**/*"}
            ):
                reasons.append(f"Agent 写入路径不够具体或可能越界: {raw_path}")
                continue
            if any(pattern.search(normalized_path) for pattern in AGENT_DECISION_SENSITIVE_PATHS):
                reasons.append(f"Agent 不得自行批准治理、发布、自动化或敏感路径: {raw_path}")
    if decision.get("reversibility") != "reversible":
        reasons.append("操作没有声明为可回滚")
    if "local_write" in effects and not str(decision.get("rollback") or "").strip():
        reasons.append("本地写入缺少具体回滚方法")
    if decision.get("cost") != "none":
        reasons.append("存在费用或费用状态未知")
    if decision.get("unknowns"):
        reasons.append("仍有未决项")
    if proposal["critic"] != current["critic"]:
        reasons.append("语义 critic 会产生额外模型调用或数据边界")
    if proposal.get("continuation", {}).get("grants") and not continuation_eligible:
        reasons.extend(continuation_reasons or ["续行动作不满足 Agent 决断门槛"])
    if proposal["permissions"]["destructive"] != "deny":
        reasons.append("破坏性权限未固定为 deny")
    if proposal["permissions"]["external_write"] == "allow":
        reasons.append("外部写入被直接放行")
    if proposal["mcp"]["unknown_effect"] == "allow":
        reasons.append("未知 MCP 效果被直接放行")
    if current["status"] == "paused" or current["runtime"]["pause_requires_revision"]:
        reasons.append("当前契约处于必须由人重建共同理解的暂停状态")
    if (
        bool(current["runtime"]["open_events"])
        if open_events_blocking is None
        else open_events_blocking
    ):
        reasons.append("当前仍有未完成的实质工具事件")
    attempts = None
    if current["runtime"]["pending_verifications"] and memory_scope.independent(proposal) and contract_path is not None:
        try:
            attempts = load_intervention_projection(contract_path).get("attempts", {})
        except (InterventionError, OSError, UnicodeError):
            attempts = None
    if memory_scope.blocking_pending(current, proposal, attempts=attempts) and not (
        _pending_verifications_are_one_sealed_compensation(current, proposal)
    ):
        reasons.append("当前仍有未结算的外部效果证据")
    if current["confirmed_by"] == "workspace-rebind-pending-intent-review":
        reasons.append("工作区迁移后的新边界必须由人重新确认")
    if memory_scope.independent(proposal) and not memory_scope.independent(current):
        reasons.append("首次声明任务不依赖记忆结果，必须由人确认依赖边界")
    permission_rank = {"deny": 0, "confirm": 1, "allow": 2}
    if proposal["permissions"]["local_write"] and not current["permissions"]["local_write"]:
        reasons.append("提案扩大了 permissions.local_write 权限")
    for permission in ("external_write", "destructive"):
        if permission_rank[proposal["permissions"][permission]] > permission_rank[
            current["permissions"][permission]
        ]:
            reasons.append(f"提案扩大了 permissions.{permission} 权限")
    for field in ("skills", "mcp"):
        if proposal[field] != current[field]:
            reasons.append(f"提案扩大或改变了 {field} 权限")
    return not reasons, reasons

def create_revision_proposal(
    path: Path,
    *,
    objective: str,
    acceptance_criteria: Iterable[str],
    mode: str,
    rationale: str = "",
    preserve: Iterable[str] = (),
    reject: Iterable[str] = (),
    allowed_paths: Iterable[str] = (),
    semantic_critic: bool = False,
    memory_dependency: str = "dependent",
    decision_route: str = "auto",
    intent_kind: str = "unknown",
    risk: str = "unknown",
    effects: Iterable[str] = ("unknown",),
    reversibility: str = "unknown",
    cost: str = "unknown",
    unattended_policy: str = UNATTENDED_AGENT_IF_ELIGIBLE,
    rollback: str = "",
    unknowns: Iterable[str] = (),
    continuation_grants: Iterable[str] = (),
    provider: str = "unknown",
    session_id: str = "",
) -> tuple[Path, str]:
    """Create an immutable candidate; this does not mutate active authority."""
    allowed_paths = list(allowed_paths)
    effects = list(effects)
    continuation_grants = list(continuation_grants)
    if memory_dependency not in {"independent", "dependent"}:
        raise IntentGuardianError("memory_dependency must be independent or dependent")
    reconcile_stale_local_write_events(
        path,
        provider=provider,
        session_id=session_id,
        boundary="proposal_request",
    )
    with contract_lock(path):
        current = load_contract(path)
        open_event_blockers = proposal_open_event_blockers(
            path,
            current,
            provider=provider,
            session_id=session_id,
            allowed_paths=allowed_paths,
            memory_independent=(memory_dependency == "independent"
                                and bool(effects) and set(effects).issubset({"read", "local_write"})
                                and not continuation_grants),
        )
        if open_event_blockers:
            first = open_event_blockers[0]
            raise IntentGuardianError(
                "cannot propose while a lane/effect/resource event is still open: "
                f"category={first['category']} reason={first['reason']} "
                f"event_id={first['event_id']}"
            )
        proposal = default_contract(
            intent_id=current["intent_id"],
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            workspace=Path(current["workspace_root"]),
            mode=mode,
            rationale=rationale,
            preserve=preserve,
            reject=reject,
            allowed_paths=allowed_paths,
            confirmed_by="unconfirmed-proposal",
            semantic_critic=semantic_critic or current["critic"]["enabled"],
        )
        # Fields not exposed by the mirror CLI retain the active contract's
        # least-authority policy. A wording revision must never silently reset
        # Skill/MCP allowlists, frozen paths, or destructive permissions.
        proposal["permissions"] = json.loads(json.dumps(current["permissions"]))
        proposal["skills"] = json.loads(json.dumps(current["skills"]))
        proposal["mcp"] = json.loads(json.dumps(current["mcp"]))
        proposal["constraints"]["frozen_paths"] = list(
            current["constraints"]["frozen_paths"]
        )
        proposal["correction_limit"] = current["correction_limit"]
        proposal["confirmation"] = json.loads(json.dumps(current["confirmation"]))
        proposal["revision"] = current["revision"] + 1
        proposal["constraints"]["memory_dependency"] = memory_dependency
        proposal["created_at"] = current["created_at"]
        proposal["proposal_for"] = {
            "contract_path": str(path.expanduser().resolve()),
            "base_revision": current["revision"],
            "base_policy_digest": policy_digest(current),
            "base_material_sequence": int(
                current["runtime"].get("material_sequence", 0)
            ),
        }
        normalized_effects = _normalize_effects(effects)
        if "destructive" in normalized_effects and "local_write" not in normalized_effects:
            raise IntentGuardianError(
                "decision.effects destructive requires its local_write transport; "
                "generic destructive authority is never proposed"
            )
        try:
            selected_unattended_policy = normalize_unattended_policy(
                unattended_policy,
                default=UNATTENDED_AGENT_IF_ELIGIBLE,
            )
        except ApprovalTimeoutPolicyError as error:
            raise IntentGuardianError(str(error)) from error
        proposal["decision"] = {
            "requested_route": decision_route,
            "selected_route": "human",
            "intent_kind": intent_kind,
            "risk": risk,
            "effects": normalized_effects,
            "reversibility": reversibility,
            "cost": cost,
            "unattended_policy": selected_unattended_policy,
            "rollback": rollback,
            "unknowns": list(unknowns),
            "agent_eligible": False,
            "agent_ineligible_reasons": [],
        }
        requested_grants = list(continuation_grants)
        requested_grants.extend(
            implicit_continuation_grant_specs(
                proposal["acceptance_criteria"],
                effects=normalized_effects,
                allowed_paths=proposal["constraints"]["allowed_paths"],
            )
        )
        proposal["continuation"] = {
            "grants": build_continuation_grants(
                requested_grants,
                acceptance_criteria=proposal["acceptance_criteria"],
                workspace=Path(current["workspace_root"]),
            )
        }
        declared_effects = set(normalized_effects)
        if "local_write" in declared_effects:
            proposal["permissions"]["local_write"] = True
        elif "unknown" not in declared_effects:
            # An explicit read-only or external-only proposal can safely drop
            # latent local-write authority.  The legacy CLI default is
            # ``unknown``; in that compatibility lane retain only the active
            # contract's existing permission so a human-approved wording
            # revision does not become a surprise denial (and never expands
            # authority).
            proposal["permissions"]["local_write"] = False
        if "external_write" in declared_effects:
            proposal["permissions"]["external_write"] = "confirm"
        if "destructive" in declared_effects:
            proposal["permissions"]["destructive"] = "confirm"
        elif "unknown" not in declared_effects:
            proposal["permissions"]["destructive"] = "deny"
        proposal = validate_contract(proposal)
        if memory_scope.independent(proposal):
            proposal["proposal_for"]["material_sequence_domain"] = "non_memory_v1"
            proposal["proposal_for"]["base_material_sequence"] = memory_scope.sequence(current["runtime"], scoped=True)
        eligible, ineligible_reasons = agent_decision_eligibility(
            current,
            proposal,
            open_events_blocking=False,
            contract_path=path,
        )
        proposal["decision"]["agent_eligible"] = eligible
        proposal["decision"]["agent_ineligible_reasons"] = ineligible_reasons
        proposal["decision"]["selected_route"] = (
            "agent"
            if eligible
            and (
                decision_route in {"auto", "agent"}
                or selected_unattended_policy == UNATTENDED_AGENT_IF_ELIGIBLE
            )
            else "human"
        )
        digest = proposal_digest(proposal)
        proposal["proposal_digest"] = digest
        stem = path.name[:-5] if path.name.endswith(".json") else path.name
        target = path.with_name(f"{stem}.proposal.{digest[:16]}.json")
        if target.exists():
            existing = load_contract(target)
            if proposal_digest(existing) != digest:
                raise IntentGuardianError(f"proposal path collision: {target}")
        else:
            _write_contract_unlocked(target, proposal)
        superseded_at = now_iso()
        for receipt in current["runtime"]["approval_receipts"]:
            if (
                receipt["action"] == "approve-proposal"
                and receipt["target"] != digest
                and not receipt["consumed_at"]
            ):
                receipt["consumed_at"] = superseded_at
                receipt["consumed_by"] = "invalidated-by-proposal-supersession"
        current["runtime"]["approved_proposal_digests"] = [
            item
            for item in current["runtime"]["approved_proposal_digests"]
            if item == digest
        ]
        current["runtime"]["pending_proposal_digest"] = digest
        _write_contract_unlocked(path, current)
    # Codex presents the proposal through PermissionRequest. Persisting a
    # generic proposal_review question here would create a second, untyped
    # lifecycle before the real native prompt exists. Other hosts retain the
    # legacy textual approval path.
    if (
        proposal["decision"]["selected_route"] == "human"
        and provider.strip().lower() != "codex"
    ):
        try:
            review = proposal_review(path, target)
            ask_approval(
                path,
                intent_id=current["intent_id"],
                intent_revision=current["revision"],
                kind="proposal",
                target=digest,
                source="proposal_review",
                card=review["decision_card"],
                workspace=current["workspace_root"],
                route="human",
            )
        except (ApprovalInvariantError, OSError, UnicodeError) as error:
            raise IntentGuardianError(
                f"cannot persist proposal approval question: {error}"
            ) from error
    _append_control_event(path, "propose-revision", actor="agent", detail=digest)
    return target, digest

def reconcile_stale_local_write_events(
    path: Path,
    *,
    provider: str,
    session_id: str,
    minimum_age_seconds: float = 5.0,
    boundary: str = "proposal_request",
) -> list[dict[str, Any]]:
    return _reconcile_stale_local_write_events(
        path,
        provider=provider,
        session_id=session_id,
        minimum_age_seconds=minimum_age_seconds,
        boundary=boundary,
    )

def ensure_workspace_contract(
    home: Path,
    workspace: Path,
    *,
    intent_id: str | None = None,
    provider: str = "unknown",
    session_id: str = "",
) -> tuple[Path, bool]:
    """Create a non-authorizing workspace contract when none exists.

    Bootstrap is mechanical setup, not human confirmation.  The resulting
    contract blocks every material write until a proposal is reviewed through
    a live host prompt and applied.
    """
    root = workspace_root(workspace)
    selected_provider = provider.strip().lower()
    selected_session = session_id.strip()
    mapped = (
        resolve_session_contract(home, selected_provider, selected_session)
        if selected_provider in {"claude", "codex"} and selected_session
        else None
    )
    path = mapped or active_contract_path(home, root)
    if mapped is None and path.is_file() and selected_session:
        current = load_contract(path)
        lanes = [
            row
            for row in current.get("runtime", {}).get("task_lanes", [])
            if isinstance(row, dict)
        ]
        owned_by_other_session = any(
            str(row.get("session_id") or "")
            and not (
                str(row.get("provider") or "").lower() == selected_provider
                and str(row.get("session_id") or "") == selected_session
            )
            for row in lanes
        )
        owned_by_current_session = any(
            str(row.get("provider") or "").lower() == selected_provider
            and str(row.get("session_id") or "") == selected_session
            for row in lanes
        )
        if owned_by_other_session and not owned_by_current_session:
            path = session_contract_path(home, selected_provider, selected_session)
    created = False
    with contract_lock(path):
        if path.is_file():
            # A live UserPromptSubmit may already have established the canonical
            # workspace contract.  Keep that lineage instead of replacing its
            # intent_id with an Agent-suggested label.
            load_contract(path)
            return path, False
        contract = default_contract(
            intent_id=intent_id or f"interactive:{workspace_key(root)}",
            objective="等待人工审阅当前任务的冻结意图提案",
            acceptance_criteria=["提案获真实宿主提示回执前只允许读取和澄清"],
            workspace=root,
            mode="shadow",
            rationale="系统自动建立的最小权限占位契约；不代表人工确认",
            confirmed_by="unconfirmed",
            confirmation_required=True,
        )
        _write_contract_unlocked(path, contract)
        created = True
    if created:
        _append_control_event(
            path,
            "bootstrap-workspace",
            actor="agent-safe-bootstrap",
            detail="non-authorizing shadow contract",
        )
        _ensure_intent_confirmation_request(path, contract)
    if path.parent == (home / "intent" / "sessions"):
        bind_session_workspace(
            home,
            provider=selected_provider,
            session_id=selected_session,
            contract_path=path,
        )
    return path, created

def proposal_review(path: Path, proposal_path: Path) -> dict[str, Any]:
    """Render the exact proposal into a deterministic, human-readable view."""
    with contract_lock(path):
        current = load_contract(path)
        proposal = load_contract(proposal_path)
        digest = proposal_digest(proposal)
        if proposal.get("proposal_digest") != digest:
            raise IntentGuardianError("proposal digest field does not match proposal content")
        validated_path = _validate_proposal_for_approval(path, current, digest)
        if validated_path.resolve() != proposal_path.expanduser().resolve():
            raise IntentGuardianError("proposal path does not match its canonical digest path")

    fields = {
        "outcome": proposal["objective"],
        "reason": proposal["rationale"],
        "preserve": proposal["constraints"]["preserve"],
        "reject": proposal["constraints"]["reject"],
        "observable_acceptance": proposal["acceptance_criteria"],
        "freedom_and_scope": {
            "workspace_root": proposal["workspace_root"],
            "allowed_paths": proposal["constraints"]["allowed_paths"],
            "frozen_paths": proposal["constraints"]["frozen_paths"],
            "permissions": proposal["permissions"],
            "skills": proposal["skills"],
            "mcp": proposal["mcp"],
        },
        "unresolved_decision": (
            proposal["confirmation"]["reason"]
            if proposal["confirmation"]["required"]
            else ""
        ),
        "continuation_grants": proposal["continuation"]["grants"],
    }
    changed_authority = [
        name
        for name, before, after in (
            ("mode", current["mode"], proposal["mode"]),
            ("constraints", current["constraints"], proposal["constraints"]),
            ("permissions", current["permissions"], proposal["permissions"]),
            ("skills", current["skills"], proposal["skills"]),
            ("mcp", current["mcp"], proposal["mcp"]),
            ("critic", current["critic"], proposal["critic"]),
        )
        if before != after
    ]
    decision = proposal.get("decision") or {
        "requested_route": "human",
        "selected_route": "human",
        "intent_kind": "unknown",
        "risk": "unknown",
        "effects": ["unknown"],
        "reversibility": "unknown",
        "cost": "unknown",
        "rollback": "",
        "unknowns": ["旧提案没有结构化决断信息"],
        "agent_eligible": False,
        "agent_ineligible_reasons": ["旧提案只能转人工审阅"],
    }
    effect_labels = {
        "read": "读取本地内容",
        "local_write": "修改明确范围内的本地文件",
        "external_write": "写入外部系统或公开发布",
        "destructive": "删除、覆盖或其他难恢复操作",
        "unknown": "效果尚不明确",
    }
    intent_kind_labels = {
        "deterministic": "确定性任务（可按明确规则验收）",
        "subjective": "主观任务（需要人的偏好判断）",
        "unknown": "任务类型尚不明确",
    }
    risk_labels = {
        "low": "低",
        "medium": "中",
        "high": "高",
        "unknown": "尚未判断",
    }
    reversibility_labels = {
        "reversible": "可以直接回滚",
        "compensatable": "不能完全撤销，只能补偿",
        "irreversible": "不可恢复",
        "unknown": "尚不明确",
    }
    cost_labels = {
        "none": "不会产生额外费用",
        "bounded": "有明确上限的费用",
        "unbounded": "费用可能持续或无明确上限",
        "unknown": "费用状态尚不明确",
    }
    permission_labels = {
        "allow": "直接允许",
        "confirm": "当前可读方案内由监督器执行；扩大范围时在对话中确认",
        "deny": "禁止",
    }
    continuation_cards = [
        {
            "动作": grant["label"],
            "绑定验收": proposal["acceptance_criteria"][grant["acceptance_index"]],
            "目标": grant["target"],
            "最多执行": grant["max_uses"],
            "独立验证": grant["verification_kind"],
            "回滚": grant["rollback"],
        }
        for grant in proposal["continuation"]["grants"]
    ]
    external_permission_label = permission_labels[
        proposal["permissions"]["external_write"]
    ]
    if (
        proposal["permissions"]["external_write"] == "confirm"
        and any(grant["effect"] == "external_write" for grant in proposal["continuation"]["grants"])
    ):
        external_permission_label = (
            "卡片内声明且可独立验证的动作由监督器执行；其他外部写入需先在对话中扩大范围"
        )
    decision_card = {
        "要完成的结果": proposal["objective"],
        "为什么要做": proposal["rationale"],
        "允许改变": {
            "预计动作": [effect_labels[item] for item in decision["effects"]],
            "可修改路径": proposal["constraints"]["allowed_paths"],
        },
        "必须保持": proposal["constraints"]["preserve"],
        "明确禁止": proposal["constraints"]["reject"],
        "如何验收": proposal["acceptance_criteria"],
        "风险与恢复": {
            "任务类型": intent_kind_labels[decision["intent_kind"]],
            "风险": risk_labels[decision["risk"]],
            "可恢复性": reversibility_labels[decision["reversibility"]],
            "回滚方法": decision["rollback"],
            "费用": cost_labels[decision["cost"]],
        },
        "执行权限边界": {
            "本地写入": "允许" if proposal["permissions"]["local_write"] else "禁止",
            "外部写入": external_permission_label,
            "破坏性操作": permission_labels[proposal["permissions"]["destructive"]],
            "Skill 允许": proposal["skills"]["allow"],
            "Skill 禁止": proposal["skills"]["deny"],
            "MCP 允许服务": proposal["mcp"]["allow_servers"],
            "MCP 允许工具": proposal["mcp"]["allow_tools"],
            "未知 MCP 效果": permission_labels[proposal["mcp"]["unknown_effect"]],
            "额外语义检查": "开启" if proposal["critic"]["enabled"] else "关闭",
        },
        "自动续行动作": continuation_cards,
        "仍未确定": decision["unknowns"],
        "无人值守策略": (
            "完整 Agent 安全门已在弹出人工确认前通过，直接使用独立 Agent 决策"
            if decision["selected_route"] == "agent"
            else "未通过前置 Agent 安全门；人工框展示后五分钟仅标记待关注，不推定同意"
            if decision.get("unattended_policy") == UNATTENDED_AGENT_IF_ELIGIBLE
            else "始终等待人工，不因超时扩大权限"
        ),
        "系统分流": (
            "Agent 可按受限规则决断"
            if decision["selected_route"] == "agent"
            else "需要人工决断"
        ),
        "不能由 Agent 决断的原因": decision["agent_ineligible_reasons"],
    }
    return {
        "schema": PROPOSAL_REVIEW_SCHEMA,
        "proposal_digest": digest,
        "contract_path": str(path.expanduser().resolve()),
        "proposal_path": str(proposal_path.expanduser().resolve()),
        "intent_id": proposal["intent_id"],
        "base_revision": current["revision"],
        "proposed_revision": proposal["revision"],
        "mode": proposal["mode"],
        "review": fields,
        "changed_authority_fields": changed_authority,
        "semantic_critic": proposal["critic"],
        "decision_route": decision["selected_route"],
        "decision_card": decision_card,
        "technical_binding": {
            "proposal_digest": digest,
            "purpose": "仅用于后台完整性校验，不是供人理解的审批内容",
        },
        "digest_bound_contract": proposal_digest_payload(proposal),
        "approval_requirement": (
            "Human mode requires a verified current-host native decision surface. Plain chat "
            "text, copied phrases, digests and manually relayed CLI commands are never authority. "
            "Agent mode requires the deterministic bounded-action gate. The digest is only an "
            "internal integrity binding."
        ),
    }

def proposal_review_for_provider(
    review: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    """Render the decision surface without changing the immutable proposal.

    Codex human decisions are made through the current conversation's native
    PermissionRequest surface. Keeping legacy prompt phrases in any provider
    output invites users and Agents to treat ordinary text as authority. A host
    without a verified native boundary stays pending instead of delegating a
    phrase or CLI command to the user.
    """
    rendered = json.loads(json.dumps(review, ensure_ascii=False))
    selected_provider = provider.strip().lower() or "unknown"
    rendered.pop("approval_prompt", None)
    rendered.pop("human_choices", None)
    if rendered.get("decision_route") == "agent":
        rendered["decision_surface"] = {
            "host": selected_provider,
            "type": "AgentPolicy",
            "text_authority": False,
            "human_prompt_presented": False,
            "next_action": (
                "Agent records one deterministic policy decision with "
                "agent-decide-proposal; no PermissionRequest is presented."
            ),
        }
        rendered["approval_requirement"] = (
            "The immutable proposal passed the bounded Agent gate before any human "
            "prompt. Agent authority remains distinct from human approval."
        )
        return rendered
    if selected_provider != "codex":
        rendered["decision_surface"] = {
            "host": selected_provider,
            "type": "NativeDecisionUnavailable",
            "status": "pending",
            "text_authority": False,
            "human_prompt_presented": False,
            "next_action": (
                "Keep the proposal pending. The Agent must establish a verified "
                "host-native decision surface; do not ask the user to type a phrase, "
                "copy a digest, or run a CLI command."
            ),
        }
        rendered["approval_requirement"] = (
            "This host has no verified native decision surface. The proposal remains "
            "pending and ordinary conversation text cannot authorize it."
        )
        return rendered
    rendered["decision_surface"] = {
        "host": "codex",
        "type": "PermissionRequest",
        "choices": ["Allow", "Deny"],
        "text_authority": False,
        "next_action": "Agent presents one current-session Allow/Deny decision.",
    }
    rendered["approval_requirement"] = (
        "Codex human mode binds authority to this readable card and the current-session "
        "Allow/Deny result."
    )
    return rendered

def proposal_review_for_digest(path: Path, digest: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise IntentGuardianError("proposal digest must be 64 lowercase hex chars")
    return proposal_review(path, _proposal_path_for_digest(path, digest))

def _current_effect_intervention(
    path: Path,
    *,
    provider: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Select the oldest unresolved effect decision for this workspace.

    A semantic revision cannot turn unresolved external truth into history.
    The card may be handled from a new session, but retry/reprobe authority is
    then explicitly rebound to that session by the resolution event.
    """
    try:
        projection = load_intervention_projection(path)
    except (InterventionError, OSError, UnicodeError) as error:
        raise IntentGuardianError(f"cannot replay interventions: {error}") from error
    selected_provider = provider.strip().lower()
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for intervention in projection["interventions"].values():
        if intervention.get("status") not in {"open", "acknowledged"}:
            continue
        attempt = projection["attempts"].get(intervention.get("attempt_id"))
        if not isinstance(attempt, dict):
            continue
        attempt_provider = str(attempt.get("provider") or "unknown").lower()
        if selected_provider not in {"", "unknown"} and attempt_provider != selected_provider:
            continue
        candidates.append((dict(intervention), dict(attempt)))
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            str(item[0].get("opened_at") or ""),
            str(item[0].get("intervention_id") or ""),
        ),
    )[0]

def _effect_intervention_card(
    intervention: dict[str, Any],
    attempt: dict[str, Any],
) -> dict[str, Any]:
    return {
        "要决定的结果": "处理一笔无法由系统证明最终结果的外部操作",
        "为什么需要决定": str(intervention.get("reason") or "外部结果缺少独立验证"),
        "当前已知": {
            "能力": str(attempt.get("capability") or "unknown"),
            "目标": str(attempt.get("target") or "unknown"),
            "宿主": str(attempt.get("provider") or "unknown"),
            "状态": str(attempt.get("state") or "unknown"),
            "派发时间": str(attempt.get("created_at") or "unknown"),
        },
        "仍然未知": "操作是否真正成功；成功回调本身不能替代外部读回证据",
        "可处理的事项": [
            "提供能够观察到的成功证据",
            "提供能够观察到的失败证据",
            "只重新检查当前外部效果",
            "对同一外部操作重试一次",
            "终止当前外部操作且不重试",
        ],
        "执行边界": (
            "事实证据可用自然语言说明，不要求固定格式。需要权限的重查、重试或终止由 "
            "Agent 展示原生 Allow/Deny，并在获准后原子执行；重试只授权同一事件一次。"
        ),
        "恢复方式": "错误裁决不改写旧 attempt；只能追加新的可审计证据或补偿动作。",
    }

def _observation_export_card(proposal: dict[str, Any]) -> dict[str, Any]:
    query = proposal.get("query") if isinstance(proposal.get("query"), dict) else {}
    return {
        "要决定的结果": "导出一份已经脱敏的本地观察快照",
        "数据范围": {
            "工作区数量": len(query.get("workspaces", []))
            if isinstance(query.get("workspaces"), list)
            else 0,
            "事件域": query.get("domains", []),
            "宿主": query.get("providers", []),
            "截止序号": proposal.get("asOfSeq"),
            "返回事件数": proposal.get("returnedEvents"),
        },
        "目标文件": str(proposal.get("destination") or "unknown"),
        "包含": "统一事件观察器已经脱敏的派生事件与汇总",
        "明确排除": "权威原始日志、原始提示词、原始工具结果、隐藏思维和网络发送权限",
        "权限边界": "只允许一次本地导出；不允许覆盖已有文件，也不授权上传或公开传播",
    }

def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

def _task_lane_sha256(provider: str, session_id: str) -> str:
    return hashlib.sha256(
        f"{provider.strip().lower()}\0{session_id.strip()}".encode(
            "utf-8", errors="replace"
        )
    ).hexdigest()

def _task_lane_allows_continuation_source(
    contract: dict[str, Any], row: dict[str, Any]
) -> bool:
    """Accept explicit eligibility or one exact pre-feature revision lane.

    Older runtimes created the newly approved revision lane before the
    continuation feature existed and persisted ``continuation_eligible=false``
    by default.  Only an exact current-epoch ``approved_revision`` lane whose
    proposal digest matches the contract's applied proposal is safe to migrate;
    arbitrary bound lanes and explicit review lanes remain ineligible.
    """
    if row.get("continuation_eligible") is True:
        return True
    applied_digest = str(contract.get("applied_proposal_digest") or "")
    return bool(
        row.get("state") == "bound"
        and row.get("source") == "approved_revision"
        and row.get("task_epoch") == contract.get("task_epoch")
        and applied_digest
        and row.get("proposal_digest") == applied_digest
    )

def _task_continuation_context_locked(
    contract: dict[str, Any], *, provider: str, session_id: str,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    if contract.get("task_continuation_selection") is not None:
        return selected_task.context(contract_path, contract, provider=provider,
            session_id=session_id, legacy_context=_legacy_task_continuation_context_locked)
    return _legacy_task_continuation_context_locked(contract, provider=provider,
        session_id=session_id, contract_path=contract_path)

def _legacy_task_continuation_context_locked(
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    contract_path: Path | None = None,
) -> dict[str, Any]:
    """Build the exact, authority-free subject for a new-session continuation."""
    selected_provider = provider.strip().lower()
    selected_session = session_id.strip()
    if selected_provider != "codex" or not selected_session:
        raise IntentGuardianError(
            "task continuation requires the current Codex session"
        )
    if contract.get("status") != "active":
        raise IntentGuardianError("current task is not active")
    if contract.get("confirmation", {}).get("required"):
        raise IntentGuardianError(
            "current intent is not confirmed; confirm it before continuing the task"
        )
    if _pause_state(
        contract,
        provider=selected_provider,
        session_id=selected_session,
    ) is not None:
        raise IntentGuardianError(
            "current task is paused; resume or revise it before session continuation"
        )
    target_lane = _task_lane(
        contract,
        provider=selected_provider,
        session_id=selected_session,
    )
    if not isinstance(target_lane, dict) or target_lane.get("state") != "review_required":
        raise IntentGuardianError(
            "current Codex session is not awaiting task continuation review"
        )
    task_epoch = str(contract.get("task_epoch") or "")
    source_lanes = [
        row
        for row in contract.get("runtime", {}).get("task_lanes", [])
        if isinstance(row, dict)
        and row.get("provider") == selected_provider
        and row.get("session_id") != selected_session
        and row.get("task_epoch") == task_epoch
        and row.get("state") == "bound"
        and _task_lane_allows_continuation_source(contract, row)
    ]
    if not source_lanes:
        raise IntentGuardianError(
            "current task has no bound Codex source lane eligible for continuation"
        )
    source_lane = sorted(
        source_lanes,
        key=lambda row: (
            str(row.get("updated_at") or ""),
            str(row.get("session_id") or ""),
        ),
    )[-1]
    policy_sha256 = policy_digest(contract)
    proposal = str(
        contract.get("applied_proposal_digest")
        or target_lane.get("proposal_digest")
        or source_lane.get("proposal_digest")
        or ""
    )
    authority_state = {
        "approved_event_fingerprints": contract.get(
            "approved_event_fingerprints", []
        ),
        "authorized_events": contract["runtime"].get("authorized_events", []),
        "continuation_uses": contract["runtime"].get("continuation_uses", []),
        "open_events": contract["runtime"].get("open_events", []),
        "pending_verifications": contract["runtime"].get(
            "pending_verifications", []
        ),
    }
    scoped_memory = memory_scope.independent(contract)
    if scoped_memory:
        # A continuation transfers no authority. Ignore only source-typed
        # optional memory activity; grants and every unknown row stay bound.
        attempts = {}
        if contract_path is not None and any(authority_state[key] for key in ("open_events", "pending_verifications", "continuation_uses")):
            try:
                attempts = load_intervention_projection(contract_path)["attempts"]
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError("memory scope authoritative attempt projection unavailable") from error
        for key in ("open_events", "pending_verifications", "continuation_uses"):
            authority_state[key] = [row for row in authority_state[key]
                                   if not memory_scope.proven_memory_row(row, attempts)]
    subject = {
        "schema": "sulde-task-continuation-subject-v1",
        "intent_id": str(contract["intent_id"]),
        "intent_revision": int(contract["revision"]),
        "task_epoch": task_epoch,
        "policy_sha256": policy_sha256,
        "proposal_digest": proposal,
        "material_sequence": memory_scope.sequence(contract["runtime"], scoped=scoped_memory),
        "authority_state_sha256": _canonical_sha256(authority_state),
        "provider": selected_provider,
        "session_id": selected_session,
        "source_lane_sha256": _task_lane_sha256(
            str(source_lane["provider"]), str(source_lane["session_id"])
        ),
        "target_lane_sha256": _task_lane_sha256(
            selected_provider, selected_session
        ),
        "target_lane_state": "review_required",
        "target_prompt_sha256": str(target_lane.get("prompt_sha256") or ""),
        "pending_task_instance_id": str(
            target_lane.get("pending_task_instance_id") or ""
        ),
    }
    target = _canonical_sha256(subject)
    card = {
        "要决定的结果": "让当前 Codex 新会话续接当前任务",
        "当前任务": {
            "目标": str(contract.get("objective") or ""),
            "验收标准": list(contract.get("acceptance_criteria") or []),
            "保留": list(contract.get("constraints", {}).get("preserve") or []),
            "拒绝": list(contract.get("constraints", {}).get("reject") or []),
            "可修改路径": list(
                contract.get("constraints", {}).get("allowed_paths") or []
            ),
        },
        "绑定范围": {
            "宿主": selected_provider,
            "目标会话": selected_session,
            "intent_revision": int(contract["revision"]),
            "task_epoch": task_epoch,
            "续接目标摘要": target,
        },
        "会继承": "任务目标、约束、验收标准和当前工作区政策",
        "明确不继承": (
            "旧会话 grant、批准回执、open event、pending verification、"
            "effect debt、continuation token 或其他执行权限"
        ),
        "外部效果边界": (
            "工作区既有未决效果仍按原账本独立阻断；本选择不授权重试或写入"
        ),
        "执行边界": (
            "Allow 只把当前 provider/session 绑定到这个 revision/task_epoch；"
            "Deny 保持只读 review_required"
        ),
    }
    return {
        "subject": subject,
        "target": target,
        "card": card,
        "source_lane": source_lane,
        "target_lane": target_lane,
    }

def _apply_task_continuation_locked(
    path: Path,
    contract: dict[str, Any],
    binding: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    if contract.get("task_continuation_selection") is not None:
        selected_task.apply(path, contract, binding, receipt,
            legacy_context=_legacy_task_continuation_context_locked)
        return {}
    context = _task_continuation_context_locked(
        contract,
        contract_path=path,
        provider=str(binding["provider"]),
        session_id=str(binding["session_id"]),
    )
    if context["target"] != binding["target"]:
        raise IntentGuardianError("task continuation subject changed before binding")
    target_lane = context["target_lane"]
    task_instance_id = str(
        target_lane.get("pending_task_instance_id")
        or target_lane.get("task_instance_id")
        or ""
    )
    lane = _upsert_task_lane_locked(
        contract,
        provider=str(binding["provider"]),
        session_id=str(binding["session_id"]),
        state="bound",
        source="native_session_continuation",
        proposal_digest=str(context["subject"]["proposal_digest"]),
        prompt_sha256=str(target_lane.get("prompt_sha256") or ""),
        task_instance_id=task_instance_id,
        pending_task_instance_id="",
        continuation_token="",
        continuation_eligible=True,
    )
    continuation_id = _canonical_sha256(
        {
            "target": binding["target"],
            "receipt_id": receipt["receipt_id"],
            "request_id": binding["request_id"],
        }
    )
    existing = [
        row
        for row in contract["runtime"].get("task_continuations", [])
        if isinstance(row, dict) and row.get("continuation_id") == continuation_id
    ]
    if not existing:
        contract["runtime"].setdefault("task_continuations", []).append(
            {
                "schema": TASK_CONTINUATION_SCHEMA,
                "continuation_id": continuation_id,
                "target": str(binding["target"]),
                "provider": str(binding["provider"]),
                "session_id": str(binding["session_id"]),
                "task_epoch": str(binding["task_epoch"]),
                "intent_revision": int(binding["intent_revision"]),
                "proposal_digest": str(context["subject"]["proposal_digest"]),
                "policy_sha256": str(context["subject"]["policy_sha256"]),
                "source_lane_sha256": str(
                    context["subject"]["source_lane_sha256"]
                ),
                "target_lane_sha256": str(
                    context["subject"]["target_lane_sha256"]
                ),
                "task_instance_id": str((lane or {}).get("task_instance_id") or ""),
                "receipt_id": str(receipt["receipt_id"]),
                "approval_request_id": str(binding["request_id"]),
                "authority_transferred": False,
                "recorded_at": now_iso(),
            }
        )
        contract["runtime"]["task_continuations"] = contract["runtime"][
            "task_continuations"
        ][-100:]
    reconcile_stale_local_write_events_locked(
        path,
        contract,
        provider=str(binding["provider"]),
        session_id=str(binding["session_id"]),
        boundary="task_continuation_applied",
    )
    return lane or {}

def native_decision_context(
    path: Path,
    *,
    kind: str,
    decision: str,
    target: str,
    provider: str,
    session_id: str = "",
) -> dict[str, Any]:
    """Resolve one human-readable decision without transferring authority."""
    selected_kind = kind.strip().lower()
    selected_decision = decision.strip().lower()
    if selected_kind not in NATIVE_DECISIONS:
        raise IntentGuardianError(f"unsupported native decision kind: {kind!r}")
    if selected_decision not in NATIVE_DECISIONS[selected_kind]:
        raise IntentGuardianError(
            f"unsupported native decision for {selected_kind}: {decision!r}"
        )
    selected_provider = provider.strip().lower()
    if selected_provider != "codex":
        raise IntentGuardianError("native PermissionRequest decisions require provider=codex")
    if selected_kind == "task-continuation":
        reconcile_stale_local_write_events(
            path,
            provider=selected_provider,
            session_id=session_id,
            boundary="task_continuation_request",
        )
    contract = load_contract(path)
    requested_target = target.strip() or "current"

    if selected_kind == "proposal":
        digest = contract["runtime"]["pending_proposal_digest"]
        if not digest:
            raise IntentGuardianError("workspace has no current proposal")
        if requested_target not in {"current", digest}:
            raise IntentGuardianError("native proposal decision targets a stale proposal")
        review = proposal_review_for_digest(path, digest)
        if review["decision_route"] == "agent":
            raise IntentGuardianError(
                "proposal passed the bounded Agent gate before any human prompt; "
                "use agent-decide-proposal instead of PermissionRequest"
            )
        card = review["decision_card"]
        resolved_target = digest
        action = "approve-proposal" if selected_decision == "approve" else "reject-proposal"
        choice = "批准当前方案" if selected_decision == "approve" else "拒绝当前方案"
    elif selected_kind == "grant":
        try:
            grant_tx = grant_transaction_context(
                path,
                target=requested_target,
                provider=selected_provider,
                session_id=session_id,
                task_epoch=str(contract["task_epoch"]),
            )
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            raise IntentGuardianError(f"cannot resolve current human grant: {error}") from error
        resolved_target = str(grant_tx["transaction_id"])
        card = dict(grant_tx["spec"]["readable_card"])
        action = "authorize-event" if selected_decision == "allow" else "deny-event"
        choice = (
            "仅授权卡片中的精确动作一次"
            if selected_decision == "allow"
            else "不执行卡片中的动作"
        )
    elif selected_kind == "intent":
        if contract["runtime"]["pending_proposal_digest"]:
            raise IntentGuardianError("workspace has a current proposal; decide it first")
        if not contract["confirmation"]["required"]:
            raise IntentGuardianError("current intent is already confirmed")
        resolved_target = _intent_confirmation_target(contract)
        if requested_target not in {"current", resolved_target}:
            raise IntentGuardianError("native intent decision targets a stale intent")
        card = _intent_confirmation_card(contract)
        action = "confirm-intent" if selected_decision == "confirm" else "reject-intent"
        choice = "确认当前意图" if selected_decision == "confirm" else "拒绝当前意图"
    elif selected_kind == "resume":
        if contract["runtime"]["pending_proposal_digest"]:
            raise IntentGuardianError("workspace has a current proposal; decide it first")
        pause = _pause_state(
            contract,
            provider=selected_provider,
            session_id=session_id,
        )
        if pause is None:
            raise IntentGuardianError("current task lane is not paused")
        if pause["requires_revision"]:
            raise IntentGuardianError(
                "current pause requires an approved revised proposal before resume"
            )
        resolved_target = _resume_decision_target(
            contract,
            provider=selected_provider,
            session_id=session_id,
        )
        if requested_target not in {"current", resolved_target}:
            raise IntentGuardianError("native resume decision targets a stale pause")
        card = _resume_decision_card(
            contract,
            provider=selected_provider,
            session_id=session_id,
        )
        action = "resume"
        choice = "恢复当前暂停的任务"
    elif selected_kind == "task-continuation":
        with selected_task.decision_lock(path):
            contract = load_contract(path)
            continuation = _task_continuation_context_locked(contract, contract_path=path,
                provider=selected_provider, session_id=session_id)
        resolved_target = str(continuation["target"])
        if requested_target not in {"current", resolved_target}:
            raise IntentGuardianError(
                "native task continuation targets a stale task world"
            )
        card = dict(continuation["card"])
        action = "continue-task"
        choice = "让当前 Codex 会话续接卡片中的同一任务"
    elif selected_kind == "workspace-handoff":
        if requested_target == "current":
            raise IntentGuardianError(
                "workspace handoff requires one explicit target worktree path"
            )
        handoff = workspace_handoff_context(
            kb_home(),
            path,
            Path(requested_target),
            provider=selected_provider,
            session_id=session_id,
        )
        resolved_target = str(handoff["target"])
        card = dict(handoff["card"])
        action = "handoff-workspace"
        choice = "把当前会话切换到卡片中的任务 worktree"
    elif selected_kind == "observation-export":
        try:
            export_proposal = current_export_proposal(kb_home(), path)
        except ObservationPrivacyError as error:
            raise IntentGuardianError(str(error)) from error
        resolved_target = str(export_proposal["proposalDigest"])
        if requested_target not in {"current", resolved_target}:
            raise IntentGuardianError("native observation export targets a stale proposal")
        card = _observation_export_card(export_proposal)
        action = (
            "approve-observation-export"
            if selected_decision == "approve"
            else "reject-observation-export"
        )
        choice = (
            "批准一次本地脱敏观察导出"
            if selected_decision == "approve"
            else "拒绝当前观察导出"
        )
    else:
        try:
            projection = load_intervention_projection(path)
        except (InterventionError, OSError, UnicodeError) as error:
            raise IntentGuardianError(f"cannot replay interventions: {error}") from error
        if requested_target == "current":
            current = _current_effect_intervention(path, provider=selected_provider)
            if current is None:
                raise IntentGuardianError(
                    "workspace has no current-revision intervention; use its explicit id"
                )
            intervention, attempt = current
        else:
            intervention = projection["interventions"].get(requested_target)
            if not isinstance(intervention, dict):
                raise IntentGuardianError("native intervention target does not exist")
            attempt = projection["attempts"].get(intervention.get("attempt_id"))
            if not isinstance(attempt, dict):
                raise IntentGuardianError("native intervention has no matching attempt")
        if intervention.get("status") not in {"open", "acknowledged"}:
            raise IntentGuardianError("native intervention is no longer open")
        if str(attempt.get("provider") or "unknown").lower() != selected_provider:
            raise IntentGuardianError("native intervention belongs to another provider")
        if (
            attempt.get("replay_authoritative") is not True
            and selected_decision != "abort"
        ):
            raise IntentGuardianError(
                "historical intervention lacks replay authority; only abort is available"
            )
        resolved_target = str(intervention["intervention_id"])
        card = _effect_intervention_card(dict(intervention), dict(attempt))
        action = "intervention-resolve"
        choice = {
            "retry_authorized": "授权同一外部操作精确重试一次",
            "reprobe_authorized": "只重新检查当前外部效果",
            "abort": "终止当前外部操作且不重试",
        }[selected_decision]

    operation = {
        "effect-intervention": "effect",
    }.get(selected_kind, selected_kind)
    bound_card = {
        "operation_id": operation,
        "decision_id": selected_decision,
        "action": action,
        "本次选择": action,
        "选择说明": choice,
        "决策内容": card,
        "宿主": "codex",
        "会话内确认": True,
    }
    return {
        "kind": selected_kind,
        "decision": selected_decision,
        "target": resolved_target,
        "action": action,
        "choice": choice,
        "card": bound_card,
        "workspace": contract["workspace_root"],
        "intent_id": contract["intent_id"],
        "intent_revision": contract["revision"],
        "task_epoch": contract["task_epoch"],
    }

def native_decision_description(context: dict[str, Any]) -> str:
    """Render the exact text Codex must show in its current-session prompt."""
    kind = str(context["kind"])
    decision = str(context["decision"])
    card = context["card"]["决策内容"]
    if kind == "proposal":
        objective = str(card.get("要完成的结果") or "当前方案")
        paths = card.get("允许改变", {}).get("可修改路径", [])
        path_count = len(paths) if isinstance(paths, list) else 0
        recovery = card.get("风险与恢复", {}).get("回滚方法", "按方案回滚")
        execution_boundary = card.get("执行权限边界", {})
        destructive_boundary = (
            execution_boundary.get("破坏性操作", "禁止")
            if isinstance(execution_boundary, dict)
            else "禁止"
        )
        external_boundary = (
            execution_boundary.get("外部写入", "禁止")
            if isinstance(execution_boundary, dict)
            else "禁止"
        )
        material_boundaries = [
            (
                "破坏性操作仍禁止"
                if destructive_boundary == "禁止"
                else "包含卡片列明的破坏性操作，且仅限精确路径与动作"
            )
        ]
        if external_boundary != "禁止":
            material_boundaries.append("外部写入仅限卡片列明的密封动作")
        verb = "批准" if decision == "approve" else "拒绝"
        return (
            f"Sulde 当前会话确认：按 Allow 将{verb}方案「{objective}」；"
            "按 Deny 不改变当前方案。"
            f"方案限定 {path_count} 个可修改路径；"
            f"{'；'.join(material_boundaries)}；"
            f"恢复方式：{recovery}。"
        )[:1500]
    if kind == "grant":
        scope = card.get("范围", [])
        rendered_scope = "、".join(str(item) for item in scope) if isinstance(scope, list) else str(scope)
        return (
            f"操作：{card.get('操作', '当前动作')}。范围：{rendered_scope or '当前卡片所列范围'}。"
            "Allow 仅执行一次；Deny 不执行。"
        )[:1500]
    if kind == "intent":
        objective = str(card.get("目标") or card.get("要完成的结果") or "当前意图")
        verb = "确认" if decision == "confirm" else "拒绝"
        return (
            f"Sulde 当前会话确认：按 Allow 将{verb}意图「{objective}」；"
            "按 Deny 不改变当前意图。"
            "该选择只作用于当前工作区与当前意图 revision。"
        )[:1500]
    if kind == "resume":
        objective = str(card.get("恢复后的意图") or "当前意图")
        return (
            f"Sulde 当前会话确认：按 Allow 将恢复任务「{objective}」；"
            "按 Deny 继续保持暂停。"
            "该选择不扩大路径、工具或外部写入权限。"
        )[:1500]
    if kind == "task-continuation":
        objective = str(card.get("当前任务", {}).get("目标") or "当前任务")
        target_session = str(card.get("绑定范围", {}).get("目标会话") or "当前会话")
        return (
            f"Sulde 当前会话确认：按 Allow 将会话 {target_session} 续接任务「{objective}」；"
            "按 Deny 保持只读复核。"
            "只继承任务目标、约束与验收标准；不继承旧会话的 grant、批准回执、"
            "未决事件、效果债务或其他执行权限。"
        )[:1500]
    if kind == "workspace-handoff":
        return (
            "Sulde 当前会话确认：按 Allow 将会话切换到任务 worktree "
            f"{card.get('目标工作区', 'unknown')}；按 Deny 继续使用当前工作区。"
            f"分支：{card.get('目标分支', 'unknown')}；"
            f"HEAD：{card.get('目标 HEAD', 'unknown')}。"
            "只继承任务目标、约束与验收标准；不继承 grant、批准回执、"
            "未决事件、效果债务或 active skill。"
        )[:1500]
    if kind == "observation-export":
        verb = "批准" if decision == "approve" else "拒绝"
        return (
            f"Sulde 当前会话确认：按 Allow 将{verb}一次本地脱敏观察导出；"
            "按 Deny 不改变当前状态。"
            f"目标文件：{card.get('目标文件', 'unknown')}；"
            "本选择不授权覆盖、上传或公开传播。"
        )[:1500]
    known = card.get("当前已知", {})
    return (
        f"Sulde 当前会话确认：按 Allow 将{context['choice']}；按 Deny 不改变当前状态。"
        f"能力：{known.get('能力', 'unknown')}；目标：{known.get('目标', 'unknown')}。"
        "旧 attempt 保持不可变；该选择只消费一次，后续结果仍需独立验证。"
    )[:1500]

def prepare_workspace_proposal(
    home: Path,
    workspace: Path,
    *,
    intent_id: str | None,
    objective: str,
    acceptance_criteria: Iterable[str],
    mode: str,
    rationale: str = "",
    preserve: Iterable[str] = (),
    reject: Iterable[str] = (),
    allowed_paths: Iterable[str] = (),
    semantic_critic: bool = False,
    memory_dependency: str = "dependent",
    decision_route: str = "auto",
    intent_kind: str = "unknown",
    risk: str = "unknown",
    effects: Iterable[str] = ("unknown",),
    reversibility: str = "unknown",
    cost: str = "unknown",
    unattended_policy: str = UNATTENDED_AGENT_IF_ELIGIBLE,
    rollback: str = "",
    unknowns: Iterable[str] = (),
    continuation_grants: Iterable[str] = (),
    provider: str = "unknown",
    session_id: str = "",
    codex_home: Path | None = None,
) -> tuple[Path, Path, str, dict[str, Any]]:
    """Bootstrap safely and freeze one proposal without asking for shell work."""
    path, bootstrapped = ensure_workspace_contract(
        home,
        workspace,
        intent_id=intent_id,
        provider=provider,
        session_id=session_id,
    )
    proposal_path, digest = create_revision_proposal(
        path,
        objective=objective,
        acceptance_criteria=acceptance_criteria,
        mode=mode,
        rationale=rationale,
        preserve=preserve,
        reject=reject,
        allowed_paths=allowed_paths,
        semantic_critic=semantic_critic,
        memory_dependency=memory_dependency,
        decision_route=decision_route,
        intent_kind=intent_kind,
        risk=risk,
        effects=effects,
        reversibility=reversibility,
        cost=cost,
        unattended_policy=unattended_policy,
        rollback=rollback,
        unknowns=unknowns,
        continuation_grants=continuation_grants,
        provider=provider,
        session_id=session_id,
    )
    review = proposal_review(path, proposal_path)
    review["workspace_bootstrapped"] = bootstrapped
    if review["decision_route"] == "human":
        review["continuation"] = prepare_continuation(
            path,
            proposal_digest_value=digest,
            provider=provider,
            session_id=session_id,
            codex_home=codex_home,
        )
    review = proposal_review_for_provider(review, provider)
    return path, proposal_path, digest, review

def prepare_continuation(
    path: Path,
    *,
    proposal_digest_value: str | None = None,
    provider: str = "unknown",
    session_id: str = "",
    codex_home: Path | None = None,
) -> dict[str, Any]:
    """Freeze one authority-free continuation capsule for the pending proposal."""
    contract = load_contract(path)
    digest = proposal_digest_value or contract["runtime"]["pending_proposal_digest"]
    if not digest:
        raise IntentGuardianError("workspace has no current proposal to continue")
    proposal_path = _validate_proposal_for_approval(path, contract, digest)
    target = continuation_path(path, digest)
    target.parent.mkdir(parents=True, exist_ok=True)
    capsule: dict[str, Any]
    capsule_lock = target.with_name(f".{target.name}.lock")
    with _exclusive_path_lock(capsule_lock):
        # Recheck the binding after waiting for a concurrent creator.
        contract = load_contract(path)
        proposal_path = _validate_proposal_for_approval(path, contract, digest)
        if target.is_file():
            try:
                capsule = load_capsule(target)
            except ContinuationError as error:
                raise IntentGuardianError(str(error)) from error
        else:
            review = proposal_review(path, proposal_path)
            proposal = load_contract(proposal_path)
            normalized_provider = provider.strip().lower()
            if normalized_provider not in {"claude", "codex", "unknown"}:
                normalized_provider = "unknown"
            native_session = session_id.strip()[:200]
            rollout = (
                locate_codex_rollout(native_session, codex_home=codex_home)
                if normalized_provider == "codex" and native_session
                else None
            )
            try:
                capsule = build_capsule(
                    contract_path=path,
                    proposal_path=proposal_path,
                    review=review,
                    workspace_root=Path(contract["workspace_root"]),
                    created_at=str(
                        proposal.get("updated_at")
                        or proposal.get("created_at")
                        or now_iso()
                    ),
                    provider=normalized_provider,
                    session_id=native_session,
                    rollout_path=rollout,
                    dialogue=recent_dialogue(rollout),
                )
            except ContinuationError as error:
                raise IntentGuardianError(str(error)) from error
            atomic_write(
                target,
                json.dumps(capsule, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )

    source = capsule["source"]
    _append_continuation_event_once(
        path,
        action="created",
        capsule=capsule,
        provider=str(source["provider"]),
        session_id=str(source["session_id"]),
    )
    try:
        return capsule_summary(capsule, path=target)
    except ContinuationError as error:
        raise IntentGuardianError(str(error)) from error

def continuation_status(path: Path) -> dict[str, Any]:
    """Return a small recovery projection without exposing the decision card."""
    contract = load_contract(path)
    digest = contract["runtime"]["pending_proposal_digest"]
    if not digest:
        return {
            "status": "none",
            "authority_transferred": False,
            "reason": "workspace has no pending proposal",
        }
    target = continuation_path(path, digest)
    if not target.is_file():
        return {
            "status": "missing",
            "authority_transferred": False,
            "reason": "pending proposal has no continuation capsule yet",
        }
    try:
        capsule = load_capsule(target)
    except ContinuationError as error:
        return {
            "status": "invalid",
            "authority_transferred": False,
            "reason": str(error),
            "path": str(target.resolve()),
        }
    if (
        capsule["workspace_root"] != contract["workspace_root"]
        or capsule["intent_id"] != contract["intent_id"]
        or capsule["proposal_digest"] != digest
        or Path(capsule["references"]["contract_path"]).resolve() != path.resolve()
        or Path(capsule["references"]["proposal_path"]).resolve()
        != _proposal_path_for_digest(path, digest).resolve()
    ):
        return {
            "status": "invalid",
            "authority_transferred": False,
            "reason": "continuation capsule no longer matches the active workspace proposal",
            "path": str(target.resolve()),
        }
    return capsule_summary(capsule, path=target)

def continuation_context(
    home: Path,
    workspace: Path,
    *,
    provider: str,
    session_id: str,
) -> str:
    """Load the pending context into SessionStart without transferring authority."""
    mapped = (
        resolve_session_contract(home, provider, session_id)
        if provider.strip().lower() in {"claude", "codex"} and session_id.strip()
        else None
    )
    path = mapped or active_contract_path(home, workspace)
    if not path.is_file():
        return ""
    if mapped is None and session_id.strip():
        discovered = load_contract(path)
        lanes = [
            row
            for row in discovered.get("runtime", {}).get("task_lanes", [])
            if isinstance(row, dict)
        ]
        if lanes and not any(
            str(row.get("provider") or "").lower() == provider.strip().lower()
            and str(row.get("session_id") or "") == session_id.strip()
            for row in lanes
        ):
            # SessionStart is not a continuation request.  Do not inject another
            # conversation's objective/proposal into a newly opened session.
            return ""
    status = continuation_status(path)
    if status.get("status") != "ready":
        return ""
    try:
        capsule = load_capsule(Path(str(status["path"])))
    except ContinuationError:
        return ""
    # A bound lane may keep executing the already approved task while another
    # session prepares the next revision.  Injecting that other session's
    # proposal capsule here confuses task continuation with proposal review and
    # can make an ordinary process restart appear to switch tasks.  The capsule
    # remains available to its source lane and to unbound/review lanes.
    contract = load_contract(path)
    lane = _task_lane(
        contract,
        provider=provider,
        session_id=session_id,
    )
    source = capsule.get("source") if isinstance(capsule.get("source"), dict) else {}
    if (
        isinstance(lane, dict)
        and lane.get("state") == "bound"
        and (
            str(source.get("provider") or "") != provider.strip().lower()
            or str(source.get("session_id") or "") != session_id.strip()
        )
    ):
        return ""
    _append_continuation_event_once(
        path,
        action="loaded",
        capsule=capsule,
        provider=provider,
        session_id=session_id,
    )
    return render_continuation_context(capsule)

def acknowledge_continuation(
    path: Path,
    *,
    proposal_digest_value: str,
    provider: str,
    session_id: str,
) -> None:
    target = continuation_path(path, proposal_digest_value)
    if not target.is_file():
        return
    try:
        capsule = load_capsule(target)
    except ContinuationError:
        return
    _append_continuation_event_once(
        path,
        action="acknowledged",
        capsule=capsule,
        provider=provider,
        session_id=session_id,
    )

def _proposal_path_for_digest(path: Path, digest: str) -> Path:
    stem = path.name[:-5] if path.name.endswith(".json") else path.name
    return path.with_name(f"{stem}.proposal.{digest[:16]}.json")

def validate_material_world(contract: dict[str, Any], proposal: dict[str, Any]) -> None:
    link = proposal["proposal_for"]
    domain = link.get("material_sequence_domain", "total")
    if domain not in {"total", "non_memory_v1"} or (domain == "non_memory_v1" and not memory_scope.independent(proposal)):
        raise IntentGuardianError("proposal material sequence scope is invalid")
    if int(link.get("base_material_sequence", -1)) != memory_scope.sequence(contract["runtime"], scoped=domain == "non_memory_v1"):
        raise IntentGuardianError("proposal base material world has changed")


def _validate_proposal_for_approval(
    path: Path,
    contract: dict[str, Any],
    digest: str,
) -> Path:
    if contract["runtime"]["pending_proposal_digest"] != digest:
        raise IntentGuardianError(
            "proposal is not the current human-visible proposal for this workspace"
        )
    proposal_path = _proposal_path_for_digest(path, digest)
    if not proposal_path.is_file():
        raise IntentGuardianError(
            f"proposal digest is not pending for this workspace contract: {digest}"
        )
    proposal = load_contract(proposal_path)
    if proposal.get("proposal_digest") != digest or proposal_digest(proposal) != digest:
        raise IntentGuardianError("proposal digest does not match the immutable proposal file")
    link = proposal.get("proposal_for")
    if not isinstance(link, dict):
        raise IntentGuardianError("proposal is missing proposal_for provenance")
    if Path(str(link.get("contract_path") or "")).expanduser().resolve() != path.resolve():
        raise IntentGuardianError("proposal targets a different intent contract")
    if int(link.get("base_revision", 0)) != contract["revision"]:
        raise IntentGuardianError("proposal base revision is stale")
    if str(link.get("base_policy_digest") or "") != policy_digest(contract):
        raise IntentGuardianError("proposal base policy has changed")
    validate_material_world(contract, proposal)
    return proposal_path

def _record_proposal_decision_locked(
    contract: dict[str, Any],
    *,
    digest: str,
    authority: str,
    verdict: str,
    rationale: str,
    evidence: Iterable[str],
    provider: str,
    session_id: str,
    receipt_id: str,
) -> dict[str, Any]:
    normalized_evidence = list(evidence)
    existing = next(
        (
            row
            for row in reversed(contract["runtime"]["proposal_decisions"])
            if row["proposal_digest"] == digest
            and row["authority"] == authority
            and row["verdict"] == verdict
            and row["provider"] == provider
            and row["session_id"] == session_id
            and row["receipt_id"] == receipt_id
        ),
        None,
    )
    if existing is not None:
        return existing
    recorded_at = now_iso()
    material = json.dumps(
        {
            "proposal_digest": digest,
            "authority": authority,
            "verdict": verdict,
            "rationale": rationale,
            "evidence": normalized_evidence,
            "provider": provider,
            "session_id": session_id,
            "receipt_id": receipt_id,
            "recorded_at": recorded_at,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    decision = {
        "schema": PROPOSAL_DECISION_SCHEMA,
        "decision_id": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "proposal_digest": digest,
        "authority": authority,
        "verdict": verdict,
        "rationale": rationale,
        "evidence": normalized_evidence,
        "provider": provider,
        "session_id": session_id,
        "receipt_id": receipt_id,
        "recorded_at": recorded_at,
    }
    contract["runtime"]["proposal_decisions"].append(decision)
    contract["runtime"]["proposal_decisions"] = contract["runtime"][
        "proposal_decisions"
    ][-100:]
    return decision

def _record_approval_receipt_locked(
    contract: dict[str, Any],
    *,
    action: str,
    target: str,
    actor: str,
    provider: str,
    session_id: str,
    channel: str,
    observation_source: str,
    decision: str = "",
    evidence_sha256: str = "",
    approval_request_id: str = "",
) -> dict[str, Any]:
    recorded_at = now_iso()
    material = json.dumps(
        {
            "intent_id": contract["intent_id"],
            "intent_revision": contract["revision"],
            "workspace_root": contract["workspace_root"],
            "action": action,
            "target": target,
            "actor": actor,
            "provider": provider,
            "session_id": session_id,
            "channel": channel,
            "observation_source": observation_source,
            "decision": decision,
            "evidence_sha256": evidence_sha256,
            "approval_request_id": approval_request_id,
            "recorded_at": recorded_at,
            "ordinal": len(contract["runtime"]["approval_receipts"]),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    receipt = {
        "schema": DECISION_RECEIPT_SCHEMA,
        "receipt_id": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "action": action,
        "target": target,
        "intent_id": contract["intent_id"],
        "intent_revision": contract["revision"],
        "workspace_root": contract["workspace_root"],
        "provider": provider or "unknown",
        "session_id": session_id,
        "channel": channel,
        "observation_source": observation_source or "unknown",
        "actor": actor,
        "decision": decision,
        "evidence_sha256": evidence_sha256,
        "approval_request_id": approval_request_id,
        "recorded_at": recorded_at,
        "consumed_at": "",
        "consumed_by": "",
    }
    contract["runtime"]["approval_receipts"].append(receipt)
    contract["runtime"]["approval_receipts"] = contract["runtime"]["approval_receipts"][-100:]
    return receipt

def _consume_approval_receipt_locked(
    receipt: dict[str, Any],
    *,
    consumer: str,
) -> None:
    """Atomically mark one exact authority receipt as spent."""
    if receipt.get("consumed_at"):
        raise IntentGuardianError(
            f"approval receipt was already consumed by {receipt.get('consumed_by') or 'unknown'}"
        )
    receipt["consumed_at"] = now_iso()
    receipt["consumed_by"] = consumer[:100]

def _invalidate_stale_approval_receipts_locked(contract: dict[str, Any]) -> int:
    """Expire receipts that can no longer authorize the current intent revision."""
    invalidated = 0
    for receipt in contract["runtime"]["approval_receipts"]:
        if receipt["consumed_at"]:
            continue
        if (
            receipt["intent_id"] != contract["intent_id"]
            or receipt["intent_revision"] != contract["revision"]
            or receipt["workspace_root"] != contract["workspace_root"]
        ):
            _consume_approval_receipt_locked(
                receipt,
                consumer="invalidated-by-intent-revision",
            )
            invalidated += 1
    return invalidated

def _existing_approval_receipt_locked(
    contract: dict[str, Any],
    *,
    action: str,
    target: str,
    actor: str,
    provider: str,
    session_id: str,
    channel: str,
    observation_source: str,
    approval_request_id: str = "",
) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in reversed(contract["runtime"]["approval_receipts"])
            if row["action"] == action
            and row["target"] == target
            and row["actor"] == actor
            and row["provider"] == (provider or "unknown")
            and row["session_id"] == session_id
            and row["channel"] == channel
            and row["observation_source"] == (observation_source or "unknown")
            and (
                not approval_request_id
                or row.get("approval_request_id") == approval_request_id
            )
            and not row["consumed_at"]
        ),
        None,
    )

def native_decision_preview(
    path: Path,
    *,
    kind: str,
    decision: str,
    target: str,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    """Return the exact command arguments and text Codex must present."""
    clean_session = session_id.strip()
    if not clean_session:
        raise IntentGuardianError("native decision requires the current Codex session id")
    context = native_decision_context(
        path,
        kind=kind,
        decision=decision,
        target=target,
        provider=provider,
        session_id=clean_session,
    )
    decision_argv = [
        "native-decision",
        context["kind"],
        "--decision",
        context["decision"],
        "--target",
        context["target"],
        "--contract",
        str(path.expanduser().resolve()),
        "--provider",
        "codex",
        "--session-id",
        clean_session,
    ]
    cli = (Path(__file__).resolve().parents[1] / "intent-guardian.py").resolve()
    return {
        "schema": "sulde-codex-native-decision-preview-v1",
        "authority_transferred": False,
        "kind": context["kind"],
        "decision": context["decision"],
        "target": context["target"],
        "description": native_decision_description(context),
        "argv": decision_argv,
        "command_argv": [sys.executable, str(cli), *decision_argv],
        "requires_native_escalation": True,
        "persistent_prefix_approval": False,
        "decision_card": context["card"],
        "next_action": (
            "Agent invokes argv through Codex native escalation using description verbatim; "
            "the user accepts or denies in this same conversation"
        ),
    }

def _native_card_sha256(card: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            card,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

def _native_binding_snapshot(
    path: Path,
    context: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    """Build the non-executing T12 request envelope shown by PermissionRequest."""
    try:
        workspace = str(Path(context["workspace"]).expanduser().resolve())
    except OSError:
        workspace = str(Path(context["workspace"]).expanduser().absolute())
    workspace_sha256 = hashlib.sha256(
        workspace.encode("utf-8", errors="replace")
    ).hexdigest()
    lane_sha256 = hashlib.sha256(
        f"codex\0{session_id}".encode("utf-8", errors="replace")
    ).hexdigest()
    journal_proof = native_journal_head_proof(path.expanduser().resolve())
    return {
        "card_sha256": _native_card_sha256(context["card"]),
        "provider": "codex",
        "session_id": session_id,
        "lane_sha256": lane_sha256,
        "target_sha256": hashlib.sha256(
            str(context["target"]).encode("utf-8", errors="replace")
        ).hexdigest(),
        "revision": int(context["intent_revision"]),
        "journal_sha256": journal_proof["journal_sha256"],
        "effect_sha256": hashlib.sha256(
            str(context["action"]).encode("utf-8", errors="replace")
        ).hexdigest(),
        "world_state_sha256": workspace_sha256,
    }

def _native_transaction_binding(
    path: Path,
    context: dict[str, Any],
    *,
    request_id: str,
    approval_kind: str,
    session_id: str,
) -> dict[str, Any]:
    del approval_kind
    operation = {
        "proposal": "proposal",
        "resume": "resume",
        "task-continuation": "task-continuation",
        "effect-intervention": "effect",
    }.get(str(context["kind"]))
    if operation is None:
        raise IntentGuardianError("native decision operation cannot be durably sealed")
    effect_attempt_id = ""
    effect_subject_intent_revision = 0
    if operation == "effect":
        try:
            projection = load_intervention_projection(path)
        except (InterventionError, OSError, UnicodeError) as error:
            raise IntentGuardianError(
                f"cannot bind native intervention subject: {error}"
            ) from error
        intervention = projection["interventions"].get(str(context["target"]))
        attempt = (
            projection["attempts"].get(intervention.get("attempt_id"))
            if isinstance(intervention, dict)
            else None
        )
        if not isinstance(attempt, dict):
            raise IntentGuardianError("native intervention has no canonical attempt subject")
        effect_attempt_id = str(attempt.get("attempt_id") or "")
        effect_subject_intent_revision = int(attempt.get("intent_revision") or 0)
    try:
        receipt = request_binding_receipt(path, request_id)
        return seal_native_binding(
            path.expanduser().resolve(),
            operation=operation,
            decision=str(context["decision"]),
            target=str(context["target"]),
            action=str(context["action"]),
            intent_id=str(context["intent_id"]),
            intent_revision=int(context["intent_revision"]),
            task_epoch=str(context["task_epoch"]),
            effect_attempt_id=effect_attempt_id,
            effect_subject_intent_revision=effect_subject_intent_revision,
            workspace=str(context["workspace"]),
            provider="codex",
            session_id=session_id,
            source=NATIVE_PERMISSION_SOURCE,
            card=context["card"],
            request_id=request_id,
            receipt=receipt,
        )
    except (ApprovalInvariantError, NativeDecisionJournalError) as error:
        raise IntentGuardianError(
            f"cannot seal native approval request: {error}"
        ) from error

def _native_decision_failpoint(stage: str) -> None:
    """Test seam for crash-boundary injection; production is deliberately inert."""
    del stage

def _native_receipt_for_request_locked(
    contract: dict[str, Any], binding: dict[str, Any]
) -> dict[str, Any] | None:
    matches = [
        row
        for row in contract["runtime"]["approval_receipts"]
        if isinstance(row, dict)
        and row.get("approval_request_id") == binding["request_id"]
        and row.get("action") == binding["action"]
        and row.get("target") == binding["target"]
        and row.get("provider") == "codex"
        and row.get("session_id") == binding["session_id"]
        and row.get("channel") == "codex-native-permission"
    ]
    if len(matches) > 1:
        raise IntentGuardianError(
            "native decision request has duplicate contract receipts"
        )
    return matches[0] if matches else None

def _record_native_host_observation_locked(
    contract: dict[str, Any],
    binding: dict[str, Any],
    receipt: dict[str, Any],
) -> None:
    observations = contract["runtime"]["host_observations"]
    if any(
        isinstance(row, dict)
        and row.get("event") == "permission_request"
        and row.get("request_id") == binding["request_id"]
        and row.get("receipt_id") == receipt["receipt_id"]
        and row.get("status") == "control_recorded"
        for row in observations
    ):
        return
    observations.append(
        {
            "event": "permission_request",
            "provider": "codex",
            "session_id": binding["session_id"],
            "source": "live_host_hook",
            "status": "control_recorded",
            "control_action": binding["action"],
            "control_target": binding["target"],
            "request_id": binding["request_id"],
            "receipt_id": receipt["receipt_id"],
            "at": now_iso(),
        }
    )
    contract["runtime"]["host_observations"] = observations[-100:]

def _native_effect_evidence(decision: str) -> str:
    return {
        "retry_authorized": "当前 Codex 会话原生批准：同一外部效果精确重试一次",
        "reprobe_authorized": "当前 Codex 会话原生批准：只重新检查同一外部效果",
        "abort": "当前 Codex 会话原生批准：终止同一外部效果且不重试",
    }.get(decision, "")

def _native_base_cas_matches(
    contract: dict[str, Any], binding: dict[str, Any]
) -> bool:
    return bool(
        contract.get("intent_id") == binding["intent_id"]
        and int(contract.get("revision") or 0) == int(binding["intent_revision"])
        and (
            "task_epoch" not in binding
            or contract.get("task_epoch") == binding["task_epoch"]
        )
        and contract.get("workspace_root") == binding["workspace"]
    )

def _native_contract_postcondition(
    contract: dict[str, Any], binding: dict[str, Any]
) -> bool:
    receipt = _native_receipt_for_request_locked(contract, binding)
    if receipt is None or not receipt.get("consumed_at"):
        return False
    if binding["kind"] == "proposal" and binding["decision"] == "approve":
        return bool(
            contract.get("applied_proposal_digest") == binding["target"]
            and contract.get("applied_approval_receipt_id") == receipt["receipt_id"]
        )
    if binding["kind"] == "proposal" and binding["decision"] == "reject":
        decisions = contract.get("runtime", {}).get("proposal_decisions", [])
        return bool(
            contract.get("runtime", {}).get("pending_proposal_digest")
            != binding["target"]
            and any(
                isinstance(row, dict)
                and row.get("proposal_digest") == binding["target"]
                and row.get("authority") == "human"
                and row.get("verdict") == "reject"
                and row.get("receipt_id") == receipt["receipt_id"]
                for row in decisions
            )
        )
    if binding["kind"] == "resume":
        resumed = contract.get("resumed_lane") or {}
        return bool(
            resumed.get("provider") == "codex"
            and resumed.get("session_id") == binding["session_id"]
            and _pause_state(
                contract,
                provider="codex",
                session_id=binding["session_id"],
            )
            is None
        )
    if binding["kind"] == "task-continuation":
        if contract.get("task_continuation_selection") is not None:
            return selected_task.committed(contract, binding, receipt)
        lane = _task_lane(
            contract,
            provider=str(binding["provider"]),
            session_id=str(binding["session_id"]),
        )
        continuations = contract.get("runtime", {}).get(
            "task_continuations", []
        )
        return bool(
            isinstance(lane, dict)
            and lane.get("state") == "bound"
            and lane.get("source") == "native_session_continuation"
            and lane.get("task_epoch") == binding["task_epoch"]
            and any(
                isinstance(row, dict)
                and row.get("target") == binding["target"]
                and row.get("provider") == binding["provider"]
                and row.get("session_id") == binding["session_id"]
                and row.get("task_epoch") == binding["task_epoch"]
                and row.get("receipt_id") == receipt["receipt_id"]
                and row.get("authority_transferred") is False
                for row in continuations
            )
        )
    return binding["kind"] == "effect-intervention"

def _native_approval_was_decided(path: Path, binding: dict[str, Any]) -> bool:
    request = approval_request_by_id(path, binding["request_id"])
    target_sha256 = hashlib.sha256(
        str(binding["target"]).encode("utf-8", errors="replace")
    ).hexdigest()
    intent_id_sha256 = hashlib.sha256(
        str(binding["intent_id"]).encode("utf-8", errors="replace")
    ).hexdigest()
    lane_sha256 = hashlib.sha256(
        f"codex\0{binding['session_id']}".encode("utf-8", errors="replace")
    ).hexdigest()
    try:
        workspace_identity = str(Path(binding["workspace"]).expanduser().resolve())
    except OSError:
        workspace_identity = str(Path(binding["workspace"]).expanduser().absolute())
    workspace_sha256 = hashlib.sha256(
        workspace_identity.encode("utf-8", errors="replace")
    ).hexdigest()
    return bool(
        request
        and request.get("request_id") == binding["request_id"]
        and request.get("intent_id_sha256") == intent_id_sha256
        and int(request.get("intent_revision") or 0)
        == int(binding["intent_revision"])
        and request.get("kind") == binding["approval_kind"]
        and request.get("target_sha256") == target_sha256
        and request.get("card_sha256") == binding["card_sha256"]
        and request.get("workspace_sha256") == workspace_sha256
        and request.get("proposal_sha256")
        == (target_sha256 if binding["approval_kind"] == "proposal" else "")
        and request.get("route") == "human"
        and request.get("provider") == "codex"
        and request.get("lane_sha256") == lane_sha256
        and request.get("source") == NATIVE_PERMISSION_SOURCE
        and request.get("status") == "decided"
        and request.get("outcome")
        == ("allow" if request.get("typed") is True else "approved")
        and request.get("decision_provider") == "codex"
        and request.get("decision_lane_sha256") == lane_sha256
        and request.get("decision_actor") == "permission-request:codex"
    )

def _native_effect_postcondition(
    path: Path, binding: dict[str, Any]
) -> dict[str, Any] | None:
    if binding["kind"] != "effect-intervention":
        return None
    projection = load_intervention_projection(path)
    row = projection["interventions"].get(binding["target"])
    if not isinstance(row, dict) or row.get("status") != "resolved":
        return None
    if row.get("decision") != binding["decision"]:
        return None
    if binding["decision"] in {"retry_authorized", "reprobe_authorized"} and (
        (row.get("takeover_provider") or row.get("provider")) != "codex"
        or (row.get("takeover_session_id") or row.get("session_id"))
        != binding["session_id"]
    ):
        return None
    return dict(row)

def _validate_native_binding_cas(
    path: Path,
    contract: dict[str, Any],
    binding: dict[str, Any],
) -> bool:
    """Validate a sealed decision while the caller holds ``contract_lock``.

    Do not call ``native_decision_context`` here: proposal review and that
    public resolver acquire the same lock. Proposal cards are content-addressed
    by the validated immutable proposal digest; the other cards can be rebuilt
    from the locked contract and the authoritative intervention ledger.
    """
    if not _native_base_cas_matches(contract, binding):
        return False
    kind = str(binding["kind"])
    decision = str(binding["decision"])
    session_id = str(binding["session_id"])
    if kind == "proposal":
        try:
            _validate_proposal_for_approval(path, contract, binding["target"])
        except IntentGuardianError:
            return False
        return True
    if kind == "resume":
        pause = _pause_state(
            contract,
            provider="codex",
            session_id=session_id,
        )
        if (
            pause is None
            or pause["requires_revision"]
            or _resume_decision_target(
                contract,
                provider="codex",
                session_id=session_id,
            )
            != binding["target"]
        ):
            return False
        card = {
            "operation_id": "resume",
            "decision_id": "resume",
            "action": "resume",
            "本次选择": "resume",
            "选择说明": "恢复当前暂停的任务",
            "决策内容": _resume_decision_card(
                contract,
                provider="codex",
                session_id=session_id,
            ),
            "宿主": "codex",
            "会话内确认": True,
        }
        return _native_card_sha256(card) == binding["card_sha256"]
    if kind == "task-continuation":
        receipt = _native_receipt_for_request_locked(contract, binding)
        if receipt and selected_task.committed(contract, binding, receipt):
            return True
        try:
            context = _task_continuation_context_locked(
                contract,
                contract_path=path,
                provider="codex",
                session_id=session_id,
            )
        except IntentGuardianError:
            return False
        card = {
            "operation_id": "task-continuation",
            "decision_id": "approve",
            "action": "continue-task",
            "本次选择": "continue-task",
            "选择说明": "让当前 Codex 会话续接卡片中的同一任务",
            "决策内容": context["card"],
            "宿主": "codex",
            "会话内确认": True,
        }
        return bool(
            context["target"] == binding["target"]
            and _native_card_sha256(card) == binding["card_sha256"]
        )
    if kind != "effect-intervention":
        return False
    try:
        projection = load_intervention_projection(path)
    except (InterventionError, OSError, UnicodeError):
        return False
    intervention = projection["interventions"].get(binding["target"])
    if not isinstance(intervention, dict) or intervention.get("status") not in {
        "open",
        "acknowledged",
    }:
        return False
    attempt = projection["attempts"].get(intervention.get("attempt_id"))
    if (
        not isinstance(attempt, dict)
        or str(attempt.get("provider") or "unknown").lower() != "codex"
        or (
            "effect_attempt_id" in binding
            and (
                binding.get("effect_attempt_id") != attempt.get("attempt_id")
                or binding.get("effect_subject_intent_revision")
                != int(attempt.get("intent_revision") or 0)
            )
        )
    ):
        return False
    if attempt.get("replay_authoritative") is not True and decision != "abort":
        return False
    choice = {
        "retry_authorized": "授权同一外部操作精确重试一次",
        "reprobe_authorized": "只重新检查当前外部效果",
        "abort": "终止当前外部操作且不重试",
    }.get(decision)
    if choice is None:
        return False
    card = {
        "operation_id": "effect",
        "decision_id": decision,
        "action": "intervention-resolve",
        "本次选择": "intervention-resolve",
        "选择说明": choice,
        "决策内容": _effect_intervention_card(
            dict(intervention),
            dict(attempt),
        ),
        "宿主": "codex",
        "会话内确认": True,
    }
    return _native_card_sha256(card) == binding["card_sha256"]

def observe_native_permission_request(
    payload: dict[str, Any],
    *,
    provider: str = "codex",
) -> dict[str, Any]:
    """Bind one native Codex prompt without deciding it for the user."""
    if (
        type(payload) is dict
        and payload.get("schema") == "sulde-native-grant-broker-control-v1"
    ):
        # This exact sealed control lane is evaluated before parsing an
        # ordinary task/tool invocation. The adapter itself remains fail closed.
        return evaluate_grant_broker_control_route(payload)
    tool_name = str(
        payload.get("tool_name") or payload.get("toolName") or ""
    ).lower()
    raw_input = payload.get("tool_input") or payload.get("toolInput") or {}
    tool_input = raw_input if isinstance(raw_input, dict) else {}
    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    invocation = _guardian_invocation(command)
    if invocation is None or invocation.get("action") != "native-decision":
        return {"action": "ignore", "reason": "not a Sulde native decision"}
    if tool_name not in {"bash", "exec_command", "command_execution"}:
        return {"action": "deny", "reason": "native decision requires the Bash tool path"}
    spec = parse_native_decision_command(command)
    if spec is None:
        return {"action": "deny", "reason": "native-decision command is not structurally valid"}
    selected_provider = provider.strip().lower()
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
    permission_mode = str(
        payload.get("permission_mode") or payload.get("permissionMode") or ""
    )
    if (
        selected_provider != "codex"
        or spec["provider"] != selected_provider
        or not session_id
        or spec["session_id"] != session_id
    ):
        return {
            "action": "deny",
            "reason": "native decision provider/session does not match the current Codex lane",
        }
    if permission_mode not in NATIVE_PERMISSION_MODES:
        return {
            "action": "deny",
            "reason": (
                "current permission mode cannot prove an interactive Codex approval "
                f"({permission_mode or 'missing'})"
            ),
        }
    try:
        path = Path(spec["contract"]).expanduser().resolve()
        resolved = resolve_contract_path(payload)
        if resolved is None or path != resolved.expanduser().resolve():
            raise IntentGuardianError(
                "native decision contract is not the active workspace contract"
            )
        context = native_decision_context(
            path,
            kind=spec["kind"],
            decision=spec["decision"],
            target=spec["target"],
            provider=selected_provider,
            session_id=session_id,
        )
        expected_description = native_decision_description(context)
        actual_description = str(
            tool_input.get("description") or tool_input.get("justification") or ""
        ).strip()
        if actual_description != expected_description:
            raise IntentGuardianError(
                "native approval description does not match the current readable decision card"
            )
        if context["kind"] == "grant":
            grant_tx = grant_transaction_context(
                path,
                target=context["target"],
                provider=selected_provider,
                session_id=session_id,
                task_epoch=str(context["task_epoch"]),
            )
            prompt = observe_grant_prompt(path, grant_tx)
            return {
                "action": "defer",
                "reason": "leave the final decision to the current Codex approval prompt",
                "request_id": grant_tx["question"]["request_id"],
                "description": expected_description,
                "observation_status": prompt.get("status", "recorded"),
            }
        approval_kind = {
            "proposal": "proposal",
            "intent": "intent-confirmation",
            "resume": "intent-confirmation",
            "task-continuation": "intent-confirmation",
            "workspace-handoff": "intent-confirmation",
            "observation-export": "observation-export",
            "effect-intervention": "effect-intervention",
        }[context["kind"]]
        approval_projection = load_approval_projection(path)
        binding_snapshot = _native_binding_snapshot(path, context, session_id)
        typed_predecessors = [
            row
            for row in approval_projection["requests"].values()
            if isinstance(row, dict)
            and row.get("typed") is True
            and row.get("kind") == approval_kind
            and row.get("target_sha256") == binding_snapshot["target_sha256"]
            and row.get("source") == NATIVE_PERMISSION_SOURCE
            and row.get("status") == "asked"
            and not isinstance(row.get("typed_receipt"), dict)
        ]
        if len(typed_predecessors) > 1:
            raise IntentGuardianError(
                "native approval target has duplicate typed request lineage"
            )
        if typed_predecessors and (
            approval_request_phase(typed_predecessors[0]) == "expired"
            or typed_predecessors[0].get("snapshot") != binding_snapshot
        ):
            request = replace_typed_approval(
                path,
                previous_request_id=typed_predecessors[0]["request_id"],
                snapshot=binding_snapshot,
                kind=approval_kind,
                source=NATIVE_PERMISSION_SOURCE,
                intent_id=context["intent_id"],
                ttl_seconds=NATIVE_HUMAN_TTL_SECONDS,
                reassess_after_seconds=REASSESS_AFTER_SECONDS,
            )
        else:
            request = ask_typed_approval(
                path,
                snapshot=binding_snapshot,
                kind=approval_kind,
                source=NATIVE_PERMISSION_SOURCE,
                intent_id=context["intent_id"],
                ttl_seconds=NATIVE_HUMAN_TTL_SECONDS,
                reassess_after_seconds=REASSESS_AFTER_SECONDS,
            )
        if request.get("prompt_shown") is not True:
            request = observe_typed_prompt(
                path,
                request_id=request["request_id"],
                snapshot=request["snapshot"],
                provider="codex",
                session_id=session_id,
                prompt_shown=True,
                decision_owner="human",
            )
        with contract_lock(path):
            contract = load_contract(path)
            contract["runtime"]["host_observations"].append(
                {
                    "event": "permission_request",
                    "provider": "codex",
                    "session_id": session_id,
                    "source": "live_host_hook",
                    "status": "control_presented",
                    "control_action": context["action"],
                    "control_target": context["target"],
                    "request_id": request["request_id"],
                    "description_sha256": hashlib.sha256(
                        expected_description.encode("utf-8")
                    ).hexdigest(),
                    "at": now_iso(),
                }
            )
            contract["runtime"]["host_observations"] = contract["runtime"][
                "host_observations"
            ][-100:]
            _write_contract_unlocked(path, contract)
    except (ApprovalInvariantError, IntentGuardianError, OSError, UnicodeError) as error:
        return {"action": "deny", "reason": str(error)}
    return {
        "action": "defer",
        "reason": "leave the final decision to the current Codex approval prompt",
        "request_id": request["request_id"],
        "description": expected_description,
    }


def evaluate_grant_broker_control_route(payload: Any) -> dict[str, Any]:
    """Evaluate only sealed H02 control routes before ordinary tool policy."""
    fields = {
        "schema", "contract", "route", "provider", "session_id", "task_epoch"
    }
    denied = {
        "schema": "sulde-grant-broker-result-v1",
        "action": "deny",
        "transaction_id": "",
        "operation": "",
        "ordinary_pretool_policy_required": True,
    }
    if type(payload) is not dict or set(payload) != fields:
        return {**denied, "reason": "grant broker adapter payload shape is invalid"}
    if payload.get("schema") != "sulde-native-grant-broker-control-v1":
        return {**denied, "reason": "grant broker adapter schema is invalid"}
    if any(
        type(payload.get(field)) is not str or not payload[field].strip()
        for field in ("contract", "provider", "session_id", "task_epoch")
    ) or type(payload.get("route")) is not dict:
        return {**denied, "reason": "grant broker adapter identity is malformed"}
    try:
        return verify_control_route(
            Path(payload["contract"]).expanduser().resolve(),
            payload["route"],
            provider=payload["provider"],
            session_id=payload["session_id"],
            task_epoch=payload["task_epoch"],
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        return {
            **denied,
            "reason": f"grant broker control route failed closed: {error}",
        }

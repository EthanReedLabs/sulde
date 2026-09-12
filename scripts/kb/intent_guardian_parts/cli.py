"""Intent Guardian cli domain component."""

from __future__ import annotations

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

from .state import (
    IntentGuardianError,
    _append_control_event,
    _pause_global_locked,
    _resume_contract_locked,
    _write_contract_unlocked,
    contract_lock,
    load_contract,
    now_iso,
)

def pause_contract(path: Path, reason: str, *, actor: str = "human") -> None:
    with contract_lock(path):
        contract = load_contract(path)
        _pause_global_locked(
            contract,
            reason=reason,
            pause_class="user",
        )
        contract["paused_by"] = actor
        contract["paused_at"] = now_iso()
        _write_contract_unlocked(path, contract)
    _append_control_event(path, "pause", actor=actor, detail=reason[:2_000])

def resume_contract(
    path: Path,
    reason: str,
    *,
    actor: str = "human",
    provider: str = "",
    session_id: str = "",
) -> None:
    with contract_lock(path):
        contract = load_contract(path)
        if contract["status"] != "paused":
            raise IntentGuardianError(f"contract is not paused: {contract['status']}")
        _resume_contract_locked(
            contract,
            reason,
            actor=actor,
            provider=provider,
            session_id=session_id,
        )
        _write_contract_unlocked(path, contract)
    _append_control_event(path, "resume", actor=actor, detail=reason[:2_000])

def approve_event(
    path: Path,
    fingerprint: str,
    *,
    actor: str = "human",
    provider: str = "unknown",
    session_id: str = "",
    channel: str = "cli",
    observation_source: str = "human_cli",
) -> dict[str, Any]:
    raise IntentGuardianError(
        "event digest approval is retired; authorize readable task scope and let the "
        "supervisor verify observable effects"
    )

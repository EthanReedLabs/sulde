"""Public compatibility facade for the split Intent Guardian domains."""

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
    settle_legacy_read_only_debt as settle_legacy_read_only_effect_debt,
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
    NativeAuthorityReaders,
    NativeDecisionJournalError,
    advance_with_authority as advance_native_transaction_with_authority,
    pending as pending_native_transactions,
    prepare as prepare_native_transaction,
    produce_contract_receipt as produce_native_contract_receipt,
    produce_effect_receipt as produce_native_effect_receipt,
    produce_external_head_receipt as produce_native_external_head_receipt,
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

from intent_guardian_parts.state import (
    CONTRACT_SCHEMA,
    EVENT_SCHEMA,
    LEGACY_HUMAN_CONTROL_RECEIPT_SCHEMA,
    DECISION_RECEIPT_SCHEMA,
    PROPOSAL_REVIEW_SCHEMA,
    PROPOSAL_DECISION_SCHEMA,
    CONTINUATION_GRANT_SCHEMA,
    CONTINUATION_USE_SCHEMA,
    TASK_CONTINUATION_SCHEMA,
    MODES,
    STATUSES,
    EFFECT_ORDER,
    EFFECTS,
    DECISION_ROUTES,
    INTENT_KINDS,
    RISK_LEVELS,
    REVERSIBILITY_LEVELS,
    COST_LEVELS,
    RUNTIME_GENERATION,
    CONTINUATION_PROFILES,
    AGENT_CONTINUATION_PROFILES,
    COMPENSATION_CONTINUATION_PROFILES,
    BOOTSTRAP_RETRY_BINDING_FIELDS,
    CONTINUATION_BINDING_FIELDS,
    CONTINUATION_BINDING_DIGEST_FIELDS,
    SYSTEM_MEMORY_PROFILE,
    SYSTEM_MEMORY_MAX_USES,
    SYSTEM_MEMORY_GRANT_ID,
    AGENT_CONTROL_ACTIONS,
    READ_ONLY_AGENT_CONTROL_ACTIONS,
    NATIVE_PERMISSION_CONTROL_ACTIONS,
    NATIVE_PERMISSION_MODES,
    NATIVE_DECISIONS,
    NATIVE_PERMISSION_SOURCE,
    HUMAN_DECISION_CLI_ACTIONS,
    BREAK_GLASS_CONTROL_ACTIONS,
    HUMAN_CONTROL_ACTIONS,
    PAUSE_SAFE_HOST_CONTROL_ACTIONS,
    GUARDIAN_LAUNCHER_NAMES,
    AGENT_DECISION_SENSITIVE_PATHS,
    READ_WORDS,
    WRITE_WORDS,
    DESTRUCTIVE_WORDS,
    CORRECTION_PATTERNS,
    SECRET_KEY,
    SUBJECTIVE_INTENT_PATTERN,
    EXTERNAL_INTENT_PATTERN,
    DESTRUCTIVE_INTENT_PATTERN,
    COST_INTENT_PATTERN,
    EXPLICIT_RELEASE_RUNTIME_INPUTS,
    _VERIFICATION_CONTENT_KEYS,
    _SECRET_VALUE_PATTERN,
    _loaded_runtime_generation,
    _has_unnegated_signal,
    IntentGuardianError,
    Decision,
    DecisionV2,
    now_iso,
    _task_epoch,
    _current_paused_task_lanes,
    _pause_state,
    _clear_pause_projection_locked,
    _refresh_lane_pause_projection_locked,
    _pause_lane_locked,
    _pause_global_locked,
    kb_home,
    atomic_write,
    _exclusive_path_lock,
    contract_lock,
    _append_jsonl,
    workspace_root,
    workspace_binding_key,
    workspace_key,
    bound_contract_path,
    active_contract_path,
    rebind_marker_path,
    retire_marker_path,
    session_contract_path,
    audit_path,
    _strings,
    _normalize_effects,
    _intent_confirmation_card,
    _intent_confirmation_target,
    _resume_decision_card,
    _resume_decision_target,
    _ensure_intent_confirmation_request,
    default_contract,
    _continuation_grant_id,
    _validate_continuation,
    validate_contract,
    load_contract,
    write_contract,
    _write_contract_unlocked,
    policy_digest,
    proposal_digest_payload,
    proposal_digest,
    _sha256_path,
    _workspace_tracked_tree_sha256,
    _json_version,
    _cachebuster_value,
    _plugin_manifest_after_cachebuster,
    _codex_plugin_cachebuster_binding,
    _codex_plugin_install_binding,
    build_continuation_grants,
    implicit_continuation_grant_specs,
    _agent_continuation_eligibility,
    event_fingerprint,
    _resume_contract_locked,
    _append_control_event,
)

from intent_guardian_parts.continuation_audit import _append_continuation_event_once

from intent_guardian_parts.pre_execution_control import (
    finalize_pre_execution_probe,
    prepare_pre_execution_probe,
)

from intent_guardian_parts.session_workspace import (
    apply_workspace_handoff,
    finalize_workspace_cleanup,
    load_session_workspace,
    prepare_workspace_handoff,
    release_completed_workspace,
    registered_worktree_identity,
    resolve_session_contract,
    seed_session_workspace_hint,
    session_workspace_path,
    workspace_cleanup_status,
    workspace_handoff_context,
)

from intent_guardian_parts.resources import (
    resolve_contract_path,
    _section,
    _bullets,
    contract_from_brief,
    _words,
    _safe_target,
    _first_input_value,
    _response_target,
    _verification_digest,
    _memory_annotation_postcondition,
    _system_memory_annotation_candidate,
    _local_memory_annotation_verification,
    _write_verification_expectation,
    _read_verification_evidence,
    _response_proves_existence,
    _input_digest,
    _contains_sensitive_material,
    _trusted_guardian_launcher_digest,
    _guardian_invocation,
    parse_native_decision_command,
    _guardian_control_command,
    _shell_syntax_check_target,
    _direct_host_callback_command,
    _trusted_script_command,
    _resolved_executable,
    _codex_plugin_cachebuster_candidate,
    _codex_plugin_install_candidate,
    _codex_plugin_read_only_maintenance_command,
    _command_effect,
    _extract_patch_text,
    _git_invocation,
    _local_git_output,
    _git_remote_digest,
    _git_head_ref,
    _git_upstream,
    _git_positionals,
    _git_ref_observation,
    _response_strings,
    _portable_tree_sha256,
    _codex_plugin_cachebuster_verification,
    _codex_plugin_install_verification,
    _continuation_candidate_from_grant,
    _registered_continuation_verification,
    _pending_verification_grant,
    _git_ref_read_evidence,
    _git_ref_read_context,
    _command_write_targets,
    _pause_safe_host_control_action,
    _guardian_skill_command,
    _capability,
    _local_target_label,
    normalize_hook_event,
)

from intent_guardian_parts.approvals import (
    _pending_verifications_are_one_sealed_compensation,
    agent_decision_eligibility,
    create_revision_proposal,
    reconcile_stale_local_write_events,
    ensure_workspace_contract,
    proposal_review,
    proposal_review_for_provider,
    proposal_review_for_digest,
    _current_effect_intervention,
    _effect_intervention_card,
    _observation_export_card,
    _task_continuation_context_locked,
    _apply_task_continuation_locked,
    native_decision_context,
    native_decision_description,
    prepare_workspace_proposal,
    prepare_continuation,
    continuation_status,
    continuation_context,
    acknowledge_continuation,
    _proposal_path_for_digest,
    _validate_proposal_for_approval,
    _record_proposal_decision_locked,
    _record_approval_receipt_locked,
    _consume_approval_receipt_locked,
    _invalidate_stale_approval_receipts_locked,
    _existing_approval_receipt_locked,
    native_decision_preview,
    _native_card_sha256,
    _native_transaction_binding,
    _native_decision_failpoint,
    _native_receipt_for_request_locked,
    _record_native_host_observation_locked,
    _native_effect_evidence,
    _native_base_cas_matches,
    _native_contract_postcondition,
    _native_approval_was_decided,
    _native_effect_postcondition,
    _validate_native_binding_cas,
    observe_native_permission_request,
)

from intent_guardian_parts.recovery import (
    decision_request_context,
    _ensure_native_receipt_projection_locked,
    _finish_native_proposal,
    _advance_native_transaction,
    recover_native_decisions,
    _late_native_proposal_result,
    execute_native_decision,
    _execute_native_decision_legacy,
    approve_proposal,
    _approve_proposal_locked,
    _receipt_has_live_prompt_evidence,
    _receipt_has_native_permission_evidence,
    _receipt_has_agent_policy_evidence,
    decide_proposal_as_agent,
    _native_proposal_requests,
    reconcile_obsolete_approval_requests,
    reassess_unattended_proposal,
    _authorize_bootstrap_retries_for_applied_proposal,
    apply_revision_proposal,
    activate_contract,
    rebind_workspace_contract,
    retire_orphan_contract,
    _reconcile_read_only_effect_debt_locked,
    _probe_pending_verifications,
    _apply_reconciled_pending_locked,
    _settled_pending_verification_ids,
    _prune_settled_pending_locked,
    reconcile_pending_verifications,
    effect_intervention_report,
    acknowledge_effect_intervention,
    resolve_effect_intervention,
    _resolve_effect_intervention_locked,
    _project_effect_intervention_locked,
)

from intent_guardian_parts.events import (
    normalize_provider_event,
    normalize_provider_events,
    _effect_attempt_target,
    _effect_resource_identity,
    _read_proof_target,
    _matches,
    _matches_mcp_server,
    _paths_allowed,
    _path_allowed,
    _paths_frozen,
    _path_frozen,
    _event_local_targets,
    _human_approved_local_destructive,
    _completion_shape_matches,
    _matching_continuation_uses,
    _completion_open_event_index,
    _hot_upgrade_completion_authorization,
    _continuation_authorization,
    _retag_guardian_violation,
    _registered_compensation_predecessor,
    _registered_semantic_retry_intervention,
)

from intent_guardian_parts.policy import (
    evaluate_event,
    _critic_inconclusive_result,
    _record_critic_result_locked,
    GuardianSession,
    _finalize_lane,
    run_semantic_critic_checkpoint,
)

from intent_guardian_parts.audit import (
    process_hook,
    finalize_host_turn,
    record_skill_event,
    observe_user_prompt,
)

from intent_guardian_parts.cli import (
    pause_contract,
    resume_contract,
    approve_event,
)

from intent_guardian_parts.readiness import (
    _approval_capture_summary,
    guardian_report,
    guardian_inventory,
    guardian_doctor,
)

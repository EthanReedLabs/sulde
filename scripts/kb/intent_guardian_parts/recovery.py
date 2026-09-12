"""Intent Guardian recovery domain component."""
from __future__ import annotations

from . import memory_scope
import hashlib
import json
import os
from pathlib import Path
import re
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
from sulde_paths import contract_identity_digest
from .native_recovery import recover_native_decisions_independently
from .native_grant import execute_native_grant_decision
from approval_invariant import (
    ApprovalInvariantError,
    authoritative_store_bytes as approval_authoritative_store_bytes,
    ask_approval,
    ask_typed_approval,
    cancel_request as cancel_approval_request,
    cancel_open_requests as cancel_open_approval_requests,
    decide_approval,
    decide_typed_approval,
    decided_request_receipt,
    load_projection as load_approval_projection,
    open_requests as approval_open_requests,
    observe_typed_prompt,
    request_binding_receipt,
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
    terminal_quarantined_attempts,
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
    _advance_receipt_chain_locked as _advance_native_receipt_chain_locked,
    advance_with_authority as advance_native_transaction_with_authority,
    head_proof as native_journal_head_proof,
    pending as pending_native_transactions,
    prepare as prepare_native_transaction,
    produce_effect_receipt as produce_native_effect_receipt,
    supersede as supersede_native_transaction,
)
from operational_readiness import project as operational_readiness_projection
from recovery_lane import REQUEST_SCHEMA as RECOVERY_REQUEST_SCHEMA, RecoveryLane
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
    validate_material_world,
    _consume_approval_receipt_locked,
    _current_effect_intervention,
    _effect_intervention_card,
    _apply_task_continuation_locked,
    _existing_approval_receipt_locked,
    _invalidate_stale_approval_receipts_locked,
    _native_approval_was_decided,
    _native_base_cas_matches,
    _native_contract_postcondition,
    _native_decision_failpoint,
    _native_effect_evidence,
    _native_effect_postcondition,
    _native_receipt_for_request_locked,
    _native_transaction_binding,
    _observation_export_card,
    _proposal_path_for_digest,
    _record_approval_receipt_locked,
    _record_native_host_observation_locked,
    _record_proposal_decision_locked,
    _validate_native_binding_cas,
    _validate_proposal_for_approval,
    acknowledge_continuation,
    agent_decision_eligibility,
    native_decision_context,
    _task_continuation_context_locked,
    proposal_review_for_digest,
)
from .resources import (
    _memory_receipt_verification,
    _input_digest,
    _continuation_candidate_from_grant,
    _pending_verification_grant,
    _registered_continuation_verification,
)
from .readiness import reconcile_git_control_debt_locked
from .stale_events import proposal_open_event_blocker, require_proposal_open_event_clear
from .figma_read_recovery import reconcile_misclassified_figma_reads
from .completion_recovery import recover_completed_audit_verifications
from .selected_task import decision_lock as native_decision_lock, recovery_origin, recover_terminal, supersede_route
from .session_workspace import (
    apply_session_mapping_rebind,
    apply_workspace_handoff,
    prepare_session_mapping_rebind,
    resolve_session_contract,
    session_may_discover_contract,
    workspace_cleanup_context,
)
from .intervention_control import (
    _project_effect_intervention_locked,
    _resolve_effect_intervention_locked,
    acknowledge_effect_intervention,
    effect_intervention_report,
    resolve_effect_intervention,
)
from .state import (
    BOOTSTRAP_RETRY_BINDING_FIELDS,
    COMPENSATION_CONTINUATION_PROFILES,
    CONTINUATION_GRANT_SCHEMA,
    IntentGuardianError,
    NATIVE_DECISIONS,
    NATIVE_PERMISSION_SOURCE,
    _append_control_event,
    _append_native_resume_event,
    _append_jsonl,
    _ensure_intent_confirmation_request,
    _exclusive_path_lock,
    _intent_confirmation_card,
    _pause_global_locked,
    _pause_state,
    _resume_contract_locked,
    _resume_decision_card,
    _resume_decision_target,
    _write_contract_unlocked,
    active_contract_path,
    atomic_write,
    audit_path,
    bound_contract_path,
    contract_lock,
    kb_home,
    load_contract,
    now_iso,
    policy_digest,
    proposal_digest,
    rebind_marker_path, retire_marker_path, validate_contract, workspace_root,
    write_contract,
)
def decision_request_context(
    home: Path,
    workspace: Path,
    *,
    provider: str,
    session_id: str,
) -> str:
    eligible = provider.strip().lower() in {"claude", "codex"} and session_id.strip()
    mapped = resolve_session_contract(home, provider, session_id) if eligible else None
    path = mapped or active_contract_path(home, workspace_root(workspace))
    if not path.is_file():
        return ""
    if mapped is None and session_id.strip() and not session_may_discover_contract(
        load_contract(path), provider=provider, session_id=session_id):
        return ""
    try:
        cancel_open_approval_requests(path, kinds={"event"}, actor="session-start-event-approval-retirement")
    except (ApprovalInvariantError, OSError, UnicodeError):
        return ""
    # A SessionStart retires stale conversational authority elsewhere, but it
    # cannot prove that this host will dispatch the next material PreToolUse.
    # Post-only gaps therefore survive restart until an exact negative canary
    # is denied before execution and finalized against an absent marker.
    # Do not ask a person to attest an effect the local verifier can now prove
    # (for example after a missing PostToolUse stdout or a hot-update restart).
    reconcile_pending_verifications(path)
    reconcile_obsolete_approval_requests(path)
    contract = load_contract(path)
    if cleanup_context := workspace_cleanup_context(contract):
        return cleanup_context
    pending = contract["runtime"]["pending_proposal_digest"]
    applicable_pause = _pause_state(
        contract,
        provider=provider,
        session_id=session_id,
    )
    try:
        export_proposal = current_export_proposal(home, path)
    except ObservationPrivacyError:
        export_proposal = None
    current_intervention = _current_effect_intervention(
        path,
        provider=provider,
    )
    if export_proposal is not None:
        card = _observation_export_card(export_proposal)
        try:
            request = ask_approval(
                path,
                intent_id=contract["intent_id"],
                intent_revision=contract["revision"],
                kind="observation-export",
                target=str(export_proposal["proposalDigest"]),
                provider=provider,
                session_id=session_id,
                source="session_start_restore",
                card=card,
                workspace=contract["workspace_root"],
                route="human",
            )
        except (ApprovalInvariantError, OSError, UnicodeError):
            return ""
        label = "当前观察导出"
    elif current_intervention is not None:
        intervention, attempt = current_intervention
        card = _effect_intervention_card(intervention, attempt)
        try:
            request = ask_approval(
                path,
                intent_id=contract["intent_id"],
                intent_revision=contract["revision"],
                kind="effect-intervention",
                target=str(intervention["intervention_id"]),
                provider=provider,
                session_id=session_id,
                source="session_start_restore",
                card=card,
                workspace=contract["workspace_root"],
                route="human",
            )
        except (ApprovalInvariantError, OSError, UnicodeError):
            return ""
        label = "当前外部效果干预"
    elif pending:
        try:
            review = proposal_review_for_digest(path, pending)
            if provider.strip().lower() == "codex":
                # SessionStart presents; PermissionRequest owns authority.
                request = {"route": "human"}
            else:
                request = ask_approval(
                    path,
                    intent_id=contract["intent_id"],
                    intent_revision=contract["revision"],
                    kind="proposal",
                    target=pending,
                    source="session_start_restore",
                    card=review["decision_card"],
                    workspace=contract["workspace_root"],
                    route="human",
                    reuse_decided=True,
                )
        except (ApprovalInvariantError, IntentGuardianError, OSError, UnicodeError):
            return ""
        card = review["decision_card"]
        label = "当前方案"
    elif contract["confirmation"]["required"]:
        try:
            request = _ensure_intent_confirmation_request(path, contract)
        except IntentGuardianError:
            return ""
        if request is None:
            return ""
        card = _intent_confirmation_card(contract)
        label = "当前意图"
    elif applicable_pause is not None and not applicable_pause["requires_revision"]:
        card = _resume_decision_card(
            contract,
            provider=provider,
            session_id=session_id,
        )
        try:
            request = ask_approval(
                path,
                intent_id=contract["intent_id"],
                intent_revision=contract["revision"],
                kind="intent-confirmation",
                target=_resume_decision_target(
                    contract,
                    provider=provider,
                    session_id=session_id,
                ),
                provider=provider,
                session_id=session_id,
                source="session_resume_card",
                card=card,
                workspace=contract["workspace_root"],
                route="human",
                reuse_decided=True,
            )
        except (ApprovalInvariantError, OSError, UnicodeError):
            return ""
        label = "当前暂停"
    elif provider.strip().lower() == "codex":
        try:
            continuation = _task_continuation_context_locked(
                contract,
                contract_path=path,
                provider=provider,
                session_id=session_id,
            )
        except IntentGuardianError:
            return ""
        request = {"route": "human"}
        card = continuation["card"]
        label = "当前任务续接"
    else:
        return ""
    if provider.strip().lower() == "codex":
        next_step = "Agent 应在当前对话展示 Codex 原生 Allow/Deny。"
    else:
        next_step = (
            "当前宿主没有已验证的原生决策面，状态保持 pending。Agent 应负责建立或修复 "
            "宿主原生决策通道；不得要求用户输入固定短语、复制摘要或执行 CLI 命令。"
        )
    return (
        f"[sulde-decision-request] OPEN route={request['route']} "
        "binding=internal authority_transferred=false\n"
        f"{label}确认卡：\n"
        + json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
        + next_step
    )

def _ensure_native_receipt_projection_locked(
    contract: dict[str, Any],
    path: Path,
    binding: dict[str, Any],
    *,
    resolved_intervention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actor = "permission-request:codex"
    receipt = _native_receipt_for_request_locked(contract, binding)
    decision = binding["decision"]
    if receipt is None:
        if binding["kind"] == "proposal" and decision == "approve":
            receipt = _approve_proposal_locked(
                contract,
                binding["target"],
                actor=actor,
                provider="codex",
                session_id=binding["session_id"],
                channel="codex-native-permission",
                observation_source="live_host_hook",
                approval_request_id=binding["request_id"],
            )
        else:
            evidence = _native_effect_evidence(decision)
            receipt = _record_approval_receipt_locked(
                contract,
                action=binding["action"],
                target=binding["target"],
                actor=actor,
                provider="codex",
                session_id=binding["session_id"],
                channel="codex-native-permission",
                observation_source="live_host_hook",
                decision=(decision if binding["kind"] == "effect-intervention" else ""),
                evidence_sha256=(
                    hashlib.sha256(evidence.encode("utf-8")).hexdigest()
                    if evidence
                    else ""
                ),
                approval_request_id=binding["request_id"],
            )
    if binding["kind"] == "proposal":
        verdict = "approve" if decision == "approve" else "reject"
        _record_proposal_decision_locked(
            contract,
            digest=binding["target"],
            authority="human",
            verdict=verdict,
            rationale=(
                "用户在当前 Codex PermissionRequest 卡片中批准方案"
                if verdict == "approve"
                else "用户在当前 Codex PermissionRequest 卡片中拒绝方案"
            ),
            evidence=["live PermissionRequest", "exact readable description"],
            provider="codex",
            session_id=binding["session_id"],
            receipt_id=receipt["receipt_id"],
        )
        if verdict == "reject":
            contract["runtime"]["approved_proposal_digests"] = [
                item
                for item in contract["runtime"]["approved_proposal_digests"]
                if item != binding["target"]
            ]
            contract["runtime"]["pending_proposal_digest"] = ""
            if not receipt.get("consumed_at"):
                _consume_approval_receipt_locked(
                    receipt, consumer="native-permission-control-executor"
                )
    elif binding["kind"] == "resume":
        if not receipt.get("consumed_at"):
            _resume_contract_locked(
                contract,
                "用户在当前 Codex PermissionRequest 中恢复任务",
                actor=actor,
                provider="codex",
                session_id=binding["session_id"],
            )
            _consume_approval_receipt_locked(
                receipt, consumer="native-permission-control-executor"
            )
    elif binding["kind"] == "task-continuation":
        if not receipt.get("consumed_at"):
            _apply_task_continuation_locked(path, contract, binding, receipt)
            receipt = _native_receipt_for_request_locked(contract, binding) or receipt
            _consume_approval_receipt_locked(
                receipt, consumer="native-permission-control-executor"
            )
    elif binding["kind"] == "effect-intervention":
        resolved = resolved_intervention
        if resolved is None:
            projection = load_intervention_projection(path)
            candidate = projection["interventions"].get(binding["target"])
            resolved = dict(candidate) if isinstance(candidate, dict) else None
        if not isinstance(resolved, dict) or resolved.get("decision") != decision:
            raise IntentGuardianError(
                "native intervention ledger does not contain the approved decision"
            )
        _project_effect_intervention_locked(
            contract,
            resolved,
            decision=decision,
            evidence=_native_effect_evidence(decision),
        )
        if not receipt.get("consumed_at"):
            _consume_approval_receipt_locked(
                receipt, consumer="native-permission-control-executor"
            )
    _record_native_host_observation_locked(contract, binding, receipt)
    return receipt

def _finish_native_proposal(
    path: Path,
    binding: dict[str, Any],
) -> dict[str, Any]:
    if binding["decision"] != "approve":
        return load_contract(path)
    current = load_contract(path)
    if current.get("applied_proposal_digest") != binding["target"]:
        current = apply_revision_proposal(
            path,
            _proposal_path_for_digest(path, binding["target"]),
            actor="native-permission-control-executor",
        )
    receipt = next(
        (
            row
            for row in current["runtime"]["approval_receipts"]
            if isinstance(row, dict)
            and row.get("approval_request_id") == binding["request_id"]
        ),
        None,
    )
    if isinstance(receipt, dict):
        _authorize_bootstrap_retries_for_applied_proposal(
            path,
            previous=current,
            applied=current,
            receipt=receipt,
            proposal_digest_value=binding["target"],
        )
    acknowledge_continuation(
        path,
        proposal_digest_value=binding["target"],
        provider="codex",
        session_id=binding["session_id"],
    )
    for open_request in approval_open_requests(
        path,
        kind="proposal",
        workspace=binding["workspace"],
        route="human",
    ):
        if (
            open_request.get("target_sha256")
            == hashlib.sha256(
                binding["target"].encode("utf-8", errors="replace")
            ).hexdigest()
            and open_request.get("source") != NATIVE_PERMISSION_SOURCE
        ):
            cancel_approval_request(
                path,
                open_request["request_id"],
                actor="native-proposal-applied",
            )
    return current

def _produce_t12_native_approval(
    path: Path, transaction: dict[str, Any], binding: dict[str, Any],
) -> bool:
    """Reuse typed authority; bridge only historical untyped requests."""
    if not _native_approval_was_decided(path, binding):
        return False
    original_request = approval_request_by_id(path, binding["request_id"])
    if isinstance(original_request, dict) and original_request.get("typed") is True:
        return True
    journal_contract = path.expanduser().resolve()
    proof = native_journal_head_proof(journal_contract)
    canonical_binding = json.dumps(
        binding,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    binding_sha256 = hashlib.sha256(canonical_binding.encode("utf-8")).hexdigest()
    contract_sha256 = contract_identity_digest(journal_contract)
    world_state_sha256 = hashlib.sha256(
        json.dumps(
            {
                "binding_sha256": binding_sha256,
                "card_sha256": binding["card_sha256"],
                "contract_sha256": contract_sha256,
                "operation": binding["operation"],
                "request_binding_sha256": binding["request_binding_sha256"],
                "request_id": binding["request_id"],
                "transaction_id": transaction["transaction_id"],
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    lane_sha256 = hashlib.sha256(
        f"{binding['provider']}\0{binding['session_id']}".encode(
            "utf-8", errors="replace"
        )
    ).hexdigest()
    snapshot = {
        "card_sha256": binding["card_sha256"],
        "provider": binding["provider"],
        "session_id": binding["session_id"],
        "lane_sha256": lane_sha256,
        "target_sha256": hashlib.sha256(
            binding["target"].encode("utf-8", errors="replace")
        ).hexdigest(),
        "revision": binding["intent_revision"],
        "journal_sha256": proof["journal_sha256"],
        "effect_sha256": hashlib.sha256(
            binding["action"].encode("utf-8", errors="replace")
        ).hexdigest(),
        "world_state_sha256": world_state_sha256,
    }
    projection = load_approval_projection(path)
    matching = [
        row
        for row in projection["requests"].values()
        if isinstance(row, dict)
        and row.get("typed") is True
        and row.get("snapshot") == snapshot
        and row.get("kind") == binding["approval_kind"]
        and row.get("source") == NATIVE_PERMISSION_SOURCE
    ]
    if len(matching) > 1:
        raise IntentGuardianError("native human decision has duplicate typed T12 requests")
    if matching:
        typed_request = matching[0]
    else:
        typed_request = ask_typed_approval(
            path,
            snapshot=snapshot,
            kind=binding["approval_kind"],
            source=NATIVE_PERMISSION_SOURCE,
            intent_id=binding["intent_id"],
            ttl_seconds=NATIVE_HUMAN_TTL_SECONDS,
            reassess_after_seconds=REASSESS_AFTER_SECONDS,
        )
    if typed_request.get("prompt_shown") is not True:
        typed_request = observe_typed_prompt(
            path,
            request_id=typed_request["request_id"],
            snapshot=snapshot,
            provider=binding["provider"],
            session_id=binding["session_id"],
            prompt_shown=True,
            decision_owner="human",
        )
    if not isinstance(typed_request.get("typed_receipt"), dict):
        binding_receipt = request_binding_receipt(path, binding["request_id"])
        human_receipt = decided_request_receipt(
            path,
            binding_receipt,
            outcome=(
                "allow"
                if approval_request_by_id(path, binding["request_id"]).get("typed")
                is True
                else "approved"
            ),
            provider=binding["provider"],
            session_id=binding["session_id"],
            actor="permission-request:codex",
        )
        decide_typed_approval(
            path,
            request_id=typed_request["request_id"],
            receipt_id=human_receipt["decision_sha256"],
            outcome="allow",
            snapshot=snapshot,
            current_snapshot=snapshot,
            provider=binding["provider"],
            session_id=binding["session_id"],
            decision_owner="human",
            actor="permission-request:codex",
        )
    return True

def _advance_native_transaction(
    path: Path,
    transaction: dict[str, Any],
    *,
    inject_failpoints: bool = False,
) -> dict[str, Any]:
    """Recover one sealed internal decision from formal durable authorities.

    Each public journal advancement performs exactly one CAS.  The operation's
    real internal postcondition is established before its source-specific
    producer runs; the producer is then independently replayed by
    ``advance_with_authority``.  Re-entering this function after any crash is
    safe because every internal mutation and every producer is idempotent.
    """
    tx_id = str(transaction["transaction_id"])
    binding = dict(transaction["binding"])
    journal_contract = path.expanduser().resolve()
    readers = NativeAuthorityReaders(
        approval=None,
        effect=None,
        contract=None,
        head_anchor=None,
    )

    while str(transaction["stage"]) != "committed":
        stage = str(transaction["stage"])
        if stage == "prepared":
            if not _produce_t12_native_approval(path, transaction, binding):
                return transaction
            result = advance_native_transaction_with_authority(
                journal_contract,
                tx_id,
                readers=readers,
            )
            if not result["advanced"]:
                return dict(transaction, advancement_reason=result["reason"])
            transaction = dict(transaction, stage=result["stage"])
            if inject_failpoints:
                _native_decision_failpoint("after_approval_decided")
            continue

        if stage == "approval_decided":
            resolved = _native_effect_postcondition(path, binding)
            with native_decision_lock(path):
                contract = load_contract(path)
                already_applied = _native_contract_postcondition(contract, binding)
                if (
                    not already_applied
                    and resolved is None
                    and not _validate_native_binding_cas(path, contract, binding)
                ):
                    return supersede_route(
                        journal_contract,
                        tx_id,
                        contract=contract, binding=binding,
                        reason=(
                            "native decision CAS became stale before internal "
                            "effect application"
                        ),
                    )
                if binding["kind"] != "effect-intervention" and not already_applied:
                    _ensure_native_receipt_projection_locked(contract, path, binding)
                    _write_contract_unlocked(path, contract)
                _append_native_resume_event(path, contract, binding)
            if binding["kind"] == "effect-intervention" and resolved is None:
                resolved = resolve_effect_intervention_store(
                    path,
                    binding["target"],
                    decision=binding["decision"],
                    evidence=_native_effect_evidence(binding["decision"]),
                    actor="permission-request:codex",
                    takeover_provider=(
                        "codex"
                        if binding["decision"]
                        in {"retry_authorized", "reprobe_authorized"}
                        else ""
                    ),
                    takeover_session_id=(
                        binding["session_id"]
                        if binding["decision"]
                        in {"retry_authorized", "reprobe_authorized"}
                        else ""
                    ),
                )
            elif binding["kind"] == "proposal" and binding["decision"] == "approve":
                _finish_native_proposal(path, binding)

            if binding["kind"] != "effect-intervention":
                # All contract mutations have finished before this lock. In
                # particular _finish_native_proposal owns its own non-reentrant
                # lock and must not be called inside the receipt-only boundary.
                # Selected-task tails also protect the source contract and
                # session mapping with the same ordered decision locks.
                with native_decision_lock(path):
                    return _advance_native_receipt_chain_locked(
                        journal_contract, transaction, readers,
                        failpoint=_native_decision_failpoint if inject_failpoints else None,
                        error_type=IntentGuardianError,
                    )

            produce_native_effect_receipt(journal_contract, tx_id)
            result = advance_native_transaction_with_authority(
                journal_contract,
                tx_id,
                readers=readers,
            )
            if not result["advanced"]:
                return dict(transaction, advancement_reason=result["reason"])
            transaction = dict(transaction, stage=result["stage"])
            if inject_failpoints:
                _native_decision_failpoint("after_effect_applied")
            continue

        if stage == "effect_applied":
            with native_decision_lock(path):
                contract = load_contract(path)
                if not _native_contract_postcondition(contract, binding):
                    if not _native_base_cas_matches(contract, binding):
                        return supersede_native_transaction(
                            journal_contract,
                            tx_id,
                            reason=(
                                "native decision CAS became stale before contract "
                                "projection"
                            ),
                        )
                    _ensure_native_receipt_projection_locked(
                        contract,
                        path,
                        binding,
                        resolved_intervention=(
                            _native_effect_postcondition(path, binding)
                            if binding["kind"] == "effect-intervention"
                            else None
                        ),
                    )
                    _write_contract_unlocked(path, contract)
                return _advance_native_receipt_chain_locked(
                    journal_contract, transaction, readers,
                    failpoint=_native_decision_failpoint if inject_failpoints else None,
                    error_type=IntentGuardianError,
                )

        if stage == "contract_applied":
            with native_decision_lock(path):
                return _advance_native_receipt_chain_locked(
                    journal_contract, transaction, readers,
                    failpoint=_native_decision_failpoint if inject_failpoints else None,
                    error_type=IntentGuardianError,
                )

        raise IntentGuardianError(f"unsupported native transaction stage: {stage}")
    return transaction

def recover_native_decisions(path: Path, *, provider: str = "", session_id: str = "") -> list[dict[str, Any]]:
    recover_terminal(path)
    origin = recovery_origin(path, provider, session_id)
    recovered = recover_native_decisions(origin) if origin is not None else []
    return recovered + recover_native_decisions_independently(
        path,
        pending=pending_native_transactions,
        advance=_advance_native_transaction,
        pending_errors=(
            ApprovalInvariantError,
            InterventionError,
            NativeDecisionJournalError, OSError, UnicodeError,
        ),
        advance_errors=(
            ApprovalInvariantError,
            InterventionError,
            NativeDecisionJournalError,
            IntentGuardianError,
            OSError, UnicodeError,
        ),
        error_factory=IntentGuardianError,
    )

def _late_native_proposal_result(
    path: Path,
    *,
    decision: str,
    target: str,
) -> dict[str, Any] | None:
    if not re.fullmatch(r"[0-9a-f]{64}", target):
        return None
    contract = load_contract(path)
    matching = [
        row
        for row in contract["runtime"].get("proposal_decisions", [])
        if isinstance(row, dict)
        and row.get("proposal_digest") == target
        and row.get("verdict") == ("approve" if decision == "approve" else "reject")
    ]
    if contract.get("applied_proposal_digest") == target and matching:
        latest = matching[-1]
        authority = str(latest.get("authority") or "unknown")
        return {
            "schema": "sulde-codex-native-decision-result-v1",
            "status": (
                "already_agent_decided"
                if authority == "agent-policy"
                else "already_decided"
            ),
            "kind": "proposal",
            "decision": decision,
            "target": target,
            "decision_authority": authority,
            "receipt_id": str(latest.get("receipt_id") or ""),
            "revision": contract["revision"],
            "authority_transferred": False,
        }
    pending = str(contract["runtime"].get("pending_proposal_digest") or "")
    if pending != target:
        return {
            "schema": "sulde-codex-native-decision-result-v1",
            "status": "superseded",
            "kind": "proposal",
            "decision": decision,
            "target": target,
            "revision": contract["revision"],
            "authority_transferred": False,
        }
    return None
def execute_native_decision(
    path: Path,
    *,
    kind: str,
    decision: str,
    target: str,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    """Apply a native decision through a recoverable internal transaction."""
    if kind == "grant":
        context = native_decision_context(path, kind=kind, decision=decision,
            target=target, provider=provider, session_id=session_id)
        return execute_native_grant_decision(path, context, provider=provider,
            session_id=session_id)
    if kind not in {
        "proposal",
        "resume",
        "task-continuation",
        "effect-intervention",
    }:
        return _execute_native_decision_legacy(
            path,
            kind=kind,
            decision=decision,
            target=target,
            provider=provider,
            session_id=session_id,
        )
    if kind == "proposal":
        terminal = _late_native_proposal_result(
            path,
            decision=decision,
            target=target,
        )
        if terminal is not None:
            return terminal
    try:
        context = native_decision_context(
            path,
            kind=kind,
            decision=decision,
            target=target,
            provider=provider,
            session_id=session_id,
        )
    except IntentGuardianError as error:
        if "bounded Agent gate" in str(error):
            raise
        if (
            kind == "proposal"
            and decision in NATIVE_DECISIONS["proposal"]
            and provider.strip().lower() == "codex"
            and session_id.strip()
            and re.fullmatch(r"[0-9a-f]{64}", target)
        ):
            return {
                "schema": "sulde-codex-native-decision-result-v1",
                "status": "superseded",
                "kind": kind,
                "decision": decision,
                "target": target,
                "revision": load_contract(path)["revision"],
                "authority_transferred": False,
            }
        raise
    approval_kind = {
        "proposal": "proposal",
        "resume": "intent-confirmation",
        "task-continuation": "intent-confirmation",
        "effect-intervention": "effect-intervention",
    }[context["kind"]]
    with native_decision_lock(path):
        contract = load_contract(path)
        try:
            request = approval_request_for_binding(
                path,
                kind=approval_kind,
                target=context["target"],
                provider="codex",
                session_id=session_id,
                card=context["card"],
                workspace=context["workspace"],
                route="human",
                source=NATIVE_PERMISSION_SOURCE,
                status="asked",
            )
            if request is None:
                request = approval_request_for_binding(
                    path,
                    kind=approval_kind,
                    target=context["target"],
                    provider="codex",
                    session_id=session_id,
                    card=context["card"],
                    workspace=context["workspace"],
                    route="human",
                    source=NATIVE_PERMISSION_SOURCE,
                    status="decided",
                )
        except ApprovalInvariantError as error:
            raise IntentGuardianError(str(error)) from error
        if request is None:
            try:
                historical_request = approval_request_for_binding(
                    path,
                    kind=approval_kind,
                    target=context["target"],
                    provider="codex",
                    session_id=session_id,
                    card=context["card"],
                    workspace=context["workspace"],
                    route="human",
                    source=NATIVE_PERMISSION_SOURCE,
                )
            except ApprovalInvariantError:
                historical_request = None
            if (
                historical_request is not None
                and approval_request_phase(historical_request) == "expired"
            ):
                return {
                    "schema": "sulde-codex-native-decision-result-v1",
                    "status": "approval_expired",
                    "kind": kind,
                    "decision": decision,
                    "target": context["target"],
                    "request_id": historical_request["request_id"],
                    "revision": contract["revision"],
                    "requires_fresh_permission_request": True,
                    "authority_transferred": False,
                }
            return {
                "schema": "sulde-codex-native-decision-result-v1",
                "status": "awaiting_human",
                "kind": kind,
                "decision": decision,
                "target": context["target"],
                "revision": contract["revision"],
                "requires_fresh_permission_request": True,
                "authority_transferred": False,
            }
        request_phase = approval_request_phase(request)
        if request_phase == "expired":
            return {
                "schema": "sulde-codex-native-decision-result-v1",
                "status": "approval_expired",
                "kind": kind,
                "decision": decision,
                "target": context["target"],
                "request_id": request["request_id"],
                "revision": contract["revision"],
                "requires_fresh_permission_request": True,
                "authority_transferred": False,
            }
        binding = _native_transaction_binding(
            path,
            context,
            request_id=str(request["request_id"]),
            approval_kind=approval_kind,
            session_id=session_id,
        )
        if not _validate_native_binding_cas(path, contract, binding):
            raise IntentGuardianError("native decision changed before execution")
        if request.get("status") == "asked":
            try:
                if request.get("typed") is True:
                    decide_typed_approval(
                        path,
                        request_id=request["request_id"],
                        receipt_id=binding["seal_id"],
                        outcome="allow",
                        snapshot=request["snapshot"],
                        current_snapshot=request["snapshot"],
                        provider="codex",
                        session_id=session_id,
                        decision_owner="human",
                        actor="permission-request:codex",
                    )
                else:
                    decide_approval(
                        path,
                        kind=approval_kind,
                        target=context["target"],
                        outcome="approved",
                        provider="codex",
                        session_id=session_id,
                        actor="permission-request:codex",
                        card=context["card"],
                        workspace=context["workspace"],
                        route="human",
                        source=NATIVE_PERMISSION_SOURCE,
                    )
            except ApprovalInvariantError as error:
                raise IntentGuardianError(str(error)) from error
        if not _native_approval_was_decided(path, binding):
            raise IntentGuardianError(
                "native decision request lacks the exact durable human outcome"
            )
        try:
            transaction = prepare_native_transaction(
                path.expanduser().resolve(), binding
            )
        except NativeDecisionJournalError as error:
            raise IntentGuardianError(str(error)) from error
        _native_decision_failpoint("after_prepared")
    transaction = _advance_native_transaction(
        path,
        transaction,
        inject_failpoints=True,
    )
    if transaction.get("stage") != "committed":
        raise IntentGuardianError(
            f"native decision transaction stopped at {transaction.get('stage')}: "
            f"{transaction.get('advancement_reason') or 'authority pending'}"
        )
    contract = load_contract(path)
    receipt = _native_receipt_for_request_locked(contract, binding)
    return {
        "schema": "sulde-codex-native-decision-result-v1",
        "status": (
            "applied"
            if (
                kind == "proposal" and decision == "approve"
            ) or kind == "task-continuation"
            else "recorded"
        ),
        "kind": kind,
        "decision": decision,
        "request_id": binding["request_id"],
        "receipt_id": str((receipt or {}).get("receipt_id") or ""),
        "revision": contract["revision"],
        "transaction_id": transaction["transaction_id"],
    }

def _execute_native_decision_legacy(
    path: Path,
    *,
    kind: str,
    decision: str,
    target: str,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    """Consume one live Codex PermissionRequest and apply its exact transition."""
    context = native_decision_context(
        path,
        kind=kind,
        decision=decision,
        target=target,
        provider=provider,
        session_id=session_id,
    )
    approval_kind = {
        "proposal": "proposal",
        "intent": "intent-confirmation",
        "resume": "intent-confirmation",
        "observation-export": "observation-export",
        "workspace-handoff": "intent-confirmation",
        "effect-intervention": "effect-intervention",
    }[context["kind"]]
    try:
        request = approval_request_for_binding(
            path,
            kind=approval_kind,
            target=context["target"],
            provider="codex",
            session_id=session_id,
            card=context["card"],
            workspace=context["workspace"],
            route="human",
            source=NATIVE_PERMISSION_SOURCE,
            status="asked",
        )
        if request is None:
            raise ApprovalInvariantError(
                "native decision has no exact open approval request"
            )
        if request.get("typed") is True:
            decide_typed_approval(
                path,
                request_id=request["request_id"],
                receipt_id=request["request_identity"],
                outcome="allow",
                snapshot=request["snapshot"],
                current_snapshot=request["snapshot"],
                provider="codex",
                session_id=session_id,
                decision_owner="human",
                actor="permission-request:codex",
            )
            request = approval_request_by_id(path, request["request_id"])
        else:
            request = decide_approval(
                path,
                kind=approval_kind,
                target=context["target"],
                outcome="approved",
                provider="codex",
                session_id=session_id,
                actor="permission-request:codex",
                card=context["card"],
                workspace=context["workspace"],
                route="human",
                source=NATIVE_PERMISSION_SOURCE,
            )
    except (ApprovalInvariantError, OSError, UnicodeError) as error:
        raise IntentGuardianError(
            "native decision has no paired live Codex PermissionRequest: " + str(error)
        ) from error

    request_id = str(request["request_id"])
    actor = "permission-request:codex"
    current = native_decision_context(
        path,
        kind=kind,
        decision=decision,
        target=context["target"],
        provider=provider,
        session_id=session_id,
    )
    if current["card"] != context["card"] or current["target"] != context["target"]:
        raise IntentGuardianError("native decision card changed before execution")
    with contract_lock(path):
        contract = load_contract(path)
        if (
            contract["intent_id"] != context["intent_id"]
            or contract["revision"] != context["intent_revision"]
            or contract["workspace_root"] != context["workspace"]
        ):
            raise IntentGuardianError("native decision intent changed before execution")
        if context["kind"] == "proposal":
            _validate_proposal_for_approval(path, contract, context["target"])
        elif (
            context["kind"] == "intent"
            and context["card"]["决策内容"]
            != _intent_confirmation_card(contract)
        ):
            raise IntentGuardianError("native decision intent card changed before execution")
        elif context["kind"] == "resume":
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
                != context["target"]
                or {
                    "本次选择": context["choice"],
                    "决策内容": _resume_decision_card(
                        contract,
                        provider="codex",
                        session_id=session_id,
                    ),
                    "宿主": "codex",
                    "会话内确认": True,
                }
                != context["card"]
            ):
                raise IntentGuardianError(
                    "native resume decision changed before execution"
                )

        if context["kind"] == "proposal" and context["decision"] == "approve":
            receipt = _approve_proposal_locked(
                contract,
                context["target"],
                actor=actor,
                provider="codex",
                session_id=session_id,
                channel="codex-native-permission",
                observation_source="live_host_hook",
                approval_request_id=request_id,
            )
            _record_proposal_decision_locked(
                contract,
                digest=context["target"],
                authority="human",
                verdict="approve",
                rationale="用户在当前 Codex PermissionRequest 卡片中批准方案",
                evidence=["live PermissionRequest", "exact readable description"],
                provider="codex",
                session_id=session_id,
                receipt_id=receipt["receipt_id"],
            )
        else:
            action = context["action"]
            receipt_decision = (
                context["decision"]
                if context["kind"] == "effect-intervention"
                else ""
            )
            evidence = {
                "retry_authorized": "当前 Codex 会话原生批准：同一外部效果精确重试一次",
                "reprobe_authorized": "当前 Codex 会话原生批准：只重新检查同一外部效果",
                "abort": "当前 Codex 会话原生批准：终止同一外部效果且不重试",
            }.get(receipt_decision, "")
            receipt = _record_approval_receipt_locked(
                contract,
                action=action,
                target=context["target"],
                actor=actor,
                provider="codex",
                session_id=session_id,
                channel="codex-native-permission",
                observation_source="live_host_hook",
                decision=receipt_decision,
                evidence_sha256=(
                    hashlib.sha256(evidence.encode("utf-8")).hexdigest()
                    if evidence
                    else ""
                ),
                approval_request_id=request_id,
            )
            if context["kind"] == "proposal":
                _record_proposal_decision_locked(
                    contract,
                    digest=context["target"],
                    authority="human",
                    verdict="reject",
                    rationale="用户在当前 Codex PermissionRequest 卡片中拒绝方案",
                    evidence=["live PermissionRequest", "exact readable description"],
                    provider="codex",
                    session_id=session_id,
                    receipt_id=receipt["receipt_id"],
                )
                contract["runtime"]["approved_proposal_digests"] = [
                    item
                    for item in contract["runtime"]["approved_proposal_digests"]
                    if item != context["target"]
                ]
                contract["runtime"]["pending_proposal_digest"] = ""
                _consume_approval_receipt_locked(
                    receipt, consumer="native-permission-control-executor"
                )
            elif context["kind"] == "intent":
                if context["decision"] == "confirm":
                    contract["confirmation"]["required"] = False
                    contract["confirmation"]["reason"] = ""
                    contract["confirmed_by"] = "codex-native-permission"
                    if contract["mode"] == "shadow":
                        contract["mode"] = "enforce"
                else:
                    contract["confirmed_by"] = "codex-native-intent-rejection"
                    _pause_global_locked(
                        contract,
                        reason="用户通过当前 Codex PermissionRequest 拒绝当前意图",
                        pause_class="semantic",
                        requires_revision=True,
                    )
                _consume_approval_receipt_locked(
                    receipt, consumer="native-permission-control-executor"
                )
            elif context["kind"] == "resume":
                _resume_contract_locked(
                    contract,
                    "用户在当前 Codex PermissionRequest 中恢复任务",
                    actor=actor,
                    provider="codex",
                    session_id=session_id,
                )
                _consume_approval_receipt_locked(
                    receipt, consumer="native-permission-control-executor"
                )
            elif context["kind"] == "workspace-handoff":
                _consume_approval_receipt_locked(
                    receipt, consumer="native-permission-control-executor"
                )
            elif context["kind"] == "observation-export":
                try:
                    decide_current_export(
                        kb_home(),
                        path,
                        outcome=(
                            "approved"
                            if context["decision"] == "approve"
                            else "rejected"
                        ),
                        provider="codex",
                        session_id=session_id,
                        actor=actor,
                        receipt_id=receipt["receipt_id"],
                    )
                except ObservationPrivacyError as error:
                    raise IntentGuardianError(
                        f"cannot persist observation export decision: {error}"
                    ) from error
                if context["decision"] == "reject":
                    _consume_approval_receipt_locked(
                        receipt, consumer="native-permission-control-executor"
                    )
            else:
                _resolve_effect_intervention_locked(
                    contract,
                    path,
                    context["target"],
                    decision=context["decision"],
                    evidence=evidence,
                    actor=actor,
                    takeover_provider="codex",
                    takeover_session_id=session_id,
                )
                _consume_approval_receipt_locked(
                    receipt, consumer="native-permission-control-executor"
                )

        contract["runtime"]["host_observations"].append(
            {
                "event": "permission_request",
                "provider": "codex",
                "session_id": session_id,
                "source": "live_host_hook",
                "status": "control_recorded",
                "control_action": context["action"],
                "control_target": context["target"],
                "request_id": request_id,
                "receipt_id": receipt["receipt_id"],
                "at": now_iso(),
            }
        )
        contract["runtime"]["host_observations"] = contract["runtime"][
            "host_observations"
        ][-100:]
        _write_contract_unlocked(path, contract)

    if context["kind"] in {
        "proposal",
        "intent",
        "resume",
        "observation-export",
        "workspace-handoff",
    }:
        try:
            cancel_open_approval_requests(
                path,
                kinds={approval_kind},
                actor="native-permission-decision-recorded",
            )
        except (ApprovalInvariantError, OSError, UnicodeError) as error:
            raise IntentGuardianError(
                "native decision was recorded but stale questions could not be closed: "
                + str(error)
            ) from error
    _append_control_event(
        path,
        "native-decision",
        actor=actor,
        detail=f"{context['kind']}:{context['decision']}:{context['target']}",
        receipt_id=receipt["receipt_id"],
    )
    if context["kind"] == "workspace-handoff":
        handoff = apply_workspace_handoff(
            kb_home(),
            path,
            Path(context["target"]),
            provider="codex",
            session_id=session_id,
            receipt_id=receipt["receipt_id"],
        )
        return {
            "schema": "sulde-codex-native-decision-result-v1",
            "status": "applied",
            "kind": context["kind"],
            "decision": context["decision"],
            "request_id": request_id,
            "receipt_id": receipt["receipt_id"],
            "authority_transferred": False,
            "handoff": handoff,
        }
    if context["kind"] == "proposal" and context["decision"] == "approve":
        proposal_path = _proposal_path_for_digest(path, context["target"])
        applied = apply_revision_proposal(
            path,
            proposal_path,
            actor="agent-after-codex-native-permission",
        )
        acknowledge_continuation(
            path,
            proposal_digest_value=context["target"],
            provider="codex",
            session_id=session_id,
        )
        return {
            "schema": "sulde-codex-native-decision-result-v1",
            "status": "applied",
            "kind": context["kind"],
            "decision": context["decision"],
            "request_id": request_id,
            "receipt_id": receipt["receipt_id"],
            "revision": applied["revision"],
        }
    return {
        "schema": "sulde-codex-native-decision-result-v1",
        "status": "recorded",
        "kind": context["kind"],
        "decision": context["decision"],
        "request_id": request_id,
        "receipt_id": receipt["receipt_id"],
    }

def approve_proposal(
    path: Path,
    digest: str,
    *,
    actor: str = "human",
    provider: str = "unknown",
    session_id: str = "",
    channel: str = "cli",
    observation_source: str = "human_cli",
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise IntentGuardianError("proposal digest must be 64 lowercase hex chars")
    initial = load_contract(path)
    try:
        review = proposal_review_for_digest(path, digest)
        ask_approval(
            path,
            intent_id=initial["intent_id"],
            intent_revision=initial["revision"],
            kind="proposal",
            target=digest,
            source="internal_approval_api",
            card=review["decision_card"],
            workspace=initial["workspace_root"],
            route="human",
            reuse_decided=True,
        )
    except (ApprovalInvariantError, OSError, UnicodeError) as error:
        raise IntentGuardianError(
            f"cannot persist proposal approval question: {error}"
        ) from error
    with contract_lock(path):
        contract = load_contract(path)
        _validate_proposal_for_approval(path, contract, digest)
        receipt = _approve_proposal_locked(
            contract,
            digest,
            actor=actor,
            provider=provider,
            session_id=session_id,
            channel=channel,
            observation_source=observation_source,
        )
        try:
            decide_approval(
                path,
                kind="proposal",
                target=digest,
                outcome="approved",
                provider=provider,
                session_id=session_id,
                actor=actor,
                receipt_id=receipt["receipt_id"],
            )
        except (ApprovalInvariantError, OSError, UnicodeError) as error:
            raise IntentGuardianError(
                f"approval decision has no paired question: {error}"
            ) from error
        _write_contract_unlocked(path, contract)
    _append_control_event(
        path,
        "approve-proposal",
        actor=actor,
        detail=digest,
        receipt_id=receipt["receipt_id"],
    )
    return receipt

def _approve_proposal_locked(
    contract: dict[str, Any],
    digest: str,
    *,
    actor: str,
    provider: str,
    session_id: str,
    channel: str,
    observation_source: str,
    approval_request_id: str = "",
) -> dict[str, Any]:
    approvals = contract["runtime"]["approved_proposal_digests"]
    if digest not in approvals:
        approvals.append(digest)
    receipt = _existing_approval_receipt_locked(
        contract,
        action="approve-proposal",
        target=digest,
        actor=actor,
        provider=provider,
        session_id=session_id,
        channel=channel,
        observation_source=observation_source,
        approval_request_id=approval_request_id,
    ) or _record_approval_receipt_locked(
        contract,
        action="approve-proposal",
        target=digest,
        actor=actor,
        provider=provider,
        session_id=session_id,
        channel=channel,
        observation_source=observation_source,
        approval_request_id=approval_request_id,
    )
    contract["last_proposal_approval"] = {
        "digest": digest,
        "by": actor,
        "at": receipt["recorded_at"],
        "receipt_id": receipt["receipt_id"],
    }
    return receipt

def _receipt_has_live_prompt_evidence(
    contract: dict[str, Any],
    receipt: dict[str, Any],
) -> bool:
    if (
        receipt["channel"] != "user-prompt"
        or receipt["observation_source"] != "live_host_hook"
        or receipt["actor"] != f"user-prompt:{receipt['provider']}"
    ):
        return False
    return any(
        row["event"] == "user_prompt_submit"
        and row["provider"] == receipt["provider"]
        and row["session_id"] == receipt["session_id"]
        and row["source"] == "live_host_hook"
        and row["status"] == "control_recorded"
        and row["control_action"] == receipt["action"]
        and row["control_target"] == receipt["target"]
        and row["receipt_id"] == receipt["receipt_id"]
        for row in contract["runtime"]["host_observations"]
    )

def _receipt_has_native_permission_evidence(
    path: Path,
    receipt: dict[str, Any],
) -> bool:
    """Prove that Codex surfaced, and the user accepted, one native request.

    ``PermissionRequest`` records the question immediately before Codex shows
    its approval UI.  The protected ``native-decision`` command can run only
    after that UI allows it; it then pairs the same request id here.  Merely
    invoking the CLI without the host event leaves no matching question.
    """
    request_id = str(receipt.get("approval_request_id") or "")
    if (
        receipt.get("channel") != "codex-native-permission"
        or receipt.get("observation_source") != "live_host_hook"
        or receipt.get("actor") != "permission-request:codex"
        or not re.fullmatch(r"apr-[0-9a-f]{24}", request_id)
    ):
        return False
    try:
        request = load_approval_projection(path)["requests"].get(request_id)
    except (ApprovalInvariantError, OSError, UnicodeError):
        return False
    return bool(
        isinstance(request, dict)
        and request.get("status") == "decided"
        and request.get("outcome")
        == ("allow" if request.get("typed") is True else "approved")
        and request.get("kind") == "proposal"
        and request.get("target_sha256")
        == hashlib.sha256(
            str(receipt.get("target") or "").encode("utf-8", errors="replace")
        ).hexdigest()
        and request.get("source") == "codex_permission_request"
        and request.get("provider") == "codex"
        and request.get("decision_provider") == "codex"
        and request.get("decision_actor") == "permission-request:codex"
    )
def _receipt_has_agent_policy_evidence(
    contract: dict[str, Any],
    receipt: dict[str, Any],
    proposal: dict[str, Any],
    path: Path | None = None,
) -> bool:
    if (
        receipt["channel"] != "agent-policy"
        or receipt["observation_source"] != "deterministic_agent_gate"
        or receipt["actor"] != f"agent-decision:{receipt['provider']}"
        or proposal.get("decision", {}).get("selected_route") != "agent"
    ):
        return False
    eligible, reasons = agent_decision_eligibility(contract, proposal, open_events_blocking=False, contract_path=path)
    if not eligible or reasons:
        return False
    return any(
        row["proposal_digest"] == receipt["target"]
        and row["authority"] == "agent-policy"
        and row["verdict"] == "approve"
        and row["receipt_id"] == receipt["receipt_id"]
        and bool(row["rationale"].strip())
        and bool(row["evidence"])
        for row in contract["runtime"]["proposal_decisions"]
    )

def decide_proposal_as_agent(
    path: Path,
    digest: str,
    *,
    rationale: str,
    evidence: Iterable[str],
    provider: str,
    session_id: str = "",
) -> dict[str, Any]:
    """Approve one eligible low-risk proposal under explicit Agent authority."""
    provider = provider.strip().lower()
    if provider not in {"claude", "codex"}:
        raise IntentGuardianError("Agent decision provider must be claude or codex")
    session_is_string = type(session_id) is str
    session_id = session_id.strip() if session_is_string else ""
    if provider == "codex" and (
        not session_is_string or not 0 < len(session_id) <= 200
    ):
        raise IntentGuardianError("Codex Agent decision requires a non-empty session_id up to 200 chars")
    observed_thread = os.environ.get("CODEX_THREAD_ID", "").strip() if provider == "codex" else ""
    if observed_thread and observed_thread != session_id:
        raise IntentGuardianError("Codex Agent decision session_id does not match CODEX_THREAD_ID")
    if os.environ.get("SULDE_GUARDIAN_STREAM_OWNER") == "1":
        raise IntentGuardianError(
            "managed L3 child cannot create Agent decision authority; the parent task must "
            "already be approved"
        )
    observed_provider = (
        os.environ.get("SULDE_HOST_PROVIDER")
        or os.environ.get("SULDE_AGENT_PROVIDER")
        or ""
    ).strip().lower()
    if observed_provider and observed_provider != provider:
        raise IntentGuardianError(
            f"Agent decision provider mismatch: observed {observed_provider}, got {provider}"
        )
    rationale = rationale.strip()
    evidence_items = [item.strip() for item in evidence if item.strip()]
    if not rationale:
        raise IntentGuardianError("Agent decision requires a concrete rationale")
    if not evidence_items:
        raise IntentGuardianError("Agent decision requires at least one evidence item")
    with contract_lock(path):
        contract = load_contract(path)
        proposal_path = _validate_proposal_for_approval(path, contract, digest)
        proposal = load_contract(proposal_path)
        blocker = proposal_open_event_blocker(path, contract, proposal, provider, session_id)
        eligible, reasons = agent_decision_eligibility(
            contract,
            proposal,
            open_events_blocking=blocker is not None,
            contract_path=path,
        )
        if proposal.get("decision", {}).get("selected_route") != "agent":
            raise IntentGuardianError("proposal is routed to human decision")
        if not eligible:
            raise IntentGuardianError(
                "proposal is not eligible for Agent decision: " + "; ".join(reasons)
            )
        actor = f"agent-decision:{provider}"
        receipt = _approve_proposal_locked(
            contract,
            digest,
            actor=actor,
            provider=provider,
            session_id=session_id,
            channel="agent-policy",
            observation_source="deterministic_agent_gate",
        )
        decision = _record_proposal_decision_locked(
            contract,
            digest=digest,
            authority="agent-policy",
            verdict="approve",
            rationale=rationale,
            evidence=evidence_items,
            provider=provider,
            session_id=session_id,
            receipt_id=receipt["receipt_id"],
        )
        _write_contract_unlocked(path, contract)
    _append_control_event(
        path,
        "agent-decide-proposal",
        actor=actor,
        detail=digest,
        receipt_id=receipt["receipt_id"],
    )
    return {
        "decision": decision,
        "receipt": receipt,
        "proposal_path": str(proposal_path),
    }

def _native_proposal_requests(
    path: Path,
    digest: str,
) -> list[dict[str, Any]]:
    target_sha256 = hashlib.sha256(
        digest.encode("utf-8", errors="replace")
    ).hexdigest()
    projection = load_approval_projection(path)
    return sorted(
        [
            dict(row)
            for row in projection["requests"].values()
            if isinstance(row, dict)
            and row.get("kind") == "proposal"
            and row.get("target_sha256") == target_sha256
            and row.get("source") == NATIVE_PERMISSION_SOURCE
            and row.get("route") == "human"
        ],
        key=lambda row: (str(row.get("asked_at") or ""), row["request_id"]),
    )

def reconcile_obsolete_approval_requests(path: Path) -> int:
    """Cancel live questions whose authoritative target is already gone.

    Approval rows are snapshotted before the contract/effect ledgers so a
    concurrently created, valid request is never cancelled from an older
    authority view. A concurrent human decision wins cleanly: exact
    cancellation then observes the decided row and leaves it untouched.
    Expired rows remain immutable history and are already excluded from the
    open count.
    """
    try:
        approval_projection = load_approval_projection(path)
        contract = load_contract(path)
        effect_projection = load_intervention_projection(path)
    except (
        ApprovalInvariantError,
        InterventionError,
        OSError,
        UnicodeError,
    ) as error:
        raise IntentGuardianError(
            f"cannot reconcile obsolete approval questions: {error}"
        ) from error

    pending_digest = str(
        contract.get("runtime", {}).get("pending_proposal_digest") or ""
    )
    valid_proposal_target = (
        hashlib.sha256(pending_digest.encode("utf-8")).hexdigest()
        if pending_digest
        else ""
    )
    valid_effect_targets = {
        hashlib.sha256(str(intervention_id).encode("utf-8")).hexdigest()
        for intervention_id, row in effect_projection["interventions"].items()
        if isinstance(row, dict)
        and row.get("status") in {"open", "acknowledged"}
    }
    stale_ids: list[str] = []
    for row in approval_projection["requests"].values():
        if (
            not isinstance(row, dict)
            or row.get("status") != "asked"
            or approval_request_phase(row) == "expired"
        ):
            continue
        kind = str(row.get("kind") or "")
        target_sha256 = str(row.get("target_sha256") or "")
        if kind == "proposal" and target_sha256 != valid_proposal_target:
            stale_ids.append(str(row["request_id"]))
        elif (
            kind == "effect-intervention"
            and target_sha256 not in valid_effect_targets
        ):
            stale_ids.append(str(row["request_id"]))

    cancelled = 0
    for request_id in stale_ids:
        try:
            result = cancel_approval_request(
                path,
                request_id,
                actor="authoritative-target-settled",
            )
        except ApprovalInvariantError:
            # A concurrent native decision may have won after our read-only
            # snapshot. Never overwrite or reinterpret that human outcome.
            continue
        if not result.get("idempotent"):
            cancelled += 1
    return cancelled

def reassess_unattended_proposal(
    path: Path,
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    """Lazily reassess one timed-out native proposal at a safe host boundary.

    This function never clicks or synthesizes a human approval.  Current Codex
    hooks expose presentation of the PermissionRequest but no signed final
    Deny/Timeout callback, so elapsed time alone can only produce liveness
    status.  Deterministically safe work is routed to Agent policy before a
    human prompt is presented; once presented, the durable question remains
    human-owned.
    """
    selected_provider = provider.strip().lower()
    clean_session = session_id.strip()
    if selected_provider != "codex" or not clean_session:
        return {"status": "not_applicable", "authority_transferred": False}

    snapshot = load_contract(path)
    pending_digest = str(snapshot["runtime"].get("pending_proposal_digest") or "")
    if not pending_digest:
        return {
            "status": (
                "already_applied"
                if snapshot.get("applied_proposal_digest")
                else "none"
            ),
            "authority_transferred": False,
        }

    requests = _native_proposal_requests(path, pending_digest)
    asked = [row for row in requests if row.get("status") == "asked"]
    if not asked:
        return {"status": "awaiting_human", "authority_transferred": False}
    phases = [(row, approval_request_phase(row)) for row in asked]
    due = [row for row, phase in phases if phase == "reassess_due"]
    if not due:
        return {
            "status": (
                "expired"
                if phases and all(phase == "expired" for _row, phase in phases)
                else "grace_period"
            ),
            "authority_transferred": False,
        }

    selected_request_id = str(due[0]["request_id"])
    proposal_path = _proposal_path_for_digest(path, pending_digest)
    try:
        with contract_lock(path):
            contract = load_contract(path)
            current_requests = _native_proposal_requests(path, pending_digest)
            current_request = next(
                (
                    row
                    for row in current_requests
                    if row.get("request_id") == selected_request_id
                    and row.get("status") == "asked"
                ),
                None,
            )
            if current_request is None:
                return {
                    "status": "decision_raced",
                    "authority_transferred": False,
                }
            phase = approval_request_phase(current_request)
            try:
                _validate_proposal_for_approval(path, contract, pending_digest)
                world_current = True
            except IntentGuardianError:
                world_current = False
            proposal = load_contract(proposal_path)
            eligible, reasons = agent_decision_eligibility(contract, proposal, contract_path=path)
            policy = normalize_unattended_policy(
                proposal.get("decision", {}).get("unattended_policy"),
                default=UNATTENDED_WAIT,
            )
            disposition = timeout_disposition(
                phase=phase,
                kind="proposal",
                unattended_policy=policy,
                eligible=eligible,
                world_current=world_current,
                # The current Codex Hook contract has no verifiable final
                # timeout/deny callback.  Never infer absence from silence.
                host_timeout_observed=False,
            )
    except (ApprovalInvariantError, ApprovalTimeoutPolicyError) as error:
        raise IntentGuardianError(
            f"cannot reassess unattended proposal: {error}"
        ) from error
    if disposition == "cancel_and_rerender":
        try:
            cancel_approval_request(
                path,
                selected_request_id,
                actor="unattended-world-drift",
            )
        except ApprovalInvariantError:
            # A real human outcome racing this liveness check is authoritative;
            # never overwrite it with a timer-driven cancellation.
            return {
                "status": "decision_raced",
                "authority_transferred": False,
                "proposal_digest": pending_digest,
                "request_id": selected_request_id,
                "agent_ineligible_reasons": reasons,
            }
        with contract_lock(path):
            current = load_contract(path)
            if current["runtime"].get("pending_proposal_digest") == pending_digest:
                try:
                    _validate_proposal_for_approval(path, current, pending_digest)
                except IntentGuardianError:
                    current["runtime"]["pending_proposal_digest"] = ""
                    current["runtime"]["approved_proposal_digests"] = [
                        digest
                        for digest in current["runtime"].get(
                            "approved_proposal_digests", []
                        )
                        if digest != pending_digest
                    ]
                    _write_contract_unlocked(path, current)
    return {
        "status": disposition,
        "authority_transferred": False,
        "proposal_digest": pending_digest,
        "request_id": selected_request_id,
        "agent_ineligible_reasons": reasons,
    }

def _authorize_bootstrap_retries_for_applied_proposal(
    path: Path,
    *,
    previous: dict[str, Any],
    applied: dict[str, Any],
    receipt: dict[str, Any],
    proposal_digest_value: str,
) -> list[dict[str, str]]:
    """Bridge one sealed install through an already-loaded older Hook.

    A long-lived Codex session may still execute a cached PreToolUse runtime
    that predates registered compensation.  That runtime already understands
    the append-only ``retry_authorized`` event.  When an applied proposal has
    one exact, one-shot installation grant, convert only its matching historic
    pending install into that older representation.  The predecessor remains
    unknown; the replacement install must still pass its independent verifier.
    """
    provider = str(receipt.get("provider") or "").strip().lower()
    session_id = str(receipt.get("session_id") or "").strip()
    if provider != "codex" or not session_id:
        return []
    pending_rows = previous.get("runtime", {}).get("pending_verifications", [])
    if not isinstance(pending_rows, list) or not pending_rows:
        return []
    try:
        projection = load_intervention_projection(path)
    except (InterventionError, OSError, UnicodeError) as error:
        raise IntentGuardianError(
            f"cannot inspect bootstrap retry predecessors: {error}"
        ) from error

    authorized: list[dict[str, str]] = []
    for grant in applied.get("continuation", {}).get("grants", []):
        if (
            not isinstance(grant, dict)
            or grant.get("profile_id") not in COMPENSATION_CONTINUATION_PROFILES
            or grant.get("schema") != CONTINUATION_GRANT_SCHEMA
            or grant.get("effect") != "external_write"
            or grant.get("target") != "[host-local:codex-plugin]"
            or grant.get("verification_kind") != "content"
            or int(grant.get("max_uses") or 0) != 1
        ):
            continue
        new_binding = grant.get("binding")
        if not isinstance(new_binding, dict):
            continue
        candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for row in pending_rows:
            if not isinstance(row, dict):
                continue
            old_grant = row.get("continuation_grant")
            if not isinstance(old_grant, dict):
                continue
            old_binding = old_grant.get("binding")
            fingerprint = str(row.get("fingerprint") or "").lower()
            attempt_id = str(row.get("attempt_id") or "")
            if (
                row.get("outcome_unknown") is not True
                or row.get("provider") != provider
                or row.get("session_id") != session_id
                or row.get("target") != grant["target"]
                or row.get("continuation_profile_id") != grant["profile_id"]
                or row.get("continuation_grant_id") != old_grant.get("grant_id")
                or old_grant.get("schema") != CONTINUATION_GRANT_SCHEMA
                or old_grant.get("profile_id") != grant["profile_id"]
                or old_grant.get("effect") != grant["effect"]
                or old_grant.get("capability") != grant["capability"]
                or old_grant.get("target") != grant["target"]
                or old_grant.get("verification_kind") != grant["verification_kind"]
                or old_grant.get("grant_id") == grant.get("grant_id")
                or not isinstance(old_binding, dict)
                or any(
                    old_binding.get(field) != new_binding.get(field)
                    for field in BOOTSTRAP_RETRY_BINDING_FIELDS
                )
                or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
                or not attempt_id
            ):
                continue
            try:
                old_verification = _continuation_candidate_from_grant(old_grant)[
                    "verification_sha256"
                ]
            except (KeyError, TypeError, ValueError):
                continue
            if row.get("verification_sha256") != old_verification:
                continue
            attempt = projection.get("attempts", {}).get(attempt_id)
            if (
                not isinstance(attempt, dict)
                or attempt.get("state") != "unknown"
                or attempt.get("fingerprint") != fingerprint
                or attempt.get("provider") != provider
                or attempt.get("session_id") != session_id
                or attempt.get("target") != grant["target"]
                or attempt.get("capability") != grant["capability"]
                or attempt.get("effect") != grant["effect"]
            ):
                continue
            interventions = [
                item
                for item in projection.get("interventions", {}).values()
                if isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
                and item.get("status") in {"open", "acknowledged"}
            ]
            if len(interventions) != 1:
                continue
            candidates.append((row, old_grant, interventions[0]))
        if len(candidates) != 1:
            continue
        row, _old_grant, intervention = candidates[0]
        evidence = json.dumps(
            {
                "schema": "sulde-system-continuation-retry-v1",
                "proposal_digest": proposal_digest_value,
                "grant_id": grant["grant_id"],
                "profile_id": grant["profile_id"],
                "predecessor_attempt_id": row["attempt_id"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            result = authorize_effect_system_retry(
                path,
                str(intervention["intervention_id"]),
                fingerprint=str(row["fingerprint"]),
                provider=provider,
                session_id=session_id,
                target=str(grant["target"]),
                evidence=evidence,
            )
        except (InterventionError, OSError, UnicodeError) as error:
            raise IntentGuardianError(
                f"applied proposal could not register its sealed bootstrap retry: {error}"
            ) from error
        authorized.append(
            {
                "intervention_id": str(result["intervention_id"]),
                "attempt_id": str(row["attempt_id"]),
                "fingerprint": str(row["fingerprint"]),
                "grant_id": str(grant["grant_id"]),
            }
        )
    return authorized

def apply_revision_proposal(
    path: Path,
    proposal_path: Path,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    proposal = load_contract(proposal_path)
    digest = proposal_digest(proposal)
    if proposal.get("proposal_digest") != digest:
        raise IntentGuardianError("proposal digest field does not match proposal content")
    with contract_lock(path):
        current = load_contract(path)
        link = proposal.get("proposal_for")
        if not isinstance(link, dict):
            raise IntentGuardianError("proposal is missing proposal_for provenance")
        if Path(str(link.get("contract_path") or "")).expanduser().resolve() != path.expanduser().resolve():
            raise IntentGuardianError("proposal targets a different intent contract")
        if int(link.get("base_revision", 0)) != current["revision"]:
            raise IntentGuardianError("proposal base revision is stale")
        if str(link.get("base_policy_digest") or "") != policy_digest(current):
            raise IntentGuardianError("proposal base policy has changed")
        validate_material_world(current, proposal)
        if current["runtime"]["pending_proposal_digest"] != digest:
            raise IntentGuardianError("proposal is no longer the current pending proposal")
        if digest not in current["runtime"]["approved_proposal_digests"]:
            raise IntentGuardianError(
                "proposal has not been approved by an authorized decision"
            )
        receipt = next(
            (
                row
                for row in reversed(current["runtime"]["approval_receipts"])
                if row["action"] == "approve-proposal"
                and row["target"] == digest
                and not row["consumed_at"]
                and row["intent_revision"] == current["revision"]
                and Path(row["workspace_root"]).resolve()
                == Path(current["workspace_root"]).resolve()
            ),
            None,
        )
        if receipt is None:
            raise IntentGuardianError(
                "proposal approval has no unconsumed decision receipt"
            )
        require_proposal_open_event_clear(path, current, proposal, receipt)
        human_authority = _receipt_has_live_prompt_evidence(
            current, receipt
        ) or _receipt_has_native_permission_evidence(path, receipt)
        agent_authority = _receipt_has_agent_policy_evidence(current, receipt, proposal, path)
        if not human_authority and not agent_authority:
            raise IntentGuardianError(
                "proposal approval lacks either a live human decision receipt or an eligible "
                "Agent policy decision; copied CLI commands and synthetic smoke cannot grant "
                "authority"
            )
        decision_authority = "human" if human_authority else "agent-policy"
        applied_actor = actor or (
            "agent-after-human-approval"
            if human_authority
            else "agent-after-agent-policy-decision"
        )
        _consume_approval_receipt_locked(receipt, consumer=applied_actor)
        applied = validate_contract(proposal)
        carried_runtime = json.loads(json.dumps(current["runtime"]))
        carried_runtime.update(
            {
                "active_skills": [],
                "active_skill_frames": [],
                "corrections": [],
                "authorized_events": [],
                "continuation_uses": [],
                "approved_proposal_digests": [],
                "pending_proposal_digest": "",
                "task_lanes": [
                    row
                    for row in carried_runtime.get("task_lanes", [])
                    if not isinstance(row, dict) or row.get("state") != "paused"
                ],
                "pause_scope": "",
                "pause_reason": "",
                "pause_origin_reason": "",
                "pause_class": "",
                "pause_event_fingerprint": "",
                "pause_requires_revision": False,
                "pause_revision": 0,
            }
        )
        applied["runtime"] = carried_runtime
        receipt_provider = str(receipt.get("provider") or "unknown")
        receipt_session = str(receipt.get("session_id") or "")
        if receipt_session:
            _upsert_task_lane_locked(
                applied,
                provider=receipt_provider,
                session_id=receipt_session,
                state="bound",
                source="approved_revision",
                continuation_eligible=True,
            )
        _invalidate_stale_approval_receipts_locked(applied)
        applied["approved_event_fingerprints"] = []
        applied["status"] = "active"
        applied["confirmed_by"] = (
            "human-readable-proposal-approval"
            if human_authority
            else "agent-policy-decision"
        )
        applied["confirmation"]["required"] = False
        applied["confirmation"]["reason"] = ""
        applied["applied_proposal_digest"] = digest
        applied["applied_approval_receipt_id"] = receipt["receipt_id"]
        applied["applied_approval_channel"] = receipt["channel"]
        applied["applied_approval_source"] = receipt["observation_source"]
        applied["applied_decision_authority"] = decision_authority
        applied["applied_by"] = applied_actor
        applied["applied_at"] = now_iso()
        applied["proposal_for"] = link
        applied.pop("proposal_digest", None)
        _write_contract_unlocked(path, applied)
    _append_control_event(
        path,
        "apply-proposal",
        actor=applied_actor,
        detail=digest,
        receipt_id=receipt["receipt_id"],
    )
    bootstrap_retries = _authorize_bootstrap_retries_for_applied_proposal(
        path,
        previous=current,
        applied=applied,
        receipt=receipt,
        proposal_digest_value=digest,
    )
    for retry in bootstrap_retries:
        _append_control_event(
            path,
            "system-authorize-continuation-retry",
            actor="system-continuation-grant",
            detail=json.dumps(retry, ensure_ascii=False, sort_keys=True),
            receipt_id=receipt["receipt_id"],
        )
    return load_contract(path)

def activate_contract(
    source: Path,
    *,
    home: Path,
    workspace: Path,
    provider: str | None = None,
    session_id: str | None = None,
) -> Path:
    if session_id:
        raise IntentGuardianError(
            "per-session intent activation is retired; activate one workspace contract instead"
        )
    contract = load_contract(source)
    root = workspace_root(workspace)
    contract["workspace_root"] = str(root)
    target = active_contract_path(home, root)
    if target.is_file():
        current = load_contract(target)
        if current["intent_id"] == contract["intent_id"] and contract["revision"] <= current["revision"]:
            raise IntentGuardianError(
                f"revision must increase above active revision {current['revision']}"
            )
    safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", contract["intent_id"])[:160]
    history = home / "intent" / "history" / safe_id / f"r{contract['revision']}.json"
    if history.exists():
        raise IntentGuardianError(f"intent history revision already exists: {history}")
    write_contract(history, contract)
    write_contract(target, contract)
    _ensure_intent_confirmation_request(target, contract)
    return target

def rebind_workspace_contract(
    path: Path,
    *,
    home: Path,
    new_workspace: Path,
    reason: str,
    actor: str = "human-cli",
) -> dict[str, Any]:
    """Move one orphaned workspace contract without carrying live authority.

    Rebinding is deliberately a human-only recovery operation. The destination
    contract is paused and requires a newly approved intent proposal before it
    can become active again.
    """
    source = path.expanduser().resolve()
    destination_root = workspace_root(new_workspace)
    if not destination_root.is_dir():
        raise IntentGuardianError(f"new workspace does not exist: {destination_root}")
    clean_reason = reason.strip()
    if not clean_reason:
        raise IntentGuardianError("workspace rebind reason must be non-empty")
    target = active_contract_path(home, destination_root)
    if target.resolve() == source:
        raise IntentGuardianError("new workspace resolves to the existing contract binding")

    registry_lock = home / "intent" / "workspaces" / ".workspace-rebind.lock"
    with _exclusive_path_lock(registry_lock), contract_lock(source):
        contract = load_contract(source)
        old_root = Path(contract["workspace_root"])
        expected_source = bound_contract_path(home, old_root).resolve()
        if source != expected_source:
            raise IntentGuardianError(
                "source is not the canonical active contract for its workspace"
            )
        if old_root.exists():
            raise IntentGuardianError(
                "source workspace still exists; rebind is only for orphaned contracts"
            )
        runtime = contract["runtime"]
        if (
            runtime["open_events"]
            or runtime["pending_verifications"]
            or runtime["active_skill_frames"]
            or runtime["active_skills"]
        ):
            raise IntentGuardianError(
                "cannot rebind with open events, pending verification, or active skills"
            )
        if target.exists():
            raise IntentGuardianError(
                f"destination workspace already has an active contract: {target}"
            )
        target_audit = audit_path(target)
        if target_audit.exists():
            raise IntentGuardianError(
                f"destination workspace already has guardian audit state: {target_audit}"
            )
        mapping_rebind_plan = prepare_session_mapping_rebind(
            home,
            source_contract_path=source,
            source_workspace=old_root,
            target_contract_path=target,
            target_workspace=destination_root,
        )

        rebound_at = now_iso()
        for receipt in runtime["approval_receipts"]:
            if not receipt["consumed_at"]:
                receipt["consumed_at"] = rebound_at
                receipt["consumed_by"] = "invalidated-by-workspace-rebind"
        runtime["authorized_events"] = []
        runtime["approved_proposal_digests"] = []
        runtime["pending_proposal_digest"] = ""
        historical_observation_count = len(runtime["host_observations"])
        runtime["host_observations"] = []
        runtime["pause_scope"] = "global"
        runtime["pause_reason"] = (
            "工作区已迁移；必须重新确认意图提案后才能恢复执行"
        )
        runtime["pause_origin_reason"] = runtime["pause_reason"]
        runtime["pause_class"] = "semantic"
        runtime["pause_event_fingerprint"] = ""
        contract["approved_event_fingerprints"] = []
        contract["revision"] += 1
        contract["workspace_root"] = str(destination_root)
        contract["status"] = "paused"
        contract["confirmed_by"] = "workspace-rebind-pending-intent-review"
        contract["confirmation"] = {
            "required": True,
            "reason": "workspace path changed; review a new immutable intent proposal",
        }
        runtime["pause_requires_revision"] = True
        runtime["pause_revision"] = contract["revision"]
        contract["workspace_rebind"] = {
            "from": str(old_root),
            "to": str(destination_root),
            "at": rebound_at,
            "by": actor,
            "reason": clean_reason[:2_000],
            "historical_host_observations": historical_observation_count,
        }

        archive = source.with_name(
            f"{source.name[:-5]}.rebound-r{contract['revision'] - 1}.json"
        )
        if archive.exists():
            raise IntentGuardianError(f"workspace rebind archive already exists: {archive}")
        marker_path = rebind_marker_path(source)
        if marker_path.exists():
            raise IntentGuardianError(f"workspace rebind marker already exists: {marker_path}")
        source_audit = audit_path(source)
        audit_content = (
            source_audit.read_text(encoding="utf-8", errors="replace")
            if source_audit.is_file()
            else ""
        )
        os.replace(source, archive)
        rebound_mappings: list[dict[str, Any]] = []
        try:
            _write_contract_unlocked(target, contract)
            if audit_content:
                atomic_write(target_audit, audit_content)
            marker = {
                "schema": "sulde-workspace-rebind-v1",
                "from_workspace": str(old_root),
                "from_contract": str(source),
                "archive_contract": str(archive),
                "to_workspace": str(destination_root),
                "to_contract": str(target),
                "intent_id": contract["intent_id"],
                "revision": contract["revision"],
                "at": rebound_at,
                "by": actor,
                "reason": clean_reason[:2_000],
            }
            _append_control_event(
                target,
                "rebind-workspace",
                actor=actor,
                detail=f"{old_root} -> {destination_root}: {clean_reason[:1_000]}",
            )
            atomic_write(
                marker_path,
                json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            # Publish session routes last.  The helper restores every prior
            # mapping byte on a partial failure; the outer transaction then
            # restores the contract binding and audit projection.
            rebound_mappings = apply_session_mapping_rebind(
                home, mapping_rebind_plan,
            )
        except Exception:
            if marker_path.exists():
                marker_path.unlink()
            if target.exists():
                target.unlink()
            if target_audit.exists():
                target_audit.unlink()
            if archive.exists() and not source.exists():
                os.replace(archive, source)
            raise
    return {
        "status": "rebound_pending_intent_review",
        "source_workspace": str(old_root),
        "destination_workspace": str(destination_root),
        "source_contract": str(source),
        "archive_contract": str(archive),
        "contract_path": str(target),
        "intent_id": contract["intent_id"],
        "revision": contract["revision"],
        "session_mappings_rebound": len(rebound_mappings),
    }

def retire_orphan_contract(
    path: Path,
    *,
    home: Path,
    reason: str,
    actor: str = "human-cli",
) -> dict[str, Any]:
    """Archive one abandoned orphan without transferring any authority."""
    source = path.expanduser().resolve()
    clean_reason = reason.strip()
    if not clean_reason:
        raise IntentGuardianError("workspace retirement reason must be non-empty")
    registry_lock = home / "intent" / "workspaces" / ".workspace-rebind.lock"
    with _exclusive_path_lock(registry_lock), contract_lock(source):
        original = source.read_text(encoding="utf-8")
        contract = load_contract(source)
        old_root = Path(contract["workspace_root"])
        if source != bound_contract_path(home, old_root).resolve():
            raise IntentGuardianError(
                "source is not the canonical active contract for its workspace"
            )
        if old_root.exists():
            raise IntentGuardianError(
                "source workspace still exists; retire-workspace is only for orphaned contracts"
            )
        runtime = contract["runtime"]
        if (
            runtime["open_events"]
            or runtime["pending_verifications"]
            or runtime["active_skill_frames"]
            or runtime["active_skills"]
        ):
            raise IntentGuardianError(
                "cannot retire with open events, pending verification, or active skills"
            )
        retired_at = now_iso()
        for receipt in runtime["approval_receipts"]:
            if not receipt["consumed_at"]:
                receipt["consumed_at"] = retired_at
                receipt["consumed_by"] = "invalidated-by-workspace-retirement"
        runtime["authorized_events"] = []
        runtime["approved_proposal_digests"] = []
        runtime["pending_proposal_digest"] = ""
        runtime["host_observations"] = []
        runtime["pause_scope"] = ""
        runtime["pause_reason"] = ""
        runtime["pause_origin_reason"] = ""
        runtime["pause_class"] = ""
        runtime["pause_event_fingerprint"] = ""
        runtime["pause_requires_revision"] = False
        runtime["pause_revision"] = 0
        contract["approved_event_fingerprints"] = []
        contract["revision"] += 1
        contract["status"] = "closed"
        contract["retired_workspace"] = {
            "root": str(old_root),
            "at": retired_at,
            "by": actor,
            "reason": clean_reason[:2_000],
        }
        archive = source.with_name(
            f"{source.name[:-5]}.retired-r{contract['revision']}.json"
        )
        marker_path = retire_marker_path(source)
        if archive.exists():
            raise IntentGuardianError(f"workspace retirement archive already exists: {archive}")
        if marker_path.exists():
            raise IntentGuardianError(f"workspace retirement marker already exists: {marker_path}")
        try:
            _write_contract_unlocked(source, contract)
            os.replace(source, archive)
            marker = {
                "schema": "sulde-workspace-retirement-v1",
                "workspace": str(old_root),
                "from_contract": str(source),
                "archive_contract": str(archive),
                "intent_id": contract["intent_id"],
                "revision": contract["revision"],
                "at": retired_at,
                "by": actor,
                "reason": clean_reason[:2_000],
            }
            atomic_write(
                marker_path,
                json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
        except Exception:
            if marker_path.exists():
                marker_path.unlink()
            if archive.exists():
                os.replace(archive, source)
            atomic_write(source, original)
            raise

    _append_jsonl(
        audit_path(source),
        {
            "schema": "sulde-intent-control-event-v1",
            "at": retired_at,
            "action": "retire-workspace",
            "actor": actor,
            "detail": clean_reason[:2_000],
            "intent_id": contract["intent_id"],
            "intent_revision": contract["revision"],
            "archive_contract": str(archive),
        },
    )
    return {
        "status": "retired",
        "workspace": str(old_root),
        "source_contract": str(source),
        "archive_contract": str(archive),
        "intent_id": contract["intent_id"],
        "revision": contract["revision"],
    }

def _reconcile_read_only_effect_debt_locked(
    path: Path,
    contract: dict[str, Any],
) -> list[str]:
    """Close legacy interventions that were incorrectly opened for reads.

    A missing callback can make the result of a read inconclusive, but it
    cannot leave an external mutation whose outcome needs human adjudication.
    Older runtimes tracked every interrupted MCP call as an effect attempt.
    Preserve those append-only events, append an explicit abort resolution,
    and remove only their derived pending-verification rows.
    """
    try:
        projection = load_intervention_projection(path)
    except (InterventionError, OSError, UnicodeError):
        return []
    read_attempt_ids = {
        str(attempt_id)
        for attempt_id, attempt in projection.get("attempts", {}).items()
        if isinstance(attempt, dict) and attempt.get("effect") == "read"
    }
    if not read_attempt_ids:
        return []

    pending_ids = {
        str(row.get("attempt_id") or "")
        for row in contract["runtime"].get("pending_verifications", [])
        if isinstance(row, dict)
    }
    reconciled_ids: set[str] = set()
    for intervention in projection.get("interventions", {}).values():
        if (
            not isinstance(intervention, dict)
            or str(intervention.get("attempt_id") or "") not in read_attempt_ids
        ):
            continue
        attempt_id = str(intervention["attempt_id"])
        if intervention.get("status") == "resolved":
            if attempt_id in pending_ids:
                reconciled_ids.add(attempt_id)
            continue
        if intervention.get("status") not in {"open", "acknowledged"}:
            continue
        try:
            settle_legacy_read_only_effect_debt(
                path,
                str(intervention["intervention_id"]),
            )
        except (InterventionError, OSError, UnicodeError):
            continue
        reconciled_ids.add(attempt_id)

    pending = contract["runtime"].get("pending_verifications", [])
    removed_pending_ids = {
        str(row.get("attempt_id") or "")
        for row in pending
        if isinstance(row, dict)
        and str(row.get("attempt_id") or "") in reconciled_ids
    }
    if removed_pending_ids:
        contract["runtime"]["pending_verifications"] = [
            row
            for row in pending
            if not isinstance(row, dict)
            or str(row.get("attempt_id") or "") not in reconciled_ids
        ]
    return sorted(reconciled_ids | removed_pending_ids)

def _probe_pending_verifications(
    path: Path,
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    """Probe sealed effects without holding the shared intent-contract lock."""
    pending = contract["runtime"].get("pending_verifications", [])
    if not pending:
        return []
    try:
        projection = load_intervention_projection(path)
    except (InterventionError, OSError, UnicodeError):
        return []
    reconciled: list[dict[str, Any]] = []
    for row in list(pending):
        if not isinstance(row, dict):
            continue
        attempt_id = str(row.get("attempt_id") or "")
        attempt = projection.get("attempts", {}).get(attempt_id)
        if not isinstance(attempt, dict) or attempt.get("state") not in {
            "verifying", "unknown"
        }:
            continue
        row_digest = str(row.get("verification_sha256") or "")
        attempt_digest = str(attempt.get("verification_sha256") or "")
        if row_digest and attempt_digest and row_digest != attempt_digest:
            continue
        expected_digest = row_digest or attempt_digest
        memory_recipe = (
            memory_scope.matches_attempt(row, projection.get("attempts", {}))
            and row.get("continuation_profile_id") == "sulde-memory-annotate-v1"
        )
        if memory_recipe:
            profile_id = "sulde-memory-annotate-v1"
            independent = _memory_receipt_verification(expected_digest)
        else:
            grant = _pending_verification_grant(path, contract, row, expected_digest=expected_digest)
            if grant is None:
                continue
            candidate = _continuation_candidate_from_grant(grant)
            if expected_digest != candidate["verification_sha256"]:
                continue
            profile_id = grant["profile_id"]
            independent = _registered_continuation_verification(grant)
        if not isinstance(independent, dict) or not isinstance(
            independent.get("evidence"), dict
        ):
            continue
        try:
            verified = verify_from_read(
                path,
                provider=str(attempt.get("provider") or row.get("provider") or "unknown"),
                session_id=str(attempt.get("session_id") or row.get("session_id") or ""),
                capability=str(independent["capability"]),
                target=str(attempt.get("target") or row.get("target") or ""),
                resource_key=str(attempt.get("resource_key") or ""),
                resource_base=str(attempt.get("resource_base") or "") or None,
                resource_context=(
                    attempt.get("resource_context")
                    if isinstance(attempt.get("resource_context"), dict)
                    else None
                ),
                verification_event_id=f"system-reconcile:{attempt_id}",
                explicit_attempt_id=attempt_id,
                evidence=independent["evidence"],
            )
        except (InterventionError, OSError, UnicodeError):
            continue
        if not verified:
            continue
        evidence_row = {
            "attempt_id": attempt_id,
            "write_fingerprint": row.get("fingerprint") or attempt.get("fingerprint"),
            "write_capability": row.get("capability") or attempt.get("capability"),
            "target": attempt.get("target") or row.get("target"),
            "verified_by_event": f"system-reconcile:{attempt_id}",
            "verified_by_capability": independent["capability"],
            "verified_at": now_iso(),
            "verification_source": "system_reconciliation",
            "evidence_source": independent["source"],
            "continuation_profile_id": profile_id,
            "compensates_attempt_id": str(
                verified[0].get("compensates_attempt_id") or ""
            ),
        }
        reconciled.append(evidence_row)
    return reconciled

def _apply_reconciled_pending_locked(
    contract: dict[str, Any], reconciled: list[dict[str, Any]]
) -> bool:
    attempt_ids = {
        str(row.get("attempt_id") or "")
        for row in reconciled
        if str(row.get("attempt_id") or "")
    }
    compensated_ids = {
        str(row.get("compensates_attempt_id") or "")
        for row in reconciled
        if str(row.get("compensates_attempt_id") or "")
    }
    settled = attempt_ids | compensated_ids
    if not settled:
        return False
    pending = contract["runtime"].get("pending_verifications", [])
    before = len(pending)
    contract["runtime"]["pending_verifications"] = [
        row
        for row in pending
        if not isinstance(row, dict) or row.get("attempt_id") not in settled
    ]
    evidence = contract["runtime"].get("verified_effects", [])
    known = {
        (str(row.get("attempt_id") or ""), str(row.get("verified_by_event") or ""))
        for row in evidence
        if isinstance(row, dict)
    }
    for row in reconciled:
        identity = (
            str(row.get("attempt_id") or ""),
            str(row.get("verified_by_event") or ""),
        )
        if identity not in known:
            evidence.append(row)
            known.add(identity)
    contract["runtime"]["verified_effects"] = evidence[-50:]
    return before != len(contract["runtime"]["pending_verifications"]) or bool(
        reconciled
    )

def _settled_pending_verification_ids(
    path: Path,
    contract: dict[str, Any],
) -> set[str]:
    """Find stale derived rows whose append-only effect truth is settled."""
    pending_ids = {
        str(row.get("attempt_id") or "")
        for row in contract.get("runtime", {}).get("pending_verifications", [])
        if isinstance(row, dict) and str(row.get("attempt_id") or "")
    }
    if not pending_ids:
        return set()
    try:
        projection = load_intervention_projection(path)
        attempts = projection.get("attempts", {})
        blocking_ids = {
            str(row.get("attempt_id") or "")
            for row in blocking_attempts(projection)
        }
        quarantined_ids = {
            str(row.get("attempt_id") or "")
            for row in terminal_quarantined_attempts(projection)
        }
    except (InterventionError, OSError, UnicodeError):
        return set()
    # Missing attempt truth remains fail-closed.  Only an authoritative attempt
    # that is no longer blocking (including a consumed retry predecessor) may
    # remove its rebuildable pending projection. A terminally aborted attempt
    # also leaves the active verification queue: its append-only attempt still
    # protects exact retries, but no verifier is pending after the human ended
    # that workflow.
    return {
        attempt_id
        for attempt_id in pending_ids
        if attempt_id in attempts
        and (
            attempt_id not in blocking_ids
            or attempt_id in quarantined_ids
        )
    }

def _prune_settled_pending_locked(
    contract: dict[str, Any],
    settled_ids: set[str],
) -> bool:
    if not settled_ids:
        return False
    pending = contract["runtime"].get("pending_verifications", [])
    before = len(pending)
    contract["runtime"]["pending_verifications"] = [
        row
        for row in pending
        if not isinstance(row, dict)
        or str(row.get("attempt_id") or "") not in settled_ids
    ]
    return before != len(contract["runtime"]["pending_verifications"])

def reconcile_pending_verifications(
    path: Path,
    *,
    recover_rollout_reads: bool = False,
) -> list[dict[str, Any]]:
    """Public recovery entrypoint used at safe host boundaries."""
    # Phase 1 may spawn a bounded verifier and hash installed trees. It must not
    # run while the 3-second workspace state lock is held. Effect transitions
    # are attempt-id CAS operations in their own append-only ledger.
    snapshot = load_contract(path)
    corrected_reads = (
        reconcile_misclassified_figma_reads(path)
        if recover_rollout_reads
        else []
    )
    recovered_completions = recover_completed_audit_verifications(path)
    reconciled = [
        *recovered_completions,
        *_probe_pending_verifications(path, snapshot),
    ]
    settled_ids = _settled_pending_verification_ids(path, snapshot)
    with contract_lock(path):
        contract = load_contract(path)
        read_only_cleanup = _reconcile_read_only_effect_debt_locked(path, contract)
        git_control_cleanup = reconcile_git_control_debt_locked(path, contract)
        applied = _apply_reconciled_pending_locked(contract, reconciled)
        settled_pruned = _prune_settled_pending_locked(contract, settled_ids)
        if read_only_cleanup or git_control_cleanup or applied or settled_pruned:
            _write_contract_unlocked(path, contract)
    if read_only_cleanup:
        _append_control_event(
            path,
            "system-reconcile-read-only-effect-debt",
            actor="system-read-only-reconciler",
            detail=",".join(read_only_cleanup),
        )
    if corrected_reads:
        _append_control_event(
            path,
            "system-correct-legacy-figma-read-classification",
            actor="system-rollout-read-classifier",
            detail=",".join(
                str(row["attempt_id"]) for row in corrected_reads
            ),
        )
    if git_control_cleanup:
        _append_control_event(
            path, "system-quarantine-legacy-git-control-debt",
            actor="system-git-control-migrator", detail=",".join(git_control_cleanup),
        )
    if settled_pruned:
        _append_control_event(
            path,
            "system-prune-settled-effect-projection",
            actor="system-effect-reconciler",
            detail=",".join(sorted(settled_ids)),
        )
    if reconciled:
        _append_control_event(
            path,
            "system-reconcile-verification",
            actor="system-verifier",
            detail=",".join(str(row["attempt_id"]) for row in reconciled),
        )
    return [*reconciled, *corrected_reads]
def route_recovery_before_ordinary_policy(
    event: Any,
    *,
    lane: RecoveryLane,
    current_pre_state: dict[str, Any],
    ordinary_policy: Callable[[Any], dict[str, Any]],
) -> dict[str, Any]:
    """Classify sealed recovery before the ordinary guard can self-lock.

    This narrow entrypoint transfers no terminal text or shell-command
    authority. Non-recovery events still flow through the ordinary policy.
    """
    if not isinstance(lane, RecoveryLane):
        raise IntentGuardianError("recovery lane instance is not trusted")
    if (
        isinstance(event, dict)
        and event.get("schema") == RECOVERY_REQUEST_SCHEMA
    ) or (
        isinstance(event, dict)
        and event.get("trusted_recovery_control") is True
    ):
        return lane.pretool_decision(
            event,
            current_pre_state=current_pre_state,
            ordinary_guard=ordinary_policy,
        )
    return ordinary_policy(event)

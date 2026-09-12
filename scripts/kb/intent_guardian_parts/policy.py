"""Intent Guardian policy domain component."""

from __future__ import annotations
from .state import READ_ONLY_AGENT_CONTROL_ACTIONS
from .control_composition import AUDIT_CONTROL_ACTIONS

from .memory_scope import advance_sequence as _advance_material_sequence_for_allowed_event

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
    is_legacy_git_control_attempt,
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

from intent_critic import run_critic, validate_result

from .approvals import (
    _invalidate_stale_approval_receipts_locked,
)

from .completion_recovery import (
    matching_authorized_completion,
    settle_matching_human_grant,
)

from .events import (
    duplicate_host_call,
    _completion_open_event_index,
    _continuation_authorization,
    _effect_attempt_target,
    _effect_resource_identity,
    _event_local_targets,
    _human_approved_local_destructive,
    _matches,
    _matches_mcp_server,
    _paths_allowed as _base_paths_allowed,
    _paths_frozen,
    _read_proof_target,
    _registered_compensation_predecessor,
    _registered_semantic_retry_intervention,
    _retag_guardian_violation,
    normalize_provider_events,
)

from .recovery import (
    _reconcile_read_only_effect_debt_locked,
    reassess_unattended_proposal,
    reconcile_obsolete_approval_requests,
    reconcile_pending_verifications,
    recover_native_decisions,
)

from .resources import (
    _read_verification_evidence,
    _response_target,
)

from .pre_execution_proof import observe_probe

from .state import (
    BREAK_GLASS_CONTROL_ACTIONS,
    CONTINUATION_USE_SCHEMA,
    SYSTEM_MEMORY_PROFILE,
    Decision,
    EVENT_SCHEMA,
    IntentGuardianError,
    RUNTIME_GENERATION,
    _append_jsonl,
    _pause_global_locked,
    _pause_lane_locked,
    _pause_state,
    _write_contract_unlocked,
    audit_path,
    contract_lock,
    event_fingerprint,
    load_contract,
    now_iso,
    policy_digest,
    workspace_key,
)


_LITERAL_PATH_META = frozenset("*?[]")


def _human_approved_shell_delete(
    contract: dict[str, Any],
    event: dict[str, Any],
) -> bool:
    """Accept only a typed, exact shell deletion under one native human card."""
    decision = contract.get("decision")
    effects = (
        set(decision.get("effects") or [])
        if isinstance(decision, dict)
        else set()
    )
    operations = event.get("local_file_operations")
    action = str(event.get("action") or "").lower()
    return bool(
        event.get("destructive_local_operation")
        and event.get("kind") == "tool"
        and action in {"bash", "exec", "exec_command", "command_execution"}
        and isinstance(operations, list)
        and operations
        and all(
            isinstance(operation, dict)
            and operation.get("operation") == "delete"
            and isinstance(operation.get("path"), str)
            and operation["path"]
            for operation in operations
        )
        and event.get("write_targets")
        == [operation["path"] for operation in operations]
        and contract["permissions"].get("local_write") is True
        and contract["permissions"].get("destructive") == "confirm"
        and {"local_write", "destructive"}.issubset(effects)
        and isinstance(decision, dict)
        and decision.get("selected_route") == "human"
        and contract.get("confirmed_by") == "human-readable-proposal-approval"
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(contract.get("applied_proposal_digest") or ""),
        )
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(contract.get("applied_approval_receipt_id") or ""),
        )
    )


def _resolved_workspace_relative(root: Path, value: str) -> tuple[Path, str] | None:
    """Resolve one path inside a workspace while retaining its lexical shape."""
    try:
        candidate = Path(value).expanduser()
        lexical = candidate if candidate.is_absolute() else root / candidate
        resolved_root = root.resolve()
        resolved = lexical.resolve()
        relative = resolved.relative_to(resolved_root).as_posix()
    except (OSError, ValueError):
        return None
    return resolved, relative or "."


def _exact_compatibility_control_path_allowed(
    target: str,
    contract: dict[str, Any],
) -> bool:
    """Allow only an exact, literal human-reviewed ``.codex-agent`` target.

    ``.git`` remains permanently protected.  Repository roots, ancestors and
    glob patterns cannot authorize a compatibility control artifact.  This is
    intentionally narrower than ordinary ``allowed_paths`` descendant
    matching and closes F00-002 without creating a broad control-directory
    allowlist.
    """
    root = Path(str(contract.get("workspace_root") or ""))
    target_identity = _resolved_workspace_relative(root, target)
    if target_identity is None:
        return False
    target_resolved, target_relative = target_identity
    target_parts = set(Path(target_relative).parts)
    if ".git" in target_parts or ".codex-agent" not in target_parts:
        return False
    for raw in contract.get("constraints", {}).get("allowed_paths", []):
        literal = str(raw or "").strip()
        if not literal or any(char in literal for char in _LITERAL_PATH_META):
            continue
        allowed_identity = _resolved_workspace_relative(root, literal)
        if allowed_identity is None:
            continue
        allowed_resolved, allowed_relative = allowed_identity
        allowed_parts = set(Path(allowed_relative).parts)
        if ".git" in allowed_parts or ".codex-agent" not in allowed_parts:
            continue
        if (
            allowed_resolved == target_resolved
            and allowed_relative == target_relative
        ):
            return True
    return False


def _paths_allowed(targets: Iterable[str], contract: dict[str, Any]) -> bool:
    """Protect control artifacts without making task paths an authority gate.

    ``allowed_paths`` remains useful to plan impact and tests, but ordinary
    local files are owned by the Agent/host.  Guardian only retains its narrow
    protected-control and frozen-path boundaries here.
    """
    normalized = [str(target) for target in targets if str(target)]
    if not normalized:
        return False
    root = Path(str(contract.get("workspace_root") or ""))
    for target in normalized:
        try:
            candidate = Path(target).expanduser()
            resolved = (
                candidate if candidate.is_absolute() else root / candidate
            ).resolve()
        except OSError:
            return False
        parts = set(resolved.parts)
        if ".git" in parts:
            return False
        if ".codex-agent" in parts:
            if not _exact_compatibility_control_path_allowed(target, contract):
                return False
    return True


def _evaluate_composition(
    contract: dict[str, Any], event: dict[str, Any], *, contract_path: Path | None,
) -> Decision:
    """Preflight every possible step against the same non-transferred authority.

    No observe(), grant consumption, fabricated completion or per-step journal
    replay occurs here. A denied program never starts, so it never pauses a lane.
    """

    composition = event["composition"]
    reason = str(composition.get("error") or "")
    verification = False
    steps = composition.get("steps", [])
    if not reason and (not isinstance(steps, list) or not steps):
        reason = "组合缺少可验证的步骤"
    if not reason:
        for step in steps:
            child = step["event"]
            if child.get("supervision_domain") == "execution_passthrough":
                continue
            if child.get("control_plane") and not child.get("composition"):
                if (child.get("control_route") != "agent"
                        or child.get("control_action") not in READ_ONLY_AGENT_CONTROL_ACTIONS | AUDIT_CONTROL_ACTIONS):
                    reason = f"第 {step['index']} 步：该控制动作没有本组合的执行权限"
                    break
                registration = child.get("composition_registration")
                if registration and (
                    registration["provider"] != event["provider"]
                    or registration["session_id"] != event["session_id"]
                    or contract_path is None
                    or Path(registration["contract_path"]).resolve() != contract_path.resolve()
                ):
                    reason = f"第 {step['index']} 步：Skill 登记与当前 session/contract 不匹配"
                    break
                continue
            decision = evaluate_event(contract, child, contract_path=contract_path)
            if decision.action != "allow":
                reason = f"第 {step['index']} 步：{decision.reason}"
                break
            verification = verification or decision.verification_required
    completed_gap = bool(reason and event.get("phase") == "completed" and event["effect"] != "read")
    return Decision(
        dispatch="deny" if reason else "allow", would_dispatch="deny" if reason else "allow",
        lifecycle="pause" if completed_gap else "continue",
        pause_class="safety" if completed_gap else "", authority="none",
        verification="required" if verification or completed_gap else "none",
        evidence_state="gap" if completed_gap else "observed",
        severity="high" if reason else "info", fingerprint=event_fingerprint(event),
        reason=(
            f"组合未执行：{reason}。请调整该步骤；无需重放已完成的其他调用"
            if reason and not completed_gap else reason if reason else
            "各可能步骤已独立预检；由原 shell 执行，短路/管道结果不推断为逐步成功"
        ),
        reason_code="control_composition_denied" if reason else "control_composition_allowed",
        decision_stage="composition_preflight",
    )


def evaluate_event(
    contract: dict[str, Any], event: dict[str, Any], *, contract_path: Path | None = None,
) -> Decision:
    if isinstance(event.get("composition"), dict):
        return _evaluate_composition(contract, event, contract_path=contract_path)
    fingerprint = event_fingerprint(event)
    mode = contract["mode"]
    effect = event["effect"]
    kind = event["kind"]
    capability = event["capability"]
    target = event["target"]
    uncertainty_kind = str(event.get("uncertainty_kind") or "")
    applicable_pause = _pause_state(
        contract,
        provider=str(event.get("provider") or "unknown"),
        session_id=str(event.get("session_id") or ""),
    )
    continuation_authorized = isinstance(event.get("continuation_authority"), dict)
    local_mcp_write = (
        kind == "mcp"
        and effect == "external_write"
        and _matches_mcp_server(str(event["server"]), contract["mcp"]["local_servers"])
    )
    declared_effects = {
        str(value)
        for value in (
            contract.get("decision", {}).get("effects", [])
            if isinstance(contract.get("decision"), dict)
            else []
        )
    }
    task_scope_authorized = (
        continuation_authorized
        or bool(event.get("retry_intervention_id"))
        or effect in declared_effects
        or (effect == "external_write" and contract["permissions"]["external_write"] == "allow")
        or local_mcp_write
    )
    violation = ""
    severity = "info"
    pause = False
    observation_gap = False
    pause_class = ""
    # A completion callback proves only that a call returned. If a material
    # MCP/external action reached completion without a matching authorized pre
    # event, its effect is still verification debt rather than a clean denial.
    lifecycle_resource = (
        event.get("typed_resource")
        if isinstance(event.get("typed_resource"), dict)
        and event["typed_resource"].get("kind") == "git_worktree_lifecycle"
        else None
    )
    verification = bool(
        lifecycle_resource
        and lifecycle_resource.get("status") in {"classified", "completion"}
    )

    if (
        contract["confirmation"]["required"]
        and contract["confirmed_by"] in {"unconfirmed", "unconfirmed-proposal"}
        and effect in {"local_write", "external_write", "destructive", "unknown"}
    ):
        violation, severity = "主观或高歧义任务尚未确认意图镜像；只允许读取和澄清", "critical"
        pause, pause_class = True, "semantic"
    elif contract["status"] == "closed":
        violation, severity = "意图契约已关闭，不能继续执行", "critical"
        pause, pause_class = True, "semantic"
    elif (
        applicable_pause is not None
        and effect in {"local_write", "external_write", "destructive", "unknown"}
        and not (
            applicable_pause.get("pause_class") == "technical"
            and not applicable_pause.get("requires_revision", False)
            and effect in {"local_write", "unknown"}
        )
    ):
        violation, severity = (
            "当前 task lane 处于暂停态；只允许读取和澄清"
            if applicable_pause.get("scope") == "lane"
            else "意图契约处于全局语义或安全暂停态；只允许读取和澄清",
            "critical",
        )
        pause, pause_class = True, str(
            applicable_pause.get("pause_class") or "semantic"
        )
    elif kind == "skill":
        name = str(event["action"])
        if _matches(name, contract["skills"]["deny"]):
            violation, severity = f"Skill {name} 被意图契约禁止", "high"
            pause, pause_class = True, "safety"
        elif contract["skills"]["allow"] and not _matches(name, contract["skills"]["allow"]):
            violation, severity = f"Skill {name} 不在允许清单", "high"
            pause, pause_class = True, "safety"
    elif kind == "mcp":
        server = str(event["server"])
        allow_servers = contract["mcp"]["allow_servers"]
        allow_tools = contract["mcp"]["allow_tools"]
        if allow_servers and not _matches_mcp_server(server, allow_servers):
            violation, severity = (
                f"MCP server {server} 超出当前可读意图范围；先在对话中确认范围扩展",
                "high",
            )
        elif allow_tools and not _matches(capability.removeprefix("mcp:"), allow_tools):
            violation, severity = (
                f"MCP tool {capability} 超出当前可读意图范围；先在对话中确认范围扩展",
                "high",
            )
        elif effect == "unknown":
            policy = contract["mcp"]["unknown_effect"]
            if uncertainty_kind == "unclassified_read_candidate":
                pass
            elif policy == "deny":
                violation, severity = f"契约明确禁止未知副作用的 {capability}", "critical"
                pause_class = "safety"
            elif event.get("phase") == "completed":
                observation_gap = True
                verification = True
                severity = "high"
            elif task_scope_authorized:
                verification = True
            else:
                violation = f"未知外部写入 {capability} 未包含在当前任务范围"
                severity = "high"

    if not violation and isinstance(event.get("invocation_violation"), dict):
        violation = str(
            event["invocation_violation"].get("reason")
            or "受控维护动作的调用形状不满足密封条件"
        )
        severity = "high"
        if event["invocation_violation"].get("kind") == "unresolved-destructive-receiver":
            # Uncertainty is not a proven destructive effect, but it is a hard
            # risk signal. Deny this invocation without freezing an unexecuted
            # task; a completed gap retains reconciliation and pause semantics.
            severity = "critical"
            if event.get("phase") == "completed":
                pause, pause_class = True, "safety"
                verification, observation_gap = True, True
        if event["invocation_violation"].get("effect") == "destructive":
            # A valid pre-execution denial of an ordinary local delete is
            # already the terminal safety action. Pausing the whole lane there
            # turns one malformed cleanup command into a control-plane self-
            # lock even though nothing ran. Tampered maintenance/control
            # invocations and completed destructive gaps still require pause.
            severity, pause_class = "critical", "safety"
            pause = not (
                event.get("phase") == "started"
                and (event["invocation_violation"].get("bounded_pre_execution_denial") is True
                     or event["invocation_violation"].get("kind") == "invalid-composition")
            )
    elif (
        not violation
        and isinstance(event.get("continuation_candidate"), dict)
        and not continuation_authorized
    ):
        candidate = event["continuation_candidate"]
        if candidate.get("dispatch_adapter") == "candidate-promotion-v1":
            violation = (
                "候选发布是尚未获得本会话原生授权的外部写入；"
                "需要对精确候选、发布件和生产前态确认 Allow/Deny"
            )
        elif candidate.get("profile_id") == SYSTEM_MEMORY_PROFILE:
            violation = "记忆登记未满足当前 lane 的本地写入权限或调用归属条件；不是历史次数额度，也不是需要续行 grant"
        else:
            violation = "登记动作没有匹配当前意图中的精确续行 grant；需要更新可读方案"
        severity = "high"
    elif (
        not violation
        and event.get("formal_maintenance") is True
        and not continuation_authorized
        and mode == "enforce"
        and isinstance(contract.get("decision"), dict)
        and contract["decision"].get("risk") in {"high", "unknown"}
    ):
        violation = (
            "高风险正式维护动作未匹配 proposal-bound 类型化 profile；"
            "必须在执行前拒绝或重新确认"
        )
        severity = "high"
    elif (
        not violation
        and lifecycle_resource is not None
        and lifecycle_resource.get("status") == "rejected"
    ):
        violation = str(
            lifecycle_resource.get("reason")
            or "Git worktree lifecycle pre-state cannot be proved"
        )
        severity = "high"
    elif not violation and effect == "destructive":
        violation, severity = "破坏性动作不在 Agent 自主权内", "critical"
        pause, pause_class = True, "safety"
    elif (
        not violation
        and event.get("sensitive_input")
        and (
            effect == "external_write"
            or (kind == "mcp" and effect != "read")
        )
    ):
        violation = "检测到可能的密钥或凭据外发；必须先在本地脱敏再执行"
        severity, pause_class = "critical", "safety"
        verification = event["phase"] == "completed"
    elif not violation and continuation_authorized:
        verification = True
    elif not violation and local_mcp_write:
        if event["phase"] == "completed":
            verification = True
            if not contract["permissions"]["local_write"]:
                observation_gap = True
                severity = "high"
        elif not contract["permissions"]["local_write"]:
            violation, severity = "本地 MCP 写入超出当前意图范围", "critical"
        else:
            verification = True
    elif not violation and effect == "external_write":
        if event["phase"] == "completed":
            # A PostToolUse callback cannot undo a dispatch.  Always enter the
            # evidence ledger, even when the matching PreTool callback was
            # missing or an older runtime used a different fingerprint.
            verification = True
            if (
                contract["permissions"]["external_write"] == "deny"
                or not task_scope_authorized
            ):
                observation_gap = True
                severity = "high"
        elif contract["permissions"]["external_write"] == "deny":
            violation = "外部写入被禁止"
            severity = "critical"
        elif task_scope_authorized:
            verification = True
        else:
            violation = "外部写入未包含在当前可读意图范围；请在对话中确认范围扩展"
            severity = "high"
    elif not violation and effect == "local_write":
        local_targets = _event_local_targets(event)
        if not contract["permissions"]["local_write"]:
            violation, severity = "本地写入未获授权", "critical"
        elif not _paths_allowed(local_targets, contract):
            violation, severity = (
                f"目标属于 Guardian 受保护的控制工件：{target or 'unknown'}",
                "critical",
            )
        elif _paths_frozen(local_targets, contract):
            violation, severity = f"目标处于冻结范围：{target}", "critical"
        elif (
            event.get("high_risk_local_operation")
            and not _base_paths_allowed(local_targets, contract)
        ):
            # Ordinary writes are Agent-owned, but a human destructive card is
            # deliberately exact: it may authorize only the paths that were
            # visible when the card was approved.
            violation = "破坏性动作超出人类决策卡列明的精确路径"
            severity, pause_class = "critical", "safety"
        elif event.get("high_risk_local_operation") and not (
            _human_approved_local_destructive(contract, event)
            or _human_approved_shell_delete(contract, event)
        ):
            violation = (
                "删除或移动必须由同一张人类决策卡同时声明 local_write 与 "
                "destructive，并绑定全部精确路径"
            )
            severity, pause_class = "critical", "safety"
    elif (
        not violation
        and capability == "tool:apply_patch"
        and target == "[unresolved-patch-target]"
    ):
        violation, severity = "apply_patch 无法解析写入目标，不能证明未越界", "critical"
    elif not violation and effect == "unknown":
        if uncertainty_kind == "unresolved_orchestrator_effect":
            violation = (
                "统一执行编排器包含动态、复合或未识别的物化调用；"
                "无法在执行前证明其任务范围"
            )
            severity = "critical"
        elif uncertainty_kind == "unresolved_local_write":
            # Ordinary local writes belong to the Agent/host.  Path ambiguity
            # is retained as an observation for impact/test planning, not as a
            # Guardian authorization barrier.  Destructive primitives and
            # protected control artifacts are classified earlier and still deny.
            observation_gap = True
            severity = "warning"
        elif uncertainty_kind == "unresolved_external_write":
            if event.get("phase") == "completed":
                observation_gap = True
                verification = True
                severity = "high"
            elif task_scope_authorized:
                verification = True
            else:
                violation = "无法解析的外部写入未包含在当前任务范围"
                severity = "high"
        elif uncertainty_kind not in {
            "opaque_execution",
            "unclassified_read_candidate",
            "execution_passthrough",
        }:
            observation_gap = True
            severity = "warning"

    would_action = "deny" if violation else "allow"
    # Shadow is observation-only for reversible local work. External,
    # destructive and unknown side effects never become safe merely because a
    # deployment is calibrating its policy.
    hard_effect = bool(violation) and (
        effect in {"external_write", "destructive"}
        or pause_class in {"semantic", "safety"}
        or applicable_pause is not None
        or (
            isinstance(event.get("invocation_violation"), dict)
            and event["invocation_violation"].get("kind") in {
                "invalid-composition", "unresolved-destructive-receiver",
            }
        )
    ) or (
        contract["confirmation"]["required"]
        and contract["confirmed_by"] in {"unconfirmed", "unconfirmed-proposal"}
        and effect in {"local_write", "external_write", "destructive", "unknown"}
    )
    action = (
        "allow"
        if mode == "off" or (mode == "shadow" and not hard_effect)
        else would_action
    )
    authority = "none"
    if action == "allow":
        authority = (
            "continuation"
            if continuation_authorized
            else (
                "human_grant"
                if event.get("retry_intervention_id")
                else (
                    "task"
                    if task_scope_authorized
                    and effect in {
                        "local_write", "external_write", "destructive", "unknown",
                    }
                    else "none"
                )
            )
        )
    verification_required = bool(
        verification
        and (action == "allow" or event.get("phase") == "completed")
    )
    reason_code = "event_allowed"
    decision_stage = "policy"
    if violation:
        reason_code = "policy_denied"
        if "外部写入" in violation or "副作用" in violation:
            reason_code, decision_stage = "external_effect_not_authorized", "effect"
        elif "路径" in violation or "范围" in violation:
            reason_code, decision_stage = "task_scope_denied", "scope"
        elif "破坏性" in violation or pause_class == "safety":
            reason_code, decision_stage = "safety_policy_denied", "safety"
        elif "暂停" in violation or "尚未确认" in violation:
            reason_code, decision_stage = "intent_not_executable", "intent"
    elif observation_gap:
        reason_code, decision_stage = "effect_observation_gap", "verification"
    elif uncertainty_kind in {"opaque_execution", "unclassified_read_candidate"}:
        reason_code, decision_stage = "non_material_observation", "classification"
    return Decision(
        dispatch=action,
        would_dispatch=would_action,
        lifecycle="pause" if pause and action == "deny" else "continue",
        authority=authority,
        verification="required" if verification_required else "none",
        evidence_state=(
            "gap" if observation_gap and action == "allow" else "observed"
        ),
        severity=severity,
        reason=(
            violation
            or (
                f"无法完整判定 {capability} 的副作用；已降级观察并保留审计"
                if observation_gap
                else "事件符合当前意图契约"
            )
        ),
        fingerprint=fingerprint,
        pause_class=pause_class,
        reason_code=reason_code,
        decision_stage=decision_stage,
        secondary_reasons=(
            (f"uncertainty:{uncertainty_kind}",) if uncertainty_kind else ()
        ),
    )

def _critic_inconclusive_result(summary: str) -> dict[str, Any]:
    return {
        "schema": "sulde-intent-critic-v1",
        "verdict": "inconclusive",
        "confidence": 1.0,
        "summary": summary[:2_000],
        "violated_constraints": [],
        "evidence": [],
        "next_action": "collect_evidence",
    }

def _record_critic_result_locked(
    path: Path,
    contract: dict[str, Any],
    result: dict[str, Any],
    *,
    event: dict[str, Any],
    batch_claim: dict[str, Any] | None = None,
) -> bool:
    """CAS one critic result into contract state without invoking a model."""
    if batch_claim is not None and not critic_claim_identity_present(
        contract, batch_claim
    ):
        return False
    world_current = (
        batch_claim is None
        or critic_claim_world_is_current(contract, batch_claim)
    )
    runtime = contract["runtime"]
    checkpoints = runtime.setdefault("critic_checkpoints", [])
    checkpoints.append(
        {
            "at": now_iso(),
            "event_id": event.get("event_id"),
            "batch_id": event.get("critic_batch_id"),
            "provider": event.get("provider"),
            "session_id": event.get("session_id"),
            "completed_writes": event.get("completed_writes"),
            "target_count": len(event.get("write_targets") or []),
            "verdict": result.get("verdict"),
            "confidence": result.get("confidence"),
            "evidence": result.get("evidence", [])[:5],
            "state_consistent": world_current,
        }
    )
    runtime["critic_checkpoints"] = checkpoints[-20:]
    drift = (
        world_current
        and result.get("verdict") == "drift"
        and float(result.get("confidence", 0)) >= contract["critic"]["min_confidence"]
        and bool(result.get("violated_constraints"))
        and bool(result.get("evidence"))
        and result.get("next_action") == "pause_and_clarify"
    )
    paused = False
    if drift and contract["mode"] == "enforce":
        paused = _pause_lane_locked(
            contract,
            provider=str(event.get("provider") or "unknown"),
            session_id=str(event.get("session_id") or ""),
            reason=str(result.get("summary") or "意图审查发现高置信漂移"),
            pause_class="semantic",
            event_fingerprint=str(event.get("critic_batch_id") or "")[:64],
            requires_revision=True,
            source="semantic_critic_checkpoint",
        ) is not None
    if result.get("verdict") == "inconclusive" or not world_current:
        runtime["inconclusive_outcomes"].append(
            {
                "event_id": event.get("event_id"),
                "capability": event.get("capability"),
                "target": event.get("target"),
                "provider": event.get("provider"),
                "session_id": event.get("session_id"),
                "recorded_at": now_iso(),
                "reason": (
                    "semantic checkpoint became stale while the workspace changed"
                    if not world_current
                    else str(
                        result.get("summary")
                        or "semantic checkpoint inconclusive"
                    )[:2_000]
                ),
            }
        )
        runtime["inconclusive_outcomes"] = runtime["inconclusive_outcomes"][-100:]
    if batch_claim is not None:
        settle_critic_claim(contract, batch_claim)
    _write_contract_unlocked(path, contract)
    _append_jsonl(
        audit_path(path),
        {
            "schema": "sulde-intent-critic-event-v1",
            "at": now_iso(),
            "intent_id": contract["intent_id"],
            "intent_revision": contract["revision"],
            "event_id": event.get("event_id"),
            "batch_id": event.get("critic_batch_id"),
            "provider": event.get("provider"),
            "session_id": event.get("session_id"),
            "result": result,
            "state_consistent": world_current,
            "action": (
                "pause_lane"
                if paused
                else ("superseded" if not world_current else "observe")
            ),
        },
    )
    return paused

class GuardianSession:
    """Stateful event evaluator shared by hooks and the L3 stream monitor."""

    def __init__(
        self,
        contract_path: Path,
        *,
        provider: str = "unknown",
        authoritative_memory: bool = False,
        session_id: str = "",
        hot_path: bool = False,
    ) -> None:
        self.path = contract_path
        # A normal Guardian boundary repairs only internal state for decisions
        # whose native human approval is already durable. Recovery never
        # invokes or retries the external tool that prompted the decision.
        self.unattended_reassessment = None
        if not hot_path:
            recover_native_decisions(contract_path, provider=provider, session_id=session_id)
            reconcile_obsolete_approval_requests(contract_path)
            self.unattended_reassessment = reassess_unattended_proposal(
                contract_path,
                provider=provider,
                session_id=session_id,
            )
            try:
                cancel_open_approval_requests(
                    contract_path,
                    kinds={"event"},
                    actor="event-fingerprint-approval-retirement",
                )
            except (ApprovalInvariantError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot migrate retired event approval questions: {error}"
                ) from error
        self.contract = load_contract(contract_path)
        self.provider = provider
        self.authoritative_memory = authoritative_memory
        self.session_id = session_id.strip()
        self.initial_policy_digest = policy_digest(self.contract)
        # Ordinary one-event Hooks do not own an in-memory execution snapshot,
        # so replaying an ever-growing audit here proves nothing and makes
        # latency grow linearly with workspace age. Managed runners retain the
        # full append-only integrity comparison.
        self._initial_audit_digests = (
            self._audit_digests() if authoritative_memory else []
        )
        self._appended_audit_digests: list[str] = []
        self._expected_effect_store = authoritative_store_bytes(self.path)
        self._expected_approval_store = approval_authoritative_store_bytes(
            self.path
        )
        self.findings = 0
        self.denials = 0
        self.last_observed_events: list[dict[str, Any]] = []
        self._provider_inflight: dict[str, dict[str, Any]] = {}
        self._seen_explicit_skill_starts: set[str] = set()

    def _persist(self) -> None:
        # Only settled history is bounded. A live/pending fingerprint protects
        # all its dispatch uses, including legacy records lacking a call ID.
        runtime = self.contract["runtime"]
        protected = {row.get("fingerprint") for key in ("open_events", "pending_verifications")
                     for row in runtime.get(key, []) if isinstance(row, dict)}
        uses = runtime.get("continuation_uses", [])
        runtime["continuation_uses"] = [row for index, row in enumerate(uses)
                                        if index >= len(uses) - 100 or row.get("fingerprint") in protected]
        _write_contract_unlocked(self.path, self.contract)

    @staticmethod
    def _payload_digest(payload: dict[str, Any]) -> str:
        rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    def _audit_digests(self) -> list[str]:
        path = audit_path(self.path)
        if not path.is_file():
            return []
        digests: list[str] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                return ["!invalid-jsonl"]
            if not isinstance(payload, dict):
                return ["!invalid-row"]
            digests.append(self._payload_digest(payload))
        return digests

    def _append_audit(self, payload: dict[str, Any]) -> None:
        _append_jsonl(audit_path(self.path), payload)
        if self.authoritative_memory:
            self._appended_audit_digests.append(self._payload_digest(payload))

    def observe(self, event: dict[str, Any]) -> Decision:
        event = dict(event)
        if self.session_id and not event.get("session_id"):
            event["session_id"] = self.session_id
        effect_changed = bool(
            self.authoritative_memory
            and authoritative_store_bytes(self.path) != self._expected_effect_store
        )
        approval_changed = bool(
            self.authoritative_memory
            and approval_authoritative_store_bytes(self.path)
            != self._expected_approval_store
        )
        if effect_changed or approval_changed:
            changed = []
            if effect_changed:
                changed.append("external-effect")
            if approval_changed:
                changed.append("approval")
            reason = (
                "provider modified the authoritative "
                + "/".join(changed)
                + " event store"
            )
            self.record_integrity_breach(reason)
            return Decision(
                dispatch="deny",
                would_dispatch="deny",
                lifecycle="pause",
                authority="none",
                verification="none",
                evidence_state="observed",
                severity="critical",
                reason=reason,
                fingerprint=event_fingerprint(event),
                pause_class="safety",
            )
        with contract_lock(self.path):
            if not self.authoritative_memory:
                self.contract = load_contract(self.path)
            decision = self._observe_locked(event)
        if self.authoritative_memory:
            self._expected_effect_store = authoritative_store_bytes(self.path)
            self._expected_approval_store = approval_authoritative_store_bytes(
                self.path
            )
        return decision

    def _observe_locked(self, event: dict[str, Any]) -> Decision:
        runtime = self.contract["runtime"]
        # Slow independent verifiers are run only at safe boundaries through
        # ``reconcile_pending_verifications``. They must never execute under
        # this short shared state lock. Unproved debt remains blocking here.
        _invalidate_stale_approval_receipts_locked(self.contract)
        runtime["sequence"] = int(runtime.get("sequence", 0)) + 1
        event = dict(event)
        if event.get("observation_source") == "explicit_skill_registration_stream":
            try:
                registration_contract = Path(
                    str(event.get("registration_contract") or "")
                ).expanduser().resolve()
                expected_contract = self.path.expanduser().resolve()
            except OSError:
                registration_contract = Path(".")
                expected_contract = self.path
            if registration_contract != expected_contract:
                _retag_guardian_violation(
                    event,
                    action="skill-registration-contract-mismatch",
                    target="[mismatched-intent-contract]",
                )
        if event["kind"] == "skill" and event.get("target"):
            skill_path = Path(str(event["target"])).expanduser()
            if skill_path.name == "SKILL.md" and skill_path.is_file():
                try:
                    event["skill_digest"] = hashlib.sha256(skill_path.read_bytes()).hexdigest()
                except OSError:
                    event["skill_digest"] = "unreadable"
            elif event.get("observation_source") == "explicit_skill_registration_stream":
                _retag_guardian_violation(
                    event,
                    action="skill-registration-path-invalid",
                    target="[invalid-skill-path]",
                )
        if event["kind"] == "skill" and event["phase"] == "completed":
            fingerprint = event_fingerprint(event)
            started = next(
                (
                    row for row in reversed(runtime["active_skill_frames"])
                    if isinstance(row, dict)
                    and row.get("name") == event.get("action")
                    and row.get("provider") == event.get("provider")
                    and row.get("session_id") == event.get("session_id")
                ),
                None,
            )
            if (
                started
                and started.get("skill_digest")
                and event.get("skill_digest")
                and started["skill_digest"] != event["skill_digest"]
            ):
                _retag_guardian_violation(
                    event,
                    action="skill-instructions-changed-during-use",
                    target="[changed-skill-instructions]",
                )
        event["sequence"] = runtime["sequence"]
        event["intent_id"] = self.contract["intent_id"]
        event["intent_revision"] = self.contract["revision"]
        event["task_epoch"] = self.contract["task_epoch"]
        duplicate = duplicate_host_call(runtime, event)
        if duplicate is not None:
            allowed, prior_event_id = duplicate
            replay_decision = Decision(
                dispatch="allow" if allowed else "deny", would_dispatch="allow" if allowed else "deny",
                lifecycle="continue", authority="none", verification="none", evidence_state="observed",
                severity="low" if allowed else "high", fingerprint=event_fingerprint(event),
                reason="重复宿主回调，仅记录审计" if allowed else "宿主 call identity 已使用或存在冲突，不能重新执行",
            )
            self._append_audit({"schema": "sulde-guardian-call-dedup-v1", "at": now_iso(),
                "provider": event["provider"], "session_id": event["session_id"], "call_id": event["call_id"],
                "phase": event["phase"], "dispatch": replay_decision.action,
                "prior_event_id": prior_event_id, "authority_transferred": False})
            self._persist()
            return replay_decision
        event.setdefault("runtime_generation", RUNTIME_GENERATION)
        frames = runtime["active_skill_frames"]
        lane = [
            row for row in frames
            if row["provider"] == event["provider"]
            and row["session_id"] == event["session_id"]
        ]
        event["parent_skills"] = [row["name"] for row in lane]
        (
            resource_key,
            resource_base,
            resource_context,
            resource_relation,
        ) = _effect_resource_identity(
            self.contract,
            event,
        )
        event["effect_resource_key"] = resource_key
        event["effect_resource_base"] = resource_base
        event["effect_resource_context"] = resource_context
        event["effect_resource_relation"] = resource_relation
        fingerprint = event_fingerprint(event)
        event["fingerprint"] = fingerprint
        authorized_completion = matching_authorized_completion(
            runtime["open_events"],
            event,
            fingerprint=fingerprint,
        )
        independent = event.get("independent_verification")
        if (
            event.get("phase") == "completed"
            and isinstance(independent, dict)
            and independent.get("capability")
            == "tool:git_worktree_lifecycle_verify"
        ):
            completion_index = _completion_open_event_index(
                runtime["open_events"], event, fingerprint=fingerprint,
            )
            opened = (
                runtime["open_events"][completion_index]
                if completion_index is not None
                else None
            )
            opened_typed = (
                opened.get("typed_resource")
                if isinstance(opened, dict)
                else None
            )
            sealed = (
                opened_typed.get("resource")
                if isinstance(opened_typed, dict)
                else None
            )
            receipt = independent.get("receipt")
            binding_valid = bool(
                isinstance(opened, dict)
                and isinstance(sealed, dict)
                and isinstance(receipt, dict)
                and independent.get("dispatch_event_id")
                == opened.get("event_id")
                and independent.get("resource_id")
                == sealed.get("resource_id")
                == receipt.get("resource_id")
                and receipt.get("schema")
                == "sulde-git-worktree-lifecycle-verifier-receipt-v1"
            )
            if not binding_valid:
                event.pop("independent_verification", None)
        operation_fingerprint = effect_operation_fingerprint(
            provider=str(event.get("provider") or "unknown"),
            capability=str(event.get("capability") or "unknown"),
            target=_effect_attempt_target(event),
            resource_key=resource_key,
            effect=str(event.get("effect") or "unknown"),
            arguments_digest=str(event.get("arguments_digest") or ""),
        )
        event["effect_operation_fingerprint"] = operation_fingerprint
        execution_passthrough = (
            event.get("supervision_domain") == "execution_passthrough"
            and event.get("execution_domain") in {"git", "figma"}
        )
        continuation_authority = (
            None
            if execution_passthrough
            else _continuation_authorization(self.contract, event)
        )
        if continuation_authority is not None:
            event["continuation_authority"] = continuation_authority
            if continuation_authority.get("hot_upgrade_adopted") is True:
                dispatch_verification = str(
                    continuation_authority["dispatch_verification_sha256"]
                )
                observed_verification = str(
                    continuation_authority["observed_verification_sha256"]
                )
                independent = event.get("independent_verification")
                if isinstance(independent, dict):
                    adopted_independent = json.loads(json.dumps(independent))
                    adopted_independent["evidence"] = {
                        "content": [dispatch_verification]
                    }
                    event["independent_verification"] = adopted_independent
                event["verification_sha256"] = dispatch_verification
                event["hot_upgrade_completion_adoption"] = {
                    "schema": "sulde-hot-upgrade-completion-adoption-v1",
                    "grant_id": continuation_authority["grant_id"],
                    "dispatch_fingerprint": continuation_authority[
                        "dispatch_fingerprint"
                    ],
                    "dispatch_verification_sha256": dispatch_verification,
                    "observed_verification_sha256": observed_verification,
                    "allowed_binding_drift": continuation_authority[
                        "allowed_binding_drift"
                    ],
                }
        retry_grant = None
        if event["phase"] == "started" and not execution_passthrough:
            try:
                retry_grant = retry_grant_for_event(
                    self.path,
                    fingerprint=fingerprint,
                    operation_fingerprint=operation_fingerprint,
                    provider=event["provider"],
                    session_id=event["session_id"],
                )
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot read effect retry authority: {error}"
                ) from error
            if retry_grant:
                event["retry_intervention_id"] = retry_grant["intervention_id"]
        # A native/human intervention may transfer exactly one retry to a
        # recovery session.  That one-shot effect authority does not bind the
        # session to the whole task, but it must outrank the broad unowned-lane
        # barrier or the approved recovery would be unusable.
        task_lane_blocked = (
            not execution_passthrough
            and _task_lane_blocks_material(self.contract, event)
            and retry_grant is None
            and not isinstance(event.get("human_grant_dispatch"), dict)
        )
        if authorized_completion is not None:
            decision = Decision(
                dispatch="allow", would_dispatch="allow",
                lifecycle="continue", authority="none",
                verification="required", evidence_state="observed",
                severity="info",
                reason=(
                    "完成回调与同一 provider/session/call-id 的已授权物质调用精确配对；"
                    "仅观察并验证既有执行结果，不产生新的执行权限"
                ),
                fingerprint=fingerprint,
                reason_code="authorized_dispatch_completion",
                decision_stage="completion_pairing",
            )
            blocker = None
        elif task_lane_blocked:
            decision = Decision(
                dispatch="deny", would_dispatch="deny",
                lifecycle="continue", authority="none",
                verification="none", evidence_state="observed",
                severity="high",
                reason=(
                    "当前 provider/session 尚未绑定本任务；新会话不得从 workspace "
                    "隐式继承旧 objective 或实质操作权限，需先显式续接或应用新方案"
                ),
                fingerprint=fingerprint,
            )
            blocker = None
        elif execution_passthrough:
            decision = Decision(
                dispatch="allow",
                would_dispatch="allow",
                lifecycle="continue",
                authority="none",
                verification="none",
                evidence_state="observed",
                severity="info",
                reason=(
                    f"{str(event.get('execution_domain') or '该能力').title()} 属于"
                    " Agent/宿主执行域；Guardian 仅记录调用发生，不授权、阻断或"
                    "形成效果债务"
                ),
                fingerprint=fingerprint,
                reason_code=f"{event.get('execution_domain')}_execution_passthrough",
                decision_stage="execution_domain",
                secondary_reasons=("authority:agent_and_human",),
            )
            blocker = None
        elif isinstance(event.get("human_grant_dispatch"), dict):
            try:
                blocker = material_event_blocker(self.path, event)
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot prove the external-effect barrier state: {error}"
                ) from error
            if blocker:
                decision = Decision(
                    dispatch="deny", would_dispatch="deny",
                    lifecycle="continue", authority="none",
                    verification="none", evidence_state="observed",
                    severity="critical",
                    reason="同一目标仍有未结算的实质效果；一次性授权未被执行",
                    fingerprint=fingerprint,
                    reason_code="effect_barrier_denied",
                    decision_stage="safety",
                )
            else:
                decision = Decision(
                    dispatch="allow", would_dispatch="allow",
                    lifecycle="continue", authority="human_grant",
                    verification=(
                        "required"
                        if event.get("effect") in {"external_write", "unknown"}
                        else "none"
                    ),
                    evidence_state="observed", severity="info",
                    reason="当前会话原生 Allow 已按精确绑定消费一次",
                    fingerprint=fingerprint,
                    reason_code="human_grant_consumed",
                    decision_stage="authority",
                    secondary_reasons=("default_policy_recheck:false",),
                )
            blocker = None
        elif event.get("control_plane"):
            if event.get("control_route") == "composition":
                decision = _evaluate_composition(self.contract, event, contract_path=self.path)
            elif event.get("control_route") == "invalid-composition":
                decision = Decision(
                    dispatch="deny", would_dispatch="deny",
                    lifecycle=("pause" if event.get("effect") == "destructive" and event.get("phase") == "completed" else "continue"),
                    pause_class=("safety" if event.get("effect") == "destructive" and event.get("phase") == "completed" else ""),
                    authority="none",
                    verification="none", evidence_state="observed",
                    severity="critical",
                    reason=(
                        "可信 Guardian 控制命令必须是单个精确调用；"
                        "禁止 shell 管道、顺序执行、条件执行、重定向或替换语法"
                    ),
                    fingerprint=fingerprint,
                )
            elif event.get("control_route") == "human":
                control_action = str(event.get("control_action") or "")
                if control_action in BREAK_GLASS_CONTROL_ACTIONS:
                    reason = (
                        "该恢复动作会改变持久控制状态；应先展示当前会话原生 Allow/Deny，"
                        "Allow 后仍由 Agent 执行精确动作"
                    )
                else:
                    reason = (
                        "Agent 不能用 CLI 生成或代替人类决定；人应在可读卡片中选择，"
                        "获授权后的机械执行由 Hook、Agent 或监督器完成"
                    )
                decision = Decision(
                    dispatch="deny", would_dispatch="deny",
                    lifecycle="continue", authority="none",
                    verification="none", evidence_state="observed",
                    severity="high",
                    reason=reason,
                    fingerprint=fingerprint,
                )
            elif event.get("control_route") == "native-permission-invalid":
                decision = Decision(
                    dispatch="deny", would_dispatch="deny",
                    lifecycle="continue", authority="none",
                    verification="none", evidence_state="observed",
                    severity="critical",
                    reason=(
                        "native-decision 命令结构无效；必须绑定当前 Codex provider、"
                        "session、contract、决策类型和目标"
                    ),
                    fingerprint=fingerprint,
                )
            elif event.get("control_route") == "host-callback-invalid":
                decision = Decision(
                    dispatch="deny", would_dispatch="deny",
                    lifecycle="continue", authority="none",
                    verification="none", evidence_state="observed",
                    severity="critical",
                    reason=(
                        "宿主 Hook 回调只能由 Codex/Claude 生命周期触发；"
                        "Agent 工具调用不得伪造 PermissionRequest 或其他 Hook 观察"
                    ),
                    fingerprint=fingerprint,
                )
            elif event.get("control_route") == "native-permission":
                permission_mode = str(event.get("permission_mode") or "")
                if event.get("provider") != "codex":
                    reason = "原生 PermissionRequest 决策通道仅属于当前 Codex 宿主"
                    action = "deny"
                elif permission_mode in {"dontAsk", "bypassPermissions", "plan"}:
                    reason = (
                        "当前 Codex 权限模式不会提供可验证的交互批准；"
                        "native-decision 已拒绝"
                    )
                    action = "deny"
                elif event.get("phase") == "started":
                    reason = (
                        "结构化决策命令仅通过预检；最终权限留给当前会话的 "
                        "PermissionRequest，命令在没有配对请求时会自行拒绝"
                    )
                    action = "allow"
                else:
                    reason = "原生 PermissionRequest 决策命令已由独立控制账本处理"
                    action = "allow"
                decision = Decision(
                    dispatch=("defer" if action == "deny" else "allow"),
                    would_dispatch=("defer" if action == "deny" else "allow"),
                    lifecycle="continue", authority="none",
                    verification="none", evidence_state="observed",
                    severity="info" if action == "allow" else "critical",
                    reason=reason,
                    fingerprint=fingerprint,
                )
            else:
                decision = Decision(
                    dispatch="allow", would_dispatch="allow",
                    lifecycle="continue", authority="none",
                    verification="none", evidence_state="observed",
                    severity="info",
                    reason="可信控制面命令由独立审计通道处理",
                    fingerprint=fingerprint,
                )
            blocker = None
        else:
            try:
                blocker = material_event_blocker(self.path, event)
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot prove the external-effect barrier state: {error}"
                ) from error
            if blocker:
                semantic_retry_intervention_id = (
                    _registered_semantic_retry_intervention(
                        self.contract,
                        event,
                        blocker,
                    )
                )
                if semantic_retry_intervention_id:
                    event["semantic_retry_intervention_id"] = (
                        semantic_retry_intervention_id
                    )
                    event["retry_intervention_id"] = (
                        semantic_retry_intervention_id
                    )
                    blocker = None
            if blocker:
                compensates_attempt_id = _registered_compensation_predecessor(
                    self.contract,
                    event,
                    blocker,
                )
                if compensates_attempt_id:
                    event["compensates_attempt_id"] = compensates_attempt_id
                    blocker = None
        if (
            task_lane_blocked
            or execution_passthrough
            or isinstance(event.get("human_grant_dispatch"), dict)
            or authorized_completion is not None
        ):
            pass
        elif not event.get("control_plane") and blocker:
            event["blocked_by_attempt_id"] = blocker["attempt_id"]
            if blocker.get("intervention_id"):
                event["blocked_by_intervention_id"] = blocker["intervention_id"]
            decision = Decision(
                dispatch="defer", would_dispatch="defer",
                lifecycle="continue", authority="none",
                verification="none", evidence_state="observed",
                severity="critical",
                reason=(
                    "同一目标或显式依赖链仍有无法证明或尚未验证的外部副作用；"
                    f"attempt={blocker['attempt_id']} "
                    f"intervention={blocker.get('intervention_id') or 'not-opened'}"
                ),
                fingerprint=fingerprint,
            )
        elif not event.get("control_plane"):
            decision = evaluate_event(self.contract, event, contract_path=self.path)
            conflicting_started_call = bool(
                event.get("phase") == "completed"
                and event.get("call_id")
                and any(
                    str(row.get("call_id") or "") == str(event.get("call_id") or "")
                    and (
                        str(row.get("provider") or "") != str(event.get("provider") or "")
                        or str(row.get("session_id") or "")
                        != str(event.get("session_id") or "")
                    )
                    for row in runtime.get("open_events", [])
                    if isinstance(row, dict)
                )
            )
            if (
                event.get("phase") == "completed"
                and decision.action == "deny"
                and event.get("kind") != "skill"
                and not str(event.get("capability") or "").startswith(
                    "guardian:skill-"
                )
                and not conflicting_started_call
            ):
                decision = replace(
                    decision,
                    dispatch="allow",
                    lifecycle="continue",
                    authority="none",
                    evidence_state="gap",
                    pause_class="",
                    reason=(
                        "宿主已完成该动作；执行前策略结果仅保留为审计证据："
                        + decision.reason
                    ),
                    decision_stage="post_execution_observation",
                )
        if decision.would_action == "deny":
            self.findings += 1
        observe_probe(runtime, event, decision)
        if decision.action == "deny":
            self.denials += 1
        metrics = runtime["supervision_metrics"]
        metrics["allowed" if decision.action == "allow" else "denied"] += 1
        if decision.observation_gap or event.get("supervision_mode") == "degraded_observe":
            metrics["degraded_observe"] += 1
        if (
            decision.action == "deny"
            and not decision.pause
            and "范围" in decision.reason
        ):
            metrics["scope_review"] += 1
        if decision.pause_class == "safety":
            metrics["hard_safety_blocks"] += 1

        if (
            event["phase"] == "started"
            and decision.action == "allow"
            and continuation_authority is not None
        ):
            runtime["continuation_uses"].append(
                {
                    "schema": CONTINUATION_USE_SCHEMA,
                    "grant_id": continuation_authority["grant_id"],
                    "profile_id": continuation_authority["profile_id"],
                    "authority": continuation_authority["authority"],
                    "fingerprint": fingerprint,
                    "event_id": event["event_id"],
                    "provider": event["provider"],
                    "session_id": event["session_id"],
                    "call_id": str(event.get("call_id") or ""),
                    "kind": event["kind"],
                    "capability": event["capability"],
                    "target": _effect_attempt_target(event),
                    "effect": event["effect"],
                    "verification_kind": str(
                        event.get("verification_kind") or "unsupported"
                    ),
                    "verification_sha256": str(
                        event.get("verification_sha256") or ""
                    ),
                    "memory_verification": event.get("memory_verification"),
                    "task_epoch": self.contract["task_epoch"],
                    "runtime_generation": str(
                        event.get("runtime_generation") or RUNTIME_GENERATION
                    ),
                    "used_at": event["at"],
                }
            )
            if fingerprint not in runtime["authorized_events"]:
                runtime["authorized_events"].append(fingerprint)

        if event["kind"] == "skill" and decision.action == "allow":
            name = str(event["action"])
            if event["phase"] == "started":
                duplicate = any(
                    row["name"] == name
                    and row["provider"] == event["provider"]
                    and row["session_id"] == event["session_id"]
                    for row in frames
                )
                if not duplicate:
                    frames.append(
                        {
                            "name": name,
                            "provider": event["provider"],
                            "session_id": event["session_id"],
                            "started_sequence": event["sequence"],
                            "skill_digest": str(event.get("skill_digest") or ""),
                            "runtime_generation": str(
                                event.get("runtime_generation") or RUNTIME_GENERATION
                            ),
                            "task_epoch": self.contract["task_epoch"],
                        }
                    )
            elif event["phase"] == "completed":
                for index in range(len(frames) - 1, -1, -1):
                    row = frames[index]
                    if (
                        row["name"] == name
                        and row["provider"] == event["provider"]
                        and row["session_id"] == event["session_id"]
                    ):
                        frames.pop(index)
                        break
            runtime["active_skill_frames"] = frames[-50:]
            runtime["active_skills"] = list(dict.fromkeys(row["name"] for row in frames))

        if (
            decision.pause
            and (
                event["phase"] == "started"
                or (
                    event["phase"] == "completed"
                    and (
                        event["kind"] == "skill"
                        or str(event.get("capability") or "").startswith(
                            "guardian:skill-"
                        )
                    )
                )
            )
        ):
            requires_revision = (
                self.contract["confirmation"]["required"]
                and self.contract["confirmed_by"] in {
                    "unconfirmed", "unconfirmed-proposal",
                }
            )
            if str(event.get("session_id") or "").strip():
                _pause_lane_locked(
                    self.contract,
                    provider=str(event.get("provider") or self.provider),
                    session_id=str(event.get("session_id") or ""),
                    reason=decision.reason,
                    pause_class=decision.pause_class or "semantic",
                    event_fingerprint=decision.fingerprint,
                    requires_revision=requires_revision,
                    source="tool_decision",
                )
            else:
                _pause_global_locked(
                    self.contract,
                    reason=decision.reason,
                    pause_class=decision.pause_class or "semantic",
                    event_fingerprint=decision.fingerprint,
                    requires_revision=requires_revision,
                )

        attempt_id = ""
        tracks_external_effect = (
            event["phase"] == "started"
            and decision.action == "allow"
            and decision.verification_required
            and (
                event["effect"] == "external_write"
                or (
                    event["kind"] == "mcp"
                    and event["effect"] != "read"
                    and event.get("uncertainty_kind")
                    != "unclassified_read_candidate"
                )
                or (
                    continuation_authority is not None
                    and event["effect"] == "local_write"
                )
            )
        )
        if tracks_external_effect:
            call_identity = str(event.get("call_id") or f"sequence:{event['sequence']}")
            effect_target = _effect_attempt_target(event)
            try:
                attempt = begin_attempt(
                    self.path,
                    intent_id=self.contract["intent_id"],
                    intent_revision=self.contract["revision"],
                    fingerprint=decision.fingerprint,
                    operation_fingerprint=operation_fingerprint,
                    source_event_id=event["event_id"],
                    capability=event["capability"],
                    target=effect_target,
                    resource_key=resource_key,
                    resource_base=resource_base or None,
                    resource_context=resource_context,
                    effect=event["effect"],
                    provider=event["provider"],
                    session_id=event["session_id"],
                    task_id=(
                        self.contract["intent_id"]
                        if str(self.contract["intent_id"]).startswith("l3:")
                        else ""
                    ),
                    idempotency_key=(
                        f"dispatch:{event['provider']}:{event['session_id']}:"
                        f"{call_identity}:{decision.fingerprint}"
                    ),
                    operation_arguments_digest=str(
                        event.get("arguments_digest") or ""
                    ),
                    verification_kind=str(event.get("verification_kind") or "unsupported"),
                    verification_sha256=str(event.get("verification_sha256") or ""),
                    compensates_attempt_id=str(
                        event.get("compensates_attempt_id") or ""
                    ),
                    semantic_retry_intervention_id=str(
                        event.get("semantic_retry_intervention_id") or ""
                    ),
                )
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot persist external effect dispatch: {error}"
                ) from error
            attempt_id = str(attempt["attempt_id"])
            event["effect_attempt_id"] = attempt_id

        open_events = runtime["open_events"]
        completed_open: dict[str, Any] | None = None
        if (
            event["phase"] == "started"
            and decision.action == "allow"
            and not event.get("control_plane")
            and (
                event["effect"] in {"local_write", "external_write"}
                or decision.verification_required
            )
        ):
            open_events.append(
                {
                    "sequence": event["sequence"],
                    "task_epoch": self.contract["task_epoch"],
                    "runtime_generation": str(
                        event.get("runtime_generation") or RUNTIME_GENERATION
                    ),
                    "fingerprint": decision.fingerprint,
                    "operation_fingerprint": operation_fingerprint,
                    "event_id": event["event_id"],
                    "kind": event["kind"],
                    "capability": event["capability"],
                    "target": _effect_attempt_target(event),
                    "effect_resource_key": resource_key,
                    "effect_resource_base": resource_base,
                    "effect_resource_context": resource_context,
                    "effect_resource_relation": resource_relation,
                    "effect": event["effect"],
                    "skill_digest": event.get("skill_digest"),
                    "provider": event["provider"],
                    "session_id": event["session_id"],
                    "call_id": event.get("call_id"),
                    "attempt_id": attempt_id,
                    "verification_kind": event.get("verification_kind") or "unsupported",
                    "verification_sha256": event.get("verification_sha256") or "",
                    "continuation_grant_id": (
                        continuation_authority.get("grant_id")
                        if continuation_authority is not None
                        else ""
                    ),
                    "continuation_profile_id": (
                        continuation_authority.get("profile_id")
                        if continuation_authority is not None
                        else ""
                    ),
                    "typed_resource": (
                        json.loads(json.dumps(event["typed_resource"]))
                        if isinstance(event.get("typed_resource"), dict)
                        else None
                    ),
                    "started_at": event["at"],
                    "memory_verification": event.get("memory_verification"),
                }
            )
            runtime["open_events"] = open_events
        elif event["phase"] == "completed":
            completed_index = _completion_open_event_index(
                open_events,
                event,
                fingerprint=decision.fingerprint,
            )
            if completed_index is not None:
                completed_open = open_events[completed_index]
                runtime["open_events"] = [
                    row
                    for index, row in enumerate(open_events)
                    if index != completed_index
                ]
                if completed_open.get("call_id"):
                    runtime.setdefault("completed_calls", []).append({
                        key: completed_open.get(key) for key in (
                            "event_id", "call_id", "provider", "session_id", "task_epoch", "kind",
                            "capability", "effect", "target", "verification_kind", "verification_sha256",
                        )
                    })
                    runtime["completed_calls"] = runtime["completed_calls"][-2048:]

        if (
            event["phase"] == "completed"
            and completed_open is None
            and decision.observation_gap
            and decision.would_action == "deny"
            and event.get("effect")
            in {"local_write", "external_write", "destructive"}
        ):
            runtime["pre_execution_gaps"].append(
                {
                    "at": event["at"],
                    "provider": event["provider"],
                    "session_id": event["session_id"],
                    "runtime_generation": str(
                        event.get("runtime_generation") or RUNTIME_GENERATION
                    ),
                    "event_id": event["event_id"],
                    "capability": event["capability"],
                    "effect": event["effect"],
                    "target": _effect_attempt_target(event),
                    "reason_code": decision.reason_code,
                }
            )
            runtime["pre_execution_gaps"] = runtime["pre_execution_gaps"][-100:]

        _advance_material_sequence_for_allowed_event(
            runtime,
            event,
            decision,
            matched_started_event=completed_open is not None,
        )

        if (
            event["phase"] == "completed"
            and event["effect"] == "local_write"
            and event.get("success") is not False
        ):
            runtime["local_write_completions"] += 1
            try:
                record_critic_local_write(self.contract, event)
            except CriticCheckpointError as error:
                raise IntentGuardianError(str(error)) from error

        if event["phase"] == "completed" and decision.verification_required:
            completed_attempt_id = str((completed_open or {}).get("attempt_id") or "")
            if not completed_attempt_id:
                call_identity = str(event.get("call_id") or f"sequence:{event['sequence']}")
                effect_target = _effect_attempt_target(event)
                try:
                    observed_attempt = begin_attempt(
                        self.path,
                        intent_id=self.contract["intent_id"],
                        intent_revision=self.contract["revision"],
                        fingerprint=decision.fingerprint,
                        operation_fingerprint=operation_fingerprint,
                        source_event_id=event["event_id"],
                        capability=event["capability"],
                        target=effect_target,
                        resource_key=resource_key,
                        resource_base=resource_base or None,
                        resource_context=resource_context,
                        effect=event["effect"],
                        provider=event["provider"],
                        session_id=event["session_id"],
                        task_id=(
                            self.contract["intent_id"]
                            if str(self.contract["intent_id"]).startswith("l3:")
                            else ""
                        ),
                        idempotency_key=(
                            f"completion-gap:{event['provider']}:{event['session_id']}:"
                            f"{call_identity}:{decision.fingerprint}"
                        ),
                        observation_gap=True,
                        operation_arguments_digest=str(
                            event.get("arguments_digest") or ""
                        ),
                        verification_kind=str(event.get("verification_kind") or "unsupported"),
                        verification_sha256=str(event.get("verification_sha256") or ""),
                    )
                except (InterventionError, OSError, UnicodeError) as error:
                    raise IntentGuardianError(
                        f"cannot persist unmatched external completion: {error}"
                    ) from error
                completed_attempt_id = str(observed_attempt["attempt_id"])
            try:
                completed_target = _effect_attempt_target(event)
                if completed_target:
                    current_attempt = load_intervention_projection(self.path).get(
                        "attempts", {}
                    ).get(completed_attempt_id)
                    if not isinstance(current_attempt, dict):
                        raise IntentGuardianError(
                            "cannot reload external effect identity before completion"
                        )
                    lifecycle_completion = bool(
                        isinstance(event.get("typed_resource"), dict)
                        and event["typed_resource"].get("kind")
                        == "git_worktree_lifecycle"
                        and event["typed_resource"].get("status") == "completion"
                    )
                    if (
                        completed_target == current_attempt.get("target")
                        and not lifecycle_completion
                    ):
                        resolve_attempt_target(
                            self.path,
                            completed_attempt_id,
                            target=completed_target,
                        )
                    else:
                        resolve_attempt_target(
                            self.path,
                            completed_attempt_id,
                            target=completed_target,
                            resource_key=resource_key,
                            resource_base=resource_base or None,
                            resource_context=resource_context,
                            operation_fingerprint=operation_fingerprint,
                            operation_arguments_digest=str(
                                event.get("arguments_digest") or ""
                            ),
                            verification_kind=str(
                                event.get("verification_kind") or "unsupported"
                            ),
                            verification_sha256=str(
                                event.get("verification_sha256") or ""
                            ),
                            expected_target_sha256=str(
                                current_attempt.get("target_sha256") or ""
                            ),
                            expected_resource_sha256=str(
                                current_attempt.get("resource_sha256") or ""
                            ),
                            expected_operation_fingerprint=str(
                                current_attempt.get("operation_fingerprint") or ""
                            ),
                        )
                effect_attempt = mark_attempt_result(
                    self.path,
                    completed_attempt_id,
                    success=event.get("success"),
                    reason=(
                        "observable completion callback reported failure"
                        if event.get("success") is False
                        else "observable completion callback returned"
                    ),
                )
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot persist external completion outcome: {error}"
                ) from error
            event["effect_attempt_id"] = completed_attempt_id
            pending = runtime["pending_verifications"]
            pending_row = {
                "attempt_id": completed_attempt_id,
                "effect": event["effect"],
                "task_epoch": self.contract["task_epoch"],
                "runtime_generation": str(
                    event.get("runtime_generation") or RUNTIME_GENERATION
                ),
                "fingerprint": decision.fingerprint,
                "capability": event["capability"],
                "target": effect_attempt.get("target") or completed_target,
                "provider": event["provider"],
                "session_id": event["session_id"],
                "created_at": now_iso(),
                "memory_verification": (completed_open or {}).get("memory_verification") or event.get("memory_verification"),
                "outcome_unknown": effect_attempt["state"] == "unknown",
                "verification_kind": effect_attempt.get("verification_kind") or "unsupported",
                "verification_sha256": effect_attempt.get("verification_sha256") or "",
                "continuation_grant_id": str(
                    (continuation_authority or {}).get("grant_id")
                    or (completed_open or {}).get("continuation_grant_id")
                    or ""
                ),
                "continuation_profile_id": str(
                    (continuation_authority or {}).get("profile_id")
                    or (completed_open or {}).get("continuation_profile_id")
                    or ""
                ),
            }
            independent_receipt = (
                event.get("independent_verification", {}).get("receipt")
                if isinstance(event.get("independent_verification"), dict)
                else None
            )
            if isinstance(independent_receipt, dict):
                pending_row["independent_verifier_status"] = str(
                    independent_receipt.get("status") or "failed"
                )
                pending_row["verifier_receipt_sha256"] = str(
                    independent_receipt.get("receipt_sha256") or ""
                )
            continuation_grant_id = pending_row["continuation_grant_id"]
            if continuation_grant_id:
                grant_snapshot = next(
                    (
                        grant
                        for grant in self.contract.get("continuation", {}).get(
                            "grants", []
                        )
                        if isinstance(grant, dict)
                        and grant.get("grant_id") == continuation_grant_id
                    ),
                    None,
                )
                if grant_snapshot is not None:
                    pending_row["continuation_grant"] = json.loads(
                        json.dumps(grant_snapshot)
                    )
            verified_attempts: list[dict[str, Any]] = []
            independent = event.get("independent_verification")
            trusted_independent_verifier = (
                isinstance(independent, dict)
                and (
                    (
                        independent.get("capability") == "mcp:sulde_kb:memory_graph"
                        and independent.get("source") == "local_memory_db_read"
                    )
                    or (
                        independent.get("capability")
                        == "tool:codex_plugin_install_verify"
                        and independent.get("source") == "local_codex_install_read"
                    )
                    or (
                        independent.get("capability")
                        == "tool:codex_plugin_cachebuster_verify"
                        and independent.get("source")
                        == "local_codex_cachebuster_read"
                    )
                    or (
                        independent.get("capability")
                        == "tool:git_worktree_lifecycle_verify"
                        and independent.get("source")
                        == "local_git_worktree_lifecycle_read"
                        and isinstance(independent.get("receipt"), dict)
                        and independent["receipt"].get("status") == "passed"
                    )
                )
            )
            if (
                effect_attempt["state"] == "verifying"
                and trusted_independent_verifier
                and isinstance(independent.get("evidence"), dict)
            ):
                try:
                    verified_attempts = verify_from_read(
                        self.path,
                        provider=event["provider"],
                        session_id=event["session_id"],
                        capability=str(independent["capability"]),
                        target=str(effect_attempt.get("target") or completed_target),
                        resource_key=str(effect_attempt.get("resource_key") or resource_key),
                        resource_base=(
                            str(effect_attempt.get("resource_base") or resource_base)
                            or None
                        ),
                        resource_context=(
                            effect_attempt.get("resource_context")
                            if isinstance(effect_attempt.get("resource_context"), dict)
                            else resource_context
                        ),
                        verification_event_id=event["event_id"],
                        explicit_attempt_id=completed_attempt_id,
                        evidence=independent["evidence"],
                    )
                except (InterventionError, OSError, UnicodeError) as error:
                    raise IntentGuardianError(
                        f"cannot persist independent local verification: {error}"
                    ) from error
            broker_settlement = settle_matching_human_grant(
                self.path,
                effect_attempt,
                event,
                verification_passed=bool(verified_attempts),
            )
            if broker_settlement is not None:
                event["human_grant_settlement"] = {
                    "schema": "sulde-human-grant-settlement-observation-v1",
                    "status": broker_settlement.get("status"),
                    "transaction_id": broker_settlement.get("transaction_id"),
                }
            if verified_attempts:
                compensated_attempt_ids = {
                    str(row.get("compensates_attempt_id") or "")
                    for row in verified_attempts
                    if row.get("compensates_attempt_id")
                }
                runtime["pending_verifications"] = [
                    row
                    for row in pending
                    if not isinstance(row, dict)
                    or row.get("attempt_id")
                    not in {completed_attempt_id, *compensated_attempt_ids}
                ]
                verified_effects = runtime["verified_effects"]
                verified_effects.append(
                    {
                        "attempt_id": completed_attempt_id,
                        "write_fingerprint": decision.fingerprint,
                        "write_capability": event["capability"],
                        "target": effect_attempt.get("target") or completed_target,
                        "verified_by_event": event["event_id"],
                        "verified_by_capability": independent["capability"],
                        "verified_at": event["at"],
                        "verification_source": "system_verification",
                        "evidence_source": independent["source"],
                        "compensates_attempt_ids": sorted(
                            compensated_attempt_ids
                        ),
                    }
                )
                runtime["verified_effects"] = verified_effects[-50:]
            else:
                replaced = False
                for index, row in enumerate(pending):
                    if isinstance(row, dict) and row.get("attempt_id") == completed_attempt_id:
                        pending[index] = pending_row
                        replaced = True
                        break
                if not replaced:
                    pending.append(pending_row)
            completed_authorizations = {
                decision.fingerprint,
                str(
                    (continuation_authority or {}).get("dispatch_fingerprint")
                    or ""
                ),
            }
            runtime["authorized_events"] = [
                value
                for value in runtime["authorized_events"]
                if value not in completed_authorizations
            ]
        elif (
            event["phase"] == "completed"
            and event["effect"] == "read"
            and _read_proof_target(event)
            and event.get("success") is not False
        ):
            pending = runtime["pending_verifications"]
            try:
                verified_attempts = verify_from_read(
                    self.path,
                    provider=event["provider"],
                    session_id=event["session_id"],
                    capability=event["capability"],
                    target=_read_proof_target(event),
                    resource_key=resource_key,
                    resource_base=resource_base or None,
                    resource_context=resource_context,
                    verification_event_id=event["event_id"],
                    explicit_attempt_id=str(event.get("verification_for") or ""),
                    evidence=(
                        event.get("verification_evidence")
                        if isinstance(event.get("verification_evidence"), dict)
                        else {}
                    ),
                )
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot persist independent verification: {error}"
                ) from error
            verified_ids = {row["attempt_id"] for row in verified_attempts}
            compensated_by = {
                str(row.get("compensates_attempt_id")): str(row["attempt_id"])
                for row in verified_attempts
                if row.get("compensates_attempt_id")
            }
            compensated_ids = set(compensated_by)
            verified = [
                row for row in pending
                if isinstance(row, dict) and row.get("attempt_id") in verified_ids
            ]
            compensated = [
                row for row in pending
                if isinstance(row, dict)
                and row.get("attempt_id") in compensated_ids
            ]
            runtime["pending_verifications"] = [
                row
                for row in pending
                if not isinstance(row, dict)
                or row.get("attempt_id") not in verified_ids | compensated_ids
            ]
            evidence = runtime["verified_effects"]
            for row in verified:
                evidence.append(
                    {
                        "attempt_id": row.get("attempt_id"),
                        "write_fingerprint": row.get("fingerprint"),
                        "write_capability": row.get("capability"),
                        "target": row.get("target"),
                        "verified_by_event": event["event_id"],
                        "verified_by_capability": event["capability"],
                        "verified_at": event["at"],
                        "verification_source": "system_verification",
                    }
                )
            for row in compensated:
                evidence.append(
                    {
                        "attempt_id": row.get("attempt_id"),
                        "write_fingerprint": row.get("fingerprint"),
                        "write_capability": row.get("capability"),
                        "target": row.get("target"),
                        "compensated_by_attempt_id": compensated_by.get(
                            str(row.get("attempt_id") or "")
                        ),
                        "verified_by_event": event["event_id"],
                        "verified_by_capability": event["capability"],
                        "verified_at": event["at"],
                        "verification_source": "system_compensation",
                        "state_preserved": "unknown",
                    }
                )
            runtime["verified_effects"] = evidence[-50:]

        if (
            event["phase"] == "completed"
            and event.get("success") is False
            and not execution_passthrough
            and (
                decision.verification_required
                or event["effect"] in {"destructive", "unknown"}
            )
        ):
            outcomes = runtime["inconclusive_outcomes"]
            outcomes.append(
                {
                    "event_id": event["event_id"],
                    "fingerprint": decision.fingerprint,
                    "capability": event["capability"],
                    "target": (
                        _effect_attempt_target(event)
                        if decision.verification_required
                        else _read_proof_target(event)
                    ),
                    "attempt_id": event.get("effect_attempt_id"),
                    "recorded_at": now_iso(),
                    "reason": "observable completion reported failure; side-effect outcome remains unknown until independent evidence",
                }
            )
            runtime["inconclusive_outcomes"] = outcomes[-100:]

        self._persist()
        self._append_audit(
            {
                "schema": EVENT_SCHEMA,
                "event": event,
                "decision": {
                    "schema": "sulde-intent-decision-v2",
                    "dispatch": decision.dispatch,
                    "would_dispatch": decision.would_dispatch,
                    "lifecycle": decision.lifecycle,
                    "authority": decision.authority,
                    "verification": decision.verification,
                    "evidence_state": decision.evidence_state,
                    "action": decision.action,
                    "would_action": decision.would_action,
                    "severity": decision.severity,
                    "reason": decision.reason,
                    "fingerprint": decision.fingerprint,
                    "verification_required": decision.verification_required,
                    "awaiting_human": decision.awaiting_human,
                    "reason_code": decision.reason_code,
                    "decision_stage": decision.decision_stage,
                    "secondary_reasons": list(decision.secondary_reasons),
                },
                "contract": {
                    "intent_id": self.contract["intent_id"],
                    "revision": self.contract["revision"],
                    "mode": self.contract["mode"],
                    "status": self.contract["status"],
                },
            },
        )
        return decision

    def observe_provider_line(self, line: str) -> Decision | None:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(record, dict):
            return None
        events = normalize_provider_events(record, provider=self.provider)
        if self.session_id:
            for event in events:
                if not event.get("session_id"):
                    event["session_id"] = self.session_id
        if self.provider == "claude" and record.get("type") == "user":
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            content = message.get("content") if isinstance(message.get("content"), list) else []
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                call_id = str(block.get("tool_use_id") or "")
                started = self._provider_inflight.pop(call_id, None)
                if started:
                    completed = dict(started)
                    completed["phase"] = "completed"
                    completed["at"] = now_iso()
                    completed["success"] = not bool(block.get("is_error"))
                    completed["result_target"] = (
                        _response_target(block.get("content"))
                        or completed.get("result_target")
                        or completed.get("target")
                    )
                    completed["verification_evidence"] = _read_verification_evidence(
                        block.get("content")
                    )
                    events.append(completed)
        filtered_events = []
        for event in events:
            call_id = str(event.get("call_id") or "")
            if (
                event.get("observation_source") == "explicit_skill_registration_stream"
                and event.get("registration_command") == "skill-start"
            ):
                marker = call_id or str(event.get("event_id") or "")
                if marker in self._seen_explicit_skill_starts:
                    continue
                self._seen_explicit_skill_starts.add(marker)
            if call_id and event["phase"] == "started":
                self._provider_inflight[call_id] = dict(event)
            filtered_events.append(event)
        self.last_observed_events = filtered_events
        decisions = [self.observe(event) for event in filtered_events]
        return next(
            (decision for decision in decisions if decision.action == "deny"),
            decisions[-1] if decisions else None,
        )

    def record_critic(
        self,
        result: dict[str, Any],
        *,
        event: dict[str, Any],
        batch_claim: dict[str, Any] | None = None,
    ) -> bool:
        """Persist a critic checkpoint and pause only on strong evidenced drift."""
        with contract_lock(self.path):
            if not self.authoritative_memory:
                self.contract = load_contract(self.path)
            paused = _record_critic_result_locked(
                self.path,
                self.contract,
                result,
                event=event,
                batch_claim=batch_claim,
            )
            if paused:
                self.findings += 1
                self.denials += 1
            return paused

    def unchanged_policy(self) -> bool:
        return policy_digest(self.contract) == self.initial_policy_digest

    def integrity_ok(self) -> bool:
        try:
            disk = load_contract(self.path)
            contract_ok = json.dumps(disk, ensure_ascii=False, sort_keys=True) == json.dumps(
                self.contract,
                ensure_ascii=False,
                sort_keys=True,
            )
            audit_ok = self._audit_digests() == [
                *self._initial_audit_digests,
                *self._appended_audit_digests,
            ]
            effect_ok = authoritative_store_bytes(self.path) == self._expected_effect_store
            approval_ok = (
                approval_authoritative_store_bytes(self.path)
                == self._expected_approval_store
            )
            return contract_ok and audit_ok and effect_ok and approval_ok
        except (
            IntentGuardianError,
            InterventionError,
            ApprovalInvariantError,
            OSError,
            UnicodeError,
        ):
            return False

    def record_integrity_breach(self, reason: str) -> None:
        """Restore authoritative state and persist a fail-closed pause."""
        if not self.authoritative_memory:
            raise IntentGuardianError("integrity breach recovery requires authoritative-memory mode")
        runtime = self.contract["runtime"]
        runtime["integrity_breaches"].append({"at": now_iso(), "reason": reason[:2_000]})
        runtime["integrity_breaches"] = runtime["integrity_breaches"][-20:]
        _pause_global_locked(
            self.contract,
            reason=reason,
            pause_class="safety",
        )
        restore_authoritative_store(self.path, self._expected_effect_store)
        restore_approval_authoritative_store(
            self.path, self._expected_approval_store
        )
        with contract_lock(self.path):
            self._persist()
        self._append_audit(
            {
                "schema": "sulde-guardian-integrity-breach-v1",
                "at": now_iso(),
                "intent_id": self.contract["intent_id"],
                "intent_revision": self.contract["revision"],
                "reason": reason[:2_000],
                "action": "pause_and_restore_authoritative_state",
            }
        )
        self._expected_effect_store = authoritative_store_bytes(self.path)
        self._expected_approval_store = approval_authoritative_store_bytes(
            self.path
        )

    def pause_for_correction(self, intervention_ids: Iterable[str]) -> None:
        """Persist a managed-run pause initiated by the correction control plane."""
        identifiers = sorted(
            {
                str(value)
                for value in intervention_ids
                if str(value).startswith("cor-")
            }
        )
        if not identifiers:
            raise IntentGuardianError(
                "managed correction pause requires an intervention id"
            )
        if self.authoritative_memory and not self.integrity_ok():
            raise IntentGuardianError(
                "intent state changed before the managed correction pause"
            )
        if self.session_id:
            _pause_lane_locked(
                self.contract,
                provider=self.provider,
                session_id=self.session_id,
                reason="用户纠正已在受管运行边界触发安全中断",
                pause_class="user",
                source="managed_correction",
            )
        else:
            _pause_global_locked(
                self.contract,
                reason="用户纠正已在受管运行边界触发安全中断",
                pause_class="user",
            )
        with contract_lock(self.path):
            self._persist()
        self._append_audit(
            {
                "schema": "sulde-correction-pause-v1",
                "at": now_iso(),
                "intent_id": self.contract["intent_id"],
                "intent_revision": self.contract["revision"],
                "intervention_ids": identifiers,
                "action": "pause_managed_run",
            }
        )

    def finalize_lane(
        self,
        *,
        critic_runner: Callable[..., dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Reconcile this managed provider lane before computing terminal state."""
        if self.authoritative_memory and not self.integrity_ok():
            raise IntentGuardianError(
                "intent contract or audit changed before managed lane finalization"
            )
        lane = self.session_id or f"workspace:{workspace_key(Path(self.contract['workspace_root']))}"
        result = _finalize_lane(self.path, host=self.provider, session_id=lane)
        result["critic"] = run_semantic_critic_checkpoint(
            self.path,
            host=self.provider,
            session_id=lane,
            critic_runner=critic_runner,
        )
        self._expected_effect_store = authoritative_store_bytes(self.path)
        self._expected_approval_store = approval_authoritative_store_bytes(
            self.path
        )
        self.contract = load_contract(self.path)
        if self.authoritative_memory:
            self._initial_audit_digests = self._audit_digests()
            self._appended_audit_digests = []
        return result

    def summary(self) -> dict[str, Any]:
        if not self.authoritative_memory:
            self.contract = load_contract(self.path)
        runtime = self.contract["runtime"]
        try:
            effect_truth = intervention_summary(self.path)
            effect_projection = load_intervention_projection(self.path)
            correction_truth = correction_intervention_summary(self.path)
            approval_truth = approval_pair_summary(self.path)
        except (
            InterventionError,
            CorrectionInterventionError,
            ApprovalInvariantError,
            OSError,
            UnicodeError,
        ) as error:
            raise IntentGuardianError(
                f"cannot replay intervention truth: {error}"
            ) from error
        current_epoch = self.contract["task_epoch"]
        current_pending = list(runtime["pending_verifications"])
        blocking = blocking_attempts(effect_projection)
        current_unknown = sum(
            1 for row in blocking if row.get("state") == "unknown"
        )
        current_interventions_open = sum(
            1
            for row in effect_projection["interventions"].values()
            if row.get("status") in {"open", "acknowledged"}
            and not is_legacy_git_control_attempt(
                effect_projection["attempts"].get(
                    str(row.get("attempt_id") or ""), {}
                )
            )
        )
        applicable_pause = _pause_state(
            self.contract,
            provider=self.provider,
            session_id=self.session_id,
        )
        effective_status = (
            "paused"
            if applicable_pause is not None
            else "active"
            if (
                self.contract["status"] == "paused"
                and self.contract["runtime"].get("pause_scope") == "lane"
            )
            else self.contract["status"]
        )
        return {
            "schema": "sulde-guardian-summary-v1",
            "intent_id": self.contract["intent_id"],
            "revision": self.contract["revision"],
            "task_epoch": current_epoch,
            "runtime_generation": RUNTIME_GENERATION,
            "mode": self.contract["mode"],
            "status": effective_status,
            "contract_status": self.contract["status"],
            "pause_scope": (
                str(applicable_pause.get("scope"))
                if applicable_pause is not None
                else ""
            ),
            "sequence": runtime["sequence"],
            "findings": self.findings,
            "denials": self.denials,
            "active_skills": len(runtime["active_skill_frames"]),
            "active_skill_frames": runtime["active_skill_frames"],
            "open_events": len(runtime["open_events"]),
            "pending_verifications": len(current_pending),
            "historical_pending_verifications": 0,
            "inconclusive_outcomes": len(runtime["inconclusive_outcomes"]),
            "pre_execution_gaps": len(runtime["pre_execution_gaps"]),
            "effect_attempts": effect_truth["attempts"],
            "effect_attempts_by_state": effect_truth["attempts_by_state"],
            "effect_unknown": current_unknown,
            "historical_effect_unknown": max(
                0,
                effect_truth["attempts_by_state"].get("unknown", 0)
                - current_unknown,
            ),
            "interventions_open": current_interventions_open,
            "historical_interventions_open": 0,
            "intervention_oldest_open_at": effect_truth["oldest_open_at"],
            "correction_interventions": correction_truth["interventions"],
            "correction_interventions_by_state": correction_truth["by_state"],
            "corrections_open": correction_truth["open"],
            "corrections_queued": correction_truth["queued"],
            "approval_requests": approval_truth["requests"],
            "approvals_open": approval_truth["open"],
            "approvals_reassess_due": approval_truth["reassess_due"],
            "approval_outcomes": approval_truth["by_outcome"],
            "unattended_reassessment": self.unattended_reassessment,
            "authorized_events": len(runtime["authorized_events"]),
            "supervision_metrics": dict(runtime["supervision_metrics"]),
            "pending_proposal": bool(runtime["pending_proposal_digest"]),
            "policy_unchanged": self.unchanged_policy(),
            "integrity_ok": self.integrity_ok(),
            "integrity_breaches": len(runtime["integrity_breaches"]),
            "audit_path": str(audit_path(self.path)),
        }

def _finalize_lane(path: Path, *, host: str, session_id: str) -> dict[str, Any]:
    """Reconcile one provider/session lane at a safe turn or task boundary."""
    interrupted: list[dict[str, Any]] = []
    closed_skills: list[str] = []
    intervention_ids: list[str] = []
    reconciled_effects: list[dict[str, Any]] = []
    with contract_lock(path):
        contract = load_contract(path)
        _invalidate_stale_approval_receipts_locked(contract)
        runtime = contract["runtime"]
        _reconcile_read_only_effect_debt_locked(path, contract)
        if not session_id:
            session_id = f"workspace:{workspace_key(Path(contract['workspace_root']))}"

        def same_lane(row: dict[str, Any]) -> bool:
            return (
                str(row.get("provider") or "unknown") == host
                and str(row.get("session_id") or "") == session_id
            )

        remaining_events = []
        for row in runtime["open_events"]:
            if isinstance(row, dict) and same_lane(row):
                interrupted.append(row)
            else:
                remaining_events.append(row)
        runtime["open_events"] = remaining_events

        interrupted_fingerprints = {
            str(row.get("fingerprint") or "") for row in interrupted
        }
        runtime["authorized_events"] = [
            fingerprint for fingerprint in runtime["authorized_events"]
            if fingerprint not in interrupted_fingerprints
        ]
        pending = runtime["pending_verifications"]
        for row in interrupted:
            fingerprint = str(row.get("fingerprint") or "")
            if row.get("effect") == "external_write" or (
                row.get("kind") == "mcp" and row.get("effect") != "read"
            ):
                attempt_id = str(row.get("attempt_id") or "")
                try:
                    if not attempt_id:
                        observed = begin_attempt(
                            path,
                            intent_id=contract["intent_id"],
                            intent_revision=contract["revision"],
                            fingerprint=fingerprint,
                            operation_fingerprint=str(
                                row.get("operation_fingerprint") or ""
                            ),
                            source_event_id=str(row.get("event_id") or ""),
                            capability=str(row.get("capability") or "unknown"),
                            target=str(row.get("target") or ""),
                            resource_key=str(row.get("effect_resource_key") or ""),
                            resource_base=(
                                str(row.get("effect_resource_base") or "") or None
                            ),
                            effect=str(row.get("effect") or "unknown"),
                            provider=host,
                            session_id=session_id,
                            task_id=(
                                contract["intent_id"]
                                if str(contract["intent_id"]).startswith("l3:")
                                else ""
                            ),
                            idempotency_key=(
                                f"turn-finalize-gap:{host}:{session_id}:"
                                f"{row.get('sequence')}:{fingerprint}"
                            ),
                            observation_gap=True,
                            verification_kind=str(
                                row.get("verification_kind") or "unsupported"
                            ),
                            verification_sha256=str(
                                row.get("verification_sha256") or ""
                            ),
                        )
                        attempt_id = str(observed["attempt_id"])
                    intervention = mark_attempt_unknown(
                        path,
                        attempt_id,
                        reason="host turn stopped without a completion callback",
                    )
                except (InterventionError, OSError, UnicodeError) as error:
                    raise IntentGuardianError(
                        f"cannot reconcile interrupted external effect: {error}"
                    ) from error
                intervention_ids.append(str(intervention["intervention_id"]))
                pending_row = {
                    "attempt_id": attempt_id,
                    "effect": row.get("effect"),
                    "task_epoch": contract["task_epoch"],
                    "runtime_generation": str(
                        row.get("runtime_generation") or "legacy"
                    ),
                    "fingerprint": fingerprint,
                    "capability": row.get("capability"),
                    "target": row.get("target"),
                    "effect_resource_key": row.get("effect_resource_key"),
                    "effect_resource_base": row.get("effect_resource_base"),
                    "provider": host,
                    "session_id": session_id,
                    "created_at": now_iso(),
                    "memory_verification": row.get("memory_verification"),
                    "outcome_unknown": True,
                    "verification_kind": str(
                        row.get("verification_kind") or "unsupported"
                    ),
                    "verification_sha256": str(
                        row.get("verification_sha256") or ""
                    ),
                    "continuation_grant_id": str(
                        row.get("continuation_grant_id") or ""
                    ),
                    "continuation_profile_id": str(
                        row.get("continuation_profile_id") or ""
                    ),
                }
                continuation_grant_id = pending_row["continuation_grant_id"]
                if continuation_grant_id:
                    grant_snapshot = next(
                        (
                            grant
                            for grant in contract.get("continuation", {}).get(
                                "grants", []
                            )
                            if isinstance(grant, dict)
                            and grant.get("grant_id") == continuation_grant_id
                        ),
                        None,
                    )
                    if grant_snapshot is not None:
                        pending_row["continuation_grant"] = json.loads(
                            json.dumps(grant_snapshot)
                        )
                existing_index = next(
                    (
                        index
                        for index, existing in enumerate(pending)
                        if isinstance(existing, dict)
                        and existing.get("attempt_id") == attempt_id
                    ),
                    None,
                )
                if existing_index is None:
                    pending.append(pending_row)
                else:
                    pending[existing_index] = pending_row
            if row.get("kind") == "skill" or row.get("effect") in {
                "local_write", "destructive", "unknown",
            }:
                outcomes = runtime["inconclusive_outcomes"]
                if not any(
                    isinstance(existing, dict) and existing.get("fingerprint") == fingerprint
                    for existing in outcomes
                ):
                    outcomes.append(
                        {
                            "fingerprint": fingerprint,
                            "capability": row.get("capability"),
                            "target": row.get("target"),
                            "recorded_at": now_iso(),
                            "reason": "host turn stopped without a completion callback",
                        }
                    )
                runtime["inconclusive_outcomes"] = outcomes[-100:]

        interrupted_attempts = {
            str(row.get("attempt_id") or "") for row in interrupted
        }
        for row in pending:
            if not isinstance(row, dict) or not same_lane(row):
                continue
            attempt_id = str(row.get("attempt_id") or "")
            if not attempt_id or attempt_id in interrupted_attempts:
                continue
            try:
                intervention = mark_attempt_unknown(
                    path,
                    attempt_id,
                    reason="host turn ended before independent verification completed",
                )
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot promote unverified effect to unknown: {error}"
                ) from error
            row["outcome_unknown"] = True
            intervention_ids.append(str(intervention["intervention_id"]))
            outcomes = runtime["inconclusive_outcomes"]
            if not any(
                isinstance(existing, dict)
                and existing.get("attempt_id") == attempt_id
                for existing in outcomes
            ):
                outcomes.append(
                    {
                        "attempt_id": attempt_id,
                        "fingerprint": row.get("fingerprint"),
                        "capability": row.get("capability"),
                        "target": row.get("target"),
                        "recorded_at": now_iso(),
                        "reason": "host turn ended before independent verification completed",
                    }
                )
            runtime["inconclusive_outcomes"] = outcomes[-100:]

        processed_attempts = {
            str(row.get("attempt_id") or "")
            for row in pending
            if isinstance(row, dict)
        } | interrupted_attempts
        try:
            effect_projection = load_intervention_projection(path)
        except (InterventionError, OSError, UnicodeError) as error:
            raise IntentGuardianError(
                f"cannot replay effect attempts during lane finalization: {error}"
            ) from error
        for attempt in effect_projection["attempts"].values():
            attempt_id = str(attempt.get("attempt_id") or "")
            if (
                attempt_id in processed_attempts
                or str(attempt.get("effect") or "") == "read"
                or str(attempt.get("provider") or "unknown") != host
                or str(attempt.get("session_id") or "") != session_id
                or attempt.get("state") not in {"dispatched", "accepted", "verifying", "unknown"}
            ):
                continue
            existing_intervention = next(
                (
                    item
                    for item in effect_projection["interventions"].values()
                    if item.get("attempt_id") == attempt_id
                ),
                None,
            )
            if (
                attempt.get("state") == "unknown"
                and existing_intervention
                and existing_intervention.get("status") == "resolved"
            ):
                continue
            try:
                intervention = mark_attempt_unknown(
                    path,
                    attempt_id,
                    reason=(
                        "safe-boundary recovery found an active effect attempt without "
                        "matching contract runtime state"
                    ),
                )
            except (InterventionError, OSError, UnicodeError) as error:
                raise IntentGuardianError(
                    f"cannot recover orphaned external effect attempt: {error}"
                ) from error
            intervention_ids.append(str(intervention["intervention_id"]))
            pending.append(
                {
                    "attempt_id": attempt_id,
                    "task_epoch": contract["task_epoch"],
                    "runtime_generation": "reconciler",
                    "fingerprint": attempt.get("fingerprint"),
                    "capability": attempt.get("capability"),
                    "target": attempt.get("target"),
                    "provider": host,
                    "session_id": session_id,
                    "created_at": attempt.get("created_at") or now_iso(),
                    "outcome_unknown": True,
                }
            )
            outcomes = runtime["inconclusive_outcomes"]
            if not any(
                isinstance(existing, dict)
                and existing.get("attempt_id") == attempt_id
                for existing in outcomes
            ):
                outcomes.append(
                    {
                        "attempt_id": attempt_id,
                        "fingerprint": attempt.get("fingerprint"),
                        "capability": attempt.get("capability"),
                        "target": attempt.get("target"),
                        "recorded_at": now_iso(),
                        "reason": "safe-boundary recovery found an orphaned active effect attempt",
                    }
                )
            runtime["inconclusive_outcomes"] = outcomes[-100:]

        remaining_frames = []
        for row in runtime["active_skill_frames"]:
            if same_lane(row):
                closed_skills.append(str(row.get("name") or ""))
            else:
                remaining_frames.append(row)
        runtime["active_skill_frames"] = remaining_frames
        runtime["active_skills"] = list(dict.fromkeys(row["name"] for row in remaining_frames))
        _write_contract_unlocked(path, contract)

    if interrupted or closed_skills or intervention_ids:
        _append_jsonl(
            audit_path(path),
            {
                "schema": "sulde-guardian-turn-finalize-v1",
                "at": now_iso(),
                "provider": host,
                "session_id": session_id,
                "outcome": "inconclusive",
                "interrupted_events": interrupted,
                "closed_skills": closed_skills,
                "intervention_ids": sorted(set(intervention_ids)),
                "contract_path": str(path),
            },
        )
    # Finalization may have just created a verification row for an interrupted
    # sealed effect.  Run the registered independent verifier at this same
    # Stop boundary instead of waiting for an unrelated next user prompt.
    reconciled_effects = reconcile_pending_verifications(path)
    return {
        "interrupted": len(interrupted),
        "closed_skills": len(closed_skills),
        "intervention_ids": sorted(set(intervention_ids)),
        "reconciled_attempt_ids": [
            str(row["attempt_id"]) for row in reconciled_effects
        ],
    }

def run_semantic_critic_checkpoint(
    path: Path,
    *,
    host: str,
    session_id: str,
    critic_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Claim under lock, evaluate outside it, then CAS the exact result."""
    with contract_lock(path):
        contract = load_contract(path)
        lane = session_id or f"workspace:{workspace_key(Path(contract['workspace_root']))}"
        try:
            claim = claim_critic_lane_batch(
                contract,
                provider=host,
                session_id=lane,
            )
        except CriticCheckpointError as error:
            raise IntentGuardianError(str(error)) from error
        if claim is None:
            return {"status": "empty_or_claimed", "paused": False}
        _write_contract_unlocked(path, contract)
        contract_snapshot = json.loads(json.dumps(contract))

    event = critic_event_for_claim(claim)
    if claim.get("state") == "abandoned":
        result = _critic_inconclusive_result(
            "semantic critic claim expired before a result was recorded; "
            "the batch was not automatically re-sent"
        )
        call_status = "abandoned"
    else:
        try:
            # Leave time for the Stop hook to persist the result before the
            # host's 120-second command timeout expires.
            contract_snapshot["critic"]["timeout_seconds"] = min(
                90.0,
                float(contract_snapshot["critic"].get("timeout_seconds", 90.0)),
            )
            selected_runner = critic_runner or run_critic
            result = validate_result(
                selected_runner(
                    contract_snapshot,
                    event,
                    provider=host,
                )
            ).as_dict()
            call_status = "evaluated"
        except (IntentGuardianError, OSError, TypeError, UnicodeError, ValueError) as error:
            result = _critic_inconclusive_result(
                f"semantic critic unavailable: {type(error).__name__}"
            )
            call_status = "inconclusive"

    with contract_lock(path):
        current = load_contract(path)
        paused = _record_critic_result_locked(
            path,
            current,
            result,
            event=event,
            batch_claim=claim,
        )
    return {
        "status": call_status,
        "paused": paused,
        "batch_id": str(claim.get("batch_id") or ""),
        "verdict": str(result.get("verdict") or "inconclusive"),
    }

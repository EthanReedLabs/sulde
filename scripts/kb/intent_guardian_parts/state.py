"""Contract state, persistence primitives, and shared immutable policy constants."""

from __future__ import annotations

from contextlib import contextmanager

from .decision_types import DecisionV2, IntentGuardianError

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
from sulde_paths import kb_home as canonical_kb_home
from .pre_execution_proof import PreExecutionProofError, normalize_runtime as normalize_pre_execution_runtime

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
    ContinuationError,
    build_capsule,
    capsule_summary,
    continuation_path,
    load_capsule,
    locate_codex_rollout,
    recent_dialogue,
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
    TASK_CONTINUATION_SCHEMA,
    blocks_material as _task_lane_blocks_material,
    claim_critic_lane_batch,
    critic_claim_identity_present,
    critic_claim_world_is_current,
    critic_event_for_claim,
    normalize_critic_batches,
    normalize_task_continuations,
    normalize_task_lanes,
    observe_prompt_lane as _observe_prompt_lane_locked,
    record_critic_local_write,
    settle_critic_claim,
    task_lane as _task_lane,
    upsert_task_lane as _upsert_task_lane_locked,
)

CONTRACT_SCHEMA = "sulde-intent-contract-v1"

EVENT_SCHEMA = "sulde-guardian-event-v1"

LEGACY_HUMAN_CONTROL_RECEIPT_SCHEMA = "sulde-human-control-receipt-v1"

DECISION_RECEIPT_SCHEMA = "sulde-decision-receipt-v2"

PROPOSAL_REVIEW_SCHEMA = "sulde-intent-proposal-review-v1"

PROPOSAL_DECISION_SCHEMA = "sulde-intent-proposal-decision-v1"

CONTINUATION_GRANT_SCHEMA = "sulde-continuation-grant-v1"

CONTINUATION_USE_SCHEMA = "sulde-continuation-use-v1"

MODES = {"off", "shadow", "enforce"}

STATUSES = {"active", "paused", "closed"}

EFFECT_ORDER = ("read", "local_write", "external_write", "destructive", "unknown")

EFFECTS = set(EFFECT_ORDER)

DECISION_ROUTES = {"auto", "human", "agent"}

INTENT_KINDS = {"deterministic", "subjective", "unknown"}

RISK_LEVELS = {"low", "medium", "high", "unknown"}

REVERSIBILITY_LEVELS = {"reversible", "compensatable", "irreversible", "unknown"}

COST_LEVELS = {"none", "bounded", "unbounded", "unknown"}

def _loaded_runtime_generation() -> str:
    """Identify the bytes that loaded this process, including hot upgrades."""
    try:
        payload = Path(__file__).read_bytes()
    except OSError:
        payload = str(Path(__file__).resolve()).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()

RUNTIME_GENERATION = _loaded_runtime_generation()
LOADED_MODULE_GENERATION = RUNTIME_GENERATION


def _loaded_artifact_generation() -> str:
    """Read the immutable delivery identity that contains the loaded module.

    Source-tree execution remains explicitly distinguishable from a packaged
    artifact; it can support unit tests but cannot satisfy a release canary.
    """
    runtime_root = Path(__file__).resolve().parents[3]
    generation_path = runtime_root.parent / ".codex-plugin" / "generation.json"
    try:
        value = json.loads(generation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return f"unpackaged:{LOADED_MODULE_GENERATION}"
    tree = value.get("runtime_tree_sha256") if isinstance(value, dict) else None
    version = value.get("plugin_version") if isinstance(value, dict) else None
    generation = value.get("generation") if isinstance(value, dict) else None
    if (
        value.get("schema") == "sulde-delivery-generation-v1"
        and isinstance(version, str)
        and version
        and isinstance(tree, str)
        and re.fullmatch(r"[0-9a-f]{64}", tree)
        and generation == f"{version}:{tree}"
    ):
        return generation
    return f"invalid-artifact:{LOADED_MODULE_GENERATION}"


ARTIFACT_GENERATION = _loaded_artifact_generation()

CONTINUATION_PROFILES = {
    "codex-plugin-cachebuster-v1": {
        "label": "使用官方 helper 为当前工作区 Codex Sulde 插件生成唯一 cachebuster",
        "effect": "local_write",
        "capability": "tool:Bash",
        "target": "integrations/codex/plugins/sulde/.codex-plugin/plugin.json",
        "max_uses": 1,
        "verification_kind": "content",
        "rollback": "恢复同一 manifest 的原版本字段，不改动其他字段",
    },
    "codex-plugin-install-v1": {
        "label": "事务化重装当前工作区的 Codex Sulde 插件",
        "effect": "external_write",
        "capability": "tool:Bash",
        "target": "[host-local:codex-plugin]",
        "max_uses": 1,
        "verification_kind": "content",
        "rollback": "恢复上一 marketplace、插件缓存、稳定 launcher 与全局规则快照",
    },
    "codex-plugin-cachebuster-v2": {
        "label": "使用密封的无字节码 Python 封装生成当前工作区 Codex Sulde 插件 cachebuster",
        "effect": "local_write",
        "capability": "tool:Bash",
        "target": "integrations/codex/plugins/sulde/.codex-plugin/plugin.json",
        "max_uses": 1,
        "verification_kind": "content",
        "rollback": "恢复同一 manifest 的原版本字段，不改动其他字段",
    },
    "codex-plugin-install-v2": {
        "label": "使用密封的无字节码 Python 封装事务化重装当前工作区 Codex Sulde 插件",
        "effect": "external_write",
        "capability": "tool:Bash",
        "target": "[host-local:codex-plugin]",
        "max_uses": 1,
        "verification_kind": "content",
        "rollback": "恢复上一 marketplace、插件缓存、稳定 launcher 与全局规则快照",
    },
    "sulde-scheduler-reconcile-v1": {
        "label": "使用已安装 generation 的密封脚本协调 16 个 Codex scheduler actors",
        "effect": "external_write",
        "capability": "tool:Bash",
        "target": "[host-local:sulde-scheduler]",
        "max_uses": 1,
        "verification_kind": "content",
        "rollback": "由 scheduler 事务恢复先前 owner、plist、loaded labels 与 deployment 状态",
    },
    "sulde-launcher-refresh-v1": {
        "label": "使用已安装 generation 的密封脚本刷新 Codex launchers 并保留 scheduler seal",
        "effect": "external_write",
        "capability": "tool:Bash",
        "target": "[host-local:sulde-launchers]",
        "max_uses": 1,
        "verification_kind": "content",
        "rollback": "恢复上一 launcher manifest 与稳定 launcher 文件",
    },
}

AGENT_CONTINUATION_PROFILES = frozenset(
    {
        "codex-plugin-cachebuster-v1",
        "codex-plugin-install-v1",
        "codex-plugin-cachebuster-v2",
        "codex-plugin-install-v2",
        "sulde-scheduler-reconcile-v1",
        "sulde-launcher-refresh-v1",
    }
)

COMPENSATION_CONTINUATION_PROFILES = frozenset(
    {
        "codex-plugin-install-v1",
        "codex-plugin-install-v2",
        "sulde-scheduler-reconcile-v1",
        "sulde-launcher-refresh-v1",
    }
)

BOOTSTRAP_RETRY_BINDING_FIELDS = frozenset(
    {
        "codex_home",
        "codex_path",
        "codex_sha256",
        "interpreter_path",
        "interpreter_sha256",
        "kb_home",
        "platform",
        "script_path",
        "workspace_root",
    }
)

CONTINUATION_BINDING_FIELDS = {
    "codex-plugin-cachebuster-v1": {
        "cachebuster",
        "helper_path",
        "helper_sha256",
        "interpreter_path",
        "interpreter_sha256",
        "manifest_path",
        "manifest_sha256",
        "plugin_root",
        "plugin_version",
        "tracked_tree_sha256",
        "workspace_root",
    },
    "codex-plugin-install-v1": {
        "artifact_root",
        "codex_path",
        "codex_sha256",
        "codex_home",
        "interpreter_path",
        "interpreter_sha256",
        "kb_home",
        "platform",
        "plugin_version",
        "script_path",
        "script_sha256",
        "tracked_tree_sha256",
        "workspace_root",
    },
    "codex-plugin-cachebuster-v2": {
        "cachebuster",
        "helper_path",
        "helper_sha256",
        "interpreter_path",
        "interpreter_sha256",
        "manifest_path",
        "manifest_sha256",
        "plugin_root",
        "plugin_version",
        "python_env",
        "python_flag",
        "tracked_tree_sha256",
        "workspace_root",
    },
    "codex-plugin-install-v2": {
        "artifact_root",
        "codex_path",
        "codex_sha256",
        "codex_home",
        "interpreter_path",
        "interpreter_sha256",
        "kb_home",
        "platform",
        "plugin_version",
        "python_env",
        "python_flag",
        "script_path",
        "script_sha256",
        "tracked_tree_sha256",
        "workspace_root",
    },
    "sulde-scheduler-reconcile-v1": {
        "codex_path",
        "codex_sha256",
        "expected_label_count",
        "expected_labels_sha256",
        "kb_home",
        "platform",
        "plugin_version",
        "runtime_root",
        "script_path",
        "script_sha256",
        "tracked_tree_sha256",
        "workspace_root",
    },
    "sulde-launcher-refresh-v1": {
        "expected_label_count",
        "expected_labels_sha256",
        "kb_home",
        "platform",
        "plugin_version",
        "runtime_root",
        "script_path",
        "script_sha256",
        "tracked_tree_sha256",
        "workspace_root",
    },
}

CONTINUATION_BINDING_DIGEST_FIELDS = {
    "codex-plugin-cachebuster-v1": {
        "helper_sha256",
        "interpreter_sha256",
        "manifest_sha256",
        "tracked_tree_sha256",
    },
    "codex-plugin-install-v1": {
        "codex_sha256",
        "interpreter_sha256",
        "script_sha256",
        "tracked_tree_sha256",
    },
    "codex-plugin-cachebuster-v2": {
        "helper_sha256",
        "interpreter_sha256",
        "manifest_sha256",
        "tracked_tree_sha256",
    },
    "codex-plugin-install-v2": {
        "codex_sha256",
        "interpreter_sha256",
        "script_sha256",
        "tracked_tree_sha256",
    },
    "sulde-scheduler-reconcile-v1": {
        "codex_sha256",
        "expected_labels_sha256",
        "script_sha256",
        "tracked_tree_sha256",
    },
    "sulde-launcher-refresh-v1": {
        "expected_labels_sha256",
        "script_sha256",
        "tracked_tree_sha256",
    },
}

SYSTEM_MEMORY_PROFILE = "sulde-memory-annotate-v1"

SYSTEM_MEMORY_MAX_USES = 3

SYSTEM_MEMORY_GRANT_ID = hashlib.sha256(
    f"system-policy:{SYSTEM_MEMORY_PROFILE}".encode("utf-8")
).hexdigest()

AGENT_CONTROL_ACTIONS = frozenset(
    {
        "show",
        "report",
        "reconcile-verifications",
        "rebuild-host-observations",
        "doctor",
        "pause",
        "prepare-proposal",
        "prepare-workspace-handoff", "prepare-task-continuation", "release-completed-workspace", "finalize-workspace-cleanup",
        "prepare-continuation",
        "proposal-show",
        "propose-revision",
        "revise",
        "agent-decide-proposal",
        "apply-proposal",
        "native-decision-preview",
        "pre-execution-proof-prepare",
        "pre-execution-proof-finalize",
        "skill-start",
        "skill-end",
        "interventions",
        "intervention-show",
        "corrections",
        "correction-propose",
        "create",
        "create-from-brief",
        "intervention-ack",
        "--sulde-launcher-probe",
        "--help",
        "-h",
    }
)

READ_ONLY_AGENT_CONTROL_ACTIONS = frozenset(
    {
        "show",
        "report",
        "doctor",
        "proposal-show",
        "native-decision-preview",
        "interventions",
        "intervention-show",
        "corrections",
        "--sulde-launcher-probe",
        "--help",
        "-h",
    }
)

NATIVE_PERMISSION_CONTROL_ACTIONS = frozenset({"native-decision"})

NATIVE_PERMISSION_MODES = frozenset({"default", "acceptEdits"})

NATIVE_DECISIONS = {
    "proposal": frozenset({"approve", "reject"}),
    "grant": frozenset({"allow", "deny"}),
    "intent": frozenset({"confirm", "reject"}),
    "resume": frozenset({"resume"}),
    "task-continuation": frozenset({"approve"}),
    "workspace-handoff": frozenset({"approve"}),
    "observation-export": frozenset({"approve", "reject"}),
    "effect-intervention": frozenset(
        {"retry_authorized", "reprobe_authorized", "abort"}
    ),
}

NATIVE_PERMISSION_SOURCE = "codex_permission_request"

HUMAN_DECISION_CLI_ACTIONS = frozenset(
    {
        "resume",
        "approve-event",
        "approve-proposal",
        "intervention-resolve",
        "correction-resolve",
    }
)

BREAK_GLASS_CONTROL_ACTIONS = frozenset(
    {
        "activate",
        "rebind-workspace",
        "retire-workspace",
    }
)

HUMAN_CONTROL_ACTIONS = HUMAN_DECISION_CLI_ACTIONS | BREAK_GLASS_CONTROL_ACTIONS

PAUSE_SAFE_HOST_CONTROL_ACTIONS = frozenset(
    {
        # Goal/plan bookkeeping and human clarification do not mutate the
        # supervised workspace or an external system.  They must remain
        # available while a task is paused, otherwise the control plane can
        # prevent itself from reporting the block or asking for recovery.
        "getgoal",
        "updategoal",
        "updateplan",
        "requestuserinput",
        # Waiting/listing is observational.  Interrupt is contraction-only:
        # it can stop delegated work but cannot start or extend it.
        "wait",
        "functionswait",
        "collaborationwaitagent",
        "collaborationlistagents",
        "collaborationinterruptagent",
    }
)

GUARDIAN_LAUNCHER_NAMES = frozenset(
    {"intent-guardian", "intent-guardian.py", "intent-guardian.cmd", "intent-guardian.exe"}
)

AGENT_DECISION_SENSITIVE_PATHS = (
    re.compile(r"^(?:AGENTS|CLAUDE)\.md$", re.IGNORECASE),
    re.compile(r"^\.github/workflows(?:/|$)", re.IGNORECASE),
    re.compile(r"^\.gitlab-ci\.ya?ml$", re.IGNORECASE),
    re.compile(r"^(?:Jenkinsfile|azure-pipelines\.ya?ml)$", re.IGNORECASE),
    re.compile(r"^\.(?:claude|codex)(?:/|$)", re.IGNORECASE),
    re.compile(r"^\.sulde-config\.ya?ml$", re.IGNORECASE),
    re.compile(r"^(?:hooks|skills|scripts/release)(?:/|$)", re.IGNORECASE),
    re.compile(r"^scripts/kb/intent[_-]guardian(?:\.py)?$", re.IGNORECASE),
    re.compile(r"(?:^|/)\.env(?:\.|$)", re.IGNORECASE),
)

READ_WORDS = {
    "get", "list", "read", "search", "find", "query", "inspect", "view",
    "open", "fetch", "status", "show", "screenshot", "describe", "lookup",
    "graph", "related", "observe",
}

WRITE_WORDS = {
    "add", "annotate", "apply", "create", "edit", "insert", "mutate", "patch", "post",
    "publish", "send", "set", "submit", "sync", "update", "upload", "write",
    "deploy", "merge", "comment", "reply", "move", "rename",
}

DESTRUCTIVE_WORDS = {
    "delete", "destroy", "drop", "erase", "force", "purge", "remove", "reset",
    "revoke", "truncate", "wipe",
}

CORRECTION_PATTERNS = (
    r"不是(?:这样|这个意思)", r"又(?:错|偏|改坏)", r"越来越偏",
    r"反复(?:犯错|改错|出错)", r"和我想要的.{0,8}不一样", r"没有理解",
    r"不要再.{0,12}(?:改|这样)", r"already (?:said|rejected)",
    r"not what i (?:meant|wanted)",
)

SECRET_KEY = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key|cookie)")

SUBJECTIVE_INTENT_PATTERN = re.compile(
    r"简历|文案|措辞|语气|写作风格|个人表达|设计风格|"
    r"不是(?:这样|这个意思)|越来越偏|和我想要的.{0,8}不一样|"
    r"反复(?:犯错|改错)|not what i (?:meant|wanted)",
    re.IGNORECASE,
)

EXTERNAL_INTENT_PATTERN = re.compile(
    # “发布件”是本地可验证 artifact 的名词，不代表执行发布动作。其余
    # “发布版本/发布讨论”等动词形态继续由这一保守后备门转人工。
    r"发布(?!件)|公开|推送|上传|发送|回复|评论|发帖|邮件|消息|"
    r"\b(?:publish|push|upload|send|reply|comment|message|email|deploy)\b|"
    r"\bpost\b(?![-_ ]?(?:only|tooluse|execution|hook))|"
    r"github\s+(?:discussion|issue|pull request|pr)",
    re.IGNORECASE,
)

DESTRUCTIVE_INTENT_PATTERN = re.compile(
    r"删除|清空|覆盖|销毁|撤销权限|强制重置|"
    r"\b(?:delete|remove|purge|wipe|drop|force[- ]?reset|revoke)\b",
    re.IGNORECASE,
)

COST_INTENT_PATTERN = re.compile(
    r"收费|付费|账单|预算|持续运行|定时任务|自动触发|"
    r"\b(?:billing|paid|budget|schedule|cron|github actions|hosted runner)\b",
    re.IGNORECASE,
)

def _has_unnegated_signal(pattern: re.Pattern[str], text: str) -> bool:
    """Conservative lexical backstop; reject-field words are handled structurally."""
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 16):match.start()]
        if re.search(
            r"(?:不|不得|禁止|避免|无|不会|不能|只限本地|仅本地|"
            r"\bnot\b|\bno\b|\bwithout\b).{0,8}$",
            prefix,
            re.IGNORECASE,
        ):
            continue
        return True
    return False




# Source compatibility for modules that imported the original type name.
Decision = DecisionV2

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _task_epoch(intent_id: str, revision: int, objective: str) -> str:
    """Bind transient execution authority to one semantic task revision."""
    material = f"{intent_id}\0{revision}\0{objective}".encode(
        "utf-8", errors="replace"
    )
    return hashlib.sha256(material).hexdigest()[:24]

def _current_paused_task_lanes(contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Return paused provider/session lanes for the active semantic task."""
    epoch = str(contract.get("task_epoch") or "")
    return [
        row
        for row in contract.get("runtime", {}).get("task_lanes", [])
        if isinstance(row, dict)
        and row.get("task_epoch") == epoch
        and row.get("state") == "paused"
    ]

def _pause_state(
    contract: dict[str, Any],
    *,
    provider: str = "",
    session_id: str = "",
) -> dict[str, Any] | None:
    """Resolve the pause that applies to one task lane.

    Legacy paused contracts did not carry ``pause_scope`` and are deliberately
    interpreted as global.  A lane pause never leaks authority or denial to a
    sibling provider/session lane.
    """
    if contract.get("status") != "paused":
        return None
    runtime = contract.get("runtime", {})
    scope = str(runtime.get("pause_scope") or "global")
    if scope != "lane":
        return {
            "scope": "global",
            "reason": str(runtime.get("pause_reason") or ""),
            "origin_reason": str(
                runtime.get("pause_origin_reason")
                or runtime.get("pause_reason")
                or ""
            ),
            "pause_class": str(runtime.get("pause_class") or "semantic"),
            "event_fingerprint": str(
                runtime.get("pause_event_fingerprint") or ""
            ),
            "requires_revision": bool(
                runtime.get("pause_requires_revision", False)
            ),
            "pause_revision": int(runtime.get("pause_revision", 0)),
        }
    lane = _task_lane(
        contract,
        provider=provider,
        session_id=session_id,
    )
    if lane is None or lane.get("state") != "paused":
        return None
    return {
        "scope": "lane",
        "provider": str(lane.get("provider") or "unknown"),
        "session_id": str(lane.get("session_id") or ""),
        "reason": str(lane.get("pause_reason") or ""),
        "origin_reason": str(lane.get("pause_reason") or ""),
        "pause_class": str(lane.get("pause_class") or "semantic"),
        "event_fingerprint": str(
            lane.get("pause_event_fingerprint") or ""
        ),
        "requires_revision": bool(
            lane.get("pause_requires_revision", False)
        ),
        "pause_revision": int(lane.get("pause_revision", 0)),
        "paused_at": str(lane.get("paused_at") or ""),
    }

def _clear_pause_projection_locked(contract: dict[str, Any]) -> None:
    runtime = contract["runtime"]
    runtime["pause_scope"] = ""
    runtime["pause_reason"] = ""
    runtime["pause_origin_reason"] = ""
    runtime["pause_class"] = ""
    runtime["pause_event_fingerprint"] = ""
    runtime["pause_requires_revision"] = False
    runtime["pause_revision"] = 0

def _refresh_lane_pause_projection_locked(contract: dict[str, Any]) -> None:
    """Keep the legacy top-level status as a projection of paused lanes."""
    runtime = contract["runtime"]
    paused = _current_paused_task_lanes(contract)
    if not paused:
        contract["status"] = "active"
        _clear_pause_projection_locked(contract)
        return
    selected = sorted(
        paused,
        key=lambda row: (
            str(row.get("updated_at") or ""),
            str(row.get("provider") or ""),
            str(row.get("session_id") or ""),
        ),
    )[-1]
    contract["status"] = "paused"
    runtime["pause_scope"] = "lane"
    runtime["pause_reason"] = str(selected.get("pause_reason") or "")[:2_000]
    runtime["pause_origin_reason"] = runtime["pause_reason"]
    runtime["pause_class"] = str(selected.get("pause_class") or "semantic")[:50]
    runtime["pause_event_fingerprint"] = str(
        selected.get("pause_event_fingerprint") or ""
    )[:64]
    runtime["pause_requires_revision"] = any(
        bool(row.get("pause_requires_revision", False)) for row in paused
    )
    runtime["pause_revision"] = max(
        int(row.get("pause_revision", 0)) for row in paused
    )

def _pause_lane_locked(
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    reason: str,
    pause_class: str,
    event_fingerprint: str = "",
    requires_revision: bool = False,
    source: str,
) -> dict[str, Any] | None:
    """Pause one bound task lane while preserving the first/root cause."""
    clean_session = session_id.strip()
    if not clean_session:
        return None
    current = _task_lane(
        contract,
        provider=provider,
        session_id=clean_session,
    )
    if current is not None and current.get("state") == "paused":
        if requires_revision and not current.get("pause_requires_revision", False):
            current["pause_requires_revision"] = True
            current["pause_revision"] = contract["revision"]
            current["updated_at"] = now_iso()
        _refresh_lane_pause_projection_locked(contract)
        return current
    row = _upsert_task_lane_locked(
        contract,
        provider=provider,
        session_id=clean_session,
        state="paused",
        source=source,
        pause_reason=reason,
        pause_class=pause_class,
        pause_event_fingerprint=event_fingerprint,
        pause_requires_revision=requires_revision,
        pause_revision=contract["revision"],
    )
    _refresh_lane_pause_projection_locked(contract)
    return row

def _pause_global_locked(
    contract: dict[str, Any],
    *,
    reason: str,
    pause_class: str,
    event_fingerprint: str = "",
    requires_revision: bool = False,
) -> None:
    runtime = contract["runtime"]
    first_pause = (
        contract.get("status") != "paused"
        or runtime.get("pause_scope") != "global"
        or not runtime.get("pause_reason")
    )
    contract["status"] = "paused"
    runtime["pause_scope"] = "global"
    if first_pause:
        runtime["pause_reason"] = reason[:2_000]
        runtime["pause_origin_reason"] = runtime["pause_reason"]
        runtime["pause_class"] = pause_class[:50] or "semantic"
        runtime["pause_event_fingerprint"] = event_fingerprint[:64]
        runtime["pause_requires_revision"] = bool(requires_revision)
        runtime["pause_revision"] = contract["revision"]
    elif requires_revision:
        runtime["pause_requires_revision"] = True
        runtime["pause_revision"] = max(
            int(runtime.get("pause_revision", 0)), contract["revision"]
        )

def kb_home() -> Path:
    return canonical_kb_home()

def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise

@contextmanager
def _exclusive_path_lock(lock_path: Path, *, timeout: float = 3.0) -> Iterator[None]:
    """Serialize one short state transition across Claude/Codex processes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        while True:
            try:
                lock_exclusive_nonblocking(lock_handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise IntentGuardianError(f"guardian state lock busy: {lock_path}")
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(lock_handle)

def contract_lock(path: Path) -> Iterator[None]:
    """Return the cross-process lock protecting one mutable intent contract."""
    return _exclusive_path_lock(path.with_name(f".{path.name}.lock"))

def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with _exclusive_path_lock(lock_path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

def _append_observation_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Best-effort, non-authoritative telemetry append for allow hot paths.

    One O_APPEND write keeps concurrent rows intact without taking the durable
    decision-ledger lock or forcing every read/Git observation to disk.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None:
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise OSError(f"observation path is not a regular file: {path}")
        if os.name != "nt" and metadata.st_uid != os.getuid():
            raise OSError(f"observation path is not owned by this user: {path}")
    line = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if os.write(descriptor, line) != len(line):
            raise OSError(f"short observation append: {path}")
    finally:
        os.close(descriptor)

def workspace_root(path: Path) -> Path:
    current = path.expanduser().resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / ".sulde-config.yaml").is_file():
            return candidate
    return current

def workspace_binding_key(root: Path) -> str:
    canonical = root.expanduser().resolve()
    return hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()[:24]

def workspace_key(path: Path) -> str:
    return workspace_binding_key(workspace_root(path))

def bound_contract_path(home: Path, root: Path) -> Path:
    return home / "intent" / "workspaces" / f"{workspace_binding_key(root)}.active.json"

def active_contract_path(home: Path, workspace: Path) -> Path:
    return bound_contract_path(home, workspace_root(workspace))

def rebind_marker_path(contract_path: Path) -> Path:
    name = contract_path.name
    if name.endswith(".active.json"):
        name = name[: -len(".active.json")]
    elif name.endswith(".json"):
        name = name[:-5]
    return contract_path.with_name(f"{name}.rebind.json")

def retire_marker_path(contract_path: Path) -> Path:
    name = contract_path.name
    if name.endswith(".active.json"):
        name = name[: -len(".active.json")]
    elif name.endswith(".json"):
        name = name[:-5]
    return contract_path.with_name(f"{name}.retired.json")

def session_contract_path(home: Path, provider: str, session_id: str) -> Path:
    native = session_id.strip()
    if not native:
        raise IntentGuardianError("session_id must be non-empty")
    host = provider.strip().lower() or "unknown"
    digest = hashlib.sha256(f"{host}:{native}".encode("utf-8")).hexdigest()[:32]
    return home / "intent" / "sessions" / f"{host}-{digest}.active.json"

def audit_path(contract_path: Path) -> Path:
    name = contract_path.name
    if name.endswith(".json"):
        name = name[:-5]
    return contract_path.with_name(f"{name}.events.jsonl")

def _strings(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if value is None and allow_empty:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise IntentGuardianError(f"{field} must be an array of strings")
    cleaned = [item.strip() for item in value if item.strip()]
    if not cleaned and not allow_empty:
        raise IntentGuardianError(f"{field} must contain at least one item")
    return cleaned

def _normalize_effects(values: Iterable[str]) -> list[str]:
    selected = {str(value).strip() for value in values if str(value).strip()}
    if not selected:
        raise IntentGuardianError("decision.effects must contain at least one item")
    invalid = selected - EFFECTS
    if invalid:
        raise IntentGuardianError(
            f"decision.effects contains invalid effects: {sorted(invalid)}"
        )
    return [effect for effect in EFFECT_ORDER if effect in selected]

def _intent_confirmation_card(contract: dict[str, Any]) -> dict[str, Any]:
    """Render the executable intent as a stable, human-readable decision card."""
    permissions = contract["permissions"]
    return {
        "要完成的结果": contract["objective"],
        "为什么要做": contract["rationale"],
        "允许改变": {
            "工作区": contract["workspace_root"],
            "可修改路径": contract["constraints"]["allowed_paths"],
            "记忆结果依赖": contract["constraints"].get("memory_dependency", "dependent"),
        },
        "必须保持": contract["constraints"]["preserve"],
        "明确禁止": contract["constraints"]["reject"],
        "如何验收": contract["acceptance_criteria"],
        "执行权限边界": {
            "本地写入": "允许" if permissions["local_write"] else "禁止",
            "外部写入": permissions["external_write"],
            "破坏性操作": permissions["destructive"],
            "Skill 允许": contract["skills"]["allow"],
            "Skill 禁止": contract["skills"]["deny"],
            "MCP 允许服务": contract["mcp"]["allow_servers"],
            "MCP 允许工具": contract["mcp"]["allow_tools"],
            "未知 MCP 效果": contract["mcp"]["unknown_effect"],
        },
        "仍未确定": (
            [contract["confirmation"]["reason"]]
            if contract["confirmation"]["required"]
            else []
        ),
    }

def _intent_confirmation_target(contract: dict[str, Any]) -> str:
    material = {
        "schema": "sulde-intent-confirmation-binding-v1",
        "intent_id": contract["intent_id"],
        "revision": contract["revision"],
        "workspace_root": contract["workspace_root"],
        "card": _intent_confirmation_card(contract),
    }
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

def _resume_decision_card(
    contract: dict[str, Any],
    *,
    provider: str = "",
    session_id: str = "",
) -> dict[str, Any]:
    pause = _pause_state(
        contract,
        provider=provider,
        session_id=session_id,
    ) or {}
    return {
        "要完成的结果": "恢复当前暂停的任务",
        "为什么暂停": pause.get("origin_reason")
        or pause.get("reason")
        or "用户此前要求暂停",
        "恢复后的意图": contract["objective"],
        "必须保持": contract["constraints"]["preserve"],
        "明确禁止": contract["constraints"]["reject"],
        "执行边界": (
            "只恢复当前 provider/session task lane；其他 lane、原权限、路径、"
            "验收条件与未决效果债务均不改变"
            if pause.get("scope") == "lane"
            else "恢复工作区全局管理暂停；原权限、路径、验收条件与 lane 状态均不改变"
        ),
        "仍未确定": [],
    }

def _resume_decision_target(
    contract: dict[str, Any],
    *,
    provider: str = "",
    session_id: str = "",
) -> str:
    pause = _pause_state(
        contract,
        provider=provider,
        session_id=session_id,
    ) or {}
    material = {
        "schema": "sulde-intent-resume-binding-v1",
        "intent_id": contract["intent_id"],
        "revision": contract["revision"],
        "task_epoch": contract["task_epoch"],
        "pause_scope": pause.get("scope") or "none",
        "provider": pause.get("provider") or "",
        "session_id": pause.get("session_id") or "",
        "pause_revision": pause.get("pause_revision", 0),
        "pause_event_fingerprint": pause.get("event_fingerprint") or "",
        "paused_at": pause.get("paused_at") or "",
        "card": _resume_decision_card(
            contract,
            provider=provider,
            session_id=session_id,
        ),
    }
    return hashlib.sha256(
        json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

def _ensure_intent_confirmation_request(
    path: Path,
    contract: dict[str, Any],
) -> dict[str, Any] | None:
    if (
        not contract["confirmation"]["required"]
        or contract["runtime"]["pending_proposal_digest"]
        or (
            contract["status"] == "paused"
            and contract["runtime"]["pause_requires_revision"]
        )
    ):
        return None
    try:
        return ask_approval(
            path,
            intent_id=contract["intent_id"],
            intent_revision=contract["revision"],
            kind="intent-confirmation",
            target=_intent_confirmation_target(contract),
            source="intent_confirmation_card",
            card=_intent_confirmation_card(contract),
            workspace=contract["workspace_root"],
            route="human",
            reuse_decided=True,
        )
    except (ApprovalInvariantError, OSError, UnicodeError) as error:
        raise IntentGuardianError(
            f"cannot persist intent confirmation question: {error}"
        ) from error

def default_contract(
    *,
    intent_id: str,
    objective: str,
    acceptance_criteria: Iterable[str],
    workspace: Path,
    mode: str = "shadow",
    rationale: str = "",
    preserve: Iterable[str] = (),
    reject: Iterable[str] = (),
    allowed_paths: Iterable[str] = (),
    confirmed_by: str = "unconfirmed",
    semantic_critic: bool = False,
    confirmation_required: bool = False,
) -> dict[str, Any]:
    return validate_contract(
        {
            "schema": CONTRACT_SCHEMA,
            "intent_id": intent_id,
            "revision": 1,
            "task_epoch": _task_epoch(intent_id, 1, objective),
            "status": "active",
            "mode": mode,
            "objective": objective,
            "rationale": rationale,
            "acceptance_criteria": list(acceptance_criteria),
            "workspace_root": str(workspace_root(workspace)),
            "confirmed_by": confirmed_by,
            "confirmation": {
                "required": confirmation_required,
                "reason": "主观或高歧义任务必须先确认意图镜像" if confirmation_required else "",
            },
            "constraints": {
                "preserve": list(preserve),
                "reject": list(reject),
                "allowed_paths": list(allowed_paths),
                "frozen_paths": [],
            },
            "permissions": {
                "local_write": True,
                "external_write": "confirm",
                "destructive": "deny",
            },
            "skills": {"allow": ["*"], "deny": []},
            "mcp": {
                "allow_servers": [],
                "allow_tools": [],
                "local_servers": ["sulde-kb"],
                "unknown_effect": "confirm",
            },
            "continuation": {"grants": []},
            "correction_limit": 2,
            "approved_event_fingerprints": [],
            "runtime": {
                "sequence": 0,
                "material_sequence": 0,
                "active_skills": [],
                "active_skill_frames": [],
                "corrections": [],
                "open_events": [],
                "pending_verifications": [],
                "verified_effects": [],
                "authorized_events": [],
                "approved_proposal_digests": [],
                "pending_proposal_digest": "",
                "proposal_decisions": [],
                "approval_receipts": [],
                "continuation_uses": [],
                "task_continuations": [],
                "host_observations": [],
                "pre_execution_gaps": [],
                "pre_execution_probe": {},
                "pre_execution_proofs": [],
                "task_lanes": [],
                "local_write_completions": 0,
                "critic_batches": [],
                "integrity_breaches": [],
                "inconclusive_outcomes": [],
                "pause_scope": "",
                "pause_reason": "",
                "pause_class": "",
                "pause_origin_reason": "",
                "pause_requires_revision": False,
                "pause_revision": 0,
                "legacy_event_authority_migrations": 0,
                "legacy_open_event_migrations": 0,
                "supervision_metrics": {
                    "allowed": 0,
                    "denied": 0,
                    "degraded_observe": 0,
                    "scope_review": 0,
                    "hard_safety_blocks": 0,
                },
            },
            "critic": {
                "enabled": semantic_critic,
                "checkpoint_boundary": "turn_stop_or_managed_terminal",
                "min_confidence": 0.9,
                "timeout_seconds": 120,
            },
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
    )


def clear_pre_execution_gaps(contract: dict[str, Any], *, provider: str, session_id: str) -> None:
    """Clear one lane only after a verified negative execution canary."""
    gaps = contract["runtime"]["pre_execution_gaps"]
    contract["runtime"]["pre_execution_gaps"] = [
        row
        for row in gaps
        if (row.get("provider"), row.get("session_id")) != (provider, session_id)
    ]


def _continuation_grant_id(grant: dict[str, Any]) -> str:
    payload = {key: value for key, value in grant.items() if key != "grant_id"}
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

def _validate_continuation(
    raw: Any,
    *,
    criteria: list[str],
    workspace: Path,
) -> dict[str, Any]:
    value = raw if isinstance(raw, dict) else {}
    raw_grants = value.get("grants", [])
    if not isinstance(raw_grants, list) or len(raw_grants) > 8:
        raise IntentGuardianError("continuation.grants must be an array of at most 8 items")
    grants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_grant in raw_grants:
        if not isinstance(raw_grant, dict):
            raise IntentGuardianError("continuation.grants entries must be objects")
        profile_id = str(raw_grant.get("profile_id") or "")
        profile = CONTINUATION_PROFILES.get(profile_id)
        if profile is None:
            raise IntentGuardianError(f"unknown continuation profile: {profile_id!r}")
        try:
            acceptance_index = int(raw_grant.get("acceptance_index"))
            max_uses = int(raw_grant.get("max_uses"))
        except (TypeError, ValueError) as error:
            raise IntentGuardianError("continuation grant numeric fields are invalid") from error
        if not 0 <= acceptance_index < len(criteria):
            raise IntentGuardianError("continuation grant acceptance index is out of range")
        if max_uses != int(profile["max_uses"]):
            raise IntentGuardianError("continuation grant max_uses differs from its sealed profile")
        acceptance_sha256 = hashlib.sha256(
            criteria[acceptance_index].encode("utf-8")
        ).hexdigest()
        if raw_grant.get("acceptance_sha256") != acceptance_sha256:
            raise IntentGuardianError("continuation grant acceptance binding changed")
        binding = raw_grant.get("binding")
        if not isinstance(binding, dict):
            raise IntentGuardianError("continuation grant binding must be an object")
        expected_binding_fields = CONTINUATION_BINDING_FIELDS[profile_id]
        if set(binding) != expected_binding_fields:
            raise IntentGuardianError("continuation grant binding fields do not match the sealed schema")
        normalized_binding = {key: str(binding.get(key) or "") for key in expected_binding_fields}
        if Path(normalized_binding["workspace_root"]).expanduser().resolve() != workspace.resolve():
            raise IntentGuardianError("continuation grant belongs to another workspace")
        for name in CONTINUATION_BINDING_DIGEST_FIELDS[profile_id]:
            if not re.fullmatch(r"[0-9a-f]{64}", normalized_binding[name]):
                raise IntentGuardianError(f"continuation grant {name} is invalid")
        if (
            "platform" in normalized_binding
            and normalized_binding["platform"] not in {"posix", "windows"}
        ):
            raise IntentGuardianError("continuation grant platform is invalid")
        if profile_id in {
            "codex-plugin-cachebuster-v2",
            "codex-plugin-install-v2",
        } and (
            normalized_binding.get("python_env") != SEALED_PYTHON_ENV
            or normalized_binding.get("python_flag") != SEALED_PYTHON_FLAG
        ):
            raise IntentGuardianError("continuation grant Python wrapper is invalid")
        grant = {
            "schema": CONTINUATION_GRANT_SCHEMA,
            "grant_id": str(raw_grant.get("grant_id") or "").lower(),
            "profile_id": profile_id,
            "label": str(profile["label"]),
            "acceptance_index": acceptance_index,
            "acceptance_sha256": acceptance_sha256,
            "effect": str(profile["effect"]),
            "capability": str(profile["capability"]),
            "target": str(profile["target"]),
            "max_uses": max_uses,
            "verification_kind": str(profile["verification_kind"]),
            "rollback": str(profile["rollback"]),
            "binding": normalized_binding,
        }
        expected_id = _continuation_grant_id(grant)
        if grant["grant_id"] != expected_id:
            raise IntentGuardianError("continuation grant integrity binding changed")
        if expected_id in seen:
            raise IntentGuardianError("duplicate continuation grant")
        seen.add(expected_id)
        grants.append(grant)
    return {"grants": grants}

def validate_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntentGuardianError("intent contract root must be an object")
    contract = json.loads(json.dumps(value, ensure_ascii=False))
    if contract.get("schema") != CONTRACT_SCHEMA:
        raise IntentGuardianError(f"unsupported intent contract schema: {contract.get('schema')!r}")
    intent_id = str(contract.get("intent_id") or "").strip()
    if not intent_id or len(intent_id) > 200:
        raise IntentGuardianError("intent_id must be a non-empty string up to 200 chars")
    try:
        revision = int(contract.get("revision"))
    except (TypeError, ValueError) as error:
        raise IntentGuardianError("revision must be a positive integer") from error
    if revision < 1:
        raise IntentGuardianError("revision must be a positive integer")
    mode = str(contract.get("mode") or "").lower()
    status = str(contract.get("status") or "").lower()
    if mode not in MODES:
        raise IntentGuardianError(f"mode must be one of {sorted(MODES)}")
    if status not in STATUSES:
        raise IntentGuardianError(f"status must be one of {sorted(STATUSES)}")
    objective = str(contract.get("objective") or "").strip()
    if not objective:
        raise IntentGuardianError("objective must be non-empty")
    task_epoch = _task_epoch(intent_id, revision, objective)
    criteria = _strings(contract.get("acceptance_criteria"), "acceptance_criteria", allow_empty=False)
    root = Path(str(contract.get("workspace_root") or "")).expanduser()
    if not str(root).strip():
        raise IntentGuardianError("workspace_root must be non-empty")
    continuation = _validate_continuation(
        contract.get("continuation"),
        criteria=criteria,
        workspace=root,
    )

    confirmation = contract.get("confirmation")
    if not isinstance(confirmation, dict):
        confirmation = {}
    confirmation["required"] = bool(confirmation.get("required", False))
    confirmation["reason"] = str(confirmation.get("reason") or "")[:2_000]

    constraints = contract.get("constraints")
    if not isinstance(constraints, dict):
        raise IntentGuardianError("constraints must be an object")
    for name in ("preserve", "reject", "allowed_paths", "frozen_paths"):
        constraints[name] = _strings(constraints.get(name), f"constraints.{name}")
    if "memory_dependency" in constraints and constraints["memory_dependency"] not in ("independent", "dependent"):
        raise IntentGuardianError("constraints.memory_dependency must be independent or dependent")

    permissions = contract.get("permissions")
    if not isinstance(permissions, dict):
        raise IntentGuardianError("permissions must be an object")
    if not isinstance(permissions.get("local_write"), bool):
        raise IntentGuardianError("permissions.local_write must be boolean")
    if permissions.get("external_write") not in {"allow", "confirm", "deny"}:
        raise IntentGuardianError("permissions.external_write must be allow, confirm or deny")
    if permissions.get("destructive") not in {"confirm", "deny"}:
        raise IntentGuardianError("permissions.destructive must be confirm or deny")

    skills = contract.get("skills")
    if not isinstance(skills, dict):
        raise IntentGuardianError("skills must be an object")
    skills["allow"] = _strings(skills.get("allow"), "skills.allow")
    skills["deny"] = _strings(skills.get("deny"), "skills.deny")

    mcp = contract.get("mcp")
    if not isinstance(mcp, dict):
        raise IntentGuardianError("mcp must be an object")
    for name in ("allow_servers", "allow_tools", "local_servers"):
        mcp[name] = _strings(mcp.get(name), f"mcp.{name}")
    if mcp.get("unknown_effect") not in {"allow", "confirm", "deny"}:
        raise IntentGuardianError("mcp.unknown_effect must be allow, confirm or deny")

    try:
        correction_limit = int(contract.get("correction_limit", 2))
    except (TypeError, ValueError) as error:
        raise IntentGuardianError("correction_limit must be a positive integer") from error
    if correction_limit < 1:
        raise IntentGuardianError("correction_limit must be a positive integer")

    runtime = contract.get("runtime")
    if not isinstance(runtime, dict):
        runtime = {}
    runtime["sequence"] = max(0, int(runtime.get("sequence", 0)))
    runtime["material_sequence"] = max(
        0, int(runtime.get("material_sequence", 0))
    )
    memory_sequence = runtime.get("memory_material_sequence", 0)
    if type(memory_sequence) is not int or not 0 <= memory_sequence <= runtime["material_sequence"]:
        raise IntentGuardianError("runtime.memory_material_sequence is invalid")
    runtime["active_skills"] = _strings(runtime.get("active_skills"), "runtime.active_skills")
    if "completed_calls" in runtime:
        rows = runtime["completed_calls"]
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("call_id"), str) or not row["call_id"] for row in rows):
            raise IntentGuardianError("runtime.completed_calls has invalid host call records")
        runtime["completed_calls"] = rows[-2048:]
    frames = runtime.get("active_skill_frames")
    runtime["active_skill_frames"] = [
        {
            "name": str(row.get("name") or "")[:200],
            "provider": str(row.get("provider") or "unknown")[:50],
            "session_id": str(row.get("session_id") or "")[:200],
            "started_sequence": max(0, int(row.get("started_sequence", 0))),
            "skill_digest": str(row.get("skill_digest") or "")[:64],
            "runtime_generation": str(row.get("runtime_generation") or "")[:64],
            "task_epoch": str(row.get("task_epoch") or task_epoch)[:24],
        }
        for row in (frames if isinstance(frames, list) else [])
        if isinstance(row, dict) and str(row.get("name") or "").strip()
        and str(row.get("task_epoch") or task_epoch) == task_epoch
    ][-50:]
    runtime["corrections"] = runtime.get("corrections") if isinstance(runtime.get("corrections"), list) else []
    raw_open_events = runtime.get("open_events", [])
    if not isinstance(raw_open_events, list) or any(not isinstance(row, dict) for row in raw_open_events):
        raise IntentGuardianError("runtime.open_events must contain objects")
    if any(row.get("kind") != "skill" and row.get("effect") not in (
        "read", "local_write", "external_write", "destructive", "unknown") for row in raw_open_events):
        raise IntentGuardianError("runtime.open_events contains an unrecognized effect")
    # Pre-P0 runtimes put reads and Skill registrations in the same queue as
    # material effects.  They later became phantom verification debt when a
    # turn ended.  Preserve material work only; Skill lineage has its own
    # frame stack and reads remain in the append-only audit.
    runtime["open_events"] = [
        {
            **row,
            "runtime_generation": str(row.get("runtime_generation") or "legacy")[:64],
            "task_epoch": str(row.get("task_epoch") or task_epoch)[:24],
        }
        for row in raw_open_events
        if isinstance(row, dict)
        and row.get("kind") != "skill"
        and row.get("effect") in {"local_write", "external_write", "destructive", "unknown"}
    ]
    migrated_open_events = len(raw_open_events) - len(runtime["open_events"])
    runtime["legacy_open_event_migrations"] = max(
        0, int(runtime.get("legacy_open_event_migrations", 0))
    ) + max(0, migrated_open_events)
    raw_pending_verifications = runtime.get("pending_verifications", [])
    if not isinstance(raw_pending_verifications, list) or any(not isinstance(row, dict) for row in raw_pending_verifications):
        raise IntentGuardianError("runtime.pending_verifications must contain objects")
    runtime["pending_verifications"] = [
        {
            **row,
            "task_epoch": str(row.get("task_epoch") or task_epoch)[:24],
            "runtime_generation": str(
                row.get("runtime_generation") or "legacy"
            )[:64],
        }
        for row in raw_pending_verifications
        if isinstance(row, dict)
    ]
    runtime["verified_effects"] = (
        runtime.get("verified_effects")
        if isinstance(runtime.get("verified_effects"), list)
        else []
    )
    runtime["authorized_events"] = _strings(
        runtime.get("authorized_events"), "runtime.authorized_events"
    )
    runtime["approved_proposal_digests"] = _strings(
        runtime.get("approved_proposal_digests"),
        "runtime.approved_proposal_digests",
    )
    pending_proposal_digest = str(runtime.get("pending_proposal_digest") or "").lower()
    if pending_proposal_digest and not re.fullmatch(r"[0-9a-f]{64}", pending_proposal_digest):
        raise IntentGuardianError(
            "runtime.pending_proposal_digest must be empty or 64 lowercase hex chars"
        )
    runtime["pending_proposal_digest"] = pending_proposal_digest
    raw_proposal_decisions = runtime.get("proposal_decisions")
    if raw_proposal_decisions is None:
        raw_proposal_decisions = []
    if not isinstance(raw_proposal_decisions, list):
        raise IntentGuardianError("runtime.proposal_decisions must be an array")
    proposal_decisions: list[dict[str, Any]] = []
    for row in raw_proposal_decisions[-100:]:
        if not isinstance(row, dict):
            raise IntentGuardianError("runtime.proposal_decisions entries must be objects")
        if row.get("schema") != PROPOSAL_DECISION_SCHEMA:
            raise IntentGuardianError("unsupported proposal decision schema")
        decision_id = str(row.get("decision_id") or "").lower()
        digest = str(row.get("proposal_digest") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", decision_id):
            raise IntentGuardianError("proposal decision_id must be 64 lowercase hex chars")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise IntentGuardianError("proposal decision digest must be 64 lowercase hex chars")
        authority = str(row.get("authority") or "")
        if authority not in {"human", "agent-policy"}:
            raise IntentGuardianError(
                "proposal decision authority must be human or agent-policy"
            )
        verdict = str(row.get("verdict") or "")
        if verdict not in {"approve", "reject"}:
            raise IntentGuardianError("proposal decision verdict must be approve or reject")
        decision_receipt_id = str(row.get("receipt_id") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", decision_receipt_id):
            raise IntentGuardianError(
                "proposal decision receipt_id must be 64 lowercase hex chars"
            )
        proposal_decisions.append(
            {
                "schema": PROPOSAL_DECISION_SCHEMA,
                "decision_id": decision_id,
                "proposal_digest": digest,
                "authority": authority,
                "verdict": verdict,
                "rationale": str(row.get("rationale") or "")[:2_000],
                "evidence": _strings(row.get("evidence"), "proposal_decision.evidence"),
                "provider": str(row.get("provider") or "unknown")[:50],
                "session_id": str(row.get("session_id") or "")[:200],
                "receipt_id": decision_receipt_id,
                "recorded_at": str(row.get("recorded_at") or "")[:100],
            }
        )
    runtime["proposal_decisions"] = proposal_decisions
    raw_receipts = runtime.get("approval_receipts")
    if raw_receipts is None:
        raw_receipts = []
    if not isinstance(raw_receipts, list):
        raise IntentGuardianError("runtime.approval_receipts must be an array")
    receipts: list[dict[str, Any]] = []
    for row in raw_receipts[-100:]:
        if not isinstance(row, dict):
            raise IntentGuardianError("runtime.approval_receipts entries must be objects")
        receipt_schema = str(row.get("schema") or "")
        if receipt_schema not in {
            LEGACY_HUMAN_CONTROL_RECEIPT_SCHEMA,
            DECISION_RECEIPT_SCHEMA,
        }:
            raise IntentGuardianError("unsupported approval receipt schema")
        receipt_id = str(row.get("receipt_id") or "").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", receipt_id):
            raise IntentGuardianError("approval receipt_id must be 64 lowercase hex chars")
        action = str(row.get("action") or "")
        if action not in {
            "approve-event",
            "approve-proposal",
            "reject-proposal",
            "approve-observation-export",
            "reject-observation-export",
            "confirm-intent",
            "reject-intent",
            "pause",
            "resume",
            "continue-task",
            "handoff-workspace",
            "intervention-resolve",
        }:
            raise IntentGuardianError(f"unsupported approval receipt action: {action!r}")
        receipt_decision = str(row.get("decision") or "")[:100]
        evidence_sha256 = str(row.get("evidence_sha256") or "").lower()
        if evidence_sha256 and not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256):
            raise IntentGuardianError(
                "approval receipt evidence_sha256 must be empty or 64 lowercase hex chars"
            )
        approval_request_id = str(row.get("approval_request_id") or "")
        if approval_request_id and not re.fullmatch(
            r"apr-[0-9a-f]{24}", approval_request_id
        ):
            raise IntentGuardianError(
                "approval receipt approval_request_id must be empty or apr-<24hex>"
            )
        if action == "intervention-resolve" and receipt_decision not in {
            "human_attested_success",
            "confirmed_failed",
            "reprobe_authorized",
            "retry_authorized",
            "abort",
        }:
            raise IntentGuardianError(
                "intervention approval receipt requires an exact supported decision"
            )
        receipts.append(
            {
                "schema": receipt_schema,
                "receipt_id": receipt_id,
                "action": action,
                "target": str(row.get("target") or "")[:256],
                "intent_id": str(row.get("intent_id") or intent_id)[:200],
                "intent_revision": max(1, int(row.get("intent_revision", revision))),
                "workspace_root": str(row.get("workspace_root") or root.resolve()),
                "provider": str(row.get("provider") or "unknown")[:50],
                "session_id": str(row.get("session_id") or "")[:200],
                "channel": str(row.get("channel") or "unknown")[:50],
                "observation_source": str(
                    row.get("observation_source") or "unknown"
                )[:100],
                "actor": str(row.get("actor") or "unknown")[:100],
                "decision": receipt_decision,
                "evidence_sha256": evidence_sha256,
                "approval_request_id": approval_request_id,
                "recorded_at": str(row.get("recorded_at") or "")[:100],
                "consumed_at": str(row.get("consumed_at") or "")[:100],
                "consumed_by": str(row.get("consumed_by") or "")[:100],
            }
        )
    runtime["approval_receipts"] = receipts
    raw_continuation_uses = runtime.get("continuation_uses", [])
    if not isinstance(raw_continuation_uses, list):
        raise IntentGuardianError("runtime.continuation_uses must be an array")
    continuation_uses: list[dict[str, Any]] = []
    configured_grants = {row["grant_id"]: row for row in continuation["grants"]}
    for row in raw_continuation_uses:
        if not isinstance(row, dict):
            raise IntentGuardianError("runtime.continuation_uses entries must be objects")
        if row.get("schema") != CONTINUATION_USE_SCHEMA:
            raise IntentGuardianError("unsupported continuation use schema")
        grant_id = str(row.get("grant_id") or "").lower()
        fingerprint = str(row.get("fingerprint") or "").lower()
        authority = str(row.get("authority") or "")
        profile_id = str(row.get("profile_id") or "")
        use_task_epoch = str(row.get("task_epoch") or task_epoch)
        if use_task_epoch != task_epoch:
            continue
        use_effect = str(row.get("effect") or "")
        use_verification_kind = str(row.get("verification_kind") or "")
        use_verification_sha256 = str(
            row.get("verification_sha256") or ""
        ).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", grant_id):
            raise IntentGuardianError("continuation use grant_id is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise IntentGuardianError("continuation use fingerprint is invalid")
        if authority == "system-policy":
            if grant_id != SYSTEM_MEMORY_GRANT_ID or profile_id != SYSTEM_MEMORY_PROFILE:
                raise IntentGuardianError("continuation use has an unknown system policy")
        elif authority == "contract-grant":
            grant = configured_grants.get(grant_id)
            if grant is None or grant["profile_id"] != profile_id:
                raise IntentGuardianError("continuation use references an unavailable contract grant")
        else:
            raise IntentGuardianError("continuation use authority is invalid")
        if use_effect and use_effect not in EFFECTS:
            raise IntentGuardianError("continuation use effect is invalid")
        if use_verification_kind and use_verification_kind not in {
            "unsupported", "existence", "content", "relation"
        }:
            raise IntentGuardianError("continuation use verification kind is invalid")
        if use_verification_sha256 and not re.fullmatch(
            r"[0-9a-f]{64}", use_verification_sha256
        ):
            raise IntentGuardianError("continuation use verification digest is invalid")
        continuation_uses.append(
            {
                "schema": CONTINUATION_USE_SCHEMA,
                "grant_id": grant_id,
                "profile_id": profile_id,
                "authority": authority,
                "fingerprint": fingerprint,
                "event_id": str(row.get("event_id") or "")[:64],
                "provider": str(row.get("provider") or "unknown")[:50],
                "session_id": str(row.get("session_id") or "")[:200],
                "call_id": str(row.get("call_id") or "")[:256],
                "kind": str(row.get("kind") or "")[:50],
                "capability": str(row.get("capability") or "")[:256],
                "target": str(row.get("target") or "")[:2_000],
                "effect": use_effect[:50],
                "verification_kind": use_verification_kind[:50],
                "verification_sha256": use_verification_sha256[:64],
                "memory_verification": row.get("memory_verification"),
                "used_at": str(row.get("used_at") or "")[:100],
                "task_epoch": use_task_epoch[:24],
                "runtime_generation": str(
                    row.get("runtime_generation") or "legacy"
                )[:64],
            }
        )
    runtime["continuation_uses"] = continuation_uses
    try:
        runtime["task_continuations"] = normalize_task_continuations(
            runtime.get("task_continuations"),
        )
    except TaskOwnershipError as error:
        raise IntentGuardianError(str(error)) from error
    raw_observations = runtime.get("host_observations")
    if raw_observations is None:
        raw_observations = []
    if not isinstance(raw_observations, list):
        raise IntentGuardianError("runtime.host_observations must be an array")
    runtime["host_observations"] = [
        {
            "event": str(row.get("event") or "")[:100],
            "provider": str(row.get("provider") or "unknown")[:50],
            "session_id": str(row.get("session_id") or "")[:200],
            "source": str(row.get("source") or "unknown")[:100],
            "status": str(row.get("status") or "unknown")[:50],
            "control_action": str(row.get("control_action") or "")[:50],
            "control_target": str(row.get("control_target") or "")[:256],
            "receipt_id": str(row.get("receipt_id") or "")[:64],
            "at": str(row.get("at") or "")[:100],
        }
        for row in raw_observations[-100:]
        if isinstance(row, dict)
    ]
    raw_pre_execution_gaps = runtime.get("pre_execution_gaps")
    if raw_pre_execution_gaps is None:
        raw_pre_execution_gaps = []
    if not isinstance(raw_pre_execution_gaps, list):
        raise IntentGuardianError("runtime.pre_execution_gaps must be an array")
    runtime["pre_execution_gaps"] = [
        {
            "at": str(row.get("at") or "")[:100],
            "provider": str(row.get("provider") or "unknown")[:50],
            "session_id": str(row.get("session_id") or "")[:200],
            "runtime_generation": str(
                row.get("runtime_generation") or "legacy"
            )[:128],
            "event_id": str(row.get("event_id") or "")[:64],
            "capability": str(row.get("capability") or "unknown")[:256],
            "effect": str(row.get("effect") or "unknown")[:50],
            "target": str(row.get("target") or "")[:1_000],
            "reason_code": str(row.get("reason_code") or "policy_denied")[:100],
        }
        for row in raw_pre_execution_gaps[-100:]
        if isinstance(row, dict)
        and str(row.get("session_id") or "").strip()
    ]
    try:
        normalize_pre_execution_runtime(runtime)
    except PreExecutionProofError as error:
        raise IntentGuardianError(str(error)) from error
    try:
        runtime["task_lanes"] = normalize_task_lanes(
            runtime.get("task_lanes"), default_epoch=task_epoch
        )
    except TaskOwnershipError as error:
        raise IntentGuardianError(str(error)) from error
    runtime["local_write_completions"] = max(
        0, int(runtime.get("local_write_completions", 0))
    )
    runtime["integrity_breaches"] = (
        runtime.get("integrity_breaches")
        if isinstance(runtime.get("integrity_breaches"), list)
        else []
    )
    runtime["inconclusive_outcomes"] = (
        runtime.get("inconclusive_outcomes")
        if isinstance(runtime.get("inconclusive_outcomes"), list)
        else []
    )[-100:]
    runtime["pause_reason"] = str(runtime.get("pause_reason") or "")[:2_000]
    runtime["pause_class"] = str(runtime.get("pause_class") or "")[:50]
    runtime["pause_origin_reason"] = str(
        runtime.get("pause_origin_reason") or runtime["pause_reason"]
    )[:2_000]
    runtime["pause_event_fingerprint"] = str(
        runtime.get("pause_event_fingerprint") or ""
    )[:64]
    runtime["pause_requires_revision"] = bool(
        runtime.get("pause_requires_revision", False)
    )
    runtime["pause_revision"] = max(0, int(runtime.get("pause_revision", 0)))
    pause_scope = str(runtime.get("pause_scope") or "").strip().lower()
    if pause_scope not in {"", "lane", "global"}:
        raise IntentGuardianError("runtime.pause_scope must be lane or global when paused")
    current_paused_lanes = [
        row
        for row in runtime["task_lanes"]
        if row.get("task_epoch") == task_epoch and row.get("state") == "paused"
    ]
    if status == "paused":
        # Older contracts had only workspace-global pause fields.  Never
        # reinterpret them as a narrower lane pause during migration.
        if pause_scope != "lane" or not current_paused_lanes:
            pause_scope = "global"
    elif current_paused_lanes:
        # Repair a partially persisted lane transition without dropping its
        # safety boundary.
        status = "paused"
        pause_scope = "lane"
    else:
        pause_scope = ""
    runtime["pause_scope"] = pause_scope
    if pause_scope == "lane":
        selected_pause = sorted(
            current_paused_lanes,
            key=lambda row: (
                str(row.get("updated_at") or ""),
                str(row.get("provider") or ""),
                str(row.get("session_id") or ""),
            ),
        )[-1]
        runtime["pause_reason"] = str(
            selected_pause.get("pause_reason") or ""
        )[:2_000]
        runtime["pause_origin_reason"] = runtime["pause_reason"]
        runtime["pause_class"] = str(
            selected_pause.get("pause_class") or "semantic"
        )[:50]
        runtime["pause_event_fingerprint"] = str(
            selected_pause.get("pause_event_fingerprint") or ""
        )[:64]
        runtime["pause_requires_revision"] = any(
            bool(row.get("pause_requires_revision", False))
            for row in current_paused_lanes
        )
        runtime["pause_revision"] = max(
            int(row.get("pause_revision", 0))
            for row in current_paused_lanes
        )
    runtime["legacy_event_authority_migrations"] = max(
        0, int(runtime.get("legacy_event_authority_migrations", 0))
    )
    raw_metrics = runtime.get("supervision_metrics")
    if not isinstance(raw_metrics, dict):
        raw_metrics = {}
    runtime["supervision_metrics"] = {
        name: max(0, int(raw_metrics.get(name, 0)))
        for name in (
            "allowed",
            "denied",
            "degraded_observe",
            "scope_review",
            "hard_safety_blocks",
        )
    }

    critic = contract.get("critic")
    if not isinstance(critic, dict):
        critic = {}
    critic["enabled"] = bool(critic.get("enabled", False))
    # `cadence_writes` belonged to the retired per-write critic protocol.  Old
    # contracts remain loadable, but every validated contract is normalized to
    # the single quiescent checkpoint boundary used by both host hooks and L3.
    critic.pop("cadence_writes", None)
    checkpoint_boundary = str(
        critic.get("checkpoint_boundary") or "turn_stop_or_managed_terminal"
    ).strip()
    if checkpoint_boundary != "turn_stop_or_managed_terminal":
        raise IntentGuardianError(
            "critic.checkpoint_boundary must be turn_stop_or_managed_terminal"
        )
    critic["checkpoint_boundary"] = checkpoint_boundary
    try:
        critic["min_confidence"] = float(critic.get("min_confidence", 0.9))
        critic["timeout_seconds"] = max(1.0, float(critic.get("timeout_seconds", 120)))
    except (TypeError, ValueError) as error:
        raise IntentGuardianError("critic numeric settings are invalid") from error
    if not 0 <= critic["min_confidence"] <= 1:
        raise IntentGuardianError("critic.min_confidence must be between 0 and 1")
    try:
        runtime["critic_batches"] = (
            normalize_critic_batches(
                runtime.get("critic_batches"),
                default_epoch=task_epoch,
            )
            if critic["enabled"]
            else []
        )
    except CriticCheckpointError as error:
        raise IntentGuardianError(str(error)) from error

    decision = contract.get("decision")
    if decision is not None:
        if not isinstance(decision, dict):
            raise IntentGuardianError("decision must be an object")
        requested_route = str(decision.get("requested_route") or "auto")
        selected_route = str(decision.get("selected_route") or "human")
        intent_kind = str(decision.get("intent_kind") or "unknown")
        risk = str(decision.get("risk") or "unknown")
        reversibility = str(decision.get("reversibility") or "unknown")
        cost = str(decision.get("cost") or "unknown")
        unattended_policy_present = "unattended_policy" in decision
        try:
            unattended_policy = normalize_unattended_policy(
                decision.get("unattended_policy"),
                # Existing immutable proposals predate unattended evaluation;
                # never opt them in retroactively during schema normalization.
                default=UNATTENDED_WAIT,
            )
        except ApprovalTimeoutPolicyError as error:
            raise IntentGuardianError(str(error)) from error
        effects = _normalize_effects(
            _strings(decision.get("effects"), "decision.effects", allow_empty=False)
        )
        if requested_route not in DECISION_ROUTES:
            raise IntentGuardianError("decision.requested_route is invalid")
        if selected_route not in {"human", "agent"}:
            raise IntentGuardianError("decision.selected_route must be human or agent")
        if intent_kind not in INTENT_KINDS:
            raise IntentGuardianError("decision.intent_kind is invalid")
        if risk not in RISK_LEVELS:
            raise IntentGuardianError("decision.risk is invalid")
        if reversibility not in REVERSIBILITY_LEVELS:
            raise IntentGuardianError("decision.reversibility is invalid")
        if cost not in COST_LEVELS:
            raise IntentGuardianError("decision.cost is invalid")
        permissions = contract["permissions"]
        if "local_write" in effects and not permissions["local_write"]:
            raise IntentGuardianError(
                "decision.effects local_write requires permissions.local_write=true"
            )
        if (
            "external_write" in effects
            and permissions["external_write"] == "deny"
        ):
            raise IntentGuardianError(
                "decision.effects external_write requires per-event confirmation"
            )
        if "destructive" in effects and (
            "local_write" not in effects
            or permissions["destructive"] != "confirm"
        ):
            raise IntentGuardianError(
                "decision.effects destructive requires local_write and "
                "permissions.destructive=confirm"
            )
        normalized_decision = {
            "requested_route": requested_route,
            "selected_route": selected_route,
            "intent_kind": intent_kind,
            "risk": risk,
            "effects": effects,
            "reversibility": reversibility,
            "cost": cost,
            "rollback": str(decision.get("rollback") or "")[:2_000],
            "unknowns": _strings(decision.get("unknowns"), "decision.unknowns"),
            "agent_eligible": bool(decision.get("agent_eligible", False)),
            "agent_ineligible_reasons": _strings(
                decision.get("agent_ineligible_reasons"),
                "decision.agent_ineligible_reasons",
            ),
        }
        if unattended_policy_present:
            normalized_decision["unattended_policy"] = unattended_policy
        contract["decision"] = normalized_decision

    if continuation["grants"]:
        sealed_decision = contract.get("decision")
        if not isinstance(sealed_decision, dict):
            raise IntentGuardianError("continuation grants require a structured decision")
        # Only local-write targets belong in allowed_paths.  Executable inputs
        # such as the installer are separately path- and digest-bound by the
        # grant; treating them as writable would broaden authority over the
        # control plane merely to run it.
        exact_targets = {
            "codex-plugin-cachebuster-v1": (
                root.resolve()
                / "integrations"
                / "codex"
                / "plugins"
                / "sulde"
                / ".codex-plugin"
                / "plugin.json"
            ),
            "codex-plugin-cachebuster-v2": (
                root.resolve()
                / "integrations"
                / "codex"
                / "plugins"
                / "sulde"
                / ".codex-plugin"
                / "plugin.json"
            ),
        }
        allowed_targets: set[Path] = set()
        for raw_path in constraints["allowed_paths"]:
            candidate = Path(raw_path).expanduser()
            try:
                resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
            except OSError:
                continue
            for profile_id, expected in exact_targets.items():
                if resolved == expected:
                    allowed_targets.add(expected)
        for grant in continuation["grants"]:
            if grant["effect"] not in sealed_decision["effects"]:
                raise IntentGuardianError(
                    "continuation grant effect is absent from the readable decision"
                )
            expected_target = exact_targets.get(grant["profile_id"])
            if expected_target is not None and expected_target not in allowed_targets:
                raise IntentGuardianError(
                    f"{grant['label']} continuation requires its exact write path"
                )

    approvals = _strings(
        contract.get("approved_event_fingerprints"),
        "approved_event_fingerprints",
    )
    if approvals:
        runtime["legacy_event_authority_migrations"] += len(approvals)
    # Event digests are audit identities, not understandable authority.  Old
    # entries remain countable in migration telemetry but never authorize a
    # future action or cross a task epoch.
    approvals = []
    runtime["authorized_events"] = []
    contract.update(
        {
            "intent_id": intent_id,
            "revision": revision,
            "task_epoch": task_epoch,
            "mode": mode,
            "status": status,
            "objective": objective,
            "rationale": str(contract.get("rationale") or "").strip(),
            "acceptance_criteria": criteria,
            "workspace_root": str(root.resolve()),
            "confirmed_by": str(contract.get("confirmed_by") or "unconfirmed"),
            "confirmation": confirmation,
            "constraints": constraints,
            "permissions": permissions,
            "skills": skills,
            "mcp": mcp,
            "continuation": continuation,
            "correction_limit": correction_limit,
            "approved_event_fingerprints": approvals,
            "runtime": runtime,
            "critic": critic,
            "created_at": str(contract.get("created_at") or now_iso()),
            "updated_at": str(contract.get("updated_at") or now_iso()),
        }
    )
    return contract

def load_contract(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntentGuardianError(f"invalid intent contract {path}: {error}") from error
    return validate_contract(payload)

def write_contract(path: Path, contract: dict[str, Any]) -> None:
    with contract_lock(path):
        _write_contract_unlocked(path, contract)

def _write_contract_unlocked(path: Path, contract: dict[str, Any]) -> None:
    normalized = validate_contract(contract)
    normalized["updated_at"] = now_iso()
    atomic_write(path, json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    contract.clear()
    contract.update(normalized)

def policy_digest(contract: dict[str, Any]) -> str:
    policy = {
        key: contract.get(key)
        for key in (
            "schema",
            "intent_id",
            "revision",
            "task_epoch",
            "mode",
            "objective",
            "rationale",
            "acceptance_criteria",
            "workspace_root",
            "confirmed_by",
            "confirmation",
            "constraints",
            "permissions",
            "skills",
            "mcp",
            "correction_limit",
            "critic",
        )
    }
    # Keep empty/legacy contracts byte-compatible with the pre-continuation
    # policy digest so an upgrade does not invalidate unrelated pending cards.
    # A material grant is authority and therefore becomes part of the base.
    if contract.get("continuation", {}).get("grants"):
        policy["continuation"] = contract["continuation"]
    rendered = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

def proposal_digest_payload(proposal: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_contract(proposal)
    # Bind every authority-bearing and runtime field, including unknown future
    # fields. Only the self-referential digest and atomic-writer timestamp are
    # excluded. This prevents an approved proposal from gaining hidden event
    # approvals or other runtime authority after the human reviewed its digest.
    return {
        key: value
        for key, value in normalized.items()
        if key not in {"proposal_digest", "updated_at"}
    }

def proposal_digest(proposal: dict[str, Any]) -> str:
    payload = proposal_digest_payload(proposal)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()

def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

_FROZEN_EXPLICIT_RELEASE_RUNTIME_INPUT_ALLOWLIST = (
    Path("scripts/kb/approval_timeout_policy.py"), Path("scripts/kb/codex_cli_contract.py"),
    Path("scripts/kb/decision_kernel.py"), Path("scripts/kb/local_file_operations.py"),
    Path("scripts/kb/native_decision_journal.py"), Path("scripts/kb/intent_guardian_parts/figma_read_recovery.py"), Path("scripts/kb/intent_guardian_parts/intervention_control.py"),
    Path("scripts/kb/intent_guardian_parts/native_grant.py"), Path("scripts/kb/intent_guardian_parts/orchestrator_resources.py"),
    Path("scripts/kb/intent_guardian_parts/pre_execution_control.py"), Path("scripts/kb/intent_guardian_parts/pre_execution_proof.py"),
    Path("scripts/kb/intent_guardian_parts/session_workspace.py"),
    Path("scripts/kb/operational_readiness.py"),
    Path("scripts/kb/production_recovery.py"), Path("scripts/kb/production_recovery_readiness.py"),
    Path("scripts/kb/production-recovery.py"), Path("scripts/kb/production_recovery_control.py"),
    Path("scripts/kb/production_recovery_targets.py"),
    Path("scripts/kb/sulde_paths.py"),
    Path("scripts/kb/sulde-statusline.py"),
    Path("scripts/kb/sulde_status_snapshot.py"),
    Path("scripts/kb/task_ownership.py"),
)

EXPLICIT_RELEASE_RUNTIME_INPUTS = (
    Path("scripts/kb/approval_timeout_policy.py"), Path("scripts/kb/codex_cli_contract.py"),
    Path("scripts/kb/decision_kernel.py"), Path("scripts/kb/local_file_operations.py"),
    Path("scripts/kb/native_decision_journal.py"), Path("scripts/kb/intent_guardian_parts/figma_read_recovery.py"), Path("scripts/kb/intent_guardian_parts/intervention_control.py"),
    Path("scripts/kb/intent_guardian_parts/native_grant.py"), Path("scripts/kb/intent_guardian_parts/orchestrator_resources.py"),
    Path("scripts/kb/intent_guardian_parts/pre_execution_control.py"), Path("scripts/kb/intent_guardian_parts/pre_execution_proof.py"),
    Path("scripts/kb/intent_guardian_parts/session_workspace.py"),
    Path("scripts/kb/operational_readiness.py"),
    Path("scripts/kb/production_recovery.py"), Path("scripts/kb/production_recovery_readiness.py"),
    Path("scripts/kb/production-recovery.py"), Path("scripts/kb/production_recovery_control.py"),
    Path("scripts/kb/production_recovery_targets.py"),
    Path("scripts/kb/sulde_paths.py"),
    Path("scripts/kb/sulde-statusline.py"),
    Path("scripts/kb/sulde_status_snapshot.py"),
    Path("scripts/kb/task_ownership.py"),
)


def _validated_explicit_release_runtime_inputs(root: Path) -> tuple[Path, ...]:
    """Reject any runtime authorization inventory outside the frozen contract."""
    explicit_inputs = EXPLICIT_RELEASE_RUNTIME_INPUTS
    path_type = type(Path())
    if type(explicit_inputs) is not tuple or any(
        type(relative) is not path_type for relative in explicit_inputs
    ):
        raise IntentGuardianError(
            "invalid explicit release runtime input allowlist: "
            "expected a tuple of platform Path values"
        )
    if any(
        relative.is_absolute()
        or relative.as_posix() in {"", "."}
        or ".." in relative.parts
        for relative in explicit_inputs
    ):
        raise IntentGuardianError(
            "invalid explicit release runtime input allowlist: "
            "paths must be canonical repository-relative paths"
        )
    if len(explicit_inputs) != len(set(explicit_inputs)):
        raise IntentGuardianError(
            "invalid explicit release runtime input allowlist: duplicate path"
        )
    if explicit_inputs != _FROZEN_EXPLICIT_RELEASE_RUNTIME_INPUT_ALLOWLIST:
        raise IntentGuardianError(
            "invalid explicit release runtime input allowlist: "
            "does not exactly match the frozen canonical order"
        )

    resolved_inputs: list[Path] = []
    try:
        resolved_root = root.resolve()
        for relative in explicit_inputs:
            resolved = (resolved_root / relative).resolve(strict=False)
            resolved.relative_to(resolved_root)
            resolved_inputs.append(resolved)
    except (OSError, RuntimeError, ValueError) as error:
        raise IntentGuardianError(
            "invalid explicit release runtime input allowlist: "
            "path escapes the repository"
        ) from error
    if len(resolved_inputs) != len(set(resolved_inputs)):
        raise IntentGuardianError(
            "invalid explicit release runtime input allowlist: "
            "duplicate canonical or physical resource"
        )
    return explicit_inputs


def _workspace_tracked_tree_sha256(
    root: Path,
    *,
    overrides: dict[Path, bytes] | None = None,
) -> str:
    """Bind a grant to all staged source bytes, modes, stages, and paths.

    Index object ids are validated but excluded from both digest and ordering:
    staging consumes working-tree bytes, so committing reviewed future bytes
    must not stale their grant. Explicit pre-index release inputs are included.
    """
    explicit_inputs = _validated_explicit_release_runtime_inputs(root)
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--stage", "-z"],
            cwd=root,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise IntentGuardianError(f"cannot enumerate tracked workspace files: {error}") from error
    if completed.returncode != 0:
        raise IntentGuardianError("cannot bind continuation grant to the tracked workspace")
    digest = hashlib.sha256()
    resolved_root = root.resolve()
    resolved_overrides = {
        Path(path).expanduser().resolve(): bytes(content)
        for path, content in (overrides or {}).items()
    }
    consumed_overrides: set[Path] = set()
    raw_records = {item for item in completed.stdout.split(b"\0") if item}
    if not raw_records:
        raise IntentGuardianError("tracked workspace is empty")
    def canonical_order(raw: bytes) -> tuple[bytes, bytes, bytes]:
        try:
            metadata, raw_path = raw.split(b"\t", 1)
            mode, _object_id, stage = metadata.split(b" ")
        except ValueError as error:
            raise IntentGuardianError("tracked workspace contains an unsafe path") from error
        return raw_path, stage, mode

    for raw in sorted(raw_records, key=canonical_order):
        try:
            metadata, raw_path = raw.split(b"\t", 1)
            metadata_parts = metadata.split(b" ")
            if len(metadata_parts) != 3:
                raise ValueError("invalid tracked metadata")
            mode, object_id, stage = metadata_parts
            if (
                re.fullmatch(rb"[0-7]{6}", mode) is None
                or re.fullmatch(rb"[0-9a-f]{40}(?:[0-9a-f]{24})?", object_id) is None
                or stage != b"0"
            ):
                raise ValueError("unsafe tracked metadata")
            bound_metadata = b" ".join((mode, stage))
            relative = Path(raw_path.decode("utf-8"))
            source = resolved_root / relative
            source_metadata = source.lstat()
            if source.is_symlink() or not stat.S_ISREG(source_metadata.st_mode):
                raise ValueError("non-regular tracked input")
            candidate = source.resolve(strict=True)
            candidate.relative_to(resolved_root)
        except (OSError, UnicodeError, ValueError) as error:
            raise IntentGuardianError("tracked workspace contains an unsafe path") from error
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(bound_metadata).to_bytes(8, "big"))
        digest.update(bound_metadata)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        if candidate in resolved_overrides:
            digest.update(resolved_overrides[candidate])
            consumed_overrides.add(candidate)
        else:
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    digest.update(b"\0sulde-explicit-release-inputs-v1\0")
    for relative in explicit_inputs:
        source = resolved_root / relative
        try:
            source_metadata = source.lstat()
            if source.is_symlink() or not stat.S_ISREG(source_metadata.st_mode):
                raise ValueError("non-regular explicit release input")
            candidate = source.resolve(strict=True)
            candidate.relative_to(resolved_root)
        except (OSError, ValueError) as error:
            raise IntentGuardianError(
                f"explicit release input is unavailable or unsafe: {relative}"
            ) from error
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update((source_metadata.st_mode & 0o777).to_bytes(4, "big"))
        if candidate in resolved_overrides:
            digest.update(resolved_overrides[candidate])
            consumed_overrides.add(candidate)
        else:
            with candidate.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    if consumed_overrides != set(resolved_overrides):
        raise IntentGuardianError("tracked-tree override does not name a tracked file")
    return digest.hexdigest()

def _json_version(path: Path, label: str) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntentGuardianError(f"cannot read {label}: {error}") from error
    value = payload.get("version") if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise IntentGuardianError(f"{label} has no version")
    return value.strip()

def _cachebuster_value(value: str) -> str:
    sanitized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    return re.sub(r"-{2,}", "-", sanitized).strip("-")

def _plugin_manifest_after_cachebuster(
    manifest_path: Path,
    cachebuster: str,
) -> tuple[str, bytes]:
    normalized = _cachebuster_value(cachebuster)
    if not normalized or normalized != cachebuster:
        raise IntentGuardianError("cachebuster token is not canonical")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise IntentGuardianError(f"cannot read Codex plugin manifest: {error}") from error
    if not isinstance(payload, dict):
        raise IntentGuardianError("Codex plugin manifest must be an object")
    current = payload.get("version")
    if not isinstance(current, str) or not current.strip():
        raise IntentGuardianError("Codex plugin manifest has no version")
    next_version = f"{current.split('+', 1)[0]}+codex.{normalized}"
    payload["version"] = next_version
    rendered = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    return next_version, rendered

def _codex_plugin_cachebuster_binding(
    workspace: Path,
    *,
    cachebuster: str,
    interpreter: Path | None = None,
    helper: Path | None = None,
) -> tuple[dict[str, str], bytes]:
    root = workspace_root(workspace).resolve()
    plugin_root = (root / "integrations/codex/plugins/sulde").resolve()
    manifest = (plugin_root / ".codex-plugin/plugin.json").resolve()
    if not manifest.is_file() or not manifest.is_relative_to(root):
        raise IntentGuardianError("Codex plugin manifest is unavailable in this workspace")
    configured_codex_home = os.environ.get("CODEX_HOME")
    codex_home = (
        Path(configured_codex_home).expanduser()
        if configured_codex_home
        else Path.home() / ".codex"
    ).resolve()
    expected_helper = (
        codex_home
        / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
    ).resolve()
    selected_helper = Path(helper or expected_helper).expanduser().resolve()
    if selected_helper != expected_helper or not selected_helper.is_file():
        raise IntentGuardianError("official plugin cachebuster helper is unavailable")
    selected_interpreter = Path(interpreter or sys.executable).expanduser().resolve()
    if not selected_interpreter.is_file():
        raise IntentGuardianError("continuation grant interpreter is unavailable")
    next_version, rendered = _plugin_manifest_after_cachebuster(manifest, cachebuster)
    binding = {
        "cachebuster": cachebuster,
        "helper_path": str(selected_helper),
        "helper_sha256": _sha256_path(selected_helper),
        "interpreter_path": str(selected_interpreter),
        "interpreter_sha256": _sha256_path(selected_interpreter),
        "manifest_path": str(manifest),
        "manifest_sha256": hashlib.sha256(rendered).hexdigest(),
        "plugin_root": str(plugin_root),
        "plugin_version": next_version,
        "tracked_tree_sha256": _workspace_tracked_tree_sha256(
            root,
            overrides={manifest: rendered},
        ),
        "workspace_root": str(root),
    }
    return binding, rendered

def _codex_plugin_install_binding(
    workspace: Path,
    *,
    interpreter: Path | None = None,
    plugin_manifest_override: bytes | None = None,
) -> dict[str, str]:
    root = workspace_root(workspace).resolve()
    script = (root / "scripts/release/install_codex_plugin.py").resolve()
    if not script.is_file() or not script.is_relative_to(root):
        raise IntentGuardianError("Codex plugin installer is unavailable in this workspace")
    selected_interpreter = Path(interpreter or sys.executable).expanduser().resolve()
    if not selected_interpreter.is_file():
        raise IntentGuardianError("continuation grant interpreter is unavailable")
    product_version = _json_version(root / ".claude-plugin/plugin.json", "product manifest")
    plugin_manifest = (
        root / "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
    ).resolve()
    if plugin_manifest_override is None:
        plugin_version = _json_version(plugin_manifest, "Codex plugin manifest")
    else:
        try:
            override_payload = json.loads(plugin_manifest_override.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise IntentGuardianError("invalid future Codex plugin manifest") from error
        raw_version = override_payload.get("version") if isinstance(override_payload, dict) else None
        if not isinstance(raw_version, str) or not raw_version.strip():
            raise IntentGuardianError("future Codex plugin manifest has no version")
        plugin_version = raw_version.strip()
    safe_product = re.sub(r"[^0-9A-Za-z._-]+", "-", product_version)
    safe_plugin = re.sub(r"[^0-9A-Za-z._-]+", "-", plugin_version)
    artifact_root = (
        Path.home() / ".sulde" / "artifacts" / f"sulde-{safe_product}-{safe_plugin}" / "codex"
    ).resolve()
    configured_codex_home = os.environ.get("CODEX_HOME")
    codex_home = Path(configured_codex_home).expanduser() if configured_codex_home else Path.home() / ".codex"
    codex_command = shutil.which("codex")
    if not codex_command:
        raise IntentGuardianError("Codex executable is unavailable for the continuation grant")
    codex_path = Path(codex_command).expanduser().resolve()
    return {
        "artifact_root": str(artifact_root),
        "codex_path": str(codex_path),
        "codex_sha256": _sha256_path(codex_path),
        "codex_home": str(codex_home.resolve()),
        "interpreter_path": str(selected_interpreter),
        "interpreter_sha256": _sha256_path(selected_interpreter),
        "kb_home": str(kb_home().resolve()),
        "platform": "windows" if os.name == "nt" else "posix",
        "plugin_version": plugin_version,
        "script_path": str(script),
        "script_sha256": _sha256_path(script),
        "tracked_tree_sha256": _workspace_tracked_tree_sha256(
            root,
            overrides=(
                {plugin_manifest: plugin_manifest_override}
                if plugin_manifest_override is not None
                else None
            ),
        ),
        "workspace_root": str(root),
    }


SEALED_PYTHON_ENV = "PYTHONDONTWRITEBYTECODE=1"

SEALED_PYTHON_FLAG = "-B"


def _sealed_python_binding(binding: dict[str, str]) -> dict[str, str]:
    """Version a maintenance binding without invalidating historical v1 rows."""
    return {
        **binding,
        "python_env": SEALED_PYTHON_ENV,
        "python_flag": SEALED_PYTHON_FLAG,
    }


def _codex_plugin_cachebuster_v2_binding(
    workspace: Path,
    *,
    cachebuster: str,
    interpreter: Path | None = None,
    helper: Path | None = None,
) -> tuple[dict[str, str], bytes]:
    binding, rendered = _codex_plugin_cachebuster_binding(
        workspace,
        cachebuster=cachebuster,
        interpreter=interpreter,
        helper=helper,
    )
    return _sealed_python_binding(binding), rendered


def _codex_plugin_install_v2_binding(
    workspace: Path,
    *,
    interpreter: Path | None = None,
    plugin_manifest_override: bytes | None = None,
) -> dict[str, str]:
    return _sealed_python_binding(
        _codex_plugin_install_binding(
            workspace,
            interpreter=interpreter,
            plugin_manifest_override=plugin_manifest_override,
        )
    )


def _launchagent_label_binding(root: Path) -> tuple[str, str]:
    labels = sorted(
        path.stem
        for path in (root / "templates/launchagents").glob("com.sulde.*.plist")
        if path.is_file()
    )
    if not labels or len(labels) != len(set(labels)):
        raise IntentGuardianError("Codex scheduler label inventory is unavailable")
    digest = hashlib.sha256(
        json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return str(len(labels)), digest


def _installed_maintenance_binding(
    workspace: Path,
    *,
    script_relative: str,
    plugin_manifest_override: bytes | None = None,
) -> dict[str, str]:
    root = workspace_root(workspace).resolve()
    install = _codex_plugin_install_binding(
        root,
        plugin_manifest_override=plugin_manifest_override,
    )
    source_script = (root / script_relative).resolve()
    if not source_script.is_file() or not source_script.is_relative_to(root):
        raise IntentGuardianError("installed maintenance source is unavailable")
    runtime_root = (
        Path(install["codex_home"])
        / "plugins/cache/sulde-local/sulde"
        / install["plugin_version"]
        / "runtime"
    ).resolve()
    installed_script = (runtime_root / script_relative).resolve()
    if not installed_script.is_file() or not installed_script.is_relative_to(
        runtime_root
    ):
        raise IntentGuardianError(
            "installed maintenance generation is unavailable; publish it before "
            "binding scheduler or launcher authority"
        )
    label_count, labels_sha256 = _launchagent_label_binding(root)
    return {
        "expected_label_count": label_count,
        "expected_labels_sha256": labels_sha256,
        "kb_home": install["kb_home"],
        "platform": install["platform"],
        "plugin_version": install["plugin_version"],
        "runtime_root": str(runtime_root),
        "script_path": str(installed_script),
        # The official stager deliberately materializes portable runtime bytes
        # (for example by neutralizing source-machine paths in install-agents).
        # Bind the executable artifact, not the pre-stage source that produced
        # it, and enforce the install -> scheduler/launcher phase boundary.
        "script_sha256": _sha256_path(installed_script),
        "tracked_tree_sha256": install["tracked_tree_sha256"],
        "workspace_root": str(root),
    }


def _scheduler_reconcile_binding(
    workspace: Path,
    *,
    plugin_manifest_override: bytes | None = None,
) -> dict[str, str]:
    install = _codex_plugin_install_binding(
        workspace,
        plugin_manifest_override=plugin_manifest_override,
    )
    return {
        **_installed_maintenance_binding(
            workspace,
            script_relative="scripts/kb/install-agents.sh",
            plugin_manifest_override=plugin_manifest_override,
        ),
        "codex_path": install["codex_path"],
        "codex_sha256": install["codex_sha256"],
    }


def _launcher_refresh_binding(
    workspace: Path,
    *,
    plugin_manifest_override: bytes | None = None,
) -> dict[str, str]:
    return _installed_maintenance_binding(
        workspace,
        script_relative="scripts/kb/bootstrap.sh",
        plugin_manifest_override=plugin_manifest_override,
    )

def build_continuation_grants(
    specs: Iterable[str],
    *,
    acceptance_criteria: list[str],
    workspace: Path,
) -> list[dict[str, Any]]:
    """Freeze explicit profile@index grants into the human-reviewed proposal."""
    parsed_specs: list[tuple[str, int]] = []
    for raw in specs:
        match = re.fullmatch(r"([a-z0-9][a-z0-9._-]*)@([1-9][0-9]*)", str(raw).strip())
        if match is None:
            raise IntentGuardianError(
                "continuation grant must use <profile>@<1-based-acceptance-index>"
            )
        parsed = (match.group(1), int(match.group(2)) - 1)
        # The CLI may receive the same exact profile explicitly and infer it
        # from the human-readable label.  That is one authority request, not
        # two uses; retain rejection for the same profile bound elsewhere.
        if parsed not in parsed_specs:
            parsed_specs.append(parsed)

    cachebuster_bindings: dict[str, dict[str, str]] = {}
    future_plugin_manifest: bytes | None = None
    selected_cache_profiles = {
        profile_id
        for profile_id, _ in parsed_specs
        if profile_id in {
            "codex-plugin-cachebuster-v1",
            "codex-plugin-cachebuster-v2",
        }
    }
    if len(selected_cache_profiles) > 1:
        raise IntentGuardianError("only one Codex plugin cachebuster profile may be selected")
    if selected_cache_profiles:
        current_tree = _workspace_tracked_tree_sha256(workspace_root(workspace))
        cachebuster = (
            datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            + "-"
            + current_tree[:10]
        )
        cache_profile_id = next(iter(selected_cache_profiles))
        if cache_profile_id == "codex-plugin-cachebuster-v2":
            binding, future_plugin_manifest = _codex_plugin_cachebuster_v2_binding(
                workspace,
                cachebuster=cachebuster,
            )
        else:
            binding, future_plugin_manifest = _codex_plugin_cachebuster_binding(
                workspace,
                cachebuster=cachebuster,
            )
        cachebuster_bindings[cache_profile_id] = binding

    grants: list[dict[str, Any]] = []
    seen_profiles: set[str] = set()
    for profile_id, acceptance_index in parsed_specs:
        profile = CONTINUATION_PROFILES.get(profile_id)
        if profile is None:
            raise IntentGuardianError(f"unknown continuation profile: {profile_id}")
        if profile_id in seen_profiles:
            raise IntentGuardianError(f"duplicate continuation profile: {profile_id}")
        if not 0 <= acceptance_index < len(acceptance_criteria):
            raise IntentGuardianError("continuation grant acceptance index is out of range")
        acceptance_sha256 = hashlib.sha256(
            acceptance_criteria[acceptance_index].encode("utf-8")
        ).hexdigest()
        if profile_id in {
            "codex-plugin-cachebuster-v1",
            "codex-plugin-cachebuster-v2",
        }:
            if profile_id not in cachebuster_bindings:  # pragma: no cover - computed above
                raise IntentGuardianError("cachebuster binding is unavailable")
            binding = cachebuster_bindings[profile_id]
        elif profile_id == "codex-plugin-install-v1":
            binding = _codex_plugin_install_binding(
                workspace,
                plugin_manifest_override=future_plugin_manifest,
            )
        elif profile_id == "codex-plugin-install-v2":
            binding = _codex_plugin_install_v2_binding(
                workspace,
                plugin_manifest_override=future_plugin_manifest,
            )
        elif profile_id == "sulde-scheduler-reconcile-v1":
            binding = _scheduler_reconcile_binding(
                workspace,
                plugin_manifest_override=future_plugin_manifest,
            )
        elif profile_id == "sulde-launcher-refresh-v1":
            binding = _launcher_refresh_binding(
                workspace,
                plugin_manifest_override=future_plugin_manifest,
            )
        else:  # pragma: no cover - registry and builder change together
            raise IntentGuardianError(f"continuation profile has no binder: {profile_id}")
        grant = {
            "schema": CONTINUATION_GRANT_SCHEMA,
            "grant_id": "",
            "profile_id": profile_id,
            "label": str(profile["label"]),
            "acceptance_index": acceptance_index,
            "acceptance_sha256": acceptance_sha256,
            "effect": str(profile["effect"]),
            "capability": str(profile["capability"]),
            "target": str(profile["target"]),
            "max_uses": int(profile["max_uses"]),
            "verification_kind": str(profile["verification_kind"]),
            "rollback": str(profile["rollback"]),
            "binding": binding,
        }
        grant["grant_id"] = _continuation_grant_id(grant)
        grants.append(grant)
        seen_profiles.add(profile_id)
    return grants

def implicit_continuation_grant_specs(
    acceptance_criteria: list[str],
    *,
    effects: Iterable[str],
    allowed_paths: Iterable[str],
) -> list[str]:
    """Infer only a human-visible, exact sealed maintenance action.

    The proposal CLI intentionally does not expose an arbitrary auto-approval
    switch.  A continuation grant exists only when the readable acceptance
    card names the registered action verbatim, declares its material effect,
    and includes the exact implementation path that will be digest-bound.
    """
    declared_effects = set(effects)
    normalized_paths = {
        str(path).replace("\\", "/").strip().removeprefix("./")
        for path in allowed_paths
    }
    profile_order = (
        "codex-plugin-cachebuster-v1",
        "codex-plugin-install-v1",
        "codex-plugin-cachebuster-v2",
        "codex-plugin-install-v2",
        "sulde-scheduler-reconcile-v1",
        "sulde-launcher-refresh-v1",
    )
    # The installer is an executable input whose exact path and digest are
    # sealed by the profile binding.  It is not a local-write target, so it
    # must not be added to allowed_paths merely to make the continuation
    # discoverable; doing so would accidentally broaden write authority over
    # release code.
    selected: list[str] = []
    cache_label_seen = False
    cache_selected = False
    for profile_id in profile_order:
        profile = CONTINUATION_PROFILES[profile_id]
        matches = [
            index
            for index, criterion in enumerate(acceptance_criteria)
            if criterion.strip() == profile["label"]
        ]
        if len(matches) > 1:
            return []
        if not matches:
            continue
        is_cache = profile_id.startswith("codex-plugin-cachebuster-")
        cache_label_seen = cache_label_seen or is_cache
        ready = profile["effect"] in declared_effects
        if is_cache:
            ready = ready and (
                "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
                in normalized_paths
            )
            cache_selected = cache_selected or ready
        if ready:
            selected.append(f"{profile_id}@{matches[0] + 1}")
    if cache_label_seen and not cache_selected:
        return []
    return selected

def _agent_continuation_eligibility(
    proposal: dict[str, Any],
) -> tuple[bool, list[str], set[str]]:
    """Validate the narrow machine-verifiable continuation lane.

    A continuation grant is not safe because it is called a grant.  It is safe
    only when it names a registered host-local profile, is one-shot, has an
    exact content verifier and a concrete rollback, and does not turn a
    digest-bound executable input into a writable path.
    """
    grants = proposal.get("continuation", {}).get("grants", [])
    if not grants:
        return False, [], set()
    reasons: list[str] = []
    covered_effects: set[str] = set()
    local_targets: set[str] = set()
    for grant in grants:
        if not isinstance(grant, dict):
            reasons.append("续行动作不是结构化 grant")
            continue
        profile_id = str(grant.get("profile_id") or "")
        if profile_id not in AGENT_CONTINUATION_PROFILES:
            reasons.append(f"续行动作不在 Agent 可决断白名单: {profile_id or 'unknown'}")
            continue
        if int(grant.get("max_uses") or 0) != 1:
            reasons.append(f"续行动作不是一次性授权: {profile_id}")
        if grant.get("verification_kind") != "content":
            reasons.append(f"续行动作缺少精确内容验证: {profile_id}")
        if not str(grant.get("rollback") or "").strip():
            reasons.append(f"续行动作缺少回滚方法: {profile_id}")
        effect = str(grant.get("effect") or "unknown")
        if effect not in {"local_write", "external_write"}:
            reasons.append(f"续行动作效果不在受监督范围: {profile_id}")
        else:
            covered_effects.add(effect)
        if effect == "local_write":
            local_targets.add(str(grant.get("target") or ""))
        if effect == "external_write" and grant.get("target") != "[host-local:codex-plugin]":
            reasons.append(f"续行动作不是封闭的宿主本地目标: {profile_id}")
    allowed_paths = {
        str(value).replace("\\", "/").strip().removeprefix("./")
        for value in proposal["constraints"]["allowed_paths"]
    }
    if "local_write" in covered_effects and not allowed_paths.issubset(local_targets):
        reasons.append("续行提案还包含未被专用 verifier 覆盖的本地写入路径")
    return not reasons, reasons, covered_effects

_VERIFICATION_CONTENT_KEYS = {"body", "content", "markdown", "text", "value"}

_SECRET_VALUE_PATTERN = re.compile(
    r"(?i)(?:authorization\s*[:=]\s*(?:bearer|basic)\s+\S+|"
    r"(?:api[_-]?key|token|password|secret|cookie)\s*[:=]\s*[^\s,;]+|"
    r"\b(?:ghp|github_pat|sk)-[a-z0-9_-]{12,})"
)

def event_fingerprint(event: dict[str, Any]) -> str:
    source = "\0".join(
        str(event.get(key) or "")
        for key in ("provider", "session_id", "capability", "target", "arguments_digest")
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()

def _resume_contract_locked(
    contract: dict[str, Any],
    reason: str,
    *,
    actor: str,
    provider: str = "",
    session_id: str = "",
) -> None:
    pause = _pause_state(
        contract,
        provider=provider,
        session_id=session_id,
    )
    if pause is None:
        raise IntentGuardianError("current task lane is not paused")
    if pause["requires_revision"]:
        raise IntentGuardianError(
            "pause requires an approved revised intent proposal before resume"
        )
    runtime = contract["runtime"]
    if pause["scope"] == "lane":
        _upsert_task_lane_locked(
            contract,
            provider=provider,
            session_id=session_id,
            state="bound",
            source="explicit_resume",
        )
        runtime["corrections"] = [
            row
            for row in runtime["corrections"]
            if not (
                isinstance(row, dict)
                and str(row.get("provider") or "") == provider
                and str(row.get("session_id") or "") == session_id
                and str(row.get("task_epoch") or "") == contract["task_epoch"]
            )
        ]
        _refresh_lane_pause_projection_locked(contract)
    else:
        runtime["corrections"] = [
            row
            for row in runtime["corrections"]
            if isinstance(row, dict) and str(row.get("session_id") or "")
        ]
        if _current_paused_task_lanes(contract):
            runtime["pause_scope"] = "lane"
            _refresh_lane_pause_projection_locked(contract)
        else:
            contract["status"] = "active"
            _clear_pause_projection_locked(contract)
    contract["resumed_by"] = actor
    contract["resume_reason"] = reason[:2_000]
    contract["resumed_at"] = now_iso()
    contract["resumed_lane"] = {
        "scope": str(pause["scope"]),
        "provider": provider,
        "session_id": session_id,
        "task_epoch": contract["task_epoch"],
        "original_pause": dict(pause),
        "original_pause_sha256": hashlib.sha256(
            json.dumps(pause, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _append_native_resume_event(path: Path, contract: dict, binding: dict) -> None:
    if binding["kind"] != "resume":
        return
    receipt = next(row for row in contract["runtime"]["approval_receipts"]
                   if row.get("approval_request_id") == binding["request_id"])
    _append_control_event(path, "native-decision", actor="permission-request:codex",
                          detail=f"resume:{binding['decision']}:{binding['target']}",
                          receipt_id=receipt["receipt_id"])


def _append_control_event(
    path: Path,
    action: str,
    *,
    actor: str,
    detail: str,
    receipt_id: str = "",
) -> None:
    contract = load_contract(path)
    row = {
        "schema": "sulde-intent-control-event-v1",
        "at": now_iso(),
        "action": action,
        "actor": actor,
        "detail": detail,
        "intent_id": contract["intent_id"],
        "intent_revision": contract["revision"],
    }
    if receipt_id:
        row["receipt_id"] = receipt_id
    if action == "resume" or (action == "native-decision" and detail.startswith("resume:")):
        recovery = contract.get("resumed_lane")
        if isinstance(recovery, dict) and recovery.get("original_pause_sha256"):
            # Append the exact corrected cause, not just a mutable latest-resume
            # projection. Original tool events and all effect debt stay intact.
            row["pause_recovery"] = json.loads(json.dumps(recovery))
            row["recovery_id"] = hashlib.sha256(
                (receipt_id + ":" + recovery["original_pause_sha256"]).encode()
            ).hexdigest()
            store = audit_path(path)
            with _exclusive_path_lock(store.with_name(f".{store.name}.lock")):
                if store.exists():
                    with store.open(encoding="utf-8") as handle:
                        for line in handle:
                            previous = json.loads(line)
                            if previous.get("recovery_id") == row["recovery_id"]:
                                if previous.get("pause_recovery") != recovery:
                                    raise IntentGuardianError("resume audit identity has conflicting cause")
                                return
                with store.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            return
    _append_jsonl(audit_path(path), row)

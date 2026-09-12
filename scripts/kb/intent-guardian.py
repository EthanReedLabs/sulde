#!/usr/bin/env python3
"""Manage and inspect Sulde intent guardian contracts."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import traceback

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from correction_intervention import (
    CorrectionInterventionError,
    load_projection as load_correction_projection,
    propose_correction,
    summary as correction_summary,
    transition_correction,
)
from intent_guardian import (
    IntentGuardianError,
    activate_contract,
    active_contract_path,
    apply_revision_proposal,
    contract_from_brief,
    create_revision_proposal,
    decide_proposal_as_agent,
    acknowledge_effect_intervention,
    effect_intervention_report,
    guardian_doctor,
    guardian_inventory,
    guardian_report,
    kb_home,
    load_contract,
    execute_native_decision,
    finalize_workspace_cleanup,
    native_decision_preview,
    pause_contract,
    prepare_continuation,
    prepare_pre_execution_probe,
    prepare_workspace_proposal,
    prepare_workspace_handoff,
    proposal_review_for_digest,
    proposal_review_for_provider,
    record_skill_event,
    reconcile_pending_verifications,
    reconcile_stale_local_write_events,
    rebind_workspace_contract,
    release_completed_workspace,
    retire_orphan_contract,
    resolve_effect_intervention,
    finalize_pre_execution_probe,
    resume_contract,
    workspace_root,
    write_contract,
)
from sulde_paths import launcher_home
from intent_guardian_parts.selected_task import prepare as prepare_task_continuation
from task_ownership import (
    TaskOwnershipError,
    require_agent_decision_session_binding,
)


def _contract_for_workspace(workspace: Path, home: Path) -> Path:
    path = active_contract_path(home, workspace_root(workspace))
    if not path.is_file():
        raise IntentGuardianError(f"no active intent contract for workspace: {workspace}")
    return path


def _selected_contract(args: argparse.Namespace, home: Path) -> Path:
    explicit = getattr(args, "contract", None)
    if explicit is not None:
        path = explicit.expanduser()
        if not path.is_file():
            raise IntentGuardianError(f"intent contract not found: {path}")
        return path
    return _contract_for_workspace(args.workspace, home)


def _require_human_terminal(action: str) -> None:
    if (
        os.environ.get("SULDE_GUARDIAN_STREAM_OWNER") == "1"
        or "SULDE_SELF_REPAIR_AUTO" in os.environ
    ):
        raise IntentGuardianError(
            f"legacy direct intervention action refused inside managed Agent execution: {action}; "
            "the Agent must use the paired host-native decision path and then perform "
            "the selected transition"
        )


def _add_decision_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--decision-route",
        choices=("auto", "human", "agent"),
        default="auto",
    )
    parser.add_argument(
        "--intent-kind",
        choices=("deterministic", "subjective", "unknown"),
        default="unknown",
    )
    parser.add_argument(
        "--risk",
        choices=("low", "medium", "high", "unknown"),
        default="unknown",
    )
    parser.add_argument(
        "--effect",
        action="append",
        choices=("read", "local_write", "external_write", "destructive", "unknown"),
        default=[],
    )
    parser.add_argument(
        "--reversibility",
        choices=("reversible", "compensatable", "irreversible", "unknown"),
        default="unknown",
    )
    parser.add_argument(
        "--cost",
        choices=("none", "bounded", "unbounded", "unknown"),
        default="unknown",
    )
    parser.add_argument(
        "--unattended-policy",
        choices=("agent-if-eligible", "wait"),
        default="agent-if-eligible",
        help=(
            "route fully eligible work to Agent policy before prompting; after a "
            "human prompt, five minutes only marks reassessment due (wait always "
            "forces the human route)"
        ),
    )
    parser.add_argument("--rollback", default="")
    parser.add_argument("--unknown", action="append", default=[])


def _add_host_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        choices=("claude", "codex", "unknown"),
        help="source host; defaults to the current native session environment",
    )
    parser.add_argument(
        "--session-id",
        help="source native session id; defaults to CODEX_THREAD_ID/CLAUDE_SESSION_ID",
    )


def _current_host(
    provider: str | None,
    session_id: str | None,
) -> tuple[str, str]:
    """Resolve explicit/native host identity without inspecting installed hosts."""
    selected_provider = str(provider or "").strip().lower()
    selected_session = str(session_id or "").strip()
    codex_session = os.environ.get("CODEX_THREAD_ID", "").strip()
    claude_session = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if not selected_session:
        if codex_session:
            selected_session = codex_session
            if not selected_provider:
                selected_provider = "codex"
        elif claude_session:
            selected_session = claude_session
            if not selected_provider:
                selected_provider = "claude"
    if not selected_provider:
        selected_provider = (
            os.environ.get("SULDE_HOST_PROVIDER")
            or os.environ.get("SULDE_AGENT_PROVIDER")
            or "unknown"
        ).strip().lower()
    if selected_provider not in {"claude", "codex", "unknown"}:
        selected_provider = "unknown"
    return selected_provider, selected_session[:200]


def _attach_continuation(
    review: dict[str, object],
    *,
    contract: Path,
    digest: str,
    provider: str | None,
    session_id: str | None,
) -> None:
    selected_provider, selected_session = _current_host(provider, session_id)
    if review.get("decision_route") == "human":
        review["continuation"] = prepare_continuation(
            contract,
            proposal_digest_value=digest,
            provider=selected_provider,
            session_id=selected_session,
        )
    rendered = proposal_review_for_provider(review, selected_provider)
    review.clear()
    review.update(rendered)


def _resolve_codex_hook(event: str, home: Path) -> tuple[Path, Path]:
    from launcher_contract import LauncherContractError, resolve_codex_hook_adapter

    runtime = Path(__file__).resolve().parents[2]
    try:
        return runtime, resolve_codex_hook_adapter(home, runtime, event)
    except LauncherContractError as error:
        raise IntentGuardianError(f"Codex hook runtime bridge refused: {error}") from error


def _probe_codex_hook(event: str, home: Path) -> int:
    runtime, adapter = _resolve_codex_hook(event, home)
    print(
        json.dumps(
            {
                "healthy": True,
                "event": event,
                "runtime": str(runtime),
                "adapter": str(adapter),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _write_subprocess_bytes(stream_name: str, value: object) -> None:
    if not value:
        return
    stream = getattr(sys, stream_name)
    if isinstance(value, bytes):
        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            buffer.write(value)
            buffer.flush()
            return
        value = value.decode("utf-8", errors="replace")
    stream.write(str(value))
    stream.flush()


def _valid_codex_policy_deny(event: str, stdout: object) -> bool:
    """Distinguish a real PreToolUse denial from adapter noise."""
    if event != "pre-tool-use" or not isinstance(stdout, (bytes, str)):
        return False
    try:
        text = stdout.decode("utf-8", errors="strict") if isinstance(stdout, bytes) else stdout
        payload = json.loads(text)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    output = payload.get("hookSpecificOutput")
    return (
        isinstance(output, dict)
        and output.get("hookEventName") == "PreToolUse"
        and output.get("permissionDecision") == "deny"
        and isinstance(output.get("permissionDecisionReason"), str)
        and bool(output["permissionDecisionReason"].strip())
    )


def _codex_pre_tool_failure_requires_deny(raw_payload: bytes, home: Path) -> bool:
    """Fail closed except for read, Git, and the exact native recovery surface."""
    from codex_recovery_defer import raw_payload_requires_fail_closed

    return raw_payload_requires_fail_closed(
        raw_payload,
        runtime_root=Path(__file__).resolve().parents[2],
        launcher_home=launcher_home(home),
    )


def _report_codex_pre_tool_failure(raw_payload: bytes, home: Path, detail: str) -> None:
    if _codex_pre_tool_failure_requires_deny(raw_payload, home):
        print(f"sulde: failed_closed Codex PreToolUse {detail}", file=sys.stderr)
        _emit_codex_pre_tool_failure_deny(detail)
        return
    print(
        "sulde: degraded_to_native_codex Codex PreToolUse retained native "
        f"authority for read/Git or exact recovery command ({detail})",
        file=sys.stderr,
    )


def _emit_codex_pre_tool_failure_deny(detail: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "Sulde PreToolUse policy could not complete; this material or "
                        "unknown action was not executed. Read-only diagnosis, one "
                        "plain Git command, and exact recovery commands remain "
                        f"available. ({detail})"
                    ),
                }
            },
            ensure_ascii=False,
        )
    )


def _run_codex_adapter_in_process(
    adapter: Path,
    *,
    environment: dict[str, str],
    input_bytes: bytes,
) -> subprocess.CompletedProcess[bytes]:
    """Execute the sealed adapter without another Python process."""
    old_argv = sys.argv
    old_stdin, old_stdout, old_stderr = sys.stdin, sys.stdout, sys.stderr
    old_path = list(sys.path)
    old_environment = os.environ.copy()
    stdin_bytes = io.BytesIO(input_bytes)
    stdout_bytes = io.BytesIO()
    stderr_bytes = io.BytesIO()
    sys.stdin = io.TextIOWrapper(stdin_bytes, encoding="utf-8", errors="strict")
    sys.stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8", errors="strict")
    sys.stderr = io.TextIOWrapper(stderr_bytes, encoding="utf-8", errors="replace")
    sys.argv = [str(adapter)]
    sys.path.insert(0, str(adapter.parent))
    os.environ.clear()
    os.environ.update(environment)
    os.environ["SULDE_CODEX_IN_PROCESS_HOOK"] = "1"
    returncode = 0
    try:
        runpy.run_path(str(adapter), run_name="__main__")
    except SystemExit as error:
        returncode = error.code if isinstance(error.code, int) else (0 if error.code is None else 1)
    except BaseException:
        traceback.print_exc(file=sys.stderr)
        returncode = 1
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        stdout = stdout_bytes.getvalue()
        stderr = stderr_bytes.getvalue()
        if environment.get("SULDE_BRIDGE_OWNS_OBSERVATION") == "1":
            try:
                from _hook_observer import observe_adapter
                observe_adapter(adapter, input_bytes, returncode, stdout, stderr)
                sys.stderr.flush()
                stderr = stderr_bytes.getvalue()
            except Exception:
                stderr += b"sulde: hook_observer_delivery_unavailable; action_not_retried\n"
        os.environ.clear()
        os.environ.update(old_environment)
        sys.path[:] = old_path
        sys.argv = old_argv
        sys.stdin, sys.stdout, sys.stderr = old_stdin, old_stdout, old_stderr
    return subprocess.CompletedProcess([sys.executable, str(adapter)], returncode, stdout, stderr)


def _dispatch_codex_hook(event: str, home: Path) -> int:
    """Bridge a version-pinned Hook path into the current verified runtime."""
    from host_capabilities import (
        HostCapabilityError,
        issue_host_provenance,
        provision_provenance_key,
        record_hook_failure,
    )
    from intent_guardian_parts.state import (
        ARTIFACT_GENERATION,
        LOADED_MODULE_GENERATION,
    )
    from intent_guardian_parts.session_workspace import load_session_workspace

    runtime, adapter = _resolve_codex_hook(event, home)
    environment = os.environ.copy()
    environment.update(
        {
            "SULDE_ACTIVE_RUNTIME_ROOT": str(runtime),
            "SULDE_HOOK_RUNTIME_REBOUND": "1",
            "SULDE_LOADED_MODULE_GENERATION": LOADED_MODULE_GENERATION,
            "SULDE_ARTIFACT_GENERATION": ARTIFACT_GENERATION,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    if event == "permission-request":
        environment["SULDE_CODEX_HOOK_EVENT"] = "PermissionRequest"
    input_stream = getattr(sys.stdin, "buffer", sys.stdin)
    raw_payload = input_stream.read()
    if isinstance(raw_payload, str):
        raw_payload = raw_payload.encode("utf-8")
    forwarded_payload = raw_payload
    session_id = ""
    workspace: object = os.getcwd()
    observation_workspace: object = workspace
    call_id = ""
    event_names = {
        "session-start": "SessionStart",
        "user-prompt-submit": "UserPromptSubmit",
        "pre-tool-use": "PreToolUse",
        "permission-request": "PermissionRequest",
        "post-tool-use": "PostToolUse",
        "stop": "Stop",
    }
    try:
        payload = json.loads(raw_payload.decode("utf-8")) if raw_payload.strip() else {}
        if isinstance(payload, dict):
            payload["client"] = "codex"
            payload["sulde_observation_source"] = "live_host_hook"
            session_id = str(
                payload.get("session_id")
                or payload.get("sessionId")
                or os.environ.get("CODEX_THREAD_ID")
                or ""
            )
            workspace = payload.get("cwd") or os.getcwd()
            observation_workspace = workspace
            if session_id:
                try:
                    mapping = load_session_workspace(home, "codex", session_id)
                except (IntentGuardianError, OSError, UnicodeError, ValueError):
                    mapping = None
                if isinstance(mapping, dict) and mapping.get("workspace_root"):
                    observation_workspace = str(mapping["workspace_root"])
            # Codex keeps the Hook payload cwd fixed to the session's launch
            # directory even after an explicit worktree handoff. Preserve cwd
            # for tool semantics, but bind readiness telemetry to the durable
            # session lane selected by the control plane.
            payload["sulde_workspace_root"] = str(observation_workspace)
            call_id = str(
                payload.get("call_id")
                or payload.get("toolUseId")
                or payload.get("tool_use_id")
                or payload.get("callId")
                or ""
            )
            provision_provenance_key(home)
            payload["sulde_host_provenance"] = issue_host_provenance(
                provider="codex",
                hook_event=event_names[event],
                session_id=session_id,
                workspace=observation_workspace,
                call_id=call_id,
                loaded_module_generation=LOADED_MODULE_GENERATION,
                artifact_generation=ARTIFACT_GENERATION,
                home=home,
            )
            forwarded_payload = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
    except (HostCapabilityError, UnicodeError, json.JSONDecodeError, OSError) as error:
        # A bridge that cannot establish provenance must never label the
        # observation live. The adapter still receives the original payload
        # and records it as non-authorizing/unclassified.
        environment["SULDE_HOOK_OBSERVATION_SOURCE"] = "unclassified"
        print(f"sulde host provenance unavailable: {error}", file=sys.stderr)
    try:
        completed = _run_codex_adapter_in_process(
            adapter,
            environment=environment,
            input_bytes=forwarded_payload,
        )
    except Exception as error:
        if event == "pre-tool-use":
            _report_codex_pre_tool_failure(
                raw_payload, home, f"adapter unavailable: {type(error).__name__}"
            )
        else:
            try:
                record_hook_failure(
                    provider="codex",
                    hook_event=event_names[event],
                    stage="adapter",
                    error_kind=type(error).__name__,
                    session_id=session_id,
                    workspace=observation_workspace,
                    call_id=call_id,
                    loaded_module_generation=LOADED_MODULE_GENERATION,
                    artifact_generation=ARTIFACT_GENERATION,
                    home=home,
                )
            except (HostCapabilityError, OSError, UnicodeError, ValueError):
                pass
            print(
                f"sulde: degraded_to_native_codex Codex hook adapter unavailable: {error}",
                file=sys.stderr,
            )
        return 0
    if completed.returncode == 0:
        adapter_stdout = getattr(completed, "stdout", b"")
        if event == "pre-tool-use" and (
            not adapter_stdout.strip()
            or _valid_codex_policy_deny(event, adapter_stdout)
        ):
            _write_subprocess_bytes("stdout", getattr(completed, "stdout", b""))
            _write_subprocess_bytes("stderr", getattr(completed, "stderr", b""))
            return 0
        if event == "pre-tool-use" and _codex_pre_tool_failure_requires_deny(raw_payload, home):
            _write_subprocess_bytes("stderr", getattr(completed, "stderr", b""))
            print(
                "sulde: failed_closed Codex hook adapter returned no valid policy decision",
                file=sys.stderr,
            )
            _emit_codex_pre_tool_failure_deny("invalid or empty policy response")
            return 0
        if event == "pre-tool-use":
            # Invalid adapter bytes are never forwarded as a host policy
            # response. Read-only and plain Git stay available by returning
            # one intentionally empty native decision.
            _write_subprocess_bytes("stderr", getattr(completed, "stderr", b""))
            return 0
        _write_subprocess_bytes("stdout", getattr(completed, "stdout", b""))
        _write_subprocess_bytes("stderr", getattr(completed, "stderr", b""))
        return 0
    if completed.returncode == 2 and _valid_codex_policy_deny(
        event, getattr(completed, "stdout", b"")
    ):
        _write_subprocess_bytes("stdout", getattr(completed, "stdout", b""))
        _write_subprocess_bytes("stderr", getattr(completed, "stderr", b""))
        # A structured Codex deny is a successful Hook response. Exit 2 is a
        # separate stderr-only protocol and must not be combined with JSON
        # stdout or Codex treats the Hook as failed and continues the tool.
        return 0
    _write_subprocess_bytes("stderr", getattr(completed, "stderr", b""))
    if event == "pre-tool-use":
        _report_codex_pre_tool_failure(
            raw_payload, home, f"adapter exited {completed.returncode}"
        )
    else:
        try:
            record_hook_failure(
                provider="codex",
                hook_event=event_names[event],
                stage="adapter",
                error_kind="nonzero_exit",
                session_id=session_id,
                workspace=observation_workspace,
                call_id=call_id,
                exit_code=completed.returncode,
                loaded_module_generation=LOADED_MODULE_GENERATION,
                artifact_generation=ARTIFACT_GENERATION,
                home=home,
            )
        except (HostCapabilityError, OSError, UnicodeError, ValueError):
            pass
        print(
            f"sulde: degraded_to_native_codex Codex hook adapter exited "
            f"{completed.returncode}",
            file=sys.stderr,
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)

    codex_hook = actions.add_parser(
        "codex-hook",
        help="dispatch one Codex Hook through the current verified runtime",
    )
    codex_hook.add_argument(
        "event",
        choices=(
            "session-start",
            "user-prompt-submit",
            "pre-tool-use",
            "permission-request",
            "post-tool-use",
            "stop",
        ),
    )
    codex_hook.add_argument("--home", type=Path)

    codex_hook_probe = actions.add_parser(
        "codex-hook-probe",
        help="verify one Codex Hook adapter without consuming Hook stdin",
    )
    codex_hook_probe.add_argument(
        "event",
        choices=(
            "session-start",
            "user-prompt-submit",
            "pre-tool-use",
            "permission-request",
            "post-tool-use",
            "stop",
        ),
    )
    codex_hook_probe.add_argument("--home", type=Path)

    create_direct = actions.add_parser("create", help="create an explicit interactive intent contract")
    create_direct.add_argument("--intent-id", required=True)
    create_direct.add_argument("--objective", required=True)
    create_direct.add_argument("--accept", action="append", required=True)
    create_direct.add_argument("--rationale", default="")
    create_direct.add_argument("--preserve", action="append", default=[])
    create_direct.add_argument("--reject", action="append", default=[])
    create_direct.add_argument("--allow-path", action="append", default=[])
    create_direct.add_argument("--workspace", type=Path, default=Path.cwd())
    create_direct.add_argument("--output", type=Path, required=True)
    create_direct.add_argument("--mode", choices=("off", "shadow", "enforce"), default="enforce")
    create_direct.add_argument("--semantic-critic", action="store_true")

    revise = actions.add_parser(
        "revise",
        help="deprecated human-only direct revision; prefer propose-revision + approve/apply-proposal",
    )
    revise.add_argument("contract", type=Path)
    revise.add_argument("--objective", required=True)
    revise.add_argument("--accept", action="append", required=True)
    revise.add_argument("--rationale", default="")
    revise.add_argument("--preserve", action="append", default=[])
    revise.add_argument("--reject", action="append", default=[])
    revise.add_argument("--allow-path", action="append", default=[])
    revise.add_argument("--mode", choices=("shadow", "enforce"), default="enforce")
    revise.add_argument("--semantic-critic", action="store_true")
    _add_decision_args(revise)
    _add_host_args(revise)

    create = actions.add_parser("create-from-brief", help="create a contract from one approved L3 brief")
    create.add_argument("brief", type=Path)
    create.add_argument("--slug", required=True)
    create.add_argument("--workspace", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--mode", choices=("off", "shadow", "enforce"), default="shadow")
    create.add_argument("--semantic-critic", action="store_true")

    activate = actions.add_parser("activate", help="activate a validated contract for a workspace")
    activate.add_argument("contract", type=Path)
    activate.add_argument("--workspace", type=Path, default=Path.cwd())
    activate.add_argument("--home", type=Path)
    activate.add_argument("--provider", choices=("claude", "codex", "unknown"))
    activate.add_argument("--session-id")

    show = actions.add_parser("show", help="show an active workspace contract")
    show.add_argument("--contract", type=Path)
    show.add_argument("--workspace", type=Path, default=Path.cwd())
    show.add_argument("--home", type=Path)

    pause = actions.add_parser("pause", help="pause writes under an active contract")
    pause.add_argument("reason")
    pause.add_argument("--contract", type=Path)
    pause.add_argument("--workspace", type=Path, default=Path.cwd())
    pause.add_argument("--home", type=Path)

    resume = actions.add_parser("resume", help="human-resume a paused contract with a new revision")
    resume.add_argument("reason")
    resume.add_argument("--contract", type=Path)
    resume.add_argument("--workspace", type=Path, default=Path.cwd())
    resume.add_argument("--home", type=Path)
    _add_host_args(resume)

    approve = actions.add_parser(
        "approve-event",
        help="retired compatibility command; event digests never grant authority",
    )
    approve.add_argument("fingerprint")
    approve.add_argument("--contract", type=Path)
    approve.add_argument("--workspace", type=Path, default=Path.cwd())
    approve.add_argument("--home", type=Path)

    propose = actions.add_parser("propose-revision", help="create an immutable intent revision candidate")
    propose.add_argument("contract", type=Path)
    propose.add_argument("--objective", required=True)
    propose.add_argument("--accept", action="append", required=True)
    propose.add_argument("--rationale", default="")
    propose.add_argument("--preserve", action="append", default=[])
    propose.add_argument("--reject", action="append", default=[])
    propose.add_argument("--allow-path", action="append", default=[])
    propose.add_argument("--memory-dependency", choices=("dependent", "independent"), default="dependent")
    propose.add_argument("--mode", choices=("shadow", "enforce"), default="enforce")
    propose.add_argument("--semantic-critic", action="store_true")
    propose.add_argument(
        "--apply-agent-eligible",
        action="store_true",
        help=(
            "decide and apply the proposal in this process only when the deterministic "
            "Agent gate selects the agent route"
        ),
    )
    propose.add_argument("--agent-rationale", default="")
    propose.add_argument("--agent-evidence", action="append", default=[])
    _add_decision_args(propose)
    _add_host_args(propose)

    prepare = actions.add_parser(
        "prepare-proposal",
        help="safely bootstrap a workspace and render one reviewable proposal",
    )
    prepare.add_argument("--intent-id")
    prepare.add_argument("--objective", required=True)
    prepare.add_argument("--accept", action="append", required=True)
    prepare.add_argument("--rationale", default="")
    prepare.add_argument("--preserve", action="append", default=[])
    prepare.add_argument("--reject", action="append", default=[])
    prepare.add_argument("--allow-path", action="append", default=[])
    prepare.add_argument("--memory-dependency", choices=("dependent", "independent"), default="dependent")
    prepare.add_argument("--workspace", type=Path, default=Path.cwd())
    prepare.add_argument("--home", type=Path)
    prepare.add_argument("--mode", choices=("shadow", "enforce"), default="enforce")
    prepare.add_argument("--semantic-critic", action="store_true")
    _add_decision_args(prepare)
    _add_host_args(prepare)

    continuation = actions.add_parser(
        "prepare-continuation",
        help="mechanically freeze an authority-free recovery capsule for the pending proposal",
    )
    continuation.add_argument("--contract", type=Path)
    continuation.add_argument("--workspace", type=Path, default=Path.cwd())
    continuation.add_argument("--home", type=Path)
    _add_host_args(continuation)

    proposal_show = actions.add_parser(
        "proposal-show",
        help="show the exact human-readable content bound to one proposal digest",
    )
    proposal_show.add_argument("digest")
    proposal_show.add_argument("--contract", type=Path)
    proposal_show.add_argument("--workspace", type=Path, default=Path.cwd())
    proposal_show.add_argument("--home", type=Path)
    _add_host_args(proposal_show)

    approve_revision = actions.add_parser(
        "approve-proposal",
        help="retired non-interactive approval command; use a live host prompt",
    )
    approve_revision.add_argument("digest")
    approve_revision.add_argument("--contract", type=Path)
    approve_revision.add_argument("--workspace", type=Path, default=Path.cwd())
    approve_revision.add_argument("--home", type=Path)

    apply_revision = actions.add_parser(
        "apply-proposal",
        help="apply an immutable proposal after human-card or Agent-policy decision",
    )
    apply_revision.add_argument("proposal", type=Path)
    apply_revision.add_argument("--contract", type=Path)
    apply_revision.add_argument("--workspace", type=Path, default=Path.cwd())
    apply_revision.add_argument("--home", type=Path)

    agent_decide = actions.add_parser(
        "agent-decide-proposal",
        help="approve one deterministically eligible low-risk proposal as Agent authority",
    )
    agent_decide.add_argument("digest")
    agent_decide.add_argument("--rationale", required=True)
    agent_decide.add_argument("--evidence", action="append", required=True)
    agent_decide.add_argument("--provider", choices=("claude", "codex"), required=True)
    agent_decide.add_argument(
        "--session-id",
        required=True,
        help="exact current host session; Codex must match CODEX_THREAD_ID when present",
    )
    agent_decide.add_argument("--contract", type=Path)
    agent_decide.add_argument("--workspace", type=Path, default=Path.cwd())
    agent_decide.add_argument("--home", type=Path)

    for action, help_text in (
        (
            "native-decision-preview",
            "render the exact current-session Codex approval command and readable text",
        ),
        (
            "native-decision",
            "consume one paired Codex PermissionRequest and apply its exact decision",
        ),
    ):
        native = actions.add_parser(action, help=help_text)
        native.add_argument(
            "kind",
            choices=(
                "proposal",
                "grant",
                "intent",
                "resume",
                "task-continuation",
                "workspace-handoff",
                "observation-export",
                "effect-intervention",
            ),
        )
        native.add_argument("--decision", required=True)
        native.add_argument("--target", default="current")
        native.add_argument("--provider", choices=("codex",), required=True)
        native.add_argument("--session-id", required=True)
        native.add_argument("--contract", type=Path)
        native.add_argument("--workspace", type=Path, default=Path.cwd())
        native.add_argument("--home", type=Path)

    proof_prepare = actions.add_parser(
        "pre-execution-proof-prepare",
        help="prepare one exact negative canary for the current host session",
    )
    proof_prepare.add_argument("--provider", choices=("claude", "codex"), required=True)
    proof_prepare.add_argument("--session-id", required=True)
    proof_prepare.add_argument("--contract", type=Path)
    proof_prepare.add_argument("--workspace", type=Path, default=Path.cwd())
    proof_prepare.add_argument("--home", type=Path)

    proof_finalize = actions.add_parser(
        "pre-execution-proof-finalize",
        help="verify a denied canary and clear only its matching session gap",
    )
    proof_finalize.add_argument("--probe-id", required=True)
    proof_finalize.add_argument("--provider", choices=("claude", "codex"), required=True)
    proof_finalize.add_argument("--session-id", required=True)
    proof_finalize.add_argument("--contract", type=Path)
    proof_finalize.add_argument("--workspace", type=Path, default=Path.cwd())
    proof_finalize.add_argument("--home", type=Path)

    selection = actions.add_parser("prepare-task-continuation", help="select an old task for authority-free native review")
    selection.add_argument("source_contract", type=Path)
    selection.add_argument("--contract", type=Path, required=True)
    selection.add_argument("--provider", choices=("codex",), required=True)
    selection.add_argument("--session-id", required=True)
    selection.add_argument("--home", type=Path)

    handoff = actions.add_parser(
        "prepare-workspace-handoff",
        help="prepare an authority-free target worktree contract for native handoff",
    )
    handoff.add_argument("target_workspace", type=Path)
    handoff.add_argument("--contract", type=Path, required=True)
    handoff.add_argument("--provider", choices=("claude", "codex"), required=True)
    handoff.add_argument("--session-id", required=True)
    handoff.add_argument("--home", type=Path)

    observations = actions.add_parser(
        "rebuild-host-observations",
        help="bounded rebuild of derived lifecycle telemetry; no task/approval/effect mutation",
    )
    observations.add_argument("--provider", choices=("claude", "codex"), required=True)
    observations.add_argument("--session-id", required=True)
    observations.add_argument("--max-bytes", type=int, default=8 * 1024 * 1024)
    observations.add_argument("--recover-current-transition", action="store_true")
    observations.add_argument("--recover-history", action="store_true",
                              help="also recover validated completed historical release pairs")

    release = actions.add_parser(
        "release-completed-workspace",
        help=(
            "deauthorize one clean task already merged into dev and publish a "
            "retryable Agent cleanup anchor; performs no Git mutation"
        ),
    )
    release.add_argument("target_workspace", type=Path)
    release.add_argument("--contract", type=Path, required=True)
    release.add_argument("--provider", choices=("claude", "codex"), required=True)
    release.add_argument("--session-id", required=True)
    release.add_argument("--home", type=Path)

    cleanup = actions.add_parser(
        "finalize-workspace-cleanup",
        help="seal the cleanup receipt after Agent-owned Git removal is observable",
    )
    cleanup.add_argument("--contract", type=Path, required=True)
    cleanup.add_argument("--provider", choices=("claude", "codex"), required=True)
    cleanup.add_argument("--session-id", required=True)
    cleanup.add_argument("--home", type=Path)

    report = actions.add_parser("report", help="summarize guardian events for a workspace")
    report.add_argument("--contract", type=Path)
    report.add_argument("--workspace", type=Path, default=Path.cwd())
    report.add_argument("--home", type=Path)
    report.add_argument(
        "--scan",
        action="store_true",
        help="stream the complete historical audit instead of the bounded tail",
    )

    reconcile = actions.add_parser(
        "reconcile-verifications",
        help=(
            "run registered independent verifiers at a trusted host boundary; "
            "never replay the original effect"
        ),
    )
    reconcile.add_argument("--contract", type=Path)
    reconcile.add_argument("--workspace", type=Path, default=Path.cwd())
    reconcile.add_argument("--home", type=Path)

    interventions = actions.add_parser(
        "interventions",
        help="list durable external-effect attempts and human interventions",
    )
    interventions.add_argument("--contract", type=Path)
    interventions.add_argument("--workspace", type=Path, default=Path.cwd())
    interventions.add_argument("--home", type=Path)

    corrections = actions.add_parser(
        "corrections",
        help="list durable user/Agent correction interventions",
    )
    corrections.add_argument("--contract", type=Path)
    corrections.add_argument("--workspace", type=Path, default=Path.cwd())
    corrections.add_argument("--home", type=Path)

    correction_propose = actions.add_parser(
        "correction-propose",
        help="queue one correction for the selected interactive or managed lane",
    )
    correction_propose.add_argument("message")
    correction_propose.add_argument(
        "--actor", choices=("human", "agent"), default="human"
    )
    correction_propose.add_argument(
        "--provider", choices=("claude", "codex"), required=True
    )
    correction_propose.add_argument("--session-id", required=True)
    correction_propose.add_argument("--request-id", default="")
    correction_propose.add_argument("--contract", type=Path)
    correction_propose.add_argument("--workspace", type=Path, default=Path.cwd())
    correction_propose.add_argument("--home", type=Path)

    correction_resolve = actions.add_parser(
        "correction-resolve",
        help="human-reject or cancel one queued correction without claiming it was applied",
    )
    correction_resolve.add_argument("intervention_id")
    correction_resolve.add_argument(
        "--state", choices=("rejected", "cancelled"), required=True
    )
    correction_resolve.add_argument("--reason-code", required=True)
    correction_resolve.add_argument("--contract", type=Path)
    correction_resolve.add_argument("--workspace", type=Path, default=Path.cwd())
    correction_resolve.add_argument("--home", type=Path)

    intervention_show = actions.add_parser(
        "intervention-show",
        help="show one external-effect intervention",
    )
    intervention_show.add_argument("intervention_id")
    intervention_show.add_argument("--contract", type=Path)
    intervention_show.add_argument("--workspace", type=Path, default=Path.cwd())
    intervention_show.add_argument("--home", type=Path)

    intervention_ack = actions.add_parser(
        "intervention-ack",
        help="human-acknowledge one open external-effect intervention",
    )
    intervention_ack.add_argument("intervention_id")
    intervention_ack.add_argument("--contract", type=Path)
    intervention_ack.add_argument("--workspace", type=Path, default=Path.cwd())
    intervention_ack.add_argument("--home", type=Path)

    intervention_resolve = actions.add_parser(
        "intervention-resolve",
        help="human-resolve one intervention with an explicit decision and evidence",
    )
    intervention_resolve.add_argument("intervention_id")
    intervention_resolve.add_argument(
        "--decision",
        required=True,
        choices=(
            "human_attested_success",
            "confirmed_failed",
            "reprobe_authorized",
            "retry_authorized",
            "abort",
        ),
    )
    intervention_resolve.add_argument("--evidence", required=True)
    intervention_resolve.add_argument("--contract", type=Path)
    intervention_resolve.add_argument("--workspace", type=Path, default=Path.cwd())
    intervention_resolve.add_argument("--home", type=Path)

    doctor = actions.add_parser(
        "doctor",
        help="report whether live host approval capture is actually observed",
    )
    doctor.add_argument("--workspace", type=Path, default=Path.cwd())
    doctor.add_argument("--home", type=Path)
    doctor.add_argument(
        "--provider",
        choices=("claude", "codex"),
        help="require live prompt evidence from this host instead of either host",
    )
    doctor.add_argument(
        "--session-id",
        help="check this exact native session; defaults to the current host session id",
    )
    doctor.add_argument(
        "--scan",
        action="store_true",
        help="inventory every active contract and report orphaned workspace roots",
    )

    rebind = actions.add_parser(
        "rebind-workspace",
        help="human-migrate one orphaned contract and force fresh intent review",
    )
    rebind.add_argument("new_workspace", type=Path)
    rebind.add_argument("--contract", type=Path, required=True)
    rebind.add_argument("--reason", required=True)
    rebind.add_argument("--home", type=Path)

    retire = actions.add_parser(
        "retire-workspace",
        help="human-archive one abandoned orphaned workspace contract",
    )
    retire.add_argument("--contract", type=Path, required=True)
    retire.add_argument("--reason", required=True)
    retire.add_argument("--home", type=Path)

    for action, help_text in (
        ("skill-start", "register the start of a Skill at a host boundary"),
        ("skill-end", "register the completion of a Skill at a host boundary"),
    ):
        skill = actions.add_parser(action, help=help_text)
        skill.add_argument("name")
        skill.add_argument("--skill-path", type=Path, required=True)
        skill.add_argument("--provider", choices=("claude", "codex", "unknown"), required=True)
        skill.add_argument("--session-id", required=True)
        skill.add_argument("--contract", type=Path)
        skill.add_argument("--workspace", type=Path, default=Path.cwd())
        skill.add_argument("--home", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    home = (getattr(args, "home", None) or kb_home()).expanduser()
    try:
        if args.action == "codex-hook-probe":
            return _probe_codex_hook(args.event, home)
        if args.action == "codex-hook":
            return _dispatch_codex_hook(args.event, home)
        if args.action in {
            "intervention-ack",
            "intervention-resolve",
            "correction-resolve",
        } or (args.action == "correction-propose" and args.actor == "human"):
            _require_human_terminal(args.action)
        if args.action == "create":
            from intent_guardian import default_contract

            contract = default_contract(
                intent_id=args.intent_id,
                objective=args.objective,
                acceptance_criteria=args.accept,
                workspace=args.workspace,
                mode=args.mode,
                rationale=args.rationale,
                preserve=args.preserve,
                reject=args.reject,
                allowed_paths=args.allow_path,
                confirmed_by="unconfirmed",
                semantic_critic=args.semantic_critic,
                confirmation_required=True,
            )
            write_contract(args.output.expanduser(), contract)
            print(
                f"INTENT CONTRACT: CREATED path={args.output} mode={args.mode} "
                "authority=unconfirmed"
            )
            return 0
        if args.action == "revise":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            proposal, digest = create_revision_proposal(
                args.contract.expanduser(),
                objective=args.objective,
                acceptance_criteria=args.accept,
                mode=args.mode,
                rationale=args.rationale,
                preserve=args.preserve,
                reject=args.reject,
                allowed_paths=args.allow_path,
                semantic_critic=args.semantic_critic,
                decision_route=args.decision_route,
                intent_kind=args.intent_kind,
                risk=args.risk,
                effects=args.effect or ["unknown"],
                reversibility=args.reversibility,
                cost=args.cost,
                unattended_policy=args.unattended_policy,
                rollback=args.rollback,
                unknowns=args.unknown,
                provider=selected_provider,
                session_id=selected_session,
            )
            review = proposal_review_for_digest(args.contract.expanduser(), digest)
            _attach_continuation(
                review,
                contract=args.contract.expanduser(),
                digest=digest,
                provider=selected_provider,
                session_id=selected_session,
            )
            print(json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "propose-revision":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            proposal, digest = create_revision_proposal(
                args.contract.expanduser(),
                objective=args.objective,
                acceptance_criteria=args.accept,
                mode=args.mode,
                rationale=args.rationale,
                preserve=args.preserve,
                reject=args.reject,
                allowed_paths=args.allow_path,
                semantic_critic=args.semantic_critic,
                memory_dependency=args.memory_dependency,
                decision_route=args.decision_route,
                intent_kind=args.intent_kind,
                risk=args.risk,
                effects=args.effect or ["unknown"],
                reversibility=args.reversibility,
                cost=args.cost,
                unattended_policy=args.unattended_policy,
                rollback=args.rollback,
                unknowns=args.unknown,
                provider=selected_provider,
                session_id=selected_session,
            )
            review = proposal_review_for_digest(args.contract.expanduser(), digest)
            _attach_continuation(
                review,
                contract=args.contract.expanduser(),
                digest=digest,
                provider=selected_provider,
                session_id=selected_session,
            )
            if args.apply_agent_eligible:
                if review["decision_route"] != "agent":
                    raise IntentGuardianError(
                        "atomic Agent apply is available only when the deterministic gate "
                        "selects decision_route=agent"
                    )
                if not args.agent_rationale.strip() or not args.agent_evidence:
                    raise IntentGuardianError(
                        "atomic Agent apply requires --agent-rationale and at least one "
                        "--agent-evidence item"
                    )
                decision = decide_proposal_as_agent(
                    args.contract.expanduser(),
                    digest,
                    rationale=args.agent_rationale,
                    evidence=args.agent_evidence,
                    provider=selected_provider,
                    session_id=selected_session,
                )
                applied = apply_revision_proposal(
                    args.contract.expanduser(),
                    proposal,
                )
                review["agent_decision"] = decision
                review["applied_revision"] = applied["revision"]
                review["applied_decision_authority"] = applied[
                    "applied_decision_authority"
                ]
            print(json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "prepare-proposal":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            existing_path = active_contract_path(home, args.workspace)
            if existing_path.is_file():
                reconcile_stale_local_write_events(
                    existing_path,
                    provider=selected_provider,
                    session_id=selected_session,
                )
            _, _, _, review = prepare_workspace_proposal(
                home,
                args.workspace,
                intent_id=args.intent_id,
                objective=args.objective,
                acceptance_criteria=args.accept,
                mode=args.mode,
                rationale=args.rationale,
                preserve=args.preserve,
                reject=args.reject,
                allowed_paths=args.allow_path,
                semantic_critic=args.semantic_critic,
                memory_dependency=args.memory_dependency,
                decision_route=args.decision_route,
                intent_kind=args.intent_kind,
                risk=args.risk,
                effects=args.effect or ["unknown"],
                reversibility=args.reversibility,
                cost=args.cost,
                unattended_policy=args.unattended_policy,
                rollback=args.rollback,
                unknowns=args.unknown,
                provider=selected_provider,
                session_id=selected_session,
            )
            print(json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "rebuild-host-observations":
            from host_capabilities import _assert_test_write_isolated, _read_provenance_key, _valid_observation
            from host_observation_index import rebuild_step
            selected_provider, selected_session = _current_host(args.provider, args.session_id)
            _assert_test_write_isolated(home, explicit_home=True)
            try:
                result = rebuild_step(home, selected_provider, selected_session,
                                      key=_read_provenance_key(home),
                                      validate=lambda row: _valid_observation(row, home), max_bytes=args.max_bytes)
            except (OSError, ValueError, TypeError, RuntimeError) as error:
                result = {"status": "inconclusive", "error_kind": type(error).__name__,
                          "source_modified": False, "authority_transferred": False}
            if (args.recover_current_transition or args.recover_history) and result["status"] == "complete":
                from session_lifecycle_lineage import recover_current_transition
                result["workspace_lineage"] = recover_current_transition(
                    home, provider=selected_provider, session_id=selected_session)
            if args.recover_history and result["status"] == "complete":
                from session_lifecycle_history import recover_history
                result["historical_lineage"] = recover_history(
                    home, provider=selected_provider, session_id=selected_session)
                if result["historical_lineage"]["status"] == "inconclusive":
                    result["status"] = "inconclusive"
            print(json.dumps(result, sort_keys=True))
            return 1 if result["status"] == "inconclusive" else 0
        if args.action == "prepare-task-continuation":
            selected_provider, selected_session = _current_host(args.provider, args.session_id)
            result = prepare_task_continuation(args.contract, args.source_contract,
                provider=selected_provider, session_id=selected_session)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "prepare-workspace-handoff":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            result = prepare_workspace_handoff(
                home,
                args.contract,
                args.target_workspace,
                provider=selected_provider,
                session_id=selected_session,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "release-completed-workspace":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            result = release_completed_workspace(
                home,
                args.contract,
                args.target_workspace,
                provider=selected_provider,
                session_id=selected_session,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "finalize-workspace-cleanup":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            result = finalize_workspace_cleanup(
                home,
                args.contract,
                provider=selected_provider,
                session_id=selected_session,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "create-from-brief":
            brief = args.brief.expanduser().read_text(encoding="utf-8")
            contract = contract_from_brief(
                brief,
                slug=args.slug,
                workspace=args.workspace,
                mode=args.mode,
                semantic_critic=args.semantic_critic,
            )
            write_contract(args.output.expanduser(), contract)
            print(f"INTENT CONTRACT: CREATED path={args.output} mode={args.mode}")
            return 0
        if args.action == "activate":
            path = activate_contract(
                args.contract.expanduser(),
                home=home,
                workspace=args.workspace,
                provider=args.provider,
                session_id=args.session_id,
            )
            print(f"INTENT CONTRACT: ACTIVE path={path}")
            return 0
        if args.action == "doctor":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            report = (
                guardian_inventory(
                    home,
                    provider=None if selected_provider == "unknown" else selected_provider,
                )
                if args.scan
                else guardian_doctor(
                    home,
                    args.workspace,
                    provider=None if selected_provider == "unknown" else selected_provider,
                    session_id=selected_session or None,
                )
            )
            print(
                json.dumps(
                    report,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.action == "rebind-workspace":
            result = rebind_workspace_contract(
                args.contract,
                home=home,
                new_workspace=args.new_workspace,
                reason=args.reason,
                actor="human-cli",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.action == "retire-workspace":
            result = retire_orphan_contract(
                args.contract,
                home=home,
                reason=args.reason,
                actor="human-cli",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0

        path = _selected_contract(args, home)
        if args.action == "show":
            print(json.dumps(load_contract(path), ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action == "prepare-continuation":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            print(
                json.dumps(
                    prepare_continuation(
                        path,
                        provider=selected_provider,
                        session_id=selected_session,
                    ),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.action == "proposal-show":
            selected_provider, _ = _current_host(
                args.provider,
                args.session_id,
            )
            print(
                json.dumps(
                    proposal_review_for_provider(
                        proposal_review_for_digest(path, args.digest),
                        selected_provider,
                    ),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.action == "pause":
            pause_contract(path, args.reason, actor="cli")
            print(f"INTENT CONTRACT: PAUSED path={path}")
        elif args.action == "resume":
            selected_provider, selected_session = _current_host(
                args.provider,
                args.session_id,
            )
            resume_contract(
                path,
                args.reason,
                actor="human-cli",
                provider=selected_provider,
                session_id=selected_session,
            )
            print(f"INTENT CONTRACT: ACTIVE path={path}")
        elif args.action == "approve-event":
            raise IntentGuardianError(
                "event digest approval is retired; authorize readable task scope and let "
                "the supervisor verify observable effects"
            )
        elif args.action == "approve-proposal":
            raise IntentGuardianError(
                "non-interactive CLI approval is retired; use the current conversation's "
                "readable Allow/Deny decision surface"
            )
        elif args.action == "apply-proposal":
            applied = apply_revision_proposal(path, args.proposal.expanduser())
            print(
                f"INTENT PROPOSAL: APPLIED digest={applied['applied_proposal_digest']} "
                f"revision={applied['revision']} path={path}"
            )
        elif args.action == "agent-decide-proposal":
            decision_session = require_agent_decision_session_binding(
                provider=args.provider,
                session_id=args.session_id,
                observed_codex_session=os.environ.get("CODEX_THREAD_ID", ""),
            )
            result = decide_proposal_as_agent(
                path,
                args.digest,
                rationale=args.rationale,
                evidence=args.evidence,
                provider=args.provider,
                session_id=decision_session,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action == "pre-execution-proof-prepare":
            result = prepare_pre_execution_probe(
                path,
                provider=args.provider,
                session_id=args.session_id,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action == "pre-execution-proof-finalize":
            result = finalize_pre_execution_probe(
                path,
                provider=args.provider,
                session_id=args.session_id,
                probe_id=args.probe_id,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action in {"native-decision-preview", "native-decision"}:
            if args.provider != "codex":  # argparse currently enforces this too.
                raise IntentGuardianError("native decisions require provider=codex")
            if args.action == "native-decision-preview":
                result = native_decision_preview(
                    path,
                    kind=args.kind,
                    decision=args.decision,
                    target=args.target,
                    provider=args.provider,
                    session_id=args.session_id,
                )
            else:
                result = execute_native_decision(
                    path,
                    kind=args.kind,
                    decision=args.decision,
                    target=args.target,
                    provider=args.provider,
                    session_id=args.session_id,
                )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action == "interventions":
            print(
                json.dumps(
                    effect_intervention_report(path),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.action == "reconcile-verifications":
            reconciled = reconcile_pending_verifications(
                path, recover_rollout_reads=True
            )
            current = load_contract(path)
            print(
                json.dumps(
                    {
                        "schema": "sulde-verification-reconciliation-v1",
                        "reconciled_attempt_ids": [
                            str(row["attempt_id"]) for row in reconciled
                        ],
                        "reconciled_count": len(reconciled),
                        "pending_verifications": len(
                            current["runtime"]["pending_verifications"]
                        ),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.action == "corrections":
            projection = load_correction_projection(path)
            print(
                json.dumps(
                    {
                        **correction_summary(path),
                        "items": list(projection["interventions"].values()),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.action == "correction-propose":
            contract = load_contract(path)
            result = propose_correction(
                path,
                intent_id=contract["intent_id"],
                intent_revision=contract["revision"],
                provider=args.provider,
                session_id=args.session_id,
                correction=args.message,
                actor=args.actor,
                source="human_terminal" if args.actor == "human" else "agent_monitor",
                request_id=args.request_id,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action == "correction-resolve":
            result = transition_correction(
                path,
                args.intervention_id,
                state=args.state,
                boundary="manual",
                reason_code=args.reason_code,
                actor="human",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action == "intervention-show":
            report = effect_intervention_report(path)
            matches = [
                row
                for row in report["interventions"]
                if row.get("intervention_id") == args.intervention_id
            ]
            if len(matches) != 1:
                raise IntentGuardianError(
                    f"expected exactly one intervention {args.intervention_id}; found={len(matches)}"
                )
            print(json.dumps(matches[0], ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action == "intervention-ack":
            result = acknowledge_effect_intervention(
                path,
                args.intervention_id,
                actor="human-cli",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action == "intervention-resolve":
            result = resolve_effect_intervention(
                path,
                args.intervention_id,
                decision=args.decision,
                evidence=args.evidence,
                actor="human-cli",
            )
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        elif args.action in {"skill-start", "skill-end"}:
            decision = record_skill_event(
                path,
                name=args.name,
                phase="started" if args.action == "skill-start" else "completed",
                provider=args.provider,
                session_id=args.session_id,
                skill_path=args.skill_path,
            )
            print(
                f"INTENT SKILL: {decision.action.upper()} phase={args.action} "
                f"name={args.name} fingerprint={decision.fingerprint} path={path}"
            )
            if decision.action == "deny":
                print(f"INTENT SKILL: DENIED: {decision.reason}", file=sys.stderr)
                return 3
        else:
            print(
                json.dumps(
                    guardian_report(
                        path,
                        deep_audit=bool(getattr(args, "scan", False)),
                    ),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    except (
        IntentGuardianError,
        TaskOwnershipError,
        CorrectionInterventionError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        print(f"INTENT GUARDIAN: FAIL: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

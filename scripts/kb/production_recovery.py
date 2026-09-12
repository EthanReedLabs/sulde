#!/usr/bin/env python3
"""Always-reachable sealed RecoveryLane adapter for production PreTool."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from codex_recovery_defer import native_recovery_read_action
from intent_guardian_parts.state import Decision, IntentGuardianError, RUNTIME_GENERATION, event_fingerprint
from recovery_lane import RecoveryLane, RecoveryLaneError, REQUEST_SCHEMA
from sulde_paths import layout


def recovery_pre_state(contract_path: Path) -> dict[str, Any]:
    """Project a bounded state even when the ordinary contract is unreadable."""
    try:
        raw = json.loads(contract_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema") != "sulde-intent-contract-v1":
            raise ValueError("schema")
        runtime = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
        return {
            "contract": "valid",
            "status": str(raw.get("status") or "unknown"),
            "revision": int(raw.get("revision") or 0),
            "pause_class": str(runtime.get("pause_class") or ""),
            "pending_proposal": bool(runtime.get("pending_proposal_digest")),
            "pending_verifications": len(runtime.get("pending_verifications") or []),
        }
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return {
            "contract": "schema_invalid",
            "status": "unavailable",
            "revision": 0,
            "pause_class": "",
            "pending_proposal": False,
            "pending_verifications": 0,
        }


def _seal_key(path: Path) -> bytes:
    # Keys are binary. strip() randomly invalidates keys beginning/ending in
    # whitespace bytes and disagrees with installation/readiness.
    from production_recovery_readiness import _private_key
    return _private_key(path)


def _request(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(raw_input, dict):
        return None
    request = raw_input.get("sulde_recovery_request")
    return request if isinstance(request, dict) and request.get("schema") == REQUEST_SCHEMA else None


def _command(payload: dict[str, Any]) -> str:
    raw_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(raw_input, dict):
        return ""
    return str(raw_input.get("command") or raw_input.get("cmd") or "").strip()


def route_production_recovery(
    payload: dict[str, Any],
    *,
    contract_path: Path,
) -> Decision | None:
    """Return ``None`` for ordinary events; never call ordinary policy for recovery."""
    selected_layout = layout()
    request = _request(payload)
    runtime_root = Path(
        os.environ.get("SULDE_ACTIVE_RUNTIME_ROOT")
        or os.environ.get("SULDE_RUNTIME_ROOT")
        or Path(__file__).resolve().parents[2]
    ).expanduser().resolve(strict=False)
    read_action = (
        None
        if request is not None
        else native_recovery_read_action(
            _command(payload),
            runtime_root=runtime_root,
            launcher_home=selected_layout.root,
        )
    )
    if request is None and read_action is None:
        return None
    if request is not None:
        # A sealed dictionary is not a binding to the shell command beside it.
        # Production writes use the exact protected native command bridge;
        # never allow an arbitrary command by attaching a read capability.
        return Decision(
            dispatch="deny", would_dispatch="deny", lifecycle="continue",
            authority="none", verification="none", evidence_state="observed",
            severity="high", reason="恢复请求必须绑定精确的原生恢复执行命令",
            fingerprint=event_fingerprint(payload),
            reason_code="recovery_command_unbound", decision_stage="recovery",
        )
    key_path = Path(
        os.environ.get("SULDE_RECOVERY_KEY_FILE")
        or selected_layout.control / "recovery.key"
    ).expanduser().resolve(strict=False)
    state_path = Path(
        os.environ.get("SULDE_RECOVERY_STATE_FILE")
        or selected_layout.state / "recovery-lane.jsonl"
    ).expanduser().resolve(strict=False)
    fingerprint = hashlib.sha256(
        json.dumps(
            request if request is not None else {
                "action": read_action,
                "command": _command(payload),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    try:
        current_identity = {
            "provider": str(payload.get("client") or "unknown").lower(),
            "session_id": str(payload.get("session_id") or payload.get("sessionId") or ""),
            "workspace": str(Path(payload.get("cwd") or os.getcwd()).expanduser().resolve()),
            "installed_generation": str(
                os.environ.get("SULDE_RUNTIME_GENERATION") or RUNTIME_GENERATION
            ),
        }
        lane = RecoveryLane(
            str(state_path),
            seal_key=_seal_key(key_path),
            wall_clock=__import__("time").time,
            monotonic_clock=__import__("time").monotonic,
        )
        if request is None:
            assert read_action is not None
            capability = lane.issue_capability(
                provider=current_identity["provider"],
                session_id=current_identity["session_id"],
                workspace=current_identity["workspace"],
                installed_generation=current_identity["installed_generation"],
                action=read_action,
                target_identity=f"recovery-control:{read_action}",
                expected_pre_state=recovery_pre_state(contract_path),
                expires_at=__import__("time").time() + 60,
                verifier_identity="sha256:" + hashlib.sha256(
                    Path(__file__).read_bytes()
                ).hexdigest(),
                nonce=fingerprint,
            )
            request = lane.request(capability)
        if any(request.get(field) != value for field, value in current_identity.items()):
            raise RecoveryLaneError(
                "recovery provider/session/workspace/generation does not match the live host"
            )
        fingerprint = hashlib.sha256(
            json.dumps(
                request,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        decision = lane.pretool_decision(
            request,
            current_pre_state=recovery_pre_state(contract_path),
            ordinary_guard=lambda _event: (_ for _ in ()).throw(
                IntentGuardianError("ordinary policy entered sealed recovery route")
            ),
        )
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        if read_action == "doctor":
            return Decision(
                dispatch="allow", would_dispatch="allow", lifecycle="continue",
                authority="none", verification="none", evidence_state="observed",
                severity="info", reason="仅放行精确只读诊断；恢复授权存储不可用",
                fingerprint=fingerprint, reason_code="recovery_diagnosis_only",
                decision_stage="recovery",
            )
        return Decision(
            dispatch="deny", would_dispatch="deny", lifecycle="continue",
            authority="none", verification="none", evidence_state="observed",
            severity="critical", reason=f"恢复能力验证失败：{error}",
            fingerprint=fingerprint, reason_code="recovery_capability_denied",
            decision_stage="recovery",
        )
    if decision.get("decision") == "allow_recovery" and decision.get("launch") is True:
        return Decision(
            dispatch="allow", would_dispatch="allow", lifecycle="continue",
            authority=("none" if decision.get("effect") == "read" else "human_grant"),
            verification="none", evidence_state="observed", severity="info",
            reason="密封恢复能力已在普通 Guardian 之前验证",
            fingerprint=fingerprint, reason_code="recovery_lane_allowed",
            decision_stage="recovery",
            secondary_reasons=("ordinary_policy:false",),
        )
    return Decision(
        dispatch="deny", would_dispatch="deny", lifecycle="continue",
        authority="none", verification="none", evidence_state="observed",
        severity="high",
        reason=(
            "恢复动作需要当前会话确认"
            if decision.get("decision") == "permission_required"
            else str(decision.get("reason") or "恢复能力不匹配")
        ),
        fingerprint=fingerprint, reason_code="recovery_permission_required",
        decision_stage="recovery",
    )

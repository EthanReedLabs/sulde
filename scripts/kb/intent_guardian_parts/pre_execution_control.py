"""Durable control operations for the negative execution canary protocol."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import secrets
from typing import Any

from .pre_execution_proof import (
    PROBE_SCHEMA,
    PROBE_TTL_SECONDS,
    PROOF_SCHEMA,
    probe_command,
    probe_target,
    proof_id,
)
from .state import (
    ARTIFACT_GENERATION,
    IntentGuardianError,
    LOADED_MODULE_GENERATION,
    RUNTIME_GENERATION,
    _write_contract_unlocked,
    clear_pre_execution_gaps,
    contract_lock,
    load_contract,
)


def prepare_pre_execution_probe(
    path: Path,
    *,
    provider: str,
    session_id: str,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    """Create one exact negative canary without claiming that it ran."""
    selected_provider = provider.strip().lower()
    selected_session = session_id.strip()
    if selected_provider not in {"claude", "codex"} or not selected_session:
        raise IntentGuardianError("pre-execution proof requires provider and session")
    current = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with contract_lock(path):
        contract = load_contract(path)
        existing = contract["runtime"].get("pre_execution_probe")
        if isinstance(existing, dict) and existing.get("status") in {
            "prepared", "pre_denied"
        }:
            try:
                expires = datetime.fromisoformat(
                    str(existing.get("expires_at") or "").replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except (ValueError, OverflowError):
                expires = current
            if (
                expires > current
                and existing.get("provider") == selected_provider
                and existing.get("session_id") == selected_session
                and existing.get("runtime_generation") == RUNTIME_GENERATION
                and existing.get("loaded_module_generation")
                == LOADED_MODULE_GENERATION
                and existing.get("artifact_generation") == ARTIFACT_GENERATION
                and str(existing.get("command") or "").startswith("rm -- ")
            ):
                return json.loads(json.dumps(existing))
        probe_id = secrets.token_hex(16)
        target = probe_target(probe_id)
        command, arguments_digest = probe_command(target)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(probe_id + "\n")
        except OSError as error:
            raise IntentGuardianError(
                f"cannot create isolated destructive canary: {error}"
            ) from error
        probe = {
            "schema": PROBE_SCHEMA,
            "probe_id": probe_id,
            "provider": selected_provider,
            "session_id": selected_session,
            "runtime_generation": RUNTIME_GENERATION,
            "loaded_module_generation": LOADED_MODULE_GENERATION,
            "artifact_generation": ARTIFACT_GENERATION,
            "target": target,
            "command": command,
            "arguments_digest": arguments_digest,
            "prepared_at": current.isoformat(),
            "expires_at": (current + timedelta(seconds=PROBE_TTL_SECONDS)).isoformat(),
            "status": "prepared",
            "started_event_id": "",
            "started_call_id": "",
            "started_at": "",
            "completed_event_id": "",
            "completed_at": "",
            "decision_fingerprint": "",
            "reason_code": "",
        }
        contract["runtime"]["pre_execution_probe"] = probe
        _write_contract_unlocked(path, contract)
        return json.loads(json.dumps(probe))


def finalize_pre_execution_probe(
    path: Path,
    *,
    provider: str,
    session_id: str,
    probe_id: str,
    current_time: datetime | None = None,
) -> dict[str, Any]:
    """Clear a latched gap only when Pre denied and no execution followed."""
    current = (current_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    with contract_lock(path):
        contract = load_contract(path)
        runtime = contract["runtime"]
        probe = runtime.get("pre_execution_probe")
        if not isinstance(probe, dict) or probe.get("probe_id") != probe_id:
            raise IntentGuardianError("pre-execution probe is missing or replaced")
        if (
            probe.get("provider") != provider.strip().lower()
            or probe.get("session_id") != session_id.strip()
            or probe.get("runtime_generation") != RUNTIME_GENERATION
            or probe.get("loaded_module_generation") != LOADED_MODULE_GENERATION
            or probe.get("artifact_generation") != ARTIFACT_GENERATION
        ):
            raise IntentGuardianError("pre-execution probe lane or generation changed")
        try:
            expires = datetime.fromisoformat(
                str(probe.get("expires_at") or "").replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (ValueError, OverflowError) as error:
            raise IntentGuardianError("pre-execution probe expiry is invalid") from error
        if current >= expires:
            raise IntentGuardianError("pre-execution probe expired")
        if probe.get("status") != "pre_denied" or not probe.get("started_event_id"):
            raise IntentGuardianError(
                "pre-execution probe lacks one live exact PreToolUse denial"
            )
        target = str(probe.get("target") or "")
        legacy_touch_probe = str(probe.get("command") or "").startswith("touch ")
        marker_exists = bool(target and os.path.lexists(target))
        if not target or (legacy_touch_probe and marker_exists) or (
            not legacy_touch_probe and not marker_exists
        ):
            raise IntentGuardianError("pre-execution canary executed or marker state differs")
        if not legacy_touch_probe:
            try:
                if Path(target).read_text(encoding="utf-8") != probe_id + "\n":
                    raise IntentGuardianError("pre-execution canary content differs")
                Path(target).unlink()
            except OSError as error:
                raise IntentGuardianError(
                    f"cannot clean verified destructive canary: {error}"
                ) from error
        before = len(runtime["pre_execution_gaps"])
        clear_pre_execution_gaps(
            contract,
            provider=provider.strip().lower(),
            session_id=session_id.strip(),
        )
        proof = {
            "schema": PROOF_SCHEMA,
            "probe_id": probe_id,
            "provider": probe["provider"],
            "session_id": probe["session_id"],
            "runtime_generation": probe["runtime_generation"],
            "loaded_module_generation": probe["loaded_module_generation"],
            "artifact_generation": probe["artifact_generation"],
            "target": target,
            "started_event_id": probe["started_event_id"],
            "started_call_id": probe["started_call_id"],
            "decision_fingerprint": probe["decision_fingerprint"],
            "prepared_at": probe["prepared_at"],
            "verified_at": current.isoformat(),
            "gaps_cleared": before - len(runtime["pre_execution_gaps"]),
        }
        proof["proof_id"] = proof_id(proof)
        runtime["pre_execution_proofs"].append(proof)
        runtime["pre_execution_proofs"] = runtime["pre_execution_proofs"][-100:]
        runtime["pre_execution_probe"] = {**probe, "status": "verified"}
        _write_contract_unlocked(path, contract)
        return json.loads(json.dumps(proof))

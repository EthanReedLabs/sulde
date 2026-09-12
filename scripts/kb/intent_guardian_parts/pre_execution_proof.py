"""Pure protocol for proving one material PreToolUse denial."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


LEGACY_PROBE_SCHEMA = "sulde-pre-execution-probe-v1"
LEGACY_PROOF_SCHEMA = "sulde-pre-execution-proof-v1"
PROBE_SCHEMA = "sulde-pre-execution-probe-v2"
PROOF_SCHEMA = "sulde-pre-execution-proof-v2"
PROBE_TTL_SECONDS = 10 * 60
PROBE_STATUSES = frozenset({
    "prepared", "pre_denied", "invalid_pre", "executed", "verified",
})
LEGACY_PROBE_FIELDS = frozenset({
    "schema", "probe_id", "provider", "session_id", "runtime_generation",
    "target", "command", "arguments_digest", "prepared_at", "expires_at",
    "status", "started_event_id", "started_call_id", "started_at",
    "completed_event_id", "completed_at", "decision_fingerprint",
    "reason_code",
})
PROBE_FIELDS = LEGACY_PROBE_FIELDS | frozenset({
    "loaded_module_generation", "artifact_generation",
})
LEGACY_PROOF_FIELDS = frozenset({
    "schema", "proof_id", "probe_id", "provider", "session_id",
    "runtime_generation", "target", "started_event_id", "started_call_id",
    "decision_fingerprint", "prepared_at", "verified_at", "gaps_cleared",
})
PROOF_FIELDS = LEGACY_PROOF_FIELDS | frozenset({
    "loaded_module_generation", "artifact_generation",
})


class PreExecutionProofError(ValueError):
    """The proof envelope is malformed or cannot establish a Pre boundary."""


def probe_target(probe_id: str) -> str:
    root = Path("/private/tmp") if os.name == "posix" else Path(tempfile.gettempdir())
    return str(root / f"sulde-pre-execution-canary-{probe_id}")


def probe_command(target: str) -> tuple[str, str]:
    command = f"rm -- {target}"
    rendered = json.dumps(
        {"command": command}, ensure_ascii=False, sort_keys=True, default=str,
    )
    return command, hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def observe_probe(runtime: dict[str, Any], event: dict[str, Any], decision: Any) -> None:
    """Bind only a live exact Pre denial, and remember any observed execution."""
    probe = runtime.get("pre_execution_probe")
    if not isinstance(probe, dict) or probe.get("schema") != PROBE_SCHEMA:
        return
    if (
        event.get("provider") != probe.get("provider")
        or event.get("session_id") != probe.get("session_id")
        or event.get("runtime_generation") != probe.get("runtime_generation")
        or event.get("loaded_module_generation")
        != probe.get("loaded_module_generation")
        or event.get("artifact_generation") != probe.get("artifact_generation")
        or event.get("arguments_digest") != probe.get("arguments_digest")
        or event.get("target") != probe.get("target")
        or event.get("write_targets") != [probe.get("target")]
    ):
        return
    if event.get("phase") == "completed":
        probe["status"] = "executed"
        probe["completed_event_id"] = str(event.get("event_id") or "")
        probe["completed_at"] = str(event.get("at") or "")
        return
    if event.get("phase") != "started" or probe.get("status") != "prepared":
        return
    exact_live_denial = bool(
        event.get("supervision_status") == "live_verified"
        and event.get("capability") == "tool:Bash"
        and event.get("effect") == "local_write"
        and decision.action == "deny"
        and decision.would_action == "deny"
    )
    probe["status"] = "pre_denied" if exact_live_denial else "invalid_pre"
    probe["started_event_id"] = str(event.get("event_id") or "")
    probe["started_call_id"] = str(event.get("call_id") or "")
    probe["started_at"] = str(event.get("at") or "")
    probe["decision_fingerprint"] = str(decision.fingerprint)
    probe["reason_code"] = str(decision.reason_code)


def _proof_material(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        PROOF_FIELDS
        if row.get("schema") == PROOF_SCHEMA
        else LEGACY_PROOF_FIELDS
    )
    return {key: row[key] for key in fields if key != "proof_id"}


def proof_id(material: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            material, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def normalize_runtime(runtime: dict[str, Any]) -> None:
    """Validate and normalize the two proof protocol projections."""
    raw_probe = runtime.get("pre_execution_probe")
    if raw_probe is None:
        raw_probe = {}
    if not isinstance(raw_probe, dict):
        raise PreExecutionProofError("runtime.pre_execution_probe must be an object")
    if raw_probe:
        expected_probe_fields = (
            PROBE_FIELDS
            if raw_probe.get("schema") == PROBE_SCHEMA
            else LEGACY_PROBE_FIELDS
            if raw_probe.get("schema") == LEGACY_PROBE_SCHEMA
            else frozenset()
        )
        if set(raw_probe) != expected_probe_fields:
            raise PreExecutionProofError("runtime.pre_execution_probe fields are invalid")
        if raw_probe.get("status") not in PROBE_STATUSES:
            raise PreExecutionProofError("runtime.pre_execution_probe status is invalid")
        if (
            not re.fullmatch(r"[0-9a-f]{32}", str(raw_probe.get("probe_id") or ""))
            or raw_probe.get("provider") not in {"claude", "codex"}
            or not str(raw_probe.get("session_id") or "").strip()
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(raw_probe.get("arguments_digest") or "")
            )
        ):
            raise PreExecutionProofError("runtime.pre_execution_probe identity is invalid")
        if raw_probe.get("schema") == PROBE_SCHEMA and (
            not re.fullmatch(
                r"[0-9a-f]{64}",
                str(raw_probe.get("loaded_module_generation") or ""),
            )
            or not str(raw_probe.get("artifact_generation") or "").strip()
        ):
            raise PreExecutionProofError(
                "runtime.pre_execution_probe generation identity is invalid"
            )
        expected_target = probe_target(str(raw_probe["probe_id"]))
        expected_command, expected_digest = probe_command(expected_target)
        legacy_command = f"touch {expected_target}"
        legacy_rendered = json.dumps(
            {"command": legacy_command},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        legacy_digest = hashlib.sha256(legacy_rendered.encode("utf-8")).hexdigest()
        if (
            raw_probe.get("target") != expected_target
            or (
                (raw_probe.get("command"), raw_probe.get("arguments_digest"))
                not in {
                    (expected_command, expected_digest),
                    (legacy_command, legacy_digest),
                }
            )
        ):
            raise PreExecutionProofError("runtime.pre_execution_probe command is invalid")
    runtime["pre_execution_probe"] = dict(raw_probe)

    raw_proofs = runtime.get("pre_execution_proofs")
    if raw_proofs is None:
        raw_proofs = []
    if not isinstance(raw_proofs, list):
        raise PreExecutionProofError("runtime.pre_execution_proofs must be an array")
    normalized: list[dict[str, Any]] = []
    for row in raw_proofs[-100:]:
        if not isinstance(row, dict):
            raise PreExecutionProofError("runtime.pre_execution_proof fields are invalid")
        expected_proof_fields = (
            PROOF_FIELDS
            if row.get("schema") == PROOF_SCHEMA
            else LEGACY_PROOF_FIELDS
            if row.get("schema") == LEGACY_PROOF_SCHEMA
            else frozenset()
        )
        if set(row) != expected_proof_fields:
            raise PreExecutionProofError("runtime.pre_execution_proof fields are invalid")
        selected = dict(row)
        if (
            not re.fullmatch(r"[0-9a-f]{64}", str(selected.get("proof_id") or ""))
            or selected["proof_id"] != proof_id(_proof_material(selected))
            or type(selected.get("gaps_cleared")) is not int
            or selected["gaps_cleared"] < 0
        ):
            raise PreExecutionProofError("runtime.pre_execution_proof seal is invalid")
        if selected.get("schema") == PROOF_SCHEMA and (
            not re.fullmatch(
                r"[0-9a-f]{64}",
                str(selected.get("loaded_module_generation") or ""),
            )
            or not str(selected.get("artifact_generation") or "").strip()
        ):
            raise PreExecutionProofError(
                "runtime.pre_execution_proof generation identity is invalid"
            )
        normalized.append(selected)
    runtime["pre_execution_proofs"] = normalized

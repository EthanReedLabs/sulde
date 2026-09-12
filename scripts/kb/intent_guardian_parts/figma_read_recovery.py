"""Evidence-bound recovery for misclassified historical Figma reads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from intervention import (
    InterventionError,
    correct_legacy_figma_read_only_classification,
    load_projection as load_intervention_projection,
)
from resource_adapters import ResourceAdapterError, classify_figma
from session_continuity import locate_codex_rollout

from .resources import _input_digest


_CODEX_EXEC_CALL_ID_RE = re.compile(
    r"(?:^|:)(exec-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})(?::|$)"
)


def _attempt_codex_call_id(attempt: dict[str, Any]) -> str:
    match = _CODEX_EXEC_CALL_ID_RE.search(str(attempt.get("idempotency_key") or ""))
    return match.group(1) if match else ""


def _rollout_figma_read_evidence(
    attempt: dict[str, Any],
) -> dict[str, str] | None:
    """Recover and prove one exact historical Codex Figma inspection call."""
    session_id = str(attempt.get("session_id") or "")
    call_id = _attempt_codex_call_id(attempt)
    expected_digest = str(attempt.get("operation_arguments_digest") or "")
    rollout = locate_codex_rollout(session_id)
    if (
        not call_id
        or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        or rollout is None
    ):
        return None
    needle = f'"id":"{call_id}"'.encode("utf-8")
    try:
        with rollout.open("rb") as handle:
            for raw_line in handle:
                if needle not in raw_line:
                    continue
                try:
                    row = json.loads(raw_line.decode("utf-8", errors="strict"))
                except (UnicodeError, json.JSONDecodeError):
                    continue
                payload = row.get("payload") if isinstance(row, dict) else None
                item = payload.get("item") if isinstance(payload, dict) else None
                if not isinstance(item, dict) or item.get("type") != "McpToolCall":
                    continue
                server = str(item.get("server") or "").lower().replace("_", "-")
                tool = str(item.get("tool") or "").lower().replace("_", "-")
                if (
                    item.get("id") != call_id
                    or server not in {"codex-apps", "figma"}
                    or tool not in {"figma.use-figma", "use-figma"}
                    or item.get("status") != "completed"
                ):
                    continue
                result = item.get("result")
                arguments = item.get("arguments")
                if (
                    not isinstance(result, dict)
                    or result.get("isError") is True
                    or not isinstance(arguments, dict)
                    or _input_digest(arguments) != expected_digest
                ):
                    continue
                try:
                    resource = classify_figma(
                        "use_figma", arguments, provider="figma"
                    )
                except (ResourceAdapterError, TypeError, ValueError):
                    continue
                if resource.get("effect") != "read":
                    continue
                code = str(arguments.get("code") or "")
                evidence = {
                    "schema": "sulde-codex-rollout-figma-read-evidence-v1",
                    "session_id": session_id,
                    "call_id": call_id,
                    "operation_arguments_digest": expected_digest,
                    "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
                    "resource_id": str(resource.get("resource_id") or ""),
                    "status": "completed",
                }
                evidence_sha256 = hashlib.sha256(
                    json.dumps(
                        evidence,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                return {
                    "operation_arguments_digest": expected_digest,
                    "classification_evidence_sha256": evidence_sha256,
                }
    except OSError:
        return None
    return None


def reconcile_misclassified_figma_reads(path: Path) -> list[dict[str, Any]]:
    """Append corrections only for aborted rows proved by native rollout input."""
    try:
        projection = load_intervention_projection(path)
    except (InterventionError, OSError, UnicodeError):
        return []
    corrected: list[dict[str, Any]] = []
    for attempt_id, attempt in sorted(projection.get("attempts", {}).items()):
        if (
            not isinstance(attempt, dict)
            or attempt.get("effect") not in {
                "external_write", "destructive", "unknown",
            }
            or attempt.get("state") != "unknown"
            or attempt.get("replay_authoritative") is not True
            or attempt.get("capability")
            not in {
                "mcp:codex_apps:figma__use_figma",
                "mcp:figma:use_figma",
            }
        ):
            continue
        resolved_abort = any(
            isinstance(intervention, dict)
            and intervention.get("attempt_id") == attempt_id
            and intervention.get("status") == "resolved"
            and intervention.get("decision") == "abort"
            for intervention in projection.get("interventions", {}).values()
        )
        if not resolved_abort:
            continue
        evidence = _rollout_figma_read_evidence(attempt)
        if evidence is None:
            continue
        try:
            corrected_attempt = correct_legacy_figma_read_only_classification(
                path,
                attempt_id,
                operation_arguments_digest=evidence[
                    "operation_arguments_digest"
                ],
                classification_evidence_sha256=evidence[
                    "classification_evidence_sha256"
                ],
            )
        except (InterventionError, OSError, UnicodeError):
            continue
        corrected.append(
            {
                "attempt_id": attempt_id,
                "reconciliation_source": "codex_rollout_figma_read",
                "classification_evidence_sha256": evidence[
                    "classification_evidence_sha256"
                ],
                "effect": corrected_attempt.get("effect"),
            }
        )
    return corrected

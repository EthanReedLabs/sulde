"""Human effect-intervention projection kept outside the recovery coordinator."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from intervention import (
    InterventionError,
    acknowledge_intervention as acknowledge_effect_intervention_store,
    load_projection as load_intervention_projection,
    resolve_intervention as resolve_effect_intervention_store,
    summary as intervention_summary,
)

from .state import (
    IntentGuardianError,
    _write_contract_unlocked,
    contract_lock,
    load_contract,
    now_iso,
)


def effect_intervention_report(path: Path) -> dict[str, Any]:
    try:
        projection = load_intervention_projection(path)
    except (InterventionError, OSError, UnicodeError) as error:
        raise IntentGuardianError(f"cannot replay interventions: {error}") from error
    return {
        "schema": "sulde-effect-intervention-report-v1",
        "contract_path": str(path),
        "attempts": list(projection["attempts"].values()),
        "interventions": list(projection["interventions"].values()),
        "summary": intervention_summary(path),
    }


def acknowledge_effect_intervention(
    path: Path,
    intervention_id: str,
    *,
    actor: str = "human-cli",
) -> dict[str, Any]:
    try:
        with contract_lock(path):
            return acknowledge_effect_intervention_store(
                path,
                intervention_id,
                actor=actor,
            )
    except (InterventionError, OSError, UnicodeError) as error:
        raise IntentGuardianError(f"cannot acknowledge intervention: {error}") from error


def resolve_effect_intervention(
    path: Path,
    intervention_id: str,
    *,
    decision: str,
    evidence: str,
    actor: str = "human-cli",
) -> dict[str, Any]:
    """Persist a human adjudication without changing semantic intent revision."""
    try:
        with contract_lock(path):
            contract = load_contract(path)
            resolved = _resolve_effect_intervention_locked(
                contract,
                path,
                intervention_id,
                decision=decision,
                evidence=evidence,
                actor=actor,
            )
            _write_contract_unlocked(path, contract)
            return resolved
    except (InterventionError, OSError, UnicodeError) as error:
        raise IntentGuardianError(f"cannot resolve intervention: {error}") from error


def _resolve_effect_intervention_locked(
    contract: dict[str, Any],
    path: Path,
    intervention_id: str,
    *,
    decision: str,
    evidence: str,
    actor: str,
    takeover_provider: str = "",
    takeover_session_id: str = "",
) -> dict[str, Any]:
    """Apply one already-authorized intervention decision under contract lock."""
    resolved = resolve_effect_intervention_store(
        path,
        intervention_id,
        decision=decision,
        evidence=evidence,
        actor=actor,
        takeover_provider=(
            takeover_provider
            if decision in {"retry_authorized", "reprobe_authorized"}
            else ""
        ),
        takeover_session_id=(
            takeover_session_id
            if decision in {"retry_authorized", "reprobe_authorized"}
            else ""
        ),
    )
    _project_effect_intervention_locked(
        contract,
        resolved,
        decision=decision,
        evidence=evidence,
    )
    return resolved


def _project_effect_intervention_locked(
    contract: dict[str, Any],
    resolved: dict[str, Any],
    *,
    decision: str,
    evidence: str,
) -> None:
    """Idempotently mirror authoritative effect truth into contract runtime."""
    attempt_id = str(resolved["attempt_id"])
    pending = contract["runtime"]["pending_verifications"]
    matching = [
        row
        for row in pending
        if isinstance(row, dict) and row.get("attempt_id") == attempt_id
    ]
    if decision != "reprobe_authorized":
        contract["runtime"]["pending_verifications"] = [
            row
            for row in pending
            if not isinstance(row, dict) or row.get("attempt_id") != attempt_id
        ]
    if decision == "human_attested_success" and matching:
        evidence_rows = contract["runtime"]["verified_effects"]
        for row in matching:
            evidence_rows.append(
                {
                    "attempt_id": attempt_id,
                    "write_fingerprint": row.get("fingerprint"),
                    "write_capability": row.get("capability"),
                    "target": row.get("target"),
                    "verified_at": now_iso(),
                    "verification_source": "human_attestation",
                    "evidence_sha256": hashlib.sha256(
                        evidence.encode("utf-8", errors="replace")
                    ).hexdigest(),
                }
            )
        contract["runtime"]["verified_effects"] = evidence_rows[-50:]

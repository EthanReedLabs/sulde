"""Native HumanGrant decision adapter kept outside the recovery monolith."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from decision_kernel import grant_transaction_context, record_grant_decision
from .state import IntentGuardianError


def execute_native_grant_decision(
    path: Path,
    context: dict[str, Any],
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any]:
    try:
        grant_tx = grant_transaction_context(
            path,
            target=context["target"],
            provider=provider,
            session_id=session_id,
            task_epoch=str(context["task_epoch"]),
        )
        result = record_grant_decision(path, grant_tx, outcome=context["decision"])
    except (OSError, UnicodeError, ValueError, RuntimeError) as error:
        raise IntentGuardianError(f"cannot record native human grant: {error}") from error
    return {
        "schema": "sulde-codex-native-decision-result-v1",
        "status": "grant_recorded",
        "kind": "grant",
        "decision": context["decision"],
        "target": context["target"],
        "revision": context["intent_revision"],
        "authority_transferred": False,
        "broker_status": result.get("status", "unknown"),
    }

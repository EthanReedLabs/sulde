"""Read-only late proposal classification; never transfers authority."""
from __future__ import annotations
from pathlib import Path
import re
from typing import Any
from .state import load_contract

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

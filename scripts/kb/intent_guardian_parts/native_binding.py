"""Canonical native request fingerprints for approval and recovery flows."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from native_decision_journal import head_proof as native_journal_head_proof, head_proof_read_only

def _native_card_sha256(card: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            card,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

def _native_binding_snapshot(
    path: Path,
    context: dict[str, Any],
    session_id: str,
    *, read_only: bool = False,
) -> dict[str, Any]:
    """Build the non-executing T12 request envelope shown by PermissionRequest."""
    try:
        workspace = str(Path(context["workspace"]).expanduser().resolve())
    except OSError:
        workspace = str(Path(context["workspace"]).expanduser().absolute())
    workspace_sha256 = hashlib.sha256(
        workspace.encode("utf-8", errors="replace")
    ).hexdigest()
    lane_sha256 = hashlib.sha256(
        f"codex\0{session_id}".encode("utf-8", errors="replace")
    ).hexdigest()
    if read_only:
        journal_proof = head_proof_read_only(path.expanduser().resolve())
    else:
        journal_proof = native_journal_head_proof(path.expanduser().resolve())
    return {
        "card_sha256": _native_card_sha256(context["card"]),
        "provider": "codex",
        "session_id": session_id,
        "lane_sha256": lane_sha256,
        "target_sha256": hashlib.sha256(
            str(context["target"]).encode("utf-8", errors="replace")
        ).hexdigest(),
        "revision": int(context["intent_revision"]),
        "journal_sha256": journal_proof["journal_sha256"],
        "effect_sha256": hashlib.sha256(
            str(context["action"]).encode("utf-8", errors="replace")
        ).hexdigest(),
        "world_state_sha256": workspace_sha256,
    }

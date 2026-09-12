#!/usr/bin/env python3
"""Session-to-task ownership for the interactive intent control plane.

This module is intentionally pure: it performs no filesystem access and does
not import the guardian.  The workspace contract remains the durable policy,
while a task lane says whether one provider/session may execute material work
for the current semantic task epoch.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
from typing import Any, Callable


TASK_LANE_STATES = frozenset({"bound", "review_required", "paused"})
TASK_CONTINUATION_SCHEMA = "sulde-task-continuation-v1"
MATERIAL_EFFECTS = frozenset({"local_write", "external_write", "destructive"})
MATERIAL_UNCERTAINTY = frozenset(
    {"unresolved_local_write", "unresolved_external_write"}
)


class TaskOwnershipError(ValueError):
    """A task-lane record or transition is invalid."""


def _proposal_digest(value: Any) -> str:
    digest = str(value or "").strip().lower()
    if digest and not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise TaskOwnershipError(
            "task lane proposal_digest must be empty or 64 lowercase hex chars"
        )
    return digest


def require_agent_decision_session_binding(
    *,
    provider: str,
    session_id: str,
    observed_codex_session: str = "",
) -> str:
    """Validate one exact host/session binding before authority is written.

    Codex authority must never be recorded against an empty compatibility
    lane.  When the native host exposes ``CODEX_THREAD_ID``, an explicit
    different value is also rejected instead of minting authority for another
    session.  The pure helper deliberately performs no environment lookup so
    callers must pass only host-observed identity.
    """
    clean_provider = provider.strip().lower()
    clean_session = session_id.strip()
    if clean_provider not in {"claude", "codex"}:
        raise TaskOwnershipError(
            "Agent decision provider must be claude or codex"
        )
    if not clean_session:
        raise TaskOwnershipError(
            f"{clean_provider} Agent decision requires a non-empty session_id"
        )
    if len(clean_session) > 200:
        raise TaskOwnershipError(
            "Agent decision session_id must be at most 200 characters"
        )
    observed = observed_codex_session.strip()
    if clean_provider == "codex" and observed and clean_session != observed:
        raise TaskOwnershipError(
            "Codex Agent decision session_id does not match CODEX_THREAD_ID"
        )
    return clean_session


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError) as error:
        raise TaskOwnershipError("task lane pause_revision must be an integer") from error


def normalize_task_lanes(value: Any, *, default_epoch: str) -> list[dict[str, Any]]:
    if value is None:
        value = []
    if not isinstance(value, list):
        raise TaskOwnershipError("runtime.task_lanes must be an array")
    return [
        {
            "provider": str(row.get("provider") or "unknown")[:50].lower(),
            "session_id": str(row.get("session_id") or "")[:200],
            # Reuse the contract's exact epoch.  A lane must not derive or
            # truncate a second task identity that native authority cannot
            # compare byte-for-byte.
            "task_epoch": str(row.get("task_epoch") or default_epoch),
            "proposal_digest": _proposal_digest(row.get("proposal_digest")),
            "state": str(row.get("state") or "review_required")[:50],
            "source": str(row.get("source") or "unknown")[:100],
            "prompt_sha256": str(row.get("prompt_sha256") or "")[:64].lower(),
            "task_instance_id": str(row.get("task_instance_id") or "")[:200],
            "pending_task_instance_id": str(
                row.get("pending_task_instance_id") or ""
            )[:200],
            "continuation_token": str(
                row.get("continuation_token") or ""
            )[:200],
            "continuation_eligible": bool(
                row.get(
                    "continuation_eligible",
                    str(row.get("state") or "") in {"bound", "paused"},
                )
            ),
            "pause_reason": str(row.get("pause_reason") or "")[:2_000],
            "pause_class": str(row.get("pause_class") or "")[:50],
            "pause_event_fingerprint": str(
                row.get("pause_event_fingerprint") or ""
            )[:64].lower(),
            "pause_requires_revision": bool(
                row.get("pause_requires_revision", False)
            ),
            "pause_revision": _nonnegative_int(row.get("pause_revision", 0)),
            "paused_at": str(row.get("paused_at") or "")[:100],
            "updated_at": str(row.get("updated_at") or "")[:100],
        }
        for row in value[-100:]
        if isinstance(row, dict)
        and str(row.get("session_id") or "").strip()
        and str(row.get("state") or "review_required") in TASK_LANE_STATES
    ]

def normalize_task_continuations(
    value: Any,
) -> list[dict[str, Any]]:
    """Validate authority-free receipts for explicit cross-session continuation."""
    if value is None:
        value = []
    if not isinstance(value, list):
        raise TaskOwnershipError("runtime.task_continuations must be an array")
    normalized: list[dict[str, Any]] = []
    for row in value[-100:]:
        if not isinstance(row, dict):
            raise TaskOwnershipError(
                "runtime.task_continuations entries must be objects"
            )
        if row.get("schema") != TASK_CONTINUATION_SCHEMA:
            raise TaskOwnershipError("unsupported task continuation schema")
        digests = {
            name: str(row.get(name) or "").lower()
            for name in (
                "continuation_id",
                "target",
                "receipt_id",
                "policy_sha256",
                "source_lane_sha256",
                "target_lane_sha256",
            )
        }
        if any(
            not re.fullmatch(r"[0-9a-f]{64}", digest)
            for digest in digests.values()
        ):
            raise TaskOwnershipError("task continuation digest is invalid")
        task_epoch = str(row.get("task_epoch") or "")
        if not re.fullmatch(r"[0-9a-f]{24}", task_epoch):
            raise TaskOwnershipError("task continuation task_epoch is invalid")
        proposal_digest = str(row.get("proposal_digest") or "").lower()
        if proposal_digest and not re.fullmatch(
            r"[0-9a-f]{64}", proposal_digest
        ):
            raise TaskOwnershipError(
                "task continuation proposal_digest is invalid"
            )
        request_id = str(row.get("approval_request_id") or "")
        if not re.fullmatch(r"apr-[0-9a-f]{24}", request_id):
            raise TaskOwnershipError(
                "task continuation approval_request_id is invalid"
            )
        if row.get("authority_transferred") is not False:
            raise TaskOwnershipError(
                "task continuation must explicitly record zero authority transfer"
            )
        provider = str(row.get("provider") or "").lower()
        session_id = str(row.get("session_id") or "")
        if provider != "codex" or not session_id or len(session_id) > 200:
            raise TaskOwnershipError(
                "task continuation requires one exact Codex session"
            )
        intent_revision = row.get("intent_revision")
        if (
            type(intent_revision) is not int
            or type(intent_revision) is bool
            or intent_revision <= 0
        ):
            raise TaskOwnershipError(
                "task continuation intent_revision is invalid"
            )
        expected_target_lane = hashlib.sha256(
            f"{provider}\0{session_id}".encode("utf-8", errors="replace")
        ).hexdigest()
        if digests["target_lane_sha256"] != expected_target_lane:
            raise TaskOwnershipError(
                "task continuation target lane digest is invalid"
            )
        expected_id = hashlib.sha256(
            json.dumps(
                {
                    "request_id": request_id,
                    "receipt_id": digests["receipt_id"],
                    "target": digests["target"],
                },
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if digests["continuation_id"] != expected_id:
            raise TaskOwnershipError(
                "task continuation id does not match its sealed receipt"
            )
        normalized.append(
            {
                "schema": TASK_CONTINUATION_SCHEMA,
                **digests,
                "provider": provider,
                "session_id": session_id,
                "task_epoch": task_epoch,
                "intent_revision": intent_revision,
                "proposal_digest": proposal_digest,
                "task_instance_id": str(row.get("task_instance_id") or "")[:200],
                "approval_request_id": request_id,
                "authority_transferred": False,
                "recorded_at": str(row.get("recorded_at") or "")[:100],
            }
        )
    return normalized


def task_lane(
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any] | None:
    clean_provider = provider.strip().lower() or "unknown"
    clean_session = session_id.strip()
    if not clean_session:
        return None
    epoch = str(contract.get("task_epoch") or "")
    return next(
        (
            row
            for row in reversed(contract.get("runtime", {}).get("task_lanes", []))
            if isinstance(row, dict)
            and row.get("provider") == clean_provider
            and row.get("session_id") == clean_session
            and row.get("task_epoch") == epoch
        ),
        None,
    )


def upsert_task_lane(
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    state: str,
    source: str,
    proposal_digest: str | None = None,
    prompt_sha256: str = "",
    task_instance_id: str | None = None,
    pending_task_instance_id: str | None = None,
    continuation_token: str | None = None,
    continuation_eligible: bool | None = None,
    pause_reason: str = "",
    pause_class: str = "",
    pause_event_fingerprint: str = "",
    pause_requires_revision: bool = False,
    pause_revision: int = 0,
) -> dict[str, Any] | None:
    clean_provider = provider.strip().lower() or "unknown"
    clean_session = session_id.strip()
    if not clean_session:
        return None
    if state not in TASK_LANE_STATES:
        raise TaskOwnershipError(f"unsupported task lane state: {state}")
    existing_row = task_lane(
        contract,
        provider=clean_provider,
        session_id=clean_session,
    )
    existing = existing_row or {}
    selected_task_instance = (
        str(existing.get("task_instance_id") or "")
        if task_instance_id is None
        else str(task_instance_id).strip()[:200]
    )
    selected_pending_instance = (
        str(existing.get("pending_task_instance_id") or "")
        if pending_task_instance_id is None
        else str(pending_task_instance_id).strip()[:200]
    )
    selected_token = (
        str(existing.get("continuation_token") or "")
        if continuation_token is None
        else str(continuation_token).strip()[:200]
    )
    if not selected_token:
        selected_token = secrets.token_urlsafe(24)
    selected_continuation_eligible = (
        bool(existing.get("continuation_eligible", False))
        if continuation_eligible is None
        else bool(continuation_eligible)
    )
    selected_proposal_digest = _proposal_digest(
        (
            existing.get("proposal_digest")
            if proposal_digest is None
            else proposal_digest
        )
        or contract.get("proposal_digest")
        or contract.get("applied_proposal_digest")
    )
    row = {
        "provider": clean_provider,
        "session_id": clean_session[:200],
        "task_epoch": str(contract["task_epoch"]),
        "proposal_digest": selected_proposal_digest,
        "state": state,
        "source": source.strip()[:100] or "unknown",
        "prompt_sha256": (
            prompt_sha256.strip().lower()[:64]
            or str(existing.get("prompt_sha256") or "")[:64]
        ),
        "task_instance_id": selected_task_instance,
        "pending_task_instance_id": selected_pending_instance,
        "continuation_token": selected_token,
        "continuation_eligible": selected_continuation_eligible,
        "pause_reason": (
            pause_reason[:2_000]
            or str(existing.get("pause_reason") or "")[:2_000]
        ) if state == "paused" else "",
        "pause_class": (
            pause_class[:50]
            or str(existing.get("pause_class") or "")[:50]
        ) if state == "paused" else "",
        "pause_event_fingerprint": (
            pause_event_fingerprint.strip().lower()[:64]
            or str(existing.get("pause_event_fingerprint") or "")[:64]
            if state == "paused"
            else ""
        ),
        "pause_requires_revision": bool(
            pause_requires_revision
            or existing.get("pause_requires_revision", False)
        )
        if state == "paused"
        else False,
        "pause_revision": max(
            0,
            int(pause_revision),
            int(existing.get("pause_revision") or 0),
        ) if state == "paused" else 0,
        "paused_at": (
            str(existing.get("paused_at") or "") or _now_iso()
        ) if state == "paused" else "",
        "updated_at": _now_iso(),
    }
    lanes = [
        existing
        for existing in contract["runtime"].get("task_lanes", [])
        if not (
            isinstance(existing, dict)
            and existing.get("provider") == row["provider"]
            and existing.get("session_id") == row["session_id"]
            and existing.get("task_epoch") == row["task_epoch"]
        )
    ]
    lanes.append(row)
    contract["runtime"]["task_lanes"] = lanes[-100:]
    return row


def _current_task_lanes(contract: dict[str, Any]) -> list[dict[str, Any]]:
    epoch = str(contract.get("task_epoch") or "")
    return [
        row
        for row in contract.get("runtime", {}).get("task_lanes", [])
        if isinstance(row, dict) and row.get("task_epoch") == epoch
    ]


def _continuation_lane(
    contract: dict[str, Any],
    token: str,
    *,
    provider: str,
    session_id: str,
) -> dict[str, Any] | None:
    selected = token.strip()
    if not selected:
        return None
    return next(
        (
            row
            for row in reversed(_current_task_lanes(contract))
            if row.get("continuation_eligible") is True
            and row.get("provider") == (provider.strip().lower() or "unknown")
            and row.get("session_id") == session_id.strip()
            and row.get("continuation_token")
            and secrets.compare_digest(
                str(row.get("continuation_token")), selected
            )
        ),
        None,
    )


def observe_prompt_lane(
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    source: str,
    prompt_sha256: str,
    task_instance_id: str = "",
    continuation_token: str = "",
    explicit_new_task: bool = False,
    contract_preexisting: bool = True,
    applied_revision_lane: bool = False,
    control_prompt: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    """Observe host task identity without guessing from prompt text.

    ``identity_status`` is observational, not an authority decision.  Missing
    host identity is reported as ``unknown`` while ordinary follow-ups retain
    their existing lane.  A changed explicit instance becomes read-only review
    unless the same provider/session echoes its continuation token.  The token
    is correlation metadata and never creates authority in a different lane.
    """
    clean_session = session_id.strip()
    if not clean_session:
        return None, "unknown"
    incoming_instance = task_instance_id.strip()[:200]
    matched_continuation = _continuation_lane(
        contract,
        continuation_token,
        provider=provider,
        session_id=clean_session,
    )
    existing = task_lane(
        contract,
        provider=provider,
        session_id=clean_session,
    )
    if existing is None:
        # Neither a readable task id nor a contract-stored bearer token grants
        # authority to a new provider/session.  Only creation or an applied
        # revision receipt may establish a new material lane.
        may_bind = bool(
            not contract_preexisting
            or applied_revision_lane
        ) and not (explicit_new_task and contract_preexisting)
        bound_instance = incoming_instance
        row = upsert_task_lane(
            contract,
            provider=provider,
            session_id=clean_session,
            state="bound" if may_bind else "review_required",
            source=(
                "contract_created"
                if not contract_preexisting
                else "applied_revision_receipt"
                if applied_revision_lane
                else "explicit_new_task"
                if explicit_new_task
                else source
            ),
            prompt_sha256=prompt_sha256,
            task_instance_id=bound_instance if may_bind else "",
            pending_task_instance_id=("" if may_bind else incoming_instance),
            continuation_token=None,
            continuation_eligible=may_bind,
        )
        if not may_bind:
            return row, "changed" if incoming_instance or explicit_new_task else "unknown"
        return row, "explicit" if incoming_instance else "unknown"

    # Control prompts are part of the current turn's state transition.  Host
    # wrappers sometimes assign them a fresh turn identifier, which must not
    # accidentally detach or re-authorize the task lane.
    if control_prompt:
        return existing, "control"

    prior_instance = str(existing.get("task_instance_id") or "")
    state = str(existing.get("state") or "review_required")
    if state == "review_required":
        may_rebind = bool(
            applied_revision_lane
            or matched_continuation
        ) and not explicit_new_task
        if may_rebind:
            row = upsert_task_lane(
                contract,
                provider=provider,
                session_id=clean_session,
                state="bound",
                source=(
                    "applied_revision_receipt"
                    if applied_revision_lane
                    else "task_continuation_token"
                    if matched_continuation is not None
                    else "applied_revision_receipt"
                ),
                prompt_sha256=prompt_sha256,
                task_instance_id=(
                    incoming_instance
                    or str(existing.get("pending_task_instance_id") or "")
                    or str((matched_continuation or {}).get("task_instance_id") or "")
                ),
                pending_task_instance_id="",
                continuation_token=(
                    str(matched_continuation.get("continuation_token") or "")
                    if matched_continuation is not None
                    else None
                ),
                continuation_eligible=True,
            )
            return row, "continued" if matched_continuation else "explicit"
        return existing, "changed" if incoming_instance or explicit_new_task else "unknown"

    identity_changed = bool(
        explicit_new_task
        or (incoming_instance and prior_instance and incoming_instance != prior_instance)
    )
    if identity_changed and matched_continuation is None:
        if state == "paused":
            # A new prompt cannot use task identity churn to escape a pause.
            existing["pending_task_instance_id"] = incoming_instance
            existing["updated_at"] = _now_iso()
            return existing, "changed"
        row = upsert_task_lane(
            contract,
            provider=provider,
            session_id=clean_session,
            state="review_required",
            source="explicit_new_task" if explicit_new_task else "task_instance_changed",
            prompt_sha256=prompt_sha256,
            task_instance_id=prior_instance,
            pending_task_instance_id=incoming_instance,
            continuation_eligible=True,
        )
        return row, "changed"

    if incoming_instance and not prior_instance:
        row = upsert_task_lane(
            contract,
            provider=provider,
            session_id=clean_session,
            state=state,
            source="task_instance_bound",
            prompt_sha256=prompt_sha256,
            task_instance_id=incoming_instance,
            pending_task_instance_id="",
        )
        return row, "explicit"
    if identity_changed and matched_continuation is not None:
        row = upsert_task_lane(
            contract,
            provider=provider,
            session_id=clean_session,
            state=state,
            source="task_continuation_token",
            prompt_sha256=prompt_sha256,
            task_instance_id=incoming_instance or prior_instance,
            pending_task_instance_id="",
            continuation_token=str(
                matched_continuation.get("continuation_token") or ""
            ),
            continuation_eligible=True,
        )
        return row, "continued"
    return existing, "explicit" if incoming_instance else "unknown"


def blocks_material(contract: dict[str, Any], event: dict[str, Any]) -> bool:
    if event.get("phase") != "started" or event.get("control_plane"):
        return False
    effect = str(event.get("effect") or "unknown")
    kind = str(event.get("kind") or "tool")
    uncertainty = str(event.get("uncertainty_kind") or "")
    material = effect in MATERIAL_EFFECTS or uncertainty in MATERIAL_UNCERTAINTY
    if not material and not (
        kind == "mcp"
        and effect != "read"
        and uncertainty != "unclassified_read_candidate"
    ):
        return False
    # Legacy contracts remain usable until the first live prompt establishes
    # lane ownership. Thereafter absence is never implicit authority.
    if not contract.get("runtime", {}).get("task_lanes"):
        return False
    lane = task_lane(
        contract,
        provider=str(event.get("provider") or "unknown"),
        session_id=str(event.get("session_id") or ""),
    )
    # A paused lane is still the owner of this task.  Its material denial is
    # evaluated by the guardian's scoped pause policy so sibling bound lanes
    # are not mistaken for unowned work.
    return lane is None or lane.get("state") == "review_required"


# Lane-scoped semantic critic batching lives beside task ownership so the
# guardian can import one pure state module without a reverse dependency on
# the model-facing intent_critic module.
CRITIC_BATCH_SCHEMA = "sulde-critic-batch-v1"
CRITIC_CLAIM_TTL_SECONDS = 180
MAX_CRITIC_BATCHES = 100
MAX_CRITIC_BATCH_EVENTS = 100
MAX_CRITIC_BATCH_TARGETS = 64
_CRITIC_BATCH_STATES = frozenset({"collecting", "claimed", "abandoned"})


class CriticCheckpointError(ValueError):
    """A critic batch or claim is structurally invalid."""


def _bounded_strings(value: Any, *, limit: int, size: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()[:size]
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def normalize_critic_batches(
    value: Any,
    *,
    default_epoch: str,
) -> list[dict[str, Any]]:
    """Validate bounded current-epoch batch state and discard stale epochs."""
    if value is None:
        value = []
    if not isinstance(value, list):
        raise CriticCheckpointError("runtime.critic_batches must be an array")
    normalized: list[dict[str, Any]] = []
    for raw in value[-MAX_CRITIC_BATCHES:]:
        if not isinstance(raw, dict):
            raise CriticCheckpointError("critic batch entries must be objects")
        state = str(raw.get("state") or "collecting")
        if state not in _CRITIC_BATCH_STATES:
            raise CriticCheckpointError(f"unsupported critic batch state: {state}")
        task_epoch = str(raw.get("task_epoch") or default_epoch)[:24]
        if task_epoch != default_epoch:
            continue
        provider = str(raw.get("provider") or "unknown").strip().lower()[:50]
        session_id = str(raw.get("session_id") or "").strip()[:200]
        batch_id = str(raw.get("batch_id") or "").strip()[:80]
        if not session_id or not batch_id:
            raise CriticCheckpointError(
                "critic batch requires non-empty session_id and batch_id"
            )
        try:
            revision = max(1, int(raw.get("revision", 1)))
            first_sequence = max(0, int(raw.get("first_sequence", 0)))
            last_sequence = max(first_sequence, int(raw.get("last_sequence", 0)))
            completed_writes = max(1, int(raw.get("completed_writes", 1)))
            target_overflow = max(0, int(raw.get("target_overflow", 0)))
            claim_material_sequence = max(
                0, int(raw.get("claim_material_sequence", 0))
            )
        except (TypeError, ValueError) as error:
            raise CriticCheckpointError("critic batch counters must be integers") from error
        claim_id = str(raw.get("claim_id") or "").strip()[:80]
        if state in {"claimed", "abandoned"} and not claim_id:
            raise CriticCheckpointError("claimed critic batch requires claim_id")
        normalized.append(
            {
                "schema": CRITIC_BATCH_SCHEMA,
                "batch_id": batch_id,
                "provider": provider or "unknown",
                "session_id": session_id,
                "task_epoch": task_epoch,
                "revision": revision,
                "state": state,
                "first_sequence": first_sequence,
                "last_sequence": last_sequence,
                "completed_writes": completed_writes,
                "targets": _bounded_strings(
                    raw.get("targets"), limit=MAX_CRITIC_BATCH_TARGETS, size=2_000
                ),
                "target_overflow": target_overflow,
                "event_ids": _bounded_strings(
                    raw.get("event_ids"), limit=MAX_CRITIC_BATCH_EVENTS, size=64
                ),
                "capabilities": _bounded_strings(
                    raw.get("capabilities"), limit=32, size=256
                ),
                "created_at": str(raw.get("created_at") or "")[:100],
                "updated_at": str(raw.get("updated_at") or "")[:100],
                "claim_id": claim_id,
                "claimed_at": str(raw.get("claimed_at") or "")[:100],
                "claim_material_sequence": claim_material_sequence,
            }
        )
    return normalized[-MAX_CRITIC_BATCHES:]


def _critic_event_targets(event: dict[str, Any]) -> list[str]:
    targets = _bounded_strings(
        event.get("write_targets"), limit=MAX_CRITIC_BATCH_TARGETS + 1, size=2_000
    )
    if targets:
        return targets
    target = str(event.get("target") or "").strip()
    if target and not target.startswith("["):
        return [target[:2_000]]
    return []


def record_critic_local_write(
    contract: dict[str, Any],
    event: dict[str, Any],
    *,
    now: Callable[[], str] = _now_iso,
) -> dict[str, Any] | None:
    """Append one successful completed local write to its lane batch."""
    if (
        not contract.get("critic", {}).get("enabled")
        or event.get("phase") != "completed"
        or event.get("effect") != "local_write"
        or event.get("success") is False
    ):
        return None
    provider = str(event.get("provider") or "unknown").strip().lower()[:50]
    session_id = str(event.get("session_id") or "").strip()[:200]
    if not session_id:
        return None
    runtime = contract.setdefault("runtime", {})
    task_epoch = str(contract.get("task_epoch") or "")[:24]
    rows = normalize_critic_batches(
        runtime.get("critic_batches"), default_epoch=task_epoch
    )
    row = next(
        (
            item
            for item in reversed(rows)
            if item["provider"] == provider
            and item["session_id"] == session_id
            and item["task_epoch"] == task_epoch
            and item["state"] == "collecting"
        ),
        None,
    )
    timestamp = now()
    try:
        sequence = max(0, int(event.get("sequence", runtime.get("sequence", 0))))
    except (TypeError, ValueError):
        sequence = max(0, int(runtime.get("sequence", 0)))
    if row is None:
        row = {
            "schema": CRITIC_BATCH_SCHEMA,
            "batch_id": "cb-" + secrets.token_hex(12),
            "provider": provider or "unknown",
            "session_id": session_id,
            "task_epoch": task_epoch,
            "revision": max(1, int(contract.get("revision", 1))),
            "state": "collecting",
            "first_sequence": sequence,
            "last_sequence": sequence,
            "completed_writes": 0,
            "targets": [],
            "target_overflow": 0,
            "event_ids": [],
            "capabilities": [],
            "created_at": timestamp,
            "updated_at": timestamp,
            "claim_id": "",
            "claimed_at": "",
            "claim_material_sequence": 0,
        }
        rows.append(row)
    row["last_sequence"] = max(int(row["last_sequence"]), sequence)
    row["completed_writes"] = int(row["completed_writes"]) + 1
    for target in _critic_event_targets(event):
        if target in row["targets"]:
            continue
        if len(row["targets"]) < MAX_CRITIC_BATCH_TARGETS:
            row["targets"].append(target)
        else:
            row["target_overflow"] = int(row["target_overflow"]) + 1
    event_id = str(event.get("event_id") or "").strip()[:64]
    if event_id and event_id not in row["event_ids"]:
        row["event_ids"] = [*row["event_ids"], event_id][-MAX_CRITIC_BATCH_EVENTS:]
    capability = str(event.get("capability") or "").strip()[:256]
    if capability and capability not in row["capabilities"]:
        row["capabilities"] = [*row["capabilities"], capability][-32:]
    row["updated_at"] = timestamp
    runtime["critic_batches"] = rows[-MAX_CRITIC_BATCHES:]
    return dict(row)


def _parsed_critic_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def claim_critic_lane_batch(
    contract: dict[str, Any],
    *,
    provider: str,
    session_id: str,
    now: Callable[[], str] = _now_iso,
    claim_id: str = "",
) -> dict[str, Any] | None:
    """Claim one lane batch or surface one expired claim as abandoned."""
    if not contract.get("critic", {}).get("enabled"):
        return None
    clean_provider = provider.strip().lower() or "unknown"
    clean_session = session_id.strip()
    if not clean_session:
        return None
    runtime = contract.setdefault("runtime", {})
    task_epoch = str(contract.get("task_epoch") or "")[:24]
    rows = normalize_critic_batches(
        runtime.get("critic_batches"), default_epoch=task_epoch
    )
    timestamp = now()
    current = _parsed_critic_time(timestamp) or datetime.now(timezone.utc)
    outstanding = next(
        (
            item
            for item in rows
            if item["provider"] == clean_provider
            and item["session_id"] == clean_session
            and item["task_epoch"] == task_epoch
            and item["state"] in {"claimed", "abandoned"}
        ),
        None,
    )
    if outstanding is not None:
        if outstanding["state"] == "claimed":
            claimed_at = _parsed_critic_time(outstanding.get("claimed_at"))
            if (
                claimed_at is not None
                and (current - claimed_at).total_seconds() < CRITIC_CLAIM_TTL_SECONDS
            ):
                runtime["critic_batches"] = rows[-MAX_CRITIC_BATCHES:]
                return None
            outstanding["state"] = "abandoned"
            outstanding["updated_at"] = timestamp
        runtime["critic_batches"] = rows[-MAX_CRITIC_BATCHES:]
        return dict(outstanding)

    selected = next(
        (
            item
            for item in rows
            if item["provider"] == clean_provider
            and item["session_id"] == clean_session
            and item["task_epoch"] == task_epoch
            and item["state"] == "collecting"
            and int(item["completed_writes"]) > 0
        ),
        None,
    )
    if selected is None:
        runtime["critic_batches"] = rows[-MAX_CRITIC_BATCHES:]
        return None
    selected["state"] = "claimed"
    selected["claim_id"] = (claim_id.strip() or "cc-" + secrets.token_hex(12))[:80]
    selected["claimed_at"] = timestamp
    selected["updated_at"] = timestamp
    selected["claim_material_sequence"] = max(
        0, int(runtime.get("material_sequence", 0))
    )
    runtime["critic_batches"] = rows[-MAX_CRITIC_BATCHES:]
    return dict(selected)


def critic_claim_identity_present(
    contract: dict[str, Any],
    claim: dict[str, Any],
) -> bool:
    """Return whether the exact claimed batch still exists in current state."""
    runtime = contract.get("runtime", {})
    return any(
        isinstance(row, dict)
        and row.get("batch_id") == claim.get("batch_id")
        and row.get("claim_id") == claim.get("claim_id")
        and row.get("state") in {"claimed", "abandoned"}
        for row in runtime.get("critic_batches", [])
    )


def critic_claim_world_is_current(
    contract: dict[str, Any],
    claim: dict[str, Any],
) -> bool:
    """CAS guard preventing a stale model result from pausing changed state."""
    return (
        critic_claim_identity_present(contract, claim)
        and str(contract.get("task_epoch") or "") == str(claim.get("task_epoch") or "")
        and int(contract.get("revision", 0)) == int(claim.get("revision", -1))
        and int(contract.get("runtime", {}).get("material_sequence", 0))
        == int(claim.get("claim_material_sequence", -1))
    )


def settle_critic_claim(
    contract: dict[str, Any],
    claim: dict[str, Any],
) -> bool:
    """Remove exactly one claimed/abandoned batch after recording its result."""
    runtime = contract.setdefault("runtime", {})
    rows = runtime.get("critic_batches", [])
    if not isinstance(rows, list):
        return False
    before = len(rows)
    runtime["critic_batches"] = [
        row
        for row in rows
        if not (
            isinstance(row, dict)
            and row.get("batch_id") == claim.get("batch_id")
            and row.get("claim_id") == claim.get("claim_id")
        )
    ][-MAX_CRITIC_BATCHES:]
    return len(runtime["critic_batches"]) != before


def critic_event_for_claim(claim: dict[str, Any]) -> dict[str, Any]:
    """Render the bounded observable event consumed by the semantic critic."""
    targets = list(claim.get("targets") or [])
    target_digest = hashlib.sha256(
        json.dumps(targets, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "phase": "completed",
        "effect": "local_write",
        "success": True,
        "provider": str(claim.get("provider") or "unknown"),
        "session_id": str(claim.get("session_id") or ""),
        "capability": "guardian:semantic-batch-checkpoint",
        "target": f"[local-target-set:{target_digest}]",
        "write_targets": targets,
        "event_ids": list(claim.get("event_ids") or []),
        "event_id": str(claim.get("batch_id") or ""),
        "critic_batch_id": str(claim.get("batch_id") or ""),
        "completed_writes": max(1, int(claim.get("completed_writes", 1))),
        "target_overflow": max(0, int(claim.get("target_overflow", 0))),
    }

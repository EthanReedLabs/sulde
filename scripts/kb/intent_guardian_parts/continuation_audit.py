"""Incremental, idempotent continuation-event audit writes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from session_continuity import (
    CONTINUATION_EVENT_SCHEMA,
    render_context as render_continuation_context,
)

from .state import (
    IntentGuardianError,
    _exclusive_path_lock,
    atomic_write,
    audit_path,
    load_contract,
    now_iso,
)


def _append_continuation_event_once(
    path: Path,
    *,
    action: str,
    capsule: dict[str, Any],
    provider: str,
    session_id: str,
) -> bool:
    """Append one idempotent continuation event to the existing intent audit."""
    if action not in {"created", "loaded", "acknowledged"}:
        raise IntentGuardianError(f"unsupported continuation action: {action}")
    contract = load_contract(path)
    normalized_provider = provider.strip().lower()
    if normalized_provider not in {"claude", "codex", "unknown"}:
        normalized_provider = "unknown"
    native_session = session_id.strip()[:200]
    idempotency_key = hashlib.sha256(
        "\0".join(
            (action, str(capsule["capsule_id"]), normalized_provider, native_session)
        ).encode("utf-8")
    ).hexdigest()
    row = {
        "schema": CONTINUATION_EVENT_SCHEMA,
        "at": now_iso(),
        "action": action,
        "actor": normalized_provider if action != "created" else "intent-guardian",
        "provider": normalized_provider,
        "session_id": native_session,
        "source_provider": capsule["source"]["provider"],
        "source_session_id_present": bool(capsule["source"]["session_id"]),
        "capsule_id": capsule["capsule_id"],
        "proposal_digest": capsule["proposal_digest"],
        "intent_id": contract["intent_id"],
        "intent_revision": contract["revision"],
        "context_chars": len(render_continuation_context(capsule)),
        "authority_transferred": False,
        "idempotency_key": idempotency_key,
    }
    target = audit_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(f".{target.name}.lock")
    index_path = target.with_name(f".{target.name}.continuation-index.json")
    with _exclusive_path_lock(lock_path):
        try:
            audit_stat = target.stat()
            audit_identity = [int(audit_stat.st_dev), int(audit_stat.st_ino)]
            audit_size = int(audit_stat.st_size)
        except FileNotFoundError:
            audit_identity = [0, 0]
            audit_size = 0
        offset = 0
        known_keys: set[str] = set()
        index_current = False
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
            if (
                isinstance(index, dict)
                and index.get("schema") == "sulde-continuation-audit-index-v1"
                and index.get("audit_identity") == audit_identity
                and isinstance(index.get("audit_offset"), int)
                and 0 <= index["audit_offset"] <= audit_size
                and isinstance(index.get("idempotency_keys"), list)
            ):
                offset = int(index["audit_offset"])
                index_current = offset == audit_size
                known_keys = {
                    str(value)
                    for value in index["idempotency_keys"]
                    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                }
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        processed_offset = offset
        if target.is_file() and offset < audit_size:
            with target.open("rb") as handle:
                handle.seek(offset)
                pending = handle.read()
            for raw_line in pending.splitlines(keepends=True):
                if not raw_line.endswith(b"\n"):
                    break
                processed_offset += len(raw_line)
                try:
                    existing = json.loads(raw_line.decode("utf-8", errors="replace"))
                except (UnicodeError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(existing, dict)
                    and existing.get("schema") == CONTINUATION_EVENT_SCHEMA
                ):
                    existing_key = existing.get("idempotency_key")
                    if isinstance(existing_key, str):
                        known_keys.add(existing_key)
        if idempotency_key in known_keys:
            if index_current and processed_offset == audit_size:
                return False
            atomic_write(
                index_path,
                json.dumps(
                    {
                        "schema": "sulde-continuation-audit-index-v1",
                        "audit_identity": audit_identity,
                        "audit_offset": processed_offset,
                        "idempotency_keys": sorted(known_keys),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
            )
            return False
        encoded_row = (
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        ).encode("utf-8")
        with target.open("ab") as handle:
            handle.write(encoded_row)
            handle.flush()
            os.fsync(handle.fileno())
        current_stat = target.stat()
        known_keys.add(idempotency_key)
        atomic_write(
            index_path,
            json.dumps(
                {
                    "schema": "sulde-continuation-audit-index-v1",
                    "audit_identity": [int(current_stat.st_dev), int(current_stat.st_ino)],
                    "audit_offset": int(current_stat.st_size),
                    "idempotency_keys": sorted(known_keys),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n",
        )
    return True

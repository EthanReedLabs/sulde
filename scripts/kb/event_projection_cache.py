#!/usr/bin/env python3
"""Fail-soft durable checkpoints for the read-only event projection.

The cache is a parsing shortcut, never an event authority.  Callers must bind
every cached source row to an exact authoritative byte prefix before reuse.
An unreadable, stale, oversized, or version-mismatched cache is discarded and
costs only a full replay.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping


CACHE_SCHEMA = "sulde-observation-projection-cache-v1"
STATE_VERSION = 3
MAX_CACHE_BYTES = 64 * 1024 * 1024


def default_cache_path(home: Path) -> Path:
    return home / "projections" / "event-observer-v1.json"


def source_key(kind: str, logical_name: str) -> str:
    return hashlib.sha256(
        f"{kind}\0{logical_name}".encode("utf-8", errors="replace")
    ).hexdigest()


def load_cache(path: Path) -> tuple[dict[str, Any], str]:
    """Load only the outer checkpoint envelope; source entries are caller-validated."""
    if not path.is_file():
        return {}, "missing"
    try:
        if path.stat().st_size > MAX_CACHE_BYTES:
            return {}, "oversized"
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, "invalid"
    if not isinstance(value, dict) or value.get("schema") != CACHE_SCHEMA:
        return {}, "invalid"
    if value.get("stateVersion") != STATE_VERSION:
        return {}, "version_mismatch"
    sources = value.get("sources")
    if not isinstance(sources, dict) or any(
        not isinstance(key, str) or not isinstance(entry, dict)
        for key, entry in sources.items()
    ):
        return {}, "invalid"
    return value, "loaded"


def write_cache(
    path: Path,
    *,
    sources: Mapping[str, Mapping[str, Any]],
    as_of_seq: int,
    source_revision: str,
) -> str:
    """Atomically replace a complete checkpoint; failure never fails observation."""
    payload = {
        "schema": CACHE_SCHEMA,
        "stateVersion": STATE_VERSION,
        "asOfSeq": int(as_of_seq),
        "sourceRevision": source_revision,
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources": dict(sources),
    }
    try:
        encoded = (
            json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        return "invalid_state"
    if len(encoded) > MAX_CACHE_BYTES:
        return "oversized"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                if os.name != "nt":
                    os.fchmod(handle.fileno(), 0o600)
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
    except OSError:
        return "write_failed"
    return "written"

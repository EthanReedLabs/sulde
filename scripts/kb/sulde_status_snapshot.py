#!/usr/bin/env python3
"""Small, fail-soft status snapshot shared by interactive status readers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any


SCHEMA = "sulde-statusline-snapshot-v1"
SNAPSHOT_RELATIVE = Path("projections") / "sulde-statusline-v1.json"
MAX_SNAPSHOT_BYTES = 16 * 1024
MAX_LINE_LENGTH = 240
MAX_AGE_SECONDS = 3 * 60 * 60
MAX_FUTURE_SKEW_SECONDS = 5 * 60
_ANSI_LIGHT = re.compile(r"\x1b\[(?:31|32|33)m●\x1b\[0m")


def snapshot_path(home: Path) -> Path:
    # Do not resolve aliases here: doing so before validation would turn a
    # symlinked ``projections`` directory into an apparently safe outside path.
    return Path(os.path.abspath(os.fspath(home.expanduser()))) / SNAPSHOT_RELATIVE


def _unsafe_container(home: Path, path: Path) -> bool:
    root = path.parent.parent
    try:
        return root.is_symlink() or path.parent.is_symlink()
    except OSError:
        return True


def _bounded_bytes(home: Path) -> tuple[bytes | None, str]:
    path = snapshot_path(home)
    if _unsafe_container(home, path):
        return None, "unsafe"
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "unreadable"
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return None, "unsafe"
    if os.name != "nt":
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            return None, "unsafe"
        getuid = getattr(os, "getuid", None)
        if callable(getuid) and metadata.st_uid != getuid():
            return None, "unsafe"
    if metadata.st_size > MAX_SNAPSHOT_BYTES:
        return None, "invalid"
    descriptor = -1
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            return None, "unsafe"
        payload = os.read(descriptor, MAX_SNAPSHOT_BYTES + 1)
        if len(payload) > MAX_SNAPSHOT_BYTES:
            return None, "invalid"
        return payload, "fresh"
    except OSError:
        return None, "unreadable"
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_line(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("sulde "):
        return None
    if not value or len(value) > MAX_LINE_LENGTH or "\n" in value or "\r" in value:
        return None
    without_lights = _ANSI_LIGHT.sub("●", value)
    if "\x1b" in without_lights:
        return None
    if any(ord(character) < 32 for character in without_lights):
        return None
    return value


def _fallback(reason: str) -> dict[str, Any]:
    labels = {
        "missing": "状态快照待刷新",
        "invalid": "状态快照无效",
        "unsafe": "状态快照路径不安全",
        "stale": "状态快照已过期",
        "unreadable": "状态快照不可读",
    }
    label = labels.get(reason, "状态快照不可用")
    return {
        "line": f"sulde \033[33m●\033[0m {label}",
        "healthy": False,
        "snapshot_status": reason,
    }


def read_snapshot(
    home: Path,
    *,
    now: datetime | None = None,
    max_age_seconds: int = MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Read one bounded snapshot without touching event or intervention logs."""
    encoded, state = _bounded_bytes(home)
    if encoded is None:
        return _fallback(state)
    try:
        payload = json.loads(encoded.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError):
        return _fallback("unreadable")
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return _fallback("invalid")
    line = _safe_line(payload.get("line"))
    generated_at = _timestamp(payload.get("generated_at"))
    healthy = payload.get("healthy")
    if line is None or generated_at is None or not isinstance(healthy, bool):
        return _fallback("invalid")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    delta = int((current - generated_at).total_seconds())
    if delta < -MAX_FUTURE_SKEW_SECONDS:
        return _fallback("invalid")
    age = max(0, delta)
    if age > max_age_seconds:
        result = _fallback("stale")
        result["snapshot_age_seconds"] = age
        return result
    return {
        "line": line,
        "healthy": healthy,
        "snapshot_status": "fresh",
        "snapshot_age_seconds": age,
        "generated_at": generated_at.isoformat(),
        "scope": str(payload.get("scope") or "background_runtime"),
    }


def write_snapshot(
    home: Path,
    *,
    line: str,
    healthy: bool,
    scope: str = "background_runtime",
    now: datetime | None = None,
) -> bool:
    """Atomically publish a bounded owner-only projection of a full status run."""
    safe_line = _safe_line(line)
    if safe_line is None or not isinstance(healthy, bool):
        return False
    path = snapshot_path(home)
    parent = path.parent
    try:
        if _unsafe_container(home, path):
            return False
        parent.mkdir(parents=True, exist_ok=True)
        if _unsafe_container(home, path):
            return False
        if path.exists() and path.is_symlink():
            return False
        payload = {
            "schema": SCHEMA,
            "generated_at": (now or datetime.now(timezone.utc))
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "healthy": healthy,
            "scope": scope,
            "line": safe_line,
        }
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
        if len(encoded) > MAX_SNAPSHOT_BYTES:
            return False
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(parent)
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
        return True
    except (OSError, TypeError, ValueError, OverflowError):
        return False

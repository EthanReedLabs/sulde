"""Canonical host-qualified identities for shared Sulde sessions."""

from __future__ import annotations

from typing import Any


HOSTS = ("claude", "codex")
SOURCE_HOSTS = (*HOSTS, "import", "unknown")


def normalize_source_host(value: Any) -> str:
    """Return a supported provenance value without trusting arbitrary clients."""
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SOURCE_HOSTS else "unknown"


def normalize_session_identity(
    session_id: Any,
    source_host: Any = "unknown",
) -> tuple[str, str]:
    """Return ``(host-qualified session ID, authoritative source host)``.

    ``claude_`` and ``codex_`` are accepted only as legacy spellings.  An
    existing host prefix is authoritative; this prevents a malformed adapter
    hint from relabelling an already-qualified session.
    """
    raw = str(session_id or "").strip()
    declared = normalize_source_host(source_host)
    if not raw:
        return "", declared

    for host in HOSTS:
        for separator in (":", "_"):
            prefix = f"{host}{separator}"
            if raw.startswith(prefix) and len(raw) > len(prefix):
                return f"{host}:{raw[len(prefix):]}", host

    if declared in HOSTS:
        return f"{declared}:{raw}", declared
    return raw, declared

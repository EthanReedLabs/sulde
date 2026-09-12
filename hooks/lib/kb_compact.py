"""Clear per-session KB recall dedup state before context compaction."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    """Mirror tools/kb-index/common.py without importing the tool dependency tree."""
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _safe_session_id(session_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:100]
    if not safe or safe in {".", ".."}:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return safe


def run(payload: dict[str, Any]) -> None:
    try:
        session_id = str(payload.get("session_id") or "")
        if not session_id:
            return
        path = _state_dir() / "session-recall" / f"{_safe_session_id(session_id)}.json"
        path.unlink(missing_ok=True)
    except Exception:
        return

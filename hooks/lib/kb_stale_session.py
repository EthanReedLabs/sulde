"""Warn when a resumed session may span plugin or environment changes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_STALE_HOURS = 4.0


def _state_dir() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _session_recall_path(session_id: str) -> Path | None:
    if not session_id:
        return None
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:100]
    if not safe or safe in {".", ".."}:
        safe = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return _state_dir() / "session-recall" / f"{safe}.json"


def _transcript_path(payload: dict[str, Any]) -> Path | None:
    for key in ("transcript_path", "transcriptPath", "transcript"):
        value = payload.get(key)
        if isinstance(value, (str, os.PathLike)) and str(value):
            return Path(value).expanduser()
    return None


def _mtime(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return path.stat().st_mtime if path.is_file() else None
    except OSError:
        return None


def _stale_threshold_hours() -> float:
    try:
        value = float(os.environ.get("SULDE_STALE_SESSION_HOURS", DEFAULT_STALE_HOURS))
        return value if value > 0 else DEFAULT_STALE_HOURS
    except (TypeError, ValueError):
        return DEFAULT_STALE_HOURS


def run(payload: Any) -> None:
    """Emit one SessionStart context line for stale resumes; fail silently."""
    try:
        if not isinstance(payload, dict) or payload.get("source") != "resume":
            return
        recall_path = _session_recall_path(str(payload.get("session_id") or ""))
        modified_at = _mtime(recall_path)
        if modified_at is None:
            modified_at = _mtime(_transcript_path(payload))
        if modified_at is None:
            return
        idle_hours = max(0.0, (time.time() - modified_at) / 3600)
        if idle_hours <= _stale_threshold_hours():
            return
        rounded_hours = max(1, int(idle_hours + 0.5))
        context = (
            f"[sulde] 本会话已闲置约 {rounded_hours} 小时——期间插件/环境可能已变更"
            "(参见 ap-0181)。如遇 hook 报错或行为异常，请重启并恢复本 thread；"
            "存在待审方案时 SessionStart 会同时恢复不含授权的结构化续接上下文。"
        )
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    except Exception:
        return

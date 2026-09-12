"""Advisory reminder for dev commits that look like bug fixes."""

from __future__ import annotations

import re
import sys
from typing import Any

from sulde_common import SuldeConfig


_GIT_COMMIT_RE = re.compile(r"\bgit\s+commit\b", re.IGNORECASE)
_FIX_RE = re.compile(r"fix|修复|bug|崩溃|crash|闪退", re.IGNORECASE)
_REMINDER = (
    "[sulde:postmortem] 修复类 commit 请先过 4 问：踩过吗/会再踩吗/"
    "能 lint 拦吗/其他端有同款吗 → skills/dev/postmortem"
)


def run(config: SuldeConfig, payload: dict[str, Any]) -> None:
    """Print one reminder when a dev is about to make a fix-like commit."""
    try:
        if config.role != "dev" or payload.get("tool_name") != "Bash":
            return
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            return
        command = str(tool_input.get("command") or "")
        if _GIT_COMMIT_RE.search(command) and _FIX_RE.search(command):
            sys.stdout.write(_REMINDER + "\n")
    except Exception:
        return

"""PreToolUse guard for writes into the governed knowledge containers."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


TOOLS = {"Write", "Edit", "MultiEdit"}
CONTAINER_DIRS = {"anti-patterns", "platform-kb", "tech-docs", "work-model"}
CONTAINERS = {"anti-patterns", "platform-kb", "tech-docs", "case-studies", "work-model"}
PLATFORMS = {"android", "ios", "flutter", "harmonyos", "web", "cross", "none"}
EXCLUDED_BASENAMES = {"INDEX.md", "README.md"}
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
DEV_BLOCK_REASON = (
    "dev role must not write knowledge/ directly — draft a sediment candidate into "
    "the handoff; the coordinator is the single writer (skills/sediment §0)"
)
ADVISORY = (
    "[sulde-kb] knowledge markdown requires valid frontmatter with controlled "
    "container/platform values; run python3 scripts/kb/lint-frontmatter.py"
)


def _knowledge_target(file_path: str) -> Path | None:
    if not file_path:
        return None
    try:
        target = Path(file_path).expanduser().resolve(strict=False)
        if target.suffix.lower() != ".md" or target.name in EXCLUDED_BASENAMES:
            return None
        cursor = target.parent
        root: Path | None = None
        while True:
            if (cursor / "knowledge" / "SEDIMENTATION-STANDARD.md").is_file():
                root = cursor
                break
            if cursor == cursor.parent:
                break
            cursor = cursor.parent
        if root is None:
            return None
        relative = target.relative_to(root)
        if (
            len(relative.parts) < 3
            or relative.parts[0] != "knowledge"
            or relative.parts[1] not in CONTAINER_DIRS
        ):
            return None
        return target
    except (OSError, RuntimeError, ValueError):
        return None


def _valid_frontmatter(content: str) -> bool:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    try:
        end = next(
            index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
        )
    except StopIteration:
        return False
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        match = KEY_RE.match(line)
        if match:
            fields[match.group(1)] = (match.group(2) or "").strip().strip("'\"")
    return fields.get("container") in CONTAINERS and fields.get("platform") in PLATFORMS


def run(config: Any, payload: dict[str, Any]) -> None:
    """Block dev writes or advise malformed Write content; fail open on errors."""
    try:
        tool_name = str(payload.get("tool_name") or "")
        if tool_name not in TOOLS:
            return
        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            return
        if _knowledge_target(str(tool_input.get("file_path") or "")) is None:
            return
        if getattr(config, "role", None) == "dev":
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": DEV_BLOCK_REASON,
                }
            }
            sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
            raise SystemExit(0)
        if tool_name == "Write" and not _valid_frontmatter(
            str(tool_input.get("content") or "")
        ):
            sys.stdout.write(ADVISORY + "\n")
    except SystemExit:
        raise
    except Exception:
        return

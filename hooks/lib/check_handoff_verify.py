"""check_handoff_verify — dev Write/Edit guard.

Blocks handoff docs that omit `改动文件清单` / `verify` sections — i.e. dev
posting "task done" without explicit file list + build/install verification.
"""

from __future__ import annotations

from typing import Any

from enforcement import sulde_exit_or_warn
from sulde_common import SuldeConfig, match_frontend_path

DEFAULT_SENTINELS = (
    "改动文件清单",
    "## §改动文件清单",
    "## §verify",
    "## Verify",
    "Build verify",
    "## §build verify",
)

DEFAULT_EXEMPT_SUBDIRS = ("archive",)


def run(config: SuldeConfig, payload: dict[str, Any]) -> None:
    if config.role not in ("dev", "both"):
        return
    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return

    tool_input = payload.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "")
    if not file_path or not file_path.endswith(".md"):
        return

    if not _is_handoff_md(file_path, config):
        return

    content = _extract_write_content(tool_name, tool_input)
    if _has_required_section(content, config):
        return

    reason_en = (
        "Dev handoff is missing required sections (改动文件清单 / verify).\n"
        f"file: {file_path}\n\n"
        "A complete handoff must include:\n"
        "  1. § 改动文件清单 — files touched\n"
        "  2. § verify — build/install/runtime evidence (commands + output)\n"
        "  3. § escalation — coordinator follow-up items (if any)\n"
        "Docs: skills/dev/handoff/SKILL.md"
    )
    reason_zh = (
        "Dev handoff 缺必备段(改动文件清单 / verify)。\n"
        f"文件:{file_path}\n\n"
        "完整 handoff 必含:\n"
        "  1. § 改动文件清单 — 改了哪些文件\n"
        "  2. § verify — build / install / 真机验证证据(命令 + 输出)\n"
        "  3. § escalation — 协调端跟进项(若有)\n"
        "细规则:skills/dev/handoff/SKILL.md"
    )

    sulde_exit_or_warn(
        config,
        "hard",
        reason=reason_en,
        reason_i18n={"en": reason_en, "zh": reason_zh},
        hook_event="PreToolUse",
        tool_name=tool_name,
        docs_section="422-check_handoff_verifypy",
    )


# ─── helpers ────────────────────────────────────────────────────────────────

def _is_handoff_md(file_path: str, config: SuldeConfig) -> bool:
    if "/.ai-workspace/handoff/" not in file_path:
        return False
    if config.frontends and match_frontend_path(config, file_path) is None:
        return False

    exempt = _override_list(config, ("enforcement", "handoff", "exempt_subdirs"), DEFAULT_EXEMPT_SUBDIRS)
    for sub in exempt:
        token = f"/handoff/{sub.strip('/')}/"
        if token in file_path:
            return False
    return True


def _has_required_section(content: str, config: SuldeConfig) -> bool:
    sentinels = _override_list(
        config, ("enforcement", "handoff", "required_sections"), DEFAULT_SENTINELS
    )
    for sentinel in sentinels:
        if sentinel and sentinel in content:
            return True
    return False


def _override_list(config: SuldeConfig, keys: tuple[str, ...], default: tuple[str, ...]) -> tuple[str, ...]:
    cursor: Any = config.raw
    for key in keys:
        if not isinstance(cursor, dict):
            return tuple(default)
        cursor = cursor.get(key)
    if isinstance(cursor, list) and cursor:
        return tuple(str(x) for x in cursor)
    return tuple(default)


def _extract_write_content(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Write":
        return str(tool_input.get("content") or "")
    if "new_string" in tool_input:
        return str(tool_input.get("new_string") or "")
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        return "\n".join(str((e or {}).get("new_string") or "") for e in edits)
    return ""

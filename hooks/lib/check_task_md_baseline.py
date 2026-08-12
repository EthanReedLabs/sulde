"""check_task_md_baseline — coordinator Write/Edit guard.

Blocks task-md drafts that omit a `§baseline` evidence section. Catches the
generic "draft from memory instead of verifying the repository" anti-pattern.

Trigger: Write/Edit a `.md` file under any `<frontend>/.ai-workspace/tasks/`
that is not in an exempt subdir (archive/ etc).
"""

from __future__ import annotations

from typing import Any

from enforcement import sulde_exit_or_warn
from sulde_common import SuldeConfig, match_frontend_path

DEFAULT_SENTINELS = (
    "§起草前 baseline 实证",
    "§起草前 baseline",
    "## §0 baseline",
    "## §起草前 baseline",
    "§0.5 baseline",
    "起草前 baseline 实证",
    "## Baseline evidence",
    "§Baseline evidence",
)

DEFAULT_EXEMPT_SUBDIRS = ("archive",)


def run(config: SuldeConfig, payload: dict[str, Any]) -> None:
    if config.role not in ("coordinator", "both"):
        return
    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return

    tool_input = payload.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "")
    if not file_path or not file_path.endswith(".md"):
        return

    if not _is_task_md(file_path, config):
        return

    content = _extract_write_content(tool_name, tool_input)
    if _has_baseline_section(content, config):
        return

    reason_en = (
        "Coordinator task-md is missing a `§baseline evidence` section.\n"
        f"file: {file_path}\n\n"
        "Required 5-step baseline before drafting (paste outputs into task-md):\n"
        "  1. git log --since=14d --oneline (per affected frontend)\n"
        "  2. grep -rn '<symbol>' (verify class/api names literally)\n"
        "  3. git log -S '<symbol>' --since=30d (provenance)\n"
        "  4. grep -rln '<scaffold>' across frontends (scaffold usage)\n"
        "  5. cross-verify scaffold values vs design-truth (conflict table)\n"
        "Docs: skills/coordinator/writing-task-md/SKILL.md §0.5"
    )
    reason_zh = (
        "协调端起草 task md 缺 `§baseline 实证` 段。\n"
        f"文件:{file_path}\n\n"
        "必跑 5 步 baseline + 引用 grep 输出 / 行号到 task md 顶部 `§起草前 baseline` 段:\n"
        "  1. git log --since=14d --oneline 各 frontend — 近 14d commit\n"
        "  2. grep -rn '<symbol>' 各 frontend 源码 — 字面 verify(class / API 真名)\n"
        "  3. git log -S '<symbol>' --since=30d — 区分自发 / 真值 / 补充\n"
        "  4. grep -rln '<scaffold>' 各 frontend 源码 — scaffold 全站既定 usage\n"
        "  5. cross verify scaffold 实际数值 vs 设计真值 — 数据源冲突表\n\n"
        "细规则:skills/coordinator/writing-task-md/SKILL.md §0.5\n"
        "反模式:docs-hub/ADR/0001-coordinator-impression-based-dispatch.md"
    )

    sulde_exit_or_warn(
        config,
        "hard",
        reason=reason_en,
        reason_i18n={"en": reason_en, "zh": reason_zh},
        hook_event="PreToolUse",
        tool_name=tool_name,
        docs_section="421-check_task_md_baselinepy",
    )


# ─── helpers ────────────────────────────────────────────────────────────────

def _is_task_md(file_path: str, config: SuldeConfig) -> bool:
    if "/.ai-workspace/tasks/" not in file_path:
        return False
    # When the project declares frontends, the task md must sit under one of them.
    if config.frontends and match_frontend_path(config, file_path) is None:
        return False

    exempt = _override_list(config, ("enforcement", "task_md", "exempt_subdirs"), DEFAULT_EXEMPT_SUBDIRS)
    for sub in exempt:
        token = f"/tasks/{sub.strip('/')}/"
        if token in file_path:
            return False
    return True


def _has_baseline_section(content: str, config: SuldeConfig) -> bool:
    sentinels = _override_list(
        config, ("enforcement", "task_md", "required_sections"), DEFAULT_SENTINELS
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
    # Edit / MultiEdit — concat new_string fields so the sentinel can land via Edit too.
    if "new_string" in tool_input:
        return str(tool_input.get("new_string") or "")
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        return "\n".join(str((e or {}).get("new_string") or "") for e in edits)
    return ""

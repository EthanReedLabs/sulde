"""check_task_md_baseline — coordinator task contract Write/Edit guard.

Blocks task-md drafts that omit a `§baseline` evidence section. Catches the
"draft from memory instead of grepping the repo" anti-pattern (SyntheticProject
ADR §0100). New full writes must also carry a provider-neutral
``capability_tier`` and must not reintroduce provider-specific runtime fields.

Trigger: Write/Edit a `.md` file under any `<frontend>/.ai-workspace/tasks/`
that is not in an exempt subdir (archive/ etc).
"""

from __future__ import annotations

import re
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
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        return

    tool_input = payload.get("tool_input") or {}
    file_path = str(tool_input.get("file_path") or "")
    if not file_path or not file_path.endswith(".md"):
        return

    if not _is_task_md(file_path, config):
        return

    content = _extract_write_content(tool_name, tool_input)
    if not _has_baseline_section(content, config):
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

    if _has_legacy_runtime_field(content):
        reason_en = (
            "New task-md metadata must not pin provider-specific `model` or "
            "`thinking_mode` fields. Use `capability_tier: light|balanced|deep`; "
            "the target Claude Code or Codex session renders native controls."
        )
        reason_zh = (
            "新 task md 禁止写提供方专属 `model` / `thinking_mode` / `思考模式` 字段。"
            "请改用 `capability_tier: light|balanced|deep`，再由目标 Claude Code 或 "
            "Codex session 按当前模型渲染原生控制。"
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

    if tool_name == "Write" and not _has_capability_tier(content):
        reason_en = (
            "New task-md metadata is missing `capability_tier: "
            "light|balanced|deep`. Provider model names are not a shared task contract."
        )
        reason_zh = (
            "新 task md 缺少 `capability_tier: light|balanced|deep`。"
            "提供方型号不能作为共享任务契约。"
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


def _has_capability_tier(content: str) -> bool:
    metadata = _metadata_block(content)
    return re.search(
        r"(?im)^\s*(?:-\s*)?capability_tier\s*:\s*"
        r"(?:\*\*)?(?:light|balanced|deep)(?:\*\*)?\s*(?:#.*)?$",
        metadata,
    ) is not None


def _has_legacy_runtime_field(content: str) -> bool:
    return re.search(
        r"(?im)^\s*(?:-\s*)?(?:"
        r"model\s*:\s*(?:\*\*)?(?:opus|sonnet|haiku)(?:\*\*)?"
        r"|(?:thinking_mode|thinking|思考模式)\s*:\s*(?:\*\*)?"
        r"(?:default|think|think[ -]hard|ultrathink)(?:\*\*)?"
        r")\s*(?:#.*)?$",
        content,
    ) is not None


def _metadata_block(content: str) -> str:
    lines = content.splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None:
        return ""
    if lines[first].strip() == "---":
        for index in range(first + 1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[first + 1:index])
    prefix: list[str] = []
    for line in lines[first:first + 40]:
        if line.lstrip().startswith("#"):
            break
        prefix.append(line)
    return "\n".join(prefix)


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

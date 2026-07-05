"""skill_trigger — UserPromptSubmit reminder hook.

When the user's prompt matches a configured trigger pattern, print a
reminder asking Claude to invoke the relevant skill before acting. Pure
advisory — never blocks, never exits non-zero.

Default trigger map covers the coordinator/dev split. Projects can extend
or override via `.sulde-config.yaml: skill_triggers:` (merged with defaults).
"""

from __future__ import annotations

import re
from typing import Any

from sulde_common import SuldeConfig


# Each entry: (regex_pattern, skill_id, role_filter, reminder)
# role_filter: "coordinator" | "dev" | "any"
DEFAULT_TRIGGERS: tuple[tuple[str, str, str, str], ...] = (
    (
        r"(?:写|起草|草拟|draft).{0,4}task\s*md|派活|派单|派任务|dispatch.{0,3}task|assign.{0,3}task|/assign\b",
        "writing-task-md",
        "coordinator",
        "Before writing a task-md, invoke the writing-task-md skill — it enforces baseline / design-truth / scope / verify / git / model-selection gates.",
    ),
    (
        r"/assign\b|执行\s*task|跑\s*task|run\s*task",
        "assign",
        "dev",
        "You are about to run a task-md. Invoke the assign skill — it gates on baseline drift, design-truth staleness, and scope.",
    ),
    (
        r"/handoff\b|写\s*handoff|提交\s*handoff|交接给协调端",
        "handoff",
        "dev",
        "Handoff-writing detected. Invoke the dev/handoff skill — required sections: file list + verify + escalation.",
    ),
    (
        r"重大评审|pre-?release|多源\s*review|对外发布|发布前\s*review|什么问题",
        "multi-source-review",
        "any",
        "Major review detected. Invoke the multi-source-review skill — it prevents single-source misjudgment via 4-class triage (A real / B reviewer-context-gap / C user-call / D nit).",
    ),
)


def run(config: SuldeConfig, payload: dict[str, Any]) -> None:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return

    matches: list[tuple[str, str]] = []
    seen: set[str] = set()
    triggers = list(DEFAULT_TRIGGERS) + _user_triggers(config)
    for pattern, skill, role_filter, reminder in triggers:
        if role_filter != "any" and role_filter != config.role and config.role != "both":
            continue
        try:
            if re.search(pattern, prompt, re.IGNORECASE):
                if skill not in seen:
                    matches.append((skill, reminder))
                    seen.add(skill)
        except re.error:
            continue

    if not matches:
        return

    lines = [
        "⚠️ sulde skill triggers matched in this prompt — invoke the relevant skill BEFORE acting:",
        "",
    ]
    for skill, reminder in matches:
        lines.append(f"  • [sulde:{skill}] {reminder}")
    lines.append("")
    lines.append("If the skill is already loaded this session, you can skip the re-invoke.")
    print("\n".join(lines))


def _user_triggers(config: SuldeConfig) -> list[tuple[str, str, str, str]]:
    entries = config.raw.get("skill_triggers") if isinstance(config.raw, dict) else None
    if not isinstance(entries, list):
        return []
    out: list[tuple[str, str, str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        regex = str(entry.get("regex") or "").strip()
        skill = str(entry.get("skill") or "").strip()
        if not regex or not skill:
            continue
        role = str(entry.get("role") or "any").strip().lower() or "any"
        reminder = str(entry.get("reminder") or f"Invoke the {skill} skill.").strip()
        out.append((regex, skill, role, reminder))
    return out

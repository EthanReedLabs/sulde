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
        r"简历|文案|措辞|表达(?:方式|风格)?|不是(?:这样|这个意思)|越来越偏|和我想要的.{0,8}不一样|反复(?:犯错|改错)|意图|监督.{0,8}(?:agent|执行)|mcp.{0,8}(?:写|改|发布|发送)",
        "intent-guardian",
        "any",
        "Intent-sensitive or drift-prone work detected. Invoke the intent-guardian skill before material changes; mirror and confirm intent, then keep Skill/MCP/tool actions under one contract.",
    ),
    (
        r"(?:写|起草|草拟|draft).{0,4}task\s*md|派活|派单|派任务|dispatch.{0,3}task|assign.{0,3}task|/assign\b",
        "writing-task-md",
        "coordinator",
        "Before writing a task-md, invoke the writing-task-md skill for its contract gates; render the final model/reasoning block with dispatch-task.",
    ),
    (
        r"给.{0,8}(?:Dev|Agent|终端).{0,8}(?:发送|复制)|(?:发送|签发|派发).{0,8}(?:Dev|Agent|终端)|继续原任务|返修任务|档位切换|模型.{0,6}(?:档位|切换)|reasoning.{0,6}(?:tier|effort|档位)",
        "dispatch-task",
        "any",
        "Before emitting a copyable dispatch block, invoke dispatch-task and paste the deterministic current-provider output. Never handwrite a Claude model command for Codex.",
    ),
    (
        r"(?:并行|parallel).{0,4}(?:task|dev)|多个并行|[2-9]\s*个并行|批量派|同时派",
        "dispatch-parallel-task",
        "coordinator",
        "Parallel dispatch detected. Invoke the dispatch-parallel-task skill — it enforces the 5-question coupling check and the shared-file whitelist.",
    ),
    (
        r"周期\s*audit|周期审计|反模式\s*audit|page-relation|脚手架规范|sweep.{0,10}handoff|处理.{0,4}handoff",
        "coordinator-maintenance",
        "coordinator",
        "Maintenance task detected. Invoke the coordinator-maintenance skill — covers handoff sweep / antipattern audit / page-relation sync.",
    ),
    (
        r"收到.{0,6}handoff|Dev.{0,8}handoff|handoff.{0,6}(来了|收到|review|评审)|review.{0,6}handoff",
        "handoff-code-review",
        "coordinator",
        "收到 handoff 后必跑 4 维 review（常规/架构统一/复用抽取/最小改动）→ skills/coordinator/handoff-code-review。",
    ),
    (
        r"sediment.{0,10}(代码|BTM|真值)|(完工|merge|合并).{0,10}sediment|BTM.{0,8}(沉淀|更新|同步)",
        "sediment-from-code",
        "coordinator",
        "代码即真值，以 git log + diff 为源沉淀 BTM → skills/coordinator/sediment-from-code。",
    ),
    (
        r"上浮.{0,6}(知识|案例|KB)|curate|Layer\s*1.{0,6}(转|上浮)|沉淀欠债",
        "curate-to-kb",
        "coordinator",
        "Layer1→Layer2 脱敏精选 → skills/coordinator/curate-to-kb。",
    ),
    (
        r"设计稿|改稿|新稿|\.pen|figma.{0,3}export|新设计|同步设计|update.{0,3}design|refresh.{0,3}design",
        "update-design",
        "coordinator",
        "Design-truth refresh requested. Invoke the update-design skill — it extracts node tree + visual + asset-reference list from the configured design-source MCP.",
    ),
    (
        r"甲方(?:补充|又说)|客户(?:提了|又改|又说)|PRD\s*(?:增加|新增|补)|需求(?:新增|补|补充)|新增需求|/record-prd",
        "record-prd-supplement",
        "coordinator",
        "PRD supplement detected. Invoke the record-prd-supplement skill — it canonicalises supplement format + verifies against design-truth.",
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
    (
        r"\A(?![\s\S]*(?:代码|BTM|真值))[\s\S]*?(?:沉淀|/sediment\b|值得记录?的坑|记入知识库|sediment)",
        "sediment",
        "any",
        "Sedimentation intent detected. Invoke the sediment skill — dedup-search first (merge-into vs series vs new). Dev role drafts a candidate into the handoff only; the coordinator is the single writer to knowledge/.",
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

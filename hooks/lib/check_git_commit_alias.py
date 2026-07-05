"""check_git_commit_alias — dev Bash guard.

`git commit` without a `git as-<alias>` prefix lets the local default author
(often the dev's personal git config) leak into the project history. We
require commits go through a project-local alias (`git as-a`, `git as-b`, ...)
so the author is unambiguous and AI traces are easier to audit.

Skip: merges / reverts / cherry-picks (those run their own commit step,
re-using the picked author).
"""

from __future__ import annotations

import re
from typing import Any

from enforcement import sulde_exit_or_warn
from sulde_common import SuldeConfig

_COMMIT_RE = re.compile(r"(?:^|[&;|]|^\s*\(\s*)\s*git\s+commit(\s|$)")
_BYPASS_RE = re.compile(r"\bgit\s+(?:merge|revert|cherry-pick|rebase|am|am3|stash)\b")
_ALIAS_RE = re.compile(r"\bgit\s+as-[a-zA-Z0-9_-]+\s+commit\b")


def run(config: SuldeConfig, payload: dict[str, Any]) -> None:
    if config.role not in ("dev", "both"):
        return
    if not _required(config):
        return
    if payload.get("tool_name") != "Bash":
        return

    command = str((payload.get("tool_input") or {}).get("command") or "")
    if not command.strip():
        return

    if not _COMMIT_RE.search(command):
        return
    if _ALIAS_RE.search(command):
        return
    if _BYPASS_RE.search(command):
        # merge / revert / cherry-pick auto-commit; allowed.
        return

    reason_en = (
        "`git commit` blocked — dev terminals must commit through a project "
        "alias so the author is unambiguous.\n\n"
        "Use `git as-<alias> commit ...` instead. The alias is configured by "
        "`/sulde-add-team-member` or pre-set by `/sulde-init`.\n"
        "Bypass: set `enforcement.branch.commit_alias_required: false`."
    )
    reason_zh = (
        "`git commit` 已拦 — Dev 终端 commit 必须走项目 alias,保证 author 明确。\n\n"
        "改用 `git as-<alias> commit ...`(alias 由 `/sulde-add-team-member` 配置,"
        "或 `/sulde-init` 时预设)。\n"
        "Bypass:`enforcement.branch.commit_alias_required: false`。"
    )

    sulde_exit_or_warn(
        config,
        "medium",
        reason=reason_en,
        reason_i18n={"en": reason_en, "zh": reason_zh},
        hook_event="PreToolUse",
        tool_name="Bash",
        docs_section="424-check_git_commit_aliaspy",
    )


def _required(config: SuldeConfig) -> bool:
    raw = config.raw.get("enforcement", {}) if isinstance(config.raw, dict) else {}
    branch_cfg = (raw.get("branch") or {}) if isinstance(raw, dict) else {}
    if isinstance(branch_cfg, dict) and not bool(branch_cfg.get("commit_alias_required", True)):
        return False

    # Solo developer / single-person project support:
    # 若 .sulde-config.yaml 的 team: 段为空(无 alias 条目),跳过 alias 检查.
    # 多人项目(team 内有 ≥ 1 个真实 alias)继续强制 alias commit.
    team = config.raw.get("team") if isinstance(config.raw, dict) else None
    if not isinstance(team, list) or len(team) == 0:
        return False
    has_alias = any(
        isinstance(member, dict) and member.get("alias")
        for member in team
    )
    return has_alias

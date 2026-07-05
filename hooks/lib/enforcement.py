"""enforcement — uniform deny/warn pathway for every sulde check_*.py module.

Each check module decides whether a tool call violates policy, then calls
`sulde_exit_or_warn(...)` here. This module knows the protocol details
(JSON permissionDecision for Write, exit 2 + stderr for Bash) and the
enforcement-level matrix.

Behavior matrix (v2 protocol-compliant):

                       strict           balanced        lenient
  hard (Write)         JSON deny + 0    JSON deny + 0   stderr + JSON allow + 0
  medium (Bash)        stderr + exit 2  stderr + exit 2 stderr + exit 0
  soft (prompt/inject) stderr + exit 0  stderr + exit 0 stderr + exit 0

Grace period forces lenient regardless of config (S2 fix).
"""

from __future__ import annotations

import json
import sys
from typing import Literal, Mapping

from sulde_common import (
    SuldeConfig,
    effective_enforcement_level,
    get_lang,
    grace_days_remaining,
    is_in_grace_period,
)

Severity = Literal["hard", "medium", "soft"]

_DOCS_URL = "https://github.com/EthanReedLabs/sulde-cc/blob/main/docs/V0.2.0-DESIGN-v2.md"

_OVERRIDE_HINT = {
    "en": "Set `enforcement_level: lenient` in .sulde-config.yaml to downgrade to warning.",
    "zh": "在 .sulde-config.yaml 设 `enforcement_level: lenient` 可降级为警告。",
    "ja": ".sulde-config.yaml で `enforcement_level: lenient` に設定すると警告に降格します。",
}

_GRACE_BANNER = {
    "en": "sulde [grace: {days}d left → forced lenient]",
    "zh": "sulde [宽限期:剩 {days} 天 → 强制 lenient]",
    "ja": "sulde [猶予期間:残り {days} 日 → 強制 lenient]",
}

_SEVERITY_EMOJI = {"hard": "🛑", "medium": "⚠️", "soft": "ℹ️"}


def sulde_exit_or_warn(
    config: SuldeConfig,
    severity: Severity,
    reason: str,
    reason_i18n: Mapping[str, str] | None = None,
    hook_event: str | None = None,
    tool_name: str | None = None,
    docs_section: str | None = None,
) -> None:
    """Emit the appropriate protocol response and exit.

    This function NEVER returns — it always calls sys.exit().
    """
    lang = get_lang(config)
    localized = _localize(reason, reason_i18n, lang)
    level = effective_enforcement_level(config)

    grace_banner = ""
    if is_in_grace_period(config):
        days = grace_days_remaining(config)
        grace_banner = _GRACE_BANNER.get(lang, _GRACE_BANNER["en"]).format(days=days)

    banner = _format_stderr_banner(
        severity=severity,
        message=localized,
        hook_event=hook_event,
        tool_name=tool_name,
        lang=lang,
        docs_section=docs_section,
        grace_banner=grace_banner,
    )

    # Soft severity: stdout reminder (UserPromptSubmit / SessionStart context),
    # never blocks regardless of level.
    if severity == "soft":
        # stderr would be too noisy for soft prompts; route to stdout so Claude
        # picks it up as additional context.
        sys.stdout.write(localized + "\n")
        sys.exit(0)

    if severity == "medium":
        sys.stderr.write(banner)
        if level == "lenient":
            sys.exit(0)
        sys.exit(2)

    # severity == "hard" — Write / Edit path
    if level == "lenient":
        sys.stderr.write(banner)
        _emit_permission_decision("allow", localized, hook_event)
        sys.exit(0)

    # strict or balanced → block via JSON
    _emit_permission_decision("deny", localized, hook_event)
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _localize(default: str, table: Mapping[str, str] | None, lang: str) -> str:
    if table is None:
        return default
    return table.get(lang) or table.get("en") or default


def _emit_permission_decision(
    decision: Literal["allow", "deny"],
    reason: str,
    hook_event: str | None,
) -> None:
    payload = {
        "hookSpecificOutput": {
            "hookEventName": hook_event or "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _format_stderr_banner(
    *,
    severity: Severity,
    message: str,
    hook_event: str | None,
    tool_name: str | None,
    lang: str,
    docs_section: str | None,
    grace_banner: str,
) -> str:
    emoji = _SEVERITY_EMOJI.get(severity, "•")
    header = f"sulde ─ {hook_event or '?'} / {tool_name or '?'}"
    docs_line = _DOCS_URL + (("#" + docs_section) if docs_section else "")
    override = _OVERRIDE_HINT.get(lang, _OVERRIDE_HINT["en"])

    lines = ["", "╔═══ " + header + " ═══"]
    if grace_banner:
        lines.append("║ " + grace_banner)
    for chunk in message.splitlines() or [message]:
        lines.append("║ " + emoji + " " + chunk)
    lines.append("║ override: " + override)
    lines.append("║ docs:     " + docs_line)
    lines.append("╚" + "═" * 60)
    lines.append("")
    return "\n".join(lines)

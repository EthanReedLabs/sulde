"""check_subdir_cd — coordinator Bash guard.

Blocks `cd <frontend>/` because cd-ing into a frontend dir auto-injects
that frontend's CLAUDE.md (~17 KB) into context via SessionStart-like
re-evaluation. Across a long session this can waste 1+ MB of tokens.

Suggests absolute paths instead (Read / Grep / Bash all accept absolute
paths — there is no functional reason to cd).
"""

from __future__ import annotations

import re
from typing import Any

from enforcement import sulde_exit_or_warn
from sulde_common import SuldeConfig


def run(config: SuldeConfig, payload: dict[str, Any]) -> None:
    enabled = _resolve_enabled(config)
    if not enabled:
        return
    tool_name = payload.get("tool_name", "")
    if tool_name != "Bash":
        return

    command = str((payload.get("tool_input") or {}).get("command") or "")
    if not command.strip():
        return

    offender = _detect_cd_into_frontend(command, config)
    if offender is None:
        return

    reason_en = (
        f"Bash `cd {offender}` blocked — cd into a frontend dir re-injects its "
        "CLAUDE.md (~17 KB) every time the working dir changes; observed waste "
        "of 1+ MB of tokens per long session.\n\n"
        "Use absolute paths instead:\n"
        f"  ❌ cd {offender}/ && ls .ai-workspace/handoff/\n"
        f"  ✅ ls {offender}/.ai-workspace/handoff/\n"
        "(Read / Grep / Bash all accept absolute paths.)"
    )
    reason_zh = (
        f"Bash `cd {offender}` 已拦 — cd 到子端目录会让子端 CLAUDE.md(~17 KB)"
        "随工作目录变化反复注入 context;长 session 实测可浪费 1MB+ token。\n\n"
        "改用绝对路径:\n"
        f"  ❌ cd {offender}/ && ls .ai-workspace/handoff/\n"
        f"  ✅ ls {offender}/.ai-workspace/handoff/\n"
        "(Read / Grep / Bash 都支持绝对路径,功能不打折。)"
    )

    sulde_exit_or_warn(
        config,
        "medium",
        reason=reason_en,
        reason_i18n={"en": reason_en, "zh": reason_zh},
        hook_event="PreToolUse",
        tool_name=tool_name,
        docs_section="423-check_subdir_cdpy",
    )


# ─── helpers ────────────────────────────────────────────────────────────────

def _resolve_enabled(config: SuldeConfig) -> bool:
    raw = config.raw.get("enforcement", {}) if isinstance(config.raw, dict) else {}
    block_cfg = (raw.get("subdir_cd_block") or {}) if isinstance(raw, dict) else {}
    setting = block_cfg.get("enabled", "auto") if isinstance(block_cfg, dict) else "auto"
    if isinstance(setting, str) and setting.lower() == "auto":
        return config.role in ("coordinator", "both")
    return bool(setting)


def _detect_cd_into_frontend(command: str, config: SuldeConfig) -> str | None:
    names = [fe.name for fe in config.frontends if fe.name]
    paths = [str(fe.path) for fe in config.frontends if fe.path]
    if not names and not paths:
        return None

    # Patterns: standalone `cd <name>` OR `; cd <name>` OR `&& cd <name>` etc
    # Allow optional ./ prefix and trailing slash.
    name_re = "|".join(re.escape(n) for n in names) if names else None
    path_re = "|".join(re.escape(p.rstrip("/")) for p in paths) if paths else None
    parts = []
    if name_re:
        parts.append(rf"(?:\./)?(?:{name_re})/?")
    if path_re:
        parts.append(rf"(?:{path_re})/?")
    alt = "|".join(parts)
    pattern = re.compile(rf"(?:^|[&;|])\s*cd\s+({alt})(?:\s|$|/)")
    m = pattern.search(command)
    if not m:
        return None
    return m.group(1).rstrip("/")

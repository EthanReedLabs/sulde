"""Narrow native-authority escape hatch for a failed Codex Guardian runtime.

This classifier does not grant execution authority.  It only decides whether
an unavailable Sulde policy runtime may stay silent so Codex can apply its own
sandbox and human Allow/Deny flow.  Keep the surface exact and recovery-only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from command_template import git_execution_passthrough, split_command_template


_READ_ONLY_TOOLS = frozenset(
    {"read", "glob", "grep", "find", "view_image", "search", "webrun", "web.run", "web__run"}
)
_READ_ONLY_SULDE_MCP_TOOLS = frozenset(
    {
        f"mcp__sulde_kb__{action}"
        for action in (
            "kb_status",
            "kb_search",
            "kb_get",
            "kb_related",
            "memory_search",
            "memory_graph",
            "event_observe",
        )
    }
)
_SHELL_TOOLS = frozenset({"bash", "shell", "exec_command", "commandexecution"})
_SHELL_CONTROL = re.compile(r"[;&|<>`$()\r\n]")
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_CODEX_PLUGIN_COMMANDS = frozenset(
    {
        ("plugin", "list", "--json"),
        ("plugin", "remove", "sulde@sulde-local", "--json"),
    }
)


def _tokens(command: str) -> tuple[str, ...]:
    if not command or _SHELL_CONTROL.search(command):
        return ()
    try:
        return tuple(split_command_template(command))
    except ValueError:
        return ()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _trusted_runtime_script(path: Path, *, runtime_root: Path, launcher_home: Path) -> bool:
    if not path.is_absolute():
        return False
    resolved = path.resolve(strict=False)
    runtime_script = (runtime_root / "scripts" / "kb").resolve(strict=False)
    stable_bin = (launcher_home / "bin").resolve(strict=False)
    if resolved.parent == runtime_script or resolved.parent == stable_bin:
        return True
    artifact_root = (launcher_home / "artifacts").resolve(strict=False)
    return _is_under(resolved, artifact_root) and tuple(resolved.parts[-4:]) == (
        "runtime",
        "scripts",
        "kb",
        resolved.name,
    )


def _doctor_arguments(arguments: tuple[str, ...]) -> bool:
    if not arguments or arguments[0] != "doctor":
        return False
    provider_codex = False
    seen: set[str] = set()
    index = 1
    while index < len(arguments):
        flag = arguments[index]
        if flag in seen:
            return False
        seen.add(flag)
        if flag == "--scan":
            index += 1
            continue
        if flag not in {"--workspace", "--home", "--provider", "--session-id"}:
            return False
        if index + 1 >= len(arguments) or arguments[index + 1].startswith("--"):
            return False
        value = arguments[index + 1]
        if flag == "--provider":
            if value != "codex":
                return False
            provider_codex = True
        index += 2
    return provider_codex


def _skill_registration_arguments(
    arguments: tuple[str, ...],
    *,
    launcher_home: Path,
) -> bool:
    """Accept one authority-free Skill lifecycle record with exact bindings."""
    if len(arguments) < 3 or arguments[0] not in {"skill-start", "skill-end"}:
        return False
    if not _SAFE_IDENTIFIER.fullmatch(arguments[1]):
        return False
    allowed = {"--skill-path", "--contract", "--provider", "--session-id"}
    options: dict[str, str] = {}
    index = 2
    while index < len(arguments):
        flag = arguments[index]
        if flag not in allowed or flag in options or index + 1 >= len(arguments):
            return False
        value = arguments[index + 1]
        if not value or value.startswith("--"):
            return False
        options[flag] = value
        index += 2
    if set(options) != allowed or options["--provider"] != "codex":
        return False
    if not _SAFE_IDENTIFIER.fullmatch(options["--session-id"]):
        return False
    contract = Path(options["--contract"]).expanduser()
    if (
        not contract.is_absolute()
        or not contract.name.endswith(".json")
        or not _is_under(
            contract,
            launcher_home / "data" / "kb" / "intent" / "workspaces",
        )
    ):
        return False
    skill_path = Path(options["--skill-path"]).expanduser()
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    skill_roots = (
        launcher_home / "artifacts",
        codex_home / "plugins",
        codex_home / "skills",
    )
    return (
        skill_path.is_absolute()
        and skill_path.name == "SKILL.md"
        and any(_is_under(skill_path, root) for root in skill_roots)
    )


def _direct_recovery_command(
    tokens: tuple[str, ...],
    *,
    runtime_root: Path,
    launcher_home: Path,
) -> bool:
    if not tokens:
        return False
    executable = Path(tokens[0]).name.casefold()
    if executable in {"codex", "codex.exe"}:
        return tuple(tokens[1:]) in _CODEX_PLUGIN_COMMANDS

    script = Path(tokens[0]).expanduser()
    if executable in {"install-agents.sh", "install-agents.ps1"}:
        return (
            tuple(tokens[1:]) == ("--uninstall", "--provider", "codex")
            and _trusted_runtime_script(
                script,
                runtime_root=runtime_root,
                launcher_home=launcher_home,
            )
        )
    if executable in {"intent-guardian", "intent-guardian.py"}:
        arguments = tuple(tokens[1:])
        return (
            (
                _doctor_arguments(arguments)
                or _skill_registration_arguments(
                    arguments,
                    launcher_home=launcher_home,
                )
            )
            and _trusted_runtime_script(
                script,
                runtime_root=runtime_root,
                launcher_home=launcher_home,
            )
        )
    return False


def is_native_recovery_defer(
    command: str,
    *,
    runtime_root: Path,
    launcher_home: Path,
) -> bool:
    """Return true only for an exact Sulde recovery/diagnostic command."""
    tokens = _tokens(command)
    if _direct_recovery_command(
        tokens,
        runtime_root=runtime_root,
        launcher_home=launcher_home,
    ):
        return True
    if len(tokens) < 3 or Path(tokens[0]).name.casefold() not in {
        "python",
        "python3",
        "python.exe",
        "py",
    }:
        return False
    offset = 1
    if Path(tokens[0]).name.casefold() == "py" and tokens[1] == "-3":
        offset = 2
    return _direct_recovery_command(
        tokens[offset:],
        runtime_root=runtime_root,
        launcher_home=launcher_home,
    )


def native_recovery_read_action(
    command: str,
    *,
    runtime_root: Path,
    launcher_home: Path,
) -> str | None:
    """Map one exact existing control command to a sealed read capability."""
    tokens = _tokens(command)

    def classify(arguments: tuple[str, ...]) -> str | None:
        if not arguments:
            return None
        script = Path(arguments[0]).expanduser()
        if (
            script.name.casefold() in {"intent-guardian", "intent-guardian.py"}
            and _doctor_arguments(tuple(arguments[1:]))
            and _trusted_runtime_script(
                script,
                runtime_root=runtime_root,
                launcher_home=launcher_home,
            )
        ):
            return "doctor"
        return None

    direct = classify(tokens)
    if direct is not None:
        return direct
    if len(tokens) < 3 or Path(tokens[0]).name.casefold() not in {
        "python", "python3", "python.exe", "py",
    }:
        return None
    offset = 2 if Path(tokens[0]).name.casefold() == "py" and tokens[1] == "-3" else 1
    return classify(tokens[offset:])


def payload_requires_fail_closed(
    payload: dict[str, Any],
    *,
    runtime_root: Path,
    launcher_home: Path,
) -> bool:
    """Classify a failed policy call without widening material authority."""
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "").strip()
    normalized = tool_name.replace("-", "_").casefold()
    figma_passthrough = (
        normalized.startswith("mcp__figma__")
        or normalized.startswith("mcp__codex_apps__figma_")
    )
    if (
        normalized in _READ_ONLY_TOOLS
        or normalized in _READ_ONLY_SULDE_MCP_TOOLS
        or figma_passthrough
    ):
        return False
    if normalized not in _SHELL_TOOLS:
        return True
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return True
    command = str(tool_input.get("command") or tool_input.get("cmd") or "").strip()
    if git_execution_passthrough(command):
        return False
    tokens = _tokens(command)
    if not tokens:
        return True
    if Path(tokens[0]).name.casefold() in {"git", "git.exe"}:
        return False
    return not is_native_recovery_defer(
        command,
        runtime_root=runtime_root,
        launcher_home=launcher_home,
    )


def raw_payload_requires_fail_closed(
    raw_payload: bytes,
    *,
    runtime_root: Path,
    launcher_home: Path,
) -> bool:
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return True
    if not isinstance(payload, dict):
        return True
    return payload_requires_fail_closed(
        payload,
        runtime_root=runtime_root,
        launcher_home=launcher_home,
    )

"""Dependency-free recovery classifier kept with the static Codex adapter."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
from typing import Any


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


def _git_execution_passthrough(command: str) -> bool:
    """Dependency-free proof that every safe shell segment invokes Git."""
    candidate = re.sub(
        r"\s+2>\s*(?:/dev/null|NUL)\s*$",
        "",
        command,
        flags=re.IGNORECASE,
    )
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(candidate):
        character = candidate[index]
        if escaped:
            current.append(character)
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            current.append(character)
            escaped = True
            index += 1
            continue
        if quote:
            current.append(character)
            if character == quote:
                quote = ""
            elif quote == '"' and character == "`":
                return False
            elif (
                quote == '"'
                and character == "$"
                and index + 1 < len(candidate)
                and candidate[index + 1] in "({"
            ):
                return False
            index += 1
            continue
        if character in {"'", '"'}:
            current.append(character)
            quote = character
            index += 1
            continue
        separator_width = 0
        if character == "|":
            if index + 1 < len(candidate) and candidate[index + 1] == "|":
                return False
            separator_width = 1
        elif character == "&":
            if index + 1 >= len(candidate) or candidate[index + 1] != "&":
                return False
            separator_width = 2
        elif character in ";\n\r":
            separator_width = 1
        if separator_width:
            segment = "".join(current).strip()
            if not segment:
                return False
            segments.append(segment)
            current = []
            index += separator_width
            continue
        if character in "<>`":
            return False
        if (
            character == "$"
            and index + 1 < len(candidate)
            and candidate[index + 1] in "({"
        ):
            return False
        current.append(character)
        index += 1
    if quote or escaped:
        return False
    final = "".join(current).strip()
    if not final:
        return False
    segments.append(final)
    try:
        return all(
            bool(tokens := shlex.split(segment, posix=os.name != "nt"))
            and Path(tokens[0]).name.casefold() in {"git", "git.exe"}
            for segment in segments
        )
    except ValueError:
        return False


def _tokens(command: str) -> tuple[str, ...]:
    if not command or _SHELL_CONTROL.search(command):
        return ()
    try:
        return tuple(shlex.split(command, posix=os.name != "nt"))
    except ValueError:
        return ()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _trusted_script(path: Path, *, runtime_root: Path, launcher_home: Path) -> bool:
    if not path.is_absolute():
        return False
    resolved = path.resolve(strict=False)
    if resolved.parent in {
        (runtime_root / "scripts" / "kb").resolve(strict=False),
        (launcher_home / "bin").resolve(strict=False),
    }:
        return True
    return (
        _is_under(resolved, launcher_home / "artifacts")
        and len(resolved.parts) >= 4
        and tuple(resolved.parts[-4:-1]) == ("runtime", "scripts", "kb")
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
    return (
        skill_path.is_absolute()
        and skill_path.name == "SKILL.md"
        and any(
            _is_under(skill_path, root)
            for root in (
                launcher_home / "artifacts",
                codex_home / "plugins",
                codex_home / "skills",
            )
        )
    )


def _direct(
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
        return tuple(tokens[1:]) == ("--uninstall", "--provider", "codex") and _trusted_script(
            script, runtime_root=runtime_root, launcher_home=launcher_home
        )
    if executable in {"intent-guardian", "intent-guardian.py"}:
        arguments = tuple(tokens[1:])
        return (
            _doctor_arguments(arguments)
            or _skill_registration_arguments(arguments, launcher_home=launcher_home)
        ) and _trusted_script(
            script, runtime_root=runtime_root, launcher_home=launcher_home
        )
    return False


def _native_recovery(
    command: str,
    *,
    runtime_root: Path,
    launcher_home: Path,
) -> bool:
    tokens = _tokens(command)
    if _direct(tokens, runtime_root=runtime_root, launcher_home=launcher_home):
        return True
    if len(tokens) < 3 or Path(tokens[0]).name.casefold() not in {
        "python", "python3", "python.exe", "py"
    }:
        return False
    offset = 2 if Path(tokens[0]).name.casefold() == "py" and tokens[1] == "-3" else 1
    return _direct(
        tokens[offset:], runtime_root=runtime_root, launcher_home=launcher_home
    )


def payload_requires_fail_closed(
    payload: dict[str, Any],
    *,
    runtime_root: Path,
    launcher_home: Path,
) -> bool:
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
    if _git_execution_passthrough(command):
        return False
    tokens = _tokens(command)
    if not tokens:
        return True
    if Path(tokens[0]).name.casefold() in {"git", "git.exe"}:
        return False
    return not _native_recovery(
        command, runtime_root=runtime_root, launcher_home=launcher_home
    )

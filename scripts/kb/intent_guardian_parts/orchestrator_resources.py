"""Pure parser for Codex unified-exec nested tool calls."""

from __future__ import annotations

import re
from typing import Any


def _javascript_string(value: str) -> str | None:
    value = value.strip()
    if len(value) < 2 or value[0] != value[-1] or value[0] not in {"'", '"', "`"}:
        return None
    if value[0] == "`" and "${" in value:
        return None
    body = value[1:-1]
    try:
        return bytes(body, "utf-8").decode("unicode_escape")
    except UnicodeError:
        return None


def _javascript_code_mask(source: str) -> str:
    """Blank strings/comments while preserving offsets for a small JS parser."""
    masked = list(source)
    index = 0
    quote = ""
    while index < len(source):
        char = source[index]
        if quote:
            masked[index] = " "
            if char == "\\":
                if index + 1 < len(source):
                    masked[index + 1] = " "
                    index += 2
                    continue
            elif char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
            masked[index] = " "
            index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index + 2)
            end = len(source) if end < 0 else end
            for position in range(index, end):
                masked[position] = " "
            index = end
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = len(source) if end < 0 else end + 2
            for position in range(index, end):
                masked[position] = " "
            index = end
            continue
        index += 1
    return "".join(masked)


def _javascript_call_argument(source: str, open_paren: int) -> str | None:
    """Return one balanced call argument region from literal source."""
    depth = 1
    index = open_paren + 1
    quote = ""
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"', "`"}:
            quote = char
        elif source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline < 0 else newline
            continue
        elif source.startswith("/*", index):
            close = source.find("*/", index + 2)
            index = len(source) if close < 0 else close + 2
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[open_paren + 1 : index]
        index += 1
    return None


def _javascript_literal_at(source: str, index: int) -> str | None:
    while index < len(source) and source[index].isspace():
        index += 1
    if index >= len(source) or source[index] not in {"'", '"', "`"}:
        return None
    quote = source[index]
    end = index + 1
    while end < len(source):
        if source[end] == "\\":
            end += 2
            continue
        if source[end] == quote:
            return _javascript_string(source[index : end + 1])
        end += 1
    return None


def _javascript_object_string(argument: str, *names: str) -> str | None:
    masked = _javascript_code_mask(argument)
    alternatives = "|".join(re.escape(name) for name in names)
    match = re.search(rf"(?:^|[{{,])\s*(?:{alternatives})\s*:", masked)
    if match is None:
        return None
    return _javascript_literal_at(argument, match.end())


def unified_exec_nested_calls(source: str) -> tuple[list[dict[str, Any]], bool]:
    """Parse statically provable ``tools.*`` calls from Codex unified exec."""
    masked = _javascript_code_mask(source)
    calls: list[dict[str, Any]] = []
    unresolved = False
    for match in re.finditer(r"\btools\.([A-Za-z_$][\w$]*)\s*\(", masked):
        name = match.group(1)
        argument = _javascript_call_argument(source, match.end() - 1)
        if argument is None:
            unresolved = True
            continue
        lowered = name.lower()
        if lowered == "exec_command":
            command = _javascript_object_string(argument, "cmd", "command")
            workdir = _javascript_object_string(argument, "workdir", "cwd")
            if command is None:
                unresolved = True
                continue
            calls.append(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "cwd": workdir or "",
                }
            )
        elif lowered == "apply_patch":
            patch = _javascript_literal_at(argument, 0)
            if patch is None:
                unresolved = True
                continue
            calls.append(
                {
                    "tool_name": "apply_patch",
                    "tool_input": {"patch": patch},
                }
            )
        elif lowered in {
            "get_goal", "list_mcp_resource_templates", "list_mcp_resources",
            "read_mcp_resource", "update_goal", "update_plan", "view_image",
            "web__run",
        }:
            calls.append({"tool_name": "Read", "tool_input": {}})
        else:
            calls.append({"tool_name": name, "tool_input": {}})
    return calls, unresolved

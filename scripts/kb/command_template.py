"""Platform-aware parsing for subprocess command templates."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path


def _unquote_windows_argument(argument: str) -> str:
    if (
        len(argument) >= 2
        and argument[0] == argument[-1]
        and argument[0] in {'"', "'"}
    ):
        return argument[1:-1]
    return argument


def split_command_template(
    command_template: str, *, os_name: str | None = None, comments: bool = False
) -> list[str]:
    """Split a command template without applying POSIX escapes on Windows."""
    current_os = os.name if os_name is None else os_name
    if current_os != "nt":
        return shlex.split(command_template, comments=comments)
    return [
        _unquote_windows_argument(argument)
        for argument in shlex.split(command_template, comments=comments, posix=False)
    ]


def join_command_template(
    arguments: list[str], *, os_name: str | None = None
) -> str:
    """Render a command template for the current platform."""
    current_os = os.name if os_name is None else os_name
    if current_os == "nt":
        return subprocess.list2cmdline(arguments)
    return shlex.join(arguments)


def shell_wrapper_payload(command: str) -> str | None:
    """Return the command string executed by one exact ``sh -c`` wrapper.

    The wrapper must contain no outer shell composition and no positional
    arguments after the command string.  Those arguments can influence a
    second stage through ``$0``/``$1`` and therefore are not a lexical proof.
    """
    if "\n" in command or "\r" in command:
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if len(tokens) < 3:
        return None
    executable = Path(tokens[0]).name.lower()
    if executable not in {"bash", "dash", "ksh", "sh", "zsh"}:
        return None
    payload_index = -1
    for index, token in enumerate(tokens[1:], start=1):
        if not token.startswith("-") or token == "--":
            break
        if "c" in token[1:]:
            payload_index = index + 1
            break
    if payload_index < 0 or payload_index != len(tokens) - 1:
        return None
    return tokens[payload_index]


def split_single_heredoc(command: str) -> tuple[str, str] | None:
    """Split one structurally valid shell heredoc into header and body.

    The body is returned as data; the caller decides whether the selected
    executable consumes it as source code (``sh``, Python or Node).  Multiple
    heredocs, here-strings, command text after the terminator, substitutions in
    an unquoted delimiter, and malformed input intentionally remain unproved.
    """
    lines = command.splitlines()
    if len(lines) < 3:
        return None
    header = lines[0]
    quote = ""
    escaped = False
    marker_start = -1
    delimiter = ""
    delimiter_quoted = False
    strip_tabs = False
    index = 0
    while index < len(header):
        character = header[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote:
            if character == quote:
                quote = ""
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if header.startswith("<<<", index):
            return None
        if not header.startswith("<<", index):
            index += 1
            continue
        if marker_start >= 0:
            return None
        marker_start = index
        index += 2
        if index < len(header) and header[index] == "-":
            strip_tabs = True
            index += 1
        while index < len(header) and header[index].isspace():
            index += 1
        delimiter_quote = ""
        if index < len(header) and header[index] in {"'", '"'}:
            delimiter_quote = header[index]
            delimiter_quoted = True
            index += 1
        start = index
        while index < len(header):
            current = header[index]
            if delimiter_quote:
                if current == delimiter_quote:
                    break
            elif current.isspace() or current in ";&|<>":
                break
            index += 1
        delimiter = header[start:index]
        if not delimiter or any(value in delimiter for value in ("$", "`", "\\")):
            return None
        if delimiter_quote:
            if index >= len(header) or header[index] != delimiter_quote:
                return None
            index += 1
        marker_end = index
        while marker_end < len(header) and header[marker_end].isspace():
            marker_end += 1
        header = (header[:marker_start] + header[marker_end:]).strip()
        break
    if marker_start < 0 or not header:
        return None
    if has_unquoted_shell_control(header):
        return None
    terminator = -1
    for line_index, line in enumerate(lines[1:], start=1):
        candidate = line.lstrip("\t") if strip_tabs else line
        if candidate == delimiter:
            terminator = line_index
            break
    if terminator < 0 or any(line.strip() for line in lines[terminator + 1 :]):
        return None
    body_lines = lines[1:terminator]
    if strip_tabs:
        body_lines = [line.lstrip("\t") for line in body_lines]
    body = "\n".join(body_lines) + ("\n" if body_lines else "")
    if not delimiter_quoted and any(character in body for character in ("$", "`", "\\")):
        # An unquoted delimiter enables parameter/command/arithmetic expansion
        # and backslash processing before the selected executable sees stdin.
        # Without a shell AST, the body cannot be proven to be inert data.
        return None
    return header, body


def has_unquoted_shell_control(command: str) -> bool:
    """Return whether shell composition appears outside quoted data."""
    quote = ""
    escaped = False
    for index, character in enumerate(command):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = ""
            elif quote == '"' and character == "`":
                return True
            elif (
                quote == '"'
                and character == "$"
                and index + 1 < len(command)
                and command[index + 1] in "({"
            ):
                return True
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character in ";&|<>`\n\r":
            return True
        if character == "$" and index + 1 < len(command) and command[index + 1] in "({":
            return True
    return bool(quote)


def read_pipeline_segments(command: str) -> list[str] | None:
    """Split safe read composition, rejecting mutation-capable shell syntax.

    Pipes, sequential separators and ``&&`` can be classified recursively.
    Redirection, substitution, backgrounding and ``||`` remain unprovable.
    An empty list means the command is not composed.
    """
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        character = command[index]
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
                return None
            elif (
                quote == '"'
                and character == "$"
                and index + 1 < len(command)
                and command[index + 1] in "({"
            ):
                return None
            index += 1
            continue
        if character in {"'", '"'}:
            current.append(character)
            quote = character
            index += 1
            continue
        separator_width = 0
        if character == "|":
            if index + 1 < len(command) and command[index + 1] == "|":
                return None
            separator_width = 1
        elif character == "&":
            if index + 1 >= len(command) or command[index + 1] != "&":
                return None
            separator_width = 2
        elif character in ";\n\r":
            separator_width = 1
        if separator_width:
            segment = "".join(current).strip()
            if not segment:
                return None
            segments.append(segment)
            current = []
            index += separator_width
            continue
        if character in "<>`":
            return None
        if character == "$" and index + 1 < len(command) and command[index + 1] in "({":
            return None
        current.append(character)
        index += 1
    if quote or escaped:
        return None
    final = "".join(current).strip()
    if not final:
        return None
    segments.append(final)
    return segments if len(segments) > 1 else []


def execution_domain_commands(command: str) -> list[tuple[str, str]] | None:
    """Return shell segments paired with their top-level executable domain.

    This intentionally inspects only the executable selected by the host.  It
    does not parse or classify subcommands and arguments.  ``None`` means the
    shell composition is not safe to split structurally.
    """
    candidate = re.sub(
        r"\s+2>\s*(?:/dev/null|NUL)\s*$",
        "",
        command,
        flags=re.IGNORECASE,
    )
    segments = read_pipeline_segments(candidate)
    if segments is None:
        return None
    candidates = segments or [candidate]
    domains: list[tuple[str, str]] = []
    for segment in candidates:
        if has_unquoted_shell_control(segment):
            return None
        try:
            tokens = split_command_template(segment)
        except ValueError:
            return None
        if not tokens:
            return None
        domains.append((Path(tokens[0]).name.lower(), segment))
    return domains


def git_execution_passthrough(command: str) -> bool:
    """Whether every executable segment belongs to Git's execution domain."""
    domains = execution_domain_commands(command)
    return bool(domains) and all(domain == "git" for domain, _ in domains)


def is_read_only_command(command: str) -> bool:
    """Conservatively prove that every command segment is read-only."""
    candidate = re.sub(
        r"\s+2>\s*(?:/dev/null|NUL)\s*$",
        "",
        command,
        flags=re.IGNORECASE,
    )
    pipeline = read_pipeline_segments(candidate)
    if pipeline is None:
        return False
    if pipeline:
        return all(is_read_only_command(segment) for segment in pipeline)
    if has_unquoted_shell_control(candidate):
        return False
    try:
        tokens = split_command_template(candidate)
    except ValueError:
        return False
    if not tokens:
        return False
    executable = Path(tokens[0]).name.lower()
    if executable in {
        "cat",
        "find",
        "grep",
        "head",
        "jq",
        "ls",
        "md5",
        "pwd",
        "realpath",
        "rg",
        "shasum",
        "sha256sum",
        "sort",
        "stat",
        "tail",
        "tree",
        "wc",
        "which",
    }:
        return True
    if executable == "sed":
        return not any(token == "-i" or token.startswith("-i") for token in tokens[1:])
    if executable in {"codex", "codex.exe"}:
        lowered_tokens = [token.lower() for token in tokens[1:]]
        if lowered_tokens in (["--help"], ["-h"], ["--version"], ["-v"]):
            return True
        if not lowered_tokens or lowered_tokens[0] != "plugin":
            return False
        if len(lowered_tokens) == 1 or lowered_tokens[1] in {"--help", "-h"}:
            return True
        if lowered_tokens[1] == "list":
            return True
        if lowered_tokens[1] == "marketplace":
            return len(lowered_tokens) == 2 or lowered_tokens[2] in {
                "list",
                "--help",
                "-h",
            }
        return False
    if executable == "kb-index" and len(tokens) > 1:
        return tokens[1].lower() in {
            "search",
            "status",
            "mem-graph",
            "mem-search",
            "mem-status",
        }
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable):
        return (
            len(tokens) > 2
            and tokens[1] == "-m"
            and tokens[2] in {"pytest", "unittest", "py_compile"}
        )
    if executable in {"pytest", "py.test"}:
        return True
    return False


def literal_git_add_arguments(arguments: list[str]) -> list[str] | None:
    """Return validated operands from the argument tail of ``git add``.

    This is a lexical proof only.  Callers must still prove that every path is
    a regular file in the intended worktree.  ``None`` means the invocation
    needs repository-level treatment and must not receive the file exception.
    """
    if len(arguments) < 2 or arguments[0] != "--":
        return None
    paths: list[str] = []
    for operand in arguments[1:]:
        candidate = str(operand)
        path = Path(candidate)
        raw_parts = candidate.replace("\\", "/").split("/")
        if (
            not candidate
            or candidate in {".", ".."}
            or candidate.startswith(("-", ":", "~"))
            or path.is_absolute()
            or any(character in candidate for character in "\0\n\r*?[]{}")
            or any(
                not part
                or part in {".", ".."}
                or part.casefold() in {".git", ".codex-agent"}
                for part in raw_parts
            )
        ):
            return None
        normalized = path.as_posix()
        if normalized not in paths:
            paths.append(normalized)
    return paths or None


def literal_git_add_paths(command: str) -> list[str] | None:
    """Return the literal operands of one narrow ``git add --`` invocation."""
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if (
        len(tokens) < 4
        or Path(tokens[0]).name.lower() != "git"
        or tokens[1].lower() != "add"
    ):
        return None
    return literal_git_add_arguments(tokens[2:])


def literal_git_worktree_lifecycle_action(
    command: str,
) -> dict[str, object] | None:
    """Parse one exact, non-authorizing ``git worktree add`` shape.

    ``attach_existing`` restores an existing local task branch into an absent
    worktree. ``create_branch`` creates one new local task branch from an
    existing local base. Filesystem identity and branch state are deliberately
    left to the typed resource adapter.
    """
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if not tokens or Path(tokens[0]).name.lower() != "git":
        return None
    index = 1
    repository = ""
    if index < len(tokens) and tokens[index] == "-C":
        if index + 1 >= len(tokens):
            return None
        repository = tokens[index + 1]
        if not _literal_worktree_path(repository, allow_absolute=True):
            return None
        index += 2
    if tokens[index:index + 2] != ["worktree", "add"]:
        return None
    arguments = tokens[index + 2:]
    if len(arguments) == 2:
        target, branch = arguments
        if not _literal_worktree_path(target, allow_absolute=True):
            return None
        if not _literal_local_branch(branch):
            return None
        return {
            "schema": "sulde-git-worktree-lifecycle-classification-v1",
            "operation": "attach_existing",
            "repository": repository,
            "target": target,
            "branch": branch,
            "base": branch,
            "effect": "local_write",
            "execution_authorized": False,
        }
    if len(arguments) == 4 and arguments[0] == "-b":
        branch, target, base = arguments[1:]
        if not _literal_local_branch(branch) or not _literal_local_branch(base):
            return None
        if not _literal_worktree_path(target, allow_absolute=True):
            return None
        return {
            "schema": "sulde-git-worktree-lifecycle-classification-v1",
            "operation": "create_branch",
            "repository": repository,
            "target": target,
            "branch": branch,
            "base": base,
            "effect": "local_write",
            "execution_authorized": False,
        }
    return None


def _literal_worktree_path(value: str, *, allow_absolute: bool) -> bool:
    candidate = str(value)
    normalized = candidate.replace("\\", "/")
    parts = normalized.split("/")
    if Path(candidate).is_absolute() and normalized.startswith("/"):
        parts = parts[1:]
    return bool(
        candidate
        and not candidate.startswith(("-", "~"))
        and (allow_absolute or not Path(candidate).is_absolute())
        and not any(character in candidate for character in "\0\n\r*?[]{}")
        and parts
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _literal_local_branch(value: str) -> bool:
    candidate = str(value)
    return bool(
        candidate
        and not candidate.startswith(("-", "/", "~", "refs/"))
        and not candidate.endswith(("/", ".", ".lock"))
        and ".." not in candidate
        and "@{" not in candidate
        and "//" not in candidate
        and not any(character in candidate for character in "\0\n\r ~^:?*[\\")
    )


def default_llm_command() -> str:
    """Route prompts through Sulde's host-neutral LLM runtime port."""
    runtime = Path(__file__).with_name("llm-runtime.py")
    return join_command_template([sys.executable, str(runtime), "{prompt}"])


def literal_git_resource_action(command: str) -> dict[str, object] | None:
    """Parse one finite Git resource action without granting execution.

    The returned plain-JSON classification is intentionally non-authorizing.
    Repository identity, current state, HumanGrantV2 and dispatch bindings are
    added by resource_adapters after filesystem classification.
    """
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if not tokens or Path(tokens[0]).name.lower() != "git":
        return None
    index = 1
    repository = ""
    if index < len(tokens) and tokens[index] == "-C":
        if index + 1 >= len(tokens):
            return None
        repository = tokens[index + 1]
        if (
            not repository
            or repository.startswith("-")
            or any(part == ".." for part in Path(repository).parts)
            or any(character in repository for character in "\x00\n\r*?[]{}")
        ):
            return None
        index += 2
    if index >= len(tokens) or tokens[index].startswith("-"):
        return None
    action = tokens[index].lower()
    arguments = tokens[index + 1 :]
    if action == "add":
        paths = literal_git_add_arguments(arguments)
        if paths is None:
            return None
        return {
            "schema": "sulde-git-resource-classification-v1",
            "action": action,
            "repository": repository,
            "arguments": paths,
            "effect": "local_write",
            "execution_authorized": False,
        }
    if action == "commit":
        if (
            len(arguments) != 2
            or arguments[0] not in {"-m", "--message"}
            or not arguments[1]
            or any(character in arguments[1] for character in "\x00\n\r")
        ):
            return None
        return {
            "schema": "sulde-git-resource-classification-v1",
            "action": action,
            "repository": repository,
            "arguments": [arguments[1]],
            "effect": "local_write",
            "execution_authorized": False,
        }
    if action == "merge":
        if (
            len(arguments) != 4
            or arguments[:2] != ["--no-ff", "-m"]
            or not arguments[2]
            or any(character in arguments[2] for character in "\x00\n\r")
            or not arguments[3]
            or arguments[3].startswith("-")
            or ".." in arguments[3]
            or any(character in arguments[3] for character in "\x00\n\r*?[]{}")
        ):
            return None
        return {
            "schema": "sulde-git-resource-classification-v1",
            "action": action,
            "repository": repository,
            "arguments": [arguments[2], arguments[3]],
            "effect": "local_write",
            "execution_authorized": False,
        }
    if action in {"status", "diff", "rev-parse", "show"}:
        if any(
            not value
            or "\x00" in value
            or value in {
                "--output", "--exec", "--ext-diff", "--textconv", "--no-index",
                "--pathspec-from-file", "--pathspec-file-nul",
            }
            or value.startswith("--output=")
            or any(part == ".." for part in Path(value).parts)
            for value in arguments
        ):
            return None
        return {
            "schema": "sulde-git-resource-classification-v1",
            "action": action,
            "repository": repository,
            "arguments": arguments,
            "effect": "read",
            "execution_authorized": False,
        }
    return None

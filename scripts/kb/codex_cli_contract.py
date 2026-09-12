"""Audited CLI protocol and installation-bound executable identity."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple


# Discovery is permitted only at the installation boundary. Managed execution
# uses the verified deployment descriptor, never this name or a PATH lookup.
DEFAULT_CODEX_EXECUTABLE = "codex"
NATIVE_AUTHORITY_SPEC_VERSION = 2
AUDITED_CODEX_VERSION = "codex-cli 0.153.4"
CODEX_PATH_ALIAS_PERMISSION_WARNING = (
    "WARNING: proceeding, even though we could not create PATH aliases: "
    "Operation not permitted (os error 1)\n"
)

_UNSTABLE_TERMINAL_ENVIRONMENT = (
    "COLORTERM",
    "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION",
)
_FIXED_NO_COLOR_ENVIRONMENT = {
    "TERM": "dumb",
    "NO_COLOR": "1",
    "CLICOLOR": "0",
    "CLICOLOR_FORCE": "0",
    "FORCE_COLOR": "0",
}


class CodexCliContractError(ValueError):
    """A Codex identity/help observation cannot enter sealed authority."""


def bound_codex_executable(authority: Mapping[str, object]) -> Path:
    """Verify a canonical, content-bound path without discovering another CLI.

    This checks an executable binding, not the authority of the surrounding
    descriptor. The runtime must verify its envelope, generation and digest
    before using this result. Installation binds the resolved target so later
    PATH or package-manager alias changes cannot select a different program.
    """
    if not isinstance(authority, Mapping):
        raise CodexCliContractError("installed Codex executable binding is invalid")
    value = authority.get("production_codex_executable")
    expected = authority.get("codex_executable_sha256")
    if (not isinstance(value, str) or not value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or not isinstance(expected, str) or len(expected) != 64
            or any(char not in "0123456789abcdef" for char in expected)):
        raise CodexCliContractError("installed Codex executable binding is invalid")
    path = Path(value)
    if (not path.is_absolute() or str(path) != value
            or str(Path(os.path.abspath(path))) != value
            or authority.get("production_codex_resolved_executable") != value):
        raise CodexCliContractError("installed Codex executable path is not canonical")
    try:
        if path.resolve(strict=True) != path or not path.is_file():
            raise CodexCliContractError("installed Codex executable target drifted")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, RuntimeError) as error:
        raise CodexCliContractError("installed Codex executable is unavailable") from error
    if actual != expected:
        raise CodexCliContractError("installed Codex executable bytes drifted")
    return path


class CodexProbeSpec(NamedTuple):
    """Shared non-interactive boundary for Codex identity/help probes."""

    environment: dict[str, str]
    stdin: str


def codex_probe_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Return a non-interactive, no-color probe environment without mutation."""
    normalized = dict(environment)
    for variable in _UNSTABLE_TERMINAL_ENVIRONMENT:
        normalized.pop(variable, None)
    normalized.update(_FIXED_NO_COLOR_ENVIRONMENT)
    return normalized


def codex_probe_spec(environment: Mapping[str, str]) -> CodexProbeSpec:
    """Fix both the probe environment and an immediate stdin EOF."""
    return CodexProbeSpec(codex_probe_environment(environment), "")


def canonicalize_codex_help(stdout: str, stderr: str) -> bytes:
    """Return exact help stdout after accepting only one known diagnostic."""
    if any(
        character != "\n"
        and (ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F)
        for character in stdout
    ):
        raise CodexCliContractError(
            "Codex help stdout contains a disallowed ASCII/C1 control character"
        )
    if stderr not in {"", CODEX_PATH_ALIAS_PERMISSION_WARNING}:
        raise CodexCliContractError("Codex help stderr contains an unknown diagnostic")
    try:
        return stdout.encode("utf-8", "strict")
    except UnicodeError as error:
        raise CodexCliContractError("Codex help stdout is not canonical UTF-8") from error


def canonical_codex_help_observation(
    probes: Sequence[tuple[int, str, str]],
) -> tuple[tuple[bytes, bytes, bytes], str]:
    """Canonicalize exactly three successful help probes and hash their bytes."""
    if len(probes) != 3:
        raise CodexCliContractError("Codex help observation must contain three probes")
    canonical = []
    for returncode, stdout, stderr in probes:
        if returncode != 0:
            raise CodexCliContractError("Codex help probe did not exit successfully")
        canonical.append(canonicalize_codex_help(stdout, stderr))
    surfaces = (canonical[0], canonical[1], canonical[2])
    digest = hashlib.sha256(b"\0".join(surfaces)).hexdigest()
    return surfaces, digest


def successful_version_identity(returncode: int, stdout: str) -> str | None:
    """Return the stable stdout identity of a successful version command.

    Diagnostics are deliberately not accepted here. Executable identity is
    bound separately, while stderr remains available to callers for reporting.
    """
    if returncode != 0:
        return None
    if stdout.endswith("\r\n"):
        return stdout[:-2]
    if stdout.endswith("\n"):
        return stdout[:-1]
    return stdout

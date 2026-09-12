#!/usr/bin/env python3
"""Digest-bound protocol and native profile probe leaf for Codex.

The protocol builders remain pure.  ``execute_native_profile_probe`` is the one
audited executable edge: it performs first-write fault injection under macOS
Seatbelt and durably records what the OS, rather than a mock, observed.
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from types import MappingProxyType
from typing import Any


REQUEST_SCHEMA = "sulde-native-broker-request-v1"
PROBE_PLAN_SCHEMA = "sulde-native-profile-probe-plan-v2"
PROBE_RECEIPT_SCHEMA = "sulde-native-profile-probe-receipt-v2"
PROVIDER_RECEIPT_SCHEMA = "sulde-native-provider-receipt-v1"
LAUNCH_PLAN_SCHEMA = "sulde-native-provider-launch-plan-v1"
STDERR_BINDING_SCHEMA = "sulde-native-stderr-binding-v1"
NATIVE_SANDBOX_EXECUTABLE = "/usr/bin/sandbox-exec"
BROKER_PROTOCOL_SPEC_VERSION = 2

MAX_PATH_UTF8_BYTES = 4096
MAX_STDERR_RAW_BYTES = 1024 * 1024
MAX_PROTOCOL_JSON_BYTES = 2 * 1024 * 1024
MAX_HOOK_JSON_BYTES = 1024 * 1024
DIAGNOSTIC_STREAM_TARGETS = frozenset(
    {"/dev/stdout", "/dev/stderr", "/dev/fd/1", "/dev/fd/2"}
)

_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CODEX_VERSION = re.compile(r"codex-cli [0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?\Z")
_RFC3339_UTC_SECONDS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")

_FROZEN_FIELDS = {
    "task_id",
    "base_commit",
    "task_definition_sha256",
    "brief_sha256",
    "worktree_canonical_path",
    "git_common_dir_canonical_path",
    "owned_paths",
    "report_relative_path",
    "model_reasoning_effort",
    "codex_executable",
    "codex_version",
    "codex_executable_sha256",
    "broker_generation",
    "broker_sha256",
    "provider_generation",
    "permission_profile_name",
    "permission_profile_bytes_sha256",
    "permission_profile_spec_sha256",
    "installed_descriptor_sha256",
    "runtime_generation",
    "runtime_tree_sha256",
    "agent_runtime_sha256",
    "nonce",
}

_REQUEST_FIELDS = _FROZEN_FIELDS | {
    "schema",
    "task_identity_sha256",
    "worktree_identity_sha256",
    "owned_paths_sha256",
    "codex_identity_sha256",
    "broker_identity_sha256",
    "permission_profile_identity_sha256",
    "coordinator_delivery_projection_sha256",
    "external_authority_required",
    "execution_authorized",
    "request_sha256",
}

_PUBLIC_STATE_FIELDS = {
    "coordinator_delivery_projection_sha256",
    "external_authority_required",
    "execution_authorized",
}

_BINDING_FIELDS = {
    "request_sha256",
    "permission_profile_name",
    "permission_profile_bytes_sha256",
    "broker_generation",
    "broker_sha256",
    "provider_generation",
    "codex_executable",
    "codex_version",
    "codex_executable_sha256",
    "codex_identity_sha256",
    "installed_descriptor_sha256",
    "runtime_generation",
    "runtime_tree_sha256",
    "agent_runtime_sha256",
    "permission_profile_spec_sha256",
} | _PUBLIC_STATE_FIELDS


class ProtocolError(ValueError):
    """The supplied value is not an exact instance of the frozen protocol."""


class UnsupportedGitLayout(ProtocolError):
    """The workspace cannot be represented by the audited Codex profile."""


def is_bounded_diagnostic_stream_target(value: Any) -> bool:
    """Recognize only the four standard stream device spellings."""
    return type(value) is str and value in DIAGNOSTIC_STREAM_TARGETS


def _ensure_plain(value: Any, *, label: str = "value", active: set[int] | None = None) -> None:
    """Reject non-plain JSON values before invoking any value-level protocol."""

    value_type = type(value)
    if value is None or value_type in (str, int, bool):
        return
    if value_type not in (dict, list):
        raise ProtocolError(f"{label} must contain only exact plain-JSON types")
    if active is None:
        active = set()
    marker = id(value)
    if marker in active:
        raise ProtocolError(f"{label} must not contain a cycle")
    active.add(marker)
    try:
        if value_type is list:
            for index, item in enumerate(value):
                _ensure_plain(item, label=f"{label}[{index}]", active=active)
        else:
            for key, item in value.items():
                if type(key) is not str:
                    raise ProtocolError(f"{label} keys must be exact JSON strings")
                _ensure_plain(item, label=f"{label}.{key}", active=active)
    finally:
        active.remove(marker)


def canonical_json_bytes(value: Any) -> bytes:
    """Return the sole canonical JSON encoding accepted by this protocol."""

    _ensure_plain(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProtocolError("value is not canonical UTF-8 JSON") from exc
    if len(encoded) > MAX_PROTOCOL_JSON_BYTES:
        raise ProtocolError("protocol JSON exceeds the fixed byte-size bound")
    return encoded


def load_plain_json(raw: Any) -> Any:
    """Parse strict UTF-8 JSON, rejecting duplicate keys and non-integer numbers."""

    if type(raw) is bytes:
        if len(raw) > MAX_PROTOCOL_JSON_BYTES:
            raise ProtocolError("protocol JSON exceeds the fixed byte-size bound")
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeError as exc:
            raise ProtocolError("JSON document must be valid UTF-8") from exc
    elif type(raw) is str:
        text = raw
        try:
            encoded_size = len(text.encode("utf-8", "strict"))
        except UnicodeError as exc:
            raise ProtocolError("JSON document must be valid UTF-8") from exc
        if encoded_size > MAX_PROTOCOL_JSON_BYTES:
            raise ProtocolError("protocol JSON exceeds the fixed byte-size bound")
    else:
        raise ProtocolError("JSON document must be an exact bytes or string value")

    def reject_float(_value: str) -> Any:
        raise ProtocolError("floating-point JSON numbers are not accepted")

    def reject_constant(_value: str) -> Any:
        raise ProtocolError("non-finite JSON numbers are not accepted")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolError("duplicate JSON object field")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except ProtocolError:
        raise
    except (json.JSONDecodeError, UnicodeError, RecursionError) as exc:
        raise ProtocolError("invalid plain JSON document") from exc
    _ensure_plain(value, label="JSON document")
    return value


def _exact_dict(value: Any, fields: set[str], *, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolError(f"{label} must be an exact JSON object")
    _ensure_plain(value, label=label)
    if set(value) != fields:
        raise ProtocolError(f"{label} fields do not match the protocol schema")
    return value


def _text(value: Any, *, label: str, pattern: re.Pattern[str] | None = None) -> str:
    if type(value) is not str or not value:
        raise ProtocolError(f"{label} must be a non-empty exact string")
    if "\x00" in value:
        raise ProtocolError(f"{label} must not contain NUL")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise ProtocolError(f"{label} has an invalid canonical form")
    return value


def _boolean(value: Any, *, label: str) -> bool:
    if type(value) is not bool:
        raise ProtocolError(f"{label} must be an exact JSON boolean")
    return value


def _integer(value: Any, *, label: str, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError(f"{label} must be an exact integer in range")
    return value


def _digest(value: Any, *, label: str) -> str:
    return _text(value, label=label, pattern=_HEX_64)


def _evidence_digest(value: Any, *, label: str) -> str:
    digest = _digest(value, label=label)
    if len(set(digest)) == 1:
        raise ProtocolError(f"{label} must not be a placeholder-only digest")
    return digest


def _run_id(value: Any, *, label: str) -> str:
    run_id = _text(value, label=label, pattern=_IDENTIFIER)
    if run_id.casefold() in {"none", "placeholder", "todo", "unknown"}:
        raise ProtocolError(f"{label} must not be a placeholder-only identifier")
    return run_id


_ALTERNATE_SEPARATORS = {"\u2044", "\u2215", "\u29f8", "\ufe68", "\uff0f", "\uff3c"}
_PATHSPEC_MAGIC = {"*", "?", "[", "]"}


def _path_text(value: Any, *, label: str) -> str:
    path = _text(value, label=label)
    try:
        encoded_length = len(path.encode("utf-8", "strict"))
    except UnicodeError as exc:
        raise ProtocolError(f"{label} must be valid UTF-8") from exc
    if encoded_length > MAX_PATH_UTF8_BYTES:
        raise ProtocolError(f"{label} exceeds the fixed byte-size bound")
    if unicodedata.normalize("NFKC", path) != path:
        raise ProtocolError(f"{label} must be NFKC-stable before path checks")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in path):
        raise ProtocolError(f"{label} must not contain control characters")
    if any(character in _ALTERNATE_SEPARATORS for character in path):
        raise ProtocolError(f"{label} must not contain alternate separators")
    return path


def _canonical_absolute(value: Any, *, label: str) -> str:
    path = _path_text(value, label=label)
    if not path.startswith("/") or "\\" in path:
        raise ProtocolError(f"{label} must be an absolute canonical POSIX path")
    parts = path.split("/")
    if len(parts) < 2 or any(part in ("", ".", "..") for part in parts[1:]):
        raise ProtocolError(f"{label} must be an absolute canonical POSIX path")
    if any(token in path for token in _PATHSPEC_MAGIC) or any(
        part.startswith((":", "!", "^")) for part in parts[1:]
    ):
        raise ProtocolError(f"{label} must not contain glob or pathspec magic")
    return path


def _canonical_relative(value: Any, *, label: str) -> str:
    path = _path_text(value, label=label)
    if path.startswith("/") or "\\" in path:
        raise ProtocolError(f"{label} must be a canonical relative POSIX exact path")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ProtocolError(f"{label} must be a canonical relative POSIX exact path")
    if any(token in path for token in _PATHSPEC_MAGIC) or any(
        part.startswith((":", "!", "^")) for part in parts
    ):
        raise ProtocolError(f"{label} must not contain glob or pathspec magic")
    return path


def _owned_paths(value: Any) -> list[str]:
    if type(value) is not list or not value:
        raise ProtocolError("owned_paths must be a non-empty exact JSON array")
    paths: list[str] = []
    collision_keys: set[str] = set()
    for index, item in enumerate(value):
        path = _canonical_relative(item, label=f"owned_paths[{index}]")
        key = unicodedata.normalize("NFKC", path).casefold()
        if key in collision_keys:
            raise ProtocolError("owned_paths contain a duplicate or NFKC/casefold collision")
        collision_keys.add(key)
        paths.append(path)
    return paths


def render_permission_profile_arguments(
    owned_paths: Any,
    *,
    profile_name: Any = "sulde-owned-paths",
) -> list[str]:
    """Render the only Codex permission profile accepted by this runtime.

    Codex 0.149 resolves ``:workspace_roots`` entries relative to the lexical
    workspace.  The workspace-wide read grant already covers a full clone's
    ``.git`` directory, so absolute traversal/common-dir roots are both
    unnecessary and rejected by the real parser.
    """
    valid_name = _text(
        profile_name,
        label="permission_profile_name",
        pattern=_IDENTIFIER,
    )
    paths = _owned_paths(owned_paths)
    workspace_rules = ['"."="read"'] + [
        json.dumps(path, ensure_ascii=False) + '="write"' for path in paths
    ]
    profile = (
        '{filesystem={":minimal"="read",":tmpdir"="deny",'
        '":slash_tmp"="deny",":workspace_roots"={'
        + ",".join(workspace_rules)
        + '}},network={enabled=false}}'
    )
    return [
        "-c",
        "default_permissions=" + json.dumps(valid_name, ensure_ascii=True),
        "-c",
        "permissions." + valid_name + "=" + profile,
    ]


def permission_profile_bytes(
    owned_paths: Any,
    *,
    worktree: Any,
    profile_name: Any = "sulde-owned-paths",
) -> bytes:
    """Return the exact raw Seatbelt bytes enforced around provider commands."""
    _text(profile_name, label="permission_profile_name", pattern=_IDENTIFIER)
    return render_native_command_profile(worktree, owned_paths).encode(
        "utf-8", "strict"
    )


_FULL_CLONE_ACTION = (
    "coordinator must create a full clone with a real .git directory inside "
    "the lexical workspace (or implement an equally isolated supported layout)"
)


def validate_supported_git_layout(
    worktree: Any,
    git_common_dir: Any,
    *,
    owned_paths: Any | None = None,
) -> tuple[str, str]:
    """Fail closed unless paths describe one physical, non-symlink full clone."""
    lexical_worktree = _canonical_absolute(
        worktree, label="worktree_canonical_path"
    )
    lexical_common = _canonical_absolute(
        git_common_dir, label="git_common_dir_canonical_path"
    )
    expected_common = lexical_worktree + "/.git"
    if lexical_common != expected_common:
        raise UnsupportedGitLayout(
            "unsupported Codex Git layout: linked worktree or external Git "
            f"common-dir; {_FULL_CLONE_ACTION}"
        )
    worktree_path = Path(lexical_worktree)
    common_path = Path(lexical_common)
    try:
        worktree_metadata = worktree_path.lstat()
        common_metadata = common_path.lstat()
        resolved_worktree = worktree_path.resolve(strict=True)
        resolved_common = common_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise UnsupportedGitLayout(
            f"unsupported Codex Git layout: workspace or .git is unavailable; "
            f"{_FULL_CLONE_ACTION}"
        ) from exc
    if (
        not stat.S_ISDIR(worktree_metadata.st_mode)
        or stat.S_ISLNK(worktree_metadata.st_mode)
        or not stat.S_ISDIR(common_metadata.st_mode)
        or stat.S_ISLNK(common_metadata.st_mode)
        or resolved_common.parent != resolved_worktree
    ):
        raise UnsupportedGitLayout(
            "unsupported Codex Git layout: workspace or .git contains a "
            f"symlink/non-directory alias; {_FULL_CLONE_ACTION}"
        )
    if owned_paths is not None:
        for value in _owned_paths(owned_paths):
            lexical = value[:-3] if value.endswith("/**") else value
            target = worktree_path / lexical
            current = worktree_path
            for part in Path(lexical).parts:
                current /= part
                if os.path.lexists(current) and current.is_symlink():
                    raise UnsupportedGitLayout(
                        "unsupported Codex owned path layout: symlink in "
                        f"{value!r}; {_FULL_CLONE_ACTION}"
                    )
            anchor = target if target.exists() else target.parent
            try:
                resolved_anchor = anchor.resolve(strict=True)
                resolved_anchor.relative_to(resolved_worktree)
            except (OSError, RuntimeError, ValueError) as exc:
                raise UnsupportedGitLayout(
                    "unsupported Codex owned path layout: path escapes or has "
                    f"an unavailable parent: {value!r}"
                ) from exc
    return lexical_worktree, lexical_common


def _identity(domain: str, value: Any) -> str:
    payload = domain.encode("ascii") + b"\x00" + canonical_json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def _request_sha(request_without_sha: dict[str, Any]) -> str:
    return _identity("sulde-native-broker-request-v1/request", request_without_sha)


def _coordinator_delivery_projection(
    *,
    task_id: str,
    base_commit: str,
    task_definition_sha256: str,
    brief_sha256: str,
    worktree_canonical_path: str,
    git_common_dir_canonical_path: str,
    owned_paths: list[str],
    report_relative_path: str,
    model_reasoning_effort: str,
    codex_executable: str,
    codex_version: str,
    codex_executable_sha256: str,
    broker_generation: int,
    broker_sha256: str,
    provider_generation: int,
    permission_profile_name: str,
    permission_profile_bytes_sha256: str,
    permission_profile_spec_sha256: str,
    installed_descriptor_sha256: str,
    runtime_generation: str,
    runtime_tree_sha256: str,
    agent_runtime_sha256: str,
    nonce: str,
) -> str:
    projection = {
        "task_id": task_id,
        "base_commit": base_commit,
        "task_definition_sha256": task_definition_sha256,
        "brief_sha256": brief_sha256,
        "worktree_canonical_path": worktree_canonical_path,
        "git_common_dir_canonical_path": git_common_dir_canonical_path,
        "owned_paths": owned_paths,
        "report_relative_path": report_relative_path,
        "model_reasoning_effort": model_reasoning_effort,
        "codex_executable": codex_executable,
        "codex_version": codex_version,
        "codex_executable_sha256": codex_executable_sha256,
        "broker_generation": broker_generation,
        "broker_sha256": broker_sha256,
        "provider_generation": provider_generation,
        "permission_profile_name": permission_profile_name,
        "permission_profile_bytes_sha256": permission_profile_bytes_sha256,
        "permission_profile_spec_sha256": permission_profile_spec_sha256,
        "installed_descriptor_sha256": installed_descriptor_sha256,
        "runtime_generation": runtime_generation,
        "runtime_tree_sha256": runtime_tree_sha256,
        "agent_runtime_sha256": agent_runtime_sha256,
        "nonce": nonce,
    }
    return _identity(
        "sulde-native-broker-v1/coordinator-delivery-projection", projection
    )


def build_request(frozen: Any) -> dict[str, Any]:
    """Build a canonical broker request from the complete frozen fact set."""

    facts = _exact_dict(frozen, _FROZEN_FIELDS, label="frozen request fields")
    task_id = _text(facts["task_id"], label="task_id", pattern=_IDENTIFIER)
    base_commit = _text(facts["base_commit"], label="base_commit", pattern=_HEX_40)
    task_definition_sha256 = _digest(
        facts["task_definition_sha256"], label="task_definition_sha256"
    )
    brief_sha256 = _digest(facts["brief_sha256"], label="brief_sha256")
    worktree = _canonical_absolute(
        facts["worktree_canonical_path"], label="worktree_canonical_path"
    )
    git_common_dir = _canonical_absolute(
        facts["git_common_dir_canonical_path"],
        label="git_common_dir_canonical_path",
    )
    owned_paths = _owned_paths(facts["owned_paths"])
    report_relative_path = _canonical_relative(
        facts["report_relative_path"], label="report_relative_path"
    )
    model_reasoning_effort = _text(
        facts["model_reasoning_effort"], label="model_reasoning_effort"
    )
    if model_reasoning_effort not in {"low", "medium", "high"}:
        raise ProtocolError("model_reasoning_effort is invalid")
    codex_executable = _canonical_absolute(
        facts["codex_executable"], label="codex_executable"
    )
    codex_version = _text(
        facts["codex_version"], label="codex_version", pattern=_CODEX_VERSION
    )
    codex_sha = _digest(
        facts["codex_executable_sha256"], label="codex_executable_sha256"
    )
    broker_generation = _integer(
        facts["broker_generation"], label="broker_generation", minimum=1
    )
    broker_sha = _digest(facts["broker_sha256"], label="broker_sha256")
    provider_generation = _integer(
        facts["provider_generation"], label="provider_generation", minimum=1
    )
    profile_name = _text(
        facts["permission_profile_name"],
        label="permission_profile_name",
        pattern=_IDENTIFIER,
    )
    profile_sha = _digest(
        facts["permission_profile_bytes_sha256"],
        label="permission_profile_bytes_sha256",
    )
    profile_spec_sha = _digest(
        facts["permission_profile_spec_sha256"],
        label="permission_profile_spec_sha256",
    )
    installed_descriptor_sha = _digest(
        facts["installed_descriptor_sha256"],
        label="installed_descriptor_sha256",
    )
    runtime_generation = _text(
        facts["runtime_generation"], label="runtime_generation"
    )
    runtime_tree_sha = _digest(
        facts["runtime_tree_sha256"], label="runtime_tree_sha256"
    )
    agent_runtime_sha = _digest(
        facts["agent_runtime_sha256"], label="agent_runtime_sha256"
    )
    nonce = _digest(facts["nonce"], label="nonce")
    projection_sha = _coordinator_delivery_projection(
        task_id=task_id,
        base_commit=base_commit,
        task_definition_sha256=task_definition_sha256,
        brief_sha256=brief_sha256,
        worktree_canonical_path=worktree,
        git_common_dir_canonical_path=git_common_dir,
        owned_paths=owned_paths,
        report_relative_path=report_relative_path,
        model_reasoning_effort=model_reasoning_effort,
        codex_executable=codex_executable,
        codex_version=codex_version,
        codex_executable_sha256=codex_sha,
        broker_generation=broker_generation,
        broker_sha256=broker_sha,
        provider_generation=provider_generation,
        permission_profile_name=profile_name,
        permission_profile_bytes_sha256=profile_sha,
        permission_profile_spec_sha256=profile_spec_sha,
        installed_descriptor_sha256=installed_descriptor_sha,
        runtime_generation=runtime_generation,
        runtime_tree_sha256=runtime_tree_sha,
        agent_runtime_sha256=agent_runtime_sha,
        nonce=nonce,
    )

    request = {
        "schema": REQUEST_SCHEMA,
        "task_id": task_id,
        "base_commit": base_commit,
        "task_definition_sha256": task_definition_sha256,
        "brief_sha256": brief_sha256,
        "task_identity_sha256": _identity(
            "sulde-native-broker-request-v1/task",
            [task_id, base_commit, task_definition_sha256, brief_sha256],
        ),
        "worktree_canonical_path": worktree,
        "git_common_dir_canonical_path": git_common_dir,
        "worktree_identity_sha256": _identity(
            "sulde-native-broker-request-v1/worktree", worktree
        ),
        "owned_paths": owned_paths,
        "owned_paths_sha256": _identity(
            "sulde-native-broker-request-v1/owned-paths", owned_paths
        ),
        "report_relative_path": report_relative_path,
        "model_reasoning_effort": model_reasoning_effort,
        "codex_executable": codex_executable,
        "codex_version": codex_version,
        "codex_executable_sha256": codex_sha,
        "codex_identity_sha256": _identity(
            "sulde-native-broker-request-v1/codex",
            [codex_executable, codex_version, codex_sha],
        ),
        "broker_generation": broker_generation,
        "broker_sha256": broker_sha,
        "broker_identity_sha256": _identity(
            "sulde-native-broker-request-v1/broker",
            [broker_generation, broker_sha],
        ),
        "provider_generation": provider_generation,
        "permission_profile_name": profile_name,
        "permission_profile_bytes_sha256": profile_sha,
        "permission_profile_identity_sha256": _identity(
            "sulde-native-broker-request-v1/permission-profile",
            [profile_name, profile_sha, profile_spec_sha],
        ),
        "permission_profile_spec_sha256": profile_spec_sha,
        "installed_descriptor_sha256": installed_descriptor_sha,
        "runtime_generation": runtime_generation,
        "runtime_tree_sha256": runtime_tree_sha,
        "agent_runtime_sha256": agent_runtime_sha,
        "nonce": nonce,
        "coordinator_delivery_projection_sha256": projection_sha,
        # These constants are protocol facts: local digest consistency never
        # confers coordinator origin or execution authority.
        "external_authority_required": True,
        "execution_authorized": False,
    }
    request["request_sha256"] = _request_sha(request)
    return request


def validate_request(request: Any, frozen: Any) -> dict[str, Any]:
    candidate = _exact_dict(request, _REQUEST_FIELDS, label="broker request")
    expected = build_request(frozen)
    if canonical_json_bytes(candidate) != canonical_json_bytes(expected):
        raise ProtocolError("broker request does not match the frozen request fields")
    return candidate


def build_provider_command(request: Any, frozen: Any) -> list[str]:
    valid = validate_request(request, frozen)
    validate_supported_git_layout(
        valid["worktree_canonical_path"],
        valid["git_common_dir_canonical_path"],
        owned_paths=valid["owned_paths"],
    )
    profile_raw = permission_profile_bytes(
        valid["owned_paths"],
        worktree=valid["worktree_canonical_path"],
        profile_name=valid["permission_profile_name"],
    )
    if hashlib.sha256(profile_raw).hexdigest() != valid[
        "permission_profile_bytes_sha256"
    ]:
        raise ProtocolError("permission profile bytes disagree with the broker renderer")
    scratch = native_command_scratch_path(valid["worktree_canonical_path"])
    hook_command = _codex_pre_tool_hook_command(
        profile_raw=profile_raw,
        broker_sha256=valid["broker_sha256"],
        scratch_path=scratch,
    )
    hook_config = (
        "hooks.PreToolUse=[{matcher=\".*\",hooks=[{type=\"command\",command="
        + json.dumps(hook_command, ensure_ascii=True)
        + ",timeout=10}]}]"
    )
    return [
        valid["codex_executable"],
        "exec",
        "--ignore-user-config",
        "--strict-config",
        "--ignore-rules",
        "-C",
        valid["worktree_canonical_path"],
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--output-last-message",
        valid["worktree_canonical_path"] + "/" + valid["report_relative_path"],
        "-s",
        "danger-full-access",
        "--dangerously-bypass-hook-trust",
        "-c",
        'approval_policy="never"',
        "-c",
        'model_reasoning_effort=' + json.dumps(valid["model_reasoning_effort"]),
        "-c",
        "features.multi_agent=false",
        "-c",
        hook_config,
        "-",
    ]


def validate_provider_command(command: Any, request: Any, frozen: Any) -> list[str]:
    if type(command) is not list:
        raise ProtocolError("provider command must be an exact JSON array")
    _ensure_plain(command, label="provider command")
    if any(type(item) is not str for item in command):
        raise ProtocolError("provider command elements must be exact strings")
    expected = build_provider_command(request, frozen)
    if command != expected:
        raise ProtocolError("provider command is not the fixed codex exec template")
    return command


_PROBE_MATRIX = (
    ("existing_owned_write", "owned-existing-file", "write", True, True, False),
    ("new_owned_create", "owned-new-file", "create", False, True, False),
    ("workspace_nonowned", "workspace-nonowned-file", "write", True, True, True),
    ("system_tmp", "system-/tmp-file", "create", False, False, True),
    ("environment_tmpdir", "environment-$TMPDIR-file", "create", False, False, True),
    ("owned_parent_escape", "owned-parent-first-write", "create", False, False, True),
    ("owned_sibling_escape", "owned-sibling-first-write", "create", False, False, True),
    ("git_common_write", "git-common-dir-first-write", "create", False, False, True),
    ("scope_outside_symlink", "owned-symlink-to-scope-outside", "write", True, True, True),
    ("scope_outside_pycache", "scope-outside-pycache", "create", False, False, True),
    ("network_socket", "loopback-network-connect", "connect", False, False, True),
    ("nonowned_unlink_file", "existing-nonowned-regular-file", "unlink", True, True, True),
    ("nonowned_unlink_empty_dir", "existing-nonowned-empty-directory", "unlink", True, True, True),
    ("nonowned_unlink_symlink", "existing-nonowned-symlink", "unlink", True, True, True),
    ("git_control_unlink", "existing-git-control-file", "unlink", True, True, True),
    ("codex_agent_control_unlink", "existing-codex-agent-control-file", "unlink", True, True, True),
    ("owned_adjacent_unlink", "existing-nonowned-owned-adjacent-file", "unlink", True, True, True),
    ("nonowned_move", "existing-nonowned-move-source", "rename", True, True, True),
    ("nonowned_replace", "existing-nonowned-replace-target", "replace", True, True, True),
)


def _bindings(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_sha256": request["request_sha256"],
        "permission_profile_name": request["permission_profile_name"],
        "permission_profile_bytes_sha256": request[
            "permission_profile_bytes_sha256"
        ],
        "broker_generation": request["broker_generation"],
        "broker_sha256": request["broker_sha256"],
        "provider_generation": request["provider_generation"],
        "codex_executable": request["codex_executable"],
        "codex_version": request["codex_version"],
        "codex_executable_sha256": request["codex_executable_sha256"],
        "codex_identity_sha256": request["codex_identity_sha256"],
        "installed_descriptor_sha256": request["installed_descriptor_sha256"],
        "runtime_generation": request["runtime_generation"],
        "runtime_tree_sha256": request["runtime_tree_sha256"],
        "agent_runtime_sha256": request["agent_runtime_sha256"],
        "permission_profile_spec_sha256": request[
            "permission_profile_spec_sha256"
        ],
        "coordinator_delivery_projection_sha256": request[
            "coordinator_delivery_projection_sha256"
        ],
        "external_authority_required": True,
        "execution_authorized": False,
    }


def build_profile_probe_plan(request: Any, frozen: Any) -> dict[str, Any]:
    valid = validate_request(request, frozen)
    probes = [
        {
            "probe_id": probe_id,
            "target_class": target_class,
            "operation": operation,
            "pre_exists": pre_exists,
            "post_exists": post_exists,
            "expected_execution_prevented": expected_prevented,
        }
        for probe_id, target_class, operation, pre_exists, post_exists, expected_prevented in _PROBE_MATRIX
    ]
    plan = {
        "schema": PROBE_PLAN_SCHEMA,
        **_bindings(valid),
        "probes": probes,
    }
    plan["plan_sha256"] = _identity(
        "sulde-native-profile-probe-plan-v2/plan", plan
    )
    return plan


_PROBE_RESULT_FIELDS = {
    "probe_id",
    "operation",
    "pre_exists",
    "post_exists",
    "pre_observation_sha256",
    "post_observation_sha256",
    "observed_denial",
    "execution_prevented",
}


def _validated_probe_results(results: Any) -> list[dict[str, Any]]:
    if type(results) is not list:
        raise ProtocolError("probe results must be an exact JSON array")
    _ensure_plain(results, label="probe results")
    if len(results) != len(_PROBE_MATRIX):
        raise ProtocolError("probe results must contain the complete fixed matrix")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, (row, expected) in enumerate(zip(results, _PROBE_MATRIX)):
        value = _exact_dict(
            row, _PROBE_RESULT_FIELDS, label=f"probe results[{index}]"
        )
        probe_id = _text(value["probe_id"], label="probe_id", pattern=_IDENTIFIER)
        if probe_id in seen or probe_id != expected[0]:
            raise ProtocolError("probe results must be unique and in fixed matrix order")
        seen.add(probe_id)
        operation = _text(value["operation"], label="probe operation", pattern=_IDENTIFIER)
        if operation != expected[2]:
            raise ProtocolError("probe result operation disagrees with fixed matrix")
        pre_exists = _boolean(value["pre_exists"], label="probe pre_exists")
        post_exists = _boolean(value["post_exists"], label="probe post_exists")
        pre_observation = _evidence_digest(
            value["pre_observation_sha256"],
            label="probe pre_observation_sha256",
        )
        post_observation = _evidence_digest(
            value["post_observation_sha256"],
            label="probe post_observation_sha256",
        )
        observed_denial = _boolean(
            value["observed_denial"], label="probe observed_denial"
        )
        execution_prevented = _boolean(
            value["execution_prevented"], label="probe execution_prevented"
        )
        prevention_from_observations = (
            pre_exists == post_exists and pre_observation == post_observation
        )
        if execution_prevented != prevention_from_observations:
            raise ProtocolError(
                "probe execution_prevented disagrees with independent observations"
            )
        if expected[5] and not observed_denial:
            raise ProtocolError(
                "required native operation denial observation is missing"
            )
        if (pre_exists, post_exists, prevention_from_observations) != (
            expected[3],
            expected[4],
            expected[5],
        ):
            raise ProtocolError("profile probe did not satisfy its fixed expectation")
        normalized.append(
            {
                "probe_id": probe_id,
                "operation": operation,
                "pre_exists": pre_exists,
                "post_exists": post_exists,
                "pre_observation_sha256": pre_observation,
                "post_observation_sha256": post_observation,
                "observed_denial": observed_denial,
                "execution_prevented": execution_prevented,
            }
        )
    return normalized


def build_probe_receipt(
    request: Any, frozen: Any, results: Any, *, probe_run_id: Any
) -> dict[str, Any]:
    valid = validate_request(request, frozen)
    probes = _validated_probe_results(results)
    plan = build_profile_probe_plan(valid, frozen)
    run_id = _run_id(probe_run_id, label="probe_run_id")
    run_identity = _identity(
        "sulde-native-profile-probe-receipt-v2/probe-run",
        {
            "coordinator_delivery_projection_sha256": valid[
                "coordinator_delivery_projection_sha256"
            ],
            "request_sha256": valid["request_sha256"],
            "probe_plan_sha256": plan["plan_sha256"],
            "probe_run_id": run_id,
            "probes": probes,
        },
    )
    receipt = {
        "schema": PROBE_RECEIPT_SCHEMA,
        **_bindings(valid),
        "probe_plan_sha256": plan["plan_sha256"],
        "probe_run_id": run_id,
        "probe_run_identity_sha256": run_identity,
        "probes": probes,
    }
    receipt["receipt_sha256"] = _identity(
        "sulde-native-profile-probe-receipt-v2/receipt", receipt
    )
    return receipt


_PROBE_RECEIPT_FIELDS = (
    {
        "schema",
        "probe_plan_sha256",
        "probe_run_id",
        "probe_run_identity_sha256",
        "probes",
        "receipt_sha256",
    }
    | _BINDING_FIELDS
)


def validate_probe_receipt(
    receipt: Any, request: Any, frozen: Any
) -> dict[str, Any]:
    candidate = _exact_dict(
        receipt, _PROBE_RECEIPT_FIELDS, label="profile probe receipt"
    )
    _evidence_digest(
        candidate["probe_run_identity_sha256"],
        label="probe_run_identity_sha256",
    )
    expected = build_probe_receipt(
        request,
        frozen,
        candidate["probes"],
        probe_run_id=candidate["probe_run_id"],
    )
    if canonical_json_bytes(candidate) != canonical_json_bytes(expected):
        raise ProtocolError("profile probe receipt binding or digest mismatch")
    return candidate


def build_launch_plan(
    request: Any, probe_receipt: Any, frozen: Any
) -> dict[str, Any]:
    valid_request = validate_request(request, frozen)
    valid_receipt = validate_probe_receipt(probe_receipt, valid_request, frozen)
    command = build_provider_command(valid_request, frozen)
    plan = {
        "schema": LAUNCH_PLAN_SCHEMA,
        **_bindings(valid_request),
        "probe_receipt_sha256": valid_receipt["receipt_sha256"],
        "probe_run_identity_sha256": valid_receipt[
            "probe_run_identity_sha256"
        ],
        "command": command,
        "stdin_source": "broker-bound-task-brief-bytes",
    }
    plan["launch_identity_sha256"] = _identity(
        "sulde-native-provider-launch-plan-v1/launch", plan
    )
    plan["plan_sha256"] = _identity(
        "sulde-native-provider-launch-plan-v1/plan", plan
    )
    return plan


_LAUNCH_PLAN_FIELDS = (
    {
        "schema",
        "probe_receipt_sha256",
        "probe_run_identity_sha256",
        "command",
        "stdin_source",
        "launch_identity_sha256",
        "plan_sha256",
    }
    | _BINDING_FIELDS
)


def validate_launch_plan(
    launch_plan: Any, request: Any, probe_receipt: Any, frozen: Any
) -> dict[str, Any]:
    candidate = _exact_dict(
        launch_plan, _LAUNCH_PLAN_FIELDS, label="provider launch plan"
    )
    if candidate["schema"] != LAUNCH_PLAN_SCHEMA:
        raise ProtocolError("provider launch plan schema mismatch")
    _evidence_digest(
        candidate["probe_run_identity_sha256"],
        label="probe_run_identity_sha256",
    )
    _evidence_digest(
        candidate["launch_identity_sha256"], label="launch_identity_sha256"
    )
    expected = build_launch_plan(request, probe_receipt, frozen)
    if canonical_json_bytes(candidate) != canonical_json_bytes(expected):
        raise ProtocolError("provider launch plan binding or digest mismatch")
    return candidate


_STDERR_FIELDS = {
    "schema",
    "path",
    "raw_bytes_base64",
    "raw_byte_count",
    "sha256",
    "fsync_completed",
}


def build_stderr_binding(
    path: Any, raw_bytes: Any, fsync_completed: Any
) -> dict[str, Any]:
    relative = _canonical_relative(path, label="stderr path")
    if type(raw_bytes) is not bytes:
        raise ProtocolError("stderr raw bytes must be an exact bytes value")
    if len(raw_bytes) > MAX_STDERR_RAW_BYTES:
        raise ProtocolError("stderr raw bytes exceed the fixed byte-size bound")
    fsynced = _boolean(fsync_completed, label="stderr fsync_completed")
    if not fsynced:
        raise ProtocolError("stderr binding requires fsync_completed true")
    return {
        "schema": STDERR_BINDING_SCHEMA,
        "path": relative,
        "raw_bytes_base64": base64.b64encode(raw_bytes).decode("ascii"),
        "raw_byte_count": len(raw_bytes),
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "fsync_completed": True,
    }


def stderr_binding_raw_bytes(binding: Any) -> bytes:
    candidate = _exact_dict(binding, _STDERR_FIELDS, label="stderr binding")
    if candidate["schema"] != STDERR_BINDING_SCHEMA:
        raise ProtocolError("stderr binding schema mismatch")
    _canonical_relative(candidate["path"], label="stderr path")
    encoded = candidate["raw_bytes_base64"]
    if type(encoded) is not str:
        raise ProtocolError("stderr raw_bytes_base64 must be an exact string")
    if len(encoded) > ((MAX_STDERR_RAW_BYTES + 2) // 3) * 4:
        raise ProtocolError("stderr raw bytes exceed the fixed byte-size bound")
    count = _integer(
        candidate["raw_byte_count"],
        label="stderr raw_byte_count",
        maximum=MAX_STDERR_RAW_BYTES,
    )
    digest = _digest(candidate["sha256"], label="stderr sha256")
    if _boolean(candidate["fsync_completed"], label="stderr fsync_completed") is not True:
        raise ProtocolError("stderr binding requires fsync_completed true")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as exc:
        raise ProtocolError("stderr raw_bytes_base64 is invalid") from exc
    if len(raw) != count or hashlib.sha256(raw).hexdigest() != digest:
        raise ProtocolError("stderr byte count or SHA-256 mismatch")
    return raw


def validate_stderr_binding(binding: Any) -> dict[str, Any]:
    stderr_binding_raw_bytes(binding)
    return binding


_JSONL_SUMMARY_FIELDS = {
    "line_count",
    "valid_json_line_count",
    "terminal_event",
    "terminal_event_count",
    "sha256",
}
_BLOB_SUMMARY_FIELDS = {"present", "raw_byte_count", "sha256"}
_TERMINAL_EVENTS = {"turn.completed", "turn.failed", "none"}


def _jsonl_summary(value: Any) -> dict[str, Any]:
    summary = _exact_dict(value, _JSONL_SUMMARY_FIELDS, label="JSONL summary")
    line_count = _integer(summary["line_count"], label="JSONL line_count")
    valid_count = _integer(
        summary["valid_json_line_count"], label="JSONL valid_json_line_count"
    )
    if valid_count > line_count:
        raise ProtocolError("JSONL valid line count exceeds total line count")
    terminal_event = _text(summary["terminal_event"], label="JSONL terminal_event")
    if terminal_event not in _TERMINAL_EVENTS:
        raise ProtocolError("JSONL terminal_event is invalid")
    terminal_event_count = _integer(
        summary["terminal_event_count"], label="JSONL terminal_event_count"
    )
    if terminal_event_count not in {0, 1}:
        raise ProtocolError("JSONL terminal event count must be zero or one")
    if (terminal_event == "none") != (terminal_event_count == 0):
        raise ProtocolError("JSONL none terminal marker disagrees with its count")
    if terminal_event_count > line_count:
        raise ProtocolError("JSONL terminal event count exceeds total line count")
    if terminal_event_count > valid_count:
        raise ProtocolError("JSONL terminal event count exceeds valid JSON line count")
    digest = _digest(summary["sha256"], label="JSONL sha256")
    return {
        "line_count": line_count,
        "valid_json_line_count": valid_count,
        "terminal_event": terminal_event,
        "terminal_event_count": terminal_event_count,
        "sha256": digest,
    }


def _timestamp(value: Any, *, label: str) -> str:
    timestamp = _text(value, label=label, pattern=_RFC3339_UTC_SECONDS)
    try:
        datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ProtocolError(f"{label} is not a valid UTC timestamp") from exc
    return timestamp


def _blob_summary(value: Any, *, label: str) -> dict[str, Any]:
    summary = _exact_dict(value, _BLOB_SUMMARY_FIELDS, label=label)
    present = _boolean(summary["present"], label=f"{label} present")
    count = _integer(summary["raw_byte_count"], label=f"{label} raw_byte_count")
    digest = _digest(summary["sha256"], label=f"{label} sha256")
    if not present and (count != 0 or digest != hashlib.sha256(b"").hexdigest()):
        raise ProtocolError(f"absent {label} must bind empty bytes")
    return {"present": present, "raw_byte_count": count, "sha256": digest}


_PROVIDER_RECEIPT_FIELDS = (
    {
        "schema",
        "started",
        "started_at",
        "terminated",
        "terminated_at",
        "quiescence_confirmed",
        "provider_pid",
        "provider_run_id",
        "probe_receipt_sha256",
        "probe_run_identity_sha256",
        "launch_plan_sha256",
        "launch_identity_sha256",
        "terminal_status",
        "termination_domain",
        "termination_reason",
        "local_interruption_evidence",
        "exit_code",
        "stderr",
        "jsonl_summary",
        "output_summary",
        "report_summary",
        "observed_denial",
        "execution_prevented",
        "receipt_sha256",
    }
    | _BINDING_FIELDS
)

_LOCAL_INTERRUPTION_FIELDS = {
    "schema",
    "run_id",
    "interrupt_reason",
    "result_stop_reason",
    "result_returncode",
    "interrupt_event_index",
    "result_event_index",
    "disposed_event_index",
    "quiescent",
    "result_before_disposed",
    "run_ledger_sha256",
}
LOCAL_INTERRUPTION_REASON_AUTHORITY = MappingProxyType({
    "paused": "policy_paused",
    "correction_intervention": "policy_paused",
    "correction_store_integrity": "policy_paused",
    "awaiting_human": "awaiting_human",
    "external_effect_outcome_unknown": "awaiting_human",
    "timeout": "timeout",
    "monitor_error": "error",
    "unsettled_finalizer": "error",
})


def local_interruption_stop_reason(value: Any) -> str | None:
    """Resolve one exact interruption reason through the immutable authority."""
    if type(value) is not str:
        return None
    return LOCAL_INTERRUPTION_REASON_AUTHORITY.get(value)


def _local_interruption_evidence(value: Any) -> dict[str, Any]:
    evidence = _exact_dict(
        value, _LOCAL_INTERRUPTION_FIELDS, label="local interruption evidence"
    )
    if evidence["schema"] != "sulde-local-interruption-evidence-v1":
        raise ProtocolError("local interruption evidence schema mismatch")
    run_id = _run_id(evidence["run_id"], label="local interruption run_id")
    interrupt_reason = _text(
        evidence["interrupt_reason"], label="local interruption reason"
    )
    result_reason = _text(
        evidence["result_stop_reason"], label="local result stop reason"
    )
    if result_reason not in {"policy_paused", "awaiting_human", "timeout", "error"}:
        raise ProtocolError("local interruption stop reason is invalid")
    if local_interruption_stop_reason(interrupt_reason) != result_reason:
        raise ProtocolError("local interruption reason does not match result stop reason")
    result_code = _integer(
        evidence["result_returncode"],
        label="local interruption result returncode",
        minimum=-255,
        maximum=255,
    )
    indexes = [
        _integer(evidence[name], label=name)
        for name in (
            "interrupt_event_index",
            "result_event_index",
            "disposed_event_index",
        )
    ]
    if indexes != sorted(indexes) or len(set(indexes)) != 3:
        raise ProtocolError("local interruption events are not strictly ordered")
    if _boolean(evidence["quiescent"], label="local quiescent") is not True:
        raise ProtocolError("local interruption is not quiescent")
    if (
        _boolean(
            evidence["result_before_disposed"],
            label="local result_before_disposed",
        )
        is not True
    ):
        raise ProtocolError("local disposed event preceded its result")
    ledger_sha = _digest(
        evidence["run_ledger_sha256"], label="local run ledger sha256"
    )
    return {
        "schema": "sulde-local-interruption-evidence-v1",
        "run_id": run_id,
        "interrupt_reason": interrupt_reason,
        "result_stop_reason": result_reason,
        "result_returncode": result_code,
        "interrupt_event_index": indexes[0],
        "result_event_index": indexes[1],
        "disposed_event_index": indexes[2],
        "quiescent": True,
        "result_before_disposed": True,
        "run_ledger_sha256": ledger_sha,
    }


def build_provider_receipt(
    request: Any,
    probe_receipt: Any,
    launch_plan: Any,
    frozen: Any,
    *,
    started_at: Any,
    terminated_at: Any,
    provider_pid: Any,
    provider_run_id: Any,
    terminal_status: Any,
    termination_domain: Any = "provider_natural",
    termination_reason: Any = None,
    local_interruption_evidence: Any = None,
    exit_code: Any,
    quiescence_confirmed: Any,
    stderr_path: Any,
    stderr_raw_bytes: Any,
    stderr_fsync_completed: Any,
    jsonl_summary: Any,
    output_summary: Any,
    report_summary: Any,
    observed_denial: Any,
    execution_prevented: Any,
) -> dict[str, Any]:
    valid = validate_request(request, frozen)
    valid_probe = validate_probe_receipt(probe_receipt, valid, frozen)
    valid_launch = validate_launch_plan(
        launch_plan, valid, valid_probe, frozen
    )
    started = _timestamp(started_at, label="started_at")
    terminated = _timestamp(terminated_at, label="terminated_at")
    if terminated < started:
        raise ProtocolError("provider termination precedes start")
    pid = _integer(provider_pid, label="provider_pid", minimum=1, maximum=2**31 - 1)
    run_id = _run_id(provider_run_id, label="provider_run_id")
    status = _text(terminal_status, label="terminal_status")
    if status not in {"succeeded", "failed", "interrupted"}:
        raise ProtocolError("terminal_status is invalid")
    code = _integer(exit_code, label="exit_code", minimum=-255, maximum=255)
    domain = _text(termination_domain, label="termination_domain")
    if domain not in {"provider_natural", "local_interruption"}:
        raise ProtocolError("termination_domain is invalid")
    if _boolean(quiescence_confirmed, label="quiescence_confirmed") is not True:
        raise ProtocolError("terminal receipt requires confirmed quiescence")
    stderr = build_stderr_binding(
        stderr_path, stderr_raw_bytes, stderr_fsync_completed
    )
    if status != "succeeded" and stderr["raw_byte_count"] == 0:
        raise ProtocolError("failed terminal receipt requires non-empty stderr binding")
    jsonl = _jsonl_summary(jsonl_summary)
    if domain == "provider_natural":
        reason = _text(
            termination_reason
            if termination_reason is not None
            else ("provider_completed" if status == "succeeded" else "provider_failed"),
            label="termination_reason",
        )
        if local_interruption_evidence is not None:
            raise ProtocolError("provider natural terminal cannot carry local interruption evidence")
        local_evidence = None
        expected = {
            "succeeded": (0, "turn.completed", "provider_completed"),
            "failed": (None, "turn.failed", "provider_failed"),
        }.get(status)
        if (
            expected is None
            or jsonl["terminal_event_count"] != 1
            or jsonl["terminal_event"] != expected[1]
            or reason != expected[2]
            or (status == "succeeded" and code != 0)
            or (status == "failed" and code == 0)
        ):
            raise ProtocolError("provider natural status, reason, exit, or terminal disagrees")
    else:
        reason = _text(termination_reason, label="termination_reason")
        if status != "interrupted" or jsonl["terminal_event_count"] != 0:
            raise ProtocolError("local interruption requires zero provider terminal")
        local_evidence = _local_interruption_evidence(local_interruption_evidence)
        if (
            local_evidence["run_id"] != run_id
            or local_evidence["result_stop_reason"] != reason
            or local_evidence["result_returncode"] != code
        ):
            raise ProtocolError("local interruption evidence does not match receipt")
    output = _blob_summary(output_summary, label="output summary")
    report = _blob_summary(report_summary, label="report summary")
    if output != report:
        raise ProtocolError("output and report summaries must bind one byte authority")
    denial = _boolean(observed_denial, label="observed_denial")
    prevented = _boolean(execution_prevented, label="execution_prevented")
    receipt = {
        "schema": PROVIDER_RECEIPT_SCHEMA,
        **_bindings(valid),
        "started": True,
        "started_at": started,
        "terminated": True,
        "terminated_at": terminated,
        "quiescence_confirmed": True,
        "provider_pid": pid,
        "provider_run_id": run_id,
        "probe_receipt_sha256": valid_probe["receipt_sha256"],
        "probe_run_identity_sha256": valid_probe[
            "probe_run_identity_sha256"
        ],
        "launch_plan_sha256": valid_launch["plan_sha256"],
        "launch_identity_sha256": valid_launch["launch_identity_sha256"],
        "terminal_status": status,
        "termination_domain": domain,
        "termination_reason": reason,
        "local_interruption_evidence": local_evidence,
        "exit_code": code,
        "stderr": stderr,
        "jsonl_summary": jsonl,
        "output_summary": output,
        "report_summary": report,
        "observed_denial": denial,
        "execution_prevented": prevented,
    }
    receipt["receipt_sha256"] = _identity(
        "sulde-native-provider-receipt-v1/receipt", receipt
    )
    return receipt


def validate_provider_receipt(
    receipt: Any,
    request: Any,
    probe_receipt: Any,
    launch_plan: Any,
    frozen: Any,
) -> dict[str, Any]:
    candidate = _exact_dict(
        receipt, _PROVIDER_RECEIPT_FIELDS, label="provider receipt"
    )
    if candidate["schema"] != PROVIDER_RECEIPT_SCHEMA:
        raise ProtocolError("provider receipt schema mismatch")
    if _boolean(candidate["started"], label="provider started") is not True:
        raise ProtocolError("provider receipt must record startup")
    if _boolean(candidate["terminated"], label="provider terminated") is not True:
        raise ProtocolError("provider receipt must record termination")
    _evidence_digest(
        candidate["probe_run_identity_sha256"],
        label="probe_run_identity_sha256",
    )
    _evidence_digest(
        candidate["launch_identity_sha256"], label="launch_identity_sha256"
    )
    raw_stderr = stderr_binding_raw_bytes(candidate["stderr"])
    expected = build_provider_receipt(
        request,
        probe_receipt,
        launch_plan,
        frozen,
        started_at=candidate["started_at"],
        terminated_at=candidate["terminated_at"],
        provider_pid=candidate["provider_pid"],
        provider_run_id=candidate["provider_run_id"],
        terminal_status=candidate["terminal_status"],
        termination_domain=candidate["termination_domain"],
        termination_reason=candidate["termination_reason"],
        local_interruption_evidence=candidate["local_interruption_evidence"],
        exit_code=candidate["exit_code"],
        quiescence_confirmed=candidate["quiescence_confirmed"],
        stderr_path=candidate["stderr"]["path"],
        stderr_raw_bytes=raw_stderr,
        stderr_fsync_completed=candidate["stderr"]["fsync_completed"],
        jsonl_summary=candidate["jsonl_summary"],
        output_summary=candidate["output_summary"],
        report_summary=candidate["report_summary"],
        observed_denial=candidate["observed_denial"],
        execution_prevented=candidate["execution_prevented"],
    )
    if canonical_json_bytes(candidate) != canonical_json_bytes(expected):
        raise ProtocolError("provider receipt binding or digest mismatch")
    return candidate


NATIVE_EVIDENCE_SCHEMA = "sulde-native-profile-execution-evidence-v2"


def _observation(path: Path) -> tuple[bool, str]:
    exists = os.path.lexists(path)
    payload: dict[str, Any] = {"exists": exists}
    if exists:
        metadata = path.lstat()
        payload["mode"] = stat.S_IFMT(metadata.st_mode)
        payload["size"] = metadata.st_size
        if stat.S_ISREG(metadata.st_mode):
            payload["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return exists, _identity("sulde-native-profile-probe-v1/observation", payload)


def _atomic_evidence(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    encoded = canonical_json_bytes(payload) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _validate_native_probe_preconditions(
    observations: dict[str, tuple[bool, str]],
) -> None:
    expected_ids = {row[0] for row in _PROBE_MATRIX}
    if type(observations) is not dict or set(observations) != expected_ids:
        raise ProtocolError("native profile probe pre-observation matrix is incomplete")
    for probe_id, _target_class, _operation, expected_pre, _expected_post, _expected_prevented in _PROBE_MATRIX:
        observation = observations[probe_id]
        if (
            type(observation) is not tuple
            or len(observation) != 2
            or type(observation[0]) is not bool
            or type(observation[1]) is not str
        ):
            raise ProtocolError("native profile probe pre-observation is malformed")
        if observation[0] != expected_pre:
            raise ProtocolError(
                f"native profile probe target pre-existed unexpectedly: {probe_id}"
            )


def _parse_native_probe_stdout(stdout: Any) -> dict[str, str]:
    if type(stdout) is not bytes:
        raise ProtocolError("native profile probe stdout must be raw bytes")
    try:
        decoded = stdout.decode("utf-8", "strict")
    except UnicodeError as error:
        raise ProtocolError("native profile probe stdout is not strict UTF-8") from error
    if not decoded.endswith("\n") or decoded.count("\n") != 1:
        raise ProtocolError("native profile probe must emit exactly one JSON line")
    try:
        payload = json.loads(decoded[:-1])
    except json.JSONDecodeError as error:
        raise ProtocolError("native profile probe returned invalid JSON") from error
    expected_ids = {row[0] for row in _PROBE_MATRIX}
    if type(payload) is not dict or set(payload) != expected_ids:
        raise ProtocolError("native profile probe stdout has wrong observation cardinality")
    for probe_id, _target_class, operation, _pre, _post, prevented in _PROBE_MATRIX:
        expected = (
            f"{operation}_permission_denied"
            if prevented
            else f"{operation}_completed"
        )
        if type(payload[probe_id]) is not str or payload[probe_id] != expected:
            raise ProtocolError(
                "native profile probe stdout has an inexact operation outcome"
            )
    if stdout != canonical_json_bytes(payload) + b"\n":
        raise ProtocolError("native profile probe stdout is not canonical JSON")
    return payload


def _native_probe_results(
    before: dict[str, tuple[bool, str]],
    after: dict[str, tuple[bool, str]],
    outcomes: dict[str, str],
) -> list[dict[str, Any]]:
    _validate_native_probe_preconditions(before)
    expected_ids = {row[0] for row in _PROBE_MATRIX}
    if type(after) is not dict or set(after) != expected_ids:
        raise ProtocolError("native profile probe post-observation matrix is incomplete")
    if type(outcomes) is not dict or set(outcomes) != expected_ids:
        raise ProtocolError("native profile probe child observation matrix is incomplete")
    results: list[dict[str, Any]] = []
    for probe_id, _target_class, operation, expected_pre, expected_post, expected_prevented in _PROBE_MATRIX:
        pre_exists, pre_digest = before[probe_id]
        post_exists, post_digest = after[probe_id]
        outcome = outcomes[probe_id]
        expected_outcome = (
            f"{operation}_permission_denied"
            if expected_prevented
            else f"{operation}_completed"
        )
        if outcome != expected_outcome:
            raise ProtocolError(
                f"native profile probe child outcome contradicted plan: {probe_id}"
            )
        prevented_by_observation = (
            pre_exists == post_exists and pre_digest == post_digest
        )
        if (pre_exists, post_exists, prevented_by_observation) != (
            expected_pre,
            expected_post,
            expected_prevented,
        ):
            raise ProtocolError(
                f"native profile probe observations contradicted plan: {probe_id}"
            )
        results.append(
            {
                "probe_id": probe_id,
                "operation": operation,
                "pre_exists": pre_exists,
                "post_exists": post_exists,
                "pre_observation_sha256": pre_digest,
                "post_observation_sha256": post_digest,
                "observed_denial": outcome == f"{operation}_permission_denied",
                "execution_prevented": prevented_by_observation,
            }
        )
    return results


def _canonical_seatbelt_path(value: Any) -> str:
    """Return the physical absolute identity Seatbelt matches for ``value``.

    ``Path.resolve(strict=False)`` resolves every existing ancestor while
    retaining a not-yet-created suffix.  That is required on macOS where a
    lexical path below ``/var`` is accessed below its ``/private/var`` kernel
    identity, and it also binds filters to the target of an existing symlink
    parent rather than to an alias that the eventual write will traverse.
    """

    if type(value) is str:
        lexical = value
    elif isinstance(value, Path):
        lexical = str(value)
    else:
        raise ProtocolError("native profile path must be an exact path string")

    def absolute_path(path: str, *, label: str) -> str:
        checked = _path_text(path, label=label)
        parts = checked.split("/")
        if not checked.startswith("/") or any(
            part in {"", ".", ".."} for part in parts[1:]
        ):
            raise ProtocolError(f"{label} must be an absolute canonical POSIX path")
        return checked

    lexical = absolute_path(lexical, label="native profile path")
    try:
        physical = Path(lexical).resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise ProtocolError("native profile path could not be resolved") from exc
    return absolute_path(str(physical), label="resolved native profile path")


def _seatbelt_file_write_profile(
    filters: list[tuple[str, Path]],
    *,
    destructive_scope: Path | None = None,
    destructive_owned_paths: list[Path] | None = None,
) -> str:
    """Build one top-level deny clause for every exact Seatbelt filter.

    Multiple filters inside a single operation clause are conjunctive in the
    native profile language.  Keeping every literal/subpath in its own clause
    makes the intended closed disjunction explicit.
    """

    clauses = ["(version 1)", "(allow default)"]
    for filter_kind, path in filters:
        if filter_kind not in {"literal", "subpath"}:
            raise ProtocolError("native profile contains an unsupported path filter")
        value = _canonical_seatbelt_path(path)
        quoted = value.replace("\\", "\\\\").replace('"', '\\"')
        clauses.append(f'(deny file-write* ({filter_kind} "{quoted}"))')
    if destructive_scope is not None:
        scope = _canonical_seatbelt_path(destructive_scope)
        quoted_scope = scope.replace("\\", "\\\\").replace('"', '\\"')
        clauses.append(
            f'(deny file-write-unlink (subpath "{quoted_scope}"))'
        )
        for path in destructive_owned_paths or []:
            owned = _canonical_seatbelt_path(path)
            quoted_owned = owned.replace("\\", "\\\\").replace('"', '\\"')
            clauses.append(
                f'(allow file-write-unlink (literal "{quoted_owned}"))'
            )
    return " ".join(clauses)


def _seatbelt_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def native_command_scratch_path(worktree: Any) -> str:
    root = _canonical_seatbelt_path(
        _canonical_absolute(worktree, label="worktree_canonical_path")
    )
    return _canonical_seatbelt_path(
        Path(root) / ".codex-agent" / ".native-command-scratch"
    )


def render_native_command_profile(
    worktree: Any,
    owned_paths: Any,
) -> str:
    """Render the single native boundary used for every provider command.

    The Codex parent must remain outside this profile so it can reach the model
    service.  A digest-bound PreToolUse hook places only the model-requested
    command below this profile.  The global write deny covers create, data
    writes, unlink, rmdir, rename, and replacement before literal owned-path
    allows are considered.
    """
    root = Path(_canonical_absolute(worktree, label="worktree_canonical_path"))
    clauses = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
        '(allow file-write* (literal "/dev/null"))',
    ]
    for relative in _owned_paths(owned_paths):
        target = _canonical_seatbelt_path(root / relative)
        clauses.append(
            f'(allow file-write* (literal "{_seatbelt_quote(target)}"))'
        )
    scratch = native_command_scratch_path(str(root))
    clauses.append(
        f'(allow file-write* (literal "{_seatbelt_quote(scratch)}"))'
    )
    clauses.append(
        f'(allow file-write* (subpath "{_seatbelt_quote(scratch)}"))'
    )
    return " ".join(clauses)


def _hook_decision(
    decision: str,
    reason: str,
    *,
    updated_input: dict[str, str] | None = None,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason,
    }
    if updated_input is not None:
        output["updatedInput"] = updated_input
    return {"hookSpecificOutput": output}


def codex_pre_tool_hook_decision(
    payload: Any,
    *,
    profile_base64: Any,
    profile_sha256: Any,
    broker_sha256: Any,
    scratch_path: Any,
) -> dict[str, Any]:
    """Fail closed or rewrite one Codex command into the native boundary."""
    expected_profile_sha = _digest(
        profile_sha256, label="hook permission profile sha256"
    )
    expected_broker_sha = _digest(broker_sha256, label="hook broker sha256")
    broker_path = Path(__file__).resolve()
    if hashlib.sha256(broker_path.read_bytes()).hexdigest() != expected_broker_sha:
        return _hook_decision("deny", "native broker digest changed")
    if type(profile_base64) is not str:
        return _hook_decision("deny", "native profile encoding is invalid")
    try:
        profile_raw = base64.b64decode(
            profile_base64.encode("ascii", "strict"), validate=True
        )
        profile = profile_raw.decode("utf-8", "strict")
    except (UnicodeError, ValueError):
        return _hook_decision("deny", "native profile encoding is invalid")
    if hashlib.sha256(profile_raw).hexdigest() != expected_profile_sha:
        return _hook_decision("deny", "native profile digest changed")
    try:
        scratch = _canonical_seatbelt_path(scratch_path)
    except ProtocolError:
        return _hook_decision("deny", "native scratch path is invalid")
    if type(payload) is not dict:
        return _hook_decision("deny", "hook input is not an exact object")
    try:
        _ensure_plain(payload, label="hook input")
    except ProtocolError:
        return _hook_decision("deny", "hook input contains unsupported values")
    tool_input = payload.get("tool_input")
    if type(tool_input) is not dict:
        return _hook_decision("deny", "non-command provider tools are disabled")
    command = tool_input.get("command")
    if type(command) is not str or not command or "\x00" in command:
        return _hook_decision("deny", "non-command provider tools are disabled")
    wrapped = shlex.join(
        [
            NATIVE_SANDBOX_EXECUTABLE,
            "-p",
            profile,
            "/usr/bin/env",
            f"TMPDIR={scratch}",
            "PYTHONDONTWRITEBYTECODE=1",
            "GIT_CONFIG_GLOBAL=/dev/null",
            "GIT_CONFIG_NOSYSTEM=1",
            "/bin/zsh",
            "-f",
            "-c",
            command,
        ]
    )
    return _hook_decision(
        "allow",
        "command confined by digest-bound native profile",
        updated_input={"command": wrapped},
    )


def _codex_pre_tool_hook_command(
    *,
    profile_raw: bytes,
    broker_sha256: str,
    scratch_path: str,
) -> str:
    path = str(Path(__file__).resolve())
    arguments = [
        sys.executable,
        "-B",
        path,
        "--codex-pre-tool-hook",
        base64.b64encode(profile_raw).decode("ascii"),
        hashlib.sha256(profile_raw).hexdigest(),
        broker_sha256,
        scratch_path,
    ]
    return shlex.join(arguments)


def classify_native_profile_failure(returncode: Any, stderr: Any) -> str:
    """Classify provider-local setup failures without relabelling host policy."""
    code = _integer(returncode, label="native profile returncode", minimum=-255, maximum=255)
    if code == 0:
        return "none"
    if type(stderr) is not bytes:
        raise ProtocolError("native profile stderr must be raw bytes")
    surface = stderr.decode("utf-8", "replace").casefold()
    nested_markers = (
        "sandbox_apply: operation not permitted",
        "sandbox initialization failed: operation not permitted",
        "deny(1) file-write",
    )
    if any(marker in surface for marker in nested_markers):
        return "nested_sandbox_interference"
    return "native_profile_initialization"


def execute_native_profile_probe(
    request: Any,
    frozen: Any,
    *,
    evidence_path: Any,
    sandbox_executable: Any = "/usr/bin/sandbox-exec",
    python_executable: Any = sys.executable,
) -> dict[str, Any]:
    """Run the fixed probe matrix before provider work and fsync its evidence.

    A Seatbelt initialization failure is not relabelled as a successful target
    denial.  It produces a durable ``policy_pause`` record and fails closed.
    """
    valid_request = validate_request(request, frozen)
    validate_supported_git_layout(
        valid_request["worktree_canonical_path"],
        valid_request["git_common_dir_canonical_path"],
        owned_paths=valid_request["owned_paths"],
    )
    evidence = Path(_canonical_absolute(evidence_path, label="evidence_path"))
    sandbox = Path(_canonical_absolute(sandbox_executable, label="sandbox_executable"))
    interpreter = Path(_canonical_absolute(python_executable, label="python_executable"))
    probe_root = Path(
        tempfile.mkdtemp(prefix=".native-probe-", dir=evidence.parent)
    )
    try:
        existing_owned = probe_root / "owned-existing"
        new_owned = probe_root / "owned-new"
        nonowned = probe_root / "workspace-nonowned"
        slash_tmp = probe_root / "system-tmp-first-write"
        environment_tmp = probe_root / "environment-tmpdir-first-write"
        alias = probe_root / "owned-alias"
        alias_target = probe_root / "scope-outside-alias-target"
        pycache = probe_root / "scope-outside-pycache"
        network_observation = probe_root / "network-connect-must-not-create"
        parent_escape = probe_root / "scope-outside-owned-parent"
        sibling_escape = probe_root / "scope-outside-owned-sibling"
        git_common_write = probe_root / "scope-outside-git-common"
        unlink_file = probe_root / "unlink-nonowned-file"
        unlink_directory = probe_root / "unlink-nonowned-empty-directory"
        unlink_symlink = probe_root / "unlink-nonowned-symlink"
        unlink_symlink_target = probe_root / "unlink-symlink-target"
        git_control = probe_root / ".git" / "protected-control"
        codex_agent_control = probe_root / ".codex-agent" / "protected-control"
        owned_adjacent = probe_root / "owned-existing.adjacent"
        move_source = probe_root / "move-nonowned-source"
        move_destination = probe_root / "move-destination"
        replace_target = probe_root / "replace-nonowned-target"
        replace_source = probe_root / "replace-source"
        existing_owned.write_bytes(b"before")
        nonowned.write_bytes(b"sealed")
        alias.symlink_to(alias_target)
        unlink_file.write_bytes(b"unlink-sealed")
        unlink_directory.mkdir()
        unlink_symlink_target.write_bytes(b"symlink-target")
        unlink_symlink.symlink_to(unlink_symlink_target)
        git_control.parent.mkdir()
        git_control.write_bytes(b"git-control")
        codex_agent_control.parent.mkdir()
        codex_agent_control.write_bytes(b"codex-agent-control")
        owned_adjacent.write_bytes(b"adjacent")
        move_source.write_bytes(b"move-source")
        replace_target.write_bytes(b"replace-target")
        replace_source.write_bytes(b"replace-source")
        targets = {
            "existing_owned_write": existing_owned,
            "new_owned_create": new_owned,
            "workspace_nonowned": nonowned,
            "system_tmp": slash_tmp,
            "environment_tmpdir": environment_tmp,
            "owned_parent_escape": parent_escape,
            "owned_sibling_escape": sibling_escape,
            "git_common_write": git_common_write,
            "scope_outside_symlink": alias,
            "scope_outside_pycache": pycache,
            "network_socket": network_observation,
            "nonowned_unlink_file": unlink_file,
            "nonowned_unlink_empty_dir": unlink_directory,
            "nonowned_unlink_symlink": unlink_symlink,
            "git_control_unlink": git_control,
            "codex_agent_control_unlink": codex_agent_control,
            "owned_adjacent_unlink": owned_adjacent,
            "nonowned_move": move_source,
            "nonowned_replace": replace_target,
        }
        before = {name: _observation(path) for name, path in targets.items()}

        base_evidence = {
            "schema": NATIVE_EVIDENCE_SCHEMA,
            "request_sha256": valid_request["request_sha256"],
            "installed_descriptor_sha256": valid_request[
                "installed_descriptor_sha256"
            ],
            "runtime_generation": valid_request["runtime_generation"],
            "broker_sha256": valid_request["broker_sha256"],
            "permission_profile_bytes_sha256": valid_request[
                "permission_profile_bytes_sha256"
            ],
            "sandbox_executable": str(sandbox),
            "returncode": None,
            "stdout_sha256": hashlib.sha256(b"").hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            "observed_denial": False,
            "policy_pause": False,
            "execution_prevented": False,
            "provider_launch_prevented": False,
            "failure_domain": "none",
            "failure_reason": "",
            "nested_sandbox_interference": False,
            "probe_receipt": None,
        }
        try:
            _validate_native_probe_preconditions(before)
        except ProtocolError:
            base_evidence["policy_pause"] = True
            base_evidence["provider_launch_prevented"] = True
            base_evidence["failure_domain"] = "probe_precondition"
            base_evidence["failure_reason"] = "native probe precondition failed"
            _atomic_evidence(evidence, base_evidence)
            raise

        profile = render_native_command_profile(
            str(probe_root),
            ["owned-existing", "owned-new"],
        )
        # Destructive probes are deliberately first and operation-labelled, so
        # a denial from a later write/create cannot stand in for unlink proof.
        child = r'''
import json, os, socket, sys
(owned, owned_new, nonowned, slash_tmp, env_tmp, parent_escape,
 sibling_escape, git_common_write, alias, pycache, unlink_file,
 unlink_directory, unlink_symlink, git_control, codex_agent_control,
 owned_adjacent, move_source, move_destination, replace_target,
 replace_source) = sys.argv[1:]
outcomes = {}
def attempt(name, operation, action):
    try:
        action()
        outcomes[name] = operation + "_completed"
    except PermissionError:
        outcomes[name] = operation + "_permission_denied"
    except OSError:
        outcomes[name] = operation + "_operation_failed"
def write(name, operation, path, flags, data=b"x"):
    def action():
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    attempt(name, operation, action)
attempt("nonowned_unlink_file", "unlink", lambda: os.unlink(unlink_file))
attempt("nonowned_unlink_empty_dir", "unlink", lambda: os.rmdir(unlink_directory))
attempt("nonowned_unlink_symlink", "unlink", lambda: os.unlink(unlink_symlink))
attempt("git_control_unlink", "unlink", lambda: os.unlink(git_control))
attempt("codex_agent_control_unlink", "unlink", lambda: os.unlink(codex_agent_control))
attempt("owned_adjacent_unlink", "unlink", lambda: os.unlink(owned_adjacent))
attempt("nonowned_move", "rename", lambda: os.rename(move_source, move_destination))
attempt("nonowned_replace", "replace", lambda: os.replace(replace_source, replace_target))
def connect_loopback():
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(1)
    try:
        connection.connect(("127.0.0.1", 9))
    finally:
        connection.close()
attempt("network_socket", "connect", connect_loopback)
write("system_tmp", "create", slash_tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
if sys.pycache_prefix != pycache:
    outcomes["scope_outside_pycache"] = "create_operation_failed"
else:
    try:
        os.mkdir(pycache, 0o700)
        write(
            "scope_outside_pycache",
            "network_socket",
            "create",
            os.path.join(pycache, "first-write.pyc"),
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        )
    except PermissionError:
        outcomes["scope_outside_pycache"] = "create_permission_denied"
    except OSError:
        outcomes["scope_outside_pycache"] = "create_operation_failed"
write("existing_owned_write", "write", owned, os.O_WRONLY | os.O_APPEND)
write("new_owned_create", "create", owned_new, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
write("workspace_nonowned", "write", nonowned, os.O_WRONLY | os.O_APPEND)
write("environment_tmpdir", "create", env_tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
write("owned_parent_escape", "create", parent_escape, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
write("owned_sibling_escape", "create", sibling_escape, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
write("git_common_write", "create", git_common_write, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
write("scope_outside_symlink", "write", alias, os.O_WRONLY | os.O_CREAT)
print(json.dumps(outcomes, sort_keys=True, separators=(",", ":")))
'''
        child_environment = os.environ.copy()
        child_environment["PYTHONPYCACHEPREFIX"] = str(pycache)
        child_environment["TMPDIR"] = str(probe_root)
        completed = subprocess.run(
            [
                str(sandbox),
                "-p",
                profile,
                str(interpreter),
                "-c",
                child,
                str(existing_owned),
                str(new_owned),
                str(nonowned),
                str(slash_tmp),
                str(environment_tmp),
                str(parent_escape),
                str(sibling_escape),
                str(git_common_write),
                str(alias),
                str(pycache),
                str(unlink_file),
                str(unlink_directory),
                str(unlink_symlink),
                str(git_control),
                str(codex_agent_control),
                str(owned_adjacent),
                str(move_source),
                str(move_destination),
                str(replace_target),
                str(replace_source),
            ],
            capture_output=True,
            check=False,
            env=child_environment,
            timeout=20,
        )
        after = {name: _observation(path) for name, path in targets.items()}
        base_evidence["returncode"] = completed.returncode
        base_evidence["stdout_sha256"] = hashlib.sha256(completed.stdout).hexdigest()
        base_evidence["stderr_sha256"] = hashlib.sha256(completed.stderr).hexdigest()
        if completed.returncode != 0:
            base_evidence["policy_pause"] = True
            base_evidence["provider_launch_prevented"] = True
            failure_domain = classify_native_profile_failure(
                completed.returncode, completed.stderr
            )
            base_evidence["failure_domain"] = failure_domain
            base_evidence["failure_reason"] = (
                "outer host policy prevented nested Seatbelt initialization"
                if failure_domain == "nested_sandbox_interference"
                else "native Seatbelt profile failed to initialize"
            )
            base_evidence["nested_sandbox_interference"] = (
                failure_domain == "nested_sandbox_interference"
            )
            _atomic_evidence(evidence, base_evidence)
            raise ProtocolError(
                "native profile probe could not initialize; durable policy pause recorded"
            )
        try:
            outcomes = _parse_native_probe_stdout(completed.stdout)
            base_evidence["observed_denial"] = any(
                outcome.endswith("_permission_denied")
                for outcome in outcomes.values()
            )
            results = _native_probe_results(before, after, outcomes)
        except ProtocolError as exc:
            base_evidence["policy_pause"] = True
            base_evidence["provider_launch_prevented"] = True
            base_evidence["failure_domain"] = "probe_contradiction"
            base_evidence["failure_reason"] = "native probe evidence contradicted plan"
            _atomic_evidence(evidence, base_evidence)
            raise ProtocolError("native profile probe returned contradictory evidence") from exc
        receipt = build_probe_receipt(
            valid_request,
            frozen,
            results,
            probe_run_id=f"native-{os.getpid()}-{valid_request['nonce'][:16]}",
        )
        required = {
            "system_tmp",
            "owned_parent_escape",
            "owned_sibling_escape",
            "git_common_write",
            "scope_outside_pycache",
            "nonowned_unlink_file",
            "nonowned_unlink_empty_dir",
            "nonowned_unlink_symlink",
            "git_control_unlink",
            "codex_agent_control_unlink",
            "owned_adjacent_unlink",
            "nonowned_move",
            "nonowned_replace",
        }
        prevented_ids = {
            row["probe_id"] for row in results if row["execution_prevented"]
        }
        base_evidence["observed_denial"] = any(
            row["observed_denial"] for row in results
        )
        base_evidence["execution_prevented"] = required <= prevented_ids
        base_evidence["probe_receipt"] = receipt
        _atomic_evidence(evidence, base_evidence)
        if not base_evidence["execution_prevented"]:
            raise ProtocolError("required first writes were not prevented")
        return base_evidence
    finally:
        shutil.rmtree(probe_root, ignore_errors=True)


__all__ = [
    "MAX_PROTOCOL_JSON_BYTES",
    "MAX_STDERR_RAW_BYTES",
    "ProtocolError",
    "build_launch_plan",
    "build_probe_receipt",
    "build_profile_probe_plan",
    "build_provider_command",
    "build_provider_receipt",
    "build_request",
    "build_stderr_binding",
    "canonical_json_bytes",
    "load_plain_json",
    "stderr_binding_raw_bytes",
    "validate_probe_receipt",
    "validate_launch_plan",
    "validate_provider_command",
    "validate_provider_receipt",
    "validate_request",
    "validate_stderr_binding",
    "execute_native_profile_probe",
    "codex_pre_tool_hook_decision",
    "native_command_scratch_path",
    "permission_profile_bytes",
    "render_native_command_profile",
    "is_bounded_diagnostic_stream_target",
    "classify_native_profile_failure",
]


def _main() -> int:
    if sys.argv[1:2] == ["--codex-pre-tool-hook"]:
        if len(sys.argv) != 6:
            print("native broker hook arguments are invalid", file=sys.stderr)
            return 2
        raw = sys.stdin.buffer.read(MAX_HOOK_JSON_BYTES + 1)
        try:
            if len(raw) > MAX_HOOK_JSON_BYTES:
                raise ProtocolError("hook input exceeds the byte limit")
            payload = json.loads(raw.decode("utf-8", "strict"))
            decision = codex_pre_tool_hook_decision(
                payload,
                profile_base64=sys.argv[2],
                profile_sha256=sys.argv[3],
                broker_sha256=sys.argv[4],
                scratch_path=sys.argv[5],
            )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            decision = _hook_decision("deny", "native hook validation failed")
        sys.stdout.buffer.write(canonical_json_bytes(decision) + b"\n")
        return 0
    if sys.argv[1:] != ["--self-check"]:
        print(
            "usage: native_agent_broker.py --self-check | "
            "--codex-pre-tool-hook <profile-b64> <profile-sha> "
            "<broker-sha> <scratch>",
            file=sys.stderr,
        )
        return 2
    path = Path(__file__).resolve()
    payload = {
        "schema": "sulde-native-broker-self-check-v1",
        "broker_protocol_spec_version": BROKER_PROTOCOL_SPEC_VERSION,
        "broker_path": str(path),
        "broker_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "protocol_schemas": [
            REQUEST_SCHEMA,
            PROBE_PLAN_SCHEMA,
            PROBE_RECEIPT_SCHEMA,
            LAUNCH_PLAN_SCHEMA,
            PROVIDER_RECEIPT_SCHEMA,
            STDERR_BINDING_SCHEMA,
        ],
    }
    print(canonical_json_bytes(payload).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

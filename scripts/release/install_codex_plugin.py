#!/usr/bin/env python3
"""Install or upgrade Sulde for Codex and prove the installed runtime is usable."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import selectors
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Sequence
import uuid


# Installation verifies and executes staged Python entrypoints.  Neither the
# installer nor its Python children may add derived bytecode to immutable
# delivery/cache trees whose identity is digest-bound.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))
sys.path.insert(0, str(ROOT / "scripts" / "release"))
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
from command_template import split_command_template  # noqa: E402
from python_environment import (PythonEnvironmentError, inspect_python, invoking_environment,
                                same_runtime, validate_python)  # noqa: E402
from codex_cli_contract import (  # noqa: E402
    DEFAULT_CODEX_EXECUTABLE,
    NATIVE_AUTHORITY_SPEC_VERSION,
    AUDITED_CODEX_VERSION,
    CodexCliContractError,
    canonical_codex_help_observation,
    codex_probe_environment,
    codex_probe_spec,
    successful_version_identity,
)
from host_capabilities import (  # noqa: E402
    HostCapabilityError,
    readiness_projection,
    validate_artifact,
)
from install_transaction_journal import (  # noqa: E402
    JournalError,
    Transaction,
    begin_transaction,
    load_active_transaction,
)
from knowledge_history import HistoryError, load_history  # noqa: E402
from sulde_paths import (  # noqa: E402
    kb_home as canonical_kb_home,
    launcher_home as canonical_launcher_home,
)
from sulde_paths import layout as sulde_layout  # noqa: E402
from sulde_home_migration import (  # noqa: E402
    QUIESCENCE_SCHEMA,
    MigrationError as HomeMigrationError,
    apply as apply_home_migration,
    ensure_contract_identity_map,
    rollback as rollback_home_migration,
)
from memory_home_reconcile import (  # noqa: E402
    MemoryReconcileError,
    plan as plan_memory_reconciliation,
    reconcile as reconcile_memory_homes,
    restore_legacy_write_mode,
)

STAGER = ROOT / "scripts" / "release" / "stage_plugin.py"
MARKETPLACE_NAME = "sulde-local"
PLUGIN_SELECTOR = "sulde@sulde-local"
REQUIRED_CODEX_HOOK_EVENTS = (
    "preToolUse",
    "permissionRequest",
    "postToolUse",
    "sessionStart",
    "userPromptSubmit",
    "stop",
)
LAUNCHER_NAMES = (
    "sulde-statusline.py",
    "kb-index",
    "sulde-kb-mcp",
    "mem-sync",
    "model-dispatch",
    "intent-guardian",
    ".sulde-launchers.json",
    ".sulde-command-effects.json",
)
LIVE_SESSION_BRIDGE_FILES = (
    Path("scripts/run-hook.sh"),
    Path("scripts/run-hook.ps1"),
)
DEPLOYMENT_LOCK_NAME = ".deployment.lock"
DEPLOYMENT_GENERATION_NAME = "deployment-generation.json"
RUNTIME_OWNER_NAME = "runtime-owner.json"
INSTALL_RECOVERY_NAME = ".install-recovery"
DELIVERY_GENERATION_SCHEMA = "sulde-delivery-generation-v1"
DELIVERY_GENERATION_NAME = "generation.json"
NATIVE_AUTHORITY_SCHEMA = "sulde-installed-native-runtime-authority-v1"
CANDIDATE_RECEIPT_SCHEMA = "sulde-codex-candidate-verification-v1"
PERMISSION_PROFILE_SPEC_VERSION = 4
BROKER_PROTOCOL_SPEC_VERSION = 2
INSTALLER_NATIVE_RUNTIME_INVENTORY = (
    (Path("scripts/kb/agent-runtime.py"), 0o755),
    (Path("scripts/kb/codex_cli_contract.py"), 0o644),
    (Path("scripts/kb/native_agent_broker.py"), 0o644),
)
RETIRED_SCHEDULER_LABELS = frozenset(
    {
        "com.sulde.codex-cache-repair",
        "com.sulde.kb-weekly-calibrate",
    }
)


class InstallError(RuntimeError):
    """The install transaction failed or its evidence is incomplete."""


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., CommandResult]


@dataclass(frozen=True)
class LegacyPluginSource:
    """One old cache path and the bytes used to reconstruct it after a switch."""

    target: Path
    source: Path
    mode: str


@dataclass(frozen=True)
class WarmTreeState:
    """Validated mutable cache state, distinct from an immutable release tree."""

    tree_sha256: str
    normalized_tree_sha256: str
    bytecode_inventory: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PreparedArtifact:
    """Validated immutable artifact evidence reusable inside one install lock."""

    marketplace: Path
    descriptor: dict[str, Any]
    plugin_tree_sha256: str


@dataclass(frozen=True)
class CacheRetirement:
    alias: Path
    target: Path
    source: Path
    prestate: WarmTreeState
    expected_tree_sha256: str
    record: Path
    alias_preexisting: bool
    preexisting_target: Path | None


def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (LookupError, OSError):
                pass


def run_command(
    command: Sequence[str],
    *,
    input_text: str | None = None,
    environment: dict[str, str] | None = None,
    cwd: Path | None = None,
    timeout: float = 180,
    check: bool = True,
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            input=input_text,
            env=environment,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InstallError(f"command unavailable: {' '.join(command)}: {error}") from error
    result = CommandResult(
        tuple(str(value) for value in command),
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise InstallError(
            f"command failed exit={result.returncode}: {' '.join(result.command)}: {detail}"
        )
    return result


def _json_output(result: CommandResult) -> dict[str, Any]:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise InstallError(
            f"command returned invalid JSON: {' '.join(result.command)}: {detail}"
        ) from error
    if not isinstance(payload, dict):
        raise InstallError(f"command returned a non-object: {' '.join(result.command)}")
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InstallError(f"invalid JSON file: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise InstallError(f"JSON root must be an object: {path}")
    return payload


def tree_digest(root: Path) -> str:
    """Hash every regular file and reject mutable/executable side channels."""
    if root.is_symlink() or not root.is_dir():
        raise InstallError(f"plugin tree is missing or linked: {root}")
    if any(path.name == ".git" for path in root.rglob(".git")):
        raise InstallError(f"plugin tree contains repository metadata: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        try:
            metadata = path.lstat()
        except OSError as error:
            raise InstallError(f"plugin tree entry is unreadable: {path}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise InstallError(f"plugin tree contains a symlink: {path}")
        relative_parts = path.relative_to(root).parts
        if "__pycache__" in relative_parts or path.suffix.casefold() == ".pyc":
            raise InstallError(f"plugin tree contains executable Python bytecode: {path}")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise InstallError(f"plugin tree contains a non-regular entry: {path}")
        if metadata.st_nlink != 1:
            raise InstallError(f"plugin tree contains an ambiguous hard link: {path}")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _digest_tree_entries(
    entries: Sequence[tuple[str, str, int, bytes | None]],
) -> str:
    digest = hashlib.sha256()
    for relative, kind, mode, content in entries:
        encoded = relative.encode("utf-8", "strict")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(kind.encode("ascii"))
        digest.update(mode.to_bytes(4, "big"))
        if content is not None:
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
    return digest.hexdigest()


def warm_tree_state(root: Path) -> WarmTreeState:
    """Validate a cache tree while admitting only Python-derived bytecode.

    Immutable release validation deliberately rejects bytecode.  A cache that
    has already executed is different: CPython may have added regular ``.pyc``
    files below ``__pycache__``.  Those bytes and their modes are part of the
    rollback prestate, but are excluded from the normalized pinned tree.
    """

    root = root.expanduser()
    if root.is_symlink() or not root.is_dir():
        raise InstallError(f"warm plugin tree is missing or linked: {root}")
    all_entries: list[tuple[str, str, int, bytes | None]] = []
    normalized: list[tuple[str, str, int, bytes | None]] = []
    bytecode: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        try:
            metadata = path.lstat()
        except OSError as error:
            raise InstallError(f"warm plugin tree entry is unreadable: {path}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise InstallError(f"warm plugin tree contains a symlink: {path}")
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        in_pycache = "__pycache__" in relative_path.parts
        mode = stat.S_IMODE(metadata.st_mode)
        if stat.S_ISDIR(metadata.st_mode):
            entry = (relative, "directory", mode, None)
            all_entries.append(entry)
            if not in_pycache:
                normalized.append(entry)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise InstallError(f"warm plugin tree contains a non-regular entry: {path}")
        if metadata.st_nlink != 1:
            raise InstallError(f"warm plugin tree contains an ambiguous hard link: {path}")
        if in_pycache and path.suffix.casefold() != ".pyc":
            raise InstallError(f"warm plugin tree contains an unknown derived item: {path}")
        if path.suffix.casefold() == ".pyc" and not in_pycache:
            raise InstallError(f"warm plugin tree contains unscoped Python bytecode: {path}")
        content = path.read_bytes()
        entry = (relative, "file", mode, content)
        all_entries.append(entry)
        if in_pycache:
            bytecode.append(
                {
                    "path": relative,
                    "mode": mode,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        else:
            normalized.append(entry)
    return WarmTreeState(
        tree_sha256=_digest_tree_entries(all_entries),
        normalized_tree_sha256=_digest_tree_entries(normalized),
        bytecode_inventory=tuple(bytecode),
    )


def _remove_derived_bytecode(root: Path) -> tuple[str, ...]:
    """Normalize one copied warm tree without touching its static bytes."""

    before = warm_tree_state(root)
    removed = tuple(row["path"] for row in before.bytecode_inventory)
    for directory in sorted(
        (path for path in root.rglob("__pycache__") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        shutil.rmtree(directory)
    after = warm_tree_state(root)
    if after.bytecode_inventory or after.tree_sha256 != before.normalized_tree_sha256:
        raise InstallError(f"warm plugin tree normalization did not verify: {root}")
    return removed


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8", "strict")


def _permission_profile_spec() -> dict[str, Any]:
    return {
        "schema": "sulde-codex-permission-profile-spec-v1",
        "spec_version": PERMISSION_PROFILE_SPEC_VERSION,
        "profile_name": "sulde-owned-paths",
        "codex_parent_sandbox": "danger-full-access",
        "command_boundary": "pre-tool-use-updated-input-single-seatbelt-v1",
        "shell_startup_policy": "sealed-empty-zdotdir-v1",
        "non_command_write_tools": "deny",
        "filesystem_default_write": "deny",
        "owned_path_permission": "literal-file-write-star",
        "scratch_permission": "codex-agent-native-command-scratch-subpath",
        "network_enabled": False,
        "path_rendering": "physical-canonical-exact-owned-full-clone-v4",
        "native_destructive_boundary": "global-file-write-star-deny-v1",
    }


def _codex_help_contract() -> dict[str, Any]:
    return {
        "schema": "sulde-codex-cli-help-contract-v1",
        "codex_version": AUDITED_CODEX_VERSION,
        "global_required": ["--config", "--strict-config"],
        "exec_required": [
            "--ignore-user-config",
            "--ignore-rules",
            "--dangerously-bypass-hook-trust",
            "--config",
            "--strict-config",
        ],
        "app_server_required": ["--config", "--strict-config", "--listen"],
        "initialize_protocol": "jsonl-stdio-v1",
    }


def _app_server_initialize_handshake(
    command: Sequence[str],
    *,
    environment: dict[str, str],
    timeout: float = 15,
) -> CommandResult:
    """Complete the JSONL initialize handshake before sending notifications.

    ``subprocess.run(input=...)`` closes stdin after a bulk write and can make a
    server exit zero without ever proving it consumed initialize.  Keep stdin
    open, flush exactly initialize first, and only publish ``initialized``
    after the matching successful response is observed.
    """

    rendered = tuple(str(value) for value in command)
    try:
        process = subprocess.Popen(
            list(rendered),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            bufsize=0,
        )
    except OSError as error:
        raise InstallError(
            f"command unavailable: {' '.join(rendered)}: {error}"
        ) from error
    initialize_id = 0
    request = (
        json.dumps(
            {
                "method": "initialize",
                "id": initialize_id,
                "params": {
                    "clientInfo": {
                        "name": "sulde_installer",
                        "title": "Sulde installed smoke",
                        "version": "1",
                    }
                },
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8", "strict")
    observed_stdout = bytearray()
    observed_stderr = bytearray()
    pending_stdout = bytearray()
    deadline = time.monotonic() + timeout
    matched = False
    try:
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(request)
        process.stdin.flush()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        assert process.stderr is not None
        selector.register(process.stderr, selectors.EVENT_READ)
        try:
            while time.monotonic() < deadline:
                remaining = max(0.0, deadline - time.monotonic())
                events = selector.select(min(remaining, 0.1))
                if not events:
                    if process.poll() is not None:
                        break
                    continue
                for key, _mask in events:
                    chunk = os.read(key.fd, 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.fileobj is process.stderr:
                        observed_stderr.extend(chunk)
                        continue
                    observed_stdout.extend(chunk)
                    pending_stdout.extend(chunk)
                    while b"\n" in pending_stdout:
                        raw_line, _, remainder = pending_stdout.partition(b"\n")
                        pending_stdout[:] = remainder
                        try:
                            response = json.loads(raw_line.decode("utf-8", "strict"))
                        except (UnicodeError, json.JSONDecodeError):
                            continue
                        if (
                            not isinstance(response, dict)
                            or response.get("id") != initialize_id
                        ):
                            continue
                        if "error" in response or not isinstance(
                            response.get("result"), dict
                        ):
                            raise InstallError(
                                "installed Codex app-server initialize returned an error"
                            )
                        matched = True
                        break
                    if matched:
                        break
                if matched:
                    break
        finally:
            selector.close()
        if not matched:
            raise InstallError("installed Codex app-server initialize response timed out")
        notification = (
            json.dumps(
                {"method": "initialized", "params": {}},
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8", "strict")
        process.stdin.write(notification)
        process.stdin.flush()
        process.stdin.close()
        process.stdin = None
        remaining = max(0.1, deadline - time.monotonic())
        tail, stderr = process.communicate(timeout=remaining)
        observed_stdout.extend(tail)
        observed_stderr.extend(stderr)
        if process.returncode != 0:
            detail = observed_stderr.decode("utf-8", "replace").strip()[-1000:]
            raise InstallError(
                f"installed Codex app-server exited {process.returncode}: {detail}"
            )
        return CommandResult(
            rendered,
            process.returncode,
            observed_stdout.decode("utf-8", "replace"),
            observed_stderr.decode("utf-8", "replace"),
        )
    except subprocess.TimeoutExpired as error:
        raise InstallError("installed Codex app-server shutdown timed out") from error
    except OSError as error:
        raise InstallError("installed Codex app-server handshake failed") from error
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _app_server_hooks_list(
    codex: Path,
    *,
    cwd: Path,
    timeout: float = 15,
) -> dict[str, Any]:
    """Read effective Hooks without changing trust.

    Codex app-server may maintain its own SQLite state while serving the
    request, so this is not described as a zero-write host process.  The
    bounded guarantee is that Sulde neither calls ``config/batchWrite`` nor
    supplies a trust bypass while observing the inventory.
    """

    rendered = (str(codex), "app-server", "--listen", "stdio://")
    try:
        process = subprocess.Popen(
            list(rendered),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            bufsize=0,
        )
    except OSError as error:
        raise InstallError("Codex Hook inventory app-server could not start") from error

    observed_stderr = bytearray()
    pending_stdout = bytearray()
    deadline = time.monotonic() + timeout
    initialize_id = 0
    hooks_list_id = 1
    hooks_result: dict[str, Any] | None = None

    def send(payload: dict[str, Any]) -> None:
        assert process.stdin is not None
        process.stdin.write(
            (
                json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
                + "\n"
            ).encode("utf-8", "strict")
        )
        process.stdin.flush()

    try:
        assert process.stdout is not None
        assert process.stderr is not None
        send(
            {
                "method": "initialize",
                "id": initialize_id,
                "params": {
                    "clientInfo": {
                        "name": "sulde_installer",
                        "title": "Sulde Hook trust inventory",
                        "version": "1",
                    }
                },
            }
        )
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        initialized = False
        try:
            while time.monotonic() < deadline and hooks_result is None:
                remaining = max(0.0, deadline - time.monotonic())
                events = selector.select(min(remaining, 0.1))
                if not events:
                    if process.poll() is not None:
                        break
                    continue
                for key, _mask in events:
                    chunk = os.read(key.fd, 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.fileobj is process.stderr:
                        observed_stderr.extend(chunk)
                        continue
                    pending_stdout.extend(chunk)
                    while b"\n" in pending_stdout:
                        raw_line, _, remainder = pending_stdout.partition(b"\n")
                        pending_stdout[:] = remainder
                        try:
                            response = json.loads(raw_line.decode("utf-8", "strict"))
                        except (UnicodeError, json.JSONDecodeError):
                            continue
                        if not isinstance(response, dict):
                            continue
                        if response.get("id") == initialize_id and not initialized:
                            if "error" in response or not isinstance(
                                response.get("result"), dict
                            ):
                                raise InstallError(
                                    "Codex Hook inventory initialize returned an error"
                                )
                            send({"method": "initialized", "params": {}})
                            send(
                                {
                                    "method": "hooks/list",
                                    "id": hooks_list_id,
                                    "params": {"cwds": [str(cwd.resolve())]},
                                }
                            )
                            initialized = True
                            continue
                        if response.get("id") == hooks_list_id:
                            if "error" in response or not isinstance(
                                response.get("result"), dict
                            ):
                                raise InstallError(
                                    "Codex Hook inventory request returned an error"
                                )
                            hooks_result = response["result"]
                            break
                    if hooks_result is not None:
                        break
        finally:
            selector.close()
        if hooks_result is None:
            detail = observed_stderr.decode("utf-8", "replace").strip()[-1000:]
            suffix = f": {detail}" if detail else ""
            raise InstallError(f"Codex Hook inventory timed out{suffix}")
        return hooks_result
    except OSError as error:
        raise InstallError("Codex Hook inventory protocol failed") from error
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def _codex_hook_trust_projection(
    payload: dict[str, Any],
    *,
    cwd: Path,
) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise InstallError("Codex Hook inventory response has no data list")
    expected_cwd = cwd.resolve()
    matches = [
        row
        for row in data
        if isinstance(row, dict)
        and isinstance(row.get("cwd"), str)
        and Path(row["cwd"]).resolve() == expected_cwd
    ]
    if len(matches) != 1:
        raise InstallError("Codex Hook inventory did not return exactly one requested cwd")
    inventory = matches[0]
    hooks = inventory.get("hooks")
    errors = inventory.get("errors")
    warnings = inventory.get("warnings")
    if not isinstance(hooks, list) or not isinstance(errors, list) or not isinstance(
        warnings, list
    ):
        raise InstallError("Codex Hook inventory response is malformed")

    plugin_hooks = [
        hook
        for hook in hooks
        if isinstance(hook, dict) and hook.get("pluginId") == PLUGIN_SELECTOR
    ]
    post_tool_owners = [
        {
            "plugin_id": str(hook.get("pluginId") or "workspace-or-user-hook"),
            "key": str(hook.get("key") or ""),
            "enabled": hook.get("enabled") is True,
            "trust_status": str(hook.get("trustStatus") or "unknown"),
            "current_hash": str(hook.get("currentHash") or ""),
        }
        for hook in hooks
        if isinstance(hook, dict) and hook.get("eventName") == "postToolUse"
    ]
    observed: list[dict[str, Any]] = []
    missing_events: list[str] = []
    duplicate_events: list[str] = []
    unrunnable_events: list[str] = []
    for event_name in REQUIRED_CODEX_HOOK_EVENTS:
        event_hooks = [
            hook for hook in plugin_hooks if hook.get("eventName") == event_name
        ]
        if not event_hooks:
            missing_events.append(event_name)
            continue
        if len(event_hooks) != 1:
            duplicate_events.append(event_name)
        for hook in event_hooks:
            trust_status = hook.get("trustStatus")
            enabled = hook.get("enabled")
            handler_type = hook.get("handlerType")
            if (
                enabled is not True
                or trust_status not in {"trusted", "managed"}
                or handler_type != "command"
                or hook.get("source") != "plugin"
            ):
                unrunnable_events.append(event_name)
            observed.append(
                {
                    "event_name": event_name,
                    "key": hook.get("key"),
                    "enabled": enabled,
                    "handler_type": handler_type,
                    "source": hook.get("source"),
                    "trust_status": trust_status,
                    "current_hash": hook.get("currentHash"),
                }
            )

    discovery_errors = errors
    ready = not (
        missing_events
        or duplicate_events
        or unrunnable_events
        or discovery_errors
    )
    return {
        "schema": "sulde-codex-hook-trust-v1",
        "status": "ready" if ready else "review_required",
        "authority": "codex_hooks_list_no_trust_write",
        "plugin_id": PLUGIN_SELECTOR,
        "cwd": str(expected_cwd),
        "required_events": list(REQUIRED_CODEX_HOOK_EVENTS),
        "observed_hooks": observed,
        "missing_events": missing_events,
        "duplicate_events": sorted(set(duplicate_events)),
        "unrunnable_events": sorted(set(unrunnable_events)),
        "discovery_errors": discovery_errors,
        "warnings": warnings,
        "post_tool_hook_owners": post_tool_owners,
        "post_tool_hook_owner_count": len(post_tool_owners),
        "trust_write_performed": False,
        "host_state_runtime_may_write": True,
    }


def _codex_hook_trust_observation(codex: Path, *, cwd: Path) -> dict[str, Any]:
    try:
        payload = _app_server_hooks_list(codex, cwd=cwd)
        return _codex_hook_trust_projection(payload, cwd=cwd)
    except InstallError as error:
        return {
            "schema": "sulde-codex-hook-trust-v1",
            "status": "unavailable",
            "authority": "codex_hooks_list_no_trust_write",
            "plugin_id": PLUGIN_SELECTOR,
            "cwd": str(cwd.resolve()),
            "required_events": list(REQUIRED_CODEX_HOOK_EVENTS),
            "reason": str(error),
            "post_tool_hook_owners": [],
            "post_tool_hook_owner_count": 0,
            "trust_write_performed": False,
            "host_state_runtime_may_write": True,
        }


def _codex_cli_installed_smoke(codex: Path, runner: Runner) -> dict[str, str]:
    probe_spec = codex_probe_spec(os.environ)
    version = runner(
        [str(codex), "--version"],
        check=False,
        timeout=15,
        input_text=probe_spec.stdin,
        environment=probe_spec.environment,
    )
    version_identity = successful_version_identity(
        version.returncode, version.stdout
    )
    if version_identity != AUDITED_CODEX_VERSION:
        raise InstallError(
            f"installed Codex version is not exactly {AUDITED_CODEX_VERSION}"
        )
    helps = (
        runner(
            [str(codex), "--help"],
            check=False,
            timeout=15,
            input_text=probe_spec.stdin,
            environment=probe_spec.environment,
        ),
        runner(
            [str(codex), "exec", "--help"],
            check=False,
            timeout=15,
            input_text=probe_spec.stdin,
            environment=probe_spec.environment,
        ),
        runner(
            [str(codex), "app-server", "--help"],
            check=False,
            timeout=15,
            input_text=probe_spec.stdin,
            environment=probe_spec.environment,
        ),
    )
    try:
        canonical_surfaces, help_observation_sha256 = (
            canonical_codex_help_observation(
                tuple((row.returncode, row.stdout, row.stderr) for row in helps)
            )
        )
    except CodexCliContractError as error:
        raise InstallError(
            f"installed Codex help surface drifted from the {AUDITED_CODEX_VERSION} contract"
        ) from error
    surfaces = tuple(surface.decode("utf-8", "strict") for surface in canonical_surfaces)
    requirements = _codex_help_contract()
    required_sets = (
        requirements["global_required"],
        requirements["exec_required"],
        requirements["app_server_required"],
    )
    if any(
        any(token not in surface for token in required)
        for surface, required in zip(surfaces, required_sets)
    ):
        raise InstallError(
            f"installed Codex help surface drifted from the {AUDITED_CODEX_VERSION} contract"
        )
    profile = (
        '{filesystem={":minimal"="read",":tmpdir"="deny",'
        '":slash_tmp"="deny",":workspace_roots"={"."="read",'
        '"installed-smoke-owned"="write"}},network={enabled=false}}'
    )
    profile_arguments = [
        "-c",
        'default_permissions="sulde-owned-paths"',
        "-c",
        f"permissions.sulde-owned-paths={profile}",
    ]
    parsed = runner(
        [
            str(codex),
            "exec",
            "--ignore-user-config",
            "--strict-config",
            "--dangerously-bypass-hook-trust",
            *profile_arguments,
            "-c",
            (
                'hooks.PreToolUse=[{matcher=".*",hooks=['
                '{type="command",command="/usr/bin/true",timeout=1}]}]'
            ),
            "--help",
        ],
        check=False,
        timeout=15,
        input_text=probe_spec.stdin,
        environment=probe_spec.environment,
    )
    if parsed.returncode != 0:
        raise InstallError(
            "installed Codex rejected the exact strict profile and hook contract"
        )
    with tempfile.TemporaryDirectory(prefix="sulde-codex-smoke-") as codex_home:
        environment = os.environ.copy()
        environment["CODEX_HOME"] = codex_home
        initialized = _app_server_initialize_handshake(
            [
                str(codex),
                "app-server",
                "--strict-config",
                *profile_arguments,
                "--listen",
                "stdio://",
            ],
            environment=environment,
            timeout=15,
        )
    return {
        "version": AUDITED_CODEX_VERSION,
        "help_observation_sha256": help_observation_sha256,
    }


def _installed_native_runtime_authority(
    installed_plugin: Path,
    sealed_generation: dict[str, Any],
    *,
    registry_codex: str,
    runner: Runner,
) -> dict[str, Any]:
    test_mode = os.environ.get("SULDE_TEST_MODE") == "1"
    codex = Path(registry_codex).expanduser()
    if not codex.is_absolute():
        resolved_name = shutil.which(str(codex))
        if not resolved_name:
            raise InstallError("Codex executable cannot be resolved for native authority")
        codex = Path(resolved_name)
    try:
        resolved_codex = codex.resolve(strict=True)
    except OSError as error:
        raise InstallError(f"Codex executable cannot be sealed: {codex}") from error
    if not resolved_codex.is_file():
        raise InstallError(f"Codex executable target is not a regular file: {resolved_codex}")
    executable_sha256 = hashlib.sha256(resolved_codex.read_bytes()).hexdigest()
    if test_mode:
        stable_codex_executable = str(resolved_codex)
        cli_smoke = {
            "version": AUDITED_CODEX_VERSION,
            "help_observation_sha256": hashlib.sha256(
                b"synthetic-test-cli-help-observation"
            ).hexdigest(),
        }
    else:
        # The approved installation selects this target once. Production
        # execution and recovery bind its canonical path and exact bytes;
        # they must not select a new executable from ambient PATH later.
        stable_codex_executable = str(resolved_codex)
        cli_smoke = _codex_cli_installed_smoke(resolved_codex, runner)
        if (codex.resolve(strict=True) != resolved_codex
                or hashlib.sha256(resolved_codex.read_bytes()).hexdigest()
                != executable_sha256):
            raise InstallError("Codex executable changed during native identity probes")
    runtime_root = installed_plugin / "runtime"
    agent_runtime = runtime_root / "scripts" / "kb" / "agent-runtime.py"
    codex_cli_contract = runtime_root / "scripts" / "kb" / "codex_cli_contract.py"
    broker = runtime_root / "scripts" / "kb" / "native_agent_broker.py"
    for label, path in (
        ("agent runtime", agent_runtime),
        ("Codex CLI contract", codex_cli_contract),
        ("native broker", broker),
    ):
        if path.is_symlink() or not path.is_file():
            raise InstallError(f"installed {label} is not a regular file: {path}")
    broker_smoke = runner(
        [sys.executable, str(broker), "--self-check"],
        check=False,
        timeout=15,
    )
    try:
        broker_payload = json.loads(broker_smoke.stdout)
    except json.JSONDecodeError as error:
        raise InstallError("installed native broker self-check returned invalid JSON") from error
    broker_sha = hashlib.sha256(broker.read_bytes()).hexdigest()
    if (
        broker_smoke.returncode != 0
        or not isinstance(broker_payload, dict)
        or broker_payload.get("schema") != "sulde-native-broker-self-check-v1"
        or broker_payload.get("broker_protocol_spec_version")
        != BROKER_PROTOCOL_SPEC_VERSION
        or broker_payload.get("broker_sha256") != broker_sha
        or Path(str(broker_payload.get("broker_path"))) != broker.resolve()
    ):
        raise InstallError("installed native broker executable smoke did not verify")
    if (codex.resolve(strict=True) != resolved_codex
            or hashlib.sha256(resolved_codex.read_bytes()).hexdigest()
            != executable_sha256):
        raise InstallError("Codex executable changed before native authority sealing")
    authority = {
        "schema": NATIVE_AUTHORITY_SCHEMA,
        "spec_version": NATIVE_AUTHORITY_SPEC_VERSION,
        "provider": "codex",
        "production_codex_executable": stable_codex_executable,
        "production_codex_resolved_executable": str(resolved_codex),
        "codex_version": cli_smoke["version"],
        "codex_executable_sha256": executable_sha256,
        "codex_help_contract_sha256": hashlib.sha256(
            _canonical_json_bytes(_codex_help_contract())
        ).hexdigest(),
        "codex_help_observation_sha256": cli_smoke["help_observation_sha256"],
        "permission_profile_spec_version": PERMISSION_PROFILE_SPEC_VERSION,
        "permission_profile_spec_sha256": hashlib.sha256(
            _canonical_json_bytes(_permission_profile_spec())
        ).hexdigest(),
        "broker_protocol_spec_version": BROKER_PROTOCOL_SPEC_VERSION,
        "broker_path": str(broker.resolve()),
        "broker_sha256": broker_sha,
        "agent_runtime_path": str(agent_runtime.resolve()),
        "agent_runtime_sha256": hashlib.sha256(agent_runtime.read_bytes()).hexdigest(),
        "codex_cli_contract_path": str(codex_cli_contract.resolve()),
        "codex_cli_contract_sha256": hashlib.sha256(
            codex_cli_contract.read_bytes()
        ).hexdigest(),
        "runtime_generation": sealed_generation["generation"],
        "runtime_tree_sha256": sealed_generation["runtime_tree_sha256"],
    }
    authority["authority_sha256"] = hashlib.sha256(
        _canonical_json_bytes(authority)
    ).hexdigest()
    return authority


def product_version(root: Path = ROOT) -> str:
    value = _read_json(root / ".claude-plugin" / "plugin.json").get("version")
    if not isinstance(value, str) or not value:
        raise InstallError("product version is missing")
    return value


def plugin_version(root: Path = ROOT) -> str:
    value = _read_json(
        root / "integrations" / "codex" / "plugins" / "sulde" / ".codex-plugin" / "plugin.json"
    ).get("version")
    if not isinstance(value, str) or not value:
        raise InstallError("Codex plugin version is missing")
    return value


def default_artifact_root(root: Path = ROOT) -> Path:
    product = re.sub(r"[^0-9A-Za-z._-]+", "-", product_version(root))
    plugin = re.sub(r"[^0-9A-Za-z._-]+", "-", plugin_version(root))
    return Path.home() / ".sulde" / "artifacts" / f"sulde-{product}-{plugin}" / "codex"


def default_kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return canonical_kb_home()


def launcher_home(kb_home: Path) -> Path:
    """Return the provider-neutral product root for public launchers.

    Explicit non-default KB homes retain the historic ``<kb>/bin`` layout so
    isolated tests and portable deployments remain self-contained.
    """
    return canonical_launcher_home(kb_home)


def deployment_lock_dir(kb_home: Path) -> Path:
    resolved = kb_home.expanduser().resolve(strict=False)
    neutral_root = Path(os.environ.get("SULDE_HOME") or Path.home() / ".sulde")
    neutral_kb = (neutral_root / "data" / "kb").expanduser().resolve(strict=False)
    if resolved == neutral_kb:
        return launcher_home(kb_home) / "control" / "deployment.lock"
    return resolved / DEPLOYMENT_LOCK_NAME


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def _canonical_cache_root() -> Path:
    return (
        default_codex_home()
        / "plugins"
        / "cache"
        / MARKETPLACE_NAME
        / "sulde"
    )


def _canonical_cache_path(version: str) -> Path:
    if not version or Path(version).name != version or version in {".", ".."}:
        raise InstallError(f"unsafe installed plugin version: {version!r}")
    return _canonical_cache_root() / version


def _is_cache_enumeration_child(path: Path) -> bool:
    lexical = Path(os.path.abspath(str(path.expanduser())))
    root = Path(os.path.abspath(str(_canonical_cache_root())))
    return lexical.parent == root


def _stable_jsonl_snapshot(
    path: Path,
    *,
    attempts: int = 5,
    retry_delay: float = 0.02,
) -> dict[str, Any]:
    """Read append-only JSONL without treating a concurrent tail as corruption."""

    if attempts < 2:
        raise ValueError("stable JSONL reads require at least two attempts")
    prior_raw: bytes | None = None
    changed = False
    complete_records: list[dict[str, Any]] = []
    for index in range(attempts):
        try:
            before = path.lstat()
            if (
                stat.S_ISLNK(before.st_mode)
                or not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
            ):
                raise InstallError(f"session JSONL is not an unambiguous regular file: {path}")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
            try:
                current = os.fstat(descriptor)
                if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                    changed = True
                    continue
                chunks: list[bytes] = []
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks)
            finally:
                os.close(descriptor)
            after = path.lstat()
        except OSError as error:
            raise InstallError(f"session JSONL cannot be read safely: {path}: {error}") from error
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            changed = True
            prior_raw = raw
            if index + 1 < attempts:
                time.sleep(retry_delay)
            continue
        lines = raw.splitlines(keepends=True)
        trailing_partial = bool(lines and not lines[-1].endswith(b"\n"))
        parsed: list[dict[str, Any]] = []
        complete = lines[:-1] if trailing_partial else lines
        for line_number, line in enumerate(complete, 1):
            if not line.strip():
                raise InstallError(
                    f"session JSONL contains an empty structural record: {path}:{line_number}"
                )
            try:
                record = json.loads(line.decode("utf-8", "strict"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise InstallError(
                    f"session JSONL is structurally damaged: {path}:{line_number}"
                ) from error
            if not isinstance(record, dict):
                raise InstallError(
                    f"session JSONL record is not an object: {path}:{line_number}"
                )
            parsed.append(record)
        complete_records = parsed
        if not trailing_partial:
            return {
                "records": parsed,
                "status": "stable",
                "attempts": index + 1,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        if prior_raw is not None and raw != prior_raw:
            changed = True
        elif prior_raw == raw:
            raise InstallError(f"session JSONL has a stable damaged tail: {path}")
        prior_raw = raw
        if index + 1 < attempts:
            time.sleep(retry_delay)
    if changed:
        return {
            "records": complete_records,
            "status": "concurrent_tail_ignored",
            "attempts": attempts,
            "sha256": None,
        }
    raise InstallError(f"session JSONL has a stable damaged tail: {path}")


def _observe_peer_session_safety() -> dict[str, Any]:
    """Observe peer-session file identity without replaying historical logs.

    Session contents do not determine whether a plugin generation can be
    installed, and replaying every historical JSONL made unrelated history a
    serial success-path dependency.  Structural JSONL validation remains
    available through ``_stable_jsonl_snapshot`` for failure-triggered
    diagnostics; the install hot path needs only a bounded metadata inventory.
    """

    sessions_root = default_codex_home() / "sessions"
    if not sessions_root.is_dir():
        return {
            "status": "no_sessions",
            "files_observed": 0,
            "concurrent_tails": 0,
            "validation_scope": "metadata_only",
            "deep_audit": "failure_triggered",
            "termination_authority": False,
        }
    files = sorted(sessions_root.rglob("*.jsonl"))
    before: dict[Path, tuple[int, int, int, int]] = {}
    for path in files:
        try:
            metadata = path.lstat()
        except OSError as error:
            raise InstallError(
                f"session JSONL metadata cannot be observed safely: {path}: {error}"
            ) from error
        if (
            stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            raise InstallError(
                f"session JSONL is not an unambiguous regular file: {path}"
            )
        before[path] = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
    concurrent = 0
    for path, identity in before.items():
        try:
            metadata = path.lstat()
        except OSError:
            concurrent += 1
            continue
        current = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
        )
        if current != identity:
            concurrent += 1
    return {
        "status": "observed",
        "files_observed": len(files),
        "concurrent_tails": concurrent,
        "validation_scope": "metadata_only",
        "deep_audit": "failure_triggered",
        "termination_authority": False,
    }


def _lock_owner(lock_dir: Path) -> dict[str, Any] | None:
    marker = lock_dir / "owner.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _looks_like_codex_host(command: str, arguments: str) -> bool:
    """Recognize Codex host processes without treating arbitrary mentions as hosts."""
    try:
        argv = split_command_template(arguments, os_name="posix")
    except ValueError:
        argv = arguments.split()
    # ``comm`` identifies native Codex directly. For interpreter-hosted CLI
    # entrypoints, argv[0:2] covers ``node codex.js`` and ``python codex-cli``.
    # Later arguments are user payload and must never create a false host match.
    names = [Path(command).name.lower()]
    names.extend(Path(token).name.lower() for token in argv[:2])
    return any(
        name == "codex"
        or name == "codex.exe"
        or name.startswith("codex-")
        or name in {"codex.js", "codex-cli", "codex-cli.exe"}
        for name in names
    )


def _codex_host_preflight(runner: Runner) -> dict[str, Any]:
    """Fail before the install transaction if any POSIX Codex host is stopped."""
    if os.name == "nt":
        return {
            "status": "not_applicable",
            "reason": "POSIX stopped process state is unavailable on Windows",
            "stopped_hosts": [],
        }
    ps = os.environ.get("SULDE_PS", "ps")
    result = runner(
        [ps, "-axo", "pid=,stat=,comm=,args="],
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1000:]
        raise InstallError(
            "cannot inspect Codex host process states before installation"
            + (f": {detail}" if detail else "")
        )
    stopped: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        fields = raw_line.strip().split(None, 3)
        if len(fields) < 3:
            continue
        raw_pid, state, command = fields[:3]
        arguments = fields[3] if len(fields) == 4 else command
        if "T" not in state.upper() or not _looks_like_codex_host(command, arguments):
            continue
        try:
            pid = int(raw_pid)
        except ValueError:
            continue
        stopped.append({"pid": pid, "state": state, "command": command})
    if stopped:
        summary = ", ".join(
            f"pid={row['pid']} state={row['state']} command={row['command']}"
            for row in stopped
        )
        raise InstallError(
            "stopped Codex host preflight failed; resume or terminate the affected "
            f"host outside this installer before retrying: {summary}"
        )
    return {"status": "clear", "stopped_hosts": []}


def _reclaim_stale_deployment_lock(lock_dir: Path) -> bool:
    """Remove only a proven-dead lock left by a crashed local installer."""
    owner = _lock_owner(lock_dir)
    if owner is not None:
        pid = owner.get("pid")
        if isinstance(pid, int) and _process_is_alive(pid):
            return False
    else:
        try:
            if time.time() - lock_dir.stat().st_mtime < 300:
                return False
        except OSError:
            return False
    try:
        marker = lock_dir / "owner.json"
        if marker.exists() or marker.is_symlink():
            marker.unlink()
        lock_dir.rmdir()
    except OSError:
        return False
    return True


@contextmanager
def _deployment_lock(kb_home: Path):
    """Serialize plugin and scheduler generation changes on one host.

    A directory lock is shared with ``install-agents.sh``.  The owner marker
    makes crash recovery bounded without allowing one live process to steal
    another process' deployment lock.
    """
    lock_dir = deployment_lock_dir(kb_home)
    lock_dir.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    acquired = False
    for _attempt in range(2):
        try:
            lock_dir.mkdir(mode=0o700)
            acquired = True
            break
        except FileExistsError:
            if not _reclaim_stale_deployment_lock(lock_dir):
                break
    if not acquired:
        raise InstallError(
            f"another plugin or scheduler deployment owns {lock_dir}"
        )
    marker = lock_dir / "owner.json"
    try:
        _atomic_bytes(
            marker,
            (
                json.dumps(
                    {
                        "schema_version": 1,
                        "pid": os.getpid(),
                        "token": token,
                        "operation": "codex-plugin-install",
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8"),
            0o600,
        )
        yield token
    finally:
        current = _lock_owner(lock_dir)
        if current is not None and current.get("token") == token:
            try:
                marker.unlink()
                lock_dir.rmdir()
            except OSError:
                pass


def _desired_scheduler_labels(runtime_root: Path) -> tuple[str, ...]:
    template_dir = runtime_root / "templates" / "launchagents"
    if not template_dir.is_dir():
        raise InstallError(f"LaunchAgent templates are missing: {template_dir}")
    labels: list[str] = []
    for path in sorted(template_dir.glob("*.plist")):
        try:
            with path.open("rb") as handle:
                payload = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException) as error:
            raise InstallError(f"invalid LaunchAgent template: {path}: {error}") from error
        label = payload.get("Label")
        if not isinstance(label, str) or not label.startswith("com.sulde."):
            raise InstallError(f"invalid Sulde LaunchAgent label: {path}")
        if path.name != f"{label}.plist":
            raise InstallError(f"LaunchAgent filename/label mismatch: {path}")
        labels.append(label)
    if not labels or len(labels) != len(set(labels)):
        raise InstallError("LaunchAgent desired labels are empty or duplicated")
    return tuple(labels)


def _launchctl_path() -> str | None:
    configured = os.environ.get("SULDE_LAUNCHCTL")
    if configured:
        return configured
    if sys.platform == "darwin":
        return "launchctl"
    return None


def _loaded_sulde_labels(runner: Runner) -> tuple[str, ...] | None:
    launchctl = _launchctl_path()
    if launchctl is None:
        return None
    result = runner([launchctl, "list"], check=False, timeout=15)
    if result.returncode != 0:
        raise InstallError(
            "cannot enumerate LaunchAgents before changing the plugin generation"
        )
    labels = {
        fields[-1]
        for line in result.stdout.splitlines()
        if (fields := line.split()) and fields[-1].startswith("com.sulde.")
    }
    return tuple(sorted(labels))


def _launchagents_dir() -> Path:
    configured = os.environ.get("SULDE_LAUNCHAGENTS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home().expanduser().resolve() / "Library" / "LaunchAgents"


def _installed_sulde_labels() -> tuple[str, ...]:
    launchagents = _launchagents_dir()
    if not launchagents.is_dir():
        return ()
    labels: set[str] = set()
    for path in sorted(launchagents.glob("com.sulde.*.plist")):
        label: object = path.stem
        try:
            with path.open("rb") as handle:
                payload = plistlib.load(handle)
            label = payload.get("Label")
        except (OSError, plistlib.InvalidFileException):
            pass
        if not isinstance(label, str) or not label.startswith("com.sulde."):
            raise InstallError(f"cannot identify installed Sulde actor: {path}")
        if path.name != f"{label}.plist":
            raise InstallError(f"installed LaunchAgent filename/label mismatch: {path}")
        labels.add(label)
    return tuple(sorted(labels))


def _scheduler_actor_preflight(runtime_root: Path, runner: Runner) -> dict[str, Any]:
    desired = set(_desired_scheduler_labels(runtime_root))
    loaded = _loaded_sulde_labels(runner)
    if loaded is None:
        return {
            "status": "unverified_platform",
            "loaded_labels": None,
            "retired_or_unknown_labels": [],
        }
    launchagents = _launchagents_dir()
    unrestorable = sorted(
        label
        for label in loaded
        if (
            (plist := launchagents / f"{label}.plist").is_symlink()
            or not plist.is_file()
        )
    )
    if unrestorable:
        raise InstallError(
            "loaded Sulde LaunchAgents have no rollback-safe plist: "
            + ", ".join(unrestorable)
        )
    installed = set(_installed_sulde_labels())
    observed = set(loaded) | installed
    outside_desired = observed - desired
    safely_retired = sorted(outside_desired & RETIRED_SCHEDULER_LABELS)
    unknown = sorted(outside_desired - RETIRED_SCHEDULER_LABELS)
    if unknown:
        raise InstallError(
            "unknown Sulde LaunchAgents block the generation switch: "
            + ", ".join(unknown)
        )
    evidence = {
        "status": "retirement_required" if safely_retired else "clear",
        "loaded_labels_before": list(loaded),
        "installed_labels_before": sorted(installed),
        "loaded_labels": list(loaded),
        "desired_labels": sorted(desired),
        "retired_or_unknown_labels": safely_retired,
        "unknown_labels": [],
        "retirement_labels": safely_retired,
    }
    return evidence


def _quiesce_loaded_scheduler_writers(
    actor_preflight: dict[str, Any], runner: Runner
) -> None:
    labels = actor_preflight.get("loaded_labels_before") or []
    launchctl = _launchctl_path()
    if labels and launchctl is None:
        raise InstallError("cannot quiesce legacy scheduler writers on this platform")
    for label in labels:
        result = runner([str(launchctl), "remove", str(label)], check=False, timeout=15)
        if result.returncode != 0:
            raise InstallError(f"cannot quiesce legacy scheduler writer: {label}")
    loaded = _loaded_sulde_labels(runner)
    if loaded is not None and set(loaded) & set(labels):
        raise InstallError("legacy scheduler writers remained loaded after quiescence")


def _legacy_home_migration_source(kb_home: Path) -> Path | None:
    neutral_root = Path(os.environ.get("SULDE_HOME") or Path.home() / ".sulde")
    neutral_kb = (neutral_root / "data" / "kb").expanduser().resolve(strict=False)
    if kb_home.expanduser().resolve(strict=False) != neutral_kb or kb_home.exists():
        return None
    legacy = Path.home() / ".claude" / "plugins" / "data" / "sulde-cc" / "kb"
    if legacy.is_dir() and not legacy.is_symlink():
        return legacy.absolute()
    return None


def _legacy_memory_database(kb_home: Path) -> Path | None:
    neutral = kb_home.expanduser().resolve(strict=False) / "memory.db"
    legacy = (
        Path.home()
        / ".claude"
        / "plugins"
        / "data"
        / "sulde-cc"
        / "kb"
        / "memory.db"
    )
    if (
        neutral.is_file()
        and not neutral.is_symlink()
        and legacy.is_file()
        and not legacy.is_symlink()
        and neutral.resolve() != legacy.resolve()
    ):
        return legacy.absolute()
    return None


def _delivery_generation(plugin: Path, *, expected_version: str) -> dict[str, Any]:
    path = plugin / ".codex-plugin" / DELIVERY_GENERATION_NAME
    payload = _read_json(path)
    runtime = plugin / "runtime"
    actual_digest = tree_digest(runtime)
    expected = {
        "schema": DELIVERY_GENERATION_SCHEMA,
        "schema_version": 1,
        "provider": "codex",
        "plugin_version": expected_version,
        "runtime_tree_sha256": actual_digest,
        "generation": f"{expected_version}:{actual_digest}",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise InstallError(
                f"delivery generation mismatch for {key}: {payload.get(key)!r} != {value!r}"
            )
    if payload.get("platform") not in {"posix", "windows"}:
        raise InstallError("delivery generation platform is invalid")
    return payload


def _plugin_mcp_stdio_route(plugin: Path, *, platform: str) -> dict[str, Any]:
    """Validate and resolve the exact stdio route Codex will spawn."""
    manifest = _read_json(plugin / ".mcp.json")
    servers = manifest.get("mcpServers")
    server = servers.get("sulde_kb") if isinstance(servers, dict) else None
    if not isinstance(server, dict):
        raise InstallError("staged plugin MCP manifest does not define sulde_kb")
    command = server.get("command")
    args = server.get("args", [])
    cwd = server.get("cwd")
    if not isinstance(command, str) or not command:
        raise InstallError("staged plugin MCP command is missing")
    if not isinstance(args, list) or any(not isinstance(value, str) for value in args):
        raise InstallError("staged plugin MCP args must be a string array")

    plugin_root = plugin.resolve()
    if platform == "posix":
        expected_command = "./scripts/run-mcp.sh"
        if command != expected_command or args or cwd != ".":
            raise InstallError(
                "POSIX plugin MCP route must use the contained ./scripts/run-mcp.sh "
                "command with plugin-relative '.' cwd"
            )
        target = plugin_root / "scripts" / "run-mcp.sh"
        try:
            metadata = target.lstat()
        except OSError as error:
            raise InstallError(f"plugin MCP command is unavailable: {target}") from error
        if (
            target.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or not os.access(target, os.X_OK)
        ):
            raise InstallError("plugin MCP command must be a contained executable regular file")
        spawn_cwd = plugin_root
    elif platform == "windows":
        expected_args = [
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            "./scripts/run-mcp.ps1",
        ]
        if command != "powershell.exe" or args != expected_args or cwd != ".":
            raise InstallError(
                "Windows plugin MCP route must use the contained PowerShell launcher"
            )
        target = plugin_root / "scripts" / "run-mcp.ps1"
        if target.is_symlink() or not target.is_file():
            raise InstallError("Windows plugin MCP launcher is unavailable or unsafe")
        spawn_cwd = plugin_root
    else:
        raise InstallError(f"unsupported plugin MCP platform: {platform}")

    return {
        "command": [command, *args],
        "cwd": str(spawn_cwd),
        "launcher": str(target),
    }


def validate_plugin_root(plugin: Path, *, expected_version: str) -> dict[str, Any]:
    descriptor_path = plugin / ".codex-plugin" / "plugin.json"
    descriptor = _read_json(descriptor_path)
    runtime = plugin / "runtime"
    required = (
        plugin / ".mcp.json",
        plugin / "hooks" / "hooks.json",
        plugin / "scripts" / "session-start.py",
        plugin / "scripts" / "user-prompt-submit.py",
        plugin / "scripts" / "pre-tool-use.py",
        plugin / "scripts" / "_recovery_defer.py",
        plugin / "scripts" / "post-tool-use.py",
        plugin / "scripts" / "record-hook-failure.py",
        plugin / "scripts" / "_hook_observer.py",
        plugin / "scripts" / "stop.py",
        plugin / "skills" / "dispatch-task" / "SKILL.md",
        plugin / "skills" / "intent-guardian" / "SKILL.md",
        runtime / "scripts" / "kb" / "bootstrap.sh",
        runtime / "scripts" / "kb" / "configure-global.py",
        runtime / "scripts" / "kb" / "launcher_contract.py",
        runtime / "scripts" / "kb" / "model-dispatch.py",
        runtime / "scripts" / "kb" / "intent-guardian.py",
        runtime / "scripts" / "kb" / "codex_recovery_defer.py",
        runtime / "scripts" / "kb" / "agent-runtime.py",
        runtime / "scripts" / "kb" / "native_agent_broker.py",
        runtime / "scripts" / "kb" / "host_capabilities.py",
        runtime / "scripts" / "kb" / "session_continuity.py",
        runtime / "scripts" / "kb" / "kb-mcp",
        runtime / "templates" / "global" / "codex-agents-rules.md",
        runtime / "tools" / "kb-mcp" / "server.py",
        runtime / "knowledge" / "MANIFEST.json",
        runtime / "knowledge" / "HISTORY.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise InstallError("staged marketplace is incomplete: " + ", ".join(missing))
    if descriptor.get("name") != "sulde":
        raise InstallError("staged plugin name is not sulde")
    if descriptor.get("version") != expected_version:
        raise InstallError(
            f"staged version mismatch: {descriptor.get('version')!r} != {expected_version!r}"
        )
    if descriptor.get("skills") != "./skills/":
        raise InstallError("staged plugin does not expose its skills directory")
    if descriptor.get("mcpServers") != "./.mcp.json":
        raise InstallError("staged plugin does not expose its MCP companion manifest")
    try:
        load_history(runtime)
    except HistoryError as error:
        raise InstallError(
            f"staged plugin knowledge history is invalid: {error}"
        ) from error
    descriptor["delivery_generation"] = _delivery_generation(
        plugin,
        expected_version=expected_version,
    )
    descriptor["mcp_stdio_route"] = _plugin_mcp_stdio_route(
        plugin,
        platform=descriptor["delivery_generation"]["platform"],
    )
    try:
        capability_evidence = validate_artifact(plugin, provider="codex")
    except HostCapabilityError as error:
        raise InstallError(f"staged plugin violates the host capability contract: {error}") from error
    descriptor["host_capability_contract"] = capability_evidence
    return descriptor


def validate_staged_marketplace(marketplace: Path, *, expected_version: str) -> dict[str, Any]:
    marketplace_descriptor = marketplace / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_descriptor.is_file():
        raise InstallError(f"staged marketplace descriptor is missing: {marketplace_descriptor}")
    return validate_plugin_root(
        marketplace / "plugins" / "sulde",
        expected_version=expected_version,
    )


def _marketplace_root(output: str) -> Path | None:
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("MARKETPLACE") or line.startswith("WARNING"):
            continue
        name, separator, root = line.partition(" ")
        if name == MARKETPLACE_NAME and separator and root.strip():
            return Path(root.strip()).expanduser()
    return None


def current_marketplace_root(codex: str, runner: Runner) -> Path | None:
    result = runner(
        [codex, "plugin", "marketplace", "list"],
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise InstallError("cannot inspect current Codex marketplaces")
    return _marketplace_root(result.stdout)


def _plugin_installation(output: str) -> tuple[str, Path] | None:
    """Parse the Sulde row without breaking an installed path that contains spaces."""
    for raw_line in output.splitlines():
        columns = re.split(r"\s{2,}", raw_line.strip(), maxsplit=3)
        if len(columns) != 4 or columns[0] != PLUGIN_SELECTOR:
            continue
        version, installed_path = columns[2], columns[3]
        if version and installed_path:
            return version, Path(installed_path).expanduser().resolve()
    return None


def current_plugin_installation(codex: str, runner: Runner) -> tuple[str, Path] | None:
    result = runner(
        [codex, "plugin", "list"],
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise InstallError("cannot inspect the current Codex plugin installation")
    return _plugin_installation(result.stdout)


def deployment_cas_snapshot(
    kb_home: Path,
    codex: str,
    runner: Runner = run_command,
) -> dict[str, Any]:
    """Return stable live identities that must not drift before promotion.

    Candidate verification can take minutes. It must never reserve or mutate the
    live generation during that time, so promotion compares this projection again
    inside the deployment lock before any registry, launcher, scheduler, home, or
    ledger write. Mutable logs and scheduler counters are intentionally excluded.
    """

    marketplace = current_marketplace_root(codex, runner)
    installation = current_plugin_installation(codex, runner)
    installed_version: str | None = None
    installed_path: Path | None = None
    installed_tree_sha256: str | None = None
    if installation is not None:
        installed_version, installed_path = installation
        if not installed_path.is_dir() or installed_path.is_symlink():
            raise InstallError(
                f"current Codex plugin path is unavailable for promotion CAS: {installed_path}"
            )
        installed_tree_sha256 = warm_tree_state(
            installed_path
        ).normalized_tree_sha256

    deployment_path = kb_home / DEPLOYMENT_GENERATION_NAME
    launcher_path = launcher_home(kb_home) / "bin" / ".sulde-launchers.json"
    owner_path = kb_home / RUNTIME_OWNER_NAME

    def stable_descriptor(path: Path) -> dict[str, Any] | None:
        digest = _file_sha256(path)
        if digest is None:
            return None
        payload = _read_json(path)
        return {
            "sha256": digest,
            "generation": payload.get("generation"),
            "runtime_tree_sha256": payload.get("runtime_tree_sha256"),
        }

    return {
        "schema": "sulde-codex-promotion-prestate-v1",
        "marketplace": str(marketplace.resolve()) if marketplace is not None else None,
        "plugin": {
            "version": installed_version,
            "path": str(installed_path.resolve()) if installed_path is not None else None,
            "normalized_tree_sha256": installed_tree_sha256,
        },
        "deployment": stable_descriptor(deployment_path),
        "launcher": stable_descriptor(launcher_path),
        "scheduler_owner": stable_descriptor(owner_path),
    }


def _assert_deployment_cas(
    expected: dict[str, Any],
    *,
    kb_home: Path,
    codex: str,
    runner: Runner,
) -> None:
    actual = deployment_cas_snapshot(kb_home, codex, runner)
    if _canonical_json_bytes(actual) != _canonical_json_bytes(expected):
        raise InstallError(
            "candidate promotion prestate drifted; prepare and verify a new candidate"
        )


def _previous_install_paths(
    installation: tuple[str, Path] | None,
) -> tuple[Path, ...]:
    if installation is None:
        return ()
    version, registered_path = installation
    canonical = _canonical_cache_path(version)
    candidates = (canonical,)
    if _is_cache_enumeration_child(registered_path):
        candidates = (registered_path, canonical)
    existing: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        existing.append(candidate)
    return tuple(existing)


def _legacy_install_paths(excluded: tuple[Path, ...]) -> tuple[Path, ...]:
    """Find older Codex cache paths that a resumed thread may still execute."""
    cache_root = _canonical_cache_root()
    excluded_resolved = {
        path.expanduser().resolve()
        for path in excluded
        if path.exists()
    }
    if not cache_root.is_dir():
        return ()
    paths: list[Path] = []
    for candidate in sorted(cache_root.iterdir()):
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        resolved = candidate.resolve()
        if resolved in excluded_resolved:
            continue
        descriptor = candidate / ".codex-plugin" / "plugin.json"
        if not descriptor.is_file():
            continue
        try:
            payload = _read_json(descriptor)
        except InstallError:
            continue
        if (
            payload.get("name") != "sulde"
            or payload.get("version") != candidate.name
        ):
            continue
        if not any((candidate / relative).is_file() for relative in LIVE_SESSION_BRIDGE_FILES):
            continue
        paths.append(candidate)
    return tuple(paths)


def _legacy_artifact_plugin_root(
    version: str,
    *,
    artifacts_root: Path | None = None,
) -> Path | None:
    """Resolve a complete persistent artifact for one damaged cache version."""
    safe_product = re.sub(r"[^0-9A-Za-z._-]+", "-", product_version())
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]*", version):
        return None
    safe_version = re.sub(r"[^0-9A-Za-z._-]+", "-", version)
    if not safe_version:
        return None
    root = artifacts_root or (Path.home() / ".sulde" / "artifacts")
    plugin = (
        root
        / f"sulde-{safe_product}-{safe_version}"
        / "codex"
        / "plugins"
        / "sulde"
    )
    if not plugin.is_dir() or plugin.is_symlink():
        return None
    required = (
        plugin / ".codex-plugin" / "plugin.json",
        plugin / "scripts" / "user-prompt-submit.py",
        plugin / "runtime" / "scripts" / "kb" / "intent-guardian.py",
        plugin / "skills" / "intent-guardian" / "SKILL.md",
        *(plugin / relative for relative in LIVE_SESSION_BRIDGE_FILES),
    )
    if any(not path.is_file() or path.is_symlink() for path in required):
        return None
    if any(path.is_symlink() for path in plugin.rglob("*")):
        return None
    try:
        descriptor = _read_json(required[0])
    except InstallError:
        return None
    if descriptor.get("name") != "sulde" or descriptor.get("version") != version:
        return None
    return plugin


def _legacy_install_sources(
    excluded: tuple[Path, ...],
    *,
    artifacts_root: Path | None = None,
) -> tuple[LegacyPluginSource, ...]:
    """Discover complete caches plus narrowly recoverable partial caches.

    A previous installer may have been interrupted after Codex pruned an old
    cache but before rollback restored the whole tree. Such a directory is
    recoverable only when it still contains a known Hook bridge and an exact,
    complete, version-matched persistent artifact exists.
    """
    complete = _legacy_install_paths(excluded)
    sources = [
        LegacyPluginSource(path, path, "existing_cache") for path in complete
    ]
    known = {path.expanduser().resolve() for path in (*excluded, *complete)}
    known_lexical = {
        Path(os.path.abspath(str(path.expanduser()))) for path in (*excluded, *complete)
    }
    cache_root = _canonical_cache_root()
    if not cache_root.is_dir():
        return tuple(sources)
    for candidate in sorted(cache_root.iterdir()):
        if Path(os.path.abspath(str(candidate))) in known_lexical:
            continue
        if candidate.is_symlink():
            target = candidate.resolve()
            record_path = target.with_name(f"{target.name}.retirement.json")
            try:
                record = _read_json(record_path)
                state = warm_tree_state(target)
                descriptor = _read_json(target / ".codex-plugin" / "plugin.json")
            except InstallError:
                record = {}
                state = None
                descriptor = {}
            if (
                _path_outside_cache_enumeration_root(target)
                and record.get("schema") == "sulde-retired-codex-cache-v1"
                and record.get("alias") == str(candidate)
                and record.get("target") == str(target)
                and state is not None
                and not state.bytecode_inventory
                and record.get("tree_sha256") == state.tree_sha256
                and descriptor.get("name") == "sulde"
                and descriptor.get("version") == candidate.name
            ):
                sources.append(
                    LegacyPluginSource(candidate, target, "controlled_retired_alias")
                )
                continue
            artifact_plugin = _legacy_artifact_plugin_root(
                candidate.name,
                artifacts_root=artifacts_root,
            )
            if artifact_plugin is not None:
                sources.append(
                    LegacyPluginSource(
                        candidate,
                        artifact_plugin,
                        "retired_whole_tree_symlink_recovery",
                    )
                )
                continue
            raise InstallError(
                "retired whole-tree cache symlink has no same-version immutable "
                f"artifact: {candidate}"
            )
        if not candidate.is_dir():
            continue
        if candidate.resolve() in known:
            continue
        descriptor = candidate / ".codex-plugin" / "plugin.json"
        if descriptor.exists():
            # A malformed or foreign descriptor is not an interrupted tree we
            # can safely reconstruct by inference.
            continue
        if not any(
            (candidate / relative).is_file()
            for relative in LIVE_SESSION_BRIDGE_FILES
        ):
            continue
        artifact_plugin = _legacy_artifact_plugin_root(
            candidate.name,
            artifacts_root=artifacts_root,
        )
        if artifact_plugin is None:
            continue
        sources.append(
            LegacyPluginSource(
                candidate,
                artifact_plugin,
                "persistent_artifact_recovery",
            )
        )
        known.add(candidate.resolve())
        known_lexical.add(Path(os.path.abspath(str(candidate))))
    return tuple(sources)


def _preserve_previous_install_path(
    previous: Path | None,
    snapshot: Path,
    *,
    current_install: Path | None = None,
) -> dict[str, Any] | None:
    """Keep one live-session path pinned to its pre-switch runtime bytes."""
    if previous is None:
        return None
    previous = previous.expanduser()
    snapshot = snapshot.expanduser().resolve()
    installed = current_install.expanduser().resolve() if current_install else None
    if installed is not None and previous.resolve() == installed:
        return {"path": str(previous), "mode": "current_install"}
    snapshot_hook = snapshot / "scripts" / "user-prompt-submit.py"
    if not snapshot.is_dir() or not snapshot_hook.is_file():
        raise InstallError(f"previous Codex plugin snapshot is incomplete: {snapshot}")
    expected_digest = warm_tree_state(snapshot).tree_sha256
    required_hook = previous / "scripts" / "user-prompt-submit.py"
    if previous.is_dir() and not previous.is_symlink():
        if required_hook.is_file() and warm_tree_state(previous).tree_sha256 == expected_digest:
            return {
                "path": str(previous),
                "mode": "existing_pinned_copy",
                "plugin_tree_sha256": expected_digest,
            }
        raise InstallError(
            f"previous Codex plugin path was reused with different bytes: {previous}"
        )
    if previous.is_symlink():
        previous.unlink()
    elif previous.exists() and not previous.is_dir():
        raise InstallError(f"previous Codex plugin path is not a directory: {previous}")
    previous.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot, previous, symlinks=False)
    if not required_hook.is_file() or warm_tree_state(previous).tree_sha256 != expected_digest:
        raise InstallError(f"previous Codex plugin path could not be preserved: {previous}")
    return {
        "path": str(previous),
        "mode": "pinned_copy",
        "plugin_tree_sha256": expected_digest,
    }


def _snapshot_previous_install_paths(
    paths: tuple[Path, ...],
    snapshot_root: Path,
) -> list[tuple[Path, Path]]:
    """Copy runtimes before Codex removes their versioned cache paths."""
    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshots: list[tuple[Path, Path]] = []
    for index, previous in enumerate(paths):
        source = previous.expanduser().resolve()
        required_hook = source / "scripts" / "user-prompt-submit.py"
        if not source.is_dir() or not required_hook.is_file():
            raise InstallError(f"current Codex plugin path is incomplete: {previous}")
        snapshot = snapshot_root / f"{index}-{previous.name}"
        shutil.copytree(source, snapshot, symlinks=False)
        if warm_tree_state(snapshot) != warm_tree_state(source):
            raise InstallError(f"cannot snapshot current Codex plugin path: {previous}")
        snapshots.append((previous, snapshot))
    return snapshots


def _snapshot_launchers(kb_home: Path) -> dict[str, tuple[bytes, int] | None]:
    snapshot: dict[str, tuple[bytes, int] | None] = {}
    for name in LAUNCHER_NAMES:
        path = launcher_home(kb_home) / "bin" / name
        try:
            snapshot[name] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        except OSError:
            snapshot[name] = None
    return snapshot


def _atomic_bytes(path: Path, content: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary.chmod(mode)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _deployment_generation(
    installed_plugin: Path,
    artifact: Path,
    *,
    plugin_tree_sha256: str,
    codex: str,
    runner: Runner,
) -> dict[str, Any]:
    runtime_root = (installed_plugin / "runtime").resolve()
    sealed = _delivery_generation(
        installed_plugin,
        expected_version=plugin_version(),
    )
    native_authority = _installed_native_runtime_authority(
        installed_plugin,
        sealed,
        registry_codex=codex,
        runner=runner,
    )
    return {
        "schema_version": 1,
        "schema": "sulde-installed-deployment-generation-v1",
        "status": "installed_degraded",
        "operational_ready": False,
        "provider": "codex",
        "platform": sealed["platform"],
        "plugin_version": plugin_version(),
        "plugin_tree_sha256": plugin_tree_sha256,
        "runtime_tree_sha256": sealed["runtime_tree_sha256"],
        "generation": sealed["generation"],
        "artifact_platform": sealed["platform"],
        "artifact": str(artifact.resolve()),
        "installed_plugin": str(installed_plugin.resolve()),
        "runtime_root": str(runtime_root),
        "managed_labels": list(_desired_scheduler_labels(runtime_root)),
        "native_runtime_authority": native_authority,
        "native_runtime_authority_sha256": native_authority["authority_sha256"],
    }


def _write_deployment_generation(kb_home: Path, payload: dict[str, Any]) -> Path:
    target = kb_home / DEPLOYMENT_GENERATION_NAME
    _atomic_bytes(
        target,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
        0o600,
    )
    if _read_json(target) != payload:
        raise InstallError(f"deployment generation did not verify: {target}")
    return target


def _verify_recomputed_native_runtime_authority(
    deployment: dict[str, Any],
    recomputed: dict[str, Any],
) -> None:
    """Require exact recomputation, including a fresh canonical authority hash."""

    unsigned = dict(recomputed)
    supplied_digest = unsigned.pop("authority_sha256", None)
    recomputed_digest = hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()
    if (
        supplied_digest != recomputed_digest
        or deployment.get("native_runtime_authority") != recomputed
        or deployment.get("native_runtime_authority_sha256") != recomputed_digest
    ):
        raise InstallError("recovery postcondition native runtime authority differs")


def _installed_native_authority_load_smoke(
    installed_plugin: Path,
    kb_home: Path,
    sealed_generation: dict[str, Any],
    authority: dict[str, Any],
    *,
    runner: Runner,
) -> dict[str, Any]:
    """Load the sealed authority in a fresh interpreter without bytecode env help."""

    agent_runtime = (
        installed_plugin / "runtime" / "scripts" / "kb" / "agent-runtime.py"
    )
    if agent_runtime.is_symlink() or not agent_runtime.is_file():
        raise InstallError(
            f"installed agent runtime is not a regular file: {agent_runtime}"
        )
    probe_source = (
        "import json,runpy,sys;"
        "namespace=runpy.run_path(sys.argv[1]);"
        "payload={'module_loaded':True} if len(sys.argv)>2 "
        "else namespace['load_installed_native_authority']();"
        "print(json.dumps(payload,"
        "ensure_ascii=False,sort_keys=True,separators=(',',':')))"
    )
    test_mode = os.environ.get("SULDE_TEST_MODE") == "1"
    environment = os.environ.copy()
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment.pop("PYTHONPYCACHEPREFIX", None)
    environment["SULDE_KB_HOME"] = str(kb_home.expanduser().resolve())
    command = [sys.executable, "-I", "-c", probe_source, str(agent_runtime.resolve())]
    expected_payload = authority
    if test_mode:
        command.append("synthetic-import-only")
        expected_payload = {"module_loaded": True}
    loaded = runner(
        command,
        environment=environment,
        check=False,
        timeout=30,
    )
    try:
        payload = json.loads(loaded.stdout)
    except json.JSONDecodeError as error:
        raise InstallError(
            "installed native authority load smoke returned invalid JSON"
        ) from error
    if loaded.returncode != 0 or payload != expected_payload:
        detail = (loaded.stderr or loaded.stdout).strip()[-1000:]
        raise InstallError(
            "installed native authority could not be loaded independently"
            + (f": {detail}" if detail else "")
        )
    reloaded_generation = _delivery_generation(
        installed_plugin,
        expected_version=plugin_version(),
    )
    if reloaded_generation != sealed_generation:
        raise InstallError("native authority load smoke changed the sealed generation")
    return {
        "authority_load_verified": not test_mode,
        "module_load_verified": True,
        "authority_sha256": authority["authority_sha256"],
        "runtime_tree_sha256": sealed_generation["runtime_tree_sha256"],
        "bytecode_free": True,
    }


def _scheduler_generation_projection(
    kb_home: Path,
    deployment: dict[str, Any],
    runner: Runner,
) -> dict[str, Any]:
    desired = set(deployment.get("managed_labels", []))
    blockers: list[str] = []
    owner_path = kb_home / RUNTIME_OWNER_NAME
    try:
        owner = _read_json(owner_path)
    except InstallError:
        owner = None
        blockers.append("runtime_owner_missing_or_invalid")
    if owner is not None:
        expected = {
            "status": "active",
            "provider": "codex",
            "runtime_root": deployment["runtime_root"],
            "runtime_tree_sha256": deployment["runtime_tree_sha256"],
            "generation": deployment["generation"],
            "managed_labels": sorted(desired),
        }
        actual = {
            "status": owner.get("status"),
            "provider": owner.get("provider"),
            "runtime_root": owner.get("runtime_root"),
            "runtime_tree_sha256": owner.get("runtime_tree_sha256"),
            "generation": owner.get("generation"),
            "managed_labels": sorted(owner.get("managed_labels", []))
            if isinstance(owner.get("managed_labels"), list)
            else None,
        }
        for key, value in expected.items():
            if actual.get(key) != value:
                blockers.append(f"runtime_owner_{key}_mismatch")

    loaded = _loaded_sulde_labels(runner)
    retired_or_unknown: list[str] = []
    missing: list[str] = []
    if loaded is None:
        blockers.append("launchctl_unverified_platform")
    else:
        loaded_set = set(loaded)
        retired_or_unknown = sorted(loaded_set - desired)
        missing = sorted(desired - loaded_set)
        if retired_or_unknown:
            blockers.append("retired_or_unknown_actor_loaded")
        if missing:
            blockers.append("managed_actor_not_loaded")

    return {
        "status": "generation_verified" if not blockers else "degraded",
        "healthy": not blockers,
        "generation": deployment["generation"],
        "runtime_owner": str(owner_path),
        "owner": owner,
        "loaded_labels": list(loaded) if loaded is not None else None,
        "retired_or_unknown_labels": retired_or_unknown,
        "missing_labels": missing,
        "blockers": blockers,
    }


def _scheduler_snapshot_targets(
    kb_home: Path,
    desired_labels: Sequence[str],
) -> tuple[Path, ...]:
    launchagents = _launchagents_dir()
    labels = set(desired_labels) | set(_installed_sulde_labels())
    return (
        kb_home / RUNTIME_OWNER_NAME,
        kb_home / "bin" / "sulde-scheduled-run",
        *(launchagents / f"{label}.plist" for label in sorted(labels)),
        launchagents / ".sulde-retired",
    )


def _scheduler_reconcile_installed_generation(
    *,
    installed_path: Path,
    kb_home: Path,
    codex: str,
    deployment_lock_token: str,
    runner: Runner,
) -> dict[str, Any]:
    script = installed_path / "runtime" / "scripts" / "kb" / "install-agents.sh"
    if script.is_symlink() or not script.is_file():
        raise InstallError(f"installed scheduler reconciler is unavailable: {script}")
    environment = os.environ.copy()
    environment["SULDE_HOME"] = str(launcher_home(kb_home))
    environment["SULDE_KB_HOME"] = str(kb_home.expanduser().resolve())
    environment["SULDE_DEPLOYMENT_LOCK_DIR"] = str(deployment_lock_dir(kb_home))
    environment["SULDE_CODEX_EXE"] = _codex_command_identity(codex)[
        "codex_command"
    ]
    result = runner(
        [
            str(script),
            "--runtime-root",
            str((installed_path / "runtime").resolve()),
            "--provider",
            "codex",
            "--accept-llm-data-egress",
            "--parent-deployment-lock-token",
            deployment_lock_token,
        ],
        environment=environment,
        check=False,
        timeout=180,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-1500:]
        raise InstallError(
            "scheduler reconciliation did not join the plugin transaction"
            + (f": {detail}" if detail else "")
        )
    deployment = _read_json(kb_home / DEPLOYMENT_GENERATION_NAME)
    projection = _scheduler_generation_projection(kb_home, deployment, runner)
    owner = projection.get("owner")
    if (
        not projection.get("healthy")
        or deployment.get("status") != "generation_verified"
        or deployment.get("operational_ready") is not True
        or not isinstance(owner, dict)
        or owner.get("installation_status") != "generation_verified"
        or owner.get("operational_ready") is not True
    ):
        raise InstallError(
            "scheduler generation did not become atomically ready: "
            + ",".join(str(value) for value in projection.get("blockers", []))
        )
    projection["reconcile_stdout"] = result.stdout.strip()[-2000:]
    return projection


def _restore_scheduler_process_state(
    descriptor: dict[str, Any],
    *,
    runner: Runner,
) -> None:
    scheduler = descriptor.get("expected_postconditions", {}).get("scheduler")
    if not isinstance(scheduler, dict):
        raise InstallError("transaction scheduler rollback identity is missing")
    old_loaded = scheduler.get("old_loaded_labels")
    desired = scheduler.get("desired_labels")
    if not isinstance(old_loaded, list) or not isinstance(desired, list):
        raise InstallError("transaction scheduler rollback labels are malformed")
    launchctl = _launchctl_path()
    if launchctl is None:
        if old_loaded:
            raise InstallError("cannot restore loaded scheduler state on this platform")
        return
    current = _loaded_sulde_labels(runner)
    if current is None:
        raise InstallError("cannot enumerate scheduler state during rollback")
    # ``launchctl remove`` reports a non-zero result for an actor that is not
    # loaded.  Desired labels are snapshot inventory, not proof of process
    # presence, so rollback may unload only the independently observed set.
    for label in sorted(set(current)):
        result = runner([launchctl, "remove", label], check=False, timeout=15)
        if result.returncode != 0:
            raise InstallError(f"cannot unload scheduler actor during rollback: {label}")
    launchagents = Path(str(scheduler["launchagents_dir"]))
    for label in old_loaded:
        plist = launchagents / f"{label}.plist"
        if not plist.is_file() or plist.is_symlink():
            raise InstallError(f"old scheduler plist is unavailable after rollback: {plist}")
        result = runner([launchctl, "load", str(plist)], check=False, timeout=15)
        if result.returncode != 0:
            raise InstallError(f"cannot reload old scheduler actor: {label}")
    restored = _loaded_sulde_labels(runner)
    if restored is None or set(restored) != set(old_loaded):
        raise InstallError("scheduler process rollback did not restore the old actor set")


def _snapshot_file(path: Path) -> tuple[bytes, int] | None:
    try:
        return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None


def _install_live_session_bridges(
    paths: tuple[Path, ...],
    current_install: Path,
) -> list[dict[str, Any]]:
    """Replace only legacy Hook entrypoints with the current stable bridge."""
    current = current_install.expanduser().resolve()
    sources: dict[Path, tuple[bytes, int]] = {}
    for relative in LIVE_SESSION_BRIDGE_FILES:
        source = current / relative
        snapshot = _snapshot_file(source)
        if snapshot is None:
            raise InstallError(f"current live-session bridge is missing: {source}")
        sources[relative] = snapshot
    evidence: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for plugin in paths:
        if not plugin.is_dir() or plugin.is_symlink():
            raise InstallError(f"legacy Codex plugin path is unsafe: {plugin}")
        resolved = plugin.resolve()
        if resolved == current or resolved in seen:
            continue
        seen.add(resolved)
        descriptor = _read_json(plugin / ".codex-plugin" / "plugin.json")
        if descriptor.get("name") != "sulde":
            raise InstallError(f"legacy bridge target is not a Sulde plugin: {plugin}")
        bridged: dict[str, str] = {}
        for relative, (content, mode) in sources.items():
            target = plugin / relative
            if target.exists() and (target.is_symlink() or not target.is_file()):
                raise InstallError(f"legacy Hook entrypoint is unsafe: {target}")
            _atomic_bytes(target, content, mode)
            if target.read_bytes() != content:
                raise InstallError(f"legacy Hook bridge did not verify: {target}")
            bridged[relative.as_posix()] = hashlib.sha256(content).hexdigest()
        evidence.append(
            {
                "path": str(plugin),
                "version": descriptor.get("version"),
                "mode": "stable_current_runtime_bridge",
                "entrypoints": bridged,
            }
        )
    return evidence


def _restore_previous_install_path(previous: Path, snapshot: Path) -> None:
    """Restore an exact pre-switch tree, including its original Hook bytes."""
    expected = warm_tree_state(snapshot)
    if previous.is_symlink() or (previous.exists() and not previous.is_dir()):
        previous.unlink()
    elif previous.is_dir():
        shutil.rmtree(previous)
    previous.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(snapshot, previous, symlinks=False)
    if warm_tree_state(previous) != expected:
        raise InstallError(f"previous Codex plugin path rollback failed: {previous}")


def _snapshot_plugin_trees(
    paths: tuple[Path, ...],
    snapshot_root: Path,
) -> list[tuple[Path, Path]]:
    """Snapshot complete or partial cache trees before Codex can prune them."""
    snapshot_root.mkdir(parents=True, exist_ok=True)
    snapshots: list[tuple[Path, Path]] = []
    for index, target in enumerate(paths):
        if target.is_symlink() or not target.is_dir():
            raise InstallError(f"legacy Codex plugin path is unsafe: {target}")
        if any(path.is_symlink() for path in target.rglob("*")):
            raise InstallError(f"legacy Codex plugin tree contains a symlink: {target}")
        snapshot = snapshot_root / f"{index}-{target.name}"
        shutil.copytree(target, snapshot, symlinks=False)
        if warm_tree_state(snapshot) != warm_tree_state(target):
            raise InstallError(f"cannot snapshot legacy Codex plugin path: {target}")
        snapshots.append((target, snapshot))
    return snapshots


def _path_outside_cache_enumeration_root(path: Path) -> bool:
    root = Path(os.path.abspath(str(_canonical_cache_root())))
    candidate = Path(os.path.abspath(str(path.expanduser())))
    try:
        return os.path.commonpath((str(root), str(candidate))) != str(root)
    except ValueError:
        return True


def _prepare_cache_retirements(
    snapshots: Sequence[tuple[Path, Path]],
    *,
    current_install: Path,
    preparation_root: Path,
) -> tuple[CacheRetirement, ...]:
    """Prepare normalized old static trees without mutating live cache paths."""

    plans: list[CacheRetirement] = []
    seen: set[Path] = set()
    active = _canonical_cache_path(plugin_version())
    retirement_root = default_codex_home() / "plugins" / "retired" / MARKETPLACE_NAME / "sulde"
    for index, (raw_alias, snapshot) in enumerate(snapshots):
        preexisting_target = raw_alias.resolve() if raw_alias.is_symlink() else None
        alias = Path(os.path.abspath(str(raw_alias.expanduser())))
        if not _is_cache_enumeration_child(alias) or alias == active:
            continue
        if alias in seen:
            continue
        seen.add(alias)
        prestate = warm_tree_state(snapshot)
        prepared = preparation_root / f"{index}-{alias.name}"
        shutil.copytree(snapshot, prepared, symlinks=False)
        _remove_derived_bytecode(prepared)
        _install_live_session_bridges((prepared,), current_install)
        normalized = warm_tree_state(prepared)
        if normalized.bytecode_inventory:
            raise InstallError(f"retired cache normalization retained bytecode: {alias}")
        safe_version = re.sub(r"[^0-9A-Za-z._-]+", "-", alias.name)
        target = retirement_root / f"{safe_version}-{normalized.tree_sha256[:20]}"
        if not _path_outside_cache_enumeration_root(target):
            raise InstallError(f"retired cache target remains enumerable: {target}")
        plans.append(
            CacheRetirement(
                alias=alias,
                target=target,
                source=prepared,
                prestate=prestate,
                expected_tree_sha256=normalized.tree_sha256,
                record=target.with_name(f"{target.name}.retirement.json"),
                alias_preexisting=raw_alias.is_symlink(),
                preexisting_target=preexisting_target,
            )
        )
    return tuple(plans)


def _retirement_descriptors(
    plans: Sequence[CacheRetirement],
) -> list[dict[str, Any]]:
    return [
        {
            "alias": str(plan.alias),
            "target": str(plan.target),
            "record": str(plan.record),
            "version": plan.alias.name,
            "prestate_tree_sha256": plan.prestate.tree_sha256,
            "prestate_normalized_tree_sha256": plan.prestate.normalized_tree_sha256,
            "prestate_bytecode_inventory": list(plan.prestate.bytecode_inventory),
            "retired_tree_sha256": plan.expected_tree_sha256,
            "alias_preexisting": plan.alias_preexisting,
            "preexisting_target": str(plan.preexisting_target)
            if plan.preexisting_target is not None
            else None,
        }
        for plan in plans
    ]


def _publish_retirement_targets(plans: Sequence[CacheRetirement]) -> None:
    for plan in plans:
        _failure_boundary("retirement.before_publish")
        if plan.target.exists() or plan.target.is_symlink():
            if plan.target.is_symlink() or not plan.target.is_dir():
                raise InstallError(f"retired cache target is unsafe: {plan.target}")
            state = warm_tree_state(plan.target)
            if state.bytecode_inventory or state.tree_sha256 != plan.expected_tree_sha256:
                raise InstallError(f"retired cache target has conflicting bytes: {plan.target}")
        else:
            plan.target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(plan.source, plan.target, symlinks=False)
        state = warm_tree_state(plan.target)
        if state.bytecode_inventory or state.tree_sha256 != plan.expected_tree_sha256:
            raise InstallError(f"retired cache target did not verify: {plan.target}")
        _failure_boundary("retirement.after_publish")


def _publish_retirement_aliases(plans: Sequence[CacheRetirement]) -> None:
    for plan in plans:
        _failure_boundary("alias.before_publish")
        if plan.alias.is_symlink():
            plan.alias.unlink()
        elif plan.alias.is_dir():
            shutil.rmtree(plan.alias)
        elif plan.alias.exists():
            raise InstallError(f"retired cache alias path has an unsupported item: {plan.alias}")
        plan.alias.parent.mkdir(parents=True, exist_ok=True)
        plan.alias.symlink_to(plan.target, target_is_directory=True)
        record = {
            "schema": "sulde-retired-codex-cache-v1",
            "schema_version": 1,
            "alias": str(plan.alias),
            "target": str(plan.target.resolve()),
            "version": plan.alias.name,
            "tree_sha256": plan.expected_tree_sha256,
        }
        _atomic_bytes(
            plan.record,
            (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
            0o600,
        )
        _failure_boundary("alias.after_publish")


def _verify_retirement_descriptors(rows: object) -> None:
    if not isinstance(rows, list):
        raise InstallError("retired cache postconditions are malformed")
    for row in rows:
        if not isinstance(row, dict):
            raise InstallError("retired cache postcondition is malformed")
        alias = Path(str(row.get("alias")))
        target = Path(str(row.get("target")))
        record_path = Path(str(row.get("record")))
        if (
            not alias.is_symlink()
            or not _is_cache_enumeration_child(alias)
            or not _path_outside_cache_enumeration_root(target)
        ):
            raise InstallError(f"retired cache alias authority differs: {alias}")
        if alias.resolve() != target.resolve():
            raise InstallError(f"retired cache alias target differs: {alias}")
        state = warm_tree_state(target)
        if state.bytecode_inventory or state.tree_sha256 != row.get("retired_tree_sha256"):
            raise InstallError(f"retired cache tree differs: {target}")
        descriptor = _read_json(target / ".codex-plugin" / "plugin.json")
        if descriptor.get("name") != "sulde" or descriptor.get("version") != row.get("version"):
            raise InstallError(f"retired cache descriptor differs: {target}")
        record = _read_json(record_path)
        if (
            record.get("schema") != "sulde-retired-codex-cache-v1"
            or record.get("alias") != str(alias)
            or record.get("target") != str(target.resolve())
            or record.get("tree_sha256") != row.get("retired_tree_sha256")
        ):
            raise InstallError(f"retired cache record differs: {record_path}")


def _remove_transaction_aliases(descriptor: dict[str, Any]) -> None:
    rows = descriptor.get("expected_postconditions", {}).get("retirements", [])
    if not isinstance(rows, list):
        raise InstallError("transaction retirement authority is malformed")
    for row in rows:
        if not isinstance(row, dict):
            raise InstallError("transaction retirement authority is malformed")
        alias = Path(str(row.get("alias")))
        target = Path(str(row.get("target")))
        if not alias.is_symlink():
            continue
        if alias.resolve() != target.resolve():
            raise InstallError(f"refusing to remove a drifted retirement alias: {alias}")
        alias.unlink()


def _restore_preexisting_retirement_aliases(descriptor: dict[str, Any]) -> None:
    rows = descriptor.get("expected_postconditions", {}).get("retirements", [])
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("alias_preexisting") is not True:
            continue
        alias = Path(str(row.get("alias")))
        prior_target = row.get("preexisting_target")
        if not isinstance(prior_target, str):
            raise InstallError(f"preexisting retirement target is missing: {alias}")
        target = Path(prior_target)
        try:
            target_state = warm_tree_state(target)
        except InstallError as error:
            raise InstallError(
                f"preexisting retirement target is unavailable: {alias}"
            ) from error
        if target_state.tree_sha256 != row.get("prestate_tree_sha256"):
            raise InstallError(f"preexisting retirement target differs: {alias}")
        if alias.exists() or alias.is_symlink():
            raise InstallError(f"cannot restore preexisting retirement alias: {alias}")
        alias.parent.mkdir(parents=True, exist_ok=True)
        alias.symlink_to(target, target_is_directory=True)


def _restore_file(path: Path, snapshot: tuple[bytes, int] | None) -> list[str]:
    try:
        if snapshot is None:
            if path.exists() or path.is_symlink():
                path.unlink()
        else:
            _atomic_bytes(path, snapshot[0], snapshot[1])
    except OSError as error:
        return [f"restore {path}: {error}"]
    return []


def _restore_launchers(
    kb_home: Path,
    snapshot: dict[str, tuple[bytes, int] | None],
) -> list[str]:
    errors: list[str] = []
    for name, previous in snapshot.items():
        path = launcher_home(kb_home) / "bin" / name
        try:
            if previous is None:
                if path.exists() or path.is_symlink():
                    path.unlink()
            else:
                _atomic_bytes(path, previous[0], previous[1])
        except OSError as error:
            errors.append(f"restore {path}: {error}")
    return errors


def _stage_artifact(
    artifact: Path,
    *,
    platform: str,
    runner: Runner,
) -> PreparedArtifact:
    artifact.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".sulde-stage-", dir=artifact.parent))
    try:
        runner(
            [
                sys.executable,
                str(STAGER),
                "--target",
                "codex",
                "--platform",
                platform,
                "--output",
                str(temporary),
            ],
            timeout=300,
        )
        _complete_staged_native_runtime(temporary, platform=platform)
        staged_descriptor = validate_staged_marketplace(
            temporary,
            expected_version=plugin_version(),
        )
        staged_digest = tree_digest(temporary / "plugins" / "sulde")
        if artifact.exists():
            existing_descriptor = validate_staged_marketplace(
                artifact,
                expected_version=plugin_version(),
            )
            existing_digest = tree_digest(artifact / "plugins" / "sulde")
            if existing_digest != staged_digest:
                raise InstallError(
                    "artifact path contains different content for the same version; "
                    "update the plugin cachebuster or choose a new versioned path"
                )
            shutil.rmtree(temporary)
            return PreparedArtifact(
                artifact.resolve(),
                existing_descriptor,
                existing_digest,
            )
        else:
            os.replace(temporary, artifact)
            published_descriptor = validate_staged_marketplace(
                artifact,
                expected_version=plugin_version(),
            )
            published_digest = tree_digest(artifact / "plugins" / "sulde")
            if published_digest != staged_digest:
                raise InstallError(
                    "published artifact content differs after atomic rename"
                )
            return PreparedArtifact(
                artifact.resolve(),
                published_descriptor,
                published_digest,
            )
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _candidate_descriptor_identity(prepared: PreparedArtifact) -> dict[str, Any]:
    """Return a location-independent identity for one validated artifact."""

    identity = dict(prepared.descriptor)
    raw_route = identity.get("mcp_stdio_route")
    if not isinstance(raw_route, dict):
        return identity

    route = dict(raw_route)
    plugin_root = (prepared.marketplace / "plugins" / "sulde").resolve()
    for key in ("cwd", "launcher"):
        raw_path = route.get(key)
        if not isinstance(raw_path, str) or not raw_path:
            raise InstallError(f"candidate descriptor MCP {key} is invalid")
        try:
            relative = Path(raw_path).resolve().relative_to(plugin_root)
        except (OSError, ValueError) as error:
            raise InstallError(
                f"candidate descriptor MCP {key} escapes the plugin root"
            ) from error
        route[key] = "." if relative == Path(".") else relative.as_posix()
    identity["mcp_stdio_route"] = route
    return identity


def _publish_verified_candidate_artifact(
    candidate: PreparedArtifact,
    *,
    platform: str,
    runner: Runner,
) -> PreparedArtifact:
    """Publish candidate-equivalent bytes to the canonical immutable store."""

    published = _stage_artifact(
        default_artifact_root(),
        platform=platform,
        runner=runner,
    )
    if (
        _candidate_descriptor_identity(published)
        != _candidate_descriptor_identity(candidate)
        or published.plugin_tree_sha256 != candidate.plugin_tree_sha256
    ):
        raise InstallError(
            "canonical candidate artifact differs from the verified candidate"
        )
    return published


def _complete_staged_native_runtime(marketplace: Path, *, platform: str) -> None:
    """Install the complete native runtime inventory before sealing staging.

    The release stager intentionally selects tracked files.  Native runtime
    modules can exist in an accepted worktree before the coordinator updates
    the Git index, so the installer owns a small explicit inventory and proves
    its exact bytes and modes in every staged marketplace it creates.
    """
    plugin = marketplace / "plugins" / "sulde"
    runtime = plugin / "runtime"
    for relative, mode in INSTALLER_NATIVE_RUNTIME_INVENTORY:
        source = ROOT / relative
        try:
            source_metadata = source.lstat()
        except OSError as error:
            raise InstallError(
                f"installer runtime source is unavailable: {relative}"
            ) from error
        if not stat.S_ISREG(source_metadata.st_mode):
            raise InstallError(
                f"installer runtime source is not a regular file: {relative}"
            )
        destination = runtime / relative
        if destination.is_symlink():
            raise InstallError(
                f"staged installer runtime destination is linked: {destination}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        if os.name != "nt":
            destination.chmod(mode)
        if source.read_bytes() != destination.read_bytes():
            raise InstallError(
                f"staged installer runtime content did not verify: {relative}"
            )
        if os.name != "nt" and stat.S_IMODE(destination.stat().st_mode) != mode:
            raise InstallError(
                f"staged installer runtime mode did not verify: {relative}"
            )

    descriptor = _read_json(plugin / ".codex-plugin" / "plugin.json")
    version = descriptor.get("version")
    if not isinstance(version, str) or not version:
        raise InstallError("staged plugin version is unavailable for runtime sealing")
    runtime_digest = tree_digest(runtime)
    generation = {
        "schema": DELIVERY_GENERATION_SCHEMA,
        "schema_version": 1,
        "provider": "codex",
        "plugin_version": version,
        "platform": platform,
        "runtime_tree_sha256": runtime_digest,
        "generation": f"{version}:{runtime_digest}",
    }
    _atomic_bytes(
        plugin / ".codex-plugin" / DELIVERY_GENERATION_NAME,
        (json.dumps(generation, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
        0o644,
    )


def _registry_remove(codex: str, runner: Runner) -> None:
    runner(
        [codex, "plugin", "remove", PLUGIN_SELECTOR, "--json"],
        check=False,
        timeout=60,
    )
    runner(
        [codex, "plugin", "marketplace", "remove", MARKETPLACE_NAME, "--json"],
        check=False,
        timeout=60,
    )


def _registry_add(
    codex: str,
    marketplace: Path,
    runner: Runner,
    *,
    expected_version: str | None,
) -> Path:
    _registry_add_marketplace(codex, marketplace, runner)
    return _registry_add_plugin(
        codex,
        runner,
        expected_version=expected_version,
    )


def _registry_add_marketplace(
    codex: str,
    marketplace: Path,
    runner: Runner,
) -> None:
    added_marketplace = _json_output(
        runner(
            [codex, "plugin", "marketplace", "add", str(marketplace), "--json"],
            timeout=120,
        )
    )
    if added_marketplace.get("marketplaceName") != MARKETPLACE_NAME:
        raise InstallError("Codex registered an unexpected marketplace name")
    installed_root = added_marketplace.get("installedRoot")
    if not isinstance(installed_root, str) or Path(installed_root).expanduser().resolve() != marketplace.resolve():
        raise InstallError(
            f"Codex marketplace root mismatch: {installed_root!r} != {str(marketplace.resolve())!r}"
        )


def _registry_add_plugin(
    codex: str,
    runner: Runner,
    *,
    expected_version: str | None,
) -> Path:
    installed = _json_output(
        runner(
            [codex, "plugin", "add", PLUGIN_SELECTOR, "--json"],
            timeout=120,
        )
    )
    if expected_version is not None and installed.get("version") != expected_version:
        raise InstallError(
            f"Codex installed unexpected version: {installed.get('version')!r}"
        )
    installed_path = installed.get("installedPath")
    if not isinstance(installed_path, str) or not installed_path:
        raise InstallError("Codex did not report the installed plugin path")
    reported = Path(installed_path).expanduser().resolve()
    if expected_version is None:
        return reported
    canonical = _canonical_cache_path(expected_version)
    try:
        canonical_readback = canonical.resolve(strict=True)
    except OSError as error:
        raise InstallError(
            f"canonical Codex cache root is unavailable after install: {canonical}"
        ) from error
    if reported != canonical_readback:
        raise InstallError(
            "Codex installedPath is not the canonical cache authority: "
            f"{reported} != {canonical_readback}"
        )
    return canonical_readback


def _restore_registry(
    codex: str,
    marketplace: Path,
    old_version: str | None,
    runner: Runner,
) -> Path | None:
    """Restore marketplace presence without inventing prior plugin authority."""
    _registry_add_marketplace(codex, marketplace, runner)
    if old_version is None:
        return None
    return _registry_add_plugin(
        codex,
        runner,
        expected_version=old_version,
    )


def _install_launchers(
    installed_plugin: Path,
    kb_home: Path,
    runner: Runner,
    *,
    platform: str,
) -> dict[str, Any]:
    runtime = installed_plugin / "runtime"
    contract = runtime / "scripts" / "kb" / "launcher_contract.py"
    public_home = launcher_home(kb_home)
    installed = runner(
        [
            sys.executable,
            str(contract),
            "install",
            "--home",
            str(public_home),
            "--data-home",
            str(kb_home),
            "--interpreter-home",
            str(kb_home),
            "--source-root",
            str(runtime),
            "--json",
        ],
        timeout=120,
    )
    payload = _json_output(installed)
    if payload.get("healthy") is not True:
        raise InstallError("stable launcher installation did not verify")
    manifest_path = public_home / "bin" / ".sulde-launchers.json"
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema") != "sulde-launcher-install-v1"
        or type(manifest.get("spec_version")) is not int
    ):
        raise InstallError("stable launcher manifest has an unsupported envelope")
    manifest.update(
        {
            "schema_version": 1,
            "provider": "codex",
            "platform": platform,
        }
    )
    _atomic_bytes(
        manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
        0o600,
    )
    if _read_json(manifest_path) != manifest:
        raise InstallError("stable launcher envelope did not verify after publication")
    interpreter = Path(str(manifest.get("interpreter") or "")).expanduser()
    yaml_required = True
    yaml_result = runner(
        [str(interpreter), "-c", "import yaml; print(yaml.__version__)"],
        environment={
            **os.environ,
            "SULDE_KB_HOME": str(kb_home.resolve()),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        check=False,
        timeout=15,
    )
    yaml_available = yaml_result.returncode == 0 and bool(yaml_result.stdout.strip())
    if yaml_required and not yaml_available:
        raise InstallError(
            "the selected stable-launcher interpreter cannot import PyYAML"
        )
    payload.update(
        {
            "schema_version": 1,
            "provider": "codex",
            "platform": platform,
            "pyyaml": {
                "required": yaml_required,
                "available": yaml_available,
                "interpreter": str(interpreter),
            },
        }
    )
    return payload


def _install_global_rules(
    installed_plugin: Path,
    kb_home: Path,
    runner: Runner,
) -> dict[str, Any]:
    configurator = installed_plugin / "runtime" / "scripts" / "kb" / "configure-global.py"
    agents_md = default_codex_home() / "AGENTS.md"
    common = [
        sys.executable,
        str(configurator),
        "--target",
        "codex",
        "--agents-md",
        str(agents_md),
        "--kb-home",
        str(kb_home),
    ]
    environment = os.environ.copy()
    environment["SULDE_PLUGIN_ROOT"] = str((installed_plugin / "runtime").resolve())
    environment["SULDE_KB_HOME"] = str(kb_home.resolve())
    runner([*common, "--install"], environment=environment, timeout=30)
    runner([*common, "--check"], environment=environment, timeout=30)
    try:
        source = agents_md.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise InstallError(f"cannot verify installed Codex global rules: {error}") from error
    if "## Codex 派单档位纪律" not in source or "$dispatch-task" not in source:
        raise InstallError("installed Codex global rules are missing the dispatch gate")
    return {
        "healthy": True,
        "path": str(agents_md.resolve()),
        "sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "dispatch_gate": True,
    }


def _mcp_initialize_smoke(
    command: Sequence[str],
    *,
    environment: dict[str, str],
    runner: Runner,
    cwd: Path | None = None,
) -> dict[str, Any]:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "sulde-installer", "version": "1"},
        },
    }
    completed = runner(
        command,
        input_text=json.dumps(request, separators=(",", ":")) + "\n",
        environment=environment,
        cwd=cwd,
        timeout=30,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise InstallError(
            "MCP initialize smoke expected exactly one stdout JSON line; "
            f"received {len(lines)}"
        )
    try:
        response = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise InstallError("MCP initialize smoke returned invalid JSON") from error
    if not isinstance(response, dict) or response.get("id") != 1:
        raise InstallError("MCP initialize smoke returned an unrelated response")
    result = response.get("result")
    server_info = result.get("serverInfo") if isinstance(result, dict) else None
    if not isinstance(server_info, dict) or server_info.get("name") != "sulde-kb":
        raise InstallError("MCP initialize smoke did not identify the sulde-kb server")
    return {
        "protocol_version": result.get("protocolVersion"),
        "server_name": server_info["name"],
    }


def _codex_plugin_mcp_projection(
    codex: str,
    installed_plugin: Path,
    *,
    declared_route: dict[str, Any],
    runner: Runner,
) -> dict[str, Any]:
    """Read back the route normalized by Codex instead of reinterpreting it."""
    completed = runner(
        [codex, "mcp", "get", "sulde_kb", "--json"],
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[-1000:]
        raise InstallError(
            f"Codex could not project the installed sulde_kb route: {detail}"
        )
    payload = _json_output(completed)
    transport = payload.get("transport")
    if (
        payload.get("name") != "sulde_kb"
        or payload.get("enabled") is not True
        or not isinstance(transport, dict)
        or transport.get("type") != "stdio"
    ):
        raise InstallError("Codex did not expose sulde_kb as an enabled stdio server")
    command = transport.get("command")
    args = transport.get("args")
    cwd = transport.get("cwd")
    declared_command = declared_route.get("command")
    if (
        not isinstance(declared_command, list)
        or not declared_command
        or command != declared_command[0]
        or args != declared_command[1:]
    ):
        raise InstallError("Codex changed the installed sulde_kb command projection")
    expected_cwd = installed_plugin.resolve()
    if not isinstance(cwd, str) or Path(cwd).resolve() != expected_cwd:
        raise InstallError(
            "Codex did not normalize the installed sulde_kb cwd to the plugin root"
        )
    return {
        "command": [command, *args],
        "cwd": str(expected_cwd),
        "source": "codex mcp get sulde_kb --json",
    }


def _smoke_installed(
    installed_plugin: Path,
    kb_home: Path,
    *,
    codex: str,
    expected_tree_sha256: str,
    runner: Runner,
    installed_descriptor: dict[str, Any] | None = None,
    installed_tree_sha256: str | None = None,
) -> dict[str, Any]:
    if installed_descriptor is None:
        installed_descriptor = validate_plugin_root(
            installed_plugin,
            expected_version=plugin_version(),
        )
    installed_runtime_sha256 = installed_descriptor[
        "host_capability_contract"
    ]["runtime_sha256"]
    if installed_tree_sha256 is None:
        installed_tree_sha256 = tree_digest(installed_plugin)
    if installed_tree_sha256 != expected_tree_sha256:
        raise InstallError("Codex cache content does not match the staged plugin artifact")
    probe = _json_output(
        runner(
            [
                sys.executable,
                str(launcher_home(kb_home) / "bin" / "intent-guardian"),
                "--sulde-launcher-probe",
            ],
            timeout=30,
        )
    )
    if probe.get("healthy") is not True:
        raise InstallError("intent-guardian stable launcher probe failed")

    dispatch = _json_output(
        runner(
            [
                sys.executable,
                str(launcher_home(kb_home) / "bin" / "model-dispatch"),
                "--provider",
                "codex",
                "--tier",
                "deep",
                "--task",
                ".ai-workspace/tasks/installed-smoke.md",
                "--format",
                "json",
            ],
            timeout=30,
        )
    )
    instructions = dispatch.get("instructions")
    if not isinstance(instructions, list):
        raise InstallError("installed model dispatch did not return instructions")
    rendered_dispatch = "\n".join(str(line) for line in instructions).lower()
    if instructions != ["执行任务文件:.ai-workspace/tasks/installed-smoke.md"]:
        raise InstallError("installed Codex dispatch must default to task-only instructions")
    if dispatch.get("actions") != [] or dispatch.get("model_advice") is not False:
        raise InstallError("installed Codex dispatch unexpectedly requested model advice")
    if any(label in rendered_dispatch for label in ("opus", "sonnet", "haiku", "/mode ", "/assign")):
        raise InstallError("installed Codex dispatch leaked Claude controls")

    with tempfile.TemporaryDirectory(prefix="sulde-installed-smoke-") as temp_name:
        temp = Path(temp_name)
        smoke_home = temp / "kb"
        workspace = temp / "workspace"
        smoke_home.mkdir()
        workspace.mkdir()
        # The installer may itself run inside a supervised host session.  A
        # synthetic child must not inherit that session's contract, tokens, or
        # provider credentials and accidentally present them as installed-host
        # evidence.
        inherited_names = {
            "CODEX_HOME",
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "TMPDIR",
            "TZ",
            "USERPROFILE",
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in inherited_names
        }
        environment.update(
            {
                "SULDE_KB_HOME": str(smoke_home),
                "SULDE_HOST_PROVIDER": "codex",
                "SULDE_HOOK_OBSERVATION_SOURCE": "synthetic_smoke",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        session = "installed-smoke"
        bridged_session_start = _json_output(
            runner(
                [
                    sys.executable,
                    str(launcher_home(kb_home) / "bin" / "intent-guardian"),
                    "codex-hook",
                    "session-start",
                    "--home",
                    str(kb_home),
                ],
                input_text=json.dumps({"cwd": str(workspace), "sessionId": session}),
                environment=environment,
                timeout=30,
            )
        )
        bridged_context = bridged_session_start.get("hookSpecificOutput")
        if (
            not isinstance(bridged_context, dict)
            or bridged_context.get("hookEventName") != "SessionStart"
        ):
            raise InstallError(
                "stable launcher did not bridge SessionStart into the current adapter"
            )
        session_start = runner(
            [sys.executable, str(installed_plugin / "scripts" / "session-start.py")],
            input_text=json.dumps({"cwd": str(workspace), "sessionId": session}),
            environment=environment,
            timeout=30,
        )
        if "SessionStart" not in session_start.stdout:
            raise InstallError("installed SessionStart did not return context")
        prompt = _json_output(
            runner(
                [sys.executable, str(installed_plugin / "scripts" / "user-prompt-submit.py")],
                input_text=json.dumps(
                    {
                        "cwd": str(workspace),
                        "sessionId": session,
                        "prompt": "verify installed intent guardian",
                    }
                ),
                environment=environment,
                timeout=30,
            )
        )
        context = (
            prompt.get("hookSpecificOutput", {}).get("additionalContext")
            if isinstance(prompt.get("hookSpecificOutput"), dict)
            else None
        )
        if not isinstance(context, str) or "[sulde intent] ACTIVE" not in context:
            raise InstallError("installed UserPromptSubmit did not establish an intent contract")
        contracts = list((smoke_home / "intent" / "workspaces").glob("*.active.json"))
        if len(contracts) != 1:
            raise InstallError("installed UserPromptSubmit did not create one workspace contract")
        contract_path = contracts[0]
        guardian = launcher_home(kb_home) / "bin" / "intent-guardian"
        permission_probe = runner(
            [
                sys.executable,
                str(guardian),
                "codex-hook",
                "permission-request",
                "--home",
                str(kb_home),
            ],
            input_text=json.dumps(
                {
                    "cwd": str(workspace),
                    "sessionId": session,
                    "permissionMode": "default",
                    "toolName": "Bash",
                    "toolInput": {"command": "true"},
                }
            ),
            environment=environment,
            timeout=30,
        )
        if permission_probe.stdout.strip():
            raise InstallError(
                "installed PermissionRequest changed an unrelated native approval"
            )
        runner(
            [
                sys.executable,
                str(guardian),
                "propose-revision",
                str(contract_path),
                "--objective",
                "verify installed native proposal decision bridge",
                "--accept",
                "fixed text grants no authority and native preview binds one readable card",
                "--allow-path",
                "smoke.txt",
                "--mode",
                "enforce",
            ],
            environment=environment,
            timeout=30,
        )
        proposals = list(contract_path.parent.glob(f"{contract_path.stem}.proposal.*.json"))
        if len(proposals) != 1:
            raise InstallError("installed guardian did not create one immutable proposal")
        proposal_path = proposals[0]
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal_digest = proposal.get("proposal_digest")
        if not isinstance(proposal_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", proposal_digest
        ):
            raise InstallError("installed guardian proposal has no valid digest")
        text_choice = _json_output(
            runner(
                [sys.executable, str(installed_plugin / "scripts" / "user-prompt-submit.py")],
                input_text=json.dumps(
                    {
                        "cwd": str(workspace),
                        "sessionId": session,
                        "prompt": "批准当前方案",
                    },
                    ensure_ascii=False,
                ),
                environment=environment,
                timeout=30,
            )
        )
        text_choice_context = (
            text_choice.get("hookSpecificOutput", {}).get("additionalContext")
            if isinstance(text_choice.get("hookSpecificOutput"), dict)
            else None
        )
        if (
            not isinstance(text_choice_context, str)
            or "NATIVE_DECISION_REQUIRED action=approve-proposal" not in text_choice_context
            or "CONTROL_RECORDED" in text_choice_context
        ):
            raise InstallError(
                "installed UserPromptSubmit did not reject fixed-text proposal authority"
            )
        # The smoke validates the native card and command binding but
        # deliberately does not execute the protected command or fabricate Allow.
        native_preview = _json_output(
            runner(
                [
                    sys.executable,
                    str(guardian),
                    "native-decision-preview",
                    "proposal",
                    "--decision",
                    "approve",
                    "--target",
                    "current",
                    "--contract",
                    str(contract_path),
                    "--provider",
                    "codex",
                    "--session-id",
                    session,
                ],
                environment=environment,
                timeout=30,
            )
        )
        command_argv = native_preview.get("command_argv")
        description = native_preview.get("description")
        if (
            native_preview.get("schema") != "sulde-codex-native-decision-preview-v1"
            or native_preview.get("target") != proposal_digest
            or native_preview.get("requires_native_escalation") is not True
            or native_preview.get("persistent_prefix_approval") is not False
            or not isinstance(command_argv, list)
            or len(command_argv) < 4
            or not all(isinstance(item, str) and item for item in command_argv)
            or not isinstance(description, str)
            or not description.strip()
        ):
            raise InstallError("installed guardian did not produce a bound native decision card")
        unauthorized_apply = runner(
            [
                sys.executable,
                str(guardian),
                "apply-proposal",
                str(proposal_path),
                "--contract",
                str(contract_path),
            ],
            environment=environment,
            timeout=30,
            check=False,
        )
        if (
            unauthorized_apply.returncode == 0
            or "not been approved" not in unauthorized_apply.stderr
        ):
            raise InstallError(
                "installed guardian allowed fixed text or preview to grant proposal authority: "
                f"exit={unauthorized_apply.returncode} "
                f"detail={(unauthorized_apply.stderr or unauthorized_apply.stdout).strip()[-500:]}"
            )
        unapplied_contract = json.loads(contract_path.read_text(encoding="utf-8"))
        receipts = unapplied_contract.get("runtime", {}).get("approval_receipts", [])
        if (
            unapplied_contract.get("applied_approval_receipt_id") is not None
            or receipts != []
            or unapplied_contract.get("runtime", {}).get(
                "approved_proposal_digests", []
            )
        ):
            raise InstallError(
                "installed guardian persisted authority from fixed text or decision preview"
            )
        audit_path = contract_path.with_name(f"{contract_path.stem}.events.jsonl")
        audit_rows = [
            json.loads(line)
            for line in audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if any(
            row.get("action") == "approve-proposal"
            and row.get("actor") == "user-prompt:codex"
            for row in audit_rows
        ):
            raise InstallError("installed guardian audit recorded fixed text as Codex approval")
        denied_result = runner(
            [sys.executable, str(installed_plugin / "scripts" / "pre-tool-use.py")],
            input_text=json.dumps(
                {
                    "cwd": str(workspace),
                    "sessionId": session,
                    "toolName": "mcp__docs__update_document",
                    "toolInput": {
                        "uri": "doc://install-smoke",
                        "content": "guardian verification",
                    },
                }
            ),
            environment=environment,
            timeout=30,
            check=False,
        )
        if denied_result.returncode != 0:
            raise InstallError(
                "installed PreToolUse structured denial did not use Codex's successful JSON protocol"
            )
        denied = _json_output(denied_result)
        _verify_installed_mcp_scope_denial(denied)

        read_call_id = "installed-smoke-read"
        read_started = runner(
            [sys.executable, str(installed_plugin / "scripts" / "pre-tool-use.py")],
            input_text=json.dumps(
                {
                    "cwd": str(workspace),
                    "sessionId": session,
                    "toolUseId": read_call_id,
                    "toolName": "Read",
                    "toolInput": {"file_path": str(workspace / "smoke.txt")},
                }
            ),
            environment=environment,
            timeout=30,
        )
        if read_started.returncode != 0:
            raise InstallError("installed PreToolUse could not observe a safe read")
        if read_started.stdout.strip():
            raise InstallError(
                "installed PreToolUse emitted a policy response for a safe read; "
                "Codex native defer must use empty stdout"
            )
        read_completed = runner(
            [sys.executable, str(installed_plugin / "scripts" / "post-tool-use.py")],
            input_text=json.dumps(
                {
                    "cwd": str(workspace),
                    "sessionId": session,
                    "toolUseId": read_call_id,
                    "toolName": "Read",
                    "toolInput": {"file_path": str(workspace / "smoke.txt")},
                    "toolResponse": {"content": "not found in isolated smoke"},
                }
            ),
            environment=environment,
            timeout=30,
        )
        if read_completed.returncode != 0:
            raise InstallError("installed PostToolUse could not close a safe read")
        stopped = runner(
            [sys.executable, str(installed_plugin / "scripts" / "stop.py")],
            input_text=json.dumps({"cwd": str(workspace), "sessionId": session}),
            environment=environment,
            timeout=30,
        )
        if stopped.returncode != 0:
            raise InstallError("installed Stop could not reconcile the synthetic turn")

        promotion_boundary = _smoke_current_session_mcp_confirmation(
            installed_plugin,
            workspace=temp / "promotion-boundary-workspace",
            session="installed-promotion-boundary",
            environment=environment,
            runner=runner,
        )

        packaged_mcp = _mcp_initialize_smoke(
            [
                sys.executable,
                str(installed_plugin / "runtime" / "tools" / "kb-mcp" / "server.py"),
            ],
            environment=environment,
            runner=runner,
        )
        manifest_environment = dict(environment)
        manifest_environment["SULDE_HOME"] = str(launcher_home(kb_home))
        manifest_environment["SULDE_KB_HOME"] = str(kb_home)
        manifest_route = installed_descriptor["mcp_stdio_route"]
        host_manifest_route = _codex_plugin_mcp_projection(
            codex,
            installed_plugin,
            declared_route=manifest_route,
            runner=runner,
        )
        plugin_manifest_mcp = _mcp_initialize_smoke(
            host_manifest_route["command"],
            environment=manifest_environment,
            runner=runner,
            cwd=Path(host_manifest_route["cwd"]),
        )
        plugin_manifest_mcp["host_projection"] = host_manifest_route
        host_readiness = readiness_projection(
            smoke_home,
            provider="codex",
            session_id=session,
            workspace=workspace,
            expected_runtime_sha256=installed_runtime_sha256,
        )
        if (
            host_readiness.get("interactive_status") != "synthetic_only"
            or host_readiness.get("supervision_status") != "synthetic_only"
            or host_readiness.get("capabilities", {})
            .get("mcp_initialize", {})
            .get("status")
            != "synthetic_only"
            or host_readiness.get("approval_required") is not False
            or host_readiness.get("capabilities", {})
            .get("host_approval", {})
            .get("required_for_interactive")
            is not False
        ):
            raise InstallError(
                "installed synthetic smoke did not cover the complete host capability contract: "
                + json.dumps(host_readiness, ensure_ascii=False, sort_keys=True)
            )

    stable_mcp = None
    if (kb_home / "kb.db").is_file() and (kb_home / "memory.db").is_file():
        stable_environment = os.environ.copy()
        stable_environment.update(
            {
                "SULDE_KB_HOME": str(kb_home),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        stable_mcp = _mcp_initialize_smoke(
            [sys.executable, str(launcher_home(kb_home) / "bin" / "sulde-kb-mcp")],
            environment=stable_environment,
            runner=runner,
        )

    listing = runner(
        [codex, "plugin", "list"],
        check=False,
        timeout=60,
    )
    matching_row = next(
        (
            line
            for line in listing.stdout.splitlines()
            if PLUGIN_SELECTOR in line and plugin_version() in line and "installed, enabled" in line
        ),
        None,
    )
    if listing.returncode != 0 or matching_row is None:
        raise InstallError("Codex plugin list does not prove the expected enabled version")
    hook_trust = _codex_hook_trust_observation(Path(codex), cwd=ROOT)
    return {
        "launcher_probe": probe,
        "live_session_hook_bridge": True,
        "codex_dispatch_native": True,
        "intent_context": True,
        "proposal_control_round_trip": True,
        "native_permission_bridge": True,
        "native_decision_preview": True,
        "fixed_text_authority_rejected": True,
        "synthetic_authority_rejected": True,
        "approval_actor": None,
        "observation_source": "synthetic_smoke",
        "host_readiness": host_readiness,
        "mcp_write_denied": True,
        "promotion_preexecution_boundary": promotion_boundary,
        "mcp_initialize": {
            "packaged_server": packaged_mcp,
            "plugin_manifest": plugin_manifest_mcp,
            "stable_launcher": stable_mcp,
        },
        "plugin_list_verified": True,
        "hook_trust": hook_trust,
        "plugin_tree_sha256": installed_tree_sha256,
    }


def _failure_boundary(label: str) -> None:
    """Hard-exit only when an explicit test failpoint names this exact boundary."""
    if os.environ.get("SULDE_INSTALL_FAILPOINT") == label:
        os._exit(86)


def _verify_installed_mcp_scope_denial(
    payload: dict[str, Any],
    *,
    require_confirmation: bool = False,
) -> dict[str, Any]:
    """Accept only an evaluated scope denial or complete native confirmation card."""

    decision = payload.get("hookSpecificOutput")
    if not isinstance(decision, dict) or decision.get("permissionDecision") != "deny":
        raise InstallError("installed PreToolUse did not deny an unapproved MCP write")
    reason = decision.get("permissionDecisionReason")
    fallback_markers = (
        "busy or unavailable",
        "runtime is unavailable",
        "material/unknown action was not dispatched",
    )
    confirmation_markers = (
        "此动作需要一次当前会话确认",
        "操作：",
        "范围：",
        "Allow 仅执行一次",
        "Deny 不执行",
    )
    scope_decision = isinstance(reason, str) and "可读意图范围" in reason
    confirmation_decision = isinstance(reason, str) and all(
        marker in reason for marker in confirmation_markers
    )
    if (
        not isinstance(reason, str)
        or not (scope_decision or confirmation_decision)
        or (require_confirmation and not confirmation_decision)
        or any(marker in reason.casefold() for marker in fallback_markers)
        or "event_fingerprint=" in reason
        or "批准事件" in reason
    ):
        raise InstallError(
            "installed MCP denial did not return a readable scope decision: "
            + repr(reason)
        )
    return decision


def _smoke_current_session_mcp_confirmation(
    installed_plugin: Path,
    *,
    workspace: Path,
    session: str,
    environment: dict[str, str],
    runner: Runner,
) -> dict[str, Any]:
    """Exercise the exact no-pending-proposal denial used after promotion."""

    workspace.mkdir(parents=True, exist_ok=False)
    prompt = _json_output(
        runner(
            [sys.executable, str(installed_plugin / "scripts/user-prompt-submit.py")],
            input_text=json.dumps(
                {
                    "cwd": str(workspace),
                    "sessionId": session,
                    "prompt": "verify current-session MCP confirmation boundary",
                }
            ),
            environment=environment,
            timeout=30,
        )
    )
    context = (
        prompt.get("hookSpecificOutput", {}).get("additionalContext")
        if isinstance(prompt.get("hookSpecificOutput"), dict)
        else None
    )
    if not isinstance(context, str) or "[sulde intent] ACTIVE" not in context:
        raise InstallError("MCP confirmation canary did not establish intent")
    denied_result = runner(
        [sys.executable, str(installed_plugin / "scripts/pre-tool-use.py")],
        input_text=json.dumps(
            {
                "cwd": str(workspace),
                "sessionId": session,
                "toolName": "mcp__docs__update_document",
                "toolInput": {
                    "uri": "doc://candidate-promotion-canary",
                    "content": "must be denied before execution",
                },
            }
        ),
        environment=environment,
        timeout=30,
        check=False,
    )
    if denied_result.returncode != 0:
        raise InstallError(
            "MCP confirmation canary did not use Codex's successful JSON protocol"
        )
    decision = _verify_installed_mcp_scope_denial(
        _json_output(denied_result),
        require_confirmation=True,
    )
    return {
        "status": "ready",
        "permission_decision": decision["permissionDecision"],
        "decision_kind": "current_session_confirmation",
    }


def _validated_candidate_receipt(
    receipt: dict[str, Any],
    *,
    prepared: PreparedArtifact,
    expected_live_state: dict[str, Any],
    codex: str,
    runner: Runner,
) -> dict[str, Any]:
    """Validate one exact, single-use candidate receipt before live mutation."""

    if (
        receipt.get("schema") != CANDIDATE_RECEIPT_SCHEMA
        or receipt.get("schema_version") != 1
        or receipt.get("status") != "verified"
    ):
        raise InstallError("candidate verification receipt is unsupported or not verified")
    supplied_digest = receipt.get("receipt_sha256")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    actual_digest = hashlib.sha256(_canonical_json_bytes(unsigned)).hexdigest()
    if supplied_digest != actual_digest:
        raise InstallError("candidate verification receipt digest differs")

    artifact = receipt.get("artifact")
    generation = prepared.descriptor.get("delivery_generation")
    if not isinstance(artifact, dict) or not isinstance(generation, dict):
        raise InstallError("candidate receipt has no sealed artifact generation")
    expected_artifact = {
        "path": str(prepared.marketplace.resolve()),
        "plugin_tree_sha256": prepared.plugin_tree_sha256,
        "runtime_tree_sha256": generation.get("runtime_tree_sha256"),
        "generation": generation.get("generation"),
        "plugin_version": generation.get("plugin_version"),
        "platform": generation.get("platform"),
    }
    if artifact != expected_artifact:
        raise InstallError("candidate receipt does not bind the prepared artifact")

    if receipt.get("live_prestate") != expected_live_state:
        raise InstallError("candidate receipt does not bind the promotion prestate")
    expected_prestate_digest = hashlib.sha256(
        _canonical_json_bytes(expected_live_state)
    ).hexdigest()
    if receipt.get("live_prestate_sha256") != expected_prestate_digest:
        raise InstallError("candidate receipt promotion prestate digest differs")

    source = receipt.get("source")
    if not isinstance(source, dict):
        raise InstallError("candidate receipt source identity is missing")
    current_commit = run_command(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, timeout=15
    ).stdout.strip()
    current_tree = run_command(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, timeout=15
    ).stdout.strip()
    if source.get("commit") != current_commit or source.get("tree") != current_tree:
        raise InstallError("candidate source commit changed after verification")

    codex_receipt = receipt.get("codex")
    if not isinstance(codex_receipt, dict):
        raise InstallError("candidate Codex identity is missing")
    current_codex = _codex_command_identity(codex)
    version_result = runner([codex, "--version"], check=False, timeout=15)
    current_version = successful_version_identity(
        version_result.returncode, version_result.stdout
    )
    if (
        codex_receipt.get("executable") != current_codex["codex_command"]
        or codex_receipt.get("executable_sha256")
        != current_codex["codex_command_sha256"]
        or codex_receipt.get("version") != current_version
    ):
        raise InstallError("Codex executable identity changed after candidate verification")
    python_receipt = receipt.get("python")
    if not isinstance(python_receipt, dict):
        raise InstallError("candidate Python identity is missing")
    try:
        candidate_python = Path(str(python_receipt.get("executable"))).resolve(
            strict=True
        )
    except OSError as error:
        raise InstallError("candidate Python executable is unavailable") from error
    if (
        not candidate_python.is_file()
        or python_receipt.get("executable_sha256")
        != hashlib.sha256(candidate_python.read_bytes()).hexdigest()
    ):
        raise InstallError("candidate Python identity changed after verification")
    try:
        validate_python(python_receipt)
    except PythonEnvironmentError as error:
        raise InstallError(str(error)) from error

    verifications = receipt.get("verifications")
    if not isinstance(verifications, dict):
        raise InstallError("candidate verification matrix is missing")
    required_ready = (
        "artifact",
        "isolated_registry",
        "hooks",
        "preexecution_chain",
        "mcp",
        "doctor",
        "scheduler_entrypoint",
    )
    if any(
        not isinstance(verifications.get(name), dict)
        or verifications[name].get("status") != "ready"
        for name in required_ready
    ):
        raise InstallError("candidate verification matrix is incomplete")
    native = verifications["preexecution_chain"]
    if (native.get("transport") != "codex-cli-app-server"
        or native.get("native_tool") != "exec_command"
        or native.get("executor") != "unified_exec"
        or any(native.get(key) is not True for key in (
            "positive_executed", "outside_plan_write_executed", "destructive_pre_denied", "marker_absent"))
        or native.get("artifact_generation") != receipt["artifact"]["generation"]
        or not re.fullmatch(r"[0-9a-f]{64}", str(native.get("loaded_module_generation", "")))
        or not re.fullmatch(r"[0-9a-f]{64}", str(native.get("proof_id", "")))
        or not all(native.get(key) for key in ("session_id", "started_event_id", "scope_denial_event_id", "native_denial_run_id"))):
        raise InstallError("candidate lacks native PreToolUse execution evidence")
    native_ui = verifications.get("native_permission_ui")
    scheduler_host = verifications.get("scheduler_host")
    for label, observation in (
        ("native PermissionRequest UI", native_ui),
        ("candidate scheduler daemon", scheduler_host),
    ):
        if (
            not isinstance(observation, dict)
            or observation.get("status") != "unobserved"
            or not isinstance(observation.get("exit_code"), int)
            or observation.get("exit_code") == 0
        ):
            raise InstallError(f"{label} must be explicitly nonzero/unobserved")
    return receipt


def _smoke_promoted_candidate(
    installed_plugin: Path,
    kb_home: Path,
    *,
    codex: str,
    expected_tree_sha256: str,
    runner: Runner,
    installed_descriptor: dict[str, Any],
    installed_tree_sha256: str,
    candidate_receipt: dict[str, Any],
) -> dict[str, Any]:
    """Run only post-switch checks that candidate isolation cannot prove.

    The expensive proposal/authority/doctor/scheduler matrix was already sealed
    against these exact bytes.  Promotion still proves Codex's installed cache,
    one real pre-execution denial, MCP routing, and live Hook discovery.
    """

    if installed_tree_sha256 != expected_tree_sha256:
        raise InstallError("promoted cache differs from the verified candidate")
    with tempfile.TemporaryDirectory(prefix="sulde-promoted-canary-") as name:
        root = Path(name)
        smoke_home = root / "kb"
        workspace = root / "workspace"
        smoke_home.mkdir()
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            in {
                "CODEX_HOME",
                "HOME",
                "LANG",
                "LC_ALL",
                "PATH",
                "SYSTEMROOT",
                "TEMP",
                "TMP",
                "TMPDIR",
                "TZ",
                "USERPROFILE",
            }
        }
        environment.update(
            {
                "SULDE_KB_HOME": str(smoke_home),
                "SULDE_HOST_PROVIDER": "codex",
                "SULDE_HOOK_OBSERVATION_SOURCE": "promotion_canary",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        promotion_boundary = _smoke_current_session_mcp_confirmation(
            installed_plugin,
            workspace=workspace,
            session="candidate-promotion-canary",
            environment=environment,
            runner=runner,
        )
        packaged_mcp = _mcp_initialize_smoke(
            [
                sys.executable,
                str(installed_plugin / "runtime/tools/kb-mcp/server.py"),
            ],
            environment=environment,
            runner=runner,
        )

    manifest_route = _codex_plugin_mcp_projection(
        codex,
        installed_plugin,
        declared_route=installed_descriptor["mcp_stdio_route"],
        runner=runner,
    )
    listing = runner([codex, "plugin", "list"], check=False, timeout=60)
    if (
        listing.returncode != 0
        or not any(
            PLUGIN_SELECTOR in line
            and plugin_version() in line
            and "installed, enabled" in line
            for line in listing.stdout.splitlines()
        )
    ):
        raise InstallError("Codex plugin list did not verify the promoted candidate")
    hook_trust = _codex_hook_trust_observation(Path(codex), cwd=ROOT)
    if hook_trust.get("status") != "ready":
        raise InstallError("promoted candidate Hooks are not live, unique, and trusted")
    return {
        "candidate_receipt_sha256": candidate_receipt["receipt_sha256"],
        "observation_source": "promotion_canary",
        "intent_context": True,
        "mcp_write_denied": True,
        "promotion_preexecution_boundary": promotion_boundary,
        "mcp_initialize": {
            "packaged_server": packaged_mcp,
            "plugin_manifest": manifest_route,
            "stable_launcher": None,
        },
        "plugin_list_verified": True,
        "hook_trust": hook_trust,
        "host_readiness": {"status": "candidate_verified_then_live_canary"},
        "proposal_control_round_trip": True,
        "synthetic_authority_rejected": True,
        "plugin_tree_sha256": installed_tree_sha256,
    }


def _codex_command_identity(codex: str) -> dict[str, str]:
    candidate = Path(codex).expanduser() if os.path.sep in codex else None
    resolved_name = str(candidate) if candidate is not None else shutil.which(codex)
    if not resolved_name:
        raise InstallError(f"Codex command cannot be resolved for recovery: {codex}")
    try:
        resolved = Path(resolved_name).resolve(strict=True)
    except OSError as error:
        raise InstallError(f"Codex command cannot be sealed for recovery: {codex}") from error
    if not resolved.is_file():
        raise InstallError(f"Codex command is not a regular file: {resolved}")
    return {
        "codex_command": str(resolved),
        "codex_command_sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def _optional_tree_digest(path: Path | None, *, warm: bool = False) -> str | None:
    if path is None or not path.is_dir() or path.is_symlink():
        return None
    return warm_tree_state(path).tree_sha256 if warm else tree_digest(path)


def _file_sha256(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _transaction_descriptor(
    *,
    transaction_id: str,
    artifact: Path,
    kb_home: Path,
    codex: str,
    platform: str,
    previous_marketplace: Path | None,
    previous_installation: tuple[str, Path] | None,
    sealed_generation: dict[str, Any],
    staged_tree_sha256: str,
    retirements: Sequence[CacheRetirement],
    actor_preflight: dict[str, Any],
) -> dict[str, Any]:
    generation_path = kb_home / DEPLOYMENT_GENERATION_NAME
    launcher_path = launcher_home(kb_home) / "bin" / ".sulde-launchers.json"
    previous_generation: object = None
    try:
        previous_generation = _read_json(generation_path).get("generation")
    except InstallError:
        pass
    old_installed_path = None
    if previous_installation is not None:
        candidate = _canonical_cache_path(previous_installation[0])
        if candidate.is_dir() and not candidate.is_symlink():
            old_installed_path = candidate
    command_identity = _codex_command_identity(codex)
    return {
        "transaction_id": transaction_id,
        "old_generation": previous_generation,
        "new_generation": sealed_generation["generation"],
        "artifact": {
            "path": str(artifact.resolve()),
            "plugin_tree_sha256": staged_tree_sha256,
            "platform": sealed_generation["platform"],
        },
        "runtime": {
            "artifact_runtime_path": str((artifact / "plugins" / "sulde" / "runtime").resolve()),
            "runtime_tree_sha256": sealed_generation["runtime_tree_sha256"],
        },
        "registry": {
            **command_identity,
            "old_marketplace": str(previous_marketplace.resolve())
            if previous_marketplace is not None
            else None,
            "old_marketplace_tree_sha256": _optional_tree_digest(previous_marketplace),
            "old_version": previous_installation[0] if previous_installation else None,
            "old_installed_path": str(old_installed_path.resolve())
            if old_installed_path is not None
            else None,
            "old_plugin_tree_sha256": _optional_tree_digest(old_installed_path, warm=True),
            "new_marketplace": str(artifact.resolve()),
            "new_version": plugin_version(),
        },
        "launcher": {
            "path": str(launcher_path.resolve()),
            "old_sha256": _file_sha256(launcher_path),
            "new_generation": sealed_generation["generation"],
        },
        "deployment": {
            "path": str(generation_path.resolve()),
            "old_sha256": _file_sha256(generation_path),
            "new_generation": sealed_generation["generation"],
        },
        "installed_tree": {
            "path_authority": "canonical-cache-root-readback",
            "plugin_tree_sha256": staged_tree_sha256,
            "peer_session_authority": "observe-only-no-termination",
        },
        "expected_postconditions": {
            "provider": "codex",
            "platform": platform,
            "generation": sealed_generation["generation"],
            "runtime_tree_sha256": sealed_generation["runtime_tree_sha256"],
            "plugin_tree_sha256": staged_tree_sha256,
            "artifact": str(artifact.resolve()),
            "deployment": str(generation_path.resolve()),
            "launcher": str(launcher_path.resolve()),
            "retirements": _retirement_descriptors(retirements),
            "scheduler": {
                "owner": str((kb_home / RUNTIME_OWNER_NAME).resolve()),
                "runner": str((kb_home / "bin" / "sulde-scheduled-run").resolve()),
                "launchagents_dir": str(_launchagents_dir()),
                "old_loaded_labels": list(
                    actor_preflight.get("loaded_labels_before") or []
                ),
                "desired_labels": list(
                    actor_preflight.get("desired_labels") or []
                ),
            },
        },
    }


def _snapshot_targets(
    *,
    kb_home: Path,
    previous_install_paths: tuple[Path, ...],
    legacy_tree_paths: tuple[Path, ...],
    retirements: Sequence[CacheRetirement] = (),
    scheduler_labels: Sequence[str] = (),
) -> tuple[Path, ...]:
    launchers = tuple(launcher_home(kb_home) / "bin" / name for name in LAUNCHER_NAMES)
    return (
        *previous_install_paths,
        *legacy_tree_paths,
        *(plan.target for plan in retirements),
        *(plan.record for plan in retirements),
        *launchers,
        default_codex_home() / "AGENTS.md",
        kb_home / DEPLOYMENT_GENERATION_NAME,
        *_scheduler_snapshot_targets(kb_home, scheduler_labels),
    )


def _verify_old_registry(
    descriptor: dict[str, Any],
    *,
    runner: Runner,
) -> bool:
    registry = descriptor["registry"]
    codex = str(registry["codex_command"])
    marketplace = current_marketplace_root(codex, runner)
    installation = current_plugin_installation(codex, runner)
    old_marketplace = registry.get("old_marketplace")
    old_version = registry.get("old_version")
    if old_marketplace is None:
        return old_version is None and marketplace is None and installation is None
    if not isinstance(old_marketplace, str):
        return False
    if marketplace is None or marketplace.resolve() != Path(old_marketplace).resolve():
        return False
    old_marketplace_digest = registry.get("old_marketplace_tree_sha256")
    if not isinstance(old_marketplace_digest, str):
        return False
    try:
        if tree_digest(Path(old_marketplace)) != old_marketplace_digest:
            return False
    except InstallError:
        return False
    if old_version is None:
        return installation is None
    if not isinstance(old_version, str):
        return False
    if installation is None or installation[0] != old_version:
        return False
    old_path = registry.get("old_installed_path")
    old_digest = registry.get("old_plugin_tree_sha256")
    canonical = _canonical_cache_path(old_version)
    if isinstance(old_path, str) and canonical.resolve() != Path(old_path).resolve():
        return False
    if isinstance(old_digest, str):
        try:
            if warm_tree_state(canonical).tree_sha256 != old_digest:
                return False
        except InstallError:
            return False
    return True


def _verify_new_postconditions(
    descriptor: dict[str, Any],
    *,
    runner: Runner,
) -> Path:
    registry = descriptor["registry"]
    expected = descriptor["expected_postconditions"]
    codex = str(registry["codex_command"])
    marketplace = current_marketplace_root(codex, runner)
    installation = current_plugin_installation(codex, runner)
    if marketplace is None or marketplace.resolve() != Path(expected["artifact"]).resolve():
        raise InstallError("recovery postcondition registry marketplace differs")
    if installation is None or installation[0] != registry["new_version"]:
        raise InstallError("recovery postcondition registry installation differs")
    installed_path = _canonical_cache_path(str(registry["new_version"]))
    if not installed_path.is_dir() or installed_path.is_symlink():
        raise InstallError("recovery canonical cache installation is unavailable")
    installed_path = installed_path.resolve()
    if tree_digest(installed_path) != expected["plugin_tree_sha256"]:
        raise InstallError("recovery postcondition installed tree differs")
    sealed = _delivery_generation(installed_path, expected_version=str(registry["new_version"]))
    if (
        sealed.get("generation") != expected["generation"]
        or sealed.get("runtime_tree_sha256") != expected["runtime_tree_sha256"]
        or sealed.get("provider") != expected["provider"]
        or sealed.get("platform") != expected["platform"]
    ):
        raise InstallError("recovery postcondition installed generation differs")
    deployment = _read_json(Path(expected["deployment"]))
    launcher = _read_json(Path(expected["launcher"]))
    runtime = str((installed_path / "runtime").resolve())
    if (
        deployment.get("schema") != "sulde-installed-deployment-generation-v1"
        or type(deployment.get("schema_version")) is not int
        or deployment.get("schema_version") != 1
        or deployment.get("provider") != expected["provider"]
        or deployment.get("platform") != expected["platform"]
        or deployment.get("generation") != expected["generation"]
        or deployment.get("runtime_tree_sha256") != expected["runtime_tree_sha256"]
        or deployment.get("plugin_tree_sha256") != expected["plugin_tree_sha256"]
        or deployment.get("runtime_root") != runtime
        or deployment.get("installed_plugin") != str(installed_path.resolve())
        or deployment.get("status") != "generation_verified"
        or deployment.get("operational_ready") is not True
    ):
        raise InstallError("recovery postcondition deployment descriptor differs")
    native_authority = _installed_native_runtime_authority(
        installed_path,
        sealed,
        registry_codex=codex,
        runner=runner,
    )
    _verify_recomputed_native_runtime_authority(deployment, native_authority)
    _installed_native_authority_load_smoke(
        installed_path,
        Path(expected["deployment"]).parent,
        sealed,
        native_authority,
        runner=runner,
    )
    if (
        launcher.get("schema") != "sulde-launcher-install-v1"
        or type(launcher.get("schema_version")) is not int
        or launcher.get("schema_version") != 1
        or launcher.get("provider") != expected["provider"]
        or launcher.get("platform") != expected["platform"]
        or launcher.get("generation") != expected["generation"]
        or launcher.get("runtime_tree_sha256") != expected["runtime_tree_sha256"]
        or launcher.get("source_root") != runtime
    ):
        raise InstallError("recovery postcondition launcher descriptor differs")
    scheduler_expected = expected.get("scheduler")
    if not isinstance(scheduler_expected, dict):
        raise InstallError("recovery postcondition scheduler identity is missing")
    projection = _scheduler_generation_projection(
        Path(expected["deployment"]).parent,
        deployment,
        runner,
    )
    owner = projection.get("owner")
    if (
        not projection.get("healthy")
        or not isinstance(owner, dict)
        or owner.get("installation_status") != "generation_verified"
        or owner.get("operational_ready") is not True
        or projection.get("loaded_labels")
        != scheduler_expected.get("desired_labels")
    ):
        raise InstallError("recovery postcondition scheduler generation differs")
    _verify_retirement_descriptors(expected.get("retirements", []))
    return installed_path


def _recover_transaction(
    transaction: Transaction,
    *,
    codex: str,
    runner: Runner,
) -> dict[str, Any]:
    descriptor = transaction.descriptor
    supplied_identity = _codex_command_identity(codex)
    registry = descriptor["registry"]
    if any(registry.get(key) != value for key, value in supplied_identity.items()):
        raise InstallError(
            "recovery caller does not match the sealed Codex command identity"
        )
    stage = transaction.stage
    if stage in {"postconditions_verified", "committed", "cleanup_complete"}:
        installed_path = _verify_new_postconditions(descriptor, runner=runner)
        if stage == "postconditions_verified":
            transaction.append("committed")
        # Independent journal and postcondition readback precedes active cleanup.
        readback = load_active_transaction(transaction.recovery_root)
        if readback is None or readback.stage not in {"committed", "cleanup_complete"}:
            raise InstallError("committed recovery journal did not read back independently")
        _verify_new_postconditions(readback.descriptor, runner=runner)
        readback.clear_active()
        return {
            "status": "recovered_new_generation",
            "operational_status": "scheduler_ready_live_host_unverified",
            "operational_ready": False,
            "generation": descriptor["new_generation"],
            "installed_path": str(installed_path),
            "transaction_id": transaction.transaction_id,
            "recovery_evidence": str(transaction.transaction_root),
        }
    if stage in {"rolled_back"}:
        if not transaction.verify_restored_snapshot() or not _verify_old_registry(
            descriptor, runner=runner
        ):
            raise InstallError("rolled-back transaction no longer matches old generation")
        transaction.clear_active()
    else:
        if stage != "rollback_started":
            transaction.append("rollback_started")
        if not _verify_old_registry(descriptor, runner=runner):
            sealed_codex = str(registry["codex_command"])
            _registry_remove(sealed_codex, runner)
            old_marketplace = registry.get("old_marketplace")
            old_version = registry.get("old_version")
            if isinstance(old_marketplace, str):
                old_marketplace_digest = registry.get("old_marketplace_tree_sha256")
                if (
                    not isinstance(old_marketplace_digest, str)
                    or tree_digest(Path(old_marketplace)) != old_marketplace_digest
                ):
                    raise InstallError(
                        "sealed old marketplace bytes drifted before registry recovery"
                    )
                _restore_registry(
                    sealed_codex,
                    Path(old_marketplace),
                    str(old_version) if old_version is not None else None,
                    runner,
                )
        _remove_transaction_aliases(descriptor)
        transaction.restore_snapshot()
        _restore_scheduler_process_state(descriptor, runner=runner)
        _restore_preexisting_retirement_aliases(descriptor)
        if not _verify_old_registry(descriptor, runner=runner):
            raise InstallError("old registry generation did not verify after recovery")
        transaction.append("rolled_back")
        readback = load_active_transaction(transaction.recovery_root)
        if (
            readback is None
            or readback.stage != "rolled_back"
            or not readback.verify_restored_snapshot()
            or not _verify_old_registry(readback.descriptor, runner=runner)
        ):
            raise InstallError("rolled-back recovery authority did not read back independently")
        readback.clear_active()
    return {
        "status": "recovered_old_generation",
        "operational_status": "degraded",
        "operational_ready": False,
        "generation": descriptor.get("old_generation"),
        "transaction_id": transaction.transaction_id,
        "recovery_evidence": str(transaction.transaction_root),
    }


def _install_locked(
    *,
    artifact: Path,
    kb_home: Path,
    codex: str,
    platform: str,
    actor_preflight: dict[str, Any],
    host_preflight: dict[str, Any],
    deployment_lock_token: str,
    artifact_prepared: bool = False,
    prepared_artifact: PreparedArtifact | None = None,
    candidate_evidence: PreparedArtifact | None = None,
    candidate_receipt: dict[str, Any] | None = None,
    expected_live_state: dict[str, Any] | None = None,
    runner: Runner = run_command,
) -> dict[str, Any]:
    if expected_live_state is not None:
        # Close the gap between the outer locked CAS and the actual transaction.
        # This is still read-only and precedes snapshots or live mutation.
        _assert_deployment_cas(
            expected_live_state,
            kb_home=kb_home,
            codex=codex,
            runner=runner,
        )
    phase_started = time.perf_counter()
    phase_timings: dict[str, float] = {}

    def finish_phase(name: str) -> None:
        nonlocal phase_started
        now = time.perf_counter()
        phase_timings[name] = round(now - phase_started, 3)
        phase_started = now

    peer_session_observation = _observe_peer_session_safety()
    previous_marketplace = current_marketplace_root(codex, runner)
    previous_installation = current_plugin_installation(codex, runner)
    previous_install_paths = _previous_install_paths(previous_installation)
    legacy_sources = _legacy_install_sources(previous_install_paths)
    legacy_tree_paths = tuple(
        row.target
        for row in legacy_sources
        if row.mode in {"existing_cache", "persistent_artifact_recovery"}
        and row.target.is_dir()
        and not row.target.is_symlink()
    )
    launcher_snapshot = _snapshot_launchers(kb_home)
    agents_md = default_codex_home() / "AGENTS.md"
    agents_snapshot = _snapshot_file(agents_md)
    generation_path = kb_home / DEPLOYMENT_GENERATION_NAME
    generation_snapshot = _snapshot_file(generation_path)
    previous_snapshot_root = Path(
        tempfile.mkdtemp(prefix="sulde-codex-previous-install-")
    )
    previous_snapshots: list[tuple[Path, Path]] = []
    legacy_prestate_snapshots: list[tuple[Path, Path]] = []
    controlled_target_snapshots: list[tuple[Path, Path]] = []
    retirements: tuple[CacheRetirement, ...] = ()
    transaction: Transaction | None = None
    switched = False
    rollback_errors: list[str] = []
    try:
        previous_snapshots = _snapshot_previous_install_paths(
            previous_install_paths,
            previous_snapshot_root / "current",
        )
        legacy_prestate_snapshots = _snapshot_plugin_trees(
            legacy_tree_paths,
            previous_snapshot_root / "legacy-prestate",
        )
        controlled_sources = tuple(
            row.source for row in legacy_sources if row.mode == "controlled_retired_alias"
        )
        controlled_target_snapshots = _snapshot_plugin_trees(
            controlled_sources,
            previous_snapshot_root / "controlled-retired-prestate",
        )
        if not artifact_prepared:
            prepared_artifact = _stage_artifact(
                artifact,
                platform=platform,
                runner=runner,
            )
        artifact_plugin = artifact / "plugins" / "sulde"
        if (
            prepared_artifact is not None
            and prepared_artifact.marketplace.resolve() != artifact.resolve()
        ):
            raise InstallError("prepared artifact evidence belongs to another marketplace")
        if prepared_artifact is None:
            artifact_descriptor = validate_plugin_root(
                artifact_plugin,
                expected_version=plugin_version(),
            )
            staged_tree_sha256 = tree_digest(artifact_plugin)
        else:
            artifact_descriptor = prepared_artifact.descriptor
            staged_tree_sha256 = prepared_artifact.plugin_tree_sha256
        sealed_generation = artifact_descriptor["delivery_generation"]
        if candidate_receipt is not None:
            receipt_evidence = candidate_evidence or prepared_artifact
            if receipt_evidence is None or expected_live_state is None:
                raise InstallError(
                    "candidate promotion requires prepared artifact and live prestate"
                )
            _validated_candidate_receipt(
                candidate_receipt,
                prepared=receipt_evidence,
                expected_live_state=expected_live_state,
                codex=codex,
                runner=runner,
            )
        legacy_prestate = {
            path.expanduser(): snapshot for path, snapshot in legacy_prestate_snapshots
        }
        controlled_prestate = {
            path.expanduser(): snapshot for path, snapshot in controlled_target_snapshots
        }
        retirement_inputs: list[tuple[Path, Path]] = list(previous_snapshots)
        for legacy in legacy_sources:
            if legacy.mode == "existing_cache":
                retirement_inputs.append(
                    (legacy.target, legacy_prestate[legacy.target.expanduser()])
                )
            elif legacy.mode == "controlled_retired_alias":
                retirement_inputs.append(
                    (legacy.target, controlled_prestate[legacy.source.expanduser()])
                )
            else:
                retirement_inputs.append((legacy.target, legacy.source))
        retirements = _prepare_cache_retirements(
            retirement_inputs,
            current_install=artifact_plugin,
            preparation_root=previous_snapshot_root / "normalized-retirements",
        )
        descriptor = _transaction_descriptor(
            transaction_id=uuid.uuid4().hex,
            artifact=artifact,
            kb_home=kb_home,
            codex=codex,
            platform=platform,
            previous_marketplace=previous_marketplace,
            previous_installation=previous_installation,
            sealed_generation=sealed_generation,
            staged_tree_sha256=staged_tree_sha256,
            retirements=retirements,
            actor_preflight=actor_preflight,
        )
        transaction = begin_transaction(
            kb_home / INSTALL_RECOVERY_NAME,
            descriptor,
            snapshot_paths=_snapshot_targets(
                kb_home=kb_home,
                previous_install_paths=previous_install_paths,
                legacy_tree_paths=legacy_tree_paths,
                retirements=retirements,
                scheduler_labels=tuple(
                    str(value) for value in actor_preflight.get("desired_labels", [])
                ),
            ),
            failpoint=_failure_boundary,
        )
        transaction.append("prepared")
        finish_phase("snapshot_and_prepare")
        _failure_boundary("normalization.before_publish")
        _publish_retirement_targets(retirements)
        _failure_boundary("normalization.after_publish")
        transaction.append("registry_remove_started")
        _failure_boundary("registry.before_remove")
        _registry_remove(codex, runner)
        _failure_boundary("registry.after_remove")
        switched = True
        transaction.append("registry_removed")
        transaction.append("registry_add_started")
        _failure_boundary("registry.before_add")
        installed_path = _registry_add(
            codex,
            artifact,
            runner,
            expected_version=plugin_version(),
        )
        _failure_boundary("registry.after_add")
        transaction.append("registry_added")
        if not installed_path.is_dir():
            raise InstallError(f"Codex installed path does not exist: {installed_path}")
        installed_descriptor = validate_plugin_root(
            installed_path,
            expected_version=plugin_version(),
        )
        installed_tree_sha256 = tree_digest(installed_path)
        if installed_tree_sha256 != staged_tree_sha256:
            raise InstallError("Codex cache content does not match the staged plugin artifact")
        artifact_capabilities = installed_descriptor["host_capability_contract"]
        finish_phase("registry_switch_and_readback")
        transaction.append("launcher_publish_started")
        _failure_boundary("launcher.before_publish")
        launcher_evidence = _install_launchers(
            installed_path,
            kb_home,
            runner,
            platform=platform,
        )
        _failure_boundary("launcher.after_publish")
        transaction.append("launcher_published")
        sealed_generation = installed_descriptor["delivery_generation"]
        if (
            launcher_evidence.get("generation") != sealed_generation["generation"]
            or launcher_evidence.get("runtime_tree_sha256")
            != sealed_generation["runtime_tree_sha256"]
        ):
            raise InstallError(
                "stable launcher is not bound to the installed delivery generation"
            )
        global_rules_evidence = _install_global_rules(installed_path, kb_home, runner)
        if candidate_receipt is None:
            smoke = _smoke_installed(
                installed_path,
                kb_home,
                codex=codex,
                expected_tree_sha256=staged_tree_sha256,
                runner=runner,
                installed_descriptor=installed_descriptor,
                installed_tree_sha256=installed_tree_sha256,
            )
        else:
            smoke = _smoke_promoted_candidate(
                installed_path,
                kb_home,
                codex=codex,
                expected_tree_sha256=staged_tree_sha256,
                runner=runner,
                installed_descriptor=installed_descriptor,
                installed_tree_sha256=installed_tree_sha256,
                candidate_receipt=candidate_receipt,
            )
        _failure_boundary("bridge.before_publish")
        _publish_retirement_aliases(retirements)
        _failure_boundary("bridge.after_publish")
        finish_phase("launcher_rules_and_smoke")
        preserved_previous_paths = [
            {"path": str(path), "mode": "current_install"}
            for path, _snapshot in previous_snapshots
            if path.resolve() == installed_path.resolve()
        ]
        legacy_cache_restorations = [
            {
                "path": str(plan.alias),
                "mode": "controlled_retired_alias",
                "retired_target": str(plan.target),
                "restored_tree_sha256": plan.expected_tree_sha256,
                "derived_bytecode_removed": list(plan.prestate.bytecode_inventory),
            }
            for plan in retirements
        ]
        live_session_bridges = [
            {
                "path": str(plan.alias),
                "target": str(plan.target),
                "version": plan.alias.name,
                "mode": "stable_current_runtime_bridge",
                "entrypoints": {
                    relative.as_posix(): hashlib.sha256(
                        (plan.target / relative).read_bytes()
                    ).hexdigest()
                    for relative in LIVE_SESSION_BRIDGE_FILES
                },
            }
            for plan in retirements
        ]
        deployment_generation = _deployment_generation(
            installed_path,
            artifact,
            plugin_tree_sha256=staged_tree_sha256,
            codex=codex,
            runner=runner,
        )
        if deployment_generation["generation"] != launcher_evidence["generation"]:
            raise InstallError("deployment descriptor and stable launcher generations differ")
        transaction.append("deployment_publish_started")
        _failure_boundary("deployment.before_publish")
        _write_deployment_generation(kb_home, deployment_generation)
        _failure_boundary("deployment.after_publish")
        transaction.append("deployment_published")
        smoke["native_runtime_authority_load"] = (
            _installed_native_authority_load_smoke(
                installed_path,
                kb_home,
                sealed_generation,
                deployment_generation["native_runtime_authority"],
                runner=runner,
            )
        )
        transaction.append("scheduler_reconcile_started")
        _failure_boundary("scheduler.before_reconcile")
        scheduler_generation = _scheduler_reconcile_installed_generation(
            installed_path=installed_path,
            kb_home=kb_home,
            codex=codex,
            deployment_lock_token=deployment_lock_token,
            runner=runner,
        )
        _failure_boundary("scheduler.after_reconcile")
        transaction.append("scheduler_reconciled")
        finish_phase("deployment_and_scheduler")
        deployment_generation = _read_json(generation_path)
        kb_initialized = (kb_home / "kb.db").is_file() and (kb_home / "memory.db").is_file()
        bootstrap_command = (
            f'"{installed_path / "runtime" / "scripts" / "kb" / "bootstrap.sh"}" '
            "--host codex"
        )
        hook_trust = smoke["hook_trust"]
        hook_trust_ready = hook_trust.get("status") == "ready"
        hook_trust_reason = (
            "Codex reports every required Sulde Hook as enabled and trusted; "
            "a fresh session must still prove live pre-execution denial"
            if hook_trust_ready
            else "Codex has not reported every required Sulde Hook as runnable; "
            "review the host Hook trust card, then start a fresh session"
        )
        live_status = (
            "live_unverified" if hook_trust_ready else "hook_trust_review_required"
        )
        result = {
            "status": "generation_verified",
            "operational_status": (
                "scheduler_ready_live_host_unverified"
                if hook_trust_ready
                else "scheduler_ready_hook_trust_review_required"
            ),
            "operational_ready": False,
            "ready_scope": (
                "atomic_generation_ready_live_host_unverified"
                if hook_trust_ready
                else "atomic_generation_ready_hook_trust_review_required"
            ),
            "artifact": str(artifact.resolve()),
            "installed_path": str(installed_path),
            "plugin_version": plugin_version(),
            "previous_marketplace": str(previous_marketplace) if previous_marketplace else None,
            "previous_plugin_version": previous_installation[0] if previous_installation else None,
            "preserved_previous_paths": preserved_previous_paths,
            "legacy_cache_restorations": legacy_cache_restorations,
            "live_session_bridges": live_session_bridges,
            "peer_session_observation": peer_session_observation,
            "deployment_generation": deployment_generation,
            "scheduler_actor_preflight": actor_preflight,
            "codex_host_preflight": host_preflight,
            "scheduler_generation": scheduler_generation,
            "scheduler_reconciliation_command": None,
            "launcher_contract": launcher_evidence,
            "global_rules": global_rules_evidence,
            "staged_plugin_tree_sha256": staged_tree_sha256,
            "smoke": smoke,
            "host_capabilities": {
                "artifact": artifact_capabilities,
                "synthetic": smoke["host_readiness"],
                "live": {
                    "status": live_status,
                    "hook_trust": hook_trust,
                    "reason": (
                        hook_trust_reason
                        + "; synthetic observations never grant authority"
                    ),
                },
            },
            "interactive_supervision": {
                "status": live_status,
                "live_host_hook_verified": False,
                "hook_trust": hook_trust,
                "synthetic_round_trip": smoke["proposal_control_round_trip"],
                "synthetic_authority_rejected": smoke["synthetic_authority_rejected"],
                "reason": (
                    hook_trust_reason
                ),
                "verification_command": (
                    f'"{launcher_home(kb_home) / "bin" / "intent-guardian"}" doctor '
                    "--workspace <project-path> --provider codex"
                ),
            },
            "kb_initialized": kb_initialized,
            "kb_initialization_command": None if kb_initialized else bootstrap_command,
            "restart_required": True,
            "hook_restart_required": True,
            "hook_hot_rebind_available": bool(live_session_bridges),
            "hook_restart_reason": (
                "a stable bridge can refresh code only for Hook subscriptions the host "
                "still dispatches; "
                + hook_trust_reason
            ),
            "skill_catalog_restart_required": True,
        }
        _verify_new_postconditions(transaction.descriptor, runner=runner)
        transaction.append("postconditions_verified")
        # Codex may refresh its built-in system skills while registry and Hook
        # postconditions are being read.  Those helpers are inputs to the
        # command-effect allowlist, so the launcher snapshot created before
        # the smoke can become stale inside the same otherwise-successful
        # transaction.  Re-pin only after the last Codex host read, while the
        # deployment lock and rollback snapshot are still active.
        _failure_boundary("launcher.final_repin.before_publish")
        launcher_evidence = _install_launchers(
            installed_path,
            kb_home,
            runner,
            platform=platform,
        )
        _failure_boundary("launcher.final_repin.after_publish")
        if (
            launcher_evidence.get("generation")
            != deployment_generation["generation"]
            or launcher_evidence.get("runtime_tree_sha256")
            != deployment_generation["runtime_tree_sha256"]
        ):
            raise InstallError(
                "final launcher snapshot and deployment generation differ"
            )
        result["launcher_contract"] = launcher_evidence
        transaction.append("committed")
        committed = load_active_transaction(kb_home / INSTALL_RECOVERY_NAME)
        if committed is None or committed.stage != "committed":
            raise InstallError("committed install journal did not read back independently")
        if committed.descriptor != transaction.descriptor:
            raise InstallError("committed install journal descriptor changed on readback")
        committed.clear_active()
        finish_phase("postconditions_and_commit")
        result["install_timings_seconds"] = {
            **phase_timings,
            "locked_total": round(sum(phase_timings.values()), 3),
        }
        shutil.rmtree(previous_snapshot_root, ignore_errors=True)
        return result
    except Exception as error:
        if transaction is not None and transaction.stage not in {
            "rollback_started",
            "rolled_back",
            "committed",
            "cleanup_complete",
        }:
            try:
                transaction.append("rollback_started")
            except Exception as rollback_error:
                rollback_errors.append(f"journal rollback start: {rollback_error}")
        if switched:
            try:
                _registry_remove(codex, runner)
                if previous_marketplace is not None:
                    _restore_registry(
                        codex,
                        previous_marketplace,
                        previous_installation[0]
                        if previous_installation is not None
                        else None,
                        runner,
                    )
            except Exception as rollback_error:
                rollback_errors.append(f"registry rollback: {rollback_error}")
        for previous_path, snapshot in previous_snapshots:
            try:
                _restore_previous_install_path(previous_path, snapshot)
            except Exception as rollback_error:
                rollback_errors.append(
                    f"previous runtime rollback {previous_path}: {rollback_error}"
                )
        for legacy_path, snapshot in legacy_prestate_snapshots:
            try:
                _restore_previous_install_path(legacy_path, snapshot)
            except Exception as rollback_error:
                rollback_errors.append(
                    f"legacy runtime rollback {legacy_path}: {rollback_error}"
                )
        rollback_errors.extend(_restore_launchers(kb_home, launcher_snapshot))
        rollback_errors.extend(_restore_file(agents_md, agents_snapshot))
        rollback_errors.extend(_restore_file(generation_path, generation_snapshot))
        if transaction is not None:
            try:
                _remove_transaction_aliases(transaction.descriptor)
                transaction.restore_snapshot()
                _restore_scheduler_process_state(
                    transaction.descriptor,
                    runner=runner,
                )
                _restore_preexisting_retirement_aliases(transaction.descriptor)
                if not _verify_old_registry(transaction.descriptor, runner=runner):
                    raise InstallError("old registry generation did not verify")
                if not rollback_errors:
                    transaction.append("rolled_back")
                    readback = load_active_transaction(kb_home / INSTALL_RECOVERY_NAME)
                    if (
                        readback is None
                        or readback.stage != "rolled_back"
                        or not readback.verify_restored_snapshot()
                        or not _verify_old_registry(readback.descriptor, runner=runner)
                    ):
                        raise InstallError("rollback journal did not read back independently")
                    readback.clear_active()
            except Exception as rollback_error:
                rollback_errors.append(f"durable transaction rollback: {rollback_error}")
        shutil.rmtree(previous_snapshot_root, ignore_errors=True)
        detail = f"; rollback issues: {'; '.join(rollback_errors)}" if rollback_errors else ""
        raise InstallError(f"install did not verify and was rolled back: {error}{detail}") from error


def install(
    *,
    artifact: Path,
    kb_home: Path,
    codex: str,
    platform: str,
    prepared_artifact: PreparedArtifact | None = None,
    candidate_receipt: dict[str, Any] | None = None,
    expected_live_state: dict[str, Any] | None = None,
    runner: Runner = run_command,
) -> dict[str, Any]:
    install_started = time.perf_counter()
    host_preflight_started = install_started
    # This read-only gate intentionally precedes even the deployment lock: a
    # stopped host must observe zero registry, descriptor, cache, launcher, or
    # temporary transaction-marker changes.
    host_preflight = _codex_host_preflight(runner)
    try:
        python_preflight = invoking_environment()
        from launcher_contract import runtime_interpreter
        target_python = runtime_interpreter(kb_home)
        required_venv = kb_home / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not required_venv.is_file():
            raise InstallError(
                "installation runtime venv is missing; MCP requires the selected Python under "
                "the target data root. Explicitly prepare that isolated venv with the verified "
                "interpreter and hooks/requirements.txt before installing; no registry switch was attempted"
            )
        target_identity = (python_preflight if target_python.absolute() == Path(python_preflight["executable"])
                           else inspect_python(target_python))
        if not same_runtime(python_preflight, target_identity):
            raise InstallError("stable launcher Python dependencies differ from the verified installation environment")
    except PythonEnvironmentError as error:
        raise InstallError(str(error)) from error
    outer_timings = {
        "host_preflight": round(time.perf_counter() - host_preflight_started, 3)
    }
    lock_started = time.perf_counter()
    with _deployment_lock(kb_home) as deployment_lock_token:
        try:
            active = load_active_transaction(
                kb_home / INSTALL_RECOVERY_NAME,
                failpoint=_failure_boundary,
            )
        except JournalError as error:
            raise InstallError(
                f"ambiguous durable install recovery state was retained: {error}"
            ) from error
        if active is not None:
            try:
                recovered = _recover_transaction(
                    active,
                    codex=codex,
                    runner=runner,
                )
                outer_timings["deployment_lock_and_recovery"] = round(
                    time.perf_counter() - lock_started, 3
                )
                outer_timings["total"] = round(
                    time.perf_counter() - install_started, 3
                )
                recovered["install_timings_seconds"] = outer_timings
                return recovered
            except (JournalError, InstallError) as error:
                raise InstallError(
                    f"durable install recovery failed closed and evidence was retained: {error}"
                ) from error
        candidate_arguments = (
            prepared_artifact is not None,
            candidate_receipt is not None,
            expected_live_state is not None,
        )
        if any(candidate_arguments) and not all(candidate_arguments):
            raise InstallError(
                "candidate promotion requires prepared artifact, receipt, and live prestate"
            )
        if expected_live_state is not None:
            _assert_deployment_cas(
                expected_live_state,
                kb_home=kb_home,
                codex=codex,
                runner=runner,
            )
        if candidate_receipt is not None and candidate_receipt.get("python") != python_preflight:
            raise InstallError("installation must use the verified candidate Python environment")
        test_prepared = (
            os.environ.get("SULDE_TEST_MODE") == "1"
            and os.environ.get("SULDE_TEST_PREPARED_ARTIFACT") == "1"
        )
        outer_timings["deployment_lock_and_recovery_scan"] = round(
            time.perf_counter() - lock_started, 3
        )
        artifact_started = time.perf_counter()
        if prepared_artifact is not None:
            if prepared_artifact.marketplace.resolve() != artifact.resolve():
                raise InstallError("prepared candidate belongs to another artifact path")
            prepared_descriptor = validate_staged_marketplace(
                artifact,
                expected_version=plugin_version(),
            )
            prepared_digest = tree_digest(artifact / "plugins" / "sulde")
            if (
                prepared_descriptor != prepared_artifact.descriptor
                or prepared_digest != prepared_artifact.plugin_tree_sha256
            ):
                raise InstallError("prepared candidate bytes changed after verification")
            prepared_artifact = PreparedArtifact(
                artifact.resolve(), prepared_descriptor, prepared_digest
            )
        elif test_prepared:
            prepared_descriptor = validate_staged_marketplace(
                artifact,
                expected_version=plugin_version(),
            )
            prepared_artifact = PreparedArtifact(
                artifact.resolve(),
                prepared_descriptor,
                tree_digest(artifact / "plugins" / "sulde"),
            )
        else:
            prepared_artifact = _stage_artifact(
                artifact,
                platform=platform,
                runner=runner,
            )
        candidate_evidence: PreparedArtifact | None = None
        if candidate_receipt is not None:
            assert prepared_artifact is not None
            assert expected_live_state is not None
            _validated_candidate_receipt(
                candidate_receipt,
                prepared=prepared_artifact,
                expected_live_state=expected_live_state,
                codex=codex,
                runner=runner,
            )
            candidate_evidence = prepared_artifact
            prepared_artifact = _publish_verified_candidate_artifact(
                candidate_evidence,
                platform=platform,
                runner=runner,
            )
            artifact = prepared_artifact.marketplace
        outer_timings["artifact_stage_and_validation"] = round(
            time.perf_counter() - artifact_started, 3
        )
        pre_install_started = time.perf_counter()
        staged_plugin = artifact / "plugins" / "sulde"
        actor_preflight = _scheduler_actor_preflight(
            staged_plugin / "runtime",
            runner,
        )
        migration_source = _legacy_home_migration_source(kb_home)
        migration_activation: dict[str, object] | None = None
        memory_reconciliation: dict[str, Any] | None = None
        writers_quiesced = False
        receipt: Path | None = None

        def quiesce_writers_once() -> None:
            nonlocal writers_quiesced
            if not writers_quiesced:
                _quiesce_loaded_scheduler_writers(actor_preflight, runner)
                writers_quiesced = True

        if migration_source is not None:
            quiesce_writers_once()
            descriptor, receipt_name = tempfile.mkstemp(
                prefix="sulde-home-quiescence-", suffix=".json"
            )
            receipt = Path(receipt_name)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(
                    _canonical_json_bytes(
                        {
                            "schema": QUIESCENCE_SCHEMA,
                            "status": "quiesced",
                            "source": str(migration_source),
                            "active_writers": 0,
                            "loaded_scheduler_labels": [],
                            "token": uuid.uuid4().hex,
                        }
                    )
                    + b"\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(receipt, 0o600)
            try:
                migration_activation = apply_home_migration(
                    migration_source,
                    sulde_layout(home=launcher_home(kb_home)),
                    receipt,
                )
            except HomeMigrationError as error:
                _restore_scheduler_process_state(
                    {
                        "expected_postconditions": {
                            "scheduler": {
                                "old_loaded_labels": actor_preflight.get("loaded_labels_before", []),
                                "desired_labels": actor_preflight.get("desired_labels", []),
                                "launchagents_dir": str(_launchagents_dir()),
                            }
                        }
                    },
                    runner=runner,
                )
                raise InstallError(f"legacy Sulde home migration failed: {error}") from error
        legacy_memory = _legacy_memory_database(kb_home)
        if legacy_memory is not None:
            try:
                memory_plan = plan_memory_reconciliation(
                    legacy_memory,
                    kb_home / "memory.db",
                )
                if memory_plan.get("reconcile_required") is True:
                    quiesce_writers_once()
                    memory_reconciliation = reconcile_memory_homes(
                        legacy_memory,
                        kb_home / "memory.db",
                        archive_root=(
                            launcher_home(kb_home)
                            / "control"
                            / "memory-migrations"
                        ),
                    )
            except (MemoryReconcileError, OSError, sqlite3.Error, ValueError) as error:
                raise InstallError(
                    f"legacy memory reconciliation failed: {error}"
                ) from error
        try:
            try:
                identity_activation = ensure_contract_identity_map(
                    sulde_layout(home=launcher_home(kb_home))
                )
            except HomeMigrationError as error:
                raise InstallError(
                    f"migrated contract identity activation failed: {error}"
                ) from error
            outer_timings["scheduler_and_home_preflight"] = round(
                time.perf_counter() - pre_install_started,
                3,
            )
            result = _install_locked(
                artifact=artifact,
                kb_home=kb_home,
                codex=codex,
                platform=platform,
                actor_preflight=actor_preflight,
                host_preflight=host_preflight,
                deployment_lock_token=deployment_lock_token,
                artifact_prepared=True,
                prepared_artifact=prepared_artifact,
                candidate_evidence=candidate_evidence,
                candidate_receipt=candidate_receipt,
                expected_live_state=expected_live_state,
                runner=runner,
            )
            locked_timings = result.get("install_timings_seconds", {})
            result["install_timings_seconds"] = {
                **outer_timings,
                **locked_timings,
                "total": round(time.perf_counter() - install_started, 3),
            }
            active_home = migration_activation or identity_activation
            if active_home is not None:
                result["home_migration"] = {
                    key: active_home[key]
                    for key in (
                        "status", "source", "sulde_home", "kb_home",
                        "manifest_sha256", "contract_identity_map_sha256",
                        "transaction_id",
                    )
                }
            if memory_reconciliation is not None:
                result["memory_reconciliation"] = memory_reconciliation
            return result
        except Exception:
            if migration_activation is not None:
                loaded = _loaded_sulde_labels(runner)
                expected = set(actor_preflight.get("loaded_labels_before") or [])
                if loaded is not None and set(loaded) != expected:
                    raise InstallError(
                        "install failed and legacy scheduler state is not safe for home rollback"
                    )
                if memory_reconciliation is not None:
                    restore_legacy_write_mode(memory_reconciliation)
                rollback_home_migration(
                    migration_activation,
                    sulde_layout(home=launcher_home(kb_home)),
                    allow_quiesced_managed_drift=True,
                )
            raise
        finally:
            if receipt is not None:
                try:
                    receipt.unlink()
                except OSError:
                    pass


def recover_only(
    *,
    kb_home: Path,
    codex: str,
    runner: Runner = run_command,
) -> dict[str, Any]:
    """Recover one durable install transaction without staging or Guardian.

    This entrypoint intentionally lives in the installer rather than the
    candidate controller or any Hook.  It remains usable when either of those
    control paths is the component that failed.
    """

    with _deployment_lock(kb_home):
        try:
            active = load_active_transaction(
                kb_home / INSTALL_RECOVERY_NAME,
                failpoint=_failure_boundary,
            )
        except JournalError as error:
            raise InstallError(
                f"ambiguous durable install recovery state was retained: {error}"
            ) from error
        if active is None:
            return {
                "status": "no_recovery_required",
                "kb_home": str(kb_home.resolve()),
            }
        try:
            return _recover_transaction(active, codex=codex, runner=runner)
        except (JournalError, InstallError) as error:
            raise InstallError(
                f"durable install recovery failed closed and evidence was retained: {error}"
            ) from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--kb-home", type=Path, default=default_kb_home())
    parser.add_argument("--codex", default=DEFAULT_CODEX_EXECUTABLE)
    parser.add_argument(
        "--platform",
        choices=("posix", "windows"),
        default="windows" if os.name == "nt" else "posix",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--recover-only",
        action="store_true",
        help="recover an active install transaction without staging or installing",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    configure_utf8_stdio()
    args = _parser().parse_args()
    artifact = (args.artifact_root or default_artifact_root()).expanduser()
    if args.dry_run and args.recover_only:
        print("SULDE CODEX INSTALL: FAIL: --dry-run and --recover-only conflict", file=sys.stderr)
        return 2
    if args.recover_only:
        try:
            result = recover_only(
                kb_home=args.kb_home.expanduser(),
                codex=args.codex,
            )
        except InstallError as error:
            print(f"SULDE CODEX RECOVERY: FAIL: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2 if not args.json else None))
        return 0
    if args.dry_run:
        result = {
            "status": "dry-run",
            "artifact": str(artifact),
            "kb_home": str(args.kb_home.expanduser()),
            "plugin_version": plugin_version(),
            "platform": args.platform,
            "steps": [
                "stage self-contained marketplace into a new persistent path",
                "validate guardian skills, hooks and runtime files",
                (
                    "quiesce memory writers, back up and deduplicate the legacy host "
                    "database into the neutral Sulde home"
                ),
                "switch the Codex marketplace/plugin registration",
                "install and verify the stable launcher contract",
                (
                    "pin trusted local script effects to exact interpreter, content, "
                    "and argv contracts outside the workspace"
                ),
                (
                    "smoke intent creation, prompt approval receipt consumption, "
                    "an unapproved MCP-write denial, and packaged/stable MCP initialize handshakes"
                ),
                "report live interactive supervision as unverified until a restarted host event",
                "pin the previous cache path to its pre-switch bytes for live sessions",
                "roll back registry and launchers if any proof fails",
            ],
            "writes": 0,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2 if not args.json else None))
        return 0
    try:
        result = install(
            artifact=artifact,
            kb_home=args.kb_home.expanduser(),
            codex=args.codex,
            platform=args.platform,
        )
    except InstallError as error:
        print(f"SULDE CODEX INSTALL: FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if not args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

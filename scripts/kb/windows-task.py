#!/usr/bin/env python3
"""Stable Windows Task Scheduler entrypoint for Sulde background jobs."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import re


KB_HOME = Path(
    os.environ.get(
        "SULDE_KB_HOME",
        Path.home() / ".sulde" / "data" / "kb",
    )
).expanduser()


SAFE_ENVIRONMENT = {
    "COMSPEC",
    "LANG",
    "LC_ALL",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TZ",
    "USERDOMAIN",
    "USERNAME",
    "USERPROFILE",
    "WINDIR",
}

DESIRED_TASK_NAMES = frozenset({"Sulde-Codex-Harvest", "Sulde-Daily-Distill"})
RETIRED_TASK_NAMES = frozenset({"Sulde-Claude-Harvest", "Sulde-Claude-Distill"})
WINDOWS_PROVIDER = "codex"
WINDOWS_PLATFORM = "windows"
DELIVERY_FIELDS = frozenset(
    {
        "schema",
        "schema_version",
        "provider",
        "platform",
        "plugin_version",
        "runtime_tree_sha256",
        "generation",
    }
)
DEPLOYMENT_FIELDS = frozenset(
    {
        "schema",
        "schema_version",
        "provider",
        "platform",
        "artifact_platform",
        "status",
        "operational_ready",
        "plugin_version",
        "plugin_tree_sha256",
        "runtime_tree_sha256",
        "generation",
        "artifact",
        "installed_plugin",
        "runtime_root",
        "managed_labels",
        "scheduler_runner",
        "scheduler_runner_sha256",
    }
)
LAUNCHER_FIELDS = frozenset(
    {
        "schema",
        "schema_version",
        "spec_version",
        "provider",
        "platform",
        "generated_at",
        "source_root",
        "runtime_sha256",
        "runtime_tree_sha256",
        "generation",
        "interpreter",
        "interpreter_sha256",
        "interpreter_prefix",
        "codex_hook_surface_sha256",
        "command_effects_sha256",
        "launchers",
        "scheduler_runner",
        "scheduler_runner_sha256",
    }
)
OWNER_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "installation_status",
        "operational_ready",
        "provider",
        "executable",
        "source_root",
        "runtime_root",
        "runtime_tree_sha256",
        "generation",
        "scheduler_runner_sha256",
        "managed_labels",
        "retired_labels",
        "task_readback",
        "scheduler",
        "installed_at",
    }
)
TASK_READBACK_FIELDS = frozenset(
    {
        "task_name",
        "action_execute",
        "action_arguments",
        "runtime_root",
        "generation",
        "runner_sha256",
        "LastTaskResult",
    }
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_plain_retired_tree(root: Path) -> None:
    if root.is_symlink():
        raise RuntimeError(f"retired-state root is a symbolic link: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"retired-state entry is a symbolic link: {path}")


def snapshot_retired_state(retired_root: Path, snapshot_root: Path) -> None:
    """Snapshot retired-state existence, entries, bytes and portable mode bits.

    This executable helper supplies deterministic non-Windows fault-injection
    coverage for the equivalent PowerShell transaction functions. Windows DACL
    capture and restoration remain in install-agents.ps1.
    """
    if snapshot_root.exists() or snapshot_root.is_symlink():
        raise RuntimeError(f"retired-state snapshot already exists: {snapshot_root}")
    if retired_root.exists() and not retired_root.is_dir():
        raise RuntimeError(f"retired-state root is not a directory: {retired_root}")
    present = retired_root.is_dir()
    snapshot_root.mkdir(parents=True)
    if present:
        _assert_plain_retired_tree(retired_root)
        shutil.copytree(retired_root, snapshot_root / "tree", copy_function=shutil.copy2)
    (snapshot_root / "manifest.json").write_text(
        json.dumps({"schema": "sulde-windows-retired-snapshot-v1", "present": present}),
        encoding="utf-8",
    )


def restore_retired_state(retired_root: Path, snapshot_root: Path) -> None:
    """Replace retired state with the byte-exact tree captured before mutation."""
    try:
        manifest = json.loads((snapshot_root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("retired-state transaction snapshot is invalid") from error
    if manifest.get("schema") != "sulde-windows-retired-snapshot-v1" or not isinstance(
        manifest.get("present"), bool
    ):
        raise RuntimeError("retired-state transaction snapshot is invalid")
    if retired_root.is_symlink():
        raise RuntimeError(f"refusing to replace retired-state symbolic link: {retired_root}")
    if retired_root.exists():
        if not retired_root.is_dir():
            raise RuntimeError(f"refusing to replace non-directory retired state: {retired_root}")
        _assert_plain_retired_tree(retired_root)
        shutil.rmtree(retired_root)
    if manifest["present"]:
        saved_tree = snapshot_root / "tree"
        if not saved_tree.is_dir():
            raise RuntimeError("retired-state transaction tree is missing")
        _assert_plain_retired_tree(saved_tree)
        retired_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(saved_tree, retired_root, copy_function=shutil.copy2)


def reconcile_task_state(
    previous: dict[str, object],
    desired: dict[str, dict[str, object]],
    *,
    fail_after: int | None,
) -> dict[str, object]:
    """Pure model of the PowerShell desired-state transaction.

    The installer uses the same inventory rule and freezes runner, owner and
    exported task XML before mutation.  This model makes second-registration
    failure and exact rollback deterministic on non-Windows test hosts.
    """
    snapshot = copy.deepcopy(previous)
    tasks = previous.get("tasks")
    if not isinstance(tasks, dict):
        raise RuntimeError("Windows task snapshot is missing")
    outside_desired = set(tasks) - set(desired)
    unknown = sorted(
        name
        for name in outside_desired
        if name.startswith("Sulde-") and name not in RETIRED_TASK_NAMES
    )
    if unknown:
        raise RuntimeError("unknown Sulde task blocks reconciliation: " + ", ".join(unknown))
    generations = {
        row.get("generation") for row in desired.values() if isinstance(row, dict)
    }
    if len(generations) != 1 or not all(isinstance(value, str) and value for value in generations):
        raise RuntimeError("desired Windows tasks do not declare one generation")
    try:
        installed: dict[str, dict[str, object]] = {}
        for index, (name, row) in enumerate(desired.items()):
            if fail_after is not None and index >= fail_after:
                raise RuntimeError("injected registration failure")
            installed[name] = copy.deepcopy(row)
        result = copy.deepcopy(previous)
        result["tasks"] = installed
        result["owner"] = {
            "status": "active",
            "installation_status": "installed_degraded",
            "operational_ready": False,
            "generation": next(iter(generations)),
            "managed_labels": sorted(desired),
            "retired_labels": sorted(set(tasks) & RETIRED_TASK_NAMES),
        }
        return result
    except Exception as error:
        raise RuntimeError(str(error), snapshot) from error


def read_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"generation authority is missing or unsafe: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"generation authority is invalid: {path}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"generation authority is not an object: {path}")
    return payload


def _envelope_error(document: str, detail: str) -> RuntimeError:
    return RuntimeError(f"Windows {document} envelope {detail}")


def _require_fields(
    document: str,
    payload: dict[str, object],
    fields: frozenset[str],
) -> None:
    if set(payload) != fields:
        missing = sorted(fields - set(payload))
        unknown = sorted(set(payload) - fields)
        raise _envelope_error(
            document,
            f"fields are missing or unknown: missing={missing} unknown={unknown}",
        )


def _require_int(document: str, payload: dict[str, object], field: str, value: int) -> None:
    actual = payload.get(field)
    if type(actual) is not int or actual != value:
        raise _envelope_error(document, f"{field} is unsupported")


def _require_string(document: str, payload: dict[str, object], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value or value != value.strip():
        raise _envelope_error(document, f"{field} is missing or invalid")
    return value


def _require_digest(document: str, payload: dict[str, object], field: str) -> str:
    value = _require_string(document, payload, field)
    if SHA256_PATTERN.fullmatch(value) is None:
        raise _envelope_error(document, f"{field} is not a lowercase SHA-256")
    return value


def _validate_delivery_envelope(payload: dict[str, object]) -> tuple[str, str, str]:
    _require_fields("runtime", payload, DELIVERY_FIELDS)
    if payload.get("schema") != "sulde-delivery-generation-v1":
        raise _envelope_error("runtime", "schema is unsupported")
    _require_int("runtime", payload, "schema_version", 1)
    if payload.get("provider") != WINDOWS_PROVIDER:
        raise _envelope_error("runtime", "provider is unsupported")
    if payload.get("platform") != WINDOWS_PLATFORM:
        raise _envelope_error("runtime", "platform is unsupported")
    version = _require_string("runtime", payload, "plugin_version")
    digest = _require_digest("runtime", payload, "runtime_tree_sha256")
    generation = _require_string("runtime", payload, "generation")
    if generation != f"{version}:{digest}":
        raise _envelope_error("runtime", "generation is truncated or inconsistent")
    return version, digest, generation


def _validate_deployment_envelope(payload: dict[str, object]) -> tuple[str, str, str]:
    _require_fields("deployment", payload, DEPLOYMENT_FIELDS)
    if payload.get("schema") != "sulde-installed-deployment-generation-v1":
        raise _envelope_error("deployment", "schema is unsupported")
    _require_int("deployment", payload, "schema_version", 1)
    if payload.get("provider") != WINDOWS_PROVIDER:
        raise _envelope_error("deployment", "provider is unsupported")
    if payload.get("platform") != WINDOWS_PLATFORM or payload.get("artifact_platform") != WINDOWS_PLATFORM:
        raise _envelope_error("deployment", "platform is unsupported")
    if payload.get("status") != "installed_degraded" or type(
        payload.get("operational_ready")
    ) is not bool or payload["operational_ready"] is not False:
        raise _envelope_error("deployment", "readiness status is invalid")
    version = _require_string("deployment", payload, "plugin_version")
    _require_digest("deployment", payload, "plugin_tree_sha256")
    digest = _require_digest("deployment", payload, "runtime_tree_sha256")
    generation = _require_string("deployment", payload, "generation")
    if generation != f"{version}:{digest}":
        raise _envelope_error("deployment", "generation is truncated or inconsistent")
    for field in ("artifact", "installed_plugin", "runtime_root", "scheduler_runner"):
        _require_string("deployment", payload, field)
    _require_digest("deployment", payload, "scheduler_runner_sha256")
    labels = payload.get("managed_labels")
    if (
        not isinstance(labels, list)
        or not all(isinstance(label, str) for label in labels)
        or set(labels) != DESIRED_TASK_NAMES
        or len(labels) != len(DESIRED_TASK_NAMES)
    ):
        raise _envelope_error("deployment", "task inventory is invalid")
    return version, digest, generation


def _validate_launcher_envelope(payload: dict[str, object]) -> tuple[str, str]:
    _require_fields("launcher", payload, LAUNCHER_FIELDS)
    if payload.get("schema") != "sulde-launcher-install-v1":
        raise _envelope_error("launcher", "schema is unsupported")
    _require_int("launcher", payload, "schema_version", 1)
    _require_int("launcher", payload, "spec_version", 8)
    if payload.get("provider") != WINDOWS_PROVIDER:
        raise _envelope_error("launcher", "provider is unsupported")
    if payload.get("platform") != WINDOWS_PLATFORM:
        raise _envelope_error("launcher", "platform is unsupported")
    for field in (
        "generated_at",
        "source_root",
        "interpreter",
        "interpreter_prefix",
        "scheduler_runner",
    ):
        _require_string("launcher", payload, field)
    for field in (
        "runtime_sha256",
        "runtime_tree_sha256",
        "interpreter_sha256",
        "codex_hook_surface_sha256",
        "command_effects_sha256",
        "scheduler_runner_sha256",
    ):
        _require_digest("launcher", payload, field)
    if not isinstance(payload.get("launchers"), dict):
        raise _envelope_error("launcher", "launcher inventory is invalid")
    return str(payload["runtime_tree_sha256"]), _require_string(
        "launcher", payload, "generation"
    )


def validate_windows_documents(
    runtime: dict[str, object],
    deployment: dict[str, object],
    launcher: dict[str, object],
    *,
    actual_runtime_tree_sha256: str | None = None,
) -> dict[str, str]:
    """Validate all Windows envelopes before comparing generation identities."""
    version, runtime_digest, runtime_generation = _validate_delivery_envelope(runtime)
    deployment_version, deployment_digest, deployment_generation = (
        _validate_deployment_envelope(deployment)
    )
    launcher_digest, launcher_generation = _validate_launcher_envelope(launcher)
    if (
        deployment_version != version
        or deployment_digest != runtime_digest
        or launcher_digest != runtime_digest
        or deployment_generation != runtime_generation
        or launcher_generation != runtime_generation
    ):
        raise _envelope_error("set", "generation or runtime digest identities differ")
    if deployment["runtime_root"] != launcher["source_root"]:
        raise _envelope_error("set", "runtime and launcher paths differ")
    if (
        deployment["scheduler_runner"] != launcher["scheduler_runner"]
        or deployment["scheduler_runner_sha256"]
        != launcher["scheduler_runner_sha256"]
    ):
        raise _envelope_error("set", "runner identity differs")
    if (
        actual_runtime_tree_sha256 is not None
        and actual_runtime_tree_sha256 != runtime_digest
    ):
        raise RuntimeError("Windows descriptor envelope does not match runtime bytes")
    return {
        "plugin_version": version,
        "runtime_tree_sha256": runtime_digest,
        "generation": runtime_generation,
        "runtime_root": str(deployment["runtime_root"]),
        "scheduler_runner": str(deployment["scheduler_runner"]),
        "scheduler_runner_sha256": str(deployment["scheduler_runner_sha256"]),
    }


def _validate_owner_envelope(
    owner: dict[str, object],
    *,
    runtime_root: str,
    runtime_tree_sha256: str,
    generation: str,
) -> tuple[str, str]:
    _require_fields("owner", owner, OWNER_FIELDS)
    _require_int("owner", owner, "schema_version", 2)
    if (
        owner.get("status") != "active"
        or owner.get("installation_status") != "installed_degraded"
        or type(owner.get("operational_ready")) is not bool
        or owner["operational_ready"] is not False
        or owner.get("provider") != WINDOWS_PROVIDER
        or owner.get("scheduler") != "windows-task-scheduler"
    ):
        raise _envelope_error("owner", "status, provider, or scheduler is unsupported")
    for field in ("executable", "source_root", "runtime_root", "generation", "installed_at"):
        _require_string("owner", owner, field)
    _require_digest("owner", owner, "runtime_tree_sha256")
    _require_digest("owner", owner, "scheduler_runner_sha256")
    runner_argument = Path(__file__)
    if runner_argument.is_symlink():
        raise RuntimeError("stable Windows task runner is a symbolic link")
    actual_runner_path = str(runner_argument.resolve())
    actual_runner_sha256 = sha256_file(Path(actual_runner_path))
    if (
        owner["source_root"] != runtime_root
        or owner["runtime_root"] != runtime_root
        or owner["runtime_tree_sha256"] != runtime_tree_sha256
        or owner["generation"] != generation
        or owner["scheduler_runner_sha256"] != actual_runner_sha256
    ):
        raise _envelope_error("owner", "generation or runner identity differs")
    managed = owner.get("managed_labels")
    retired = owner.get("retired_labels")
    if (
        not isinstance(managed, list)
        or not all(isinstance(label, str) for label in managed)
        or set(managed) != DESIRED_TASK_NAMES
        or len(managed) != len(DESIRED_TASK_NAMES)
        or not isinstance(retired, list)
        or not all(isinstance(label, str) for label in retired)
        or set(retired) != RETIRED_TASK_NAMES
        or len(retired) != len(RETIRED_TASK_NAMES)
    ):
        raise _envelope_error("owner", "task inventory is invalid")
    readback = owner.get("task_readback")
    if not isinstance(readback, list) or len(readback) != len(DESIRED_TASK_NAMES):
        raise _envelope_error("owner", "task action readback inventory is invalid")
    observed: set[str] = set()
    for row in readback:
        if not isinstance(row, dict) or set(row) != TASK_READBACK_FIELDS:
            raise _envelope_error("owner", "task action readback fields are invalid")
        task_name = row.get("task_name")
        if not isinstance(task_name, str) or task_name not in DESIRED_TASK_NAMES:
            raise _envelope_error("owner", "task action readback name is invalid")
        observed.add(task_name)
        execute = row.get("action_execute")
        arguments = row.get("action_arguments")
        expected_job = (
            "harvest" if task_name == "Sulde-Codex-Harvest" else "distill"
        )
        expected_arguments = (
            f'"{actual_runner_path}" --kb-home "{KB_HOME}" '
            f'--runtime-root "{runtime_root}" --generation "{generation}" '
            f'--runner-sha256 "{actual_runner_sha256}" '
            f'--provider "{owner["provider"]}" '
            f'--provider-executable "{owner["executable"]}" {expected_job}'
        )
        action_issues: list[str] = []
        if execute != sys.executable:
            action_issues.append("execute")
        if arguments != expected_arguments:
            action_issues.append("arguments")
        if row.get("runtime_root") != runtime_root:
            action_issues.append("runtime_readback")
        if row.get("generation") != generation:
            action_issues.append("generation_readback")
        if row.get("runner_sha256") != actual_runner_sha256:
            action_issues.append("runner_readback")
        if type(row.get("LastTaskResult")) is not int:
            action_issues.append("last_result")
        if action_issues:
            raise _envelope_error(
                "owner", "task action binding drifted: " + ",".join(action_issues)
            )
    if observed != DESIRED_TASK_NAMES:
        raise _envelope_error("owner", "task action inventory drifted")
    return actual_runner_path, actual_runner_sha256


def runtime_tree_digest(root: Path) -> str:
    argument = root.expanduser()
    if argument.is_symlink():
        raise RuntimeError(f"scheduler runtime root is a symbolic link: {argument}")
    runtime = argument.resolve()
    if not runtime.is_dir() or (runtime / ".git").exists():
        raise RuntimeError(f"scheduler runtime is mutable or missing: {runtime}")
    digest = hashlib.sha256()
    for path in sorted(runtime.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"scheduler runtime contains a symbolic link: {path}")
        relative_parts = path.relative_to(runtime).parts
        if ".git" in relative_parts:
            raise RuntimeError(f"scheduler runtime contains repository metadata: {path}")
        if "__pycache__" in relative_parts or path.suffix.casefold() == ".pyc":
            raise RuntimeError(
                f"scheduler runtime contains executable Python bytecode: {path}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(runtime).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def verify_staged_runtime(root: Path, expected_generation: str | None = None) -> dict[str, object]:
    runtime = root.expanduser()
    if runtime.is_symlink():
        raise RuntimeError(f"staged runtime root is a symbolic link: {runtime}")
    runtime = runtime.resolve()
    descriptor = read_json(runtime.parent / ".codex-plugin" / "generation.json")
    version, declared_digest, generation = _validate_delivery_envelope(descriptor)
    digest = runtime_tree_digest(runtime)
    if declared_digest != digest:
        raise RuntimeError("staged delivery generation does not match runtime bytes")
    if expected_generation is not None and generation != expected_generation:
        raise RuntimeError("staged delivery generation does not match installer request")
    return {
        "runtime_root": str(runtime),
        "schema": str(descriptor["schema"]),
        "schema_version": int(descriptor["schema_version"]),
        "provider": str(descriptor["provider"]),
        "platform": str(descriptor["platform"]),
        "plugin_version": version,
        "runtime_tree_sha256": digest,
        "generation": generation,
    }


def resolve_runtime(
    root: Path | None,
    expected_generation: str | None,
    expected_runner_sha256: str | None,
) -> Path:
    if root is None or expected_generation is None or expected_runner_sha256 is None:
        raise RuntimeError("scheduler runtime, generation, and runner digest must be explicit")
    argument = root.expanduser()
    if argument.is_symlink():
        raise RuntimeError(f"scheduler runtime root is a symbolic link: {argument}")
    runtime = argument.resolve()
    runtime_document = read_json(runtime.parent / ".codex-plugin" / "generation.json")
    owner = read_json(KB_HOME / "runtime-owner.json")
    deployment = read_json(KB_HOME / "deployment-generation.json")
    launcher = read_json(KB_HOME / "bin" / ".sulde-launchers.json")
    validated = validate_windows_documents(
        runtime_document,
        deployment,
        launcher,
    )
    digest = runtime_tree_digest(runtime)
    if validated["runtime_tree_sha256"] != digest:
        raise RuntimeError("Windows descriptor envelope does not match runtime bytes")
    if validated["runtime_root"] != str(runtime):
        raise RuntimeError("Windows descriptor envelope runtime path differs from request")
    if validated["generation"] != expected_generation:
        raise RuntimeError("Windows descriptor envelope generation differs from request")
    if validated["scheduler_runner_sha256"] != expected_runner_sha256:
        raise RuntimeError("Windows descriptor envelope runner differs from request")
    runner_argument = Path(__file__)
    if runner_argument.is_symlink():
        raise RuntimeError("stable Windows task runner is a symbolic link")
    process_runner_path = str(runner_argument.resolve())
    process_runner_sha256 = sha256_file(Path(process_runner_path))
    if process_runner_path != validated["scheduler_runner"]:
        raise RuntimeError("stable Windows task runner path drifted")
    if process_runner_sha256 != expected_runner_sha256:
        raise RuntimeError("stable Windows task runner digest drifted")
    actual_runner_path, actual_runner_sha256 = _validate_owner_envelope(
        owner,
        runtime_root=str(runtime),
        runtime_tree_sha256=digest,
        generation=expected_generation,
    )
    if actual_runner_path != process_runner_path:
        raise RuntimeError("stable Windows task runner path drifted")
    if actual_runner_sha256 != process_runner_sha256:
        raise RuntimeError("stable Windows task runner digest drifted")
    return runtime


def append_log(job: str, stream: str, content: str) -> None:
    if not content.strip():
        return
    timestamp = datetime.now(timezone.utc).isoformat()
    with (KB_HOME / f"{job}.{stream}.log").open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {content.rstrip()}\n")


def require_clean_memory(runtime: Path, environment: dict[str, str]) -> None:
    scanner = runtime / "scripts" / "kb" / "mem-secret-scan.py"
    completed = subprocess.run(
        [sys.executable, str(scanner), "--json"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=environment,
    )
    append_log("secret-scan", "stdout", completed.stdout)
    append_log("secret-scan", "stderr", completed.stderr)
    if completed.returncode == 0:
        return
    detail = completed.stdout.strip() or completed.stderr.strip()
    if completed.returncode == 1:
        raise RuntimeError(
            "secret scan blocked Daily Distill; review the masked report in "
            f"{KB_HOME / 'secret-scan.stdout.log'} and redact matched entries"
        )
    raise RuntimeError(
        f"secret scan failed with exit code {completed.returncode}: {detail[:500]}"
    )


def run_job(
    job: str,
    provider: str = "auto",
    provider_executable: Path | None = None,
    runtime_root: Path | None = None,
    generation: str | None = None,
    runner_sha256: str | None = None,
) -> int:
    runtime = resolve_runtime(runtime_root, generation, runner_sha256)
    if job == "harvest":
        script = runtime / "scripts" / "kb" / "codex-harvest.py"
        command = [sys.executable, str(script)]
    elif job == "embed":
        script = runtime / "tools" / "kb-index" / "memory.py"
        command = [
            sys.executable,
            str(script),
            "embed-pending",
            "--limit",
            "250",
        ]
    else:
        script = runtime / "scripts" / "kb" / "auto-distill.py"
        command = [sys.executable, str(script)]
    environment = {
        key: value for key, value in os.environ.items() if key in SAFE_ENVIRONMENT
    }
    environment["SULDE_KB_HOME"] = str(KB_HOME)
    environment["SULDE_HOST_PROVIDER"] = provider
    environment["SULDE_LLM_PROVIDER"] = provider
    environment["SULDE_AGENT_PROVIDER"] = provider
    environment["SULDE_RUNTIME_ROOT"] = str(runtime)
    environment["SULDE_RUNTIME_GENERATION"] = str(generation)
    environment["SULDE_SCHEDULER_OWNER"] = str(KB_HOME / "runtime-owner.json")
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    if job == "distill":
        environment["SULDE_LLM_PROVIDER"] = provider
        environment["SULDE_HOST_PROVIDER"] = provider
        if provider_executable is not None and provider in {"claude", "codex"}:
            variable = "SULDE_CLAUDE_EXE" if provider == "claude" else "SULDE_CODEX_EXE"
            environment[variable] = str(provider_executable)
        require_clean_memory(runtime, environment)
    completed = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=environment,
    )
    append_log(job, "stdout", completed.stdout)
    append_log(job, "stderr", completed.stderr)
    if completed.stdout and sys.stdout is not None:
        print(completed.stdout, end="")
    if completed.stderr and sys.stderr is not None:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.returncode


def main() -> int:
    global KB_HOME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-home", type=Path)
    parser.add_argument("--provider", choices=("auto", "claude", "codex"), default="auto")
    parser.add_argument("--provider-executable", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--generation")
    parser.add_argument("--runner-sha256")
    parser.add_argument("job", choices=("harvest", "embed", "distill", "verify-staged"))
    args = parser.parse_args()
    if args.kb_home is not None:
        KB_HOME = args.kb_home.expanduser().resolve()
    KB_HOME.mkdir(parents=True, exist_ok=True)
    if args.job == "verify-staged":
        if args.runtime_root is None:
            raise RuntimeError("verify-staged requires --runtime-root")
        print(json.dumps(verify_staged_runtime(args.runtime_root, args.generation), sort_keys=True))
        return 0
    return run_job(
        args.job,
        args.provider,
        args.provider_executable,
        args.runtime_root,
        args.generation,
        args.runner_sha256,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        KB_HOME.mkdir(parents=True, exist_ok=True)
        append_log("windows-task", "stderr", f"{type(error).__name__}: {error}")
        if sys.stderr is not None:
            print(f"sulde-windows-task: {error}", file=sys.stderr)
        raise SystemExit(2)

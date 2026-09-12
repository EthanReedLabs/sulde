#!/usr/bin/env python3
"""Prepare, verify, promote, inspect, or discard one isolated Codex candidate."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
from typing import Any, Iterator
import uuid


sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))
sys.path.insert(0, str(ROOT / "hooks" / "lib"))
import install_codex_plugin as installer  # noqa: E402
from kb_cli import resolve_venv_python  # noqa: E402
from python_environment import (PythonEnvironmentError, inspect_python, invoking_environment,
                                same_runtime, validate_python)  # noqa: E402


STATE_SCHEMA = "sulde-codex-candidate-state-v1"
RECEIPT_SCHEMA = installer.CANDIDATE_RECEIPT_SCHEMA
_CANDIDATE_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z._-]{0,80}")
_FAULTS = {
    "hook_invalid_json",
    "decision_null",
    "generation_mismatch",
    "mcp_missing",
    "scheduler_failure",
}


class CandidateError(RuntimeError):
    """Candidate state, isolation, verification, or promotion failed."""


def _canonical(value: object) -> bytes:
    """Use the installer's canonical byte authority for cross-module seals."""

    return installer._canonical_json_bytes(value)


def _legacy_digest(value: object) -> str:
    """Read pre-unification state seals without accepting legacy receipts."""

    canonical = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_candidate_home() -> Path:
    configured = os.environ.get("SULDE_CANDIDATE_HOME")
    if configured:
        return Path(configured).expanduser()
    sulde_home = Path(os.environ.get("SULDE_HOME") or Path.home() / ".sulde")
    return sulde_home.expanduser() / "candidates" / "codex"


def _safe_root(root: Path, *, create: bool) -> Path:
    selected = root.expanduser().absolute()
    if selected.is_symlink():
        raise CandidateError(f"candidate home must not be a symlink: {selected}")
    if create:
        selected.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            selected.chmod(0o700)
    if not selected.is_dir():
        raise CandidateError(f"candidate home is unavailable: {selected}")
    return selected.resolve()


def _slot(root: Path, candidate_id: str, *, create_root: bool = False) -> Path:
    if not _CANDIDATE_ID.fullmatch(candidate_id) or candidate_id in {".", ".."}:
        raise CandidateError(f"unsafe candidate id: {candidate_id!r}")
    selected_root = _safe_root(root, create=create_root)
    selected = selected_root / candidate_id
    if selected.is_symlink():
        raise CandidateError(f"candidate slot must not be a symlink: {selected}")
    if selected.resolve(strict=False).parent != selected_root:
        raise CandidateError("candidate slot escapes the candidate home")
    return selected


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    content = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _sealed(payload: dict[str, Any], field: str) -> dict[str, Any]:
    unsigned = dict(payload)
    unsigned.pop(field, None)
    unsigned[field] = _digest(unsigned)
    return unsigned


def _load_sealed(path: Path, *, schema: str, field: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise CandidateError(f"candidate authority is not a regular file: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CandidateError(f"candidate authority is unreadable: {path}: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise CandidateError(f"candidate authority schema differs: {path}")
    supplied = payload.get(field)
    unsigned = dict(payload)
    unsigned.pop(field, None)
    digest_matches = supplied == _digest(unsigned)
    if field == "state_sha256" and not digest_matches:
        digest_matches = supplied == _legacy_digest(unsigned)
    if not digest_matches:
        raise CandidateError(f"candidate authority digest differs: {path}")
    return payload


def _state_path(slot: Path) -> Path:
    return slot / "state.json"


def _receipt_path(slot: Path) -> Path:
    return slot / "verification-receipt.json"


def _write_state(slot: Path, state: dict[str, Any]) -> dict[str, Any]:
    sealed = _sealed(state, "state_sha256")
    _atomic_json(_state_path(slot), sealed)
    return sealed


def _load_state(slot: Path) -> dict[str, Any]:
    return _load_sealed(_state_path(slot), schema=STATE_SCHEMA, field="state_sha256")


def _source_identity() -> dict[str, Any]:
    commit = installer.run_command(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, timeout=15
    ).stdout.strip()
    tree = installer.run_command(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, timeout=15
    ).stdout.strip()
    dirty = installer.run_command(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        timeout=30,
    ).stdout
    if dirty.strip():
        raise CandidateError(
            "candidate source must be committed and clean before preparation"
        )
    return {
        "commit": commit,
        "tree": tree,
        "plugin_version": installer.plugin_version(),
    }


def _python_identity(interpreter: Path) -> dict[str, Any]:
    try:
        return inspect_python(interpreter)
    except PythonEnvironmentError as error:
        raise CandidateError(str(error)) from error


def _candidate_python() -> dict[str, Any]:
    try:
        return invoking_environment()
    except PythonEnvironmentError as error:
        raise CandidateError(str(error)) from error


def _candidate_environment(
    slot: Path,
    codex: str,
    python_identity: dict[str, str],
) -> dict[str, str]:
    sulde_home = slot / "isolated" / "sulde-home"
    kb_home = sulde_home / "data" / "kb"
    codex_home = slot / "isolated" / "codex-home"
    workspace = slot / "isolated" / "workspace"
    launchagents = slot / "isolated" / "launchagents"
    for path in (sulde_home, kb_home, codex_home, workspace, launchagents):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    isolated_python = _install_isolated_python(
        kb_home, Path(python_identity["executable"])
    )
    try:
        if not same_runtime(python_identity, inspect_python(isolated_python)):
            raise CandidateError("candidate isolated Python dependencies differ from preflight")
    except PythonEnvironmentError as error:
        raise CandidateError(str(error)) from error
    # Own the boundary here, not in the caller's test harness. In particular,
    # a fresh candidate must never fall back to a parent's absolute contract.
    environment = {key: value for key, value in os.environ.items() if key in {
        "PATH", "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "SystemRoot",
        "WINDIR", "COMSPEC", "PATHEXT",
    }}
    environment.setdefault("PATH", os.defpath)
    roots = {
        "HOME": slot / "isolated/home", "USERPROFILE": slot / "isolated/home",
        "XDG_CONFIG_HOME": slot / "isolated/xdg-config",
        "XDG_CACHE_HOME": slot / "isolated/xdg-cache",
        "XDG_DATA_HOME": slot / "isolated/xdg-data",
        "APPDATA": slot / "isolated/appdata", "LOCALAPPDATA": slot / "isolated/local-appdata",
        "TMPDIR": slot / "isolated/tmp", "TMP": slot / "isolated/tmp", "TEMP": slot / "isolated/tmp",
    }
    for key, path in roots.items():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        environment[key] = str(path)
    environment.update(
        {
            "CODEX_HOME": str(codex_home),
            "SULDE_HOME": str(sulde_home),
            "SULDE_KB_HOME": str(kb_home),
            "SULDE_LAUNCHER_HOME": str(sulde_home),
            "SULDE_LAUNCHAGENTS_DIR": str(launchagents),
            "SULDE_HOST_PROVIDER": "codex",
            "SULDE_CODEX_EXE": codex,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
        }
    )
    return environment


def _install_isolated_python(kb_home: Path, interpreter: Path) -> Path:
    """Copy the audited interpreter so ``sys.executable`` stays candidate-local."""

    venv_home = kb_home / "venv"
    result = installer.run_command(
        [
            str(interpreter),
            "-B",
            "-m",
            "venv",
            "--copies",
            "--system-site-packages",
            str(venv_home),
        ],
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        raise CandidateError(
            "candidate Python environment could not be created: "
            + (result.stderr or result.stdout).strip()[-500:]
        )
    target = resolve_venv_python(kb_home, require_executable=True)
    if target is None or target.is_symlink():
        raise CandidateError("candidate Python resolver returned no regular executable")
    if target.read_bytes() != interpreter.read_bytes():
        shutil.copy2(interpreter, target)
    if os.name != "nt":
        target.chmod(0o700)
    return target


@contextmanager
def _process_environment(environment: dict[str, str]) -> Iterator[None]:
    previous = os.environ.copy()
    os.environ.clear()
    os.environ.update(environment)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def _bound_runner(environment: dict[str, str]) -> installer.Runner:
    def run(command, **kwargs):
        supplied = kwargs.pop("environment", None)
        merged = dict(environment)
        if supplied is not None:
            merged.update(supplied)
        for key in (
            "CODEX_HOME",
            "SULDE_HOME",
            "SULDE_LAUNCHAGENTS_DIR",
        ):
            merged[key] = environment[key]
        merged.setdefault("SULDE_KB_HOME", environment["SULDE_KB_HOME"])
        merged.setdefault("SULDE_LAUNCHER_HOME", environment["SULDE_LAUNCHER_HOME"])
        merged["PYTHONDONTWRITEBYTECODE"] = "1"
        return installer.run_command(command, environment=merged, **kwargs)

    return run


def prepare(
    *,
    candidate_home: Path,
    codex: str,
    platform: str,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    # Cheap identity rejection precedes Python setup, source scans and all
    # candidate writes. Full help/profile/handshake proof remains mandatory.
    codex_identity = installer._codex_command_identity(codex)
    try:
        version = installer._codex_version_preflight(Path(codex), installer.run_command)
    except installer.InstallError as error:
        raise CandidateError(str(error)) from error
    if installer._codex_command_identity(codex) != codex_identity:
        raise CandidateError("Codex executable changed during candidate preflight")
    python_identity = _candidate_python()
    source = _source_identity()
    identifier = candidate_id or (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:12]
    )
    slot = _slot(candidate_home, identifier, create_root=True)
    if slot.exists():
        raise CandidateError(f"candidate already exists: {identifier}")
    slot.mkdir(mode=0o700)
    artifact = slot / "artifact"
    state: dict[str, Any] = {
        "schema": STATE_SCHEMA,
        "schema_version": 1,
        "candidate_id": identifier,
        "status": "preparing",
        "created_at": _now(),
        "updated_at": _now(),
        "source": source,
        "platform": platform,
        "codex": {
            "executable": codex_identity["codex_command"],
            "executable_sha256": codex_identity["codex_command_sha256"],
            "version": version,
        },
        "python": python_identity,
        "artifact": {"path": str(artifact.resolve())},
        "receipt_sha256": None,
        "promotion_consumed": False,
    }
    _write_state(slot, state)
    try:
        prepared = installer._stage_artifact(
            artifact,
            platform=platform,
            runner=installer.run_command,
        )
        generation = prepared.descriptor["delivery_generation"]
        validate_python(python_identity)
        state.update({
            "status": "prepared",
            "updated_at": _now(),
            "artifact": {
                "path": str(prepared.marketplace.resolve()),
                "plugin_tree_sha256": prepared.plugin_tree_sha256,
                "runtime_tree_sha256": generation["runtime_tree_sha256"],
                "generation": generation["generation"],
                "plugin_version": generation["plugin_version"],
                "platform": generation["platform"],
            },
            "prepare_live_observation": installer.deployment_cas_snapshot(
                installer.default_kb_home(), codex
            ),
            "timings_ms": {
                "prepare_total": round((time.monotonic() - started) * 1000, 3),
            },
        })
        return _write_state(slot, state)
    except Exception as error:
        state.update(
            {
                "status": "prepare_failed",
                "updated_at": _now(),
                "prepare_error": str(error),
            }
        )
        _write_state(slot, state)
        raise


def _parse_json_result(result: installer.CommandResult, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise CandidateError(f"{label} did not return JSON") from error
    if not isinstance(payload, dict):
        raise CandidateError(f"{label} did not return a JSON object")
    return payload


def _guardian_audit_event(row: dict[str, Any]) -> dict[str, Any]:
    event = row.get("event")
    return event if isinstance(event, dict) else row


def _activate_candidate_enforce_contract(
    guardian: Path,
    *,
    kb_home: Path,
    workspace: Path,
    session: str,
    environment: dict[str, str],
    runner: installer.Runner,
) -> tuple[Path, dict[str, Any]]:
    """Activate one bounded enforce contract through fresh candidate CLI processes."""

    control_environment = dict(environment)
    control_environment["CODEX_THREAD_ID"] = session
    prepared = _parse_json_result(
        runner(
            [
                sys.executable,
                str(guardian),
                "prepare-proposal",
                "--objective",
                "verify candidate real pre-execution denial",
                "--accept",
                "out-of-scope marker is denied before execution",
                "--rationale",
                "isolated deterministic candidate verification",
                "--reject",
                "no production write",
                "--allow-path",
                "allowed.txt",
                "--workspace",
                str(workspace),
                "--home",
                str(kb_home),
                "--mode",
                "enforce",
                "--decision-route",
                "agent",
                "--intent-kind",
                "deterministic",
                "--risk",
                "low",
                "--effect",
                "local_write",
                "--reversibility",
                "reversible",
                "--cost",
                "none",
                "--rollback",
                "discard isolated candidate workspace",
                "--provider",
                "codex",
                "--session-id",
                session,
            ],
            environment=control_environment,
            timeout=30,
        ),
        label="candidate enforce proposal",
    )
    if prepared.get("decision_route") != "agent":
        raise CandidateError("candidate enforce proposal did not use Agent policy")
    contract_path = Path(str(prepared.get("contract_path") or ""))
    proposal_path = Path(str(prepared.get("proposal_path") or ""))
    digest = str(prepared.get("proposal_digest") or "")
    decided = _parse_json_result(
        runner(
            [
                sys.executable,
                str(guardian),
                "agent-decide-proposal",
                digest,
                "--rationale",
                "bounded isolated local-write canary is deterministic and reversible",
                "--evidence",
                "candidate workspace and knowledge root are isolated from production",
                "--evidence",
                "the negative marker must remain absent",
                "--provider",
                "codex",
                "--session-id",
                session,
                "--contract",
                str(contract_path),
                "--workspace",
                str(workspace),
                "--home",
                str(kb_home),
            ],
            environment=control_environment,
            timeout=30,
        ),
        label="candidate Agent-policy decision",
    )
    if decided.get("decision", {}).get("authority") != "agent-policy":
        raise CandidateError("candidate enforce proposal lacks Agent authority")
    applied_result = runner(
        [
            sys.executable,
            str(guardian),
            "apply-proposal",
            str(proposal_path),
            "--contract",
            str(contract_path),
            "--workspace",
            str(workspace),
            "--home",
            str(kb_home),
        ],
        environment=control_environment,
        timeout=30,
    )
    if "INTENT PROPOSAL: APPLIED" not in applied_result.stdout:
        raise CandidateError("candidate enforce proposal was not applied")
    contract = _parse_json_result(
        runner(
            [
                sys.executable,
                str(guardian),
                "show",
                "--contract",
                str(contract_path),
                "--workspace",
                str(workspace),
                "--home",
                str(kb_home),
            ],
            environment=control_environment,
            timeout=30,
        ),
        label="candidate enforce contract",
    )
    if (
        contract.get("mode") != "enforce"
        or contract.get("status") != "active"
        or contract.get("applied_decision_authority") != "agent-policy"
    ):
        raise CandidateError("candidate contract did not become enforce-active")
    return contract_path, {
        "status": "ready",
        "mode": "enforce",
        "revision": contract.get("revision"),
        "decision_authority": "agent-policy",
        "proposal_digest": digest,
    }


def _verify_real_preexecution_chain(
    installed: Path,
    *,
    kb_home: Path,
    environment: dict[str, str],
    runner: installer.Runner,
    expected_artifact_generation: str,
    externally_isolated: bool = False,
) -> dict[str, Any]:
    """Real native session -> unified exec -> candidate Hook -> independent proof."""
    from native_pretool_canary import NativeCanary, NativeCanaryError
    workspace = Path(environment["SULDE_HOME"]) / ("preexecution-" + uuid.uuid4().hex)
    workspace.mkdir(parents=True, exist_ok=False)
    guardian = Path(environment["SULDE_HOME"]) / "bin/intent-guardian"
    # The native host chooses session identity before any proposal or probe is made.
    host = NativeCanary(environment["SULDE_CODEX_EXE"], workspace, environment,
                        externally_isolated=externally_isolated)
    try:
        with host.start():
            session = host.session
            contract_path, activation = _activate_candidate_enforce_contract(
                guardian, kb_home=kb_home, workspace=workspace, session=session,
                environment=environment, runner=runner)
            control = {**environment, "CODEX_THREAD_ID": session}
            def control_call(action, *arguments):
                return _parse_json_result(runner(
                    [sys.executable, str(guardian), action, *arguments, "--provider", "codex",
                     "--session-id", session, "--contract", str(contract_path)],
                    environment=control, timeout=30), label=action)
            prepared = control_call("pre-execution-proof-prepare")
            if prepared.get("artifact_generation") != expected_artifact_generation:
                raise CandidateError("candidate probe loaded another artifact")
            import shlex
            allowed, outside_plan = workspace / "allowed.txt", workspace / "outside-plan.txt"
            commands = ["touch " + shlex.quote(str(allowed)), "touch " + shlex.quote(str(outside_plan)),
                        prepared["command"]]
            items = host.execute(commands)
            # Task paths are planning data, not ordinary-write authority. The
            # destructive v2 probe is the actual retained denial boundary.
            if not allowed.is_file() or not outside_plan.is_file():
                diagnostic = {"allowed_exists": allowed.is_file(), "outside_plan_exists": outside_plan.is_file(),
                    "items": [{key: item.get(key) for key in ("id", "exitCode", "status", "aggregatedOutput")}
                              for item in items],
                    "hooks": [{key: row.get("params", {}).get("run", {}).get(key)
                               for key in ("id", "eventName", "status")}
                              for row in host.notifications if row.get("method") == "hook/completed"]}
                # Only candidate-local fixture results; never a business prompt.
                raise CandidateError("native local-write canary failed: " + json.dumps(diagnostic)[-12000:])
            if sum(item.get("exitCode") == 0 for item in items) != 2:
                raise CandidateError("native host did not report a successful positive execution")
            native_denials = [row["params"]["run"] for row in host.notifications
                if row.get("method") == "hook/completed"
                and row.get("params", {}).get("run", {}).get("eventName") == "preToolUse"
                and row["params"]["run"].get("status") == "blocked"
                and row["params"]["run"].get("id", "").endswith(":candidate_native_2")]
            if len(native_denials) != 1:
                raise CandidateError("native host did not report one exact pre-execution denial")
            proof = control_call("pre-execution-proof-finalize", "--probe-id", prepared["probe_id"])
    except NativeCanaryError as error:
        raise CandidateError(str(error)) from error
    if (
        proof.get("schema") != "sulde-pre-execution-proof-v2"
        or proof.get("started_call_id") != "candidate_native_2"
        or proof.get("loaded_module_generation") != prepared.get("loaded_module_generation")
        or proof.get("artifact_generation") != expected_artifact_generation
        or os.path.lexists(str(prepared["target"]))
    ):
        raise CandidateError("native PreToolUse proof identity differs")
    audit = contract_path.with_name(f"{contract_path.stem}.events.jsonl")
    events = [_guardian_audit_event(json.loads(line))
              for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [event for event in events if event.get("event_id") == proof.get("started_event_id")]
    scope_events = [event for event in events if event.get("call_id") == "candidate_native_2"
                    and event.get("phase") == "started" and event.get("target") == prepared["target"]]
    if len(selected) != 1 or len(scope_events) != 1:
        raise CandidateError("native denial audit missing or ambiguous")
    for event in selected + scope_events:
        if (event.get("loaded_module_generation") != proof["loaded_module_generation"]
            or event.get("artifact_generation") != expected_artifact_generation
            or event.get("provider") != "codex" or event.get("session_id") != session
            or event.get("supervision_status") != "live_verified"):
            raise CandidateError("native denial event lacks live dual-generation identity")
    return {
        "status": "ready", "transport": "codex-cli-app-server",
        "native_tool": "exec_command", "executor": "unified_exec",
        "hook": "PreToolUse", "permission_decision": "deny",
        "contract_activation": activation, "session_id": session,
        "probe_id": proof["probe_id"], "proof_id": proof["proof_id"],
        "started_event_id": proof["started_event_id"],
        "started_call_id": proof["started_call_id"],
        "native_denial_run_id": native_denials[0]["id"],
        "scope_denial_event_id": scope_events[0]["event_id"],
        "loaded_module_generation": proof["loaded_module_generation"],
        "artifact_generation": proof["artifact_generation"],
        "positive_executed": True, "outside_plan_write_executed": True,
        "destructive_pre_denied": True, "marker_absent": True,
        "external_model_requests": 0,
    }


def _write_fake_launchctl(path: Path, *, fail: bool) -> None:
    exit_code = 91 if fail else 0
    source = (
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = list ]; then exit " + str(exit_code) + "; fi\n"
        "exit " + str(exit_code) + "\n"
    )
    path.write_text(source, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o700)


def _fault_injected_installed_tree(
    installed: Path,
    fault: str | None,
) -> None:
    if fault == "hook_invalid_json":
        hook = installed / "scripts" / "pre-tool-use.py"
        hook.write_text("#!/usr/bin/env python3\nprint('not-json')\n", encoding="utf-8")
        hook.chmod(0o755)
    elif fault == "decision_null":
        hook = installed / "scripts" / "pre-tool-use.py"
        hook.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "print(json.dumps({'hookSpecificOutput': None}))\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
    elif fault == "generation_mismatch":
        generation = installed / ".codex-plugin" / installer.DELIVERY_GENERATION_NAME
        payload = json.loads(generation.read_text(encoding="utf-8"))
        payload["generation"] = "injected-mismatch"
        generation.write_text(json.dumps(payload), encoding="utf-8")
    elif fault == "mcp_missing":
        (installed / "runtime" / "tools" / "kb-mcp" / "server.py").unlink()


def verify(
    *,
    candidate_home: Path,
    candidate_id: str,
    codex: str | None = None,
    fault: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    if fault is not None and fault not in _FAULTS:
        raise CandidateError(f"unknown candidate failpoint: {fault}")
    slot = _slot(candidate_home, candidate_id)
    state = _load_state(slot)
    if state.get("status") != "prepared":
        raise CandidateError("only a prepared candidate can be verified")
    selected_codex = codex or str(state["codex"]["executable"])
    if state["codex"].get("version") != installer.AUDITED_CODEX_VERSION:
        raise CandidateError("candidate was prepared for another audited Codex version")
    identity = installer._codex_command_identity(selected_codex)
    if (identity["codex_command"] != state["codex"]["executable"]
            or identity["codex_command_sha256"] != state["codex"]["executable_sha256"]):
        raise CandidateError("Codex executable changed after candidate preparation")
    try:
        installer._codex_version_preflight(Path(selected_codex), installer.run_command)
    except installer.InstallError as error:
        raise CandidateError(str(error)) from error
    before = installer.deployment_cas_snapshot(
        installer.default_kb_home(), selected_codex
    )
    python_identity = state.get("python")
    if not isinstance(python_identity, dict):
        raise CandidateError("candidate Python identity is missing")
    try:
        validate_python(python_identity)
        if _candidate_python() != python_identity:
            raise CandidateError("candidate Python identity changed after preparation")
    except PythonEnvironmentError as error:
        raise CandidateError(str(error)) from error
    # The official outer test runner has already proved the OS production-write
    # denial. Avoid nesting macOS sandbox-exec; never propagate its parent env.
    externally_isolated = bool(os.environ.get("SULDE_ISOLATED_TEST_RUN_ID"))
    environment = _candidate_environment(slot, selected_codex, python_identity)
    runner = _bound_runner(environment)
    artifact = Path(str(state["artifact"]["path"]))
    verification: dict[str, Any] = {}
    try:
        descriptor = installer.validate_staged_marketplace(
            artifact, expected_version=state["artifact"]["plugin_version"]
        )
        artifact_digest = installer.tree_digest(artifact / "plugins" / "sulde")
        if artifact_digest != state["artifact"]["plugin_tree_sha256"]:
            raise CandidateError("candidate artifact changed after preparation")
        verification["artifact"] = {"status": "ready"}

        with _process_environment(environment):
            installed = installer._registry_add(
                selected_codex,
                artifact,
                runner,
                expected_version=state["artifact"]["plugin_version"],
            )
            installed_descriptor = installer.validate_plugin_root(
                installed, expected_version=state["artifact"]["plugin_version"]
            )
            installed_digest = installer.tree_digest(installed)
            if installed_digest != artifact_digest:
                raise CandidateError("isolated Codex cache differs from candidate artifact")
            verification["isolated_registry"] = {
                "status": "ready",
                "codex_home": environment["CODEX_HOME"],
                "installed_path": str(installed),
            }

            _fault_injected_installed_tree(installed, fault)
            if fault in {
                "hook_invalid_json",
                "decision_null",
                "generation_mismatch",
                "mcp_missing",
            }:
                # Revalidate first so byte/generation/MCP corruption is rejected at
                # its earliest production boundary, before any live promotion.
                installer.validate_plugin_root(
                    installed, expected_version=state["artifact"]["plugin_version"]
                )
                if installer.tree_digest(installed) != artifact_digest:
                    raise CandidateError(f"injected {fault} was rejected")

            kb_home = Path(environment["SULDE_KB_HOME"])
            launcher = installer._install_launchers(
                installed,
                kb_home,
                runner,
                platform=state["platform"],
            )
            smoke = installer._smoke_installed(
                installed,
                kb_home,
                codex=selected_codex,
                expected_tree_sha256=artifact_digest,
                runner=runner,
                installed_descriptor=installed_descriptor,
                installed_tree_sha256=installed_digest,
            )
            verification["hooks"] = {
                "status": "ready",
                "real_entrypoints": True,
                "host_discovery": smoke["hook_trust"],
            }
            verification["preexecution_chain"] = _verify_real_preexecution_chain(
                installed,
                kb_home=kb_home,
                environment=environment,
                runner=runner,
                externally_isolated=externally_isolated,
                expected_artifact_generation=str(state["artifact"]["generation"]),
            )
            verification["mcp"] = {
                "status": "ready",
                "initialize": smoke["mcp_initialize"],
            }

            workspace = Path(environment["SULDE_HOME"]) / "doctor-workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            doctor = runner(
                [
                    sys.executable,
                    str(Path(environment["SULDE_HOME"]) / "bin/intent-guardian"),
                    "doctor",
                    "--workspace",
                    str(workspace),
                    "--provider",
                    "codex",
                ],
                check=False,
                timeout=60,
            )
            doctor_payload = _parse_json_result(doctor, label="candidate doctor")
            verification["doctor"] = {
                "status": "ready",
                "exit_code": doctor.returncode,
                "projection": doctor_payload,
            }

            fake_launchctl = slot / "isolated" / "launchctl"
            _write_fake_launchctl(
                fake_launchctl, fail=fault == "scheduler_failure"
            )
            scheduler_environment = dict(environment)
            scheduler_environment.update(
                {
                    "SULDE_LAUNCHCTL": str(fake_launchctl),
                    "SULDE_SCHEDULER_PYTHON": sys.executable,
                    "SULDE_PLATFORM_NAME": "Darwin",
                    "SULDE_PLUGIN_ROOT": str(installed / "runtime"),
                }
            )
            scheduler = runner(
                [
                    "bash",
                    str(installed / "runtime/scripts/kb/install-agents.sh"),
                    "--dry-run",
                    "--provider",
                    "codex",
                    "--runtime-root",
                    str(installed / "runtime"),
                ],
                environment=scheduler_environment,
                check=False,
                timeout=120,
            )
            if scheduler.returncode != 0:
                raise CandidateError(
                    "candidate scheduler entrypoint failed: "
                    + (scheduler.stderr or scheduler.stdout).strip()[-500:]
                )
            labels = installer._desired_scheduler_labels(installed / "runtime")
            if any(label not in scheduler.stdout for label in labels):
                raise CandidateError("candidate scheduler dry-run omitted managed labels")
            verification["scheduler_entrypoint"] = {
                "status": "ready",
                "mode": "production-entrypoint-isolated-dry-run",
                "managed_labels": list(labels),
            }

        verification["native_permission_ui"] = {
            "status": "unobserved",
            "exit_code": 78,
            "reason": "isolated CLI has no attachable current-session PermissionRequest surface",
        }
        verification["scheduler_host"] = {
            "status": "unobserved",
            "exit_code": 79,
            "reason": "candidate must not load production launchd labels before promotion",
        }
        after = installer.deployment_cas_snapshot(
            installer.default_kb_home(), selected_codex
        )
        if after != before:
            raise CandidateError("live generation changed during candidate verification")

        help_contract = installer._codex_cli_installed_smoke(
            Path(selected_codex), installer.run_command
        )
        validate_python(python_identity)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "schema_version": 1,
            "status": "verified",
            "candidate_id": candidate_id,
            "verified_at": _now(),
            "source": state["source"],
            "artifact": state["artifact"],
            "codex": {
                **state["codex"],
                "help_observation_sha256": help_contract[
                    "help_observation_sha256"
                ],
            },
            "python": python_identity,
            "live_prestate": before,
            "live_prestate_sha256": _digest(before),
            "verifications": verification,
            "timings_ms": {
                **(
                    state.get("timings_ms")
                    if isinstance(state.get("timings_ms"), dict)
                    else {}
                ),
                "verify_total": round((time.monotonic() - started) * 1000, 3),
            },
        }
        receipt = _sealed(receipt, "receipt_sha256")
        _atomic_json(_receipt_path(slot), receipt)
        state.update(
            {
                "status": "verified",
                "updated_at": _now(),
                "receipt_sha256": receipt["receipt_sha256"],
                "verification_summary": verification,
                "timings_ms": receipt["timings_ms"],
            }
        )
        _write_state(slot, state)
        return receipt
    except Exception as error:
        after = installer.deployment_cas_snapshot(
            installer.default_kb_home(), selected_codex
        )
        state.update(
            {
                "status": "verification_failed",
                "updated_at": _now(),
                "verification_error": str(error),
                "fault_injection": fault,
                "live_prestate": before,
                "live_poststate": after,
                "live_preserved": after == before,
            }
        )
        _write_state(slot, state)
        if after != before:
            raise CandidateError(
                f"candidate verification failed and live state drifted: {error}"
            ) from error
        raise CandidateError(
            f"candidate verification failed before promotion; live state preserved: {error}"
        ) from error


def promote(
    *,
    candidate_home: Path,
    candidate_id: str,
    kb_home: Path,
    codex: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    slot = _slot(candidate_home, candidate_id)
    state = _load_state(slot)
    if state.get("status") != "verified" or state.get("promotion_consumed") is True:
        raise CandidateError("candidate receipt is not available for one-time promotion")
    receipt = _load_sealed(
        _receipt_path(slot), schema=RECEIPT_SCHEMA, field="receipt_sha256"
    )
    if receipt.get("receipt_sha256") != state.get("receipt_sha256"):
        raise CandidateError("candidate state and receipt differ")
    selected_codex = codex or str(state["codex"]["executable"])
    artifact = Path(str(state["artifact"]["path"]))
    descriptor = installer.validate_staged_marketplace(
        artifact, expected_version=state["artifact"]["plugin_version"]
    )
    prepared = installer.PreparedArtifact(
        artifact.resolve(),
        descriptor,
        installer.tree_digest(artifact / "plugins" / "sulde"),
    )
    state.update(
        {
            "status": "promoting",
            "updated_at": _now(),
            "promotion_consumed": True,
        }
    )
    _write_state(slot, state)
    try:
        result = installer.install(
            artifact=artifact,
            kb_home=kb_home,
            codex=selected_codex,
            platform=state["platform"],
            prepared_artifact=prepared,
            candidate_receipt=receipt,
            expected_live_state=receipt["live_prestate"],
        )
    except Exception as error:
        state.update(
            {
                "status": "promotion_failed",
                "updated_at": _now(),
                "promotion_error": str(error),
            }
        )
        _write_state(slot, state)
        raise CandidateError(f"candidate promotion failed: {error}") from error
    state.update(
        {
            "status": "promoted",
            "updated_at": _now(),
            "promotion_result": result,
            "timings_ms": {
                **(
                    state.get("timings_ms")
                    if isinstance(state.get("timings_ms"), dict)
                    else {}
                ),
                "promote_total": round((time.monotonic() - started) * 1000, 3),
            },
        }
    )
    _write_state(slot, state)
    return result


def show(*, candidate_home: Path, candidate_id: str) -> dict[str, Any]:
    return _load_state(_slot(candidate_home, candidate_id))


def discard(*, candidate_home: Path, candidate_id: str) -> dict[str, Any]:
    slot = _slot(candidate_home, candidate_id)
    state_path = _state_path(slot)
    if state_path.is_file():
        state = _load_state(slot)
        if state.get("status") in {"promoting"}:
            raise CandidateError("an in-progress promotion cannot be discarded")
    else:
        allowed_orphan_entries = {"artifact", "isolated"}
        try:
            entries = set(path.name for path in slot.iterdir())
        except OSError as error:
            raise CandidateError(f"candidate orphan cannot be inspected: {slot}") from error
        if not entries.issubset(allowed_orphan_entries) or any(
            path.is_symlink() for path in slot.rglob("*")
        ):
            raise CandidateError("unsealed candidate orphan contains ambiguous content")
    root = _safe_root(candidate_home, create=False)
    if slot.parent.resolve() != root or not slot.is_dir() or slot.is_symlink():
        raise CandidateError("candidate discard target is ambiguous")
    shutil.rmtree(slot)
    return {"status": "discarded", "candidate_id": candidate_id}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-home", type=Path, default=default_candidate_home())
    parser.add_argument("--codex")
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--candidate-id")
    prepare_parser.add_argument(
        "--platform",
        choices=("posix", "windows"),
        default="windows" if os.name == "nt" else "posix",
    )
    for command in ("verify", "promote", "show", "discard"):
        selected = subparsers.add_parser(command)
        selected.add_argument("candidate_id")
        if command == "verify":
            selected.add_argument("--fault", choices=sorted(_FAULTS))
        if command == "promote":
            selected.add_argument("--kb-home", type=Path, default=installer.default_kb_home())
    return parser


def main() -> int:
    installer.configure_utf8_stdio()
    args = _parser().parse_args()
    try:
        if args.command == "prepare":
            result = prepare(
                candidate_home=args.candidate_home,
                codex=args.codex or installer.DEFAULT_CODEX_EXECUTABLE,
                platform=args.platform,
                candidate_id=args.candidate_id,
            )
        elif args.command == "verify":
            result = verify(
                candidate_home=args.candidate_home,
                candidate_id=args.candidate_id,
                codex=args.codex,
                fault=args.fault,
            )
        elif args.command == "promote":
            result = promote(
                candidate_home=args.candidate_home,
                candidate_id=args.candidate_id,
                kb_home=args.kb_home.expanduser(),
                codex=args.codex,
            )
        elif args.command == "show":
            result = show(
                candidate_home=args.candidate_home,
                candidate_id=args.candidate_id,
            )
        else:
            result = discard(
                candidate_home=args.candidate_home,
                candidate_id=args.candidate_id,
            )
    except (CandidateError, installer.InstallError, OSError, ValueError) as error:
        print(f"SULDE CODEX CANDIDATE: FAIL: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2 if not args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

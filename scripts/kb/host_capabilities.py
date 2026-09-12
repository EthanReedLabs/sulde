#!/usr/bin/env python3
"""Canonical host capability contract and live-observation projection.

The contract is deliberately smaller than either host's complete hook surface.
It names only the boundaries Sulde relies on for context recovery, human
control, tool supervision, turn reconciliation, and MCP availability.  Build,
install, smoke, and runtime diagnostics must consume this module instead of
maintaining independent required-hook lists.

Signed live observations provide integrity for telemetry that a host adapter
invoked a boundary. They never grant permission or prove a human decision;
native PermissionRequest pairing, Intent Guardian, and EffectAttempt remain
the independent authorities for authorization and outcome truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
from typing import Any, Mapping

# MCP loads this module with runpy from another entrypoint directory. Pin our
# sibling runtime imports to this concrete artifact, never to the caller's cwd.
_RUNTIME_DIRECTORY = str(Path(__file__).resolve().parent)
if _RUNTIME_DIRECTORY not in sys.path:
    sys.path.insert(0, _RUNTIME_DIRECTORY)


CONTRACT_SCHEMA = "sulde-host-capability-contract-v1"
OBSERVATION_SCHEMA = "sulde-host-capability-observation-v1"
PROVENANCE_SCHEMA = "sulde-host-hook-provenance-v1"
CONTRACT_VERSION = 1
OBSERVATION_LOG_NAME = "host-capabilities.jsonl"
HOOK_FAILURE_DIRECTORY = "hook-failures"
HOOK_FAILURE_SCHEMA = "sulde-host-hook-failure-v1"
PROVENANCE_KEY_NAME = "host-provenance.key"
MAX_OBSERVATION_BYTES = 4 * 1024 * 1024
SESSION_OBSERVATION_TTL_SECONDS = 30 * 60
PROVIDER_OBSERVATION_TTL_SECONDS = 24 * 60 * 60
OBSERVATION_REFRESH_SECONDS = 60
PROVENANCE_TTL_SECONDS = 120
PROVENANCE_CLOCK_SKEW_SECONDS = 10
TOOL_ROUNDTRIP_MAX_SECONDS = 15 * 60
PROVIDERS = ("claude", "codex")
OBSERVATION_SOURCES = {
    "live_host_hook",
    "synthetic_smoke",
    "managed_l3",
    "unclassified",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEX_32_RE = re.compile(r"^[0-9a-f]{32}$")
_TRUSTED_OBSERVATION_SOURCES = {"live_host_hook", "managed_l3"}
_TOOL_CALL_EVENTS = {"PreToolUse", "PostToolUse", "PostToolUseFailure"}


class HostCapabilityError(RuntimeError):
    """A host artifact or observation violates the shared capability contract."""


class HostProvenanceError(HostCapabilityError):
    """A claimed live host observation has no valid host-issued proof."""


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    hook_events: tuple[str, ...]
    entrypoints: tuple[str, ...]
    command_fragments: tuple[tuple[str, tuple[str, ...]], ...] = ()
    interactive_gate: bool = False
    approval_gate: bool = False
    live_scope: str = "session"
    freshness_ttl_seconds: int | None = SESSION_OBSERVATION_TTL_SECONDS


_CAPABILITIES: dict[str, tuple[CapabilitySpec, ...]] = {
    "claude": (
        CapabilitySpec(
            "session_context",
            ("SessionStart",),
            ("hooks/canon_inject.py", "hooks/session_start.py"),
            (("SessionStart", ("canon_inject.py", "session_start.py")),),
            interactive_gate=True,
            freshness_ttl_seconds=None,
        ),
        CapabilitySpec(
            "prompt_control",
            ("UserPromptSubmit",),
            ("hooks/user_prompt_submit.py",),
            (("UserPromptSubmit", ("user_prompt_submit.py",)),),
            interactive_gate=True,
        ),
        CapabilitySpec(
            "tool_guard",
            ("PreToolUse",),
            ("hooks/pre_tool_use.py",),
            (("PreToolUse", ("pre_tool_use.py",)),),
        ),
        CapabilitySpec(
            "tool_result",
            ("PostToolUse", "PostToolUseFailure"),
            ("hooks/post_tool_use.py",),
            (
                ("PostToolUse", ("post_tool_use.py",)),
                ("PostToolUseFailure", ("post_tool_use.py",)),
            ),
        ),
        CapabilitySpec(
            "turn_reconcile",
            ("Stop",),
            ("hooks/stop.py",),
            (("Stop", ("stop.py",)),),
        ),
        CapabilitySpec(
            "mcp_initialize",
            ("MCPInitialize",),
            ("tools/kb-mcp/server.py",),
            live_scope="provider",
            freshness_ttl_seconds=PROVIDER_OBSERVATION_TTL_SECONDS,
        ),
    ),
    "codex": (
        CapabilitySpec(
            "session_context",
            ("SessionStart",),
            ("scripts/session-start.py",),
            (("SessionStart", ("session-start",)),),
            interactive_gate=True,
            freshness_ttl_seconds=None,
        ),
        CapabilitySpec(
            "prompt_control",
            ("UserPromptSubmit",),
            (
                "scripts/user-prompt-submit.py",
                "runtime/hooks/user_prompt_submit.py",
            ),
            (("UserPromptSubmit", ("user-prompt-submit",)),),
            interactive_gate=True,
        ),
        CapabilitySpec(
            "tool_guard",
            ("PreToolUse",),
            ("scripts/pre-tool-use.py", "runtime/hooks/pre_tool_use.py"),
            (("PreToolUse", ("pre-tool-use",)),),
        ),
        CapabilitySpec(
            "host_approval",
            ("PermissionRequest",),
            (
                "scripts/pre-tool-use.py",
                "runtime/hooks/pre_tool_use.py",
            ),
            (("PermissionRequest", ("permission-request",)),),
            interactive_gate=True,
            approval_gate=True,
        ),
        CapabilitySpec(
            "tool_result",
            ("PostToolUse",),
            ("scripts/post-tool-use.py", "runtime/hooks/post_tool_use.py"),
            (("PostToolUse", ("post-tool-use",)),),
        ),
        CapabilitySpec(
            "turn_reconcile",
            ("Stop",),
            ("scripts/stop.py", "runtime/hooks/stop.py"),
            (("Stop", (" stop",)),),
        ),
        CapabilitySpec(
            "mcp_initialize",
            ("MCPInitialize",),
            ("runtime/tools/kb-mcp/server.py",),
            live_scope="provider",
            freshness_ttl_seconds=PROVIDER_OBSERVATION_TTL_SECONDS,
        ),
    ),
}

_ARTIFACT_METADATA = {
    "claude": {
        "descriptor": ".claude-plugin/plugin.json",
        "hook_config": "hooks/hooks.json",
        "contract_runtime": "scripts/kb/host_capabilities.py",
    },
    "codex": {
        "descriptor": ".codex-plugin/plugin.json",
        "hook_config": "hooks/hooks.json",
        "contract_runtime": "runtime/scripts/kb/host_capabilities.py",
    },
}


def _provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in PROVIDERS:
        raise HostCapabilityError(f"unsupported host provider: {value!r}")
    return provider


def capability_specs(provider: str) -> tuple[CapabilitySpec, ...]:
    return _CAPABILITIES[_provider(provider)]


def capability_contract(provider: str) -> dict[str, Any]:
    host = _provider(provider)
    capabilities = [
        {
            "capability_id": spec.capability_id,
            "hook_events": list(spec.hook_events),
            "entrypoints": list(spec.entrypoints),
            "interactive_gate": spec.interactive_gate,
            "approval_gate": spec.approval_gate,
            "live_scope": spec.live_scope,
        }
        for spec in capability_specs(host)
    ]
    digest = hashlib.sha256(
        json.dumps(
            capabilities,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema": CONTRACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "provider": host,
        "sha256": digest,
        "capabilities": capabilities,
    }


def _identity_paths(root: Path, provider: str) -> list[tuple[str, Path]]:
    host = _provider(provider)
    metadata = _ARTIFACT_METADATA[host]
    paths: list[tuple[str, Path]] = [
        ("descriptor", root / metadata["descriptor"]),
        ("hook_config", root / metadata["hook_config"]),
        ("contract_runtime", root / metadata["contract_runtime"]),
    ]
    runtime_directory = (root / metadata["contract_runtime"]).parent
    for name in ("host_observation_index.py", "session_lifecycle_lineage.py", "session_lifecycle_history.py"):
        paths.append(("contract_dependency:" + name, runtime_directory / name))
    for spec in capability_specs(host):
        paths.extend(
            (f"{spec.capability_id}:{relative}", root / relative)
            for relative in spec.entrypoints
        )
    return paths


def artifact_identity(root: Path, *, provider: str) -> str:
    """Hash the concrete hook/adapter files that implement one host contract."""
    digest = hashlib.sha256()
    for logical_name, path in sorted(_identity_paths(root, provider)):
        digest.update(logical_name.encode("utf-8"))
        digest.update(b"\0")
        try:
            content = path.read_bytes()
        except OSError:
            content = b"[missing]"
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _runtime_artifact_root(provider: str) -> Path | None:
    host = _provider(provider)
    metadata = _ARTIFACT_METADATA[host]
    module = Path(__file__).resolve()
    for candidate in module.parents:
        if (candidate / metadata["descriptor"]).is_file():
            return candidate
    if host == "codex":
        # Development checkout: the shared runtime lives at repository root,
        # while the provider adapter is nested under integrations/codex.
        for candidate in module.parents:
            plugin = candidate / "integrations" / "codex" / "plugins" / "sulde"
            if (plugin / ".codex-plugin" / "plugin.json").is_file():
                return plugin
    return None


def runtime_identity(provider: str) -> str:
    """Identify the exact currently executing host implementation.

    Packaged artifacts use their native layout.  A source checkout maps Codex
    runtime entrypoints back to repository files so development and tests have
    the same stale-runtime protection as installed plugins.
    """
    host = _provider(provider)
    artifact = _runtime_artifact_root(host)
    module = Path(__file__).resolve()
    if artifact is not None and (
        artifact / _ARTIFACT_METADATA[host]["contract_runtime"]
    ).is_file():
        return artifact_identity(artifact, provider=host)
    if host == "codex" and artifact is not None:
        source_root = module.parents[2]
        digest = hashlib.sha256()
        metadata = _ARTIFACT_METADATA[host]
        paths: list[tuple[str, Path]] = [
            ("descriptor", artifact / metadata["descriptor"]),
            ("hook_config", artifact / "hooks.posix.json"),
            ("contract_runtime", module),
        ]
        for name in ("host_observation_index.py", "session_lifecycle_lineage.py", "session_lifecycle_history.py"):
            paths.append(("contract_dependency:" + name, module.parent / name))
        for spec in capability_specs(host):
            for relative in spec.entrypoints:
                path = (
                    source_root / relative.removeprefix("runtime/")
                    if relative.startswith("runtime/")
                    else artifact / relative
                )
                paths.append((f"{spec.capability_id}:{relative}", path))
        for logical_name, path in sorted(paths):
            digest.update(logical_name.encode("utf-8"))
            digest.update(b"\0")
            try:
                content = path.read_bytes()
            except OSError:
                content = b"[missing]"
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()
    # This path is intentionally stable but visibly incomplete. Artifact
    # validation will still fail if required files are not packaged.
    return hashlib.sha256(module.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise HostCapabilityError(f"invalid host capability JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise HostCapabilityError(f"host capability JSON root must be an object: {path}")
    return value


def _hook_commands(registrations: Any, event: str) -> list[str]:
    if not isinstance(registrations, list) or len(registrations) != 1:
        raise HostCapabilityError(
            f"{event} must have exactly one registration path; got "
            f"{len(registrations) if isinstance(registrations, list) else 'invalid'}"
        )
    hooks = registrations[0].get("hooks") if isinstance(registrations[0], dict) else None
    if not isinstance(hooks, list) or not hooks:
        raise HostCapabilityError(f"{event} has no executable hook entries")
    commands = [
        str(row.get("command") or "")
        for row in hooks
        if isinstance(row, dict) and row.get("type") == "command"
    ]
    if not commands:
        raise HostCapabilityError(f"{event} has no command hook")
    return commands


def validate_artifact(root: Path, *, provider: str) -> dict[str, Any]:
    """Validate one staged/installed artifact against the single host contract."""
    host = _provider(provider)
    artifact = root.expanduser().resolve()
    metadata = _ARTIFACT_METADATA[host]
    descriptor = _read_object(artifact / metadata["descriptor"])
    # Both hosts discover hooks from their standard path.  Re-introducing an
    # explicit descriptor field would create a second registration path.
    if "hooks" in descriptor:
        raise HostCapabilityError(
            f"{host} descriptor must not explicitly register hooks; use the standard path only"
        )
    hook_document = _read_object(artifact / metadata["hook_config"])
    hooks = hook_document.get("hooks")
    if not isinstance(hooks, dict):
        raise HostCapabilityError(f"{host} hook configuration has no hooks object")
    runtime_contract = artifact / metadata["contract_runtime"]
    if not runtime_contract.is_file():
        raise HostCapabilityError(
            f"{host} artifact is missing its capability contract runtime: {runtime_contract}"
        )

    evidence: dict[str, dict[str, Any]] = {}
    for spec in capability_specs(host):
        missing = [relative for relative in spec.entrypoints if not (artifact / relative).is_file()]
        if missing:
            raise HostCapabilityError(
                f"{host} capability {spec.capability_id} is missing entrypoints: "
                + ", ".join(missing)
            )
        declared_events: list[str] = []
        for event, fragments in spec.command_fragments:
            commands = _hook_commands(hooks.get(event), event)
            for fragment in fragments:
                if not any(fragment in command for command in commands):
                    raise HostCapabilityError(
                        f"{host} capability {spec.capability_id} hook {event} "
                        f"does not route through {fragment!r}"
                    )
            declared_events.append(event)
        evidence[spec.capability_id] = {
            "declared": True,
            "packaged": True,
            "hook_events": list(spec.hook_events),
            "validated_hook_events": declared_events,
            "entrypoint_count": len(spec.entrypoints),
            "interactive_gate": spec.interactive_gate,
            "approval_gate": spec.approval_gate,
            "live_scope": spec.live_scope,
        }
    contract = capability_contract(host)
    return {
        "schema": CONTRACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "provider": host,
        "status": "artifact_ready",
        "contract_sha256": contract["sha256"],
        "runtime_sha256": artifact_identity(artifact, provider=host),
        "capabilities": evidence,
    }


def default_kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.environ.get("SULDE_TEST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        raise HostCapabilityError(
            "SULDE_TEST_MODE requires an explicit SULDE_KB_HOME; refusing the default production KB"
        )
    from sulde_paths import kb_home as canonical_kb_home

    return canonical_kb_home()


def observation_path(home: Path) -> Path:
    return home / OBSERVATION_LOG_NAME


def hook_failure_path(home: Path) -> Path:
    return home / "runtime" / HOOK_FAILURE_DIRECTORY


def provenance_key_path(home: Path) -> Path:
    return home / "runtime" / PROVENANCE_KEY_NAME


def _canonical_workspace(value: Any) -> str:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        return ""
    try:
        current = Path(value).expanduser().resolve()
        if current.is_file():
            current = current.parent
        for candidate in (current, *current.parents):
            if (candidate / ".git").exists() or (candidate / ".sulde-config.yaml").is_file():
                return str(candidate)
        return str(current)
    except (OSError, RuntimeError, ValueError):
        return os.path.abspath(os.path.expanduser(str(value)))


def workspace_identifier(value: Any) -> str:
    normalized = _canonical_workspace(value)
    if not normalized:
        return ""
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _call_id_sha256(hook_event: str, value: Any) -> str:
    """Return a non-reversible correlation key for a host tool lifecycle."""
    if hook_event not in _TOOL_CALL_EVENTS:
        return ""
    call_id = str(value or "").strip()
    if not call_id or len(call_id) > 1024:
        return ""
    return hashlib.sha256(call_id.encode("utf-8")).hexdigest()


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _utc_now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise HostCapabilityError("host observation clock must be timezone-aware")
    return current.astimezone(timezone.utc)


def _resolved(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return Path(os.path.abspath(os.path.expanduser(str(path))))


def _assert_test_write_isolated(target_home: Path, *, explicit_home: bool) -> None:
    """Fail fast if a test attempts to append under the production KB tree."""
    if os.environ.get("SULDE_TEST_MODE", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return
    if not explicit_home and not os.environ.get("SULDE_KB_HOME"):
        raise HostCapabilityError(
            "SULDE_TEST_MODE requires an explicit observation home"
        )
    production_value = os.environ.get("SULDE_PRODUCTION_KB_HOME", "").strip()
    if not production_value:
        return
    production = _resolved(Path(production_value))
    target = _resolved(target_home)
    if target == production or production in target.parents:
        raise HostCapabilityError(
            f"test observation refused under production KB: {target}"
        )


def _read_provenance_key(home: Path) -> bytes:
    path = provenance_key_path(home)
    descriptor = -1
    try:
        path_metadata = path.lstat()
        if stat.S_ISLNK(path_metadata.st_mode):
            raise HostProvenanceError("host provenance key must not be a symlink")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
        ):
            raise HostProvenanceError("host provenance key permissions are not private")
        chunks: list[bytes] = []
        remaining = 33
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
    except HostProvenanceError:
        raise
    except OSError as error:
        raise HostProvenanceError("host provenance key is unavailable") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(value) != 32:
        raise HostProvenanceError("host provenance key has invalid length")
    return value


def provision_provenance_key(home: Path) -> Path:
    """Provision the local host-adapter key with private permissions.

    Installation/launcher code owns this call. Runtime hook consumers only
    verify existing proofs and never create authority for themselves.
    """
    target_home = home.expanduser()
    _assert_test_write_isolated(target_home, explicit_home=True)
    path = provenance_key_path(target_home)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        _read_provenance_key(target_home)
        return path
    except HostProvenanceError:
        if os.path.lexists(path):
            # A concurrent publisher may have appeared after our first
            # FileNotFound. Re-read it once: a complete private winner is
            # accepted, while malformed/symlink authority is never replaced.
            _read_provenance_key(target_home)
            return path
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{PROVENANCE_KEY_NAME}.",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        key = secrets.token_bytes(32)
        written = os.write(descriptor, key)
        if written != len(key):
            raise OSError("host provenance key write was incomplete")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        # Hard-link publication is atomic and cannot overwrite another
        # install/bridge process that won the same initialization race.
        os.link(temporary, path)
    except FileExistsError:
        _read_provenance_key(target_home)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return path


def _provenance_payload(value: Mapping[str, Any]) -> bytes:
    unsigned = {key: item for key, item in value.items() if key != "signature"}
    return json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def issue_host_provenance(
    *,
    provider: str,
    hook_event: str,
    session_id: str = "",
    workspace: Any = "",
    call_id: str = "",
    source: str = "live_host_hook",
    loaded_module_generation: str = "",
    artifact_generation: str = "",
    home: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Issue short-lived telemetry integrity proof, never permission authority."""
    host = _provider(provider)
    _spec_for_hook(host, hook_event)
    if source not in _TRUSTED_OBSERVATION_SOURCES:
        raise HostProvenanceError("only trusted live sources receive host provenance")
    current = _utc_now(now)
    key = _read_provenance_key(home.expanduser())
    proof: dict[str, Any] = {
        "schema": PROVENANCE_SCHEMA,
        "provider": host,
        "hook_event": hook_event,
        "runtime_sha256": runtime_identity(host),
        "session_id": str(session_id or "")[:256],
        "workspace_id": workspace_identifier(workspace),
        "source": source,
        "issued_at": current.isoformat(),
        "expires_at": (current + timedelta(seconds=PROVENANCE_TTL_SECONDS)).isoformat(),
        "nonce": secrets.token_hex(16),
    }
    loaded_generation = str(loaded_module_generation or "").strip()
    artifact = str(artifact_generation or "").strip()
    if bool(loaded_generation) != bool(artifact):
        raise HostProvenanceError(
            "loaded module and artifact generation must be issued together"
        )
    if loaded_generation:
        proof["loaded_module_generation"] = loaded_generation
        proof["artifact_generation"] = artifact
    call_id_sha256 = _call_id_sha256(hook_event, call_id)
    if call_id_sha256:
        proof["call_id_sha256"] = call_id_sha256
    proof["signature"] = hmac.new(
        key,
        _provenance_payload(proof),
        hashlib.sha256,
    ).hexdigest()
    return proof


def verify_host_provenance(
    proof: Any,
    *,
    provider: str,
    hook_event: str,
    session_id: str,
    workspace: Any,
    call_id: str = "",
    source: str,
    home: Path,
    now: datetime | None = None,
    runtime_sha256: str | None = None,
    loaded_module_generation: str | None = None,
    artifact_generation: str | None = None,
) -> dict[str, Any]:
    """Verify exact binding, generation, signature, and issuance freshness."""
    if not isinstance(proof, Mapping):
        raise HostProvenanceError("live host observation is missing signed provenance")
    host = _provider(provider)
    current = _utc_now(now)
    expected_runtime = runtime_sha256 or runtime_identity(host)
    expected = {
        "schema": PROVENANCE_SCHEMA,
        "provider": host,
        "hook_event": hook_event,
        "runtime_sha256": expected_runtime,
        "session_id": str(session_id or "")[:256],
        "workspace_id": workspace_identifier(workspace),
        "source": source,
    }
    if loaded_module_generation is not None or artifact_generation is not None:
        if not loaded_module_generation or not artifact_generation:
            raise HostProvenanceError(
                "loaded module and artifact generation must be verified together"
            )
        expected["loaded_module_generation"] = loaded_module_generation
        expected["artifact_generation"] = artifact_generation
    for name, value in expected.items():
        if proof.get(name) != value:
            raise HostProvenanceError(f"host provenance {name} binding mismatch")
    expected_call_id = _call_id_sha256(hook_event, call_id)
    if str(proof.get("call_id_sha256") or "") != expected_call_id:
        raise HostProvenanceError("host provenance call_id binding mismatch")
    nonce = str(proof.get("nonce") or "")
    signature = str(proof.get("signature") or "")
    issued = _parse_time(proof.get("issued_at"))
    expires = _parse_time(proof.get("expires_at"))
    if _HEX_32_RE.fullmatch(nonce) is None or _SHA256_RE.fullmatch(signature) is None:
        raise HostProvenanceError("host provenance token shape is invalid")
    if issued is None or expires is None or expires <= issued:
        raise HostProvenanceError("host provenance time window is invalid")
    if (expires - issued).total_seconds() > PROVENANCE_TTL_SECONDS:
        raise HostProvenanceError("host provenance lifetime exceeds policy")
    skew = timedelta(seconds=PROVENANCE_CLOCK_SKEW_SECONDS)
    if current < issued - skew or current > expires + skew:
        raise HostProvenanceError("host provenance is not fresh")
    expected_signature = hmac.new(
        _read_provenance_key(home.expanduser()),
        _provenance_payload(proof),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise HostProvenanceError("host provenance signature mismatch")
    return dict(proof)


def _stored_provenance_valid(row: Mapping[str, Any], home: Path) -> bool:
    source = str(row.get("source") or "")
    if source not in _TRUSTED_OBSERVATION_SOURCES:
        return True
    proof = row.get("provenance")
    if not isinstance(proof, Mapping):
        return False
    for name in (
        "provider",
        "hook_event",
        "runtime_sha256",
        "session_id",
        "workspace_id",
        "source",
    ):
        if proof.get(name) != row.get(name):
            return False
    generation_fields = ("loaded_module_generation", "artifact_generation")
    if any(proof.get(name) or row.get(name) for name in generation_fields):
        if not all(
            isinstance(proof.get(name), str)
            and bool(str(proof.get(name)).strip())
            and proof.get(name) == row.get(name)
            for name in generation_fields
        ):
            return False
    proof_call_id = str(proof.get("call_id_sha256") or "")
    row_call_id = str(row.get("call_id_sha256") or "")
    if proof_call_id != row_call_id or (
        proof_call_id and _SHA256_RE.fullmatch(proof_call_id) is None
    ):
        return False
    if proof.get("schema") != PROVENANCE_SCHEMA:
        return False
    issued = _parse_time(proof.get("issued_at"))
    expires = _parse_time(proof.get("expires_at"))
    observed = _parse_time(row.get("at"))
    signature = str(proof.get("signature") or "")
    nonce = str(proof.get("nonce") or "")
    if (
        issued is None
        or expires is None
        or observed is None
        or expires <= issued
        or (expires - issued).total_seconds() > PROVENANCE_TTL_SECONDS
        or _SHA256_RE.fullmatch(signature) is None
        or _HEX_32_RE.fullmatch(nonce) is None
    ):
        return False
    skew = timedelta(seconds=PROVENANCE_CLOCK_SKEW_SECONDS)
    if observed < issued - skew or observed > expires + skew:
        return False
    try:
        expected = hmac.new(
            _read_provenance_key(home),
            _provenance_payload(proof),
            hashlib.sha256,
        ).hexdigest()
    except HostProvenanceError:
        return False
    return hmac.compare_digest(signature, expected)


def _spec_for_hook(provider: str, hook_event: str) -> CapabilitySpec:
    for spec in capability_specs(provider):
        if hook_event in spec.hook_events:
            return spec
    raise HostCapabilityError(
        f"{provider} hook {hook_event!r} is outside the Sulde host capability contract"
    )


def _append_observation(home: Path, row: Mapping[str, Any]) -> None:
    target = observation_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("host observation append made no progress")
            view = view[written:]
    finally:
        os.close(descriptor)


def _hook_failure_digest(value: Mapping[str, Any]) -> str:
    unsigned = {
        key: item for key, item in value.items() if key != "integrity_sha256"
    }
    return hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def record_hook_failure(
    *,
    provider: str,
    hook_event: str,
    stage: str,
    error_kind: str,
    session_id: str = "",
    workspace: Any = "",
    call_id: str = "",
    exit_code: int | None = None,
    loaded_module_generation: str = "",
    artifact_generation: str = "",
    home: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist one redacted, non-authorizing Hook failure receipt.

    Receipts intentionally live outside the intent/effect ledgers. They prove
    only that audit delivery was inconclusive, never that the tool succeeded or
    that no side effect occurred. One file per stable id makes concurrent
    retries idempotent without sharing a journal lock with Guardian policy.
    """
    host = _provider(provider)
    _spec_for_hook(host, hook_event)
    if stage not in {"wrapper", "bridge", "adapter", "runtime"}:
        raise HostCapabilityError("hook failure stage is invalid")
    failure_kind = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(error_kind or "unknown"))[:96]
    target_home = (home if home is not None else default_kb_home()).expanduser()
    _assert_test_write_isolated(target_home, explicit_home=home is not None)
    current = _utc_now(now)
    call_id_sha256 = _call_id_sha256(hook_event, call_id)
    identity: dict[str, Any] = {
        "provider": host,
        "hook_event": hook_event,
        "stage": stage,
        "error_kind": failure_kind or "unknown",
        "session_id": str(session_id or "")[:256],
        "workspace_id": workspace_identifier(workspace),
        "call_id_sha256": call_id_sha256,
        "loaded_module_generation": str(loaded_module_generation or "")[:256],
        "artifact_generation": str(artifact_generation or "")[:512],
        "exit_code": exit_code if isinstance(exit_code, int) else None,
    }
    if not call_id_sha256:
        # A host event without a call id remains observable, but repeated
        # failures are coalesced only inside a bounded minute rather than for
        # the lifetime of a session.
        identity["minute_bucket"] = current.strftime("%Y-%m-%dT%H:%MZ")
    failure_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    row: dict[str, Any] = {
        "schema": HOOK_FAILURE_SCHEMA,
        "failure_id": failure_id,
        "at": current.isoformat(),
        **identity,
        "outcome": "inconclusive",
        "effect_claim": "none",
        "authority": "telemetry_only",
    }
    row["integrity_sha256"] = _hook_failure_digest(row)
    directory = hook_failure_path(target_home)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        metadata = directory.lstat()
    except OSError as error:
        raise HostCapabilityError("hook failure receipt directory is unavailable") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or (hasattr(os, "getuid") and metadata.st_uid != os.getuid())
    ):
        raise HostCapabilityError("hook failure receipt directory is unsafe")
    path = directory / f"{failure_id}.json"
    encoded = (
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{failure_id}.",
        dir=directory,
    )
    temporary = Path(temporary_name)
    try:
        try:
            os.chmod(temporary, 0o600)
            view = memoryview(encoded)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("hook failure receipt write made no progress")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            # Publish only complete fsynced bytes. A concurrent identical
            # writer either wins this link or reads the complete winner.
            os.link(temporary, path)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise HostCapabilityError(
                    "existing hook failure receipt is invalid"
                ) from error
            if (
                not isinstance(existing, dict)
                or existing.get("failure_id") != failure_id
                or existing.get("integrity_sha256")
                != _hook_failure_digest(existing)
            ):
                raise HostCapabilityError(
                    "existing hook failure receipt failed integrity"
                )
            return existing
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return row


def _read_hook_failures(home: Path) -> tuple[list[dict[str, Any]], int]:
    directory = hook_failure_path(home)
    if not directory.is_dir() or directory.is_symlink():
        return [], int(directory.exists())
    rows: list[dict[str, Any]] = []
    invalid = 0
    try:
        paths = sorted(directory.glob("*.json"))[-500:]
    except OSError:
        return [], 1
    for path in paths:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            invalid += 1
            continue
        if (
            not isinstance(row, dict)
            or row.get("schema") != HOOK_FAILURE_SCHEMA
            or row.get("outcome") != "inconclusive"
            or row.get("effect_claim") != "none"
            or row.get("authority") != "telemetry_only"
            or row.get("failure_id") != path.stem
            or row.get("integrity_sha256") != _hook_failure_digest(row)
            or _parse_time(row.get("at")) is None
        ):
            invalid += 1
            continue
        rows.append(row)
    return rows, invalid


def hook_failure_projection(
    home: Path,
    *,
    provider: str | None = None,
    session_id: str | None = None,
    workspace: Any = None,
) -> dict[str, Any]:
    """Return an idempotent, read-only settlement view of Hook failures."""
    failures, invalid = _read_hook_failures(home.expanduser())
    observations, observation_invalid = _read_tail(observation_path(home.expanduser()))
    selected_provider = _provider(provider) if provider else ""
    selected_session = str(session_id or "")
    selected_workspace = workspace_identifier(workspace) if workspace is not None else ""
    recovered_at: dict[tuple[str, ...], datetime] = {}
    for row in observations:
        if (
            row.get("source") not in _TRUSTED_OBSERVATION_SOURCES
            or not row.get("call_id_sha256")
        ):
            continue
        observed_at = _parse_time(row.get("at"))
        if observed_at is None:
            continue
        key = (
            str(row.get("provider") or ""),
            str(row.get("session_id") or ""),
            str(row.get("workspace_id") or ""),
            str(row.get("hook_event") or ""),
            str(row.get("call_id_sha256") or ""),
            str(row.get("loaded_module_generation") or ""),
            str(row.get("artifact_generation") or ""),
        )
        if observed_at > recovered_at.get(key, datetime.min.replace(tzinfo=timezone.utc)):
            recovered_at[key] = observed_at
    current: list[dict[str, Any]] = []
    other: list[dict[str, Any]] = []
    recovered = 0
    for row in failures:
        key = (
            str(row.get("provider") or ""),
            str(row.get("session_id") or ""),
            str(row.get("workspace_id") or ""),
            str(row.get("hook_event") or ""),
            str(row.get("call_id_sha256") or ""),
            str(row.get("loaded_module_generation") or ""),
            str(row.get("artifact_generation") or ""),
        )
        failed_at = _parse_time(row.get("at"))
        status = (
            "callback_recovered"
            if row.get("call_id_sha256")
            and failed_at is not None
            and recovered_at.get(key, datetime.min.replace(tzinfo=timezone.utc))
            > failed_at
            else "inconclusive"
        )
        if status == "callback_recovered":
            recovered += 1
        summary = {
            "failure_id": row["failure_id"],
            "at": row["at"],
            "hook_event": row["hook_event"],
            "stage": row["stage"],
            "error_kind": row["error_kind"],
            "status": status,
            "effect_outcome": "inconclusive",
            "loaded_module_generation": row.get("loaded_module_generation") or "unknown",
            "artifact_generation": row.get("artifact_generation") or "unknown",
        }
        is_current = (
            (not selected_provider or row.get("provider") == selected_provider)
            and (not selected_session or row.get("session_id") == selected_session)
            and (not selected_workspace or row.get("workspace_id") == selected_workspace)
        )
        (current if is_current else other).append(summary)
    return {
        "schema": "sulde-host-hook-failure-projection-v1",
        "status": "invalid" if invalid else "observed" if current else "clear",
        "authority": "telemetry_only_not_effect_truth",
        "current_lane": current[-20:],
        "current_lane_total": len(current),
        "other_lanes_total": len(other),
        "callback_recovered_total": recovered,
        "invalid_receipts": invalid,
        "invalid_observations": observation_invalid,
    }


def record_observation(
    *,
    provider: str,
    hook_event: str,
    session_id: str = "",
    workspace: Any = "",
    call_id: str = "",
    source: str | None = None,
    home: Path | None = None,
    provenance: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append non-authorizing telemetry that a host boundary was invoked."""
    host = _provider(provider)
    spec = _spec_for_hook(host, hook_event)
    target_home = (home if home is not None else default_kb_home()).expanduser()
    _assert_test_write_isolated(target_home, explicit_home=home is not None)
    current = _utc_now(now)
    observation_source = str(
        source or os.environ.get("SULDE_HOOK_OBSERVATION_SOURCE") or "unclassified"
    ).strip()
    if observation_source not in OBSERVATION_SOURCES:
        observation_source = "unclassified"
    verified_provenance: dict[str, Any] | None = None
    if observation_source in _TRUSTED_OBSERVATION_SOURCES:
        proof_loaded_generation = (
            str(provenance.get("loaded_module_generation") or "")
            if isinstance(provenance, Mapping)
            and "loaded_module_generation" in provenance
            else None
        )
        proof_artifact_generation = (
            str(provenance.get("artifact_generation") or "")
            if isinstance(provenance, Mapping) and "artifact_generation" in provenance
            else None
        )
        verified_provenance = verify_host_provenance(
            provenance,
            provider=host,
            hook_event=hook_event,
            session_id=str(session_id or ""),
            workspace=workspace,
            call_id=call_id,
            source=observation_source,
            home=target_home,
            now=current,
            loaded_module_generation=proof_loaded_generation,
            artifact_generation=proof_artifact_generation,
        )
    row: dict[str, Any] = {
        "schema": OBSERVATION_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "at": current.isoformat(),
        "provider": host,
        "runtime_sha256": runtime_identity(host),
        "session_id": str(session_id or "")[:256],
        "workspace_id": workspace_identifier(workspace),
        "capability_id": spec.capability_id,
        "hook_event": hook_event,
        "source": observation_source,
        "outcome": "observed",
    }
    call_id_sha256 = _call_id_sha256(hook_event, call_id)
    if call_id_sha256:
        row["call_id_sha256"] = call_id_sha256
    if verified_provenance is not None:
        row["provenance"] = verified_provenance
        if verified_provenance.get("loaded_module_generation"):
            row["loaded_module_generation"] = verified_provenance[
                "loaded_module_generation"
            ]
            row["artifact_generation"] = verified_provenance[
                "artifact_generation"
            ]
    # Readiness needs proof that a boundary exists, not a duplicate audit row
    # for every tool call. Keep one fact per runtime/session/workspace/hook/source
    # in the bounded tail; the authoritative tool lifecycle remains Intent audit.
    index_session = "@provider" if spec.live_scope == "provider" else str(row["session_id"])
    existing_rows, _index = _read_session_observations(target_home, host, index_session)
    identity_fields: tuple[str, ...] = (
        "provider",
        "runtime_sha256",
        "session_id",
        "workspace_id",
        "capability_id",
        "hook_event",
        "source",
        "outcome",
        "loaded_module_generation",
        "artifact_generation",
    )
    if call_id_sha256 and _verified_tool_roundtrip(
        existing_rows,
        provider=host,
        runtime_sha256=str(row["runtime_sha256"]),
        session_id=str(row["session_id"]),
        workspace_id=str(row["workspace_id"]),
        now=current,
    ) is None:
        # Preserve only enough exact call correlation to establish one current
        # runtime roundtrip. Once established, normal refresh de-duplication
        # resumes so the readiness journal does not grow per tool call.
        identity_fields += ("call_id_sha256",)
    for existing in reversed(existing_rows):
        if all(existing.get(key) == row.get(key) for key in identity_fields):
            observed_at = _parse_time(existing.get("at"))
            if (
                observed_at is not None
                and 0 <= (current - observed_at).total_seconds() < OBSERVATION_REFRESH_SECONDS
            ):
                if _index.get("status") != "verified":
                    _publish_session_observations(target_home, host, index_session)
                return existing
            break
    row["event_id"] = hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    _append_observation(target_home, row)
    _publish_session_observations(target_home, host, index_session)
    return row


def record_hook_observation(
    payload: Mapping[str, Any],
    *,
    provider: str,
    hook_event: str,
    home: Path | None = None,
) -> bool:
    """Best-effort hook adapter; authority never depends on readiness telemetry."""
    requested_source = str(
        payload.get("sulde_observation_source")
        or os.environ.get("SULDE_HOOK_OBSERVATION_SOURCE")
        or "unclassified"
    )
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "")
    workspace = (
        payload.get("sulde_workspace_root")
        or payload.get("cwd")
        or os.getcwd()
    )
    call_id = str(
        payload.get("call_id")
        or payload.get("toolUseId")
        or payload.get("tool_use_id")
        or payload.get("callId")
        or ""
    )
    try:
        record_observation(
            provider=provider,
            hook_event=hook_event,
            session_id=session_id,
            workspace=workspace,
            call_id=call_id,
            source=requested_source,
            home=home,
            provenance=(
                payload.get("sulde_host_provenance")
                if isinstance(payload.get("sulde_host_provenance"), Mapping)
                else None
            ),
        )
        return True
    except HostProvenanceError:
        # Preserve an auditable non-authorizing fact. A payload/env string can
        # request a source label, but only a signed adapter proof can elevate it.
        try:
            record_observation(
                provider=provider,
                hook_event=hook_event,
                session_id=session_id,
                workspace=workspace,
                call_id=call_id,
                source="unclassified",
                home=home,
            )
        except (HostCapabilityError, OSError, UnicodeError, ValueError):
            return False
        return False
    except HostCapabilityError:
        if os.environ.get("SULDE_TEST_MODE", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            raise
        return False
    except (OSError, UnicodeError, ValueError):
        return False


def _valid_observation(row: Any, home: Path) -> bool:
    if (
        not isinstance(row, dict)
        or row.get("schema") != OBSERVATION_SCHEMA
        or not isinstance(row.get("provider"), str)
        or row.get("provider") not in PROVIDERS
        or not isinstance(row.get("source"), str)
        or row.get("source") not in OBSERVATION_SOURCES
        or row.get("outcome") != "observed"
        or not isinstance(row.get("runtime_sha256"), str)
        or _SHA256_RE.fullmatch(str(row.get("runtime_sha256"))) is None
        or _parse_time(row.get("at")) is None
        or (row.get("call_id_sha256") is not None and row.get("call_id_sha256") != ""
            and _SHA256_RE.fullmatch(str(row.get("call_id_sha256"))) is None)
        or bool(row.get("loaded_module_generation")) != bool(row.get("artifact_generation"))
    ):
        return False
    try:
        spec = _spec_for_hook(str(row["provider"]), str(row.get("hook_event") or ""))
        return row.get("capability_id") == spec.capability_id and _stored_provenance_valid(row, home)
    except (HostCapabilityError, TypeError, ValueError):
        return False


def _read_session_observations(home: Path, provider: str, session_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from host_observation_index import read_index

    try:
        return read_index(home, provider, session_id, key=_read_provenance_key(home),
                          validate=lambda row: _valid_observation(row, home))
    except (HostProvenanceError, OSError, ValueError, TypeError):
        rows, invalid = _read_tail(observation_path(home))
        return rows, {"status": "unavailable", "invalid_rows": invalid,
                      "authority": "telemetry_only_not_permission"}


def _publish_session_observations(home: Path, provider: str, session_id: str) -> bool:
    from host_observation_index import publish_index

    try:
        return publish_index(home, provider, session_id, key=_read_provenance_key(home),
                             validate=lambda row: _valid_observation(row, home))
    except (HostProvenanceError, OSError, ValueError, TypeError):
        return False


def _read_tail(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.is_file():
        return [], 0
    invalid = 0
    rows: list[dict[str, Any]] = []
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            offset = max(0, size - MAX_OBSERVATION_BYTES)
            handle.seek(offset)
            payload = handle.read(MAX_OBSERVATION_BYTES)
        if offset:
            newline = payload.find(b"\n")
            payload = payload[newline + 1 :] if newline >= 0 else b""
    except OSError:
        return [], 1
    for raw_line in payload.splitlines():
        try:
            row = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            invalid += 1
            continue
        if not _valid_observation(row, path.parent):
            invalid += 1
            continue
        rows.append(row)
    return rows, invalid


def _source_status(rows: list[dict[str, Any]]) -> str:
    if any(row.get("source") in {"live_host_hook", "managed_l3"} for row in rows):
        return "live_verified"
    if any(row.get("source") == "synthetic_smoke" for row in rows):
        return "synthetic_only"
    return "unobserved"


def _verified_tool_roundtrip(
    rows: list[dict[str, Any]],
    *,
    provider: str,
    runtime_sha256: str,
    session_id: str,
    workspace_id: str,
    now: datetime,
) -> dict[str, Any] | None:
    """Find the latest signed, ordered Pre/Post pair for one exact host call."""
    eligible: list[tuple[dict[str, Any], datetime]] = []
    for row in rows:
        if (
            row.get("provider") != provider
            or row.get("runtime_sha256") != runtime_sha256
            or row.get("session_id") != session_id
            or row.get("workspace_id") != workspace_id
            or row.get("source") not in _TRUSTED_OBSERVATION_SOURCES
            or _SHA256_RE.fullmatch(str(row.get("call_id_sha256") or "")) is None
        ):
            continue
        observed = _parse_time(row.get("at"))
        if observed is None:
            continue
        age_seconds = (now - observed).total_seconds()
        if (
            age_seconds < -PROVENANCE_CLOCK_SKEW_SECONDS
            or age_seconds > SESSION_OBSERVATION_TTL_SECONDS
        ):
            continue
        eligible.append((row, observed))
    starts: dict[
        tuple[str, str, str], list[tuple[dict[str, Any], datetime]]
    ] = {}
    for row, observed in eligible:
        if row.get("hook_event") == "PreToolUse":
            key = (
                str(row["call_id_sha256"]),
                str(row.get("loaded_module_generation") or ""),
                str(row.get("artifact_generation") or ""),
            )
            starts.setdefault(key, []).append((row, observed))
    pairs: list[tuple[datetime, datetime, str, str, str]] = []
    for row, completed_at in eligible:
        if row.get("hook_event") not in {"PostToolUse", "PostToolUseFailure"}:
            continue
        call_key = str(row["call_id_sha256"])
        generation_key = (
            call_key,
            str(row.get("loaded_module_generation") or ""),
            str(row.get("artifact_generation") or ""),
        )
        for _started, started_at in starts.get(generation_key, []):
            elapsed = (completed_at - started_at).total_seconds()
            if 0 < elapsed <= TOOL_ROUNDTRIP_MAX_SECONDS:
                pairs.append((completed_at, started_at, *generation_key))
    if not pairs:
        return None
    (
        completed_at,
        started_at,
        call_key,
        loaded_module_generation,
        artifact_generation,
    ) = max(pairs)
    return {
        "call_id_sha256": call_key,
        "started_at": started_at,
        "completed_at": completed_at,
        "loaded_module_generation": loaded_module_generation or "legacy",
        "artifact_generation": artifact_generation or "legacy",
    }


def readiness_projection(
    home: Path,
    *,
    provider: str | None = None,
    session_id: str | None = None,
    workspace: Path | str | None = None,
    expected_runtime_sha256: str | None = None,
    approval_required: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Project artifact-independent live readiness without exposing raw event rows."""
    if provider is None:
        by_provider = {
            host: readiness_projection(
                home,
                provider=host,
                session_id=session_id,
                workspace=workspace,
                expected_runtime_sha256=expected_runtime_sha256,
                approval_required=approval_required,
                now=now,
            )
            for host in PROVIDERS
        }
        states = {value["status"] for value in by_provider.values()}
        status = (
            "interactive_ready"
            if "interactive_ready" in states
            else "interactive_partial"
            if "interactive_partial" in states
            else "synthetic_only"
            if "synthetic_only" in states
            else "unobserved"
        )
        return {
            "schema": CONTRACT_SCHEMA,
            "version": CONTRACT_VERSION,
            "provider": "any",
            "status": status,
            "telemetry_authority": "integrity_only_not_permission_authority",
            "by_provider": by_provider,
        }

    host = _provider(provider)
    if session_id:
        rows, index_projection = _read_session_observations(home, host, session_id)
        provider_rows, provider_index = _read_session_observations(home, host, "@provider")
        identities = {json.dumps(row, sort_keys=True) for row in rows}
        rows.extend(row for row in provider_rows if row.get("capability_id") == "mcp_initialize"
                    and json.dumps(row, sort_keys=True) not in identities)
        invalid = index_projection.get("invalid_rows", 0) + provider_index.get("invalid_rows", 0)
    else:
        rows, invalid = _read_tail(observation_path(home))
        index_projection = {"status": "provider_tail", "authority": "telemetry_only_not_permission"}
    current = _utc_now(now)
    current_runtime = expected_runtime_sha256 or runtime_identity(host)
    if _SHA256_RE.fullmatch(current_runtime) is None:
        raise HostCapabilityError("expected runtime identity must be lowercase sha256")
    wanted_workspace = workspace_identifier(workspace) if workspace is not None else ""
    selected: dict[str, list[dict[str, Any]]] = {}
    stale: dict[str, int] = {}
    stale_runtime_rows = 0
    for spec in capability_specs(host):
        matches = []
        stale_count = 0
        ttl = spec.freshness_ttl_seconds
        for row in rows:
            if row.get("provider") != host or row.get("capability_id") != spec.capability_id:
                continue
            if row.get("runtime_sha256") != current_runtime:
                stale_runtime_rows += 1
                continue
            if spec.live_scope == "session":
                if session_id is not None and row.get("session_id") != session_id:
                    continue
                if wanted_workspace and row.get("workspace_id") != wanted_workspace:
                    continue
            observed = _parse_time(row.get("at"))
            if observed is None:
                stale_count += 1
                continue
            age_seconds = (current - observed).total_seconds()
            if age_seconds < -PROVENANCE_CLOCK_SKEW_SECONDS:
                stale_count += 1
                continue
            if ttl is not None and age_seconds > ttl:
                stale_count += 1
                continue
            matches.append(row)
        selected[spec.capability_id] = matches
        stale[spec.capability_id] = stale_count

    roundtrip = (
        _verified_tool_roundtrip(
            rows,
            provider=host,
            runtime_sha256=current_runtime,
            session_id=str(session_id or ""),
            workspace_id=wanted_workspace,
            now=current,
        )
        if session_id and wanted_workspace
        else None
    )
    carried_runtime_by_capability: dict[str, str] = {}
    carried_workspace_by_capability: dict[str, str] = {}
    workspace_continuity_status = "unverified"
    active_turn_capabilities: set[str] = set()
    if roundtrip is not None:
        roundtrip_started = roundtrip["started_at"]
        from session_lifecycle_lineage import predecessor_workspaces

        if (roundtrip["loaded_module_generation"] != "legacy"
                and roundtrip["artifact_generation"] != "legacy"):
            predecessors, workspace_continuity_status = predecessor_workspaces(
                home, provider=host, session_id=str(session_id),
                target_workspace_id=wanted_workspace, before=roundtrip_started,
            )
        else:
            predecessors, workspace_continuity_status = {}, "missing_generation_binding"

        def session_row(row: Mapping[str, Any], capability_id: str) -> bool:
            row_workspace = str(row.get("workspace_id") or "")
            workspace_matches = row_workspace == wanted_workspace
            if not workspace_matches and row_workspace in predecessors:
                observed = _parse_time(row.get("at"))
                workspace_matches = observed is not None and observed <= predecessors[row_workspace]
            return bool(
                row.get("provider") == host
                and row.get("capability_id") == capability_id
                and row.get("session_id") == session_id
                and workspace_matches
                and row.get("source") in _TRUSTED_OBSERVATION_SOURCES
            )

        def observed_before_roundtrip(row: Mapping[str, Any]) -> datetime | None:
            observed = _parse_time(row.get("at"))
            if observed is None:
                return None
            if observed >= roundtrip_started:
                return None
            return observed

        def prompt_belongs_to_active_turn(observed: datetime) -> bool:
            for candidate in rows:
                # Stop ends this host turn even if it was observed while the
                # same session visited another workspace or runtime generation.
                if not (candidate.get("provider") == host
                        and candidate.get("session_id") == session_id
                        and candidate.get("capability_id") == "turn_reconcile"
                        and candidate.get("source") in _TRUSTED_OBSERVATION_SOURCES):
                    continue
                stopped = _parse_time(candidate.get("at"))
                if (
                    stopped is not None
                    and observed < stopped <= current
                ):
                    return False
            return True

        selected["prompt_control"] = [
            row
            for row in selected["prompt_control"]
            if row.get("source") not in _TRUSTED_OBSERVATION_SOURCES
            or (
                (observed := observed_before_roundtrip(row)) is not None
                and prompt_belongs_to_active_turn(observed)
            )
        ]

        # A long tool call can legitimately outlive the prompt activity TTL.
        # Keep that prompt only while an exact current-runtime tool roundtrip
        # proves the turn is still running and no Stop reconciled it.
        if _source_status(selected["prompt_control"]) != "live_verified":
            current_prompts: list[tuple[datetime, dict[str, Any]]] = []
            for row in rows:
                if (
                    row.get("runtime_sha256") == current_runtime
                    and session_row(row, "prompt_control")
                ):
                    observed = observed_before_roundtrip(row)
                    if (
                        observed is not None
                        and (current - observed).total_seconds()
                        >= -PROVENANCE_CLOCK_SKEW_SECONDS
                        and prompt_belongs_to_active_turn(observed)
                    ):
                        current_prompts.append((observed, row))
            if current_prompts:
                _observed, prompt = max(current_prompts, key=lambda item: item[0])
                selected["prompt_control"].append(prompt)
                active_turn_capabilities.add("prompt_control")
                if prompt.get("workspace_id") != wanted_workspace:
                    carried_workspace_by_capability["prompt_control"] = str(prompt["workspace_id"])
                    carried_runtime_by_capability["prompt_control"] = current_runtime

        missing_lineage = [
            capability_id
            for capability_id in ("session_context", "prompt_control")
            if _source_status(selected[capability_id]) != "live_verified"
        ]
        predecessor_rows: dict[
            str, dict[str, list[tuple[datetime, dict[str, Any]]]]
        ] = {}
        for row in rows:
            capability_id = str(row.get("capability_id") or "")
            row_runtime = str(row.get("runtime_sha256") or "")
            if (
                capability_id not in missing_lineage
                or (row_runtime == current_runtime and row.get("workspace_id") == wanted_workspace)
                or not session_row(row, capability_id)
            ):
                continue
            observed = observed_before_roundtrip(row)
            if observed is None:
                continue
            spec = next(
                item
                for item in capability_specs(host)
                if item.capability_id == capability_id
            )
            age_seconds = (current - observed).total_seconds()
            normally_fresh = bool(
                age_seconds >= -PROVENANCE_CLOCK_SKEW_SECONDS
                and (
                    spec.freshness_ttl_seconds is None
                    or age_seconds <= spec.freshness_ttl_seconds
                )
            )
            active_turn = bool(
                capability_id == "prompt_control"
                and prompt_belongs_to_active_turn(observed)
            )
            if capability_id == "prompt_control" and not active_turn:
                continue
            if not normally_fresh and not active_turn:
                continue
            predecessor_rows.setdefault(row_runtime, {}).setdefault(
                capability_id, []
            ).append((observed, row))

        # SessionStart lives for the native session; its current prompt can
        # legitimately come from a later install. Each fact must satisfy its
        # own provenance, workspace-chain and time checks above. Requiring all
        # missing facts to share one obsolete runtime couples unrelated clocks.
        for capability_id in missing_lineage:
            candidates = [(observed, row, runtime)
                          for runtime, by_capability in predecessor_rows.items()
                          for observed, row in by_capability.get(capability_id, [])]
            if candidates:
                observed, row, predecessor_runtime = max(candidates, key=lambda item: item[0])
                selected[capability_id].append(row)
                carried_runtime_by_capability[capability_id] = predecessor_runtime
                if row.get("workspace_id") != wanted_workspace:
                    carried_workspace_by_capability[capability_id] = str(row["workspace_id"])
                spec = next(
                    item
                    for item in capability_specs(host)
                    if item.capability_id == capability_id
                )
                if (
                    spec.freshness_ttl_seconds is not None
                    and (current - observed).total_seconds()
                    > spec.freshness_ttl_seconds
                ):
                    active_turn_capabilities.add(capability_id)

    capabilities: dict[str, dict[str, Any]] = {}
    latest_values: list[str] = []
    for spec in capability_specs(host):
        matches = selected[spec.capability_id]
        latest = max((str(row.get("at") or "") for row in matches), default="") or None
        if latest:
            latest_values.append(latest)
        capabilities[spec.capability_id] = {
            "status": _source_status(matches),
            "live_observations": sum(
                1
                for row in matches
                if row.get("source") in {"live_host_hook", "managed_l3"}
            ),
            "synthetic_observations": sum(
                1 for row in matches if row.get("source") == "synthetic_smoke"
            ),
            "last_observed_at": latest,
            "live_scope": spec.live_scope,
            "stale_observations": stale[spec.capability_id],
            "freshness_policy": (
                "session_lifetime"
                if spec.freshness_ttl_seconds is None
                else "activity_ttl"
            ),
            "freshness_ttl_seconds": spec.freshness_ttl_seconds,
            "required_for_interactive": bool(
                spec.interactive_gate
                and (not spec.approval_gate or approval_required)
            ),
            "runtime_binding": (
                "verified_workspace_continuity"
                if spec.capability_id in carried_workspace_by_capability
                else "verified_hot_rebind"
                if spec.capability_id in carried_runtime_by_capability
                else "current_runtime_active_turn"
                if spec.capability_id in active_turn_capabilities
                else "current_runtime"
            ),
            "carried_from_runtime_sha256": carried_runtime_by_capability.get(
                spec.capability_id
            ),
            "carried_from_workspace_id": carried_workspace_by_capability.get(spec.capability_id),
            "active_turn_continuity": bool(
                spec.capability_id in active_turn_capabilities
            ),
        }

    interactive_specs = [
        spec
        for spec in capability_specs(host)
        if spec.interactive_gate and (not spec.approval_gate or approval_required)
    ]
    interactive_states = [
        capabilities[spec.capability_id]["status"]
        for spec in interactive_specs
    ]
    if interactive_states and all(value == "live_verified" for value in interactive_states):
        interactive_status = "live_verified"
        status = "interactive_ready"
    elif any(value == "live_verified" for value in interactive_states):
        interactive_status = "partial"
        status = "interactive_partial"
    elif interactive_states and all(value == "synthetic_only" for value in interactive_states):
        interactive_status = "synthetic_only"
        status = "synthetic_only"
    else:
        interactive_status = "unobserved"
        status = "unobserved"

    supervision_ids = ("tool_guard", "tool_result", "turn_reconcile")
    supervision_states = [capabilities[name]["status"] for name in supervision_ids]
    active_turn_supervised = bool(
        roundtrip is not None
        and capabilities["tool_guard"]["status"] == "live_verified"
        and capabilities["tool_result"]["status"] == "live_verified"
    )
    supervision_status = (
        "live_verified"
        if all(value == "live_verified" for value in supervision_states)
        or active_turn_supervised
        else "partial"
        if any(value == "live_verified" for value in supervision_states)
        else "synthetic_only"
        if all(value == "synthetic_only" for value in supervision_states)
        else "unobserved"
    )
    return {
        "schema": CONTRACT_SCHEMA,
        "version": CONTRACT_VERSION,
        "provider": host,
        "status": status,
        "telemetry_authority": "integrity_only_not_permission_authority",
        "interactive_status": interactive_status,
        "observation_index": {
            key: value for key, value in index_projection.items() if key != "checkpoint"
        },
        "approval_required": bool(approval_required),
        "approval_status": (
            capabilities["host_approval"]["status"]
            if host == "codex"
            else "not_supported"
        ),
        "supervision_status": supervision_status,
        "session_id_present": bool(session_id),
        "workspace_bound": bool(wanted_workspace),
        "observation_count": sum(len(value) for value in selected.values()),
        "runtime_sha256": current_runtime,
        "stale_runtime_rows": stale_runtime_rows,
        "carried_runtime_rows": len(carried_runtime_by_capability),
        "invalid_rows": invalid,
        "latest_observed_at": max(latest_values, default=None),
        "runtime_continuity": {
            "status": "verified" if roundtrip is not None else "unverified",
            "call_id_sha256": (
                str(roundtrip["call_id_sha256"]) if roundtrip is not None else None
            ),
            "started_at": (
                roundtrip["started_at"].isoformat() if roundtrip is not None else None
            ),
            "completed_at": (
                roundtrip["completed_at"].isoformat() if roundtrip is not None else None
            ),
            "carried_capabilities": sorted(carried_runtime_by_capability),
            "active_turn_capabilities": sorted(active_turn_capabilities),
            "authority": "telemetry_integrity_only_not_permission_authority",
        },
        "workspace_continuity": {
            "status": workspace_continuity_status,
            "carried_capabilities": sorted(carried_workspace_by_capability),
            "authority_transferred": False,
        },
        "capabilities": capabilities,
    }

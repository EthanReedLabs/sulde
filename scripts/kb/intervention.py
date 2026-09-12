#!/usr/bin/env python3
"""Durable external-effect attempts and human interventions for Sulde.

This module is deliberately independent from the intent contract.  The intent
contract answers whether an action is authorized; this log records the exact
prepare/dispatch boundary, what is known about a released external effect, and
whether a human must adjudicate it.  Its JSONL file is authoritative and the
adjacent JSON file is only a replayable projection.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterator
import unicodedata
from urllib.parse import SplitResult, urlsplit, urlunsplit

from file_lock import lock_exclusive_nonblocking, unlock
from sulde_effects import DEFAULT_EFFECT_ROUTER

contract_identity_digest = runpy.run_path(
    str(Path(__file__).resolve().with_name("sulde_paths.py"))
)["contract_identity_digest"]


EVENT_SCHEMA = "sulde-intervention-event-v2"
LEGACY_EVENT_SCHEMA = "sulde-intervention-event-v1"
PROJECTION_SCHEMA = "sulde-intervention-projection-v1"
ARCHIVE_SCHEMA = "sulde-intervention-archive-v1"
ATTEMPT_STATES = {
    "authorized",
    "dispatched",
    "accepted",
    "verifying",
    "system_verified",
    "human_attested_success",
    "confirmed_failed",
    "unknown",
}
INTERVENTION_STATUSES = {"open", "acknowledged", "resolved"}
HUMAN_DECISIONS = {
    "human_attested_success",
    "confirmed_failed",
    "reprobe_authorized",
    "retry_authorized",
    "abort",
}
RESOLUTION_DECISIONS = HUMAN_DECISIONS | {
    "system_verified",
    "system_compensated",
}
ACTIVE_ATTEMPT_STATES = {"dispatched", "accepted", "verifying", "unknown"}
MATERIAL_EFFECTS = {"local_write", "external_write", "destructive", "unknown"}
VERIFICATION_KINDS = {"unsupported", "existence", "content", "relation"}
LEGACY_READ_DEBT_ACTOR = "system-read-only-reconciler"
LEGACY_READ_DEBT_EVIDENCE = (
    "system reconciliation: the recorded operation was read-only, so no "
    "material external effect exists to adjudicate"
)
LEGACY_READ_CLASSIFICATION_ACTOR = "system-rollout-read-classifier"
LEGACY_READ_CLASSIFICATION_EVIDENCE = "codex-rollout-figma-read-v1"
LEGACY_GIT_CONTROL_DEBT_ACTOR = "system-git-control-migrator"
LEGACY_GIT_CONTROL_DEBT_EVIDENCE = (
    "system migration: Git execution left Guardian control at policy version "
    "guardian-git-decontrol-v1; historical outcome remains unasserted"
)

_TRANSITIONS = {
    "authorized": {"dispatched", "unknown"},
    "dispatched": {"accepted", "unknown"},
    "accepted": {"verifying", "unknown"},
    "verifying": {"system_verified", "unknown"},
    "unknown": {
        "system_verified",
        "human_attested_success",
        "confirmed_failed",
    },
    "system_verified": set(),
    "human_attested_success": set(),
    "confirmed_failed": set(),
}
_ID_RE = re.compile(r"^(?:att|int)-[0-9a-f]{24}$")
_BATCH_ID_RE = re.compile(r"^bat-[0-9a-f]{24}$")
_RESOURCE_KEY_VERSION = "v2"
_RESOURCE_KINDS = ("opaque", "path", "uri", "mcp", "git")
_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*$")
_URI_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_URI_DEFAULT_PORTS = {
    "ftp": 21,
    "http": 80,
    "https": 443,
    "ws": 80,
    "wss": 443,
}
_MCP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_GIT_OID_RE = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")


class InterventionError(RuntimeError):
    """A durable effect/intervention transition is invalid or unavailable."""


def effect_operation_fingerprint(
    *,
    provider: str,
    capability: str,
    target: str,
    resource_key: str = "",
    effect: str,
    arguments_digest: str,
) -> str:
    """Seal the raw dispatch and its typed resource without one session."""
    source = "\0".join(
        (
            provider,
            capability,
            target,
            resource_key,
            effect,
            arguments_digest,
        )
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _legacy_effect_operation_fingerprint(
    *,
    provider: str,
    capability: str,
    target: str,
    resource_key: str,
    effect: str,
    arguments_digest: str,
) -> str:
    """Frozen repair3 operation derivation for read-only legacy replay."""
    source = "\0".join(
        (provider, capability, resource_key or target, effect, arguments_digest)
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def _contract_stem(contract_path: Path) -> str:
    name = contract_path.name
    return name[:-5] if name.endswith(".json") else name


def event_store_path(contract_path: Path) -> Path:
    return contract_path.with_name(f"{_contract_stem(contract_path)}.interventions.jsonl")


def projection_path(contract_path: Path) -> Path:
    return contract_path.with_name(f"{_contract_stem(contract_path)}.interventions.json")


def contract_digest(contract_path: Path) -> str:
    return contract_identity_digest(contract_path)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as error:
        raise InterventionError(f"intervention value is not lossless JSON: {error}") from error


def _digest(prefix: str, *values: Any, length: int = 24) -> str:
    rendered = "\0".join(str(value or "") for value in values)
    return f"{prefix}-" + hashlib.sha256(rendered.encode("utf-8", errors="replace")).hexdigest()[:length]


def _target_digest(target: Any) -> str:
    return hashlib.sha256(str(target or "").encode("utf-8", errors="replace")).hexdigest()


def _pending_path_filesystem_type(parent: Path) -> str:
    """Return a read-only, device-bound filesystem type or fail closed."""
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["/sbin/mount"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2,
            )
            device = int(parent.stat().st_dev)
            matches: list[tuple[int, str]] = []
            for line in completed.stdout.splitlines():
                match = re.match(r"^.+ on (.+) \(([^,()]+)(?:,|\))", line)
                if not match:
                    continue
                mount_text = re.sub(
                    r"\\([0-7]{3})",
                    lambda value: chr(int(value.group(1), 8)),
                    match.group(1),
                )
                mount_point = Path(mount_text)
                try:
                    if int(mount_point.stat().st_dev) == device:
                        matches.append((len(mount_text), match.group(2).lower()))
                except OSError:
                    continue
            if matches:
                return sorted(matches)[-1][1]
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    elif sys.platform.startswith("linux"):
        try:
            completed = subprocess.run(
                ["stat", "-f", "-c", "%T", str(parent)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2,
            )
            filesystem_type = completed.stdout.strip().lower()
            if filesystem_type:
                return filesystem_type
        except (OSError, subprocess.SubprocessError):
            pass
    raise InterventionError(
        "pending path parent filesystem type cannot be proved"
    )


def _pending_path_semantics(parent: Path) -> tuple[str, str]:
    """Prove pending-name semantics from the actual parent filesystem."""
    try:
        status = parent.stat()
        probe = parent
        case_semantics = ""
        while int(probe.stat().st_dev) == int(status.st_dev):
            alternate_name = probe.name.swapcase()
            if alternate_name and alternate_name != probe.name:
                exact_entries = {entry.name for entry in probe.parent.iterdir()}
                if alternate_name not in exact_entries:
                    alternate = probe.with_name(alternate_name)
                    try:
                        alternate_status = alternate.stat()
                    except FileNotFoundError:
                        case_semantics = "case-sensitive"
                    else:
                        probe_status = probe.stat()
                        if (
                            int(alternate_status.st_dev),
                            int(alternate_status.st_ino),
                        ) == (int(probe_status.st_dev), int(probe_status.st_ino)):
                            case_semantics = "case-insensitive"
                        else:
                            raise InterventionError(
                                "pending path parent case semantics are ambiguous"
                            )
                    break
            if probe == probe.parent:
                break
            probe = probe.parent
        if not case_semantics:
            raise InterventionError(
                "pending path parent does not expose a case-semantics probe"
            )
    except InterventionError:
        raise
    except (OSError, RuntimeError) as error:
        raise InterventionError(
            "pending path parent filesystem semantics cannot be proved"
        ) from error

    filesystem_type = _pending_path_filesystem_type(parent)
    if filesystem_type in {"apfs", "hfs", "hfs+", "hfsplus"}:
        unicode_semantics = "unicode-normalized"
    elif filesystem_type in {
        "ext2",
        "ext3",
        "ext4",
        "ext2/ext3",
        "ext2/ext3/ext4",
        "tmpfs",
        "ufs",
        "xfs",
    }:
        unicode_semantics = "unicode-exact"
    else:
        raise InterventionError(
            "pending path Unicode namespace semantics cannot be proved"
        )
    return case_semantics, unicode_semantics


def _canonical_pending_names(parent: Path, missing: list[str]) -> tuple[list[str], str, str]:
    case_semantics, unicode_semantics = _pending_path_semantics(parent)
    if case_semantics not in {"case-sensitive", "case-insensitive"}:
        raise InterventionError("pending path case semantics are not authoritative")
    if unicode_semantics not in {"unicode-exact", "unicode-normalized"}:
        raise InterventionError("pending path Unicode semantics are not authoritative")
    names = list(missing)
    if unicode_semantics == "unicode-normalized":
        names = [unicodedata.normalize("NFC", name) for name in names]
    if case_semantics == "case-insensitive":
        names = [name.casefold() for name in names]
    return names, case_semantics, unicode_semantics


def _require_identity_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise InterventionError(f"{label} must be a non-empty exact string")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise InterventionError(f"{label} contains a control character")
    return value


def _normalize_percent_encoding(value: str, *, label: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "%":
            output.append(character)
            index += 1
            continue
        escape = value[index + 1 : index + 3]
        if len(escape) != 2 or not re.fullmatch(r"[0-9A-Fa-f]{2}", escape):
            raise InterventionError(f"{label} contains an invalid percent escape")
        decoded = chr(int(escape, 16))
        output.append(decoded if decoded in _URI_UNRESERVED else f"%{escape.upper()}")
        index += 3
    return "".join(output)


def _remove_uri_dot_segments(path: str) -> str:
    """Apply RFC 3986 section 5.2.4 without collapsing repeated slashes."""
    remaining = path
    output = ""
    while remaining:
        if remaining.startswith("../"):
            remaining = remaining[3:]
        elif remaining.startswith("./"):
            remaining = remaining[2:]
        elif remaining.startswith("/./"):
            remaining = "/" + remaining[3:]
        elif remaining == "/.":
            remaining = "/"
        elif remaining.startswith("/../"):
            remaining = "/" + remaining[4:]
            output = output.rsplit("/", 1)[0]
        elif remaining == "/..":
            remaining = "/"
            output = output.rsplit("/", 1)[0]
        elif remaining in {".", ".."}:
            remaining = ""
        else:
            start = 1 if remaining.startswith("/") else 0
            slash = remaining.find("/", start)
            if slash < 0:
                output += remaining
                remaining = ""
            else:
                output += remaining[:slash]
                remaining = remaining[slash:]
    return output


def _canonical_uri_v1(value: str) -> str:
    """Frozen validation semantics for immutable unversioned URI keys."""
    raw = _require_identity_text(value, "URI resource identifier")
    if any(character.isspace() for character in raw) or "\\" in raw:
        raise InterventionError("URI resource identifier contains an unsafe character")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise InterventionError(f"URI resource identifier is invalid: {error}") from error
    if not parsed.scheme or not _URI_SCHEME_RE.fullmatch(parsed.scheme):
        raise InterventionError("URI resource identifier requires a valid scheme")
    scheme = parsed.scheme.lower()
    if parsed.netloc and parsed.hostname is None:
        raise InterventionError("URI authority requires a host")
    host = parsed.hostname or ""
    if host:
        try:
            host = ipaddress.ip_address(host).compressed
        except ValueError:
            try:
                host = host.encode("idna").decode("ascii").lower()
            except UnicodeError as error:
                raise InterventionError("URI host cannot be normalized losslessly") from error
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0]
        userinfo = _normalize_percent_encoding(userinfo, label="URI userinfo") + "@"
    if ":" in host:
        host = f"[{host}]"
    port_text = ""
    if port is not None and port != _URI_DEFAULT_PORTS.get(scheme):
        port_text = f":{port}"
    authority = f"{userinfo}{host}{port_text}"
    if parsed.netloc and not authority:
        raise InterventionError("URI authority cannot be normalized")
    if scheme in {"http", "https", "ws", "wss", "ftp"} and not host:
        raise InterventionError(f"{scheme} URI requires a host")
    path = _normalize_percent_encoding(parsed.path, label="URI path")
    path = _remove_uri_dot_segments(path)
    if not path and authority and scheme in _URI_DEFAULT_PORTS:
        path = "/"
    query = _normalize_percent_encoding(parsed.query, label="URI query")
    before_fragment = raw.split("#", 1)[0]
    query_present = "?" in before_fragment
    # Fragments are intentionally excluded: they are client-side selectors and
    # must not let two spellings evade debt on the same remotely mutated URI.
    normalized = urlunsplit(SplitResult(scheme, authority, path, query, ""))
    if query_present and not query and not normalized.endswith("?"):
        normalized += "?"
    return normalized


def _canonical_uri(value: str) -> str:
    raw = _require_identity_text(value, "URI resource identifier")
    if any(character.isspace() for character in raw) or "\\" in raw:
        raise InterventionError("URI resource identifier contains an unsafe character")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as error:
        raise InterventionError(f"URI resource identifier is invalid: {error}") from error
    if not parsed.scheme or not _URI_SCHEME_RE.fullmatch(parsed.scheme):
        raise InterventionError("URI resource identifier requires a valid scheme")
    scheme = parsed.scheme.lower()
    if parsed.netloc and parsed.hostname is None:
        raise InterventionError("URI authority requires a host")
    host = parsed.hostname or ""
    if host:
        try:
            host = ipaddress.ip_address(host).compressed
        except ValueError:
            host = _normalize_percent_encoding(host, label="URI host")
            if host.endswith("..") or ".." in host:
                raise InterventionError("URI host contains an empty reg-name label")
            host = host[:-1] if host.endswith(".") else host
            if not host:
                raise InterventionError("URI authority requires a host")
            try:
                host = host.encode("idna").decode("ascii").lower()
            except UnicodeError as error:
                raise InterventionError("URI host cannot be normalized losslessly") from error
    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0]
        userinfo = _normalize_percent_encoding(userinfo, label="URI userinfo") + "@"
    if ":" in host:
        host = f"[{host}]"
    port_text = ""
    if port is not None and port != _URI_DEFAULT_PORTS.get(scheme):
        port_text = f":{port}"
    authority = f"{userinfo}{host}{port_text}"
    if parsed.netloc and not authority:
        raise InterventionError("URI authority cannot be normalized")
    if scheme in {"http", "https", "ws", "wss", "ftp"} and not host:
        raise InterventionError(f"{scheme} URI requires a host")
    path = _normalize_percent_encoding(parsed.path, label="URI path")
    path = _remove_uri_dot_segments(path)
    if not path and authority and scheme in _URI_DEFAULT_PORTS:
        path = "/"
    query = _normalize_percent_encoding(parsed.query, label="URI query")
    before_fragment = raw.split("#", 1)[0]
    query_present = "?" in before_fragment
    normalized = urlunsplit(SplitResult(scheme, authority, path, query, ""))
    if query_present and not query and not normalized.endswith("?"):
        normalized += "?"
    return normalized


def _structured_identity(target: Any, labels: tuple[str, ...], kind: str) -> tuple[str, ...]:
    if isinstance(target, dict):
        values = tuple(target.get(label) for label in labels)
    elif isinstance(target, (tuple, list)) and len(target) == len(labels):
        values = tuple(target)
    else:
        raise InterventionError(
            f"{kind} resource identity requires {', '.join(labels)}"
        )
    return tuple(
        _require_identity_text(value, f"{kind} {label}")
        for label, value in zip(labels, values)
    )


def _canonical_mcp(target: Any) -> str:
    server, resource_kind, identifier = _structured_identity(
        target,
        ("server", "resource_kind", "identifier"),
        "MCP",
    )
    if not _MCP_NAME_RE.fullmatch(server) or not _MCP_NAME_RE.fullmatch(resource_kind):
        raise InterventionError("MCP server and resource kind must be explicit names")
    # Guardian authorization already treats '-' and '_' server spellings as
    # aliases.  Folding them here prevents that accepted alias from evading an
    # existing resource debt; identifiers remain byte-exact.
    server = server.lower().replace("_", "-")
    resource_kind = resource_kind.lower().replace("_", "-")
    return _canonical([server, resource_kind, identifier])


def _canonical_git_ref(remote: str, ref: str, *, base: Path | str | None = None) -> tuple[str, str]:
    clean_remote = _require_identity_text(remote, "Git remote")
    clean_ref = _require_identity_text(ref, "Git ref")
    if not clean_ref.startswith("refs/") or any(
        marker in clean_ref for marker in ("..", "@{", "\\", " ", "~", "^", ":", "?", "*", "[")
    ) or clean_ref.endswith(("/", ".", ".lock")):
        raise InterventionError("Git resource identity requires one exact full ref")
    if "://" in clean_remote:
        remote_identity = f"{_RESOURCE_KEY_VERSION}:uri:" + _canonical_uri(clean_remote)
    elif re.fullmatch(r"[0-9a-fA-F]{64}", clean_remote):
        remote_identity = "digest:" + clean_remote.lower()
    elif clean_remote.startswith(("/", "./", "../", "~")):
        remote_identity = canonical_resource_key(clean_remote, kind="path", base=base)
    else:
        # SCP-like remotes and logical remote names have no universally safe
        # equivalence rule.  Preserve them in an explicit opaque sub-namespace.
        remote_identity = f"{_RESOURCE_KEY_VERSION}:opaque:" + clean_remote
    return remote_identity, clean_ref


def git_ref_verification_digest(
    *,
    remote: str,
    ref: str,
    oid: str,
    base: Path | str | None = None,
) -> str:
    """Seal the independently observed Git remote/ref/OID postcondition."""
    remote_identity, clean_ref = _canonical_git_ref(remote, ref, base=base)
    clean_oid = _require_identity_text(oid, "Git object ID")
    if not _GIT_OID_RE.fullmatch(clean_oid):
        raise InterventionError("Git object ID must be one full SHA-1 or SHA-256 OID")
    return hashlib.sha256(
        _canonical(
            {"remote": remote_identity, "ref": clean_ref, "oid": clean_oid.lower()}
        ).encode("utf-8")
    ).hexdigest()


def _canonical_path_identity(
    target: Any,
    *,
    base: Path | str | None,
) -> str:
    rendered = str(target) if target is not None else ""
    if not rendered or "\x00" in rendered:
        raise InterventionError("path resource identity requires one exact path")
    candidate = Path(rendered).expanduser()
    if not candidate.is_absolute():
        if base is None or not str(base):
            raise InterventionError(
                "relative path resource identity requires an explicit workspace/base"
            )
        root = Path(base).expanduser()
        try:
            root = root.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise InterventionError("path resource base cannot be safely resolved") from error
        if not root.is_dir():
            raise InterventionError("path resource base must be an existing directory")
        candidate = root / candidate
    try:
        normalized = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise InterventionError("path resource cannot be safely resolved") from error

    try:
        status = normalized.stat()
    except FileNotFoundError:
        missing: list[str] = []
        parent = normalized
        while True:
            if parent == parent.parent and not parent.exists():
                raise InterventionError("path resource has no resolvable parent directory")
            try:
                parent_status = parent.stat()
                break
            except FileNotFoundError:
                if parent.name in {"", ".", ".."}:
                    raise InterventionError("path resource has an unsafe unresolved component")
                missing.insert(0, parent.name)
                parent = parent.parent
            except (OSError, RuntimeError) as error:
                raise InterventionError("path resource parent cannot be safely resolved") from error
        if not parent.is_dir():
            raise InterventionError("path resource parent is not a directory")
        canonical_missing, case_semantics, unicode_semantics = (
            _canonical_pending_names(parent, missing)
        )
        return _canonical(
            [
                "pending",
                int(parent_status.st_dev),
                int(parent_status.st_ino),
                case_semantics,
                unicode_semantics,
                canonical_missing,
            ]
        )
    except (OSError, RuntimeError) as error:
        raise InterventionError("path resource cannot be safely identified") from error
    return _canonical(["object", int(status.st_dev), int(status.st_ino)])


def _canonical_path_v1(
    target: Any,
    *,
    base: Path | str | None,
) -> str:
    """Frozen v1 path derivation used only for migration equivalence proofs."""
    rendered = str(target) if target is not None else ""
    if not rendered or "\x00" in rendered:
        raise InterventionError("legacy path identity requires one exact path")
    candidate = Path(rendered).expanduser()
    if not candidate.is_absolute():
        if base is None or not str(base):
            raise InterventionError(
                "relative legacy path identity requires an explicit workspace/base"
            )
        root = Path(base).expanduser()
        try:
            root = root.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise InterventionError(
                "legacy path resource base cannot be safely resolved"
            ) from error
        if not root.is_dir():
            raise InterventionError(
                "legacy path resource base must be an existing directory"
            )
        candidate = root / candidate
    try:
        normalized = candidate.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise InterventionError("legacy path resource cannot be safely resolved") from error
    return "path:" + os.path.normcase(str(normalized))


def canonical_resource_key(
    target: Any,
    *,
    kind: str = "opaque",
    base: Path | str | None = None,
) -> str:
    """Return one typed resource identity while retaining the raw target separately.

    Paths resolve local aliases, generic URIs apply only syntax-level proven
    equivalences, and MCP/Git identities require structured namespace fields.
    Unknown provider-specific semantics remain in the explicit ``opaque`` kind.
    """
    clean_kind = str(kind or "opaque").strip().lower()
    if clean_kind == "mcp":
        return f"{_RESOURCE_KEY_VERSION}:mcp:" + _canonical_mcp(target)
    if clean_kind == "git":
        if isinstance(target, dict):
            remote = target.get("remote")
            ref = target.get("ref")
            oid = target.get("oid")
        elif isinstance(target, (tuple, list)) and len(target) in {2, 3}:
            remote, ref, *oid_values = target
            oid = oid_values[0] if oid_values else None
        else:
            raise InterventionError("Git resource identity requires remote and ref")
        remote_identity, clean_ref = _canonical_git_ref(remote, ref, base=base)
        if oid is not None:
            clean_oid = _require_identity_text(oid, "Git object ID")
            if not _GIT_OID_RE.fullmatch(clean_oid):
                raise InterventionError("Git object ID must be one full SHA-1 or SHA-256 OID")
        # OID is deliberately not part of the mutable resource identity.  It is
        # a postcondition sealed by git_ref_verification_digest; including it
        # here would let a second push to the same ref evade unknown debt.
        return f"{_RESOURCE_KEY_VERSION}:git:" + _canonical(
            [remote_identity, clean_ref]
        )
    rendered = str(target or "").strip()
    if clean_kind == "uri":
        return f"{_RESOURCE_KEY_VERSION}:uri:" + _canonical_uri(rendered)
    if not rendered:
        return ""
    if clean_kind == "opaque":
        return f"{_RESOURCE_KEY_VERSION}:opaque:{rendered}"
    if clean_kind != "path":
        raise InterventionError(f"unsupported resource identity kind: {kind}")
    return f"{_RESOURCE_KEY_VERSION}:path:" + _canonical_path_identity(
        target, base=base
    )


def _resource_digest(resource_key: str) -> str:
    return _target_digest(resource_key) if resource_key else ""


def _structured_key_values(resource_key: str, prefix: str, count: int) -> tuple[str, ...]:
    try:
        values = json.loads(resource_key[len(prefix) :])
    except (json.JSONDecodeError, TypeError) as error:
        raise InterventionError("effect resource key is not canonical JSON") from error
    if (
        not isinstance(values, list)
        or len(values) != count
        or not all(isinstance(value, str) and value for value in values)
    ):
        raise InterventionError("effect resource key has an invalid structured identity")
    return tuple(values)


def _resource_key_parts(
    resource_key: str,
    *,
    allow_legacy: bool,
) -> tuple[str, str, str, str]:
    if resource_key != resource_key.strip() or not resource_key:
        raise InterventionError("effect resource key must be one exact non-empty string")
    for kind in _RESOURCE_KINDS:
        prefix = f"{_RESOURCE_KEY_VERSION}:{kind}:"
        if resource_key.startswith(prefix):
            return _RESOURCE_KEY_VERSION, kind, resource_key[len(prefix) :], prefix
    version = re.match(r"^(v[0-9]+):", resource_key)
    if version:
        raise InterventionError(
            f"effect resource key version is unknown: {version.group(1)}"
        )
    if allow_legacy:
        for kind in _RESOURCE_KINDS:
            prefix = f"{kind}:"
            if resource_key.startswith(prefix):
                return "v1", kind, resource_key[len(prefix) :], prefix
    raise InterventionError("effect resource key requires the current explicit version")


def _validate_path_payload(payload: str) -> None:
    try:
        values = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as error:
        raise InterventionError("path resource key is not canonical JSON") from error
    if _canonical(values) != payload or not isinstance(values, list):
        raise InterventionError("path resource key is not canonical")
    if (
        len(values) == 3
        and values[0] == "object"
        and all(isinstance(value, int) and value >= 0 for value in values[1:])
    ):
        return
    if (
        len(values) == 6
        and values[0] == "pending"
        and all(isinstance(value, int) and value >= 0 for value in values[1:3])
        and values[3] in {"case-sensitive", "case-insensitive"}
        and values[4] in {"unicode-exact", "unicode-normalized"}
        and isinstance(values[5], list)
        and values[5]
        and all(
            isinstance(value, str)
            and value not in {"", ".", ".."}
            and "/" not in value
            and "\x00" not in value
            for value in values[5]
        )
    ):
        return
    raise InterventionError("path resource key has an invalid canonical identity")


def _validate_v1_resource_key(kind: str, payload: str, prefix: str) -> None:
    """Frozen read-only validation; v1 keys are never regenerated as v2."""
    if not payload:
        raise InterventionError("legacy resource key has an empty identity")
    if kind == "opaque":
        _require_identity_text(payload, "legacy opaque resource identifier")
    elif kind == "path":
        if payload.startswith("["):
            try:
                json.loads(payload)
            except json.JSONDecodeError as error:
                raise InterventionError("legacy path resource key is invalid") from error
        elif not Path(payload).is_absolute() or os.path.normpath(payload) != payload:
            raise InterventionError("legacy path resource key is not canonical")
    elif kind == "uri":
        if prefix + _canonical_uri_v1(payload) != prefix + payload:
            raise InterventionError("legacy URI resource key is not canonical")
    elif kind == "mcp":
        server, resource_kind, identifier = _structured_key_values(
            prefix + payload, prefix, 3
        )
        if prefix + _canonical_mcp((server, resource_kind, identifier)) != prefix + payload:
            raise InterventionError("legacy MCP resource key is not canonical")
    elif kind == "git":
        remote_identity, ref = _structured_key_values(prefix + payload, prefix, 2)
        if remote_identity.startswith("digest:"):
            if not re.fullmatch(r"digest:[0-9a-f]{64}", remote_identity):
                raise InterventionError("legacy Git remote digest identity is invalid")
        else:
            _validate_resource_key(remote_identity, allow_legacy=True)
        _, expected_ref = _canonical_git_ref("x", ref)
        if expected_ref != ref:
            raise InterventionError("legacy Git resource key is not canonical")


def _validate_resource_key(
    resource_key: str,
    *,
    allow_legacy: bool = False,
    target: str | None = None,
    base: Path | str | None = None,
    external: bool = False,
) -> tuple[str, str]:
    version, kind, payload, prefix = _resource_key_parts(
        resource_key, allow_legacy=allow_legacy
    )
    if not payload:
        raise InterventionError("effect resource key must not have an empty identity")
    if version == "v1":
        _validate_v1_resource_key(kind, payload, prefix)
        return version, kind
    if kind == "opaque":
        _require_identity_text(payload, "opaque resource identifier")
    elif kind == "path":
        _validate_path_payload(payload)
        if external:
            expected = canonical_resource_key(target, kind="path", base=base)
            if expected != resource_key:
                raise InterventionError(
                    "path resource key is not canonical for the supplied target/base"
                )
    elif kind == "uri":
        if canonical_resource_key(payload, kind="uri") != resource_key:
            raise InterventionError("URI resource key is not canonical")
    elif kind == "mcp":
        server, resource_kind, identifier = _structured_key_values(
            resource_key, prefix, 3
        )
        if canonical_resource_key(
            (server, resource_kind, identifier), kind="mcp"
        ) != resource_key:
            raise InterventionError("MCP resource key is not canonical")
    elif kind == "git":
        remote_identity, ref = _structured_key_values(resource_key, prefix, 2)
        if remote_identity.startswith("digest:"):
            if not re.fullmatch(r"digest:[0-9a-f]{64}", remote_identity):
                raise InterventionError("Git remote digest identity is invalid")
        else:
            _validate_resource_key(remote_identity, allow_legacy=False)
        _, expected_ref = _canonical_git_ref("x", ref)
        if expected_ref != ref:
            raise InterventionError("Git resource key is not canonical")
    return version, kind


def _exact_resource_context(
    resource_context: dict[str, Any] | None,
    required: tuple[str, ...],
    kind: str,
) -> dict[str, str]:
    if not isinstance(resource_context, dict) or set(resource_context) != set(required):
        raise InterventionError(
            f"{kind} resource identity requires exact context fields: "
            + ", ".join(required)
        )
    return {
        field: _require_identity_text(resource_context.get(field), f"{kind} {field}")
        for field in required
    }


def _validate_external_resource_key(
    resource_key: str,
    *,
    target: str,
    base: Path | str | None,
    resource_context: dict[str, Any] | None,
) -> tuple[str, dict[str, str], str]:
    """Re-derive one caller-supplied v2 key from its complete live context."""
    version, kind = _validate_resource_key(resource_key, allow_legacy=False)
    if version != _RESOURCE_KEY_VERSION:
        raise InterventionError("external effect resource key requires the current version")
    normalized_context: dict[str, str] = {}
    relation_sha256 = ""
    if kind == "path":
        if resource_context:
            raise InterventionError("path resource identity does not accept extra context")
        expected = canonical_resource_key(target, kind="path", base=base)
    elif kind == "uri":
        if resource_context:
            raise InterventionError("URI resource identity does not accept extra context")
        expected = canonical_resource_key(target, kind="uri")
    elif kind == "mcp":
        normalized_context = _exact_resource_context(
            resource_context,
            ("server", "resource_kind", "identifier"),
            "MCP",
        )
        if normalized_context["identifier"] != target:
            raise InterventionError(
                "MCP resource context identifier must exactly equal the supplied target"
            )
        expected = canonical_resource_key(
            (
                normalized_context["server"],
                normalized_context["resource_kind"],
                normalized_context["identifier"],
            ),
            kind="mcp",
        )
    elif kind == "git":
        normalized_context = _exact_resource_context(
            resource_context,
            ("remote", "ref", "oid"),
            "Git",
        )
        expected = canonical_resource_key(
            {
                "remote": normalized_context["remote"],
                "ref": normalized_context["ref"],
            },
            kind="git",
            base=base,
        )
        relation_sha256 = git_ref_verification_digest(
            remote=normalized_context["remote"],
            ref=normalized_context["ref"],
            oid=normalized_context["oid"],
            base=base,
        )
    else:
        normalized_context = _exact_resource_context(
            resource_context,
            ("schema", "value"),
            "opaque",
        )
        if normalized_context["schema"] != "exact":
            raise InterventionError("opaque resource identity requires schema=exact")
        if normalized_context["value"] != target:
            raise InterventionError(
                "opaque resource context value must exactly equal the supplied target"
            )
        expected = canonical_resource_key(normalized_context["value"], kind="opaque")
    if expected != resource_key:
        raise InterventionError(
            f"{kind} resource key does not match the supplied target and complete context"
        )
    return kind, normalized_context, relation_sha256


def _event_resource_fields(
    *,
    target: str,
    resource_key: str,
    resource_base: Path | str | None,
    resource_context: dict[str, Any] | None,
) -> tuple[str, str, str, dict[str, str], str]:
    # No caller-supplied key means identity is genuinely absent.  Do not mint
    # an opaque pseudo-identity that later looks as authoritative as a typed
    # path/URI/MCP/Git key; keyless rows use the audited legacy fallback.
    selected = resource_key
    normalized_base = ""
    normalized_context: dict[str, str] = {}
    relation_sha256 = ""
    if selected:
        kind, normalized_context, relation_sha256 = _validate_external_resource_key(
            selected,
            target=target,
            base=resource_base,
            resource_context=resource_context,
        )
        if kind == "path":
            if resource_base:
                try:
                    normalized_base = str(Path(resource_base).expanduser().resolve(strict=True))
                except (OSError, RuntimeError) as error:
                    raise InterventionError(
                        "path resource base cannot be safely resolved"
                    ) from error
        elif resource_base:
            raise InterventionError("only path resources may carry a resolution base")
    elif resource_context:
        raise InterventionError("resource context requires one explicit typed resource key")
    return (
        selected,
        _resource_digest(selected),
        normalized_base,
        normalized_context,
        relation_sha256,
    )


def _stored_path_event_fields(
    *,
    target: str,
    resource_key: str,
    resource_base: Path | str | None,
    resource_context: dict[str, Any] | None,
) -> tuple[str, str, str, dict[str, str], str]:
    """Validate one already-appended path identity without consulting its inode.

    A v2 path key identifies the object that existed when the effect was
    dispatched. Re-resolving that key while replaying the immutable event log
    turns a legitimate atomic replacement into historical tampering. New
    events still pass through ``_event_resource_fields`` before append; replay
    instead checks the frozen key/digest and every stable retained input.
    """
    _version, kind = _validate_resource_key(resource_key, allow_legacy=False)
    if kind != "path":
        raise InterventionError("stored path event requires a path resource key")
    if resource_context:
        raise InterventionError("path resource identity does not accept extra context")
    rendered = str(target or "")
    if not rendered or "\x00" in rendered:
        raise InterventionError("path resource identity requires one exact path")
    candidate = Path(rendered).expanduser()
    normalized_base = ""
    if resource_base:
        try:
            root = Path(resource_base).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise InterventionError(
                "path resource base cannot be safely resolved"
            ) from error
        if not root.is_dir():
            raise InterventionError("path resource base must be an existing directory")
        normalized_base = str(root)
    elif not candidate.is_absolute():
        raise InterventionError(
            "relative path resource identity requires an explicit workspace/base"
        )
    return resource_key, _resource_digest(resource_key), normalized_base, {}, ""


def _legacy_git_key(target: Any, *, base: Path | str | None = None) -> str:
    rendered = str(target or "")
    match = re.fullmatch(r"git-ref:([0-9a-fA-F]{64}):(refs/.+)", rendered)
    if not match:
        return ""
    try:
        return canonical_resource_key(
            {"remote": match.group(1), "ref": match.group(2)},
            kind="git",
            base=base,
        )
    except InterventionError:
        return ""


def _legacy_mcp_matches(attempt: dict[str, Any], selected: str) -> bool:
    try:
        _, kind, _payload, prefix = _resource_key_parts(
            selected, allow_legacy=False
        )
        if kind != "mcp":
            return False
        server, _resource_kind, identifier = _structured_key_values(
            selected, prefix, 3
        )
    except InterventionError:
        return False
    capability = str(attempt.get("capability") or "")
    parts = capability.split(":", 2)
    if len(parts) != 3 or parts[0] != "mcp":
        return False
    legacy_server = parts[1].lower().replace("_", "-")
    # Old attempts did not retain a resource kind.  Same server + exact
    # identifier is therefore intentionally conservative across kinds.
    return legacy_server == server and str(attempt.get("target") or "") == identifier


def _legacy_keyless_resource_domain(attempt: dict[str, Any]) -> str:
    """Recover only a capability domain sealed by a legacy keyless row.

    Legacy Codex Apps attempts retained the transport-shaped capability even
    when the Figma target and resource key were empty.  That exact capability
    proves the operation could only affect Figma, but it does not identify a
    Figma file or node.  Keep the allow-list deliberately narrow: a guessed
    MCP server or verb must never turn missing resource identity into proof of
    a cross-domain relationship.
    """
    capability = str(attempt.get("capability") or "")
    if capability in {
        "mcp:codex_apps:figma__use_figma",
        "mcp:figma:use_figma",
    }:
        return "figma"
    return ""


def _unresolved_figma_attempt_identity(attempt: dict[str, Any]) -> bool:
    """Recognize only legacy-empty or the exact synthetic unresolved target."""
    target = str(attempt.get("target") or "")
    resource_key = str(attempt.get("resource_key") or "")
    if not target and not resource_key:
        return attempt.get("replay_authoritative") is not True
    unresolved_target = "[unresolved-figma-target]"
    if target != unresolved_target:
        return False
    try:
        kind, normalized_context, _relation = _validate_external_resource_key(
            resource_key,
            target=target,
            base=str(attempt.get("resource_base") or "") or None,
            resource_context=(
                attempt.get("resource_context")
                if isinstance(attempt.get("resource_context"), dict)
                else None
            ),
        )
    except (InterventionError, OSError, RuntimeError, ValueError):
        return False
    return bool(
        attempt.get("replay_authoritative") is True
        and kind == "mcp"
        and attempt.get("resource_sha256") == _resource_digest(resource_key)
        and normalized_context.get("server").lower().replace("_", "-") == "figma"
        and normalized_context.get("resource_kind").lower().replace("_", "-")
        == "use-figma"
        and normalized_context.get("identifier") == unresolved_target
    )


def _terminal_unresolved_figma_debt_allows_independent_operation(
    attempt: dict[str, Any],
    *,
    quarantined_attempt_ids: set[str],
    intent_id: str,
    intent_revision: int,
    capability: str,
    operation_fingerprint: str,
) -> bool:
    """Exclude one proved-new Figma operation from unresolved historical debt.

    Terminal abort does not settle the historical external effect.  It does,
    however, end that operation's retry chain. A different, sealed Figma
    operation may therefore start without treating the
    old target-less row (including its later synthetic placeholder encoding)
    as a wildcard over the whole Figma domain.  Missing lineage, a reused
    operation fingerprint, or a non-terminal intervention remains
    conservatively blocking.
    """
    attempt_id = str(attempt.get("attempt_id") or "")
    if (
        not attempt_id
        or attempt_id not in quarantined_attempt_ids
        or attempt.get("state") != "unknown"
        or _legacy_keyless_resource_domain(attempt) != "figma"
        or not _unresolved_figma_attempt_identity(attempt)
    ):
        return False
    if _legacy_keyless_resource_domain({"capability": capability}) != "figma":
        return False
    selected_operation = str(operation_fingerprint or "").strip()
    historical_operation = str(attempt.get("operation_fingerprint") or "").strip()
    return bool(
        re.fullmatch(r"[0-9a-f]{64}", selected_operation)
        and re.fullmatch(r"[0-9a-f]{64}", historical_operation)
        and selected_operation != historical_operation
    )


def _v1_row_is_bound(attempt: dict[str, Any], historical_key: str, kind: str) -> bool:
    """Validate an immutable v1 row with only the context that v1 retained."""
    try:
        _validate_resource_key(historical_key, allow_legacy=True)
        target = str(attempt.get("target") or "")
        if kind == "path":
            return _canonical_path_v1(
                target,
                base=str(attempt.get("resource_base") or "") or None,
            ) == historical_key
        if kind == "uri":
            return "uri:" + _canonical_uri_v1(target) == historical_key
        if kind == "opaque":
            return historical_key == "opaque:" + target
        if kind == "mcp":
            _version, _kind, _payload, prefix = _resource_key_parts(
                historical_key,
                allow_legacy=True,
            )
            server, _resource_kind, identifier = _structured_key_values(
                historical_key,
                prefix,
                3,
            )
            capability = str(attempt.get("capability") or "")
            parts = capability.split(":", 2)
            return bool(
                identifier == target
                and len(parts) == 3
                and parts[0] == "mcp"
                and parts[1].lower().replace("_", "-") == server
            )
        if kind == "git":
            # Frozen v1 Git rows sealed remote/ref in the typed key while the
            # raw target remained a provider command/display string.
            return True
    except (InterventionError, OSError, RuntimeError, ValueError):
        return False
    return False


def _v1_candidate_for_current(
    *,
    kind: str,
    target: str,
    resource_key: str,
    resource_base: Path | str | None,
    resource_context: dict[str, Any] | None,
) -> str:
    # First prove that the current key is exactly bound to its live inputs.
    current_kind, _normalized_context, _relation = _validate_external_resource_key(
        resource_key,
        target=target,
        base=resource_base,
        resource_context=resource_context,
    )
    if current_kind != kind:
        return ""
    if kind == "path":
        return _canonical_path_v1(target, base=resource_base)
    if kind == "uri":
        return "uri:" + _canonical_uri_v1(target)
    if kind in {"mcp", "opaque"}:
        return resource_key[len(_RESOURCE_KEY_VERSION) + 1 :]
    if kind == "git":
        context = _exact_resource_context(
            resource_context,
            ("remote", "ref", "oid"),
            "Git",
        )
        remote = context["remote"]
        if "://" in remote:
            remote_identity = "uri:" + _canonical_uri_v1(remote)
        elif re.fullmatch(r"[0-9a-fA-F]{64}", remote):
            remote_identity = "digest:" + remote.lower()
        elif remote.startswith(("/", "./", "../", "~")):
            remote_identity = _canonical_path_v1(remote, base=resource_base)
        else:
            remote_identity = "opaque:" + remote
        _remote, ref = _canonical_git_ref("x", context["ref"])
        return "git:" + _canonical([remote_identity, ref])
    return ""


def _v2_candidate_for_v1_row(
    attempt: dict[str, Any],
    historical_key: str,
    kind: str,
) -> str:
    """Derive v2 from retained v1 inputs without rewriting the immutable row."""
    target = str(attempt.get("target") or "")
    base = str(attempt.get("resource_base") or "") or None
    _version, _kind, _payload, prefix = _resource_key_parts(
        historical_key,
        allow_legacy=True,
    )
    if kind == "path":
        return canonical_resource_key(target, kind="path", base=base)
    if kind == "uri":
        return canonical_resource_key(target, kind="uri")
    if kind == "opaque":
        return canonical_resource_key(target, kind="opaque")
    if kind == "mcp":
        server, resource_kind, identifier = _structured_key_values(
            historical_key,
            prefix,
            3,
        )
        return canonical_resource_key(
            (server, resource_kind, identifier),
            kind="mcp",
        )
    if kind == "git":
        remote_identity, ref = _structured_key_values(
            historical_key,
            prefix,
            2,
        )
        if remote_identity.startswith("digest:"):
            migrated_remote = remote_identity
        else:
            remote_version, remote_kind, remote_payload, _remote_prefix = (
                _resource_key_parts(remote_identity, allow_legacy=True)
            )
            if remote_version == _RESOURCE_KEY_VERSION:
                migrated_remote = remote_identity
            elif remote_kind == "uri":
                migrated_remote = canonical_resource_key(remote_payload, kind="uri")
            elif remote_kind == "opaque":
                migrated_remote = canonical_resource_key(remote_payload, kind="opaque")
            else:
                # A v1 local-path remote does not retain enough stable object
                # history for inode-based v2 proof after the fact.
                raise InterventionError(
                    "legacy Git path remote cannot be migrated with stable proof"
                )
        return f"{_RESOURCE_KEY_VERSION}:git:" + _canonical([migrated_remote, ref])
    return ""


def _typed_resource_match_state(
    attempt: dict[str, Any],
    *,
    target: str,
    resource_key: str,
    resource_base: Path | str | None,
    resource_context: dict[str, Any] | None,
) -> str:
    """Return same/different/unknown for two typed versioned identities."""
    historical_key = str(attempt.get("resource_key") or "")
    if historical_key == resource_key:
        return (
            "same"
            if attempt.get("resource_sha256") == _resource_digest(resource_key)
            else "unknown"
        )
    try:
        historical_version, historical_kind, _payload, _prefix = _resource_key_parts(
            historical_key,
            allow_legacy=True,
        )
        current_version, current_kind, _payload, _prefix = _resource_key_parts(
            resource_key,
            allow_legacy=False,
        )
    except InterventionError:
        return "unknown"
    if historical_kind != current_kind:
        return "different"
    if historical_version != "v1" or current_version != _RESOURCE_KEY_VERSION:
        return "different" if historical_version == current_version else "unknown"
    if not _v1_row_is_bound(attempt, historical_key, historical_kind):
        return "unknown"
    try:
        candidate = _v1_candidate_for_current(
            kind=historical_kind,
            target=target,
            resource_key=resource_key,
            resource_base=resource_base,
            resource_context=resource_context,
        )
    except (InterventionError, OSError, RuntimeError, ValueError):
        candidate = ""
    if candidate == historical_key:
        return "same"
    try:
        migrated = _v2_candidate_for_v1_row(
            attempt,
            historical_key,
            historical_kind,
        )
    except (InterventionError, OSError, RuntimeError, ValueError):
        migrated = ""
    if migrated == resource_key:
        return "same"
    return "different" if candidate and migrated else "unknown"


def settlement_resource_match(
    attempt: dict[str, Any],
    *,
    target: str,
    resource_key: str,
    resource_base: Path | str | None = None,
    resource_context: dict[str, Any] | None = None,
) -> str:
    """Return ``proved_same``, ``proved_different`` or ``unproved``.

    Settlement is deliberately stricter than blocking: both sides must carry
    typed keys and the frozen version migration must prove equivalence.  Raw
    target equality is audit evidence, never a success/compensation proof.
    """
    historical_key = str(attempt.get("resource_key") or "")
    selected = str(resource_key or "").strip()
    if not historical_key or not selected:
        return "unproved"
    if attempt.get("resource_sha256") != _resource_digest(historical_key):
        return "unproved"
    try:
        _validate_external_resource_key(
            selected,
            target=target,
            base=resource_base,
            resource_context=resource_context,
        )
    except (InterventionError, OSError, RuntimeError, ValueError):
        return "unproved"
    state = _typed_resource_match_state(
        attempt,
        target=target,
        resource_key=selected,
        resource_base=resource_base,
        resource_context=resource_context,
    )
    if state == "same":
        return "proved_same"
    if state == "different":
        return "proved_different"
    return "unproved"


def blocker_resource_match(
    attempt: dict[str, Any],
    *,
    target: str,
    resource_key: str,
    resource_base: Path | str | None = None,
    resource_context: dict[str, Any] | None = None,
) -> bool:
    """Conservatively match current debt and every replay-verified old alias."""
    history = attempt.get("identity_history")
    if history is None:
        history = []
    if not isinstance(history, list) or any(
        not isinstance(identity, dict) for identity in history
    ):
        return True
    identities = [*history, attempt]
    for identity in identities:
        proof = settlement_resource_match(
            identity,
            target=target,
            resource_key=resource_key,
            resource_base=resource_base,
            resource_context=resource_context,
        )
        if proof == "proved_same":
            return True
        if proof == "proved_different":
            continue
        # Keyless history never proves settlement.  It can let unrelated work
        # pass only when retained authoritative inputs rederive a difference;
        # every derivation gap remains unknown and therefore blocks.
        if _attempt_resource_match_state(
            identity,
            target=target,
            resource_key=resource_key,
            resource_base=resource_base,
            resource_context=resource_context,
        ) != "different":
            return True
    return False


def _rows_settlement_proved(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Require typed proof for verification, compensation and retry links."""
    left_key = str(left.get("resource_key") or "")
    right_key = str(right.get("resource_key") or "")
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        expected_digest = _resource_digest(left_key)
        return (
            left.get("resource_sha256") == expected_digest
            and right.get("resource_sha256") == expected_digest
        )
    return settlement_resource_match(
        left,
        target=str(right.get("target") or ""),
        resource_key=right_key,
        resource_base=str(right.get("resource_base") or "") or None,
        resource_context=(
            right.get("resource_context")
            if isinstance(right.get("resource_context"), dict)
            else None
        ),
    ) == "proved_same"


def _attempt_matches_resource(
    attempt: dict[str, Any],
    *,
    target: str,
    resource_key: str,
    resource_base: Path | str | None = None,
    resource_context: dict[str, Any] | None = None,
) -> bool:
    """Compatibility alias for settlement-only callers."""
    return settlement_resource_match(
        attempt,
        target=target,
        resource_key=resource_key,
        resource_base=resource_base,
        resource_context=resource_context,
    ) == "proved_same"


def _attempt_resource_match_state(
    attempt: dict[str, Any],
    *,
    target: str,
    resource_key: str,
    resource_base: Path | str | None = None,
    resource_context: dict[str, Any] | None = None,
) -> str:
    """Tri-state matcher; callers choose whether unknown must block."""
    selected = resource_key.strip()
    historical_key = str(attempt.get("resource_key") or "")
    if historical_key and selected:
        return _typed_resource_match_state(
            attempt,
            target=target,
            resource_key=selected,
            resource_base=resource_base,
            resource_context=resource_context,
        )
    raw_matches = attempt.get("target_sha256") == _target_digest(target)
    if not historical_key or not selected:
        if raw_matches:
            return "same"
    if not selected:
        # A raw mismatch is never proof that a keyless current call names a
        # different resource, regardless of whether history is typed.
        return "unknown"

    # The historical row has no resource identity at all.  Keep this legacy
    # bridge isolated from v1/v2 typed rows and derive only namespaces with a
    # retained, explicit comparison context.
    attempt_base = attempt.get("resource_base") or None
    try:
        _version, kind, _payload, _prefix = _resource_key_parts(
            selected, allow_legacy=False
        )
        legacy_domain = _legacy_keyless_resource_domain(attempt)
        if legacy_domain:
            # Capability-level domain evidence can prove that a fully bound
            # local path is outside Figma.  It cannot prove which Figma object
            # the old call touched, nor can it separate any other resource
            # family, so every non-path comparison remains unknown/blocked.
            if legacy_domain != "figma" or kind != "path":
                return "unknown"
            try:
                current_kind, _context, _relation = _validate_external_resource_key(
                    selected,
                    target=target,
                    base=resource_base,
                    resource_context=resource_context,
                )
            except (InterventionError, OSError, RuntimeError, ValueError):
                return "unknown"
            return "different" if current_kind == "path" else "unknown"
        if kind == "path":
            if not attempt_base:
                return "unknown"
            matches = canonical_resource_key(
                attempt.get("target"), kind="path", base=attempt_base
            ) == selected
        elif kind == "uri":
            matches = canonical_resource_key(attempt.get("target"), kind="uri") == selected
        elif kind == "mcp":
            capability = str(attempt.get("capability") or "")
            parts = capability.split(":", 2)
            if len(parts) != 3 or parts[0] != "mcp":
                return "unknown"
            matches = _legacy_mcp_matches(attempt, selected)
        elif kind == "git":
            historical_git_key = _legacy_git_key(
                attempt.get("target"), base=attempt_base
            )
            if not historical_git_key:
                return "unknown"
            matches = historical_git_key == selected
        elif kind == "opaque":
            historical_context = attempt.get("resource_context")
            if not isinstance(historical_context, dict) or historical_context != {
                "schema": "exact",
                "value": str(attempt.get("target") or ""),
            }:
                return "unknown"
            matches = canonical_resource_key(
                historical_context["value"], kind="opaque"
            ) == selected
        else:
            return "unknown"
        return "same" if matches else "different"
    except (InterventionError, OSError, RuntimeError):
        return "unknown"


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextmanager
def _store_lock(path: Path, *, timeout: float = 3.0) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with lock_path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                lock_exclusive_nonblocking(handle)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise InterventionError(f"intervention store lock busy: {lock_path}")
                time.sleep(0.01)
        try:
            yield
        finally:
            unlock(handle)


def _empty_projection_for_digest(contract_sha256: str) -> dict[str, Any]:
    return {
        "schema": PROJECTION_SCHEMA,
        "contract_sha256": contract_sha256,
        "sequence": 0,
        "attempts": {},
        "interventions": {},
        "idempotency": {},
        "batches": {},
        "batch_idempotency": {},
        "batch_calls": {},
        "updated_at": None,
    }


def _validate_base(row: Any, expected_contract: str) -> dict[str, Any]:
    if not isinstance(row, dict) or row.get("schema") not in {
        EVENT_SCHEMA,
        LEGACY_EVENT_SCHEMA,
    }:
        raise InterventionError("unsupported intervention event row")
    if row.get("contract_sha256") != expected_contract:
        raise InterventionError("intervention event belongs to another contract")
    try:
        sequence = int(row.get("sequence"))
    except (TypeError, ValueError) as error:
        raise InterventionError("intervention event sequence is invalid") from error
    if sequence < 1:
        raise InterventionError("intervention event sequence must be positive")
    if not isinstance(row.get("at"), str) or not row["at"].strip():
        raise InterventionError("intervention event timestamp is missing")
    if not isinstance(row.get("type"), str) or not row["type"].strip():
        raise InterventionError("intervention event type is missing")
    return row


def _attempt_row_has_replay_authority(row: dict[str, Any]) -> bool:
    """Recompute every identity field carried by a new attempt row."""
    new_schema = row.get("schema") == EVENT_SCHEMA
    if not new_schema and row.get("schema") != LEGACY_EVENT_SCHEMA:
        return False
    raw_target = row.get("target")
    if not new_schema and raw_target == "":
        target = ""
    else:
        target = _require_identity_text(raw_target, "effect target")
    if row.get("target_sha256") != _target_digest(target):
        if new_schema:
            raise InterventionError("effect attempt target digest is not replayable")
        return False
    raw_resource_key = row.get("resource_key")
    if not isinstance(raw_resource_key, str) or not raw_resource_key:
        return False
    resource_key = _require_identity_text(raw_resource_key, "effect resource key")
    version, kind = _validate_resource_key(
        resource_key,
        allow_legacy=not new_schema,
    )
    if new_schema and version != _RESOURCE_KEY_VERSION:
        raise InterventionError("new effect attempts require a versioned resource key")
    resource_context = row.get("resource_context")
    if resource_context is None:
        resource_context = {}
    expected_relation = ""
    if version == _RESOURCE_KEY_VERSION:
        try:
            event_fields = (
                _stored_path_event_fields(
                    target=target,
                    resource_key=resource_key,
                    resource_base=str(row.get("resource_base") or "") or None,
                    resource_context=resource_context,
                )
                if kind == "path"
                else _event_resource_fields(
                    target=target,
                    resource_key=resource_key,
                    resource_base=str(row.get("resource_base") or "") or None,
                    resource_context=resource_context,
                )
            )
            (
                expected_key,
                expected_resource_sha256,
                expected_base,
                expected_context,
                expected_relation,
            ) = event_fields
        except (InterventionError, OSError, RuntimeError, ValueError):
            if new_schema:
                raise
            return False
        if (
            row.get("resource_key") != expected_key
            or row.get("resource_sha256") != expected_resource_sha256
            or str(row.get("resource_base") or "") != expected_base
            or resource_context != expected_context
        ):
            if new_schema:
                raise InterventionError(
                    "effect attempt resource identity is not replayable from target/context"
                )
            return False
    else:
        # A legacy line may retain enough frozen inputs to remain authoritative.
        # Git v1 cannot bind its provider command/display target to remote/ref,
        # so it remains readable and blocking-only even when relation inputs exist.
        if (
            kind == "git"
            or row.get("resource_sha256") != _resource_digest(resource_key)
            or not _v1_row_is_bound(row, resource_key, kind)
        ):
            return False
        expected_key = resource_key
        expected_resource_sha256 = _resource_digest(resource_key)
        expected_base = str(row.get("resource_base") or "")
        expected_context = resource_context
        if kind in {"uri", "path"} and resource_context:
            return False
        if kind == "mcp":
            _version, _kind, _payload, prefix = _resource_key_parts(
                resource_key,
                allow_legacy=True,
            )
            server, resource_kind, identifier = _structured_key_values(
                resource_key,
                prefix,
                3,
            )
            if resource_context != {
                "server": server,
                "resource_kind": resource_kind,
                "identifier": identifier,
            }:
                return False
        elif kind == "opaque" and resource_context not in (
            {},
            {"schema": "exact", "value": target},
        ):
            return False
    if (
        row.get("resource_key") != expected_key
        or row.get("resource_sha256") != expected_resource_sha256
        or str(row.get("resource_base") or "") != expected_base
        or resource_context != expected_context
    ):
        if new_schema:
            raise InterventionError(
                "effect attempt resource identity is not replayable from target/context"
            )
        return False
    arguments_digest = str(row.get("operation_arguments_digest") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", arguments_digest):
        if new_schema:
            raise InterventionError(
                "effect attempt operation inputs are missing or invalid"
            )
        return False
    operation_deriver = (
        effect_operation_fingerprint
        if new_schema
        else _legacy_effect_operation_fingerprint
    )
    expected_operation = operation_deriver(
        provider=str(row.get("provider") or "unknown"),
        capability=str(row.get("capability") or "unknown"),
        target=target,
        resource_key=resource_key,
        effect=str(row.get("effect") or "unknown"),
        arguments_digest=arguments_digest,
    )
    if row.get("operation_fingerprint") != expected_operation:
        if new_schema:
            raise InterventionError(
                "effect attempt operation fingerprint is not replayable"
            )
        return False
    if expected_relation:
        if (
            row.get("verification_kind") != "relation"
            or row.get("verification_sha256") != expected_relation
        ):
            if new_schema:
                raise InterventionError(
                    "Git relation is not replayable from remote/ref/OID context"
                )
            return False
    idempotency_key = _require_identity_text(
        row.get("idempotency_key"), "attempt idempotency key"
    )
    expected_attempt_id = _digest(
        "att", row.get("contract_sha256"), idempotency_key
    )
    if row.get("attempt_id") != expected_attempt_id:
        if new_schema:
            raise InterventionError(
                "attempt/idempotency relationship is not replayable"
            )
        return False
    return True


def _legacy_creation_is_replayable(row: dict[str, Any]) -> bool:
    """Validate the identity fields that the original v1 writer could seal.

    A v1 creation can be replayed as historical audit truth without becoming
    settlement authority.  This deliberately proves less than
    ``_attempt_row_has_replay_authority``: it binds only the immutable v1
    attempt/target identity and never derives a typed resource.
    """
    if row.get("schema") != LEGACY_EVENT_SCHEMA:
        return False
    try:
        raw_target = row.get("target")
        target = (
            ""
            if raw_target == ""
            else _require_identity_text(raw_target, "effect target")
        )
        idempotency_key = _require_identity_text(
            row.get("idempotency_key"), "attempt idempotency key"
        )
    except InterventionError:
        return False
    return bool(
        row.get("target_sha256") == _target_digest(target)
        and row.get("attempt_id")
        == _digest("att", row.get("contract_sha256"), idempotency_key)
    )


_LEGACY_ATTEMPT_ECHO_FIELDS = (
    "intent_id",
    "intent_revision",
    "provider",
    "session_id",
    "task_id",
    "capability",
    "effect",
    "target_sha256",
)


def _legacy_row_matches_attempt(
    row: dict[str, Any], attempt: dict[str, Any]
) -> bool:
    """Require one v1 follow-up row to echo its original attempt exactly."""
    return bool(
        row.get("schema") == LEGACY_EVENT_SCHEMA
        and attempt.get("legacy_creation_replayable") is True
        and row.get("attempt_id") == attempt.get("attempt_id")
        and attempt.get("target_sha256") == _target_digest(attempt.get("target"))
        and all(row.get(field) == attempt.get(field) for field in _LEGACY_ATTEMPT_ECHO_FIELDS)
    )


def _legacy_terminal_transition_is_replayable(
    row: dict[str, Any], attempt: dict[str, Any], state: str
) -> bool:
    """Recognize a frozen v1 terminal fact without promoting its authority."""
    if not _legacy_row_matches_attempt(row, attempt):
        return False
    if state == "system_verified":
        verification_event_id = str(row.get("verification_event_id") or "")
        verification_capability = str(row.get("verification_capability") or "")
        return bool(
            row.get("state_source") == "system_verification"
            and verification_event_id
            and verification_capability
            and verifier_matches(
                str(attempt.get("capability") or ""), verification_capability
            )
            and not row.get("evidence_sha256")
        )
    if state in {"human_attested_success", "confirmed_failed"}:
        return bool(
            row.get("state_source") == "human_attestation"
            and re.fullmatch(r"[0-9a-f]{64}", str(row.get("evidence_sha256") or ""))
            and not row.get("verification_event_id")
            and not row.get("verification_capability")
        )
    return False


def _legacy_resolution_is_replayable(
    row: dict[str, Any],
    attempt: dict[str, Any],
    intervention: dict[str, Any],
    decision: str,
) -> bool:
    """Validate a v1 resolution as history, never as current grant authority."""
    if (
        not _legacy_row_matches_attempt(row, attempt)
        or row.get("intervention_id") != intervention.get("intervention_id")
        or intervention.get("attempt_id") != attempt.get("attempt_id")
    ):
        return False
    actor = str(row.get("actor") or "")
    provider = str(attempt.get("provider") or "")
    if decision in {
        "system_verified",
        "human_attested_success",
        "confirmed_failed",
    }:
        expected_actor = (
            {"system-verifier"}
            if decision == "system_verified"
            else {"human-cli", f"user-prompt:{provider}"}
        )
        evidence = str(row.get("evidence") or "")
        transition = (
            attempt.get("transitions", [])[-1]
            if attempt.get("transitions")
            else {}
        )
        evidence_matches = bool(
            decision == "system_verified"
            or (
                evidence.strip()
                and transition.get("evidence_sha256")
                == hashlib.sha256(
                    evidence.encode("utf-8", errors="replace")
                ).hexdigest()
            )
        )
        return bool(
            attempt.get("legacy_terminal_replayed") is True
            and attempt.get("state") == decision
            and actor in expected_actor
            and evidence_matches
        )
    if decision == "retry_authorized":
        return bool(
            attempt.get("state") == "unknown"
            and actor == "system-continuation-grant"
            and bool(str(row.get("evidence") or "").strip())
            and not row.get("takeover_provider")
            and not row.get("takeover_session_id")
        )
    if decision == "reprobe_authorized":
        return bool(
            attempt.get("state") == "unknown"
            and actor == f"permission-request:{provider}"
            and bool(str(row.get("evidence") or "").strip())
            and row.get("takeover_provider") == provider
            and bool(str(row.get("takeover_session_id") or "").strip())
        )
    return False


def _legacy_retry_attempt_is_replayable(
    row: dict[str, Any],
    retry: dict[str, Any] | None,
    predecessor: dict[str, Any] | None,
) -> bool:
    """Replay one already-recorded v1 retry edge without making it reusable."""
    if (
        not isinstance(retry, dict)
        or not isinstance(predecessor, dict)
        or retry.get("legacy_resolution_replayed") is not True
        or retry.get("decision") != "retry_authorized"
        or retry.get("retry_consumed_by")
        or predecessor.get("state") != "unknown"
        or not _legacy_creation_is_replayable(row)
        or row.get("retry_intervention_id") != retry.get("intervention_id")
        or row.get("predecessor_attempt_id") != predecessor.get("attempt_id")
    ):
        return False
    return bool(
        row.get("provider") == predecessor.get("provider")
        and row.get("session_id") == predecessor.get("session_id")
        and row.get("task_id") == predecessor.get("task_id")
        and row.get("capability") == predecessor.get("capability")
        and row.get("effect") == predecessor.get("effect")
        and row.get("target") == predecessor.get("target")
        and row.get("target_sha256") == predecessor.get("target_sha256")
        and row.get("fingerprint") == predecessor.get("fingerprint")
    )


_BATCH_RESOURCE_FIELDS = frozenset(
    {
        "ordinal",
        "attempt_id",
        "idempotency_key",
        "target",
        "target_sha256",
        "resource_key",
        "resource_sha256",
        "resource_base",
        "resource_context",
        "operation_fingerprint",
        "operation_arguments_digest",
        "verification_kind",
        "verification_sha256",
    }
)


def _batch_member_idempotency_key(
    batch_id: str,
    ordinal: int,
    resource_sha256: str,
) -> str:
    return f"{batch_id}:resource:{ordinal}:{resource_sha256}"


def _batch_semantics_payload(
    row: dict[str, Any],
    resources: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "batch_id": row.get("batch_id"),
        "call_id": row.get("call_id"),
        "idempotency_key": row.get("idempotency_key"),
        "intent_id": row.get("intent_id"),
        "intent_revision": int(row.get("intent_revision") or 0),
        "fingerprint": row.get("fingerprint"),
        "source_event_id": row.get("source_event_id"),
        "capability": row.get("capability"),
        "effect": row.get("effect"),
        "provider": row.get("provider"),
        "session_id": row.get("session_id"),
        "task_id": row.get("task_id"),
        "operation_arguments_digest": row.get("operation_arguments_digest"),
        "resources": resources,
    }


def _batch_semantics_sha256(
    row: dict[str, Any],
    resources: list[dict[str, Any]],
) -> str:
    return hashlib.sha256(
        _canonical(_batch_semantics_payload(row, resources)).encode("utf-8")
    ).hexdigest()


def _batch_call_identity_sha256(
    *,
    provider: Any,
    session_id: Any,
    call_id: Any,
) -> str:
    """Bind one host call independently of caller-selected idempotency keys."""
    identity = {
        "provider": _require_identity_text(provider, "effect batch provider"),
        "session_id": _require_identity_text(
            session_id, "effect batch session"
        ),
        "call_id": _require_identity_text(call_id, "effect batch call id"),
    }
    return hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()


def _batch_call_semantics_sha256(
    row: dict[str, Any],
    resources: list[dict[str, Any]],
) -> str:
    """Seal call semantics without batch/idempotency-derived authority IDs."""
    semantic_resources = [
        {
            key: value
            for key, value in member.items()
            if key not in {"attempt_id", "idempotency_key"}
        }
        for member in resources
    ]
    payload = {
        "capability": row.get("capability"),
        "effect": row.get("effect"),
        "operation_arguments_digest": row.get("operation_arguments_digest"),
        "resources": semantic_resources,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _batch_attempt_row(
    batch_row: dict[str, Any],
    member: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": EVENT_SCHEMA,
        "contract_sha256": batch_row["contract_sha256"],
        "sequence": batch_row.get("sequence", 1),
        "at": batch_row.get("at") or now_iso(),
        "type": "effect.attempt_created",
        "state": "dispatched",
        "state_source": "system",
        "reason": "typed resource batch CAS released this exact host call",
        "batch_id": batch_row["batch_id"],
        "batch_call_id": batch_row["call_id"],
        "batch_idempotency_key": batch_row["idempotency_key"],
        "intent_id": batch_row.get("intent_id"),
        "intent_revision": batch_row.get("intent_revision"),
        "provider": batch_row.get("provider"),
        "session_id": batch_row.get("session_id"),
        "task_id": batch_row.get("task_id"),
        "fingerprint": batch_row.get("fingerprint"),
        "source_event_id": batch_row.get("source_event_id"),
        "capability": batch_row.get("capability"),
        "effect": batch_row.get("effect"),
        "predecessor_attempt_id": None,
        "retry_intervention_id": None,
        "semantic_retry_authority": False,
        "compensates_attempt_id": None,
        **member,
    }


def _validated_batch_members(row: dict[str, Any]) -> list[dict[str, Any]]:
    batch_id = _require_identity_text(row.get("batch_id"), "effect batch id")
    call_id = _require_identity_text(row.get("call_id"), "effect batch call id")
    idempotency_key = _require_identity_text(
        row.get("idempotency_key"), "effect batch idempotency key"
    )
    if not _BATCH_ID_RE.fullmatch(batch_id):
        raise InterventionError("effect batch id is invalid")
    expected_batch_id = _digest(
        "bat", row.get("contract_sha256"), idempotency_key
    )
    if batch_id != expected_batch_id:
        raise InterventionError("effect batch/idempotency relationship is not replayable")
    if not call_id:
        raise InterventionError("effect batch call id must not be empty")
    arguments_digest = str(row.get("operation_arguments_digest") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", arguments_digest):
        raise InterventionError("effect batch requires one replayable arguments digest")
    resources = row.get("resources")
    if not isinstance(resources, list) or not resources:
        raise InterventionError("effect batch requires at least one typed resource")

    seen_keys: set[str] = set()
    seen_attempts: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for ordinal, raw_member in enumerate(resources):
        if not isinstance(raw_member, dict) or set(raw_member) != _BATCH_RESOURCE_FIELDS:
            raise InterventionError("effect batch resource fields are incomplete or unexpected")
        member = dict(raw_member)
        if member.get("ordinal") != ordinal:
            raise InterventionError("effect batch resource order is not replayable")
        if member.get("operation_arguments_digest") != arguments_digest:
            raise InterventionError(
                "effect batch resources must share the host call arguments digest"
            )
        resource_key = str(member.get("resource_key") or "")
        resource_sha256 = str(member.get("resource_sha256") or "")
        if not resource_key:
            raise InterventionError("effect batch resources require typed resource keys")
        if resource_key in seen_keys:
            raise InterventionError(
                "effect batch has a duplicate canonical resource key or alias"
            )
        seen_keys.add(resource_key)
        expected_member_key = _batch_member_idempotency_key(
            batch_id, ordinal, resource_sha256
        )
        if member.get("idempotency_key") != expected_member_key:
            raise InterventionError("effect batch member idempotency is not replayable")
        expected_attempt_id = _digest(
            "att", row.get("contract_sha256"), expected_member_key
        )
        if member.get("attempt_id") != expected_attempt_id:
            raise InterventionError("effect batch member attempt identity is not replayable")
        if expected_attempt_id in seen_attempts:
            raise InterventionError("effect batch contains a duplicate attempt identity")
        seen_attempts.add(expected_attempt_id)
        attempt_row = _batch_attempt_row(row, member)
        if _attempt_row_has_replay_authority(attempt_row) is not True:
            raise InterventionError("effect batch member lacks replay authority")
        normalized.append(member)

    expected_set_sha256 = hashlib.sha256(
        _canonical(normalized).encode("utf-8")
    ).hexdigest()
    if row.get("resource_set_sha256") != expected_set_sha256:
        raise InterventionError("effect batch resource set digest is not replayable")
    if row.get("batch_semantics_sha256") != _batch_semantics_sha256(row, normalized):
        raise InterventionError("effect batch semantics digest is not replayable")
    return normalized


def _batch_blockers(
    projection: dict[str, Any],
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blocked: list[dict[str, Any]] = []
    for member in resources:
        for attempt in blocking_attempts(projection):
            if blocker_resource_match(
                attempt,
                target=str(member.get("target") or ""),
                resource_key=str(member.get("resource_key") or ""),
                resource_base=str(member.get("resource_base") or "") or None,
                resource_context=(
                    member.get("resource_context")
                    if isinstance(member.get("resource_context"), dict)
                    else None
                ),
            ):
                blocked.append(attempt)
    return blocked


def _batch_member_owner(
    projection: dict[str, Any],
    idempotency_key: str,
) -> str:
    for batch_id, batch in projection.get("batches", {}).items():
        resources = batch.get("resources") if isinstance(batch, dict) else None
        if isinstance(resources, list) and any(
            isinstance(member, dict)
            and member.get("idempotency_key") == idempotency_key
            for member in resources
        ):
            return str(batch_id)
    return ""


def _apply_event(
    projection: dict[str, Any],
    row: dict[str, Any],
    *,
    _batch_dispatch: bool = False,
) -> None:
    event_type = row["type"]
    attempts = projection["attempts"]
    interventions = projection["interventions"]
    batches = projection["batches"]
    batch_calls = projection["batch_calls"]
    attempt_id = str(row.get("attempt_id") or "")
    intervention_id = str(row.get("intervention_id") or "")

    if event_type == "effect.batch_prepared":
        if row.get("schema") != EVENT_SCHEMA:
            raise InterventionError("effect batch preparation requires the current schema")
        resources = _validated_batch_members(row)
        batch_id = str(row.get("batch_id") or "")
        idempotency_key = str(row.get("idempotency_key") or "")
        call_identity_sha256 = _batch_call_identity_sha256(
            provider=row.get("provider"),
            session_id=row.get("session_id"),
            call_id=row.get("call_id"),
        )
        call_semantics_sha256 = _batch_call_semantics_sha256(row, resources)
        if batch_id in batches:
            raise InterventionError(f"duplicate effect batch id: {batch_id!r}")
        if call_identity_sha256 in batch_calls:
            raise InterventionError(
                "effect batch call identity is already bound to another batch"
            )
        if idempotency_key in projection["batch_idempotency"]:
            raise InterventionError("effect batch idempotency key is duplicated")
        if idempotency_key in projection["idempotency"]:
            raise InterventionError(
                "effect batch idempotency conflicts with a single attempt"
            )
        if _batch_member_owner(projection, idempotency_key):
            raise InterventionError(
                "effect batch idempotency conflicts with a prepared batch member"
            )
        for member in resources:
            if (
                member["attempt_id"] in attempts
                or member["idempotency_key"] in projection["idempotency"]
                or member["idempotency_key"] in projection["batch_idempotency"]
                or _batch_member_owner(
                    projection, str(member["idempotency_key"])
                )
            ):
                raise InterventionError(
                    "effect batch member identity conflicts with prior authority"
                )
        if _batch_blockers(projection, resources):
            raise InterventionError(
                "same-resource blocker/debt prevents atomic batch preparation"
            )
        batches[batch_id] = {
            "batch_id": batch_id,
            "call_id": str(row.get("call_id") or ""),
            "idempotency_key": idempotency_key,
            "intent_id": str(row.get("intent_id") or ""),
            "intent_revision": int(row.get("intent_revision") or 0),
            "provider": str(row.get("provider") or "unknown"),
            "session_id": str(row.get("session_id") or ""),
            "task_id": str(row.get("task_id") or ""),
            "fingerprint": str(row.get("fingerprint") or ""),
            "source_event_id": str(row.get("source_event_id") or ""),
            "capability": str(row.get("capability") or "unknown"),
            "effect": str(row.get("effect") or "unknown"),
            "operation_arguments_digest": str(
                row.get("operation_arguments_digest") or ""
            ),
            "resource_set_sha256": str(row.get("resource_set_sha256") or ""),
            "batch_semantics_sha256": str(
                row.get("batch_semantics_sha256") or ""
            ),
            "call_identity_sha256": call_identity_sha256,
            "call_semantics_sha256": call_semantics_sha256,
            "resources": [dict(member) for member in resources],
            "attempt_ids": [str(member["attempt_id"]) for member in resources],
            "state": "prepared",
            "prepared_event_id": str(row.get("event_id") or ""),
            "dispatched_event_id": "",
            "prepared_at": row["at"],
            "dispatched_at": None,
            "updated_at": row["at"],
        }
        projection["batch_idempotency"][idempotency_key] = batch_id
        batch_calls[call_identity_sha256] = batch_id
    elif event_type == "effect.batch_dispatched":
        if row.get("schema") != EVENT_SCHEMA:
            raise InterventionError("effect batch dispatch requires the current schema")
        batch_id = str(row.get("batch_id") or "")
        batch = batches.get(batch_id)
        if not isinstance(batch, dict):
            raise InterventionError("effect batch dispatch references an unknown prepare")
        if batch.get("state") != "prepared":
            raise InterventionError("effect batch prepare authority was already consumed")
        if (
            row.get("call_id") != batch.get("call_id")
            or row.get("idempotency_key") != batch.get("idempotency_key")
            or row.get("prepared_event_id") != batch.get("prepared_event_id")
            or row.get("resource_set_sha256") != batch.get("resource_set_sha256")
            or row.get("batch_semantics_sha256")
            != batch.get("batch_semantics_sha256")
        ):
            raise InterventionError(
                "effect batch dispatch CAS does not match the prepared call/idempotency"
            )
        prepared_row = {
            "schema": EVENT_SCHEMA,
            "contract_sha256": projection["contract_sha256"],
            "sequence": row["sequence"],
            "at": row["at"],
            **batch,
        }
        resources = _validated_batch_members(prepared_row)
        if _batch_blockers(projection, resources):
            raise InterventionError(
                "same-resource blocker/debt prevents atomic batch dispatch"
            )
        for member in resources:
            if (
                member["attempt_id"] in attempts
                or member["idempotency_key"] in projection["idempotency"]
                or (
                    _batch_member_owner(
                        projection, str(member["idempotency_key"])
                    )
                    != batch_id
                )
            ):
                raise InterventionError(
                    "effect batch dispatch would create duplicate authority"
                )
        for member in resources:
            _apply_event(
                projection,
                _batch_attempt_row(prepared_row, member),
                _batch_dispatch=True,
            )
        batch["state"] = "dispatched"
        batch["dispatched_event_id"] = str(row.get("event_id") or "")
        batch["dispatched_at"] = row["at"]
        batch["updated_at"] = row["at"]
    elif event_type == "effect.attempt_created":
        if bool(row.get("batch_id")) != _batch_dispatch:
            raise InterventionError(
                "batch member attempts require one atomic batch dispatch event"
            )
        key = str(row.get("idempotency_key") or "")
        member_owner = _batch_member_owner(projection, key)
        if _batch_dispatch:
            if (
                member_owner != str(row.get("batch_id") or "")
                or key in projection["batch_idempotency"]
            ):
                raise InterventionError(
                    "batch member attempt is not reserved by this dispatch CAS"
                )
        elif key in projection["batch_idempotency"] or member_owner:
            raise InterventionError(
                "single attempt idempotency conflicts with prepared batch authority"
            )
        if not _ID_RE.fullmatch(attempt_id) or attempt_id in attempts:
            raise InterventionError(f"invalid or duplicate attempt id: {attempt_id!r}")
        if "identity_history" in row:
            raise InterventionError(
                "attempt creation cannot supply a caller-authored identity history"
            )
        state = str(row.get("state") or "")
        if state not in {"authorized", "dispatched"}:
            raise InterventionError("new effect attempt must start as authorized or observation-gap dispatched")
        replay_authoritative = _attempt_row_has_replay_authority(row)
        verification_kind = str(row.get("verification_kind") or "unsupported")
        verification_sha256 = str(row.get("verification_sha256") or "")
        operation_fingerprint = str(row.get("operation_fingerprint") or "")
        if operation_fingerprint and not re.fullmatch(
            r"[0-9a-f]{64}", operation_fingerprint
        ):
            raise InterventionError("effect operation fingerprint is invalid")
        resource_key = str(row.get("resource_key") or "")
        resource_sha256 = str(row.get("resource_sha256") or "")
        resource_base = str(row.get("resource_base") or "")
        resource_context = row.get("resource_context")
        if resource_context is None:
            resource_context = {}
        if not isinstance(resource_context, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in resource_context.items()
        ):
            raise InterventionError("effect attempt resource context is invalid")
        resource_kind = ""
        if resource_key:
            expected_resource_sha256 = _resource_digest(resource_key)
            _, resource_kind = _validate_resource_key(
                resource_key, allow_legacy=True
            )
            if (
                resource_sha256 != expected_resource_sha256
            ):
                raise InterventionError("effect attempt resource identity is invalid")
        elif resource_sha256:
            raise InterventionError("legacy effect attempt cannot carry only a resource digest")
        if resource_base and resource_kind != "path":
            raise InterventionError("only path resources may carry a resolution base")
        if verification_kind not in VERIFICATION_KINDS:
            raise InterventionError("effect attempt verification kind is invalid")
        if resource_key and resource_kind == "git" and verification_kind != "relation":
            raise InterventionError(
                "Git ref effects require remote/ref/OID relation verification"
            )
        if verification_kind in {"content", "relation"}:
            if not re.fullmatch(r"[0-9a-f]{64}", verification_sha256):
                raise InterventionError("effect attempt verification digest is invalid")
        elif verification_sha256:
            raise InterventionError("effect attempt verification digest is unexpected")
        compensates_attempt_id = str(row.get("compensates_attempt_id") or "")
        if compensates_attempt_id:
            predecessor = attempts.get(compensates_attempt_id)
            unresolved = any(
                intervention.get("attempt_id") == compensates_attempt_id
                and intervention.get("status") in {"open", "acknowledged"}
                for intervention in interventions.values()
            )
            if (
                not isinstance(predecessor, dict)
                or predecessor.get("state") != "unknown"
                or predecessor.get("replay_authoritative") is not True
                or not _rows_settlement_proved(predecessor, row)
                or not unresolved
            ):
                raise InterventionError(
                    "a compensating attempt requires one unresolved unknown predecessor "
                    "with the exact same target"
                )
        retry_intervention_id = str(row.get("retry_intervention_id") or "")
        if retry_intervention_id:
            retry = interventions.get(retry_intervention_id)
            predecessor = attempts.get(str((retry or {}).get("attempt_id") or ""))
            legacy_retry_replay = _legacy_retry_attempt_is_replayable(
                row,
                retry if isinstance(retry, dict) else None,
                predecessor if isinstance(predecessor, dict) else None,
            )
            sealed_operation = str(
                predecessor.get("operation_fingerprint") or ""
            ) if isinstance(predecessor, dict) else ""
            operation_matches = bool(
                sealed_operation
                and sealed_operation == str(row.get("operation_fingerprint") or "")
            )
            fingerprint_matches = bool(
                not sealed_operation
                and predecessor
                and predecessor.get("fingerprint")
                == str(row.get("fingerprint") or "")
            )
            retry_identity_matches = (
                operation_matches
                if sealed_operation
                else (
                    fingerprint_matches
                    or row.get("semantic_retry_authority") is True
                )
            )
            if (
                not isinstance(retry, dict)
                or retry.get("status") != "resolved"
                or retry.get("decision") != "retry_authorized"
                or retry.get("retry_consumed_by")
                or not isinstance(predecessor, dict)
                or predecessor.get("state") != "unknown"
                or (
                    predecessor.get("replay_authoritative") is not True
                    and not legacy_retry_replay
                )
                or predecessor.get("provider") != str(row.get("provider") or "unknown")
                or (
                    retry.get("takeover_provider") or retry.get("provider")
                )
                != str(row.get("provider") or "unknown")
                or (
                    retry.get("takeover_session_id") or retry.get("session_id")
                )
                != str(row.get("session_id") or "")
                or predecessor.get("capability") != str(row.get("capability") or "unknown")
                or predecessor.get("effect") != str(row.get("effect") or "unknown")
                or (
                    not _rows_settlement_proved(predecessor, row)
                    and not legacy_retry_replay
                )
                or not retry_identity_matches
            ):
                raise InterventionError(
                    "retry attempt does not match its explicit takeover authority"
                )
        attempts[attempt_id] = {
            "attempt_id": attempt_id,
            "batch_id": str(row.get("batch_id") or ""),
            "batch_call_id": str(row.get("batch_call_id") or ""),
            "batch_idempotency_key": str(
                row.get("batch_idempotency_key") or ""
            ),
            "predecessor_attempt_id": row.get("predecessor_attempt_id") or None,
            "compensates_attempt_id": compensates_attempt_id or None,
            "retry_intervention_id": retry_intervention_id or None,
            "semantic_retry_authority": (
                row.get("semantic_retry_authority") is True
            ),
            "intent_id": str(row.get("intent_id") or ""),
            "intent_revision": int(row.get("intent_revision") or 0),
            "provider": str(row.get("provider") or "unknown"),
            "session_id": str(row.get("session_id") or ""),
            "task_id": str(row.get("task_id") or ""),
            "fingerprint": str(row.get("fingerprint") or ""),
            "operation_fingerprint": operation_fingerprint,
            "operation_arguments_digest": str(
                row.get("operation_arguments_digest") or ""
            ),
            "source_event_id": str(row.get("source_event_id") or ""),
            "idempotency_key": str(row.get("idempotency_key") or ""),
            "capability": str(row.get("capability") or "unknown"),
            "effect": str(row.get("effect") or "unknown"),
            "target": str(row.get("target") or ""),
            "target_sha256": str(row.get("target_sha256") or ""),
            "resource_key": resource_key,
            "resource_sha256": resource_sha256,
            "resource_base": resource_base,
            "resource_context": dict(resource_context),
            "verification_kind": verification_kind,
            "verification_sha256": verification_sha256,
            "replay_authoritative": replay_authoritative,
            "legacy_creation_replayable": _legacy_creation_is_replayable(row),
            "legacy_terminal_replayed": False,
            "initial_target": str(row.get("target") or ""),
            "identity_history": [],
            "effect_classification_history": [],
            "state": state,
            "state_source": str(row.get("state_source") or "system"),
            "created_at": row["at"],
            "updated_at": row["at"],
            "transitions": [{"state": state, "at": row["at"], "reason": row.get("reason") or ""}],
        }
        if not key or key in projection["idempotency"]:
            raise InterventionError("attempt idempotency key is missing or duplicated")
        projection["idempotency"][key] = attempt_id
        if retry_intervention_id:
            # The bound retry attempt is itself the durable consumption fact.
            # This makes every prefix ending at attempt_created one-shot even
            # for historical logs whose producer appended a second marker row.
            retry["retry_consumed_by"] = attempt_id
            retry["updated_at"] = row["at"]
    elif event_type == "effect.attempt_classification_corrected":
        attempt = attempts.get(attempt_id)
        if not isinstance(attempt, dict):
            raise InterventionError(
                f"effect classification correction references unknown attempt: {attempt_id}"
            )
        operation_arguments_digest = str(
            row.get("operation_arguments_digest") or ""
        )
        evidence_sha256 = str(row.get("classification_evidence_sha256") or "")
        resolved_abort = any(
            intervention.get("attempt_id") == attempt_id
            and intervention.get("status") == "resolved"
            and intervention.get("decision") == "abort"
            for intervention in interventions.values()
        )
        if (
            row.get("schema") != EVENT_SCHEMA
            or row.get("actor") != LEGACY_READ_CLASSIFICATION_ACTOR
            or row.get("classification_evidence_kind")
            != LEGACY_READ_CLASSIFICATION_EVIDENCE
            or row.get("previous_effect") != attempt.get("effect")
            or row.get("corrected_effect") != "read"
            or attempt.get("effect") not in MATERIAL_EFFECTS
            or attempt.get("state") != "unknown"
            or attempt.get("capability")
            not in {
                "mcp:codex_apps:figma__use_figma",
                "mcp:figma:use_figma",
            }
            or attempt.get("operation_arguments_digest")
            != operation_arguments_digest
            or not re.fullmatch(r"[0-9a-f]{64}", operation_arguments_digest)
            or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
            or not resolved_abort
        ):
            raise InterventionError(
                "legacy read classification correction is not bound to one "
                "aborted unknown Figma attempt and exact rollout evidence"
            )
        history = attempt.get("effect_classification_history")
        if not isinstance(history, list) or any(
            not isinstance(item, dict) for item in history
        ):
            raise InterventionError(
                "effect classification history is not replayable"
            )
        history.append(
            {
                "at": row["at"],
                "previous_effect": attempt["effect"],
                "corrected_effect": "read",
                "operation_arguments_digest": operation_arguments_digest,
                "classification_evidence_kind": LEGACY_READ_CLASSIFICATION_EVIDENCE,
                "classification_evidence_sha256": evidence_sha256,
                "actor": LEGACY_READ_CLASSIFICATION_ACTOR,
            }
        )
        attempt["effect"] = "read"
        attempt["updated_at"] = row["at"]
    elif event_type == "effect.attempt_transitioned":
        attempt = attempts.get(attempt_id)
        if not isinstance(attempt, dict):
            raise InterventionError(f"attempt transition references unknown attempt: {attempt_id}")
        if (
            row.get("schema") == LEGACY_EVENT_SCHEMA
            and not _legacy_row_matches_attempt(row, attempt)
        ):
            raise InterventionError(
                "legacy attempt transition lost its original attempt binding"
            )
        state = str(row.get("state") or "")
        current = str(attempt.get("state") or "")
        legacy_terminal_replay = bool(
            attempt.get("replay_authoritative") is not True
            and _legacy_terminal_transition_is_replayable(row, attempt, state)
        )
        if (
            state in {
                "system_verified",
                "human_attested_success",
                "confirmed_failed",
            }
            and attempt.get("replay_authoritative") is not True
            and not legacy_terminal_replay
        ):
            raise InterventionError(
                "historical attempt lacks replay authority for settlement"
            )
        if state not in ATTEMPT_STATES or state not in _TRANSITIONS.get(current, set()):
            raise InterventionError(f"invalid effect transition: {current} -> {state}")
        attempt["state"] = state
        attempt["state_source"] = str(row.get("state_source") or "system")
        if legacy_terminal_replay:
            attempt["legacy_terminal_replayed"] = True
        attempt["updated_at"] = row["at"]
        attempt["transitions"].append(
            {
                "state": state,
                "at": row["at"],
                "reason": str(row.get("reason") or ""),
                "evidence_sha256": row.get("evidence_sha256"),
                "verification_event_id": row.get("verification_event_id"),
                "verification_capability": row.get("verification_capability"),
            }
        )
    elif event_type == "effect.attempt_target_resolved":
        attempt = attempts.get(attempt_id)
        if not isinstance(attempt, dict):
            raise InterventionError(f"target resolution references unknown attempt: {attempt_id}")
        if attempt.get("state") not in ACTIVE_ATTEMPT_STATES:
            raise InterventionError("a terminal effect attempt target cannot be rewritten")
        target = str(row.get("target") or "")
        if not target:
            raise InterventionError("resolved effect target must not be empty")
        old_identity = {
            "target": attempt.get("target"),
            "target_sha256": attempt.get("target_sha256"),
            "resource_key": attempt.get("resource_key"),
            "resource_sha256": attempt.get("resource_sha256"),
            "resource_base": attempt.get("resource_base"),
            "resource_context": dict(attempt.get("resource_context") or {}),
            "operation_fingerprint": attempt.get("operation_fingerprint"),
            "operation_arguments_digest": attempt.get(
                "operation_arguments_digest"
            ),
            "verification_kind": attempt.get("verification_kind"),
            "verification_sha256": attempt.get("verification_sha256"),
        }
        if row.get("schema") == EVENT_SCHEMA:
            if (
                not attempt.get("resource_key")
                or attempt.get("replay_authoritative") is not True
            ):
                raise InterventionError(
                    "typed CAS rebind requires an authoritative typed attempt"
                )
            expected_old = row.get("expected_old_identity")
            if not isinstance(expected_old, dict) or expected_old != old_identity:
                raise InterventionError(
                    "typed CAS rebind lost its old identity comparison"
                )
            previous_history = attempt.get("identity_history")
            if not isinstance(previous_history, list) or any(
                not isinstance(identity, dict) for identity in previous_history
            ):
                raise InterventionError(
                    "typed CAS rebind identity history is not replayable"
                )
            expected_history = [
                *[dict(identity) for identity in previous_history],
                old_identity,
            ]
            if row.get("identity_history") != expected_history:
                raise InterventionError(
                    "typed CAS rebind identity history is not append-only"
                )
            _attempt_row_has_replay_authority(row)
            attempt["target"] = target
            attempt["target_sha256"] = str(row.get("target_sha256") or "")
            attempt["resource_key"] = str(row.get("resource_key") or "")
            attempt["resource_sha256"] = str(row.get("resource_sha256") or "")
            attempt["resource_base"] = str(row.get("resource_base") or "")
            attempt["resource_context"] = dict(row.get("resource_context") or {})
            attempt["operation_fingerprint"] = str(
                row.get("operation_fingerprint") or ""
            )
            attempt["operation_arguments_digest"] = str(
                row.get("operation_arguments_digest") or ""
            )
            attempt["verification_kind"] = str(
                row.get("verification_kind") or "unsupported"
            )
            attempt["verification_sha256"] = str(
                row.get("verification_sha256") or ""
            )
        else:
            if (
                "identity_history" in row
                or
                row.get("legacy_keyless_resolution") is not True
                or attempt.get("resource_key")
                or attempt.get("replay_authoritative") is True
                or attempt.get("state") != "unknown"
                or row.get("target_sha256") != _target_digest(target)
            ):
                raise InterventionError(
                    "target-only resolution is restricted to unresolved legacy keyless debt"
                )
            attempt["target"] = target
            attempt["target_sha256"] = str(row.get("target_sha256") or "")
        attempt.setdefault("initial_target", old_identity["target"])
        attempt.setdefault("identity_history", []).append(old_identity)
        attempt["updated_at"] = row["at"]
    elif event_type == "intent.intervention_opened":
        if not _ID_RE.fullmatch(intervention_id) or intervention_id in interventions:
            raise InterventionError(f"invalid or duplicate intervention id: {intervention_id!r}")
        attempt = attempts.get(attempt_id)
        if not isinstance(attempt, dict) or attempt.get("state") != "unknown":
            raise InterventionError("an intervention may open only for an unknown attempt")
        if (
            row.get("schema") == LEGACY_EVENT_SCHEMA
            and not _legacy_row_matches_attempt(row, attempt)
        ):
            raise InterventionError(
                "legacy intervention opening lost its original attempt binding"
            )
        interventions[intervention_id] = {
            "intervention_id": intervention_id,
            "attempt_id": attempt_id,
            "status": "open",
            "decision": None,
            "reason": str(row.get("reason") or ""),
            "evidence": "",
            "actor": "system",
            "provider": attempt["provider"],
            "session_id": attempt["session_id"],
            "task_id": attempt["task_id"],
            "fingerprint": attempt["fingerprint"],
            "operation_fingerprint": attempt.get("operation_fingerprint") or "",
            "capability": attempt["capability"],
            "target_sha256": attempt["target_sha256"],
            "opened_at": row["at"],
            "updated_at": row["at"],
            "retry_consumed_by": None,
            "reprobe_consumed_by": None,
            "legacy_resolution_replayed": False,
        }
    elif event_type == "intent.intervention_acknowledged":
        intervention = interventions.get(intervention_id)
        if not isinstance(intervention, dict) or intervention.get("status") != "open":
            raise InterventionError("only an open intervention can be acknowledged")
        attempt = attempts.get(str(intervention.get("attempt_id") or ""))
        if (
            row.get("schema") == LEGACY_EVENT_SCHEMA
            and (
                not isinstance(attempt, dict)
                or not _legacy_row_matches_attempt(row, attempt)
            )
        ):
            raise InterventionError(
                "legacy intervention acknowledgement lost its attempt binding"
            )
        intervention["status"] = "acknowledged"
        intervention["actor"] = str(row.get("actor") or "human")
        intervention["updated_at"] = row["at"]
    elif event_type == "intent.intervention_resolved":
        intervention = interventions.get(intervention_id)
        if not isinstance(intervention, dict) or intervention.get("status") not in {"open", "acknowledged"}:
            raise InterventionError("only an unresolved intervention can be resolved")
        attempt = attempts.get(str(intervention.get("attempt_id") or ""))
        if not isinstance(attempt, dict):
            raise InterventionError("intervention resolution references unknown attempt")
        decision = str(row.get("decision") or "")
        if decision not in RESOLUTION_DECISIONS:
            raise InterventionError(f"unsupported intervention decision: {decision}")
        legacy_resolution_replay = bool(
            attempt.get("replay_authoritative") is not True
            and _legacy_resolution_is_replayable(
                row, attempt, intervention, decision
            )
        )
        if (
            decision != "abort"
            and attempt.get("replay_authoritative") is not True
            and not legacy_resolution_replay
        ):
            raise InterventionError(
                "historical attempt lacks replay authority for intervention settlement"
            )
        compensated_by_attempt_id = str(
            row.get("compensated_by_attempt_id") or ""
        )
        if decision == "system_compensated":
            original_attempt = attempts.get(str(intervention.get("attempt_id") or ""))
            compensating_attempt = attempts.get(compensated_by_attempt_id)
            if (
                row.get("actor") != "system-verifier"
                or not isinstance(original_attempt, dict)
                or original_attempt.get("state") != "unknown"
                or not isinstance(compensating_attempt, dict)
                or compensating_attempt.get("state") != "system_verified"
                or compensating_attempt.get("compensates_attempt_id")
                != original_attempt.get("attempt_id")
                or not _rows_settlement_proved(
                    original_attempt, compensating_attempt
                )
            ):
                raise InterventionError(
                    "system compensation requires an independently verified linked attempt"
                )
        elif compensated_by_attempt_id:
            raise InterventionError(
                "only system_compensated may name a compensating attempt"
            )
        takeover_provider = str(row.get("takeover_provider") or "")
        takeover_session_id = str(row.get("takeover_session_id") or "")
        if decision in {"retry_authorized", "reprobe_authorized"}:
            if not takeover_provider:
                takeover_provider = str(attempt.get("provider") or "unknown")
            if not takeover_session_id:
                takeover_session_id = str(attempt.get("session_id") or "")
            if (
                takeover_provider != str(attempt.get("provider") or "unknown")
                or not takeover_session_id
            ):
                raise InterventionError(
                    "effect takeover must stay on the original provider and name one session"
                )
        elif takeover_provider or takeover_session_id:
            raise InterventionError(
                "only retry/reprobe authority may name a takeover lane"
            )
        intervention["status"] = "resolved"
        intervention["decision"] = decision
        intervention["legacy_resolution_replayed"] = legacy_resolution_replay
        intervention["evidence"] = str(row.get("evidence") or "")
        intervention["actor"] = str(row.get("actor") or "unknown")
        intervention["compensated_by_attempt_id"] = (
            compensated_by_attempt_id or None
        )
        intervention["takeover_provider"] = takeover_provider or None
        intervention["takeover_session_id"] = takeover_session_id or None
        intervention["resolved_at"] = row["at"]
        intervention["updated_at"] = row["at"]
    elif event_type == "intent.intervention_retry_consumed":
        intervention = interventions.get(intervention_id)
        retry_attempt_id = str(row.get("retry_attempt_id") or "")
        if (
            not isinstance(intervention, dict)
            or intervention.get("decision") != "retry_authorized"
            or intervention.get("retry_consumed_by") not in {None, retry_attempt_id}
            or retry_attempt_id not in attempts
        ):
            raise InterventionError("retry grant is unavailable or already consumed")
        intervention["retry_consumed_by"] = retry_attempt_id
        intervention["updated_at"] = row["at"]
    elif event_type == "intent.intervention_reprobe_consumed":
        intervention = interventions.get(intervention_id)
        reprobe_event_id = str(row.get("reprobe_event_id") or "")
        if (
            not isinstance(intervention, dict)
            or intervention.get("decision") != "reprobe_authorized"
            or intervention.get("reprobe_consumed_by")
            or not reprobe_event_id
            or intervention.get("attempt_id") != attempt_id
        ):
            raise InterventionError("reprobe grant is unavailable or already consumed")
        intervention["reprobe_consumed_by"] = reprobe_event_id
        intervention["updated_at"] = row["at"]
    elif event_type == "notification.intervention_requested":
        intervention = interventions.get(intervention_id)
        if not isinstance(intervention, dict):
            raise InterventionError("notification references unknown intervention")
        attempt = attempts.get(str(intervention.get("attempt_id") or ""))
        if (
            row.get("schema") == LEGACY_EVENT_SCHEMA
            and (
                not isinstance(attempt, dict)
                or not _legacy_row_matches_attempt(row, attempt)
                or row.get("intervention_id")
                != intervention.get("intervention_id")
            )
        ):
            raise InterventionError(
                "legacy intervention notification lost its attempt binding"
            )
    else:
        raise InterventionError(f"unsupported intervention event type: {event_type}")

    projection["sequence"] = int(row["sequence"])
    projection["updated_at"] = row["at"]


def replay(contract_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _replay_digest(contract_digest(contract_path), rows)


def _replay_digest(
    expected_contract: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", expected_contract):
        raise InterventionError("intervention contract digest is invalid")
    projection = _empty_projection_for_digest(expected_contract)
    for expected_sequence, raw in enumerate(rows, 1):
        row = _validate_base(raw, expected_contract)
        if int(row["sequence"]) != expected_sequence:
            raise InterventionError(
                f"intervention sequence gap: expected {expected_sequence}, got {row['sequence']}"
            )
        expected_event_id = hashlib.sha256(
            _canonical({key: value for key, value in row.items() if key != "event_id"}).encode("utf-8")
        ).hexdigest()
        if row.get("event_id") != expected_event_id:
            raise InterventionError(f"intervention event digest mismatch at sequence {expected_sequence}")
        _apply_event(projection, row)
    return projection


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise InterventionError(f"intervention row {number} is not an object")
            rows.append(value)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InterventionError(f"invalid intervention JSONL: {error}") from error
    return rows


def load_projection(contract_path: Path) -> dict[str, Any]:
    """Replay the authoritative log; never trust a stale materialized projection."""
    return replay(contract_path, _read_rows(event_store_path(contract_path)))


def authoritative_store_bytes(contract_path: Path) -> bytes:
    store = event_store_path(contract_path)
    return store.read_bytes() if store.is_file() else b""


def restore_authoritative_store(contract_path: Path, payload: bytes) -> None:
    """Restore the parent supervisor's last validated bytes after child tampering."""
    if os.environ.get("SULDE_GUARDIAN_STREAM_OWNER") == "1":
        raise InterventionError("managed Agent execution cannot restore intervention authority")
    try:
        text = payload.decode("utf-8")
        rows = []
        for number, raw in enumerate(text.splitlines(), 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise InterventionError(f"intervention row {number} is not an object")
            rows.append(value)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InterventionError(f"cannot restore invalid intervention bytes: {error}") from error
    projection = replay(contract_path, rows)
    store = event_store_path(contract_path)
    with _store_lock(store):
        current = store.read_bytes() if store.is_file() else b""
        if current != payload and current.startswith(payload):
            raise InterventionError(
                "authoritative restore refuses to truncate an append-only ledger"
            )
        _atomic_bytes(store, payload)
        _atomic_json(projection_path(contract_path), projection)


def archive_store(
    contract_path: Path,
    archive_root: Path,
    *,
    slug: str,
) -> Path | None:
    """Copy one validated authoritative store before its L3 worktree is removed."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise InterventionError(f"invalid intervention archive slug: {slug}")
    store = event_store_path(contract_path)
    if not store.is_file():
        return None
    with _store_lock(store):
        rows = _read_rows(store)
        projection = replay(contract_path, rows)
        payload = store.read_bytes()
    store_sha256 = hashlib.sha256(payload).hexdigest()
    identity = f"{slug}-{projection['contract_sha256'][:16]}-{store_sha256[:16]}"
    destination = archive_root / identity
    events = destination / "events.jsonl"
    manifest_path = destination / "manifest.json"
    manifest = {
        "schema": ARCHIVE_SCHEMA,
        "slug": slug,
        "archived_at": now_iso(),
        "source_contract_path": str(contract_path.expanduser().absolute()),
        "contract_sha256": projection["contract_sha256"],
        "event_store_sha256": store_sha256,
        "event_count": projection["sequence"],
        "attempt_count": len(projection["attempts"]),
        "intervention_count": len(projection["interventions"]),
        "events_file": events.name,
    }
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise InterventionError(
                f"intervention archive manifest is unreadable: {error}"
            ) from error
        if (
            isinstance(existing, dict)
            and existing.get("schema") == ARCHIVE_SCHEMA
            and existing.get("event_store_sha256") == store_sha256
            and events.is_file()
            and hashlib.sha256(events.read_bytes()).hexdigest() == store_sha256
        ):
            return manifest_path
        raise InterventionError(f"intervention archive collision: {destination}")
    _atomic_bytes(events, payload)
    _atomic_json(manifest_path, manifest)
    return manifest_path


def load_archived_projection(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InterventionError(f"invalid intervention archive manifest: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != ARCHIVE_SCHEMA:
        raise InterventionError("unsupported intervention archive manifest")
    events_name = str(manifest.get("events_file") or "")
    if Path(events_name).name != events_name or events_name != "events.jsonl":
        raise InterventionError("intervention archive events path is invalid")
    events = manifest_path.parent / events_name
    try:
        payload = events.read_bytes()
    except OSError as error:
        raise InterventionError(f"intervention archive events are unavailable: {error}") from error
    if hashlib.sha256(payload).hexdigest() != manifest.get("event_store_sha256"):
        raise InterventionError("intervention archive digest mismatch")
    projection = _replay_digest(
        str(manifest.get("contract_sha256") or ""),
        _read_rows(events),
    )
    if projection["sequence"] != manifest.get("event_count"):
        raise InterventionError("intervention archive event count mismatch")
    return projection


Mutation = Callable[[dict[str, Any]], tuple[list[dict[str, Any]], Any]]


def _mutate(contract_path: Path, mutation: Mutation) -> tuple[dict[str, Any], Any]:
    if os.environ.get("SULDE_GUARDIAN_STREAM_OWNER") == "1":
        raise InterventionError(
            "managed Agent execution cannot mutate authoritative intervention truth"
        )
    store = event_store_path(contract_path)
    with _store_lock(store):
        rows = _read_rows(store)
        projection = replay(contract_path, rows)
        specs, result_hint = mutation(projection)
        if specs:
            at_default = now_iso()
            with store.open("a", encoding="utf-8") as handle:
                for spec in specs:
                    sequence = len(rows) + 1
                    row = {
                        "schema": str(spec.pop("schema", EVENT_SCHEMA)),
                        "contract_sha256": projection["contract_sha256"],
                        "sequence": sequence,
                        "at": str(spec.pop("at", at_default)),
                        **spec,
                    }
                    row["event_id"] = hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    rows.append(row)
                handle.flush()
                os.fsync(handle.fileno())
            projection = replay(contract_path, rows)
            _atomic_json(projection_path(contract_path), projection)
        return projection, result_hint


def _matching_retry(
    projection: dict[str, Any],
    *,
    fingerprint: str,
    operation_fingerprint: str = "",
    provider: str,
    session_id: str,
) -> dict[str, Any] | None:
    candidates = []
    for intervention in projection["interventions"].values():
        attempt = projection["attempts"].get(intervention.get("attempt_id"), {})
        sealed_operation = str(
            intervention.get("operation_fingerprint")
            or attempt.get("operation_fingerprint")
            or ""
        )
        operation_matches = (
            bool(operation_fingerprint)
            and bool(sealed_operation)
            and operation_fingerprint == sealed_operation
        )
        legacy_fingerprint_matches = (
            not sealed_operation
            and intervention.get("fingerprint") == fingerprint
        )
        if (
            intervention.get("status") == "resolved"
            and intervention.get("decision") == "retry_authorized"
            and not intervention.get("retry_consumed_by")
            and (operation_matches or legacy_fingerprint_matches)
            and (
                intervention.get("takeover_provider")
                or intervention.get("provider")
            )
            == provider
            and (
                intervention.get("takeover_session_id")
                or intervention.get("session_id")
            )
            == session_id
            and attempt.get("state") == "unknown"
            and attempt.get("replay_authoritative") is True
        ):
            candidates.append(intervention)
    return sorted(candidates, key=lambda row: str(row.get("opened_at") or ""))[-1] if candidates else None


def retry_grant_for_event(
    contract_path: Path,
    *,
    fingerprint: str,
    operation_fingerprint: str = "",
    provider: str,
    session_id: str,
) -> dict[str, Any] | None:
    return _matching_retry(
        load_projection(contract_path),
        fingerprint=fingerprint,
        operation_fingerprint=operation_fingerprint,
        provider=provider,
        session_id=session_id,
    )


def authorize_system_retry(
    contract_path: Path,
    intervention_id: str,
    *,
    fingerprint: str,
    provider: str,
    session_id: str,
    target: str,
    evidence: str,
    actor: str = "system-continuation-grant",
) -> dict[str, Any]:
    """Append one exact retry authority without claiming the old effect succeeded.

    This is the bootstrap-compatible half of a sealed compensation chain.  An
    already-loaded older Hook understands ``retry_authorized`` and can consume
    it, while the current supervisor remains responsible for independently
    verifying the replacement operation.  Every dispatch identity is checked
    again here so a proposal cannot turn a same-lane or same-tool coincidence
    into retry authority.
    """
    clean_fingerprint = fingerprint.strip().lower()
    clean_provider = provider.strip().lower()
    clean_session = session_id.strip()
    clean_target = target.strip()
    clean_evidence = evidence.strip()
    clean_actor = actor.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", clean_fingerprint):
        raise InterventionError("system retry requires an exact event fingerprint")
    if not clean_provider or not clean_session:
        raise InterventionError("system retry requires an exact provider and session")
    if not clean_target:
        raise InterventionError("system retry requires an exact effect target")
    if not clean_evidence or not clean_actor:
        raise InterventionError("system retry requires machine evidence and actor identity")
    target_sha256 = _target_digest(clean_target)

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        intervention = projection["interventions"].get(intervention_id)
        if not isinstance(intervention, dict):
            raise InterventionError(f"unknown intervention: {intervention_id}")
        if intervention.get("status") == "resolved":
            if (
                intervention.get("decision") == "retry_authorized"
                and intervention.get("evidence") == clean_evidence
                and intervention.get("actor") == clean_actor
            ):
                return [], intervention_id
            raise InterventionError("intervention was already resolved with another decision")
        if intervention.get("status") not in {"open", "acknowledged"}:
            raise InterventionError("system retry requires one unresolved intervention")
        attempt = projection["attempts"].get(intervention.get("attempt_id"))
        if not isinstance(attempt, dict) or attempt.get("state") != "unknown":
            raise InterventionError("system retry requires one unknown predecessor attempt")
        if attempt.get("replay_authoritative") is not True:
            raise InterventionError(
                "historical attempt lacks replay authority for retry"
            )
        if (
            attempt.get("fingerprint") != clean_fingerprint
            or intervention.get("fingerprint") != clean_fingerprint
            or str(attempt.get("provider") or "").lower() != clean_provider
            or str(intervention.get("provider") or "").lower() != clean_provider
            or attempt.get("session_id") != clean_session
            or intervention.get("session_id") != clean_session
            or attempt.get("target_sha256") != target_sha256
            or intervention.get("target_sha256") != target_sha256
        ):
            raise InterventionError(
                "system retry identity does not match fingerprint/provider/session/target"
            )
        return [
            {
                "type": "intent.intervention_resolved",
                "intervention_id": intervention_id,
                "attempt_id": attempt["attempt_id"],
                "intent_id": attempt.get("intent_id"),
                "intent_revision": attempt.get("intent_revision"),
                "provider": attempt.get("provider"),
                "session_id": attempt.get("session_id"),
                "task_id": attempt.get("task_id"),
                "capability": attempt.get("capability"),
                "effect": attempt.get("effect"),
                "target_sha256": attempt.get("target_sha256"),
                "decision": "retry_authorized",
                "evidence": clean_evidence[:4_000],
                "actor": clean_actor[:100],
            }
        ], intervention_id

    projection, _ = _mutate(contract_path, mutation)
    return dict(projection["interventions"][intervention_id])


_BATCH_RESOURCE_INPUT_FIELDS = frozenset(
    {
        "target",
        "resource_key",
        "resource_base",
        "resource_context",
        "operation_fingerprint",
        "operation_arguments_digest",
        "verification_kind",
        "verification_sha256",
    }
)


def _normalize_batch_resource_specs(
    *,
    contract_sha256: str,
    batch_id: str,
    provider: str,
    capability: str,
    effect: str,
    operation_arguments_digest: str,
    resources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(resources, list) or not resources:
        raise InterventionError("effect batch requires at least one typed resource")
    if not re.fullmatch(r"[0-9a-f]{64}", operation_arguments_digest):
        raise InterventionError("effect batch requires one replayable arguments digest")
    normalized: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for ordinal, raw in enumerate(resources):
        if not isinstance(raw, dict):
            raise InterventionError("effect batch resource must be one exact object")
        unexpected = set(raw) - _BATCH_RESOURCE_INPUT_FIELDS
        if unexpected:
            raise InterventionError(
                "effect batch resource has unexpected fields: "
                + ", ".join(sorted(unexpected))
            )
        target = _require_identity_text(
            raw.get("target"), f"effect batch resource {ordinal} target"
        )
        resource_key = _require_identity_text(
            raw.get("resource_key"),
            f"effect batch resource {ordinal} typed key",
        )
        member_arguments_digest = str(
            raw.get("operation_arguments_digest")
            or operation_arguments_digest
        )
        if not re.fullmatch(r"[0-9a-f]{64}", member_arguments_digest):
            raise InterventionError(
                "effect batch resource operation arguments digest is invalid"
            )
        if member_arguments_digest != operation_arguments_digest:
            raise InterventionError(
                "effect batch resources must share the host call arguments digest"
            )
        (
            selected_key,
            resource_sha256,
            normalized_base,
            normalized_context,
            relation_sha256,
        ) = _event_resource_fields(
            target=target,
            resource_key=resource_key,
            resource_base=raw.get("resource_base"),
            resource_context=raw.get("resource_context"),
        )
        if not selected_key:
            raise InterventionError(
                "effect batch resources require explicit typed resource keys"
            )
        if selected_key in seen_keys:
            raise InterventionError(
                "effect batch has a duplicate canonical resource key or alias"
            )
        seen_keys.add(selected_key)
        _version, resource_kind = _validate_resource_key(selected_key)
        verification_kind = str(raw.get("verification_kind") or "unsupported")
        verification_sha256 = str(raw.get("verification_sha256") or "")
        if verification_kind not in VERIFICATION_KINDS:
            raise InterventionError("unsupported effect verification kind")
        if verification_kind in {"content", "relation"}:
            if not re.fullmatch(r"[0-9a-f]{64}", verification_sha256):
                raise InterventionError(
                    "content/relation verification requires a sha256 digest"
                )
        elif verification_sha256:
            raise InterventionError(
                "only content/relation verification accepts a digest"
            )
        if resource_kind == "git" and (
            verification_kind != "relation"
            or verification_sha256 != relation_sha256
        ):
            raise InterventionError(
                "Git batch resource requires the rederived remote/ref/OID relation"
            )
        derived_operation = effect_operation_fingerprint(
            provider=provider,
            capability=capability,
            target=target,
            resource_key=selected_key,
            effect=effect,
            arguments_digest=member_arguments_digest,
        )
        supplied_operation = str(raw.get("operation_fingerprint") or "")
        if supplied_operation and supplied_operation != derived_operation:
            raise InterventionError(
                "effect batch resource operation fingerprint does not match replay inputs"
            )
        member_key = _batch_member_idempotency_key(
            batch_id, ordinal, resource_sha256
        )
        normalized.append(
            {
                "ordinal": ordinal,
                "attempt_id": _digest("att", contract_sha256, member_key),
                "idempotency_key": member_key,
                "target": target,
                "target_sha256": _target_digest(target),
                "resource_key": selected_key,
                "resource_sha256": resource_sha256,
                "resource_base": normalized_base,
                "resource_context": normalized_context,
                "operation_fingerprint": derived_operation,
                "operation_arguments_digest": member_arguments_digest,
                "verification_kind": verification_kind,
                "verification_sha256": verification_sha256,
            }
        )
    return normalized


def _batch_result(
    projection: dict[str, Any],
    batch_id: str,
    *,
    claimed: bool | None = None,
) -> dict[str, Any]:
    batch = dict(projection["batches"][batch_id])
    batch["resources"] = [dict(member) for member in batch["resources"]]
    batch["attempt_ids"] = list(batch["attempt_ids"])
    if claimed is not None:
        batch["claimed"] = claimed
    return batch


def prepare_attempt_batch(
    contract_path: Path,
    *,
    intent_id: str,
    intent_revision: int,
    fingerprint: str,
    source_event_id: str,
    capability: str,
    effect: str,
    provider: str,
    session_id: str,
    call_id: str,
    idempotency_key: str,
    operation_arguments_digest: str,
    resources: list[dict[str, Any]],
    task_id: str = "",
) -> dict[str, Any]:
    """Atomically prepare every typed resource for one not-yet-started host call.

    The single append is validation authority only.  It deliberately creates
    no attempt and therefore cannot prove that a tool started, settle an
    effect, or create effect debt.  ``dispatch_attempt_batch`` is the sole CAS
    that consumes this exact call/idempotency preparation.
    """
    clean_call_id = _require_identity_text(call_id, "effect batch call id")
    clean_idempotency = _require_identity_text(
        idempotency_key, "effect batch idempotency key"
    )
    clean_provider = _require_identity_text(provider, "effect batch provider")
    clean_session = _require_identity_text(session_id, "effect batch session")
    clean_capability = _require_identity_text(
        capability, "effect batch capability"
    )
    clean_effect = _require_identity_text(effect, "effect batch effect")
    clean_intent_id = _require_identity_text(intent_id, "effect batch intent id")
    clean_source_event = _require_identity_text(
        source_event_id, "effect batch source event id"
    )
    clean_fingerprint = str(fingerprint or "")
    if not re.fullmatch(r"[0-9a-f]{64}", clean_fingerprint):
        raise InterventionError("effect batch fingerprint must be one sha256 digest")
    clean_arguments_digest = str(operation_arguments_digest or "")
    expected_contract = contract_digest(contract_path)
    batch_id = _digest("bat", expected_contract, clean_idempotency)
    normalized_resources = _normalize_batch_resource_specs(
        contract_sha256=expected_contract,
        batch_id=batch_id,
        provider=clean_provider,
        capability=clean_capability,
        effect=clean_effect,
        operation_arguments_digest=clean_arguments_digest,
        resources=resources,
    )
    prepared_spec: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "type": "effect.batch_prepared",
        "batch_id": batch_id,
        "call_id": clean_call_id,
        "idempotency_key": clean_idempotency,
        "intent_id": clean_intent_id,
        "intent_revision": int(intent_revision),
        "fingerprint": clean_fingerprint,
        "source_event_id": clean_source_event,
        "capability": clean_capability,
        "effect": clean_effect,
        "provider": clean_provider,
        "session_id": clean_session,
        "task_id": str(task_id or ""),
        "operation_arguments_digest": clean_arguments_digest,
        "resources": normalized_resources,
        "resource_set_sha256": hashlib.sha256(
            _canonical(normalized_resources).encode("utf-8")
        ).hexdigest(),
    }
    prepared_spec["batch_semantics_sha256"] = _batch_semantics_sha256(
        prepared_spec, normalized_resources
    )
    call_identity_sha256 = _batch_call_identity_sha256(
        provider=clean_provider,
        session_id=clean_session,
        call_id=clean_call_id,
    )
    call_semantics_sha256 = _batch_call_semantics_sha256(
        prepared_spec, normalized_resources
    )

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        if projection["contract_sha256"] != expected_contract:
            raise InterventionError("effect batch contract identity changed")
        single = projection["idempotency"].get(clean_idempotency)
        if single:
            raise InterventionError(
                "effect batch idempotency conflicts with a single attempt"
            )
        if _batch_member_owner(projection, clean_idempotency):
            raise InterventionError(
                "effect batch idempotency conflicts with a prepared batch member"
            )
        existing_id = projection["batch_idempotency"].get(clean_idempotency)
        call_batch_id = projection["batch_calls"].get(call_identity_sha256)
        if call_batch_id:
            existing = projection["batches"].get(str(call_batch_id))
            if (
                not isinstance(existing, dict)
                or (existing_id and existing_id != call_batch_id)
            ):
                raise InterventionError(
                    "effect batch call identity conflicts with idempotency authority"
                )
            if existing.get("call_semantics_sha256") != call_semantics_sha256:
                raise InterventionError(
                    "effect batch call identity was reused for different semantics"
                )
            return [], str(call_batch_id)
        if existing_id:
            existing = projection["batches"].get(str(existing_id))
            if (
                not isinstance(existing, dict)
                or existing_id != batch_id
                or existing.get("call_id") != clean_call_id
                or existing.get("batch_semantics_sha256")
                != prepared_spec["batch_semantics_sha256"]
            ):
                raise InterventionError(
                    "effect batch idempotency key was reused for different semantics"
                )
            return [], batch_id
        replay_row = {
            "contract_sha256": projection["contract_sha256"],
            "sequence": projection["sequence"] + 1,
            "at": now_iso(),
            **prepared_spec,
        }
        replay_resources = _validated_batch_members(replay_row)
        if _batch_blockers(projection, replay_resources):
            raise InterventionError(
                "same-resource blocker/debt prevents atomic batch preparation"
            )
        return [dict(prepared_spec)], batch_id

    projection, result_batch_id = _mutate(contract_path, mutation)
    return _batch_result(projection, result_batch_id)


def dispatch_attempt_batch(
    contract_path: Path,
    *,
    call_id: str,
    idempotency_key: str,
    prepared_event_id: str,
) -> dict[str, Any]:
    """Consume one exact prepared batch immediately before the host call."""
    clean_call_id = _require_identity_text(call_id, "effect batch call id")
    clean_idempotency = _require_identity_text(
        idempotency_key, "effect batch idempotency key"
    )
    clean_prepared_event = _require_identity_text(
        prepared_event_id, "effect batch prepared event id"
    )
    if not re.fullmatch(r"[0-9a-f]{64}", clean_prepared_event):
        raise InterventionError("effect batch prepared event CAS is invalid")
    expected_contract = contract_digest(contract_path)
    batch_id = _digest("bat", expected_contract, clean_idempotency)

    def mutation(
        projection: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], tuple[str, bool]]:
        existing_id = projection["batch_idempotency"].get(clean_idempotency)
        batch = projection["batches"].get(batch_id)
        if existing_id != batch_id or not isinstance(batch, dict):
            raise InterventionError(
                "effect batch dispatch has no matching prepared call/idempotency CAS"
            )
        if (
            batch.get("call_id") != clean_call_id
            or batch.get("idempotency_key") != clean_idempotency
            or batch.get("prepared_event_id") != clean_prepared_event
        ):
            raise InterventionError(
                "effect batch dispatch CAS does not match the prepared call/idempotency"
            )
        if batch.get("state") == "dispatched":
            return [], (batch_id, False)
        if batch.get("state") != "prepared":
            raise InterventionError("effect batch is not dispatchable")
        prepared_row = {
            "schema": EVENT_SCHEMA,
            "contract_sha256": projection["contract_sha256"],
            "sequence": projection["sequence"] + 1,
            "at": now_iso(),
            **batch,
        }
        replay_resources = _validated_batch_members(prepared_row)
        if _batch_blockers(projection, replay_resources):
            raise InterventionError(
                "same-resource blocker/debt prevents atomic batch dispatch"
            )
        return (
            [
                {
                    "schema": EVENT_SCHEMA,
                    "type": "effect.batch_dispatched",
                    "batch_id": batch_id,
                    "call_id": clean_call_id,
                    "idempotency_key": clean_idempotency,
                    "prepared_event_id": clean_prepared_event,
                    "resource_set_sha256": batch["resource_set_sha256"],
                    "batch_semantics_sha256": batch["batch_semantics_sha256"],
                }
            ],
            (batch_id, True),
        )

    projection, result = _mutate(contract_path, mutation)
    result_batch_id, claimed = result
    return _batch_result(projection, result_batch_id, claimed=claimed)


def begin_attempt(
    contract_path: Path,
    *,
    intent_id: str,
    intent_revision: int,
    fingerprint: str,
    operation_fingerprint: str = "",
    operation_arguments_digest: str = "",
    source_event_id: str,
    capability: str,
    target: str,
    resource_key: str = "",
    resource_base: Path | str | None = None,
    resource_context: dict[str, Any] | None = None,
    effect: str,
    provider: str,
    session_id: str,
    task_id: str = "",
    idempotency_key: str,
    observation_gap: bool = False,
    verification_kind: str = "unsupported",
    verification_sha256: str = "",
    compensates_attempt_id: str = "",
    semantic_retry_intervention_id: str = "",
) -> dict[str, Any]:
    if not idempotency_key.strip():
        raise InterventionError("attempt idempotency key must not be empty")
    if verification_kind not in VERIFICATION_KINDS:
        raise InterventionError("unsupported effect verification kind")
    if verification_kind in {"content", "relation"}:
        if not re.fullmatch(r"[0-9a-f]{64}", verification_sha256):
            raise InterventionError("content/relation verification requires a sha256 digest")
    elif verification_sha256:
        raise InterventionError("only content/relation verification accepts a digest")
    (
        selected_resource_key,
        resource_sha256,
        normalized_resource_base,
        normalized_resource_context,
        relation_sha256,
    ) = _event_resource_fields(
        target=target,
        resource_key=resource_key,
        resource_base=resource_base,
        resource_context=resource_context,
    )
    selected_resource_kind = ""
    if selected_resource_key:
        _, selected_resource_kind = _validate_resource_key(selected_resource_key)
    if selected_resource_kind == "git" and verification_kind != "relation":
        raise InterventionError(
            "Git ref effects require remote/ref/OID relation verification"
        )
    if selected_resource_kind == "git" and verification_sha256 != relation_sha256:
        raise InterventionError(
            "Git verification digest does not match the supplied remote/ref/OID relation"
        )
    selected_arguments_digest = operation_arguments_digest or fingerprint
    if not re.fullmatch(r"[0-9a-f]{64}", selected_arguments_digest):
        raise InterventionError(
            "effect operation requires one replayable arguments digest"
        )
    derived_operation_fingerprint = effect_operation_fingerprint(
        provider=provider,
        capability=capability,
        target=target,
        resource_key=selected_resource_key,
        effect=effect,
        arguments_digest=selected_arguments_digest,
    )
    if operation_fingerprint and operation_fingerprint != derived_operation_fingerprint:
        raise InterventionError(
            "effect operation fingerprint does not match its replay inputs"
        )
    operation_fingerprint = derived_operation_fingerprint

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        if (
            projection["batch_idempotency"].get(idempotency_key)
            or _batch_member_owner(projection, idempotency_key)
        ):
            raise InterventionError(
                "effect attempt idempotency conflicts with a prepared batch call"
            )
        existing = projection["idempotency"].get(idempotency_key)
        if existing:
            attempt = projection["attempts"].get(str(existing), {})
            expected = {
                "fingerprint": fingerprint,
                "provider": provider,
                "session_id": session_id,
                "capability": capability,
                "target": target,
                "effect": effect,
                "verification_kind": verification_kind,
                "verification_sha256": verification_sha256,
                "compensates_attempt_id": compensates_attempt_id or None,
            }
            if any(attempt.get(key) != value for key, value in expected.items()):
                raise InterventionError(
                    "effect attempt idempotency key was reused for different semantics"
                )
            # Historical idempotency rows predate resource identity.  Exact
            # raw target equality above is enough for them; once a row carries
            # a resource key, it must continue to match the canonical binding.
            if attempt.get("resource_key") and (
                attempt.get("resource_key") != selected_resource_key
                or attempt.get("resource_sha256") != resource_sha256
            ):
                raise InterventionError(
                    "effect attempt idempotency key was reused for another resource"
                )
            if (
                attempt.get("operation_fingerprint")
                and attempt.get("operation_fingerprint")
                != operation_fingerprint
            ):
                raise InterventionError(
                    "effect attempt idempotency key was reused for another operation"
                )
            if (
                semantic_retry_intervention_id
                and attempt.get("retry_intervention_id")
                != semantic_retry_intervention_id
            ):
                raise InterventionError(
                    "effect attempt idempotency key was reused for another retry authority"
                )
            return [], str(existing)
        retry = _matching_retry(
            projection,
            fingerprint=fingerprint,
            operation_fingerprint=operation_fingerprint,
            provider=provider,
            session_id=session_id,
        )
        if semantic_retry_intervention_id:
            semantic_retry = projection["interventions"].get(
                semantic_retry_intervention_id
            )
            semantic_attempt = projection["attempts"].get(
                str((semantic_retry or {}).get("attempt_id") or "")
            )
            if (
                not isinstance(semantic_retry, dict)
                or semantic_retry.get("status") != "resolved"
                or semantic_retry.get("decision") != "retry_authorized"
                or semantic_retry.get("retry_consumed_by")
                or not isinstance(semantic_attempt, dict)
                or semantic_attempt.get("state") != "unknown"
                or (
                    semantic_retry.get("takeover_provider")
                    or semantic_retry.get("provider")
                )
                != provider
                or (
                    semantic_retry.get("takeover_session_id")
                    or semantic_retry.get("session_id")
                )
                != session_id
                or semantic_attempt.get("provider") != provider
                or semantic_attempt.get("capability") != capability
                or semantic_attempt.get("effect") != effect
                or not _attempt_matches_resource(
                    semantic_attempt,
                    target=target,
                    resource_key=selected_resource_key,
                    resource_base=normalized_resource_base or None,
                    resource_context=normalized_resource_context,
                )
            ):
                raise InterventionError(
                    "semantic retry authority does not match provider/session/target/effect"
                )
            sealed_operation = str(
                semantic_retry.get("operation_fingerprint")
                or semantic_attempt.get("operation_fingerprint")
                or ""
            )
            if sealed_operation and operation_fingerprint != sealed_operation:
                raise InterventionError(
                    "semantic retry operation does not match the sealed predecessor"
                )
            if (
                retry is not None
                and retry.get("intervention_id")
                != semantic_retry_intervention_id
            ):
                raise InterventionError(
                    "exact and semantic retry authorities disagree"
                )
            retry = semantic_retry
        if retry and compensates_attempt_id:
            raise InterventionError(
                "one attempt cannot consume a human retry and a system compensation grant"
            )
        predecessor = str(retry.get("attempt_id") or "") if retry else ""
        intervention_id = str(retry.get("intervention_id") or "") if retry else ""
        if compensates_attempt_id:
            predecessor_attempt = projection["attempts"].get(compensates_attempt_id)
            unresolved = any(
                row.get("attempt_id") == compensates_attempt_id
                and row.get("status") in {"open", "acknowledged"}
                for row in projection["interventions"].values()
            )
            if (
                not isinstance(predecessor_attempt, dict)
                or predecessor_attempt.get("state") != "unknown"
                or predecessor_attempt.get("replay_authoritative") is not True
                or not _attempt_matches_resource(
                    predecessor_attempt,
                    target=target,
                    resource_key=selected_resource_key,
                    resource_base=normalized_resource_base or None,
                    resource_context=normalized_resource_context,
                )
                or not unresolved
            ):
                raise InterventionError(
                    "compensation requires replay authority and typed same-resource proof"
                )
        permitted_blockers = {
            value
            for value in (predecessor, compensates_attempt_id)
            if value
        }
        quarantined_attempt_ids = {
            str(row.get("attempt_id") or "")
            for row in terminal_quarantined_attempts(projection)
        }
        conflicting_debt = [
            attempt
            for attempt in blocking_attempts(projection)
            if attempt.get("attempt_id") not in permitted_blockers
            and blocker_resource_match(
                attempt,
                target=target,
                resource_key=selected_resource_key,
                resource_base=normalized_resource_base or None,
                resource_context=normalized_resource_context,
            )
            and not _terminal_unresolved_figma_debt_allows_independent_operation(
                attempt,
                quarantined_attempt_ids=quarantined_attempt_ids,
                intent_id=intent_id,
                intent_revision=intent_revision,
                capability=capability,
                operation_fingerprint=operation_fingerprint,
            )
        ]
        if conflicting_debt:
            raise InterventionError(
                "same-resource blocker/debt prevents dispatch before grant consumption"
            )
        attempt_id = _digest(
            "att",
            projection["contract_sha256"],
            idempotency_key,
        )
        common = {
            "attempt_id": attempt_id,
            "intent_id": intent_id,
            "intent_revision": int(intent_revision),
            "provider": provider,
            "session_id": session_id,
            "task_id": task_id,
            "fingerprint": fingerprint,
            "operation_fingerprint": operation_fingerprint,
            "operation_arguments_digest": selected_arguments_digest,
            "semantic_retry_authority": bool(
                semantic_retry_intervention_id
            ),
            "source_event_id": source_event_id,
            "capability": capability,
            "effect": effect,
            "target": target,
            "target_sha256": _target_digest(target),
            "resource_key": selected_resource_key,
            "resource_sha256": resource_sha256,
            "resource_base": normalized_resource_base,
            "resource_context": normalized_resource_context,
            "verification_kind": verification_kind,
            "verification_sha256": verification_sha256,
            "compensates_attempt_id": compensates_attempt_id or None,
        }
        specs = [
            {
                "schema": (
                    EVENT_SCHEMA
                    if selected_resource_key
                    else LEGACY_EVENT_SCHEMA
                ),
                "type": "effect.attempt_created",
                # begin_attempt is called at the observable host/provider
                # dispatch boundary.  Persist that boundary as one authority
                # event so a torn multi-row append cannot leave an invisible
                # ``authorized`` attempt which neither blocks nor finalizes.
                "state": "dispatched",
                "state_source": "observation_gap" if observation_gap else "system",
                "reason": (
                    "completion was observed without a matching pre-dispatch callback"
                    if observation_gap
                    else "intent guardian authorized and released this exact dispatch to the host"
                ),
                "idempotency_key": idempotency_key,
                "predecessor_attempt_id": predecessor or None,
                "retry_intervention_id": intervention_id or None,
                **common,
            },
        ]
        return specs, attempt_id

    projection, attempt_id = _mutate(contract_path, mutation)
    return dict(projection["attempts"][attempt_id])


def _transition_spec(
    attempt: dict[str, Any],
    state: str,
    reason: str,
    *,
    state_source: str = "system",
    evidence: str = "",
    verification_event_id: str = "",
    verification_capability: str = "",
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "type": "effect.attempt_transitioned",
        "attempt_id": attempt["attempt_id"],
        "intent_id": attempt.get("intent_id"),
        "intent_revision": attempt.get("intent_revision"),
        "provider": attempt.get("provider"),
        "session_id": attempt.get("session_id"),
        "task_id": attempt.get("task_id"),
        "capability": attempt.get("capability"),
        "effect": attempt.get("effect"),
        "target_sha256": attempt.get("target_sha256"),
        "state": state,
        "state_source": state_source,
        "reason": reason[:2_000],
    }
    if evidence:
        spec["evidence_sha256"] = hashlib.sha256(evidence.encode("utf-8", errors="replace")).hexdigest()
    if verification_event_id:
        spec["verification_event_id"] = verification_event_id
    if verification_capability:
        spec["verification_capability"] = verification_capability
    return spec


def _unknown_specs(
    projection: dict[str, Any],
    attempt: dict[str, Any],
    reason: str,
) -> tuple[list[dict[str, Any]], str, bool]:
    history = [
        row
        for row in projection["interventions"].values()
        if row.get("attempt_id") == attempt["attempt_id"]
    ]
    unresolved = next(
        (
            row
            for row in reversed(history)
            if row.get("status") in {"open", "acknowledged"}
        ),
        None,
    )
    if unresolved:
        return [], str(unresolved["intervention_id"]), False
    if history and history[-1].get("decision") != "reprobe_authorized":
        return [], str(history[-1]["intervention_id"]), False
    intervention_id = (
        _digest("int", projection["contract_sha256"], attempt["attempt_id"])
        if not history
        else _digest(
            "int",
            projection["contract_sha256"],
            attempt["attempt_id"],
            f"round:{len(history) + 1}",
        )
    )
    specs: list[dict[str, Any]] = []
    if attempt["state"] != "unknown":
        specs.append(_transition_spec(attempt, "unknown", reason))
    specs.extend(
        [
            {
                "type": "intent.intervention_opened",
                "intervention_id": intervention_id,
                "attempt_id": attempt["attempt_id"],
                "intent_id": attempt.get("intent_id"),
                "intent_revision": attempt.get("intent_revision"),
                "provider": attempt.get("provider"),
                "session_id": attempt.get("session_id"),
                "task_id": attempt.get("task_id"),
                "capability": attempt.get("capability"),
                "effect": attempt.get("effect"),
                "target_sha256": attempt.get("target_sha256"),
                "reason": reason[:2_000],
            },
            {
                "type": "notification.intervention_requested",
                "intervention_id": intervention_id,
                "attempt_id": attempt["attempt_id"],
                "intent_id": attempt.get("intent_id"),
                "intent_revision": attempt.get("intent_revision"),
                "provider": attempt.get("provider"),
                "session_id": attempt.get("session_id"),
                "task_id": attempt.get("task_id"),
                "capability": attempt.get("capability"),
                "effect": attempt.get("effect"),
                "target_sha256": attempt.get("target_sha256"),
            },
        ]
    )
    return specs, intervention_id, True


def mark_attempt_result(
    contract_path: Path,
    attempt_id: str,
    *,
    success: bool | None,
    reason: str = "",
) -> dict[str, Any]:
    created_intervention = False

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        nonlocal created_intervention
        attempt = projection["attempts"].get(attempt_id)
        if not isinstance(attempt, dict):
            raise InterventionError(f"unknown effect attempt: {attempt_id}")
        state = str(attempt["state"])
        if state in {"system_verified", "human_attested_success", "confirmed_failed"}:
            return [], None
        if success is False:
            specs, intervention_id, created_intervention = _unknown_specs(
                projection,
                attempt,
                reason or "completion reported failure; the remote side effect cannot be proven absent",
            )
            return specs, intervention_id
        specs: list[dict[str, Any]] = []
        if state == "authorized":
            specs.append(_transition_spec(attempt, "dispatched", "completion arrived without an observed dispatch callback"))
            state = "dispatched"
            attempt = {**attempt, "state": state}
        if state == "dispatched":
            specs.append(_transition_spec(attempt, "accepted", reason or "provider returned without an observable failure"))
            attempt = {**attempt, "state": "accepted"}
        if attempt["state"] == "accepted":
            specs.append(_transition_spec(attempt, "verifying", "provider success is provisional until an independent read proves the effect"))
        return specs, None

    projection, intervention_id = _mutate(contract_path, mutation)
    if created_intervention and intervention_id:
        _notify_human(contract_path, projection["interventions"][intervention_id])
    return dict(projection["attempts"][attempt_id])


def resolve_attempt_target(
    contract_path: Path,
    attempt_id: str,
    *,
    target: str,
    resource_key: str = "",
    resource_base: Path | str | None = None,
    resource_context: dict[str, Any] | None = None,
    operation_fingerprint: str = "",
    operation_arguments_digest: str = "",
    verification_kind: str = "unsupported",
    verification_sha256: str = "",
    expected_target_sha256: str = "",
    expected_resource_sha256: str = "",
    expected_operation_fingerprint: str = "",
) -> dict[str, Any]:
    if not target.strip():
        raise InterventionError("resolved effect target must not be empty")

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        attempt = projection["attempts"].get(attempt_id)
        if not isinstance(attempt, dict):
            raise InterventionError(f"unknown effect attempt: {attempt_id}")
        rebind_requested = any(
            (
                resource_key,
                resource_base,
                resource_context,
                operation_fingerprint,
                operation_arguments_digest,
                verification_sha256,
                expected_target_sha256,
                expected_resource_sha256,
                expected_operation_fingerprint,
            )
        ) or verification_kind != "unsupported"
        if attempt.get("target") == target and not rebind_requested:
            return [], attempt_id
        common = {
            "type": "effect.attempt_target_resolved",
            "attempt_id": attempt_id,
            "intent_id": attempt.get("intent_id"),
            "intent_revision": attempt.get("intent_revision"),
            "provider": attempt.get("provider"),
            "session_id": attempt.get("session_id"),
            "task_id": attempt.get("task_id"),
            "capability": attempt.get("capability"),
            "effect": attempt.get("effect"),
            "target": target,
            "target_sha256": _target_digest(target),
        }
        if not attempt.get("resource_key"):
            if (
                attempt.get("state") != "unknown"
                or attempt.get("replay_authoritative") is True
                or not str(attempt.get("target") or "").startswith(
                    "[unresolved-"
                )
                or any(
                    (
                        resource_key,
                        resource_base,
                        resource_context,
                        operation_fingerprint,
                        operation_arguments_digest,
                        verification_sha256,
                        expected_target_sha256,
                        expected_resource_sha256,
                        expected_operation_fingerprint,
                    )
                )
                or verification_kind != "unsupported"
            ):
                raise InterventionError(
                    "legacy target-only resolution requires unresolved keyless debt"
                )
            return [
                {
                    "schema": LEGACY_EVENT_SCHEMA,
                    "legacy_keyless_resolution": True,
                    **common,
                }
            ], attempt_id

        if not resource_key:
            raise InterventionError(
                "typed attempt retarget requires a complete CAS identity rebind"
            )
        if (
            expected_target_sha256 != attempt.get("target_sha256")
            or expected_resource_sha256 != attempt.get("resource_sha256")
            or expected_operation_fingerprint
            != attempt.get("operation_fingerprint")
        ):
            raise InterventionError(
                "typed CAS rebind expected identity does not match current identity"
            )
        (
            selected_key,
            resource_sha256,
            normalized_base,
            normalized_context,
            relation_sha256,
        ) = _event_resource_fields(
            target=target,
            resource_key=resource_key,
            resource_base=resource_base,
            resource_context=resource_context,
        )
        if verification_kind not in VERIFICATION_KINDS:
            raise InterventionError("typed CAS rebind verification kind is invalid")
        if relation_sha256:
            if (
                verification_kind != "relation"
                or verification_sha256 != relation_sha256
            ):
                raise InterventionError(
                    "typed Git CAS rebind requires the rederived relation"
                )
        elif verification_kind in {"content", "relation"}:
            if not re.fullmatch(r"[0-9a-f]{64}", verification_sha256):
                raise InterventionError(
                    "typed CAS rebind verification digest is invalid"
                )
        elif verification_sha256:
            raise InterventionError(
                "typed CAS rebind has an unexpected verification digest"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", operation_arguments_digest):
            raise InterventionError(
                "typed CAS rebind requires replayable operation inputs"
            )
        derived_operation = effect_operation_fingerprint(
            provider=str(attempt.get("provider") or "unknown"),
            capability=str(attempt.get("capability") or "unknown"),
            target=target,
            resource_key=selected_key,
            effect=str(attempt.get("effect") or "unknown"),
            arguments_digest=operation_arguments_digest,
        )
        if operation_fingerprint != derived_operation:
            raise InterventionError(
                "typed CAS rebind operation fingerprint is not replayable"
            )
        old_identity = {
            "target": attempt.get("target"),
            "target_sha256": attempt.get("target_sha256"),
            "resource_key": attempt.get("resource_key"),
            "resource_sha256": attempt.get("resource_sha256"),
            "resource_base": attempt.get("resource_base"),
            "resource_context": dict(attempt.get("resource_context") or {}),
            "operation_fingerprint": attempt.get("operation_fingerprint"),
            "operation_arguments_digest": attempt.get(
                "operation_arguments_digest"
            ),
            "verification_kind": attempt.get("verification_kind"),
            "verification_sha256": attempt.get("verification_sha256"),
        }
        identity_history = attempt.get("identity_history")
        if not isinstance(identity_history, list) or any(
            not isinstance(identity, dict) for identity in identity_history
        ):
            raise InterventionError(
                "typed CAS rebind identity history is not replayable"
            )
        return [
            {
                **common,
                "idempotency_key": attempt.get("idempotency_key"),
                "resource_key": selected_key,
                "resource_sha256": resource_sha256,
                "resource_base": normalized_base,
                "resource_context": normalized_context,
                "operation_fingerprint": operation_fingerprint,
                "operation_arguments_digest": operation_arguments_digest,
                "verification_kind": verification_kind,
                "verification_sha256": verification_sha256,
                "expected_old_identity": old_identity,
                "identity_history": [
                    *[dict(identity) for identity in identity_history],
                    old_identity,
                ],
            }
        ], attempt_id

    projection, _ = _mutate(contract_path, mutation)
    return dict(projection["attempts"][attempt_id])


def mark_attempt_unknown(
    contract_path: Path,
    attempt_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    created = False

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        nonlocal created
        attempt = projection["attempts"].get(attempt_id)
        if not isinstance(attempt, dict):
            raise InterventionError(f"unknown effect attempt: {attempt_id}")
        specs, intervention_id, created = _unknown_specs(projection, attempt, reason)
        return specs, intervention_id

    projection, intervention_id = _mutate(contract_path, mutation)
    intervention = dict(projection["interventions"][intervention_id])
    if created:
        _notify_human(contract_path, intervention)
    return intervention


def acknowledge_intervention(
    contract_path: Path,
    intervention_id: str,
    *,
    actor: str = "human-cli",
) -> dict[str, Any]:
    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        intervention = projection["interventions"].get(intervention_id)
        if not isinstance(intervention, dict):
            raise InterventionError(f"unknown intervention: {intervention_id}")
        if intervention["status"] == "acknowledged":
            return [], intervention_id
        if intervention["status"] != "open":
            raise InterventionError(f"intervention is not open: {intervention['status']}")
        attempt = projection["attempts"][intervention["attempt_id"]]
        return [
            {
                "type": "intent.intervention_acknowledged",
                "intervention_id": intervention_id,
                "attempt_id": intervention["attempt_id"],
                "intent_id": attempt.get("intent_id"),
                "intent_revision": attempt.get("intent_revision"),
                "provider": attempt.get("provider"),
                "session_id": attempt.get("session_id"),
                "task_id": attempt.get("task_id"),
                "capability": attempt.get("capability"),
                "effect": attempt.get("effect"),
                "target_sha256": attempt.get("target_sha256"),
                "actor": actor,
            }
        ], intervention_id

    projection, _ = _mutate(contract_path, mutation)
    return dict(projection["interventions"][intervention_id])


def resolve_intervention(
    contract_path: Path,
    intervention_id: str,
    *,
    decision: str,
    evidence: str,
    actor: str = "human-cli",
    takeover_provider: str = "",
    takeover_session_id: str = "",
) -> dict[str, Any]:
    if decision not in HUMAN_DECISIONS:
        raise InterventionError(f"unsupported human intervention decision: {decision}")
    if not evidence.strip():
        raise InterventionError("intervention resolution requires non-empty evidence")
    clean_takeover_provider = takeover_provider.strip().lower()
    clean_takeover_session = takeover_session_id.strip()
    if bool(clean_takeover_provider) != bool(clean_takeover_session):
        raise InterventionError(
            "effect takeover requires both provider and session identity"
        )

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        intervention = projection["interventions"].get(intervention_id)
        if not isinstance(intervention, dict):
            raise InterventionError(f"unknown intervention: {intervention_id}")
        if intervention["status"] == "resolved":
            expected_provider = clean_takeover_provider or str(
                intervention.get("provider") or "unknown"
            )
            expected_session = clean_takeover_session or str(
                intervention.get("session_id") or ""
            )
            if (
                intervention.get("decision") == decision
                and intervention.get("evidence") == evidence
                and (
                    intervention.get("takeover_provider")
                    or intervention.get("provider")
                )
                == expected_provider
                and (
                    intervention.get("takeover_session_id")
                    or intervention.get("session_id")
                )
                == expected_session
            ):
                return [], intervention_id
            raise InterventionError("intervention was already resolved with another decision")
        attempt = projection["attempts"][intervention["attempt_id"]]
        if (
            decision != "abort"
            and attempt.get("replay_authoritative") is not True
        ):
            raise InterventionError(
                "historical attempt lacks replay authority for settlement or recovery; "
                "only abort is permitted"
            )
        specs: list[dict[str, Any]] = []
        if decision == "human_attested_success":
            specs.append(
                _transition_spec(
                    attempt,
                    "human_attested_success",
                    "human supplied independent evidence of success",
                    state_source="human_attestation",
                    evidence=evidence,
                )
            )
        elif decision == "confirmed_failed":
            specs.append(
                _transition_spec(
                    attempt,
                    "confirmed_failed",
                    "human supplied independent evidence of failure",
                    state_source="human_attestation",
                    evidence=evidence,
                )
            )
        specs.append(
            {
                "type": "intent.intervention_resolved",
                "intervention_id": intervention_id,
                "attempt_id": intervention["attempt_id"],
                "intent_id": attempt.get("intent_id"),
                "intent_revision": attempt.get("intent_revision"),
                "provider": clean_takeover_provider or attempt.get("provider"),
                "session_id": clean_takeover_session or attempt.get("session_id"),
                "task_id": attempt.get("task_id"),
                "capability": attempt.get("capability"),
                "effect": attempt.get("effect"),
                "target_sha256": attempt.get("target_sha256"),
                "decision": decision,
                "evidence": evidence[:4_000],
                "actor": actor,
                "takeover_provider": clean_takeover_provider,
                "takeover_session_id": clean_takeover_session,
            }
        )
        return specs, intervention_id

    projection, _ = _mutate(contract_path, mutation)
    return dict(projection["interventions"][intervention_id])


def settle_legacy_read_only_debt(
    contract_path: Path,
    intervention_id: str,
) -> dict[str, Any]:
    """Append the one system-only settlement allowed for typed read debt.

    This API deliberately accepts no caller-selected decision, evidence,
    actor, takeover lane, retry, or reprobe authority.  It preserves the
    generic human resolver's replay-authority rule while allowing an old,
    typed read attempt that was incorrectly escalated to be marked inapplicable
    without deleting its audit history.
    """
    if type(intervention_id) is not str or not _ID_RE.fullmatch(intervention_id):
        raise InterventionError("legacy read debt intervention id is invalid")

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        intervention = projection["interventions"].get(intervention_id)
        if not isinstance(intervention, dict):
            raise InterventionError(f"unknown intervention: {intervention_id}")
        if intervention.get("status") == "resolved":
            if (
                intervention.get("decision") == "abort"
                and intervention.get("actor") == LEGACY_READ_DEBT_ACTOR
                and intervention.get("evidence") == LEGACY_READ_DEBT_EVIDENCE
                and not intervention.get("takeover_provider")
                and not intervention.get("takeover_session_id")
            ):
                return [], intervention_id
            raise InterventionError(
                "legacy read debt was already resolved by another authority"
            )
        if intervention.get("status") not in {"open", "acknowledged"}:
            raise InterventionError(
                "legacy read debt intervention must still be open or acknowledged"
            )
        attempt = projection["attempts"].get(intervention.get("attempt_id"))
        if not isinstance(attempt, dict):
            raise InterventionError("legacy read debt has no matching attempt")
        if type(attempt.get("effect")) is not str or attempt.get("effect") != "read":
            raise InterventionError(
                "legacy read debt settlement requires effect exactly equal to read"
            )
        resource_key = attempt.get("resource_key")
        resource_sha256 = attempt.get("resource_sha256")
        if (
            type(resource_key) is not str
            or not resource_key
            or type(resource_sha256) is not str
            or resource_sha256 != _resource_digest(resource_key)
        ):
            raise InterventionError(
                "legacy read debt settlement requires a typed resource identity"
            )
        if attempt.get("state") != "unknown":
            raise InterventionError(
                "legacy read debt settlement requires one unknown interrupted attempt"
            )
        return [
            {
                "type": "intent.intervention_resolved",
                "intervention_id": intervention_id,
                "attempt_id": intervention["attempt_id"],
                "intent_id": attempt.get("intent_id"),
                "intent_revision": attempt.get("intent_revision"),
                "provider": attempt.get("provider"),
                "session_id": attempt.get("session_id"),
                "task_id": attempt.get("task_id"),
                "capability": attempt.get("capability"),
                "effect": "read",
                "target_sha256": attempt.get("target_sha256"),
                "decision": "abort",
                "evidence": LEGACY_READ_DEBT_EVIDENCE,
                "actor": LEGACY_READ_DEBT_ACTOR,
                "takeover_provider": "",
                "takeover_session_id": "",
            }
        ], intervention_id

    projection, _ = _mutate(contract_path, mutation)
    return dict(projection["interventions"][intervention_id])


def correct_legacy_figma_read_only_classification(
    contract_path: Path,
    attempt_id: str,
    *,
    operation_arguments_digest: str,
    classification_evidence_sha256: str,
) -> dict[str, Any]:
    """Append one exact, system-only correction for a misclassified Figma read.

    The trusted caller must first recover the original Codex MCP item, match
    its canonical input digest to the immutable attempt, and prove the Plugin
    API script belongs to the narrow read-only language. This function does
    not accept caller-selected effects or actors and never rewrites the
    original attempt/intervention rows.
    """
    if type(attempt_id) is not str or not _ID_RE.fullmatch(attempt_id):
        raise InterventionError("legacy Figma read attempt id is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", operation_arguments_digest):
        raise InterventionError("legacy Figma read arguments digest is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", classification_evidence_sha256):
        raise InterventionError("legacy Figma read evidence digest is invalid")

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        attempt = projection["attempts"].get(attempt_id)
        if not isinstance(attempt, dict):
            raise InterventionError(f"unknown effect attempt: {attempt_id}")
        if attempt.get("effect") == "read":
            history = attempt.get("effect_classification_history") or []
            if any(
                isinstance(item, dict)
                and item.get("operation_arguments_digest")
                == operation_arguments_digest
                and item.get("classification_evidence_sha256")
                == classification_evidence_sha256
                for item in history
            ):
                return [], attempt_id
            raise InterventionError(
                "effect attempt was already classified as read by different evidence"
            )
        return [
            {
                "type": "effect.attempt_classification_corrected",
                "attempt_id": attempt_id,
                "actor": LEGACY_READ_CLASSIFICATION_ACTOR,
                "previous_effect": attempt.get("effect"),
                "corrected_effect": "read",
                "operation_arguments_digest": operation_arguments_digest,
                "classification_evidence_kind": LEGACY_READ_CLASSIFICATION_EVIDENCE,
                "classification_evidence_sha256": classification_evidence_sha256,
            }
        ], attempt_id

    projection, selected = _mutate(contract_path, mutation)
    return dict(projection["attempts"][selected])


def is_legacy_git_control_attempt(attempt: dict[str, Any]) -> bool:
    """Identify historical attempts created by Guardian's retired Git policy."""
    if not isinstance(attempt, dict):
        return False
    capability = str(attempt.get("capability") or "").strip().lower()
    target = str(attempt.get("target") or "").strip().lower()
    resource_key = str(attempt.get("resource_key") or "")
    resource_kind = str(attempt.get("resource_kind") or "").lower()
    if resource_kind in {"git", "git_metadata", "git_worktree_lifecycle"}:
        return True
    if capability.startswith("git.") or capability.startswith("tool:git_"):
        return True
    if target.startswith("git-ref:"):
        return True
    try:
        if resource_key and _validate_resource_key(
            resource_key, allow_legacy=True
        )[1] == "git":
            return True
    except InterventionError:
        pass
    # Earliest ledgers sometimes retained only Bash plus a display command.
    return capability == "tool:bash" and target.startswith("git ")


def _legacy_git_resolution_spec(
    attempt: dict[str, Any], intervention_id: str,
) -> dict[str, Any]:
    return {
        "type": "intent.intervention_resolved",
        "intervention_id": intervention_id,
        "attempt_id": attempt["attempt_id"],
        "intent_id": attempt.get("intent_id"),
        "intent_revision": attempt.get("intent_revision"),
        "provider": attempt.get("provider"),
        "session_id": attempt.get("session_id"),
        "task_id": attempt.get("task_id"),
        "capability": attempt.get("capability"),
        "effect": attempt.get("effect"),
        "target_sha256": attempt.get("target_sha256"),
        "decision": "abort",
        "evidence": LEGACY_GIT_CONTROL_DEBT_EVIDENCE,
        "actor": LEGACY_GIT_CONTROL_DEBT_ACTOR,
        "takeover_provider": "",
        "takeover_session_id": "",
    }


def reconcile_legacy_git_control_debt(contract_path: Path) -> list[str]:
    """Append-only quarantine for debt created by the retired Git controller.

    The migration never asserts success or failure and never rewrites an old
    row.  Existing human/system resolutions are left untouched.  Replaying the
    same store is idempotent.
    """
    reconciled: list[str] = []

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        specs: list[dict[str, Any]] = []
        interventions = list(projection["interventions"].values())
        for attempt in projection["attempts"].values():
            if (
                attempt.get("state") != "unknown"
                or not is_legacy_git_control_attempt(attempt)
            ):
                continue
            history = [
                row
                for row in interventions
                if row.get("attempt_id") == attempt.get("attempt_id")
            ]
            latest = history[-1] if history else None
            if latest and latest.get("status") == "resolved":
                if (
                    latest.get("decision") == "abort"
                    and latest.get("actor") == LEGACY_GIT_CONTROL_DEBT_ACTOR
                    and latest.get("evidence") == LEGACY_GIT_CONTROL_DEBT_EVIDENCE
                ):
                    reconciled.append(str(attempt["attempt_id"]))
                continue
            if latest is None:
                opened, intervention_id, _created = _unknown_specs(
                    projection,
                    attempt,
                    "historical Git control debt awaiting policy migration",
                )
                specs.extend(opened)
            elif latest.get("status") in {"open", "acknowledged"}:
                intervention_id = str(latest["intervention_id"])
            else:
                continue
            specs.append(_legacy_git_resolution_spec(attempt, intervention_id))
            reconciled.append(str(attempt["attempt_id"]))
        return specs, sorted(set(reconciled))

    _projection, result = _mutate(contract_path, mutation)
    return list(result)


def _capability_parts(capability: str) -> tuple[str, str, str]:
    parts = capability.split(":", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2].lower()
    if len(parts) == 2:
        return parts[0], "", parts[1].lower()
    return "", "", capability.lower()


def verifier_matches(write_capability: str, read_capability: str) -> bool:
    registered_match = DEFAULT_EFFECT_ROUTER.verifier_match(
        write_capability,
        read_capability,
    )
    if registered_match is not None:
        return registered_match
    if (
        write_capability == "tool:Bash"
        and read_capability
        in {
            "tool:codex_plugin_cachebuster_verify",
            "tool:codex_plugin_install_verify",
            "tool:sulde_scheduler_reconcile_verify",
            "tool:sulde_launcher_refresh_verify",
        }
    ):
        return True
    if (
        write_capability
        in {
            "git.worktree.attach_existing",
            "git.worktree.create_branch",
        }
        and read_capability == "tool:git_worktree_lifecycle_verify"
    ):
        return True
    write_kind, write_server, write_action = _capability_parts(write_capability)
    read_kind, read_server, read_action = _capability_parts(read_capability)
    if write_kind != read_kind or write_server != read_server:
        return False
    explicit = {
        "memory_annotate": {"memory_search", "memory_graph", "memory_get"},
        "create_document": {"read_document", "get_document"},
        "update_document": {"read_document", "get_document"},
        "edit_document": {"read_document", "get_document"},
        "write_document": {"read_document", "get_document"},
    }
    if read_action in explicit.get(write_action, set()):
        return True
    write_suffix = re.sub(r"^(?:add|annotate|apply|create|edit|patch|post|set|update|write)_?", "", write_action)
    read_suffix = re.sub(r"^(?:find|get|inspect|list|query|read|search|show)_?", "", read_action)
    return bool(write_suffix and write_suffix == read_suffix)


def verify_from_read(
    contract_path: Path,
    *,
    provider: str,
    session_id: str,
    capability: str,
    target: str,
    resource_key: str = "",
    resource_base: Path | str | None = None,
    resource_context: dict[str, Any] | None = None,
    verification_event_id: str,
    explicit_attempt_id: str = "",
    evidence: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    normalized_resource_context: dict[str, str] = {}
    relation_sha256 = ""
    if resource_key:
        _kind, normalized_resource_context, relation_sha256 = _validate_external_resource_key(
            resource_key,
            target=target,
            base=resource_base,
            resource_context=resource_context,
        )
    elif resource_context:
        raise InterventionError("resource context requires one explicit typed resource key")
    selected_ids: list[str] = []
    raw_evidence = evidence or {}
    if relation_sha256 and relation_sha256 not in raw_evidence.get("relation", []):
        raise InterventionError(
            "Git verification evidence does not match the supplied remote/ref/OID relation"
        )
    evidence = {
        kind: [
            value
            for value in values
            if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        ]
        for kind, values in raw_evidence.items()
        if kind in {"existence", "content", "relation"} and isinstance(values, list)
    }

    def mutation(projection: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        def takeover_for_verification(
            attempt: dict[str, Any],
        ) -> tuple[bool, dict[str, Any] | None]:
            if (
                attempt.get("provider") == provider
                and attempt.get("session_id") == session_id
            ):
                return True, None
            if not explicit_attempt_id:
                return False, None
            intervention = next(
                (
                    row
                    for row in projection["interventions"].values()
                    if row.get("attempt_id") == attempt.get("attempt_id")
                    and row.get("status") == "resolved"
                    and row.get("decision")
                    in {"retry_authorized", "reprobe_authorized"}
                    and (
                        row.get("decision") != "reprobe_authorized"
                        or not row.get("reprobe_consumed_by")
                    )
                ),
                None,
            )
            allowed = bool(
                intervention
                and (
                    intervention.get("takeover_provider")
                    or intervention.get("provider")
                )
                == provider
                and (
                    intervention.get("takeover_session_id")
                    or intervention.get("session_id")
                )
                == session_id
            )
            return allowed, intervention if allowed else None

        eligible: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        for attempt in projection["attempts"].values():
            same_resource = _attempt_matches_resource(
                attempt,
                target=target,
                resource_key=resource_key,
                resource_base=resource_base,
                resource_context=normalized_resource_context,
            )
            lane_allowed, takeover = takeover_for_verification(attempt)
            if not (
                attempt.get("state") in {"verifying", "unknown"}
                and attempt.get("replay_authoritative") is True
                and lane_allowed
                and same_resource
                and verifier_matches(
                    str(attempt.get("capability") or ""), capability
                )
            ):
                continue
            eligible.append((attempt, takeover))
        if explicit_attempt_id:
            eligible = [
                pair
                for pair in eligible
                if pair[0].get("attempt_id") == explicit_attempt_id
            ]
        elif len(eligible) != 1:
            eligible = []

        specs: list[dict[str, Any]] = []
        candidates = []
        for attempt, takeover in eligible:
            if (
                takeover
                and takeover.get("decision") == "reprobe_authorized"
            ):
                specs.append(
                    {
                        "type": "intent.intervention_reprobe_consumed",
                        "intervention_id": takeover["intervention_id"],
                        "attempt_id": attempt["attempt_id"],
                        "reprobe_event_id": verification_event_id,
                    }
                )
            verification_kind = str(
                attempt.get("verification_kind") or "unsupported"
            )
            if verification_kind == "existence":
                # New aliases prove existence through their canonical resource
                # identity; legacy callers still provide the original raw
                # target digest and keep the exact historical behavior.
                existence_digests = evidence.get("existence", [])
                proved = bool(
                    attempt.get("target_sha256") in existence_digests
                    or (
                        resource_key
                        and _target_digest(target) in existence_digests
                    )
                )
            else:
                proved = bool(
                    verification_kind in {"content", "relation"}
                    and attempt.get("verification_sha256")
                    and attempt.get("verification_sha256")
                    in evidence.get(verification_kind, [])
                )
            if proved:
                candidates.append(attempt)
        for attempt in candidates:
            selected_ids.append(str(attempt["attempt_id"]))
            specs.append(
                _transition_spec(
                    attempt,
                    "system_verified",
                    "an independent read proved the exact expected postcondition",
                    state_source="system_verification",
                    verification_event_id=verification_event_id,
                    verification_capability=capability,
                )
            )
            intervention = next(
                (
                    row
                    for row in projection["interventions"].values()
                    if row.get("attempt_id") == attempt["attempt_id"]
                    and row.get("status") in {"open", "acknowledged"}
                ),
                None,
            )
            if intervention:
                specs.append(
                    {
                        "type": "intent.intervention_resolved",
                        "intervention_id": intervention["intervention_id"],
                        "attempt_id": attempt["attempt_id"],
                        "intent_id": attempt.get("intent_id"),
                        "intent_revision": attempt.get("intent_revision"),
                        "provider": attempt.get("provider"),
                        "session_id": attempt.get("session_id"),
                        "task_id": attempt.get("task_id"),
                        "capability": attempt.get("capability"),
                        "effect": attempt.get("effect"),
                        "target_sha256": attempt.get("target_sha256"),
                        "decision": "system_verified",
                        "evidence": "",
                        "actor": "system-verifier",
                    }
                )
            compensated_attempt_id = str(
                attempt.get("compensates_attempt_id") or ""
            )
            if compensated_attempt_id:
                compensated_intervention = next(
                    (
                        row
                        for row in projection["interventions"].values()
                        if row.get("attempt_id") == compensated_attempt_id
                        and row.get("status") in {"open", "acknowledged"}
                    ),
                    None,
                )
                if compensated_intervention:
                    compensated_attempt = projection["attempts"].get(
                        compensated_attempt_id,
                        {},
                    )
                    specs.append(
                        {
                            "type": "intent.intervention_resolved",
                            "intervention_id": compensated_intervention[
                                "intervention_id"
                            ],
                            "attempt_id": compensated_attempt_id,
                            "intent_id": compensated_attempt.get("intent_id"),
                            "intent_revision": compensated_attempt.get(
                                "intent_revision"
                            ),
                            "provider": compensated_attempt.get("provider"),
                            "session_id": compensated_attempt.get("session_id"),
                            "task_id": compensated_attempt.get("task_id"),
                            "capability": compensated_attempt.get("capability"),
                            "effect": compensated_attempt.get("effect"),
                            "target_sha256": compensated_attempt.get(
                                "target_sha256"
                            ),
                            "decision": "system_compensated",
                            "evidence": "",
                            "actor": "system-verifier",
                            "compensated_by_attempt_id": attempt["attempt_id"],
                        }
                    )
        return specs, list(selected_ids)

    projection, verified = _mutate(contract_path, mutation)
    return [dict(projection["attempts"][attempt_id]) for attempt_id in verified]


def _legacy_event_resource_identity(
    event: dict[str, Any],
    target: str,
) -> tuple[str, Path | str | None, dict[str, str], bool]:
    """Recover a conservative identity for callers predating resource keys.

    Only syntax-level URI equivalence, an explicit typed context, or a local
    path with a retained resolution base is safe to derive.  The boolean is
    false when no such proof exists so callers can fail closed instead of
    treating an empty key as proof that no debt matches.
    """
    context = event.get("context")
    if not isinstance(context, dict):
        context = {}
    explicit_key = str(
        event.get("effect_resource_key")
        or context.get("effect_resource_key")
        or context.get("resource_key")
        or ""
    ).strip()
    base = str(
        event.get("effect_resource_base")
        or event.get("resource_base")
        or context.get("effect_resource_base")
        or context.get("resource_base")
        or context.get("cwd")
        or context.get("workspace_root")
        or ""
    ) or None
    if explicit_key:
        explicit_context = (
            event.get("effect_resource_context")
            or event.get("resource_context")
            or context.get("effect_resource_context")
            or context.get("resource_context")
        )
        if not isinstance(explicit_context, dict):
            _version, explicit_kind, _payload, _prefix = _resource_key_parts(
                explicit_key,
                allow_legacy=False,
            )
            if explicit_kind == "mcp":
                explicit_context = {
                    "server": event.get("server") or context.get("server"),
                    "resource_kind": (
                        event.get("resource_kind") or context.get("resource_kind")
                    ),
                    "identifier": (
                        event.get("identifier") or context.get("identifier") or target
                    ),
                }
            elif explicit_kind == "git":
                explicit_context = {
                    field: event.get(field) or context.get(field)
                    for field in ("remote", "ref", "oid")
                }
            elif explicit_kind == "opaque":
                explicit_context = {
                    "schema": event.get("resource_schema") or context.get("resource_schema"),
                    "value": event.get("resource_value") or context.get("resource_value"),
                }
            else:
                explicit_context = None
        _kind, normalized_context, _relation = _validate_external_resource_key(
            explicit_key,
            target=target,
            base=base,
            resource_context=explicit_context,
        )
        return explicit_key, base, normalized_context, True
    if not target or target.startswith("["):
        return "", base, {}, False

    event_kind = str(event.get("kind") or event.get("type") or "").lower()
    identity_hint = str(
        event.get("effect_resource_kind")
        or context.get("effect_resource_kind")
        or context.get("target_kind")
        or ""
    ).lower()
    semantic_kind = str(context.get("resource_kind") or "")
    if not identity_hint and semantic_kind.lower() in {
        "git",
        "mcp",
        "opaque",
        "path",
        "uri",
        "url",
    }:
        identity_hint = semantic_kind.lower()

    try:
        if identity_hint in {"uri", "url"}:
            return canonical_resource_key(target, kind="uri"), base, {}, True

        if identity_hint == "path" or (
            event_kind in {"tool", "file_change", "file_changes"}
            and str(event.get("effect") or "") in {"local_write", "read"}
        ):
            if not base:
                return "", None, {}, False
            return canonical_resource_key(target, kind="path", base=base), base, {}, True

        server = str(event.get("server") or context.get("server") or "")
        if event_kind == "mcp" and server and semantic_kind:
            normalized_context = {
                "server": server,
                "resource_kind": semantic_kind,
                "identifier": target,
            }
            return (
                canonical_resource_key((server, semantic_kind, target), kind="mcp"),
                base,
                normalized_context,
                True,
            )
    except (InterventionError, OSError, RuntimeError, ValueError):
        return "", base, {}, False
    return "", base, {}, False


def material_event_blocker(contract_path: Path, event: dict[str, Any]) -> dict[str, Any] | None:
    """Block only work that depends on the same unresolved effect target.

    An old implementation treated provider/session as one global serial lane.
    One unknown remote callback therefore froze unrelated files, MCP objects,
    plugin operations and even control-plane repairs.  The durable attempt is
    still authoritative, but its debt now follows the exact target (or an
    explicit dependency) instead of every later material action in the lane.
    """
    if event.get("phase") != "started":
        return None
    if event.get("supervision_domain") == "execution_passthrough":
        return None
    effect = str(event.get("effect") or "unknown")
    kind = str(event.get("kind") or "tool")
    uncertainty = str(event.get("uncertainty_kind") or "")
    material_unknown = uncertainty in {
        "unresolved_local_write", "unresolved_external_write",
    }
    if (
        effect not in {"local_write", "external_write", "destructive"}
        and not material_unknown
        and not (
            kind == "mcp"
            and effect != "read"
            and uncertainty != "unclassified_read_candidate"
        )
    ):
        return None
    projection = load_projection(contract_path)
    provider = str(event.get("provider") or "unknown")
    session_id = str(event.get("session_id") or "")
    fingerprint = str(event.get("fingerprint") or "")
    event_target = str(event.get("target") or "")
    unresolved_target = (
        not event_target
        or event_target.startswith("[unresolved-")
    )
    resource_key, resource_base, resource_context, _resource_identity_resolved = (
        _legacy_event_resource_identity(event, event_target)
    )
    grant = _matching_retry(
        projection,
        fingerprint=fingerprint,
        operation_fingerprint=str(
            event.get("effect_operation_fingerprint") or ""
        ),
        provider=provider,
        session_id=session_id,
    )
    if grant:
        granted_attempt = projection["attempts"].get(grant.get("attempt_id"), {})
        if (
            isinstance(granted_attempt, dict)
            and settlement_resource_match(
                granted_attempt,
                target=event_target,
                resource_key=resource_key,
                resource_base=resource_base,
                resource_context=resource_context,
            )
            == "proved_same"
        ):
            return None
    # Effect truth belongs to the resource, not to the terminal that happened
    # to dispatch it.  A second session must not duplicate a write merely
    # because the original completion callback was lost elsewhere.
    target_active = blocking_attempts(projection)
    quarantined_attempt_ids = {
        str(row.get("attempt_id") or "")
        for row in terminal_quarantined_attempts(projection)
    }
    dependency = str(
        event.get("depends_on_attempt_id")
        or event.get("verification_for")
        or ""
    )
    active = [
        attempt
        for attempt in target_active
        if (
            (dependency and attempt.get("attempt_id") == dependency)
            or (
                not dependency
                and (
                    (
                        unresolved_target
                        or blocker_resource_match(
                            attempt,
                            target=event_target,
                            resource_key=resource_key,
                            resource_base=resource_base,
                            resource_context=resource_context,
                        )
                    )
                    and not _terminal_unresolved_figma_debt_allows_independent_operation(
                        attempt,
                        quarantined_attempt_ids=quarantined_attempt_ids,
                        intent_id=str(event.get("intent_id") or ""),
                        intent_revision=event.get("intent_revision") or 0,
                        capability=str(event.get("capability") or ""),
                        operation_fingerprint=str(
                            event.get("effect_operation_fingerprint") or ""
                        ),
                    )
                )
            )
        )
    ]
    if not active:
        return None
    raw_target_sha256 = _target_digest(event_target)
    exact_raw = []
    for candidate in active:
        candidate_history = candidate.get("identity_history")
        aliases = (
            candidate_history
            if isinstance(candidate_history, list)
            and all(isinstance(identity, dict) for identity in candidate_history)
            else []
        )
        if any(
            identity.get("target_sha256") == raw_target_sha256
            for identity in [*aliases, candidate]
        ):
            exact_raw.append(candidate)
    selected = exact_raw or active
    attempt = sorted(selected, key=lambda row: str(row.get("created_at") or ""))[0]
    intervention_rows = [
        row
        for row in projection["interventions"].values()
        if row.get("attempt_id") == attempt["attempt_id"]
    ]
    intervention = intervention_rows[-1] if intervention_rows else None
    return {
        "attempt_id": attempt["attempt_id"],
        "attempt_state": attempt["state"],
        "intervention_id": intervention.get("intervention_id") if intervention else None,
        "intervention_status": intervention.get("status") if intervention else None,
        "decision": intervention.get("decision") if intervention else None,
        "retry_consumed_by": (
            intervention.get("retry_consumed_by") if intervention else None
        ),
        "reprobe_consumed_by": (
            intervention.get("reprobe_consumed_by") if intervention else None
        ),
        "takeover_provider": (
            (intervention.get("takeover_provider") or intervention.get("provider"))
            if intervention
            else None
        ),
        "takeover_session_id": (
            (
                intervention.get("takeover_session_id")
                or intervention.get("session_id")
            )
            if intervention
            else None
        ),
        "target_sha256": attempt.get("target_sha256"),
        "resource_sha256": attempt.get("resource_sha256"),
    }


def open_interventions(contract_path: Path) -> list[dict[str, Any]]:
    projection = load_projection(contract_path)
    attempts = projection.get("attempts", {})
    return [
        dict(row)
        for row in projection["interventions"].values()
        if row.get("status") in {"open", "acknowledged"}
        and not is_legacy_git_control_attempt(
            attempts.get(str(row.get("attempt_id") or ""), {})
        )
    ]


def summary(contract_path: Path) -> dict[str, Any]:
    projection = load_projection(contract_path)
    attempts = list(projection["attempts"].values())
    interventions = list(projection["interventions"].values())
    by_state: dict[str, int] = {}
    by_decision: dict[str, int] = {}
    for attempt in attempts:
        state = str(attempt.get("state") or "unknown")
        by_state[state] = by_state.get(state, 0) + 1
    for intervention in interventions:
        decision = str(intervention.get("decision") or "unresolved")
        by_decision[decision] = by_decision.get(decision, 0) + 1
    unresolved = [
        row
        for row in interventions
        if row.get("status") != "resolved"
        and not is_legacy_git_control_attempt(
            projection["attempts"].get(str(row.get("attempt_id") or ""), {})
        )
    ]
    return {
        "schema": "sulde-intervention-summary-v1",
        "attempts": len(attempts),
        "attempts_by_state": dict(sorted(by_state.items())),
        "interventions": len(interventions),
        "interventions_open": len(unresolved),
        "interventions_by_decision": dict(sorted(by_decision.items())),
        "oldest_open_at": min((str(row.get("opened_at")) for row in unresolved), default=None),
        "event_store": str(event_store_path(contract_path)),
    }


def _legacy_retry_chain_reaches_terminal(
    attempt: dict[str, Any],
    attempts: dict[str, dict[str, Any]],
    interventions: list[dict[str, Any]],
    *,
    seen: set[str] | None = None,
) -> bool:
    """Prove that one historical unknown was replaced by a settled v1 retry."""
    attempt_id = str(attempt.get("attempt_id") or "")
    visited = set(seen or ())
    if not attempt_id or attempt_id in visited:
        return False
    visited.add(attempt_id)
    for intervention in interventions:
        if (
            intervention.get("attempt_id") != attempt_id
            or intervention.get("status") != "resolved"
            or intervention.get("decision") != "retry_authorized"
            or intervention.get("legacy_resolution_replayed") is not True
        ):
            continue
        replacement_id = str(intervention.get("retry_consumed_by") or "")
        replacement = attempts.get(replacement_id)
        if not isinstance(replacement, dict):
            continue
        if (
            replacement.get("retry_intervention_id")
            != intervention.get("intervention_id")
            or replacement.get("predecessor_attempt_id") != attempt_id
            or replacement.get("provider") != attempt.get("provider")
            or replacement.get("session_id") != attempt.get("session_id")
            or replacement.get("task_id") != attempt.get("task_id")
            or replacement.get("capability") != attempt.get("capability")
            or replacement.get("effect") != attempt.get("effect")
            or replacement.get("target") != attempt.get("target")
            or replacement.get("target_sha256") != attempt.get("target_sha256")
            or replacement.get("fingerprint") != attempt.get("fingerprint")
        ):
            continue
        if (
            replacement.get("legacy_terminal_replayed") is True
            and replacement.get("state")
            in {"system_verified", "human_attested_success"}
        ):
            return True
        if (
            replacement.get("state") == "unknown"
            and _legacy_retry_chain_reaches_terminal(
                replacement,
                attempts,
                interventions,
                seen=visited,
            )
        ):
            return True
    return False


def blocking_attempts(projection: dict[str, Any]) -> list[dict[str, Any]]:
    """Return attempts whose external truth still forbids dependent writes/cleanup."""
    interventions = list(projection.get("interventions", {}).values())
    attempts = projection.get("attempts", {})
    blocked: list[dict[str, Any]] = []
    for attempt in attempts.values():
        # Historical Git attempts remain append-only audit evidence, but Git
        # no longer belongs to Guardian's control or dependency domain.
        if is_legacy_git_control_attempt(attempt):
            continue
        capability = str(attempt.get("capability") or "").lower()
        resource_context = (
            attempt.get("resource_context")
            if isinstance(attempt.get("resource_context"), dict)
            else {}
        )
        server_tokens = {
            token
            for token in re.split(
                r"[^a-z0-9]+",
                str(resource_context.get("server") or "").lower(),
            )
            if token
        }
        capability_tokens = {
            token
            for token in re.split(r"[^a-z0-9]+", capability)
            if token
        }
        # Figma is an Agent/host execution domain.  Preserve every historical
        # attempt and intervention verbatim for audit, but never turn those
        # rows into a dispatch or global-readiness blocker.
        if (
            "figma" in server_tokens
            or "figma" in capability_tokens
            or str(resource_context.get("resource_kind") or "").lower()
            == "figma"
        ):
            continue
        # Reads are audit evidence, never unresolved external-write debt. Keep
        # their complete history while excluding them from material/readiness
        # blockers, including migrated rows without replay authority.
        if attempt.get("effect") == "read":
            continue
        if attempt.get("replay_authoritative") is not True:
            if (
                attempt.get("legacy_terminal_replayed") is True
                and attempt.get("state")
                in {"system_verified", "human_attested_success", "confirmed_failed"}
            ):
                continue
            if (
                attempt.get("state") == "unknown"
                and _legacy_retry_chain_reaches_terminal(
                    attempt,
                    attempts,
                    interventions,
                )
            ):
                continue
            blocked.append(dict(attempt))
            continue
        state = attempt.get("state")
        if state in {"dispatched", "accepted", "verifying"}:
            blocked.append(dict(attempt))
            continue
        if state != "unknown":
            continue
        matching = [
            row
            for row in interventions
            if row.get("attempt_id") == attempt.get("attempt_id")
        ]
        intervention = matching[-1] if matching else None
        if not intervention or intervention.get("status") != "resolved":
            blocked.append(dict(attempt))
        elif intervention.get("decision") in {"reprobe_authorized", "abort"}:
            # Abort is terminal for the intervention workflow, not evidence of
            # external settlement.  The unknown attempt therefore remains in
            # the authoritative same-resource safety set.
            blocked.append(dict(attempt))
        elif (
            intervention.get("decision") == "retry_authorized"
            and not intervention.get("retry_consumed_by")
        ):
            blocked.append(dict(attempt))
    return blocked


def terminal_quarantined_attempts(
    projection: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return unknown debt whose latest intervention terminally aborted.

    Quarantine preserves the attempt in ``blocking_attempts`` for exact
    resource matching while preventing abandoned historical debt from acting
    as a global current-lane readiness gate.
    """
    interventions = list(projection.get("interventions", {}).values())
    quarantined: list[dict[str, Any]] = []
    for attempt in projection.get("attempts", {}).values():
        if attempt.get("state") != "unknown":
            continue
        matching = [
            row
            for row in interventions
            if row.get("attempt_id") == attempt.get("attempt_id")
        ]
        latest = matching[-1] if matching else None
        if (
            latest
            and latest.get("status") == "resolved"
            and latest.get("decision") == "abort"
        ):
            quarantined.append(dict(attempt))
    return quarantined


def readiness_blocking_attempts(
    projection: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project blockers for the global current-lane operational gate."""
    quarantined_ids = {
        str(row.get("attempt_id") or "")
        for row in terminal_quarantined_attempts(projection)
    }
    return [
        row
        for row in blocking_attempts(projection)
        if str(row.get("attempt_id") or "") not in quarantined_ids
    ]


def inventory(home: Path) -> dict[str, Any]:
    """Aggregate interactive and registered L3 stores without mutating them."""
    stores: set[Path] = set()
    intent_root = home / "intent"
    if intent_root.is_dir():
        stores.update(intent_root.glob("**/*.interventions.jsonl"))
    pending_path = home / "self-repair" / "pending.json"
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        pending = []
    if isinstance(pending, list):
        for row in pending:
            if not isinstance(row, dict) or not row.get("worktree"):
                continue
            state = Path(str(row["worktree"])) / ".codex-agent"
            if state.is_dir():
                stores.update(state.glob("*.interventions.jsonl"))
    totals = {
        "intervention_stores": 0,
        "effect_attempts": 0,
        "effect_unknown": 0,
        "effect_verifying": 0,
        "effect_blocking": 0,
        "effect_readiness_blocking": 0,
        "effect_quarantined": 0,
        "interventions_open": 0,
        "interventions_resolved": 0,
        "intervention_invalid_stores": 0,
    }
    oldest: str | None = None
    projections: dict[str, tuple[str, dict[str, Any], tuple[str, ...]]] = {}
    conflicted: set[str] = set()

    def register(
        source: str,
        projection: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> None:
        identity = str(projection["contract_sha256"])
        if identity in conflicted:
            return
        event_ids = tuple(str(row.get("event_id") or "") for row in rows)
        existing = projections.get(identity)
        if existing is None:
            projections[identity] = (source, projection, event_ids)
            return
        existing_ids = existing[2]
        if event_ids == existing_ids:
            return
        if len(event_ids) > len(existing_ids) and event_ids[: len(existing_ids)] == existing_ids:
            projections[identity] = (source, projection, event_ids)
            return
        if len(existing_ids) > len(event_ids) and existing_ids[: len(event_ids)] == event_ids:
            return
        totals["intervention_invalid_stores"] += 1
        conflicted.add(identity)
        projections.pop(identity, None)

    for store in sorted(stores):
        suffix = ".interventions.jsonl"
        contract = store.with_name(store.name[: -len(suffix)] + ".json")
        try:
            rows = _read_rows(store)
            projection = replay(contract, rows)
        except (InterventionError, OSError, UnicodeError):
            totals["intervention_invalid_stores"] += 1
            continue
        register(str(store), projection, rows)
    archive_root = home / "interventions" / "archive"
    if archive_root.is_dir():
        for manifest in sorted(archive_root.glob("*/manifest.json")):
            try:
                projection = load_archived_projection(manifest)
                archive = json.loads(manifest.read_text(encoding="utf-8"))
                rows = _read_rows(manifest.parent / str(archive["events_file"]))
            except (
                InterventionError,
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
            ):
                totals["intervention_invalid_stores"] += 1
                continue
            register(str(manifest), projection, rows)
    for _source, projection, _event_ids in projections.values():
        totals["intervention_stores"] += 1
        attempts = list(projection["attempts"].values())
        interventions = list(projection["interventions"].values())
        totals["effect_attempts"] += len(attempts)
        totals["effect_unknown"] += sum(row.get("state") == "unknown" for row in attempts)
        totals["effect_verifying"] += sum(row.get("state") == "verifying" for row in attempts)
        totals["effect_blocking"] += len(blocking_attempts(projection))
        totals["effect_readiness_blocking"] += len(
            readiness_blocking_attempts(projection)
        )
        totals["effect_quarantined"] += len(
            terminal_quarantined_attempts(projection)
        )
        attempts_by_id = projection["attempts"]
        open_rows = [
            row
            for row in interventions
            if row.get("status") != "resolved"
            and not is_legacy_git_control_attempt(
                attempts_by_id.get(str(row.get("attempt_id") or ""), {})
            )
        ]
        totals["interventions_open"] += len(open_rows)
        totals["interventions_resolved"] += len(interventions) - len(open_rows)
        candidate = min((str(row.get("opened_at")) for row in open_rows), default=None)
        if candidate and (oldest is None or candidate < oldest):
            oldest = candidate
    return {**totals, "intervention_oldest_open_at": oldest}


def _notification_root(contract_path: Path) -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    for parent in contract_path.expanduser().absolute().parents:
        if parent.name == "intent":
            return parent.parent
        if parent.name == ".codex-agent":
            return parent
    return contract_path.expanduser().absolute().parent


def _append_inbox(contract_path: Path, row: dict[str, Any]) -> None:
    path = _notification_root(contract_path) / "interventions" / "inbox.jsonl"
    with _store_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


def _notify_human(contract_path: Path, intervention: dict[str, Any]) -> None:
    """Persist an inbox notification, then best-effort a host-neutral OS alert."""
    identifier = str(intervention["intervention_id"])
    _append_inbox(
        contract_path,
        {
            "schema": "sulde-intervention-notification-v1",
            "at": now_iso(),
            "intervention_id": identifier,
            "attempt_id": intervention["attempt_id"],
            "contract_sha256": contract_digest(contract_path),
            "status": "attention_required",
        }
    )
    if os.environ.get("SULDE_NOTIFY", "").lower() == "off":
        return
    message = f"需要人工确认外部操作结果：{identifier}"
    try:
        if sys.platform == "darwin":
            safe = message.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["/usr/bin/osascript", "-e", f'display notification "{safe}" with title "Sulde"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        elif os.name == "nt":
            subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "Add-Type -AssemblyName System.Windows.Forms; "
                        "$n=New-Object System.Windows.Forms.NotifyIcon; "
                        "$n.Icon=[System.Drawing.SystemIcons]::Warning; "
                        "$n.BalloonTipTitle='Sulde'; "
                        f"$n.BalloonTipText='{message}'; "
                        "$n.Visible=$true; $n.ShowBalloonTip(5000)"
                    ),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    except OSError:
        return

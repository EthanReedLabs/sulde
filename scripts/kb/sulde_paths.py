#!/usr/bin/env python3
"""Canonical provider-neutral Sulde filesystem layout."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat


CURRENT_HOME_SCHEMA = "sulde-current-home-v1"
CONTRACT_IDENTITY_SCHEMA = "sulde-contract-identity-map-v1"
CONTRACT_IDENTITY_FILE = "contract-identities.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SuldePathError(RuntimeError):
    """A provider-neutral path authority is missing or unsafe."""


@dataclass(frozen=True)
class SuldeLayout:
    root: Path
    bin: Path
    control: Path
    state: Path
    data: Path
    kb: Path
    cache: Path
    logs: Path
    venv: Path
    artifacts: Path


def _absolute(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def layout(*, home: Path | None = None) -> SuldeLayout:
    root = _absolute(
        home
        or os.environ.get("SULDE_HOME")
        or (Path.home() / ".sulde")
    )
    data = root / "data"
    compatibility_kb = os.environ.get("SULDE_KB_HOME") if home is None else None
    # Preserve the lexical form of the legacy override.  Existing contracts
    # can bind `/var/...` while macOS resolves the same path as `/private/var/...`.
    kb = Path(compatibility_kb).expanduser() if compatibility_kb else data / "kb"
    return SuldeLayout(
        root=root,
        bin=root / "bin",
        control=root / "control",
        state=root / "state",
        data=data,
        kb=kb,
        cache=root / "cache",
        logs=root / "logs",
        venv=root / "venv",
        artifacts=root / "artifacts",
    )


def sulde_home() -> Path:
    return layout().root


def kb_home() -> Path:
    """Compatibility accessor; new state must prefer the typed subroots."""
    return layout().kb


def sync_repository_path(configured: str, *, home: Path | None = None) -> Path:
    """One executor/verifier path contract; never redirect legacy data silently."""
    root = (home or kb_home()).expanduser().resolve()
    candidate = Path(configured).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink():
        raise SuldePathError("sync repository cannot be a symlink")
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise SuldePathError("sync repository must be inside the Sulde data root; migration approval required") from error
    if resolved.name != "mem-sync-repo" or not relative.parts:
        raise SuldePathError("sync repository must be a mem-sync-repo child")
    return resolved


def launcher_home(kb: Path) -> Path:
    """Map the neutral KB leaf to its product-wide launcher/control root.

    Portable and legacy KB homes keep their historic self-contained ``bin``
    directory.  Only the canonical ``SULDE_HOME/data/kb`` leaf is projected
    back to ``SULDE_HOME``.
    """
    selected = layout()
    candidate = _absolute(kb)
    explicit = os.environ.get("SULDE_LAUNCHER_HOME")
    # The override belongs to the configured data root, not every unrelated
    # portable/test home passed by a caller in the same process.
    if explicit and candidate == _absolute(selected.kb):
        return _absolute(explicit)
    neutral_kb = _absolute(selected.root / "data" / "kb")
    return selected.root if candidate == neutral_kb else candidate


def _path_digest(path: Path) -> str:
    return hashlib.sha256(
        str(path).encode("utf-8", errors="replace")
    ).hexdigest()


def _protected_json(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    try:
        metadata = path.stat(follow_symlinks=False)
        payload_bytes = path.read_bytes()
        payload = json.loads(payload_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SuldePathError(f"{label} is unavailable: {error}") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise SuldePathError(f"{label} is not a protected regular file")
    if os.name != "nt" and (
        metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise SuldePathError(f"{label} is not owner-only")
    if not isinstance(payload, dict):
        raise SuldePathError(f"{label} is not one JSON object")
    return payload, payload_bytes


def contract_identity_digest(contract: Path) -> str:
    """Return the append-only identity preserved across a verified home move.

    A contract that did not exist in the migrated source keeps the ordinary
    digest of its current absolute path.  Existing migrated contracts use only
    the source identity explicitly sealed by the active home pointer.
    """
    current = _absolute(contract)
    current_digest = _path_digest(current)
    selected = layout()
    neutral_kb = _absolute(selected.root / "data" / "kb")
    try:
        relative = current.relative_to(neutral_kb)
    except ValueError:
        return current_digest

    pointer_path = selected.control / "current-home.json"
    if not pointer_path.exists() and not pointer_path.is_symlink():
        return current_digest
    pointer, _pointer_bytes = _protected_json(pointer_path, "current home pointer")
    if (
        pointer.get("schema") != CURRENT_HOME_SCHEMA
        or pointer.get("status") != "active"
        or _absolute(str(pointer.get("sulde_home") or "")) != selected.root
        or _absolute(str(pointer.get("kb_home") or "")) != neutral_kb
        or not isinstance(pointer.get("transaction_id"), str)
        or not pointer["transaction_id"]
    ):
        raise SuldePathError("current home pointer does not bind this neutral home")

    expected_map_sha256 = pointer.get("contract_identity_map_sha256")
    if not isinstance(expected_map_sha256, str) or not _SHA256_RE.fullmatch(
        expected_map_sha256
    ):
        raise SuldePathError("current home pointer has no contract identity authority")
    identity_path = selected.control / CONTRACT_IDENTITY_FILE
    identity_map, identity_bytes = _protected_json(
        identity_path, "contract identity map"
    )
    if hashlib.sha256(identity_bytes).hexdigest() != expected_map_sha256:
        raise SuldePathError("contract identity map digest differs from current home")
    if (
        identity_map.get("schema") != CONTRACT_IDENTITY_SCHEMA
        or identity_map.get("transaction_id") != pointer["transaction_id"]
        or _absolute(str(identity_map.get("source") or ""))
        != _absolute(str(pointer.get("source") or ""))
        or _absolute(str(identity_map.get("kb_home") or "")) != neutral_kb
    ):
        raise SuldePathError("contract identity map does not match current home")
    identities = identity_map.get("identities")
    if not isinstance(identities, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or not _SHA256_RE.fullmatch(value)
        for key, value in identities.items()
    ):
        raise SuldePathError("contract identity map entries are invalid")
    relative_key = relative.as_posix()
    legacy_digest = identities.get(relative_key)
    return legacy_digest if isinstance(legacy_digest, str) else current_digest

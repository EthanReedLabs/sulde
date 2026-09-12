#!/usr/bin/env python3
"""Provision and observe the production RecoveryLane without ordinary policy."""

from __future__ import annotations

import os
from pathlib import Path
import secrets
import stat
import tempfile
from typing import Any

from recovery_lane import REQUEST_SCHEMA, ROUTE_SPECS, RecoveryLane, RecoveryLaneError
from sulde_paths import launcher_home


RECOVERY_KEY_NAME = "recovery.key"
RECOVERY_STATE_NAME = "recovery-lane.jsonl"
_REQUIRED_READ_ROUTES = frozenset({"status", "doctor", "readback"})


class ProductionRecoveryReadinessError(RuntimeError):
    """The independent production recovery authority is unavailable or unsafe."""


def recovery_paths(kb_home: Path) -> tuple[Path, Path]:
    root = launcher_home(kb_home.expanduser())
    return root / "control" / RECOVERY_KEY_NAME, root / "state" / RECOVERY_STATE_NAME


def _trusted_uid() -> int:
    return os.geteuid() if hasattr(os, "geteuid") else os.getuid()


def _private_directory(path: Path, *, label: str) -> None:
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise ProductionRecoveryReadinessError(
            f"{label} is unavailable: {error}"
        ) from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != _trusted_uid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise ProductionRecoveryReadinessError(
            f"{label} identity or permissions are invalid"
        )


def _private_key(path: Path) -> bytes:
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        chunks: list[bytes] = []
        remaining = 33
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
    except OSError as error:
        raise ProductionRecoveryReadinessError(
            f"recovery seal key is unavailable: {error}"
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != _trusted_uid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_nlink != 1
    ):
        raise ProductionRecoveryReadinessError(
            "recovery seal key identity or permissions are invalid"
        )
    if len(payload) != 32:
        raise ProductionRecoveryReadinessError(
            "recovery seal key must contain exactly 32 bytes"
        )
    return payload


def provision_recovery_key(kb_home: Path) -> Path:
    """Atomically provision one persistent owner-only recovery authority.

    Install/lifecycle code owns this operation. Hooks and readiness readers only
    consume the already provisioned key and can never manufacture authority.
    """
    key_path, state_path = recovery_paths(kb_home)
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private_directory(key_path.parent, label="recovery control directory")
    _private_directory(state_path.parent, label="recovery state directory")
    try:
        _private_key(key_path)
        return key_path
    except ProductionRecoveryReadinessError:
        if os.path.lexists(key_path):
            # Never replace malformed, aliased, or concurrently published authority.
            _private_key(key_path)
            return key_path

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{RECOVERY_KEY_NAME}.",
        dir=key_path.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        key = secrets.token_bytes(32)
        if os.write(descriptor, key) != len(key):
            raise OSError("recovery seal key write was incomplete")
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, key_path)
        except FileExistsError:
            _private_key(key_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    _private_key(key_path)
    return key_path


def observe_recovery_truth(kb_home: Path) -> dict[str, Any]:
    """Return bounded structural truth without creating a journal or lock file."""
    key_path, state_path = recovery_paths(kb_home)
    typed_route_available = bool(
        REQUEST_SCHEMA == "sulde-recovery-request-v1"
        and _REQUIRED_READ_ROUTES.issubset(ROUTE_SPECS)
        and Path(__file__).with_name("production_recovery.py").is_file()
    )
    capabilities = {
        "diagnosis_available": True,
        "human_confirmation": "unobserved",
        "repair_execution": "unverified",
        "recovery_verified": False,
    }
    try:
        _private_directory(key_path.parent, label="recovery control directory")
        _private_directory(state_path.parent, label="recovery state directory")
        key = _private_key(key_path)
        lane = RecoveryLane(
            str(state_path),
            seal_key=key,
            wall_clock=__import__("time").time,
            monotonic_clock=__import__("time").monotonic,
        )
        try:
            snapshot = lane.state.snapshot_read_only()
        finally:
            lane.state.close()
    except (OSError, RuntimeError, RecoveryLaneError) as error:
        return {
            **capabilities,
            "lane_available": False,
            "typed_route_available": typed_route_available,
            "snapshot_status": "unavailable",
            "hook_generation_status": "unknown",
            "skill_catalog_status": "unknown",
            "probe_reason": type(error).__name__,
        }
    events = snapshot.get("events", [])
    terminals = [e["payload"] for e in events if e.get("event_type") == "recovery_terminal_recorded"]
    receipts = {e["payload"].get("receipt_id"): e["payload"] for e in events if e.get("event_type") == "recovery_verifier_observed"}
    latest = terminals[-1] if terminals else None
    if latest:
        receipt = receipts.get(latest.get("result", {}).get("verifier_receipt_id"), {})
        verified = (latest.get("status") == "succeeded"
                    and latest.get("reason") == "independent_verification_passed"
                    and receipt.get("status") == "passed"
                    and all(receipt.get(k) == latest.get(k) for k in ("run_id", "action", "target_identity")))
        capabilities.update(repair_execution="verified" if verified else latest.get("status", "unverified"), recovery_verified=verified,
                            last_terminal={k: latest.get(k) for k in ("run_id", "action", "status", "reason", "observed_wall")})
    terminal_ids = {t.get("run_id") for t in terminals}
    active = [e["payload"] for e in events if e.get("event_type") == "recovery_run_prepared" and e["payload"].get("run_id") not in terminal_ids]
    return {
        **capabilities,
        "lane_available": True,
        "typed_route_available": typed_route_available,
        "snapshot_status": "current" if state_path.is_file() else "empty",
        "hook_generation_status": "unknown",
        "skill_catalog_status": "unknown",
        "active_run": {k: active[-1].get(k) for k in ("run_id", "action")} if active else None,
    }

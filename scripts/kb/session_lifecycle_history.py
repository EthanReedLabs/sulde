"""Explicit bounded migration of committed historical lifecycle evidence.

Never imported by the per-tool reader. Old release pairs survive worktree
deletion: the source is closed and the independent completion anchor binds the
exact source/target, release digest and completed Git readback. A prepared target
or a human Allow alone is NOT a historical committed handoff. Such handoffs need
an already recorded signed transition or the current-mapping recovery route.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from file_lock import lock_exclusive_nonblocking, unlock
from host_observation_index import _atomic_signed, _encoded, _private_file
import session_lifecycle_lineage as lineage

MAX_CONTRACTS = 256
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024


def _time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("history time is not a string")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("history time lacks timezone")
    return result


def _recorded_workspace_id(value: str) -> str:
    # Release records already contain the physical registered-worktree root.
    # Rediscovering its Git root after deletion silently selects the enclosing
    # repository, destroying the very historical identity being reconstructed.
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


class Snapshot:
    def __init__(self, home: Path):
        self.root = (home / "intent").resolve()
        self.files: dict[Path, tuple[bytes, tuple[int, int, int, int]]] = {}
        self.total = 0

    def read(self, path: Path) -> dict:
        path = path.absolute()
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("history source escapes the intent root")
        if path not in self.files:
            with os.fdopen(_private_file(path, os.O_RDONLY), "rb") as handle:
                before = os.fstat(handle.fileno())
                raw = handle.read(MAX_FILE_BYTES + 1)
                after = os.fstat(handle.fileno())
            identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
            if len(raw) > MAX_FILE_BYTES or identity(before) != identity(after):
                raise ValueError("history source oversized or changed while reading")
            self.total += len(raw)
            if self.total > MAX_TOTAL_BYTES:
                raise ValueError("history byte budget exceeded")
            self.files[path] = (raw, identity(after))
        result = json.loads(self.files[path][0])
        if not isinstance(result, dict):
            raise ValueError("history source is not an object")
        return result

    def unchanged(self) -> bool:
        for path, (raw, identity) in self.files.items():
            with os.fdopen(_private_file(path, os.O_RDONLY), "rb") as handle:
                now = os.fstat(handle.fileno())
                if (now.st_dev, now.st_ino, now.st_size, now.st_mtime_ns) != identity:
                    return False
                if handle.read(len(raw) + 1) != raw:
                    return False
        return True


def _release_edge(snapshot: Snapshot, path: Path, anchor: dict, *,
                  provider: str, session_id: str, now: datetime) -> dict | None:
    from intent_guardian_parts.session_workspace import _cleanup_record

    raw = anchor.get("workspace_cleanup")
    if not isinstance(raw, dict) or raw.get("provider") != provider or raw.get("session_id") != session_id:
        return None
    record = _cleanup_record(anchor)
    if record["status"] != "complete":
        return None  # no historical committed mapping can be inferred yet
    for name in ("source_contract", "source_workspace", "target_workspace", "source_git_common_dir"):
        value = record[name]
        if (not isinstance(value, str) or not value or not Path(value).is_absolute()
                or ".." in Path(value).parts or str(Path(value)) != value):
            raise ValueError("history resource identity is not an absolute path")
    source_path = Path(record["source_contract"])
    source = snapshot.read(source_path)
    released = source.get("workspace_release")
    if not isinstance(released, dict):
        raise ValueError("completed anchor lacks its closed source")
    if (anchor.get("schema") != "sulde-intent-contract-v1"
            or source.get("schema") != "sulde-intent-contract-v1"
            or source.get("status") != "closed"
            or released.get("schema") != "sulde-workspace-release-source-v1"
            or released.get("authority_transferred") is not False
            or released.get("provider") != provider or released.get("session_id") != session_id
            or released.get("release_id") != record["release_id"]
            or Path(released.get("completion_contract", "")).resolve() != path.resolve()
            or source.get("workspace_root") != record["source_workspace"]
            or anchor.get("workspace_root") != record["target_workspace"]):
        raise ValueError("historical release counterpart differs")
    prepared, closed, completed = (_time(record["released_at"]),
                                  _time(released.get("released_at")), _time(record["completed_at"]))
    if not prepared <= closed <= completed <= now:
        raise ValueError("historical release ordering differs")
    # Use the completed readback time, not the earlier prepared-anchor time,
    # as the conservative upper bound at which the transition was committed.
    evidence = {"cleanup": record, "closed_source": released,
                "source_workspace": source["workspace_root"], "target_workspace": anchor["workspace_root"]}
    return {"source_workspace_id": _recorded_workspace_id(record["source_workspace"]),
            "target_workspace_id": _recorded_workspace_id(record["target_workspace"]),
            "at": completed.isoformat(), "receipt_sha256": hashlib.sha256(record["release_id"].encode()).hexdigest(),
            "evidence_kind": "completed_release_pair",
            "commit_evidence_sha256": hashlib.sha256(_encoded(evidence)).hexdigest(),
            "authority_transferred": False}


def recover_history(home: Path, *, provider: str, session_id: str, dry_run: bool = False) -> dict:
    from host_capabilities import _assert_test_write_isolated, _read_provenance_key
    from intent_guardian_parts.session_workspace import load_session_workspace

    result = {"schema": "sulde-lifecycle-history-recovery-v1", "status": "inconclusive",
              "authority_transferred": False, "source_modified": False,
              "coverage": "verified_release_pairs_and_recorded_transitions"}
    try:
        if not dry_run:
            _assert_test_write_isolated(home, explicit_home=True)
        mapping = load_session_workspace(home, provider, session_id)
        if mapping is None:
            return {**result, "reason": "no_current_session_mapping"}
        snapshot = Snapshot(home)
        paths = []
        for directory in (snapshot.root / "sessions", snapshot.root / "workspaces"):
            if directory.is_symlink():
                raise ValueError("history directory is a symlink")
            if directory.is_dir():
                for path in directory.glob("*.active.json"):
                    paths.append(path)
                    if len(paths) > MAX_CONTRACTS:
                        raise ValueError("history inventory budget exceeded")
        edges, invalid_inventory = [], 0
        for path in sorted(paths):
            try:
                anchor = snapshot.read(path)
            except (UnicodeError, json.JSONDecodeError):
                # A corrupt unrelated inventory entry cannot grant an edge.
                # A referenced counterpart is validated again and fails closed.
                invalid_inventory += 1
                continue
            edge = _release_edge(snapshot, path, anchor, provider=provider,
                                 session_id=session_id, now=datetime.now(timezone.utc))
            if edge is not None:
                edges.append(edge)
        key = _read_provenance_key(home)
        path = lineage.lineage_path(home, provider, session_id)
        if dry_run:
            if not snapshot.unchanged() or load_session_workspace(home, provider, session_id) != mapping:
                raise ValueError("history snapshot changed")
            return {**result, "status": "planned", "verified_edges": edges,
                    "scanned_bytes": snapshot.total, "invalid_inventory": invalid_inventory}
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.parent.is_symlink():
            raise ValueError("lineage directory is a symlink")
        with os.fdopen(_private_file(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT), "r+") as lock:
            lock_exclusive_nonblocking(lock)
            try:
                try:
                    previous = lineage._read(home, provider, session_id, key)
                except FileNotFoundError:
                    previous = []
                seen = {(row["source_workspace_id"], row["target_workspace_id"], row["receipt_sha256"])
                        for row in previous}
                added = [row for row in edges if (row["source_workspace_id"], row["target_workspace_id"], row["receipt_sha256"]) not in seen]
                combined = previous + added
                if len(combined) > lineage.MAX_EDGES:
                    raise ValueError("lineage edge budget exceeded")
                if not snapshot.unchanged() or load_session_workspace(home, provider, session_id) != mapping:
                    raise ValueError("history snapshot changed")
                if added:
                    _atomic_signed(path, {"schema": lineage.SCHEMA, "provider": provider,
                                          "session_id": session_id, "edges": combined}, key)
            finally:
                unlock(lock)
        return {**result, "status": "recovered", "verified_edges": len(edges),
                "added_edges": len(added), "scanned_bytes": snapshot.total,
                "invalid_inventory": invalid_inventory, "mapping_sha256": mapping["mapping_sha256"]}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        return {**result, "reason": str(error)[:200], "error_kind": type(error).__name__}

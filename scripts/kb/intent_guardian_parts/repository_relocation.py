"""Explicit native relocation with frozen evidence and bounded recovery.

A snapshot is NOT an approval. The protected executor separately verifies the
typed execution choice, fences writers, moves/rebinds, verifies its terminal
and retires the fence. Success still leaves task authority paused for review.
Keep the ordinary workspace-handoff same-common-dir check unchanged.
"""

from __future__ import annotations

from approval_invariant import (
    ApprovalInvariantError, load_projection as approvals,
    load_projection as approval_projection, request_is_open,
    verify_request_binding_receipt, request_binding_receipt, decided_request_receipt,
    request_for_binding, decide_typed_approval, event_store_path as approval_store,
)
from intervention import (
    InterventionError, blocking_attempts, load_projection as effects,
    event_store_path as effect_store,
)
import native_decision_journal as native_journal
from native_decision_journal import (
    NativeDecisionJournalError, NativeAuthorityReaders,
    is_legacy_unsealed_prepared_diagnostic, advance_with_authority,
    head_proof_read_only, journal_path, prepare, seal_binding,
    _stable_read_source_bytes, effect_receipt_store_path, contract_receipt_store_path,
    external_head_receipt_store_path, _require_durable_seal_origin, _verify_sealed_approval,
    _decode_authority_events, _decode_rows, replay, verify_recorded_external_head_receipt,
    head_pending_path, _recover_anchored_rows, complete_repository_relocation,
)
from .session_workspace import (
    _validated_mapping, session_workspace_path, relocation_review_contract, _canonical_sha256,
)
from .state import (
    load_contract, policy_digest, contract_lock, audit_path,
    validate_contract, Decision, event_fingerprint,
)
from .historical_retirement import verify
from .repository_relocation_consumers import (
    freeze as freeze_consumers, frozen as frozen_consumer, verify_published,
)
from .native_binding import _native_binding_snapshot, _native_card_sha256
from .resources import _guardian_invocation, parse_native_decision_command

from .relocation_storage import (
    atomic_write, _exclusive_path_lock,
    _digest,
    _canonical,
    _git,
    _read_plan_file,
    _store_home,
    _fence_directory,
    _read_write_fences,
    require_relocation_write_allowed,
    relocation_registration_write,
    _store_snapshot as _snapshot_store_bytes,
    MAX_WORKTREES, MAX_STORE_BYTES, STORE_READ_BYTES, FENCE_SCHEMA,
)

from contextlib import ExitStack, contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any

from .decision_types import IntentGuardianError


# Ledger writers import relocation_storage, never this execution controller.




SCHEMA = "sulde-repository-relocation-evidence-v2"
PATH_FACTS_SCHEMA = "sulde-repository-path-facts-v1"
# Bounded support for whole repositories with retained historical clones and
# evidence archives. Cardinality is independent of the unchanged byte budget.
MAX_ENTRIES = 500_000
MAX_CONTENT_BYTES = 8 * 1024**3
# Recovery stores are not Git indexes. Keep independent, bounded budgets.
MAX_STORE_TOTAL_BYTES = 1024**3


def _store_snapshot(path: Path, *, remaining_bytes: int | None = None,
                    allow_archive_link: bool = False) -> dict[str, Any]:
    """Preserve the controller's existing budget configuration seam."""
    return _snapshot_store_bytes(
        path, remaining_bytes=remaining_bytes, allow_archive_link=allow_archive_link,
        max_bytes=MAX_STORE_BYTES, read_bytes=STORE_READ_BYTES,
    )






def _identity(path: Path) -> dict[str, int]:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise IntentGuardianError("relocation identity must be a physical directory")
    if info.st_uid != os.getuid():
        raise IntentGuardianError("relocation directory belongs to another owner")
    return {"device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode)}




def _git_path(root: Path, *args: str) -> Path:
    raw = Path(os.fsdecode(_git(root, *args).rstrip(b"\n")))
    return _canonical(raw if raw.is_absolute() else root / raw)


def _index_digest(path: Path) -> str:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return ""
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024**2:
            raise IntentGuardianError("relocation index is not a bounded regular file")
        content = hashlib.sha256()
        read_size = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            read_size += len(chunk)
            if read_size > before.st_size:
                raise IntentGuardianError("relocation index grew during observation")
            content.update(chunk)
        after = os.fstat(fd)
        current = path.lstat()
        if (read_size != before.st_size or current.st_ino != before.st_ino
                or after.st_mtime_ns != before.st_mtime_ns or after.st_ctime_ns != before.st_ctime_ns):
            raise IntentGuardianError("relocation index changed during observation")
        return content.hexdigest()
    finally:
        os.close(fd)


def _worktrees(root: Path) -> list[dict[str, Any]]:
    common = root / ".git"
    if _git_path(root, "rev-parse", "--show-toplevel") != root:
        raise IntentGuardianError("relocation source is not the main worktree root")
    if _git_path(root, "rev-parse", "--git-common-dir") != common:
        raise IntentGuardianError("relocation requires an internal main Git directory")
    if os.path.lexists(common / "objects/info/alternates"):
        raise IntentGuardianError("relocation does not support alternate object directories")
    rows = []
    output = _git(root, "worktree", "list", "--porcelain", "-z")
    for block in output.split(b"\0\0"):
        if not block:
            continue
        fields: dict[str, bytes] = {}
        for field in block.split(b"\0"):
            key, _, value = field.partition(b" ")
            name = key.decode("ascii")
            if name in fields:
                raise IntentGuardianError("duplicate relocation worktree field")
            fields[name] = value
        if set(fields) != {"worktree", "HEAD", "branch"}:
            raise IntentGuardianError("relocation requires available unlocked attached worktrees")
        workspace = _canonical(Path(os.fsdecode(fields["worktree"])))
        if not workspace.is_relative_to(root):
            raise IntentGuardianError("relocation has a linked worktree outside the source root")
        relative = workspace.relative_to(root).as_posix()
        if _git_path(workspace, "rev-parse", "--show-toplevel") != workspace:
            raise IntentGuardianError("relocation worktree registration differs")
        if _git_path(workspace, "rev-parse", "--git-common-dir") != common:
            raise IntentGuardianError("relocation worktree uses another Git common-dir")
        git_dir = _git_path(workspace, "rev-parse", "--absolute-git-dir")
        if not git_dir.is_relative_to(common):
            raise IntentGuardianError("relocation worktree has an external Git directory")
        index = git_dir / "index"
        if index.is_symlink():
            raise IntentGuardianError("relocation index cannot be a symlink")
        # This is a raw index digest, distinct from HEAD and checkout contents.
        index_hash = _index_digest(index)
        config = _git(workspace, "config", "--local", "--includes", "--null", "--list")
        if any(entry.partition(b"\n")[0] in {b"core.worktree", b"extensions.worktreeconfig"}
               for entry in config.split(b"\0")):
            raise IntentGuardianError("relocation does not support path-bound worktree configuration")
        if any(entry.startswith(b"160000 ") for entry in _git(workspace, "ls-files", "--stage", "-z").split(b"\0")):
            raise IntentGuardianError("relocation does not support submodule administration")
        head = _git(workspace, "rev-parse", "HEAD").strip()
        branch = _git(workspace, "symbolic-ref", "HEAD").strip()
        if head != fields["HEAD"] or branch != fields["branch"]:
            raise IntentGuardianError("relocation worktree branch/HEAD drifted")
        rows.append({
            "relative_path": relative,
            "identity": _identity(workspace),
            "git_dir": git_dir.relative_to(root).as_posix(),
            "git_identity": _identity(git_dir),
            "head": head.decode("ascii"),
            "branch": os.fsdecode(branch),
            "index_sha256": index_hash,
            "config_sha256": hashlib.sha256(config).hexdigest(),
            "status_sha256": hashlib.sha256(_git(
                workspace, "status", "--porcelain=v1", "-z", "--untracked-files=all",
            )).hexdigest(),
        })
        if len(rows) > MAX_WORKTREES:
            raise IntentGuardianError("relocation worktree inventory exceeds evidence bound")
    if len({row["relative_path"] for row in rows}) != len(rows) or not any(
        row["relative_path"] == "." for row in rows
    ):
        raise IntentGuardianError("relocation worktree inventory is incomplete or duplicated")
    return sorted(rows, key=lambda row: row["relative_path"])


def _content(root: Path, worktrees: list[dict[str, Any]]) -> dict[str, Any]:
    """Hash user data, including ignored data; never follow a content symlink.

    Only Git-owned administrative roots/backlinks are excluded. They need a
    separate repair verifier. No pathname or content is emitted in the result.
    Descriptor-relative traversal prevents a concurrent directory-to-symlink
    swap from redirecting a read outside the frozen tree.
    """
    excluded = {".git"}
    excluded.update(
        f"{row['relative_path']}/.git" for row in worktrees if row["relative_path"] != "."
    )
    digest = hashlib.sha256()
    count = 0
    discovered = 0
    total = 0

    def child_names(descriptor: int, relative: str) -> list[str]:
        nonlocal discovered
        names = []
        # Reserve the GLOBAL budget when discovering each name, including
        # siblings not yet hashed in ancestor directories. listdir() would
        # allocate the entire directory before the first capacity check.
        with os.scandir(descriptor) as entries:
            for entry in entries:
                child = f"{relative}/{entry.name}" if relative else entry.name
                if child in excluded:
                    continue
                discovered += 1
                if discovered > MAX_ENTRIES:
                    raise IntentGuardianError("relocation content entry bound exceeded")
                names.append(entry.name)
        # Preserve the exact existing recursive hash order and snapshot format.
        return sorted(names)

    def visit(descriptor: int, relative: str) -> None:
        nonlocal count, total
        device = os.fstat(descriptor).st_dev
        for name in child_names(descriptor, relative):
            child = f"{relative}/{name}" if relative else name
            count += 1
            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            row: dict[str, Any] = {
                "path": child, "device": before.st_dev, "inode": before.st_ino,
                "mode": before.st_mode,
            }
            if before.st_dev != device:
                raise IntentGuardianError("relocation content crosses a mount boundary")
            if stat.S_ISDIR(before.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    opened = os.fstat(fd)
                    if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                        raise IntentGuardianError("relocation directory changed during read")
                    visit(fd, child)
                finally:
                    os.close(fd)
            elif stat.S_ISREG(before.st_mode):
                total += before.st_size
                if total > MAX_CONTENT_BYTES:
                    raise IntentGuardianError("relocation content byte bound exceeded")
                content = hashlib.sha256()
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                try:
                    opened = os.fstat(fd)
                    if opened != before:
                        raise IntentGuardianError("relocation file changed during open")
                    read_size = 0
                    while True:
                        chunk = os.read(fd, 1024 * 1024)
                        if not chunk:
                            break
                        read_size += len(chunk)
                        if read_size > before.st_size:
                            raise IntentGuardianError("relocation file grew during read")
                        content.update(chunk)
                    after_read = os.fstat(fd)
                    if (read_size != before.st_size or after_read.st_mtime_ns != before.st_mtime_ns
                            or after_read.st_ctime_ns != before.st_ctime_ns):
                        raise IntentGuardianError("relocation file changed during read")
                finally:
                    os.close(fd)
                row.update(size=before.st_size, sha256=content.hexdigest())
            elif stat.S_ISLNK(before.st_mode):
                row["link"] = os.readlink(name, dir_fd=descriptor)
            else:
                raise IntentGuardianError("relocation contains unsupported special file")
            after = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (before.st_dev, before.st_ino, before.st_mode, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_mode, after.st_mtime_ns, after.st_ctime_ns
            ):
                raise IntentGuardianError("relocation content changed during inventory")
            digest.update(bytes.fromhex(_digest(row)))

    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(descriptor, "")
    finally:
        os.close(descriptor)
    return {"entries": count, "bytes": total, "sha256": digest.hexdigest()}


def _small_git_file(path: Path) -> dict[str, Any]:
    """Bounded metadata read, never follow a redirected Git pointer file."""
    _canonical(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                    or before.st_size > 4096 or before.st_nlink != 1):
                raise IntentGuardianError("relocation Git pointer is not a bounded owned regular file")
            payload = os.read(descriptor, 4097)
            after = os.fstat(descriptor)
            current = path.lstat()
            if (len(payload) != before.st_size or after.st_ctime_ns != before.st_ctime_ns
                    or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)):
                raise IntentGuardianError("relocation Git pointer changed during observation")
        finally:
            os.close(descriptor)
        return {"text": payload.decode("utf-8"), "mode": stat.S_IMODE(before.st_mode)}
    except (OSError, UnicodeError) as error:
        raise IntentGuardianError("relocation Git pointer is unavailable or invalid") from error


def _git_link_inventory(source: Path, destination: Path, worktrees: list[dict[str, Any]]) -> list[dict[str, Any]]:
    links = []
    for row in worktrees:
        if row["relative_path"] == ".":
            continue
        workspace, admin = source / row["relative_path"], source / row["git_dir"]
        specs = (
            (workspace / ".git", workspace, admin, "gitdir: ", f"gitdir: {destination / row['git_dir']}\n"),
            (admin / "gitdir", admin, workspace / ".git", "", f"{destination / row['relative_path'] / '.git'}\n"),
            (admin / "commondir", admin, source / ".git", "", None),
        )
        for path, base, expected, prefix, replacement in specs:
            value = _small_git_file(path)
            text = value["text"]
            if not text.startswith(prefix) or not text.endswith("\n") or text.count("\n") != 1:
                raise IntentGuardianError("relocation Git pointer syntax is unsupported")
            raw = Path(text[len(prefix):-1])
            if (base / raw).resolve() != expected:
                raise IntentGuardianError("relocation Git pointer target differs")
            if replacement is None:
                if raw.is_absolute():
                    raise IntentGuardianError("relocation requires a relative worktree commondir")
                replacement = text
            links.append({"relative_path": path.relative_to(source).as_posix(), "mode": value["mode"],
                          "before": text, "after": replacement})
    return sorted(links, key=lambda row: row["relative_path"])


def _inspect_git_links(snapshot: dict[str, Any], root: Path) -> list[dict[str, str]]:
    expected = {name for row in snapshot["worktrees"] if row["relative_path"] != "."
                for name in (f"{row['relative_path']}/.git", f"{row['git_dir']}/gitdir", f"{row['git_dir']}/commondir")}
    links = snapshot.get("git_links")
    if (not isinstance(links, list) or len(links) != len(expected)
            or {row["relative_path"] for row in links} != expected):
        raise IntentGuardianError("relocation requires a complete frozen Git link inventory")
    states = []
    for link in links:
        relative = Path(link["relative_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise IntentGuardianError("relocation Git link escapes the repository")
        observed = _small_git_file(root / relative)
        if observed["mode"] != link["mode"]:
            raise IntentGuardianError("relocation Git link permissions changed")
        if observed["text"] == link["after"]:
            state = "after"
        elif observed["text"] == link["before"]:
            state = "before"
        else:
            raise IntentGuardianError("relocation Git link is neither the frozen predecessor nor successor")
        states.append({"relative_path": link["relative_path"], "state": state})
    return states


def inspect_relocation_filesystem(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Read-only recovery diagnosis, including root-moved/links-partial windows.

    Does not resolve the stale session route, follow a linked worktree's broken
    .git pointer, repair Git, or infer execution permission from physical state.
    """
    material = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    if (snapshot.get("schema") != SCHEMA or snapshot.get("snapshot_sha256") != _digest(material)
            or snapshot.get("authority_transferred") is not False):
        raise IntentGuardianError("relocation recovery requires intact v2 physical evidence")
    source, target = _canonical(Path(snapshot["source"])), _canonical(Path(snapshot["destination"]))
    if source.exists():
        verify_repository_identity(snapshot)
        return {"status": "source_intact", "links_pending": [], "execution_authorized": False,
                "authority_transferred": False, "mutation_performed": False}
    if (not target.exists() or _identity(target) != snapshot["source_identity"]
            or _identity(target / ".git") != snapshot["git_identity"]
            or _identity(target.parent) != snapshot["destination_parent_identity"]):
        raise IntentGuardianError("relocation recovery physical identity differs or both roots are missing")
    # Validate metadata and contents through physical admin paths, not through
    # broken .git links. After all links are repaired, the ordinary full Git
    # verifier additionally checks status and worktree registration.
    for row in snapshot["worktrees"]:
        workspace, admin = target / row["relative_path"], target / row["git_dir"]
        if (_identity(_canonical(workspace)) != row["identity"]
                or _identity(_canonical(admin)) != row["git_identity"]
                or _index_digest(admin / "index") != row["index_sha256"]
                or _small_git_file(admin / "HEAD")["text"] != f"ref: {row['branch']}\n"
                or _git(target, "rev-parse", row["branch"]).strip().decode("ascii") != row["head"]):
            raise IntentGuardianError("relocation recovery worktree identity/index/HEAD differs")
    expected_admin = {row["git_dir"] for row in snapshot["worktrees"] if row["relative_path"] != "."}
    admin_root = target / ".git/worktrees"
    actual_admin = {item.relative_to(target).as_posix() for item in admin_root.iterdir()} if admin_root.exists() else set()
    if actual_admin != expected_admin:
        raise IntentGuardianError("relocation recovery worktree registration set changed")
    if hashlib.sha256(_git(target, "show-ref", "--head")).hexdigest() != snapshot["refs_sha256"]:
        raise IntentGuardianError("relocation recovery refs changed")
    config = hashlib.sha256(_git(target, "config", "--local", "--includes", "--null", "--list")).hexdigest()
    if any(row["config_sha256"] != config for row in snapshot["worktrees"]):
        raise IntentGuardianError("relocation recovery Git configuration changed")
    if _content(target, snapshot["worktrees"]) != snapshot["content"]:
        raise IntentGuardianError("relocation recovery user content or permissions changed")
    links = _inspect_git_links(snapshot, target)
    pending = [row["relative_path"] for row in links if row["state"] == "before"]
    if not pending:
        verify_repository_identity(snapshot, moved=True)
    return {"status": "links_pending" if pending else "git_repaired", "links_pending": pending,
            "execution_authorized": False, "authority_transferred": False, "mutation_performed": False}


def _repository_locator(source: Path, destination: Path) -> dict[str, Any]:
    """Cheap physical/Git addressing checks, NOT a frozen content identity."""
    source = _canonical(source)
    destination = _canonical(destination)
    if any(char in str(root) for root in (source, destination) for char in ("\r", "\n")):
        raise IntentGuardianError("relocation roots cannot contain Git pointer line separators")
    source_identity = _identity(source)
    parent_identity = _identity(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise IntentGuardianError("relocation destination already exists")
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise IntentGuardianError("relocation roots must not overlap")
    if source_identity["device"] != parent_identity["device"]:
        raise IntentGuardianError("relocation requires the same filesystem device")
    common_identity = _identity(source / ".git")
    worktrees = _worktrees(source)
    links = _git_link_inventory(source, destination, worktrees)
    refs_hash = hashlib.sha256(_git(source, "show-ref", "--head")).hexdigest()
    return {
        "source": str(source), "destination": str(destination),
        "source_identity": source_identity, "destination_parent_identity": parent_identity,
        "git_identity": common_identity, "worktrees": worktrees,
        "refs_sha256": refs_hash, "git_links": links,
    }


def freeze_repository_identity(source: Path, destination: Path) -> dict[str, Any]:
    """Observe a whole-root move candidate, without granting permission to move."""
    locator = _repository_locator(source, destination)
    source, destination = Path(locator["source"]), Path(locator["destination"])
    worktrees, refs_hash, links = (locator[key] for key in ("worktrees", "refs_sha256", "git_links"))
    content = _content(source, worktrees)
    if worktrees != _worktrees(source) or refs_hash != hashlib.sha256(_git(source, "show-ref", "--head")).hexdigest():
        raise IntentGuardianError("relocation Git state changed during inventory")
    if links != _git_link_inventory(source, destination, worktrees):
        raise IntentGuardianError("relocation Git links changed during inventory")
    if locator["source_identity"] != _identity(source) or locator["git_identity"] != _identity(source / ".git"):
        raise IntentGuardianError("relocation physical root changed during inventory")
    if destination.exists() or destination.is_symlink() or locator["destination_parent_identity"] != _identity(destination.parent):
        raise IntentGuardianError("relocation destination changed during inventory")
    material = {
        "schema": SCHEMA, **locator, "content": content, "authority_transferred": False,
    }
    return {**material, "snapshot_sha256": _digest(material)}


def verify_repository_identity(snapshot: dict[str, Any], *, moved: bool = False) -> dict[str, Any]:
    """Recheck a candidate or a physically moved, Git-repaired root read-only.

    This deliberately cannot repair links or relax a session-mapping check.
    The future execution transaction must separately prove native authority,
    settled effects, and a quiescent writer boundary at every mutation stage.
    """
    material = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    if (snapshot.get("schema") != SCHEMA or snapshot.get("authority_transferred") is not False
            or snapshot.get("snapshot_sha256") != _digest(material)):
        raise IntentGuardianError("relocation snapshot integrity differs")
    source = _canonical(Path(snapshot["source"]))
    destination = _canonical(Path(snapshot["destination"]))
    if not moved:
        if freeze_repository_identity(source, destination) != snapshot:
            raise IntentGuardianError("relocation candidate drifted")
    else:
        if source.exists() or source.is_symlink():
            raise IntentGuardianError("relocation source still exists")
        if _identity(destination) != snapshot["source_identity"] or _identity(destination / ".git") != snapshot["git_identity"]:
            raise IntentGuardianError("relocation physical repository identity differs")
        if _identity(destination.parent) != snapshot["destination_parent_identity"]:
            raise IntentGuardianError("relocation destination parent identity differs")
        if _worktrees(destination) != snapshot["worktrees"]:
            raise IntentGuardianError("relocation worktrees differ or links need repair")
        if any(row["state"] != "after" for row in _inspect_git_links(snapshot, destination)):
            raise IntentGuardianError("relocation Git links are not fully repaired")
        if hashlib.sha256(_git(destination, "show-ref", "--head")).hexdigest() != snapshot["refs_sha256"]:
            raise IntentGuardianError("relocation refs changed")
        if _content(destination, snapshot["worktrees"]) != snapshot["content"]:
            raise IntentGuardianError("relocation user content or permissions changed")
    return {"status": "verified", "moved": moved, "snapshot_sha256": snapshot["snapshot_sha256"],
            "authority_transferred": False, "git_mutation_performed": False}


def _binding_inventory(
    home: Path, repository: dict[str, Any], *, provider: str, session_id: str,
    native_question: dict[str, Any] | None = None,
    _mapping_target_required: bool = True,
) -> dict[str, Any]:
    """Inspect only matching live roots; do not migrate historical orphan lanes.

    The registry lookup reads workspace selectors from current contract/mapping
    files. Only the selected repository's contracts and ledgers are replayed.
    Host observations and unrelated historical warnings do not become a CAS
    baseline. This still does not acquire execution authority or freeze writers.
    """

    source = Path(repository["source"])
    roots = {str(source / row["relative_path"]) for row in repository["worktrees"]}
    contracts: dict[str, dict[str, Any]] = {}
    mappings = []
    intent = home / "intent"

    def relevant(path: Path) -> bool:
        if path.is_symlink() or path.stat().st_size > 8 * 1024**2:
            raise IntentGuardianError("relocation registry selector is unsafe or oversized")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise IntentGuardianError("relocation registry selector is unreadable") from error
        if not isinstance(value, dict) or not isinstance(value.get("workspace_root"), str):
            raise IntentGuardianError("relocation registry selector is invalid")
        raw_root = Path(value["workspace_root"]).expanduser()
        if str(raw_root) in roots:
            return True
        if raw_root.is_relative_to(source) and raw_root.exists():
            raise IntentGuardianError("relocation has a contract for an unregistered live workspace")
        return False

    candidates = sorted({
        *list((intent / "workspaces").glob("*.active.json")),
        *list((intent / "sessions").glob("*.active.json")),
    })
    for path in candidates:
        if not relevant(path):
            continue
        path = _canonical(path)
        contract = load_contract(path)
        runtime = contract["runtime"]
        # A draft or a Skill frame is not an executing effect. Original bytes
        # are fenced and archived; successors are paused with no copied runtime.
        # Live native questions/transactions are still checked below. Never
        # treat this distinction as permission to hide an outstanding operation.
        blocked_fields = [field for field in (
            "open_events", "pending_verifications", "pre_execution_gaps",
        ) if runtime.get(field)]
        if blocked_fields:
            if runtime.get("historical_retirement") and not runtime.get("pending_verifications"):
                verify(home, path, contract)
            else:
                raise IntentGuardianError("relocation requires settled contract state: " + ", ".join(blocked_fields))
        try:
            effect_state = effects(path)
            approval_state = approvals(path)
            native_state = native_journal.load_projection_read_only(path)
        except (ApprovalInvariantError, InterventionError, NativeDecisionJournalError) as error:
            raise IntentGuardianError("relocation cannot verify authoritative ledger state") from error
        if blocking_attempts(effect_state):
            raise IntentGuardianError("relocation requires settled effect debt")
        own_questions = 0
        open_questions = []
        for row in approval_state["requests"].values():
            # Use the same effective TTL as the authoritative approval APIs.
            # Expiry grants nothing and does not settle the independent effect
            # or native-transaction gates. Keep all ledger bytes as history.
            if not request_is_open(row):
                continue
            # SessionStart's legacy display card is not a native permission
            # request. Once a later revision is actually active/confirmed it
            # cannot authorize anything in that revision. Keep its bytes as
            # history, without treating this obsolete UI card as live debt.
            # Current cards, typed requests and any unfinished native tx still
            # fail the ordinary checks below; no decision is manufactured here.
            if (row.get("typed") is not True and row.get("kind") == "intent-confirmation"
                    and row.get("source") == "intent_confirmation_card"
                    and row.get("intent_id_sha256") == hashlib.sha256(contract["intent_id"].encode()).hexdigest()
                    and 0 < row.get("intent_revision", 0) < contract["revision"]
                    and contract["status"] == "active" and not contract["confirmation"]["required"]):
                continue
            if (native_question and native_question["contract_path"] == str(path)
                    and row.get("typed") is True and row.get("prompt_shown") is True
                    and row.get("source") == "codex_permission_request"
                    and row.get("kind") == "intent-confirmation"
                    and row.get("decision_owner") == "human"
                    and all(row.get("snapshot", {}).get(key) == value
                            for key, value in native_question["snapshot"].items())):
                own_questions += 1
            else:
                open_questions.append(row)
        if open_questions or own_questions > 1:
            raise IntentGuardianError("relocation has an open approval question")
        own_transactions = 0
        for row in native_state["transactions"].values():
            if row.get("stage") in {"committed", "superseded"}:
                continue
            # Same exact classification as the legacy projection adapter. This
            # preserves correlation history, not permission or a settled effect.
            # The independent live-question and effect gates have already run.
            if is_legacy_unsealed_prepared_diagnostic(row):
                continue
            binding = row.get("binding", {})
            expected = (native_question or {}).get("transaction_binding")
            request = approval_state["requests"].get(binding.get("request_id"), {})
            if (expected and native_question["contract_path"] == str(path)
                    and row.get("stage") in {"prepared", "approval_decided"}
                    and all(binding.get(key) == value for key, value in expected.items())
                    and request.get("typed") is True and request.get("prompt_shown") is True
                    and request.get("decision_owner") == "human"
                    and request.get("source") == "codex_permission_request"
                    and (request.get("typed_receipt") or {}).get("outcome") == "allow"
                    and all(request.get("snapshot", {}).get(key) == value
                            for key, value in native_question["snapshot"].items())):
                own_transactions += 1
            else:
                raise IntentGuardianError("relocation has an unfinished native transaction")
        if own_transactions > 1:
            raise IntentGuardianError("relocation has ambiguous native execution transactions")
        contracts[str(path)] = {
            "contract_path": str(path), "workspace_root": contract["workspace_root"],
            "intent_id": contract["intent_id"], "revision": contract["revision"],
            "task_epoch": contract["task_epoch"], "policy_sha256": policy_digest(contract),
            "status": contract["status"], "task_lanes_sha256": _digest(runtime.get("task_lanes", [])),
        }
    for path in sorted((intent / "sessions").glob("*.workspace.json")):
        if not relevant(path):
            continue
        mapping = _validated_mapping(path, require_target=_mapping_target_required)
        if session_workspace_path(home, mapping["provider"], mapping["session_id"]) != path:
            raise IntentGuardianError("relocation session mapping filename differs")
        if mapping["contract_path"] not in contracts:
            raise IntentGuardianError("relocation mapped contract is outside the frozen registry")
        if mapping["git_common_dir"] != str(source / ".git"):
            raise IntentGuardianError("relocation mapping Git common-dir differs")
        mappings.append({"path": str(path), **mapping})
    matching = [row for row in mappings if row["provider"] == provider and row["session_id"] == session_id]
    if len(matching) != 1:
        raise IntentGuardianError("relocation requires the exact current provider/session mapping")
    return {"contracts": list(contracts.values()), "mappings": mappings,
            "provider": provider, "session_id": session_id, "effect_debt_count": 0}


def _assess_relocation_bindings(home, source, destination, *, provider, session_id, native_question=None):
    """Fail cheap checks before reading the entire repository's contents."""
    home, source = _canonical(home), _canonical(source)
    if provider not in {"claude", "codex"} or not session_id.strip():
        raise IntentGuardianError("relocation preflight requires provider/session")
    if home.is_relative_to(source):
        raise IntentGuardianError("relocation recovery home must remain outside the moved repository")
    locator = _repository_locator(source, destination)
    freeze_consumers(home, locator)  # Cheap validation precedes content traversal.
    bindings = _binding_inventory(home, locator, provider=provider, session_id=session_id,
                                  native_question=native_question)
    return locator, bindings


def assess_repository_relocation(home: Path, source: Path, destination: Path, *, provider: str, session_id: str) -> dict[str, Any]:
    """Local diagnosis only: no content snapshot, plan, install or authority.

    Success means only that expensive evidence collection is worth attempting.
    The executor accepts neither this schema nor a claim of global readiness.
    """
    locator, bindings = _assess_relocation_bindings(home, source, destination, provider=provider, session_id=session_id)
    return {"schema": "sulde-repository-relocation-assessment-v1", "status": "ready_for_evidence",
            "source": locator["source"], "destination": locator["destination"],
            "worktree_count": len(locator["worktrees"]), "contract_count": len(bindings["contracts"]),
            "mapping_count": len(bindings["mappings"]), "content_verified": False,
            "authority_transferred": False, "execution_authorized": False}


def freeze_relocation_preflight(
    home: Path, source: Path, destination: Path, *, provider: str, session_id: str,
    _native_question: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Non-authorizing combined Git/Guardian observation, suitable for review.

    Do not consume this output as permission: an execution route must obtain a
    native decision, establish its writer barrier and revalidate this evidence.
    """
    _, bindings = _assess_relocation_bindings(home, source, destination, provider=provider,
                                             session_id=session_id, native_question=_native_question)
    repository = freeze_repository_identity(source, destination)
    consumers = freeze_consumers(_canonical(home), repository)
    verify_repository_identity(repository)
    if bindings != _binding_inventory(home, repository, provider=provider, session_id=session_id,
                                     native_question=_native_question):
        raise IntentGuardianError("relocation Guardian bindings changed during preflight")
    material = {"schema": "sulde-repository-relocation-preflight-v1", "repository": repository,
                "bindings": bindings, "path_facts_schema": PATH_FACTS_SCHEMA, "consumers": consumers,
                "authority_transferred": False, "execution_authorized": False}
    result = {**material, "preflight_sha256": _digest(material)}
    # Detect store capacity/type failures before preparing any execution or
    # publishing a fence. These hashes are not authority and are re-read under
    # the execution fence; do not freeze mutable audit bytes into the card.
    _frozen_store_bytes(_fence_inventory(home, result)[0])
    return result


PLAN_SCHEMA = "sulde-repository-relocation-plan-v1"
DECISION_SCHEMA = "sulde-repository-relocation-decision-v1"
NATIVE_ACTION = "review-repository-relocation"
NATIVE_CHOICE = "确认精确迁移计划；本次仅记录决定，不移动目录"
EXECUTION_KIND = "repository-relocation-execution"
EXECUTION_ACTION = "execute-repository-relocation"
EXECUTION_CHOICE = "执行精确整仓迁移；完成后保持业务暂停，重新确认才恢复"


def _plan_path(home: Path, plan_id: str, *, decision: bool = False) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", plan_id):
        raise IntentGuardianError("relocation requires an exact plan id")
    root = _canonical(home) / "intent" / "repository-relocations"
    _canonical(root)
    return root / f"{plan_id}.{'decision' if decision else 'plan'}.json"




def prepare_relocation_plan(
    home: Path, path: Path, source: Path, destination: Path, *, provider: str, session_id: str,
) -> dict[str, Any]:
    """Persist immutable review material, with no decision or execution authority."""
    if provider != "codex":
        raise IntentGuardianError("relocation native review currently requires Codex")
    path = _canonical(path)
    preflight = freeze_relocation_preflight(home, source, destination, provider=provider, session_id=session_id)
    lane = next(row for row in preflight["bindings"]["mappings"]
                if row["provider"] == provider and row["session_id"] == session_id)
    if lane["contract_path"] != str(path):
        raise IntentGuardianError("relocation plan contract differs from the current lane")
    material = {"schema": PLAN_SCHEMA, "contract_path": str(path), "provider": provider,
                "session_id": session_id, "preflight": preflight, "denial_predecessor": ""}
    requests = approval_projection(path)["requests"].values()
    # A Deny is immutable. A later preparation creates a distinct review with
    # explicit denial lineage; it never revives the old one-shot question.
    for _ in range(64):
        plan_id = _digest(material)
        denied = [row for row in requests if row.get("typed") is True
                  and row.get("source") == "codex_permission_request"
                  and row.get("kind") == "intent-confirmation"
                  and row.get("target_sha256") == hashlib.sha256(plan_id.encode()).hexdigest()
                  and row.get("provider") == provider
                  and row.get("snapshot", {}).get("session_id") == session_id
                  and (row.get("typed_receipt") or {}).get("outcome") == "deny"]
        if not denied:
            break
        if len(denied) != 1:
            raise IntentGuardianError("relocation has ambiguous denial lineage")
        material["denial_predecessor"] = plan_id
    else:
        raise IntentGuardianError("relocation review lineage exceeds bound")
    plan = {**material, "plan_id": _digest(material)}
    target = _plan_path(home, plan["plan_id"])
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _identity(target.parent)
    with _exclusive_path_lock(target.parent / ".prepare.lock"):
        if target.exists() or target.is_symlink():
            if _read_plan_file(target) != plan:
                raise IntentGuardianError("relocation immutable plan conflict")
        else:
            atomic_write(target, json.dumps(plan, ensure_ascii=True, sort_keys=True, indent=2) + "\n")
            target.chmod(0o600)
    return {"status": "prepared", "plan_id": plan["plan_id"], "plan_path": str(target),
            "execution_authorized": False, "authority_transferred": False}


def relocation_review_context(
    home: Path, path: Path, plan_id: str, *, provider: str, session_id: str,
    _execution: bool = False,
) -> dict[str, Any]:
    """Independently rebuild the current material, ignoring only its exact question."""
    plan = _read_plan_file(_plan_path(home, plan_id))
    material = {key: value for key, value in plan.items() if key != "plan_id"}
    if (set(plan) != {"schema", "contract_path", "provider", "session_id", "preflight", "plan_id", "denial_predecessor"}
            or plan["schema"] != PLAN_SCHEMA or plan["plan_id"] != plan_id or _digest(material) != plan_id
            or plan["contract_path"] != str(_canonical(path)) or provider != "codex"
            or plan["provider"] != provider or plan["session_id"] != session_id):
        raise IntentGuardianError("relocation plan integrity or current lane differs")
    predecessor = plan["denial_predecessor"]
    if predecessor:
        old = _read_plan_file(_plan_path(home, predecessor))
        old_material = {key: value for key, value in old.items() if key != "plan_id"}
        if (old.get("plan_id") != predecessor or _digest(old_material) != predecessor
                or any(old.get(key) != plan[key] for key in
                       ("schema", "contract_path", "provider", "session_id", "preflight"))):
            raise IntentGuardianError("relocation denial predecessor differs")
        denied = [row for row in approval_projection(path)["requests"].values()
                  if row.get("typed") is True and row.get("source") == "codex_permission_request"
                  and row.get("kind") == "intent-confirmation" and row.get("provider") == provider
                  and row.get("snapshot", {}).get("session_id") == session_id
                  and row.get("target_sha256") == hashlib.sha256(predecessor.encode()).hexdigest()
                  and (row.get("typed_receipt") or {}).get("outcome") == "deny"]
        if len(denied) != 1:
            raise IntentGuardianError("relocation predecessor lacks one exact durable Deny")
    result = _relocation_card_material(plan, load_contract(path), execution=_execution)
    repo = plan["preflight"]["repository"]
    current = freeze_relocation_preflight(
        home, Path(repo["source"]), Path(repo["destination"]), provider=provider, session_id=session_id,
        _native_question=result["expected_question"],
    )
    if "consumers" not in plan["preflight"]:
        # An old immutable card never gains new configuration authority.
        current.pop("consumers", None)
        current["preflight_sha256"] = _digest({key: val for key, val in current.items()
                                               if key != "preflight_sha256"})
    if current != plan["preflight"]:
        raise IntentGuardianError("relocation plan world changed; prepare a fresh review")
    return result


def _relocation_card_material(plan: dict[str, Any], contract: dict[str, Any], *, execution: bool) -> dict[str, Any]:
    """Pure card construction; callers must separately verify world and authority."""
    repo = plan["preflight"]["repository"]
    path, plan_id = Path(plan["contract_path"]), plan["plan_id"]
    provider, session_id = plan["provider"], plan["session_id"]
    card = {
        "要决定的结果": "确认一次精确的整仓迁移计划",
        "当前根目录": repo["source"], "目标根目录": repo["destination"],
        "worktree 数量": len(repo["worktrees"]),
        "保留": "物理仓库、用户文件、权限和历史账本；不继承旧任务执行权限",
        "本次动作": "仅记录当前会话的原生决定，不移动目录、不修复 Git、不重绑定",
        "执行门禁": "后续执行器必须独立重验决定和物理证据、建立写者屏障并记录单次执行终态",
        "计划摘要": plan_id,
    }
    kind, decision, action, choice = "repository-relocation", "approve", NATIVE_ACTION, NATIVE_CHOICE
    if _rebase_path_facts(plan["preflight"]):
        card["路径事实"] = "仅将迁移根内的结构化路径映射到新根；原提案和技能记录归档，新任务仍需审阅，不转移授权"
    consumer = plan["preflight"].get("consumers") or {}
    if consumer.get("after") is not None:
        card["外部源码绑定"] = {"配置": consumer["path"],
            "迁移后源码": consumer["after"]["source_root"],
            "迁移后Git目录": consumer["after"]["git_common_dir"],
            "边界": "保留旧配置证据；仅重绑定同一物理仓库；迁移期间自动沉淀不写入，不转移信任或授权"}
    if execution:
        kind, decision, action, choice = EXECUTION_KIND, "execute", EXECUTION_ACTION, EXECUTION_CHOICE
        card.update({
            "要决定的结果": "执行一次精确的整仓迁移，不恢复旧任务权限",
            "本次动作": "冻结受影响写者、移动上述根目录、修复已登记 Git 指针、发布暂停的继任合同和会话映射",
            "执行门禁": "原生决定与物理证据独立复检；中断仅恢复同一事务，不重复搬迁；终态核验后释放屏障",
            "不包含": "生产安装、远端修改、文件内容改写、删除历史账本、恢复业务执行或转移旧审批",
            "失败处理": "不扩大路径、不覆盖目的地；保留恢复证据，未核验时不放行业务写入",
        })
    bound_card = {"operation_id": "repository-relocation", "decision_id": decision,
                  "action": action, "本次选择": action, "选择说明": choice,
                  "决策内容": card, "宿主": "codex", "会话内确认": True}
    expected_question = {"contract_path": str(path), "snapshot": {
        "card_sha256": _native_card_sha256(bound_card), "provider": provider, "session_id": session_id,
        "revision": contract["revision"], "target_sha256": hashlib.sha256(plan_id.encode()).hexdigest(),
        "world_state_sha256": hashlib.sha256(str(Path(contract["workspace_root"]).resolve()).encode()).hexdigest(),
        "lane_sha256": hashlib.sha256(f"codex\0{session_id}".encode()).hexdigest(),
        "effect_sha256": hashlib.sha256(action.encode()).hexdigest(),
    }}
    if execution:
        expected_question["transaction_binding"] = {
            "operation": "repository-relocation", "kind": kind, "decision": decision, "action": action,
            "target": plan_id, "provider": provider, "session_id": session_id,
            "source": "codex_permission_request", "approval_kind": "intent-confirmation",
            "card_sha256": _native_card_sha256(bound_card), "workspace": contract["workspace_root"],
            "intent_id": contract["intent_id"], "intent_revision": contract["revision"],
            "task_epoch": contract["task_epoch"], "effect_attempt_id": "", "effect_subject_intent_revision": 0,
        }
    context = {"kind": kind, "decision": decision, "target": plan_id,
               "action": action, "choice": choice, "card": bound_card,
               "workspace": contract["workspace_root"], "intent_id": contract["intent_id"],
               "intent_revision": contract["revision"], "task_epoch": contract["task_epoch"]}
    return {"plan": plan, "card": card, "bound_card": bound_card, "context": context,
            "expected_question": expected_question}


def _execution_prepare_boundary(stage: str) -> None:
    """Inert test seam; no environment-controlled production interruption."""
    del stage


def _prepare_relocation_execution(
    home: Path, path: Path, plan_id: str, *, provider: str, session_id: str,
) -> dict[str, Any]:
    """Bind an ALREADY decided execution card into the existing native journal.

    Internal stage, not an independently callable host/CLI action. The public
    executor owns fence recovery, physical execution, rebind and terminal
    release. This function neither decides a question nor moves files nor
    publishes a fence.
    The old review's Allow and its .decision.json are never execution authority.
    """
    home, path = _canonical(home), _canonical(path)
    # Match ordinary writers' contract -> ledger lock order; the plan lock is
    # outside the moving repository and only serializes this exact plan.
    target = _plan_path(home, plan_id).with_suffix(".execution.lock")
    with _exclusive_path_lock(target), contract_lock(path):
        review = relocation_review_context(home, path, plan_id, provider=provider,
                                         session_id=session_id, _execution=True)
        context = review["context"]
        request = _exact_request(path, context, session_id, "decided")
        receipt = (request or {}).get("typed_receipt") or {}
        if (not request or request.get("typed") is not True or request.get("prompt_shown") is not True
                or request.get("decision_owner") != "human" or receipt.get("outcome") != "allow"
                or receipt.get("execution_authorized") is not False):
            raise IntentGuardianError("relocation requires an exact decided execution-card native Allow")
        request_receipt = request_binding_receipt(path, request["request_id"])
        verify_request_binding_receipt(path, request_receipt)
        decided_request_receipt(path, request_receipt, outcome="allow", provider=provider,
                                session_id=session_id, actor="permission-request:codex")
        projection = native_journal.load_projection_read_only(path)
        seals = [row for row in projection["seals"].values()
                 if row["binding"]["request_id"] == request["request_id"]]
        expected = _native_binding_snapshot(path, context, session_id, read_only=True)
        if seals:
            if len(seals) != 1:
                raise IntentGuardianError("relocation execution has ambiguous seal origin")
            # Recover the pre-seal prompt head, not today's journal head. Only
            # our immutable seal can explain this CAS difference. No wildcard
            # exemption for audit events or unrelated native transactions.
            proof = head_proof_read_only(path)
            payload = _stable_read_source_bytes(journal_path(path), label="relocation prompt origin")
            if hashlib.sha256(payload).hexdigest() != proof["journal_sha256"]:
                raise IntentGuardianError("relocation native journal changed during recovery")
            sequence = seals[0]["seal_sequence"]
            expected["journal_sha256"] = hashlib.sha256(
                b"".join(payload.splitlines(keepends=True)[:sequence - 1])
            ).hexdigest()
        if request["snapshot"] != expected:
            raise IntentGuardianError("relocation execution prompt snapshot changed")
        binding = seal_binding(
            path, operation="repository-relocation", decision="execute", target=plan_id,
            action=EXECUTION_ACTION, intent_id=context["intent_id"], intent_revision=context["intent_revision"],
            task_epoch=context["task_epoch"], effect_attempt_id="", effect_subject_intent_revision=0,
            workspace=context["workspace"], provider=provider, session_id=session_id,
            source="codex_permission_request", card=context["card"], request_id=request["request_id"],
            receipt=request_receipt,
        )
        _execution_prepare_boundary("sealed")
        transaction = prepare(path, binding)
        _execution_prepare_boundary("prepared")
        # This reader replays the canonical T12 rows. Neither caller data nor
        # the previous review's consent projection can stand in for a receipt.
        if transaction["stage"] == "prepared":
            result = advance_with_authority(path, transaction["transaction_id"],
                                           readers=NativeAuthorityReaders(None, None, None, None))
            if result["stage"] != "approval_decided":
                raise IntentGuardianError("relocation execution native authority could not be verified")
        elif transaction["stage"] != "approval_decided":
            raise IntentGuardianError("relocation execution preparation has an unexpected terminal/stage")
        _execution_prepare_boundary("approval_decided")
        # Do not release an execution capability or claim completion. The
        # enclosing executor must establish the fence and revalidate this binding
        # plus physical evidence at the action boundary before any mutation.
        return {"status": "approval_decided", "transaction_id": transaction["transaction_id"],
                "plan_id": plan_id, "request_id": request["request_id"],
                "card_sha256": _native_card_sha256(context["card"]),
                "execution_authorized": False, "authority_transferred": False,
                "physical_mutation_performed": False, "executor_registered": False}


def _exact_request(path: Path, context: dict[str, Any], session_id: str, status: str) -> dict | None:
    return request_for_binding(
        path, kind="intent-confirmation", target=context["target"], provider="codex", session_id=session_id,
        source="codex_permission_request", card=context["card"], workspace=context["workspace"],
        route="human", status=status,
    )


def _decision_record(path: Path, context: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Derive data-only evidence from the replayed typed approval ledger."""
    request = _exact_request(path, context, session_id, "decided")
    receipt = (request or {}).get("typed_receipt")
    if (not request or request.get("typed") is not True or request.get("prompt_shown") is not True
            or request.get("decision_owner") != "human" or not isinstance(receipt, dict)
            or receipt.get("outcome") != "allow" or receipt.get("execution_authorized") is not False
            or request["snapshot"] != _native_binding_snapshot(path, context, session_id, read_only=True)):
        raise IntentGuardianError("relocation has no exact current typed native Allow")
    return {"schema": DECISION_SCHEMA, "plan_id": context["target"], "contract_path": str(path),
            "provider": "codex", "session_id": session_id, "request_id": request["request_id"],
            "decision_identity": receipt["decision_identity"], "snapshot": request["snapshot"],
            "decision_recorded": True, "execution_authorized": False, "authority_transferred": False}


def record_relocation_decision(
    home: Path, path: Path, plan_id: str, *, decision: str, provider: str, session_id: str,
) -> dict[str, Any]:
    """Native executor records consent only; never moves a root or grants a task.

    The typed ledger is the sole decision truth. The owner-only decision file
    is rebuildable evidence, not a bearer token. R3 must independently verify
    this evidence before its execution transaction can authorize any mutation.
    """
    if decision != "approve" or provider != "codex":
        raise IntentGuardianError("unsupported relocation review decision")
    target = _plan_path(home, plan_id, decision=True)
    with _exclusive_path_lock(target.with_suffix(".lock")):
        context = relocation_review_context(home, path, plan_id, provider=provider, session_id=session_id)["context"]
        try:
            request = _exact_request(path, context, session_id, "asked")
            if request is not None:
                if request.get("typed") is not True:
                    raise IntentGuardianError("relocation requires a typed native request")
                decide_typed_approval(
                    path, request_id=request["request_id"], receipt_id=request["request_identity"],
                    outcome="allow", snapshot=request["snapshot"],
                    current_snapshot=_native_binding_snapshot(path, context, session_id),
                    provider=provider, session_id=session_id, decision_owner="human",
                    actor="permission-request:codex",
                )
            # Recheck after the durable human decision. A crash now can recover
            # the same evidence; it cannot approve again or move a directory.
            context = relocation_review_context(home, path, plan_id, provider=provider, session_id=session_id)["context"]
            record = _decision_record(path, context, session_id)
        except ApprovalInvariantError as error:
            raise IntentGuardianError("relocation native decision binding failed") from error
        if target.exists() or target.is_symlink():
            if _read_plan_file(target) != record:
                raise IntentGuardianError("relocation decision evidence conflict")
        else:
            atomic_write(target, json.dumps(record, ensure_ascii=True, sort_keys=True, indent=2) + "\n")
            target.chmod(0o600)
        return {"status": "decision_recorded", **record, "decision_path": str(target)}


def verify_relocation_decision(
    home: Path, path: Path, plan_id: str, *, provider: str, session_id: str,
) -> dict[str, Any]:
    context = relocation_review_context(home, path, plan_id, provider=provider, session_id=session_id)["context"]
    record = _decision_record(path, context, session_id)
    if _read_plan_file(_plan_path(home, plan_id, decision=True)) != record:
        raise IntentGuardianError("relocation decision evidence differs from authoritative approval")
    return {"status": "verified", **record}


def inspect_relocation_plan(home: Path, plan_id: str, *, provider: str, session_id: str) -> dict[str, Any]:
    """Recovery entry independent of the possibly missing mapped workspace.

    A successful diagnosis neither closes a transaction nor transfers a lane.
    The exact plan is explicit: do not discover or silently adopt another task.
    """
    plan = _read_plan_file(_plan_path(home, plan_id))
    material = {key: value for key, value in plan.items() if key != "plan_id"}
    if (plan.get("schema") != PLAN_SCHEMA or plan.get("plan_id") != plan_id
            or _digest(material) != plan_id or provider != "codex"
            or plan.get("provider") != provider or plan.get("session_id") != session_id):
        raise IntentGuardianError("relocation recovery plan or exact session binding differs")
    _fence_inventory(_canonical(home), plan["preflight"])
    result = inspect_relocation_filesystem(plan["preflight"]["repository"])
    return {**result, "plan_id": plan_id, "routing_verified": False,
            "rebind_required": result["status"] != "source_intact"}














def _fence_inventory(home: Path, preflight: dict[str, Any]) -> tuple[dict[str, Any], list[Path]]:
    material = {key: val for key, val in preflight.items() if key != "preflight_sha256"}
    if (preflight.get("schema") != "sulde-repository-relocation-preflight-v1"
            or preflight.get("preflight_sha256") != _digest(material)):
        raise IntentGuardianError("relocation fence requires intact preflight evidence")
    originals = {_canonical(Path(row["contract_path"])) for row in preflight["bindings"]["contracts"]}
    contracts = sorted(originals | {_relocation_successor_path(preflight, path) for path in originals})
    mappings = sorted({_canonical(Path(row["path"])) for row in preflight["bindings"]["mappings"]})
    ledgers = sorted({factory(path) for path in contracts
                      for factory in (approval_store, effect_store, journal_path, audit_path,
                                      effect_receipt_store_path, contract_receipt_store_path, external_head_receipt_store_path)})
    stores = contracts + mappings + ledgers
    consumer = frozen_consumer(home, preflight)
    if consumer is not None:
        stores.append(_canonical(Path(consumer["path"])))
    if not stores or len(stores) > MAX_WORKTREES * 32 or any(_store_home(path) != home for path in stores):
        raise IntentGuardianError("relocation fence requires stores in the exact recovery home")
    value = {"schema": FENCE_SCHEMA, "source": preflight["repository"]["source"],
             "destination": preflight["repository"]["destination"],
             "stores": sorted(str(path) for path in stores), "preflight_sha256": preflight["preflight_sha256"]}
    # Match existing cross-contract order: contracts, mappings, then stores.
    # Raw lock acquisition is internal to the exact recovery executor; there
    # is no CLI/host operation exposing it as a general write exemption.
    # A parent auto-sediment launch owns launch -> child execution -> registry.
    # Acquire consumer locks FIRST so its child can finish without lock inversion.
    locks = ([home / "auto-sediment-launch.lock", home / "auto-sediment.lock"]
             if consumer is not None else [])
    locks += [home / "intent" / "workspaces" / ".workspace-rebind.lock"]
    locks += [path.with_name("." + path.name + ".lock") for path in stores]
    locks += [home / "intent" / ".repository-relocation-registry.lock"]
    return {**value, "sha256": _digest(value)}, locks


def _relocation_successor_path(preflight: dict[str, Any], source: Path) -> Path:
    # Known before movement, so new contracts AND their future ledgers are
    # fenced too. A Deny/fresh review does not create an unfenced target lane.
    identity = _digest({"preflight": preflight["preflight_sha256"], "source": str(source)})[:32]
    return source.with_name("relocation-" + identity + ".active.json")


def _relocation_archive_path(plan: dict[str, Any], source: Path) -> Path:
    home = _store_home(source)
    if home is None:
        raise IntentGuardianError("relocation source is outside the canonical registry")
    return home / "intent/repository-relocations/archives" / (plan["plan_id"] + "-" + _digest(str(source))[:32] + ".json")


def _original_relocation_contract(plan: dict[str, Any], source: Path) -> dict[str, Any]:
    archive = _relocation_archive_path(plan, source)
    if source.exists() and archive.exists() and (not source.samefile(archive) or source.stat().st_nlink != 2):
        raise IntentGuardianError("relocation source and archive are not the exact interrupted archival link")
    selected = source if source.exists() else archive
    return validate_contract(_read_plan_file(_canonical(selected)))


def _publish_relocation_write_fence(home: Path, preflight: dict[str, Any]) -> dict[str, Any]:
    """Internal inhibition primitive; NOT a migration executor or permission.

    No production command calls this yet. The execution-authorizing native
    transaction must still be implemented before publishing a real fence. Tests
    exercise this primitive only with disposable stores. After publication only
    the future verified terminal recovery may retire it; there is deliberately
    no force-clear, expiry, PID-liveness bypass or environment escape hatch.
    """
    home = _canonical(home)
    value, locks = _fence_inventory(home, preflight)
    with ExitStack() as stack:
        for lock in locks[:-1]:
            stack.enter_context(_exclusive_path_lock(lock))
        bindings = preflight["bindings"]
        observed = freeze_relocation_preflight(
            home, Path(value["source"]), Path(value["destination"]),
            provider=bindings["provider"], session_id=bindings["session_id"],
        )
        if observed != preflight:
            raise IntentGuardianError("relocation world changed before fence publication")
        # Hashing a large repository must not monopolize the shared registry.
        # Existing stores are already locked; only membership needs one final
        # recheck under the brief registry-publication lock.
        stack.enter_context(_exclusive_path_lock(locks[-1]))
        if _binding_inventory(home, preflight["repository"], provider=bindings["provider"],
                              session_id=bindings["session_id"]) != bindings:
            raise IntentGuardianError("relocation registry changed before fence publication")
        return _persist_write_fence_locked(home, value)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(_canonical(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _persist_write_fence_locked(home: Path, value: dict[str, Any]) -> dict[str, Any]:
    """Caller holds the complete writer lock set and the short registry lock."""
    existing = _read_write_fences(home)
    if any(row != value and (set(row["stores"]) & set(value["stores"])
            or any(Path(value[key]).is_relative_to(Path(row[other]))
                   or Path(row[other]).is_relative_to(Path(value[key]))
                   for key in ("source", "destination") for other in ("source", "destination")))
           for row in existing):
        raise IntentGuardianError("relocation fence conflicts with another relocation")
    root = _fence_directory(home)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / (value["sha256"] + ".json")
    if value not in existing:
        if len(existing) >= MAX_WORKTREES:
            raise IntentGuardianError("relocation fence registry exceeds bound")
        # Never expose an incomplete atomic-write temporary in this registry.
        staging = root.parent / (".fence-stage-" + value["sha256"] + ".json")
        atomic_write(staging, json.dumps(value, sort_keys=True) + "\n")
        os.replace(staging, target)
    if os.name != "nt":
        _fsync_directory(root)
        _fsync_directory(root.parent)
    return {"status": "write_fenced", "execution_authorized": False,
            "authority_transferred": False, "fence_path": str(target), "sha256": value["sha256"]}


def _relocation_move_api():
    """v1 requires the macOS atomic, exclusive rename, never check-then-replace.

    SDK sys/stdio.h defines RENAME_EXCL=4 and renameatx_np's five arguments.
    Unsupported hosts fail BEFORE preparing a native transaction or fence.
    """
    if sys.platform != "darwin":
        raise IntentGuardianError("relocation execution requires the verified macOS exclusive rename API")
    library = ctypes.CDLL(None, use_errno=True)
    function = getattr(library, "renameatx_np", None)
    if function is None:
        raise IntentGuardianError("relocation exclusive rename API unavailable")
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    return function


def _move_root_exclusive(snapshot: dict[str, Any]) -> None:
    function = _relocation_move_api()
    source, target = Path(snapshot["source"]), Path(snapshot["destination"])
    descriptors = []
    try:
        for parent in (source.parent, target.parent):
            descriptors.append(os.open(_canonical(parent), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        if (_identity(_canonical(source)) != snapshot["source_identity"]
                or _identity(target.parent) != snapshot["destination_parent_identity"]):
            raise IntentGuardianError("relocation root identity changed before exclusive rename")
        # Preserve Python's standard mutation audit boundary when using the
        # native exclusive API. In particular, the official isolated runner
        # must be able to refuse a production-root mutation before the syscall.
        sys.audit("os.rename", str(source), str(target), descriptors[0], descriptors[1])
        if function(descriptors[0], os.fsencode(source.name), descriptors[1], os.fsencode(target.name), 4):
            # Never fall back to os.rename/replace: an empty late destination
            # must survive too. Do not include arbitrary OS diagnostics.
            raise IntentGuardianError("relocation exclusive rename refused: errno=" + str(ctypes.get_errno()))
        for descriptor in descriptors:
            os.fsync(descriptor)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)




def _frozen_store_bytes(fence: dict[str, Any]) -> list[dict[str, Any]]:
    """Hashes only: no contract/log contents in relocation recovery evidence."""
    rows = []
    remaining = MAX_STORE_TOTAL_BYTES
    if len(fence["stores"]) > MAX_WORKTREES * 32:
        raise IntentGuardianError("relocation stores exceed count bound")
    for raw in fence["stores"]:
        path = _canonical(Path(raw))
        snapshot = _store_snapshot(path, remaining_bytes=remaining)
        remaining -= snapshot["size"]
        rows.append({"path": raw, "sha256": snapshot["sha256"], "mode": snapshot["mode"]})
    return rows


def _prepared_execution_authority(plan: dict[str, Any], tx_id: str, *, _native_projection=None) -> dict[str, Any]:
    """Independent read-back works under the fence and with the old root absent.

    Neither the caller's transaction id nor a filesystem manifest is authority.
    Rebuild the exact card, replay the original approval, and prove its durable
    native seal/stage. No ordinary session route or writing head API is used.
    """
    path = Path(plan["contract_path"])
    contract = _original_relocation_contract(plan, path)
    card = _relocation_card_material(plan, contract, execution=True)
    projection = native_journal.load_projection_read_only(path) if _native_projection is None else _native_projection
    transaction = projection["transactions"].get(tx_id)
    if not transaction or transaction.get("stage") not in {"approval_decided", "effect_applied", "contract_applied", "committed"}:
        raise IntentGuardianError("relocation requires its prepared execution authority, not a review or terminal claim")
    binding = _require_durable_seal_origin(projection, transaction)
    expected = card["expected_question"]["transaction_binding"]
    if any(binding.get(key) != value for key, value in expected.items()):
        raise IntentGuardianError("relocation prepared execution binding differs")
    details = transaction["stage_details"].get("approval_decided", {})
    if not all(isinstance(details.get(key), str) and re.fullmatch(r"[a-f0-9]{64}", details[key])
               for key in ("decision_sha256", "authority_sha256")):
        raise IntentGuardianError("relocation native authority stage is incomplete")
    _verify_sealed_approval(path, binding, decision_sha256=details["decision_sha256"],
                           authority_sha256=details["authority_sha256"])
    # The binding verifier intentionally returns the immutable ASKED prefix;
    # prompt/decision must be read from the canonical terminal projection.
    verify_request_binding_receipt(path, request_binding_receipt(path, binding["request_id"]))
    request = approvals(path)["requests"].get(binding["request_id"], {})
    if (request.get("typed") is not True or request.get("prompt_shown") is not True
            or request.get("decision_owner") != "human"
            or (request.get("typed_receipt") or {}).get("outcome") != "allow"
            or request.get("typed_receipt") != details.get("authority_receipt")
            or any(request.get("snapshot", {}).get(key) != value
                   for key, value in card["expected_question"]["snapshot"].items())):
        raise IntentGuardianError("relocation lacks the exact typed execution decision")
    return binding


def _relocation_filesystem_boundary(stage: str) -> None:
    """Inert crash-injection seam, not a production switch or hook callback."""
    del stage


def _write_frozen_git_link(home: Path, plan: dict[str, Any], link: dict[str, Any]) -> None:
    repo = plan["preflight"]["repository"]
    root = _canonical(Path(repo["destination"]))
    target = _canonical(root / link["relative_path"])
    if not target.is_relative_to(root) or _identity(root) != repo["source_identity"]:
        raise IntentGuardianError("relocation Git repair root differs")
    expected = {"text": link["before"], "mode": link["mode"]}
    current = _small_git_file(target)
    if current == {"text": link["after"], "mode": link["mode"]}:
        return
    if current != expected:
        raise IntentGuardianError("relocation Git pointer changed before repair")
    # Stage outside the moved tree, on the same device. A crash before replace
    # leaves the original pointer intact, and no scratch file pollutes the
    # content snapshot. This path is reserved by the immutable manifest.
    staging = _plan_path(home, plan["plan_id"]).with_suffix(".git-link-stage")
    _canonical(staging)
    if staging.exists():
        info = staging.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise IntentGuardianError("relocation Git staging file is unsafe")
    atomic_write(staging, link["after"])
    descriptor = os.open(staging, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fchmod(descriptor, link["mode"])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _relocation_filesystem_boundary("link_staged:" + link["relative_path"])
    if _small_git_file(target) != expected:
        raise IntentGuardianError("relocation Git pointer changed at repair boundary")
    os.replace(staging, target)
    _fsync_directory(target.parent)
    _fsync_directory(staging.parent)


def _execute_relocation_filesystem(home: Path, plan_id: str, *, provider: str, session_id: str) -> dict[str, Any]:
    """Internal physical phase; deliberately NOT a public native/CLI executor.

    Ends fenced at git_repaired, not committed. The full executor must publish
    paused routing, independently settle native effect/contract stages and
    release the fence. No bypass is added to any ordinary writer, even for the
    current process.
    """
    _relocation_move_api()  # unavailable platform fails without a transaction
    home = _canonical(home)
    plan_path = _plan_path(home, plan_id)
    plan = _read_plan_file(plan_path)
    if (plan.get("schema") != PLAN_SCHEMA or plan.get("plan_id") != plan_id
            or _digest({key: val for key, val in plan.items() if key != "plan_id"}) != plan_id
            or provider != "codex" or plan.get("provider") != provider or plan.get("session_id") != session_id):
        raise IntentGuardianError("relocation execution plan or current session differs")
    path, repo = _canonical(Path(plan["contract_path"])), plan["preflight"]["repository"]
    if (home.is_relative_to(Path(repo["source"])) or home.is_relative_to(Path(repo["destination"]))
            or _identity(home)["device"] != repo["source_identity"]["device"]
            or Path(__file__).resolve().is_relative_to(Path(repo["source"]))):
        raise IntentGuardianError("relocation executor/recovery home must stay outside the move on the same device")
    manifest_path = plan_path.with_suffix(".filesystem.json")
    prepared = None
    if not os.path.lexists(manifest_path):
        prepared = _prepare_relocation_execution(home, path, plan_id, provider=provider, session_id=session_id)
    fence, locks = _fence_inventory(home, plan["preflight"])
    with _exclusive_path_lock(plan_path.with_suffix(".execution.lock")), ExitStack() as stack:
        # Same complete writer set on initial execution AND after process death.
        # All are raw acquisition here, never an exemption for ordinary APIs.
        for lock in locks[:-1]:
            stack.enter_context(_exclusive_path_lock(lock))
        if os.path.lexists(manifest_path):
            manifest = _read_plan_file(manifest_path)
            material = {key: val for key, val in manifest.items() if key != "sha256"}
            if (set(manifest) != {"schema", "plan_id", "transaction_id", "binding_sha256", "fence_sha256", "stores", "sha256"}
                    or manifest["schema"] != "sulde-repository-relocation-filesystem-v1"
                    or manifest["sha256"] != _digest(material) or manifest["plan_id"] != plan_id
                    or manifest["fence_sha256"] != fence["sha256"]):
                raise IntentGuardianError("relocation filesystem manifest integrity differs")
            tx_id = manifest["transaction_id"]
            binding = _prepared_execution_authority(plan, tx_id)
            if manifest["binding_sha256"] != _digest(binding) or manifest["stores"] != _frozen_store_bytes(fence):
                raise IntentGuardianError("relocation frozen authority/store bytes changed")
        else:
            if prepared is None:
                raise IntentGuardianError("relocation manifest disappeared before writer fence")
            tx_id = prepared["transaction_id"]
            binding = _prepared_execution_authority(plan, tx_id)
            material = {"schema": "sulde-repository-relocation-filesystem-v1", "plan_id": plan_id,
                        "transaction_id": tx_id, "binding_sha256": _digest(binding),
                        "fence_sha256": fence["sha256"], "stores": _frozen_store_bytes(fence)}
            manifest = {**material, "sha256": _digest(material)}
        successor_paths = {str(_relocation_successor_path(plan["preflight"], Path(row["contract_path"])))
                           for row in plan["preflight"]["bindings"]["contracts"]}
        if any(row["path"] in successor_paths and row["sha256"] for row in manifest["stores"]):
            raise IntentGuardianError("relocation successor slot was occupied before the move")
        existing = _read_write_fences(home)
        if fence not in existing:
            # A missing fence can only recover BEFORE movement. Never infer
            # permission to recreate one from a moved tree or a caller token.
            if not Path(repo["source"]).is_dir():
                raise IntentGuardianError("relocation lost its fence after root movement; no automatic recreation")
            review = relocation_review_context(home, path, plan_id, provider=provider,
                                             session_id=session_id, _execution=True)
            with _exclusive_path_lock(locks[-1]):
                if _binding_inventory(home, repo, provider=provider, session_id=session_id,
                                      native_question=review["expected_question"]) != plan["preflight"]["bindings"]:
                    raise IntentGuardianError("relocation registry changed before execution fence")
                if not os.path.lexists(manifest_path):
                    atomic_write(manifest_path, json.dumps(manifest, sort_keys=True) + "\n")
                    _fsync_directory(manifest_path.parent)
                _relocation_filesystem_boundary("manifest")
                _persist_write_fence_locked(home, fence)
        elif not os.path.lexists(manifest_path):
            raise IntentGuardianError("relocation cannot adopt a fence without its execution manifest")
        _relocation_filesystem_boundary("fenced")
        if manifest["stores"] != _frozen_store_bytes(fence):
            raise IntentGuardianError("relocation authority/store drift at physical boundary")
        question = _relocation_card_material(plan, load_contract(path), execution=True)["expected_question"]
        if _binding_inventory(home, repo, provider=provider, session_id=session_id, native_question=question,
                              _mapping_target_required=False) != plan["preflight"]["bindings"]:
            raise IntentGuardianError("relocation semantic bindings changed during recovery")
        observed = inspect_relocation_filesystem(repo)
        if observed["status"] == "source_intact":
            _move_root_exclusive(repo)
            _relocation_filesystem_boundary("moved")
            observed = inspect_relocation_filesystem(repo)
        pending = set(observed["links_pending"])
        for link in repo["git_links"]:
            if link["relative_path"] not in pending:
                continue
            _write_frozen_git_link(home, plan, link)
            _relocation_filesystem_boundary("link_repaired:" + link["relative_path"])
        observed = inspect_relocation_filesystem(repo)
        if observed["status"] != "git_repaired" or manifest["stores"] != _frozen_store_bytes(fence):
            raise IntentGuardianError("relocation physical postcondition or frozen authority differs")
        _prepared_execution_authority(plan, tx_id)
        _relocation_filesystem_boundary("physical_verified")
        return {"status": "physical_verified_rebind_pending", "plan_id": plan_id, "transaction_id": tx_id,
                "filesystem_status": observed["status"], "fence_active": True, "routing_verified": False,
                "authority_transferred": False, "execution_authorized": False, "executor_registered": False}


def _checked_relocation_plan(home: Path, plan_id: str) -> dict[str, Any]:
    plan = _read_plan_file(_plan_path(home, plan_id))
    if (plan.get("schema") != PLAN_SCHEMA or plan.get("plan_id") != plan_id
            or _digest({key: val for key, val in plan.items() if key != "plan_id"}) != plan_id):
        raise IntentGuardianError("relocation plan integrity differs")
    _fence_inventory(home, plan["preflight"])
    return plan


def _object_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _fixed_relocation_object(path: Path, value: dict[str, Any]) -> None:
    if os.path.lexists(path):
        if _read_plan_file(_canonical(path)) != value:
            raise IntentGuardianError("relocation immutable object conflicts")
        return
    atomic_write(path, _object_text(value))
    _fsync_directory(path.parent)


def _filesystem_manifest(home: Path, plan: dict[str, Any], *, _native_projection=None) -> dict[str, Any]:
    value = _read_plan_file(_plan_path(home, plan["plan_id"]).with_suffix(".filesystem.json"))
    fence, _ = _fence_inventory(home, plan["preflight"])
    if (set(value) != {"schema", "plan_id", "transaction_id", "binding_sha256", "fence_sha256", "stores", "sha256"}
            or value.get("schema") != "sulde-repository-relocation-filesystem-v1"
            or value.get("plan_id") != plan["plan_id"] or value.get("fence_sha256") != fence["sha256"]
            or value.get("sha256") != _digest({key: val for key, val in value.items() if key != "sha256"})
            or not isinstance(value.get("stores"), list)
            or [row.get("path") for row in value["stores"]] != fence["stores"]):
        raise IntentGuardianError("relocation filesystem manifest integrity differs")
    if _digest(_prepared_execution_authority(plan, value["transaction_id"], _native_projection=_native_projection)) != value["binding_sha256"]:
        raise IntentGuardianError("relocation filesystem manifest authority differs")
    return value


def _rebase_path_facts(preflight: dict[str, Any]) -> bool:
    version = preflight.get("path_facts_schema")
    if version not in (None, PATH_FACTS_SCHEMA):
        raise IntentGuardianError("unsupported relocation path-fact policy")
    return version == PATH_FACTS_SCHEMA


def _rebind_recipe(home: Path, plan: dict[str, Any], manifest: dict[str, Any], *, _native_projection=None) -> dict[str, Any]:
    """Rebuildable desired state, containing no copied source execution runtime."""
    frozen = {row["path"]: row for row in manifest["stores"]}
    contracts = []
    source_root = Path(plan["preflight"]["repository"]["source"])
    destination = Path(plan["preflight"]["repository"]["destination"])
    for row in plan["preflight"]["bindings"]["contracts"]:
        source = Path(row["contract_path"])
        target = _relocation_successor_path(plan["preflight"], source)
        archive = _relocation_archive_path(plan, source)
        if frozen[str(target)]["sha256"]:
            raise IntentGuardianError("relocation successor slot was occupied before the move")
        original_file = source if source.exists() else archive
        original = _original_relocation_contract(plan, source)
        archived_pair = source.exists() and archive.exists() and source.samefile(archive)
        if _store_snapshot(original_file, allow_archive_link=archived_pair)["sha256"] != frozen[str(source)]["sha256"]:
            raise IntentGuardianError("relocation original contract bytes changed")
        workspace = destination / Path(row["workspace_root"]).relative_to(source_root)
        candidate = relocation_review_contract(original, workspace, plan["plan_id"],
            repository_source=source_root, repository_destination=destination,
            rebase_paths=_rebase_path_facts(plan["preflight"]))
        contracts.append({"source": str(source), "archive": str(archive), "target": str(target), "document": candidate})
    targets = {row["source"]: row for row in contracts}
    projection = (native_journal.load_projection_read_only(Path(plan["contract_path"]))
                  if _native_projection is None else _native_projection)
    transaction = projection["transactions"][manifest["transaction_id"]]
    mappings = []
    for old in plan["preflight"]["bindings"]["mappings"]:
        subject = targets[old["contract_path"]]
        value = {key: val for key, val in old.items() if key not in {"path", "mapping_sha256"}}
        value.update(contract_path=subject["target"], workspace_root=subject["document"]["workspace_root"],
                     git_common_dir=str(destination / ".git"), source_contract_path=subject["archive"],
                     bound_at=transaction["prepared_at"])
        value["mapping_sha256"] = _canonical_sha256(value)
        mappings.append({"path": old["path"], "after": value})
    material = {"schema": "sulde-repository-relocation-rebind-v1", "plan_id": plan["plan_id"],
                "filesystem_sha256": manifest["sha256"], "transaction_id": manifest["transaction_id"],
                "contracts": contracts, "mappings": mappings}
    consumer = frozen_consumer(home, plan["preflight"])
    if consumer is not None:
        if frozen[consumer["path"]]["sha256"] != consumer["sha256"] or frozen[consumer["path"]]["mode"] != consumer["mode"]:
            raise IntentGuardianError("relocation consumer differs from its reviewed snapshot")
        material["consumers"] = ([{"path": consumer["path"], "after": consumer["after"]}]
                                 if consumer["after"] is not None else [])
    return {**material, "sha256": _digest(material)}


def _native_relocation_suffix(path: Path, frozen: dict[str, Any], contract: Path, tx_id: str, stage: str, *, _payload=None) -> None:
    """Only an append-only exact transaction tail may differ from frozen bytes."""
    if not path.exists() and not frozen["sha256"]:
        return
    payload = _stable_read_source_bytes(path, label="relocation native suffix") if _payload is None else _payload
    if stat.S_IMODE(path.stat().st_mode) != (frozen["mode"] if frozen["mode"] is not None else 0o600):
        raise IntentGuardianError("relocation native suffix permissions changed")
    lines = payload.splitlines(keepends=True)
    prefix = 0 if not frozen["sha256"] else None
    digest = hashlib.sha256()
    for index, line in enumerate(lines, 1):
        digest.update(line)
        if digest.hexdigest() == frozen["sha256"]:
            prefix = index
            break
    if prefix is None:
        raise IntentGuardianError("relocation native history is not the frozen prefix")
    if stage == "journal":
        rows = _decode_rows(payload)
        replay(contract, rows)
        allowed = lambda row: row.get("event") == "advanced" and row.get("stage") in {"effect_applied", "contract_applied", "committed"}
    else:
        rows = _decode_authority_events(contract, payload, stage=stage)
        allowed = lambda row: row.get("stage") == stage
    if any(row.get("transaction_id") != tx_id or not allowed(row) for row in rows[prefix:]):
        raise IntentGuardianError("relocation native suffix contains another transaction or action")


def _verify_rebind_state(home: Path, plan: dict[str, Any], manifest: dict[str, Any], recipe: dict[str, Any], *, complete: bool, _native_projection=None) -> None:
    if recipe != _rebind_recipe(home, plan, manifest, _native_projection=_native_projection):
        raise IntentGuardianError("relocation rebind recipe differs from independently rebuilt successors")
    source = Path(plan["contract_path"])
    native = {str(factory(source)): stage for factory, stage in (
        (journal_path, "journal"), (effect_receipt_store_path, "effect_applied"),
        (contract_receipt_store_path, "contract_applied"), (external_head_receipt_store_path, "committed"),
    )}
    sources = {row["source"]: row for row in recipe["contracts"]}
    targets = {row["target"]: row["document"] for row in recipe["contracts"]}
    mappings = {row["path"]: row["after"] for row in recipe["mappings"]}
    mappings.update({row["path"]: row["after"] for row in recipe.get("consumers", [])})
    remaining = MAX_STORE_TOTAL_BYTES
    for frozen in manifest["stores"]:
        raw = frozen["path"]
        path = Path(raw)
        if raw in native:
            remaining -= _store_snapshot(path, remaining_bytes=remaining)["size"]
            _native_relocation_suffix(path, frozen, source, manifest["transaction_id"], native[raw])
            continue
        expected_sha, expected_mode = frozen["sha256"], frozen["mode"]
        archived_pair = False
        if raw in sources:
            archive = Path(sources[raw]["archive"])
            if path.exists() and archive.exists() and (not path.samefile(archive) or path.stat().st_nlink != 2):
                raise IntentGuardianError("relocation duplicated original contract")
            if complete and (path.exists() or not archive.exists()):
                raise IntentGuardianError("relocation source contract has not been archived")
            archived_pair = path.exists() and archive.exists() and path.samefile(archive)
            path = path if path.exists() else archive
        snapshot = _store_snapshot(path, remaining_bytes=remaining, allow_archive_link=archived_pair)
        remaining -= snapshot["size"]
        if raw in targets or raw in mappings:
            value = targets.get(raw, mappings.get(raw))
            successor_sha = hashlib.sha256(_object_text(value).encode()).hexdigest()
            actual = snapshot["sha256"]
            if complete or actual != expected_sha:
                expected_sha, expected_mode = successor_sha, 0o600
        if snapshot["sha256"] != expected_sha:
            raise IntentGuardianError("relocation rebind store differs from its exact before/after state")
        if snapshot["mode"] is not None and snapshot["mode"] != expected_mode:
            raise IntentGuardianError("relocation rebind store permissions changed")
    verify_repository_identity(plan["preflight"]["repository"], moved=True)
    if complete:
        verify_published(home, plan["preflight"])
        for row in recipe["mappings"]:
            if _validated_mapping(Path(row["path"])) != row["after"]:
                raise IntentGuardianError("relocation published mapping did not validate")


def relocation_postcondition(contract_path: Path, binding: dict[str, Any], *, stage: str):
    """Read-only source-specific producer for the existing native journal."""
    home = _store_home(contract_path)
    if home is None or stage not in {"effect_applied", "contract_applied"}:
        raise IntentGuardianError("unsupported relocation postcondition")
    plan = _checked_relocation_plan(home, binding["target"])
    if (plan["contract_path"] != str(contract_path.resolve()) or plan["provider"] != binding["provider"]
            or plan["session_id"] != binding["session_id"]):
        raise IntentGuardianError("relocation postcondition belongs to another native lane")
    manifest = _filesystem_manifest(home, plan)
    if _digest(binding) != manifest["binding_sha256"]:
        raise IntentGuardianError("relocation postcondition binding differs")
    native_stage = native_journal.load_projection_read_only(contract_path)["transactions"][manifest["transaction_id"]]["stage"]
    fence, _ = _fence_inventory(home, plan["preflight"])
    if native_stage != "committed" and fence not in _read_write_fences(home):
        raise IntentGuardianError("relocation lost its fence before native commitment")
    recipe_path = _plan_path(home, plan["plan_id"]).with_suffix(".rebind.json")
    recipe = _read_plan_file(recipe_path)
    _verify_rebind_state(home, plan, manifest, recipe, complete=True)
    if stage == "effect_applied":
        subject = manifest
        value = {"kind": "repository-relocation-filesystem", "plan_id": plan["plan_id"],
                 "snapshot_sha256": plan["preflight"]["repository"]["snapshot_sha256"], "verified": True}
    else:
        subject = recipe
        value = {"kind": "repository-relocation-bindings", "plan_id": plan["plan_id"],
                 "rebind_sha256": recipe["sha256"], "contracts": len(recipe["contracts"]),
                 "mappings": len(recipe["mappings"]), "authority_transferred": False, "review_required": True}
    return value, subject["sha256"], subject["sha256"]


def _relocation_rebind_boundary(stage: str) -> None:
    """Inert interruption seam for every durable rebind/commit boundary."""
    del stage


def _archive_relocation_source(source: Path, archive: Path) -> None:
    """No overwrite: recover the exact link+unlink archival interruption."""
    _canonical(archive)
    archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not source.exists():
        if not archive.exists():
            raise IntentGuardianError("relocation source and archive both missing")
        return
    if not archive.exists():
        os.link(source, archive, follow_symlinks=False)
        _fsync_directory(archive.parent)
    elif not source.samefile(archive) or source.stat().st_nlink != 2:
        raise IntentGuardianError("relocation archive destination conflicts")
    _relocation_rebind_boundary("archive_linked:" + source.name)
    source.unlink()
    _fsync_directory(source.parent)


def _finish_relocation_fence(home: Path, plan: dict[str, Any], manifest: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    source = Path(plan["contract_path"])
    transaction = native_journal.load_projection_read_only(source)["transactions"][manifest["transaction_id"]]
    if transaction["stage"] != "committed":
        raise IntentGuardianError("relocation fence cannot release before native commitment")
    verify_recorded_external_head_receipt(source, manifest["transaction_id"], read_only=True)
    fence, locks = _fence_inventory(home, plan["preflight"])
    marker = _fence_directory(home) / (fence["sha256"] + ".json")
    retired = _fence_directory(home).parent / "completed-fences" / marker.name
    terminal_path = _plan_path(home, plan["plan_id"]).with_suffix(".terminal.json")
    if not marker.exists():
        # A finished transaction is immutable history. Later human-approved
        # task revisions must not cause replay of the old physical migration.
        terminal = _read_plan_file(terminal_path)
        if (_read_plan_file(retired) != fence or terminal.get("sha256") != _digest(
                {key: val for key, val in terminal.items() if key != "sha256"})
                or terminal.get("plan_id") != plan["plan_id"] or terminal.get("transaction_id") != manifest["transaction_id"]
                or terminal.get("rebind_sha256") != recipe["sha256"]
                or terminal.get("native_head") != head_proof_read_only(source)):
            raise IntentGuardianError("relocation completion evidence differs")
        return terminal
    with ExitStack() as stack:
        for lock in locks:
            stack.enter_context(_exclusive_path_lock(lock))
        _verify_rebind_state(home, plan, manifest, recipe, complete=True)
        if fence not in _read_write_fences(home):
            raise IntentGuardianError("relocation fence changed before terminal release")
        current = next(row for row in recipe["mappings"] if row["after"]["provider"] == plan["provider"]
                       and row["after"]["session_id"] == plan["session_id"])
        material = {"schema": "sulde-repository-relocation-terminal-v1", "plan_id": plan["plan_id"],
                    "transaction_id": manifest["transaction_id"], "rebind_sha256": recipe["sha256"],
                    "native_head": head_proof_read_only(source), "contract_path": current["after"]["contract_path"],
                    "workspace_root": current["after"]["workspace_root"], "authority_transferred": False,
                    "review_required": True}
        terminal = {**material, "sha256": _digest(material)}
        _fixed_relocation_object(terminal_path, terminal)
        _relocation_rebind_boundary("terminal_recorded")
        _canonical(retired)
        retired.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if retired.exists():
            raise IntentGuardianError("relocation retired fence already exists alongside the live fence")
        os.rename(marker, retired)
        _fsync_directory(marker.parent)
        _fsync_directory(retired.parent)
        _relocation_rebind_boundary("fence_retired")
        return terminal


def _recover_relocation_native_head(home: Path, plan: dict[str, Any]) -> None:
    """Finish only a validated journal append, not a new effect or approval.

    The execution lock is held by the caller. Preview the journal's existing
    anchored recovery protocol without writes, then verify both its actual and
    prospective suffix against the frozen history and complete rebind. Only
    under the whole writer lock set may that exact append be recovered.
    """
    source = Path(plan["contract_path"])
    pending = _canonical(head_pending_path(source))
    if not pending.exists():
        return
    fence, locks = _fence_inventory(home, plan["preflight"])
    with ExitStack() as stack:
        for lock in locks:
            stack.enter_context(_exclusive_path_lock(lock))
        if fence not in _read_write_fences(home):
            raise IntentGuardianError("relocation native recovery requires its live fence")
        _read_plan_file(pending)  # bounded owner-only, no symlink/hardlink
        preview = _recover_anchored_rows(source, _preview=True)
        projection, payload = preview[1], preview[2]
        manifest = _filesystem_manifest(home, plan, _native_projection=projection)
        recipe = _read_plan_file(_plan_path(home, plan["plan_id"]).with_suffix(".rebind.json"))
        _verify_rebind_state(home, plan, manifest, recipe, complete=True, _native_projection=projection)
        store = journal_path(source)
        frozen = next(row for row in manifest["stores"] if row["path"] == str(store))
        _native_relocation_suffix(store, frozen, source, manifest["transaction_id"], "journal", _payload=payload)
        recovered = _recover_anchored_rows(source)
        if recovered != preview:
            raise IntentGuardianError("relocation native recovery differs from verified preview")


def verify_relocation_recovery_authority(home: Path, plan_id: str, *, provider: str, session_id: str) -> dict[str, Any]:
    """Read-only exact decision check before routing around a stale mapping."""
    home = _canonical(home)
    plan = _checked_relocation_plan(home, plan_id)
    if provider != "codex" or plan["provider"] != provider or plan["session_id"] != session_id:
        raise IntentGuardianError("relocation recovery does not belong to the current session")
    path = Path(plan["contract_path"])
    manifest_path = _plan_path(home, plan_id).with_suffix(".filesystem.json")
    if manifest_path.exists():
        # This is a preview, not the recovery owner. No files or locks change.
        projection = _recover_anchored_rows(path, _preview=True)[1]
        _filesystem_manifest(home, plan, _native_projection=projection)
    else:
        context = _relocation_card_material(plan, _original_relocation_contract(plan, path), execution=True)["context"]
        request = _exact_request(path, context, session_id, "decided")
        if request is None:
            raise IntentGuardianError("relocation recovery requires an existing exact native execution Allow")
        decided_request_receipt(path, request_binding_receipt(path, request["request_id"]),
                                outcome="allow", provider=provider, session_id=session_id,
                                actor="permission-request:codex")
    return plan


def recover_repository_relocation(home: Path, plan_id: str, *, provider: str, session_id: str) -> dict[str, Any]:
    verify_relocation_recovery_authority(home, plan_id, provider=provider, session_id=session_id)
    return execute_repository_relocation(home, plan_id, provider=provider, session_id=session_id)


def execute_native_relocation(home: Path, path: Path, plan_id: str, *, decision: str, provider: str, session_id: str) -> dict[str, Any]:
    """Protected native command: consume the paired prompt, then execute once."""
    _relocation_move_api()
    plan = _checked_relocation_plan(_canonical(home), plan_id)
    if (decision != "execute" or provider != "codex" or plan["provider"] != provider
            or plan["session_id"] != session_id or str(_canonical(path)) != plan["contract_path"]):
        raise IntentGuardianError("relocation native command does not match its exact plan and lane")
    if _plan_path(home, plan_id).with_suffix(".filesystem.json").exists():
        return recover_repository_relocation(home, plan_id, provider=provider, session_id=session_id)
    with _exclusive_path_lock(_plan_path(home, plan_id).with_suffix(".native-decision.lock")):
        review = relocation_review_context(home, path, plan_id, provider=provider, session_id=session_id, _execution=True)
        context = review["context"]
        request = _exact_request(path, context, session_id, "asked")
        if request is not None:
            if request.get("typed") is not True or request.get("prompt_shown") is not True:
                raise IntentGuardianError("relocation requires a paired typed native execution prompt")
            decide_typed_approval(path, request_id=request["request_id"], receipt_id=request["request_identity"],
                                 outcome="allow", snapshot=request["snapshot"],
                                 current_snapshot=_native_binding_snapshot(path, context, session_id),
                                 provider=provider, session_id=session_id, decision_owner="human",
                                 actor="permission-request:codex")
    return recover_repository_relocation(home, plan_id, provider=provider, session_id=session_id)


def route_relocation_recovery(payload: dict[str, Any], *, home: Path, provider: str, session_id: str):
    """Exact trusted command only; evaluated before ordinary session lookup.

    The read-only gate never settles a journal, creates approval, or exempts a
    compound shell command. The command executor repeats the authority check.
    """
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "").lower()
    if tool_name not in {"bash", "exec", "exec_command", "command_execution"}:
        return None
    tool = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool, dict):
        return None
    command = str(tool.get("command") or tool.get("cmd") or "")
    invocation = _guardian_invocation(command)
    if invocation is None:
        return None
    spec = parse_native_decision_command(command)
    is_native = bool(spec and spec["kind"] == EXECUTION_KIND)
    if invocation["action"] != "recover-repository-relocation" and not is_native:
        return None
    try:
        if invocation["chained"] or not invocation["runtime_sha256"]:
            raise IntentGuardianError("relocation recovery requires one exact trusted command")
        if is_native:
            plan_id = spec["target"]
            if spec["provider"] != provider or spec["session_id"] != session_id:
                raise IntentGuardianError("relocation native recovery command lane differs")
            plan = _checked_relocation_plan(home, plan_id)
            if str(_canonical(Path(spec["contract"]))) != plan["contract_path"]:
                raise IntentGuardianError("relocation native recovery source differs")
            if not _plan_path(home, plan_id).with_suffix(".filesystem.json").exists():
                # First execution goes through normal structural/native prompt
                # observation. Never use this route to create a human decision.
                return None
        else:
            tokens = invocation["tokens"][invocation["action_index"] + 1:]
            if len(tokens) != 5 or set(tokens[1::2]) != {"--provider", "--session-id"}:
                raise IntentGuardianError("relocation recovery requires exact plan/provider/session arguments")
            plan_id = tokens[0]
            options = dict(zip(tokens[1::2], tokens[2::2]))
            if options["--provider"] != provider or options["--session-id"] != session_id:
                raise IntentGuardianError("relocation recovery command lane differs")
        verify_relocation_recovery_authority(home, plan_id, provider=provider, session_id=session_id)
        return Decision(dispatch="allow", would_dispatch="allow", lifecycle="continue", authority="none",
                        verification="none", evidence_state="observed", severity="info",
                        reason="仅恢复当前会话已原生批准的精确迁移事务；不恢复业务权限",
                        fingerprint=event_fingerprint(payload), reason_code="repository_relocation_recovery",
                        decision_stage="recovery")
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        return Decision(dispatch="deny", would_dispatch="deny", lifecycle="continue", authority="none",
                        verification="none", evidence_state="observed", severity="high",
                        reason="整仓迁移恢复绑定不可验证：" + str(error), fingerprint=event_fingerprint(payload),
                        reason_code="repository_relocation_recovery_unverified", decision_stage="recovery")


def execute_repository_relocation(home: Path, plan_id: str, *, provider: str, session_id: str) -> dict[str, Any]:
    """Complete the exact approved root migration; never resume business work."""
    home = _canonical(home)
    plan = _checked_relocation_plan(home, plan_id)
    if provider != "codex" or plan["provider"] != provider or plan["session_id"] != session_id:
        raise IntentGuardianError("relocation execution belongs to another current session")
    plan_path = _plan_path(home, plan_id)
    recipe_path = plan_path.with_suffix(".rebind.json")
    if not recipe_path.exists():
        _execute_relocation_filesystem(home, plan_id, provider=provider, session_id=session_id)
    with _exclusive_path_lock(plan_path.with_suffix(".execution.lock")):
        _recover_relocation_native_head(home, plan)
        manifest = _filesystem_manifest(home, plan)
        if recipe_path.exists():
            recipe = _read_plan_file(recipe_path)
        else:
            recipe = _rebind_recipe(home, plan, manifest)
        terminal_path = plan_path.with_suffix(".terminal.json")
        fence, locks = _fence_inventory(home, plan["preflight"])
        marker = _fence_directory(home) / (fence["sha256"] + ".json")
        if terminal_path.exists() and not marker.exists():
            terminal = _finish_relocation_fence(home, plan, manifest, recipe)
            return {"status": "committed", **terminal, "fence_released": True, "execution_authorized": False}
        if fence not in _read_write_fences(home):
            raise IntentGuardianError("relocation rebind requires its live write fence")
        with ExitStack() as stack:
            for lock in locks[:-1]:
                stack.enter_context(_exclusive_path_lock(lock))
            _verify_rebind_state(home, plan, manifest, recipe, complete=False)
            _fixed_relocation_object(recipe_path, recipe)
            _relocation_rebind_boundary("rebind_prepared")
            with _exclusive_path_lock(locks[-1]):
                for row in recipe["contracts"]:
                    _fixed_relocation_object(Path(row["target"]), row["document"])
                    _relocation_rebind_boundary("successor_written:" + Path(row["target"]).name)
                for row in recipe["contracts"]:
                    _archive_relocation_source(Path(row["source"]), Path(row["archive"]))
                    _relocation_rebind_boundary("source_archived:" + Path(row["source"]).name)
                for row in recipe["mappings"]:
                    target = Path(row["path"])
                    if _read_plan_file(target) != row["after"]:
                        atomic_write(target, _object_text(row["after"]))
                        _fsync_directory(target.parent)
                    _relocation_rebind_boundary("mapping_written:" + target.name)
                for row in recipe.get("consumers", []):
                    target = Path(row["path"])
                    if _read_plan_file(target) != row["after"]:
                        atomic_write(target, _object_text(row["after"]))
                        _fsync_directory(target.parent)
                    _relocation_rebind_boundary("consumer_written:" + target.name)
            _verify_rebind_state(home, plan, manifest, recipe, complete=True)
        _relocation_rebind_boundary("rebind_verified")
        # Normal writers remain fenced after releasing OS locks. Only the
        # source-specific journal adapter may append its independently verified
        # effect/contract/head receipts; its context never admits task writers.
        complete_repository_relocation(Path(plan["contract_path"]), manifest["transaction_id"])
        _relocation_rebind_boundary("native_committed")
        terminal = _finish_relocation_fence(home, plan, manifest, recipe)
        return {"status": "committed", **terminal, "fence_released": True, "execution_authorized": False}

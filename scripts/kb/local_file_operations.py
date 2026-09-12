"""Pure parsing for structured local file operations at the tool boundary.

Human-readable targets remain useful in audit output, but authorization must
not depend on joining or splitting filenames with a delimiter.  This module
turns an ``apply_patch`` envelope into an ordered, typed target list which the
guardian can validate one path at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat


_FILE_HEADER = re.compile(r"^\*\*\* (Add|Update|Delete) File:\s*(.+?)\s*$")
_MOVE_HEADER = re.compile(r"^\*\*\* Move to:\s*(.+?)\s*$")


class LocalFileOperationError(ValueError):
    """An apply_patch envelope cannot be mapped to exact file operations."""


def path_components_are_not_symlinks(root: Path, target: Path) -> bool:
    """Prove that every existing component below ``root`` is lexical."""
    try:
        relative = target.relative_to(root)
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if stat.S_ISLNK(cursor.lstat().st_mode):
                return False
    except (OSError, ValueError):
        return False
    return True


def bounded_path_reference(path: Path) -> Path | None:
    """Read one small path-only metadata file without following a link."""
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return None
        if metadata.st_size <= 0 or metadata.st_size > 4096:
            return None
        raw = path.read_text(encoding="utf-8").strip()
        if not raw or "\x00" in raw or "\n" in raw or "\r" in raw:
            return None
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = path.parent / candidate
        return candidate.resolve(strict=True)
    except (OSError, UnicodeError, ValueError):
        return None


@dataclass(frozen=True)
class LocalFileOperation:
    operation: str
    path: str

    def as_dict(self) -> dict[str, str]:
        return {"operation": self.operation, "path": self.path}


def parse_apply_patch_operations(patch_text: str) -> tuple[LocalFileOperation, ...]:
    """Return exact Add/Update/Delete/Move operations from one patch envelope.

    A move is represented as both ``move_from`` and ``move_to`` so both sides
    of the rename are independently checked against the contract.  An orphan
    ``Move to`` header is rejected instead of being treated as an ordinary
    write target.
    """
    operations: list[LocalFileOperation] = []
    current_update_index: int | None = None
    saw_envelope = False

    for line in str(patch_text or "").splitlines():
        if line == "*** Begin Patch":
            saw_envelope = True
            current_update_index = None
            continue
        if line == "*** End Patch":
            current_update_index = None
            continue
        file_match = _FILE_HEADER.fullmatch(line)
        if file_match is not None:
            verb, raw_path = file_match.groups()
            path = raw_path.strip()
            if not path:
                raise LocalFileOperationError("apply_patch file target is empty")
            operation = verb.lower()
            operations.append(LocalFileOperation(operation, path))
            current_update_index = len(operations) - 1 if operation == "update" else None
            continue
        move_match = _MOVE_HEADER.fullmatch(line)
        if move_match is not None:
            target = move_match.group(1).strip()
            if not target or current_update_index is None:
                raise LocalFileOperationError("apply_patch move has no exact source and target")
            source = operations[current_update_index]
            operations[current_update_index] = LocalFileOperation("move_from", source.path)
            operations.append(LocalFileOperation("move_to", target))
            current_update_index = None

    if not saw_envelope or not operations:
        raise LocalFileOperationError("apply_patch envelope has no exact file operations")
    return tuple(operations)


def operation_targets(
    operations: tuple[LocalFileOperation, ...],
) -> tuple[str, ...]:
    """Return de-duplicated targets without inventing a string delimiter."""
    targets: list[str] = []
    for operation in operations:
        if operation.path not in targets:
            targets.append(operation.path)
    return tuple(targets)


def has_destructive_operation(
    operations: tuple[LocalFileOperation, ...],
) -> bool:
    return any(
        operation.operation in {"delete", "move_from", "move_to"}
        for operation in operations
    )


def canonical_existing_local_target(
    target: str | Path,
    *,
    parent: str | Path,
) -> dict[str, object]:
    """Classify one existing child without following symlinks.

    This is filesystem classification only.  The returned stat identity is a
    world-state fact, never deletion authority.
    """
    raw = str(target)
    if (
        not raw
        or "\x00" in raw
        or "$" in raw
        or any(character in raw for character in "*?[]{}")
    ):
        raise LocalFileOperationError("local target is not one literal path")
    try:
        boundary_lexical = Path(os.path.abspath(Path(parent).expanduser()))
        parent_path = boundary_lexical.resolve(strict=True)
        if boundary_lexical != parent_path:
            raise LocalFileOperationError("local parent may not be an alias")
        lexical = Path(target).expanduser()
        if not lexical.is_absolute():
            lexical = parent_path / lexical
        lexical = Path(os.path.abspath(lexical))
        metadata = lexical.lstat()
        resolved = lexical.resolve(strict=True)
        relative = resolved.relative_to(parent_path)
        if not relative.parts:
            raise LocalFileOperationError("local target may not be its boundary")
        cursor = parent_path
        for part in relative.parts:
            cursor /= part
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise LocalFileOperationError(
                    "local target traverses a symlink"
                )
    except (OSError, ValueError, RuntimeError) as error:
        raise LocalFileOperationError(
            "local target is missing, aliased, or outside its parent"
        ) from error
    if lexical != resolved or stat.S_ISLNK(metadata.st_mode):
        raise LocalFileOperationError("local target may not be a symlink or alias")
    if not (
        stat.S_ISREG(metadata.st_mode)
        or stat.S_ISDIR(metadata.st_mode)
    ):
        raise LocalFileOperationError("local target type is unsupported")
    immediate_parent = resolved.parent
    parent_metadata = immediate_parent.lstat()
    return {
        "schema": "sulde-local-target-classification-v1",
        "path": str(resolved),
        "parent": str(immediate_parent),
        "target_type": (
            "directory" if stat.S_ISDIR(metadata.st_mode) else "file"
        ),
        "target_device": int(metadata.st_dev),
        "target_inode": int(metadata.st_ino),
        "parent_device": int(parent_metadata.st_dev),
        "parent_inode": int(parent_metadata.st_ino),
        "execution_authorized": False,
    }

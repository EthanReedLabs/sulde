#!/usr/bin/env python3
"""Manifest-first, fail-closed private-to-Community release staging."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "scripts" / "community-export-manifest.json"
DEFAULT_PUBLIC = REPO_ROOT.parent / "sulde-cc"

FORBIDDEN_PATHS = (
    re.compile(r"^knowledge/"),
    re.compile(r"^scripts/kb/"),
    re.compile(r"^tools/kb-index/"),
    re.compile(r"^integrations/codex/"),
    re.compile(r"(^|/)\.env(?:\.|$)"),
    re.compile(r"(^|/)(?:memory|kb)\.db$"),
    re.compile(r"(^|/)(?:sessions?|rollouts?)(/|$)"),
)
FORBIDDEN_TEXT = (
    "/Users/eric",
    "sulde-cc-pro",
    "SpielbergGao",
    "cognee-project-memory",
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN EC PRIVATE KEY",
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{12,}"
)
IGNORED_TARGET_PARTS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache"}
IGNORED_TARGET_NAMES = {".DS_Store"}


class ExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    destination: PurePosixPath
    mode: int
    sha256: str
    source: PurePosixPath | None

    @property
    def policy(self) -> str:
        return "copy" if self.source is not None else "preserve"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_digest(path: Path) -> str:
    return sha256_file(path)


def safe_relative(value: str) -> PurePosixPath:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
    ):
        raise ExportError(f"unsafe manifest path: {value!r}")
    return path


def within(root: Path, relative: PurePosixPath) -> Path:
    root_resolved = root.resolve()
    candidate = (root_resolved / Path(*relative.parts)).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ExportError(f"manifest path escapes root: {relative}") from exc
    return candidate


def load_manifest(path: Path) -> list[Entry]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"cannot read manifest: {exc}") from exc
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ExportError("manifest must be a version 1 object")
    raw_entries = value.get("files")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ExportError("manifest files must be a non-empty list")
    entries: list[Entry] = []
    seen: set[PurePosixPath] = set()
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ExportError(f"manifest entry {index} must be an object")
        destination = safe_relative(str(raw.get("destination", "")))
        if destination in seen:
            raise ExportError(f"duplicate manifest destination: {destination}")
        seen.add(destination)
        policy = raw.get("policy")
        if policy not in {"copy", "preserve"}:
            raise ExportError(f"invalid policy for {destination}: {policy}")
        source = safe_relative(str(raw.get("source", ""))) if policy == "copy" else None
        mode_raw = str(raw.get("mode", ""))
        if mode_raw not in {"100644", "100755"}:
            raise ExportError(f"invalid mode for {destination}: {mode_raw}")
        expected = str(raw.get("sha256", ""))
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ExportError(f"invalid sha256 for {destination}")
        entries.append(
            Entry(
                destination=destination,
                mode=0o755 if mode_raw == "100755" else 0o644,
                sha256=expected,
                source=source,
            )
        )
    return sorted(entries, key=lambda item: item.destination.as_posix())


def source_for(entry: Entry, source_root: Path, target_root: Path) -> Path:
    relative = entry.source if entry.source is not None else entry.destination
    root = source_root if entry.source is not None else target_root
    path = within(root, relative)
    if path.is_symlink():
        raise ExportError(f"symlinks are forbidden in Community export: {relative}")
    if not path.is_file():
        raise ExportError(f"missing {entry.policy} file: {path}")
    actual = sha256_file(path)
    if actual != entry.sha256:
        raise ExportError(
            f"digest mismatch for {entry.destination}: expected {entry.sha256}, got {actual}"
        )
    return path


def stage(entries: list[Entry], source_root: Path, target_root: Path, stage_root: Path) -> None:
    for entry in entries:
        source = source_for(entry, source_root, target_root)
        destination = within(stage_root, entry.destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination, follow_symlinks=False)
        destination.chmod(entry.mode)


def iter_tree_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if any(part in IGNORED_TARGET_PARTS for part in relative.parts):
            continue
        if path.name in IGNORED_TARGET_NAMES:
            continue
        if path.is_symlink():
            raise ExportError(f"unexpected symlink in public tree: {relative}")
        if path.is_file():
            yield path


def verify_target_inventory(entries: list[Entry], target_root: Path) -> None:
    expected = {entry.destination.as_posix() for entry in entries}
    required_existing = {
        entry.destination.as_posix() for entry in entries if entry.policy == "preserve"
    }
    actual = {path.relative_to(target_root).as_posix() for path in iter_tree_files(target_root)}
    extras = sorted(actual - expected)
    missing = sorted(required_existing - actual)
    if extras or missing:
        details = []
        if extras:
            details.append(f"unmanaged files={extras[:10]}")
        if missing:
            details.append(f"missing files={missing[:10]}")
        raise ExportError("public tree does not match manifest: " + "; ".join(details))


def scan_stage(stage_root: Path) -> None:
    for path in iter_tree_files(stage_root):
        relative = path.relative_to(stage_root).as_posix()
        if any(pattern.search(relative) for pattern in FORBIDDEN_PATHS):
            raise ExportError(f"forbidden public path: {relative}")
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise ExportError(f"binary file requires explicit release-policy support: {relative}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExportError(f"non-UTF-8 public file: {relative}") from exc
        for marker in FORBIDDEN_TEXT:
            if marker in text:
                raise ExportError(f"forbidden marker in {relative}: {marker}")
        if SECRET_ASSIGNMENT.search(text):
            raise ExportError(f"credential-like assignment in {relative}")


def run_checked(command: list[str], cwd: Path, *, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        output = (result.stdout + "\n" + result.stderr).strip()
        raise ExportError(f"validation failed: {' '.join(command)}\n{output[-4000:]}")


def validate_stage(stage_root: Path) -> None:
    env = os.environ.copy()
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    run_checked([sys.executable, "-m", "json.tool", ".claude-plugin/plugin.json"], stage_root, env=env)
    run_checked([sys.executable, "-m", "json.tool", "hooks/hooks.json"], stage_root, env=env)
    run_checked([sys.executable, "-m", "json.tool", "extensions/registry.json"], stage_root, env=env)
    run_checked([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], stage_root, env=env)
    run_checked([sys.executable, "tests/p1_hook_dryrun.py"], stage_root, env=env)
    run_checked([sys.executable, "tests/p2_template_dryrun.py"], stage_root, env=env)
    run_checked([sys.executable, "scripts/sulde.py", "doctor", "--strict"], stage_root, env=env)
    if os.name != "nt":
        shell_files = [
            path.relative_to(stage_root).as_posix()
            for path in iter_tree_files(stage_root)
            if path.read_bytes().startswith((b"#!/bin/sh", b"#!/bin/bash", b"#!/usr/bin/env sh", b"#!/usr/bin/env bash"))
        ]
        if shell_files:
            run_checked(["bash", "-n", *shell_files], stage_root, env=env)


def git_clean(target_root: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(target_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode == 0 and not result.stdout.strip()


def changed_copy_entries(entries: list[Entry], stage_root: Path, target_root: Path) -> list[Entry]:
    changed = []
    for entry in entries:
        if entry.policy != "copy":
            continue
        staged = within(stage_root, entry.destination)
        target = within(target_root, entry.destination)
        if not target.is_file() or sha256_file(target) != sha256_file(staged):
            changed.append(entry)
            continue
        target_mode = stat.S_IMODE(target.stat().st_mode)
        if bool(target_mode & 0o111) != bool(entry.mode & 0o111):
            changed.append(entry)
    return changed


def atomic_copy(source: Path, destination: Path, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle, source.open("rb") as source_handle:
            shutil.copyfileobj(source_handle, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(mode)
        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def apply(entries: list[Entry], changed: list[Entry], stage_root: Path, target_root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="sulde-community-backup-") as backup_name:
        backup_root = Path(backup_name)
        existed: set[PurePosixPath] = set()
        for entry in changed:
            target = within(target_root, entry.destination)
            if target.is_file():
                existed.add(entry.destination)
                backup = within(backup_root, entry.destination)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
        replaced: list[Entry] = []
        try:
            for entry in changed:
                atomic_copy(
                    within(stage_root, entry.destination),
                    within(target_root, entry.destination),
                    entry.mode,
                )
                replaced.append(entry)
        except Exception as exc:
            for entry in reversed(replaced):
                target = within(target_root, entry.destination)
                if entry.destination in existed:
                    backup = within(backup_root, entry.destination)
                    atomic_copy(backup, target, stat.S_IMODE(backup.stat().st_mode))
                else:
                    target.unlink(missing_ok=True)
            raise ExportError(f"apply failed and was rolled back: {type(exc).__name__}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public_repo", nargs="?", default=str(DEFAULT_PUBLIC))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--apply", action="store_true", help="apply reviewed copy entries after staging")
    parser.add_argument(
        "--approve-digest",
        default="",
        help="required with --apply; exact SHA-256 of the reviewed manifest",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target_root = Path(args.public_repo).resolve()
    manifest_path = Path(args.manifest).resolve()
    digest = manifest_digest(manifest_path)
    try:
        entries = load_manifest(manifest_path)
        if not target_root.is_dir():
            raise ExportError(f"public repository does not exist: {target_root}")
        verify_target_inventory(entries, target_root)
        with tempfile.TemporaryDirectory(prefix="sulde-community-stage-") as stage_name:
            stage_root = Path(stage_name)
            stage(entries, REPO_ROOT, target_root, stage_root)
            scan_stage(stage_root)
            validate_stage(stage_root)
            changed = changed_copy_entries(entries, stage_root, target_root)
            print(f"manifest_sha256={digest}")
            print(f"files={len(entries)} copy_changes={len(changed)}")
            for entry in changed:
                print(f"  COPY {entry.source} -> {entry.destination}")
            if not args.apply:
                print("dry-run only; pass --apply --approve-digest <manifest_sha256> after review")
                return 0
            if args.approve_digest != digest:
                raise ExportError("--approve-digest does not match the reviewed manifest")
            if not git_clean(target_root):
                raise ExportError("public repository must be clean before --apply")
            apply(entries, changed, stage_root, target_root)
            print(f"applied={len(changed)}; commit and push remain manual")
            return 0
    except ExportError as exc:
        print(f"export-community: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

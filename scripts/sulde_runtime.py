#!/usr/bin/env python3
"""Shared, dependency-light helpers for Sulde's public command line tools."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


MIN_PYTHON = (3, 10)
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,50}$")


class SuldeCliError(RuntimeError):
    """Expected user-facing CLI failure."""


def configure_utf8() -> None:
    """Make CLI output deterministic on Windows code pages and POSIX shells."""
    for stream in (getattr(__import__("sys"), "stdout"), getattr(__import__("sys"), "stderr")):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
            except (LookupError, OSError):
                pass


def validate_slug(value: str) -> str:
    slug = value.strip().lower()
    if not SLUG_PATTERN.fullmatch(slug):
        raise SuldeCliError(
            "name must match ^[a-z][a-z0-9-]{1,50}$ "
            "(lowercase letters, numbers, and hyphens)"
        )
    return slug


def safe_relative_path(value: str) -> PurePosixPath:
    """Validate a manifest path without trusting suffixes or host separators."""
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise SuldeCliError(f"unsafe relative path: {value!r}")
    return path


def resolve_within(root: Path, relative: str | PurePosixPath) -> Path:
    root_resolved = root.resolve()
    rel = safe_relative_path(str(relative))
    candidate = (root_resolved / Path(*rel.parts)).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise SuldeCliError(f"path escapes root: {relative}") from exc
    return candidate


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SuldeCliError(f"missing file: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuldeCliError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SuldeCliError(f"JSON root must be an object: {path}")
    return value


def atomic_write_text(path: Path, content: str, *, overwrite: bool = True, mode: int | None = None) -> None:
    """Write UTF-8 via a same-directory temporary file and atomic replace."""
    if path.exists() and not overwrite:
        raise SuldeCliError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            temp_path.chmod(mode)
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def plugin_root_from_script(script_file: str) -> Path:
    return Path(script_file).resolve().parent.parent

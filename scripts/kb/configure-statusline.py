#!/usr/bin/env python3
"""Safely install Sulde's stable Claude Code status-line command."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

from sulde_paths import launcher_home


STATUS_LAUNCHER = Path("bin") / "sulde-statusline.py"
SETTINGS_ENV = "SULDE_CLAUDE_SETTINGS"
DEFAULT_BACKUP_LIMIT = 5
MISSING = object()


class ConfigError(RuntimeError):
    """An expected, user-actionable configuration failure."""


def configure_utf8_stdio() -> None:
    """Keep all CLI output safe and UTF-8 when the inherited console is cp936."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def absolute_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def default_kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return absolute_path(configured)
    return absolute_path(Path.home() / ".sulde" / "data" / "kb")


def default_settings_path() -> Path:
    configured = os.environ.get(SETTINGS_ENV)
    if configured:
        return absolute_path(configured)
    return absolute_path(Path.home() / ".claude" / "settings.json")


def resolve_runtime(kb_home: Path, python_override: str | None) -> tuple[Path, Path]:
    if python_override:
        python_path = absolute_path(python_override)
    elif os.name == "nt":
        python_path = kb_home / "venv" / "Scripts" / "python.exe"
    else:
        python_path = kb_home / "venv" / "bin" / "python"
    launcher_path = launcher_home(kb_home) / STATUS_LAUNCHER

    missing = [str(path) for path in (python_path, launcher_path) if not path.is_file()]
    if missing:
        raise ConfigError("required status-line runtime file is missing: " + ", ".join(missing))
    if os.name != "nt" and not os.access(python_path, os.X_OK):
        raise ConfigError(f"venv Python is not executable: {python_path}")
    return python_path, launcher_path


def quote_path(path: Path) -> str:
    value = str(path)
    if os.name != "nt":
        value = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
    return f'"{value}"'


def desired_status_line(python_path: Path, launcher_path: Path) -> dict[str, str]:
    return {
        "type": "command",
        "command": f"{quote_path(python_path)} {quote_path(launcher_path)}",
    }


def is_sulde_status_line(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("type") != "command":
        return False
    command = value.get("command")
    if not isinstance(command, str):
        return False
    normalized = command.replace("\\", "/")
    return bool(
        re.search(
            r'(?:"[^"]*/bin/sulde-statusline\.py"|[^\s"]*/bin/sulde-statusline\.py)\s*$',
            normalized,
        )
    )


def read_settings(path: Path) -> tuple[dict[str, Any], bytes | None]:
    if not path.exists():
        return {}, None
    if not path.is_file():
        raise ConfigError(f"settings path is not a file: {path}")
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"settings file is not valid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(f"settings JSON root must be an object: {path}")
    return parsed, raw


def serialized(settings: dict[str, Any]) -> str:
    return json.dumps(settings, ensure_ascii=False, indent=2) + "\n"


def backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}.{suffix}.bak")
        suffix += 1
    return candidate


def prune_generated_backups(path: Path, limit: int) -> None:
    if limit == 0:
        return
    pattern = re.compile(
        rf"^{re.escape(path.name)}\."
        r"(?P<stamp>\d{8}T\d{6}\.\d{6}Z)"
        r"(?:\.(?P<suffix>[1-9]\d*))?\.bak$"
    )
    matches: list[tuple[str, int, Path]] = []
    for candidate in path.parent.iterdir():
        match = pattern.fullmatch(candidate.name)
        if match and candidate.is_file():
            matches.append(
                (match.group("stamp"), int(match.group("suffix") or 0), candidate)
            )
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _, _, candidate in matches[limit:]:
        candidate.unlink()


def atomic_write(
    path: Path,
    content: str,
    original: bytes | None,
    backup_limit: int = DEFAULT_BACKUP_LIMIT,
) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    original_mode: int | None = None
    if original is not None:
        backup = backup_path(path)
        shutil.copy2(path, backup)
        original_mode = stat.S_IMODE(path.stat().st_mode)

    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if original_mode is not None:
            os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, path)
        prune_generated_backups(path, backup_limit)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return backup


def install(args: argparse.Namespace, settings_path: Path, kb_home: Path) -> int:
    python_path, launcher_path = resolve_runtime(kb_home, args.python_path)
    wanted = desired_status_line(python_path, launcher_path)
    settings, original = read_settings(settings_path)
    current = settings.get("statusLine", MISSING)

    if current == wanted:
        print(f"statusLine is already up to date: {wanted['command']}")
        return 0
    if current is not MISSING and not is_sulde_status_line(current) and not args.force:
        raise ConfigError(
            "refusing to overwrite a non-Sulde statusLine; use --install --force to replace it"
        )

    updated = dict(settings)
    updated["statusLine"] = wanted
    content = serialized(updated)
    if args.dry_run:
        print(f"dry-run: would write {settings_path}:\n{content}", end="")
        return 0
    backup = atomic_write(settings_path, content, original, args.backup_limit)
    backup_note = f"; backup: {backup}" if backup else ""
    print(f"statusLine installed: {wanted['command']}{backup_note}")
    return 0


def uninstall(args: argparse.Namespace, settings_path: Path) -> int:
    settings, original = read_settings(settings_path)
    current = settings.get("statusLine", MISSING)
    if current is MISSING:
        print("statusLine is already absent")
        return 0
    if not is_sulde_status_line(current):
        raise ConfigError("refusing to remove a non-Sulde statusLine")

    updated = dict(settings)
    del updated["statusLine"]
    content = serialized(updated)
    if args.dry_run:
        print(f"dry-run: would write {settings_path}:\n{content}", end="")
        return 0
    backup = atomic_write(settings_path, content, original, args.backup_limit)
    print(f"Sulde statusLine removed; backup: {backup}")
    return 0


def check(args: argparse.Namespace, settings_path: Path, kb_home: Path) -> int:
    python_path, launcher_path = resolve_runtime(kb_home, args.python_path)
    settings, _ = read_settings(settings_path)
    wanted = desired_status_line(python_path, launcher_path)
    if settings.get("statusLine") != wanted:
        raise ConfigError(f"statusLine is not installed with the expected command: {wanted['command']}")

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            [str(python_path), str(launcher_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=args.timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(f"status command could not run: {exc}") from exc
    elapsed_ms = (time.perf_counter() - started) * 1000
    output = completed.stdout.strip()
    if completed.returncode != 0:
        raise ConfigError(
            f"status command exited {completed.returncode} after {elapsed_ms:.1f} ms: "
            f"{completed.stderr.strip()}"
        )
    if not output:
        raise ConfigError(f"status command produced empty output after {elapsed_ms:.1f} ms")
    print(f"statusLine check OK ({elapsed_ms:.1f} ms): {output}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true", help="install or update Sulde statusLine")
    action.add_argument("--check", action="store_true", help="validate and execute Sulde statusLine")
    action.add_argument("--uninstall", action="store_true", help="remove Sulde's statusLine only")
    parser.add_argument("--force", action="store_true", help="replace a non-Sulde statusLine on install")
    parser.add_argument("--dry-run", action="store_true", help="show changes without writing")
    parser.add_argument("--kb-home", help="override SULDE_KB_HOME")
    parser.add_argument("--settings", help=f"override settings path (or set {SETTINGS_ENV})")
    parser.add_argument("--python", dest="python_path", help="override venv Python (primarily for tests)")
    parser.add_argument("--timeout", type=float, default=3.0, help="check timeout in seconds")
    parser.add_argument(
        "--backup-limit",
        type=int,
        default=DEFAULT_BACKUP_LIMIT,
        help=(
            "maximum generated settings backups to retain after writes "
            f"(default: {DEFAULT_BACKUP_LIMIT}; 0 disables pruning)"
        ),
    )
    args = parser.parse_args(argv)
    if args.force and not args.install:
        parser.error("--force is only valid with --install")
    if args.dry_run and args.check:
        parser.error("--dry-run is only valid with --install or --uninstall")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.backup_limit < 0:
        parser.error("--backup-limit must be non-negative")
    return args


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    args = parse_args(argv)
    settings_path = absolute_path(args.settings) if args.settings else default_settings_path()
    kb_home = absolute_path(args.kb_home) if args.kb_home else default_kb_home()
    try:
        if args.install:
            return install(args, settings_path, kb_home)
        if args.uninstall:
            return uninstall(args, settings_path)
        return check(args, settings_path, kb_home)
    except ConfigError as exc:
        print(f"configure-statusline: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"configure-statusline: filesystem error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create and rotate dated backups of Sulde memory state."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


BACKUP_PREFIX = "memory-"
BACKUP_SUFFIX = ".db"
FILE_BACKUPS = (
    ("distill-candidates.md", "distill-candidates-{date}.md"),
    ("recall-log.jsonl", "recall-log-{date}.jsonl"),
)
DATE_GROUP = re.compile(
    r"^(?:memory-(?P<memory>\d{8})\.db|"
    r"distill-candidates-(?P<distill>\d{8})\.md|"
    r"recall-log-(?P<recall>\d{8})\.jsonl)$"
)


class BackupError(RuntimeError):
    """Expected operational error (exit code 2)."""


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def backup_date(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError("--date must use YYYYMMDD") from error
    if parsed.strftime("%Y%m%d") != value:
        raise argparse.ArgumentTypeError("--date must use YYYYMMDD")
    return value


def positive_keep(value: str) -> int:
    try:
        keep = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--keep must be a positive integer") from error
    if keep < 1:
        raise argparse.ArgumentTypeError("--keep must be a positive integer")
    return keep


def grouped_dates(backup_dir: Path) -> list[str]:
    dates: set[str] = set()
    for candidate in backup_dir.iterdir():
        match = DATE_GROUP.fullmatch(candidate.name)
        if match and candidate.is_file():
            dates.add(next(value for value in match.groups() if value is not None))
    return sorted(dates)


def create_backup(home: Path, date: str, keep: int) -> tuple[list[Path], list[str]]:
    source_path = home / "memory.db"
    if not source_path.is_file():
        raise BackupError(f"memory database does not exist: {source_path}")
    backup_dir = home / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{BACKUP_PREFIX}{date}{BACKUP_SUFFIX}"
    staged: list[tuple[Path, Path]] = []
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=backup_dir
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        staged.append((temporary, target))
        source_uri = f"file:{quote(str(source_path.resolve()), safe='/')}?mode=ro"
        with sqlite3.connect(source_uri, uri=True, timeout=5.0) as source:
            with sqlite3.connect(str(temporary)) as destination:
                source.backup(destination)

        for source_name, target_pattern in FILE_BACKUPS:
            source = home / source_name
            if not source.is_file():
                continue
            extra_target = backup_dir / target_pattern.format(date=date)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{extra_target.name}.", suffix=".tmp", dir=backup_dir
            )
            os.close(descriptor)
            extra_temporary = Path(temporary_name)
            staged.append((extra_temporary, extra_target))
            shutil.copyfile(source, extra_temporary)

        for staged_path, final_path in staged:
            os.replace(staged_path, final_path)
    finally:
        for staged_path, _ in staged:
            staged_path.unlink(missing_ok=True)

    dates = grouped_dates(backup_dir)
    obsolete_dates = set(dates[:-keep])
    for candidate in backup_dir.iterdir():
        match = DATE_GROUP.fullmatch(candidate.name)
        if not match or not candidate.is_file():
            continue
        candidate_date = next(value for value in match.groups() if value is not None)
        if candidate_date in obsolete_dates:
            candidate.unlink()
    created = [final_path for _, final_path in staged]
    return created, grouped_dates(backup_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", type=positive_keep, default=4)
    parser.add_argument("--date", type=backup_date, default=datetime.now().strftime("%Y%m%d"))
    args = parser.parse_args()
    try:
        targets, retained_dates = create_backup(kb_home(), args.date, args.keep)
        for target in targets:
            print(f"backup={target} size={target.stat().st_size} bytes")
        print("retained_dates=" + ",".join(retained_dates))
        return 0
    except (BackupError, OSError, sqlite3.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

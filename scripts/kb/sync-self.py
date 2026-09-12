#!/usr/bin/env python3
"""Synchronize constitutional SELF sections without overwriting runtime reflection."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "templates/SELF.md"
SYNCED_SECTIONS = ("我的能力阶梯", "我能自主做什么")


class SyncError(RuntimeError):
    pass


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".sulde/data/kb"


def section(text: str, name: str) -> str:
    match = re.search(rf"^## {re.escape(name)}\s*$.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise SyncError(f"missing section: {name}")
    return match.group(0).rstrip()


def synchronize(template: str, runtime: str) -> str:
    result = runtime
    for name in SYNCED_SECTIONS:
        replacement = section(template, name)
        pattern = rf"^## {re.escape(name)}\s*$.*?(?=^## |\Z)"
        result, count = re.subn(pattern, replacement + "\n\n", result, count=1, flags=re.MULTILINE | re.DOTALL)
        if count != 1:
            raise SyncError(f"runtime section count is not one: {name}")
    return result.rstrip() + "\n"


def atomic_write(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    runtime_path = kb_home() / "SELF.md"
    template = TEMPLATE.read_text(encoding="utf-8")
    runtime = runtime_path.read_text(encoding="utf-8")
    merged = synchronize(template, runtime)
    changed = merged != runtime
    if args.apply and changed:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = runtime_path.with_name(f"SELF.md.backup-{stamp}")
        shutil.copy2(runtime_path, backup)
        atomic_write(runtime_path, merged)
        print(f"SELF SYNC: UPDATED backup={backup}")
    else:
        print(f"SELF SYNC: {'DRIFT' if changed else 'CURRENT'} writes=0")
    return 1 if args.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())

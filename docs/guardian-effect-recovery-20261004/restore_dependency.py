"""Exact, no-overwrite recovery of three reviewed archived dependency files.

Not a plugin installer, a permission bypass or a claim of upstream freshness.
Destination changes require the current host's separately approved repair card.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


PINS = {
    "update_plugin_cachebuster.py": "6a630dfbdc2bca6952580da9c2c7ece08030926819ccd81d9deb518c24c1b0ed",
    "identifier_validation.py": "a6d51ce4a9a7e8f85626ff5808a467a67574e7f8cdf1167ffb467c5f67e57223",
    "validate_plugin.py": "f4eeadb733b28b0c3e714de263a76d6542866a672f3e99bdffcf4dbcdf85e944",
}


def safe_path(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("symlink dependency path rejected")


def restore(source: Path, destination: Path, *, apply: bool = False) -> dict:
    safe_path(source)
    safe_path(destination)
    contents = {}
    for name, expected in PINS.items():
        src, dst = source / name, destination / name
        safe_path(src)
        safe_path(dst)
        content = src.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("archive digest mismatch: " + name)
        if dst.exists() and dst.read_bytes() != content:
            raise ValueError("destination conflict: " + name)
        contents[name] = content
    if apply:
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name, content in contents.items():
            dst = destination / name
            safe_path(dst)
            if dst.exists():
                if dst.read_bytes() != content:
                    raise ValueError("destination changed: " + name)
                continue
            # Exclusive creation never overwrites another writer. A crash can
            # leave a partial file: subsequent recovery refuses that conflict.
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        for name, expected in PINS.items():
            safe_path(destination / name)
            if hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected:
                raise ValueError("recovery readback mismatch: " + name)
    return {"applied": apply, "sha256": PINS, "source": str(source),
            "destination": str(destination), "upstream_current_version": "unverified"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(restore(args.source, args.destination, apply=args.apply), indent=2))

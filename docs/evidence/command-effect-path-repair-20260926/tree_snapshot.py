#!/usr/bin/env python3
"""Snapshot a tree's file inventory + sha256 (hygiene proof for acceptance).

Excludes .git and derived bytecode (__pycache__, *.pyc/pyo). Prints one JSON
object: {root, file_count, tree_sha256, files: {relpath: sha256}}.
Bytecode presence is reported separately so the driver can assert absence.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

root = Path(sys.argv[1]).resolve()
files: dict[str, str] = {}
bytecode: list[str] = []
for path in sorted(root.rglob("*")):
    if not path.is_file():
        continue
    rel = path.relative_to(root)
    parts = rel.parts
    if ".git" in parts:
        continue
    if "__pycache__" in parts or path.suffix in {".pyc", ".pyo"}:
        bytecode.append(str(rel))
        continue
    files[str(rel)] = hashlib.sha256(path.read_bytes()).digest().hex()
digest = hashlib.sha256()
for rel in sorted(files):
    digest.update(rel.encode())
    digest.update(bytes.fromhex(files[rel]))
print(json.dumps({
    "root": str(root),
    "file_count": len(files),
    "tree_sha256": digest.hexdigest(),
    "bytecode_paths": bytecode,
    "files": files,
}))

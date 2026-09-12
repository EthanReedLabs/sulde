#!/usr/bin/env python3
"""Reject sensitive terms and secret-shaped values in changed knowledge files."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Pattern


REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = REPO_ROOT / "knowledge"
SECRET_SCANNER = Path(__file__).with_name("mem-secret-scan.py")


class DenyLintError(RuntimeError):
    """Invalid invocation or local configuration (exit 2)."""


def kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def load_secret_patterns() -> tuple[tuple[str, Pattern[str]], ...]:
    spec = importlib.util.spec_from_file_location("mem_secret_scan", SECRET_SCANNER)
    if spec is None or spec.loader is None:
        raise DenyLintError(f"cannot load secret patterns from {SECRET_SCANNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    patterns = getattr(module, "PATTERNS", None)
    if not isinstance(patterns, tuple):
        raise DenyLintError("mem-secret-scan PATTERNS is unavailable")
    return patterns


def load_deny_patterns(home: Path) -> list[str]:
    path = home / "sediment-deny.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DenyLintError(f"invalid deny configuration: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"patterns"}:
        raise DenyLintError("deny configuration must contain only a patterns array")
    values = payload["patterns"]
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value.strip() for value in values
    ):
        raise DenyLintError("deny configuration patterns must be non-empty strings")
    return [value.strip() for value in values]


def staged_knowledge_files() -> list[Path]:
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=AM",
            "-z",
            "--",
            "knowledge",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise DenyLintError("cannot enumerate staged knowledge files")
    return [
        REPO_ROOT / Path(raw.decode("utf-8"))
        for raw in completed.stdout.split(b"\0")
        if raw
    ]


def resolve_paths(arguments: list[Path]) -> list[Path]:
    candidates = arguments or staged_knowledge_files()
    resolved: list[Path] = []
    root = KNOWLEDGE_ROOT.resolve()
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else REPO_ROOT / candidate
        try:
            actual = path.resolve(strict=True)
            actual.relative_to(root)
        except (OSError, ValueError) as error:
            raise DenyLintError(f"path is not a knowledge file: {candidate}") from error
        if not actual.is_file():
            raise DenyLintError(f"path is not a file: {candidate}")
        if actual not in resolved:
            resolved.append(actual)
    return resolved


def scan(paths: list[Path], deny_patterns: list[str]) -> list[tuple[Path, int, str]]:
    secret_patterns = load_secret_patterns()
    violations: list[tuple[Path, int, str]] = []
    folded_denies = [(index, value.casefold()) for index, value in enumerate(deny_patterns, 1)]
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as error:
            raise DenyLintError(f"cannot read {path}: {error}") from error
        for number, line in enumerate(lines, 1):
            folded = line.casefold()
            for index, pattern in folded_denies:
                if pattern in folded:
                    violations.append((path, number, f"local deny pattern #{index}"))
            for name, pattern in secret_patterns:
                if pattern.search(line):
                    violations.append((path, number, f"secret pattern {name}"))
    return violations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="knowledge files to scan (default: staged added/modified files)",
    )
    return parser.parse_args()


def main() -> int:
    try:
        args = parse_args()
        paths = resolve_paths(args.paths)
        violations = scan(paths, load_deny_patterns(kb_home()))
    except DenyLintError as error:
        print(f"kb-deny-lint: {error}", file=sys.stderr)
        return 2
    if violations:
        print(f"kb deny lint failed: {len(violations)} violation(s)")
        for path, line, category in violations:
            print(f"{path.relative_to(REPO_ROOT)}:{line}: {category}")
        return 1
    print(f"kb deny lint passed: {len(paths)} knowledge file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

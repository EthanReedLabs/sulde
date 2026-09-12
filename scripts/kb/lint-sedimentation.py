#!/usr/bin/env python3
"""Validate sedimentation-v2 semantics and require v2 on substantive KB writes."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sedimentation_schema import split_document, validate_document  # noqa: E402


KNOWLEDGE_CONTAINERS = {"anti-patterns", "platform-kb", "tech-docs", "work-model"}


def _knowledge_document(path: Path) -> bool:
    return (
        path.suffix.lower() == ".md"
        and len(path.parts) >= 3
        and path.parts[0] == "knowledge"
        and path.parts[1] in KNOWLEDGE_CONTAINERS
        and path.name not in {"INDEX.md", "README.md"}
    )


def tracked_documents() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "knowledge"], cwd=ROOT
    )
    return sorted(
        (Path(raw.decode("utf-8")) for raw in output.split(b"\0") if raw),
        key=lambda item: item.as_posix(),
    )


def staged_changes() -> dict[Path, str]:
    changed_output = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "-z", "--", "knowledge"],
        cwd=ROOT,
    )
    added_output = subprocess.check_output(
        [
            "git", "diff", "--cached", "--name-only", "--diff-filter=A", "-z",
            "--", "knowledge",
        ],
        cwd=ROOT,
    )
    changed = {Path(raw.decode("utf-8")) for raw in changed_output.split(b"\0") if raw}
    added = {Path(raw.decode("utf-8")) for raw in added_output.split(b"\0") if raw}
    return {path: "A" if path in added else "M" for path in changed}


def staged_markdown(path: Path) -> str:
    """Read exactly what a pre-commit would commit, never the working-tree copy."""
    completed = subprocess.run(
        ["git", "show", f":{path.as_posix()}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "path is absent from the git index"
        raise ValueError(f"cannot read staged document: {detail}")
    return completed.stdout


def substantive_staged_change(path: Path, status: str) -> bool:
    if status == "A":
        return True
    completed = subprocess.run(
        ["git", "diff", "--cached", "--unified=0", "--", path.as_posix()],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        return True
    for line in completed.stdout.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        content = line[1:].strip()
        if not content or content.startswith("related:"):
            continue
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    changes = staged_changes()
    explicit = bool(args.paths)
    candidates = args.paths if explicit else tracked_documents()
    violations: list[tuple[Path, str]] = []
    validated = 0
    for raw in candidates:
        relative = raw if not raw.is_absolute() else raw.resolve().relative_to(ROOT.resolve())
        if not _knowledge_document(relative) or not (ROOT / relative).is_file():
            continue
        try:
            markdown = (
                (ROOT / relative).read_text(encoding="utf-8")
                if explicit
                else staged_markdown(relative)
            )
        except (OSError, UnicodeError, ValueError) as error:
            violations.append((relative, str(error)))
            continue
        try:
            fields, _body = split_document(markdown)
        except ValueError as error:
            violations.append((relative, str(error)))
            continue
        require_v2 = explicit or (
            relative in changes and substantive_staged_change(relative, changes[relative])
        )
        if not require_v2 and not fields.get("sedimentation_schema"):
            continue
        validated += 1
        violations.extend(
            (relative, error)
            for error in validate_document(markdown, root=ROOT, require_v2=require_v2)
        )
    if violations:
        print(f"sedimentation lint failed: {len(violations)} violation(s)")
        for relative, message in violations:
            print(f"{relative}: {message}")
        return 1
    print(f"sedimentation lint passed: {validated} v2 document(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

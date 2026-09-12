#!/usr/bin/env python3
"""Lint retrieval-contract frontmatter in tracked knowledge Markdown files."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


CONTAINERS = {"anti-patterns", "platform-kb", "tech-docs", "case-studies", "work-model"}
PLATFORMS = {"android", "ios", "flutter", "harmonyos", "web", "cross", "none"}
CONTAINER_DIRS = {"anti-patterns", "platform-kb", "tech-docs", "work-model"}
PLATFORM_DIRS = {
    "android": "android",
    "ios": "ios",
    "flutter": "flutter",
    "harmonyos": "harmonyos",
    "web": "web",
    "harmony": "harmonyos",
    "mobile-android-ios": "cross",
}
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tracked_documents(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "knowledge"], cwd=root
    )
    result = []
    for raw_path in output.split(b"\0"):
        if not raw_path:
            continue
        path = Path(raw_path.decode("utf-8"))
        if (
            path.suffix.lower() == ".md"
            and len(path.parts) >= 3
            and path.parts[0] == "knowledge"
            and path.parts[1] in CONTAINER_DIRS
        ):
            result.append(path)
    return sorted(result, key=lambda path: path.as_posix())


def expected(path: Path) -> tuple[str, str, str]:
    relative = path.relative_to("knowledge")
    top = relative.parts[0]
    slug = relative.with_suffix("").as_posix()
    if top == "anti-patterns":
        match = re.match(r"^(\d{4})-", path.name)
        return (f"ap-{match.group(1)}" if match else slug, "anti-patterns", "none")
    if top == "platform-kb":
        if len(relative.parts) == 2:
            return slug, "platform-kb", "none"
        platform_dir = relative.parts[1]
        if platform_dir not in PLATFORM_DIRS:
            raise ValueError(f"unsupported platform directory: {platform_dir}")
        return slug, "platform-kb", PLATFORM_DIRS[platform_dir]
    if top == "tech-docs":
        container = (
            "case-studies"
            if len(relative.parts) >= 3 and relative.parts[1] == "案例研究"
            else "tech-docs"
        )
        return slug, container, "none"
    return slug, "work-model", "none"


def decode_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def parse_frontmatter(path: Path, text: str) -> tuple[dict[str, str], list[str]]:
    lines = text.splitlines()
    errors: list[str] = []
    if not lines or lines[0].strip() != "---":
        return {}, ["missing frontmatter at first line"]
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return {}, ["frontmatter is not closed"]
    fields: dict[str, str] = {}
    for number, line in enumerate(lines[1:end], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = KEY_RE.match(line)
        if not match:
            errors.append(f"malformed flat field at line {number}")
            continue
        key, raw_value = match.groups()
        if key in fields:
            errors.append(f"duplicate field: {key}")
            continue
        try:
            fields[key] = decode_scalar(raw_value or "")
        except (ValueError, json.JSONDecodeError):
            errors.append(f"invalid scalar for {key}")
    return fields, errors


def related_ids(raw: str) -> list[str] | None:
    raw = raw.strip()
    if not (raw.startswith("[") and raw.endswith("]")):
        return None
    inner = raw[1:-1].strip()
    if not inner:
        return []
    return [item.strip().strip("'\"") for item in inner.split(",") if item.strip()]


def main() -> int:
    root = repo_root()
    documents = tracked_documents(root)
    violations: list[tuple[Path, str]] = []
    parsed: dict[Path, dict[str, str]] = {}
    doc_id_paths: dict[str, list[Path]] = {}

    for relative in documents:
        fields, errors = parse_frontmatter(
            relative, (root / relative).read_text(encoding="utf-8")
        )
        parsed[relative] = fields
        violations.extend((relative, error) for error in errors)
        for key in ("doc_id", "container", "platform", "summary"):
            if not fields.get(key, "").strip():
                violations.append((relative, f"missing or empty field: {key}"))
        if fields.get("container") and fields["container"] not in CONTAINERS:
            violations.append((relative, f"invalid container: {fields['container']}"))
        if fields.get("platform") and fields["platform"] not in PLATFORMS:
            violations.append((relative, f"invalid platform: {fields['platform']}"))
        try:
            doc_id, container, platform = expected(relative)
            expected_fields = [("doc_id", doc_id), ("container", container)]
            if relative.parts[1] == "platform-kb":
                expected_fields.append(("platform", platform))
            for key, wanted in expected_fields:
                if fields.get(key) and fields[key] != wanted:
                    violations.append(
                        (relative, f"{key} does not match path: {fields[key]} != {wanted}")
                    )
        except ValueError as error:
            violations.append((relative, str(error)))
        if fields.get("doc_id"):
            doc_id_paths.setdefault(fields["doc_id"], []).append(relative)

    for doc_id, paths in doc_id_paths.items():
        if len(paths) > 1:
            joined = ", ".join(path.as_posix() for path in paths)
            violations.append((paths[0], f"duplicate doc_id {doc_id}: {joined}"))

    known_ids = set(doc_id_paths)
    for relative, fields in parsed.items():
        if "related" not in fields:
            continue
        targets = related_ids(fields["related"])
        if targets is None:
            violations.append((relative, "related must be an inline list: [doc-id, ...]"))
            continue
        for target in targets:
            if target not in known_ids:
                violations.append((relative, f"related target does not exist: {target}"))

    if violations:
        print(f"frontmatter lint failed: {len(violations)} violation(s)")
        for relative, message in violations:
            print(f"{relative}: {message}")
        return 1
    print(f"frontmatter lint passed: {len(documents)} tracked markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

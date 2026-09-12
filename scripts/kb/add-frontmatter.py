#!/usr/bin/env python3
"""Add retrieval-contract frontmatter to tracked knowledge Markdown files."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import subprocess
from pathlib import Path


REQUIRED_KEYS = ("doc_id", "container", "platform", "summary")
CONTAINER_DIRS = {"anti-patterns", "platform-kb", "tech-docs", "work-model"}
PLATFORM_DIRS = {
    "android": "android",
    "ios": "ios",
    "flutter": "flutter",
    "harmonyos": "harmonyos",
    "web": "web",
    # Historical directory names retained by this repository.
    "harmony": "harmonyos",
    "mobile-android-ios": "cross",
}
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
LIST_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
RULE_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
PLATFORM_BULLET_RE = re.compile(
    r"^\s*-\s+\*\*平台\*\*\s*[:：]\s*(.*?)\s*$", re.IGNORECASE
)
NUMBERED_TITLE_RE = re.compile(r"^\d{4}\s*(?:—|-)\s*")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def tracked_documents(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "knowledge"], cwd=root
    )
    documents: list[Path] = []
    for raw_path in output.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(raw_path.decode("utf-8"))
        if (
            relative.suffix.lower() == ".md"
            and len(relative.parts) >= 3
            and relative.parts[0] == "knowledge"
            and relative.parts[1] in CONTAINER_DIRS
        ):
            documents.append(relative)
    return sorted(documents, key=lambda path: path.as_posix())


def metadata_for(path: Path) -> tuple[str, str, str]:
    relative = path.relative_to("knowledge")
    top = relative.parts[0]
    slug = relative.with_suffix("").as_posix()
    if top == "anti-patterns":
        match = re.match(r"^(\d{4})-", path.name)
        doc_id = f"ap-{match.group(1)}" if match else slug
        return doc_id, "anti-patterns", "none"
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


def frontmatter_end(lines: list[str]) -> int | None:
    if not lines or lines[0].strip() != "---":
        return None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return index
    return None


def frontmatter_keys(lines: list[str], end: int | None) -> set[str]:
    if end is None:
        return set()
    keys: set[str] = set()
    for line in lines[1:end]:
        match = KEY_RE.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def document_title(lines: list[str], body_start: int, path: Path) -> str:
    for line in lines[body_start:]:
        match = HEADING_RE.match(line.strip())
        if match:
            return match.group(1).strip()
    return path.stem


def fallback_title(lines: list[str], body_start: int, path: Path) -> str:
    return NUMBERED_TITLE_RE.sub("", document_title(lines, body_start, path), count=1)


def derive_platform(
    lines: list[str], body_start: int, path: Path, path_platform: str
) -> str:
    if path.parts[1] == "platform-kb":
        return path_platform
    for line in lines[body_start:]:
        match = PLATFORM_BULLET_RE.match(line)
        if not match:
            continue
        value = re.sub(r"[（(][^）)]*[）)]", "", match.group(1))
        if "跨端" in value:
            return "cross"
        platforms: set[str] = set()
        mappings = (
            (r"(?i)harmonyos|鸿蒙", "harmonyos"),
            (r"(?i)android", "android"),
            (r"(?i)\bios\b", "ios"),
            (r"(?i)flutter", "flutter"),
            (r"(?i)\bweb\b|\bh5\b", "web"),
        )
        for pattern, platform in mappings:
            if re.search(pattern, value):
                platforms.add(platform)
        if len(platforms) >= 2:
            return "cross"
        if len(platforms) == 1:
            return next(iter(platforms))
        return "none"
    return "none"


def shorten(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    sentence = re.split(r"(?<=[。！？!?])|(?<=\.)\s+", text, maxsplit=1)[0]
    if len(sentence) <= limit:
        return sentence
    return sentence[: limit - 1].rstrip() + "…"


def derive_summary(lines: list[str], body_start: int, path: Path) -> tuple[str, str]:
    title = shorten(fallback_title(lines, body_start, path))
    title_seen = False
    index = body_start
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped or RULE_RE.match(stripped):
            index += 1
            continue
        if HEADING_RE.match(stripped):
            title_seen = True
            index += 1
            continue
        if not title_seen:
            title_seen = True
        if (
            stripped.startswith(("```", "~~~", "|", "![", "<table"))
            or LIST_RE.match(stripped)
        ):
            return title, "低"
        paragraph: list[str] = []
        while index < len(lines):
            part = lines[index].strip()
            if not part:
                break
            if HEADING_RE.match(part) or RULE_RE.match(part):
                break
            if part.startswith(">"):
                part = part.lstrip("> ").strip()
            paragraph.append(part)
            index += 1
        summary = shorten(" ".join(paragraph))
        return (summary, "高") if summary else (title, "低")
    return title, "低"


def yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def frontmatter_values(lines: list[str], end: int | None) -> dict[str, str]:
    if end is None:
        return {}
    values: dict[str, str] = {}
    for line in lines[1:end]:
        match = KEY_RE.match(line)
        if match:
            values[match.group(1)] = decode_scalar(match.group(2) or "")
    return values


def update_frontmatter(text: str, replacements: dict[str, str]) -> str:
    lines = text.splitlines(keepends=True)
    for index in range(1, len(lines)):
        plain = lines[index].rstrip("\r\n")
        if plain.strip() == "---":
            break
        match = KEY_RE.match(plain)
        if not match or match.group(1) not in replacements:
            continue
        ending = lines[index][len(plain) :]
        key = match.group(1)
        rendered = (
            yaml_string(replacements[key])
            if key == "summary"
            else replacements[key]
        )
        lines[index] = f"{key}: {rendered}{ending}"
    return "".join(lines)


def render_fields(doc_id: str, container: str, platform: str, summary: str) -> list[str]:
    return [
        f"doc_id: {yaml_string(doc_id)}",
        f"container: {container}",
        f"platform: {platform}",
        f"summary: {yaml_string(summary)}",
    ]


def write_if_changed(path: Path, content: str) -> None:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def review_report(rows: list[tuple[str, str, str, str]]) -> str:
    low = [row for row in rows if row[3] == "低"]
    distribution = Counter(platform for _, platform, _, _ in rows)
    distribution_text = "；".join(
        f"{platform} {distribution.get(platform, 0)}"
        for platform in ("android", "ios", "flutter", "harmonyos", "web", "cross", "none")
    )
    lines = [
        "# WP1 frontmatter summary 人审清单",
        "",
        f"> 共 {len(rows)} 个 tracked 文档；高置信 {len(rows) - len(low)}，低置信 {len(low)}。",
        f"> 平台分布：{distribution_text}。",
        "",
        "## 全量清单",
        "",
    ]
    lines.extend(
        f"{doc_id} | {platform} | {summary} | {confidence}"
        for doc_id, platform, summary, confidence in rows
    )
    lines.extend(["", f"## 低置信项（{len(low)}）", ""])
    lines.extend(
        f"{doc_id} | {platform} | {summary} | {confidence}"
        for doc_id, platform, summary, confidence in low
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    parser.add_argument(
        "--update",
        action="store_true",
        help="refresh only platform and fallback summary in existing frontmatter",
    )
    args = parser.parse_args()

    root = repo_root()
    documents = tracked_documents(root)
    rows: list[tuple[str, str, str, str]] = []
    changed = 0
    skipped = 0
    legacy_augmented = 0
    platform_updated = 0
    summary_updated = 0

    for relative in documents:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        end = frontmatter_end(lines)
        if lines and lines[0].strip() == "---" and end is None:
            raise ValueError(f"unclosed frontmatter: {relative}")
        body_start = end + 1 if end is not None else 0
        doc_id, container, path_platform = metadata_for(relative)
        platform = derive_platform(lines, body_start, relative, path_platform)
        derived_summary, confidence = derive_summary(lines, body_start, relative)
        values = frontmatter_values(lines, end)
        summary = (
            derived_summary
            if confidence == "低" or not values.get("summary")
            else values["summary"]
        )
        rows.append((doc_id, platform, summary, confidence))
        keys = frontmatter_keys(lines, end)
        missing = [key for key in REQUIRED_KEYS if key not in keys]
        if args.update and end is not None and not missing:
            replacements: dict[str, str] = {}
            if values.get("platform") != platform:
                replacements["platform"] = platform
                platform_updated += 1
            if confidence == "低" and values.get("summary") != summary:
                replacements["summary"] = summary
                summary_updated += 1
            if replacements:
                changed += 1
                if not args.dry_run:
                    path.write_text(
                        update_frontmatter(text, replacements), encoding="utf-8"
                    )
            else:
                skipped += 1
            continue
        if end is not None and not missing:
            skipped += 1
            continue

        fields = render_fields(doc_id, container, platform, summary)
        if end is None:
            new_text = "---\n" + "\n".join(fields) + "\n---\n\n" + text
        else:
            # Preserve legacy skill metadata and add only missing contract fields.
            values = dict(zip(REQUIRED_KEYS, fields))
            additions = [values[key] for key in missing]
            new_text = "\n".join([lines[0], *additions, *lines[1:]]) + "\n"
            legacy_augmented += 1
        changed += 1
        if not args.dry_run:
            path.write_text(new_text, encoding="utf-8")

    if not args.dry_run:
        report_path = root / ".codex-agent" / "wp1-summary-review.md"
        write_if_changed(report_path, review_report(rows))

    mode = "dry-run" if args.dry_run else "write"
    if args.update:
        mode = f"update-{mode}"
    low_count = sum(confidence == "低" for _, _, _, confidence in rows)
    print(
        f"{mode}: tracked={len(documents)} changed={changed} skipped={skipped} "
        f"platform_updated={platform_updated} summary_updated={summary_updated} "
        f"legacy_augmented={legacy_augmented} low_confidence={low_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

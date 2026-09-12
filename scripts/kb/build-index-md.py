#!/usr/bin/env python3
"""Build the deterministic T0/T1 knowledge catalog from tracked Markdown."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))

from common import git_tracked_documents

CONTAINER_ORDER = (
    "anti-patterns",
    "platform-kb",
    "tech-docs",
    "case-studies",
    "work-model",
)
KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$")
NUMBER_PREFIX_RE = re.compile(r"^\d{4}\s*(?:—|-)\s*")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def decode_scalar(value: str) -> str:
    value = value.strip()
    if value.startswith('"'):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, str) else str(decoded)
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def parse_document(path: Path, text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: missing frontmatter")
    try:
        end = next(
            index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
        )
    except StopIteration as error:
        raise ValueError(f"{path}: unclosed frontmatter") from error

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        match = KEY_RE.match(line)
        if match:
            fields[match.group(1)] = decode_scalar(match.group(2) or "")
    for key in ("doc_id", "container", "platform", "summary"):
        if not fields.get(key):
            raise ValueError(f"{path}: missing or empty {key}")

    title = ""
    for line in lines[end + 1 :]:
        match = H1_RE.match(line)
        if match:
            title = match.group(1).strip()
            break
    if not title:
        title = path.stem
    title = NUMBER_PREFIX_RE.sub("", title, count=1).strip()
    return fields, title


def render_index(root: Path) -> tuple[str, int]:
    sections: dict[str, list[tuple[str, str]]] = {
        container: [] for container in CONTAINER_ORDER
    }
    for relative in git_tracked_documents(root):
        fields, title = parse_document(
            relative, (root / relative).read_text(encoding="utf-8")
        )
        container = fields["container"]
        if container not in sections:
            raise ValueError(f"{relative}: unsupported container {container}")
        suffix = "" if fields["summary"] == title else f" — {fields['summary']}"
        if fields["platform"] != "none":
            suffix += f" [{fields['platform']}]"
        line = f"- {fields['doc_id']} {title}{suffix}"
        sections[container].append((fields["doc_id"], line))

    total = sum(len(entries) for entries in sections.values())
    lines = [
        "# 知识库索引",
        "",
        "> 生成时间戳：<deterministic-placeholder>；由 build-index-md.py 生成,勿手改。",
        f"> 文档总数：{total}",
        "",
    ]
    for container in CONTAINER_ORDER:
        lines.extend([f"## {container}", ""])
        lines.extend(line for _, line in sorted(sections[container], key=lambda item: item[0]))
        lines.append("")
    return "\n".join(lines), total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if knowledge/INDEX.md is stale"
    )
    args = parser.parse_args()

    root = repo_root()
    output_path = root / "knowledge" / "INDEX.md"
    rendered, total = render_index(root)
    if args.check:
        if not output_path.exists() or output_path.read_text(encoding="utf-8") != rendered:
            print("knowledge/INDEX.md is stale; rerun python3 scripts/kb/build-index-md.py")
            return 1
        print(f"knowledge/INDEX.md is current: {total} documents")
        return 0

    output_path.write_text(rendered, encoding="utf-8")
    print(f"generated knowledge/INDEX.md: {total} documents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

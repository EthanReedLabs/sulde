#!/usr/bin/env python3
"""Public Sulde CLI: health checks, extension scaffolds, and a local KB kit."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sulde_doctor import command as doctor_command
from sulde_extensions import command as extension_command
from sulde_knowledge import command as knowledge_command
from sulde_runtime import MIN_PYTHON, SuldeCliError, configure_utf8


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sulde", description="Sulde Community extension toolkit")
    parser.add_argument(
        "--plugin-root",
        default=str(Path(__file__).resolve().parent.parent),
        help="Sulde checkout or installed plugin root",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check runtime, plugin, extension, and project health")
    doctor.add_argument("--project", help="optional Sulde project to validate")
    doctor.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    doctor.add_argument("--strict", action="store_true", help="treat warnings as a non-zero result")
    doctor.set_defaults(handler=doctor_command)

    for operation, help_text in (
        ("add-skill", "scaffold a project-specific skill"),
        ("add-hook", "scaffold a hook extension"),
        ("add-check", "scaffold a doctor check"),
        ("add-knowledge-container", "register a knowledge container"),
    ):
        command = subparsers.add_parser(operation, help=help_text)
        command.add_argument("name", help="lowercase kebab-case name")
        command.add_argument("--description", default="", help="short purpose statement; generated skills add trigger context")
        command.add_argument("--root", help="fork/plugin root; defaults to --plugin-root")
        command.add_argument("--force", action="store_true", help="reserved; existing files are still preserved")
        if operation == "add-hook":
            command.add_argument(
                "--event",
                required=True,
                choices=("PreToolUse", "UserPromptSubmit", "SessionStart"),
            )
            command.add_argument("--matcher", default=".*", help="tool matcher for PreToolUse")
        command.set_defaults(handler=extension_command, operation=operation)

    kb = subparsers.add_parser("kb", help="grow a project-local, Git-tracked knowledge base")
    kb_sub = kb.add_subparsers(dest="kb_command", required=True)
    for name, help_text in (
        ("init", "copy the empty knowledge skeleton into a project"),
        ("add", "add a document after deterministic dedup and redaction gates"),
        ("dedup", "find likely duplicate documents"),
        ("redact", "scan a draft for likely sensitive or project-specific values"),
        ("lint", "validate frontmatter and paths"),
        ("index", "rebuild deterministic knowledge/INDEX.md"),
        ("search", "search locally without a service or model"),
        ("sediment", "turn an incident draft into a reviewed knowledge draft"),
    ):
        command = kb_sub.add_parser(name, help=help_text)
        command.add_argument("--root", default=".", help="project root (default: current directory)")
        command.set_defaults(handler=knowledge_command, kb_command=name)
        if name in {"add", "sediment"}:
            command.add_argument("--container", required=True)
            command.add_argument("--title", required=True)
            command.add_argument("--summary", required=True)
            command.add_argument("--platform", default="cross")
            command.add_argument(
                "--body",
                required=name == "add",
                help="reviewed UTF-8 markdown body file" if name == "add" else "optional reviewed replacement body",
            )
        if name == "sediment":
            command.add_argument("--source", required=True, help="incident/draft source file")
        if name in {"dedup", "search"}:
            command.add_argument("query")
            command.add_argument("-k", type=int, default=5)
        if name == "redact":
            command.add_argument("path")
            command.add_argument("--output", help="optional path for redacted copy; source is never overwritten")
        if name == "index":
            command.add_argument("--check", action="store_true")
        if name == "init":
            command.add_argument("--force", action="store_true", help="copy missing files; never overwrite content")

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_utf8()
    if sys.version_info[:2] < MIN_PYTHON:
        print("sulde: Python 3.10+ is required", file=sys.stderr)
        return 2
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except SuldeCliError as exc:
        print(f"sulde: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("sulde: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

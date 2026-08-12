#!/usr/bin/env python3
"""Idempotent extension scaffolds for Community forks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sulde_runtime import SuldeCliError, atomic_write_json, atomic_write_text, read_json, resolve_within, validate_slug


REGISTRY = "extensions/registry.json"
EVENTS = {"PreToolUse", "UserPromptSubmit", "SessionStart"}


def _description(args: Any, fallback: str) -> str:
    value = str(getattr(args, "description", "") or "").strip()
    return value or fallback


def _load_registry(root: Path) -> tuple[Path, dict[str, Any]]:
    path = resolve_within(root, REGISTRY)
    registry = read_json(path)
    for key in ("skills", "hooks", "checks", "knowledge_containers"):
        if not isinstance(registry.get(key), list):
            raise SuldeCliError(f"extension registry field must be a list: {key}")
    return path, registry


def _ensure_unique(registry: dict[str, Any], section: str, slug: str) -> None:
    for entry in registry[section]:
        if isinstance(entry, dict) and entry.get("name") == slug:
            raise SuldeCliError(f"{section} entry already exists: {slug}")


def _write_new(path: Path, content: str, *, mode: int | None = None) -> None:
    atomic_write_text(path, content, overwrite=False, mode=mode)


def _skill(root: Path, registry: dict[str, Any], slug: str, description: str) -> dict[str, str]:
    _ensure_unique(registry, "skills", slug)
    rel = f"skills/community/{slug}/SKILL.md"
    path = resolve_within(root, rel)
    trigger_description = f"{description.rstrip('.')} . Use when this project needs the `{slug}` workflow."
    trigger_description = trigger_description.replace(" .", ".")
    content = f"""---
name: {slug}
description: {json.dumps(trigger_description, ensure_ascii=False)}
---

# {slug}

## Inputs

- Required facts:
- Optional context:

## Procedure

1. Verify the current project state before making claims.
2. Make the smallest change that satisfies the stated acceptance criteria.
3. Capture objective verification evidence.

## Boundaries

- Do not widen write or publishing authority.
- Do not depend on private Sulde content or another agent host.

## Acceptance

- List the commands, files, or outputs that prove completion.
"""
    _write_new(path, content)
    registry["skills"].append({"name": slug, "path": rel, "description": trigger_description})
    return {"created": rel, "registered": "skills"}


def _hook(root: Path, registry: dict[str, Any], slug: str, description: str, event: str, matcher: str) -> dict[str, str]:
    if event not in EVENTS:
        raise SuldeCliError(f"unsupported hook event: {event}")
    _ensure_unique(registry, "hooks", slug)
    rel = f"extensions/hooks/{slug}.py"
    path = resolve_within(root, rel)
    content = f'''"""Project-specific deterministic Community hook."""

from __future__ import annotations

from typing import Any

DESCRIPTION = {json.dumps(description, ensure_ascii=False)}


def run(config: Any, payload: dict[str, Any]) -> None:
    """Observe {event}; remain silent unless the extension has useful context."""
    _ = (config, payload)
'''
    _write_new(path, content)
    registry["hooks"].append(
        {"name": slug, "event": event, "matcher": matcher, "module": rel, "description": description}
    )
    return {"created": rel, "registered": "hooks"}


def _check(root: Path, registry: dict[str, Any], slug: str, description: str) -> dict[str, str]:
    _ensure_unique(registry, "checks", slug)
    rel = f"extensions/checks/{slug}.py"
    path = resolve_within(root, rel)
    content = f'''"""Project-specific Community doctor check."""

from __future__ import annotations

from typing import Any

DESCRIPTION = {json.dumps(description, ensure_ascii=False)}


def run(context: dict[str, Any]) -> dict[str, str]:
    """Return status=pass|warn|error; never include secrets in messages."""
    _ = context
    return {{"status": "pass", "message": "{slug} check is installed"}}
'''
    _write_new(path, content)
    registry["checks"].append({"name": slug, "module": rel, "description": description})
    return {"created": rel, "registered": "checks"}


def _knowledge_container(
    root: Path, registry: dict[str, Any], slug: str, description: str
) -> dict[str, str]:
    _ensure_unique(registry, "knowledge_containers", slug)
    rel = f"template/_project/knowledge/containers/{slug}/README.md"
    path = resolve_within(root, rel)
    content = f"""# {slug}

{description}

This container starts empty. Add only de-identified, reusable engineering knowledge.
Every document must pass `sulde kb dedup`, `sulde kb redact`, and `sulde kb lint`.
"""
    _write_new(path, content)
    registry["knowledge_containers"].append(
        {"name": slug, "path": f"knowledge/containers/{slug}", "description": description}
    )
    container_registry_path = resolve_within(root, "template/_project/knowledge/containers.json")
    container_registry = read_json(container_registry_path)
    containers = container_registry.get("containers")
    if not isinstance(containers, list):
        raise SuldeCliError("template knowledge containers registry must contain a list")
    containers.append(
        {"name": slug, "path": f"containers/{slug}", "description": description}
    )
    atomic_write_json(container_registry_path, container_registry)
    return {"created": rel, "registered": "knowledge_containers"}


def command(args: Any) -> int:
    root = Path(args.root or args.plugin_root).resolve()
    registry_path, registry = _load_registry(root)
    slug = validate_slug(args.name)
    operation = str(args.operation)
    handlers = {
        "add-skill": lambda: _skill(root, registry, slug, _description(args, "Project-specific workflow")),
        "add-hook": lambda: _hook(
            root,
            registry,
            slug,
            _description(args, "Project-specific deterministic hook"),
            str(args.event),
            str(args.matcher),
        ),
        "add-check": lambda: _check(root, registry, slug, _description(args, "Project-specific health check")),
        "add-knowledge-container": lambda: _knowledge_container(
            root, registry, slug, _description(args, "Project-specific knowledge category")
        ),
    }
    result = handlers[operation]()
    atomic_write_json(registry_path, registry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

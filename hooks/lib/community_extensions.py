"""Load explicitly registered Community hook extensions exactly once."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

from sulde_common import SuldeConfig


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PLUGIN_ROOT / "extensions" / "registry.json"


def _registered_hooks() -> list[dict[str, Any]]:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"sulde: extension registry unavailable ({type(exc).__name__})\n")
        return []
    hooks = registry.get("hooks", []) if isinstance(registry, dict) else []
    return [entry for entry in hooks if isinstance(entry, dict)] if isinstance(hooks, list) else []


def _module_path(relative: str) -> Path | None:
    normalized = relative.replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        return None
    root = PLUGIN_ROOT.resolve()
    path = (root / Path(*normalized.split("/"))).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def run(event: str, config: SuldeConfig, payload: dict[str, Any]) -> None:
    tool_name = str(payload.get("tool_name", ""))
    for entry in _registered_hooks():
        if entry.get("event") != event:
            continue
        matcher = str(entry.get("matcher", ".*"))
        try:
            if event == "PreToolUse" and re.search(matcher, tool_name) is None:
                continue
        except re.error:
            sys.stderr.write(f"sulde: invalid matcher for extension {entry.get('name', '<unnamed>')}\n")
            continue
        module_path = _module_path(str(entry.get("module", "")))
        if module_path is None:
            sys.stderr.write(f"sulde: missing module for extension {entry.get('name', '<unnamed>')}\n")
            continue
        module_name = f"sulde_community_hook_{abs(hash(str(module_path)))}"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            continue
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            handler = getattr(module, "run", None)
            if callable(handler):
                handler(config, payload)
        except Exception as exc:
            # Keep hooks available while disclosing the failing extension type.
            sys.stderr.write(
                f"sulde: extension {entry.get('name', '<unnamed>')} failed ({type(exc).__name__})\n"
            )

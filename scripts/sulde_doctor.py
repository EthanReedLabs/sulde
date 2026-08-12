#!/usr/bin/env python3
"""Deterministic health checks for a source checkout or installed Sulde plugin."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sulde_runtime import MIN_PYTHON, SuldeCliError, read_json, resolve_within


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    message: str
    detail: str = ""


def _check(name: str, status: str, message: str, detail: str = "") -> Check:
    return Check(name=name, status=status, message=message, detail=detail)


def _version_tuple(raw: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", raw)
    return tuple(int(part) for part in numbers[:3])


def _load_custom_check(path: Path, context: dict[str, Any]) -> Check:
    module_name = f"sulde_public_check_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return _check(f"extension:{path.name}", "error", "cannot load custom check")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        runner = getattr(module, "run", None)
        if not callable(runner):
            return _check(f"extension:{path.name}", "error", "custom check has no run(context) function")
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with redirect_stdout(captured_stdout), redirect_stderr(captured_stderr):
            result = runner(context)
    except Exception as exc:  # extension boundary: report type, never dump project payloads
        return _check(f"extension:{path.name}", "error", "custom check raised", type(exc).__name__)
    if not isinstance(result, dict):
        return _check(f"extension:{path.name}", "error", "custom check must return an object")
    if captured_stdout.getvalue() or captured_stderr.getvalue():
        return _check(
            f"extension:{path.name}",
            "error",
            "custom check wrote directly to stdout/stderr",
            "return status/message/detail instead",
        )
    status = str(result.get("status", "error"))
    if status not in {"pass", "warn", "error"}:
        status = "error"
    return _check(
        f"extension:{path.name}",
        status,
        str(result.get("message", "custom check completed")),
        str(result.get("detail", "")),
    )


def run_checks(plugin_root: Path, project_root: Path | None = None) -> list[Check]:
    root = plugin_root.resolve()
    checks: list[Check] = []

    py_ok = sys.version_info[:2] >= MIN_PYTHON
    checks.append(
        _check(
            "python",
            "pass" if py_ok else "error",
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "requires Python 3.10+" if not py_ok else "",
        )
    )

    stdout_encoding = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")
    checks.append(
        _check(
            "utf8",
            "pass" if stdout_encoding == "utf8" else "warn",
            f"stdout encoding is {getattr(sys.stdout, 'encoding', None) or 'unknown'}",
            "hooks/run-hook.sh forces UTF-8 for production hooks",
        )
    )

    try:
        import yaml  # type: ignore

        yaml_version = str(getattr(yaml, "__version__", "0"))
        yaml_ok = _version_tuple(yaml_version) >= (6, 0)
        checks.append(
            _check(
                "pyyaml",
                "pass" if yaml_ok else "error",
                f"PyYAML {yaml_version}",
                "requires PyYAML 6.0+" if not yaml_ok else "",
            )
        )
    except ImportError:
        checks.append(_check("pyyaml", "error", "PyYAML is not installed", "install hooks/requirements.txt"))

    required = (
        ".claude-plugin/plugin.json",
        "hooks/hooks.json",
        "hooks/run-hook.sh",
        "bin/sulde",
        "scripts/sulde.py",
        "extensions/registry.json",
        "template/_project/knowledge/schema.yaml",
        "template/_project/knowledge/containers.json",
    )
    missing = [item for item in required if not (root / item).is_file()]
    checks.append(
        _check(
            "layout",
            "pass" if not missing else "error",
            "required plugin files are present" if not missing else f"missing {len(missing)} required file(s)",
            ", ".join(missing),
        )
    )

    manifest_path = root / ".claude-plugin" / "plugin.json"
    try:
        manifest = read_json(manifest_path)
        version_path = root / "VERSION"
        version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else ""
        issues: list[str] = []
        if manifest.get("version") != version:
            issues.append("VERSION and plugin.json differ")
        if "hooks" in manifest:
            issues.append("plugin.json explicitly registers auto-discovered hooks")
        checks.append(
            _check(
                "manifest",
                "pass" if not issues else "error",
                f"plugin manifest {manifest.get('version', 'unknown')}",
                "; ".join(issues),
            )
        )
    except (SuldeCliError, OSError, UnicodeError) as exc:
        checks.append(_check("manifest", "error", "plugin manifest is unreadable", str(exc)))

    hooks_path = root / "hooks" / "hooks.json"
    try:
        hooks = read_json(hooks_path)
        rendered = json.dumps(hooks, ensure_ascii=False)
        events = hooks.get("hooks", {})
        required_events = {"PreToolUse", "UserPromptSubmit", "SessionStart"}
        problems: list[str] = []
        if not isinstance(events, dict) or not required_events.issubset(events):
            problems.append("required hook events missing")
        if "run-hook.sh" not in rendered:
            problems.append("hook launcher is not used")
        if "python3 " in rendered:
            problems.append("hook manifest bypasses the cross-platform launcher")
        if '"shell": "bash"' not in rendered:
            problems.append("hook shell contract is not explicit")
        checks.append(
            _check(
                "hooks",
                "pass" if not problems else "error",
                "hook registration uses one launcher path",
                "; ".join(problems),
            )
        )
    except SuldeCliError as exc:
        checks.append(_check("hooks", "error", "hooks.json is unreadable", str(exc)))

    registry_path = root / "extensions" / "registry.json"
    custom_check_paths: list[Path] = []
    try:
        registry = read_json(registry_path)
        registry_issues: list[str] = []
        for key in ("skills", "hooks", "checks", "knowledge_containers"):
            if not isinstance(registry.get(key), list):
                registry_issues.append(f"{key} must be a list")
        for entry in registry.get("hooks", []) + registry.get("checks", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("module"), str):
                registry_issues.append("extension module entry is invalid")
                continue
            try:
                path = resolve_within(root, entry["module"])
            except SuldeCliError as exc:
                registry_issues.append(str(exc))
                continue
            if not path.is_file():
                registry_issues.append(f"missing extension module: {entry['module']}")
            elif entry in registry.get("checks", []):
                custom_check_paths.append(path)
        checks.append(
            _check(
                "extensions",
                "pass" if not registry_issues else "error",
                "extension registry is valid" if not registry_issues else "extension registry has errors",
                "; ".join(registry_issues),
            )
        )
    except SuldeCliError as exc:
        checks.append(_check("extensions", "error", "extension registry is unreadable", str(exc)))

    schema_path = root / "template" / "_project" / "knowledge" / "schema.yaml"
    try:
        import yaml  # type: ignore

        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        containers_registry = read_json(root / "template" / "_project" / "knowledge" / "containers.json")
        schema_ok = (
            isinstance(schema, dict)
            and isinstance(schema.get("containers"), dict)
            and isinstance(schema.get("platforms"), list)
            and isinstance(schema.get("required_frontmatter"), list)
            and isinstance(containers_registry.get("containers"), list)
        )
        checks.append(
            _check(
                "knowledge-kit",
                "pass" if schema_ok else "error",
                "knowledge schema is valid" if schema_ok else "knowledge schema is incomplete",
            )
        )
    except Exception as exc:
        checks.append(_check("knowledge-kit", "error", "knowledge schema is unreadable", type(exc).__name__))

    resolved_project = project_root.resolve() if project_root else None
    if resolved_project is not None:
        config_path = resolved_project / ".sulde-config.yaml"
        if not config_path.is_file():
            checks.append(_check("project", "warn", "project has not opted in", str(config_path)))
        else:
            try:
                import yaml  # type: ignore

                config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                config_ok = isinstance(config, dict) and isinstance(config.get("frontends"), list)
                checks.append(
                    _check(
                        "project",
                        "pass" if config_ok else "error",
                        "project configuration is readable" if config_ok else "project configuration is invalid",
                    )
                )
            except Exception as exc:
                checks.append(_check("project", "error", "project configuration is unreadable", type(exc).__name__))

    context = {
        "plugin_root": root,
        "project_root": resolved_project,
        "environment": {"os_name": os.name, "python": sys.version_info[:3]},
    }
    for path in custom_check_paths:
        checks.append(_load_custom_check(path, context))
    return checks


def emit(checks: list[Check], *, as_json: bool = False) -> None:
    counts = {status: sum(1 for item in checks if item.status == status) for status in ("pass", "warn", "error")}
    if as_json:
        print(json.dumps({"checks": [asdict(item) for item in checks], "summary": counts}, ensure_ascii=False, indent=2))
        return
    icons = {"pass": "✅", "warn": "⚠️", "error": "❌"}
    for item in checks:
        line = f"{icons[item.status]} {item.name}: {item.message}"
        if item.detail:
            line += f" — {item.detail}"
        print(line)
    print(f"\nSulde doctor: {counts['pass']} pass, {counts['warn']} warn, {counts['error']} error")


def command(args: Any) -> int:
    checks = run_checks(Path(args.plugin_root), Path(args.project).resolve() if args.project else None)
    emit(checks, as_json=args.json)
    if any(item.status == "error" for item in checks):
        return 1
    if args.strict and any(item.status == "warn" for item in checks):
        return 2
    return 0

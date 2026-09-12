#!/usr/bin/env python3
"""Register a project-relative sensitive path in Sulde and Claude settings."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import yaml
except ImportError:
    sys.stderr.write("sulde: pyyaml is required; run pip install pyyaml>=6.0\n")
    raise SystemExit(1)


def _project_root(start: Path) -> Path:
    cursor = start.resolve()
    while True:
        if (cursor / ".sulde-config.yaml").is_file():
            return cursor
        if cursor == cursor.parent:
            raise ValueError("no .sulde-config.yaml found; run /sulde-init first")
        cursor = cursor.parent


def _relative_path(raw: str) -> str:
    value = raw.strip().replace("\\", "/")
    candidate = PurePosixPath(value)
    if (
        not value
        or candidate.is_absolute()
        or re.match(r"^[A-Za-z]:/", value)
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("path must be a non-empty project-relative path without '.' or '..'")
    return candidate.as_posix()


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} root must be a mapping")
    sensitivity = value.setdefault("scope_sensitivity", {})
    if not isinstance(sensitivity, dict):
        raise ValueError("scope_sensitivity must be a mapping")
    sensitive_files = sensitivity.setdefault("sensitive_files", [])
    if not isinstance(sensitive_files, list):
        raise ValueError("scope_sensitivity.sensitive_files must be an array")
    return value


def _read_settings(path: Path) -> tuple[dict[str, Any], bool]:
    existed = path.is_file()
    if not existed:
        return {}, False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} root must be a JSON object")
    return value, True


def _append_once(items: list[Any], value: str) -> None:
    found = False
    deduplicated: list[Any] = []
    for item in items:
        if item == value:
            if found:
                continue
            found = True
        deduplicated.append(item)
    if not found:
        deduplicated.append(value)
    items[:] = deduplicated


def _prepare_deny(settings: dict[str, Any], relative: str) -> None:
    permissions = settings.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError("settings permissions must be a JSON object")
    deny = permissions.setdefault("deny", [])
    if not isinstance(deny, list):
        raise ValueError("settings permissions.deny must be an array")
    for rule in (f"Edit({relative})", f"Write({relative})"):
        _append_once(deny, rule)


def _stage(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    return temporary


def register(raw_path: str, start: Path) -> tuple[Path, str, bool]:
    root = _project_root(start)
    relative = _relative_path(raw_path)
    config_path = root / ".sulde-config.yaml"
    settings_path = root / ".claude" / "settings.json"
    backup_path = settings_path.with_name("settings.json.bak-sulde")

    config = _read_yaml(config_path)
    settings, settings_existed = _read_settings(settings_path)
    _prepare_deny(settings, relative)
    sensitive_files = config["scope_sensitivity"]["sensitive_files"]
    _append_once(sensitive_files, relative)

    config_temp = _stage(
        config_path,
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    )
    settings_temp = _stage(
        settings_path,
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
    )
    backup_created = False
    try:
        if settings_existed and not backup_path.exists():
            shutil.copy2(settings_path, backup_path)
            backup_created = True
        os.replace(config_temp, config_path)
        os.replace(settings_temp, settings_path)
    finally:
        for temporary in (config_temp, settings_temp):
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    verified_config = _read_yaml(config_path)
    verified_settings, _ = _read_settings(settings_path)
    verified_deny = verified_settings.get("permissions", {}).get("deny", [])
    if (
        verified_config["scope_sensitivity"]["sensitive_files"].count(relative) != 1
        or verified_deny.count(f"Edit({relative})") != 1
        or verified_deny.count(f"Write({relative})") != 1
    ):
        raise RuntimeError("post-write verification failed")
    return root, relative, backup_created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="project-relative sensitive file path")
    args = parser.parse_args()
    try:
        root, relative, backup_created = register(args.path, Path.cwd())
    except (OSError, RuntimeError, ValueError) as exc:
        sys.stderr.write(f"sulde: sensitive file registration failed: {exc}\n")
        return 1
    print(f"registered sensitive file: {relative}")
    print(f"advisory: {root / '.sulde-config.yaml'}")
    print(f"harness deny: {root / '.claude' / 'settings.json'}")
    print(f"backup created: {'yes' if backup_created else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

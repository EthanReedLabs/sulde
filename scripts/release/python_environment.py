"""Deterministic, read-only runtime preflight shared by candidate and installer.

An explicit SULDE_CANDIDATE_PYTHON selects one environment; otherwise the
invoking interpreter is selected. No fallback search or package installation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

SCHEMA = "sulde-python-environment-v1"
REPAIR = ("Create an explicitly chosen isolated venv, install hooks/requirements.txt there "
          "with approval, then invoke prepare/verify/install with that venv's Python and "
          "SULDE_CANDIDATE_PYTHON pointing to it. No system Python was modified.")
PROBE = r'''
import hashlib, json, pathlib, re, sqlite3, ssl, sys, venv
if not ((3, 10) <= sys.version_info[:2] <= (3, 14)):
    raise RuntimeError("supported Python versions: 3.10 through 3.14")
import yaml
version = tuple(int(x) for x in re.match(r"^(\d+)\.(\d+)", yaml.__version__).groups())
if version < (6, 0):
    raise RuntimeError("PyYAML >= 6.0 is required")
root = pathlib.Path(yaml.__file__).resolve().parent
entries = []
for path in sorted(root.rglob("*")):
    if path.is_file() and path.suffix in {".py", ".so", ".pyd", ".dll", ".dylib"}:
        entries.append([str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest()])
print(json.dumps({"version": list(sys.version_info[:3]), "implementation": sys.implementation.name,
 "cache_tag": sys.implementation.cache_tag, "prefix": str(pathlib.Path(sys.prefix).resolve()),
 "base_prefix": str(pathlib.Path(sys.base_prefix).resolve()),
 "dependencies": {"PyYAML": {"version": yaml.__version__, "root": str(root),
    "content_sha256": hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()},
    "sqlite3": sqlite3.sqlite_version, "ssl": ssl.OPENSSL_VERSION, "venv": "available"}}))
'''


class PythonEnvironmentError(RuntimeError):
    pass


def selected_python() -> Path:
    return Path(os.environ.get("SULDE_CANDIDATE_PYTHON") or sys.executable).expanduser().absolute()


def inspect_python(interpreter: Path) -> dict:
    # Keep the venv invocation path: resolving its symlink selects a different
    # sys.prefix even when the two executable files have identical bytes.
    selected = interpreter.expanduser().absolute()
    try:
        binary = selected.resolve(strict=True)
        before = hashlib.sha256(binary.read_bytes()).hexdigest()
        result = subprocess.run([str(selected), "-I", "-B", "-c", PROBE],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
        if result.returncode:
            reason = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "probe failed"
            raise PythonEnvironmentError(f"Python dependency preflight failed for {selected}: {reason}. {REPAIR}")
        facts = json.loads(result.stdout)
        if hashlib.sha256(binary.read_bytes()).hexdigest() != before:
            raise PythonEnvironmentError("Python executable changed during preflight")
        return {"schema": SCHEMA, "executable": str(selected), "executable_sha256": before,
                "environment": facts}
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise PythonEnvironmentError(f"Python preflight unavailable for {selected}: {type(error).__name__}. {REPAIR}") from error


def validate_python(identity: dict) -> dict:
    if not isinstance(identity, dict) or identity.get("schema") != SCHEMA:
        raise PythonEnvironmentError("Python environment identity is missing; prepare a new candidate")
    current = inspect_python(Path(identity["executable"]))
    if current != identity:
        raise PythonEnvironmentError("Python identity changed (interpreter, environment or dependency content); prepare and verify again")
    return current


def invoking_environment() -> dict:
    identity = inspect_python(selected_python())
    if selected_python() != Path(sys.executable).absolute():
        current = inspect_python(Path(sys.executable))
        if current["environment"] != identity["environment"] or current["executable_sha256"] != identity["executable_sha256"]:
            raise PythonEnvironmentError("Invoke this command with the selected SULDE_CANDIDATE_PYTHON; environment switching is not implicit. " + REPAIR)
    return identity


def same_runtime(left: dict, right: dict) -> bool:
    """Copied venv paths differ, but interpreter and loaded dependencies must not."""
    def material(value):
        facts = dict(value["environment"])
        facts.pop("prefix", None)
        dependencies = dict(facts["dependencies"])
        yaml = dict(dependencies["PyYAML"])
        # The loaded package's location is provenance, not its content identity.
        # Compare bytes/version across venvs; validate_python still binds the
        # complete path-bearing identity when checking one exact receipt.
        yaml.pop("root", None)
        dependencies["PyYAML"] = yaml
        facts["dependencies"] = dependencies
        return value["executable_sha256"], facts
    return material(left) == material(right)

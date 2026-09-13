#!/usr/bin/env python3
"""Install and verify version-independent Sulde runtime launchers.

The generated launchers are derived artifacts.  This module gives them an
explicit installation contract so a plugin update cannot look healthy while
``SULDE_HOME/bin`` still contains an older launcher specification.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sulde_paths import launcher_home as canonical_launcher_home


SCHEMA = "sulde-launcher-install-v1"
SPEC_VERSION = 12
MANIFEST_NAME = ".sulde-launchers.json"
DELIVERY_GENERATION_SCHEMA = "sulde-delivery-generation-v1"
DELIVERY_GENERATION_NAME = "generation.json"
COMMAND_EFFECT_SCHEMA = "sulde-command-effect-snapshot-v1"
COMMAND_EFFECT_SPEC_VERSION = 2
COMMAND_EFFECT_MANIFEST_NAME = ".sulde-command-effects.json"
DEPLOYMENT_GENERATION_NAME = "deployment-generation.json"
RUNTIME_OWNER_NAME = "runtime-owner.json"
SCHEDULER_RUNNER_NAMES = frozenset(
    {"sulde-scheduled-run", "sulde-windows-task.py"}
)
RUNTIME_CODE_PREFIXES = (
    Path("hooks/lib"),
    Path("scripts/kb"),
    Path("tools/kb-index"),
    Path("tools/kb-mcp"),
)
CODEX_HOOK_ADAPTERS = {
    "session-start": "scripts/session-start.py",
    "user-prompt-submit": "scripts/user-prompt-submit.py",
    "pre-tool-use": "scripts/pre-tool-use.py",
    "permission-request": "scripts/pre-tool-use.py",
    "post-tool-use": "scripts/post-tool-use.py",
    "stop": "scripts/stop.py",
}
CODEX_RUNTIME_HOOKS = tuple(
    f"runtime/hooks/{name}"
    for name in (
        "session_start.py",
        "user_prompt_submit.py",
        "pre_tool_use.py",
        "post_tool_use.py",
        "stop.py",
    )
)
CODEX_RUNTIME_HOOK_BY_EVENT = {
    "session-start": "runtime/hooks/session_start.py",
    "user-prompt-submit": "runtime/hooks/user_prompt_submit.py",
    "pre-tool-use": "runtime/hooks/pre_tool_use.py",
    "permission-request": "runtime/hooks/pre_tool_use.py",
    "post-tool-use": "runtime/hooks/post_tool_use.py",
    "stop": "runtime/hooks/stop.py",
}
CODEX_HOOK_SURFACE = (
    ".codex-plugin/plugin.json",
    "scripts/_adapter_common.py",
    "scripts/_hook_observer.py",
    "scripts/_hook_entry.py",
    *dict.fromkeys(CODEX_HOOK_ADAPTERS.values()),
    *dict.fromkeys(CODEX_RUNTIME_HOOKS),
)


def _is_sha256(value: Any) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class LauncherSpec:
    name: str
    override_env: str
    target_relative: str
    target_kind: str


@dataclass(frozen=True)
class ScriptEffectProfile:
    profile_id: str
    script_relative: str
    effect: str
    argv_contract: str
    root_kind: str = "codex-home"


LAUNCHERS = (
    LauncherSpec(
        "sulde-statusline.py",
        "SULDE_STATUS_SCRIPT",
        "scripts/kb/sulde-statusline.py",
        "statusline",
    ),
    LauncherSpec("kb-index", "SULDE_KB_INDEX", "scripts/kb/kb-index", "python"),
    LauncherSpec("sulde-kb-mcp", "SULDE_KB_MCP", "scripts/kb/kb-mcp", "python"),
    LauncherSpec("mem-sync", "SULDE_MEM_SYNC", "scripts/kb/mem-sync.py", "python"),
    LauncherSpec(
        "model-dispatch",
        "SULDE_MODEL_DISPATCH",
        "scripts/kb/model-dispatch.py",
        "python",
    ),
    LauncherSpec(
        "intent-guardian",
        "SULDE_INTENT_GUARDIAN",
        "scripts/kb/intent-guardian.py",
        "python",
    ),
)


# These are declarations of the only script *shapes* Sulde understands.  They
# do not grant trust by themselves: installation must also pin the exact local
# script and interpreter bytes in a protected snapshot outside the workspace.
SCRIPT_EFFECT_PROFILES = (
    ScriptEffectProfile(
        "codex-plugin-validate-v1",
        "skills/.system/plugin-creator/scripts/validate_plugin.py",
        "read",
        "plugin-root-only",
    ),
    ScriptEffectProfile(
        "codex-plugin-cachebuster-v1",
        "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py",
        "local_write",
        "plugin-root-with-optional-cachebuster",
    ),
    ScriptEffectProfile(
        "sulde-agent-runtime-git-lifecycle-v1",
        "scripts/kb/agent-runtime.py",
        "local_write",
        "agent-runtime-git-lifecycle-v1",
        "runtime",
    ),
)


class LauncherContractError(RuntimeError):
    """The generated launcher installation is incomplete or stale."""


def configure_utf8_stdio() -> None:
    for stream_name in ("stdin", "stdout", "stderr"):
        stream = getattr(__import__("sys"), stream_name)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (LookupError, OSError):
                pass


def default_kb_home() -> Path:
    from sulde_paths import kb_home as canonical_kb_home

    return canonical_kb_home()


def default_source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_codex_home(
    environment: dict[str, str] | None = None,
) -> Path:
    env = os.environ if environment is None else environment
    configured = env.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_files(source_root: Path) -> Iterable[Path]:
    for prefix in RUNTIME_CODE_PREFIXES:
        directory = source_root / prefix
        if not directory.is_dir():
            raise LauncherContractError(
                f"runtime code directory is missing: {directory}"
            )
        for path in sorted(directory.rglob("*")):
            relative_parts = path.relative_to(source_root).parts
            if "__pycache__" in relative_parts or path.suffix.casefold() == ".pyc":
                raise LauncherContractError(
                    f"runtime code contains executable Python bytecode: {path}"
                )
            if not path.is_file():
                continue
            yield path


def runtime_digest(source_root: Path) -> str:
    """Hash runtime paths and bytes so source and installed wiring cannot drift."""
    root = source_root.resolve()
    digest = hashlib.sha256()
    for path in _runtime_files(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _runtime_tree_digest(source_root: Path, *, ignore_bytecode: bool) -> str:
    argument = source_root.expanduser()
    if argument.is_symlink():
        raise LauncherContractError(f"runtime root is a symlink: {argument}")
    root = argument.resolve()
    if not root.is_dir():
        raise LauncherContractError(f"runtime is missing: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise LauncherContractError(f"runtime tree contains a symlink: {path}")
        relative_parts = path.relative_to(root).parts
        if ".git" in relative_parts:
            raise LauncherContractError(
                f"runtime tree contains repository metadata: {path}"
            )
        if "__pycache__" in relative_parts or path.suffix.casefold() == ".pyc":
            if ignore_bytecode:
                continue
            raise LauncherContractError(
                f"runtime tree contains executable Python bytecode: {path}"
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def runtime_tree_digest(source_root: Path) -> str:
    """Hash the complete immutable runtime using the delivery algorithm."""
    return _runtime_tree_digest(source_root, ignore_bytecode=False)


def _delivery_generation_payload(source_root: Path) -> dict[str, Any] | None:
    root = source_root.expanduser().resolve()
    path = root.parent / ".codex-plugin" / DELIVERY_GENERATION_NAME
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise LauncherContractError(f"delivery generation is unsafe: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LauncherContractError(f"delivery generation is invalid: {path}") from error
    version = payload.get("plugin_version") if isinstance(payload, dict) else None
    if not isinstance(payload, dict) or not isinstance(version, str) or not version:
        raise LauncherContractError("delivery generation has no plugin version")
    expected = {
        "schema": DELIVERY_GENERATION_SCHEMA,
        "schema_version": 1,
        "provider": "codex",
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise LauncherContractError(f"delivery generation mismatch: {key}")
    tree_sha256 = payload.get("runtime_tree_sha256")
    generation = payload.get("generation")
    if not isinstance(tree_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", tree_sha256):
        raise LauncherContractError("delivery generation has an invalid runtime digest")
    if generation != f"{version}:{tree_sha256}":
        raise LauncherContractError("delivery generation mismatch: generation")
    return payload


def delivery_generation(source_root: Path) -> dict[str, Any] | None:
    """Read a staged generation descriptor and bind it to current runtime bytes."""
    root = source_root.expanduser().resolve()
    payload = _delivery_generation_payload(root)
    if payload is None:
        return None
    if runtime_tree_digest(root) != payload["runtime_tree_sha256"]:
        raise LauncherContractError("delivery generation mismatch: runtime_tree_sha256")
    return payload


def repair_generated_bytecode(source_root: Path) -> dict[str, Any]:
    """Remove only generated bytecode from an otherwise exact staged runtime."""
    argument = source_root.expanduser()
    if argument.is_symlink():
        raise LauncherContractError(f"runtime root is a symlink: {argument}")
    root = argument.resolve()
    payload = _delivery_generation_payload(root)
    if payload is None:
        raise LauncherContractError(
            "generated-bytecode repair requires a staged delivery generation"
        )
    cache_directories: list[Path] = []
    bytecode_files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise LauncherContractError(f"runtime tree contains a symlink: {path}")
        relative = path.relative_to(root)
        in_cache = "__pycache__" in relative.parts
        if path.is_dir():
            if in_cache:
                if path.name != "__pycache__":
                    raise LauncherContractError(
                        f"runtime bytecode cache contains an unexpected directory: {path}"
                    )
                cache_directories.append(path)
            continue
        if in_cache and path.suffix.casefold() != ".pyc":
            raise LauncherContractError(
                f"runtime bytecode cache contains an unexpected file: {path}"
            )
        if in_cache or path.suffix.casefold() == ".pyc":
            bytecode_files.append(path)
    without_bytecode = _runtime_tree_digest(root, ignore_bytecode=True)
    if without_bytecode != payload["runtime_tree_sha256"]:
        raise LauncherContractError(
            "runtime has non-bytecode drift; generated-bytecode repair refused"
        )
    for path in bytecode_files:
        path.unlink()
    for path in sorted(cache_directories, key=lambda item: len(item.parts), reverse=True):
        path.rmdir()
    if runtime_tree_digest(root) != payload["runtime_tree_sha256"]:
        raise LauncherContractError("runtime bytecode repair did not restore generation")
    return {
        "schema": "sulde-runtime-bytecode-repair-v1",
        "generation": payload["generation"],
        "removed_files": len(bytecode_files),
        "removed_directories": len(cache_directories),
        "healthy": True,
    }


def codex_hook_surface_digest(source_root: Path) -> str | None:
    """Hash the current Codex adapters paired with one staged runtime.

    Source checkouts do not have the staged ``plugin/runtime`` layout, so this
    identity is optional there. Installed Codex artifacts must expose every
    adapter as a regular non-symlink file next to ``runtime``.
    """
    root = source_root.expanduser().resolve()
    if root.name != "runtime":
        return None
    plugin_root = root.parent
    descriptor = plugin_root / ".codex-plugin" / "plugin.json"
    if not descriptor.is_file():
        return None
    digest = hashlib.sha256()
    for relative in CODEX_HOOK_SURFACE:
        path = plugin_root / relative
        try:
            metadata = path.lstat()
        except OSError as error:
            raise LauncherContractError(
                f"Codex hook adapter is missing or unreadable: {path}"
            ) from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise LauncherContractError(
                f"Codex hook adapter must be a regular non-symlink file: {path}"
            )
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def codex_hook_file_digests(source_root: Path) -> dict[str, str] | None:
    """Return install-time identities for each file in the sealed Hook surface."""
    root = source_root.expanduser().resolve()
    if root.name != "runtime":
        return None
    plugin_root = root.parent
    if not (plugin_root / ".codex-plugin" / "plugin.json").is_file():
        return None
    records: dict[str, str] = {}
    for relative in CODEX_HOOK_SURFACE:
        path = plugin_root / relative
        try:
            metadata = path.lstat()
        except OSError as error:
            raise LauncherContractError(
                f"Codex hook adapter is missing or unreadable: {path}"
            ) from error
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise LauncherContractError(
                f"Codex hook adapter must be a regular non-symlink file: {path}"
            )
        records[relative] = sha256_file(path)
    return records


def resolve_codex_hook_adapter(
    kb_home: Path,
    source_root: Path,
    event: str,
) -> Path:
    """Resolve one current adapter only when the protected bridge matches it."""
    relative = CODEX_HOOK_ADAPTERS.get(event)
    if relative is None:
        raise LauncherContractError(f"unsupported Codex hook event: {event}")
    root = source_root.expanduser().resolve()
    manifest, issues = _read_manifest(kb_home)
    if manifest is None or issues:
        raise LauncherContractError(
            "; ".join(issues) or "launcher manifest unavailable"
        )
    manifest_root = manifest.get("source_root")
    try:
        recorded_root = Path(str(manifest_root)).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise LauncherContractError("launcher manifest source_root is invalid") from error
    if recorded_root != root:
        raise LauncherContractError(
            f"Codex hook bridge runtime mismatch: {recorded_root} != {root}"
        )
    expected_files = manifest.get("codex_hook_file_sha256")
    if not isinstance(expected_files, dict):
        raise LauncherContractError("Codex hook file identities are unavailable")
    selected = (
        ".codex-plugin/plugin.json",
        "scripts/_adapter_common.py",
        relative,
        CODEX_RUNTIME_HOOK_BY_EVENT[event],
    )
    plugin_root = root.parent
    for selected_relative in dict.fromkeys(selected):
        expected = expected_files.get(selected_relative)
        path = plugin_root / selected_relative
        try:
            metadata = path.lstat()
        except OSError as error:
            raise LauncherContractError(
                f"Codex hook event surface is missing: {path}"
            ) from error
        if (
            not isinstance(expected, str)
            or not _is_sha256(expected)
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
            or sha256_file(path) != expected
        ):
            raise LauncherContractError(
                f"Codex hook event surface changed: {selected_relative}"
            )
    adapter = root.parent / relative
    if not adapter.is_file():
        raise LauncherContractError(f"Codex hook adapter is missing: {adapter}")
    return adapter


def _version_key(path: str) -> tuple[int, ...]:
    runtime_root = path.rsplit(os.sep + "scripts", 1)[0].rstrip(os.sep)
    if os.path.basename(runtime_root) == "runtime":
        runtime_root = os.path.dirname(runtime_root)
    return tuple(int(piece) for piece in re.findall(r"\d+", os.path.basename(runtime_root)))


def resolve_target(
    spec: LauncherSpec,
    source_hint: Path,
    *,
    environment: dict[str, str] | None = None,
) -> tuple[Path | None, bool]:
    env = os.environ if environment is None else environment
    override = env.get(spec.override_env)
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate.resolve(), True
    hinted = source_hint / Path(spec.target_relative)
    if hinted.is_file():
        return hinted.resolve(), False

    claude_home = Path(env.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")).expanduser()
    codex_home = Path(env.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    candidates = [
        *claude_home.glob(
            "plugins/cache/sulde/sulde-cc/*/" + spec.target_relative
        ),
        *claude_home.glob(
            "plugins/cache/sulde/sulde/*/" + spec.target_relative
        ),
        *codex_home.glob(
            "plugins/cache/sulde-local/sulde/*/runtime/" + spec.target_relative
        ),
    ]
    files = sorted(
        (candidate.resolve() for candidate in candidates if candidate.is_file()),
        key=lambda candidate: _version_key(str(candidate)),
    )
    return (files[-1], False) if files else (None, False)


_LAUNCHER_TEMPLATE = r'''#!/usr/bin/env python3
# sulde-observer-in-process-v1
"""Stable Sulde launcher generated from a verified runtime contract."""
import sys
sys.dont_write_bytecode = True

import glob
import hashlib
import json
import os
import re
import runpy
import shutil
import subprocess

NO_BYTECODE_ENV = os.environ.copy()
NO_BYTECODE_ENV["PYTHONDONTWRITEBYTECODE"] = "1"

for stream in (sys.stdin, sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="strict")
        except (LookupError, OSError, ValueError):
            pass

SPEC_VERSION = __SPEC_VERSION__
HINT = __HINT__
LAUNCHER_NAME = __LAUNCHER_NAME__
OVERRIDE_ENV = __OVERRIDE_ENV__
TARGET_RELATIVE = __TARGET_RELATIVE__
TARGET_KIND = __TARGET_KIND__
EXPECTED_TARGET_SHA256 = __EXPECTED_TARGET_SHA256__
EXPECTED_RUNTIME_SHA256 = __EXPECTED_RUNTIME_SHA256__
EXPECTED_RUNTIME_TREE_SHA256 = __EXPECTED_RUNTIME_TREE_SHA256__
EXPECTED_GENERATION = __EXPECTED_GENERATION__
EXPECTED_INTERPRETER = __EXPECTED_INTERPRETER__
EXPECTED_INTERPRETER_SHA256 = __EXPECTED_INTERPRETER_SHA256__
EXPECTED_INTERPRETER_PREFIX = __EXPECTED_INTERPRETER_PREFIX__
RUNTIME_CODE_PREFIXES = (
    os.path.join("hooks", "lib"),
    os.path.join("scripts", "kb"),
    os.path.join("tools", "kb-index"),
    os.path.join("tools", "kb-mcp"),
)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_root(target):
    absolute = os.path.abspath(target)
    marker = os.sep + os.path.join("scripts", "kb") + os.sep
    if marker not in absolute:
        return None
    return absolute.split(marker, 1)[0]


def _runtime_digest(source_root):
    digest = hashlib.sha256()
    for prefix in RUNTIME_CODE_PREFIXES:
        root = os.path.join(source_root, prefix)
        if not os.path.isdir(root):
            return None
        selected = []
        for directory, names, filenames in os.walk(root):
            if "__pycache__" in names:
                return None
            names[:] = sorted(names)
            for filename in sorted(filenames):
                if filename.lower().endswith(".pyc"):
                    return None
                selected.append(os.path.join(directory, filename))
        for path in sorted(selected):
            relative = os.path.relpath(path, source_root).replace(os.sep, "/").encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def _runtime_tree_digest(source_root):
    if not source_root or os.path.islink(source_root):
        return None
    digest = hashlib.sha256()
    selected = []
    for directory, names, filenames in os.walk(source_root):
        if any(os.path.islink(os.path.join(directory, name)) for name in names):
            return None
        if any(name in {"__pycache__", ".git"} for name in names):
            return None
        names[:] = sorted(names)
        for filename in filenames:
            path = os.path.join(directory, filename)
            if os.path.islink(path):
                return None
            if filename.lower().endswith(".pyc") or filename == ".git":
                return None
            selected.append(path)
    for path in sorted(selected):
        relative = os.path.relpath(path, source_root).replace(os.sep, "/").encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _verify_delivery_generation(source_root):
    """Validate the immutable activation seal without rescanning its whole tree."""
    if EXPECTED_GENERATION is None:
        return True
    path = os.path.join(source_root, os.pardir, ".codex-plugin", "generation.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, UnicodeError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema") == "sulde-delivery-generation-v1"
        and payload.get("generation") == EXPECTED_GENERATION
        and payload.get("runtime_tree_sha256") == EXPECTED_RUNTIME_TREE_SHA256
    )


def _version_key(path):
    runtime_root = path.rsplit(os.sep + "scripts", 1)[0].rstrip(os.sep)
    if os.path.basename(runtime_root) == "runtime":
        runtime_root = os.path.dirname(runtime_root)
    return tuple(int(piece) for piece in re.findall(r"\d+", os.path.basename(runtime_root)))


def resolve():
    override = os.environ.get(OVERRIDE_ENV)
    if override and os.path.isfile(override):
        return os.path.abspath(override), True
    hinted = os.path.join(HINT, *TARGET_RELATIVE.split("/"))
    if os.path.isfile(hinted):
        return hinted, False
    claude_home = os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))
    codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
    patterns = (
        os.path.join(
            claude_home, "plugins", "cache", "sulde", "sulde-cc", "*",
            *TARGET_RELATIVE.split("/"),
        ),
        os.path.join(
            claude_home, "plugins", "cache", "sulde", "sulde", "*",
            *TARGET_RELATIVE.split("/"),
        ),
        os.path.join(
            codex_home, "plugins", "cache", "sulde-local", "sulde", "*", "runtime",
            *TARGET_RELATIVE.split("/"),
        ),
    )
    candidates = sorted(
        (candidate for pattern in patterns for candidate in glob.glob(pattern) if os.path.isfile(candidate)),
        key=_version_key,
    )
    return (candidates[-1], False) if candidates else (None, False)


def _fail(reason):
    bootstrap = os.path.join(HINT, "scripts", "kb", "bootstrap.sh")
    generation = os.path.join(HINT, os.pardir, ".codex-plugin", "generation.json")
    repair = " --repair-generated-bytecode" if os.path.isfile(generation) else ""
    instruction = (
        f"run {bootstrap} --launchers-only{repair} --host <claude|codex>"
    )
    if TARGET_KIND == "statusline":
        print(f"sulde 🔴(接线未同步: {reason}; {instruction})")
        raise SystemExit(0)
    print(f"{LAUNCHER_NAME}: launcher contract failed: {reason}; {instruction}", file=sys.stderr)
    raise SystemExit(2)


def _rebind_interpreter():
    if not os.path.isfile(EXPECTED_INTERPRETER):
        _fail(f"runtime interpreter missing: {EXPECTED_INTERPRETER}")
    if _sha256(EXPECTED_INTERPRETER) != EXPECTED_INTERPRETER_SHA256:
        _fail("runtime interpreter digest changed")
    current = os.path.normcase(os.path.abspath(sys.executable))
    expected = os.path.normcase(os.path.abspath(EXPECTED_INTERPRETER))
    current_prefix = os.path.normcase(os.path.abspath(sys.prefix))
    expected_prefix = os.path.normcase(os.path.abspath(EXPECTED_INTERPRETER_PREFIX))
    if current == expected or current_prefix == expected_prefix:
        return
    environment = NO_BYTECODE_ENV.copy()
    environment["SULDE_LAUNCHER_INTERPRETER_REBOUND"] = "1"
    try:
        os.execve(
            EXPECTED_INTERPRETER,
            [EXPECTED_INTERPRETER, os.path.abspath(__file__), *sys.argv[1:]],
            environment,
        )
    except OSError as error:
        _fail(f"runtime interpreter cannot start: {error}")


_rebind_interpreter()


target, override_used = resolve()
if target is None:
    _fail(f"target not found: {TARGET_RELATIVE}")

actual_target = _sha256(target)
source_root = _source_root(target)
deep_verify = (
    sys.argv[1:] == ["--sulde-launcher-probe"]
    or os.environ.get("SULDE_LAUNCHER_DEEP_VERIFY") == "1"
    or EXPECTED_GENERATION is None
)
actual_runtime = _runtime_digest(source_root) if source_root and deep_verify else EXPECTED_RUNTIME_SHA256
actual_runtime_tree = (
    _runtime_tree_digest(source_root)
    if source_root and deep_verify and EXPECTED_RUNTIME_TREE_SHA256 is not None
    else EXPECTED_RUNTIME_TREE_SHA256
)
if not override_used:
    if actual_target != EXPECTED_TARGET_SHA256:
        _fail("entrypoint digest changed")
    if source_root is None or not _verify_delivery_generation(source_root):
        _fail("delivery generation seal changed")
    if actual_runtime != EXPECTED_RUNTIME_SHA256:
        _fail("runtime digest changed")
    if actual_runtime_tree != EXPECTED_RUNTIME_TREE_SHA256:
        _fail("runtime tree digest changed")

if sys.argv[1:] == ["--sulde-launcher-probe"]:
    print(json.dumps({
        "healthy": True,
        "launcher": LAUNCHER_NAME,
        "spec_version": SPEC_VERSION,
        "target": target,
        "target_sha256": actual_target,
        "runtime_sha256": actual_runtime,
        "runtime_tree_sha256": actual_runtime_tree,
        "generation": EXPECTED_GENERATION,
        "interpreter": EXPECTED_INTERPRETER,
        "interpreter_sha256": EXPECTED_INTERPRETER_SHA256,
        "override_used": override_used,
    }, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0)

if TARGET_KIND == "statusline":
    status_env = NO_BYTECODE_ENV.copy()
    status_env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [sys.executable, target, "--statusline", *sys.argv[1:]],
            env=status_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1.0,
        )
    except Exception:
        print("sulde 🔴(状态脚本异常)")
        raise SystemExit(0)
    if not completed.stdout.strip():
        print("sulde 🔴(状态脚本无输出)")
        raise SystemExit(0)
    sys.stdout.buffer.write(completed.stdout.encode("utf-8"))
    sys.stdout.buffer.flush()
    raise SystemExit(0)
elif TARGET_KIND == "shell":
    bash = shutil.which("bash")
    if bash is None:
        _fail(f"bash is required to run {target}")
    completed = subprocess.run(
        [bash, target, *sys.argv[1:]],
        env=NO_BYTECODE_ENV,
    )
else:
    os.environ.update(NO_BYTECODE_ENV)
    sys.argv = [target, *sys.argv[1:]]
    sys.path.insert(0, os.path.dirname(target))
    runpy.run_path(target, run_name="__main__")
    raise SystemExit(0)
raise SystemExit(completed.returncode)
'''


def render_launcher(
    spec: LauncherSpec,
    source_root: Path,
    *,
    target_sha256: str,
    runtime_sha256: str,
    runtime_tree_sha256: str,
    generation: str | None,
    interpreter: Path,
    interpreter_sha256: str,
    interpreter_prefix: Path,
) -> str:
    replacements = {
        "__SPEC_VERSION__": str(SPEC_VERSION),
        "__HINT__": repr(str(source_root.resolve())),
        "__LAUNCHER_NAME__": repr(spec.name),
        "__OVERRIDE_ENV__": repr(spec.override_env),
        "__TARGET_RELATIVE__": repr(spec.target_relative),
        "__TARGET_KIND__": repr(spec.target_kind),
        "__EXPECTED_TARGET_SHA256__": repr(target_sha256),
        "__EXPECTED_RUNTIME_SHA256__": repr(runtime_sha256),
        "__EXPECTED_RUNTIME_TREE_SHA256__": repr(runtime_tree_sha256),
        "__EXPECTED_GENERATION__": repr(generation),
        "__EXPECTED_INTERPRETER__": repr(str(interpreter)),
        "__EXPECTED_INTERPRETER_SHA256__": repr(interpreter_sha256),
        "__EXPECTED_INTERPRETER_PREFIX__": repr(str(interpreter_prefix)),
    }
    rendered = _LAUNCHER_TEMPLATE
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


def runtime_interpreter(kb_home: Path) -> Path:
    """Return the exact interpreter path launchers must use.

    A bootstrapped KB venv owns optional runtime dependencies.  Falling back to
    the installing interpreter keeps ``--launchers-only`` usable for recovery,
    while the manifest still pins the chosen binary bytes.
    """
    home = kb_home.expanduser().resolve()
    candidates = (
        home / "venv" / "bin" / "python",
        home / "venv" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.absolute()
    return Path(sys.executable).absolute()


def runtime_interpreter_prefix(interpreter: Path, kb_home: Path) -> Path:
    home = kb_home.expanduser().resolve()
    if (
        interpreter.parent.name in {"bin", "Scripts"}
        and interpreter.parent.parent == home / "venv"
    ):
        return home / "venv"
    return Path(sys.prefix).absolute()


def _resolved_executable(
    raw: str,
    *,
    environment: dict[str, str] | None = None,
) -> Path | None:
    env = os.environ if environment is None else environment
    expanded = Path(raw).expanduser()
    if expanded.is_absolute() or expanded.parent != Path("."):
        candidate = expanded
    else:
        located = shutil.which(raw, path=env.get("PATH"))
        if not located:
            return None
        candidate = Path(located)
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    return resolved if resolved.is_file() else None


def _installed_interpreters(
    *,
    environment: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    candidates = [sys.executable, "python3", "python"]
    records: dict[str, dict[str, str]] = {}
    for raw in candidates:
        resolved = _resolved_executable(raw, environment=environment)
        if resolved is None:
            continue
        rendered = str(resolved)
        if rendered not in records:
            records[rendered] = {
                "path": rendered,
                "sha256": sha256_file(resolved),
            }
    return [records[path] for path in sorted(records)]


def build_command_effect_snapshot(
    *,
    runtime_sha256: str,
    source_root: Path,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a machine-local, digest-pinned declaration of understood scripts."""
    codex_home = default_codex_home(environment).resolve()
    runtime_root = source_root.expanduser().resolve()
    commands: list[dict[str, str]] = []
    for profile in SCRIPT_EFFECT_PROFILES:
        candidate = (
            runtime_root if profile.root_kind == "runtime" else codex_home
        ) / profile.script_relative
        try:
            script = candidate.resolve(strict=True)
        except OSError:
            continue
        if not script.is_file():
            continue
        commands.append(
            {
                "argv_contract": profile.argv_contract,
                "effect": profile.effect,
                "path": str(script),
                "profile_id": profile.profile_id,
                "sha256": sha256_file(script),
            }
        )
    return {
        "schema": COMMAND_EFFECT_SCHEMA,
        "spec_version": COMMAND_EFFECT_SPEC_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_sha256": runtime_sha256,
        "runtime_root": str(runtime_root),
        "codex_home": str(codex_home),
        "interpreters": _installed_interpreters(environment=environment),
        "commands": commands,
    }


def _snapshot_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _protected_regular_file(path: Path, issues: list[str], label: str) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        issues.append(f"{label} missing or unreadable: {path}")
        return False
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        issues.append(f"{label} must be a regular non-symlink file: {path}")
        return False
    if os.name != "nt" and (
        stat.S_IMODE(metadata.st_mode) & 0o077 or metadata.st_uid != os.geteuid()
    ):
        issues.append(f"{label} owner or permissions are unsafe: {path}")
        return False
    return True


def _read_protected_json_object(path: Path, *, label: str) -> dict[str, Any] | None:
    issues: list[str] = []
    if not _protected_regular_file(path, issues, label):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if type(payload) is dict else None


def _scheduler_launcher_extension(
    kb_home: Path,
    source_root: Path,
    *,
    runtime_tree_sha256: str | None,
    generation: str | None,
) -> dict[str, Any]:
    return scheduler_seal_preflight(
        kb_home, source_root, runtime_tree_sha256=runtime_tree_sha256,
        generation=generation,
    )["extension"]


def scheduler_seal_preflight(
    kb_home: Path,
    source_root: Path,
    *,
    runtime_tree_sha256: str | None,
    generation: str | None,
) -> dict[str, Any]:
    """Compose an existing scheduler seal only when both owners still agree.

    ``install-agents`` owns the scheduler runner while this module owns the
    launcher projection.  A launcher-only refresh must not erase a valid seal,
    but it must also never copy an orphaned or stale field from the old
    launcher manifest.  Deployment and runtime-owner are therefore treated as
    two independent inputs and the runner bytes are verified before composing
    the extension into the new manifest.
    """
    def incomplete(reason: str) -> dict[str, Any]:
        return {"status": "unavailable", "reasons": [reason], "extension": {}}

    if runtime_tree_sha256 is None or generation is None:
        return {"status": "not_applicable", "reasons": ["no_staged_generation"], "extension": {}}
    home = kb_home.expanduser().resolve()
    root = source_root.expanduser().resolve()
    deployment = _read_protected_json_object(
        home / DEPLOYMENT_GENERATION_NAME,
        label="deployment generation",
    )
    owner = _read_protected_json_object(
        home / RUNTIME_OWNER_NAME,
        label="runtime owner",
    )
    if deployment is None or owner is None:
        return incomplete("scheduler_deployment_or_owner_missing_or_unsafe")
    provider = deployment.get("provider")
    platform = deployment.get("platform")
    runner_value = deployment.get("scheduler_runner")
    runner_sha256 = deployment.get("scheduler_runner_sha256")
    generation_state = (
        deployment.get("status"),
        deployment.get("operational_ready"),
        owner.get("installation_status"),
        owner.get("operational_ready"),
    )
    accepted_generation_states = {
        ("installed_degraded", False, "installed_degraded", False),
        ("installed_live_unverified", False, "installed_degraded", False),
        ("generation_verified", True, "generation_verified", True),
    }
    if (
        deployment.get("schema") != "sulde-installed-deployment-generation-v1"
        or deployment.get("schema_version") != 1
        or generation_state not in accepted_generation_states
        or provider != "codex"
        or platform not in {"posix", "windows"}
        or deployment.get("runtime_root") != str(root)
        or deployment.get("runtime_tree_sha256") != runtime_tree_sha256
        or deployment.get("generation") != generation
        or type(runner_value) is not str
        or not runner_value
        or not _is_sha256(runner_sha256)
        or owner.get("schema_version") != 2
        or owner.get("status") != "active"
        or owner.get("provider") != provider
        or owner.get("source_root") != str(root)
        or owner.get("runtime_root") != str(root)
        or owner.get("runtime_tree_sha256") != runtime_tree_sha256
        or owner.get("generation") != generation
        or owner.get("scheduler_runner_sha256") != runner_sha256
        or owner.get("scheduler")
        != ("windows-task-scheduler" if platform == "windows" else "launchd")
    ):
        return incomplete("scheduler_identity_or_generation_mismatch")
    activation = deployment.get("scheduler_activation_id")
    if platform == "posix" and (
        type(activation) is not str or not activation
        or owner.get("scheduler_activation_id") != activation
    ):
        return incomplete("scheduler_activation_identity_missing_or_mismatched")
    runner = Path(runner_value).expanduser()
    try:
        metadata = runner.lstat()
        resolved_runner = runner.resolve(strict=True)
        # Both scheduler installers write their runner under the DATA root.
        # It is not one of the six public launchers under launcher_home/bin.
        expected_runner = home / "bin" / (
            "sulde-windows-task.py" if platform == "windows" else "sulde-scheduled-run"
        )
    except OSError:
        return incomplete("scheduler_runner_missing_or_unreadable")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or runner != expected_runner
        or resolved_runner != expected_runner
        or (os.name != "nt" and (metadata.st_uid != os.geteuid() or metadata.st_mode & 0o022))
        or sha256_file(resolved_runner) != runner_sha256
    ):
        return incomplete("scheduler_runner_path_identity_or_digest_mismatch")
    extension = {
        "schema_version": 1,
        "provider": provider,
        "platform": platform,
        "scheduler_runner": str(resolved_runner),
        "scheduler_runner_sha256": runner_sha256,
    }
    if platform == "posix":
        extension["scheduler_activation_id"] = activation
    return {"status": "verified", "reasons": [], "extension": extension}


def verify_scheduler_seal(
    kb_home: Path, source_root: Path, manifest: dict[str, Any],
) -> dict[str, Any]:
    """Read scheduler authorities again and compare the actual new manifest."""
    probe = scheduler_seal_preflight(
        kb_home, source_root, runtime_tree_sha256=manifest.get("runtime_tree_sha256"),
        generation=manifest.get("generation"),
    )
    if probe["status"] == "verified" and any(
        manifest.get(key) != value for key, value in probe["extension"].items()
    ):
        return {"status": "unavailable", "reasons": ["launcher_scheduler_seal_missing_or_mismatched"]}
    return {"status": probe["status"], "reasons": probe["reasons"]}


def _validated_command_effect_snapshot(
    kb_home: Path,
    *,
    launcher_manifest: dict[str, Any] | None = None,
    expected_runtime_sha256: str | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    home = canonical_launcher_home(kb_home)
    launcher_path = home / "bin" / MANIFEST_NAME
    snapshot_path = home / "bin" / COMMAND_EFFECT_MANIFEST_NAME
    issues: list[str] = []
    if launcher_manifest is None:
        if not _protected_regular_file(launcher_path, issues, "launcher manifest"):
            return None, issues
        try:
            launcher_manifest = json.loads(launcher_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            issues.append(f"launcher manifest missing or invalid: {launcher_path}")
            return None, issues
    if not isinstance(launcher_manifest, dict):
        issues.append("launcher manifest is not an object")
        return None, issues
    if launcher_manifest.get("schema") != SCHEMA:
        issues.append("command effect snapshot is bound to an unknown launcher schema")
    if launcher_manifest.get("spec_version") != SPEC_VERSION:
        issues.append("command effect snapshot is bound to a stale launcher specification")
    if not _protected_regular_file(snapshot_path, issues, "command effect snapshot"):
        return None, issues
    try:
        snapshot_bytes = snapshot_path.read_bytes()
        payload = json.loads(snapshot_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        issues.append(f"command effect snapshot is invalid: {snapshot_path}")
        return None, issues
    if not isinstance(payload, dict):
        issues.append("command effect snapshot is not an object")
        return None, issues
    expected_fields = {
        "schema",
        "spec_version",
        "generated_at",
        "runtime_sha256",
        "runtime_root",
        "codex_home",
        "interpreters",
        "commands",
    }
    if set(payload) != expected_fields:
        issues.append("command effect snapshot fields do not match the sealed schema")
    expected_snapshot_digest = launcher_manifest.get("command_effects_sha256")
    actual_snapshot_digest = hashlib.sha256(snapshot_bytes).hexdigest()
    if expected_snapshot_digest != actual_snapshot_digest:
        issues.append("command effect snapshot digest is not bound by the launcher manifest")
    if payload.get("schema") != COMMAND_EFFECT_SCHEMA:
        issues.append(f"command effect schema mismatch: {payload.get('schema')!r}")
    if payload.get("spec_version") != COMMAND_EFFECT_SPEC_VERSION:
        issues.append(
            "command effect spec mismatch: "
            f"installed={payload.get('spec_version')!r} expected={COMMAND_EFFECT_SPEC_VERSION}"
        )
    runtime_sha256 = payload.get("runtime_sha256")
    if runtime_sha256 != launcher_manifest.get("runtime_sha256"):
        issues.append("command effect snapshot runtime is not bound to the launcher runtime")
    if expected_runtime_sha256 is not None and runtime_sha256 != expected_runtime_sha256:
        issues.append("command effect snapshot does not match the expected runtime")

    runtime_root = Path(str(payload.get("runtime_root") or "")).expanduser()
    try:
        runtime_root = runtime_root.resolve(strict=True)
    except OSError:
        issues.append("command effect snapshot runtime root is unavailable")
    if str(runtime_root) != launcher_manifest.get("source_root"):
        issues.append("command effect snapshot runtime root is not launcher-bound")

    env = os.environ if environment is None else environment
    codex_home = default_codex_home(env).resolve()
    if payload.get("codex_home") != str(codex_home):
        issues.append("command effect snapshot belongs to a different CODEX_HOME")

    raw_interpreters = payload.get("interpreters")
    interpreter_records: dict[str, str] = {}
    if not isinstance(raw_interpreters, list) or len(raw_interpreters) > 16:
        issues.append("command effect snapshot has invalid interpreter records")
    else:
        for record in raw_interpreters:
            if not isinstance(record, dict):
                issues.append("command effect snapshot has a non-object interpreter record")
                continue
            raw_path = record.get("path")
            digest = record.get("sha256")
            if not isinstance(raw_path, str) or not isinstance(digest, str):
                issues.append("command effect snapshot has an incomplete interpreter record")
                continue
            candidate = Path(raw_path).expanduser()
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                issues.append(f"trusted interpreter cannot be resolved: {raw_path}")
                continue
            if str(resolved) != raw_path or not resolved.is_file():
                issues.append(f"trusted interpreter path changed: {raw_path}")
                continue
            if sha256_file(resolved) != digest:
                issues.append(f"trusted interpreter digest changed: {raw_path}")
                continue
            if raw_path in interpreter_records:
                issues.append(f"duplicate trusted interpreter: {raw_path}")
                continue
            interpreter_records[raw_path] = digest
    if not interpreter_records:
        issues.append("command effect snapshot has no verified Python interpreter")

    profiles = {profile.profile_id: profile for profile in SCRIPT_EFFECT_PROFILES}
    raw_commands = payload.get("commands")
    command_records: dict[str, dict[str, str]] = {}
    if not isinstance(raw_commands, list) or len(raw_commands) > len(profiles):
        issues.append("command effect snapshot has invalid command records")
    else:
        for record in raw_commands:
            if not isinstance(record, dict):
                issues.append("command effect snapshot has a non-object command record")
                continue
            profile_id = record.get("profile_id")
            profile = profiles.get(profile_id) if isinstance(profile_id, str) else None
            if profile is None:
                issues.append(f"unknown command effect profile: {profile_id!r}")
                continue
            if profile_id in command_records:
                issues.append(f"duplicate command effect profile: {profile_id}")
                continue
            profile_root = runtime_root if profile.root_kind == "runtime" else codex_home
            expected_path = (profile_root / profile.script_relative).resolve()
            if record.get("path") != str(expected_path):
                issues.append(f"command effect path mismatch: {profile_id}")
                continue
            if record.get("effect") != profile.effect:
                issues.append(f"command effect declaration mismatch: {profile_id}")
                continue
            if record.get("argv_contract") != profile.argv_contract:
                issues.append(f"command argv contract mismatch: {profile_id}")
                continue
            digest = record.get("sha256")
            if not isinstance(digest, str):
                issues.append(f"command digest missing: {profile_id}")
                continue
            try:
                script = expected_path.resolve(strict=True)
            except OSError:
                issues.append(f"trusted command cannot be resolved: {profile_id}")
                continue
            if not script.is_file() or sha256_file(script) != digest:
                issues.append(f"trusted command digest changed: {profile_id}")
                continue
            command_records[profile_id] = {
                "argv_contract": profile.argv_contract,
                "effect": profile.effect,
                "path": str(script),
                "profile_id": profile.profile_id,
                "sha256": digest,
            }
    if issues:
        return None, list(dict.fromkeys(issues))
    payload["_verified_interpreters"] = interpreter_records
    payload["_verified_commands"] = command_records
    return payload, []


def verify_command_effect_snapshot(
    kb_home: Path,
    *,
    launcher_manifest: dict[str, Any] | None = None,
    expected_runtime_sha256: str | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload, issues = _validated_command_effect_snapshot(
        kb_home,
        launcher_manifest=launcher_manifest,
        expected_runtime_sha256=expected_runtime_sha256,
        environment=environment,
    )
    commands = payload.get("_verified_commands", {}) if payload is not None else {}
    interpreters = payload.get("_verified_interpreters", {}) if payload is not None else {}
    return {
        "healthy": payload is not None and not issues,
        "schema": COMMAND_EFFECT_SCHEMA,
        "spec_version": COMMAND_EFFECT_SPEC_VERSION,
        "manifest": str(
            canonical_launcher_home(kb_home) / "bin" / COMMAND_EFFECT_MANIFEST_NAME
        ),
        "command_count": len(commands),
        "interpreter_count": len(interpreters),
        "profiles": sorted(commands),
        "issues": issues,
    }


def _plugin_root_and_manifest(raw: str, cwd: Path) -> tuple[Path, Path] | None:
    if not raw or raw.startswith("-"):
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = cwd / candidate
    try:
        root = candidate.resolve(strict=True)
    except OSError:
        return None
    manifest = root / ".codex-plugin" / "plugin.json"
    try:
        resolved_manifest = manifest.resolve(strict=True)
    except OSError:
        return None
    if (
        not root.is_dir()
        or manifest.is_symlink()
        or not resolved_manifest.is_file()
        or resolved_manifest.parent != root / ".codex-plugin"
    ):
        return None
    return root, resolved_manifest


def identify_trusted_script_command(
    tokens: list[str],
    *,
    kb_home: Path,
    cwd: Path,
    environment: dict[str, str] | None = None,
) -> dict[str, str] | None:
    """Verify only the interpreter and script identity of a declared command."""
    if len(tokens) < 2:
        return None
    home = canonical_launcher_home(kb_home)
    try:
        if (home / "bin" / COMMAND_EFFECT_MANIFEST_NAME).resolve().is_relative_to(
            cwd.expanduser().resolve()
        ):
            return None
    except (OSError, ValueError):
        return None
    payload, issues = _validated_command_effect_snapshot(
        home,
        environment=environment,
    )
    if payload is None or issues:
        return None
    interpreter = _resolved_executable(tokens[0], environment=environment)
    if interpreter is None:
        return None
    interpreter_digest = payload["_verified_interpreters"].get(str(interpreter))
    if not interpreter_digest or sha256_file(interpreter) != interpreter_digest:
        return None
    raw_script = Path(tokens[1]).expanduser()
    if not raw_script.is_absolute():
        return None
    try:
        script = raw_script.resolve(strict=True)
    except OSError:
        return None
    matched = next(
        (
            record
            for record in payload["_verified_commands"].values()
            if record["path"] == str(script) and record["sha256"] == sha256_file(script)
        ),
        None,
    )
    if matched is None:
        return None
    return dict(matched)


_GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_TASK_BRANCH = re.compile(
    r"^(?:fix|task|feature|repair)/[A-Za-z0-9][A-Za-z0-9._/-]{0,180}$"
)


def _lifecycle_absolute_path(raw: str, cwd: Path, *, must_exist: bool) -> Path | None:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        return None
    lexical = candidate.absolute()
    if lexical.is_symlink():
        return None
    try:
        return lexical.resolve(strict=must_exist)
    except OSError:
        return None


def _lifecycle_content_targets(root: Path, values: list[str]) -> list[str] | None:
    if not values or len(set(values)) != len(values):
        return None
    targets: list[str] = []
    for value in values:
        if (
            not value
            or value.startswith(("/", "\\", "-", ":"))
            or "\\" in value
            or any(character in value for character in ("*", "?", "[", "]", "{", "}"))
            or any(ord(character) < 32 for character in value)
            or any(
                part in {"", ".", "..", ".git", ".codex-agent"}
                for part in value.split("/")
            )
        ):
            return None
        try:
            target = (root / value).resolve(strict=False)
            target.relative_to(root)
        except (OSError, ValueError):
            return None
        current = root
        for part in Path(value).parts[:-1]:
            current = current / part
            if current.is_symlink():
                return None
        targets.append(str(target))
    return sorted(targets)


def _repeated_path_values(argv: list[str], start: int) -> list[str] | None:
    values: list[str] = []
    index = start
    while index < len(argv):
        if argv[index] != "--path" or index + 1 >= len(argv):
            return None
        values.append(argv[index + 1])
        index += 2
    return values or None


def _classify_agent_runtime_git_lifecycle(
    argv: list[str], cwd: Path
) -> dict[str, Any] | None:
    """Bind only the canonical argv shapes implemented by agent-runtime.py."""
    del cwd  # Lifecycle paths are deliberately absolute and never cwd-relative.
    if not argv:
        return None
    action = argv[0]
    if action == "provision":
        if (
            len(argv) != 9
            or argv[3] != "--branch"
            or argv[5:7] != ["--base-ref", "dev"]
            or argv[7] != "--base-commit"
            or _GIT_OBJECT_ID.fullmatch(argv[8]) is None
            or _TASK_BRANCH.fullmatch(argv[4]) is None
            or any(marker in argv[4] for marker in ("..", "@{", "//"))
        ):
            return None
        repository = _lifecycle_absolute_path(argv[1], Path("/"), must_exist=True)
        target = _lifecycle_absolute_path(argv[2], Path("/"), must_exist=False)
        if repository is None or target is None or os.path.lexists(target):
            return None
        worktrees = repository / ".worktrees"
        try:
            if (
                worktrees.is_symlink()
                or not worktrees.is_dir()
                or target.parent.resolve(strict=True) != worktrees.resolve(strict=True)
            ):
                return None
        except OSError:
            return None
        return {
            "git_lifecycle_action": action,
            "repository": str(repository),
            "target": str(target),
            "targets": [str(target)],
        }
    if action == "commit":
        if (
            len(argv) < 8
            or argv[2] != "--expected-head"
            or _GIT_OBJECT_ID.fullmatch(argv[3]) is None
            or argv[4] != "--message"
            or not argv[5]
            or "\n" in argv[5]
            or len(argv[5]) > 200
        ):
            return None
        root = _lifecycle_absolute_path(argv[1], Path("/"), must_exist=True)
        values = _repeated_path_values(argv, 6)
        targets = (
            _lifecycle_content_targets(root, values)
            if root is not None and values is not None
            else None
        )
        if root is None or targets is None:
            return None
        return {
            "git_lifecycle_action": action,
            "repository": str(root),
            "target": targets[0] if len(targets) == 1 else str(root),
            "targets": targets,
        }
    if action == "merge":
        if (
            len(argv) < 12
            or argv[2] != "--target-branch"
            or argv[3] not in {"dev", "main"}
            or argv[4] != "--source-ref"
            or argv[6] != "--expected-target-head"
            or _GIT_OBJECT_ID.fullmatch(argv[7]) is None
            or argv[8] != "--expected-source-head"
            or _GIT_OBJECT_ID.fullmatch(argv[9]) is None
            or any(marker in argv[5] for marker in ("..", "@{", "//"))
            or (
                argv[3] == "main" and argv[5] != "dev"
            )
            or (
                argv[3] == "dev" and _TASK_BRANCH.fullmatch(argv[5]) is None
            )
        ):
            return None
        root = _lifecycle_absolute_path(argv[1], Path("/"), must_exist=True)
        values = _repeated_path_values(argv, 10)
        targets = (
            _lifecycle_content_targets(root, values)
            if root is not None and values is not None
            else None
        )
        if root is None or targets is None:
            return None
        return {
            "git_lifecycle_action": action,
            "repository": str(root),
            "target": targets[0] if len(targets) == 1 else str(root),
            "targets": targets,
        }
    return None


def classify_trusted_script_command(
    tokens: list[str],
    *,
    kb_home: Path,
    cwd: Path,
    environment: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Classify one exact interpreter/script/argv tuple or fail closed."""
    if len(tokens) < 3:
        return None
    matched = identify_trusted_script_command(
        tokens,
        kb_home=kb_home,
        cwd=cwd,
        environment=environment,
    )
    if matched is None:
        return None

    argv = tokens[2:]
    contract = matched["argv_contract"]
    if contract == "plugin-root-only":
        if len(argv) != 1:
            return None
    elif contract == "plugin-root-with-optional-cachebuster":
        if len(argv) == 1:
            pass
        elif (
            len(argv) == 3
            and argv[1] == "--cachebuster"
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", argv[2])
        ):
            pass
        else:
            return None
    elif contract == "agent-runtime-git-lifecycle-v1":
        lifecycle = _classify_agent_runtime_git_lifecycle(argv, cwd)
        if lifecycle is None:
            return None
        return {
            "argv_contract": contract,
            "effect": matched["effect"],
            "profile_id": matched["profile_id"],
            "script_sha256": matched["sha256"],
            **lifecycle,
        }
    else:
        return None
    resolved = _plugin_root_and_manifest(argv[0], cwd.expanduser().resolve())
    if resolved is None:
        return None
    plugin_root, manifest = resolved
    result = {
        "argv_contract": contract,
        "effect": matched["effect"],
        "profile_id": matched["profile_id"],
        "script_sha256": matched["sha256"],
        "plugin_root": str(plugin_root),
    }
    if matched["effect"] == "local_write":
        result["target"] = str(manifest)
    return result


def _atomic_write(
    path: Path,
    content: str,
    *,
    executable: bool = False,
    mode: int | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            if executable:
                temporary.chmod(0o755)
            elif mode is not None:
                temporary.chmod(mode)
        os.replace(temporary, path)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def install_launchers(
    kb_home: Path,
    source_root: Path,
    *,
    interpreter_home: Path | None = None,
    data_home: Path | None = None,
    require_scheduler_seal: bool = False,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    home = canonical_launcher_home(kb_home)
    data_root = (data_home or kb_home).expanduser().resolve()
    root = source_root.expanduser().resolve()
    dependency_home = (
        interpreter_home.expanduser().resolve()
        if interpreter_home is not None
        else data_root
    )
    interpreter = runtime_interpreter(dependency_home)
    if not interpreter.is_file():
        raise LauncherContractError(
            f"runtime interpreter is missing: {interpreter}"
        )
    interpreter_sha256 = sha256_file(interpreter)
    interpreter_prefix = runtime_interpreter_prefix(interpreter, dependency_home)
    runtime_sha256 = runtime_digest(root)
    sealed_generation = delivery_generation(root)
    runtime_tree_sha256 = (
        str(sealed_generation["runtime_tree_sha256"])
        if sealed_generation is not None
        else None
    )
    generation = (
        str(sealed_generation["generation"])
        if sealed_generation is not None
        else None
    )
    codex_hook_sha256 = codex_hook_surface_digest(root)
    codex_hook_files = codex_hook_file_digests(root)
    records: dict[str, dict[str, Any]] = {}
    rendered: dict[str, str] = {}
    for spec in LAUNCHERS:
        target = root / Path(spec.target_relative)
        if not target.is_file():
            raise LauncherContractError(f"launcher target is missing: {target}")
        target_sha256 = sha256_file(target)
        source = render_launcher(
            spec,
            root,
            target_sha256=target_sha256,
            runtime_sha256=runtime_sha256,
            runtime_tree_sha256=runtime_tree_sha256,
            generation=generation,
            interpreter=interpreter,
            interpreter_sha256=interpreter_sha256,
            interpreter_prefix=interpreter_prefix,
        )
        rendered[spec.name] = source
        records[spec.name] = {
            "override_env": spec.override_env,
            "target_relative": spec.target_relative,
            "target_kind": spec.target_kind,
            "target_sha256": target_sha256,
            "launcher_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        }

    command_effects = build_command_effect_snapshot(
        runtime_sha256=runtime_sha256,
        source_root=root,
        environment=environment,
    )
    command_effects_text = _snapshot_text(command_effects)
    command_effects_sha256 = hashlib.sha256(
        command_effects_text.encode("utf-8")
    ).hexdigest()

    scheduler = scheduler_seal_preflight(
        data_root, root, runtime_tree_sha256=runtime_tree_sha256, generation=generation,
    )
    if require_scheduler_seal and scheduler["status"] == "unavailable":
        raise LauncherContractError("scheduler seal preflight incomplete: " + "; ".join(scheduler["reasons"]))
    bin_dir = home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for spec in LAUNCHERS:
        _atomic_write(bin_dir / spec.name, rendered[spec.name], executable=True)
    _atomic_write(
        bin_dir / COMMAND_EFFECT_MANIFEST_NAME,
        command_effects_text,
        mode=0o600,
    )
    manifest = {
        "schema": SCHEMA,
        "spec_version": SPEC_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root),
        "runtime_sha256": runtime_sha256,
        "runtime_tree_sha256": runtime_tree_sha256,
        "generation": generation,
        "interpreter": str(interpreter),
        "interpreter_sha256": interpreter_sha256,
        "interpreter_prefix": str(interpreter_prefix),
        "codex_hook_surface_sha256": codex_hook_sha256,
        "codex_hook_file_sha256": codex_hook_files,
        "command_effects_sha256": command_effects_sha256,
        "launchers": records,
    }
    manifest.update(scheduler["extension"])
    _atomic_write(
        bin_dir / MANIFEST_NAME,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        mode=0o600,
    )
    return manifest


def _read_manifest(kb_home: Path) -> tuple[dict[str, Any] | None, list[str]]:
    path = canonical_launcher_home(kb_home) / "bin" / MANIFEST_NAME
    issues: list[str] = []
    if not _protected_regular_file(path, issues, "launcher manifest"):
        return None, issues
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, [f"launcher manifest missing or invalid: {path}"]
    if not isinstance(payload, dict):
        return None, [f"launcher manifest is not an object: {path}"]
    return payload, []


def verify_installation(
    kb_home: Path,
    *,
    expected_source_root: Path | None = None,
    data_home: Path | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    home = canonical_launcher_home(kb_home)
    manifest, issues = _read_manifest(home)
    if manifest is None:
        return {
            "healthy": False,
            "schema": SCHEMA,
            "spec_version": SPEC_VERSION,
            "issues": issues,
            "launchers": {},
        }
    if manifest.get("schema") != SCHEMA:
        issues.append(f"launcher schema mismatch: {manifest.get('schema')!r}")
    if manifest.get("spec_version") != SPEC_VERSION:
        issues.append(
            f"launcher spec mismatch: installed={manifest.get('spec_version')!r} expected={SPEC_VERSION}"
        )
    interpreter_value = manifest.get("interpreter")
    interpreter = (
        Path(interpreter_value).expanduser()
        if isinstance(interpreter_value, str) and interpreter_value
        else None
    )
    if interpreter is None or not interpreter.is_file():
        issues.append("launcher runtime interpreter is missing")
    elif sha256_file(interpreter) != manifest.get("interpreter_sha256"):
        issues.append("launcher runtime interpreter digest mismatch")
    interpreter_prefix_value = manifest.get("interpreter_prefix")
    if not isinstance(interpreter_prefix_value, str) or not interpreter_prefix_value:
        issues.append("launcher runtime interpreter prefix is missing")
    manifest_root_value = manifest.get("source_root")
    manifest_root = (
        Path(manifest_root_value).expanduser()
        if isinstance(manifest_root_value, str) and manifest_root_value
        else None
    )
    expected_root = expected_source_root.expanduser().resolve() if expected_source_root else None
    expected_runtime: str | None = None
    expected_runtime_tree: str | None = None
    expected_generation: str | None = None
    expected_codex_hook_surface: str | None = None
    if expected_root is not None:
        try:
            expected_runtime = runtime_digest(expected_root)
        except (OSError, LauncherContractError) as error:
            issues.append(f"current runtime cannot be fingerprinted: {error}")
        if expected_runtime is not None and manifest.get("runtime_sha256") != expected_runtime:
            issues.append("installed launcher runtime digest does not match the current plugin runtime")
        try:
            sealed_generation = delivery_generation(expected_root)
            expected_runtime_tree = (
                str(sealed_generation["runtime_tree_sha256"])
                if sealed_generation is not None
                else None
            )
            expected_generation = (
                str(sealed_generation["generation"])
                if sealed_generation is not None
                else None
            )
        except (OSError, LauncherContractError) as error:
            issues.append(f"current runtime tree cannot be fingerprinted: {error}")
        if (
            expected_runtime_tree is not None
            and manifest.get("runtime_tree_sha256") != expected_runtime_tree
        ):
            issues.append("installed launcher runtime tree digest does not match the delivery runtime")
        if manifest.get("generation") != expected_generation:
            issues.append("installed launcher generation does not match the delivery descriptor")
        try:
            expected_codex_hook_surface = codex_hook_surface_digest(expected_root)
        except (OSError, LauncherContractError) as error:
            issues.append(f"current Codex hook surface cannot be fingerprinted: {error}")
        if (
            expected_codex_hook_surface is not None
            and manifest.get("codex_hook_surface_sha256")
            != expected_codex_hook_surface
        ):
            issues.append(
                "installed Codex hook surface digest does not match the current plugin adapters"
            )

    records = manifest.get("launchers")
    if not isinstance(records, dict):
        records = {}
        issues.append("launcher manifest has no launcher records")
    launcher_results: dict[str, dict[str, Any]] = {}
    for spec in LAUNCHERS:
        result: dict[str, Any] = {"healthy": True}
        record = records.get(spec.name)
        if not isinstance(record, dict):
            issues.append(f"launcher record missing: {spec.name}")
            result["healthy"] = False
            launcher_results[spec.name] = result
            continue
        for field, expected in (
            ("override_env", spec.override_env),
            ("target_relative", spec.target_relative),
            ("target_kind", spec.target_kind),
        ):
            if record.get(field) != expected:
                issues.append(f"launcher {spec.name} {field} mismatch")
                result["healthy"] = False
        launcher = home / "bin" / spec.name
        if not launcher.is_file():
            issues.append(f"launcher file missing: {launcher}")
            result["healthy"] = False
        else:
            actual_launcher = sha256_file(launcher)
            result["launcher_sha256"] = actual_launcher
            if actual_launcher != record.get("launcher_sha256"):
                issues.append(f"launcher file digest mismatch: {spec.name}")
                result["healthy"] = False

        hint = manifest_root if manifest_root is not None else (expected_root or Path("."))
        target, override_used = resolve_target(spec, hint)
        result["target"] = str(target) if target is not None else None
        result["override_used"] = override_used
        if target is None:
            issues.append(f"launcher target cannot be resolved: {spec.name}")
            result["healthy"] = False
        elif not override_used:
            actual_target = sha256_file(target)
            result["target_sha256"] = actual_target
            if actual_target != record.get("target_sha256"):
                issues.append(f"launcher target digest mismatch: {spec.name}")
                result["healthy"] = False
        if expected_root is not None:
            expected_target = expected_root / Path(spec.target_relative)
            if not expected_target.is_file():
                issues.append(f"current plugin target missing: {expected_target}")
                result["healthy"] = False
            elif sha256_file(expected_target) != record.get("target_sha256"):
                issues.append(f"launcher {spec.name} does not match the current plugin entrypoint")
                result["healthy"] = False
        launcher_results[spec.name] = result

    command_effects = verify_command_effect_snapshot(
        home,
        launcher_manifest=manifest,
        expected_runtime_sha256=expected_runtime,
        environment=environment,
    )
    issues.extend(
        f"command effects: {issue}" for issue in command_effects["issues"]
    )

    unique_issues = list(dict.fromkeys(issues))
    scheduler = (
        verify_scheduler_seal(data_home or kb_home, expected_root or manifest_root, manifest)
        if expected_root is not None or manifest_root is not None
        else {"status": "unavailable", "reasons": ["runtime_root_missing"]}
    )
    return {
        "healthy": not unique_issues,
        "schema": SCHEMA,
        "spec_version": SPEC_VERSION,
        "manifest": str(home / "bin" / MANIFEST_NAME),
        "source_root": str(manifest_root) if manifest_root is not None else None,
        "runtime_sha256": manifest.get("runtime_sha256"),
        "runtime_tree_sha256": manifest.get("runtime_tree_sha256"),
        "generation": manifest.get("generation"),
        "interpreter": str(interpreter) if interpreter is not None else None,
        "interpreter_sha256": manifest.get("interpreter_sha256"),
        "interpreter_prefix": manifest.get("interpreter_prefix"),
        "current_runtime_sha256": expected_runtime,
        "current_runtime_tree_sha256": expected_runtime_tree,
        "current_generation": expected_generation,
        "codex_hook_surface_sha256": manifest.get("codex_hook_surface_sha256"),
        "current_codex_hook_surface_sha256": expected_codex_hook_surface,
        "issues": unique_issues,
        "launchers": launcher_results,
        "command_effects": command_effects,
        "scheduler_seal": scheduler,
    }


def installed_launchers_match(result: dict[str, Any]) -> bool:
    """Prove installed artifacts while allowing only external host helper drift.

    This is effect evidence, not permission to execute a changed helper. The
    command snapshot checksum, launcher bytes and sealed runtime stay strict.
    """
    if result.get("healthy") is True:
        return True
    issues = result.get("issues")
    host_mutable_command_drift = {
        "command effects: trusted command digest changed: codex-plugin-validate-v1",
        "command effects: trusted command digest changed: codex-plugin-cachebuster-v1",
    }
    return isinstance(issues, list) and bool(issues) and all(
        issue in host_mutable_command_drift for issue in issues
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("install", "verify"):
        command = subparsers.add_parser(action)
        command.add_argument("--home", type=Path, default=default_kb_home())
        command.add_argument("--interpreter-home", type=Path)
        command.add_argument("--data-home", type=Path)
        command.add_argument("--require-scheduler-seal", action="store_true")
        command.add_argument("--source-root", type=Path, default=default_source_root())
        command.add_argument("--json", action="store_true")
    repair = subparsers.add_parser("repair-bytecode")
    repair.add_argument("--source-root", type=Path, default=default_source_root())
    repair.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    configure_utf8_stdio()
    args = _parser().parse_args()
    try:
        if args.action == "repair-bytecode":
            result = repair_generated_bytecode(args.source_root)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            else:
                print(
                    "SULDE RUNTIME BYTECODE: REPAIRED "
                    f"files={result['removed_files']} directories={result['removed_directories']}"
                )
            return 0
        if args.action == "install":
            install_launchers(
                args.home,
                args.source_root,
                interpreter_home=args.interpreter_home,
                data_home=args.data_home,
                require_scheduler_seal=args.require_scheduler_seal,
            )
        result = verify_installation(
            args.home,
            expected_source_root=args.source_root,
            data_home=args.data_home,
        )
    except (OSError, ValueError, LauncherContractError) as error:
        print(f"SULDE LAUNCHERS: FAIL: {error}", file=__import__("sys").stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result["healthy"]:
        print(
            f"SULDE LAUNCHERS: READY spec={SPEC_VERSION} "
            f"count={len(LAUNCHERS)} home={args.home.expanduser()} "
            f"scheduler_seal={result['scheduler_seal']['status']}"
        )
    else:
        print("SULDE LAUNCHERS: STALE", file=__import__("sys").stderr)
        for issue in result["issues"]:
            print(f"- {issue}", file=__import__("sys").stderr)
    seal_incomplete = args.require_scheduler_seal and result.get("scheduler_seal", {}).get("status") == "unavailable"
    if seal_incomplete:
        print("SULDE SCHEDULER SEAL: INCOMPLETE: " + "; ".join(result["scheduler_seal"]["reasons"]), file=sys.stderr)
    return 0 if result["healthy"] and not seal_incomplete else 1


if __name__ == "__main__":
    raise SystemExit(main())

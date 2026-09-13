"""sulde_common — shared utilities for every sulde hook entrypoint.

Walks up from the current working directory to find `.sulde-config.yaml`,
parses it into a typed dataclass, and exposes frontend / role / grace-period
helpers. Designed so that every hook entrypoint can import the same module
and behave consistently across worktrees, submodules, and monorepos.

Cross-OS: pure stdlib + pyyaml. No bash assumptions, no `os.system` calls.
Path handling via `pathlib.Path` so Windows path separators just work.

Grace period (#23 fix) uses marker files in the project root:
  .sulde-grace-started  — written by sulde-init / sulde-migrate-from-v0.1.0
  .sulde-grace-ended    — written by /sulde-end-grace command

The marker-file approach is deliberate: mtime-based detection lets users
inadvertently reset the grace window by editing the config file.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def configure_utf8_stdio() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="strict")
            except (LookupError, OSError):
                pass


configure_utf8_stdio()

try:
    import yaml
except ImportError:  # pragma: no cover — handled by entrypoint guard
    yaml = None  # type: ignore[assignment]


CONFIG_FILENAME = ".sulde-config.yaml"
GRACE_STARTED_MARKER = ".sulde-grace-started"
GRACE_ENDED_MARKER = ".sulde-grace-ended"

VALID_ROLES = ("coordinator", "dev", "both", "unknown")
VALID_LEVELS = ("strict", "balanced", "lenient")


@dataclass(frozen=True)
class Frontend:
    name: str
    path: Path
    stack: str  # mobile-android | mobile-ios | mobile-flutter | mobile-harmony | ...


@dataclass(frozen=True)
class SuldeConfig:
    config_path: Path
    project_root: Path
    role: str  # one of VALID_ROLES
    frontends: tuple[Frontend, ...]
    enforcement_level: str  # one of VALID_LEVELS
    grace_period_days: int
    lang: str  # "auto" | "en" | "zh" | "ja" | ...
    enabled: bool
    raw: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def load_config(start_dir: Path | str | None = None) -> SuldeConfig | None:
    """Walk up from start_dir (default cwd) until `.sulde-config.yaml` found.

    Returns None when no config exists in the ancestor chain, OR when pyyaml
    is missing, OR when the file exists but is malformed. The caller should
    treat None as "not a sulde-managed project" and exit 0 silently.
    """
    if yaml is None:
        return None
    config_path = _find_config_path(start_dir)
    if config_path is None:
        return None
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except (yaml.YAMLError, OSError) as exc:  # type: ignore[union-attr]
        sys.stderr.write(
            f"sulde: failed to parse {config_path}: {exc}\n"
            "sulde: hook enforcement disabled for this invocation.\n"
        )
        return None
    if not isinstance(raw, dict):
        sys.stderr.write(f"sulde: {config_path} root must be a mapping\n")
        return None
    return _build_config(config_path, raw)


def silent_exit_if_no_config(start_dir: Path | str | None = None) -> SuldeConfig:
    """Either return a loaded config, or exit 0 if this is not a sulde project.

    Use before project-specific KB/enforcement work: keeps those features
    invisible to projects that did not opt in. The workspace intent guardian
    intentionally runs before this gate and is documented separately.
    """
    cfg = load_config(start_dir)
    if cfg is None:
        sys.exit(0)
    if not cfg.enabled:
        sys.exit(0)
    return cfg


def match_frontend_path(config: SuldeConfig, file_path: Path | str) -> Frontend | None:
    """Return the frontend that owns `file_path`, or None if none match.

    Resolves both sides through realpath so macOS `/tmp` ↔ `/private/tmp`
    style symlinks don't cause spurious misses.
    """
    raw = Path(file_path)
    try:
        resolved = raw.resolve()
    except OSError:
        resolved = raw
    candidates = {str(raw), str(resolved)}
    for fe in config.frontends:
        try:
            fe_resolved = Path(fe.path).resolve()
        except OSError:
            fe_resolved = fe.path
        for fe_str in {str(fe.path).rstrip("/\\"), str(fe_resolved).rstrip("/\\")}:
            for target in candidates:
                if target == fe_str or target.startswith(fe_str + "/") or target.startswith(fe_str + os.sep):
                    return fe
    return None


def get_frontend_subpath(config: SuldeConfig, file_path: Path | str) -> str | None:
    """Return the relative path of `file_path` inside its frontend, or None."""
    fe = match_frontend_path(config, file_path)
    if fe is None:
        return None
    target = Path(file_path)
    try:
        return str(target.relative_to(fe.path))
    except ValueError:
        # `target` is not absolute relative to fe.path — try string strip
        s = str(target)
        prefix = str(fe.path).rstrip("/\\")
        if s.startswith(prefix + os.sep) or s.startswith(prefix + "/"):
            return s[len(prefix) + 1:]
        return None


def is_in_grace_period(config: SuldeConfig) -> bool:
    """Marker-file-based grace check (#23 fix).

    Order:
      1. If `.sulde-grace-ended` exists → False (explicitly ended)
      2. If `.sulde-grace-started` exists and started_at + days > now → True
      3. Otherwise → False (no init/migrate ran, no grace applies)
    """
    ended = config.project_root / GRACE_ENDED_MARKER
    if ended.exists():
        return False
    started = config.project_root / GRACE_STARTED_MARKER
    if not started.exists():
        return False
    try:
        payload = json.loads(started.read_text(encoding="utf-8"))
        started_at = datetime.fromisoformat(payload["started_at"])
        days = int(payload.get("grace_period_days", config.grace_period_days))
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        # Malformed marker → fail closed (no grace).
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    elapsed_days = (now - started_at).total_seconds() / 86400
    return elapsed_days < days


def grace_days_remaining(config: SuldeConfig) -> int:
    """Whole days left in grace window (0 when not in grace)."""
    if not is_in_grace_period(config):
        return 0
    started = config.project_root / GRACE_STARTED_MARKER
    try:
        payload = json.loads(started.read_text(encoding="utf-8"))
        started_at = datetime.fromisoformat(payload["started_at"])
        days = int(payload.get("grace_period_days", config.grace_period_days))
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return 0
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed_days = (datetime.now(timezone.utc) - started_at).total_seconds() / 86400
    remaining = days - elapsed_days
    return max(0, int(remaining + 0.999))


def detect_multi_root(start_dir: Path | str | None = None) -> list[Path]:
    """List all .sulde-config.yaml paths reachable in the git tree.

    Used to warn when a worktree / submodule / monorepo has multiple configs.
    The hook itself always uses the closest-ancestor config (walk-up from cwd).
    """
    start = Path(start_dir or os.getcwd()).resolve()
    results: list[Path] = []
    # Walk up to find all configs from cwd to filesystem root
    cursor: Path | None = start
    while cursor is not None:
        candidate = cursor / CONFIG_FILENAME
        if candidate.exists():
            results.append(candidate)
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    return results


def effective_enforcement_level(config: SuldeConfig) -> str:
    """Returns the runtime enforcement level: grace period forces lenient."""
    if is_in_grace_period(config):
        return "lenient"
    return config.enforcement_level


def get_lang(config: SuldeConfig) -> str:
    """Resolve effective language (en | zh | ja | ...)."""
    lang = (config.lang or "auto").lower()
    if lang != "auto":
        return lang
    env_lang = os.environ.get("SULDE_LANG") or os.environ.get("LANG") or os.environ.get("LC_ALL") or "en"
    env_lang = env_lang.lower()
    if env_lang.startswith("zh"):
        return "zh"
    if env_lang.startswith("ja"):
        return "ja"
    return "en"


def read_json_stdin() -> dict[str, Any]:
    """Parse hook payload from stdin; returns {} on failure (caller decides)."""
    try:
        return json.load(sys.stdin) or {}
    except (json.JSONDecodeError, ValueError):
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_config_path(start_dir: Path | str | None) -> Path | None:
    start = Path(start_dir or os.getcwd()).resolve()
    cursor: Path | None = start
    while cursor is not None:
        candidate = cursor / CONFIG_FILENAME
        if candidate.exists():
            return candidate
        if cursor == cursor.parent:
            return None
        cursor = cursor.parent
    return None


def _build_config(config_path: Path, raw: dict[str, Any]) -> SuldeConfig:
    project_root = config_path.parent

    role = str(raw.get("role", "coordinator")).strip().lower()
    if role not in VALID_ROLES:
        role = "unknown"

    level = str(raw.get("enforcement_level", "balanced")).strip().lower()
    if level not in VALID_LEVELS:
        level = "balanced"

    grace_days = raw.get("enforcement_grace_period_days", 7)
    try:
        grace_days = int(grace_days)
    except (TypeError, ValueError):
        grace_days = 7

    lang = str(raw.get("lang", "auto")).strip().lower() or "auto"
    enabled = bool(raw.get("enabled", True))

    frontends = tuple(_parse_frontends(raw.get("frontends"), project_root))

    return SuldeConfig(
        config_path=config_path,
        project_root=project_root,
        role=role,
        frontends=frontends,
        enforcement_level=level,
        grace_period_days=grace_days,
        lang=lang,
        enabled=enabled,
        raw=raw,
    )


def _parse_frontends(raw: Any, project_root: Path) -> Iterable[Frontend]:
    if not isinstance(raw, list):
        return ()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        path_str = str(item.get("path", "")).strip()
        stack = str(item.get("stack", "")).strip()
        if not name or not path_str:
            continue
        path = Path(path_str)
        if not path.is_absolute():
            path = (project_root / path).resolve()
        yield Frontend(name=name, path=path, stack=stack)

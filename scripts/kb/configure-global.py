#!/usr/bin/env python3
"""Safely install Sulde's global Claude and Codex rule blocks."""

from __future__ import annotations

import argparse
import difflib
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


BEGIN_MARKER = "<!-- sulde:rules:begin -->"
END_MARKER = "<!-- sulde:rules:end -->"
DEFAULT_BACKUP_LIMIT = 5
TEMPLATES = {
    "claude": Path("templates/global/claude-rules.md"),
    "codex": Path("templates/global/codex-agents-rules.md"),
}
KB_LAUNCHER = Path("bin") / "kb-index"


class ConfigError(RuntimeError):
    """An expected, user-actionable configuration failure."""


def configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def absolute_path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def default_kb_home() -> Path:
    from sulde_paths import kb_home as canonical_kb_home

    return absolute_path(canonical_kb_home())


def quote_command_path(path: os.PathLike[str] | str, platform_name: str) -> str:
    value = str(path)
    if platform_name != "nt":
        value = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("$", "\\$")
            .replace("`", "\\`")
        )
    return f'"{value}"'


def kb_cli_command(kb_home: Path, platform_name: str | None = None) -> str:
    from sulde_paths import launcher_home

    platform_name = platform_name or os.name
    launcher = launcher_home(kb_home) / KB_LAUNCHER
    if platform_name != "nt":
        return quote_command_path(launcher, platform_name)
    candidates = (
        kb_home / "venv" / "Scripts" / "python.exe",
        kb_home / "venv" / "bin" / "python",
    )
    python_path = next((path for path in candidates if path.is_file()), candidates[0])
    return (
        f"{quote_command_path(python_path, platform_name)} "
        f"{quote_command_path(launcher, platform_name)}"
    )


def has_templates(path: Path) -> bool:
    return all((path / relative).is_file() for relative in TEMPLATES.values())


def is_repo_root(path: Path) -> bool:
    return (path / "knowledge/INDEX.md").is_file()


def version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(piece) if piece.isdigit() else 0 for piece in path.name.split("."))


def root_candidates() -> list[Path]:
    override = os.environ.get("SULDE_PLUGIN_ROOT")
    candidates: list[Path] = []
    if override:
        candidates.append(absolute_path(override))
    candidates.append(Path(__file__).resolve().parents[2])
    cache = Path.home() / ".claude/plugins/cache/sulde/sulde-cc"
    if cache.is_dir():
        candidates.extend(sorted(cache.iterdir(), key=version_key, reverse=True))
    return candidates


def resolve_repo_root() -> Path | None:
    for candidate in root_candidates():
        if is_repo_root(candidate):
            return candidate
    return None


def template_root() -> Path:
    for candidate in root_candidates():
        if has_templates(candidate):
            return candidate
    raise ConfigError("could not locate canonical templates in a Sulde plugin source")


def render_template(
    kind: str, templates_root: Path, repo_root: Path | None, kb_home: Path
) -> tuple[str, bool]:
    path = templates_root / TEMPLATES[kind]
    try:
        canonical = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"template is not valid UTF-8: {path}: {exc}") from exc
    rendered = canonical.replace("{KB_CLI}", kb_cli_command(kb_home))
    rendered = rendered.replace("{KB_HOME}", str(kb_home))
    from sulde_paths import launcher_home

    rendered = rendered.replace("{SULDE_BIN}", str(launcher_home(kb_home) / "bin"))
    if repo_root is not None:
        rendered = rendered.replace("{REPO_ROOT}", str(repo_root))
    return rendered.rstrip("\n"), repo_root is not None


def desired_block(rendered: str) -> bytes:
    return f"{BEGIN_MARKER}\n{rendered}\n{END_MARKER}\n".encode("utf-8")


def read_target(path: Path) -> bytes | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise ConfigError(f"target path is not a file: {path}")
    return path.read_bytes()


def locate_block(raw: bytes, force: bool = False) -> tuple[int, int] | None:
    begin = BEGIN_MARKER.encode()
    end = END_MARKER.encode()
    begins = [match.start() for match in re.finditer(re.escape(begin), raw)]
    ends = [match.start() for match in re.finditer(re.escape(end), raw)]
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or begins[0] >= ends[0]:
        if not force:
            raise ConfigError("malformed or duplicate Sulde rule markers; inspect the file or use --force")
        if not begins or not ends or begins[0] >= ends[-1]:
            raise ConfigError("cannot safely repair unmatched or reversed Sulde rule markers")
        start, end_start = begins[0], ends[-1]
    else:
        start, end_start = begins[0], ends[0]
    finish = end_start + len(end)
    if raw[finish : finish + 2] == b"\r\n":
        finish += 2
    elif raw[finish : finish + 1] == b"\n":
        finish += 1
    return start, finish


def separator_before(raw: bytes, start: int) -> tuple[int, bytes]:
    if start == 0:
        return start, b""
    if raw[max(0, start - 2) : start] == b"\r\n":
        return start - 2, b"\r\n"
    if raw[start - 1 : start] == b"\n":
        return start - 1, b"\n"
    return start, b""


def install_content(raw: bytes | None, block: bytes, force: bool) -> bytes:
    current = raw or b""
    location = locate_block(current, force)
    if location is not None:
        start, finish = location
        return current[:start] + block + current[finish:]
    separator = b"\n" if current else b""
    return current + separator + block


def uninstall_content(raw: bytes | None, force: bool) -> bytes | None:
    if raw is None:
        return None
    location = locate_block(raw, force)
    if location is None:
        return raw
    start, finish = location
    removal_start, _ = separator_before(raw, start)
    return raw[:removal_start] + raw[finish:]


def backup_path(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{stamp}.{suffix}.bak")
        suffix += 1
    return candidate


def prune_generated_backups(path: Path, limit: int) -> None:
    if limit == 0:
        return
    pattern = re.compile(
        rf"^{re.escape(path.name)}\."
        r"(?P<stamp>\d{8}T\d{6}\.\d{6}Z)"
        r"(?:\.(?P<suffix>[1-9]\d*))?\.bak$"
    )
    matches: list[tuple[str, int, Path]] = []
    for candidate in path.parent.iterdir():
        match = pattern.fullmatch(candidate.name)
        if match and candidate.is_file():
            matches.append((match.group("stamp"), int(match.group("suffix") or 0), candidate))
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _, _, candidate in matches[limit:]:
        candidate.unlink()


def atomic_write(path: Path, content: bytes, original: bytes | None, limit: int) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    original_mode: int | None = None
    if original is not None:
        backup = backup_path(path)
        shutil.copy2(path, backup)
        original_mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if original_mode is not None:
            os.chmod(temporary, original_mode)
        os.replace(temporary, path)
        prune_generated_backups(path, limit)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return backup


def diff_summary(path: Path, actual: bytes | None, wanted: bytes) -> str:
    actual_text = "" if actual is None else actual.decode("utf-8", errors="replace")
    wanted_text = wanted.decode("utf-8")
    return "".join(difflib.unified_diff(
        actual_text.splitlines(keepends=True), wanted_text.splitlines(keepends=True),
        fromfile=str(path), tofile=f"{path} (expected)", n=2,
    ))


def selected_targets(args: argparse.Namespace) -> list[tuple[str, Path]]:
    defaults = {
        "claude": Path.home() / ".claude/CLAUDE.md",
        "codex": Path.home() / ".codex/AGENTS.md",
    }
    overrides = {"claude": args.claude_md, "codex": args.agents_md}
    kinds = [args.target] if args.target != "all" else ["claude", "codex"]
    return [(kind, absolute_path(overrides[kind]) if overrides[kind] else absolute_path(defaults[kind])) for kind in kinds]


def run(args: argparse.Namespace) -> int:
    templates_root = template_root()
    repo_root = resolve_repo_root()
    kb = absolute_path(args.kb_home) if args.kb_home else default_kb_home()
    failed = False
    for kind, path in selected_targets(args):
        rendered, repo_resolved = render_template(kind, templates_root, repo_root, kb)
        if not repo_resolved and "{REPO_ROOT}" in rendered:
            print(f"warning: {kind}: REPO_ROOT unresolved; placeholder retained", file=sys.stderr)
        block = desired_block(rendered)
        original = read_target(path)
        if args.check:
            location = locate_block(original or b"", args.force)
            actual = None if location is None else (original or b"")[location[0] : location[1]]
            if actual != block:
                reason = "missing" if location is None else "drifted"
                print(f"{kind}: rule block {reason}: {path}", file=sys.stderr)
                print(diff_summary(path, actual, block), file=sys.stderr, end="")
                failed = True
            else:
                print(f"{kind}: rule block OK: {path}")
            continue
        updated = install_content(original, block, args.force) if args.install else uninstall_content(original, args.force)
        if updated == original or (updated is None and original is None):
            print(f"{kind}: no change: {path}")
            continue
        if args.dry_run:
            print(f"{kind}: dry-run: would write {path}")
            print(diff_summary(path, original, updated or b""), end="")
            continue
        backup = atomic_write(path, updated or b"", original, args.backup_limit)
        action = "installed" if args.install else "removed"
        note = f"; backup: {backup}" if backup else ""
        print(f"{kind}: rule block {action}: {path}{note}")
    return 1 if failed else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--uninstall", action="store_true")
    parser.add_argument("--target", choices=("claude", "codex", "all"), default="all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--claude-md")
    parser.add_argument("--agents-md")
    parser.add_argument("--kb-home")
    parser.add_argument("--backup-limit", type=int, default=DEFAULT_BACKUP_LIMIT)
    args = parser.parse_args(argv)
    if args.dry_run and args.check:
        parser.error("--dry-run is only valid with --install or --uninstall")
    if args.force and args.check:
        parser.error("--force is only valid with --install or --uninstall")
    if args.backup_limit < 0:
        parser.error("--backup-limit must be non-negative")
    return args


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    try:
        return run(parse_args(argv))
    except ConfigError as exc:
        print(f"configure-global: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"configure-global: filesystem error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

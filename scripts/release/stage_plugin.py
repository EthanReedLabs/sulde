#!/usr/bin/env python3
"""Stage deterministic, self-contained Sulde plugin artifacts."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import os
import shutil
import stat
import subprocess
import sys
from typing import Literal


# Staging and artifact validation are read-only operations.  Prevent imports in
# this process (and Python children spawned by validators) from mutating either
# the source tree or an already sealed runtime with derived bytecode.
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "kb-index"))
sys.path.insert(0, str(ROOT / "scripts" / "kb"))
from corpus_manifest import load_manifest
from knowledge_history import build_history, load_history, write_history
from host_capabilities import validate_artifact


CLAUDE_PREFIXES = (
    ".claude-plugin/",
    "commands/",
    "hooks/",
    "knowledge/",
    "scripts/",
    "skills/",
    "template/",
    "templates/",
    "tools/",
)
CLAUDE_FILES = {
    "CANON.md",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "docs/dual-runtime-contract.md",
    "docs/event-observability.md",
    "docs/intent-guardian.md",
    "docs/kb-retrieval-contract.md",
    "spec/task-authoring.md",
    "spec/task-contract.md",
}
# Private publication tooling consumes the source repository, not an installed
# runtime. Keep its importer and overlay together on the source side; do not
# sanitize their matching rules or exclude the unrelated maintenance tools.
PRIVATE_PUBLISHING_FILES = frozenset({
    "scripts/release/export_public_harness.py",
    "scripts/release/verify_public_harness_candidate.py",
})
PRIVATE_PUBLISHING_PREFIXES = ("scripts/release/public_harness_overlay/",)
CODEX_ROOT = Path("integrations/codex")
CODEX_PLUGIN = CODEX_ROOT / "plugins" / "sulde"
RUNTIME_PREFIXES = (
    "hooks/",
    "knowledge/",
    "scripts/kb/",
    "skills/sediment/",
    "templates/",
    "tools/kb-index/",
    "tools/kb-mcp/",
)
RUNTIME_FILES = {
    "CANON.md",
    "LICENSE",
    "docs/dual-runtime-contract.md",
    "docs/event-observability.md",
    "docs/intent-guardian.md",
    "docs/kb-retrieval-contract.md",
    "spec/task-authoring.md",
    "spec/task-contract.md",
    "template/_project/docs-hub/00_shared-rules/task-brief.md.template",
}
# Runtime modules may be created by an in-progress change before they enter the
# Git index.  Keep this inventory deliberately narrow: staging must not turn
# into a generic "copy every untracked file" operation, because the source tree
# can also contain local state and credentials.
_FROZEN_REQUIRED_RUNTIME_SOURCE_ALLOWLIST = (
    Path("scripts/kb/approval_timeout_policy.py"),
    Path("scripts/kb/codex_cli_contract.py"),
    Path("scripts/kb/decision_kernel.py"),
    Path("scripts/kb/local_file_operations.py"),
    Path("scripts/kb/native_decision_journal.py"),
    Path("scripts/kb/intent_guardian_parts/figma_read_recovery.py"),
    Path("scripts/kb/intent_guardian_parts/intervention_control.py"),
    Path("scripts/kb/intent_guardian_parts/native_grant.py"),
    Path("scripts/kb/intent_guardian_parts/orchestrator_resources.py"),
    Path("scripts/kb/intent_guardian_parts/pre_execution_control.py"),
    Path("scripts/kb/intent_guardian_parts/pre_execution_proof.py"),
    Path("scripts/kb/intent_guardian_parts/session_workspace.py"),
    Path("scripts/kb/operational_readiness.py"),
    Path("scripts/kb/production_recovery.py"),
    Path("scripts/kb/production_recovery_readiness.py"),
    Path("scripts/kb/production-recovery.py"),
    Path("scripts/kb/production_recovery_control.py"),
    Path("scripts/kb/production_recovery_targets.py"),
    Path("scripts/kb/sulde_paths.py"),
    Path("scripts/kb/sulde-statusline.py"),
    Path("scripts/kb/sulde_status_snapshot.py"),
    Path("scripts/kb/task_ownership.py"),
)

REQUIRED_RUNTIME_SOURCE_FILES = (
    Path("scripts/kb/approval_timeout_policy.py"),
    Path("scripts/kb/codex_cli_contract.py"),
    Path("scripts/kb/decision_kernel.py"),
    Path("scripts/kb/local_file_operations.py"),
    Path("scripts/kb/native_decision_journal.py"),
    Path("scripts/kb/intent_guardian_parts/figma_read_recovery.py"),
    Path("scripts/kb/intent_guardian_parts/intervention_control.py"),
    Path("scripts/kb/intent_guardian_parts/native_grant.py"),
    Path("scripts/kb/intent_guardian_parts/orchestrator_resources.py"),
    Path("scripts/kb/intent_guardian_parts/pre_execution_control.py"),
    Path("scripts/kb/intent_guardian_parts/pre_execution_proof.py"),
    Path("scripts/kb/intent_guardian_parts/session_workspace.py"),
    Path("scripts/kb/operational_readiness.py"),
    Path("scripts/kb/production_recovery.py"),
    Path("scripts/kb/production_recovery_readiness.py"),
    Path("scripts/kb/production-recovery.py"),
    Path("scripts/kb/production_recovery_control.py"),
    Path("scripts/kb/production_recovery_targets.py"),
    Path("scripts/kb/sulde_paths.py"),
    Path("scripts/kb/sulde-statusline.py"),
    Path("scripts/kb/sulde_status_snapshot.py"),
    Path("scripts/kb/task_ownership.py"),
)
CODEX_SKILLS = (
    "dispatch-task",
    "intent-guardian",
    "kb-search",
    "memory-distill",
    "sediment",
)
PLATFORM_TEMPLATES = {
    "posix": CODEX_PLUGIN / "hooks.posix.json",
    "windows": CODEX_PLUGIN / "hooks.windows.json",
}
WINDOWS_MCP_SERVER = {
    "command": "powershell.exe",
    "args": [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        "./scripts/run-mcp.ps1",
    ],
    "cwd": ".",
}
PORTABLE_PATH_TOKENS = {
}
DELIVERY_GENERATION_SCHEMA = "sulde-delivery-generation-v1"
DELIVERY_GENERATION_NAME = "generation.json"


@dataclass(frozen=True)
class GitEntry:
    path: Path
    mode: int


def git_entries(root: Path) -> list[GitEntry]:
    output = subprocess.check_output(["git", "ls-files", "-s", "-z"], cwd=root)
    entries: list[GitEntry] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode = int(metadata.split(b" ", 1)[0], 8)
        entries.append(GitEntry(Path(raw_path.decode("utf-8")), mode))
    return entries


def _validated_required_runtime_sources(root: Path) -> tuple[Path, ...]:
    """Reject any staging inventory outside the frozen runtime contract."""
    required_sources = REQUIRED_RUNTIME_SOURCE_FILES
    path_type = type(Path())
    if type(required_sources) is not tuple or any(
        type(relative) is not path_type for relative in required_sources
    ):
        raise ValueError(
            "invalid required runtime source allowlist: "
            "expected a tuple of platform Path values"
        )
    if any(
        relative.is_absolute()
        or relative.as_posix() in {"", "."}
        or ".." in relative.parts
        for relative in required_sources
    ):
        raise ValueError(
            "invalid required runtime source allowlist: "
            "paths must be canonical repository-relative paths"
        )
    if len(required_sources) != len(set(required_sources)):
        raise ValueError(
            "invalid required runtime source allowlist: duplicate path"
        )
    if required_sources != _FROZEN_REQUIRED_RUNTIME_SOURCE_ALLOWLIST:
        raise ValueError(
            "invalid required runtime source allowlist: "
            "does not exactly match the frozen canonical order"
        )

    resolved_sources: list[Path] = []
    try:
        resolved_root = root.resolve()
        for relative in required_sources:
            resolved = (resolved_root / relative).resolve(strict=False)
            resolved.relative_to(resolved_root)
            resolved_sources.append(resolved)
    except (OSError, RuntimeError, ValueError) as error:
        raise ValueError(
            "invalid required runtime source allowlist: "
            "path escapes the repository"
        ) from error
    if len(resolved_sources) != len(set(resolved_sources)):
        raise ValueError(
            "invalid required runtime source allowlist: "
            "duplicate canonical or physical resource"
        )
    return required_sources


def release_entries(root: Path) -> list[GitEntry]:
    """Return tracked files plus the explicit required-runtime inventory.

    Every allowlisted source is validated even after it becomes tracked.  A
    missing file, directory, symlink, or other non-regular source is a release
    error rather than an artifact that silently omits a runtime dependency.
    """
    required_sources = _validated_required_runtime_sources(root)
    entries = git_entries(root)
    tracked_paths = {entry.path for entry in entries}
    for relative in required_sources:
        source = root / relative
        try:
            metadata = source.lstat()
        except OSError as error:
            raise ValueError(
                f"required runtime source is unavailable: {relative}"
            ) from error
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(
                f"required runtime source is not a regular file: {relative}"
            )
        if relative not in tracked_paths:
            mode = 0o100755 if metadata.st_mode & 0o111 else 0o100644
            entries.append(GitEntry(relative, mode))
    return entries


def prepare_output(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)


def copy_entry(root: Path, output: Path, entry: GitEntry, destination: Path) -> None:
    source = root / entry.path
    try:
        metadata = source.lstat()
    except OSError as error:
        raise ValueError(f"release source is unavailable: {entry.path}") from error
    if entry.mode not in {0o100644, 0o100755} or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"release source is not a regular file: {entry.path}")
    resolved = source.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"tracked path escapes repository: {entry.path}")
    lowered = {part.casefold() for part in entry.path.parts}
    if (
        entry.path.name == "mem-sync.key"
        or entry.path.suffix == ".db"
        or lowered & {"data", "cache", ".git"}
    ):
        raise ValueError(f"forbidden artifact path: {entry.path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if os.name != "nt":
        if entry.mode == 0o100755:
            destination.chmod(0o755)
        elif entry.mode == 0o100644:
            destination.chmod(0o644)


def is_prefixed(path: Path, prefixes: tuple[str, ...]) -> bool:
    rendered = path.as_posix()
    return any(rendered.startswith(prefix) for prefix in prefixes)


def is_claude_release_path(path: Path) -> bool:
    rendered = path.as_posix()
    if rendered in PRIVATE_PUBLISHING_FILES or is_prefixed(
        path, PRIVATE_PUBLISHING_PREFIXES
    ):
        return False
    return rendered in CLAUDE_FILES or is_prefixed(path, CLAUDE_PREFIXES)


def neutralize_launchagent_paths(runtime: Path) -> None:
    """Turn source-only machine tokens into portable staged placeholders."""
    targets = [
        runtime / "scripts" / "kb" / "install-agents.sh",
        runtime / "scripts" / "release" / "stage_plugin.py",
    ]
    targets.extend(sorted((runtime / "templates" / "launchagents").glob("*.plist")))
    for path in targets:
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        rendered = source
        for machine_path, token in PORTABLE_PATH_TOKENS.items():
            rendered = rendered.replace(machine_path, token)
        if rendered != source:
            path.write_text(rendered, encoding="utf-8")


def tree_digest(root: Path) -> str:
    """Hash one portable immutable tree and reject release-time aliases."""
    argument = root.expanduser()
    if argument.is_symlink():
        raise ValueError(f"runtime is a symlink: {argument}")
    selected = argument.resolve()
    if not selected.is_dir() or any(
        path.name == ".git" for path in selected.rglob(".git")
    ):
        raise ValueError(f"runtime is not an immutable artifact tree: {selected}")
    digest = hashlib.sha256()
    for path in sorted(selected.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"runtime tree contains a symlink: {path}")
        relative_parts = path.relative_to(selected).parts
        if "__pycache__" in relative_parts or path.suffix.casefold() == ".pyc":
            raise ValueError(f"runtime tree contains executable Python bytecode: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(selected).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def write_delivery_generation(plugin_root: Path, platform: str) -> dict[str, str | int]:
    descriptor = plugin_root / ".codex-plugin" / "plugin.json"
    plugin = json.loads(descriptor.read_text(encoding="utf-8"))
    version = plugin.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("Codex plugin version is missing while sealing generation")
    runtime_sha256 = tree_digest(plugin_root / "runtime")
    payload: dict[str, str | int] = {
        "schema_version": 1,
        "schema": DELIVERY_GENERATION_SCHEMA,
        "provider": "codex",
        "platform": platform,
        "plugin_version": version,
        "runtime_tree_sha256": runtime_sha256,
        "generation": f"{version}:{runtime_sha256}",
    }
    target = plugin_root / ".codex-plugin" / DELIVERY_GENERATION_NAME
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def stage_claude(root: Path, output: Path) -> Path:
    _validated_required_runtime_sources(root)
    prepare_output(output)
    for entry in release_entries(root):
        if is_claude_release_path(entry.path):
            copy_entry(root, output, entry, output / entry.path)
    neutralize_launchagent_paths(output)
    manifest = load_manifest(output, verify_files=True)
    write_history(output, build_history(output, root, manifest=manifest))
    load_history(output, manifest=manifest)
    validate_artifact(output, provider="claude")
    _report(output, manifest.document_count)
    return output


def stage_codex(
    root: Path,
    output: Path,
    platform: Literal["posix", "windows"],
) -> Path:
    _validated_required_runtime_sources(root)
    prepare_output(output)
    entries = release_entries(root)
    # The source tree keeps a root-level POSIX convenience copy, but Codex
    # discovers plugin hooks from hooks/hooks.json by convention.  Exclude all
    # source templates here so the staged plugin exposes exactly one discovery
    # path after selecting the target platform.
    plugin_templates = set(PLATFORM_TEMPLATES.values()) | {
        CODEX_PLUGIN / "hooks.json"
    }

    for entry in entries:
        if entry.path == CODEX_ROOT / ".agents" / "plugins" / "marketplace.json":
            copy_entry(root, output, entry, output / entry.path.relative_to(CODEX_ROOT))
        elif entry.path.is_relative_to(CODEX_PLUGIN):
            if entry.path not in plugin_templates:
                copy_entry(
                    root,
                    output,
                    entry,
                    output / entry.path.relative_to(CODEX_ROOT),
                )

    runtime = output / "plugins" / "sulde" / "runtime"
    for entry in entries:
        if entry.path.as_posix() in RUNTIME_FILES or is_prefixed(
            entry.path, RUNTIME_PREFIXES
        ):
            copy_entry(root, output, entry, runtime / entry.path)

    plugin_root = output / "plugins" / "sulde"
    for entry in entries:
        if any(
            entry.path.is_relative_to(Path("skills") / name)
            for name in CODEX_SKILLS
        ):
            copy_entry(root, output, entry, plugin_root / entry.path)

    descriptor = plugin_root / ".codex-plugin" / "plugin.json"
    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    payload["skills"] = "./skills/"
    descriptor.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if platform == "windows":
        mcp_manifest = plugin_root / ".mcp.json"
        mcp_payload = json.loads(mcp_manifest.read_text(encoding="utf-8"))
        mcp_payload["mcpServers"]["sulde_kb"] = WINDOWS_MCP_SERVER
        mcp_manifest.write_text(
            json.dumps(mcp_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    neutralize_launchagent_paths(runtime)

    template = PLATFORM_TEMPLATES[platform]
    template_entry = next((entry for entry in entries if entry.path == template), None)
    if template_entry is None:
        raise ValueError(f"platform hook template is not tracked: {template}")
    copy_entry(
        root,
        output,
        template_entry,
        output / "plugins" / "sulde" / "hooks" / "hooks.json",
    )

    manifest = load_manifest(runtime, verify_files=True)
    write_history(runtime, build_history(runtime, root, manifest=manifest))
    load_history(runtime, manifest=manifest)
    generation = write_delivery_generation(plugin_root, platform)

    validate_artifact(plugin_root, provider="codex")
    if tree_digest(runtime) != generation["runtime_tree_sha256"]:
        raise ValueError("Codex artifact changed after generation was sealed")
    _report(output, manifest.document_count)
    return output


def _report(output: Path, document_count: int) -> None:
    file_count = sum(path.is_file() for path in output.rglob("*"))
    print(
        f"staged {file_count} files; verified {document_count} corpus documents: "
        f"{output}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("claude", "codex"), required=True)
    parser.add_argument("--platform", choices=("posix", "windows"))
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.target == "claude":
        stage_claude(ROOT, args.output)
    else:
        platform = args.platform or ("windows" if os.name == "nt" else "posix")
        stage_codex(ROOT, args.output, platform)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

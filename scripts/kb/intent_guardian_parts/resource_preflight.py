"""Narrow, side-effect-free resource preflight helpers."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from typing import Any, Iterable

from command_template import (
    has_unquoted_shell_control,
    read_pipeline_segments,
    split_command_template,
)
from intervention import git_ref_verification_digest
from local_file_operations import path_components_are_not_symlinks

from launcher_contract import (
    installed_launchers_match,
    verify_installation as verify_launcher_installation,
    verify_scheduler_seal,
)
from sulde_paths import launcher_home

from .state import (
    CONTINUATION_PROFILES,
    SEALED_PYTHON_ENV,
    SEALED_PYTHON_FLAG,
    SECRET_KEY,
    _SECRET_VALUE_PATTERN,
    IntentGuardianError,
    _codex_plugin_install_binding,
    _codex_plugin_cachebuster_v2_binding,
    _codex_plugin_install_v2_binding,
    _launcher_refresh_binding,
    _scheduler_reconcile_binding,
    _sha256_path,
    workspace_root,
)


def git_worktree_lifecycle_event(typed: Any) -> dict[str, Any]:
    if not isinstance(typed, dict) or typed.get("kind") != "git_worktree_lifecycle":
        return {}
    overlay: dict[str, Any] = {}
    capability = str(typed.get("capability") or "")
    target = str(typed.get("target") or "")
    if capability:
        overlay["capability"] = capability
    if target:
        overlay.update({"target": target, "write_targets": [target]})
    sealed = typed.get("resource")
    resource_id = str(sealed.get("resource_id") or "") if isinstance(sealed, dict) else ""
    if typed.get("status") == "classified" and resource_id.startswith("sha256:"):
        overlay.update({
            "verification_kind": "relation",
            "verification_sha256": resource_id.removeprefix("sha256:"),
        })
    return overlay


def command_execution_cwd(
    payload: dict[str, Any], tool_input: dict[str, Any],
) -> str:
    return str(
        tool_input.get("cwd")
        or tool_input.get("workdir")
        or payload.get("cwd")
        or os.getcwd()
    )


def git_invocation(
    command: str,
    *,
    cwd: str,
) -> tuple[Path, str, list[str]] | None:
    """Parse one unchained Git command and resolve only its local working tree."""
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if not tokens or Path(tokens[0]).name.lower() != "git":
        return None
    base = Path(cwd or os.getcwd()).expanduser()
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token == "-C" and index + 1 < len(tokens):
            candidate = Path(tokens[index + 1]).expanduser()
            base = candidate if candidate.is_absolute() else base / candidate
            index += 2
            continue
        if token == "-c" and index + 1 < len(tokens):
            index += 2
            continue
        if token in {"--no-pager", "--paginate"}:
            index += 1
            continue
        if token.startswith("--git-dir=") or token.startswith("--work-tree="):
            return None
        if token.startswith("-"):
            return None
        return base, token.lower(), tokens[index + 1 :]
    return None


def _local_git_output(cwd: Path, *arguments: str) -> str:
    """Read bounded local Git metadata; never invoke a network subcommand."""
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _git_remote_digest(cwd: Path, remote: str) -> str:
    resolved = _local_git_output(cwd, "remote", "get-url", "--push", remote)
    material = resolved or f"{cwd.resolve()}\0{remote}"
    return hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()


def _git_head_ref(value: str) -> str:
    candidate = value.strip()
    if not candidate or any(marker in candidate for marker in ("*", "?", "[", "^")):
        return ""
    if candidate.startswith("refs/heads/"):
        return candidate
    if candidate.startswith("refs/") or candidate in {"HEAD", "@"}:
        return ""
    return f"refs/heads/{candidate}"


def _git_upstream(cwd: Path) -> tuple[str, str] | None:
    upstream = _local_git_output(
        cwd,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    )
    if not upstream or "/" not in upstream:
        return None
    remote, branch = upstream.split("/", 1)
    ref = _git_head_ref(branch)
    return (remote, ref) if remote and ref else None


def _git_positionals(arguments: list[str], *, action: str) -> list[str]:
    takes_value = {
        "push": {"--exec", "--receive-pack", "--repo"},
        "ls-remote": {"--server-option", "--sort", "--upload-pack"},
    }.get(action, set())
    values: list[str] = []
    index = 0
    positional_only = False
    while index < len(arguments):
        token = arguments[index]
        if positional_only:
            values.append(token)
        elif token == "--":
            positional_only = True
        elif token in takes_value:
            index += 1
        elif any(token.startswith(f"{option}=") for option in takes_value):
            pass
        elif token.startswith("-"):
            pass
        else:
            values.append(token)
        index += 1
    return values


def git_ref_observation(
    command: str,
    *,
    cwd: str,
) -> dict[str, Any] | None:
    """Describe one exact branch push or independent remote-ref read."""
    invocation = git_invocation(command, cwd=cwd)
    if invocation is None:
        return None
    repository, action, arguments = invocation
    if action not in {"push", "ls-remote"}:
        return None
    positionals = _git_positionals(arguments, action=action)
    remote = ""
    ref = ""
    source = ""
    if action == "push":
        if any(token == "--delete" or token.startswith("--delete=") for token in arguments):
            return None
        if not positionals:
            upstream = _git_upstream(repository)
            if upstream is None:
                return None
            remote, ref = upstream
            source = "HEAD"
        elif len(positionals) == 1:
            upstream = _git_upstream(repository)
            if upstream is None or upstream[0] != positionals[0]:
                return None
            remote, ref = upstream
            source = "HEAD"
        elif len(positionals) == 2:
            remote, refspec = positionals
            refspec = refspec.removeprefix("+")
            if refspec.startswith(":"):
                return None
            if ":" in refspec:
                source, destination = refspec.split(":", 1)
                ref = _git_head_ref(destination)
            else:
                source = refspec
                ref = _git_head_ref(refspec)
            if not source or not ref:
                return None
        else:
            return None
    else:
        if len(positionals) != 2:
            return None
        remote, requested = positionals
        if "--heads" in arguments and not requested.startswith("refs/"):
            requested = f"refs/heads/{requested}"
        ref = _git_head_ref(requested)
        if not ref:
            return None
    remote_identity = _git_remote_digest(repository, remote)
    target = f"git-ref:{remote_identity}:{ref}"
    result: dict[str, Any] = {
        "action": action,
        "target": target,
        "remote": remote_identity,
        "ref": ref,
    }
    if action == "push":
        oid = _local_git_output(repository, "rev-parse", f"{source}^{{commit}}")
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", oid):
            return {**result, "verification_kind": "unsupported", "verification_sha256": ""}
        oid = oid.lower()
        expectation = git_ref_verification_digest(
            remote=remote_identity,
            ref=ref,
            oid=oid,
            base=repository,
        )
        return {
            **result,
            "oid": oid,
            "verification_kind": "relation",
            "verification_sha256": expectation,
        }
    return {**result, "verification_kind": "unsupported", "verification_sha256": ""}


def tool_local_write_targets(
    targets: list[str], payload: dict[str, Any], tool_input: dict[str, Any],
) -> list[str]:
    local = tool_input.get("cwd") or tool_input.get("workdir")
    if not local:
        return targets
    base = Path(str(local)).expanduser()
    if not base.is_absolute():
        base = Path(str(payload.get("cwd") or os.getcwd())).expanduser() / base
    normalized: list[str] = []
    for target in targets:
        candidate = Path(target).expanduser()
        normalized.append(
            target
            if candidate.is_absolute() or target.startswith("[")
            else str((base / candidate).resolve(strict=False))
        )
    return normalized


def safe_target(value: Any) -> str:
    if value is None:
        return ""
    rendered = str(value).strip().replace("\n", " ")[:500]
    if SECRET_KEY.search(rendered):
        return "[redacted-sensitive-target]"
    return rendered


def safe_local_path(value: Any) -> str:
    """Preserve local path identity without mistaking filenames for secrets."""
    if value is None:
        return ""
    rendered = str(value).strip().replace("\n", " ")[:1000]
    if _SECRET_VALUE_PATTERN.search(rendered):
        return "[redacted-sensitive-target]"
    return rendered


def first_input_value(tool_input: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = tool_input.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return safe_target(value)
    return ""


def response_target(value: Any, *, depth: int = 0) -> str:
    if depth > 3:
        return ""
    if isinstance(value, dict):
        for key in (
            "uri", "url", "resource_uri", "resourceUri", "node_id", "nodeId",
            "document_id", "documentId", "file_path", "path", "id",
        ):
            candidate = value.get(key)
            if isinstance(candidate, (str, int)) and str(candidate).strip():
                return safe_target(candidate)
        for key in (
            "structuredContent", "structured_content", "result", "data", "content",
        ):
            candidate = response_target(value.get(key), depth=depth + 1)
            if candidate:
                return candidate
    elif isinstance(value, list):
        for item in value[:20]:
            candidate = response_target(item, depth=depth + 1)
            if candidate:
                return candidate
    return ""


def resolved_executable(value: str, *, cwd: Path) -> Path | None:
    candidate = Path(value).expanduser()
    if candidate.is_absolute() or len(candidate.parts) > 1:
        resolved = (candidate if candidate.is_absolute() else cwd / candidate).resolve()
    else:
        located = shutil.which(value)
        if not located:
            return None
        resolved = Path(located).expanduser().resolve()
    return resolved if resolved.is_file() else None


def sealed_python_invocation(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Parse the only environment/flag wrapper accepted by v2 profiles."""
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if (
        len(tokens) < 5
        or tokens[0] != SEALED_PYTHON_ENV
        or tokens[2] != SEALED_PYTHON_FLAG
    ):
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    interpreter = resolved_executable(tokens[1], cwd=working_directory)
    if interpreter is None or not re.fullmatch(
        r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?",
        interpreter.name.lower(),
    ):
        return None
    return {
        "argv": tokens[3:],
        "interpreter": interpreter,
        "python_env": tokens[0],
        "python_flag": tokens[2],
    }


def _executed_script_token_index(tokens: list[str], *, cwd: Path) -> int | None:
    """Locate a Python/shell script operand without treating data as execution."""
    index = 0
    while True:
        while index < len(tokens) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]
        ):
            index += 1
        if index >= len(tokens):
            return None
        executable = resolved_executable(tokens[index], cwd=cwd)
        executable_name = (
            executable.name.lower()
            if executable is not None
            else Path(tokens[index]).name.lower()
        )
        if executable_name != "env":
            break
        index += 1
        while index < len(tokens) and re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]
        ):
            index += 1
        # Unknown env options may change argv interpretation.  Return no role
        # proof so callers can keep their conservative fallback.
        if index >= len(tokens) or tokens[index].startswith("-"):
            return None
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable_name):
        # Interpreter flags are not authority. Scan only the small prefix in
        # which Python can select its script, and require a real path later.
        for candidate in range(index + 1, min(len(tokens), index + 6)):
            if not tokens[candidate].startswith("-"):
                return candidate
        return None
    if executable_name in {
        "bash",
        "sh",
        "zsh",
        "powershell",
        "powershell.exe",
        "pwsh",
    }:
        return index + 1 if index + 1 < len(tokens) else None
    return index


def _candidate_controller_subcommand(
    tokens: list[str], *, script_index: int,
) -> str:
    """Return the candidate controller role without interpreting option data."""
    index = script_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token == "--json":
            index += 1
            continue
        if token in {"--candidate-home", "--codex"}:
            if index + 1 >= len(tokens):
                return ""
            index += 2
            continue
        if token.startswith("-"):
            return ""
        return token
    return ""


def unsealed_sulde_maintenance_invocation(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Fail closed when a known writer is invoked outside its sealed shape."""
    if has_unquoted_shell_control(command):
        return None
    if codex_plugin_read_only_maintenance_command(command, cwd=cwd):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    script_index = _executed_script_token_index(tokens, cwd=working_directory)
    if script_index is None or script_index >= len(tokens):
        return None
    raw_script = Path(tokens[script_index]).expanduser()
    candidate_promotion = (
        raw_script.name.lower() == "candidate_codex_plugin.py"
        and _candidate_controller_subcommand(
            tokens, script_index=script_index,
        ) == "promote"
    )
    try:
        script = (
            raw_script if raw_script.is_absolute() else working_directory / raw_script
        ).resolve(strict=True)
    except OSError:
        if not candidate_promotion:
            return None
        script = raw_script
    targets = {
        "install_codex_plugin.py": "[host-local:codex-plugin]",
        "install-agents.sh": "[host-local:sulde-scheduler]",
        "install-agents.ps1": "[host-local:sulde-scheduler]",
        "bootstrap.sh": "[host-local:sulde-launchers]",
    }
    target = (
        "[host-local:codex-plugin]"
        if candidate_promotion
        else targets.get(script.name)
    )
    if target is None:
        return None
    return {
        "effect": "external_write",
        "formal_maintenance": True,
        "reason": (
            f"正式维护入口 {raw_script.name} 未匹配 proposal-bound 密封调用；"
            "已在执行前拒绝，普通 unknown 策略不适用"
        ),
        "target": target,
        "write_targets": [],
    }


def formal_maintenance_reference(command: str) -> bool:
    """Tag an executed maintenance script without treating argv data as code."""
    pattern = (
        r"(?:^|[\s/'\"])(?:install_codex_plugin\.py|install-agents\.(?:sh|ps1)|bootstrap\.sh)(?:$|[\s'\"])"
    )
    if has_unquoted_shell_control(command):
        segments = read_pipeline_segments(command)
        if segments:
            return any(formal_maintenance_reference(segment) for segment in segments)
        # Unsupported shell composition stays conservative, but ordinary
        # ``&&``/pipeline diagnostics are classified by executed role rather
        # than by filenames embedded in quoted interpreter data.
        return bool(re.search(pattern, command))
    try:
        tokens = split_command_template(command)
    except ValueError:
        return False
    working_directory = Path(os.getcwd()).expanduser().resolve()
    script_index = _executed_script_token_index(tokens, cwd=working_directory)
    if script_index is None or script_index >= len(tokens):
        return bool(re.search(pattern, command))
    if tokens[script_index].startswith("-"):
        return bool(re.search(pattern, command))
    script_name = Path(tokens[script_index]).name.lower()
    if script_name == "candidate_codex_plugin.py":
        return _candidate_controller_subcommand(
            tokens, script_index=script_index,
        ) == "promote"
    return script_name in {
        "install_codex_plugin.py",
        "install-agents.sh",
        "install-agents.ps1",
        "bootstrap.sh",
    }


def _load_candidate_authority(
    path: Path, *, schema: str, digest_field: str,
) -> dict[str, Any] | None:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != schema:
        return None
    supplied = value.get(digest_field)
    unsigned = dict(value)
    unsigned.pop(digest_field, None)
    expected = hashlib.sha256(
        json.dumps(
            unsigned, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return value if supplied == expected else None


def _candidate_git_output(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def codex_candidate_promotion_candidate(
    command: str, *, cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Seal exactly one verified candidate promotion as an install effect."""
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    sealed_python = len(tokens) == 10 and tokens[1] == SEALED_PYTHON_FLAG
    script_index = 2 if sealed_python else 1
    argument_index = script_index + 1
    if (
        len(tokens) != (10 if sealed_python else 9)
        or tokens[argument_index] != "--candidate-home"
        or tokens[argument_index + 2:argument_index + 4] != ["--json", "promote"]
        or tokens[argument_index + 5] != "--kb-home"
        or re.fullmatch(
            r"[0-9A-Za-z][0-9A-Za-z._-]{0,80}",
            tokens[argument_index + 4],
        ) is None
    ):
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    interpreter = resolved_executable(tokens[0], cwd=working_directory)
    if interpreter is None or not re.fullmatch(
        r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", interpreter.name.lower(),
    ):
        return None
    script_value = Path(tokens[script_index]).expanduser()
    script = (
        script_value if script_value.is_absolute() else working_directory / script_value
    ).resolve()
    if script.name != "candidate_codex_plugin.py" or not script.is_file():
        return None
    workspace = script.parents[2]
    if script != workspace / "scripts/release/candidate_codex_plugin.py":
        return None
    candidate_home = Path(tokens[argument_index + 1]).expanduser()
    if not candidate_home.is_absolute():
        return None
    try:
        candidate_home = candidate_home.resolve(strict=True)
        slot = candidate_home / tokens[argument_index + 4]
        if slot.is_symlink() or slot.resolve(strict=True).parent != candidate_home:
            return None
    except OSError:
        return None
    candidate_id = tokens[argument_index + 4]
    state = _load_candidate_authority(
        slot / "state.json", schema="sulde-codex-candidate-state-v1",
        digest_field="state_sha256",
    )
    receipt = _load_candidate_authority(
        slot / "verification-receipt.json",
        schema="sulde-codex-candidate-verification-v1",
        digest_field="receipt_sha256",
    )
    if (
        state is None or receipt is None
        or state.get("status") not in {
            "verified", "promoting", "promoted", "promotion_failed",
        }
        or receipt.get("status") != "verified"
        or state.get("receipt_sha256") != receipt.get("receipt_sha256")
        or state.get("candidate_id") != candidate_id
        or receipt.get("candidate_id") != candidate_id
    ):
        return None
    python_identity, source = receipt.get("python"), receipt.get("source")
    artifact, codex = receipt.get("artifact"), receipt.get("codex")
    if not all(
        isinstance(value, dict)
        for value in (python_identity, source, artifact, codex)
    ):
        return None
    profile_id = (
        "codex-plugin-install-v2" if sealed_python else "codex-plugin-install-v1"
    )
    try:
        binding = (
            _codex_plugin_install_v2_binding(workspace, interpreter=interpreter)
            if sealed_python
            else _codex_plugin_install_binding(workspace, interpreter=interpreter)
        )
    except IntentGuardianError:
        return None
    if (
        python_identity.get("executable") != str(interpreter)
        or python_identity.get("executable_sha256") != _sha256_path(interpreter)
        or source.get("commit") != _candidate_git_output(workspace, "rev-parse", "HEAD")
        or source.get("tree") != _candidate_git_output(
            workspace, "rev-parse", "HEAD^{tree}",
        )
        or artifact.get("plugin_version") != binding["plugin_version"]
        or codex.get("executable") != binding["codex_path"]
        or Path(tokens[argument_index + 6]).expanduser().resolve()
        != Path(binding["kb_home"])
    ):
        return None
    artifact_root = Path(str(artifact.get("path") or "")).expanduser()
    try:
        artifact_root = artifact_root.resolve(strict=True)
        artifact_root.relative_to(slot)
        generation = json.loads(
            (artifact_root / "plugins/sulde/.codex-plugin/generation.json").read_text(
                encoding="utf-8",
            )
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    if (
        not isinstance(generation, dict)
        or generation.get("generation") != artifact.get("generation")
        or generation.get("plugin_version") != binding["plugin_version"]
    ):
        return None
    expected_digest = hashlib.sha256(
        json.dumps(
            {
                "profile_id": profile_id,
                "target": CONTINUATION_PROFILES[profile_id]["target"],
                "binding": binding,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "profile_id": profile_id,
        "effect": "external_write",
        "capability": "tool:Bash",
        "target": CONTINUATION_PROFILES[profile_id]["target"],
        "verification_kind": "content",
        "verification_sha256": expected_digest,
        "binding": binding,
        "dispatch_adapter": "candidate-promotion-v1",
        "candidate": {
            "candidate_home": str(candidate_home),
            "candidate_id": candidate_id,
            "state_sha256": str(state["state_sha256"]),
            "receipt_sha256": str(receipt["receipt_sha256"]),
            "script_path": str(script),
            "script_sha256": _sha256_path(script),
            "artifact_generation": str(artifact["generation"]),
        },
    }


def codex_plugin_read_only_maintenance_command(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> bool:
    """Recognize exact diagnostics without authorizing their writer shape."""
    if has_unquoted_shell_control(command):
        return False
    try:
        tokens = split_command_template(command)
    except ValueError:
        return False
    if len(tokens) < 2:
        return False
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    # Exact help argv for repository-owned shell entrypoints. The filename
    # alone is not authority, and extra writer arguments never match.
    shell = Path(tokens[0]).name.lower()
    offset = 1 if shell in {"bash", "sh"} else 0
    if len(tokens) == offset + 2 and tokens[-1] in {"--help", "-h"}:
        candidate = Path(tokens[offset]).expanduser()
        candidate = candidate if candidate.is_absolute() else working_directory / candidate
        try:
            root = workspace_root(working_directory).resolve()
            if not candidate.is_symlink() and candidate.resolve(strict=True) in {
                (root / "scripts/kb/bootstrap.sh").resolve(),
                (root / "scripts/kb/install-agents.sh").resolve(),
            }:
                return True
        except (OSError, IntentGuardianError):
            pass
    if len(tokens) < 3:
        return False
    interpreter = resolved_executable(tokens[0], cwd=working_directory)
    if interpreter is None or not re.fullmatch(
        r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?",
        interpreter.name.lower(),
    ):
        return False
    raw_script = Path(tokens[1]).expanduser()
    if raw_script.is_symlink():
        return False
    try:
        script = (
            raw_script if raw_script.is_absolute() else working_directory / raw_script
        ).resolve(strict=True)
    except OSError:
        return False
    argv = [token.lower() for token in tokens[2:]]
    try:
        root = workspace_root(working_directory).resolve()
    except (IntentGuardianError, OSError):
        root = working_directory
    installer = (root / "scripts/release/install_codex_plugin.py").resolve()
    if script == installer and argv in (
        ["--help"],
        ["-h"],
        ["--dry-run"],
        ["--dry-run", "--json"],
        ["--json", "--dry-run"],
    ):
        return True
    configured_codex_home = os.environ.get("CODEX_HOME")
    codex_home = (
        Path(configured_codex_home).expanduser()
        if configured_codex_home
        else Path.home() / ".codex"
    ).resolve()
    helper = (
        codex_home
        / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
    ).resolve()
    return script == helper and argv in (["--help"], ["-h"])


def verification_digest(value: Any) -> str:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError):
        return ""
    return hashlib.sha256(rendered.encode("utf-8", errors="replace")).hexdigest()


def _candidate(profile_id: str, binding: dict[str, str]) -> dict[str, Any]:
    target = str(CONTINUATION_PROFILES[profile_id]["target"])
    digest = verification_digest(
        {"profile_id": profile_id, "target": target, "binding": binding}
    )
    return {
        "profile_id": profile_id,
        "effect": str(CONTINUATION_PROFILES[profile_id]["effect"]),
        "capability": "tool:Bash",
        "target": target,
        "verification_kind": "content",
        "verification_sha256": digest,
        "binding": binding,
    }


def codex_plugin_cachebuster_v2_candidate(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    sealed = sealed_python_invocation(command, cwd=cwd)
    if sealed is None:
        return None
    tokens = sealed["argv"]
    if len(tokens) != 4 or tokens[2] != "--cachebuster":
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    helper_value = Path(tokens[0]).expanduser()
    helper = (
        helper_value if helper_value.is_absolute() else working_directory / helper_value
    ).resolve()
    plugin_value = Path(tokens[1]).expanduser()
    plugin_root = (
        plugin_value if plugin_value.is_absolute() else working_directory / plugin_value
    ).resolve()
    if plugin_root.name != "sulde" or len(plugin_root.parents) < 4:
        return None
    workspace = plugin_root.parents[3]
    if plugin_root != (workspace / "integrations/codex/plugins/sulde").resolve():
        return None
    try:
        binding, _ = _codex_plugin_cachebuster_v2_binding(
            workspace,
            cachebuster=tokens[3],
            interpreter=sealed["interpreter"],
            helper=helper,
        )
    except IntentGuardianError:
        return None
    return _candidate("codex-plugin-cachebuster-v2", binding)


def codex_plugin_install_v2_candidate(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    sealed = sealed_python_invocation(command, cwd=cwd)
    if sealed is None:
        return None
    tokens = sealed["argv"]
    if len(tokens) < 2:
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    script_value = Path(tokens[0]).expanduser()
    script = (
        script_value if script_value.is_absolute() else working_directory / script_value
    ).resolve()
    if script.name != "install_codex_plugin.py" or not script.is_file():
        return None
    workspace = script.parents[2]
    if script != workspace / "scripts/release/install_codex_plugin.py":
        return None
    options: dict[str, str] = {}
    json_output = False
    index = 1
    valued = {"--artifact-root", "--kb-home", "--codex", "--platform"}
    while index < len(tokens):
        option = tokens[index]
        if option == "--json":
            if json_output:
                return None
            json_output = True
            index += 1
            continue
        if option not in valued or option in options or index + 1 >= len(tokens):
            return None
        options[option] = tokens[index + 1]
        index += 2
    if not json_output:
        return None
    try:
        binding = _codex_plugin_install_v2_binding(
            workspace,
            interpreter=sealed["interpreter"],
        )
    except IntentGuardianError:
        return None
    for option, binding_key in {
        "--artifact-root": "artifact_root",
        "--kb-home": "kb_home",
    }.items():
        supplied = options.get(option)
        if supplied is None:
            continue
        supplied_path = Path(supplied).expanduser()
        supplied_path = (
            supplied_path if supplied_path.is_absolute() else working_directory / supplied_path
        )
        if supplied_path.resolve() != Path(binding[binding_key]).resolve():
            return None
    supplied_codex = options.get("--codex")
    if supplied_codex is not None:
        codex_executable = resolved_executable(supplied_codex, cwd=working_directory)
        if codex_executable is None or codex_executable != Path(binding["codex_path"]):
            return None
    if options.get("--platform", binding["platform"]) != binding["platform"]:
        return None
    return _candidate("codex-plugin-install-v2", binding)


def _installed_candidate(
    profile_id: str,
    binding: dict[str, str],
    tokens: list[str],
    expected_tokens: list[str],
) -> dict[str, Any] | None:
    if tokens != expected_tokens:
        return None
    script = Path(binding["script_path"])
    try:
        if not script.is_file() or _sha256_path(script) != binding["script_sha256"]:
            return None
    except (IntentGuardianError, OSError):
        return None
    return _candidate(profile_id, binding)


def scheduler_reconcile_candidate(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
        binding = _scheduler_reconcile_binding(Path(cwd or os.getcwd()))
    except (ValueError, IntentGuardianError, OSError):
        return None
    return _installed_candidate(
        "sulde-scheduler-reconcile-v1",
        binding,
        tokens,
        [
            binding["script_path"],
            "--runtime-root",
            binding["runtime_root"],
            "--provider",
            "codex",
            "--accept-llm-data-egress",
        ],
    )


def launcher_refresh_candidate(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
        binding = _launcher_refresh_binding(Path(cwd or os.getcwd()))
    except (ValueError, IntentGuardianError, OSError):
        return None
    return _installed_candidate(
        "sulde-launcher-refresh-v1",
        binding,
        tokens,
        [binding["script_path"], "--launchers-only", "--host", "codex"],
    )


def protected_json_object(path: Path) -> dict[str, Any] | None:
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            return None
        if os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def labels_digest(labels: Any) -> tuple[str, str] | None:
    if (
        not isinstance(labels, list)
        or not labels
        or any(not isinstance(label, str) or not label for label in labels)
    ):
        return None
    normalized = sorted(labels)
    if len(normalized) != len(set(normalized)):
        return None
    digest = hashlib.sha256(
        json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return str(len(normalized)), digest


def portable_tree_sha256(root: Path) -> str:
    """Hash deployable files while excluding generated bytecode and metadata."""
    if not root.is_dir():
        return ""
    digest = hashlib.sha256()
    try:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc" or path.name == ".DS_Store":
                continue
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def scheduler_reconcile_verification(
    candidate: dict[str, Any],
    *,
    expected_digest: str,
) -> dict[str, Any] | None:
    binding = candidate.get("binding")
    if not isinstance(binding, dict) or expected_digest != candidate.get("verification_sha256"):
        return None
    kb_root = Path(str(binding.get("kb_home") or "")).expanduser().resolve()
    runtime_root = Path(str(binding.get("runtime_root") or "")).expanduser().resolve()
    deployment = protected_json_object(kb_root / "deployment-generation.json")
    owner = protected_json_object(kb_root / "runtime-owner.json")
    if deployment is None or owner is None:
        return None
    if any(
        deployment.get(key) != value or owner.get(key) != value
        for key, value in {"provider": "codex", "runtime_root": str(runtime_root)}.items()
    ):
        return None
    generation_state = (
        deployment.get("status"),
        deployment.get("operational_ready"),
        owner.get("installation_status"),
        owner.get("operational_ready"),
    )
    accepted_generation_states = {
        (
            "installed_live_unverified",
            False,
            "installed_degraded",
            False,
        ),
        (
            "generation_verified",
            True,
            "generation_verified",
            True,
        ),
    }
    if (
        deployment.get("schema") != "sulde-installed-deployment-generation-v1"
        or generation_state not in accepted_generation_states
        or owner.get("schema_version") != 2
        or owner.get("status") != "active"
        or owner.get("scheduler") != "launchd"
        or any(
            deployment.get(key) != owner.get(key)
            for key in ("generation", "runtime_tree_sha256", "managed_labels")
        )
    ):
        return None
    if labels_digest(owner.get("managed_labels")) != (
        str(binding.get("expected_label_count") or ""),
        str(binding.get("expected_labels_sha256") or ""),
    ):
        return None
    runner_value = str(deployment.get("scheduler_runner") or "")
    runner = Path(runner_value).expanduser().resolve() if runner_value else None
    runner_sha256 = str(deployment.get("scheduler_runner_sha256") or "")
    if (
        runner is None
        or not runner.is_file()
        or owner.get("scheduler_runner_sha256") != runner_sha256
        or _sha256_path(runner) != runner_sha256
    ):
        return None
    launchctl = shutil.which("launchctl")
    if not launchctl:
        return None
    try:
        observed = subprocess.run(
            [str(Path(launchctl).resolve()), "list"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    loaded = sorted(
        fields[-1]
        for line in observed.stdout.splitlines()
        if (fields := line.split()) and fields[-1].startswith("com.sulde.")
    )
    if observed.returncode != 0 or loaded != sorted(owner["managed_labels"]):
        return None
    return {
        "capability": "tool:sulde_scheduler_reconcile_verify",
        "evidence": {"content": [expected_digest]},
        "source": "local_scheduler_owner_and_launchctl_read",
    }


def launcher_refresh_verification(
    candidate: dict[str, Any],
    *,
    expected_digest: str,
) -> dict[str, Any] | None:
    binding = candidate.get("binding")
    if not isinstance(binding, dict) or expected_digest != candidate.get("verification_sha256"):
        return None
    kb_root = Path(str(binding.get("kb_home") or "")).expanduser().resolve()
    runtime_root = Path(str(binding.get("runtime_root") or "")).expanduser().resolve()
    if not installed_launchers_match(verify_launcher_installation(
        kb_root,
        expected_source_root=runtime_root,
    )):
        return None
    deployment = protected_json_object(kb_root / "deployment-generation.json")
    owner = protected_json_object(kb_root / "runtime-owner.json")
    manifest = protected_json_object(launcher_home(kb_root) / "bin/.sulde-launchers.json")
    if deployment is None or owner is None or manifest is None:
        return None
    if verify_scheduler_seal(kb_root, runtime_root, manifest)["status"] != "verified":
        return None
    if (
        deployment.get("runtime_root") != str(runtime_root)
        or owner.get("runtime_root") != str(runtime_root)
        or deployment.get("generation") != owner.get("generation")
        or manifest.get("generation") != owner.get("generation")
        or deployment.get("runtime_tree_sha256") != owner.get("runtime_tree_sha256")
        or manifest.get("runtime_tree_sha256") != owner.get("runtime_tree_sha256")
        or deployment.get("scheduler_runner") != manifest.get("scheduler_runner")
        or deployment.get("scheduler_runner_sha256")
        != owner.get("scheduler_runner_sha256")
        or manifest.get("scheduler_runner_sha256")
        != owner.get("scheduler_runner_sha256")
        or labels_digest(owner.get("managed_labels"))
        != (
            str(binding.get("expected_label_count") or ""),
            str(binding.get("expected_labels_sha256") or ""),
        )
    ):
        return None
    return {
        "capability": "tool:sulde_launcher_refresh_verify",
        "evidence": {"content": [expected_digest]},
        "source": "local_launcher_scheduler_seal_read",
    }


def unsealed_codex_plugin_cachebuster_invocation(
    command: str,
    *,
    cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Recognize the official helper's unsealed default-token shape.

    This recognizer only produces a non-pausing invocation violation.  It
    never grants authority, and it refuses composition, alternate helpers,
    non-canonical plugin roots, and missing manifests.
    """
    if has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if len(tokens) != 3:
        return None
    working_directory = Path(cwd or os.getcwd()).expanduser().resolve()
    interpreter = resolved_executable(tokens[0], cwd=working_directory)
    if interpreter is None or not re.fullmatch(
        r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?",
        interpreter.name.lower(),
    ):
        return None
    configured_codex_home = os.environ.get("CODEX_HOME")
    codex_home = (
        Path(configured_codex_home).expanduser()
        if configured_codex_home
        else Path.home() / ".codex"
    ).resolve()
    expected_helper = (
        codex_home
        / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
    ).resolve()
    helper_value = Path(tokens[1]).expanduser()
    helper = (
        helper_value if helper_value.is_absolute() else working_directory / helper_value
    ).resolve()
    if helper != expected_helper or not helper.is_file():
        return None
    plugin_value = Path(tokens[2]).expanduser()
    plugin_root = (
        plugin_value if plugin_value.is_absolute() else working_directory / plugin_value
    ).resolve()
    if plugin_root.name != "sulde" or len(plugin_root.parents) < 4:
        return None
    workspace = plugin_root.parents[3]
    if plugin_root != (workspace / "integrations/codex/plugins/sulde").resolve():
        return None
    manifest = (plugin_root / ".codex-plugin/plugin.json").resolve()
    if not manifest.is_file() or not manifest.is_relative_to(workspace):
        return None
    return {
        "effect": "local_write",
        "reason": (
            "官方 Codex 插件 cachebuster 必须显式提供 proposal-bound token；"
            "省略 token 的时间派生调用已拒绝但不会暂停任务"
        ),
        "target": "integrations/codex/plugins/sulde/.codex-plugin/plugin.json",
        "write_targets": [str(manifest)],
    }


_LITERAL_RM_SHORT_FLAGS = frozenset("rf")
_LITERAL_RM_LONG_FLAGS = frozenset({"--force", "--recursive"})
_LITERAL_RM_PATH_META = frozenset("*?[]$`{}()")


def literal_shell_delete_operations(
    command: str,
    *,
    cwd: str | Path | None,
    require_existing: bool,
) -> list[dict[str, str]] | None:
    """Prove one uncomposed ``rm`` invocation has exact local targets."""
    if not command or has_unquoted_shell_control(command):
        return None
    try:
        tokens = split_command_template(command)
    except ValueError:
        return None
    if not tokens or Path(tokens[0]).name.lower() != "rm":
        return None

    raw_targets: list[str] = []
    options_open = True
    for token in tokens[1:]:
        if options_open and token == "--":
            options_open = False
            continue
        if options_open and token.startswith("-") and token != "-":
            if token.startswith("--"):
                if token not in _LITERAL_RM_LONG_FLAGS:
                    return None
            elif not token[1:] or not set(token[1:]).issubset(
                _LITERAL_RM_SHORT_FLAGS
            ):
                return None
            continue
        options_open = False
        raw_targets.append(token)
    if not raw_targets:
        return None

    try:
        base = Path(cwd or os.getcwd()).expanduser().resolve(strict=True)
        if not base.is_dir():
            return None
    except (OSError, ValueError):
        return None

    resolved_targets: list[Path] = []
    operations: list[dict[str, str]] = []
    for raw_target in raw_targets:
        if (
            not raw_target
            or raw_target in {".", "..", "/"}
            or raw_target.startswith("~")
            or any(character in raw_target for character in _LITERAL_RM_PATH_META)
            or any(character in raw_target for character in ("\n", "\r", "\x00"))
            or ".." in Path(raw_target).parts
        ):
            return None
        candidate = Path(raw_target).expanduser()
        lexical = Path(
            os.path.abspath(candidate if candidate.is_absolute() else base / candidate)
        )
        anchor = Path(lexical.anchor)
        if lexical == anchor:
            return None
        try:
            if not path_components_are_not_symlinks(anchor, lexical.parent):
                return None
            metadata = lexical.lstat()
        except FileNotFoundError:
            if require_existing:
                return None
            metadata = None
        except (OSError, ValueError):
            return None
        if metadata is not None and (
            stat.S_ISLNK(metadata.st_mode)
            or not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode))
        ):
            return None
        if metadata is not None and not path_components_are_not_symlinks(
            anchor,
            lexical,
        ):
            return None
        try:
            resolved = lexical.resolve(strict=metadata is not None)
        except (OSError, ValueError):
            return None
        if resolved == anchor or resolved in resolved_targets:
            return None
        if any(
            resolved in existing.parents or existing in resolved.parents
            for existing in resolved_targets
        ):
            return None
        resolved_targets.append(resolved)
        operations.append({"operation": "delete", "path": str(resolved)})
    return operations or None


def literal_shell_delete_is_high_risk(
    command: str,
    operations: list[dict[str, str]],
) -> bool:
    """Separate bounded file cleanup from genuinely broad local destruction.

    Exact non-recursive regular-file deletion remains a host/Agent operation.
    Recursive deletion, directory deletion, large target sets and the formal
    pre-execution canary retain Guardian's human decision boundary.
    """
    try:
        tokens = split_command_template(command)
    except ValueError:
        return True
    recursive = any(
        token == "--recursive"
        or (
            token.startswith("-")
            and not token.startswith("--")
            and "r" in token[1:]
        )
        for token in tokens[1:]
    )
    if recursive or len(operations) > 16:
        return True
    for operation in operations:
        path = Path(str(operation.get("path") or ""))
        if path.name.startswith("sulde-pre-execution-canary-"):
            return True
        try:
            if path.is_dir():
                return True
        except OSError:
            return True
    return False


def local_target_label(targets: Iterable[str]) -> str:
    values = [str(value) for value in targets if str(value)]
    if len(values) == 1:
        return values[0]
    if not values:
        return ""
    digest = hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"[local-target-set:{digest}]"

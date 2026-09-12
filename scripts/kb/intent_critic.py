"""Read-only semantic checkpoint for one observable intent-guardian event."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import runpy
import stat
import subprocess
import contextlib
from types import SimpleNamespace
from typing import Any
import unicodedata

from intent_guardian_errors import IntentGuardianError
from runtime_provider import ProviderError, cognitive_command, select_provider
from sedimentation_schema import guidance_excerpt


_command_template = runpy.run_path(str(Path(__file__).with_name("command_template.py")))
split_command_template = _command_template["split_command_template"]
kb_cli = SimpleNamespace(
    **runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "hooks" / "lib" / "kb_cli.py")
    )
)


MAX_EVIDENCE_CHARS = 40_000
MAX_TARGET_BYTES = 1_000_000
MAX_EVENT_TARGETS = 64
MAX_TARGET_CHARS = 2_000
VERDICTS = {"aligned", "drift", "inconclusive"}
KB_SCORE_MIN = 0.55
KB_MAX_GUIDANCE = 2
TASK_SCOPE_SCHEMA = "sulde-intent-critic-task-scope-v1"


@dataclass(frozen=True)
class CriticResult:
    verdict: str
    confidence: float
    summary: str
    violated_constraints: tuple[str, ...]
    evidence: tuple[str, ...]
    next_action: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "sulde-intent-critic-v1",
            "verdict": self.verdict,
            "confidence": self.confidence,
            "summary": self.summary,
            "violated_constraints": list(self.violated_constraints),
            "evidence": list(self.evidence),
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class TaskCriticScope:
    task_id: str
    baseline: str
    run_id: str
    owned_paths: tuple[str, ...]
    baseline_snapshot: dict[str, str]
    evidence_floor_sequence: int
    registered_evidence: tuple[dict[str, Any], ...]

    def as_projection(self) -> dict[str, Any]:
        """Return the exact coordinator projection consumed by the critic."""

        return {
            "schema": TASK_SCOPE_SCHEMA,
            "task_id": self.task_id,
            "base_commit": self.baseline,
            "verification_run_id": self.run_id,
            "owned_paths": list(self.owned_paths),
            "baseline_snapshot": dict(self.baseline_snapshot),
            "evidence_floor_sequence": self.evidence_floor_sequence,
            "registered_evidence": [dict(row) for row in self.registered_evidence],
        }


def _secret_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    path = Path(__file__).with_name("mem-secret-scan.py")
    spec = importlib.util.spec_from_file_location("sulde_guardian_secret_scan", path)
    if spec is None or spec.loader is None:
        raise IntentGuardianError("secret scanner cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(module)
    return tuple(module.PATTERNS)


def secret_matches(text: str) -> list[str]:
    return [name for name, pattern in _secret_patterns() if pattern.search(text)]


def _is_exact_string(value: Any) -> bool:
    """Return true only for a native string, never for a coercible substitute."""

    return type(value) is str


def _is_plain_string_dict(value: Any) -> bool:
    """Validate a plain object and its keys before any keyed lookup or iteration."""

    if type(value) is not dict:
        return False
    return all(_is_exact_string(key) for key in value.keys())


def _raw_event_targets(event: dict[str, Any]) -> tuple[list[str], str]:
    """Return the complete, unmodified target inventory or a binding error."""

    if not _is_plain_string_dict(event):
        return [], "critic checkpoint event must be a plain object"
    if "write_targets" in event:
        raw = event.get("write_targets")
        if type(raw) is not list:
            return [], "target inventory must be a list"
        targets: Any = raw[:]
    else:
        target = event.get("target")
        if (
            not _is_exact_string(target)
            or not target
            or target.startswith("[")
        ):
            return [], "event has no explicit target inventory"
        targets = [target]
    if not targets:
        return [], "event has no explicit target inventory"
    if not all(_is_exact_string(item) for item in targets):
        return [], "target inventory entries must be strings"
    if any(not item or item != item.strip() for item in targets):
        return [], "target inventory entries must be exact nonempty strings"
    if any(len(item) > MAX_TARGET_CHARS for item in targets):
        return [], "target inventory entry exceeds the size bound"
    return targets, ""


def _target_inventory_fields(targets: list[str]) -> dict[str, Any]:
    binding = hashlib.sha256(
        json.dumps(targets, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "target": f"[local-target-set:{binding[:16]}]",
        "target_count": len(targets),
        "target_overflow": max(0, len(targets) - MAX_EVENT_TARGETS),
        "target_binding": binding,
    }


def _event_targets(event: dict[str, Any]) -> tuple[list[str], str]:
    """Validate the complete target inventory and its coordinator binding."""

    targets, error = _raw_event_targets(event)
    if error:
        return [], error
    expected = _target_inventory_fields(targets)
    for field, value in expected.items():
        observed = event.get(field)
        if type(observed) is not type(value) or observed != value:
            return [], f"target inventory {field} does not match the full input"
    if len(targets) > MAX_EVENT_TARGETS:
        return [], "target inventory exceeds the bounded target inventory"
    return targets, ""


def _canonical_owned_path(value: Any) -> str:
    if not _is_exact_string(value):
        return ""
    path = value
    parts = path.split("/")
    recursive = path.endswith("/**")
    literal = path[:-3] if recursive else path
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or any(part in {"", ".", ".."} for part in parts)
        or any(ord(character) < 32 for character in path)
        or any(token in literal for token in ("*", "?", "[", "]"))
        or (not recursive and any(token in path for token in ("*", "?", "[", "]")))
    ):
        return ""
    return path


def _aliased_value(
    raw: dict[str, Any], primary: str, fallback: str
) -> Any:
    """Read one authority field without truthiness-based alias fallback."""

    return raw[primary] if primary in raw else raw.get(fallback)


def _identity_string(
    value: Any, label: str, *, max_chars: int | None = None
) -> tuple[str, str]:
    """Accept only an exact, nonempty string identity; never manufacture one."""

    if type(value) is not str or not value or value != value.strip():
        return "", f"critic {label} must be an exact nonempty string"
    if max_chars is not None and len(value) > max_chars:
        return "", f"critic {label} exceeds the identity size bound"
    return value, ""


def _registered_evidence_authority_error(row: dict[str, Any]) -> str:
    """Validate evidence selectors without coercion or truthiness callbacks."""

    for field in ("kind", "verdict"):
        if field in row and not _is_exact_string(row[field]):
            return f"critic registered evidence {field} must be an exact string"
    scope = row.get("scope")
    if scope is not None and (
        not _is_exact_string(scope) or scope != "task"
    ):
        return "critic registered evidence scope must be the exact task enum"
    for field in ("superseded_by", "binding_error"):
        value = row.get(field)
        if value is not None and not _is_exact_string(value):
            return f"critic registered evidence {field} must be an exact string"
    for field in ("invalid", "valid"):
        if field in row and type(row[field]) is not bool:
            return f"critic registered evidence {field} must be an exact boolean"
    if (
        "recorded_sequence" in row
        and type(row["recorded_sequence"]) is not int
    ):
        return "critic registered evidence sequence must be an exact integer"
    return ""


def _ownership_key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _ownership_match(
    relative: str, owned_paths: tuple[str, ...]
) -> tuple[bool, str]:
    """Match literal authorization; normalization can only reject ambiguity."""

    for pattern in owned_paths:
        recursive = pattern.endswith("/**")
        literal = pattern[:-3] if recursive else pattern
        if relative == literal or (recursive and relative.startswith(f"{literal}/")):
            return True, ""
    candidate_key = _ownership_key(relative)
    for pattern in owned_paths:
        recursive = pattern.endswith("/**")
        literal = pattern[:-3] if recursive else pattern
        literal_key = _ownership_key(literal)
        if candidate_key == literal_key or (
            recursive and candidate_key.startswith(f"{literal_key}/")
        ):
            return False, "target ownership is ambiguous after Unicode/case normalization"
    return False, ""


def _path_is_owned(relative: str, owned_paths: tuple[str, ...]) -> bool:
    """Compatibility predicate with exact, case-sensitive authorization semantics."""

    owned, _error = _ownership_match(relative, owned_paths)
    return owned


def _scope_from_projection(
    raw: Any,
) -> tuple[TaskCriticScope | None, str]:
    if not _is_plain_string_dict(raw):
        return None, "critic task scope must be an object"
    schema = raw.get("schema")
    if not _is_exact_string(schema) or schema != TASK_SCOPE_SCHEMA:
        return None, "unsupported critic task scope schema"
    task_id, identity_error = _identity_string(
        raw.get("task_id"), "task scope task_id", max_chars=200
    )
    if identity_error:
        return None, identity_error
    baseline, identity_error = _identity_string(
        _aliased_value(raw, "base_commit", "baseline"),
        "task scope baseline",
    )
    if identity_error:
        return None, identity_error
    run_id, identity_error = _identity_string(
        _aliased_value(raw, "verification_run_id", "run_id"),
        "task scope run_id",
        max_chars=200,
    )
    if identity_error:
        return None, identity_error
    raw_owned = raw.get("owned_paths")
    if type(raw_owned) is not list or not raw_owned:
        return None, "critic task scope has no owned paths"
    if not all(
        _is_exact_string(item) and item and item == item.strip()
        for item in raw_owned
    ):
        return None, "critic owned path entries must be exact nonempty strings"
    owned_paths = tuple(_canonical_owned_path(item) for item in raw_owned)
    if any(not item for item in owned_paths):
        return None, "critic task scope contains a noncanonical owned path"
    if len(set(owned_paths)) != len(owned_paths):
        return None, "critic task scope contains duplicate owned paths"
    normalized_owned = [_ownership_key(item) for item in owned_paths]
    if len(set(normalized_owned)) != len(normalized_owned):
        return None, "critic task scope contains ambiguous normalized owned paths"
    raw_snapshot = raw.get("baseline_snapshot")
    if not _is_plain_string_dict(raw_snapshot):
        return None, "critic task scope has no frozen baseline snapshot"
    baseline_snapshot: dict[str, str] = {}
    for path, digest in raw_snapshot.items():
        if (
            not _is_exact_string(path)
            or not path
            or path != path.strip()
            or not _is_exact_string(digest)
        ):
            return None, "critic baseline snapshot contains an invalid entry"
        canonical = _canonical_owned_path(path)
        if not canonical or canonical.endswith("/**"):
            return None, "critic baseline snapshot contains an invalid entry"
        baseline_snapshot[path] = digest
    evidence_floor = raw.get("evidence_floor_sequence")
    if (
        type(evidence_floor) is not int
        or evidence_floor < 0
    ):
        return None, "critic evidence floor must be an explicit nonnegative integer"
    raw_evidence = raw.get("registered_evidence", [])
    if type(raw_evidence) is not list or not all(
        _is_plain_string_dict(row) for row in raw_evidence
    ):
        return None, "critic registered evidence must be an array of objects"
    for row in raw_evidence:
        evidence_id, evidence_id_error = _identity_string(
            row.get("evidence_id"), "registered evidence_id", max_chars=200
        )
        row_task, row_task_error = _identity_string(
            row.get("task_id"), "registered evidence task_id", max_chars=200
        )
        row_baseline, row_baseline_error = _identity_string(
            _aliased_value(row, "baseline", "base_commit"),
            "registered evidence baseline",
        )
        row_run, row_run_error = _identity_string(
            _aliased_value(row, "run_id", "verification_run_id"),
            "registered evidence run_id",
            max_chars=200,
        )
        if (
            evidence_id_error
            or row_task_error
            or row_baseline_error
            or row_run_error
            or not evidence_id
            or not row_task
            or not row_baseline
            or not row_run
        ):
            return None, "critic registered evidence identities must be exact nonempty strings"
        authority_error = _registered_evidence_authority_error(row)
        if authority_error:
            return None, authority_error
    registered_evidence = tuple(dict(row) for row in raw_evidence)
    return (
        TaskCriticScope(
            task_id=task_id,
            baseline=baseline,
            run_id=run_id,
            owned_paths=owned_paths,
            baseline_snapshot=baseline_snapshot,
            evidence_floor_sequence=evidence_floor,
            registered_evidence=registered_evidence,
        ),
        "",
    )


def _task_critic_scope(
    contract: dict[str, Any],
) -> tuple[TaskCriticScope | None, str]:
    """Read the coordinator-bound task scope or fail closed."""

    if not _is_plain_string_dict(contract):
        return None, "critic contract must be a plain object"
    critic = contract.get("critic")
    if not _is_plain_string_dict(critic):
        return None, "critic task scope is not registered"
    raw = critic.get("task_scope")
    if raw is None:
        return None, "critic task scope is not registered"
    return _scope_from_projection(raw)


def build_task_critic_scope(
    task_projection: dict[str, Any],
    valid_evidence: list[dict[str, Any]] | tuple[dict[str, Any], ...] | dict[str, dict[str, Any]],
    baseline_snapshot: dict[str, str],
) -> TaskCriticScope:
    """Build T06's scope from one verified Guardian Program task projection.

    ``valid_evidence`` is the already verified/effective evidence collection, not
    the Guardian Program's global ``evidence_errors`` collection.
    """

    if not _is_plain_string_dict(task_projection):
        raise IntentGuardianError("critic task projection must be an object")
    if _is_plain_string_dict(valid_evidence):
        rows: Any = list(valid_evidence.values())
    elif type(valid_evidence) in (list, tuple):
        rows = list(valid_evidence)
    else:
        rows = None
    if rows is None or not all(_is_plain_string_dict(row) for row in rows):
        raise IntentGuardianError("valid critic evidence must be a collection of objects")
    floor = task_projection.get("evidence_floor_sequence")
    raw = {
        "schema": TASK_SCOPE_SCHEMA,
        "task_id": task_projection.get("task_id"),
        "base_commit": _aliased_value(
            task_projection, "base_commit", "baseline"
        ),
        "verification_run_id": _aliased_value(
            task_projection, "verification_run_id", "run_id"
        ),
        "owned_paths": task_projection.get("owned_paths"),
        "baseline_snapshot": baseline_snapshot,
        "evidence_floor_sequence": floor,
        "registered_evidence": rows,
    }
    scope, error = _scope_from_projection(raw)
    if error or scope is None:
        raise IntentGuardianError(error or "critic task scope is unavailable")
    selected: list[dict[str, Any]] = []
    evidence_ids: set[str] = set()
    for row in rows:
        evidence_id, evidence_id_error = _identity_string(
            row.get("evidence_id"), "evidence_id", max_chars=200
        )
        row_task_id, row_task_error = _identity_string(
            row.get("task_id"), "evidence task_id", max_chars=200
        )
        row_baseline, row_baseline_error = _identity_string(
            _aliased_value(row, "baseline", "base_commit"),
            "evidence baseline",
        )
        row_run_id, row_run_error = _identity_string(
            _aliased_value(row, "run_id", "verification_run_id"),
            "evidence run_id",
            max_chars=200,
        )
        sequence = row.get("recorded_sequence")
        row_scope = row.get("scope")
        superseded_by = row.get("superseded_by")
        binding_error = row.get("binding_error")
        invalid = row.get("invalid")
        valid = row.get("valid")
        if (
            evidence_id_error
            or row_task_error
            or row_baseline_error
            or row_run_error
            or evidence_id in evidence_ids
            or type(sequence) is not int
            or sequence <= scope.evidence_floor_sequence
            or row_task_id != scope.task_id
            or row_baseline != scope.baseline
            or row_run_id != scope.run_id
            or row_scope not in (None, "task")
            or superseded_by not in (None, "")
            or binding_error not in (None, "")
            or invalid is True
            or valid is False
        ):
            continue
        evidence_ids.add(evidence_id)
        selected.append(dict(row))
    raw["registered_evidence"] = selected
    scope, error = _scope_from_projection(raw)
    if error or scope is None:
        raise IntentGuardianError(error or "critic task scope is unavailable")
    return scope


def bind_task_critic_checkpoint_event(
    event: dict[str, Any], scope: TaskCriticScope
) -> dict[str, Any]:
    """Decorate a checkpoint event with exact task/run/baseline/evidence binding."""

    if not _is_plain_string_dict(event):
        raise IntentGuardianError("critic checkpoint event must be an object")
    if type(scope) is not TaskCriticScope:
        raise IntentGuardianError("critic checkpoint scope must be a TaskCriticScope")
    if (
        type(scope.owned_paths) is not tuple
        or type(scope.registered_evidence) is not tuple
        or not _is_plain_string_dict(scope.baseline_snapshot)
        or not all(
            _is_plain_string_dict(row) for row in scope.registered_evidence
        )
    ):
        raise IntentGuardianError("critic checkpoint scope has malformed containers")
    validated_scope, scope_error = _scope_from_projection(
        {
            "schema": TASK_SCOPE_SCHEMA,
            "task_id": scope.task_id,
            "base_commit": scope.baseline,
            "verification_run_id": scope.run_id,
            "owned_paths": list(scope.owned_paths),
            "baseline_snapshot": dict(scope.baseline_snapshot),
            "evidence_floor_sequence": scope.evidence_floor_sequence,
            "registered_evidence": [dict(row) for row in scope.registered_evidence],
        }
    )
    if scope_error or validated_scope is None:
        raise IntentGuardianError(scope_error or "critic task scope is unavailable")
    targets, target_error = _raw_event_targets(event)
    if target_error:
        raise IntentGuardianError(target_error)
    evidence_ids = [
        row["evidence_id"]
        for row in validated_scope.registered_evidence
    ]
    return {
        **event,
        "write_targets": targets,
        **_target_inventory_fields(targets),
        "task_id": validated_scope.task_id,
        "baseline": validated_scope.baseline,
        "run_id": validated_scope.run_id,
        "registered_evidence_ids": evidence_ids,
    }


def _run_git(
    root: Path,
    arguments: list[str],
    *,
    binary: bool = False,
) -> subprocess.CompletedProcess[Any]:
    environment = os.environ.copy()
    environment["GIT_LITERAL_PATHSPECS"] = "1"
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=environment,
        capture_output=True,
        text=not binary,
        encoding="utf-8" if not binary else None,
        errors="replace" if not binary else None,
        check=False,
        timeout=10,
    )


def _baseline_file_bytes(
    root: Path, baseline: str, relative: str
) -> tuple[str | None, bytes | None, str]:
    """Return a raw baseline blob and its agent-runtime fingerprint."""

    try:
        tree = _run_git(
            root, ["ls-tree", "-z", baseline, "--", relative], binary=True
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, None, f"task baseline lookup failed: {type(error).__name__}"
    if tree.returncode != 0:
        return None, None, "task baseline lookup failed"
    record = tree.stdout.rstrip(b"\0")
    if not record:
        return None, None, ""
    metadata, separator, observed_path = record.partition(b"\t")
    fields = metadata.split()
    if not separator or observed_path != os.fsencode(relative) or len(fields) != 3:
        return None, None, "task baseline returned an ambiguous path"
    mode, kind, _object_id = fields
    if kind != b"blob" or mode not in {b"100644", b"100755"}:
        return None, None, "task baseline target is not a regular file"
    try:
        size = _run_git(root, ["cat-file", "-s", _object_id.decode("ascii")])
        if size.returncode != 0 or not re.fullmatch(r"[0-9]+", size.stdout.strip()):
            return None, None, "task baseline size lookup failed"
        if int(size.stdout.strip()) > MAX_TARGET_BYTES:
            return None, None, "task baseline exceeds the raw-byte size bound"
        blob = _run_git(
            root, ["cat-file", "blob", _object_id.decode("ascii")], binary=True
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return None, None, f"task baseline read failed: {type(error).__name__}"
    if blob.returncode != 0:
        return None, None, "task baseline read failed"
    permissions = int(mode, 8) & 0o7777
    return (
        f"{permissions:o}:{hashlib.sha256(blob.stdout).hexdigest()}",
        blob.stdout,
        "",
    )


def _validate_scope_baseline(
    root: Path, scope: TaskCriticScope
) -> tuple[str, str]:
    try:
        object_format = _run_git(root, ["rev-parse", "--show-object-format"])
        if object_format.returncode != 0:
            return "", "critic task baseline object format lookup failed"
        format_name = object_format.stdout.strip()
        oid_length = {"sha1": 40, "sha256": 64}.get(format_name)
        if oid_length is None or not re.fullmatch(
            rf"[0-9a-f]{{{oid_length}}}", scope.baseline
        ):
            return "", "critic task baseline must be a full lowercase commit OID"
        resolved = _run_git(
            root,
            ["rev-parse", "--verify", "--end-of-options", f"{scope.baseline}^{{commit}}"],
        )
        if resolved.returncode != 0:
            return "", "critic task baseline is not a commit"
        baseline = resolved.stdout.strip()
        if baseline != scope.baseline:
            return "", "critic task baseline resolution changed its exact OID"
        ancestry = _run_git(root, ["merge-base", "--is-ancestor", baseline, "HEAD"])
    except (OSError, subprocess.TimeoutExpired) as error:
        return "", f"critic task baseline check failed: {type(error).__name__}"
    if ancestry.returncode != 0:
        return "", "workspace HEAD drifted outside the frozen task baseline"
    return baseline, ""


def _scope_event_binding_error(
    scope: TaskCriticScope, event: dict[str, Any]
) -> str:
    bindings = (
        ("task_id", scope.task_id),
        ("run_id", scope.run_id),
        ("baseline", scope.baseline),
    )
    for name, expected in bindings:
        expected_identity, expected_error = _identity_string(
            expected,
            f"task scope {name}",
            max_chars=None if name == "baseline" else 200,
        )
        if expected_error:
            return expected_error
        observed, observed_error = _identity_string(
            event.get(name),
            f"event {name}",
            max_chars=None if name == "baseline" else 200,
        )
        if observed_error:
            return observed_error
        if observed != expected_identity:
            return f"critic event {name} does not match the current task scope"
    return ""


def _registered_evidence_text(
    scope: TaskCriticScope, event: dict[str, Any]
) -> tuple[str, str]:
    if "registered_evidence_ids" not in event:
        return "", "critic event must explicitly provide registered_evidence_ids"
    requested = event["registered_evidence_ids"]
    if type(requested) is not list or not all(
        _is_exact_string(item) and item for item in requested
    ):
        return "", "critic event registered_evidence_ids must be a list of strings"
    if len(set(requested)) != len(requested):
        return "", "critic event registered_evidence_ids contains duplicates"
    requested_ids = set(requested)
    selected: list[dict[str, Any]] = []
    allowed_fields = (
        "evidence_id",
        "kind",
        "verdict",
        "summary",
        "facts",
        "requirements",
        "findings",
        "acceptance",
        "commands",
        "artifacts",
    )
    for row in scope.registered_evidence:
        evidence_id, evidence_id_error = _identity_string(
            row.get("evidence_id"), "evidence_id", max_chars=200
        )
        row_task, row_task_error = _identity_string(
            row.get("task_id"), "evidence task_id", max_chars=200
        )
        row_run, row_run_error = _identity_string(
            _aliased_value(row, "run_id", "verification_run_id"),
            "evidence run_id",
            max_chars=200,
        )
        row_baseline, row_baseline_error = _identity_string(
            _aliased_value(row, "baseline", "base_commit"),
            "evidence baseline",
        )
        sequence = row.get("recorded_sequence")
        if type(sequence) is not int:
            continue
        row_scope = row.get("scope")
        superseded_by = row.get("superseded_by")
        binding_error = row.get("binding_error")
        invalid = row.get("invalid")
        valid = row.get("valid")
        if (
            evidence_id_error
            or row_task_error
            or row_run_error
            or row_baseline_error
            or row_task != scope.task_id
            or row_run != scope.run_id
            or row_baseline != scope.baseline
            or sequence <= scope.evidence_floor_sequence
            or row_scope not in (None, "task")
            or superseded_by not in (None, "")
            or binding_error not in (None, "")
            or invalid is True
            or valid is False
            or evidence_id not in requested_ids
        ):
            continue
        selected.append({name: row[name] for name in allowed_fields if name in row})
    if not selected:
        return "", ""
    text = json.dumps(selected, ensure_ascii=False, indent=2)
    if len(text) > MAX_EVIDENCE_CHARS:
        return "", "registered evidence exceeds the critic size bound"
    return text, ""


def _file_state(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _path_identity(info: os.stat_result) -> tuple[int, int]:
    return (info.st_dev, info.st_ino)


def _secure_open_capability_error() -> str:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    dir_fd = getattr(os, "supports_dir_fd", frozenset())
    follow_symlinks = getattr(os, "supports_follow_symlinks", frozenset())
    if (
        not isinstance(nofollow, int)
        or isinstance(nofollow, bool)
        or nofollow == 0
        or not isinstance(directory, int)
        or isinstance(directory, bool)
        or directory == 0
        or os.open not in dir_fd
        or os.stat not in dir_fd
        or os.stat not in follow_symlinks
    ):
        return "platform lacks the secure open capability required by the critic"
    return ""


def _target_relative(root: Path, target: str) -> tuple[str, str]:
    if not _is_exact_string(target):
        return "", "target path must be an exact nonempty string"
    raw = target
    if not raw or raw != raw.strip() or "\\" in raw or "\0" in raw:
        return "", "target path is not a canonical workspace path"
    path = Path(raw)
    raw_parts = raw.split("/")
    checked_parts = raw_parts[1:] if path.is_absolute() else raw_parts
    if any(part in {"", ".", ".."} for part in checked_parts):
        return "", "target path is not a canonical workspace path"
    try:
        relative_path = path.relative_to(root) if path.is_absolute() else path
    except ValueError:
        return "", "target escapes the contract workspace"
    relative = relative_path.as_posix()
    if not _canonical_owned_path(relative) or relative.endswith("/**"):
        return "", "target path is not a canonical workspace path"
    return relative, ""


def _read_stable_regular_bytes(root: Path, relative: str) -> tuple[bytes | None, str]:
    """Open beneath ``root`` without following links and verify a stable inode."""

    capability_error = _secure_open_capability_error()
    if capability_error:
        return None, capability_error
    nofollow = os.O_NOFOLLOW
    directory = os.O_DIRECTORY
    cloexec = getattr(os, "O_CLOEXEC", 0)
    descriptors: list[int] = []
    verification_descriptors: list[int] = []
    try:
        root_info = root.lstat()
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            return None, "contract workspace root must be a real directory"
        current_fd = os.open(root, os.O_RDONLY | directory | nofollow | cloexec)
        descriptors.append(current_fd)
        opened_root = os.fstat(current_fd)
        if not stat.S_ISDIR(opened_root.st_mode) or _path_identity(
            root_info
        ) != _path_identity(opened_root):
            return None, "contract workspace root changed while being opened"
        directory_identities = [_path_identity(opened_root)]
        parts = relative.split("/")
        for component in parts[:-1]:
            before = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode):
                return None, "critic target path contains a symbolic link"
            if not stat.S_ISDIR(before.st_mode):
                return None, "critic target path component is not a directory"
            next_fd = os.open(
                component,
                os.O_RDONLY | directory | nofollow | cloexec,
                dir_fd=current_fd,
            )
            opened = os.fstat(next_fd)
            if _file_state(before) != _file_state(opened):
                os.close(next_fd)
                return None, "critic target path changed while being opened"
            descriptors.append(next_fd)
            current_fd = next_fd
            directory_identities.append(_path_identity(opened))
        name = parts[-1]
        before = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode):
            return None, "critic target is a symbolic link"
        if not stat.S_ISREG(before.st_mode):
            return None, "critic target is not a regular file"
        if before.st_nlink != 1:
            return None, "critic target is a hardlink alias"
        file_fd = os.open(name, os.O_RDONLY | nofollow | cloexec, dir_fd=current_fd)
        descriptors.append(file_fd)
        opened = os.fstat(file_fd)
        before_state = _file_state(before)
        opened_state = _file_state(opened)
        if before_state != opened_state:
            return None, "critic target changed while being opened"
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            return None, "critic target is not a single-link regular file"
        if opened.st_size > MAX_TARGET_BYTES:
            return None, "critic target exceeds the raw-byte size bound"
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(65_536, MAX_TARGET_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_TARGET_BYTES:
                return None, "critic target exceeds the raw-byte size bound"
        after = os.fstat(file_fd)
        path_after = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
        after_state = _file_state(after)
        path_after_state = _file_state(path_after)
        if (
            opened_state != after_state
            or opened_state != path_after_state
            or stat.S_ISLNK(path_after.st_mode)
            or not stat.S_ISREG(path_after.st_mode)
            or path_after.st_nlink != 1
        ):
            return None, "critic target changed while being read"

        verification_fd = os.open(
            root, os.O_RDONLY | directory | nofollow | cloexec
        )
        verification_descriptors.append(verification_fd)
        verified_root = os.fstat(verification_fd)
        if (
            not stat.S_ISDIR(verified_root.st_mode)
            or _path_identity(verified_root) != directory_identities[0]
        ):
            return None, "critic target declared path changed while being read"
        for index, component in enumerate(parts[:-1], start=1):
            declared = os.stat(
                component, dir_fd=verification_fd, follow_symlinks=False
            )
            if stat.S_ISLNK(declared.st_mode) or not stat.S_ISDIR(declared.st_mode):
                return None, "critic target declared path changed while being read"
            next_fd = os.open(
                component,
                os.O_RDONLY | directory | nofollow | cloexec,
                dir_fd=verification_fd,
            )
            verification_descriptors.append(next_fd)
            verified = os.fstat(next_fd)
            if (
                not stat.S_ISDIR(verified.st_mode)
                or _path_identity(declared) != directory_identities[index]
                or _path_identity(verified) != directory_identities[index]
            ):
                return None, "critic target declared path changed while being read"
            verification_fd = next_fd
        declared_leaf = os.stat(
            name, dir_fd=verification_fd, follow_symlinks=False
        )
        if (
            stat.S_ISLNK(declared_leaf.st_mode)
            or not stat.S_ISREG(declared_leaf.st_mode)
            or declared_leaf.st_nlink != 1
            or _file_state(declared_leaf) != opened_state
        ):
            return None, "critic target declared path changed while being read"
        return b"".join(chunks), ""
    except (OSError, ValueError) as error:
        if isinstance(error, OSError) and error.errno in {
            getattr(os, "ELOOP", 40),
        }:
            return None, "critic target path contains a symbolic link"
        return None, f"critic target read failed: {type(error).__name__}"
    finally:
        for descriptor in reversed(verification_descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _decode_source(data: bytes, relative: str) -> tuple[str, str]:
    if len(data) > MAX_TARGET_BYTES:
        return "", f"critic target is too large for a bounded diff: {relative}"
    if b"\0" in data:
        return "", f"critic target is binary: {relative}"
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        return "", f"critic target is not valid UTF-8: {relative}"


def _raw_unified_diff(
    baseline: bytes | None, current: bytes, relative: str
) -> tuple[str, str]:
    before, error = _decode_source(baseline or b"", relative)
    if error:
        return "", error
    after, error = _decode_source(current, relative)
    if error:
        return "", error
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative}" if baseline is not None else "/dev/null",
            tofile=f"b/{relative}",
            n=0,
            lineterm="\n",
        )
    )
    if len(diff) > MAX_EVIDENCE_CHARS:
        return "", f"critic target diff exceeds the evidence bound: {relative}"
    return diff, ""


def _scoped_increment(
    contract: dict[str, Any],
    event: dict[str, Any],
    scope: TaskCriticScope,
    targets: list[str],
) -> tuple[str, str]:
    binding_error = _scope_event_binding_error(scope, event)
    if binding_error:
        return "", binding_error
    registered, registered_error = _registered_evidence_text(scope, event)
    if registered_error:
        return "", registered_error
    workspace_root = contract.get("workspace_root")
    if not _is_exact_string(workspace_root) or not workspace_root:
        return "", "contract workspace root is unavailable"
    try:
        root = Path(workspace_root).expanduser().absolute()
    except (TypeError, ValueError):
        return "", "contract workspace root is unavailable"
    baseline, baseline_error = _validate_scope_baseline(root, scope)
    if baseline_error:
        return "", baseline_error
    selected: list[str] = []
    for target in targets:
        relative, path_error = _target_relative(root, target)
        if path_error:
            return "", path_error
        owned, ownership_error = _ownership_match(relative, scope.owned_paths)
        if ownership_error:
            return "", ownership_error
        if owned and relative not in selected:
            selected.append(relative)
    if not selected:
        return "", "event has no registered target owned by the current task"

    evidence_parts: list[str] = []
    for relative in selected:
        if relative not in scope.baseline_snapshot:
            return "", f"baseline snapshot has no explicit entry for target: {relative}"
        baseline_fingerprint, baseline_bytes, fingerprint_error = _baseline_file_bytes(
            root, baseline, relative
        )
        if fingerprint_error:
            return "", fingerprint_error
        snapshot_fingerprint = scope.baseline_snapshot.get(relative)
        expected_snapshot = (
            "!missing" if baseline_fingerprint is None else baseline_fingerprint
        )
        if snapshot_fingerprint != expected_snapshot:
            return "", f"target was not clean at the frozen task baseline: {relative}"
        current_bytes, read_error = _read_stable_regular_bytes(root, relative)
        if read_error or current_bytes is None:
            return "", read_error or "critic target read failed"
        diff, diff_error = _raw_unified_diff(baseline_bytes, current_bytes, relative)
        if diff_error:
            return "", diff_error
        if diff.strip():
            evidence_parts.append(f"TARGET: {relative}\n\nINCREMENT:\n{diff}")
    if not evidence_parts:
        return "", "current task has no non-empty increment after its frozen baseline"
    evidence = (
        f"TASK: {scope.task_id}\nBASELINE: {scope.baseline}\nRUN: {scope.run_id}\n\n"
        + "\n\n--- TASK-OWNED INCREMENT ---\n\n".join(evidence_parts)
    )
    if registered:
        evidence += "\n\nREGISTERED CURRENT-RUN EVIDENCE:\n" + registered
    if len(evidence) > MAX_EVIDENCE_CHARS:
        return "", "critic evidence exceeds the bounded model input"
    return evidence, ""


def _read_target(contract: dict[str, Any], event: dict[str, Any]) -> tuple[str, str]:
    if not _is_plain_string_dict(event):
        return "", "critic checkpoint event must be a plain object"
    effect = event.get("effect")
    if not _is_exact_string(effect) or effect != "local_write":
        return "", "event has no readable local artifact"
    scope, scope_error = _task_critic_scope(contract)
    if scope_error:
        return "", scope_error
    if scope is None:  # Kept explicit for type narrowing and fail-closed review.
        return "", "critic task scope is unavailable"
    targets, target_error = _event_targets(event)
    if target_error:
        return "", target_error
    return _scoped_increment(contract, event, scope, targets)


def _kb_home() -> Path:
    configured = os.environ.get("SULDE_KB_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".sulde" / "data" / "kb"


def relevant_knowledge(
    contract: dict[str, Any], event: dict[str, Any]
) -> list[dict[str, str]]:
    """Read applicable, verified sample guidance without making it authoritative."""
    root = Path(__file__).resolve().parents[2]
    query_parts = [
        str(contract.get("objective") or ""),
        *[str(item) for item in contract.get("constraints", {}).get("preserve", [])],
        *[str(item) for item in contract.get("constraints", {}).get("reject", [])],
        str(event.get("capability") or ""),
    ]
    query = " ".join(" ".join(query_parts).split())[:4_000]
    if not query:
        return []
    completed = kb_cli.run_cli(
        root,
        _kb_home(),
        "search",
        [query, "-k", "5", "--json", "--purpose", "route"],
        timeout=5,
    )
    if not completed.ok:
        return []
    try:
        results = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(results, list):
        return []
    ranked: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        ranked.append({**item, "score": score})
    ranked.sort(key=lambda item: float(item["score"]), reverse=True)
    if ranked and (
        str(ranked[0].get("applicability") or "apply") != "apply"
        or str(ranked[0].get("evidence_status") or "legacy") == "inconclusive"
    ):
        # An explicit high-score exclusion or evidence gap outranks a weaker
        # positive match.  Falling through would turn a boundary into advice.
        return []
    selected: list[dict[str, str]] = []
    knowledge_root = (root / "knowledge").resolve()
    for item in ranked:
        score = float(item["score"])
        if (
            score < KB_SCORE_MIN
            or str(item.get("applicability") or "apply") != "apply"
            or str(item.get("evidence_status") or "legacy") == "inconclusive"
        ):
            continue
        raw_path = item.get("source_path")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        try:
            source = (root / raw_path).resolve(strict=True)
            source.relative_to(knowledge_root)
            markdown = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            continue
        excerpt = guidance_excerpt(markdown)
        if not excerpt:
            continue
        selected.append(
            {
                "doc_id": str(item.get("doc_id") or ""),
                "source_path": raw_path,
                "matched_role": str(item.get("role") or "general"),
                "guidance": excerpt,
            }
        )
        if len(selected) >= KB_MAX_GUIDANCE:
            break
    return selected


def build_prompt(
    contract: dict[str, Any],
    event: dict[str, Any],
    evidence: str,
    knowledge: list[dict[str, str]] | None = None,
) -> str:
    intent = {
        "intent_id": contract["intent_id"],
        "revision": contract["revision"],
        "objective": contract["objective"],
        "rationale": contract["rationale"],
        "acceptance_criteria": contract["acceptance_criteria"],
        "preserve": contract["constraints"]["preserve"],
        "reject": contract["constraints"]["reject"],
    }
    observed = {
        "capability": event.get("capability"),
        "target": event.get("target"),
        "write_targets": event.get("write_targets", []),
        "completed_writes": event.get("completed_writes"),
        "effect": event.get("effect"),
        "parent_skills": event.get("parent_skills", []),
        "task_id": event.get("task_id"),
        "baseline": event.get("baseline"),
        "run_id": event.get("run_id"),
        "registered_evidence_ids": event.get("registered_evidence_ids", []),
    }
    knowledge_text = json.dumps(knowledge or [], ensure_ascii=False, indent=2)
    return f"""你是 Sulde 的只读意图审查器。只评估下面的可观察产物，不猜测隐藏思维。

意图契约：
{json.dumps(intent, ensure_ascii=False, indent=2)}

执行事件：
{json.dumps(observed, ensure_ascii=False, indent=2)}

产物证据：
{evidence}

相关结构化沉淀（已经过 apply/skip 与证据状态门控，但仍只是辅助线索）：
{knowledge_text}

判断规则：
- aligned：证据支持目标，且未违反 preserve/reject；
- drift：引用具体证据证明违反明确约束或偏离目标；
- inconclusive：证据不足、约束含糊或只能凭主观猜测。
- 不得因为有改动就判 drift；不得把偏好建议当硬约束；不得修改契约。
- 意图契约优先于知识；只有当前事件符合知识的适用边界且不命中路由反例时才可采用。
- 用执行合格/失败例帮助验收，不得把构造样本冒充当前任务的一手事实。

只输出一个 JSON 对象，不用 Markdown：
{{"verdict":"aligned|drift|inconclusive","confidence":0.0,"summary":"...","violated_constraints":["..."],"evidence":["不超过5条具体短证据"],"next_action":"continue|pause_and_clarify|collect_evidence"}}
"""


def _parse_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise IntentGuardianError(f"intent critic returned invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise IntentGuardianError("intent critic JSON root must be an object")
    return payload


def validate_result(value: dict[str, Any]) -> CriticResult:
    verdict = str(value.get("verdict") or "")
    if verdict not in VERDICTS:
        raise IntentGuardianError(f"invalid critic verdict: {verdict!r}")
    try:
        confidence = float(value.get("confidence"))
    except (TypeError, ValueError) as error:
        raise IntentGuardianError("critic confidence must be numeric") from error
    if not 0 <= confidence <= 1:
        raise IntentGuardianError("critic confidence must be between 0 and 1")
    violated = value.get("violated_constraints")
    evidence = value.get("evidence")
    if not isinstance(violated, list) or not all(isinstance(item, str) for item in violated):
        raise IntentGuardianError("critic violated_constraints must be strings")
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise IntentGuardianError("critic evidence must be strings")
    next_action = str(value.get("next_action") or "")
    if next_action not in {"continue", "pause_and_clarify", "collect_evidence"}:
        raise IntentGuardianError(f"invalid critic next_action: {next_action!r}")
    if verdict == "drift" and (not violated or not evidence or next_action != "pause_and_clarify"):
        raise IntentGuardianError("drift requires violated constraints, concrete evidence and pause_and_clarify")
    return CriticResult(
        verdict=verdict,
        confidence=confidence,
        summary=str(value.get("summary") or "")[:2_000],
        violated_constraints=tuple(item[:500] for item in violated[:10]),
        evidence=tuple(item[:1_000] for item in evidence[:5]),
        next_action=next_action,
    )


def run_critic(
    contract: dict[str, Any],
    event: dict[str, Any],
    *,
    provider: str,
    command: list[str] | None = None,
) -> dict[str, Any]:
    if (
        not _is_exact_string(provider)
        or not provider
        or (
            command is not None
            and (
                type(command) is not list
                or not command
                or not all(_is_exact_string(item) and item for item in command)
            )
        )
    ):
        return CriticResult(
            verdict="inconclusive",
            confidence=1.0,
            summary="critic provider command authority must use exact strings",
            violated_constraints=(),
            evidence=(),
            next_action="collect_evidence",
        ).as_dict()
    evidence, missing = _read_target(contract, event)
    if missing:
        return CriticResult(
            verdict="inconclusive",
            confidence=1.0,
            summary=missing,
            violated_constraints=(),
            evidence=(),
            next_action="collect_evidence",
        ).as_dict()
    matches = secret_matches(evidence)
    if matches:
        return CriticResult(
            verdict="inconclusive",
            confidence=1.0,
            summary="密钥扫描阻止将产物发送给认知审查器",
            violated_constraints=(),
            evidence=("secret_patterns=" + ",".join(matches),),
            next_action="collect_evidence",
        ).as_dict()
    knowledge = relevant_knowledge(contract, event)
    prompt = build_prompt(contract, event, evidence, knowledge)
    if command is None:
        override = os.environ.get("SULDE_GUARDIAN_CRITIC_CMD", "").strip()
        if override:
            command = split_command_template(override)
        else:
            selected, executable = select_provider(provider)
            command = cognitive_command(selected, executable)
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            cwd=contract["workspace_root"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(contract["critic"]["timeout_seconds"]),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ProviderError) as error:
        raise IntentGuardianError(f"intent critic unavailable: {error}") from error
    if completed.returncode != 0:
        raise IntentGuardianError(
            f"intent critic failed exit={completed.returncode}: {completed.stderr[-500:]}"
        )
    return validate_result(_parse_json(completed.stdout)).as_dict()

"""Single versioned launch description shared by preflight and execution.

One managed run has exactly one launch description.  Preflight validates the
same parsed description that execution consumes; the description is digest-only
(no argv, no prompts, no secrets) so it can be persisted beside the frozen
static controls and re-validated on local retry.  This closes the split where
preflight re-derived the launch command while execution re-composed it.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any


LAUNCH_DESCRIPTION_SCHEMA = "sulde-launch-description-v1"
LAUNCH_DESCRIPTION_ARTIFACT_SCHEMA = "sulde-launch-description-artifact-v1"
LAUNCH_DESCRIPTION_FIELDS = frozenset(
    {
        "schema",
        "provider",
        "provider_source",
        "effort",
        "report_relative_path",
        "durable_report_relative_path",
        "command_sha256",
        "profile_arguments_sha256",
        "execution_binding_sha256",
        "task_id",
        "base_commit",
        "report_contract",
        "dependency_checks",
    }
)
PROVIDER_SOURCES = frozenset({"explicit", "environment", "auto"})
_DEPENDENCY_CHECK_NAMES = frozenset(
    {"provider_executable", "report_contract", "report_location"}
)
_SHA256_RE_LENGTH_64 = (64,)


class LaunchDescriptionError(RuntimeError):
    """A launch description cannot be built, parsed, or trusted."""


class LaunchPreflightError(RuntimeError):
    """A bounded pre-launch failure detected with zero model calls."""

    def __init__(self, message: str, failures: list[dict[str, str]]) -> None:
        super().__init__(message)
        self.failures = [dict(row) for row in failures]


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LaunchDescriptionError(f"launch description {label} is not a sha256 digest")
    return value


def build_launch_description(
    *,
    provider: str,
    provider_source: str,
    effort: str,
    report_relative_path: str,
    command_sha256: str,
    profile_arguments_sha256: str | None,
    execution_binding_sha256: str,
    task_id: str,
    base_commit: str,
    report_contract: dict[str, Any],
    dependency_checks: list[dict[str, str]],
    durable_report_relative_path: str | None = None,
    require_durable_report: bool = False,
) -> dict[str, Any]:
    """Build one validated, digest-only launch description."""
    if provider not in ("claude", "codex"):
        raise LaunchDescriptionError(f"unsupported provider: {provider!r}")
    if provider_source not in PROVIDER_SOURCES:
        raise LaunchDescriptionError(f"unsupported provider source: {provider_source!r}")
    if effort not in ("low", "medium", "high"):
        raise LaunchDescriptionError(f"unsupported effort: {effort!r}")
    if not isinstance(report_relative_path, str) or not report_relative_path:
        raise LaunchDescriptionError("launch description report path is empty")
    if durable_report_relative_path is not None and (
        not isinstance(durable_report_relative_path, str)
        or not durable_report_relative_path
    ):
        raise LaunchDescriptionError(
            "launch description durable report path is invalid"
        )
    if require_durable_report and durable_report_relative_path is None:
        raise LaunchDescriptionError(
            "this launch requires the durable report path resolved by the "
            "finalize-time contract parse"
        )
    _require_sha256(command_sha256, "command digest")
    _require_sha256(execution_binding_sha256, "execution binding digest")
    if profile_arguments_sha256 is not None:
        _require_sha256(profile_arguments_sha256, "profile arguments digest")
    if not isinstance(task_id, str) or not task_id.strip():
        raise LaunchDescriptionError("launch description task id is empty")
    if not isinstance(base_commit, str) or not base_commit.strip():
        raise LaunchDescriptionError("launch description base commit is empty")
    contract = report_contract
    if not isinstance(contract, dict) or set(contract) != {
        "schema",
        "headings",
        "evidence_schema",
    }:
        raise LaunchDescriptionError("launch description report contract fields are invalid")
    headings = contract["headings"]
    if (
        not isinstance(headings, list)
        or not headings
        or any(not isinstance(item, str) or not item.strip() for item in headings)
    ):
        raise LaunchDescriptionError("launch description report contract headings are invalid")
    if not isinstance(contract["evidence_schema"], str) or not contract["evidence_schema"]:
        raise LaunchDescriptionError("launch description evidence schema is empty")
    checks = dependency_checks
    if not isinstance(checks, list) or any(
        not isinstance(item, dict)
        or set(item) != {"name", "evidence"}
        or item.get("name") not in _DEPENDENCY_CHECK_NAMES
        or not isinstance(item.get("evidence"), str)
        or not item["evidence"]
        for item in checks
    ):
        raise LaunchDescriptionError("launch description dependency checks are invalid")
    names = [item["name"] for item in checks]
    if len(set(names)) != len(names):
        raise LaunchDescriptionError("launch description dependency checks repeat a name")
    description: dict[str, Any] = {
        "schema": LAUNCH_DESCRIPTION_SCHEMA,
        "provider": provider,
        "provider_source": provider_source,
        "effort": effort,
        "report_relative_path": report_relative_path,
        "durable_report_relative_path": durable_report_relative_path,
        "command_sha256": command_sha256,
        "profile_arguments_sha256": profile_arguments_sha256,
        "execution_binding_sha256": execution_binding_sha256,
        "task_id": task_id,
        "base_commit": base_commit,
        "report_contract": {
            "schema": contract["schema"],
            "headings": list(headings),
            "evidence_schema": contract["evidence_schema"],
        },
        "dependency_checks": [dict(item) for item in checks],
    }
    return description


def launch_description_digest(description: dict[str, Any]) -> str:
    if (
        not isinstance(description, dict)
        or set(description) != LAUNCH_DESCRIPTION_FIELDS
    ):
        raise LaunchDescriptionError("launch description fields are invalid")
    return _digest(description)


def launch_description_artifact(
    description: dict[str, Any],
) -> tuple[bytes, str]:
    digest = launch_description_digest(description)
    artifact = {
        "schema": LAUNCH_DESCRIPTION_ARTIFACT_SCHEMA,
        "description": description,
        "description_sha256": digest,
    }
    return (
        _canonical_json_bytes(artifact) + b"\n",
        digest,
    )


def parse_launch_description_artifact(
    payload: bytes,
) -> tuple[dict[str, Any], str]:
    try:
        artifact = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise LaunchDescriptionError(
            f"launch description artifact is invalid: {error}"
        ) from error
    if (
        not isinstance(artifact, dict)
        or set(artifact) != {"schema", "description", "description_sha256"}
        or artifact.get("schema") != LAUNCH_DESCRIPTION_ARTIFACT_SCHEMA
        or not isinstance(artifact.get("description"), dict)
    ):
        raise LaunchDescriptionError("launch description artifact fields are invalid")
    digest = launch_description_digest(artifact["description"])
    if artifact.get("description_sha256") != digest:
        raise LaunchDescriptionError("launch description canonical digest drifted")
    return artifact["description"], digest


def command_digest_for(command: list[str]) -> str:
    """Digest the final launch command exactly like the run ledger does."""
    joined = "\0".join(str(value) for value in command)
    return hashlib.sha256(joined.encode("utf-8", errors="replace")).hexdigest()


LAUNCH_IDENTITY_EXCLUDED_FIELDS = frozenset({"command_sha256"})


def launch_description_identity(description: dict[str, Any]) -> str:
    """Executable-independent semantic identity of one launch description.

    The provider executable can legitimately change between attempts of the
    same request (e.g. a recovery finisher binary replaces a crashed one);
    the command digest is the only field that embeds it.  Everything else —
    provider, effort, brief, task, binding, report contract — must stay
    identical for the same slug across attempts.
    """
    if (
        not isinstance(description, dict)
        or set(description) != LAUNCH_DESCRIPTION_FIELDS
    ):
        raise LaunchDescriptionError("launch description fields are invalid")
    identity = {
        key: value
        for key, value in description.items()
        if key not in LAUNCH_IDENTITY_EXCLUDED_FIELDS
    }
    return _digest(identity)


def preflight_launch_description(
    description: dict[str, Any],
    *,
    state_dir: Path,
    provider_executable_evidence: str,
) -> list[dict[str, str]]:
    """Run bounded pre-launch checks with zero model calls.

    Covers the infrastructure mismatch classes that otherwise surface only
    after the provider has already burned a model turn: a malformed report
    contract, an unwritable or drifting report location, and an unresolvable
    provider executable.  Returns the dependency-check evidence rows that are
    folded back into the persisted description's ``dependency_checks``.
    """
    failures: list[dict[str, str]] = []
    evidence: list[dict[str, str]] = []
    relative = description["report_relative_path"]
    planned_report = state_dir / Path(relative).name
    if planned_report.parent != state_dir or planned_report.is_symlink():
        failures.append(
            {
                "check": "report_location",
                "reason": "planned report path escapes the state directory or is a symlink",
            }
        )
    elif not state_dir.is_dir() or state_dir.is_symlink():
        failures.append(
            {
                "check": "report_location",
                "reason": "state directory is missing or not a real directory",
            }
        )
    else:
        probe = state_dir / ".launch-preflight-report-probe"
        try:
            # Exclusive-create, no-follow: the probe never overwrites an
            # existing file and never writes through a symlink.
            descriptor = os.open(
                probe,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            os.close(descriptor)
            probe.unlink()
            evidence.append(
                {"name": "report_location", "evidence": "state directory writable"}
            )
        except FileExistsError:
            failures.append(
                {
                    "check": "report_location",
                    "reason": "preflight probe file already exists; refusing to overwrite",
                }
            )
        except OSError as error:
            failures.append(
                {
                    "check": "report_location",
                    "reason": f"report parent is not writable: {type(error).__name__}",
                }
            )
    contract = description["report_contract"]
    if not contract["headings"] or not contract["evidence_schema"]:
        failures.append(
            {
                "check": "report_contract",
                "reason": "report contract has no headings or empty evidence schema",
            }
        )
    else:
        evidence.append(
            {
                "name": "report_contract",
                "evidence": (
                    f"{len(contract['headings'])} headings; "
                    f"schema={contract['schema']}"
                ),
            }
        )
    resolved = provider_executable_evidence.strip()
    if resolved:
        evidence.append(
            {"name": "provider_executable", "evidence": resolved[:128]}
        )
    else:
        failures.append(
            {
                "check": "provider_executable",
                "reason": (
                    f"provider {description['provider']} executable is not resolvable"
                ),
            }
        )
    if failures:
        raise LaunchPreflightError(
            "launch preflight found "
            f"{len(failures)} blocking issue(s) before any model call: "
            + "; ".join(row["check"] for row in failures),
            failures,
        )
    return evidence


def preflight_failure_evidence(
    slug: str,
    error: LaunchPreflightError,
    *,
    description_sha256: str | None = None,
) -> dict[str, Any]:
    """Persisted failure evidence, written before any model call."""
    return {
        "schema": "sulde-launch-preflight-failure-v1",
        "slug": slug,
        "description_sha256": description_sha256,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "failures": error.failures,
    }

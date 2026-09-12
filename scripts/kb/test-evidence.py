#!/usr/bin/env python3
"""Plan, run, reuse and expire exact Sulde test evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import runpy
import subprocess
import sys
import time
from typing import Any, Iterable


sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "kb" / "run-isolated-tests.py"
SCHEMA = "sulde-test-evidence-v2"
LEGACY_SCHEMAS = frozenset({"sulde-test-evidence-v1", SCHEMA})
DEFAULT_TTL_DAYS = 30
DEFAULT_MAX_RECORDS = 250
GC_INTERVAL_SECONDS = 24 * 60 * 60
SOURCE_BYTECODE_ROOTS = (
    "hooks",
    "integrations/codex/plugins/sulde",
    "scripts",
    "tests",
)

_REFACTOR_PREFIXES = (
    "scripts/kb/intent_guardian",
    "scripts/kb/intervention.py",
    "scripts/kb/task_ownership.py",
    "scripts/kb/run-isolated-tests.py",
    "scripts/release/install_codex_plugin.py",
    "scripts/release/candidate_codex_plugin.py",
    "integrations/codex/plugins/sulde/scripts/",
    "hooks/",
)

_IMPACT_MAP = {
    "scripts/kb/intervention.py": ("tests.test_intervention",),
    "scripts/kb/resource_adapters.py": ("tests.test_resource_adapters",),
    "scripts/kb/life-cycle.py": ("tests.test_life_cycle", "tests.test_operational_readiness"),
    "scripts/kb/self-repair.py": ("tests.test_self_repair", "tests.test_life_cycle"),
    "scripts/kb/organ-evolution.py": ("tests.test_organ_evolution", "tests.test_life_cycle"),
    "scripts/kb/event_contract.py": ("tests.test_event_observer",),
    "scripts/kb/event_observer.py": ("tests.test_event_observer",),
    "scripts/kb/event-observer.py": ("tests.test_event_observer",),
    "scripts/kb/event_projection_cache.py": ("tests.test_event_observer",),
    "scripts/kb/agent-experience.py": ("tests.test_agent_experience", "tests.test_test_evidence"),
    "scripts/kb/agent-runtime.py": ("tests.test_agent_runtime",),
    "scripts/kb/test-evidence.py": ("tests.test_test_evidence",),
    "scripts/kb/run-isolated-tests.py": ("tests.test_isolated_test_runner",),
    "scripts/release/candidate_codex_plugin.py": (
        "tests.test_candidate_codex_plugin",
    ),
    "scripts/release/install_codex_plugin.py": ("tests.test_codex_plugin_install",),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def evidence_root() -> Path:
    configured = os.environ.get("SULDE_TEST_EVIDENCE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    sulde_home = Path(os.environ.get("SULDE_HOME") or Path.home() / ".sulde")
    return (sulde_home / "data" / "test-evidence").expanduser().resolve()


def clean_source_bytecode(root: Path = ROOT) -> dict[str, int]:
    """Remove only derived Python bytecode from repository source roots.

    ``python -B`` prevents import caches, but ``py_compile`` writes bytecode
    explicitly and ignores that import setting.  Keeping this cleanup inside
    the supported test runner prevents those derived files from surviving an
    Agent validation pass or leaking into a staged plugin.
    """
    files_removed = 0
    directories: set[Path] = set()
    for relative in SOURCE_BYTECODE_ROOTS:
        base = root / relative
        if not base.is_dir() or base.is_symlink():
            continue
        for path in base.rglob("*"):
            if path.is_symlink():
                continue
            if path.is_dir() and path.name == "__pycache__":
                directories.add(path)
                continue
            if path.is_file() and path.suffix.casefold() in {".pyc", ".pyo"}:
                path.unlink()
                files_removed += 1
                if path.parent.name == "__pycache__":
                    directories.add(path.parent)
    directories_removed = 0
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            continue
        directories_removed += 1
    return {
        "files_removed": files_removed,
        "directories_removed": directories_removed,
    }


def _git(*arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout).strip())
    return completed.stdout


def changed_paths(base: str) -> list[str]:
    values = set(
        line.strip()
        for line in _git("diff", "--name-only", f"{base}...HEAD").splitlines()
        if line.strip()
    )
    for line in _git("status", "--porcelain=v1", "--untracked-files=all").splitlines():
        value = line[3:].strip() if len(line) > 3 else ""
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        if value:
            values.add(value)
    return sorted(values)


def _test_module(path: str) -> str | None:
    candidate = Path(path)
    if candidate.parent == Path("tests") and candidate.name.startswith("test_"):
        return ".".join(candidate.with_suffix("").parts)
    return None


def classify(paths: Iterable[str], *, requested: str = "auto") -> str:
    if requested != "auto":
        return requested
    selected = tuple(sorted(set(paths)))
    if (
        len(selected) > 12
        or any(path.startswith(_REFACTOR_PREFIXES) for path in selected)
        or len({Path(path).parts[0] for path in selected if Path(path).parts}) > 3
    ):
        return "refactor"
    if len(selected) <= 3:
        return "small"
    return "medium"


def impacted_tests(paths: Iterable[str], risk: str) -> list[str]:
    if risk == "refactor":
        return []
    selected: set[str] = set()
    for path in paths:
        module = _test_module(path)
        if module:
            selected.add(module)
        selected.update(_IMPACT_MAP.get(path, ()))
        stem = Path(path).stem.replace("-", "_")
        candidate = ROOT / "tests" / f"test_{stem}.py"
        if candidate.is_file():
            selected.add(f"tests.test_{stem}")
        if path.startswith("integrations/codex/plugins/sulde/scripts/"):
            selected.update(
                {
                    "tests.test_codex_user_prompt_adapter",
                    "tests.test_codex_hook_bridge",
                }
            )
        if "intent_guardian" in path:
            selected.add("tests.test_intent_guardian")
    if not selected:
        selected.add("tests.test_stage_release_inventory")
    return sorted(selected)


def experience_test_hints(paths: Iterable[str]) -> dict[str, Any]:
    """Only verified experience may add tests; weaker records stay diagnostic."""
    home_value = os.environ.get("SULDE_KB_HOME")
    if not home_value:
        return {
            "strategy": {"source": "default", "recommended_tests": [], "experience_ids": []},
            "diagnostic_hints": [],
            "unresolved_retained": 0,
            "matched": 0,
        }
    script_directory = str(Path(__file__).resolve().parent)
    sys.path.insert(0, script_directory)
    try:
        module = runpy.run_path(str(Path(__file__).with_name("agent-experience.py")))
        return module["recall"](
            Path(home_value).expanduser(),
            problem_type="test_selection",
            symptom=" ".join(paths),
            affected_components=paths,
        )
    except (ImportError, OSError, ValueError):
        return {
            "strategy": {"source": "default", "recommended_tests": [], "experience_ids": []},
            "diagnostic_hints": [],
            "unresolved_retained": 0,
            "matched": 0,
        }
    finally:
        try:
            sys.path.remove(script_directory)
        except ValueError:
            pass


def plan(base: str, *, requested: str = "auto") -> dict[str, Any]:
    paths = changed_paths(base)
    risk = classify(paths, requested=requested)
    tests = impacted_tests(paths, risk)
    experience = experience_test_hints(paths)
    if risk != "refactor":
        for module in experience["strategy"]["recommended_tests"]:
            candidate = ROOT / f"{module.replace('.', '/')}.py"
            if module.startswith("tests.test_") and candidate.is_file():
                tests.append(module)
        tests = sorted(set(tests))
    impact_graph = {
        path: impacted_tests([path], "medium")
        for path in paths
    }
    return {
        "schema": "sulde-test-plan-v1",
        "base": base,
        "baseline_commit": _git("rev-parse", base).strip(),
        "head": _git("rev-parse", "HEAD").strip(),
        "risk": risk,
        "changed_paths": paths,
        "tests": tests,
        "impact_graph": impact_graph,
        "experience_recall": experience,
        "scope": {
            "changed_paths": paths,
            "selected_tests": tests,
            "selection": "full" if not tests else "impact_graph",
        },
        "suite": "full" if not tests else "targeted",
        "runner": str(RUNNER),
        "rationale": {
            "small": "leaf change: run direct mapped tests",
            "medium": "cross-file change: run dependency/ownership impact set",
            "refactor": "control/runtime/refactor change: run the full isolated suite",
        }[risk],
    }


def _workspace_digest() -> str:
    # Bind executable inputs and their fixtures, not commits or unrelated output.
    # Root dependency manifests are included; report/log-only commits stay reusable.
    source_roots = {"scripts", "hooks", "integrations", "tools", "tests", "templates", "template", "commands",
                    "config", "skills", "knowledge", ".codex-plugin", ".claude-plugin"}
    root_inputs = {"AGENTS.md", "CANON.md", "LICENSE", "docs/dual-runtime-contract.md",
                   "docs/event-observability.md", "docs/intent-guardian.md", "pyproject.toml", "uv.lock", "poetry.lock",
                   "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
    inventory = _git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    rows: list[dict[str, Any]] = []
    for path in sorted(set(inventory.split("\0")) - {""}):
        parts = Path(path).parts
        if not parts or (parts[0] not in source_roots and path not in root_inputs
                         and not path.startswith("requirements")):
            continue
        if "__pycache__" in parts or path.endswith((".pyc", ".pyo")):
            continue
        candidate = ROOT / path
        try:
            metadata = candidate.lstat()
            if candidate.is_symlink():
                entry = {
                    "type": "symlink",
                    "target": os.readlink(candidate),
                }
            elif candidate.is_file():
                entry = {
                    "type": "file",
                    "mode": metadata.st_mode & 0o777,
                    "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                }
            elif candidate.is_dir():
                entry = {"type": "directory", "mode": metadata.st_mode & 0o777}
            else:
                entry = {"type": "special", "mode": metadata.st_mode & 0o777}
        except FileNotFoundError:
            entry = {"type": "missing"}
        except OSError:
            entry = {"type": "unreadable"}
        rows.append({"path": path, **entry})
    return _digest({"input_policy": "source-dependencies-fixtures-v1", "inputs": rows})


def evidence_key(selected_plan: dict[str, Any]) -> str:
    return _digest(
        {
            "repository": str(ROOT.resolve()),
            "workspace_sha256": _workspace_digest(),
            "risk": selected_plan["risk"],
            "tests": selected_plan["tests"],
            "runner_sha256": hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
            "python": str(Path(sys.executable).resolve()),
            "python_version": platform.python_version(),
            "python_dependencies": sorted(
                (distribution.metadata.get("Name", "unknown"), distribution.version)
                for distribution in importlib.metadata.distributions()
            ),
            "platform": platform.platform(),
        }
    )


def _records(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    values: list[tuple[Path, dict[str, Any]]] = []
    if not root.is_dir():
        return values
    for path in sorted(root.glob("*.json")):
        if path.name == "gc-state.json":
            continue
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(row, dict) and row.get("schema") in LEGACY_SCHEMAS:
            values.append((path, row))
    return values


def reusable_record(root: Path, key: str, *, current: datetime) -> dict[str, Any] | None:
    cutoff = current - timedelta(days=DEFAULT_TTL_DAYS)
    matches: list[dict[str, Any]] = []
    for _path, row in _records(root):
        try:
            ended = datetime.fromisoformat(str(row["ended_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        reusable = bool(
            row.get("evidence_key") == key
            and row.get("status") == "passed"
            and row.get("partial") is not True
            and row.get("exit_code") in {None, 0}
            and result.get("complete", True) is True
            and result.get("verdict", "passed") == "passed"
            and ended >= cutoff
        )
        if reusable:
            matches.append(row)
    return sorted(matches, key=lambda row: str(row.get("ended_at") or ""))[-1] if matches else None


def run_plan(selected_plan: dict[str, Any], *, reuse: bool = True) -> tuple[int, dict[str, Any]]:
    root = evidence_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    cleanup_before = clean_source_bytecode()
    key = evidence_key(selected_plan)
    current = _now()
    if reuse:
        prior = reusable_record(root, key, current=current)
        if prior is not None:
            return 0, {**prior, "reused": True}
    run_id = current.strftime("%Y%m%dT%H%M%S.%f") + "-" + key[:12]
    log_path = root / f"{run_id}.log"
    command = [sys.executable, "-B", str(RUNNER), *selected_plan["tests"]]
    started = time.monotonic()
    try:
        with log_path.open("wb") as output:
            completed = subprocess.run(
                command,
                cwd=ROOT,
                stdout=output,
                stderr=subprocess.STDOUT,
                check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
    finally:
        cleanup_after = clean_source_bytecode()
    ended = _now()
    record = {
        "schema": SCHEMA,
        "run_id": run_id,
        "evidence_key": key,
        "repository": str(ROOT.resolve()),
        "base": selected_plan["base"],
        "head": selected_plan["head"],
        "workspace_sha256": _workspace_digest(),
        "risk": selected_plan["risk"],
        "suite": selected_plan["suite"],
        "tests": selected_plan["tests"],
        "scope": selected_plan.get("scope", {
            "changed_paths": selected_plan.get("changed_paths", []),
            "selected_tests": selected_plan["tests"],
            "selection": selected_plan["suite"],
        }),
        "baseline": {
            "ref": selected_plan["base"],
            "commit": selected_plan.get("baseline_commit", selected_plan["head"]),
        },
        "command": command,
        "command_sha256": _digest(command),
        "runner_sha256": hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
        "python": str(Path(sys.executable).resolve()),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "started_at": current.isoformat(),
        "ended_at": ended.isoformat(),
        "expires_at": (ended + timedelta(days=DEFAULT_TTL_DAYS)).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "exit_code": completed.returncode,
        "status": "passed" if completed.returncode == 0 else "failed",
        "partial": False,
        "result": {
            "complete": True,
            "verdict": "passed" if completed.returncode == 0 else "failed",
            "exit_code": completed.returncode,
        },
        "environment": {
            "python": str(Path(sys.executable).resolve()),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "bytecode_disabled": True,
            "runner_sha256": hashlib.sha256(RUNNER.read_bytes()).hexdigest(),
        },
        "log": log_path.name,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "reused": False,
        "source_bytecode_cleanup": {
            "before": cleanup_before,
            "after": cleanup_after,
        },
    }
    record_path = root / f"{run_id}.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return completed.returncode, record


def gc_records(
    root: Path,
    *,
    current: datetime | None = None,
    scheduled: bool = False,
    ttl_days: int = DEFAULT_TTL_DAYS,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> dict[str, Any]:
    """Project retention candidates without deleting evidence (P2 owns deletion)."""
    current = (current or _now()).astimezone(timezone.utc)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = root / "gc-state.json"
    if scheduled and state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last = datetime.fromisoformat(str(state["last_run_at"]).replace("Z", "+00:00"))
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            last = datetime.min.replace(tzinfo=timezone.utc)
        if (current - last).total_seconds() < GC_INTERVAL_SECONDS:
            return {
                "status": "skipped",
                "reason": "interval",
                "removed": 0,
                "deletion_performed": False,
            }
    records = _records(root)
    first_failures: dict[str, tuple[Path, dict[str, Any]]] = {}
    full_passes: list[tuple[Path, dict[str, Any]]] = []
    for path, row in records:
        if row.get("status") == "failed":
            key = str(row.get("evidence_key") or "")
            prior = first_failures.get(key)
            if prior is None or str(row.get("ended_at")) < str(prior[1].get("ended_at")):
                first_failures[key] = (path, row)
        if row.get("status") == "passed" and row.get("suite") == "full":
            full_passes.append((path, row))
    capacity = max(1, max_records)
    protected: set[Path] = set()
    if full_passes:
        protected.add(max(full_passes, key=lambda item: str(item[1].get("ended_at")))[0])
    failure_slots = max(0, capacity - len(protected))
    protected.update(
        path
        for path, _row in sorted(
            first_failures.values(),
            key=lambda item: str(item[1].get("ended_at") or ""),
            reverse=True,
        )[:failure_slots]
    )
    cutoff = current - timedelta(days=max(1, ttl_days))
    ordered = sorted(
        records,
        key=lambda item: str(item[1].get("ended_at") or ""),
        reverse=True,
    )
    retained = set(protected)
    for path, row in ordered:
        if len(retained) >= capacity:
            break
        try:
            ended = datetime.fromisoformat(str(row["ended_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            continue
        if ended >= cutoff:
            retained.add(path)
    candidates = [
        {
            "record": path.name,
            "log": str(row.get("log") or ""),
            "reason": "expired_or_over_capacity",
            "record_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path, row in records
        if path not in retained
    ]
    state = {
        "schema": "sulde-test-evidence-retention-plan-v1",
        "last_run_at": current.isoformat(),
        "removed": 0,
        "retained": len(records),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "deletion_performed": False,
        "policy": "evidence recall only; automatic deletion is deferred to P2",
    }
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {"status": "planned", **state}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("plan", "run"):
        selected = subparsers.add_parser(action)
        selected.add_argument("--base", default="dev")
        selected.add_argument(
            "--risk", choices=("auto", "small", "medium", "refactor"), default="auto"
        )
        if action == "run":
            selected.add_argument("--no-reuse", action="store_true")
    gc = subparsers.add_parser("gc")
    gc.add_argument("--scheduled", action="store_true")
    gc.add_argument("--ttl-days", type=int, default=DEFAULT_TTL_DAYS)
    gc.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.action == "gc":
        result = gc_records(
            evidence_root(),
            scheduled=args.scheduled,
            ttl_days=args.ttl_days,
            max_records=args.max_records,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    selected_plan = plan(args.base, requested=args.risk)
    if args.action == "plan":
        print(json.dumps(selected_plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return_code, record = run_plan(selected_plan, reuse=not args.no_reuse)
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())

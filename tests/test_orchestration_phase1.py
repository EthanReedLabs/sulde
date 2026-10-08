"""Phase 1 (orchestration iteration) tests: launch description + dispatch idempotency.

Covers:
- C1: one versioned launch description consumed by preflight and execution;
  preflighable failures are detected with zero model calls; the executed
  description digest is embedded in the run ledger's first event.
- C2: persistence-backed dispatch-request identity (same request resumes,
  same id with different content conflicts, terminal attempts never block
  resubmission); bounded launch concurrency; stale heartbeat refusal.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
RUNTIME = SCRIPT_DIR / "agent-runtime.py"
REPORT = """## 结果
任务完成。
✅ 验证通过：`python -m unittest`，exit 0；输出 OK；candidate_sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa；execution_binding_sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb；environment_sha256=cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc；command_sha256=88d1e4ef3a5e210c702e32c1f294a637fcac036aae538cf3e0500c2c054b49c7；count=1
## 过程
执行最小改动。
## 遇到的问题
无。
## 解决方式
按任务书实现。
## 遗留风险与建议
无已知风险。
"""

sys.path.insert(0, str(SCRIPT_DIR))

import dispatch_registry  # noqa: E402
import launch_description  # noqa: E402
import run_concurrency  # noqa: E402
import execution_backend  # noqa: E402
import runtime_provider  # noqa: E402


def load_runtime_module():
    spec = importlib.util.spec_from_file_location("orchestration_agent_runtime", RUNTIME)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {RUNTIME}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def valid_description(**overrides):
    values = dict(
        provider="claude",
        provider_source="explicit",
        effort="high",
        report_relative_path=".codex-agent/slug.last.md",
        command_sha256="a" * 64,
        profile_arguments_sha256=None,
        execution_binding_sha256="b" * 64,
        task_id="T01",
        base_commit="fixture",
        report_contract={
            "schema": "sulde-worker-report-v1",
            "headings": ["结果", "过程"],
            "evidence_schema": "evidence-template",
        },
        dependency_checks=[
            {"name": "report_location", "evidence": "state directory writable"},
            {"name": "report_contract", "evidence": "2 headings"},
            {"name": "provider_executable", "evidence": "resolved"},
        ],
    )
    values.update(overrides)
    return launch_description.build_launch_description(**values)


class LaunchDescriptionTests(unittest.TestCase):
    def test_artifact_roundtrip_and_digest_stability(self) -> None:
        description = valid_description()
        payload, digest = launch_description.launch_description_artifact(description)
        parsed, parsed_digest = launch_description.parse_launch_description_artifact(
            payload
        )
        self.assertEqual(parsed, description)
        self.assertEqual(parsed_digest, digest)
        again, again_digest = launch_description.launch_description_artifact(
            description
        )
        self.assertEqual(again_digest, digest)
        self.assertEqual(again, payload)

    def test_tampered_artifact_is_rejected(self) -> None:
        description = valid_description()
        payload, digest = launch_description.launch_description_artifact(description)
        tampered = json.loads(payload.decode("utf-8"))
        tampered["description"]["effort"] = "low"
        encoded = json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
        with self.assertRaises(launch_description.LaunchDescriptionError):
            launch_description.parse_launch_description_artifact(encoded)

    def test_field_validation_rejects_bad_inputs(self) -> None:
        with self.assertRaises(launch_description.LaunchDescriptionError):
            valid_description(provider="auto")
        with self.assertRaises(launch_description.LaunchDescriptionError):
            valid_description(command_sha256="short")
        with self.assertRaises(launch_description.LaunchDescriptionError):
            valid_description(effort="ultra")
        with self.assertRaises(launch_description.LaunchDescriptionError):
            valid_description(
                dependency_checks=[
                    {"name": "report_location", "evidence": "x"},
                    {"name": "report_location", "evidence": "y"},
                ]
            )
        with self.assertRaises(launch_description.LaunchDescriptionError):
            valid_description(
                report_contract={
                    "schema": "s",
                    "headings": [],
                    "evidence_schema": "e",
                }
            )

    def test_preflight_detects_symlinked_report_without_model_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            outside = Path(directory) / "outside.md"
            outside.write_text("x", encoding="utf-8")
            planned = state_dir / "slug.last.md"
            planned.symlink_to(outside)
            with self.assertRaises(launch_description.LaunchPreflightError) as ctx:
                launch_description.preflight_launch_description(
                    {
                        "provider": "claude",
                        "report_relative_path": "state/slug.last.md",
                        "report_contract": {
                            "schema": "s",
                            "headings": ["结果"],
                            "evidence_schema": "e",
                        },
                    },
                    state_dir=state_dir,
                    provider_executable_evidence="resolved",
                )
            checks = {row["check"] for row in ctx.exception.failures}
            self.assertIn("report_location", checks)

    def test_preflight_detects_unresolvable_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            with self.assertRaises(launch_description.LaunchPreflightError):
                launch_description.preflight_launch_description(
                    {
                        "provider": "claude",
                        "report_relative_path": "state/slug.last.md",
                        "report_contract": {
                            "schema": "s",
                            "headings": ["结果"],
                            "evidence_schema": "e",
                        },
                    },
                    state_dir=state_dir,
                    provider_executable_evidence="",
                )

    def test_preflight_success_returns_evidence_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            evidence = launch_description.preflight_launch_description(
                {
                    "provider": "claude",
                    "report_relative_path": "state/slug.last.md",
                    "report_contract": {
                        "schema": "s",
                        "headings": ["结果"],
                        "evidence_schema": "e",
                    },
                },
                state_dir=state_dir,
                provider_executable_evidence="resolved",
            )
            names = {row["name"] for row in evidence}
            self.assertEqual(
                names, {"report_location", "report_contract", "provider_executable"}
            )
            self.assertFalse(
                list(state_dir.glob(".launch-preflight-report-probe*")),
                "probe file must be cleaned up",
            )

    def test_failure_evidence_shape(self) -> None:
        error = launch_description.LaunchPreflightError(
            "blocked", [{"check": "report_location", "reason": "nope"}]
        )
        evidence = launch_description.preflight_failure_evidence("slug", error)
        self.assertEqual(evidence["schema"], "sulde-launch-preflight-failure-v1")
        self.assertEqual(evidence["slug"], "slug")
        self.assertEqual(evidence["failures"][0]["check"], "report_location")


class DispatchRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.registry = Path(self._temporary.name) / "slug.dispatch.jsonl"

    def test_completed_request_returns_existing_result_never_reexecutes(self) -> None:
        first = dispatch_registry.open_request(
            self.registry,
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
        )
        self.assertTrue(first["created"])
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=1, run_id="run-" + "a" * 24
        )
        dispatch_registry.record_closed(
            self.registry,
            request_id="req-1",
            attempt=1,
            run_id="run-" + "a" * 24,
            outcome="terminal",
            stop_reason="completed",
        )
        # R1-04: completion does not invalidate idempotency — the duplicate
        # resolves to the original attempt, and there is no retry path for a
        # completed request.
        duplicate = dispatch_registry.open_request(
            self.registry,
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
        )
        self.assertFalse(duplicate["created"])
        self.assertEqual(duplicate["state"], "closed")
        self.assertEqual(duplicate["stop_reason"], "completed")
        self.assertEqual(duplicate["run_id"], "run-" + "a" * 24)
        with self.assertRaises(dispatch_registry.DispatchRegistryError):
            dispatch_registry.open_retry(
                self.registry,
                retry_op_id="op-1",
                request_id="req-1",
                request_sha256="a" * 64,
                slug="slug",
                from_run_id="run-" + "a" * 24,
            )

    def test_retryable_terminal_attempt_gets_linked_new_attempt(self) -> None:
        dispatch_registry.open_request(
            self.registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
        )
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=1, run_id="run-" + "a" * 24
        )
        dispatch_registry.record_closed(
            self.registry,
            request_id="req-1",
            attempt=1,
            run_id="run-" + "a" * 24,
            outcome="terminal",
            stop_reason="timeout",
        )
        retry = dispatch_registry.open_retry(
            self.registry,
            retry_op_id="op-1",
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
            from_run_id="run-" + "a" * 24,
        )
        self.assertTrue(retry["created"])
        self.assertEqual(retry["attempt"], 2)
        self.assertEqual(retry["retries_of_run_id"], "run-" + "a" * 24)
        self.assertTrue(dispatch_registry.retryable("timeout"))
        # awaiting_human is a human gate: never auto-retried.
        self.assertFalse(dispatch_registry.retryable("awaiting_human"))
        self.assertFalse(dispatch_registry.retryable("completed"))
        # R3-04: the SAME retry operation is idempotent even after its own
        # attempt failed — resolving it never advances the chain.
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=2, run_id="run-" + "c" * 24
        )
        dispatch_registry.record_closed(
            self.registry,
            request_id="req-1",
            attempt=2,
            run_id="run-" + "c" * 24,
            outcome="terminal",
            stop_reason="timeout",
        )
        repeat = dispatch_registry.open_retry(
            self.registry,
            retry_op_id="op-1",
            request_id="req-1",
            request_sha256="a" * 64,
            slug="slug",
            from_run_id="run-" + "a" * 24,
        )
        self.assertFalse(repeat["created"])
        self.assertEqual(repeat["attempt"], 2)

    def test_same_request_resumes_existing_attempt(self) -> None:
        dispatch_registry.open_request(
            self.registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
        )
        resumed = dispatch_registry.open_request(
            self.registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
        )
        self.assertFalse(resumed["created"])
        self.assertEqual(resumed["state"], "opened")

    def test_same_id_different_content_is_a_hard_conflict(self) -> None:
        dispatch_registry.open_request(
            self.registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
        )
        with self.assertRaises(dispatch_registry.DispatchConflictError):
            dispatch_registry.open_request(
                self.registry,
                request_id="req-1",
                request_sha256="b" * 64,
                slug="slug",
            )

    def test_launched_requires_opened_and_is_run_bound(self) -> None:
        with self.assertRaises(dispatch_registry.DispatchRegistryError):
            dispatch_registry.record_launched(
                self.registry,
                request_id="req-x",
                attempt=1,
                run_id="run-" + "a" * 24,
            )
        dispatch_registry.open_request(
            self.registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
        )
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=1, run_id="run-" + "a" * 24
        )
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=1, run_id="run-" + "a" * 24
        )
        with self.assertRaises(dispatch_registry.DispatchRegistryError):
            dispatch_registry.record_launched(
                self.registry, request_id="req-1", attempt=1, run_id="run-" + "b" * 24
            )

    def test_close_validates_run_and_outcome(self) -> None:
        dispatch_registry.open_request(
            self.registry, request_id="req-1", request_sha256="a" * 64, slug="slug"
        )
        dispatch_registry.record_launched(
            self.registry, request_id="req-1", attempt=1, run_id="run-" + "b" * 24
        )
        with self.assertRaises(dispatch_registry.DispatchRegistryError):
            dispatch_registry.record_closed(
                self.registry,
                request_id="req-1",
                attempt=1,
                run_id="run-" + "c" * 24,
                outcome="terminal",
            )
        with self.assertRaises(dispatch_registry.DispatchRegistryError):
            dispatch_registry.record_closed(
                self.registry,
                request_id="req-1",
                attempt=1,
                run_id="run-" + "b" * 24,
                outcome="exploded",
            )
        dispatch_registry.record_closed(
            self.registry,
            request_id="req-1",
            attempt=1,
            run_id="run-" + "b" * 24,
            outcome="terminal",
            stop_reason="completed",
        )
        segment = dispatch_registry.lookup(self.registry, "req-1")
        self.assertEqual(segment["state"], "closed")
        self.assertEqual(segment["stop_reason"], "completed")
        # A closed attempt is never closed twice into a new row.
        dispatch_registry.record_closed(
            self.registry,
            request_id="req-1",
            attempt=1,
            run_id="run-" + "b" * 24,
            outcome="terminal",
            stop_reason="completed",
        )
        rows = dispatch_registry.read_registry(self.registry)
        self.assertEqual(
            sum(
                1
                for row in rows
                if row["type"] == "dispatch.closed" and row["request_id"] == "req-1"
            ),
            1,
        )

    def test_different_slug_sharing_a_request_id_conflicts(self) -> None:
        dispatch_registry.open_request(
            self.registry, request_id="req-1", request_sha256="a" * 64, slug="slug-a"
        )
        with self.assertRaises(dispatch_registry.DispatchConflictError):
            dispatch_registry.open_request(
                self.registry,
                request_id="req-1",
                request_sha256="a" * 64,
                slug="slug-b",
            )

    def test_torn_tail_fails_closed(self) -> None:
        self.registry.parent.mkdir(parents=True, exist_ok=True)
        self.registry.write_bytes(b'{"schema": "x"}\n{"sch')
        with self.assertRaises(dispatch_registry.DispatchRegistryError):
            dispatch_registry.read_registry(self.registry)

    def test_derived_request_id_is_deterministic(self) -> None:
        first = dispatch_registry.derive_request_id("managed-run", "slug", "d" * 64)
        second = dispatch_registry.derive_request_id("managed-run", "slug", "d" * 64)
        third = dispatch_registry.derive_request_id("managed-run", "slug", "e" * 64)
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)
        self.assertRegex(first, r"^req-[0-9a-f]{24}$")


class RunConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.state_dir = Path(self._temporary.name) / "state"
        self.state_dir.mkdir()

    def test_acquire_release_cycle(self) -> None:
        lease = run_concurrency.acquire_run_slot(
            self.state_dir, max_concurrent=1, timeout_seconds=1.0
        )
        self.assertTrue(lease.held)
        self.assertTrue(lease.path.is_file())
        lease.release()
        self.assertFalse(lease.held)
        self.assertFalse(lease.path.exists())
        lease.release()  # idempotent

    def test_limit_is_bounded_and_fail_closed(self) -> None:
        lease = run_concurrency.acquire_run_slot(
            self.state_dir, max_concurrent=1, timeout_seconds=0.0
        )
        try:
            with self.assertRaises(run_concurrency.RunConcurrencyLimitError):
                run_concurrency.acquire_run_slot(
                    self.state_dir, max_concurrent=1, timeout_seconds=0.2
                )
        finally:
            lease.release()

    def test_stale_lease_from_dead_process_is_pruned(self) -> None:
        stale_path = (
            self.state_dir
            / "run-leases"
            / "999999-deadbeef.lease"
        )
        stale_path.parent.mkdir(parents=True, exist_ok=True)
        stale_path.write_text("{}", encoding="utf-8")
        lease = run_concurrency.acquire_run_slot(
            self.state_dir, max_concurrent=1, timeout_seconds=1.0
        )
        try:
            self.assertFalse(stale_path.exists(), "unlocked lease must be pruned")
        finally:
            lease.release()

    def test_environment_override_is_validated(self) -> None:
        self.assertEqual(
            run_concurrency.max_concurrent_runs({}), run_concurrency.DEFAULT_MAX_CONCURRENT_RUNS
        )
        self.assertEqual(
            run_concurrency.max_concurrent_runs({"SULDE_MAX_CONCURRENT_RUNS": "2"}), 2
        )
        with self.assertRaises(run_concurrency.RunConcurrencyError):
            run_concurrency.max_concurrent_runs({"SULDE_MAX_CONCURRENT_RUNS": "zero"})
        with self.assertRaises(run_concurrency.RunConcurrencyError):
            run_concurrency.max_concurrent_runs({"SULDE_MAX_CONCURRENT_RUNS": "0"})


class LedgerEmbeddingTests(unittest.TestCase):
    def test_replay_accepts_embedded_launch_description_digest(self) -> None:
        rows = (
            json.dumps(
                {
                    "schema": "sulde-run-event-v1",
                    "at": "2026-09-25T00:00:00+00:00",
                    "run_id": "run-" + "a" * 24,
                    "provider": "codex",
                    "type": "execution.requested",
                    "command_sha256": "a" * 64,
                    "workspace_id": "sha256:" + "b" * 24,
                    "parent_death_watchdog": True,
                    "launch_description_sha256": "c" * 64,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode()
        path = Path(tempfile.mkdtemp()) / "run.jsonl"
        path.write_bytes(rows)
        projection = execution_backend.replay_run_ledger(path)
        self.assertIsNotNone(projection)

    def test_replay_rejects_invalid_embedded_digest(self) -> None:
        rows = (
            json.dumps(
                {
                    "schema": "sulde-run-event-v1",
                    "at": "2026-09-25T00:00:00+00:00",
                    "run_id": "run-" + "a" * 24,
                    "provider": "codex",
                    "type": "execution.requested",
                    "command_sha256": "a" * 64,
                    "workspace_id": "sha256:" + "b" * 24,
                    "parent_death_watchdog": True,
                    "launch_description_sha256": "not-a-digest",
                },
                sort_keys=True,
            )
            + "\n"
        ).encode()
        path = Path(tempfile.mkdtemp()) / "run.jsonl"
        path.write_bytes(rows)
        with self.assertRaises(execution_backend.ExecutionBackendError):
            execution_backend.replay_run_ledger(path)

    def test_legacy_ledger_without_digest_still_replays(self) -> None:
        rows = (
            json.dumps(
                {
                    "schema": "sulde-run-event-v1",
                    "at": "2026-09-25T00:00:00+00:00",
                    "run_id": "run-" + "a" * 24,
                    "provider": "codex",
                    "type": "execution.requested",
                    "command_sha256": "a" * 64,
                    "workspace_id": "sha256:" + "b" * 24,
                    "parent_death_watchdog": True,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode()
        path = Path(tempfile.mkdtemp()) / "run.jsonl"
        path.write_bytes(rows)
        projection = execution_backend.replay_run_ledger(path)
        self.assertIsNotNone(projection)


class ManagedRunProviderTests(unittest.TestCase):
    def test_production_codex_host_shortcut_skips_path(self) -> None:
        environment = {
            "CODEX_THREAD_ID": "thread-1",
            "PATH": "",
        }
        provider, executable = runtime_provider.resolve_managed_run_provider(
            None, environment=environment, which=lambda name: None, test_mode=False
        )
        self.assertEqual((provider, executable), ("codex", ""))

    def test_explicit_unavailable_provider_never_falls_back(self) -> None:
        environment = {"PATH": ""}
        with self.assertRaises(runtime_provider.ProviderError):
            runtime_provider.resolve_managed_run_provider(
                "claude", environment=environment, which=lambda name: None
            )

    def test_agent_provider_env_is_part_of_the_single_chain(self) -> None:
        environment = {
            "SULDE_AGENT_PROVIDER": "claude",
            "PATH": "",
        }
        with mock.patch.object(
            runtime_provider,
            "resolve_executable",
            return_value="/tmp/claude-fixture",
        ) as resolver:
            provider, executable = runtime_provider.resolve_managed_run_provider(
                None, environment=environment, which=lambda name: None
            )
        self.assertEqual(provider, "claude")
        self.assertEqual(executable, "/tmp/claude-fixture")
        resolver.assert_called_once()


class CliIntegrationTests(unittest.TestCase):
    """Integration through the real CLI entry, zero paid model calls."""

    def setUp(self) -> None:
        self.environment_patch = mock.patch.dict(
            os.environ,
            {
                "SULDE_TEST_MODE": "1",
                "SULDE_INTENT_CONTRACT": "",
                "SULDE_GUARDIAN_STREAM_OWNER": "",
                "SULDE_GUARDIAN_STREAM_PROVIDER": "",
            },
            clear=False,
        )
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)

    def temporary_directory(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory()

    def prepare(self, directory: Path, slug: str) -> tuple[Path, Path]:
        worktree = directory / "worktree"
        state = worktree / ".codex-agent"
        state.mkdir(parents=True)
        (worktree / "base.txt").write_text("base\n", encoding="utf-8")
        brief = state / f"{slug}.md"
        brief.write_text("# Task\n\nDo the work.\n", encoding="utf-8")
        brief.chmod(0o400)
        return worktree, brief

    def write_provider_executable(
        self, directory: Path, name: str = "codex", *, sleep_seconds: int = 0
    ) -> Path:
        executable = directory / name
        executable.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/python3
                import sys, time
                from pathlib import Path
                args = sys.argv[1:]
                if {sleep_seconds}:
                    time.sleep({sleep_seconds})
                report = Path(args[args.index('--output-last-message') + 1])
                report.write_text({REPORT!r}, encoding='utf-8')
                print('{{"type":"done"}}')
                """
            ),
            encoding="utf-8",
        )
        executable.chmod(0o755)
        return executable

    def test_preflightable_report_conflict_fails_before_any_provider_launch(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "preflight-symlink")
            executable = self.write_provider_executable(directory)
            outside = directory / "outside.md"
            outside.write_text("x", encoding="utf-8")
            planned_report = worktree / ".codex-agent/preflight-symlink.last.md"
            planned_report.symlink_to(outside)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "preflight-symlink",
                    str(brief),
                    "--timeout",
                    "5",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
            evidence_path = worktree / ".codex-agent/preflight-symlink.launch-preflight.json"
            self.assertTrue(evidence_path.is_file(), "failure evidence must be persisted")
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(evidence["schema"], "sulde-launch-preflight-failure-v1")
            self.assertTrue(
                any(row["check"] == "report_location" for row in evidence["failures"])
            )
            self.assertFalse(
                (worktree / ".codex-agent/preflight-symlink.run.jsonl").is_file(),
                "no provider process may be launched after a preflight failure",
            )
            self.assertIn("report_location", completed.stderr)

    def test_concurrent_same_slug_submission_produces_one_effective_launch(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "concurrent")
            executable = self.write_provider_executable(
                directory, sleep_seconds=3
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )
            first = subprocess.Popen(
                [
                    sys.executable,
                    str(RUNTIME),
                    "run",
                    str(worktree),
                    "concurrent",
                    str(brief),
                    "--timeout",
                    "20",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                ledger = worktree / ".codex-agent/concurrent.run.jsonl"
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if ledger.is_file() and "execution.started" in ledger.read_text(
                        errors="replace"
                    ):
                        break
                    if first.poll() is not None:
                        break
                    time.sleep(0.02)
                self.assertIsNone(
                    first.poll(), "first run ended before the duplicate submission"
                )
                second = subprocess.run(
                    [
                        sys.executable,
                        str(RUNTIME),
                        "run",
                        str(worktree),
                        "concurrent",
                        str(brief),
                        "--timeout",
                        "20",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=environment,
                    check=False,
                    timeout=30,
                )
                self.assertEqual(
                    second.returncode,
                    2,
                    "duplicate submission must be rejected while one launch is active: "
                    + second.stdout
                    + second.stderr,
                )
                self.assertIn("task lock is already held", second.stderr)
            finally:
                stdout, stderr = first.communicate(timeout=40)
            self.assertEqual(first.returncode, 0, stdout + stderr)
            status = (worktree / ".codex-agent/concurrent.status").read_text()
            self.assertTrue(status.startswith("status=success "), status)
            launched_rows = [
                json.loads(line)
                for line in (
                    worktree / ".codex-agent/concurrent.dispatch.jsonl"
                ).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            launched = [row for row in launched_rows if row["type"] == "dispatch.launched"]
            self.assertEqual(
                len(launched), 1, "exactly one effective launch for the same request"
            )

    def test_successful_run_embeds_description_digest_and_allows_retry(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "embed")
            executable = self.write_provider_executable(directory)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )
            run_command = [
                sys.executable,
                str(RUNTIME),
                "run",
                str(worktree),
                "embed",
                str(brief),
                "--timeout",
                "15",
            ]
            completed = subprocess.run(
                run_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
                timeout=40,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            state = worktree / ".codex-agent"
            description_artifact = json.loads(
                (state / "embed.launch.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                description_artifact["schema"], "sulde-launch-description-artifact-v1"
            )
            embedded_digest = description_artifact["description_sha256"]
            first_ledger_row = json.loads(
                (state / "embed.run.jsonl").read_text(encoding="utf-8").splitlines()[0]
            )
            self.assertEqual(
                first_ledger_row.get("launch_description_sha256"), embedded_digest
            )
            self.assertEqual(
                first_ledger_row["command_sha256"],
                description_artifact["description"]["command_sha256"],
            )
            registry_rows = [
                json.loads(line)
                for line in (state / "embed.dispatch.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                [row["type"] for row in registry_rows],
                ["dispatch.opened", "dispatch.launched", "dispatch.closed"],
            )
            # R1-04: an identical resubmission after completion returns the
            # original result instead of re-executing — one request, one
            # effective launch, duplicates included.
            retry = subprocess.run(
                run_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
                timeout=40,
            )
            self.assertEqual(retry.returncode, 0, retry.stdout + retry.stderr)
            self.assertIn("duplicate_of_run", retry.stdout)
            self.assertFalse(
                (state / "embed.round1.run.jsonl").is_file(),
                "a completed request duplicate must not launch a new round",
            )
            retry_rows = [
                json.loads(line)
                for line in (state / "embed.dispatch.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(
                [row["type"] for row in retry_rows],
                ["dispatch.opened", "dispatch.launched", "dispatch.closed"],
                "the duplicate must not append new dispatch rows",
            )

    def test_explicit_request_id_with_changed_content_conflicts_before_launch(self) -> None:
        with self.temporary_directory() as directory_name:
            directory = Path(directory_name)
            worktree, brief = self.prepare(directory, "conflict")
            executable = self.write_provider_executable(directory)
            environment = os.environ.copy()
            environment.update(
                {
                    "SULDE_AGENT_PROVIDER": "codex",
                    "SULDE_CODEX_EXE": str(executable),
                }
            )
            base_command = [
                sys.executable,
                str(RUNTIME),
                "run",
                str(worktree),
                "conflict",
                str(brief),
                "--request-id",
                "req-contract-check",
                "--timeout",
                "15",
            ]
            completed = subprocess.run(
                base_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
                timeout=40,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            conflicting = subprocess.run(
                [*base_command, "--effort", "low"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=environment,
                check=False,
                timeout=40,
            )
            self.assertEqual(
                conflicting.returncode,
                2,
                "same request id with different content must be a hard conflict: "
                + conflicting.stdout
                + conflicting.stderr,
            )
            # Either the launch-description drift check or the dispatch
            # registry conflict rejects it; both happen before any launch.
            self.assertTrue(
                "launch description changed" in conflicting.stderr
                or "different content" in conflicting.stderr,
                conflicting.stderr,
            )
            self.assertFalse(
                (worktree / ".codex-agent/conflict.round1.run.jsonl").is_file(),
                "conflicting resubmission must not launch a provider process",
            )


if __name__ == "__main__":
    unittest.main()

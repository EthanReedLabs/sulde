from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kb" / "run-isolated-tests.py"


def load_module():
    spec = importlib.util.spec_from_file_location("sulde_isolated_test_runner", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IsolatedTestRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.managed_environment = mock.patch.dict(
            os.environ,
            {
                "SULDE_INTENT_CONTRACT": "",
                "SULDE_GUARDIAN_STREAM_OWNER": "",
                "SULDE_GUARDIAN_STREAM_PROVIDER": "",
            },
            clear=False,
        )
        self.managed_environment.start()
        self.addCleanup(self.managed_environment.stop)

    @staticmethod
    def _legacy_observation(host, *, hook_event: str, session_id: str) -> dict[str, object]:
        specification = next(
            item
            for item in host.capability_specs("codex")
            if hook_event in item.hook_events
        )
        row: dict[str, object] = {
            "schema": host.OBSERVATION_SCHEMA,
            "contract_version": host.CONTRACT_VERSION,
            "at": datetime.now(timezone.utc).isoformat(),
            "provider": "codex",
            "runtime_sha256": host.runtime_identity("codex"),
            "session_id": session_id,
            "workspace_id": host.workspace_identifier(ROOT),
            "capability_id": specification.capability_id,
            "hook_event": hook_event,
            "source": "live_host_hook",
            "outcome": "observed",
        }
        row["event_id"] = hashlib.sha256(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return row

    def test_environment_rehomes_every_persistent_test_surface(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            production = root / "production-kb"
            environment = module.isolated_environment(
                root / "isolated",
                production_kb=production,
                inherited={
                    "PATH": "/fixture/bin",
                    "CODEX_THREAD_ID": "real-thread",
                    "CLAUDE_SESSION_ID": "real-session",
                    "SULDE_INTENT_CONTRACT": "/production/contract.json",
                    "LLM_API_KEY": "must-not-leak",
                    "GITHUB_TOKEN": "must-not-leak",
                },
            )

        self.assertEqual(environment["SULDE_TEST_MODE"], "1")
        self.assertEqual(environment["SULDE_PRODUCTION_KB_HOME"], str(production))
        self.assertNotEqual(environment["SULDE_KB_HOME"], str(production))
        self.assertNotEqual(environment["HOME"], str(Path.home()))
        self.assertTrue(environment["CODEX_HOME"].endswith("codex-home"))
        self.assertTrue(environment["CLAUDE_CONFIG_DIR"].endswith("claude-home"))
        self.assertEqual(environment["SULDE_HOOK_OBSERVATION_SOURCE"], "synthetic_smoke")
        self.assertEqual(
            environment["SULDE_ISOLATED_TEST_PRODUCTION_ROOT"],
            str(production),
        )
        self.assertRegex(environment["SULDE_ISOLATED_TEST_RUN_ID"], r"^[0-9a-f]{32}$")
        self.assertTrue(
            environment["SULDE_ISOLATED_TEST_VIOLATION_LOG"].endswith(
                "production-write-attempts.jsonl"
            )
        )
        self.assertIn("process-guard", environment["PYTHONPATH"])
        self.assertNotIn("CODEX_THREAD_ID", environment)
        self.assertNotIn("CLAUDE_SESSION_ID", environment)
        self.assertNotIn("SULDE_INTENT_CONTRACT", environment)
        self.assertNotIn("LLM_API_KEY", environment)
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertTrue(environment["TMPDIR"].endswith("tmp"))
        self.assertTrue(environment["XDG_CONFIG_HOME"].endswith("xdg-config"))
        self.assertTrue(environment["PYTHONPYCACHEPREFIX"].endswith("pycache"))

    def test_entrypoint_disables_bytecode_before_sibling_imports(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            kb = root / "scripts" / "kb"
            kb.mkdir(parents=True)
            for source in (SCRIPT, SCRIPT.with_name("audit_cursor.py"), SCRIPT.with_name("sulde_paths.py")):
                shutil.copy2(source, kb / source.name)
            environment = dict(os.environ)
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            environment.pop("PYTHONPYCACHEPREFIX", None)
            completed = subprocess.run(
                [sys.executable, str(kb / SCRIPT.name), "--help"],
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(list(kb.rglob("__pycache__")), [])
            self.assertEqual(list(kb.rglob("*.pyc")), [])

    def test_production_snapshot_detects_same_size_rewrite(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            target = root / "host-capabilities.jsonl"
            target.write_text("before\n", encoding="utf-8")
            before = module.filesystem_snapshot(root)
            target.write_text("after!\n", encoding="utf-8")
            after = module.filesystem_snapshot(root)

        self.assertNotEqual(before, after)

    def test_command_supports_discovery_and_targeted_runs(self) -> None:
        module = load_module()
        discovery = module.unittest_command([], start="tests", pattern="test_*.py")
        targeted = module.unittest_command(
            ["test_host_capabilities.HostCapabilityTests"],
            start="ignored",
            pattern="ignored",
        )

        self.assertIn("discover", discovery)
        self.assertEqual(targeted[-1], "test_host_capabilities.HostCapabilityTests")
        self.assertNotIn("discover", targeted)

    def test_process_guard_reports_a_caught_production_write_attempt(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            production = root / "production-kb"
            production.mkdir()
            protected = production / "protected.jsonl"
            protected.write_text("before\n", encoding="utf-8")
            environment = module.isolated_environment(
                root / "isolated",
                production_kb=production,
                inherited={"PATH": os.environ.get("PATH", "")},
            )
            script = """
import os
from pathlib import Path

target = Path(os.environ["SULDE_PRODUCTION_KB_HOME"]) / "protected.jsonl"
try:
    target.write_text("after\\n", encoding="utf-8")
except PermissionError:
    pass
else:
    raise SystemExit(9)
"""
            completed = subprocess.run(
                [sys.executable, "-c", script],
                env=environment,
                cwd=ROOT,
                check=False,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            violations = module.process_guard_violations(environment)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(protected.read_text(encoding="utf-8"), "before\n")
            self.assertEqual(len(violations), 1)
            self.assertEqual(
                violations[0]["run_id"],
                environment["SULDE_ISOLATED_TEST_RUN_ID"],
            )
            self.assertEqual(violations[0]["event"], "open")
            self.assertGreater(int(violations[0]["pid"]), 0)

    def test_runner_exits_three_even_when_test_catches_the_guard_denial(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            production = Path(directory_name) / "production-kb"
            production.mkdir()
            protected = production / "protected.jsonl"
            protected.write_text("before\n", encoding="utf-8")
            script = """
import os
from pathlib import Path

target = Path(os.environ["SULDE_PRODUCTION_KB_HOME"]) / "protected.jsonl"
try:
    target.write_text("after\\n", encoding="utf-8")
except PermissionError:
    pass
"""
            stderr = io.StringIO()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SULDE_PRODUCTION_KB_HOME": str(production),
                        "SULDE_AUDIT_CURSOR_HOME": str(
                            Path(directory_name) / "cursors"
                        ),
                    },
                    clear=False,
                ),
                mock.patch.object(
                    module,
                    "unittest_command",
                    return_value=[sys.executable, "-c", script],
                ),
                mock.patch.object(
                    module,
                    "os_isolated_test_command",
                    side_effect=lambda command, _production: command,
                ),
                mock.patch.object(module, "preflight_os_test_isolation"),
                mock.patch.object(
                    sys,
                    "argv",
                    [str(SCRIPT), "--production-diagnostics"],
                ),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 3)
            self.assertEqual(protected.read_text(encoding="utf-8"), "before\n")
            self.assertIn("test subprocess attempted 1 production KB write", stderr.getvalue())

    def test_verified_native_boundary_separates_external_concurrency_from_test_writes(
        self,
    ) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            production = Path(directory_name) / "production-kb"
            production.mkdir()
            stderr = io.StringIO()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SULDE_PRODUCTION_KB_HOME": str(production),
                        "SULDE_AUDIT_CURSOR_HOME": str(
                            Path(directory_name) / "cursors"
                        ),
                    },
                    clear=False,
                ),
                mock.patch.object(module, "preflight_os_test_isolation"),
                mock.patch.object(module, "filesystem_snapshot", return_value=()),
                mock.patch.object(
                    module,
                    "_observation_baseline",
                    return_value={"valid": True},
                ),
                mock.patch.object(
                    module,
                    "_guardian_baseline",
                    return_value={"valid": True},
                ),
                mock.patch.object(
                    module,
                    "os_isolated_test_command",
                    side_effect=lambda command, _production: command,
                ),
                mock.patch.object(
                    module,
                    "unittest_command",
                    return_value=[sys.executable, "-c", "raise SystemExit(0)"],
                ),
                mock.patch.object(module, "process_guard_violations", return_value=[]),
                mock.patch.object(
                    module,
                    "production_mutation_verdict",
                    return_value=(
                        False,
                        0,
                        "production KB changed outside attributable host state: other-session",
                    ),
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    [str(SCRIPT), "--production-diagnostics"],
                ),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = module.main()

            self.assertEqual(exit_code, 0)
            self.assertIn("concurrent external production state", stderr.getvalue())

    def test_default_code_evidence_does_not_snapshot_ambient_production_state(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            production = Path(directory_name) / "production-kb"
            production.mkdir()
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "SULDE_PRODUCTION_KB_HOME": str(production),
                        "SULDE_AUDIT_CURSOR_HOME": str(Path(directory_name) / "cursors"),
                    },
                    clear=False,
                ),
                mock.patch.object(module, "preflight_os_test_isolation"),
                mock.patch.object(
                    module,
                    "os_isolated_test_command",
                    side_effect=lambda command, _production: command,
                ),
                mock.patch.object(
                    module,
                    "unittest_command",
                    return_value=[sys.executable, "-c", "raise SystemExit(0)"],
                ),
                mock.patch.object(module, "process_guard_violations", return_value=[]),
                mock.patch.object(
                    module,
                    "filesystem_snapshot",
                    side_effect=AssertionError("ambient tree entered code evidence"),
                ),
                mock.patch.object(
                    module,
                    "production_mutation_verdict",
                    side_effect=AssertionError("ambient verdict entered code evidence"),
                ),
                mock.patch.object(sys, "argv", [str(SCRIPT)]),
            ):
                self.assertEqual(module.main(), 0)

    def test_only_fresh_signed_append_is_accepted_as_concurrent_host_work(self) -> None:
        module = load_module()
        host = module._host_capabilities_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            production = root / "production-kb"
            production.mkdir()
            host.provision_provenance_key(production)
            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            proof = host.issue_host_provenance(
                provider="codex",
                hook_event="PreToolUse",
                session_id="concurrent-host-session",
                workspace=ROOT,
                source="live_host_hook",
                home=production,
            )
            host.record_observation(
                provider="codex",
                hook_event="PreToolUse",
                session_id="concurrent-host-session",
                workspace=ROOT,
                source="live_host_hook",
                home=production,
                provenance=proof,
            )
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
            )

            self.assertNotEqual(before_filesystem, after_filesystem)
            self.assertTrue(safe, reason)
            self.assertEqual(accepted, 1)

            # Signed source appends cannot excuse an arbitrary cache mutation.
            index = next((production / "host-capability-index").glob("*.json"))
            index.write_text("{}", encoding="utf-8")
            safe, _accepted, _reason = module.production_mutation_verdict(
                production, before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=module.filesystem_snapshot(production),
                started_at=started_at, ended_at=ended_at,
            )
            self.assertFalse(safe)

    def test_unsigned_observation_append_is_not_ignored(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            production = root / "production-kb"
            production.mkdir()
            log = production / "host-capabilities.jsonl"
            log.touch(mode=0o600)
            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"source": "live_host_hook"}) + "\n")
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
            )

            self.assertFalse(safe)
            self.assertEqual(accepted, 0)
            self.assertIn("not trusted live evidence", reason)

    def test_legacy_append_requires_parent_session_workspace_and_runtime_continuity(
        self,
    ) -> None:
        module = load_module()
        host = module._host_capabilities_module()
        with tempfile.TemporaryDirectory() as directory_name:
            production = Path(directory_name) / "production-kb"
            production.mkdir()
            log = production / "host-capabilities.jsonl"
            log.write_text(
                json.dumps(
                    self._legacy_observation(
                        host,
                        hook_event="UserPromptSubmit",
                        session_id="parent-session",
                    ),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            log.chmod(0o600)
            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        self._legacy_observation(
                            host,
                            hook_event="PreToolUse",
                            session_id="parent-session",
                        ),
                        sort_keys=True,
                    )
                    + "\n"
                )
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
                parent_host_sessions={"codex": "parent-session"},
                expected_workspace=ROOT,
            )

            self.assertTrue(safe, reason)
            self.assertEqual(accepted, 1)

            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        self._legacy_observation(
                            host,
                            hook_event="PostToolUse",
                            session_id="different-session",
                        ),
                        sort_keys=True,
                    )
                    + "\n"
                )
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
                parent_host_sessions={"codex": "parent-session"},
                expected_workspace=ROOT,
            )

            self.assertFalse(safe)
            self.assertEqual(accepted, 0)
            self.assertIn("lacks attributable provenance", reason)

    def test_parent_guardian_read_projection_is_attributed_but_direct_contract_write_fails(
        self,
    ) -> None:
        module = load_module()
        guardian = module._intent_guardian_module()
        with tempfile.TemporaryDirectory() as directory_name:
            production = Path(directory_name) / "production-kb"
            relative = module._guardian_relative_paths(ROOT)
            contract_path = production / relative["contract"]
            contract = guardian.default_contract(
                intent_id="isolated-runner-parent-guard",
                objective="verify parent hook attribution",
                rationale="test fixture",
                acceptance_criteria=["read-only parent events are replayable"],
                workspace=ROOT,
                mode="enforce",
                preserve=["production state"],
                reject=["test writes"],
                allowed_paths=["**"],
                confirmed_by="human",
            )
            guardian.write_contract(contract_path, contract)
            monitor = guardian.GuardianSession(
                contract_path,
                provider="codex",
                session_id="parent-session",
            )

            def observe_read(phase: str) -> None:
                event = guardian.normalize_hook_event(
                    {
                        "client": "codex",
                        "session_id": "parent-session",
                        "cwd": str(ROOT),
                        "tool_name": "Read",
                        "tool_input": {"path": str(ROOT / "README.md")},
                        "success": True,
                        "call_id": "parent-poll",
                    },
                    phase=phase,
                    provider="codex",
                )
                decision = monitor.observe(event)
                self.assertEqual(decision.action, "allow")

            def observe_unknown_completion(phase: str, call_id: str) -> None:
                event = guardian.normalize_hook_event(
                    {
                        "client": "codex",
                        "session_id": "parent-session",
                        "cwd": str(ROOT),
                        "tool_name": "Bash",
                        "tool_input": {"command": "opaque-parent-runner-command"},
                        "success": True,
                        "call_id": call_id,
                    },
                    phase=phase,
                    provider="codex",
                )
                self.assertEqual(event["effect"], "unknown")
                decision = monitor.observe(event)
                self.assertEqual(decision.action, "allow")

            observe_read("started")
            observe_read("completed")
            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            before_guardian = module._guardian_baseline(production, ROOT)
            observe_read("started")
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
                parent_host_sessions={"codex": "parent-session"},
                expected_workspace=ROOT,
                before_guardian=before_guardian,
            )

            self.assertTrue(safe, reason)
            self.assertEqual(accepted, 1)

            observe_unknown_completion("started", "parent-command")
            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            before_guardian = module._guardian_baseline(production, ROOT)
            observe_unknown_completion("completed", "parent-command")
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
                parent_host_sessions={"codex": "parent-session"},
                expected_workspace=ROOT,
                before_guardian=before_guardian,
            )

            self.assertTrue(safe, reason)
            self.assertEqual(accepted, 1)

            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            before_guardian = module._guardian_baseline(production, ROOT)
            observe_unknown_completion("completed", "unmatched-parent-command")
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
                parent_host_sessions={"codex": "parent-session"},
                expected_workspace=ROOT,
                before_guardian=before_guardian,
            )

            self.assertFalse(safe)
            self.assertEqual(accepted, 0)
            self.assertIn("not an attributable read event", reason)

            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            before_guardian = module._guardian_baseline(production, ROOT)
            tampered = json.loads(contract_path.read_text(encoding="utf-8"))
            tampered["runtime"]["sequence"] += 1
            contract_path.write_text(
                json.dumps(tampered, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
                parent_host_sessions={"codex": "parent-session"},
                expected_workspace=ROOT,
                before_guardian=before_guardian,
            )

            self.assertFalse(safe)
            self.assertEqual(accepted, 0)
            self.assertIn("changed without an audit append", reason)

    def test_snapshot_catches_a_non_python_guard_bypass(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            production = root / "production-kb"
            production.mkdir()
            environment = module.isolated_environment(
                root / "isolated",
                production_kb=production,
                inherited={"PATH": os.environ.get("PATH", "")},
            )
            started_at = datetime.now(timezone.utc)
            before_filesystem = module.filesystem_snapshot(production)
            before_observation = module._observation_baseline(production)
            script = (
                "import os; from pathlib import Path; "
                "(Path(os.environ['SULDE_PRODUCTION_KB_HOME']) / 'raw-write')."
                "write_text('escaped audit hook', encoding='utf-8')"
            )
            completed = subprocess.run(
                [sys.executable, "-S", "-c", script],
                env=environment,
                cwd=ROOT,
                check=False,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
            ended_at = datetime.now(timezone.utc)
            after_filesystem = module.filesystem_snapshot(production)
            safe, _accepted, reason = module.production_mutation_verdict(
                production,
                before_filesystem=before_filesystem,
                before_observation=before_observation,
                after_filesystem=after_filesystem,
                started_at=started_at,
                ended_at=ended_at,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(safe)
            self.assertIn("outside attributable host state", reason)
            self.assertIn("raw-write", reason)

    def test_warm_audit_cursor_does_not_replay_historical_bytes(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name).resolve(strict=True)
            production = root / "production-kb"
            cursors = root / "cursors"
            production.mkdir()
            log = production / "host-capabilities.jsonl"
            historical = b"".join(
                json.dumps({"row": index}, sort_keys=True).encode("utf-8") + b"\n"
                for index in range(2000)
            )
            log.write_bytes(historical)
            first = module._observation_baseline(production, cursor_home=cursors)
            second = module._observation_baseline(production, cursor_home=cursors)
            appended = json.dumps({"row": 2000}, sort_keys=True).encode("utf-8") + b"\n"
            with log.open("ab") as handle:
                handle.write(appended)
            third = module._observation_baseline(production, cursor_home=cursors)

            self.assertEqual(first["catchup_bytes"], len(historical))
            self.assertEqual(second["catchup_bytes"], 0)
            self.assertEqual(third["catchup_bytes"], len(appended))

    def test_os_boundary_blocks_non_python_write_before_file_appears(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory_name:
            root = Path(directory_name)
            production = root / "production-kb"
            production.mkdir()
            target = production / "native-bypass"
            environment = module.isolated_environment(
                root / "isolated",
                production_kb=production,
            )
            try:
                module.preflight_os_test_isolation(production, environment)
            except RuntimeError as error:
                self.assertFalse(target.exists())
                self.assertIn("write denial", str(error))
                if os.environ.get("SULDE_REQUIRE_NATIVE_OS_EVIDENCE") == "1":
                    self.fail(
                        "formal native evidence required but the outer launcher blocks sandbox_init"
                    )
                self.skipTest("blocked: outer launcher prevents child Seatbelt initialization")
            command = module.os_isolated_test_command(
                [
                    sys.executable,
                    "-S",
                    "-c",
                    f"from pathlib import Path; Path({str(target)!r}).write_text('bad')",
                ],
                production,
            )
            completed = subprocess.run(
                command,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()

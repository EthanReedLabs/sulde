"""S2 coordinator: actual managed input and terminal consumer wiring."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.test_r3_real_entry_chain import _Chain, RUNTIME, load_runtime_module
from execution_method import execution_method_prompt


class IsolatedChain(_Chain):
    def environment(self):
        return {
            **super().environment(),
            "PYTHONDONTWRITEBYTECODE": "1",
            "SULDE_KB_HOME": str(self.tmp / "kb-home"),
            "SULDE_TEST_EVIDENCE_HOME": str(self.tmp / "test-evidence"),
        }


class RuntimeConsumerTests(unittest.TestCase):
    def inbox(self, chain):
        paths = list((chain.state / "test-kb-home/experience/inbox").glob("*.json"))
        self.assertEqual(len(paths), 1)
        return json.loads(paths[0].read_text(encoding="utf-8")), paths[0]

    def test_normal_control(self):
        with tempfile.TemporaryDirectory() as directory:
            chain = IsolatedChain(Path(directory), mode="wellbehaved")
            result = chain.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(chain.probe().stdout.strip(), "ok 2")
            self.assertFalse(chain.store.exists())

    def test_execution_method_reaches_actual_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            chain = IsolatedChain(Path(directory), mode="wellbehaved")
            result = chain.run()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                "--- Sulde 有界执行方法（不新增权限） ---", chain.captured_prompt()
            )
            self.assertIn(execution_method_prompt(), chain.captured_prompt())
            self.assertEqual(chain.probe().stdout.strip(), "ok 2")

    def test_resolved_success_is_observation_and_duplicate_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            chain = IsolatedChain(Path(directory), mode="wellbehaved")
            completed = chain.run()
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            envelope, path = self.inbox(chain)
            self.assertEqual(envelope["facts"]["status"], "success")
            self.assertTrue(envelope["facts"]["quiescent"])
            self.assertEqual(envelope["record"]["outcome"], "inconclusive")
            self.assertEqual(envelope["record"]["problem_type"], "managed_run_no_issue")
            original = path.read_bytes()
            self.assertNotIn(str(chain.worktree).encode(), original)
            repeated = chain.run()
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertIn("no new launch", repeated.stdout)
            self.assertEqual(path.read_bytes(), original)

    def test_provider_success_without_report_stays_failed_unresolved(self):
        with tempfile.TemporaryDirectory() as directory:
            chain = IsolatedChain(Path(directory), mode="wellbehaved")
            # Fault at provider output boundary; production report validator runs.
            source = chain.executable.read_text(encoding="utf-8")
            chain.executable.write_text(source.replace(
                "sys.exit(code)", "report.write_text('incomplete', encoding='utf-8')\nsys.exit(code)"
            ), encoding="utf-8")
            completed = chain.run()
            self.assertNotEqual(completed.returncode, 0)
            envelope, _ = self.inbox(chain)
            self.assertEqual(envelope["facts"]["returncode"], 0)
            self.assertEqual(envelope["facts"]["status"], "failed")
            self.assertFalse(envelope["facts"]["report_passed"])
            self.assertEqual(envelope["record"]["outcome"], "unresolved")

    def test_post_terminal_error_preserves_observed_provider_returncode(self):
        runtime = load_runtime_module()
        with tempfile.TemporaryDirectory() as directory:
            chain = IsolatedChain(Path(directory), mode="wellbehaved")
            completed = chain.run()
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            contract = json.loads((chain.state / "embed.intent.json").read_text(encoding="utf-8"))
            summary = json.loads((chain.state / "embed.guardian.json").read_text(encoding="utf-8"))
            status_path = chain.state / "embed.status"
            # Inject a coordinator error after a real provider result was settled.
            status_path.write_text("status=failed rc=2 reason=OSError\n", encoding="utf-8")
            with mock.patch("experience_maintenance.record_run_retrospective", return_value={
                "status": "queued", "execution_authorized": False, "task_status_changed": False,
            }) as record:
                runtime._record_terminal_retrospective(
                    chain.state, slug="embed", root=chain.worktree, task_id="embed",
                    guardian=SimpleNamespace(contract=contract, session_id="managed:l3:embed"),
                    run_ledger_path=chain.state / "embed.run.jsonl", status_path=status_path,
                    status="failed", report_passed=False, summary=summary, test_mode=True,
                )
            self.assertEqual(record.call_args.kwargs["status"], "failed")
            self.assertEqual(record.call_args.kwargs["returncode"], 0)
            self.assertFalse(record.call_args.kwargs["report_passed"])

    def test_retrospective_storage_failure_does_not_fail_successful_task(self):
        with tempfile.TemporaryDirectory() as directory:
            chain = IsolatedChain(Path(directory), mode="wellbehaved")
            (chain.state / "test-kb-home").write_text("unavailable", encoding="utf-8")
            completed = chain.run()
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            receipt = json.loads((chain.state / "embed.retrospective.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "degraded")
            self.assertFalse(receipt["task_status_changed"])
            self.assertIn('"status": "degraded"', completed.stdout)
            self.assertIn("status=success", (chain.state / "embed.status").read_text(encoding="utf-8"))

    def test_timeout_and_pause_are_recorded_as_unresolved(self):
        for terminal in ("timeout", "paused"):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as directory:
                chain = IsolatedChain(Path(directory), mode="wellbehaved")
                source = chain.executable.read_text(encoding="utf-8")
                chain.executable.write_text(source.replace(
                    "args = sys.argv[1:]", "import time\ntime.sleep(30)\nargs = sys.argv[1:]"
                ), encoding="utf-8")
                command = [sys.executable, "-B", str(RUNTIME), "run", str(chain.worktree),
                           "embed", str(chain.brief), "--timeout", "1" if terminal == "timeout" else "15",
                           "--task-id", "embed"]
                with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, encoding="utf-8", errors="replace", env=chain.environment()) as process:
                    if terminal == "paused":
                        deadline = time.monotonic() + 8
                        while not chain.prompt_capture.exists() and process.poll() is None and time.monotonic() < deadline:
                            time.sleep(0.02)
                        self.assertTrue(chain.prompt_capture.exists())
                        correction = subprocess.run([
                            sys.executable, "-B", str(RUNTIME.with_name("intent-guardian.py")),
                            "correction-propose", "Pause at the current task boundary", "--provider", "codex",
                            "--session-id", "managed:l3:embed", "--contract", str(chain.state / "embed.intent.json"),
                        ], capture_output=True, text=True, encoding="utf-8", errors="replace", env=chain.environment(), timeout=15)
                        self.assertEqual(correction.returncode, 0, correction.stdout + correction.stderr)
                    stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 1, stdout + stderr)
                envelope, _ = self.inbox(chain)
                self.assertEqual(envelope["facts"]["status"], terminal)
                self.assertEqual(envelope["record"]["outcome"], "unresolved")

    def test_prelaunch_failure_does_not_fabricate_run(self):
        runtime = load_runtime_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            observation = runtime._record_terminal_retrospective(
                root, slug="none", root=root, task_id="none", guardian=None,
                run_ledger_path=root / "missing.jsonl", status_path=root / "missing.status",
                status="failed", report_passed=False, test_mode=True,
            )
            self.assertEqual(observation["status"], "non_run")
            self.assertFalse((root / "test-kb-home").exists())

    def test_observation_output_failure_cannot_escape_to_task_handler(self):
        runtime = load_runtime_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch("builtins.print", side_effect=BrokenPipeError("closed")):
                result = runtime._record_terminal_retrospective(
                    root, slug="none", root=root, task_id="none", guardian=None,
                    run_ledger_path=root / "missing.jsonl", status_path=root / "missing.status",
                    status="success", report_passed=True, test_mode=True,
                )
            self.assertEqual(result["status"], "degraded")
            self.assertFalse(result["task_status_changed"])


class LifecycleConsumerTests(unittest.TestCase):
    def test_actual_run_inbox_is_consumed_by_lifecycle_apply(self):
        from tests.test_life_cycle import LIFE
        with tempfile.TemporaryDirectory() as directory:
            chain = IsolatedChain(Path(directory), mode="wellbehaved")
            completed = chain.run()
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            home = chain.state / "test-kb-home"
            inbox = list((home / "experience/inbox").glob("*.json"))
            self.assertEqual(len(inbox), 1)
            source = json.loads(inbox[0].read_text(encoding="utf-8"))
            with mock.patch.dict("os.environ", {
                "SULDE_KB_HOME": str(home), "SULDE_TEST_MODE": "1",
                "SULDE_TEST_EVIDENCE_HOME": str(chain.tmp / "test-evidence"),
            }):
                observed = LIFE.build(home, apply=True)
            maintenance = observed["experience_maintenance"]
            self.assertEqual(maintenance["merged"], 1, maintenance)
            self.assertFalse(inbox[0].exists())
            rows = [json.loads(line) for line in (home / "experience/agent.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()]
            self.assertIn(source["record"], rows)
            self.assertFalse(maintenance["execution_authorized"])

    def test_dry_run_is_readonly_and_maintenance_failure_not_health_gate(self):
        # Compose fixture; do not inherit its TestCase and duplicate every test.
        from tests.test_life_cycle import LIFE, LifeCycleTests
        fixture = LifeCycleTests()
        fixture.setUp()
        try:
            def snapshot():
                return {str(path.relative_to(fixture.home)): path.read_bytes()
                        for path in fixture.home.rglob("*") if path.is_file()}
            before = snapshot()
            normal = LIFE.build(fixture.home, scheduler_probe=fixture.scheduler_probe)
            self.assertEqual(snapshot(), before)
            self.assertEqual(normal["experience_maintenance"]["status"], "dry_run")
            with mock.patch.object(LIFE, "experience_maintenance", side_effect=OSError("private")):
                failed = LIFE.build(fixture.home, scheduler_probe=fixture.scheduler_probe)
            self.assertEqual(failed["experience_maintenance"]["status"], "degraded")
            self.assertEqual(failed["status"], normal["status"])
            self.assertEqual(snapshot(), before)
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()

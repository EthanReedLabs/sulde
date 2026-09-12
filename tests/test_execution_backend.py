from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from execution_backend import (  # noqa: E402
    ExecutionBackend,
    ExecutionBackendError,
    recover_incomplete_run,
    replay_run_ledger,
)


@unittest.skipIf(os.name == "nt", "POSIX process-group assertions")
class ExecutionBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ledger = self.root / "run.jsonl"
        self.backend = ExecutionBackend(cleanup_grace=0.2)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def rows(self) -> list[dict]:
        return [
            json.loads(line)
            for line in self.ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def start(self, source: str):
        return self.backend.start(
            [sys.executable, "-c", source],
            cwd=self.root,
            ledger_path=self.ledger,
            provider="codex",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_success_result_and_idempotent_dispose_are_separate_facts(self) -> None:
        handle = self.start("print('complete')")
        stdout, _stderr = handle.process.communicate(timeout=5)

        result = handle.settle(stop_reason="completed", output=stdout)
        cleanup = handle.dispose()
        repeated = handle.dispose()

        self.assertTrue(result.succeeded)
        self.assertTrue(result.output_present)
        self.assertTrue(cleanup.quiescent)
        self.assertFalse(cleanup.idempotent)
        self.assertTrue(repeated.idempotent)
        self.assertEqual(
            [row["type"] for row in self.rows()],
            [
                "execution.requested",
                "execution.started",
                "execution.result",
                "execution.disposed",
            ],
        )
        projection = replay_run_ledger(self.ledger)
        self.assertIsNotNone(projection)
        self.assertTrue(projection.terminal)
        self.assertTrue(projection.publishable)

    def test_partial_output_does_not_turn_error_into_success(self) -> None:
        handle = self.start("print('partial evidence'); raise SystemExit(3)")
        stdout, _stderr = handle.process.communicate(timeout=5)

        result = handle.settle(stop_reason="error", output=stdout)
        cleanup = handle.dispose()

        self.assertEqual(result.returncode, 3)
        self.assertFalse(result.succeeded)
        self.assertTrue(result.output_present)
        self.assertTrue(cleanup.quiescent)

    def test_dispose_kills_descendant_after_process_leader_exits(self) -> None:
        child_file = self.root / "child.pid"
        source = (
            "import pathlib, subprocess, sys\n"
            "child=subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL, close_fds=True)\n"
            f"pathlib.Path({str(child_file)!r}).write_text(str(child.pid))\n"
        )
        handle = self.start(source)
        handle.process.wait(timeout=5)
        child_pid = int(child_file.read_text(encoding="utf-8"))
        result = handle.settle(stop_reason="completed")

        cleanup = handle.dispose()

        self.assertTrue(result.succeeded)
        self.assertTrue(cleanup.quiescent, cleanup.errors)
        deadline = time.monotonic() + 2
        alive = True
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                alive = False
                break
            time.sleep(0.02)
        self.assertFalse(alive, f"descendant {child_pid} survived dispose")

    def test_interrupt_preserves_timeout_reason_and_then_disposes(self) -> None:
        handle = self.start("import time; time.sleep(60)")

        handle.interrupt("timeout")
        result = handle.settle(stop_reason="timeout")
        cleanup = handle.dispose()

        self.assertEqual(result.stop_reason, "timeout")
        self.assertFalse(result.succeeded)
        self.assertTrue(cleanup.quiescent)
        self.assertIn("execution.interrupt_requested", [row["type"] for row in self.rows()])

    def test_start_failure_is_durable_and_never_returns_a_handle(self) -> None:
        with self.assertRaises(ExecutionBackendError):
            self.backend.start(
                [str(self.root / "missing-provider")],
                cwd=self.root,
                ledger_path=self.ledger,
                provider="codex",
            )
        self.assertEqual(
            [row["type"] for row in self.rows()],
            ["execution.requested", "execution.start_failed"],
        )

    def test_requested_only_hard_crash_recovers_as_aborted_and_quiescent(self) -> None:
        run_id = "run-" + "a" * 24
        self.ledger.write_text(
            json.dumps(
                {
                    "schema": "sulde-run-event-v1",
                    "at": "2026-08-15T00:00:00+00:00",
                    "run_id": run_id,
                    "type": "execution.requested",
                    "provider": "codex",
                    "parent_death_watchdog": True,
                }
            )
            + "\n"
        )

        recovered = recover_incomplete_run(self.ledger, settle_timeout=0)

        self.assertTrue(recovered.terminal)
        self.assertFalse(recovered.publishable)
        self.assertEqual(recovered.result["stop_reason"], "aborted")
        self.assertTrue(recovered.disposed["quiescent"])
        self.assertTrue(recovered.disposed["recovered_from_crash"])

    def test_observable_legacy_process_group_stays_unknown_and_is_not_killed(self) -> None:
        run_id = "run-" + "b" * 24
        rows = [
            {
                "schema": "sulde-run-event-v1",
                "at": "2026-08-15T00:00:00+00:00",
                "run_id": run_id,
                "type": "execution.requested",
                "provider": "codex",
            },
            {
                "schema": "sulde-run-event-v1",
                "at": "2026-08-15T00:00:01+00:00",
                "run_id": run_id,
                "type": "execution.started",
                "provider": "codex",
                "pid": os.getpgrp(),
                "tree_scope": "posix-process-group",
            },
        ]
        self.ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))

        recovered = recover_incomplete_run(self.ledger, settle_timeout=0)

        self.assertFalse(recovered.terminal)
        self.assertTrue(recovered.recovery_blocked)
        self.assertEqual(self.rows()[-1]["type"], "execution.recovery_blocked")
        os.killpg(os.getpgrp(), 0)

    def test_incomplete_tail_is_preserved_and_never_guessed(self) -> None:
        self.ledger.write_text('{"schema":"sulde-run-event-v1"', encoding="utf-8")
        before = self.ledger.read_bytes()

        with self.assertRaisesRegex(ExecutionBackendError, "incomplete tail"):
            recover_incomplete_run(self.ledger, settle_timeout=0)

        self.assertEqual(self.ledger.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()

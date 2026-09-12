from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from execution_backend import ExecutionBackend  # noqa: E402
from terminal_invariants import terminal_invariant_failures  # noqa: E402


class TerminalInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.ledger = self.root / "run.jsonl"
        backend = ExecutionBackend(cleanup_grace=0.2)
        handle = backend.start(
            [sys.executable, "-c", "print('done')"],
            cwd=self.root,
            ledger_path=self.ledger,
            provider="codex",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = handle.process.communicate(timeout=5)
        result = handle.settle(stop_reason="completed", output=stdout)
        cleanup = handle.dispose()
        self.guardian = {
            "schema": "sulde-guardian-summary-v1",
            "policy_unchanged": True,
            "integrity_ok": True,
            "status": "active",
            "pending_proposal": False,
            "active_skills": 0,
            "open_events": 0,
            "pending_verifications": 0,
            "effect_unknown": 0,
            "interventions_open": 0,
            "corrections_open": 0,
            "approvals_open": 0,
            "authorized_events": 0,
            "integrity_breaches": 0,
            "denials": 0,
            "inconclusive_outcomes": 7,
            "execution": {
                "run_id": result.run_id,
                "returncode": result.returncode,
                "stop_reason": result.stop_reason,
                "cleanup_quiescent": cleanup.quiescent,
                "cleanup_error_count": len(cleanup.errors),
            },
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_all_subsystems_must_be_quiescent_but_historical_unknown_is_not_debt(self) -> None:
        self.assertEqual(
            terminal_invariant_failures(self.guardian, self.ledger), []
        )

        for field in (
            "active_skills",
            "open_events",
            "pending_verifications",
            "effect_unknown",
            "interventions_open",
            "corrections_open",
            "approvals_open",
            "authorized_events",
            "integrity_breaches",
            "denials",
        ):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.guardian)
                candidate[field] = 1
                self.assertTrue(
                    terminal_invariant_failures(candidate, self.ledger)
                )

    def test_summary_cannot_override_run_ledger_truth(self) -> None:
        candidate = copy.deepcopy(self.guardian)
        candidate["execution"]["run_id"] = "run-" + "f" * 24
        failures = terminal_invariant_failures(candidate, self.ledger)
        self.assertTrue(any("run id" in failure for failure in failures))

        rows = self.ledger.read_text().splitlines()
        self.ledger.write_text("\n".join(rows[:-1]) + "\n")
        failures = terminal_invariant_failures(self.guardian, self.ledger)
        self.assertTrue(any("no terminal cleanup" in failure for failure in failures))
        self.assertTrue(any("not publishable" in failure for failure in failures))


if __name__ == "__main__":
    unittest.main()

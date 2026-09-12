"""Contract-backed native receipt concurrency regression using isolated fixtures.

All approval files belong to TemporaryDirectory. No live host/ledger/CLI is used.
The production receipt writers and verifiers are NOT stubbed.
"""
from __future__ import annotations
import json
import hashlib
import platform
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from tests import test_intent_guardian as fixture_module
from intent_guardian_parts import recovery, state
import native_decision_journal as journal


WRITER = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts.state import contract_lock, load_contract, _write_contract_unlocked
from file_lock import lock_exclusive_nonblocking, unlock
path = Path(sys.argv[2])
with path.with_name('.' + path.name + '.lock').open('a+') as probe:
    try:
        lock_exclusive_nonblocking(probe)
    except BlockingIOError:
        state = 'blocked'
    else:
        unlock(probe)
        state = 'unlocked'
print(state, flush=True)
with contract_lock(path):
    document = load_contract(path)
    document['runtime']['sequence'] += 1
    _write_contract_unlocked(path, document)
print('written', flush=True)
"""
RECOVER = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from intent_guardian_parts.recovery import recover_native_decisions
from native_decision_journal import load_projection
path = Path(sys.argv[2])
result = recover_native_decisions(path)
transactions = load_projection(path)['transactions']
print(json.dumps({'stages': [row['stage'] for row in transactions.values()],
                  'failed': [row.get('recovery_error') for row in result if row.get('recovery_status') == 'failed']}))
"""


class NativeReceiptConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("REPRODUCIBILITY " + json.dumps({
            "python": platform.python_version(), "executable": sys.executable,
            "recovery_sha256": hashlib.sha256(Path(recovery.__file__).read_bytes()).hexdigest(),
            "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "fixture_sha256": hashlib.sha256(Path(fixture_module.__file__).read_bytes()).hexdigest(),
            "data": "temporary synthetic contracts only", "random_sampling": False,
        }, sort_keys=True), file=sys.stderr, flush=True)

    def setUp(self):
        self.fixture = fixture_module.IntentGuardianTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.contract()
        self.path = self.fixture.contract_path
        self.kb = str(fixture_module.SCRIPT_DIR)
        self.session = "isolated-native-receipt-consistency"
        self.children = []
        self.addCleanup(self.stop_children)
        _proposal, self.digest = fixture_module.create_revision_proposal(
            self.path, objective="isolated receipt consistency regression",
            acceptance_criteria=["one decision, strict identity, no interleaved receipt source write"],
            mode="enforce", allowed_paths=["resume.md"], decision_route="human",
        )
        preview = fixture_module.native_decision_preview(
            self.path, kind="proposal", decision="approve", target="current",
            provider="codex", session_id=self.session,
        )
        fixture_module.observe_native_permission_request(
            self.fixture.native_permission_payload(preview, session_id=self.session),
            provider="codex",
        )

    def stop_children(self):
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=10)

    def execute(self):
        return fixture_module.execute_native_decision(
            self.path, kind="proposal", decision="approve", target=self.digest,
            provider="codex", session_id=self.session,
        )

    def transaction(self):
        transactions = journal.load_projection(self.path)["transactions"]
        self.assertEqual(len(transactions), 1)
        return next(iter(transactions.values()))

    def assert_once(self):
        document = state.load_contract(self.path)
        self.assertEqual(document["applied_proposal_digest"], self.digest)
        self.assertEqual(len(document["runtime"]["proposal_decisions"]), 1)
        self.assertEqual(len(document["runtime"]["approval_receipts"]), 1)
        decisions = [json.loads(line) for line in journal.journal_path(self.path).read_text().splitlines()]
        self.assertEqual(sum(row.get("event") == "sealed" for row in decisions), 1)
        tx = self.transaction()
        self.assertEqual(tx["stage"], "committed")
        for path in (journal.effect_receipt_store_path(self.path),
                     journal.contract_receipt_store_path(self.path),
                     journal.external_head_receipt_store_path(self.path)):
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(sum(row["transaction_id"] == tx["transaction_id"] for row in rows), 1)

    def concurrent_write(self, boundary):
        processes = []
        wrote_inside = []

        def at_boundary(stage):
            if stage != boundary:
                return
            child = subprocess.Popen(
                [sys.executable, "-c", WRITER, self.kb, str(self.path)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace",
            )
            self.children.append(child)
            processes.append(child)
            lock_state = child.stdout.readline().strip()
            self.assertIn(lock_state, {"blocked", "unlocked"})
            if lock_state == "unlocked":
                output, error = child.communicate(timeout=0.25)
                self.assertEqual(child.returncode, 0, error)
                wrote_inside.append("written" in output)
            else:
                wrote_inside.append(False)

        error = None
        with mock.patch.object(recovery, "_native_decision_failpoint", side_effect=at_boundary):
            try:
                self.execute()
            except Exception as exc:
                error = exc
        for child in processes:
            output, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, stderr)
        self.assertIsNone(error, str(error))
        self.assertEqual(wrote_inside, [False], "contract writer interleaved inside receipt tail")
        self.assert_once()

    def test_writer_waits_until_commit_after_effect(self):
        self.concurrent_write("after_effect_applied")

    def test_writer_waits_until_commit_after_contract(self):
        self.concurrent_write("after_contract_applied")

    def test_writer_waits_until_commit_after_anchor(self):
        self.concurrent_write("after_anchor_receipt")

    def crash_at(self, boundary):
        def crash(stage):
            if stage == boundary:
                raise RuntimeError("isolated crash")
        with mock.patch.object(recovery, "_native_decision_failpoint", side_effect=crash):
            with self.assertRaisesRegex(RuntimeError, "isolated crash"):
                self.execute()

    def recover_process(self):
        return subprocess.Popen(
            [sys.executable, "-c", RECOVER, self.kb, str(self.path)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )

    def test_fresh_process_recovers_after_effect_without_second_decision(self):
        self.crash_at("after_effect_applied")
        child = self.recover_process()
        self.children.append(child)
        output, error = child.communicate(timeout=20)
        self.assertEqual(child.returncode, 0, error)
        self.assertEqual(json.loads(output), {"stages": ["committed"], "failed": []})
        self.assert_once()

    def test_fresh_process_recovers_after_contract_without_second_decision(self):
        self.crash_at("after_contract_applied")
        child = self.recover_process()
        self.children.append(child)
        output, error = child.communicate(timeout=20)
        self.assertEqual(child.returncode, 0, error)
        self.assertEqual(json.loads(output), {"stages": ["committed"], "failed": []})
        self.assert_once()

    def test_two_recoverers_do_not_duplicate_receipts_or_authority(self):
        self.crash_at("after_effect_applied")
        children = [self.recover_process(), self.recover_process()]
        self.children.extend(children)
        for child in children:
            output, error = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, error)
            self.assertEqual(json.loads(output), {"stages": ["committed"], "failed": []})
        self.assert_once()

    def reject_unlocked_change(self, field):
        """Out-of-protocol writes must NOT be accepted just because a lock exists."""
        def tamper(stage):
            if stage != "after_effect_applied":
                return
            document = json.loads(self.path.read_text())
            if field == "objective":
                document["objective"] = "unapproved scope"
            elif field == "allowed_paths":
                document["constraints"]["allowed_paths"] = ["unapproved/*"]
            elif field == "permission":
                document["permissions"]["destructive"] = "allow"
            elif field == "session":
                document["runtime"]["approval_receipts"][0]["session_id"] = "other-session"
            elif field == "unknown":
                document["unknown_authority_field"] = True
            else:
                document["runtime"]["sequence"] += 1
            self.path.write_text(json.dumps(document))
        with mock.patch.object(recovery, "_native_decision_failpoint", side_effect=tamper):
            with self.assertRaises((journal.NativeDecisionJournalError, state.IntentGuardianError)):
                self.execute()
        self.assertIn(self.transaction()["stage"], {"effect_applied", "superseded"})

    def test_changed_objective_stays_rejected(self):
        self.reject_unlocked_change("objective")

    def test_changed_allowed_paths_stays_rejected(self):
        self.reject_unlocked_change("allowed_paths")

    def test_changed_permissions_stay_rejected(self):
        self.reject_unlocked_change("permission")

    def test_changed_session_stays_rejected(self):
        self.reject_unlocked_change("session")

    def test_unknown_field_stays_rejected(self):
        self.reject_unlocked_change("unknown")

    def test_noncooperating_writer_stays_rejected(self):
        self.reject_unlocked_change("observation")

    def test_mutation_after_crash_is_not_silently_rebased(self):
        self.crash_at("after_effect_applied")
        old = journal.journal_path(self.path).read_bytes()
        with state.contract_lock(self.path):
            document = state.load_contract(self.path)
            document["runtime"]["sequence"] += 1
            state._write_contract_unlocked(self.path, document)
        result = recovery.recover_native_decisions(self.path)
        self.assertTrue(any(row.get("recovery_status") == "failed" for row in result))
        self.assertEqual(self.transaction()["stage"], "effect_applied")
        self.assertEqual(journal.journal_path(self.path).read_bytes(), old)

    def test_missing_receipt_source_is_rejected(self):
        self.crash_at("after_effect_applied")
        journal.effect_receipt_store_path(self.path).unlink()
        result = recovery.recover_native_decisions(self.path)
        self.assertTrue(any(row.get("recovery_status") == "failed" for row in result))
        self.assertEqual(self.transaction()["stage"], "effect_applied")

    def test_superseded_transaction_is_never_reactivated(self):
        self.crash_at("after_effect_applied")
        tx = self.transaction()
        journal.supersede(self.path, tx["transaction_id"], reason="isolated stale task")
        before = journal.journal_path(self.path).read_bytes()
        recovery.recover_native_decisions(self.path)
        self.assertEqual(self.transaction()["stage"], "superseded")
        self.assertEqual(before, journal.journal_path(self.path).read_bytes())


if __name__ == "__main__":
    unittest.main()

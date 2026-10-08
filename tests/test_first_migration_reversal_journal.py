"""Typed journal controls; no host approval or live installation claims."""
import json
import unittest

from tests import test_install_transaction_journal as fixture

load_journal = fixture.load_journal


class ReversalJournalTests(unittest.TestCase):
    setUp = fixture.InstallTransactionJournalTests.setUp
    tearDown = fixture.InstallTransactionJournalTests.tearDown
    descriptor = fixture.InstallTransactionJournalTests.descriptor

    def forward(self):
        journal = load_journal()
        origin = journal.begin_transaction(self.recovery, self.descriptor(),
                                           snapshot_paths=(self.old_tree, self.launcher))
        origin.append("prepared")
        self.launcher.write_bytes(b"new launcher")
        origin.append("committed")
        origin.clear_active()
        return journal, origin

    def reverse(self, journal, origin):
        return journal.begin_reversal(self.recovery, operation_id="b" * 32, origin=origin,
                                      authority_json=journal._canonical({"fixture": True}).decode())

    def test_normal_exact_old_snapshot_and_original_journal_unchanged(self):
        journal, origin = self.forward()
        before = origin.journal_path.read_bytes()
        reverse = self.reverse(journal, origin)
        self.assertEqual(reverse.snapshot_sha256, origin.snapshot_sha256)
        self.assertEqual(reverse.origin_transaction().descriptor, origin.descriptor)
        reverse.append("prepared")
        reverse.append("fenced")
        reverse.append("restore_started")
        reverse.restore_snapshot()
        reverse.append("restored")
        reverse.append("committed")
        self.assertTrue(reverse.verify_restored_snapshot())
        self.assertEqual(self.launcher.read_bytes(), b"old launcher\n")
        reverse.clear_active()
        self.assertIsNone(journal.load_active_transaction(self.recovery))
        self.assertEqual(origin.journal_path.read_bytes(), before)

    def test_single_owner_and_no_forward_stage_or_snapshot_substitution(self):
        journal, origin = self.forward()
        reverse = self.reverse(journal, origin)
        self.assertEqual(self.reverse(journal, origin).descriptor, reverse.descriptor)
        with self.assertRaises(journal.TransactionCollision):
            journal.begin_transaction(self.recovery, self.descriptor("c" * 32), snapshot_paths=())
        with self.assertRaises(journal.JournalError):
            reverse.append("rollback_started")
        with self.assertRaises(journal.JournalError):
            reverse.clear_active()
        active = json.loads(reverse.active_path.read_bytes())
        active["schema"] = journal.ACTIVE_SCHEMA
        journal._atomic_write(reverse.active_path, journal._canonical(active))
        with self.assertRaisesRegex(journal.JournalError, "type differs"):
            journal.load_active_transaction(self.recovery)

    def test_start_crash_has_durable_identity_and_corruption_is_not_recovered(self):
        journal, origin = self.forward()
        def crash(point):
            if point == "reversal.after_active":
                raise RuntimeError("interrupted")
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            journal.begin_reversal(self.recovery, operation_id="b" * 32, origin=origin,
                authority_json=journal._canonical({"fixture": True}).decode(), failpoint=crash)
        reverse = journal.load_active_transaction(self.recovery)
        self.assertIsInstance(reverse, journal.ReverseTransaction)
        self.assertIsNone(reverse.stage)
        blob = next((origin.snapshot_root / "blobs").iterdir())
        blob.write_bytes(b"damaged")
        with self.assertRaises(journal.JournalError):
            journal.load_active_transaction(self.recovery)
        self.assertTrue(reverse.active_path.exists())


if __name__ == "__main__":
    unittest.main()

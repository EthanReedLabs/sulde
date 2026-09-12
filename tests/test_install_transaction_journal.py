from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "scripts" / "release" / "install_transaction_journal.py"


def load_journal():
    spec = importlib.util.spec_from_file_location("test_install_transaction_journal", JOURNAL)
    if spec is None or spec.loader is None:
        raise RuntimeError("install_transaction_journal.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallTransactionJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.recovery = self.root / "kb" / ".install-recovery"
        self.old_tree = self.root / "old-plugin"
        self.old_tree.mkdir()
        (self.old_tree / "runtime.py").write_bytes(b"old runtime\r\n")
        (self.old_tree / "runtime.py").chmod(0o640)
        self.launcher = self.root / "kb" / "bin" / "launcher"
        self.launcher.parent.mkdir(parents=True)
        self.launcher.write_bytes(b"old launcher\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def descriptor(self, transaction_id: str = "a" * 32) -> dict[str, object]:
        digest = "1" * 64
        return {
            "transaction_id": transaction_id,
            "old_generation": "0.2.4:" + "0" * 64,
            "new_generation": "0.2.5:" + digest,
            "artifact": {"path": str(self.root / "artifact"), "tree_sha256": digest},
            "runtime": {"path": str(self.root / "new-plugin"), "tree_sha256": digest},
            "registry": {
                "codex_command": str(self.root / "fake-codex"),
                "old_marketplace": str(self.root / "old-artifact"),
                "old_version": "0.2.4",
                "old_installed_path": str(self.old_tree),
                "new_marketplace": str(self.root / "artifact"),
                "new_version": "0.2.5",
            },
            "launcher": {"path": str(self.launcher), "new_generation": "0.2.5:" + digest},
            "deployment": {
                "path": str(self.root / "kb" / "deployment-generation.json"),
                "new_generation": "0.2.5:" + digest,
            },
            "installed_tree": {"path": str(self.root / "new-plugin"), "tree_sha256": digest},
            "expected_postconditions": {
                "provider": "codex",
                "platform": "windows",
                "generation": "0.2.5:" + digest,
                "runtime_tree_sha256": digest,
            },
        }

    def test_owner_only_content_addressed_snapshot_and_monotonic_journal(self) -> None:
        journal = load_journal()
        transaction = journal.begin_transaction(
            self.recovery,
            self.descriptor(),
            snapshot_paths=(self.old_tree, self.launcher, self.root / "missing"),
        )
        transaction.append("prepared")
        transaction.append("registry_remove_started")
        transaction.append("registry_removed")

        loaded = journal.load_active_transaction(self.recovery)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.transaction_id, "a" * 32)
        self.assertEqual(loaded.stage, "registry_removed")
        self.assertEqual(loaded.descriptor["snapshot_sha256"], loaded.snapshot_sha256)
        self.assertTrue(loaded.verify_snapshot())
        self.assertEqual(loaded.read_records()[-1]["stage"], "registry_removed")
        self.assertTrue(loaded.journal_path.read_bytes().endswith(b"\n"))
        if os.name != "nt":
            self.assertEqual(loaded.transaction_root.stat().st_mode & 0o777, 0o700)
            for path in (loaded.descriptor_path, loaded.journal_path, loaded.active_path):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.stat().st_nlink, 1)

        with self.assertRaisesRegex(journal.JournalError, "monotonic"):
            loaded.append("registry_remove_started")

    def test_snapshot_restore_is_byte_and_mode_exact_and_idempotent(self) -> None:
        journal = load_journal()
        transaction = journal.begin_transaction(
            self.recovery,
            self.descriptor(),
            snapshot_paths=(self.old_tree, self.launcher, self.root / "missing"),
        )
        transaction.append("prepared")
        (self.old_tree / "runtime.py").write_bytes(b"new bytes\n")
        (self.old_tree / "extra").write_bytes(b"remove me")
        self.launcher.write_bytes(b"new launcher\n")
        (self.root / "missing").write_bytes(b"new file")

        transaction.restore_snapshot()
        transaction.restore_snapshot()
        self.assertEqual((self.old_tree / "runtime.py").read_bytes(), b"old runtime\r\n")
        self.assertEqual((self.old_tree / "runtime.py").stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.old_tree / "extra").exists())
        self.assertEqual(self.launcher.read_bytes(), b"old launcher\n")
        self.assertFalse((self.root / "missing").exists())
        self.assertTrue(transaction.verify_restored_snapshot())

    def test_truncation_snapshot_corruption_and_metadata_drift_fail_closed(self) -> None:
        journal = load_journal()
        transaction = journal.begin_transaction(
            self.recovery,
            self.descriptor(),
            snapshot_paths=(self.old_tree, self.launcher),
        )
        transaction.append("prepared")
        raw = transaction.journal_path.read_bytes()
        transaction.journal_path.write_bytes(raw[:-1])
        with self.assertRaisesRegex(journal.JournalError, "truncated"):
            journal.load_active_transaction(self.recovery)
        self.assertTrue(transaction.transaction_root.exists())

        transaction.journal_path.write_bytes(raw)
        blob = next((transaction.snapshot_root / "blobs").iterdir())
        blob.write_bytes(blob.read_bytes() + b"corrupt")
        with self.assertRaisesRegex(journal.JournalError, "snapshot"):
            journal.load_active_transaction(self.recovery)
        self.assertTrue(transaction.transaction_root.exists())

        # A fresh transaction exercises owner-only mode, link, and owner checks.
        second_recovery = self.root / "kb2" / ".install-recovery"
        second = journal.begin_transaction(
            second_recovery,
            self.descriptor("b" * 32),
            snapshot_paths=(self.old_tree,),
        )
        second.append("prepared")
        if os.name != "nt":
            second.journal_path.chmod(0o644)
            with self.assertRaisesRegex(journal.JournalError, "mode"):
                journal.load_active_transaction(second_recovery)
            second.journal_path.chmod(0o600)
            linked = self.root / "journal-link"
            os.link(second.journal_path, linked)
            with self.assertRaisesRegex(journal.JournalError, "link"):
                journal.load_active_transaction(second_recovery)
            linked.unlink()

            original_uid = second.journal_path.stat().st_uid
            with mock.patch.object(journal, "_current_uid", return_value=original_uid + 1):
                with self.assertRaisesRegex(journal.JournalError, "owner"):
                    journal.load_active_transaction(second_recovery)

    def test_same_transaction_replay_and_different_transaction_collision(self) -> None:
        journal = load_journal()
        secret_descriptor = self.descriptor("d" * 32)
        secret_descriptor["artifact"]["credential"] = "must-never-be-persisted"
        with self.assertRaisesRegex(journal.JournalError, "forbidden"):
            journal.begin_transaction(
                self.root / "secret-recovery",
                secret_descriptor,
                snapshot_paths=(self.old_tree,),
            )
        first = journal.begin_transaction(
            self.recovery,
            self.descriptor(),
            snapshot_paths=(self.old_tree,),
        )
        first.append("prepared")
        replay = journal.begin_transaction(
            self.recovery,
            self.descriptor(),
            snapshot_paths=(self.old_tree,),
        )
        self.assertEqual(replay.transaction_id, first.transaction_id)
        self.assertEqual(replay.stage, "prepared")
        with self.assertRaisesRegex(journal.TransactionCollision, "different transaction"):
            journal.begin_transaction(
                self.recovery,
                self.descriptor("c" * 32),
                snapshot_paths=(self.old_tree,),
            )


if __name__ == "__main__":
    unittest.main()

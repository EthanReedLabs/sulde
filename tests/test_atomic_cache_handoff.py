"""Atomic publication controls and injected failures; no production roots."""
import hashlib
import os
import json
import shutil
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/release"))
import atomic_cache_handoff as handoff
import legacy_maintenance as maintenance
import install_codex_plugin as installer
from tests.test_legacy_maintenance import fixture_plan
from tests import test_install_transaction_journal as journal_tests
load_journal = journal_tests.load_journal


@unittest.skipUnless(sys.platform == "darwin" or sys.platform.startswith("linux"), "atomic exchange platform")
class AtomicHandoffTests(unittest.TestCase):
    def test_failed_candidate_retention_binds_release_and_warm_digests_separately(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            codex = root / "codex"
            source = root / "artifact/plugins/sulde"
            (source / ".codex-plugin").mkdir(parents=True)
            (source / ".codex-plugin/plugin.json").write_text(
                json.dumps({"name": "sulde", "version": "2.0.0"}), encoding="utf-8")
            (source / "marker").write_bytes(b"candidate")
            alias = codex / "plugins/cache/sulde-local/sulde/2.0.0"
            shutil.copytree(source, alias)
            descriptor = {"registry": {"new_version": "2.0.0"},
                "expected_postconditions": {"artifact": str(root / "artifact"),
                    "plugin_tree_sha256": installer.tree_digest(source)}}
            self.assertNotEqual(installer.tree_digest(source), installer.warm_tree_state(source).tree_sha256)
            with mock.patch.object(installer, "default_codex_home", return_value=codex):
                installer._retain_failed_candidate_path(descriptor)
                installer._retain_failed_candidate_path(descriptor)
                self.assertTrue(alias.is_symlink())
                self.assertEqual((alias / "marker").read_bytes(), b"candidate")
                (alias / "marker").write_bytes(b"drift")
                with self.assertRaises(installer.InstallError):
                    installer._retain_failed_candidate_path(descriptor)

    def test_normal_roundtrip_and_continuous_reads(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            old, target, replacement = root / "old", root / "target", root / "replacement"
            old.mkdir()
            target.mkdir()
            (old / "marker").write_bytes(b"old")
            (target / "marker").write_bytes(b"new")
            replacement.symlink_to(target)
            observed, stop = [], threading.Event()
            def read():
                while not stop.is_set():
                    try:
                        observed.append((old / "marker").read_bytes())
                    except OSError as error:
                        observed.append(type(error).__name__)
            reader = threading.Thread(target=read)
            reader.start()
            try:
                for _ in range(100):
                    handoff.exchange(old, replacement)
            finally:
                stop.set()
                reader.join()
            self.assertTrue(observed)
            self.assertLessEqual(set(observed), {b"old", b"new"})
            self.assertFalse(old.is_symlink())
            handoff.probe(root)

    def test_unsupported_exchange_preserves_both_entries(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name).resolve()
            old, other = root / "old", root / "other"
            old.mkdir()
            other.symlink_to(old)
            with mock.patch.object(handoff.sys, "platform", "unsupported"):
                with self.assertRaises(handoff.AtomicHandoffError):
                    handoff.exchange(old, other)
            self.assertTrue(old.is_dir())
            self.assertFalse(old.is_symlink())
            self.assertTrue(other.is_symlink())

    def test_live_host_is_owned_without_claiming_other_sessions_drained(self):
        with tempfile.TemporaryDirectory() as name:
            plan = fixture_plan(Path(name).resolve())
            plan.update(schema=maintenance.LIVE_SCHEMA, cohort=[])
            raw = maintenance.canonical(plan)
            ctx = maintenance.operation_context(raw, hashlib.sha256(raw).hexdigest())
            rows = [{**plan["maintenance_host"], "parent_pid": 1},
                    {**plan["maintenance_host"], "pid": 101, "parent_pid": 1},
                    {"pid": os.getpid(), "parent_pid": 100, "started": "worker", "executable": "/python"}]
            ctx.check_processes(rows)
            self.assertEqual(ctx.claim_record()["schema"], maintenance.LIVE_SCHEMA)
            rows[-1]["parent_pid"] = 1
            with self.assertRaises(maintenance.MaintenanceError):
                ctx.check_processes(rows)
            plan["cohort"] = [rows[1]]
            raw = maintenance.canonical(plan)
            with self.assertRaises(maintenance.MaintenanceError):
                maintenance.operation_context(raw, hashlib.sha256(raw).hexdigest())


@unittest.skipUnless(sys.platform == "darwin" or sys.platform.startswith("linux"), "atomic exchange platform")
class AtomicSnapshotTests(journal_tests.InstallTransactionJournalTests):
    # Inherit baseline journal invariants as well as new atomic restore cases.
    def setUp(self):
        super().setUp()
        self.root = self.root.resolve()
        self.old_tree = self.old_tree.resolve()
        self.launcher = self.launcher.resolve()
        self.recovery = self.recovery.resolve()

    def test_restore_link_to_original_directory_is_atomic_and_repeatable(self):
        journal = load_journal()
        transaction = journal.begin_transaction(self.recovery, self.descriptor(),
            snapshot_paths=(self.old_tree, self.launcher))
        retained = self.root / "retained"
        retained.mkdir()
        (retained / "runtime.py").write_bytes(b"new runtime")
        replacement = self.root / "replacement"
        replacement.symlink_to(retained)
        handoff.exchange(self.old_tree, replacement)
        observations, stop = [], threading.Event()
        def read():
            while not stop.is_set():
                try:
                    observations.append((self.old_tree / "runtime.py").read_bytes())
                except OSError as error:
                    observations.append(type(error).__name__)
        reader = threading.Thread(target=read)
        reader.start()
        try:
            for _ in range(2):
                transaction.restore_snapshot(atomic_directories=(self.old_tree,),
                    staging_parent=self.root.resolve())
        finally:
            stop.set()
            reader.join()
        self.assertTrue(transaction.verify_restored_snapshot())
        self.assertTrue(observations)
        self.assertLessEqual(set(observations), {b"new runtime", b"old runtime\r\n"})

    def test_injected_exchange_failure_preserves_callable_alias(self):
        journal = load_journal()
        transaction = journal.begin_transaction(self.recovery, self.descriptor(),
            snapshot_paths=(self.old_tree,))
        with mock.patch.object(handoff, "exchange", side_effect=OSError("injected")):
            with self.assertRaisesRegex(OSError, "injected"):
                transaction.restore_snapshot(atomic_directories=(self.old_tree,),
                    staging_parent=self.root.resolve())
        self.assertEqual((self.old_tree / "runtime.py").read_bytes(), b"old runtime\r\n")

    def test_rollback_preserves_resolved_target_and_directory_fd_but_not_arbitrary_outputs(self):
        journal = load_journal()
        prepared = self.root / "prepared"
        prepared.mkdir()
        (prepared / "runtime.py").write_bytes(b"published bridge")
        retained = self.root / "retained"
        arbitrary = self.root / "unrelated"
        descriptor = self.descriptor()
        descriptor["expected_postconditions"].update(cache_handoff="atomic-v1",
            retirements=[{"target": str(retained), "record": str(self.root / "record")}],
            retained_outputs={str(retained): journal.content_identity(prepared)})
        transaction = journal.begin_transaction(self.recovery, descriptor,
            snapshot_paths=(self.old_tree, retained, arbitrary))
        transaction.append("prepared")
        shutil.copytree(prepared, retained)
        transaction.append("registry_remove_started")
        alias = self.root / "alias"
        alias.symlink_to(retained)
        handoff.exchange(self.old_tree, alias)
        resolved = self.old_tree.resolve()
        directory_fd = os.open(self.old_tree, os.O_RDONLY | os.O_DIRECTORY)
        arbitrary.write_bytes(b"must be removed, not exempted")
        try:
            for _ in range(2):
                transaction.restore_snapshot(atomic_directories=(self.old_tree,), staging_parent=self.root)
                self.assertTrue(transaction.verify_restored_snapshot())
                self.assertEqual((resolved / "runtime.py").read_bytes(), b"published bridge")
                child = os.open("runtime.py", os.O_RDONLY, dir_fd=directory_fd)
                try:
                    self.assertEqual(os.read(child, 100), b"published bridge")
                finally:
                    os.close(child)
                self.assertFalse(arbitrary.exists())
            (retained / "runtime.py").write_bytes(b"unproven")
            with self.assertRaisesRegex(journal.JournalError, "content differs"):
                transaction.verify_restored_snapshot()
            with self.assertRaisesRegex(journal.JournalError, "content differs"):
                transaction.restore_snapshot(atomic_directories=(self.old_tree,), staging_parent=self.root)
            self.assertTrue(retained.exists())
        finally:
            os.close(directory_fd)

    def test_unpublished_partial_target_is_rollback_owned(self):
        journal = load_journal()
        partial = self.root / "partial"
        descriptor = self.descriptor()
        descriptor["expected_postconditions"].update(cache_handoff="atomic-v1",
            retirements=[{"target": str(partial), "record": str(self.root / "record")}],
            retained_outputs={str(partial): "f" * 64})
        transaction = journal.begin_transaction(self.recovery, descriptor, snapshot_paths=(partial,))
        transaction.append("prepared")
        partial.mkdir()
        (partial / "incomplete").write_bytes(b"partial copy; never published")
        transaction.restore_snapshot()
        self.assertFalse(partial.exists())

    def test_published_missing_target_is_not_successful_rollback(self):
        journal = load_journal()
        prepared = self.root / "prepared"
        prepared.mkdir()
        (prepared / "runtime.py").write_bytes(b"published bridge")
        retained, record = self.root / "retained", self.root / "record"
        descriptor = self.descriptor()
        descriptor["expected_postconditions"].update(cache_handoff="atomic-v1",
            retirements=[{"target": str(retained), "record": str(record)}],
            retained_outputs={str(retained): journal.content_identity(prepared)})
        transaction = journal.begin_transaction(self.recovery, descriptor,
            snapshot_paths=(retained, record))
        transaction.append("prepared")
        # Construct the post-publication missing-target state without deleting
        # any directory. The durable boundary makes the target mandatory.
        transaction.append("registry_remove_started")
        with self.assertRaises(journal.JournalError):
            transaction.verify_restored_snapshot()
        with self.assertRaises(journal.JournalError):
            transaction.restore_snapshot()
        self.assertFalse(retained.exists())
        self.assertFalse(record.exists())

    def test_published_target_with_unwritten_record_is_valid(self):
        journal = load_journal()
        prepared = self.root / "prepared"
        prepared.mkdir()
        (prepared / "runtime.py").write_bytes(b"published bridge")
        retained, record = self.root / "retained", self.root / "record"
        descriptor = self.descriptor()
        descriptor["expected_postconditions"].update(cache_handoff="atomic-v1",
            retirements=[{"target": str(retained), "record": str(record)}],
            retained_outputs={str(retained): journal.content_identity(prepared)})
        transaction = journal.begin_transaction(self.recovery, descriptor,
            snapshot_paths=(retained, record))
        transaction.append("prepared")
        shutil.copytree(prepared, retained)
        transaction.append("registry_remove_started")
        for _ in range(2):
            transaction.restore_snapshot()
            self.assertTrue(transaction.verify_restored_snapshot())
            self.assertEqual((retained / "runtime.py").read_bytes(), b"published bridge")
            self.assertFalse(record.exists())


if __name__ == "__main__":
    unittest.main()

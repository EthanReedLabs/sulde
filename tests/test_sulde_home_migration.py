from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

from sulde_home_migration import (
    MigrationError,
    QUIESCENCE_SCHEMA,
    apply,
    ensure_contract_identity_map,
    plan,
    rollback,
)
from sulde_paths import (
    CONTRACT_IDENTITY_FILE,
    SuldePathError,
    contract_identity_digest,
    layout,
)
from approval_invariant import _contract_digest as approval_contract_digest
from correction_intervention import contract_digest as correction_contract_digest
from intervention import contract_digest as intervention_contract_digest
from native_decision_journal import _contract_digest as native_contract_digest


class SuldeHomeMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "legacy-kb"
        self.source.mkdir()
        (self.source / "intent" / "workspaces").mkdir(parents=True)
        (self.source / "intent" / "workspaces" / "a.json").write_text(
            '{"status":"confirmed"}\n', encoding="utf-8"
        )
        (self.source / "intent" / "workspaces" / "guard.active.json").write_text(
            '{"status":"active"}\n', encoding="utf-8"
        )
        (self.source / "bin").mkdir()
        launcher = self.source / "bin" / "intent-guardian"
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
        database = sqlite3.connect(self.source / "memory.db")
        database.execute("create table facts(value text)")
        database.execute("insert into facts values ('kept')")
        database.commit()
        database.close()
        self.destination = layout(home=self.root / ".sulde")
        self.receipt = self.root / "quiesced.json"
        self.receipt.write_text(
            json.dumps(
                {
                    "schema": QUIESCENCE_SCHEMA,
                    "status": "quiesced",
                    "source": str(self.source.absolute()),
                    "active_writers": 0,
                    "loaded_scheduler_labels": [],
                    "token": "exact-transaction-token",
                }
            ),
            encoding="utf-8",
        )
        self.receipt.chmod(0o600)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_is_read_only_and_checks_sqlite(self) -> None:
        result = plan(self.source, self.destination)
        self.assertTrue(result["ready"])
        self.assertIn("memory.db", result["sqlite_checked"])
        self.assertFalse(self.destination.root.exists())

    def test_apply_copies_exact_state_and_publishes_pointer_last(self) -> None:
        result = apply(self.source, self.destination, self.receipt)
        self.assertTrue(result["ready"])
        self.assertEqual(
            (self.destination.kb / "intent/workspaces/a.json").read_bytes(),
            (self.source / "intent/workspaces/a.json").read_bytes(),
        )
        self.assertTrue((self.destination.bin / "intent-guardian").is_file())
        pointer = json.loads(
            (self.destination.control / "current-home.json").read_text(encoding="utf-8")
        )
        self.assertEqual(pointer["manifest_sha256"], result["manifest_sha256"])
        identity_path = self.destination.control / CONTRACT_IDENTITY_FILE
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        self.assertEqual(
            pointer["contract_identity_map_sha256"],
            hashlib.sha256(identity_path.read_bytes()).hexdigest(),
        )
        relative = "intent/workspaces/guard.active.json"
        self.assertEqual(
            identity["identities"][relative],
            hashlib.sha256(
                str(self.source / relative).encode("utf-8")
            ).hexdigest(),
        )
        self.assertTrue(self.source.is_dir(), "legacy source remains a rollback authority")
        self.assertFalse((self.destination.control / "home-migration.lock").exists())

    def test_contract_identity_survives_move_without_rewriting_history(self) -> None:
        apply(self.source, self.destination, self.receipt)
        migrated = self.destination.kb / "intent/workspaces/guard.active.json"
        legacy = self.source / "intent/workspaces/guard.active.json"
        new_contract = self.destination.kb / "intent/workspaces/new.active.json"
        new_contract.write_text('{"status":"active"}\n', encoding="utf-8")

        with mock.patch.dict(
            os.environ,
            {
                "SULDE_HOME": str(self.destination.root),
                "SULDE_KB_HOME": str(self.destination.kb),
            },
        ):
            self.assertEqual(
                contract_identity_digest(migrated),
                hashlib.sha256(str(legacy).encode("utf-8")).hexdigest(),
            )
            for digest in (
                approval_contract_digest,
                correction_contract_digest,
                intervention_contract_digest,
                native_contract_digest,
            ):
                self.assertEqual(
                    digest(migrated),
                    hashlib.sha256(str(legacy).encode("utf-8")).hexdigest(),
                )
            self.assertEqual(
                contract_identity_digest(new_contract),
                hashlib.sha256(str(new_contract.resolve()).encode("utf-8")).hexdigest(),
            )
            identity_path = self.destination.control / CONTRACT_IDENTITY_FILE
            identity_path.write_text("{}\n", encoding="utf-8")
            identity_path.chmod(0o600)
            with self.assertRaisesRegex(SuldePathError, "digest differs"):
                contract_identity_digest(migrated)

    def test_legacy_pointer_upgrade_revalidates_retained_source(self) -> None:
        apply(self.source, self.destination, self.receipt)
        pointer_path = self.destination.control / "current-home.json"
        identity_path = self.destination.control / CONTRACT_IDENTITY_FILE
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer.pop("contract_identity_map_sha256")
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
        pointer_path.chmod(0o600)
        identity_path.unlink()

        upgraded = ensure_contract_identity_map(self.destination)

        self.assertIsNotNone(upgraded)
        self.assertTrue(identity_path.is_file())
        self.assertRegex(
            str(upgraded["contract_identity_map_sha256"]), r"^[0-9a-f]{64}$"
        )

    def test_legacy_pointer_upgrade_allows_unrelated_runtime_state_drift(self) -> None:
        apply(self.source, self.destination, self.receipt)
        pointer_path = self.destination.control / "current-home.json"
        identity_path = self.destination.control / CONTRACT_IDENTITY_FILE
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer.pop("contract_identity_map_sha256")
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
        pointer_path.chmod(0o600)
        identity_path.unlink()
        (self.source / "runtime-state.json").write_text(
            '{"status":"changed-after-migration"}\n', encoding="utf-8"
        )

        upgraded = ensure_contract_identity_map(self.destination)

        self.assertIsNotNone(upgraded)
        self.assertTrue(identity_path.is_file())

    def test_legacy_pointer_upgrade_rejects_changed_identity_state(self) -> None:
        apply(self.source, self.destination, self.receipt)
        pointer_path = self.destination.control / "current-home.json"
        identity_path = self.destination.control / CONTRACT_IDENTITY_FILE
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer.pop("contract_identity_map_sha256")
        pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
        pointer_path.chmod(0o600)
        identity_path.unlink()
        (self.source / "intent/workspaces/guard.active.json").write_text(
            '{"status":"changed-after-migration"}\n', encoding="utf-8"
        )

        with self.assertRaisesRegex(MigrationError, "identity-bearing state changed"):
            ensure_contract_identity_map(self.destination)

    @unittest.skipIf(os.name == "nt", "POSIX mode preservation contract")
    def test_apply_preserves_and_manifest_binds_private_path_modes(self) -> None:
        recovery = self.source / ".install-recovery"
        recovery.mkdir()
        recovery.chmod(0o700)
        evidence = recovery / "active.json"
        evidence.write_text('{"stage":"rolled_back"}\n', encoding="utf-8")
        evidence.chmod(0o600)

        activation = apply(self.source, self.destination, self.receipt)

        migrated_recovery = self.destination.kb / ".install-recovery"
        migrated_evidence = migrated_recovery / "active.json"
        self.assertEqual(stat.S_IMODE(migrated_recovery.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(migrated_evidence.stat().st_mode), 0o600)
        self.assertGreater(activation["directory_count"], 0)

        migrated_evidence.chmod(0o644)
        with self.assertRaises(MigrationError):
            rollback(activation, self.destination)

    def test_apply_rejects_receipt_that_does_not_prove_quiescence(self) -> None:
        payload = json.loads(self.receipt.read_text(encoding="utf-8"))
        payload["active_writers"] = 1
        self.receipt.write_text(json.dumps(payload), encoding="utf-8")
        self.receipt.chmod(0o600)
        with self.assertRaises(MigrationError):
            apply(self.source, self.destination, self.receipt)
        self.assertFalse(self.destination.kb.exists())

    def test_rollback_requires_exact_pointer_and_preserves_legacy_source(self) -> None:
        activation = apply(self.source, self.destination, self.receipt)
        rollback(activation, self.destination)
        self.assertFalse(self.destination.kb.exists())
        self.assertFalse(self.destination.bin.exists())
        self.assertFalse((self.destination.control / "current-home.json").exists())
        self.assertFalse((self.destination.control / CONTRACT_IDENTITY_FILE).exists())
        self.assertTrue((self.source / "memory.db").is_file())

    @unittest.skipIf(os.name == "nt", "symlink privilege varies on Windows")
    def test_symlink_source_member_is_rejected(self) -> None:
        (self.source / "escape").symlink_to(self.root / "outside")
        with self.assertRaises(MigrationError):
            plan(self.source, self.destination)

    @unittest.skipIf(os.name == "nt", "symlink privilege varies on Windows")
    def test_internal_content_link_is_manifest_bound_and_preserved(self) -> None:
        blobs = self.source / "fastembed_cache" / "blobs"
        snapshot = self.source / "fastembed_cache" / "snapshots" / "v1"
        blobs.mkdir(parents=True)
        snapshot.mkdir(parents=True)
        (blobs / "model.bin").write_bytes(b"model-bytes")
        (snapshot / "model.bin").symlink_to("../../blobs/model.bin")

        result = apply(self.source, self.destination, self.receipt)

        migrated = self.destination.kb / "fastembed_cache/snapshots/v1/model.bin"
        self.assertTrue(migrated.is_symlink())
        self.assertEqual(os.readlink(migrated), "../../blobs/model.bin")
        self.assertEqual(migrated.read_bytes(), b"model-bytes")
        self.assertEqual(
            result["manifest_sha256"],
            json.loads(
                (self.destination.control / "current-home.json").read_text(
                    encoding="utf-8"
                )
            )["manifest_sha256"],
        )

    @unittest.skipIf(os.name == "nt", "symlink privilege varies on Windows")
    def test_venv_interpreter_chain_allows_only_a_safe_executable(self) -> None:
        host_bin = self.root / "host-bin"
        host_bin.mkdir()
        interpreter = host_bin / "python3.10"
        interpreter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        interpreter.chmod(0o755)
        host_python = host_bin / "python3"
        host_python.symlink_to("python3.10")
        bin_dir = self.source / "venv" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python3").symlink_to(host_python)
        (bin_dir / "python").symlink_to("python3")

        apply(self.source, self.destination, self.receipt)

        migrated_bin = self.destination.kb / "venv" / "bin"
        self.assertEqual(os.readlink(migrated_bin / "python3"), str(host_python))
        self.assertEqual(os.readlink(migrated_bin / "python"), "python3")
        self.assertEqual(
            (migrated_bin / "python").read_bytes(),
            interpreter.read_bytes(),
        )

        rollback(
            json.loads(
                (self.destination.control / "current-home.json").read_text(
                    encoding="utf-8"
                )
            ),
            self.destination,
        )
        interpreter.chmod(0o777)
        with self.assertRaises(MigrationError):
            plan(self.source, self.destination)

    @unittest.skipIf(os.name == "nt", "POSIX venv relocation contract")
    def test_real_venv_remains_executable_at_the_neutral_kb_path(self) -> None:
        base_python = (
            Path(sys.base_prefix)
            / "bin"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
        )
        self.assertTrue(base_python.is_file())
        created = subprocess.run(
            [
                str(base_python),
                "-m",
                "venv",
                "--without-pip",
                str(self.source / "venv"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(created.returncode, 0, created.stderr)

        result = apply(self.source, self.destination, self.receipt)

        migrated_python = self.destination.kb / "venv/bin/python"
        probed = subprocess.run(
            [
                str(migrated_python),
                "-c",
                (
                    "import json, pathlib, sqlite3, sys; "
                    "print(pathlib.Path(sys.prefix).resolve())"
                ),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(probed.returncode, 0, probed.stderr)
        self.assertEqual(
            Path(probed.stdout.strip()),
            (self.destination.kb / "venv").resolve(),
        )
        self.assertGreater(result["symlink_count"], 0)


if __name__ == "__main__":
    unittest.main()

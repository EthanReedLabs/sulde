from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "kb" / "guardian-recovery.py"


def load_module():
    spec = importlib.util.spec_from_file_location("test_guardian_recovery_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GuardianRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        # macOS exposes /tmp as a symlink to /private/tmp.  Recovery correctly
        # rejects that ancestor alias, so destructive fixtures live under the
        # canonical absolute worktree while remaining TemporaryDirectory-bound.
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = Path(self.temp.name)
        self.target = self.root / "synthetic-marker.txt"
        self.target.write_bytes(b"F")
        metadata = self.target.stat()
        self.event_id = "synthetic-event-13"
        self.session_id = "fixture-session"
        self.audit = self.root / "audit.jsonl"
        self.record = {
            "schema": self.module.CANDIDATE_SCHEMA,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "artifact": {
                "kind": "single_file",
                "synthetic": True,
                "target": str(self.target),
                "identity": {
                    "dev": metadata.st_dev,
                    "inode": metadata.st_ino,
                    "size": metadata.st_size,
                    "sha256": hashlib.sha256(b"F").hexdigest(),
                    "uid": metadata.st_uid,
                },
            },
        }
        self.audit.write_text(json.dumps(self.record) + "\n", encoding="utf-8")
        self.audit.chmod(0o600)
        self.findings = self.module.finding_path(self.audit)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def candidate(self):
        return self.module.load_candidate(
            self.audit,
            event_id=self.event_id,
            session_id=self.session_id,
        )

    def findings_rows(self):
        return [json.loads(line) for line in self.findings.read_text().splitlines()]

    def lexical_alias(self, path: Path) -> str:
        alias = f"{path.parent}//{path.name}"
        self.assertNotEqual(alias, str(path))
        return alias

    def test_plan_only_is_read_only_and_contains_exact_native_action(self) -> None:
        before = self.target.read_bytes()
        plan = self.module.build_plan(self.candidate(), audit=self.audit)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertFalse(self.findings.exists())
        self.assertTrue(plan["requires_native_permission_request"])
        self.assertEqual(
            plan["native_permission_request_scope"],
            "new one-time Codex native PermissionRequest",
        )
        self.assertNotIn("--target", plan["apply_command"])
        self.assertEqual(plan["identity"]["sha256"], hashlib.sha256(b"F").hexdigest())

    def test_successful_apply_removes_only_bound_fixture_and_appends_finding(self) -> None:
        neighbor = self.root / "neighbor.txt"
        neighbor.write_text("preserve", encoding="utf-8")
        real_fsync = self.module.os.fsync
        real_unlink = self.module.os.unlink
        fsync_calls: list[int] = []

        def recording_fsync(fd: int) -> None:
            fsync_calls.append(fd)
            real_fsync(fd)

        def checked_unlink(path, *, dir_fd=None) -> None:
            self.assertGreaterEqual(len(fsync_calls), 1, "prepared finding was not fsynced")
            real_unlink(path, dir_fd=dir_fd)

        with mock.patch.object(
            self.module.os, "fsync", side_effect=recording_fsync
        ), mock.patch.object(self.module.os, "unlink", side_effect=checked_unlink):
            result = self.module.apply_candidate(
                self.candidate(), findings=self.findings
            )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(len(fsync_calls), 2)
        self.assertFalse(self.target.exists())
        self.assertEqual(neighbor.read_text(), "preserve")
        rows = self.findings_rows()
        self.assertEqual([row["status"] for row in rows], ["prepared", "applied"])
        self.assertEqual(rows[0]["operation_sha256"], rows[1]["operation_sha256"])
        self.assertEqual(rows[0]["target_identity"], self.record["artifact"]["identity"])

    def test_identity_drift_fails_closed_and_appends_failure(self) -> None:
        candidate = self.candidate()
        self.target.write_bytes(b"changed")
        with self.assertRaisesRegex(self.module.RecoveryError, "identity drifted"):
            self.module.apply_candidate(candidate, findings=self.findings)
        self.assertTrue(self.target.exists())
        self.assertEqual(
            [row["status"] for row in self.findings_rows()],
            ["prepared", "failed"],
        )
        self.assertFalse(self.findings_rows()[-1]["removed"])

        # The historical live marker may disappear outside this recovery
        # action.  Its audit record remains loadable, but neither plan nor
        # apply may recreate it or claim the old inode was recovered.
        self.findings.unlink()
        self.target.unlink()
        missing_candidate = self.candidate()
        with self.assertRaisesRegex(self.module.RecoveryError, "target is missing"):
            self.module.build_plan(missing_candidate, audit=self.audit)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.findings.exists())
        with self.assertRaisesRegex(self.module.RecoveryError, "target is missing"):
            self.module.apply_candidate(missing_candidate, findings=self.findings)
        self.assertFalse(self.target.exists())
        self.assertEqual(
            [row["status"] for row in self.findings_rows()],
            ["prepared", "failed"],
        )
        self.assertFalse(self.findings_rows()[-1]["removed"])

    def test_symlink_and_hardlink_are_rejected_without_removal(self) -> None:
        original = self.root / "original.txt"
        original.write_text("original", encoding="utf-8")
        self.target.unlink()
        self.target.symlink_to(original)
        with self.assertRaises(self.module.RecoveryError):
            self.module.apply_candidate(self.candidate(), findings=self.findings)
        self.assertTrue(self.target.is_symlink())
        self.assertTrue(original.exists())
        self.assertEqual(self.findings_rows()[-1]["status"], "failed")

        self.findings.unlink()
        self.target.unlink()
        self.target.write_bytes(b"F")
        alias = self.root / "alias.txt"
        os.link(self.target, alias)
        metadata = self.target.stat()
        self.record["artifact"]["identity"].update(
            dev=metadata.st_dev,
            inode=metadata.st_ino,
            size=metadata.st_size,
            uid=metadata.st_uid,
        )
        self.audit.write_text(json.dumps(self.record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(self.module.RecoveryError, "exactly one hard link"):
            self.module.apply_candidate(self.candidate(), findings=self.findings)
        self.assertTrue(self.target.exists())
        self.assertTrue(alias.exists())
        self.assertEqual(self.findings_rows()[-1]["status"], "failed")

    def test_path_swap_between_checks_fails_closed(self) -> None:
        candidate = self.candidate()
        replacement = self.root / "replacement.txt"
        replacement.write_bytes(b"F")

        def checkpoint(label: str) -> None:
            if label == "before_unlink":
                self.target.rename(self.root / "moved-original.txt")
                replacement.rename(self.target)

        with self.assertRaises(self.module.RecoveryError):
            self.module.apply_candidate(
                candidate,
                findings=self.findings,
                checkpoint=checkpoint,
            )
        self.assertTrue(self.target.exists())
        self.assertTrue((self.root / "moved-original.txt").exists())
        self.assertEqual(self.findings_rows()[-1]["status"], "failed")
        self.assertFalse(self.findings_rows()[-1]["removed"])

    def test_target_ancestor_symlink_is_rejected_without_removal(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        real_target = real_parent / "marker.txt"
        real_target.write_bytes(b"F")
        alias_parent = self.root / "alias-parent"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        metadata = real_target.stat()
        self.record["artifact"]["target"] = str(alias_parent / real_target.name)
        self.record["artifact"]["identity"].update(
            dev=metadata.st_dev,
            inode=metadata.st_ino,
            size=metadata.st_size,
            uid=metadata.st_uid,
        )
        self.audit.write_text(json.dumps(self.record) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(self.module.RecoveryError, "symlink or non-directory ancestor"):
            self.candidate()
        self.assertTrue(real_target.exists())
        self.assertFalse(self.findings.exists())

    def test_direct_and_ancestor_audit_symlinks_are_rejected(self) -> None:
        direct_alias = self.root / "audit-alias.jsonl"
        direct_alias.symlink_to(self.audit)
        with self.assertRaisesRegex(self.module.RecoveryError, "opened safely"):
            self.module.load_candidate(
                direct_alias,
                event_id=self.event_id,
                session_id=self.session_id,
            )

        real_parent = self.root / "audit-parent"
        real_parent.mkdir()
        nested_audit = real_parent / "audit.jsonl"
        nested_audit.write_text(json.dumps(self.record) + "\n", encoding="utf-8")
        nested_audit.chmod(0o600)
        alias_parent = self.root / "audit-parent-alias"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(self.module.RecoveryError, "symlink or non-directory ancestor"):
            self.module.load_candidate(
                alias_parent / nested_audit.name,
                event_id=self.event_id,
                session_id=self.session_id,
            )

    def test_audit_requires_absolute_owner_only_singly_linked_regular_input(self) -> None:
        relative = Path(self.audit.name)
        with self.assertRaisesRegex(self.module.RecoveryError, "canonical absolute"):
            self.module.load_candidate(
                relative,
                event_id=self.event_id,
                session_id=self.session_id,
            )

        self.audit.chmod(0o644)
        with self.assertRaisesRegex(self.module.RecoveryError, "owner-only"):
            self.candidate()
        self.audit.chmod(0o600)

        audit_alias = self.root / "audit-hardlink.jsonl"
        os.link(self.audit, audit_alias)
        with self.assertRaisesRegex(self.module.RecoveryError, "singly linked"):
            self.candidate()

    def test_audit_size_bound_and_read_identity_drift_fail_closed(self) -> None:
        with mock.patch.object(self.module, "MAX_AUDIT_BYTES", 32):
            with self.assertRaisesRegex(self.module.RecoveryError, "bounded"):
                self.candidate()

        real_read = self.module.os.read
        drifted = False

        def drifting_read(fd: int, size: int) -> bytes:
            nonlocal drifted
            payload = real_read(fd, size)
            if payload and not drifted:
                drifted = True
                with self.audit.open("ab") as stream:
                    stream.write(b" ")
            return payload

        with mock.patch.object(self.module.os, "read", side_effect=drifting_read):
            with self.assertRaisesRegex(self.module.RecoveryError, "changed"):
                self.candidate()
        self.assertTrue(self.target.exists())

    def test_cli_rejects_audit_lexical_alias_before_loading(self) -> None:
        aliased_audit = self.lexical_alias(self.audit)
        argv = [
            str(MODULE_PATH),
            "--audit",
            aliased_audit,
            "--event-id",
            self.event_id,
            "--session-id",
            self.session_id,
        ]
        stderr = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
            self.module.sys, "stderr", stderr
        ):
            self.assertEqual(self.module.main(), 2)
        self.assertIn("pathname alias", stderr.getvalue())
        self.assertTrue(self.target.exists())

    def test_unsafe_finding_sinks_fail_preflight_and_preserve_target(self) -> None:
        other = self.root / "other-findings.jsonl"
        other.write_text("", encoding="utf-8")
        other.chmod(0o600)
        self.findings.symlink_to(other)
        with self.assertRaises(self.module.RecoveryError):
            self.module.apply_candidate(self.candidate(), findings=self.findings)
        self.assertTrue(self.target.exists())
        self.assertEqual(other.read_text(encoding="utf-8"), "")

        self.findings.unlink()
        os.link(other, self.findings)
        with self.assertRaisesRegex(self.module.RecoveryError, "singly linked"):
            self.module.apply_candidate(self.candidate(), findings=self.findings)
        self.assertTrue(self.target.exists())
        self.assertEqual(other.read_text(encoding="utf-8"), "")

        self.findings.unlink()
        other.unlink()
        self.findings.write_text("", encoding="utf-8")
        self.findings.chmod(0o644)
        with self.assertRaisesRegex(self.module.RecoveryError, "owner-only"):
            self.module.apply_candidate(self.candidate(), findings=self.findings)
        self.assertTrue(self.target.exists())
        self.assertEqual(self.findings.read_text(encoding="utf-8"), "")

    def test_finding_sink_cannot_alias_the_bound_target(self) -> None:
        candidate = self.candidate()
        self.target.chmod(0o600)
        with self.assertRaisesRegex(self.module.RecoveryError, "aliases"):
            self.module.apply_candidate(candidate, findings=self.target)
        self.assertEqual(self.target.read_bytes(), b"F")

    def test_finding_ancestor_symlink_and_creation_race_preserve_target(self) -> None:
        real_parent = self.root / "finding-parent"
        real_parent.mkdir()
        alias_parent = self.root / "finding-parent-alias"
        alias_parent.symlink_to(real_parent, target_is_directory=True)
        aliased_findings = alias_parent / "findings.jsonl"
        with self.assertRaisesRegex(self.module.RecoveryError, "symlink or non-directory ancestor"):
            self.module.apply_candidate(self.candidate(), findings=aliased_findings)
        self.assertTrue(self.target.exists())

        real_open = self.module.os.open

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            if (
                path == self.findings.name
                and flags & os.O_CREAT
                and flags & os.O_EXCL
            ):
                self.findings.write_text("", encoding="utf-8")
                self.findings.chmod(0o600)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(self.module.os, "open", side_effect=racing_open):
            with self.assertRaisesRegex(self.module.RecoveryError, "creation raced"):
                self.module.apply_candidate(self.candidate(), findings=self.findings)
        self.assertTrue(self.target.exists())
        self.assertEqual(self.findings.read_text(encoding="utf-8"), "")

    def test_finding_permission_or_hardlink_drift_before_unlink_preserves_target(self) -> None:
        def drift_permissions(label: str) -> None:
            if label == "after_prepared":
                self.findings.chmod(0o644)

        with self.assertRaisesRegex(self.module.RecoveryError, "owner-only"):
            self.module.apply_candidate(
                self.candidate(), findings=self.findings, checkpoint=drift_permissions
            )
        self.assertTrue(self.target.exists())
        self.assertEqual([row["status"] for row in self.findings_rows()], ["prepared"])

        self.findings.unlink()

        def drift_links(label: str) -> None:
            if label == "after_prepared":
                os.link(self.findings, self.root / "finding-hardlink.jsonl")

        with self.assertRaisesRegex(self.module.RecoveryError, "singly linked"):
            self.module.apply_candidate(
                self.candidate(), findings=self.findings, checkpoint=drift_links
            )
        self.assertTrue(self.target.exists())
        self.assertEqual([row["status"] for row in self.findings_rows()], ["prepared"])

    def test_unknown_duplicate_cross_session_and_glob_records_are_rejected(self) -> None:
        with self.assertRaisesRegex(self.module.RecoveryError, "exactly one known"):
            self.module.load_candidate(
                self.audit,
                event_id="unknown-event",
                session_id=self.session_id,
            )
        with self.assertRaisesRegex(self.module.RecoveryError, "cross-session"):
            self.module.load_candidate(
                self.audit,
                event_id=self.event_id,
                session_id="other-session",
            )
        with self.audit.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(self.record) + "\n")
        with self.assertRaisesRegex(self.module.RecoveryError, "exactly one known"):
            self.candidate()

        glob_record = json.loads(json.dumps(self.record))
        glob_record["event_id"] = "glob-event"
        glob_record["artifact"]["target"] = str(self.root / "*.txt")
        self.audit.write_text(json.dumps(glob_record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(self.module.RecoveryError, "glob-like"):
            self.module.load_candidate(
                self.audit,
                event_id="glob-event",
                session_id=self.session_id,
            )

        alias_record = json.loads(json.dumps(self.record))
        alias_record["event_id"] = "alias-event"
        alias_record["artifact"]["target"] = self.lexical_alias(self.target)
        self.audit.write_text(json.dumps(alias_record) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(self.module.RecoveryError, "pathname alias"):
            self.module.load_candidate(
                self.audit,
                event_id="alias-event",
                session_id=self.session_id,
            )


if __name__ == "__main__":
    unittest.main()

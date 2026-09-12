from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "scripts" / "kb"
sys.path.insert(0, str(KB))

import accepted_snapshot_protocol as protocol  # noqa: E402


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return completed.stdout


class SimulatedDeath(BaseException):
    pass


class SimulatedException(Exception):
    pass


class AcceptedSnapshotProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir(mode=0o700)
        git(self.repo, "init", "-q")
        self.base_bytes = b"base bytes from committed object\n"
        (self.repo / "base.txt").write_bytes(self.base_bytes)
        os.chmod(self.repo / "base.txt", 0o644)
        git(self.repo, "add", "base.txt")
        git(
            self.repo,
            "-c",
            "user.name=Synthetic Test",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-qm",
            "synthetic base",
        )
        self.base_commit = git(self.repo, "rev-parse", "HEAD").decode().strip()
        self.base_object = git(
            self.repo, "rev-parse", f"{self.base_commit}:base.txt"
        ).decode().strip()
        self.changed_bytes = b"exact accepted current bytes\n"
        (self.repo / "changed.txt").write_bytes(self.changed_bytes)
        os.chmod(self.repo / "changed.txt", 0o600)
        self.authority_root = self.root / "authority"
        self.authority_root.mkdir(mode=0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def source(
        self,
        *,
        path: str = "changed.txt",
        data: bytes | None = None,
        operation: str = "modify",
        source_kind: str = "current",
        mode: int = 0o600,
        before: str | None = SHA_A,
        git_object: str | None = None,
    ) -> dict[str, object]:
        selected = self.changed_bytes if data is None else data
        return {
            "operation": operation,
            "path": path,
            "mode": mode,
            "expected_before_sha256": before,
            "expected_after_sha256": digest(selected),
            "size": len(selected),
            "source_kind": source_kind,
            "git_object": git_object,
        }

    def authority(self, sources: list[dict[str, object]] | None = None) -> dict:
        evidence = [
            {
                "evidence_id": "evidence-1",
                "sha256": SHA_C,
                "status": "ok",
                "observed_at": "2026-08-19T09:00:00+00:00",
            }
        ]
        task_definition_sha = SHA_B
        task = {
            "task_id": "T16",
            "generation": 3,
            "generation_state": "accepted",
            "superseded_by_generation": None,
            "open_successor_generation": None,
            "accepted_event": {
                "event_id": "event-task-accepted",
                "event_sha256": "d" * 64,
                "sequence": 40,
                "recorded_at": "2026-08-19T10:00:00+00:00",
            },
            "accepted_verification": {
                "run_id": "verify-run-7",
                "epoch": 7,
                "verified_at": "2026-08-19T09:30:00+00:00",
                "accepted_event_id": "event-task-accepted",
                "task_definition_sha256": task_definition_sha,
                "evidence_set_sha256": canonical_digest(evidence),
            },
            "task_definition_sha256": task_definition_sha,
            "active_evidence": evidence,
            "selected_predecessor": {
                "task_id": "T15",
                "generation": 2,
                "accepted_event_id": "event-t15-accepted",
                "accepted_event_sha256": "e" * 64,
            },
            "supersession": {
                "selected_generation": 3,
                "supersedes_generation": 2,
            },
            "dependency_closure": [
                {
                    "task_id": "T15",
                    "generation": 2,
                    "accepted_event_id": "event-t15-accepted",
                    "accepted_event_sha256": "e" * 64,
                    "state": "accepted",
                }
            ],
            "sources": sources or [self.source()],
        }
        return {
            "schema": protocol.AUTHORITY_CUT_SCHEMA,
            "authority_cut_id": "authority-cut-41",
            "recorded_at": "2026-08-19T10:05:00+00:00",
            "program": {
                "program_id": "guardian-program-main",
                "as_of_sequence": 41,
                "last_event_sha256": SHA_A,
                "accepted_event_id": "event-task-accepted",
                "accepted_event_sha256": "d" * 64,
                "accepted_event_sequence": 40,
            },
            "repository": {
                "root_identity": protocol.repository_root_identity(self.repo),
                "base_commit": self.base_commit,
            },
            "selected_tasks": [task],
        }

    def capture(self, authority: dict, **kwargs: object) -> dict:
        plan = protocol.make_capture_plan(
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )
        return protocol.capture_plan(
            plan,
            repository_root=self.repo,
            authority_root=self.authority_root,
            captured_at="2026-08-20T01:01:00+00:00",
            **kwargs,
        )

    def assert_denied(
        self, disposition: str, code: str, callable_: object, *args: object, **kwargs: object
    ) -> protocol.AcceptedSnapshotError:
        with self.assertRaises(protocol.AcceptedSnapshotError) as raised:
            callable_(*args, **kwargs)  # type: ignore[operator]
        self.assertEqual(raised.exception.disposition, disposition)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_closed_plain_json_authority_schema_rejects_extra_and_non_json(self) -> None:
        authority = self.authority()
        authority["mutable_tail"] = []
        self.assert_denied(
            "BLOCKED",
            "AUTHORITY_SCHEMA",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )
        authority = self.authority()
        authority["selected_tasks"][0]["sources"][0]["path"] = Path("changed.txt")
        self.assert_denied(
            "BLOCKED",
            "AUTHORITY_NOT_PLAIN_JSON",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )

    def test_event_status_mismatch_and_mutable_status_are_blocked(self) -> None:
        authority = self.authority()
        authority["program"]["accepted_event_sha256"] = SHA_C
        self.assert_denied(
            "BLOCKED",
            "ACCEPTED_EVENT_MISMATCH",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )

        authority = self.authority()
        authority["selected_tasks"][0]["generation_state"] = "completed"
        self.assert_denied(
            "INSUFFICIENT",
            "GENERATION_NOT_ACCEPTED",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )

    def test_stale_verification_run_is_blocked(self) -> None:
        authority = self.authority()
        authority["selected_tasks"][0]["accepted_verification"][
            "task_definition_sha256"
        ] = SHA_C
        self.assert_denied(
            "BLOCKED",
            "STALE_VERIFICATION",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )

    def test_active_evidence_error_or_set_drift_is_insufficient(self) -> None:
        authority = self.authority()
        authority["selected_tasks"][0]["active_evidence"][0]["status"] = "error"
        self.assert_denied(
            "INSUFFICIENT",
            "ACTIVE_EVIDENCE_ERROR",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )

        authority = self.authority()
        authority["selected_tasks"][0]["active_evidence"][0]["sha256"] = SHA_A
        self.assert_denied(
            "BLOCKED",
            "EVIDENCE_SET_MISMATCH",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )

    def test_superseded_open_or_unaccepted_generation_is_insufficient(self) -> None:
        cases = (
            ("superseded_by_generation", 4, "GENERATION_SUPERSEDED"),
            ("open_successor_generation", 4, "OPEN_SUCCESSOR"),
            ("generation_state", "open", "GENERATION_NOT_ACCEPTED"),
        )
        for field, value, code in cases:
            with self.subTest(field=field):
                authority = self.authority()
                authority["selected_tasks"][0][field] = value
                self.assert_denied(
                    "INSUFFICIENT",
                    code,
                    protocol.make_capture_plan,
                    authority,
                    repository_root=self.repo,
                    planned_at="2026-08-20T01:00:00+00:00",
                )

    def test_dependency_closure_must_be_accepted_and_predecessor_selected(self) -> None:
        authority = self.authority()
        authority["selected_tasks"][0]["dependency_closure"][0]["state"] = "open"
        self.assert_denied(
            "INSUFFICIENT",
            "DEPENDENCY_NOT_ACCEPTED",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )
        authority = self.authority()
        authority["selected_tasks"][0]["selected_predecessor"]["generation"] = 1
        self.assert_denied(
            "BLOCKED",
            "PREDECESSOR_CLOSURE_MISMATCH",
            protocol.make_capture_plan,
            authority,
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )

    def test_exact_current_bytes_publish_with_data_only_receipt(self) -> None:
        receipt = self.capture(self.authority())
        blob = receipt["blobs"][0]
        destination = self.authority_root / blob["relative_path"]
        self.assertEqual(destination.read_bytes(), self.changed_bytes)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(destination.stat().st_nlink, 1)
        self.assertFalse(receipt["execution_authorized"])
        self.assertFalse(receipt["composition_ready"])
        self.assertTrue(receipt["later_coordinator_authority_required"])
        protocol.validate_capture_receipt(receipt)

    def test_missing_or_polluted_current_bytes_are_insufficient(self) -> None:
        (self.repo / "changed.txt").unlink()
        self.assert_denied("INSUFFICIENT", "SOURCE_MISSING", self.capture, self.authority())

        (self.repo / "changed.txt").write_bytes(b"T01 critic polluted current bytes\n")
        os.chmod(self.repo / "changed.txt", 0o600)
        self.assert_denied("BLOCKED", "SOURCE_DRIFT", self.capture, self.authority())

    def test_known_t01_critic_shape_cannot_be_blessed_by_authority_digest(self) -> None:
        polluted = json.dumps(
            {
                "schema": "sulde-intent-critic-v1",
                "task_id": "T01",
                "verdict": "accepted",
            },
            sort_keys=True,
        ).encode()
        (self.repo / "changed.txt").write_bytes(polluted)
        os.chmod(self.repo / "changed.txt", 0o600)
        authority = self.authority([self.source(data=polluted)])
        self.assert_denied("BLOCKED", "KNOWN_T01_CRITIC_POLLUTION", self.capture, authority)

    def test_base_path_reads_pinned_blob_not_worktree_or_filter(self) -> None:
        attributes = self.repo / ".gitattributes"
        attributes.write_text("base.txt filter=poison\n", encoding="utf-8")
        git(self.repo, "config", "filter.poison.smudge", "printf FILTERED")
        git(self.repo, "config", "filter.poison.clean", "cat")
        (self.repo / "base.txt").write_bytes(b"mutable worktree poison\n")
        source = self.source(
            path="base.txt",
            data=self.base_bytes,
            operation="unchanged",
            source_kind="git_object",
            mode=0o644,
            before=digest(self.base_bytes),
            git_object=self.base_object,
        )
        receipt = self.capture(self.authority([source]))
        destination = self.authority_root / receipt["blobs"][0]["relative_path"]
        self.assertEqual(destination.read_bytes(), self.base_bytes)

    def test_wrong_git_object_binding_is_blocked(self) -> None:
        source = self.source(
            path="base.txt",
            data=self.base_bytes,
            operation="unchanged",
            source_kind="git_object",
            mode=0o644,
            before=digest(self.base_bytes),
            git_object="f" * len(self.base_object),
        )
        self.assert_denied("BLOCKED", "GIT_OBJECT_MISMATCH", self.capture, self.authority([source]))

    def test_symlink_hardlink_and_path_traversal_are_blocked(self) -> None:
        (self.repo / "changed.txt").unlink()
        os.symlink("base.txt", self.repo / "changed.txt")
        self.assert_denied("BLOCKED", "SOURCE_SYMLINK", self.capture, self.authority())

        (self.repo / "changed.txt").unlink()
        (self.repo / "changed.txt").write_bytes(self.changed_bytes)
        os.chmod(self.repo / "changed.txt", 0o600)
        os.link(self.repo / "changed.txt", self.repo / "other-link")
        self.assert_denied("BLOCKED", "SOURCE_HARDLINK", self.capture, self.authority())

        for path in ("../changed.txt", "/changed.txt", "a//b", "a/./b"):
            with self.subTest(path=path):
                authority = self.authority([self.source(path=path)])
                self.assert_denied(
                    "BLOCKED",
                    "UNSAFE_PATH",
                    protocol.make_capture_plan,
                    authority,
                    repository_root=self.repo,
                    planned_at="2026-08-20T01:00:00+00:00",
                )

    def test_nfkc_casefold_path_collision_is_blocked(self) -> None:
        second = self.source(path="ＣＨＡＮＧＥＤ.txt")
        first = self.source(path="changed.txt")
        self.assert_denied(
            "BLOCKED",
            "PATH_COLLISION",
            protocol.make_capture_plan,
            self.authority([first, second]),
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )

    def test_parent_rename_during_read_is_blocked(self) -> None:
        nested = self.repo / "nested"
        nested.mkdir(mode=0o700)
        target = nested / "accepted.txt"
        target.write_bytes(self.changed_bytes)
        os.chmod(target, 0o600)
        authority = self.authority([self.source(path="nested/accepted.txt")])
        renamed = self.repo / "nested-old"

        def boundary(label: str, _details: dict[str, object]) -> None:
            if label == "source.after_open":
                nested.rename(renamed)
                nested.mkdir(mode=0o700)

        self.assert_denied(
            "BLOCKED", "SOURCE_PARENT_DRIFT", self.capture, authority, boundary=boundary
        )

    def test_owner_and_mode_drift_are_blocked(self) -> None:
        os.chmod(self.repo / "changed.txt", 0o644)
        self.assert_denied("BLOCKED", "SOURCE_MODE", self.capture, self.authority())
        os.chmod(self.repo / "changed.txt", 0o600)
        with (
            mock.patch.object(
                protocol, "_validate_authority_root", return_value=self.authority_root
            ),
            mock.patch.object(protocol.os, "geteuid", return_value=os.geteuid() + 1000),
        ):
            self.assert_denied(
                "BLOCKED", "SOURCE_OWNER", self.capture, self.authority()
            )

    def test_fsync_failure_never_makes_final_blob_visible(self) -> None:
        real_fsync = protocol.os.fsync
        failed = False

        def fail_first_regular_file(fd: int) -> None:
            nonlocal failed
            if not failed and stat.S_ISREG(os.fstat(fd).st_mode):
                failed = True
                raise OSError("synthetic fsync failure")
            real_fsync(fd)

        with mock.patch.object(protocol.os, "fsync", side_effect=fail_first_regular_file):
            self.assert_denied("BLOCKED", "PUBLICATION_IO", self.capture, self.authority())
        final = self.authority_root / protocol.accepted_blob_relative_path(digest(self.changed_bytes))
        self.assertFalse(final.exists())

    def test_process_death_after_visibility_recovers_to_single_link(self) -> None:
        died = False

        def boundary(label: str, _details: dict[str, object]) -> None:
            nonlocal died
            if label == "publish.after_link" and not died:
                died = True
                raise SimulatedDeath()

        plan = protocol.make_capture_plan(
            self.authority(),
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )
        with self.assertRaises(SimulatedDeath):
            protocol.capture_plan(
                plan,
                repository_root=self.repo,
                authority_root=self.authority_root,
                captured_at="2026-08-20T01:01:00+00:00",
                boundary=boundary,
            )
        receipt = protocol.capture_plan(
            plan,
            repository_root=self.repo,
            authority_root=self.authority_root,
            captured_at="2026-08-20T01:02:00+00:00",
        )
        destination = self.authority_root / receipt["blobs"][0]["relative_path"]
        self.assertEqual(destination.read_bytes(), self.changed_bytes)
        self.assertEqual(destination.stat().st_nlink, 1)
        self.assertEqual(list(destination.parent.glob(".stage-*")), [])

    def test_exception_at_every_publication_boundary_is_recoverable(self) -> None:
        labels = (
            "publish.after_directory_fsync",
            "publish.after_lock_entry_fsync",
            "publish.after_stage_entry_fsync",
            "publish.after_write",
            "publish.after_file_fsync",
            "publish.after_link",
            "publish.after_final_dir_fsync",
            "publish.after_stage_unlink",
        )
        plan = protocol.make_capture_plan(
            self.authority(),
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )
        for index, selected_label in enumerate(labels):
            with self.subTest(boundary=selected_label):
                authority_root = self.root / f"exception-authority-{index}"
                authority_root.mkdir(mode=0o700)
                injected = False

                def boundary(label: str, _details: dict[str, object]) -> None:
                    nonlocal injected
                    if label == selected_label and not injected:
                        injected = True
                        raise SimulatedException(selected_label)

                self.assert_denied(
                    "BLOCKED",
                    "PUBLICATION_IO",
                    protocol.capture_plan,
                    plan,
                    repository_root=self.repo,
                    authority_root=authority_root,
                    captured_at="2026-08-20T01:01:00+00:00",
                    boundary=boundary,
                )
                self.assertTrue(injected)
                receipt = protocol.capture_plan(
                    plan,
                    repository_root=self.repo,
                    authority_root=authority_root,
                    captured_at="2026-08-20T01:02:00+00:00",
                )
                destination = authority_root / receipt["blobs"][0]["relative_path"]
                self.assertEqual(destination.read_bytes(), self.changed_bytes)
                self.assertEqual(destination.stat().st_nlink, 1)
                self.assertEqual(list(destination.parent.glob(".stage-*")), [])

    def test_process_death_at_every_pre_and_post_visibility_boundary_recovers(self) -> None:
        labels = (
            "publish.after_directory_fsync",
            "publish.after_lock_entry_fsync",
            "publish.after_stage_entry_fsync",
            "publish.after_write",
            "publish.after_file_fsync",
            "publish.after_link",
            "publish.after_final_dir_fsync",
            "publish.after_stage_unlink",
        )
        plan = protocol.make_capture_plan(
            self.authority(),
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )
        for index, selected_label in enumerate(labels):
            with self.subTest(boundary=selected_label):
                authority_root = self.root / f"death-authority-{index}"
                authority_root.mkdir(mode=0o700)
                injected = False

                def boundary(label: str, _details: dict[str, object]) -> None:
                    nonlocal injected
                    if label == selected_label and not injected:
                        injected = True
                        raise SimulatedDeath(selected_label)

                with self.assertRaises(SimulatedDeath):
                    protocol.capture_plan(
                        plan,
                        repository_root=self.repo,
                        authority_root=authority_root,
                        captured_at="2026-08-20T01:01:00+00:00",
                        boundary=boundary,
                    )
                self.assertTrue(injected)
                receipt = protocol.capture_plan(
                    plan,
                    repository_root=self.repo,
                    authority_root=authority_root,
                    captured_at="2026-08-20T01:02:00+00:00",
                )
                destination = authority_root / receipt["blobs"][0]["relative_path"]
                self.assertEqual(destination.read_bytes(), self.changed_bytes)
                self.assertEqual(destination.stat().st_nlink, 1)
                self.assertEqual(list(destination.parent.glob(".stage-*")), [])

    def test_concurrent_same_plan_is_idempotent(self) -> None:
        plan = protocol.make_capture_plan(
            self.authority(),
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )
        receipts: list[dict] = []
        failures: list[BaseException] = []
        gate = threading.Barrier(3)

        def run() -> None:
            try:
                gate.wait()
                receipts.append(
                    protocol.capture_plan(
                        plan,
                        repository_root=self.repo,
                        authority_root=self.authority_root,
                        captured_at="2026-08-20T01:01:00+00:00",
                    )
                )
            except BaseException as error:
                failures.append(error)

        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(failures, [])
        self.assertEqual(len(receipts), 2)
        self.assertEqual(receipts[0]["receipt_id"], receipts[1]["receipt_id"])
        destination = self.authority_root / receipts[0]["blobs"][0]["relative_path"]
        self.assertEqual(destination.stat().st_nlink, 1)

    def test_concurrent_different_plans_do_not_cross_bless(self) -> None:
        other_bytes = b"a second accepted source\n"
        other = self.repo / "other.txt"
        other.write_bytes(other_bytes)
        os.chmod(other, 0o600)
        authorities = [
            self.authority(),
            self.authority([self.source(path="other.txt", data=other_bytes)]),
        ]
        plans = [
            protocol.make_capture_plan(
                authority,
                repository_root=self.repo,
                planned_at="2026-08-20T01:00:00+00:00",
            )
            for authority in authorities
        ]
        receipts: list[dict] = []
        failures: list[BaseException] = []
        gate = threading.Barrier(3)

        def run(plan: dict) -> None:
            try:
                gate.wait()
                receipts.append(
                    protocol.capture_plan(
                        plan,
                        repository_root=self.repo,
                        authority_root=self.authority_root,
                        captured_at="2026-08-20T01:01:00+00:00",
                    )
                )
            except BaseException as error:
                failures.append(error)

        threads = [threading.Thread(target=run, args=(plan,)) for plan in plans]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(failures, [])
        self.assertEqual(
            {blob["sha256"] for receipt in receipts for blob in receipt["blobs"]},
            {digest(self.changed_bytes), digest(other_bytes)},
        )

    def test_plan_and_receipt_identity_reject_tampering(self) -> None:
        plan = protocol.make_capture_plan(
            self.authority(),
            repository_root=self.repo,
            planned_at="2026-08-20T01:00:00+00:00",
        )
        tampered = copy.deepcopy(plan)
        tampered["sources"][0]["size"] += 1
        self.assert_denied(
            "BLOCKED",
            "PLAN_IDENTITY_MISMATCH",
            protocol.capture_plan,
            tampered,
            repository_root=self.repo,
            authority_root=self.authority_root,
            captured_at="2026-08-20T01:01:00+00:00",
        )
        receipt = self.capture(self.authority())
        receipt["execution_authorized"] = True
        self.assert_denied(
            "BLOCKED", "RECEIPT_SCHEMA", protocol.validate_capture_receipt, receipt
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

import guardian_program as guardian_program_module  # noqa: E402
from guardian_program import (  # noqa: E402
    EVENT_SCHEMA,
    EVIDENCE_SCHEMA,
    GuardianProgramError,
    MANIFEST_SCHEMA,
    TASK_SCHEMA,
    _append_event,
    authority_recovery_confirmation,
    complete,
    final_gate,
    initialize,
    materialize_completion_permissions,
    project,
    record_evidence,
    record_finding,
    register_task,
    resolve_finding,
    rotate_lost_authority,
    supersede_evidence,
    transition,
)


class GuardianProgramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.program = self.base / "program"
        self.manifest_path = self.base / "manifest-source.json"
        self.manifest_path.write_text(
            json.dumps(
                {
                    "schema": MANIFEST_SCHEMA,
                    "program_id": "guardian-p0",
                    "objective": "close every guardian remediation requirement",
                    "coordinator": "coordinator",
                    "requirements": [
                        {
                            "id": "R1",
                            "title": "one traceable requirement",
                            "acceptance": ["accepted task and independent evidence"],
                        }
                    ],
                    "program_evidence_required": ["full_isolated_suite"],
                    "allow_human_deferred": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        initialize(self.program, self.manifest_path, actor="coordinator")
        self.evidence_counter = 0
        self.previous_authority = os.environ.get("SULDE_GUARDIAN_PROGRAM_AUTHORITY")
        os.environ["SULDE_GUARDIAN_PROGRAM_AUTHORITY"] = (
            self.program / ".coordinator-authority"
        ).read_text(encoding="utf-8").strip()

    def tearDown(self) -> None:
        if self.previous_authority is None:
            os.environ.pop("SULDE_GUARDIAN_PROGRAM_AUTHORITY", None)
        else:
            os.environ["SULDE_GUARDIAN_PROGRAM_AUTHORITY"] = self.previous_authority
        self.temp.cleanup()

    def task_file(
        self,
        task_id: str = "T1",
        *,
        owner: str = "worker",
        depends_on: list[str] | None = None,
        supersedes: list[str] | None = None,
        requirements: list[str] | None = None,
        owned_paths: list[str] | None = None,
    ) -> Path:
        path = self.base / f"{task_id}.json"
        path.write_text(
            json.dumps(
                {
                    "schema": TASK_SCHEMA,
                    "task_id": task_id,
                    "title": f"task {task_id}",
                    "owner": owner,
                    "capability_tier": "deep",
                    "base_commit": "snapshot-deadbeef",
                    "depends_on": depends_on or [],
                    "supersedes": supersedes or [],
                    "owned_paths": owned_paths or [f"scripts/kb/{task_id.lower()}.py"],
                    "requirements": requirements if requirements is not None else ["R1"],
                    "acceptance": ["targeted and integration evidence are recorded"],
                    "evidence_gates": {
                        "implemented": ["task_report", "changed_files"],
                        "task_verified": ["targeted_tests", "failure_injection"],
                        "integrated": ["integration_tests"],
                        "system_verified": ["system_tests"],
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def evidence(
        self,
        kind: str,
        *,
        task_id: str = "T1",
        actor: str = "worker",
        scope: str = "task",
        findings: list[str] | None = None,
        commands: list[dict] | None = None,
        verdict: str = "pass",
        run_id: str | None = None,
        acceptance_rows: list[dict] | None = None,
    ) -> Path:
        directory = self.program / "evidence"
        directory.mkdir(exist_ok=True)
        self.evidence_counter += 1
        suffix = f"{self.evidence_counter:03d}"
        path = directory / f"{scope}-{task_id or 'program'}-{kind}-{suffix}.json"
        artifact = directory / f"{scope}-{task_id or 'program'}-{kind}-{suffix}.artifact.txt"
        artifact.write_text(f"synthetic {kind} fact\n", encoding="utf-8")
        summary = f"independent {kind} evidence"
        requirements = []
        acceptance = []
        status = project(self.program)
        baseline = (
            status["tasks"][task_id]["base_commit"]
            if scope == "task"
            else f"program:{status['program_id']}"
        )
        effective_run_id = run_id or (
            status["tasks"][task_id]["verification_run_id"]
            if scope == "task"
            else f"run-{suffix}"
        )
        if scope == "task" and kind == "requirement_traceability":
            requirements = status["tasks"][task_id]["requirements"]
            acceptance = [
                {
                    "requirement_id": requirement_id,
                    "clause": clause,
                    "fact": f"synthetic evidence for {requirement_id}: {clause}",
                }
                for requirement_id in requirements
                for clause in status["requirements"][requirement_id]["acceptance"]
            ]
        if acceptance_rows is not None:
            acceptance = acceptance_rows
        path.write_text(
            json.dumps(
                {
                    "schema": EVIDENCE_SCHEMA,
                    "scope": scope,
                    "task_id": task_id,
                    "kind": kind,
                    "baseline": baseline,
                    "run_id": effective_run_id,
                    "verdict": verdict,
                    "summary": summary,
                    "facts": [f"synthetic {kind} fixture passed"],
                    "requirements": requirements,
                    "findings": findings or [],
                    "acceptance": acceptance,
                    "commands": commands or [],
                    "artifacts": [
                        {
                            "path": artifact.relative_to(self.program).as_posix(),
                            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        record_evidence(
            self.program,
            actor=actor,
            scope=scope,
            task_id=task_id,
            kind=kind,
            path=path,
            summary=summary,
        )
        return path

    def register_and_start(self) -> None:
        register_task(self.program, self.task_file(), actor="coordinator")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="ready",
            note="scope and ownership checked",
        )
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="running",
            note="isolated implementation started",
        )

    def make_task_accepted(self) -> None:
        register_task(self.program, self.task_file(), actor="coordinator")
        self.advance_task_to_accepted("T1")

    def advance_task_to_accepted(self, task_id: str, *, owner: str = "worker") -> None:
        transition(
            self.program,
            actor=owner,
            task_id=task_id,
            destination="ready",
            note="scope and ownership checked",
        )
        transition(
            self.program,
            actor=owner,
            task_id=task_id,
            destination="running",
            note="isolated implementation started",
        )
        self.evidence("task_report", task_id=task_id, actor=owner)
        self.evidence("changed_files", task_id=task_id, actor=owner)
        transition(
            self.program,
            actor=owner,
            task_id=task_id,
            destination="implemented",
            note="worker implementation complete",
        )
        self.evidence("targeted_tests", task_id=task_id, actor=owner)
        self.evidence("failure_injection", task_id=task_id, actor=owner)
        transition(
            self.program,
            actor="coordinator",
            task_id=task_id,
            destination="task_verified",
            note="coordinator independently verified the task",
        )
        self.evidence(
            "integration_tests", task_id=task_id, actor="coordinator"
        )
        transition(
            self.program,
            actor="coordinator",
            task_id=task_id,
            destination="integrated",
            note="single-writer integration passed",
        )
        self.evidence("system_tests", task_id=task_id, actor="coordinator")
        transition(
            self.program,
            actor="coordinator",
            task_id=task_id,
            destination="system_verified",
            note="system gate passed",
        )
        self.evidence(
            "requirement_traceability", task_id=task_id, actor="coordinator"
        )
        transition(
            self.program,
            actor="coordinator",
            task_id=task_id,
            destination="accepted",
            note="task traceability is complete",
        )

    def test_worker_can_implement_but_cannot_self_verify(self) -> None:
        self.register_and_start()
        with self.assertRaisesRegex(GuardianProgramError, "lacks evidence"):
            transition(
                self.program,
                actor="worker",
                task_id="T1",
                destination="implemented",
                note="unsupported completion claim",
            )
        self.evidence("task_report")
        self.evidence("changed_files")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="implemented",
            note="implementation evidence attached",
        )
        self.evidence("targeted_tests")
        self.evidence("failure_injection")
        with self.assertRaisesRegex(GuardianProgramError, "only the coordinator"):
            transition(
                self.program,
                actor="worker",
                task_id="T1",
                destination="task_verified",
                note="worker cannot accept its own result",
            )
        self.assertEqual(project(self.program)["tasks"]["T1"]["state"], "implemented")

    def test_open_finding_blocks_verification_until_coordinator_resolves_it(self) -> None:
        self.register_and_start()
        self.evidence("task_report")
        self.evidence("changed_files")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="implemented",
            note="implementation complete",
        )
        self.evidence("targeted_tests")
        self.evidence("failure_injection")
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F1",
            symptom="an alias bypassed the resource gate",
            evidence="synthetic alias case failed before the fix",
            evidence_status="verified",
        )
        with self.assertRaisesRegex(GuardianProgramError, "unresolved findings"):
            transition(
                self.program,
                actor="coordinator",
                task_id="T1",
                destination="task_verified",
                note="must not hide the finding",
            )
        resolve_finding(
            self.program,
            actor="coordinator",
            finding_id="F1",
            disposition="fixed_current",
            root_cause="resource identity used the presentation string",
            resolution="canonical identity is now the ledger key",
        )
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="task_verified",
            note="finding and task evidence independently verified",
        )
        finding = project(self.program)["findings"]["F1"]
        self.assertEqual(finding["disposition"], "fixed_current")

    def test_dependencies_must_be_accepted_before_ready(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        register_task(
            self.program,
            self.task_file("T2", depends_on=["T1"], requirements=[]),
            actor="coordinator",
        )
        with self.assertRaisesRegex(GuardianProgramError, "dependencies"):
            transition(
                self.program,
                actor="worker",
                task_id="T2",
                destination="ready",
                note="dependency is not accepted",
            )

    def test_final_gate_requires_accepted_coverage_and_program_evidence(self) -> None:
        self.make_task_accepted()
        gate = final_gate(self.program)
        self.assertFalse(gate["ready"])
        self.assertEqual(
            gate["blockers"],
            [{"kind": "missing_program_evidence", "id": "full_isolated_suite"}],
        )
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        self.assertTrue(final_gate(self.program)["ready"])
        complete(self.program, actor="coordinator")
        self.assertTrue(project(self.program)["program_completed"])

    def test_evidence_digest_drift_fails_the_final_gate(self) -> None:
        self.make_task_accepted()
        evidence_path = self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        self.assertTrue(final_gate(self.program)["ready"])
        evidence_path.write_text("tampered", encoding="utf-8")
        gate = final_gate(self.program)
        self.assertFalse(gate["ready"])
        self.assertEqual(gate["blockers"][0]["kind"], "invalid_evidence")
        self.assertEqual(gate["blockers"][0]["reason"], "digest_mismatch")

    def test_event_log_tampering_fails_closed(self) -> None:
        register_task(self.program, self.task_file(), actor="coordinator")
        path = self.program / "events.jsonl"
        rows = path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(rows[-1])
        self.assertEqual(tampered["schema"], EVENT_SCHEMA)
        tampered["payload"]["title"] = "silently changed"
        rows[-1] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(GuardianProgramError, "digest mismatch"):
            project(self.program)

    def test_human_deferral_is_not_a_silent_resolution(self) -> None:
        self.register_and_start()
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F1",
            symptom="a live host fact is unavailable",
            evidence="no independent canary was captured",
            evidence_status="inconclusive",
        )
        with self.assertRaisesRegex(GuardianProgramError, "human deferral"):
            resolve_finding(
                self.program,
                actor="coordinator",
                finding_id="F1",
                disposition="deferred_human",
                root_cause="live observation is unavailable",
                resolution="defer until a supervised canary can run",
                human_evidence="receipt-present-but-manifest-forbids-deferral",
            )

    def test_overlapping_path_ownership_requires_serial_dependency(self) -> None:
        register_task(
            self.program,
            self.task_file("T1", owned_paths=["scripts/kb/shared/**"]),
            actor="coordinator",
        )
        with self.assertRaisesRegex(GuardianProgramError, "overlaps"):
            register_task(
                self.program,
                self.task_file(
                    "T2",
                    requirements=[],
                    owned_paths=["scripts/kb/shared/state.py"],
                ),
                actor="coordinator",
            )
        register_task(
            self.program,
            self.task_file(
                "T3",
                depends_on=["T1"],
                requirements=[],
                owned_paths=["scripts/kb/shared/state.py"],
            ),
            actor="coordinator",
        )
        self.assertIn("T3", project(self.program)["tasks"])

    def test_ownership_rejects_case_and_unicode_equivalent_aliases(self) -> None:
        register_task(
            self.program,
            self.task_file("T10", owned_paths=["scripts/kb/shared.py"]),
            actor="coordinator",
        )
        with self.assertRaisesRegex(GuardianProgramError, "overlaps"):
            register_task(
                self.program,
                self.task_file(
                    "T11",
                    requirements=[],
                    owned_paths=["scripts/kb/SHARED.py"],
                ),
                actor="coordinator",
            )

        register_task(
            self.program,
            self.task_file(
                "T12",
                requirements=[],
                owned_paths=["scripts/kb/caf\u00e9.py"],
            ),
            actor="coordinator",
        )
        with self.assertRaisesRegex(GuardianProgramError, "overlaps"):
            register_task(
                self.program,
                self.task_file(
                    "T13",
                    requirements=[],
                    owned_paths=["scripts/kb/cafe\u0301.py"],
                ),
                actor="coordinator",
            )

    def test_owned_paths_reject_ambiguous_glob_syntax(self) -> None:
        for index, owned_path in enumerate(
            (
                "scripts/kb/file[\u00df].py",
                "scripts/kb/file[\ufb03].py",
                "scripts/kb/filea*.py",
                "scripts/kb/file?.py",
                "scripts/**/state.py",
            ),
            start=20,
        ):
            with self.subTest(owned_path=owned_path):
                before = project(self.program)["event_count"]
                with self.assertRaisesRegex(GuardianProgramError, "terminal /\\*\\* subtree"):
                    register_task(
                        self.program,
                        self.task_file(
                            f"T{index}",
                            requirements=[],
                            owned_paths=[owned_path],
                        ),
                        actor="coordinator",
                    )
                self.assertEqual(project(self.program)["event_count"], before)

    def test_stale_writer_compare_and_append_fails_without_a_partial_event(self) -> None:
        stale = project(self.program)["last_event_sha256"]
        register_task(self.program, self.task_file(), actor="coordinator")
        before = project(self.program)["event_count"]
        with self.assertRaisesRegex(GuardianProgramError, "state changed"):
            _append_event(
                self.program,
                actor="coordinator",
                kind="unsupported_stale_event",
                payload={},
                expected_last_sha256=stale,
            )
        self.assertEqual(project(self.program)["event_count"], before)

    def test_only_coordinator_can_unblock_a_task(self) -> None:
        self.register_and_start()
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="blocked",
            note="worker reports a real blocker",
        )
        with self.assertRaisesRegex(GuardianProgramError, "coordinator may unblock"):
            transition(
                self.program,
                actor="worker",
                task_id="T1",
                destination="running",
                note="worker must not self-clear the blocker",
            )

    def test_drifted_task_evidence_blocks_task_verification(self) -> None:
        self.register_and_start()
        self.evidence("task_report")
        self.evidence("changed_files")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="implemented",
            note="implementation complete",
        )
        targeted = self.evidence("targeted_tests")
        self.evidence("failure_injection")
        targeted.write_text("drifted", encoding="utf-8")
        with self.assertRaisesRegex(GuardianProgramError, "has drifted"):
            transition(
                self.program,
                actor="coordinator",
                task_id="T1",
                destination="task_verified",
                note="drift must be rejected before integration",
            )

    def test_earlier_gate_evidence_remains_authoritative_at_later_gates(self) -> None:
        self.register_and_start()
        report = self.evidence("task_report")
        self.evidence("changed_files")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="implemented",
            note="implementation complete",
        )
        self.evidence("targeted_tests")
        self.evidence("failure_injection")
        report.write_text("drifted after implemented", encoding="utf-8")
        with self.assertRaisesRegex(GuardianProgramError, "has drifted"):
            transition(
                self.program,
                actor="coordinator",
                task_id="T1",
                destination="task_verified",
                note="all earlier evidence must remain bound",
            )

    def test_program_is_immutable_after_completion(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        complete(self.program, actor="coordinator")
        with self.assertRaisesRegex(GuardianProgramError, "already completed"):
            self.evidence(
                "after_complete",
                task_id="",
                actor="coordinator",
                scope="program",
            )

    def test_initialize_recovers_matching_orphan_manifest(self) -> None:
        orphan = self.base / "orphan-program"
        orphan.mkdir(mode=0o700)
        (orphan / "manifest.json").write_text(
            self.manifest_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (orphan / "manifest.json").chmod(0o600)
        (orphan / "events.jsonl").write_text("", encoding="utf-8")
        (orphan / "events.jsonl").chmod(0o600)
        initialize(orphan, self.manifest_path, actor="coordinator")
        recovered = project(orphan)
        self.assertEqual(recovered["event_count"], 1)

    def test_finding_evidence_status_is_closed_enum(self) -> None:
        self.register_and_start()
        with self.assertRaisesRegex(GuardianProgramError, "evidence_status is invalid"):
            record_finding(
                self.program,
                actor="worker",
                task_id="T1",
                finding_id="F-invalid",
                symptom="invalid evidence classification",
                evidence="synthetic fixture",
                evidence_status="probably",
            )

    def test_duplicate_finding_resolution_does_not_append(self) -> None:
        self.register_and_start()
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F-once",
            symptom="one finding",
            evidence="synthetic evidence",
            evidence_status="verified",
        )
        resolve_finding(
            self.program,
            actor="coordinator",
            finding_id="F-once",
            disposition="fixed_current",
            root_cause="one cause",
            resolution="one resolution",
        )
        before = project(self.program)["event_count"]
        with self.assertRaisesRegex(GuardianProgramError, "already resolved"):
            resolve_finding(
                self.program,
                actor="coordinator",
                finding_id="F-once",
                disposition="fixed_current",
                root_cause="second cause",
                resolution="second resolution",
            )
        self.assertEqual(project(self.program)["event_count"], before)

    def test_actor_label_cannot_replace_coordinator_authority(self) -> None:
        self.register_and_start()
        self.evidence("task_report")
        self.evidence("changed_files")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="implemented",
            note="worker report is centrally recorded",
        )
        self.evidence("targeted_tests")
        self.evidence("failure_injection")
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(GuardianProgramError, "controlled execution context"):
                transition(
                    self.program,
                    actor="coordinator",
                    task_id="T1",
                    destination="task_verified",
                    note="a caller-supplied label is not authority",
                )

    def test_lost_authority_recovery_is_head_bound_and_append_only(self) -> None:
        before = project(self.program)
        authority_path = self.program / ".coordinator-authority"
        authority_path.unlink()
        os.environ.pop("SULDE_GUARDIAN_PROGRAM_AUTHORITY", None)
        confirmation = authority_recovery_confirmation(
            before["program_id"], before["last_event_sha256"]
        )

        row = rotate_lost_authority(
            self.program,
            actor="coordinator",
            expected_last_sha256=before["last_event_sha256"],
            confirmation=confirmation,
            approval_id="human-approved-recovery-1",
            reason="the owner-only capability file was lost between worktrees",
        )

        after = project(self.program)
        replacement = authority_path.read_text(encoding="utf-8").strip()
        self.assertEqual(row["type"], "coordinator_authority_rotated")
        self.assertEqual(after["event_count"], before["event_count"] + 1)
        self.assertEqual(
            after["coordinator_authority_sha256"],
            hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
        )
        self.assertNotEqual(
            after["coordinator_authority_sha256"],
            before["coordinator_authority_sha256"],
        )
        os.environ["SULDE_GUARDIAN_PROGRAM_AUTHORITY"] = replacement
        register_task(self.program, self.task_file(), actor="coordinator")

    def test_lost_authority_recovery_rejects_wrong_head_confirmation(self) -> None:
        before = project(self.program)
        authority_path = self.program / ".coordinator-authority"
        authority_path.unlink()
        os.environ.pop("SULDE_GUARDIAN_PROGRAM_AUTHORITY", None)

        with self.assertRaisesRegex(GuardianProgramError, "does not bind"):
            rotate_lost_authority(
                self.program,
                actor="coordinator",
                expected_last_sha256=before["last_event_sha256"],
                confirmation="0" * 64,
                approval_id="human-approved-recovery-2",
                reason="negative fixture",
            )

        self.assertFalse(authority_path.exists())
        self.assertEqual(project(self.program)["event_count"], before["event_count"])

    def test_break_glass_recovery_rejects_live_matching_authority(self) -> None:
        before = project(self.program)
        confirmation = authority_recovery_confirmation(
            before["program_id"], before["last_event_sha256"]
        )
        with self.assertRaisesRegex(GuardianProgramError, "still available"):
            rotate_lost_authority(
                self.program,
                actor="coordinator",
                expected_last_sha256=before["last_event_sha256"],
                confirmation=confirmation,
                approval_id="human-approved-recovery-3",
                reason="negative fixture",
            )
        self.assertEqual(project(self.program)["event_count"], before["event_count"])

    def test_bogus_evidence_content_is_rejected_before_append(self) -> None:
        self.register_and_start()
        directory = self.program / "evidence"
        directory.mkdir(exist_ok=True)
        bogus = directory / "bogus.json"
        bogus.write_text("bogus", encoding="utf-8")
        before = project(self.program)["event_count"]
        with self.assertRaisesRegex(GuardianProgramError, "cannot read JSON object"):
            record_evidence(
                self.program,
                actor="worker",
                scope="task",
                task_id="T1",
                kind="task_report",
                path=bogus,
                summary="bogus must not count",
            )
        self.assertEqual(project(self.program)["event_count"], before)

    def test_blocked_task_cannot_bypass_unaccepted_dependency(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        register_task(
            self.program,
            self.task_file("T2", depends_on=["T1"], requirements=[]),
            actor="coordinator",
        )
        transition(
            self.program,
            actor="worker",
            task_id="T2",
            destination="blocked",
            note="waiting for dependency",
        )
        with self.assertRaisesRegex(GuardianProgramError, "dependencies"):
            transition(
                self.program,
                actor="coordinator",
                task_id="T2",
                destination="running",
                note="dependency must still be accepted",
            )

    def test_finding_cannot_transfer_to_its_own_task(self) -> None:
        self.register_and_start()
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F-self",
            symptom="self transfer",
            evidence="synthetic evidence",
            evidence_status="verified",
        )
        with self.assertRaisesRegex(GuardianProgramError, "different non-terminal"):
            resolve_finding(
                self.program,
                actor="coordinator",
                finding_id="F-self",
                disposition="transferred",
                root_cause="self transfer is not work",
                resolution="must point to a different task",
                linked_task="T1",
            )

    def test_completion_binds_an_immutable_snapshot_before_append(self) -> None:
        self.make_task_accepted()
        program_evidence = self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        source_document = json.loads(program_evidence.read_text(encoding="utf-8"))
        source_artifact = self.program / source_document["artifacts"][0]["path"]
        real_write_event_row = guardian_program_module._write_event_row

        def drift_then_append(root: Path, row: dict) -> None:
            program_evidence.write_text(
                "drifted after immutable capture", encoding="utf-8"
            )
            source_artifact.write_text(
                "artifact drifted after immutable capture", encoding="utf-8"
            )
            real_write_event_row(root, row)

        with mock.patch.object(
            guardian_program_module,
            "_write_event_row",
            side_effect=drift_then_append,
        ):
            complete(self.program, actor="coordinator")
        status = project(self.program, verify_evidence=True)
        self.assertTrue(status["program_completed"])
        self.assertEqual(status["evidence_errors"], [])
        self.assertTrue(final_gate(self.program)["ready"])

    def test_completion_rejects_drift_before_snapshot_capture(self) -> None:
        self.make_task_accepted()
        program_evidence = self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        program_evidence.write_text("drifted before capture", encoding="utf-8")
        before = project(self.program)["event_count"]
        with self.assertRaisesRegex(GuardianProgramError, "final gate is not ready"):
            complete(self.program, actor="coordinator")
        self.assertEqual(project(self.program)["event_count"], before)

    def test_empty_task_contract_is_rejected(self) -> None:
        task_path = self.task_file()
        value = json.loads(task_path.read_text(encoding="utf-8"))
        value["owned_paths"] = []
        value["acceptance"] = []
        task_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(GuardianProgramError, "non-empty"):
            register_task(self.program, task_path, actor="coordinator")

    def test_initial_event_write_failure_is_retriable_without_partial_log(self) -> None:
        retry_root = self.base / "retry-program"
        with mock.patch.object(
            guardian_program_module,
            "_write_initial_event",
            side_effect=OSError("synthetic pre-replace failure"),
        ):
            with self.assertRaisesRegex(OSError, "synthetic pre-replace"):
                initialize(retry_root, self.manifest_path, actor="coordinator")
        event_path = retry_root / "events.jsonl"
        self.assertTrue(not event_path.exists() or event_path.stat().st_size == 0)
        initialize(retry_root, self.manifest_path, actor="coordinator")
        self.assertEqual(project(retry_root)["event_count"], 1)

    def test_event_append_pre_replace_failure_preserves_valid_old_head(self) -> None:
        register_task(self.program, self.task_file(), actor="coordinator")
        before = project(self.program)
        with mock.patch.object(
            guardian_program_module.os,
            "replace",
            side_effect=OSError("synthetic event replace failure"),
        ):
            with self.assertRaisesRegex(OSError, "event replace failure"):
                record_finding(
                    self.program,
                    actor="worker",
                    task_id="T1",
                    finding_id="F-never-written",
                    symptom="synthetic failure",
                    evidence="synthetic evidence",
                    evidence_status="verified",
                )
        after = project(self.program)
        self.assertEqual(after["event_count"], before["event_count"])
        self.assertEqual(after["last_event_sha256"], before["last_event_sha256"])

    def test_event_append_post_replace_error_leaves_a_valid_committed_head(self) -> None:
        register_task(self.program, self.task_file(), actor="coordinator")
        real_replace = guardian_program_module.os.replace

        def replace_then_report_failure(source: Path, target: Path) -> None:
            real_replace(source, target)
            raise OSError("synthetic post-replace event report")

        with mock.patch.object(
            guardian_program_module.os,
            "replace",
            side_effect=replace_then_report_failure,
        ):
            with self.assertRaisesRegex(OSError, "post-replace event"):
                record_finding(
                    self.program,
                    actor="worker",
                    task_id="T1",
                    finding_id="F-committed",
                    symptom="synthetic committed finding",
                    evidence="synthetic evidence",
                    evidence_status="verified",
                )
        status = project(self.program)
        self.assertIn("F-committed", status["findings"])
        self.assertEqual(status["event_count"], 3)

    def test_manifest_boolean_is_not_truthy_string_coercion(self) -> None:
        invalid_manifest = self.base / "invalid-manifest.json"
        value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        value["allow_human_deferred"] = "false"
        invalid_manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(GuardianProgramError, "JSON boolean"):
            initialize(self.base / "invalid-program", invalid_manifest, actor="coordinator")

    def test_drifted_evidence_requires_explicit_bound_replacement(self) -> None:
        self.register_and_start()
        original_path = self.evidence("task_report")
        original_id = next(
            evidence_id
            for evidence_id, row in project(self.program)["evidence"].items()
            if row["path"] == original_path.relative_to(self.program).as_posix()
        )
        original_path.write_text("drifted", encoding="utf-8")
        replacement_path = self.evidence("task_report")
        replacement_id = next(
            evidence_id
            for evidence_id, row in project(self.program)["evidence"].items()
            if row["path"] == replacement_path.relative_to(self.program).as_posix()
        )
        errors = project(self.program, verify_evidence=True)["evidence_errors"]
        self.assertTrue(any(row["reason"] == "digest_mismatch" for row in errors))
        self.assertEqual(
            sum(row["reason"] == "active_identity_conflict" for row in errors),
            2,
        )
        supersede_evidence(
            self.program,
            actor="coordinator",
            evidence_id=original_id,
            replacement_id=replacement_id,
        )
        status = project(self.program, verify_evidence=True)
        self.assertEqual(status["evidence_errors"], [])
        self.assertEqual(status["evidence"][original_id]["superseded_by"], replacement_id)

    def test_current_head_unsupported_event_is_rejected_before_append(self) -> None:
        before = project(self.program)
        with self.assertRaisesRegex(GuardianProgramError, "unsupported program event"):
            _append_event(
                self.program,
                actor="coordinator",
                kind="unsupported_current_event",
                payload={},
                expected_last_sha256=before["last_event_sha256"],
            )
        self.assertEqual(project(self.program)["event_count"], before["event_count"])

    def test_passing_evidence_cannot_hide_a_failed_command(self) -> None:
        self.register_and_start()
        before = project(self.program)["event_count"]
        with self.assertRaisesRegex(GuardianProgramError, "successful commands"):
            self.evidence(
                "task_report",
                commands=[
                    {
                        "argv": ["synthetic-check"],
                        "exit_code": 1,
                        "result": "fail",
                    }
                ],
            )
        self.assertEqual(project(self.program)["event_count"], before)

    def test_conflicting_active_evidence_identity_blocks_completion(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
            run_id="same-run",
        )
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
            run_id="same-run",
            verdict="fail",
        )
        gate = final_gate(self.program)
        self.assertFalse(gate["ready"])
        self.assertTrue(
            any(
                blocker.get("reason") == "active_identity_conflict"
                for blocker in gate["blockers"]
            )
        )
        with self.assertRaisesRegex(GuardianProgramError, "final gate is not ready"):
            complete(self.program, actor="coordinator")

    def test_evidence_cannot_be_superseded_by_an_older_record(self) -> None:
        self.register_and_start()
        older_path = self.evidence("task_report")
        newer_path = self.evidence("task_report")
        evidence = project(self.program)["evidence"]
        older_id = next(
            key
            for key, row in evidence.items()
            if row["path"] == older_path.relative_to(self.program).as_posix()
        )
        newer_id = next(
            key
            for key, row in evidence.items()
            if row["path"] == newer_path.relative_to(self.program).as_posix()
        )
        before = project(self.program)["event_count"]
        with self.assertRaisesRegex(GuardianProgramError, "supersession"):
            supersede_evidence(
                self.program,
                actor="coordinator",
                evidence_id=newer_id,
                replacement_id=older_id,
            )
        self.assertEqual(project(self.program)["event_count"], before)

    def test_finding_evidence_supersession_preserves_all_bound_findings(self) -> None:
        self.register_and_start()
        self.evidence("task_report")
        self.evidence("changed_files")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="implemented",
            note="implementation complete",
        )
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F1",
            symptom="first disputed finding",
            evidence="synthetic evidence one",
            evidence_status="verified",
        )
        first_path = self.evidence(
            "finding_resolution", actor="coordinator", findings=["F1"]
        )
        first_id = next(
            evidence_id
            for evidence_id, row in project(self.program)["evidence"].items()
            if row["path"] == first_path.relative_to(self.program).as_posix()
        )
        resolve_finding(
            self.program,
            actor="coordinator",
            finding_id="F1",
            disposition="rejected_with_evidence",
            root_cause="the finding was disproven",
            resolution="bind rejection to exact evidence",
            evidence_id=first_id,
        )
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F2",
            symptom="second independent finding",
            evidence="synthetic evidence two",
            evidence_status="verified",
        )
        second_path = self.evidence(
            "finding_resolution", actor="coordinator", findings=["F2"]
        )
        second_id = next(
            evidence_id
            for evidence_id, row in project(self.program)["evidence"].items()
            if row["path"] == second_path.relative_to(self.program).as_posix()
        )
        with self.assertRaisesRegex(GuardianProgramError, "supersession"):
            supersede_evidence(
                self.program,
                actor="coordinator",
                evidence_id=first_id,
                replacement_id=second_id,
            )
        combined_path = self.evidence(
            "finding_resolution",
            actor="coordinator",
            findings=["F1", "F2"],
        )
        combined_id = next(
            evidence_id
            for evidence_id, row in project(self.program)["evidence"].items()
            if row["path"] == combined_path.relative_to(self.program).as_posix()
        )
        supersede_evidence(
            self.program,
            actor="coordinator",
            evidence_id=first_id,
            replacement_id=combined_id,
        )
        supersede_evidence(
            self.program,
            actor="coordinator",
            evidence_id=second_id,
            replacement_id=combined_id,
        )
        resolve_finding(
            self.program,
            actor="coordinator",
            finding_id="F2",
            disposition="fixed_current",
            root_cause="a second independent cause",
            resolution="the second finding was fixed",
        )
        self.evidence("targeted_tests")
        self.evidence("failure_injection")
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="task_verified",
            note="all findings retain active evidence",
        )
        self.evidence("integration_tests", actor="coordinator")
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="integrated",
            note="integration passed",
        )
        self.evidence("system_tests", actor="coordinator")
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="system_verified",
            note="system test passed",
        )
        self.evidence("requirement_traceability", actor="coordinator")
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="accepted",
            note="traceability passed",
        )
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        self.assertTrue(final_gate(self.program)["ready"])
        complete(self.program, actor="coordinator")
        self.assertTrue(project(self.program)["program_completed"])

    def test_successor_and_predecessor_cannot_run_concurrently(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="ready",
            note="predecessor is ready",
        )
        register_task(
            self.program,
            self.task_file("T2", supersedes=["T1"], requirements=["R1"]),
            actor="coordinator",
        )
        with self.assertRaisesRegex(GuardianProgramError, "successor prevents"):
            transition(
                self.program,
                actor="worker",
                task_id="T1",
                destination="running",
                note="must not overlap successor",
            )
        with self.assertRaisesRegex(GuardianProgramError, "predecessor is superseded"):
            transition(
                self.program,
                actor="worker",
                task_id="T2",
                destination="ready",
                note="must wait for explicit handoff",
            )
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="superseded",
            superseded_by="T2",
            note="explicit ownership handoff",
        )
        transition(
            self.program,
            actor="worker",
            task_id="T2",
            destination="ready",
            note="handoff is now authoritative",
        )

    def test_final_gate_follows_a_supersession_chain(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        register_task(
            self.program,
            self.task_file(
                "T2",
                supersedes=["T1"],
                requirements=["R1"],
                owned_paths=["scripts/kb/t2-replacement.py"],
            ),
            actor="coordinator",
        )
        register_task(
            self.program,
            self.task_file(
                "T3",
                supersedes=["T2"],
                requirements=["R1"],
                owned_paths=["scripts/kb/t3-replacement.py"],
            ),
            actor="coordinator",
        )
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="superseded",
            superseded_by="T2",
            note="first replacement",
        )
        transition(
            self.program,
            actor="coordinator",
            task_id="T2",
            destination="superseded",
            superseded_by="T3",
            note="second replacement",
        )
        self.advance_task_to_accepted("T3")
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        self.assertTrue(final_gate(self.program)["ready"])

    def test_transferred_finding_creates_a_verified_target_obligation(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        register_task(
            self.program,
            self.task_file("T2", requirements=[]),
            actor="coordinator",
        )
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F-transfer",
            symptom="integration ownership gap",
            evidence="synthetic verified finding",
            evidence_status="verified",
        )
        resolve_finding(
            self.program,
            actor="coordinator",
            finding_id="F-transfer",
            disposition="transferred",
            root_cause="the fix belongs to the integration task",
            resolution="bind the finding to T2 evidence",
            linked_task="T2",
        )
        transition(
            self.program,
            actor="worker",
            task_id="T2",
            destination="ready",
            note="target task accepted the obligation",
        )
        transition(
            self.program,
            actor="worker",
            task_id="T2",
            destination="running",
            note="target task started",
        )
        self.evidence("task_report", task_id="T2")
        self.evidence("changed_files", task_id="T2")
        transition(
            self.program,
            actor="worker",
            task_id="T2",
            destination="implemented",
            note="target implementation complete",
        )
        self.evidence("targeted_tests", task_id="T2")
        self.evidence("failure_injection", task_id="T2")
        with self.assertRaisesRegex(GuardianProgramError, "finding obligations"):
            transition(
                self.program,
                actor="coordinator",
                task_id="T2",
                destination="task_verified",
                note="finding evidence is still missing",
            )
        self.evidence(
            "finding_resolution",
            task_id="T2",
            actor="coordinator",
            findings=["F-transfer"],
        )
        transition(
            self.program,
            actor="coordinator",
            task_id="T2",
            destination="task_verified",
            note="transferred finding is independently evidenced",
        )

    def test_successor_inherits_transferred_finding_obligations(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        register_task(
            self.program,
            self.task_file("T2", requirements=[]),
            actor="coordinator",
        )
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F-inherited",
            symptom="replacement must preserve the remediation obligation",
            evidence="synthetic verified finding",
            evidence_status="verified",
        )
        resolve_finding(
            self.program,
            actor="coordinator",
            finding_id="F-inherited",
            disposition="transferred",
            root_cause="the target owns the required correction",
            resolution="bind the correction to T2 and any successor",
            linked_task="T2",
        )
        register_task(
            self.program,
            self.task_file(
                "T3",
                supersedes=["T2"],
                requirements=[],
                owned_paths=["scripts/kb/t3-successor.py"],
            ),
            actor="coordinator",
        )
        status = project(self.program)
        self.assertEqual(status["tasks"]["T3"]["finding_obligations"], ["F-inherited"])
        with self.assertRaisesRegex(GuardianProgramError, "different non-terminal"):
            record_finding(
                self.program,
                actor="worker",
                task_id="T1",
                finding_id="F-late-transfer",
                symptom="late transfer to replaced target",
                evidence="synthetic verified finding",
                evidence_status="verified",
            )
            resolve_finding(
                self.program,
                actor="coordinator",
                finding_id="F-late-transfer",
                disposition="transferred",
                root_cause="T2 already has a registered successor",
                resolution="must transfer to terminal successor instead",
                linked_task="T2",
            )

    def test_rejected_finding_requires_later_exact_finding_evidence(self) -> None:
        self.register_and_start()
        generic_path = self.evidence("task_report")
        generic_id = next(
            evidence_id
            for evidence_id, row in project(self.program)["evidence"].items()
            if row["path"] == generic_path.relative_to(self.program).as_posix()
        )
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F-reject",
            symptom="a disputed blocker",
            evidence="synthetic finding",
            evidence_status="verified",
        )
        with self.assertRaisesRegex(GuardianProgramError, "passing evidence"):
            resolve_finding(
                self.program,
                actor="coordinator",
                finding_id="F-reject",
                disposition="rejected_with_evidence",
                root_cause="the generic report does not decide this finding",
                resolution="require exact later finding evidence",
                evidence_id=generic_id,
            )

    def test_only_coordinator_can_reopen_verified_work(self) -> None:
        self.register_and_start()
        self.evidence("task_report")
        self.evidence("changed_files")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="implemented",
            note="implementation complete",
        )
        self.evidence("targeted_tests")
        self.evidence("failure_injection")
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="task_verified",
            note="verification complete",
        )
        with self.assertRaisesRegex(GuardianProgramError, "reopen verified work"):
            transition(
                self.program,
                actor="worker",
                task_id="T1",
                destination="running",
                note="worker cannot invalidate coordinator verification",
            )

    def test_drifted_evidence_blocks_implemented_transition(self) -> None:
        self.register_and_start()
        report = self.evidence("task_report")
        self.evidence("changed_files")
        report.write_text("drifted before implemented", encoding="utf-8")
        with self.assertRaisesRegex(GuardianProgramError, "has drifted"):
            transition(
                self.program,
                actor="worker",
                task_id="T1",
                destination="implemented",
                note="drifted worker evidence cannot advance",
            )

    def test_initialize_is_idempotent_after_committed_event_fsync_error(self) -> None:
        retry_root = self.base / "post-commit-retry-program"
        real_write_initial_event = guardian_program_module._write_initial_event

        def write_then_report_failure(path: Path, row: dict) -> None:
            real_write_initial_event(path, row)
            raise OSError("synthetic post-replace directory fsync report")

        with mock.patch.object(
            guardian_program_module,
            "_write_initial_event",
            side_effect=write_then_report_failure,
        ):
            with self.assertRaisesRegex(OSError, "post-replace"):
                initialize(retry_root, self.manifest_path, actor="coordinator")
        committed = initialize(retry_root, self.manifest_path, actor="coordinator")
        self.assertEqual(committed["type"], "program_initialized")
        self.assertEqual(project(retry_root)["event_count"], 1)

    def test_completion_snapshot_tampering_fails_closed(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        complete(self.program, actor="coordinator")
        completion = project(self.program)["completion"]
        snapshot = self.program / completion["evidence_snapshot_path"]
        snapshot.chmod(0o600)
        snapshot.write_text("tampered", encoding="utf-8")
        status = project(self.program)
        self.assertTrue(status["completion_event_seen"])
        self.assertFalse(status["program_completed"])
        self.assertEqual(status["completion"]["integrity"], "failed")
        self.assertEqual(
            status["evidence_errors"],
            [
                {
                    "evidence_id": "completion-snapshot",
                    "reason": "completion_integrity_failed",
                }
            ],
        )
        self.assertFalse(final_gate(self.program)["ready"])

    def test_completion_retry_returns_the_committed_event(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        real_write_event_row = guardian_program_module._write_event_row

        def write_then_report_failure(root: Path, row: dict) -> None:
            real_write_event_row(root, row)
            raise OSError("synthetic completion post-replace report")

        with mock.patch.object(
            guardian_program_module,
            "_write_event_row",
            side_effect=write_then_report_failure,
        ):
            with self.assertRaisesRegex(OSError, "completion post-replace"):
                complete(self.program, actor="coordinator")
        committed = complete(self.program, actor="coordinator")
        self.assertEqual(committed["type"], "program_completed")
        self.assertEqual(project(self.program)["event_count"], committed["sequence"])

    def test_prepared_completion_recovers_after_sources_disappear(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        source_paths: set[Path] = set()
        for evidence in project(self.program)["evidence"].values():
            document_path = self.program / evidence["path"]
            document = json.loads(document_path.read_text(encoding="utf-8"))
            source_paths.add(document_path)
            source_paths.update(
                self.program / artifact["path"]
                for artifact in document["artifacts"]
            )
        with mock.patch.object(
            guardian_program_module,
            "_write_event_row",
            side_effect=OSError("synthetic crash after prepare"),
        ):
            with self.assertRaisesRegex(OSError, "after prepare"):
                complete(self.program, actor="coordinator")
        self.assertTrue(any((self.program / "completion-evidence/prepared").iterdir()))
        for source in source_paths:
            source.unlink()
        committed = complete(self.program, actor="coordinator")
        self.assertEqual(committed["type"], "program_completed")
        self.assertEqual(project(self.program)["completion"]["integrity"], "verified")

    def test_completed_final_gate_reproduces_attested_digest(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        complete(self.program, actor="coordinator")
        status = project(self.program)
        gate = final_gate(self.program)
        self.assertEqual(
            guardian_program_module._digest(gate),
            status["completion"]["final_gate_sha256"],
        )

    def test_hardlinked_evidence_source_is_rejected_from_completion(self) -> None:
        self.make_task_accepted()
        program_path = self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        document = json.loads(program_path.read_text(encoding="utf-8"))
        artifact = self.program / document["artifacts"][0]["path"]
        outside = self.base / "outside-hardlink-source.txt"
        outside.write_bytes(artifact.read_bytes())
        artifact.unlink()
        os.link(outside, artifact)
        gate = final_gate(self.program)
        self.assertFalse(gate["ready"])
        self.assertTrue(
            any(blocker.get("reason") == "artifact_invalid" for blocker in gate["blockers"])
        )
        with self.assertRaisesRegex(GuardianProgramError, "final gate is not ready"):
            complete(self.program, actor="coordinator")

    def test_snapshot_publish_failure_before_replace_is_retriable(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        real_fchmod = guardian_program_module.os.fchmod
        failed = False

        def fail_first_readonly_publish(descriptor: int, mode: int) -> None:
            nonlocal failed
            if mode == 0o400 and not failed:
                failed = True
                raise OSError("synthetic pre-publish metadata failure")
            real_fchmod(descriptor, mode)

        with mock.patch.object(
            guardian_program_module.os,
            "fchmod",
            side_effect=fail_first_readonly_publish,
        ):
            with self.assertRaisesRegex(OSError, "metadata failure"):
                complete(self.program, actor="coordinator")
        committed = complete(self.program, actor="coordinator")
        self.assertEqual(committed["type"], "program_completed")

    @unittest.skipIf(os.name == "nt", "POSIX permission materialization")
    def test_fresh_checkout_completion_permissions_are_verified_then_hardened(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        complete(self.program, actor="coordinator")
        completion = self.program / "completion-evidence"
        directories = [completion, *(path for path in completion.iterdir() if path.is_dir())]
        files = sorted(path for path in completion.rglob("*") if path.is_file())
        self.assertTrue(files)
        for path in files:
            path.chmod(0o644)
        for path in directories:
            path.chmod(0o755)

        result = materialize_completion_permissions(self.program)

        self.assertEqual(result["files_verified"], len(files))
        self.assertEqual(result["files_hardened"], len(files))
        self.assertEqual(result["directories_hardened"], len(directories))
        self.assertTrue(all((path.stat().st_mode & 0o777) == 0o400 for path in files))
        self.assertTrue(
            all((path.stat().st_mode & 0o777) == 0o700 for path in directories)
        )
        self.assertTrue(project(self.program)["program_completed"])

    @unittest.skipIf(os.name == "nt", "POSIX permission materialization")
    def test_completion_materializer_is_two_phase_and_rejects_digest_drift(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        complete(self.program, actor="coordinator")
        completion = self.program / "completion-evidence"
        directories = [completion, *(path for path in completion.iterdir() if path.is_dir())]
        files = sorted(path for path in completion.rglob("*") if path.is_file())
        for path in files:
            path.chmod(0o644)
        for path in directories:
            path.chmod(0o755)
        drifted = next(path for path in files if path.parent.name == "blobs")
        drifted.write_bytes(drifted.read_bytes() + b"drift")

        with self.assertRaisesRegex(GuardianProgramError, "content digest mismatch"):
            materialize_completion_permissions(self.program)

        self.assertTrue(all((path.stat().st_mode & 0o777) == 0o644 for path in files))
        self.assertTrue(
            all((path.stat().st_mode & 0o777) == 0o755 for path in directories)
        )

    def test_snapshot_race_becomes_a_diagnostic_integrity_blocker(self) -> None:
        self.make_task_accepted()
        self.evidence(
            "full_isolated_suite",
            task_id="",
            actor="coordinator",
            scope="program",
        )
        real_write_event_row = guardian_program_module._write_event_row

        def corrupt_then_commit(root: Path, row: dict) -> None:
            snapshot = root / row["payload"]["evidence_snapshot_path"]
            snapshot.chmod(0o600)
            snapshot.write_text("synthetic concurrent corruption", encoding="utf-8")
            real_write_event_row(root, row)

        with mock.patch.object(
            guardian_program_module,
            "_write_event_row",
            side_effect=corrupt_then_commit,
        ):
            with self.assertRaisesRegex(GuardianProgramError, "committed with failed"):
                complete(self.program, actor="coordinator")
        status = project(self.program)
        self.assertTrue(status["completion_event_seen"])
        self.assertFalse(status["program_completed"])
        self.assertEqual(status["completion"]["integrity"], "failed")

    def test_owned_paths_reject_noncanonical_aliases(self) -> None:
        task_path = self.task_file("T-alias")
        value = json.loads(task_path.read_text(encoding="utf-8"))
        value["owned_paths"] = ["scripts/kb/../kb/shared.py"]
        task_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(GuardianProgramError, "canonical relative"):
            register_task(self.program, task_path, actor="coordinator")

    def test_superseded_dependency_follows_its_unique_terminal_successor(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        register_task(
            self.program,
            self.task_file("TD", depends_on=["T1"], requirements=[]),
            actor="coordinator",
        )
        register_task(
            self.program,
            self.task_file(
                "T2",
                supersedes=["T1"],
                requirements=["R1"],
                owned_paths=["scripts/kb/t2-successor.py"],
            ),
            actor="coordinator",
        )
        with self.assertRaisesRegex(GuardianProgramError, "supersession target"):
            register_task(
                self.program,
                self.task_file(
                    "T3",
                    supersedes=["T1"],
                    requirements=["R1"],
                    owned_paths=["scripts/kb/t3-competing.py"],
                ),
                actor="coordinator",
            )
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="superseded",
            superseded_by="T2",
            note="unique successor takes authority",
        )
        with self.assertRaisesRegex(GuardianProgramError, "dependencies"):
            transition(
                self.program,
                actor="worker",
                task_id="TD",
                destination="ready",
                note="successor is not accepted yet",
            )
        self.advance_task_to_accepted("T2")
        transition(
            self.program,
            actor="worker",
            task_id="TD",
            destination="ready",
            note="terminal successor now satisfies dependency",
        )

    def test_task_cannot_depend_on_the_predecessor_it_supersedes(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        with self.assertRaisesRegex(GuardianProgramError, "cannot depend"):
            register_task(
                self.program,
                self.task_file(
                    "T2",
                    depends_on=["T1"],
                    supersedes=["T1"],
                    requirements=["R1"],
                ),
                actor="coordinator",
            )

    def test_finding_resolution_channels_are_mutually_exclusive(self) -> None:
        register_task(self.program, self.task_file("T1"), actor="coordinator")
        register_task(
            self.program,
            self.task_file("T2", requirements=[]),
            actor="coordinator",
        )
        record_finding(
            self.program,
            actor="worker",
            task_id="T1",
            finding_id="F-channel",
            symptom="ambiguous disposition payload",
            evidence="synthetic evidence",
            evidence_status="verified",
        )
        before = project(self.program)["event_count"]
        with self.assertRaisesRegex(GuardianProgramError, "channels"):
            resolve_finding(
                self.program,
                actor="coordinator",
                finding_id="F-channel",
                disposition="fixed_current",
                root_cause="fixed_current must not point elsewhere",
                resolution="reject ambiguous channel union",
                linked_task="T2",
            )
        self.assertEqual(project(self.program)["event_count"], before)

    def test_requirement_acceptance_mapping_rejects_duplicate_keys(self) -> None:
        self.register_and_start()
        clause = project(self.program)["requirements"]["R1"]["acceptance"][0]
        with self.assertRaisesRegex(GuardianProgramError, "exactly once"):
            self.evidence(
                "requirement_traceability",
                acceptance_rows=[
                    {
                        "requirement_id": "R1",
                        "clause": clause,
                        "fact": "first claim",
                    },
                    {
                        "requirement_id": "R1",
                        "clause": clause,
                        "fact": "contradictory duplicate claim",
                    },
                ],
            )

    def test_reopen_requires_a_new_coordinator_issued_evidence_run(self) -> None:
        self.register_and_start()
        old_run = project(self.program)["tasks"]["T1"]["verification_run_id"]
        self.evidence("task_report")
        self.evidence("changed_files")
        transition(
            self.program,
            actor="worker",
            task_id="T1",
            destination="implemented",
            note="first implementation",
        )
        self.evidence("targeted_tests")
        self.evidence("failure_injection")
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="task_verified",
            note="first verification",
        )
        transition(
            self.program,
            actor="coordinator",
            task_id="T1",
            destination="running",
            note="new defect requires a fresh verification campaign",
        )
        task = project(self.program)["tasks"]["T1"]
        self.assertNotEqual(task["verification_run_id"], old_run)
        self.assertEqual(task["verification_epoch"], 2)
        with self.assertRaisesRegex(GuardianProgramError, "current coordinator-issued"):
            self.evidence("task_report", run_id=old_run)
        with self.assertRaisesRegex(GuardianProgramError, "lacks evidence"):
            transition(
                self.program,
                actor="worker",
                task_id="T1",
                destination="implemented",
                note="old evidence must not be reused",
            )


if __name__ == "__main__":
    unittest.main()

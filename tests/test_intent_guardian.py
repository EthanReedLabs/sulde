from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock
from concurrent.futures import ThreadPoolExecutor
from tests.synthetic_sedimentation import write_examples


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts" / "kb"
RELEASE_DIR = ROOT / "scripts" / "release"
import sys

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(RELEASE_DIR))

from intent_guardian import (  # noqa: E402
    DecisionV2,
    GuardianSession,
    IntentGuardianError,
    active_contract_path,
    activate_contract,
    audit_path,
    apply_revision_proposal,
    approve_event,
    approve_proposal,
    create_revision_proposal,
    continuation_context,
    decide_proposal_as_agent,
    default_contract,
    evaluate_event,
    execute_native_decision,
    finalize_workspace_cleanup,
    finalize_host_turn,
    guardian_doctor,
    guardian_inventory,
    guardian_report,
    load_contract,
    normalize_hook_event,
    normalize_provider_events,
    native_decision_preview,
    observe_native_permission_request,
    observe_user_prompt,
    prepare_continuation,
    prepare_pre_execution_probe,
    prepare_workspace_handoff,
    prepare_workspace_proposal,
    proposal_digest,
    proposal_review_for_digest,
    finalize_pre_execution_probe,
    reassess_unattended_proposal,
    record_skill_event,
    reconcile_stale_local_write_events,
    release_completed_workspace,
    resolve_contract_path,
    resolve_session_contract,
    seed_session_workspace_hint,
    apply_workspace_handoff,
    rebind_workspace_contract,
    resolve_effect_intervention,
    retire_orphan_contract,
    resume_contract,
    write_contract,
    workspace_cleanup_status,
)
from intent_critic import run_critic, validate_result  # noqa: E402
import intent_critic  # noqa: E402
import intent_guardian as guardian_module  # noqa: E402
import resource_adapters  # noqa: E402
from intent_guardian_parts import policy as guardian_policy  # noqa: E402
from intent_guardian_parts import audit as guardian_audit  # noqa: E402
from intent_guardian_parts import approvals as guardian_approvals  # noqa: E402
from intent_guardian_parts import readiness as guardian_readiness  # noqa: E402
from intent_guardian_parts import recovery as guardian_recovery  # noqa: E402
from intent_guardian_parts import figma_read_recovery as guardian_figma_recovery  # noqa: E402
from intent_guardian_parts import resources as guardian_resources  # noqa: E402
from intent_guardian_parts import resource_preflight as guardian_resource_preflight  # noqa: E402
from intent_guardian_parts import session_workspace as guardian_session_workspace  # noqa: E402
from intent_guardian_parts import events as guardian_events  # noqa: E402
from intent_guardian_parts import stale_events as guardian_stale_events  # noqa: E402
import launcher_contract  # noqa: E402
import stage_plugin  # noqa: E402
from human_control import parse_human_control  # noqa: E402
from intervention import (  # noqa: E402
    InterventionError,
    begin_attempt as begin_effect_attempt,
    load_projection as load_intervention_projection,
)
from native_decision_journal import (  # noqa: E402
    NativeAuthorityReaders,
    advance_with_authority as advance_native_with_authority,
    load_projection as load_native_decision_projection,
)
from approval_invariant import (  # noqa: E402
    event_store_path as approval_event_store_path,
    load_projection as load_approval_projection,
)


class IntentGuardianTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.contract_path = Path(self.temp.name) / "intent.json"
        self.skill_path = ROOT / "skills" / "intent-guardian" / "SKILL.md"
        self.codex_home = Path(self.temp.name) / "codex-home"
        official_helper = (
            self.codex_home
            / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        )

        official_helper.parent.mkdir(parents=True)
        official_helper.write_text(
            "# isolated official cachebuster helper fixture\n",
            encoding="utf-8",
        )
        fake_bin = Path(self.temp.name) / "bin"
        fake_bin.mkdir()
        fake_codex = fake_bin / "codex"
        fake_codex.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_codex.chmod(0o755)
        isolated_environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("SULDE_")
        }
        isolated_environment.update(
            {
                "CODEX_HOME": str(self.codex_home),
                # Session routing is durable by design.  Keep every test's
                # provider/session mapping inside the disposable fixture so a
                # prior test cannot leave a validly sealed mapping to a
                # contract that its TemporaryDirectory has already removed.
                "SULDE_KB_HOME": str(Path(self.temp.name) / "kb-home"),
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "XDG_CONFIG_HOME": str(Path(self.temp.name) / "xdg"),
            }
        )
        self.environment = mock.patch.dict(
            os.environ,
            isolated_environment,
            clear=True,
        )
        self.environment.start()

    def real_worktree_fixture(self) -> tuple[Path, Path, Path, Path]:
        repo = Path(self.temp.name) / "handoff-repo"
        target = Path(self.temp.name) / "handoff-task"
        home = Path(self.temp.name) / "handoff-kb"
        subprocess.run(
            ["git", "init", "-b", "dev", str(repo)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Sulde Test"],
            check=True,
        )
        (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "base"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-b", "task/handoff", str(target)],
            check=True,
            capture_output=True,
        )
        source_path = active_contract_path(home, repo)
        source = default_contract(
            intent_id="workspace-handoff",
            objective="continue the same task in its worktree",
            acceptance_criteria=["session resolves to the task worktree"],
            workspace=repo,
            mode="enforce",
            allowed_paths=[str(repo)],
            confirmed_by="test",
        )
        source["runtime"]["pre_execution_gaps"] = [
            {
                "at": "2026-09-02T00:00:00+00:00",
                "provider": "codex",
                "session_id": "handoff-session",
                "runtime_generation": "legacy",
                "event_id": "old-gap",
                "capability": "tool:Bash",
                "effect": "local_write",
                "target": "/private/tmp/old-gap",
                "reason_code": "task_scope_denied",
            }
        ]
        write_contract(source_path, source)
        seed_session_workspace_hint(
            home,
            provider="codex",
            session_id="handoff-session",
            contract_path=source_path,
        )
        return repo, target, home, source_path

    def completed_worktree_fixture(self) -> tuple[Path, Path, Path, Path]:
        repo, target, home, source_path = self.real_worktree_fixture()
        prepared = prepare_workspace_handoff(
            home,
            source_path,
            target,
            provider="codex",
            session_id="handoff-session",
        )
        apply_workspace_handoff(
            home,
            source_path,
            target,
            provider="codex",
            session_id="handoff-session",
            receipt_id="fixture-handoff",
        )
        task_path = Path(prepared["target_contract"])
        (target / "tracked.txt").write_text("completed task\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(target), "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(target), "commit", "-m", "completed task"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "merge", "--no-ff", "task/handoff", "-m", "merge task"],
            check=True,
            capture_output=True,
        )
        return repo, target, home, task_path

    def orphan_rebind_fixture(self) -> tuple[Path, Path, Path, Path, Path]:
        repo = Path(self.temp.name) / "rebind-repo"
        source = Path(self.temp.name) / "rebind-source"
        target = Path(self.temp.name) / "rebind-target"
        home = Path(self.temp.name) / "rebind-kb"
        subprocess.run(
            ["git", "init", "-b", "dev", str(repo)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Sulde Test"],
            check=True,
        )
        (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "base"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-b", "task/orphan", str(source)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "add", "-b", "task/rebound", str(target)],
            check=True,
            capture_output=True,
        )
        source_path = active_contract_path(home, source)
        write_contract(
            source_path,
            default_contract(
                intent_id="mapped-orphan-rebind",
                objective="recover one removed task worktree",
                acceptance_criteria=["mapped session follows the reviewed replacement"],
                workspace=source,
                mode="enforce",
                confirmed_by="test",
            ),
        )
        seed_session_workspace_hint(
            home,
            provider="codex",
            session_id="mapped-orphan-session",
            contract_path=source_path,
        )
        seed_session_workspace_hint(
            home,
            provider="codex",
            session_id="mapped-orphan-session-two",
            contract_path=source_path,
        )
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", str(source)],
            check=True,
            capture_output=True,
        )
        return repo, source, target, home, source_path

    def tearDown(self) -> None:
        self.environment.stop()
        self.temp.cleanup()

    def install_maintenance_runtime_fixture(self) -> Path:
        """Materialize the same portable script bytes as the official stager."""
        descriptor = json.loads(
            (
                ROOT
                / "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
            ).read_text(encoding="utf-8")
        )
        runtime = (
            self.codex_home
            / "plugins/cache/sulde-local/sulde"
            / descriptor["version"]
            / "runtime"
        )
        for relative in (
            Path("scripts/kb/install-agents.sh"),
            Path("scripts/kb/bootstrap.sh"),
        ):
            destination = runtime / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        stage_plugin.neutralize_launchagent_paths(runtime)
        return runtime

    def contract(self, *, mode: str = "enforce") -> dict:
        contract = default_contract(
            intent_id="resume-edit",
            objective="改进简历表达，但不得改变事实",
            rationale="保持本人表达",
            acceptance_criteria=["事实与数字不变", "没有营销式措辞"],
            workspace=self.root,
            mode=mode,
            preserve=["事实", "已经认可的段落"],
            reject=["夸大", "营销式措辞"],
            allowed_paths=["resume.md"],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        return load_contract(self.contract_path)

    def stale_local_write_fixture(
        self,
        name: str,
        *,
        source_session: str = "source-session",
    ) -> tuple[Path, Path, dict]:
        root = Path(self.temp.name) / name / "project"
        root.mkdir(parents=True)
        (root / ".git").mkdir()
        contract_path = Path(self.temp.name) / name / "intent.json"
        contract = default_contract(
            intent_id=f"stale-{name}",
            objective="edit one local file",
            acceptance_criteria=["local file remains auditable"],
            workspace=root,
            mode="enforce",
            allowed_paths=["notes.md"],
            confirmed_by="human",
        )
        write_contract(contract_path, contract)
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": source_session,
                "cwd": str(root),
                "tool_name": "Write",
                "tool_input": {"file_path": "notes.md"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(GuardianSession(contract_path).observe(event).action, "allow")
        return root, contract_path, event

    def age_open_event(self, contract_path: Path) -> None:
        contract = load_contract(contract_path)
        opened = contract["runtime"]["open_events"][0]
        opened["started_at"] = "2000-01-01T00:00:00+00:00"
        write_contract(contract_path, contract)
        rows = [
            json.loads(line)
            for line in audit_path(contract_path).read_text(encoding="utf-8").splitlines()
        ]
        source = next(
            row["event"]
            for row in rows
            if isinstance(row.get("event"), dict)
            and row["event"].get("event_id") == opened["event_id"]
        )
        source["at"] = opened["started_at"]
        audit_path(contract_path).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def add_formal_continuation(
        self,
        contract_path: Path,
        *,
        source_session: str = "source-session",
        target_session: str = "new-session",
    ) -> None:
        contract = load_contract(contract_path)
        request_id = "apr-" + "1" * 24
        receipt_id = "2" * 64
        target = "3" * 64
        continuation_id = hashlib.sha256(
            json.dumps(
                {
                    "request_id": request_id,
                    "receipt_id": receipt_id,
                    "target": target,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        contract["runtime"]["task_continuations"].append(
            {
                "schema": "sulde-task-continuation-v1",
                "continuation_id": continuation_id,
                "target": target,
                "receipt_id": receipt_id,
                "policy_sha256": "4" * 64,
                "source_lane_sha256": hashlib.sha256(
                    f"codex\0{source_session}".encode()
                ).hexdigest(),
                "target_lane_sha256": hashlib.sha256(
                    f"codex\0{target_session}".encode()
                ).hexdigest(),
                "provider": "codex",
                "session_id": target_session,
                "task_epoch": contract["task_epoch"],
                "intent_revision": contract["revision"],
                "proposal_digest": "",
                "task_instance_id": "continued-task",
                "approval_request_id": request_id,
                "authority_transferred": False,
                "recorded_at": "2026-09-03T00:00:00+00:00",
            }
        )
        write_contract(contract_path, contract)

    def test_workspace_handoff_atomically_rebinds_without_runtime_authority(self) -> None:
        repo, target, home, source_path = self.real_worktree_fixture()
        prepared = prepare_workspace_handoff(
            home,
            source_path,
            target,
            provider="codex",
            session_id="handoff-session",
        )
        # Preparing is idempotent and does not move the current session lane.
        repeated = prepare_workspace_handoff(
            home,
            source_path,
            target,
            provider="codex",
            session_id="handoff-session",
        )
        self.assertEqual(prepared["target_contract"], repeated["target_contract"])
        self.assertEqual(
            resolve_session_contract(home, "codex", "handoff-session"),
            source_path.resolve(),
        )
        target_path = Path(prepared["target_contract"])
        pending = load_contract(target_path)
        self.assertTrue(pending["confirmation"]["required"])
        self.assertEqual(pending["continuation"]["grants"], [])
        for field in (
            "open_events", "pending_verifications", "verified_effects",
            "authorized_events", "approval_receipts", "continuation_uses",
            "pre_execution_gaps", "active_skills", "active_skill_frames",
        ):
            self.assertEqual(pending["runtime"][field], [], field)
        self.assertEqual(
            pending["constraints"]["allowed_paths"], [str(target.resolve())]
        )

        result = apply_workspace_handoff(
            home,
            source_path,
            target,
            provider="codex",
            session_id="handoff-session",
            receipt_id="receipt-handoff",
        )
        self.assertEqual(result["status"], "bound")
        self.assertFalse(result["authority_transferred"])
        self.assertEqual(
            resolve_session_contract(home, "codex", "handoff-session"),
            target_path.resolve(),
        )
        with mock.patch.dict(
            os.environ,
            {
                "SULDE_KB_HOME": str(home),
                "SULDE_INTENT_CONTRACT": str(source_path),
            },
        ):
            self.assertEqual(
                resolve_contract_path(
                    {
                        "client": "codex",
                        "session_id": "handoff-session",
                        "cwd": str(repo),
                        "intent_contract": str(source_path),
                    }
                ),
                target_path.resolve(),
            )

    def test_missing_launch_contract_hint_falls_back_to_live_workspace(self) -> None:
        repo, _target, home, source_path = self.real_worktree_fixture()
        missing = home / "intent" / "workspaces" / "removed.active.json"
        with mock.patch.dict(
            os.environ,
            {
                "SULDE_KB_HOME": str(home),
                "SULDE_INTENT_CONTRACT": str(missing),
            },
        ):
            resolved = resolve_contract_path(
                {
                    "client": "codex",
                    "session_id": "unmapped-current-session",
                    "cwd": str(repo),
                }
            )
        self.assertEqual(resolved.resolve(), source_path.resolve())

    def test_native_workspace_handoff_consumes_exact_permission_receipt(self) -> None:
        _, target, home, source_path = self.real_worktree_fixture()
        import host_capabilities
        import session_lifecycle_lineage
        host_capabilities.provision_provenance_key(home)
        prepare_workspace_handoff(
            home,
            source_path,
            target,
            provider="codex",
            session_id="handoff-session",
        )
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            preview = native_decision_preview(
                source_path,
                kind="workspace-handoff",
                decision="approve",
                target=str(target),
                provider="codex",
                session_id="handoff-session",
            )
            observed = observe_native_permission_request(
                self.native_permission_payload(
                    preview,
                    session_id="handoff-session",
                    contract_path=source_path,
                ),
                provider="codex",
            )
            result = execute_native_decision(
                source_path,
                kind="workspace-handoff",
                decision="approve",
                target=str(target),
                provider="codex",
                session_id="handoff-session",
            )

        self.assertEqual(observed["action"], "defer")
        self.assertEqual(result["status"], "applied")
        self.assertFalse(result["authority_transferred"])
        self.assertEqual(
            resolve_session_contract(home, "codex", "handoff-session"),
            active_contract_path(home, target).resolve(),
        )
        receipt = load_contract(source_path)["runtime"]["approval_receipts"][-1]
        self.assertEqual(receipt["action"], "handoff-workspace")
        self.assertEqual(
            receipt["consumed_by"], "native-permission-control-executor"
        )
        self.assertTrue(result["handoff"]["lifecycle_lineage_recorded"])
        lineage_path = session_lifecycle_lineage.lineage_path(home, "codex", "handoff-session")
        original_source = source_path.read_bytes()
        # Simulate an old installation / failed derived publication. Independent
        # asked/decided receipts, not a supplied receipt string, repair this edge.
        lineage_path.unlink()
        recovered = session_lifecycle_lineage.recover_current_transition(
            home, provider="codex", session_id="handoff-session",
        )
        self.assertEqual(recovered["status"], "recovered", recovered)
        self.assertEqual(source_path.read_bytes(), original_source)
        self.assertTrue(lineage_path.is_file())

    def test_workspace_handoff_identity_drift_keeps_old_mapping(self) -> None:
        _, target, home, source_path = self.real_worktree_fixture()
        prepare_workspace_handoff(
            home,
            source_path,
            target,
            provider="codex",
            session_id="handoff-session",
        )
        (target / "tracked.txt").write_text("changed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(target), "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(target), "commit", "-m", "drift"],
            check=True,
            capture_output=True,
        )

        with self.assertRaisesRegex(IntentGuardianError, "lineage differs"):
            apply_workspace_handoff(
                home,
                source_path,
                target,
                provider="codex",
                session_id="handoff-session",
                receipt_id="receipt-must-not-apply",
            )
        self.assertEqual(
            resolve_session_contract(home, "codex", "handoff-session"),
            source_path.resolve(),
        )

    def test_completed_workspace_release_deauthorizes_then_finalizes_cleanup(self) -> None:
        repo, target, home, task_path = self.completed_worktree_fixture()
        result = release_completed_workspace(
            home,
            task_path,
            repo,
            provider="codex",
            session_id="handoff-session",
        )

        self.assertEqual(result["status"], "pending")
        self.assertFalse(result["authority_transferred"])
        self.assertFalse(result["git_mutation_performed"])
        anchor_path = Path(result["completion_contract"])
        self.assertNotEqual(anchor_path, active_contract_path(home, repo))
        self.assertEqual(
            anchor_path.parent,
            (home / "intent" / "sessions").resolve(),
        )
        self.assertEqual(
            resolve_session_contract(home, "codex", "handoff-session"),
            anchor_path.resolve(),
        )
        self.assertEqual(load_contract(task_path)["status"], "closed")
        anchor = load_contract(anchor_path)
        self.assertFalse(anchor["permissions"]["local_write"])
        self.assertEqual(anchor["permissions"]["external_write"], "deny")
        self.assertEqual(anchor["permissions"]["destructive"], "deny")
        self.assertEqual(anchor["continuation"]["grants"], [])
        for field in (
            "open_events",
            "pending_verifications",
            "verified_effects",
            "authorized_events",
            "approval_receipts",
            "continuation_uses",
            "pre_execution_gaps",
            "active_skills",
            "active_skill_frames",
        ):
            self.assertEqual(anchor["runtime"][field], [], field)
        self.assertEqual(workspace_cleanup_status(anchor)["status"], "pending")
        with (
            mock.patch.object(
                guardian_readiness,
                "host_readiness_projection",
                return_value={"status": "ready"},
            ),
            mock.patch.object(
                guardian_readiness,
                "operational_readiness_projection",
                return_value={"status": "ready"},
            ),
            mock.patch.object(
                guardian_readiness,
                "observe_recovery_truth",
                return_value={"status": "ready"},
            ),
        ):
            doctor = guardian_doctor(
                home,
                repo,
                provider="codex",
                session_id="handoff-session",
            )
        self.assertEqual(doctor["status"], "cleanup_pending")
        self.assertEqual(doctor["workspace_cleanup"]["status"], "pending")
        self.assertIn(
            "WORKTREE_CLEANUP_PENDING",
            guardian_recovery.decision_request_context(
                home,
                repo,
                provider="codex",
                session_id="handoff-session",
            ),
        )
        with self.assertRaisesRegex(IntentGuardianError, "still registered"):
            finalize_workspace_cleanup(
                home,
                anchor_path,
                provider="codex",
                session_id="handoff-session",
            )

        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", str(target)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "branch", "-d", "task/handoff"],
            check=True,
            capture_output=True,
        )
        finalized = finalize_workspace_cleanup(
            home,
            anchor_path,
            provider="codex",
            session_id="handoff-session",
        )
        self.assertEqual(finalized["status"], "complete")
        self.assertFalse(finalized["idempotent"])
        repeated = finalize_workspace_cleanup(
            home,
            anchor_path,
            provider="codex",
            session_id="handoff-session",
        )
        self.assertTrue(repeated["idempotent"])

    def test_completed_workspace_release_is_idempotent_before_git_cleanup(self) -> None:
        repo, _target, home, task_path = self.completed_worktree_fixture()
        first = release_completed_workspace(
            home,
            task_path,
            repo,
            provider="codex",
            session_id="handoff-session",
        )
        repeated = release_completed_workspace(
            home,
            task_path,
            repo,
            provider="codex",
            session_id="handoff-session",
        )
        self.assertEqual(first["completion_contract"], repeated["completion_contract"])
        self.assertEqual(first["cleanup"]["release_id"], repeated["cleanup"]["release_id"])

    def test_completed_workspace_release_rejects_dirty_or_unmerged_task(self) -> None:
        repo, target, home, task_path = self.completed_worktree_fixture()
        (target / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(IntentGuardianError, "not clean"):
            release_completed_workspace(
                home,
                task_path,
                repo,
                provider="codex",
                session_id="handoff-session",
            )

        (target / "dirty.txt").unlink()
        (target / "tracked.txt").write_text("not merged\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(target), "add", "tracked.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(target), "commit", "-m", "not merged"],
            check=True,
            capture_output=True,
        )
        with self.assertRaisesRegex(IntentGuardianError, "not merged into dev"):
            release_completed_workspace(
                home,
                task_path,
                repo,
                provider="codex",
                session_id="handoff-session",
            )

    def test_completed_workspace_release_rejects_unsettled_or_active_state(self) -> None:
        repo, _target, home, task_path = self.completed_worktree_fixture()
        contract = load_contract(task_path)
        contract["runtime"]["active_skills"] = ["sulde:intent-guardian"]
        contract["runtime"]["active_skill_frames"] = [
            {
                "name": "sulde:intent-guardian",
                "provider": "codex",
                "session_id": "handoff-session",
                "started_sequence": 1,
                "skill_digest": "a" * 64,
                "runtime_generation": "test",
                "task_epoch": contract["task_epoch"],
            }
        ]
        write_contract(task_path, contract)
        with self.assertRaisesRegex(IntentGuardianError, "active_skills"):
            release_completed_workspace(
                home,
                task_path,
                repo,
                provider="codex",
                session_id="handoff-session",
            )

    def test_completed_workspace_release_ignores_prior_epoch_local_state(self) -> None:
        repo, _target, home, task_path = self.completed_worktree_fixture()
        contract = load_contract(task_path)
        prior = {"task_epoch": "prior-task-epoch", "effect": "local_write"}
        contract["runtime"]["open_events"] = [prior]
        contract["runtime"]["pending_verifications"] = [prior]
        contract["runtime"]["pre_execution_gaps"] = [prior]
        write_contract(task_path, contract)

        result = release_completed_workspace(
            home,
            task_path,
            repo,
            provider="codex",
            session_id="handoff-session",
        )
        self.assertEqual(result["status"], "pending")

    def test_completed_workspace_release_rejects_current_epoch_local_state(self) -> None:
        repo, _target, home, task_path = self.completed_worktree_fixture()
        contract = load_contract(task_path)
        contract["runtime"]["open_events"] = [
            {"task_epoch": contract["task_epoch"], "effect": "local_write"}
        ]
        write_contract(task_path, contract)

        with self.assertRaisesRegex(IntentGuardianError, "open_events"):
            release_completed_workspace(
                home,
                task_path,
                repo,
                provider="codex",
                session_id="handoff-session",
            )

    def test_completed_workspace_release_keeps_prior_epoch_material_debt(self) -> None:
        repo, _target, home, task_path = self.completed_worktree_fixture()
        contract = load_contract(task_path)
        contract["runtime"]["pending_verifications"] = [
            {"task_epoch": "prior-task-epoch", "effect": "external_write"}
        ]
        write_contract(task_path, contract)

        with self.assertRaisesRegex(IntentGuardianError, "pending_verifications"):
            release_completed_workspace(
                home,
                task_path,
                repo,
                provider="codex",
                session_id="handoff-session",
            )

    def test_completed_workspace_release_rejects_pending_proposal_and_effect_debt(self) -> None:
        repo, _target, home, task_path = self.completed_worktree_fixture()
        contract = load_contract(task_path)
        contract["runtime"]["pending_proposal_digest"] = "b" * 64
        write_contract(task_path, contract)
        with self.assertRaisesRegex(IntentGuardianError, "pending_proposal"):
            release_completed_workspace(
                home,
                task_path,
                repo,
                provider="codex",
                session_id="handoff-session",
            )

        contract = load_contract(task_path)
        contract["runtime"]["pending_proposal_digest"] = ""
        write_contract(task_path, contract)
        begin_effect_attempt(
            task_path,
            intent_id=contract["intent_id"],
            intent_revision=contract["revision"],
            fingerprint="c" * 64,
            source_event_id="unfinished-effect",
            capability="mcp:example:write",
            target="example:item:1",
            effect="external_write",
            provider="codex",
            session_id="handoff-session",
            idempotency_key="unfinished-effect",
        )
        with self.assertRaisesRegex(IntentGuardianError, "effect_debt"):
            release_completed_workspace(
                home,
                task_path,
                repo,
                provider="codex",
                session_id="handoff-session",
            )

    def test_completed_workspace_release_rejects_identity_boundary_changes(self) -> None:
        repo, target, home, task_path = self.completed_worktree_fixture()
        source_identity = guardian_session_workspace.registered_worktree_identity(target)
        target_identity = guardian_session_workspace.registered_worktree_identity(repo)
        cases = (
            (
                "protected branch",
                {**source_identity, "branch": "main"},
                target_identity,
                "not a disposable task branch",
            ),
            (
                "different repository",
                source_identity,
                {**target_identity, "git_common_dir": str(repo / "other.git")},
                "same Git common-dir",
            ),
            (
                "non-dev target",
                source_identity,
                {**target_identity, "branch": "main"},
                "target must be the dev branch",
            ),
        )
        for label, source_value, target_value, error in cases:
            with self.subTest(label=label), mock.patch.object(
                guardian_session_workspace,
                "registered_worktree_identity",
                side_effect=[source_value, target_value],
            ), self.assertRaisesRegex(IntentGuardianError, error):
                release_completed_workspace(
                    home,
                    task_path,
                    repo,
                    provider="codex",
                    session_id="handoff-session",
                )

    def test_completed_workspace_release_digest_tamper_fails_closed(self) -> None:
        repo, _target, home, task_path = self.completed_worktree_fixture()
        result = release_completed_workspace(
            home,
            task_path,
            repo,
            provider="codex",
            session_id="handoff-session",
        )
        anchor_path = Path(result["completion_contract"])
        payload = json.loads(anchor_path.read_text(encoding="utf-8"))
        payload["workspace_cleanup"]["source_branch"] = "task/tampered"
        anchor_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(IntentGuardianError, "release digest differs"):
            workspace_cleanup_status(load_contract(anchor_path))

    def test_completed_workspace_release_only_uses_read_only_git_commands(self) -> None:
        repo, _target, home, task_path = self.completed_worktree_fixture()
        original = guardian_session_workspace.subprocess.run
        observed: list[tuple[str, ...]] = []

        def record_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            command = args[0] if args else kwargs.get("args")
            if isinstance(command, list) and command and command[0] == "git":
                observed.append(tuple(str(value) for value in command[3:]))
            return original(*args, **kwargs)

        with mock.patch.object(
            guardian_session_workspace.subprocess,
            "run",
            side_effect=record_git,
        ):
            release_completed_workspace(
                home,
                task_path,
                repo,
                provider="codex",
                session_id="handoff-session",
            )
        forbidden = {"add", "branch", "checkout", "commit", "merge", "mv", "reset", "rm"}
        self.assertTrue(observed)
        self.assertFalse(
            any(command and command[0] in forbidden for command in observed),
            observed,
        )

    def declare_effects(self, path: Path, *effects: str) -> dict:
        """Seal task-level effects without creating an event-digest ticket."""
        contract = load_contract(path)
        ordered = [value for value in ("local_write", "external_write", "unknown") if value in effects]
        contract["decision"] = {
            "requested_route": "human",
            "selected_route": "human",
            "intent_kind": "deterministic",
            "risk": "medium",
            "effects": ordered,
            "reversibility": "reversible",
            "cost": "none",
            "rollback": "test fixture rollback",
            "unknowns": [],
            "agent_eligible": False,
            "agent_ineligible_reasons": [],
        }
        write_contract(path, contract)
        return load_contract(path)

    def typed_effect_identity(
        self,
        *,
        target: str,
        capability: str,
        effect: str,
        arguments_digest: str,
    ) -> dict:
        """Build the replay inputs required by current effect-ledger fixtures."""
        kind = "uri" if re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*://.+", target) else "opaque"
        context = {} if kind == "uri" else {"schema": "exact", "value": target}
        resource_key = guardian_module.canonical_resource_key(target, kind=kind)
        return {
            "resource_key": resource_key,
            "resource_context": context,
            "operation_arguments_digest": arguments_digest,
            "operation_fingerprint": guardian_module.effect_operation_fingerprint(
                provider="codex",
                capability=capability,
                target=target,
                resource_key=resource_key,
                effect=effect,
                arguments_digest=arguments_digest,
            ),
        }

    def initialize_critic_baseline(self) -> str:
        subprocess.run(
            ["git", "init", "-q"],
            cwd=self.root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-qm",
                "critic baseline",
            ],
            cwd=self.root,
            check=True,
            capture_output=True,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout.strip()

    def write_explicit_release_inputs(self, workspace: Path) -> None:
        """Materialize the same untracked runtime inputs required by a release."""
        for relative in guardian_module.EXPLICIT_RELEASE_RUNTIME_INPUTS:
            target = workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"# fixture for {relative.as_posix()}\n", encoding="utf-8")

    def clean_launcher_source(self) -> Path:
        """Copy only launcher runtime inputs so source bytecode cannot poison tests."""
        target = Path(self.temp.name) / "clean-launcher-source"
        if target.exists():
            return target
        for prefix in launcher_contract.RUNTIME_CODE_PREFIXES:
            source = ROOT / prefix
            destination = target / prefix
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        return target

    def live_approve_proposal(
        self,
        path: Path,
        digest: str,
        *,
        provider: str = "codex",
        session_id: str = "human-review-session",
    ) -> dict:
        self.assertEqual(provider, "codex")
        preview = native_decision_preview(
            path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider=provider,
            session_id=session_id,
        )
        observed = observe_native_permission_request(
            self.native_permission_payload(
                preview,
                session_id=session_id,
                contract_path=path,
            ),
            provider="codex",
        )
        self.assertEqual(observed["action"], "defer")
        result = execute_native_decision(
            path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id=session_id,
        )
        self.assertEqual(result["status"], "applied")
        return result

    def native_permission_payload(
        self,
        preview: dict,
        *,
        session_id: str = "native-review",
        permission_mode: str = "default",
        description: str | None = None,
        contract_path: Path | None = None,
    ) -> dict:
        command = shlex.join(preview["command_argv"])
        return {
            "client": "codex",
            "session_id": session_id,
            "cwd": str(self.root),
            "intent_contract": str(contract_path or self.contract_path),
            "permission_mode": permission_mode,
            "tool_name": "Bash",
            "tool_input": {
                "command": command,
                "description": (
                    preview["description"] if description is None else description
                ),
            },
        }

    def codex_agent_decide(
        self,
        path: Path,
        digest: str,
        *,
        session_id: str,
        rationale: str,
        evidence: list[str],
    ) -> dict:
        """Bind AgentPolicy fixtures to the same host-observed Codex session."""
        with mock.patch.dict(
            os.environ,
            {"CODEX_THREAD_ID": session_id},
            clear=False,
        ):
            return decide_proposal_as_agent(
                path,
                digest,
                rationale=rationale,
                evidence=evidence,
                provider="codex",
                session_id=session_id,
            )

    def force_native_request_timing(
        self,
        *,
        reassess_at: str,
        expires_at: str | None = None,
    ) -> str:
        store = approval_event_store_path(self.contract_path)
        rows = [json.loads(line) for line in store.read_text().splitlines()]
        matches = [
            row
            for row in rows
            if row.get("type") == "approval.asked"
            and row.get("source") == "codex_permission_request"
        ]
        self.assertEqual(len(matches), 1)
        matches[0]["reassess_at"] = reassess_at
        if expires_at is not None:
            matches[0]["expires_at"] = expires_at
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        return str(matches[0]["request_id"])

    def test_skill_mcp_and_tool_lineage_are_recorded(self) -> None:
        self.contract()
        session = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="l3:test",
        )
        skill = normalize_hook_event(
            {"tool_name": "Skill", "tool_input": {"skill": "resume-kit"}},
            phase="started",
            provider="codex",
        )
        self.assertEqual(session.observe(skill).action, "allow")
        read = normalize_hook_event(
            {
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc://resume"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(session.observe(read).action, "allow")
        rows = [json.loads(line) for line in self.contract_path.with_name("intent.events.jsonl").read_text().splitlines()]
        mcp = rows[-1]["event"]
        self.assertEqual(mcp["kind"], "mcp")
        self.assertEqual(mcp["parent_skills"], ["resume-kit"])

    def test_git_execution_passthrough_is_audit_only_even_when_paused(self) -> None:
        contract = self.contract()
        contract["status"] = "paused"
        contract["runtime"]["pause_scope"] = "global"
        contract["runtime"]["pause_reason"] = "synthetic semantic pause"
        contract["runtime"]["pause_class"] = "semantic"
        write_contract(self.contract_path, contract)
        session = GuardianSession(
            self.contract_path, provider="codex", session_id="git-thread"
        )
        with mock.patch.object(
            guardian_policy,
            "_continuation_authorization",
            side_effect=AssertionError("Git must not consult Guardian authority"),
        ):
            for phase in ("started", "completed"):
                event = normalize_hook_event(
                    {
                        "client": "codex",
                        "session_id": "git-thread",
                        "tool_name": "Bash",
                        "tool_input": {"command": "git push --force origin main"},
                        "success": True,
                    },
                    phase=phase,
                    provider="codex",
                )
                self.assertEqual(
                    event.get("supervision_domain"), "execution_passthrough", event
                )
                decision = session.observe(event)
                self.assertEqual(decision.action, "allow", decision.reason)
                self.assertEqual(decision.reason_code, "git_execution_passthrough")
                self.assertEqual(decision.decision_stage, "execution_domain")
                self.assertFalse(decision.verification_required)
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(projection["attempts"], {})
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(runtime["material_sequence"], 0)
        audit = json.loads(audit_path(self.contract_path).read_text().splitlines()[-1])
        self.assertEqual(audit["decision"]["reason_code"], "git_execution_passthrough")

    def test_figma_execution_passthrough_never_blocks_or_creates_effect_debt(self) -> None:
        contract = self.contract()
        contract["status"] = "paused"
        contract["runtime"]["pause_scope"] = "global"
        contract["runtime"]["pause_reason"] = "synthetic semantic pause"
        contract["runtime"]["pause_class"] = "semantic"
        write_contract(self.contract_path, contract)
        session = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="figma-thread",
        )
        payload = {
            "client": "codex",
            "session_id": "figma-thread",
            "tool_name": "mcp__figma__use_figma",
            "tool_input": {
                "fileKey": "File_123",
                "code": "const p = figma.currentPage; p.name = 'R2';",
            },
            "success": True,
        }
        for phase in ("started", "completed"):
            event = normalize_hook_event(payload, phase=phase, provider="codex")
            self.assertEqual(event["supervision_domain"], "execution_passthrough")
            self.assertEqual(event["execution_domain"], "figma")
            self.assertEqual(event["effect"], "external_write")
            decision = session.observe(event)
            self.assertEqual(decision.action, "allow", decision.reason)
            self.assertEqual(decision.reason_code, "figma_execution_passthrough")
            self.assertFalse(decision.verification_required)

        self.assertEqual(load_intervention_projection(self.contract_path)["attempts"], {})
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(runtime["material_sequence"], 0)

    def test_process_hook_skips_contract_and_ledger_for_flattened_figma_tool(self) -> None:
        payload = {
            "client": "codex",
            "session_id": "figma-flat-thread",
            "cwd": str(self.root),
            "tool_name": "mcp__codex_apps__figma_use_figma",
            "tool_input": {
                "fileKey": "File_123",
                "code": "const p=figma.currentPage; p.name='R2';",
            },
        }
        with (
            mock.patch.object(
                guardian_audit, "route_production_recovery", return_value=None
            ),
            mock.patch.object(
                guardian_audit,
                "resolve_contract_path",
                side_effect=AssertionError("Figma must not resolve a contract"),
            ),
        ):
            decision, path = guardian_audit.process_hook(
                payload, phase="started", provider="codex"
            )

        self.assertIsNone(path)
        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.reason_code, "figma_execution_passthrough")

    def test_process_hook_routes_read_only_mcp_through_lock_free_hot_path(self) -> None:
        self.contract()
        payload = {
            "client": "codex",
            "session_id": "kb-status-thread",
            "cwd": str(self.root),
            "tool_name": "mcp__sulde_kb__kb_status",
            "tool_input": {},
        }
        with (
            mock.patch.object(
                guardian_audit, "route_production_recovery", return_value=None
            ),
            mock.patch.object(
                guardian_audit, "resolve_contract_path", return_value=self.contract_path
            ),
            mock.patch.object(
                guardian_audit,
                "GuardianSession",
                side_effect=AssertionError("read-only MCP must not take the ledger lock"),
            ),
        ):
            decision, path = guardian_audit.process_hook(
                payload, phase="started", provider="codex"
            )

        self.assertEqual(path, self.contract_path)
        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.reason_code, "read_hot_path")

    def test_external_mcp_read_still_reaches_effect_verification(self) -> None:
        self.contract()
        payload = {
            "client": "codex",
            "session_id": "document-verifier-thread",
            "cwd": str(self.root),
            "tool_name": "mcp__docs__read_document",
            "tool_input": {"uri": "doc://resume"},
        }
        with (
            mock.patch.object(
                guardian_audit, "route_production_recovery", return_value=None
            ),
            mock.patch.object(
                guardian_audit, "resolve_contract_path", return_value=self.contract_path
            ),
            mock.patch.object(
                guardian_audit.GuardianSession,
                "observe",
                return_value=guardian_module.Decision(
                    dispatch="allow",
                    would_dispatch="allow",
                    lifecycle="continue",
                    authority="none",
                    verification="none",
                    evidence_state="observed",
                    severity="info",
                    reason="external read verified a pending effect",
                    fingerprint="f" * 64,
                ),
            ) as observe,
        ):
            decision, path = guardian_audit.process_hook(
                payload, phase="completed", provider="codex"
            )

        self.assertEqual(path, self.contract_path)
        self.assertEqual(decision.reason, "external read verified a pending effect")
        observe.assert_called_once()

    def test_declared_multi_project_roots_are_impact_hints_not_write_authority(self) -> None:
        frontend = self.root
        backend = Path(self.temp.name) / "backend"
        unrelated = Path(self.temp.name) / "unrelated"
        backend.mkdir()
        unrelated.mkdir()
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = [str(frontend), str(backend)]
        write_contract(self.contract_path, contract)
        current = load_contract(self.contract_path)
        cases = (
            (frontend / "src" / "screen.tsx", "allow"),
            (backend / "src" / "api.py", "allow"),
            (unrelated / "notes.txt", "allow"),
        )
        for target, expected in cases:
            with self.subTest(target=target):
                event = normalize_hook_event(
                    {"tool_name": "Write", "tool_input": {"file_path": str(target)}},
                    phase="started",
                    provider="codex",
                )
                decision = evaluate_event(current, event)
                self.assertEqual(decision.action, expected)

    def test_interrupted_codex_apps_read_creates_no_effect_debt(self) -> None:
        self.contract()
        session = GuardianSession(
            self.contract_path, provider="codex", session_id="read-thread"
        )
        for phase in ("started", "completed"):
            event = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "read-thread",
                    "tool_name": "mcp__codex_apps__figma__get_screenshot",
                    "tool_input": {"fileKey": "File", "nodeId": "1:2"},
                    "success": False,
                },
                phase=phase,
                provider="codex",
            )
            self.assertEqual(event["effect"], "read")
            self.assertEqual(session.observe(event).action, "allow")
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(projection["attempts"], {})
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["pending_verifications"],
            [],
        )

    def test_skill_start_records_instruction_file_digest(self) -> None:
        self.contract()
        skill_file = Path(self.temp.name) / "SKILL.md"
        skill_file.write_text("# Resume Kit\n", encoding="utf-8")
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "Skill",
                "tool_input": {"skill": "resume-kit", "skill_path": str(skill_file)},
            },
            phase="started",
            provider="codex",
        )
        GuardianSession(self.contract_path).observe(event)
        row = json.loads(
            self.contract_path.with_name("intent.events.jsonl").read_text().splitlines()[-1]
        )
        self.assertEqual(
            row["event"]["skill_digest"],
            hashlib.sha256(skill_file.read_bytes()).hexdigest(),
        )

    def test_external_mcp_write_uses_readable_task_scope_not_event_digest(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(denied.action, "deny")
        self.assertFalse(denied.pause)
        self.assertFalse(denied.awaiting_human)
        self.assertIn("可读意图范围", denied.reason)
        self.assertEqual(load_contract(self.contract_path)["status"], "active")
        approved_contract = self.declare_effects(
            self.contract_path, "external_write"
        )
        self.assertEqual(approved_contract["status"], "active")
        approved = evaluate_event(approved_contract, event)
        self.assertEqual(approved.action, "allow")
        self.assertTrue(approved.verification_required)

    def test_event_digest_approval_api_is_retired(self) -> None:
        self.contract()
        payload = {
            "client": "claude",
            "session_id": "thread-one",
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://resume", "content": "new"},
        }
        event = normalize_hook_event(payload, phase="started", provider="codex")
        fingerprint = evaluate_event(load_contract(self.contract_path), event).fingerprint
        with self.assertRaisesRegex(IntentGuardianError, "retired"):
            approve_event(self.contract_path, fingerprint)
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["approval_receipts"], []
        )

        changed_session = normalize_hook_event(
            {**payload, "session_id": "thread-two"},
            phase="started",
            provider="codex",
        )
        self.assertNotEqual(
            fingerprint,
            evaluate_event(load_contract(self.contract_path), changed_session).fingerprint,
        )

    def test_mutable_event_approval_without_receipt_is_not_authority(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-one",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
            },
            phase="started",
            provider="codex",
        )
        fingerprint = evaluate_event(load_contract(self.contract_path), event).fingerprint
        contract = load_contract(self.contract_path)
        contract["approved_event_fingerprints"].append(fingerprint)
        write_contract(self.contract_path, contract)

        denied = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(denied.action, "deny")
        self.assertNotIn(
            fingerprint,
            load_contract(self.contract_path)["approved_event_fingerprints"],
        )

    def test_event_approval_does_not_resume_an_unrelated_pause(self) -> None:
        self.contract()
        contract = load_contract(self.contract_path)
        contract["status"] = "paused"
        contract["runtime"]["pause_reason"] = "用户明确暂停"
        write_contract(self.contract_path, contract)
        with self.assertRaisesRegex(IntentGuardianError, "retired"):
            approve_event(self.contract_path, "a" * 64)
        self.assertEqual(load_contract(self.contract_path)["status"], "paused")

    def test_read_compositions_and_web_reads_never_require_event_approval(self) -> None:
        contract = self.contract()
        commands = (
            "git status --short --branch && rg -n intent scripts/kb/intent_guardian.py",
            "sed -n '1,10p' README.md; sed -n '1,10p' CHANGELOG.md",
            "rg -n intent scripts/kb/intent_guardian.py | head -5",
        )
        for command in commands:
            event = normalize_hook_event(
                {"tool_name": "Bash", "tool_input": {"command": command}},
                phase="started",
                provider="codex",
            )
            self.assertEqual(event["effect"], "read", command)
            decision = evaluate_event(contract, event)
            self.assertEqual(decision.action, "allow", command)
            self.assertFalse(decision.awaiting_human, command)

        web = normalize_hook_event(
            {"tool_name": "webrun", "tool_input": {"query": "official docs"}},
            phase="started",
            provider="codex",
        )
        self.assertEqual(web["effect"], "read")
        self.assertEqual(evaluate_event(contract, web).action, "allow")

    def test_sensitive_logs_are_readable_locally_but_secret_egress_is_blocked(self) -> None:
        contract = self.contract()
        local_read = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "rg 'Authorization: Bearer ghp_1234567890abcdef' app.log"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(local_read["sensitive_input"])
        self.assertEqual(local_read["effect"], "read")
        self.assertEqual(evaluate_event(contract, local_read).action, "allow")

        contract = self.declare_effects(self.contract_path, "external_write")
        egress = normalize_hook_event(
            {
                "tool_name": "mcp__github__create_comment",
                "tool_input": {
                    "body": "Authorization: Bearer ghp_1234567890abcdef"
                },
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(self.contract_path).observe(egress)
        self.assertEqual(denied.action, "deny")
        self.assertEqual(denied.pause_class, "safety")
        self.assertFalse(denied.awaiting_human)
        self.assertEqual(
            guardian_report(self.contract_path)["supervision"]["metrics"][
                "hard_safety_blocks"
            ],
            1,
        )

    def test_multiline_external_effect_evidence_remains_one_exact_control(self) -> None:
        control = parse_human_control(
            "确认外部操作成功：第一项已独立读取\n第二项摘要一致\n第三项没有额外修改"
        )
        self.assertIsNotNone(control)
        self.assertEqual(control.action, "intervention-resolve")
        self.assertEqual(control.decision, "human_attested_success")
        self.assertEqual(
            control.evidence,
            "第一项已独立读取\n第二项摘要一致\n第三项没有额外修改",
        )

    def test_unknown_mcp_effect_is_denied_before_dispatch(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "tool_name": "mcp__docs__transform",
                "tool_input": {"uri": "doc://resume", "operation": "rewrite"},
            },
            phase="started",
            provider="codex",
        )
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "deny")
        self.assertFalse(decision.observation_gap)
        self.assertFalse(decision.verification_required)
        self.assertEqual(decision.reason_code, "external_effect_not_authorized")

    def test_unmatched_unknown_mcp_completion_retains_non_git_effect_debt(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "unknown-completion",
                "call_id": "unknown-call",
                "tool_name": "mcp__docs__transform",
                "tool_input": {"uri": "doc://resume", "operation": "rewrite"},
                "success": True,
                "tool_response": {"uri": "doc://resume"},
            },
            phase="completed",
            provider="codex",
        )
        self.assertEqual(event["uncertainty_kind"], "unresolved_external_write")
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "allow")
        self.assertTrue(decision.observation_gap)
        self.assertTrue(decision.verification_required)
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(len(projection["attempts"]), 1)
        attempt = next(iter(projection["attempts"].values()))
        self.assertEqual(attempt["effect"], "unknown")
        self.assertEqual(attempt["state"], "verifying")

    def test_local_sulde_mcp_write_uses_real_schema_and_stays_pending_without_db_proof(self) -> None:
        self.contract()
        payload = {
            "client": "codex",
            "session_id": "thread",
            "tool_name": "mcp__sulde_kb__memory_annotate",
            "tool_input": {
                "entities": [
                    {"name": "A", "type": "component"},
                    {"name": "B", "type": "risk"},
                ],
                "edges": [
                    {"src": "A", "rel": "prevents", "dst": "B", "confidence": 1.0}
                ],
                "extracted_by": "codex",
            },
        }
        empty_home = Path(self.temp.name) / "empty-kb"
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(empty_home)}):
            started = normalize_hook_event(payload, phase="started", provider="codex")
        self.assertEqual(started["effect"], "local_write")
        self.assertRegex(started["target"], r"^\[memory-annotation:[0-9a-f]{64}\]$")
        self.assertNotIn("A", started["target"])
        self.assertEqual(started["verification_kind"], "relation")
        authorized = GuardianSession(self.contract_path).observe(started)
        self.assertEqual(authorized.action, "allow")
        self.assertTrue(authorized.verification_required)
        session = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="thread",
        )
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(empty_home)}):
            completed = normalize_hook_event(
                {**payload, "success": True},
                phase="completed",
                provider="codex",
            )
        session.observe(completed)
        pending = load_contract(self.contract_path)["runtime"]["pending_verifications"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["capability"], "mcp:sulde_kb:memory_annotate")
        self.assertEqual(pending[0]["target"], started["target"])

    def test_local_sulde_memory_batch_is_system_verified_from_independent_db_read(self) -> None:
        self.contract()
        home = Path(self.temp.name) / "kb-home"
        home.mkdir()
        memory_writer = runpy.run_path(str(ROOT / "tools/kb-index/memory.py"))
        memory_writer["initialize"](home / "memory.db")
        payload = {
            "client": "codex",
            "session_id": "thread",
            "tool_name": "mcp__sulde_kb__memory_annotate",
            "tool_input": {
                "entities": [
                    {"name": "A", "type": "component"},
                    {"name": "B", "type": "risk"},
                    {"name": "C", "type": "component"},
                    {"name": "D", "type": "risk"},
                ],
                "edges": [
                    {"src": "A", "rel": "prevents", "dst": "B"},
                    {"src": "C", "rel": "prevents", "dst": "D"},
                ],
                "extracted_by": "codex",
            },
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            started = normalize_hook_event(payload, phase="started", provider="codex")
        authorized = GuardianSession(self.contract_path).observe(started)
        self.assertEqual(authorized.action, "allow")
        database = memory_writer["connect"](home / "memory.db")
        try:
            memory_writer["annotate_memory"](database, payload["tool_input"])
        finally:
            database.close()
        session = GuardianSession(self.contract_path, provider="codex", session_id="thread")
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            completed = normalize_hook_event(
                {**payload, "success": True},
                phase="completed",
                provider="codex",
            )
        self.assertEqual(
            completed["independent_verification"]["source"],
            "local_memory_db_read",
        )
        session.observe(completed)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(runtime["verified_effects"][-1]["verification_source"], "system_verification")
        self.assertEqual(runtime["verified_effects"][-1]["evidence_source"], "local_memory_db_read")
        attempts = load_intervention_projection(self.contract_path)["attempts"]
        self.assertEqual(next(iter(attempts.values()))["state"], "system_verified")

    def test_local_sulde_memory_batch_requires_every_entity_and_edge(self) -> None:
        self.contract()
        home = Path(self.temp.name) / "partial-kb"
        home.mkdir()
        database = sqlite3.connect(home / "memory.db")
        database.executescript(
            """
            CREATE TABLE mem_entities(name TEXT PRIMARY KEY, type TEXT NOT NULL);
            CREATE TABLE mem_edges(
                src TEXT NOT NULL,
                rel TEXT NOT NULL,
                dst TEXT NOT NULL,
                entry_id INTEGER,
                extracted_by TEXT NOT NULL,
                confidence REAL NOT NULL
            );
            INSERT INTO mem_entities(name, type) VALUES ('A', 'component'), ('B', 'risk');
            INSERT INTO mem_edges(src, rel, dst, entry_id, extracted_by, confidence)
            VALUES ('A', 'prevents', 'B', NULL, 'codex', 1.0);
            """
        )
        database.commit()
        database.close()
        payload = {
            "client": "codex",
            "session_id": "thread",
            "tool_name": "mcp__sulde_kb__memory_annotate",
            "tool_input": {
                "entities": [
                    {"name": "A", "type": "component"},
                    {"name": "B", "type": "risk"},
                    {"name": "missing", "type": "risk"},
                ],
                "edges": [
                    {"src": "A", "rel": "prevents", "dst": "B"},
                    {"src": "A", "rel": "prevents", "dst": "missing"},
                ],
                "extracted_by": "codex",
            },
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            started = normalize_hook_event(payload, phase="started", provider="codex")
        authorized = GuardianSession(self.contract_path).observe(started)
        self.assertEqual(authorized.action, "allow")
        session = GuardianSession(self.contract_path, provider="codex", session_id="thread")
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            completed = normalize_hook_event(
                {**payload, "success": True},
                phase="completed",
                provider="codex",
            )
        self.assertNotIn("independent_verification", completed)
        session.observe(completed)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(len(runtime["pending_verifications"]), 1)
        self.assertEqual(runtime["verified_effects"], [])

    def test_local_memory_system_policy_is_bounded_and_provider_attributed(self) -> None:
        self.contract()
        contract = load_contract(self.contract_path)
        for index in range(3):
            contract["runtime"]["continuation_uses"].append(
                {
                    "schema": "sulde-continuation-use-v1",
                    "grant_id": hashlib.sha256(
                        b"system-policy:sulde-memory-annotate-v1"
                    ).hexdigest(),
                    "profile_id": "sulde-memory-annotate-v1",
                    "authority": "system-policy",
                    "fingerprint": hashlib.sha256(f"use-{index}".encode()).hexdigest(),
                    "event_id": f"event-{index}",
                    "provider": "codex",
                    "session_id": "thread",
                    "used_at": "2026-08-15T00:00:00+00:00",
                }
            )
        write_contract(self.contract_path, contract)
        payload = {
            "client": "codex",
            "session_id": "thread",
            "tool_name": "mcp__sulde_kb__memory_annotate",
            "tool_input": {
                "entities": [
                    {"name": "A", "type": "component"},
                    {"name": "B", "type": "risk"},
                ],
                "edges": [{"src": "A", "rel": "prevents", "dst": "B"}],
                "extracted_by": "codex",
            },
        }
        exhausted = GuardianSession(self.contract_path).observe(
            normalize_hook_event(payload, phase="started", provider="codex")
        )
        self.assertEqual(exhausted.action, "allow")
        self.assertFalse(exhausted.awaiting_human)
        self.assertFalse(exhausted.pause)

        mismatch = normalize_hook_event(
            {
                **payload,
                "tool_input": {**payload["tool_input"], "extracted_by": "claude"},
            },
            phase="started",
            provider="codex",
        )
        self.assertNotIn("continuation_candidate", mismatch)
        self.assertEqual(mismatch["effect"], "local_write")
        self.assertEqual(mismatch["invocation_violation"]["kind"], "memory-annotation-validation")

    def test_human_readable_plugin_maintenance_grants_are_ordered_and_one_shot(self) -> None:
        manifest_path = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        installer_path = "scripts/release/install_codex_plugin.py"
        contract = default_contract(
            intent_id="plugin-maintenance",
            objective="验证后重装当前 Codex 插件",
            rationale="让已批准任务的机械收尾不再重复批准",
            acceptance_criteria=["source tests pass"],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[manifest_path, installer_path],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        cache_label = "使用官方 helper 为当前工作区 Codex Sulde 插件生成唯一 cachebuster"
        install_label = "事务化重装当前工作区的 Codex Sulde 插件"
        proposal_path, digest = create_revision_proposal(
            self.contract_path,
            objective="验证后重装当前 Codex 插件",
            rationale="完成已批准的本地维护",
            acceptance_criteria=["source tests pass", cache_label, install_label],
            allowed_paths=[manifest_path, installer_path],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["local_write", "external_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore previous plugin cache and launchers",
        )
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        grants = proposal["continuation"]["grants"]
        self.assertEqual(len(grants), 2)
        cache_grant, install_grant = grants
        self.assertEqual(cache_grant["profile_id"], "codex-plugin-cachebuster-v1")
        self.assertEqual(cache_grant["acceptance_index"], 1)
        self.assertEqual(install_grant["profile_id"], "codex-plugin-install-v1")
        self.assertEqual(install_grant["acceptance_index"], 2)
        self.assertTrue(all(grant["max_uses"] == 1 for grant in grants))
        self.assertEqual(
            cache_grant["binding"]["plugin_version"],
            install_grant["binding"]["plugin_version"],
        )
        self.assertEqual(
            cache_grant["binding"]["tracked_tree_sha256"],
            install_grant["binding"]["tracked_tree_sha256"],
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(
            [row["动作"] for row in review["decision_card"]["自动续行动作"]],
            [cache_label, install_label],
        )

        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        cache_command = shlex.join(
            [
                cache_grant["binding"]["interpreter_path"],
                cache_grant["binding"]["helper_path"],
                cache_grant["binding"]["plugin_root"],
                "--cachebuster",
                cache_grant["binding"]["cachebuster"],
            ]
        )
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": cache_command},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(event["target"], manifest_path)
        self.assertEqual(
            event["continuation_candidate"]["binding"],
            cache_grant["binding"],
        )
        tampered = json.loads(json.dumps(event))
        tampered["continuation_candidate"]["binding"]["helper_sha256"] = "0" * 64
        denied = GuardianSession(self.contract_path).observe(tampered)
        self.assertEqual(denied.action, "deny")
        self.assertFalse(denied.awaiting_human)

        allowed = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(allowed.action, "allow")
        self.assertTrue(allowed.verification_required)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(len(runtime["continuation_uses"]), 1)
        self.assertEqual(runtime["continuation_uses"][0]["authority"], "contract-grant")
        self.assertEqual(
            runtime["continuation_uses"][0]["profile_id"],
            "codex-plugin-cachebuster-v1",
        )

        install_command = shlex.join(
            [
                install_grant["binding"]["interpreter_path"],
                install_grant["binding"]["script_path"],
                "--json",
            ]
        )
        premature_install = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "other-thread",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": install_command},
            },
            phase="started",
            provider="codex",
        )
        self.assertNotEqual(
            premature_install["continuation_candidate"]["binding"],
            install_grant["binding"],
        )

    def test_v2_release_requires_install_before_scheduler_and_launcher_binding(self) -> None:
        manifest_path = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        release_labels = [
            guardian_module.CONTINUATION_PROFILES[profile_id]["label"]
            for profile_id in (
                "codex-plugin-cachebuster-v2",
                "codex-plugin-install-v2",
            )
        ]
        live_labels = [
            guardian_module.CONTINUATION_PROFILES[profile_id]["label"]
            for profile_id in (
                "sulde-scheduler-reconcile-v1",
                "sulde-launcher-refresh-v1",
            )
        ]
        contract = default_contract(
            intent_id="typed-release-maintenance",
            objective="类型化发布当前 Codex 插件",
            rationale="正式维护不能降级为 unknown Bash",
            acceptance_criteria=["source tests pass"],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[manifest_path],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        with self.assertRaisesRegex(
            IntentGuardianError,
            "installed maintenance generation is unavailable",
        ):
            create_revision_proposal(
                self.contract_path,
                objective="类型化发布当前 Codex 插件",
                rationale="正式维护不能降级为 unknown Bash",
                acceptance_criteria=[
                    "source tests pass",
                    *release_labels,
                    *live_labels,
                ],
                allowed_paths=[manifest_path],
                mode="enforce",
                decision_route="human",
                intent_kind="deterministic",
                risk="high",
                effects=["local_write", "external_write"],
                reversibility="compensatable",
                cost="bounded",
                rollback="restore the prior generation",
            )

        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="类型化发布当前 Codex 插件",
            rationale="正式维护不能降级为 unknown Bash",
            acceptance_criteria=["source tests pass", *release_labels],
            allowed_paths=[manifest_path],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="high",
            effects=["local_write", "external_write"],
            reversibility="compensatable",
            cost="bounded",
            rollback="restore the prior generation",
        )
        grants = json.loads(proposal_path.read_text(encoding="utf-8"))[
            "continuation"
        ]["grants"]
        self.assertEqual(
            [grant["profile_id"] for grant in grants],
            [
                "codex-plugin-cachebuster-v2",
                "codex-plugin-install-v2",
            ],
        )
        self.assertTrue(all(grant["max_uses"] == 1 for grant in grants))
        cache, install = grants
        self.assertEqual(cache["binding"]["python_env"], "PYTHONDONTWRITEBYTECODE=1")
        self.assertEqual(cache["binding"]["python_flag"], "-B")
        self.assertEqual(install["binding"]["python_env"], "PYTHONDONTWRITEBYTECODE=1")
        self.assertEqual(install["binding"]["python_flag"], "-B")
        self.assertEqual(
            {
                grant["binding"]["plugin_version"]
                for grant in (cache, install)
            },
            {cache["binding"]["plugin_version"]},
        )
        self.assertEqual(
            {
                grant["binding"]["tracked_tree_sha256"]
                for grant in (cache, install)
            },
            {cache["binding"]["tracked_tree_sha256"]},
        )

        self.install_maintenance_runtime_fixture()
        scheduler = guardian_resource_preflight._scheduler_reconcile_binding(ROOT)
        launcher = guardian_resource_preflight._launcher_refresh_binding(ROOT)
        self.assertEqual(scheduler["expected_label_count"], "16")
        self.assertEqual(
            scheduler["expected_labels_sha256"],
            launcher["expected_labels_sha256"],
        )

    def test_v2_install_wrapper_is_one_shot_and_near_misses_fail_closed(self) -> None:
        label = guardian_module.CONTINUATION_PROFILES["codex-plugin-install-v2"][
            "label"
        ]
        contract = default_contract(
            intent_id="sealed-install-wrapper",
            objective="重装当前 Codex 插件",
            rationale="验证无字节码封装",
            acceptance_criteria=["source tests pass"],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="重装当前 Codex 插件",
            rationale="验证无字节码封装",
            acceptance_criteria=[label],
            allowed_paths=[],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="high",
            effects=["external_write"],
            reversibility="compensatable",
            cost="bounded",
            rollback="restore the prior generation",
        )
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        grant = proposal["continuation"]["grants"][0]
        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        command = shlex.join(
            [
                grant["binding"]["python_env"],
                grant["binding"]["interpreter_path"],
                grant["binding"]["python_flag"],
                grant["binding"]["script_path"],
                "--json",
            ]
        )
        payload = {
            "client": "codex",
            "session_id": "sealed-install",
            "cwd": str(ROOT),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        event = normalize_hook_event(payload, phase="started", provider="codex")
        self.assertEqual(event["continuation_candidate"]["profile_id"], grant["profile_id"])
        first = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(first.action, "allow")
        second = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(second.action, "deny")
        self.assertEqual(
            len(load_contract(self.contract_path)["runtime"]["continuation_uses"]),
            1,
        )

        for near_miss in (
            command.replace("PYTHONDONTWRITEBYTECODE=1", "PYTHONPATH=/tmp"),
            f"{command} --unexpected",
        ):
            denied_event = normalize_hook_event(
                {**payload, "tool_input": {"command": near_miss}},
                phase="started",
                provider="codex",
            )
            self.assertEqual(denied_event["effect"], "external_write")
            self.assertTrue(denied_event["formal_maintenance"])
            self.assertIn("invocation_violation", denied_event)
            denied = evaluate_event(load_contract(self.contract_path), denied_event)
            self.assertEqual(denied.action, "deny")

    def test_scheduler_and_launcher_commands_require_installed_digest_bound_scripts(self) -> None:
        installed = self.install_maintenance_runtime_fixture()
        # Explicitly model a distinct installed version, even when portable
        # source bytes need no path rendering. This is not an identity bypass.
        script = installed / "scripts/kb/install-agents.sh"
        script.write_bytes(script.read_bytes() + b"\n# independently constructed installed fixture\n")
        scheduler_binding = guardian_resource_preflight._scheduler_reconcile_binding(ROOT)
        launcher_binding = guardian_resource_preflight._launcher_refresh_binding(ROOT)
        self.assertNotEqual(
            guardian_resources._sha256_path(ROOT / "scripts/kb/install-agents.sh"),
            guardian_resources._sha256_path(Path(scheduler_binding["script_path"])),
        )
        self.assertEqual(
            scheduler_binding["script_sha256"],
            guardian_resources._sha256_path(Path(scheduler_binding["script_path"])),
        )
        labels = [
            guardian_module.CONTINUATION_PROFILES[profile_id]["label"]
            for profile_id in (
                "sulde-scheduler-reconcile-v1",
                "sulde-launcher-refresh-v1",
            )
        ]
        contract = default_contract(
            intent_id="installed-maintenance",
            objective="协调已安装 generation",
            rationale="验证 artifact-bound authority",
            acceptance_criteria=labels,
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="协调已安装 generation",
            rationale="验证 artifact-bound authority",
            acceptance_criteria=labels,
            allowed_paths=[],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="high",
            effects=["external_write"],
            reversibility="compensatable",
            cost="bounded",
            rollback="restore the prior generation",
        )
        contract = json.loads(proposal_path.read_text(encoding="utf-8"))
        contract["confirmed_by"] = "human-readable-proposal-approval"
        contract["confirmation"] = {"required": False, "reason": ""}
        contract["status"] = "active"

        commands = (
            (
                shlex.join(
                    [
                        scheduler_binding["script_path"],
                        "--runtime-root",
                        scheduler_binding["runtime_root"],
                        "--provider",
                        "codex",
                        "--accept-llm-data-egress",
                    ]
                ),
                "sulde-scheduler-reconcile-v1",
            ),
            (
                shlex.join(
                    [
                        launcher_binding["script_path"],
                        "--launchers-only",
                        "--host",
                        "codex",
                    ]
                ),
                "sulde-launcher-refresh-v1",
            ),
        )
        for index, (command, profile_id) in enumerate(commands):
            event = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "typed-maintenance",
                    "cwd": str(ROOT),
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(
                event["continuation_candidate"]["profile_id"],
                profile_id,
            )
            self.assertEqual(event["effect"], "external_write")
            self.assertEqual(
                event["continuation_candidate"]["binding"],
                contract["continuation"]["grants"][index]["binding"],
            )
            grant = contract["continuation"]["grants"][index]
            self.assertEqual(
                (
                    event["continuation_candidate"]["effect"],
                    event["effect"],
                    event["capability"],
                    event["continuation_candidate"]["target"],
                    event["target"],
                    event["verification_kind"],
                ),
                (
                    grant["effect"],
                    grant["effect"],
                    grant["capability"],
                    grant["target"],
                    grant["target"],
                    grant["verification_kind"],
                ),
            )
            self.assertIsNotNone(
                guardian_events._continuation_authorization(contract, event)
            )

        launch_workspace = Path(self.temp.name) / "session-launch-workspace"
        launch_workspace.mkdir()
        mapped = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "typed-maintenance-handoff",
                "cwd": str(launch_workspace),
                "sulde_workspace_root": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": commands[1][0]},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(mapped["resource_base"], str(launch_workspace))
        self.assertEqual(
            mapped["continuation_candidate"]["binding"],
            contract["continuation"]["grants"][1]["binding"],
        )
        self.assertIsNotNone(
            guardian_events._continuation_authorization(contract, mapped)
        )
        unmapped = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "typed-maintenance-handoff",
                "cwd": str(launch_workspace),
                "tool_name": "Bash",
                "tool_input": {"command": commands[1][0]},
            },
            phase="started",
            provider="codex",
        )
        self.assertNotIn("continuation_candidate", unmapped)
        self.assertIn("invocation_violation", unmapped)

        scheduler_script = Path(scheduler_binding["script_path"])
        scheduler_script.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
        drifted = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "typed-maintenance",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": commands[0][0]},
            },
            phase="started",
            provider="codex",
        )
        self.assertIn("continuation_candidate", drifted)
        self.assertNotEqual(
            drifted["continuation_candidate"]["binding"],
            contract["continuation"]["grants"][0]["binding"],
        )
        self.assertIsNone(
            guardian_events._continuation_authorization(contract, drifted)
        )
        self.assertTrue(drifted["formal_maintenance"])

    def test_scheduler_and_launcher_verifiers_require_live_matching_seals(self) -> None:
        self.install_maintenance_runtime_fixture()
        scheduler_binding = guardian_resource_preflight._scheduler_reconcile_binding(ROOT)
        launcher_binding = guardian_resource_preflight._launcher_refresh_binding(ROOT)
        kb_home = (Path(self.temp.name) / "verification-kb").resolve()
        runtime_root = (Path(self.temp.name) / "installed-runtime").resolve()
        scheduler_binding = {
            **scheduler_binding,
            "kb_home": str(kb_home),
            "runtime_root": str(runtime_root),
        }
        launcher_binding = {
            **launcher_binding,
            "kb_home": str(kb_home),
            "runtime_root": str(runtime_root),
        }
        (kb_home / "bin").mkdir(parents=True, exist_ok=True)
        runtime_root.mkdir(parents=True, exist_ok=True)
        labels = sorted(
            path.stem
            for path in (ROOT / "templates/launchagents").glob("com.sulde.*.plist")
        )
        runner = kb_home / "bin/sulde-scheduled-run"
        runner.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        runner.chmod(0o700)
        runner_sha256 = hashlib.sha256(runner.read_bytes()).hexdigest()
        generation = f"delivery:{'a' * 64}"
        deployment = {
            "schema": "sulde-installed-deployment-generation-v1",
            "schema_version": 1,
            "platform": "posix",
            "status": "generation_verified",
            "operational_ready": True,
            "provider": "codex",
            "runtime_root": str(runtime_root),
            "runtime_tree_sha256": "a" * 64,
            "generation": generation,
            "managed_labels": labels,
            "scheduler_runner": str(runner),
            "scheduler_runner_sha256": runner_sha256,
        }
        owner = {
            "schema_version": 2,
            "status": "active",
            "installation_status": "generation_verified",
            "operational_ready": True,
            "provider": "codex",
            "source_root": str(runtime_root),
            "runtime_root": str(runtime_root),
            "runtime_tree_sha256": "a" * 64,
            "generation": generation,
            "managed_labels": labels,
            "scheduler": "launchd",
            "scheduler_runner_sha256": runner_sha256,
        }
        launcher_manifest = {
            "schema_version": 1,
            "provider": "codex",
            "platform": "posix",
            "generation": generation,
            "runtime_tree_sha256": "a" * 64,
            "scheduler_runner": str(runner),
            "scheduler_runner_sha256": runner_sha256,
        }
        for path, payload in (
            (kb_home / "deployment-generation.json", deployment),
            (kb_home / "runtime-owner.json", owner),
            (kb_home / "bin/.sulde-launchers.json", launcher_manifest),
        ):
            payload["scheduler_activation_id"] = "matching-activation"
            path.write_text(json.dumps(payload), encoding="utf-8")
            path.chmod(0o600)
        self.assertEqual(
            guardian_resources._labels_digest(labels),
            (
                scheduler_binding["expected_label_count"],
                scheduler_binding["expected_labels_sha256"],
            ),
        )
        self.assertIsNotNone(
            guardian_resources._protected_json_object(
                kb_home / "deployment-generation.json"
            )
        )
        self.assertIsNotNone(
            guardian_resources._protected_json_object(kb_home / "runtime-owner.json")
        )
        self.assertEqual(deployment["provider"], owner["provider"])
        self.assertEqual(deployment["runtime_root"], owner["runtime_root"])
        self.assertEqual(deployment["generation"], owner["generation"])
        self.assertEqual(
            deployment["runtime_tree_sha256"], owner["runtime_tree_sha256"]
        )
        self.assertEqual(deployment["managed_labels"], owner["managed_labels"])
        self.assertEqual(owner["scheduler_runner_sha256"], runner_sha256)
        self.assertEqual(guardian_resources._sha256_path(runner), runner_sha256)

        def candidate(profile_id: str, binding: dict) -> tuple[dict, str]:
            target = guardian_module.CONTINUATION_PROFILES[profile_id]["target"]
            digest = guardian_resources._verification_digest(
                {"profile_id": profile_id, "target": target, "binding": binding}
            )
            return (
                {
                    "profile_id": profile_id,
                    "target": target,
                    "binding": binding,
                    "verification_sha256": digest,
                },
                digest,
            )

        scheduler_candidate, scheduler_digest = candidate(
            "sulde-scheduler-reconcile-v1",
            scheduler_binding,
        )
        persisted_deployment = guardian_resources._protected_json_object(
            kb_home / "deployment-generation.json"
        )
        persisted_owner = guardian_resources._protected_json_object(
            kb_home / "runtime-owner.json"
        )
        preconditions = {
            "digest": scheduler_digest
            == scheduler_candidate["verification_sha256"],
            "deployment": persisted_deployment is not None,
            "owner": persisted_owner is not None,
            "provider": persisted_deployment.get("provider") == "codex"
            and persisted_owner.get("provider") == "codex",
            "runtime": persisted_deployment.get("runtime_root")
            == str(runtime_root.resolve())
            and persisted_owner.get("runtime_root") == str(runtime_root.resolve()),
            "status": persisted_deployment.get("status")
            == "generation_verified"
            and persisted_deployment.get("operational_ready") is True
            and persisted_owner.get("status") == "active"
            and persisted_owner.get("installation_status")
            == "generation_verified"
            and persisted_owner.get("operational_ready") is True,
            "schema": persisted_deployment.get("schema")
            == "sulde-installed-deployment-generation-v1"
            and persisted_owner.get("schema_version") == 2,
            "scheduler": persisted_owner.get("scheduler") == "launchd",
            "labels": guardian_resources._labels_digest(
                persisted_owner.get("managed_labels")
            )
            == (
                scheduler_binding["expected_label_count"],
                scheduler_binding["expected_labels_sha256"],
            ),
            "runner": Path(persisted_deployment["scheduler_runner"]).is_file()
            and guardian_resources._sha256_path(runner)
            == persisted_deployment["scheduler_runner_sha256"]
            == persisted_owner["scheduler_runner_sha256"],
        }
        self.assertTrue(all(preconditions.values()), preconditions)
        listing = subprocess.CompletedProcess(
            ["/bin/launchctl", "list"],
            0,
            "\n".join(f"-\t0\t{label}" for label in labels),
            "",
        )
        with (
            mock.patch.object(
                guardian_resource_preflight.shutil,
                "which",
                return_value="/bin/launchctl",
            ),
            mock.patch.object(
                guardian_resource_preflight.subprocess,
                "run",
                return_value=listing,
            ) as scheduler_probe,
        ):
            scheduler_verified = guardian_resources._scheduler_reconcile_verification(
                scheduler_candidate,
                expected_digest=scheduler_digest,
            )
        self.assertTrue(scheduler_probe.called)
        self.assertEqual(
            scheduler_verified["source"],
            "local_scheduler_owner_and_launchctl_read",
        )

        launcher_candidate, launcher_digest = candidate(
            "sulde-launcher-refresh-v1",
            launcher_binding,
        )
        with mock.patch.object(
            guardian_resource_preflight,
            "verify_launcher_installation",
            return_value={"healthy": True},
        ):
            launcher_verified = guardian_resources._launcher_refresh_verification(
                launcher_candidate,
                expected_digest=launcher_digest,
            )
        self.assertEqual(
            launcher_verified["source"],
            "local_launcher_scheduler_seal_read",
        )

        runner.write_text("tampered\n", encoding="utf-8")
        with (
            mock.patch.object(
                guardian_resource_preflight.shutil,
                "which",
                return_value="/bin/launchctl",
            ),
            mock.patch.object(
                guardian_resource_preflight.subprocess,
                "run",
                return_value=listing,
            ),
        ):
            self.assertIsNone(
                guardian_resources._scheduler_reconcile_verification(
                    scheduler_candidate,
                    expected_digest=scheduler_digest,
                )
            )

    def test_high_risk_formal_unknown_denies_without_changing_ordinary_unknown(self) -> None:
        self.contract()
        contract = self.declare_effects(self.contract_path, "unknown")
        contract["decision"]["risk"] = "high"
        write_contract(self.contract_path, contract)
        ordinary = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "unknown-policy",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "opaque-command-for-test"},
            },
            phase="started",
            provider="codex",
        )
        ordinary_decision = evaluate_event(load_contract(self.contract_path), ordinary)
        self.assertEqual(ordinary_decision.action, "allow")
        self.assertFalse(ordinary_decision.observation_gap)
        self.assertEqual(ordinary_decision.reason_code, "non_material_observation")
        formal = {**ordinary, "formal_maintenance": True}
        formal_decision = evaluate_event(load_contract(self.contract_path), formal)
        self.assertEqual(formal_decision.action, "deny")
        self.assertIn("类型化 profile", formal_decision.reason)
        installer = ROOT / "scripts/release/install_codex_plugin.py"
        composed = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "unknown-policy",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{shlex.join([sys.executable, str(installer), '--json'])} "
                        "; echo chained"
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(composed["formal_maintenance"])
        self.assertEqual(
            evaluate_event(load_contract(self.contract_path), composed).action,
            "deny",
        )

    def test_formal_maintenance_reference_uses_executed_script_role(self) -> None:
        expected = self.root / "scripts/kb/bootstrap.sh"
        expected.parent.mkdir(parents=True)
        expected.write_text("#!/bin/sh\n", encoding="utf-8")
        self.contract()
        contract = self.declare_effects(self.contract_path, "local_write")
        contract["constraints"]["allowed_paths"] = [str(expected)]
        contract["decision"]["risk"] = "high"
        write_contract(self.contract_path, contract)
        agent_runtime = ROOT / "scripts/kb/agent-runtime.py"
        data_operand = shlex.join(
            [
                sys.executable,
                "-B",
                str(agent_runtime),
                "merge",
                str(self.root),
                "--target-branch",
                "main",
                "--source-ref",
                "dev",
                "--expected-target-head",
                "a" * 40,
                "--expected-source-head",
                "b" * 40,
                "--path",
                "scripts/kb/bootstrap.sh",
            ]
        )
        self.assertFalse(
            guardian_resource_preflight.formal_maintenance_reference(data_operand)
        )
        diagnostic_code = (
            'import ast; files=["scripts/release/install_codex_plugin.py"]; '
            "print(len(files))"
        )
        diagnostic = (
            f"{shlex.join([sys.executable, '-B', '-c', diagnostic_code])} "
            "&& git diff --check"
        )
        self.assertFalse(
            guardian_resource_preflight.formal_maintenance_reference(diagnostic)
        )
        with mock.patch.object(
            guardian_resources,
            "_trusted_script_command",
            return_value={
                "effect": "local_write",
                "profile_id": "sulde-agent-runtime-git-lifecycle-v1",
                "targets": [str(expected)],
            },
        ):
            event = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "git-lifecycle-data-operand",
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {"command": data_operand},
                },
                phase="started",
                provider="codex",
            )
        self.assertNotIn("formal_maintenance", event)
        self.assertEqual(
            evaluate_event(load_contract(self.contract_path), event).action,
            "allow",
        )

        installer = ROOT / "scripts/release/install_codex_plugin.py"
        direct_writer = shlex.join([sys.executable, "-B", str(installer), "--json"])
        self.assertTrue(
            guardian_resource_preflight.formal_maintenance_reference(direct_writer)
        )
        self.assertTrue(
            guardian_resource_preflight.formal_maintenance_reference(
                shlex.join(["env", "PYTHONDONTWRITEBYTECODE=1", *shlex.split(direct_writer)])
            )
        )
        self.assertTrue(
            guardian_resource_preflight.formal_maintenance_reference(
                shlex.join(["sh", "-c", direct_writer])
            )
        )
        self.assertTrue(
            guardian_resource_preflight.formal_maintenance_reference(
                f"echo safe ; {direct_writer}"
            )
        )

    def test_sealed_host_local_maintenance_can_be_decided_by_agent_policy(self) -> None:
        manifest_path = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        contract = default_contract(
            intent_id="agent-plugin-maintenance",
            objective="保持当前工作区可验证",
            rationale="执行确定性的宿主本地维护",
            acceptance_criteria=["source tests pass"],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[manifest_path],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        cache_label = "使用官方 helper 为当前工作区 Codex Sulde 插件生成唯一 cachebuster"
        install_label = "事务化重装当前工作区的 Codex Sulde 插件"
        proposal_path, digest = create_revision_proposal(
            self.contract_path,
            objective="完成已验证代码的宿主本地插件重装",
            rationale="让机器可证明的机械收尾由监督器执行",
            acceptance_criteria=[cache_label, install_label],
            allowed_paths=[manifest_path],
            mode="enforce",
            decision_route="auto",
            intent_kind="deterministic",
            risk="medium",
            effects=["local_write", "external_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复旧版本缓存、launcher 与全局规则快照",
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(review["decision_route"], "agent")
        self.assertEqual(len(review["decision_card"]["自动续行动作"]), 2)
        self.assertIn(
            "监督器执行",
            review["decision_card"]["执行权限边界"]["外部写入"],
        )
        self.assertEqual(
            review["decision_card"]["不能由 Agent 决断的原因"],
            [],
        )
        self.codex_agent_decide(
            self.contract_path,
            digest,
            rationale="两个物质动作均为一次性、宿主本地且有独立 verifier",
            evidence=["精确 manifest 写入目标", "安装缓存整树与注册表可独立读回"],
            session_id="agent-plugin-maintenance",
        )
        applied = apply_revision_proposal(self.contract_path, proposal_path)
        self.assertEqual(applied["applied_decision_authority"], "agent-policy")
        self.assertEqual(len(applied["continuation"]["grants"]), 2)

    def test_applied_sealed_install_bridges_one_old_hook_retry(self) -> None:
        install_label = "事务化重装当前工作区的 Codex Sulde 插件"
        base = default_contract(
            intent_id="old-hook-bootstrap-retry",
            objective="完成当前 Codex 插件的可验证自举修复",
            rationale="旧 Hook 仍持有缓存 runtime",
            acceptance_criteria=[install_label],
            workspace=ROOT,
            mode="enforce",
            confirmed_by="human",
        )
        write_contract(self.contract_path, base)
        seed_path, _ = create_revision_proposal(
            self.contract_path,
            objective="安装当前工作区的已验证 Codex 插件",
            rationale="使用事务安装器替换旧 Hook 入口",
            acceptance_criteria=[install_label],
            mode="enforce",
            decision_route="agent",
            intent_kind="deterministic",
            risk="medium",
            effects=["external_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore previous plugin cache and launchers",
        )
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        old_grant = json.loads(json.dumps(seed["continuation"]["grants"][0]))
        old_grant["grant_id"] = "e" * 64
        old_candidate = guardian_module._continuation_candidate_from_grant(old_grant)

        # Reset the proposal pointer, then reproduce one old installation whose
        # final state was not independently proven.
        write_contract(self.contract_path, base)
        old = begin_effect_attempt(
            self.contract_path,
            intent_id=base["intent_id"],
            intent_revision=base["revision"],
            fingerprint="a" * 64,
            source_event_id="old-cached-hook-install",
            capability=old_grant["capability"],
            target=old_grant["target"],
            effect=old_grant["effect"],
            provider="codex",
            session_id="bootstrap-thread",
            idempotency_key="old-cached-hook-install",
            **self.typed_effect_identity(
                target=old_grant["target"],
                capability=old_grant["capability"],
                effect=old_grant["effect"],
                arguments_digest="a" * 64,
            ),
            verification_kind="content",
            verification_sha256=old_candidate["verification_sha256"],
        )
        old_intervention = guardian_module.mark_attempt_unknown(
            self.contract_path,
            old["attempt_id"],
            reason="old Hook lost the post-install verifier callback",
        )
        current = load_contract(self.contract_path)
        current["runtime"]["pending_verifications"] = [
            {
                "attempt_id": old["attempt_id"],
                "fingerprint": "a" * 64,
                "capability": old_grant["capability"],
                "target": old_grant["target"],
                "provider": "codex",
                "session_id": "bootstrap-thread",
                "created_at": "2026-08-16T00:00:00+00:00",
                "outcome_unknown": True,
                "verification_kind": "content",
                "verification_sha256": old_candidate["verification_sha256"],
                "continuation_grant_id": old_grant["grant_id"],
                "continuation_profile_id": old_grant["profile_id"],
                "continuation_grant": old_grant,
            }
        ]
        write_contract(self.contract_path, current)

        proposal_path, digest = create_revision_proposal(
            self.contract_path,
            objective="安装当前工作区的已验证 Codex 插件",
            rationale="让新 Hook 通过稳定入口接管当前长寿命会话",
            acceptance_criteria=[install_label],
            mode="enforce",
            decision_route="agent",
            intent_kind="deterministic",
            risk="medium",
            effects=["external_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore previous plugin cache and launchers",
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(review["decision_route"], "agent")
        proposal_contract = load_contract(proposal_path)
        previous = load_contract(self.contract_path)
        drifted = json.loads(json.dumps(previous))
        drifted["runtime"]["pending_verifications"][0]["continuation_grant"][
            "binding"
        ]["codex_sha256"] = "0" * 64
        receipt_shape = {"provider": "codex", "session_id": "bootstrap-thread"}
        self.assertEqual(
            guardian_module._authorize_bootstrap_retries_for_applied_proposal(
                self.contract_path,
                previous=drifted,
                applied=proposal_contract,
                receipt=receipt_shape,
                proposal_digest_value=digest,
            ),
            [],
        )
        self.assertEqual(
            guardian_module._authorize_bootstrap_retries_for_applied_proposal(
                self.contract_path,
                previous=previous,
                applied=proposal_contract,
                receipt={"provider": "codex", "session_id": "other-thread"},
                proposal_digest_value=digest,
            ),
            [],
        )
        no_grant = json.loads(json.dumps(proposal_contract))
        no_grant["continuation"]["grants"] = []
        self.assertEqual(
            guardian_module._authorize_bootstrap_retries_for_applied_proposal(
                self.contract_path,
                previous=previous,
                applied=no_grant,
                receipt=receipt_shape,
                proposal_digest_value=digest,
            ),
            [],
        )
        self.assertEqual(
            load_intervention_projection(self.contract_path)["interventions"][
                old_intervention["intervention_id"]
            ]["status"],
            "open",
        )
        self.codex_agent_decide(
            self.contract_path,
            digest,
            rationale="安装动作一次性、宿主本地、可回滚且有内容 verifier",
            evidence=["旧 pending 与新 grant 的执行身份逐字段匹配"],
            session_id="bootstrap-thread",
        )
        applied = apply_revision_proposal(self.contract_path, proposal_path)

        self.assertEqual(applied["applied_decision_authority"], "agent-policy")
        projection = load_intervention_projection(self.contract_path)
        resolved = projection["interventions"][old_intervention["intervention_id"]]
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["decision"], "retry_authorized")
        self.assertEqual(resolved["actor"], "system-continuation-grant")
        self.assertEqual(projection["attempts"][old["attempt_id"]]["state"], "unknown")
        retry = guardian_module.retry_grant_for_event(
            self.contract_path,
            fingerprint="a" * 64,
            operation_fingerprint=str(old["operation_fingerprint"]),
            provider="codex",
            session_id="bootstrap-thread",
        )
        self.assertEqual(retry["intervention_id"], old_intervention["intervention_id"])

        current_grant = applied["continuation"]["grants"][0]
        current_candidate = guardian_module._continuation_candidate_from_grant(
            current_grant
        )
        semantic_event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "bootstrap-thread",
                "call_id": "new-runtime-install-alias",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "opaque-stable-install-alias"},
            },
            phase="started",
            provider="codex",
        )
        semantic_event.update(
            {
                "effect": current_grant["effect"],
                "capability": current_grant["capability"],
                "target": current_grant["target"],
                "arguments_digest": old["operation_arguments_digest"],
                "verification_kind": current_grant["verification_kind"],
                "verification_sha256": current_candidate["verification_sha256"],
                "continuation_candidate": current_candidate,
            }
        )
        authority = guardian_module._continuation_authorization(
            applied,
            semantic_event,
        )
        self.assertIsNotNone(authority)
        semantic_event["continuation_authority"] = authority
        blocker = guardian_module.material_event_blocker(
            self.contract_path,
            {**semantic_event, "fingerprint": guardian_module.event_fingerprint(semantic_event)},
        )
        self.assertIsNotNone(blocker)
        self.assertEqual(
            guardian_module._registered_semantic_retry_intervention(
                applied,
                {**semantic_event, "session_id": "other-thread"},
                blocker,
            ),
            "",
        )
        drifted_applied = json.loads(json.dumps(applied))
        drifted_applied["runtime"]["pending_verifications"][0][
            "continuation_grant"
        ]["binding"]["codex_sha256"] = "0" * 64
        self.assertEqual(
            guardian_module._registered_semantic_retry_intervention(
                drifted_applied,
                semantic_event,
                blocker,
            ),
            "",
        )

        with mock.patch.object(
            guardian_recovery,
            "_registered_continuation_verification",
            return_value=None,
        ):
            decision = GuardianSession(self.contract_path).observe(semantic_event)
        self.assertEqual(decision.action, "allow")
        projection = load_intervention_projection(self.contract_path)
        retry_attempts = [
            attempt
            for attempt_id, attempt in projection["attempts"].items()
            if attempt_id != old["attempt_id"]
        ]
        self.assertEqual(len(retry_attempts), 1)
        self.assertEqual(
            retry_attempts[0]["predecessor_attempt_id"],
            old["attempt_id"],
        )
        self.assertEqual(
            retry_attempts[0]["retry_intervention_id"],
            old_intervention["intervention_id"],
        )
        self.assertEqual(
            projection["interventions"][old_intervention["intervention_id"]][
                "retry_consumed_by"
            ],
            retry_attempts[0]["attempt_id"],
        )
        with mock.patch.object(
            guardian_recovery,
            "_registered_continuation_verification",
            return_value=None,
        ):
            self.assertEqual(
                guardian_module.reconcile_pending_verifications(self.contract_path),
                [],
            )
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["pending_verifications"],
            [],
        )

    def test_new_sealed_install_may_compensate_only_a_matching_old_unknown(self) -> None:
        manifest_path = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        install_label = "事务化重装当前工作区的 Codex Sulde 插件"
        contract = default_contract(
            intent_id="verified-install-compensation",
            objective="修复上次未闭合的宿主本地插件安装",
            rationale="旧安装留下部分状态且无法证明最终结果",
            acceptance_criteria=[install_label],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[manifest_path],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="修复上次未闭合的宿主本地插件安装",
            rationale="只允许密封安装器建立补偿链",
            acceptance_criteria=[install_label],
            allowed_paths=[manifest_path],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["external_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore previous plugin cache and launchers",
        )
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        current_grant = proposal["continuation"]["grants"][0]
        old_grant = json.loads(json.dumps(current_grant))
        old_grant["grant_id"] = "e" * 64
        old_candidate = guardian_module._continuation_candidate_from_grant(old_grant)
        old = begin_effect_attempt(
            self.contract_path,
            intent_id=proposal["intent_id"],
            intent_revision=proposal["revision"],
            fingerprint="a" * 64,
            source_event_id="old-install",
            capability=old_grant["capability"],
            target=old_grant["target"],
            effect=old_grant["effect"],
            provider="codex",
            session_id="compensation-thread",
            idempotency_key="old-install",
            **self.typed_effect_identity(
                target=old_grant["target"],
                capability=old_grant["capability"],
                effect=old_grant["effect"],
                arguments_digest="a" * 64,
            ),
            verification_kind="content",
            verification_sha256=old_candidate["verification_sha256"],
        )
        guardian_module.mark_attempt_unknown(
            self.contract_path,
            old["attempt_id"],
            reason="old installer changed part of the cache before proof was lost",
        )
        current = load_contract(self.contract_path)
        current["runtime"]["pending_verifications"] = [
            {
                "attempt_id": old["attempt_id"],
                "fingerprint": "a" * 64,
                "capability": old_grant["capability"],
                "target": old_grant["target"],
                "provider": "codex",
                "session_id": "compensation-thread",
                "created_at": "2026-08-16T00:00:00+00:00",
                "outcome_unknown": True,
                "verification_kind": "content",
                "verification_sha256": old_candidate["verification_sha256"],
                "continuation_grant_id": old_grant["grant_id"],
                "continuation_profile_id": old_grant["profile_id"],
                "continuation_grant": old_grant,
            }
        ]
        write_contract(self.contract_path, current)
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "compensation-thread",
                "call_id": "new-install",
                "tool_name": "Bash",
                "tool_input": {"command": "opaque-unsealed-command"},
            },
            phase="started",
            provider="codex",
        )
        event.update(
            {
                "action": "Bash",
                "capability": old_grant["capability"],
                "effect": old_grant["effect"],
                "target": old_grant["target"],
                "verification_kind": "content",
                "verification_sha256": "b" * 64,
            }
        )
        with mock.patch.object(
            guardian_recovery,
            "_registered_continuation_verification",
            return_value=None,
        ):
            blocked = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(blocked.action, "deny")
        self.assertTrue(blocked.awaiting_human)

        authority = {
            "authority": "contract-grant",
            "grant_id": current_grant["grant_id"],
            "profile_id": "codex-plugin-install-v1",
        }
        with (
            mock.patch.object(
                guardian_recovery,
                "_registered_continuation_verification",
                return_value=None,
            ),
            mock.patch.object(
                guardian_policy,
                "_continuation_authorization",
                return_value=authority,
            ),
        ):
            allowed = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(allowed.action, "allow")
        attempts = load_intervention_projection(self.contract_path)["attempts"]
        compensation = next(
            row
            for attempt_id, row in attempts.items()
            if attempt_id != old["attempt_id"]
        )
        self.assertEqual(
            compensation["compensates_attempt_id"],
            old["attempt_id"],
        )

        wrong_profile_event = dict(event)
        wrong_profile_event["continuation_authority"] = {
            **authority,
            "profile_id": "codex-plugin-cachebuster-v1",
        }
        blocker = guardian_module.material_event_blocker(
            self.contract_path,
            wrong_profile_event,
        )
        self.assertIsNotNone(blocker)
        self.assertEqual(
            guardian_module._registered_compensation_predecessor(
                load_contract(self.contract_path),
                wrong_profile_event,
                blocker,
            ),
            "",
        )

        completed = {
            **event,
            "phase": "completed",
            "success": True,
            "independent_verification": {
                "capability": "tool:codex_plugin_install_verify",
                "source": "local_codex_install_read",
                "evidence": {"content": ["b" * 64]},
            },
        }
        with mock.patch.object(
            guardian_policy,
            "_continuation_authorization",
            return_value={**authority, "completion": True},
        ):
            completed_decision = GuardianSession(self.contract_path).observe(completed)
        self.assertEqual(completed_decision.action, "allow")
        after = load_contract(self.contract_path)
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(
            projection["attempts"][old["attempt_id"]]["state"],
            "unknown",
        )
        old_intervention = next(
            row
            for row in projection["interventions"].values()
            if row["attempt_id"] == old["attempt_id"]
        )
        self.assertEqual(old_intervention["decision"], "system_compensated")
        self.assertEqual(
            old_intervention["compensated_by_attempt_id"],
            compensation["attempt_id"],
        )
        self.assertEqual(
            after["runtime"]["verified_effects"][-1]["compensates_attempt_ids"],
            [old["attempt_id"]],
        )

    def test_proposal_effect_narrows_only_when_effect_is_explicit(self) -> None:
        contract = default_contract(
            intent_id="proposal-effect-narrowing",
            objective="保留已确认边界",
            acceptance_criteria=["现有本地修改权限不被意外改变"],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=["allowed.txt"],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)

        legacy_path, _ = create_revision_proposal(
            self.contract_path,
            objective="按已确认表达更新 allowed.txt",
            acceptance_criteria=["allowed.txt 包含 approved"],
            allowed_paths=["allowed.txt"],
            mode="enforce",
            decision_route="human",
        )
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        self.assertEqual(legacy["decision"]["effects"], ["unknown"])
        self.assertTrue(legacy["permissions"]["local_write"])

        explicit_path, _ = create_revision_proposal(
            self.contract_path,
            objective="只执行外部宿主动作",
            acceptance_criteria=["外部状态被独立读回"],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["external_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复宿主原状态",
        )
        explicit = json.loads(explicit_path.read_text(encoding="utf-8"))
        self.assertFalse(explicit["permissions"]["local_write"])

    def test_hot_upgrade_completion_adopts_the_same_host_call_id(self) -> None:
        manifest_path = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        label = "使用官方 helper 为当前工作区 Codex Sulde 插件生成唯一 cachebuster"
        contract = default_contract(
            intent_id="hot-upgrade-pairing",
            objective="刷新宿主本地插件版本",
            rationale="验证跨运行时回调配对",
            acceptance_criteria=[label],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[manifest_path],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="刷新宿主本地插件版本",
            rationale="验证跨运行时回调配对",
            acceptance_criteria=[label],
            allowed_paths=[manifest_path],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 manifest 原版本字段",
            continuation_grants=["codex-plugin-cachebuster-v1@1"],
        )
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        grant = proposal["continuation"]["grants"][0]
        command = shlex.join(
            [
                grant["binding"]["interpreter_path"],
                grant["binding"]["helper_path"],
                grant["binding"]["plugin_root"],
                "--cachebuster",
                grant["binding"]["cachebuster"],
            ]
        )
        base_payload = {
            "client": "codex",
            "session_id": "hot-session",
            "call_id": "same-host-call",
            "cwd": str(ROOT),
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        started = normalize_hook_event(base_payload, phase="started", provider="codex")
        started["runtime_generation"] = "installed-generation-before-upgrade"
        self.assertEqual(GuardianSession(self.contract_path).observe(started).action, "allow")
        hijack = normalize_hook_event(
            {
                **base_payload,
                "session_id": "other-session",
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        hijack_decision = GuardianSession(self.contract_path).observe(hijack)
        self.assertEqual(hijack_decision.action, "deny")
        self.assertFalse(hijack_decision.awaiting_human)
        completed = normalize_hook_event(
            {
                **base_payload,
                "tool_input": {
                    "command": command,
                    "adapter_runtime": "new-version",
                },
                "success": False,
            },
            phase="completed",
            provider="codex",
        )
        self.assertNotEqual(started["runtime_generation"], completed["runtime_generation"])
        self.assertNotEqual(started["arguments_digest"], completed["arguments_digest"])
        decision = GuardianSession(self.contract_path).observe(completed)
        self.assertEqual(decision.action, "allow")
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["open_events"], [])
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(len(projection["attempts"]), 1)

    def test_hot_upgrade_install_completion_adopts_only_verified_tree_drift(self) -> None:
        install_label = "事务化重装当前工作区的 Codex Sulde 插件"
        contract = default_contract(
            intent_id="hot-upgrade-install-pairing",
            objective="重装并独立验证当前 Codex 插件",
            rationale="安装过程会切换稳定 Hook bridge",
            acceptance_criteria=[install_label],
            workspace=ROOT,
            mode="enforce",
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="重装并独立验证当前 Codex 插件",
            rationale="安装过程会切换稳定 Hook bridge",
            acceptance_criteria=[install_label],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["external_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore previous plugin cache and stable launchers",
        )
        proposal = load_contract(proposal_path)
        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        grant = proposal["continuation"]["grants"][0]
        dispatched_candidate = guardian_module._continuation_candidate_from_grant(grant)
        started = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "hot-install-session",
                "call_id": "same-install-call",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "sealed-install-test-entrypoint"},
            },
            phase="started",
            provider="codex",
        )
        started.update(
            {
                "effect": grant["effect"],
                "capability": grant["capability"],
                "target": grant["target"],
                "verification_kind": grant["verification_kind"],
                "verification_sha256": dispatched_candidate["verification_sha256"],
                "continuation_candidate": dispatched_candidate,
                "runtime_generation": "installed-generation-before-upgrade",
            }
        )
        self.assertEqual(GuardianSession(self.contract_path).observe(started).action, "allow")

        observed_candidate = json.loads(json.dumps(dispatched_candidate))
        observed_candidate["binding"]["tracked_tree_sha256"] = "c" * 64
        observed_candidate["verification_sha256"] = guardian_module._verification_digest(
            {
                "profile_id": observed_candidate["profile_id"],
                "target": observed_candidate["target"],
                "binding": observed_candidate["binding"],
            }
        )
        completed = {
            **started,
            "phase": "completed",
            "success": True,
            "runtime_generation": "installed-generation-after-upgrade",
            "verification_sha256": observed_candidate["verification_sha256"],
            "continuation_candidate": observed_candidate,
            "independent_verification": {
                "capability": "tool:codex_plugin_install_verify",
                "source": "local_codex_install_read",
                "evidence": {"content": [observed_candidate["verification_sha256"]]},
            },
        }
        current = load_contract(self.contract_path)
        adopted = guardian_module._hot_upgrade_completion_authorization(
            current,
            completed,
        )
        self.assertIsNotNone(adopted)
        self.assertEqual(adopted["allowed_binding_drift"], ["tracked_tree_sha256"])

        missing_verifier = dict(completed)
        missing_verifier.pop("independent_verification")
        self.assertIsNone(
            guardian_module._hot_upgrade_completion_authorization(
                current,
                missing_verifier,
            )
        )
        for field, value in (
            ("script_sha256", "d" * 64),
            ("plugin_version", "0.2.5+different"),
        ):
            tampered = json.loads(json.dumps(completed))
            tampered["continuation_candidate"]["binding"][field] = value
            tampered_digest = guardian_module._verification_digest(
                {
                    "profile_id": tampered["continuation_candidate"]["profile_id"],
                    "target": tampered["continuation_candidate"]["target"],
                    "binding": tampered["continuation_candidate"]["binding"],
                }
            )
            tampered["continuation_candidate"]["verification_sha256"] = tampered_digest
            tampered["verification_sha256"] = tampered_digest
            tampered["independent_verification"]["evidence"] = {
                "content": [tampered_digest]
            }
            self.assertIsNone(
                guardian_module._hot_upgrade_completion_authorization(
                    current,
                    tampered,
                )
            )
        for field, value in (
            ("session_id", "other-session"),
            ("call_id", "other-call"),
            ("runtime_generation", "installed-generation-before-upgrade"),
        ):
            mismatched = dict(completed)
            mismatched[field] = value
            self.assertIsNone(
                guardian_module._hot_upgrade_completion_authorization(
                    current,
                    mismatched,
                )
            )

        decision = GuardianSession(self.contract_path).observe(completed)
        self.assertEqual(decision.action, "allow")
        after = load_contract(self.contract_path)
        self.assertEqual(after["runtime"]["open_events"], [])
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        projection = load_intervention_projection(self.contract_path)
        attempt = next(iter(projection["attempts"].values()))
        self.assertEqual(attempt["state"], "system_verified")

    def test_cachebuster_continuation_requires_exact_manifest_and_tree_proof(self) -> None:
        base = Path(self.temp.name) / "cachebuster-proof"
        workspace = base / "workspace"
        plugin_root = workspace / "integrations/codex/plugins/sulde"
        manifest = plugin_root / ".codex-plugin/plugin.json"
        helper = (
            base
            / "codex-home/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        )
        interpreter = base / "python3"
        tracked = workspace / "tracked.txt"
        manifest.parent.mkdir(parents=True)
        helper.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"name": "sulde", "version": "0.2.5+old"}, indent=2) + "\n",
            encoding="utf-8",
        )
        helper.write_text("# fixed helper\n", encoding="utf-8")
        interpreter.write_text("fixed interpreter\n", encoding="utf-8")
        tracked.write_text("stable\n", encoding="utf-8")
        self.write_explicit_release_inputs(workspace)
        subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=workspace, check=True, capture_output=True)
        environment = {"CODEX_HOME": str(base / "codex-home")}
        with mock.patch.dict(os.environ, environment, clear=False):
            binding, rendered = guardian_module._codex_plugin_cachebuster_binding(
                workspace,
                cachebuster="proof-1",
                interpreter=interpreter,
                helper=helper,
            )
        digest = "c" * 64
        candidate = {
            "binding": binding,
            "verification_sha256": digest,
        }
        with mock.patch.dict(os.environ, environment, clear=False):
            self.assertIsNone(
                guardian_module._codex_plugin_cachebuster_verification(
                    candidate,
                    expected_digest=digest,
                )
            )
            manifest.write_bytes(rendered)
            verified = guardian_module._codex_plugin_cachebuster_verification(
                candidate,
                expected_digest=digest,
            )
            self.assertEqual(verified["source"], "local_codex_cachebuster_read")
            tracked.write_text("drift\n", encoding="utf-8")
            self.assertIsNone(
                guardian_module._codex_plugin_cachebuster_verification(
                    candidate,
                    expected_digest=digest,
                )
            )

    def test_cachebuster_continuation_closes_with_system_verification(self) -> None:
        base = Path(self.temp.name) / "cachebuster-session"
        workspace = base / "workspace"
        plugin_root = workspace / "integrations/codex/plugins/sulde"
        manifest = plugin_root / ".codex-plugin/plugin.json"
        helper = (
            base
            / "codex-home/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        )
        manifest.parent.mkdir(parents=True)
        helper.parent.mkdir(parents=True)
        manifest.write_text(
            json.dumps({"name": "sulde", "version": "0.2.5+old"}, indent=2) + "\n",
            encoding="utf-8",
        )
        helper.write_text(
            "import argparse, json\n"
            "from pathlib import Path\n"
            "p=argparse.ArgumentParser(); p.add_argument('plugin'); "
            "p.add_argument('--cachebuster', required=True); a=p.parse_args()\n"
            "m=Path(a.plugin)/'.codex-plugin/plugin.json'; d=json.loads(m.read_text()); "
            "d['version']=d['version'].split('+',1)[0]+'+codex.'+a.cachebuster; "
            "m.write_text(json.dumps(d, indent=2)+'\\n')\n",
            encoding="utf-8",
        )
        self.write_explicit_release_inputs(workspace)
        subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=workspace, check=True, capture_output=True)
        manifest_target = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        label = "使用官方 helper 为当前工作区 Codex Sulde 插件生成唯一 cachebuster"
        environment = {"CODEX_HOME": str(base / "codex-home")}
        with mock.patch.dict(os.environ, environment, clear=False):
            contract = default_contract(
                intent_id="cachebuster-session",
                objective="刷新插件版本",
                rationale="为确定性安装准备唯一版本",
                acceptance_criteria=[label],
                workspace=workspace,
                mode="enforce",
                allowed_paths=[manifest_target],
                confirmed_by="human",
            )
            write_contract(self.contract_path, contract)
            proposal_path, _ = create_revision_proposal(
                self.contract_path,
                objective="刷新插件版本",
                rationale="为确定性安装准备唯一版本",
                acceptance_criteria=[label],
                allowed_paths=[manifest_target],
                mode="enforce",
                decision_route="human",
                intent_kind="deterministic",
                risk="medium",
                effects=["local_write"],
                reversibility="reversible",
                cost="none",
                rollback="restore prior version field",
                continuation_grants=["codex-plugin-cachebuster-v1@1"],
            )
            proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
            proposal["confirmed_by"] = "human-readable-proposal-approval"
            proposal["confirmation"] = {"required": False, "reason": ""}
            proposal["status"] = "active"
            write_contract(self.contract_path, proposal)
            binding = proposal["continuation"]["grants"][0]["binding"]
            command = shlex.join(
                [
                    binding["interpreter_path"],
                    binding["helper_path"],
                    binding["plugin_root"],
                    "--cachebuster",
                    binding["cachebuster"],
                ]
            )
            payload = {
                "client": "codex",
                "session_id": "thread",
                "call_id": "cachebuster-call",
                "cwd": str(workspace),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
            started = normalize_hook_event(payload, phase="started", provider="codex")
            self.assertEqual(GuardianSession(self.contract_path).observe(started).action, "allow")
            execution = subprocess.run(
                shlex.split(command),
                cwd=workspace,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(execution.returncode, 0, execution.stderr)
            completed = normalize_hook_event(
                {
                    **payload,
                    "success": True,
                    "tool_response": {
                        "stdout": execution.stdout,
                        "stderr": execution.stderr,
                    },
                },
                phase="completed",
                provider="codex",
            )
            self.assertEqual(
                completed["independent_verification"]["source"],
                "local_codex_cachebuster_read",
            )
            GuardianSession(self.contract_path).observe(completed)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(
            runtime["verified_effects"][-1]["verified_by_capability"],
            "tool:codex_plugin_cachebuster_verify",
        )

    def test_install_continuation_requires_independent_tree_and_registry_proof(self) -> None:
        base = Path(self.temp.name) / "install-proof"
        workspace = base / "workspace"
        artifact = base / "artifact"
        codex_home = base / "codex-home"
        registered = artifact / "plugins" / "sulde"
        installed = (
            codex_home
            / "plugins"
            / "cache"
            / "sulde-local"
            / "sulde"
            / "0.2.5+proof"
        )
        kb_root = base / "kb"
        codex_path = base / "codex"
        interpreter = base / "python3"
        script = workspace / "scripts" / "release" / "install_codex_plugin.py"
        for path in (
            registered / ".codex-plugin",
            registered / "runtime",
            installed / ".codex-plugin",
            installed / "runtime",
            kb_root,
            script.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
        descriptor = json.dumps({"name": "sulde", "version": "0.2.5+proof"})
        for plugin in (registered, installed):
            (plugin / ".codex-plugin" / "plugin.json").write_text(
                descriptor,
                encoding="utf-8",
            )
            (plugin / "runtime" / "probe.txt").write_text("same", encoding="utf-8")
        codex_home.mkdir(parents=True, exist_ok=True)
        (codex_home / "AGENTS.md").write_text(
            "## Codex 派单档位纪律\nuse $dispatch-task\n",
            encoding="utf-8",
        )
        for path in (codex_path, interpreter, script):
            path.write_text("fixed", encoding="utf-8")
        binding = {
            "artifact_root": str(artifact.resolve()),
            "codex_path": str(codex_path.resolve()),
            "codex_sha256": hashlib.sha256(codex_path.read_bytes()).hexdigest(),
            "codex_home": str(codex_home.resolve()),
            "interpreter_path": str(interpreter.resolve()),
            "interpreter_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(),
            "kb_home": str(kb_root.resolve()),
            "platform": "posix",
            "plugin_version": "0.2.5+proof",
            "script_path": str(script.resolve()),
            "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "tracked_tree_sha256": "a" * 64,
            "workspace_root": str(workspace.resolve()),
        }
        digest = "b" * 64
        tree_digest = guardian_module._portable_tree_sha256(installed)
        candidate = {
            "binding": binding,
            "verification_sha256": digest,
        }
        response = {
            "status": "ready",
            "ready_scope": "installed_artifact_and_local_runtime",
            "artifact": str(artifact),
            "installed_path": str(installed),
            "plugin_version": "0.2.5+proof",
            "staged_plugin_tree_sha256": tree_digest,
            "smoke": {
                "plugin_tree_sha256": tree_digest,
                "plugin_list_verified": True,
            },
        }
        listing = subprocess.CompletedProcess(
            [str(codex_path), "plugin", "list"],
            0,
            (
                "sulde@sulde-local  installed, enabled  0.2.5+proof  "
                f"{registered}\n"
            ),
            "",
        )
        script.write_text("changed after dispatch", encoding="utf-8")
        with mock.patch.object(
            guardian_resources,
            "verify_launcher_installation",
            return_value={"healthy": True},
        ) as launcher_verification, mock.patch.object(
            guardian_module.subprocess,
            "run",
            return_value=listing,
        ):
            verified = guardian_module._codex_plugin_install_verification(
                candidate,
                expected_digest=digest,
            )
            self.assertEqual(verified["source"], "local_codex_install_read")
            listing.stdout = (
                "sulde@sulde-local  installed, enabled  0.2.5+stale-display  "
                f"{registered}\n"
            )
            stale_display_verified = (
                guardian_module._codex_plugin_install_verification(
                    candidate,
                    expected_digest=digest,
                )
            )
            self.assertEqual(
                stale_display_verified["source"],
                "local_codex_install_read",
            )
            launcher_verification.return_value = {
                "healthy": False,
                "issues": [
                    "command effects: trusted command digest changed: "
                    "codex-plugin-validate-v1",
                    "command effects: trusted command digest changed: "
                    "codex-plugin-cachebuster-v1",
                ],
            }
            host_refresh_verified = (
                guardian_module._codex_plugin_install_verification(
                    candidate,
                    expected_digest=digest,
                )
            )
            self.assertEqual(
                host_refresh_verified["source"],
                "local_codex_install_read",
            )
            launcher_verification.return_value = {
                "healthy": False,
                "issues": ["launcher file digest mismatch: intent-guardian"],
            }
            self.assertIsNone(
                guardian_module._codex_plugin_install_verification(
                    candidate,
                    expected_digest=digest,
                )
            )
            launcher_verification.return_value = {"healthy": True}
            (installed / "runtime" / "probe.txt").write_text("tampered", encoding="utf-8")
            self.assertIsNone(
                guardian_module._codex_plugin_install_verification(
                    candidate,
                    response,
                    expected_digest=digest,
                )
            )
            (installed / "runtime" / "probe.txt").write_text("same", encoding="utf-8")
            unrelated = base / "unrelated" / "sulde"
            (unrelated / ".codex-plugin").mkdir(parents=True)
            (unrelated / "runtime").mkdir()
            (unrelated / ".codex-plugin" / "plugin.json").write_text(
                descriptor,
                encoding="utf-8",
            )
            (unrelated / "runtime" / "probe.txt").write_text(
                "same",
                encoding="utf-8",
            )
            listing.stdout = (
                "sulde@sulde-local  installed, enabled  0.2.5+proof  "
                f"{unrelated}\n"
            )
            self.assertIsNone(
                guardian_module._codex_plugin_install_verification(
                    candidate,
                    expected_digest=digest,
                )
            )

    def test_registered_verifier_reconciles_pending_effect_without_human_attestation(self) -> None:
        manifest_path = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        label = "使用官方 helper 为当前工作区 Codex Sulde 插件生成唯一 cachebuster"
        contract = default_contract(
            intent_id="system-reconcile",
            objective="刷新宿主本地插件版本",
            rationale="恢复缺少完成回调证据的确定性操作",
            acceptance_criteria=[label],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[manifest_path],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="刷新宿主本地插件版本",
            rationale="恢复缺少完成回调证据的确定性操作",
            acceptance_criteria=[label],
            allowed_paths=[manifest_path],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 manifest 原版本字段",
            continuation_grants=["codex-plugin-cachebuster-v1@1"],
        )
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        grant = proposal["continuation"]["grants"][0]
        candidate = guardian_module._continuation_candidate_from_grant(grant)
        attempt = begin_effect_attempt(
            self.contract_path,
            intent_id=proposal["intent_id"],
            intent_revision=proposal["revision"],
            fingerprint="a" * 64,
            source_event_id="missing-post-callback",
            capability=grant["capability"],
            target=grant["target"],
            effect=grant["effect"],
            provider="codex",
            session_id="reconcile-session",
            idempotency_key="system-reconcile-attempt",
            **self.typed_effect_identity(
                target=grant["target"],
                capability=grant["capability"],
                effect=grant["effect"],
                arguments_digest="a" * 64,
            ),
            verification_kind="content",
            verification_sha256=candidate["verification_sha256"],
        )
        guardian_module.mark_attempt_result(
            self.contract_path,
            attempt["attempt_id"],
            success=True,
            reason="callback returned without independently readable stdout",
        )
        guardian_module.mark_attempt_unknown(
            self.contract_path,
            attempt["attempt_id"],
            reason="host restarted before independent verification completed",
        )
        proposal = load_contract(self.contract_path)
        proposal["runtime"]["pending_verifications"] = [
            {
                "attempt_id": attempt["attempt_id"],
                "fingerprint": "a" * 64,
                "capability": grant["capability"],
                "target": grant["target"],
                "provider": "codex",
                "session_id": "reconcile-session",
                "created_at": "2026-08-16T00:00:00+00:00",
                "outcome_unknown": False,
                "verification_kind": "content",
                "verification_sha256": candidate["verification_sha256"],
                "continuation_grant_id": grant["grant_id"],
                "continuation_profile_id": grant["profile_id"],
            }
        ]
        proposal["revision"] += 1
        proposal["continuation"] = {"grants": []}
        write_contract(self.contract_path, proposal)
        proof = {
            "capability": "tool:codex_plugin_cachebuster_verify",
            "evidence": {"content": [candidate["verification_sha256"]]},
            "source": "local_codex_cachebuster_read",
        }
        with mock.patch.object(
            guardian_recovery,
            "_registered_continuation_verification",
            return_value=proof,
        ):
            reconciled = guardian_module.reconcile_pending_verifications(
                self.contract_path
            )
        self.assertEqual(len(reconciled), 1)
        after = load_contract(self.contract_path)
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        self.assertEqual(
            after["runtime"]["verified_effects"][-1]["verification_source"],
            "system_reconciliation",
        )
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(
            projection["attempts"][attempt["attempt_id"]]["state"],
            "system_verified",
        )
        intervention = next(iter(projection["interventions"].values()))
        self.assertEqual(intervention["status"], "resolved")
        self.assertEqual(intervention["decision"], "system_verified")

    def test_reconcile_verifications_cli_is_idempotent_without_pending_work(self) -> None:
        self.contract()

        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "reconcile-verifications",
                "--contract",
                str(self.contract_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema"], "sulde-verification-reconciliation-v1")
        self.assertEqual(result["reconciled_attempt_ids"], [])
        self.assertEqual(result["reconciled_count"], 0)
        self.assertEqual(result["pending_verifications"], 0)

    def test_reconcile_verifications_is_a_trusted_control_command_only(self) -> None:
        self.contract()
        launcher = f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'}"
        command = (
            f"{launcher} reconcile-verifications "
            f"--contract {self.contract_path}"
        )

        event = normalize_hook_event(
            {"tool_name": "Bash", "tool_input": {"command": command}},
            phase="started",
            provider="codex",
        )
        self.assertTrue(event["control_plane"])
        self.assertEqual(event["control_route"], "agent")
        self.assertEqual(event["effect"], "read")
        self.assertEqual(
            GuardianSession(self.contract_path).observe(event).action,
            "allow",
        )
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["open_events"],
            [],
        )

        fake_launcher = self.root / "intent-guardian.py"
        fake_launcher.write_text("print('untrusted')\n", encoding="utf-8")
        untrusted = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{sys.executable} {fake_launcher} "
                        "reconcile-verifications --contract /tmp/intent.json"
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertFalse(untrusted.get("control_plane", False))

        composed = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"{command} ; echo unexpected"},
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(composed["control_plane"])
        self.assertEqual(composed["control_route"], "invalid-composition" if os.name == "nt" else "composition")
        self.assertEqual(
            GuardianSession(self.contract_path).observe(composed).action,
            "deny" if os.name == "nt" else "allow",
        )

    def test_reprobe_uses_attempt_digest_when_recovered_pending_row_lost_it(self) -> None:
        manifest_path = "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        label = "使用官方 helper 为当前工作区 Codex Sulde 插件生成唯一 cachebuster"
        contract = default_contract(
            intent_id="reprobe-orphaned-pending",
            objective="复查热升级期间丢失完成回调的插件操作",
            rationale="safe-boundary 只恢复了最小 pending 投影",
            acceptance_criteria=[label],
            workspace=ROOT,
            mode="enforce",
            allowed_paths=[manifest_path],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="复查热升级期间丢失完成回调的插件操作",
            rationale="safe-boundary 只恢复了最小 pending 投影",
            acceptance_criteria=[label],
            allowed_paths=[manifest_path],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 manifest 原版本字段",
            continuation_grants=["codex-plugin-cachebuster-v1@1"],
        )
        proposal = json.loads(proposal_path.read_text(encoding="utf-8"))
        grant = proposal["continuation"]["grants"][0]
        candidate = guardian_module._continuation_candidate_from_grant(grant)

        # A second immutable proposal mirrors the real maintenance history:
        # multiple verifier recipes remain discoverable after the active
        # revision has carried only the effect debt forward.
        decoy = json.loads(json.dumps(proposal))
        decoy_grant = decoy["continuation"]["grants"][0]
        decoy_grant["binding"]["tracked_tree_sha256"] = "f" * 64
        decoy_grant["grant_id"] = guardian_module._continuation_grant_id(
            decoy_grant
        )
        decoy["proposal_digest"] = ""
        decoy_digest = proposal_digest(decoy)
        decoy["proposal_digest"] = decoy_digest
        decoy_path = self.contract_path.with_name(
            f"{self.contract_path.stem}.proposal.{decoy_digest[:16]}.json"
        )
        decoy_path.write_text(
            json.dumps(decoy, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        decoy_candidate = guardian_module._continuation_candidate_from_grant(
            decoy_grant
        )
        self.assertNotEqual(
            decoy_candidate["verification_sha256"],
            candidate["verification_sha256"],
        )
        self.assertIsNone(
            guardian_module._pending_verification_grant(
                self.contract_path,
                proposal,
                {"verification_sha256": decoy_candidate["verification_sha256"]},
                expected_digest=candidate["verification_sha256"],
            )
        )

        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        attempt = begin_effect_attempt(
            self.contract_path,
            intent_id=proposal["intent_id"],
            intent_revision=proposal["revision"],
            fingerprint="b" * 64,
            source_event_id="hot-upgrade-orphaned-dispatch",
            capability=grant["capability"],
            target=grant["target"],
            effect=grant["effect"],
            provider="codex",
            session_id="reprobe-session",
            idempotency_key="reprobe-orphaned-attempt",
            **self.typed_effect_identity(
                target=grant["target"],
                capability=grant["capability"],
                effect=grant["effect"],
                arguments_digest="b" * 64,
            ),
            verification_kind="content",
            verification_sha256=candidate["verification_sha256"],
        )
        guardian_module.mark_attempt_result(
            self.contract_path,
            attempt["attempt_id"],
            success=True,
            reason="installer returned before the new runtime handled PostToolUse",
        )
        intervention = guardian_module.mark_attempt_unknown(
            self.contract_path,
            attempt["attempt_id"],
            reason="safe-boundary recovered an orphaned active effect",
        )
        current = load_contract(self.contract_path)
        current["runtime"]["pending_verifications"] = [
            {
                "attempt_id": attempt["attempt_id"],
                "fingerprint": "b" * 64,
                "capability": grant["capability"],
                "target": grant["target"],
                "provider": "codex",
                "session_id": "reprobe-session",
                "created_at": "2026-08-17T00:00:00+00:00",
                "outcome_unknown": True,
            }
        ]
        current["revision"] += 1
        current["continuation"] = {"grants": []}
        write_contract(self.contract_path, current)
        guardian_module.resolve_effect_intervention(
            self.contract_path,
            intervention["intervention_id"],
            decision="reprobe_authorized",
            evidence="当前会话只授权独立复查，不重做原操作",
            actor="permission-request:codex",
        )

        proof = {
            "capability": "tool:codex_plugin_cachebuster_verify",
            "evidence": {"content": [candidate["verification_sha256"]]},
            "source": "local_codex_cachebuster_read",
        }

        def verify_selected_grant(selected: dict) -> dict:
            selected_candidate = guardian_module._continuation_candidate_from_grant(
                selected
            )
            self.assertEqual(
                selected_candidate["verification_sha256"],
                candidate["verification_sha256"],
            )
            return proof

        with mock.patch.object(
            guardian_recovery,
            "_registered_continuation_verification",
            side_effect=verify_selected_grant,
        ):
            reconciled = guardian_module.reconcile_pending_verifications(
                self.contract_path
            )

        self.assertEqual(len(reconciled), 1)
        after = load_contract(self.contract_path)
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(
            projection["attempts"][attempt["attempt_id"]]["state"],
            "system_verified",
        )

    def test_real_memory_graph_schema_produces_relation_evidence(self) -> None:
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__sulde_kb__memory_graph",
                "tool_input": {"entity": "A", "limit": 10},
                "tool_response": {
                    "rows": [
                        {
                            "src": "A",
                            "rel": "prevents",
                            "dst": "B",
                            "confidence": 1.0,
                            "extracted_by": "codex",
                            "hop": 1,
                        }
                    ]
                },
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        relation = {"subject": "A", "predicate": "prevents", "object": "B"}
        expected = hashlib.sha256(
            json.dumps(
                relation,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(event["effect"], "read")
        self.assertIn(expected, event["verification_evidence"]["relation"])

    def test_mcp_create_uses_result_id_as_verification_target(self) -> None:
        self.contract()
        started = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__create_document",
                "tool_input": {"name": "resume"},
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(self.contract_path).observe(started)
        self.assertEqual(denied.action, "deny")
        self.declare_effects(self.contract_path, "external_write")
        session = GuardianSession(self.contract_path)
        session.observe(started)
        completed = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__create_document",
                "tool_input": {"name": "resume"},
                "tool_response": {"structuredContent": {"id": "doc-123"}},
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        session.observe(completed)
        pending = load_contract(self.contract_path)["runtime"]["pending_verifications"]
        self.assertEqual(pending[0]["target"], "doc-123")
        empty_read = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc-123"},
                "tool_response": {"items": []},
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        session.observe(empty_read)
        self.assertEqual(
            len(load_contract(self.contract_path)["runtime"]["pending_verifications"]),
            1,
        )
        found_read = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc-123"},
                "tool_response": {"id": "doc-123"},
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        session.observe(found_read)
        self.assertEqual(load_contract(self.contract_path)["runtime"]["pending_verifications"], [])

    def test_external_completion_without_pre_callback_still_creates_verification_debt(self) -> None:
        self.contract()
        completed = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        decision = GuardianSession(self.contract_path).observe(completed)
        self.assertEqual(decision.action, "allow")
        self.assertTrue(decision.observation_gap)
        pending = load_contract(self.contract_path)["runtime"]["pending_verifications"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["target"], "doc://resume")

    def test_mcp_write_then_independent_read_records_verification_evidence(self) -> None:
        self.contract()
        write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(self.contract_path).observe(write)
        self.assertEqual(denied.action, "deny")
        self.declare_effects(self.contract_path, "external_write")
        session = GuardianSession(self.contract_path)
        session.observe(write)
        completed_write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
                "tool_response": {"id": "reply-member-not-the-write-target"},
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        session.observe(completed_write)
        self.assertEqual(len(load_contract(self.contract_path)["runtime"]["pending_verifications"]), 1)
        read = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc://resume"},
            },
            phase="started",
            provider="codex",
        )
        session.observe(read)
        completed_read = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc://resume"},
                "tool_response": {
                    "id": "nested-member-not-the-read-target",
                    "content": "new",
                },
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        session.observe(completed_read)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(runtime["verified_effects"][0]["target"], "doc://resume")

    @unittest.skip("retired: Git effects no longer enter Guardian verification debt")
    def test_git_push_is_verified_by_exact_remote_ref_oid(self) -> None:
        repository = Path(self.temp.name) / "git-project"
        repository.mkdir()
        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=repository,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=repository,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Intent Test"],
            cwd=repository,
            check=True,
        )
        (repository / "README.md").write_text("verified ref\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
        subprocess.run(
            ["git", "commit", "-m", "fixture"],
            cwd=repository,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "remote", "add", "origin", "../remote.git"],
            cwd=repository,
            check=True,
        )
        oid = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        ).stdout.strip()
        contract = default_contract(
            intent_id="typed-git-effect",
            objective="发布当前 main ref 并独立验证",
            acceptance_criteria=["远端 main 精确等于本地提交"],
            workspace=repository,
            mode="enforce",
            allowed_paths=["."],
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        payload = {
            "client": "codex",
            "session_id": "git-thread",
            "cwd": str(repository),
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main"},
        }
        started = normalize_hook_event(payload, phase="started", provider="codex")
        self.assertEqual(started["effect"], "external_write")
        self.assertTrue(started["target"].startswith("git-ref:"))
        self.assertTrue(started["target"].endswith(":refs/heads/main"))
        self.assertEqual(started["verification_kind"], "relation")
        self.assertRegex(started["verification_sha256"], r"^[0-9a-f]{64}$")

        denied = GuardianSession(self.contract_path).observe(started)
        self.assertEqual(denied.action, "deny")
        self.declare_effects(self.contract_path, "external_write")
        session = GuardianSession(self.contract_path)
        self.assertEqual(session.observe(started).action, "allow")
        completed = normalize_hook_event(
            {**payload, "success": True, "tool_response": "push completed"},
            phase="completed",
            provider="codex",
        )
        session.observe(completed)
        self.assertEqual(
            len(load_contract(self.contract_path)["runtime"]["pending_verifications"]),
            1,
        )

        verified_read = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "git-thread",
                "cwd": str(repository),
                "tool_name": "Bash",
                "tool_input": {
                    "command": "git ls-remote origin refs/heads/main"
                },
                "tool_response": f"{oid}\trefs/heads/main\n",
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        self.assertEqual(verified_read["effect"], "read")
        self.assertEqual(verified_read["target"], started["target"])
        self.assertIn(
            started["verification_sha256"],
            verified_read["verification_evidence"]["relation"],
        )
        session.observe(verified_read)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(
            runtime["verified_effects"][-1]["verification_source"],
            "system_verification",
        )

    def test_successful_read_with_wrong_content_stays_unknown_at_turn_end(self) -> None:
        self.contract()
        write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(self.contract_path).observe(write)
        self.assertEqual(denied.action, "deny")
        self.declare_effects(self.contract_path, "external_write")
        session = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="thread",
        )
        session.observe(write)
        session.observe(dict(write, phase="completed", success=True))
        wrong_read = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc://resume"},
                "tool_response": {"content": "old"},
                "success": True,
            },
            phase="completed",
            provider="codex",
        )
        session.observe(wrong_read)
        self.assertEqual(
            len(load_contract(self.contract_path)["runtime"]["pending_verifications"]),
            1,
        )
        session.finalize_lane()
        report = guardian_report(self.contract_path)
        self.assertEqual(report["effect_truth"]["attempts_by_state"]["unknown"], 1)
        self.assertEqual(report["effect_truth"]["interventions_open"], 1)

    def test_unknown_effect_opens_scoped_intervention_without_semantic_pause(self) -> None:
        self.contract()
        write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(self.contract_path).observe(write)
        self.assertEqual(denied.action, "deny")
        self.declare_effects(self.contract_path, "external_write")
        session = GuardianSession(self.contract_path)
        session.observe(write)
        completion = session.observe(dict(write, phase="completed", success=False))
        self.assertEqual(completion.action, "allow")
        self.assertEqual(load_contract(self.contract_path)["status"], "active")
        report = guardian_report(self.contract_path)
        self.assertEqual(report["effect_truth"]["interventions_open"], 1)
        next_write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__create_document",
                "tool_input": {"name": "another"},
            },
            phase="started",
            provider="codex",
        )
        unrelated = GuardianSession(self.contract_path).observe(next_write)
        self.assertEqual(unrelated.action, "allow")
        same_target = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "retry"},
            },
            phase="started",
            provider="codex",
        )
        blocked = GuardianSession(self.contract_path).observe(same_target)
        self.assertEqual(blocked.action, "deny")
        self.assertTrue(blocked.awaiting_human)
        self.assertFalse(blocked.pause)
        self.assertEqual(load_contract(self.contract_path)["status"], "active")
        cross_session = GuardianSession(self.contract_path).observe(
            {**same_target, "session_id": "recovery-thread"}
        )
        self.assertEqual(cross_session.action, "deny")
        self.assertIn("同一目标", cross_session.reason)

    def test_unresolved_effect_debt_stays_current_after_new_task_revision(self) -> None:
        self.contract()
        self.declare_effects(self.contract_path, "external_write")
        payload = {
            "client": "codex",
            "session_id": "old-task",
            "call_id": "old-call",
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://resume", "content": "new"},
        }
        started = normalize_hook_event(payload, phase="started", provider="codex")
        session = GuardianSession(self.contract_path)
        self.assertEqual(session.observe(started).action, "allow")
        completed = normalize_hook_event(
            {**payload, "success": False},
            phase="completed",
            provider="codex",
        )
        self.assertEqual(session.observe(completed).action, "allow")
        prior_epoch = load_contract(self.contract_path)["task_epoch"]

        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="开始一个只读的新任务",
            acceptance_criteria=["历史外部事实仍可审计"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
            intent_kind="deterministic",
            risk="low",
            effects=["read"],
            reversibility="reversible",
            cost="none",
            rollback="无需回滚",
        )
        self.live_approve_proposal(self.contract_path, digest)
        applied = load_contract(self.contract_path)
        self.assertNotEqual(applied["task_epoch"], prior_epoch)
        current_intervention = guardian_module._current_effect_intervention(
            self.contract_path,
            provider="codex",
        )
        self.assertEqual(current_intervention[0]["status"], "open")
        report = guardian_report(self.contract_path)
        self.assertEqual(report["supervision"]["current_pending_verifications"], 1)
        self.assertEqual(report["supervision"]["historical_pending_verifications"], 0)
        self.assertEqual(report["supervision"]["current_interventions_open"], 1)
        self.assertEqual(report["supervision"]["historical_interventions_open"], 0)
        terminal = GuardianSession(self.contract_path).summary()
        self.assertEqual(terminal["pending_verifications"], 1)
        self.assertEqual(terminal["effect_unknown"], 1)
        self.assertEqual(terminal["interventions_open"], 1)

        same_target = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "new-task-session",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "again"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(
            GuardianSession(self.contract_path).observe(same_target).action,
            "deny",
        )

    def test_material_world_change_invalidates_an_already_approved_proposal(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="在当前事实基础上继续修改简历",
            acceptance_criteria=["事实保持不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 resume.md",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="human-review-session",
        )
        observed = observe_native_permission_request(
            self.native_permission_payload(
                preview,
                session_id="human-review-session",
            ),
            provider="codex",
        )
        self.assertEqual(observed["action"], "defer")

        payload = {
            "client": "codex",
            "session_id": "human-review-session",
            "call_id": "world-change",
            "cwd": str(self.root),
            "tool_name": "Write",
            "tool_input": {"file_path": "resume.md", "content": "changed"},
        }
        session = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="human-review-session",
        )
        started = normalize_hook_event(payload, phase="started", provider="codex")
        started_decision = session.observe(started)
        self.assertEqual(started_decision.action, "allow", started_decision.reason)
        completed = normalize_hook_event(
            {**payload, "success": True},
            phase="completed",
            provider="codex",
        )
        completed_decision = session.observe(completed)
        self.assertEqual(completed_decision.action, "allow", completed_decision.reason)
        changed = load_contract(self.contract_path)
        changed["runtime"]["material_sequence"] += 1
        write_contract(self.contract_path, changed)

        result = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="human-review-session",
        )
        self.assertEqual(result["status"], "superseded")
        self.assertFalse(result["authority_transferred"])
        self.assertEqual(load_contract(proposal)["proposal_digest"], digest)

    def test_human_effect_resolution_does_not_increment_intent_revision(self) -> None:
        self.contract()
        write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(self.contract_path).observe(write)
        self.assertEqual(denied.action, "deny")
        self.declare_effects(self.contract_path, "external_write")
        session = GuardianSession(self.contract_path)
        session.observe(write)
        session.observe(dict(write, phase="completed", success=False))
        before = load_contract(self.contract_path)
        ledger = load_intervention_projection(self.contract_path)
        intervention_id = next(iter(ledger["interventions"]))
        resolved = resolve_effect_intervention(
            self.contract_path,
            intervention_id,
            decision="human_attested_success",
            evidence="operator independently inspected the remote document",
        )
        after = load_contract(self.contract_path)
        self.assertEqual(resolved["decision"], "human_attested_success")
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["status"], "active")
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        self.assertEqual(
            after["runtime"]["verified_effects"][-1]["verification_source"],
            "human_attestation",
        )

    def test_resume_does_not_reclassify_unresolved_effect_as_history(self) -> None:
        self.contract()
        self.declare_effects(self.contract_path, "external_write")
        payload = {
            "client": "codex",
            "session_id": "effect-session",
            "call_id": "write-before-pause",
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://resume", "content": "new"},
        }
        event = normalize_hook_event(payload, phase="started", provider="codex")
        session = GuardianSession(self.contract_path)
        self.assertEqual(session.observe(event).action, "allow")
        self.assertEqual(
            session.observe({**event, "phase": "completed", "success": False}).action,
            "allow",
        )
        prior_revision = load_contract(self.contract_path)["revision"]
        prior_epoch = load_contract(self.contract_path)["task_epoch"]
        guardian_module.pause_contract(self.contract_path, "operator pause")
        resume_contract(self.contract_path, "continue same semantic task")

        current = load_contract(self.contract_path)
        self.assertEqual(current["revision"], prior_revision)
        self.assertEqual(current["task_epoch"], prior_epoch)
        terminal = GuardianSession(self.contract_path).summary()
        self.assertEqual(terminal["pending_verifications"], 1)
        self.assertEqual(terminal["effect_unknown"], 1)
        self.assertEqual(terminal["interventions_open"], 1)

    def test_resume_cli_binds_the_current_native_task_lane(self) -> None:
        self.contract()
        contract = load_contract(self.contract_path)
        contract["status"] = "paused"
        contract["runtime"]["pause_scope"] = "lane"
        contract["runtime"]["pause_reason"] = "operator confirmed recovery"
        contract["runtime"]["pause_class"] = "user"
        contract["runtime"]["task_lanes"] = [
            {
                "provider": "codex",
                "session_id": "thread-cli-resume",
                "state": "paused",
                "source": "test",
                "task_epoch": contract["task_epoch"],
                "pause_reason": "operator confirmed recovery",
                "pause_class": "user",
                "pause_requires_revision": False,
                "pause_revision": contract["revision"],
            }
        ]
        write_contract(self.contract_path, contract)
        environment = os.environ.copy()
        environment["CODEX_THREAD_ID"] = "thread-cli-resume"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "resume",
                "continue the exact approved task",
                "--contract",
                str(self.contract_path),
            ],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        resumed = load_contract(self.contract_path)
        self.assertEqual(resumed["status"], "active")
        self.assertEqual(resumed["runtime"]["task_lanes"][0]["state"], "bound")

    def test_unmatched_post_tool_policy_gap_latches_readiness_without_effect_debt(self) -> None:
        self.contract()
        # Post-only gaps remain meaningful for the formal high-risk canary;
        # bounded ordinary file cleanup is intentionally host/Agent-owned.
        delete_target = self.root / "sulde-pre-execution-canary-post-only"
        delete_target.write_text("fixture\n", encoding="utf-8")
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "post-only-thread",
                "call_id": "post-only-destructive",
                "cwd": str(self.root.resolve()),
                "tool_name": "Bash",
                "tool_input": {
                    "command": f"rm -- {shlex.quote(str(delete_target.resolve()))}"
                },
            },
            phase="completed",
            provider="codex",
        )
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.would_action, "deny")
        self.assertEqual(decision.decision_stage, "post_execution_observation")
        current = load_contract(self.contract_path)
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["runtime"]["open_events"], [])
        self.assertEqual(current["runtime"]["pending_verifications"], [])
        self.assertEqual(len(current["runtime"]["pre_execution_gaps"]), 1)
        self.assertEqual(
            current["runtime"]["pre_execution_gaps"][0]["session_id"],
            "post-only-thread",
        )

    def test_matching_session_start_does_not_erase_pre_execution_gap(self) -> None:
        home = Path(self.temp.name) / "kb"
        path = active_contract_path(home, self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        contract = default_contract(
            intent_id="session-gap-reset",
            objective="恢复真实执行前监督",
            rationale="SessionStart 不能证明物化工具拥有执行前边界",
            acceptance_criteria=["其他 session 的缺口保持"],
            workspace=self.root,
            mode="enforce",
            allowed_paths=["resume.md"],
            confirmed_by="human",
        )
        contract["runtime"]["pre_execution_gaps"] = [
            {
                "at": "2026-08-30T09:58:07+00:00",
                "provider": "codex",
                "session_id": session_id,
                "runtime_generation": "fixture",
                "event_id": f"gap-{session_id}",
                "capability": "tool:Bash",
                "effect": "local_write",
                "target": "/private/tmp/sulde-canary",
                "reason_code": "task_scope_denied",
            }
            for session_id in ("restarted-thread", "other-thread")
        ]
        write_contract(path, contract)

        guardian_recovery.decision_request_context(
            home,
            self.root,
            provider="codex",
            session_id="restarted-thread",
        )

        current = load_contract(path)
        self.assertEqual(
            [row["session_id"] for row in current["runtime"]["pre_execution_gaps"]],
            ["restarted-thread", "other-thread"],
        )

    def test_live_negative_canary_proof_clears_only_matching_session_gap(self) -> None:
        contract = self.contract()
        contract["runtime"]["pre_execution_gaps"] = [
            {
                "at": "2026-08-30T09:58:07+00:00",
                "provider": "codex",
                "session_id": session_id,
                "runtime_generation": "fixture",
                "event_id": f"gap-{session_id}",
                "capability": "tool:Bash",
                "effect": "local_write",
                "target": "/private/tmp/sulde-canary",
                "reason_code": "task_scope_denied",
            }
            for session_id in ("proved-thread", "other-thread")
        ]
        write_contract(self.contract_path, contract)
        probe = prepare_pre_execution_probe(
            self.contract_path,
            provider="codex",
            session_id="proved-thread",
        )
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "proved-thread",
                "call_id": "negative-canary",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": probe["command"]},
            },
            phase="started",
            provider="codex",
        )
        event["supervision_status"] = "live_verified"
        event["supervision_mode"] = "enforce"
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "deny")

        proof = finalize_pre_execution_probe(
            self.contract_path,
            provider="codex",
            session_id="proved-thread",
            probe_id=probe["probe_id"],
        )
        self.assertEqual(proof["gaps_cleared"], 1)
        current = load_contract(self.contract_path)
        self.assertEqual(
            [row["session_id"] for row in current["runtime"]["pre_execution_gaps"]],
            ["other-thread"],
        )
        self.assertEqual(
            current["runtime"]["pre_execution_probe"]["status"], "verified"
        )
        self.assertEqual(current["runtime"]["pre_execution_proofs"][-1], proof)
        tampered = json.loads(json.dumps(current))
        tampered["runtime"]["pre_execution_proofs"][-1]["gaps_cleared"] = 99
        with self.assertRaisesRegex(IntentGuardianError, "proof seal is invalid"):
            write_contract(self.contract_path, tampered)

    def test_live_negative_canary_recognizes_codex_unified_exec_wrapper(self) -> None:
        self.contract()
        probe = prepare_pre_execution_probe(
            self.contract_path,
            provider="codex",
            session_id="wrapped-proof-thread",
        )
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "wrapped-proof-thread",
                "cwd": str(self.root),
                "tool_name": "exec",
                "tool_input": (
                    "const result = await tools.exec_command({"
                    f"cmd:{json.dumps(probe['command'])},"
                    f"workdir:{json.dumps(str(self.root))}"
                    "}); text(result.output);"
                ),
                "call_id": "outer-unified-exec",
            },
            phase="started",
            provider="codex",
        )
        event["supervision_status"] = "live_verified"
        event["supervision_mode"] = "enforce"

        decision = GuardianSession(self.contract_path).observe(event)

        self.assertEqual(decision.action, "deny")
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["pre_execution_probe"]["status"], "pre_denied")
        proof = finalize_pre_execution_probe(
            self.contract_path,
            provider="codex",
            session_id="wrapped-proof-thread",
            probe_id=probe["probe_id"],
        )
        self.assertEqual(proof["started_call_id"], "outer-unified-exec")

    def test_pre_execution_v2_requires_both_loaded_and_artifact_generation(self) -> None:
        self.contract()
        for field, replacement in (
            ("loaded_module_generation", "0" * 64),
            ("artifact_generation", "other-artifact:" + "0" * 64),
        ):
            with self.subTest(field=field):
                probe = prepare_pre_execution_probe(
                    self.contract_path,
                    provider="codex",
                    session_id=f"dual-generation-{field}",
                )
                event = normalize_hook_event(
                    {
                        "client": "codex",
                        "session_id": f"dual-generation-{field}",
                        "call_id": f"dual-{field}",
                        "cwd": str(self.root),
                        "tool_name": "Bash",
                        "tool_input": {"command": probe["command"]},
                    },
                    phase="started",
                    provider="codex",
                )
                event["supervision_status"] = "live_verified"
                event["supervision_mode"] = "enforce"
                event[field] = replacement
                GuardianSession(self.contract_path).observe(event)
                current = load_contract(self.contract_path)
                self.assertEqual(
                    current["runtime"]["pre_execution_probe"]["status"],
                    "prepared",
                )
                with self.assertRaisesRegex(
                    IntentGuardianError, "lacks one live exact PreToolUse denial"
                ):
                    finalize_pre_execution_probe(
                        self.contract_path,
                        provider="codex",
                        session_id=f"dual-generation-{field}",
                        probe_id=probe["probe_id"],
                    )
                Path(probe["target"]).unlink(missing_ok=True)
                current["runtime"]["pre_execution_probe"] = {}
                write_contract(self.contract_path, current)

    def test_pre_execution_v1_probe_remains_loadable_without_upgrade_authority(self) -> None:
        contract = self.contract()
        probe = prepare_pre_execution_probe(
            self.contract_path,
            provider="codex",
            session_id="legacy-preexecution",
        )
        legacy = dict(probe)
        legacy["schema"] = "sulde-pre-execution-probe-v1"
        legacy.pop("loaded_module_generation")
        legacy.pop("artifact_generation")
        contract = load_contract(self.contract_path)
        contract["runtime"]["pre_execution_probe"] = legacy
        write_contract(self.contract_path, contract)

        loaded = load_contract(self.contract_path)
        self.assertEqual(
            loaded["runtime"]["pre_execution_probe"]["schema"],
            "sulde-pre-execution-probe-v1",
        )
        with self.assertRaisesRegex(IntentGuardianError, "lane or generation changed"):
            finalize_pre_execution_probe(
                self.contract_path,
                provider="codex",
                session_id="legacy-preexecution",
                probe_id=probe["probe_id"],
            )
        Path(probe["target"]).unlink(missing_ok=True)

    def test_post_only_canary_cannot_be_finalized_even_after_marker_cleanup(self) -> None:
        self.contract()
        probe = prepare_pre_execution_probe(
            self.contract_path,
            provider="codex",
            session_id="post-only-thread",
        )
        Path(probe["target"]).unlink()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "post-only-thread",
                "call_id": "post-only-canary",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": probe["command"]},
            },
            phase="completed",
            provider="codex",
        )
        GuardianSession(self.contract_path).observe(event)
        self.assertFalse(os.path.lexists(probe["target"]))
        with self.assertRaisesRegex(
            IntentGuardianError, "lacks one live exact PreToolUse denial"
        ):
            finalize_pre_execution_probe(
                self.contract_path,
                provider="codex",
                session_id="post-only-thread",
                probe_id=probe["probe_id"],
            )
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["pre_execution_probe"][
                "status"
            ],
            "executed",
        )

    def test_proven_read_only_use_figma_never_enters_effect_ledger(self) -> None:
        self.contract()
        payload = {
            "client": "codex",
            "session_id": "figma-read-session",
            "call_id": "figma-read-call",
            "cwd": str(self.root),
            "tool_name": "mcp__codex_apps__figma__use_figma",
            "tool_input": {
                "fileKey": "0G32qTbFLqMfW5gG8wvv8X",
                "description": "Inspect the existing pages and fonts",
                "skillNames": "figma-use",
                "code": (
                    "const pages=figma.root.children.map(p=>"
                    "({id:p.id,name:p.name,childCount:p.children.length}));"
                    "const fonts=await figma.listAvailableFontsAsync();"
                    "return {editorType:figma.editorType,pages,fonts:fonts.slice(0,80)};"
                ),
            },
        }
        for phase in ("started", "completed"):
            event = normalize_hook_event(payload, phase=phase, provider="codex")
            self.assertEqual(event["effect"], "read")
            decision = GuardianSession(self.contract_path).observe(event)
            self.assertEqual(decision.action, "allow")

        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(projection["attempts"], {})
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["pending_verifications"], [])

    def test_live_readable_intervention_choice_resolves_without_external_cli(self) -> None:
        home = Path(self.temp.name) / "kb"
        path = active_contract_path(home, self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        contract = default_contract(
            intent_id="external-effect-recovery",
            objective="完成一次可验证的外部更新",
            rationale="失败时保持 unknown 并转人工裁决",
            acceptance_criteria=["结果被独立证明或明确标为失败"],
            workspace=self.root,
            mode="enforce",
            allowed_paths=["."],
            confirmed_by="human",
        )
        write_contract(path, contract)
        write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "original-thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(path).observe(write)
        self.assertEqual(denied.action, "deny")
        self.declare_effects(path, "external_write")
        session = GuardianSession(path)
        session.observe(write)
        session.observe(dict(write, phase="completed", success=False))
        before = load_contract(path)
        intervention_id = next(
            iter(load_intervention_projection(path)["interventions"])
        )

        payload = {
            "client": "codex",
            "session_id": "restored-thread",
            "cwd": str(self.root),
            "prompt": "继续处理当前任务",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            card = observe_user_prompt(payload, provider="codex")
            self.assertIn("当前外部效果干预确认卡", card)
            self.assertIn("事实证据可用自然语言说明", card)
            self.assertNotIn("确认外部操作失败：<", card)
            payload["prompt"] = "确认外部操作失败：远端记录不存在"
            resolved_context = observe_user_prompt(payload, provider="codex")

        after = load_contract(path)
        intervention = load_intervention_projection(path)["interventions"][
            intervention_id
        ]
        receipt = next(
            row
            for row in after["runtime"]["approval_receipts"]
            if row["action"] == "intervention-resolve"
        )
        self.assertIn(
            f"CONTROL_RECORDED action=intervention-resolve target={intervention_id}",
            resolved_context,
        )
        self.assertEqual(intervention["status"], "resolved")
        self.assertEqual(intervention["decision"], "confirmed_failed")
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        self.assertEqual(receipt["decision"], "confirmed_failed")
        self.assertTrue(receipt["evidence_sha256"])
        self.assertEqual(receipt["consumed_by"], "guardian-control-executor")
        self.assertTrue(receipt["consumed_at"])

    def test_effect_intervention_precedes_pending_revision_proposal(self) -> None:
        home = Path(self.temp.name) / "kb"
        path = active_contract_path(home, self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        contract = default_contract(
            intent_id="intervention-before-proposal",
            objective="完成一次可验证的外部更新",
            rationale="先裁决外部事实，再审阅后续方案",
            acceptance_criteria=["外部结果有明确证据"],
            workspace=self.root,
            mode="enforce",
            allowed_paths=["."],
            confirmed_by="human",
        )
        write_contract(path, contract)
        write = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "original-thread",
                "tool_name": "mcp__docs__update_document",
                "tool_input": {"uri": "doc://resume", "content": "new"},
            },
            phase="started",
            provider="codex",
        )
        denied = GuardianSession(path).observe(write)
        self.assertEqual(denied.action, "deny")
        self.declare_effects(path, "external_write")
        session = GuardianSession(path)
        session.observe(write)
        session.observe(dict(write, phase="completed", success=False))
        _proposal, digest = create_revision_proposal(
            path,
            objective="修复外部写入后的恢复流程",
            acceptance_criteria=["外部事实已先完成裁决"],
            mode="enforce",
            allowed_paths=["."],
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore previous files",
        )

        payload = {
            "client": "codex",
            "session_id": "restored-thread",
            "cwd": str(self.root),
            "prompt": "继续处理当前任务",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            first_card = observe_user_prompt(payload, provider="codex")
            self.assertIn("当前外部效果干预确认卡", first_card)
            self.assertNotIn("当前方案确认卡", first_card)
            payload["prompt"] = "确认外部操作失败：远端对象不存在"
            observe_user_prompt(payload, provider="codex")
            payload["prompt"] = "继续处理当前任务"
            proposal_card = observe_user_prompt(payload, provider="codex")

        self.assertIn("当前方案确认卡", proposal_card)
        self.assertEqual(
            load_contract(path)["runtime"]["pending_proposal_digest"],
            digest,
        )

    def test_codex_multi_file_event_is_checked_one_path_at_a_time(self) -> None:
        self.contract()
        events = normalize_provider_events(
            {
                "type": "item.completed",
                "item": {
                    "id": "change-1",
                    "type": "file_change",
                    "status": "completed",
                    "changes": [{"path": "resume.md"}, {"path": "other.md"}],
                },
            },
            provider="codex",
        )
        self.assertEqual([event["target"] for event in events], ["resume.md", "other.md"])
        decisions = [evaluate_event(load_contract(self.contract_path), event) for event in events]
        self.assertEqual([decision.action for decision in decisions], ["allow", "allow"])

    def test_shadow_mode_allows_local_findings_but_never_external_or_destructive(self) -> None:
        contract = self.contract(mode="shadow")
        local = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": "other.md"}},
            phase="started",
        )
        local_decision = evaluate_event(contract, local)
        self.assertEqual(local_decision.action, "allow")
        self.assertEqual(local_decision.would_action, "allow")
        destructive = normalize_hook_event(
            {"tool_name": "Bash", "tool_input": {"command": "drop table users"}},
            phase="started",
        )
        self.assertEqual(evaluate_event(contract, destructive).action, "deny")

    def test_ordinary_local_write_outside_hint_is_agent_owned(self) -> None:
        self.contract()
        session = GuardianSession(self.contract_path)
        event = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": "other.md"}},
            phase="started",
        )
        decision = session.observe(event)
        self.assertEqual(decision.action, "allow")
        self.assertEqual(decision.dispatch, "allow")
        self.assertEqual(decision.lifecycle, "continue")
        self.assertEqual(decision.authority, "none")
        self.assertEqual(decision.verification, "none")
        self.assertEqual(decision.evidence_state, "observed")
        self.assertEqual(load_contract(self.contract_path)["status"], "active")

    def test_task_worktree_uses_checkout_relative_path_policy(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = ["hooks/**", "scripts/kb/**"]
        task = self.root / ".worktrees" / "guardian-v3"
        allowed = task / "hooks" / "pre_tool_use.py"
        ordinary = task / "docs" / "unplanned.md"
        contract["constraints"]["frozen_paths"] = ["scripts/kb/frozen.py"]

        allowed_event = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": str(allowed)}},
            phase="started",
        )
        ordinary_event = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": str(ordinary)}},
            phase="started",
        )
        frozen_event = normalize_hook_event(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(task / "scripts/kb/frozen.py")},
            },
            phase="started",
        )

        self.assertEqual(evaluate_event(contract, allowed_event).action, "allow")
        self.assertEqual(evaluate_event(contract, ordinary_event).action, "allow")
        self.assertEqual(evaluate_event(contract, frozen_event).action, "deny")

    def test_sibling_workspace_write_is_agent_owned_without_an_allowlist(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = []
        write_contract(self.contract_path, contract)
        event = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": str(self.root.parent / "escape.txt")}},
            phase="started",
        )
        self.assertEqual(evaluate_event(load_contract(self.contract_path), event).action, "allow")

    def test_agent_cannot_write_guardian_control_artifacts(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = []
        write_contract(self.contract_path, contract)
        for target in (".git/config", ".codex-agent/task.status", ".codex-agent/task.intent.json"):
            event = normalize_hook_event(
                {"tool_name": "Write", "tool_input": {"file_path": target}},
                phase="started",
            )
            self.assertEqual(evaluate_event(load_contract(self.contract_path), event).action, "deny")

    @unittest.skip("retired: Git execution no longer uses Guardian path policy")
    def test_repository_scope_does_not_broaden_nonliteral_git_add(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = [str(self.root)]
        write_contract(self.contract_path, contract)
        for command in ("git add -A", "git add -u", "git add resume.md"):
            event = normalize_hook_event(
                {"tool_name": "Bash", "tool_input": {"command": command}},
                phase="started",
                provider="codex",
            )
            self.assertEqual(event["effect"], "local_write", command)
            self.assertEqual(event["target"], ".git", command)
            self.assertEqual(evaluate_event(load_contract(self.contract_path), event).action, "deny", command)

    @unittest.skip("retired: Git execution no longer uses Guardian path policy")
    def test_repository_scope_still_allows_narrow_commit_and_merge_metadata(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = [str(self.root)]
        write_contract(self.contract_path, contract)
        for command in (
            "git commit -m 'verified change'",
            "git merge --no-edit origin/main",
        ):
            event = normalize_hook_event(
                {"tool_name": "Bash", "tool_input": {"command": command}},
                phase="started",
                provider="codex",
            )
            self.assertEqual(event["effect"], "local_write", command)
            self.assertEqual(event["target"], ".", command)
            self.assertEqual(
                evaluate_event(load_contract(self.contract_path), event).action,
                "allow",
                command,
            )

    @unittest.skip("retired: Git execution no longer uses per-file Guardian grants")
    def test_literal_git_add_is_authorized_one_regular_file_at_a_time(self) -> None:
        (self.root / "resume.md").write_text("resume\n", encoding="utf-8")
        (self.root / "other.md").write_text("other\n", encoding="utf-8")
        contract = self.contract()
        exact = normalize_hook_event(
            {
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "git add -- resume.md"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(exact["effect"], "local_write")
        self.assertEqual(exact["target"], "resume.md")
        self.assertEqual(exact["write_targets"], ["resume.md"])
        self.assertEqual(evaluate_event(contract, exact).action, "allow")

        extra = normalize_hook_event(
            {
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "git add -- resume.md other.md"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(extra["write_targets"], ["resume.md", "other.md"])
        self.assertEqual(evaluate_event(contract, extra).action, "deny")

    def test_digest_pinned_git_lifecycle_uses_declared_content_targets(self) -> None:
        task = self.root / ".worktrees" / "task-one"
        task.mkdir(parents=True)
        expected = task / "scripts" / "one.py"
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = [str(expected)]
        write_contract(self.contract_path, contract)
        command = (
            f"{sys.executable} /installed/agent-runtime.py commit {task} "
            f"--expected-head {'a' * 40} --message verified --path scripts/one.py"
        )
        classified = {
            "effect": "local_write",
            "profile_id": "sulde-agent-runtime-git-lifecycle-v1",
            "targets": [str(expected)],
        }
        with mock.patch.object(
            guardian_resources,
            "_trusted_script_command",
            return_value=classified,
        ):
            event = normalize_hook_event(
                {
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                },
                phase="started",
                provider="codex",
            )
        self.assertEqual(event["effect"], "local_write")
        self.assertEqual(event["write_targets"], [str(expected)])
        self.assertEqual(
            evaluate_event(load_contract(self.contract_path), event).action,
            "allow",
        )

    @unittest.skip("retired: Git execution no longer uses Guardian resource adapters")
    def test_git_dash_c_attributes_exact_linked_worktree_and_fails_closed(self) -> None:
        linked = self.root / ".worktrees" / "t32"
        linked.mkdir(parents=True)
        admin = self.root / ".git" / "worktrees" / "t32"
        admin.mkdir(parents=True)
        marker = linked / ".git"
        marker.write_text(f"gitdir: {admin}\n", encoding="utf-8")
        (admin / "gitdir").write_text(str(marker), encoding="utf-8")
        source = linked / "resume.md"
        source.write_text("resume\n", encoding="utf-8")
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = [
            str(linked),
            str(source),
        ]
        write_contract(self.contract_path, contract)
        quoted = shlex.quote(str(linked))

        add_event = normalize_hook_event(
            {
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": f"git -C {quoted} add -- resume.md"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(add_event["effect"], "local_write")
        self.assertEqual(add_event["write_targets"], [str(source.resolve())])
        self.assertEqual(add_event["resource_base"], str(linked.resolve()))
        self.assertEqual(evaluate_event(load_contract(self.contract_path), add_event).action, "allow")

        for command in (
            f"git -C {quoted} commit -m 'verified change'",
            f"git -C {quoted} merge --no-edit origin/main",
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {
                        "cwd": str(self.root),
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "local_write")
                self.assertEqual(event["write_targets"], [str(linked.resolve())])
                self.assertEqual(event["resource_base"], str(linked.resolve()))
                self.assertEqual(
                    evaluate_event(load_contract(self.contract_path), event).action,
                    "allow",
                )

        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / ".git").mkdir()
        (outside / "resume.md").write_text("outside\n", encoding="utf-8")
        alias = self.root / ".worktrees" / "alias"
        try:
            alias.symlink_to(linked, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink fixture unavailable: {error}")
        unsafe = (
            f"git -C {quoted} add -A",
            f"git -c core.hooksPath=/tmp -C {quoted} add -- resume.md",
            (
                f"git --git-dir={shlex.quote(str(admin))} "
                f"--work-tree={quoted} add -- resume.md"
            ),
            f"git -C {quoted} add -- ../resume.md",
            f"git -C {shlex.quote(str(alias))} add -- resume.md",
            f"git -C {shlex.quote(str(outside))} add -- resume.md",
            f"git -C {quoted} commit --amend -m rewritten",
            f"git -C {quoted} merge --strategy custom feature",
        )
        for command in unsafe:
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {
                        "cwd": str(self.root),
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertIn(".git", event["write_targets"][0])
                self.assertEqual(
                    evaluate_event(load_contract(self.contract_path), event).action,
                    "deny",
                )

    def test_digest_pinned_plugin_scripts_use_declared_effect_and_exact_target(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = [str(self.root)]
        write_contract(self.contract_path, contract)
        codex_home = Path(self.temp.name) / "codex-home"
        validate_script = (
            codex_home / "skills/.system/plugin-creator/scripts/validate_plugin.py"
        )
        cachebuster_script = (
            codex_home
            / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        )
        for script in (validate_script, cachebuster_script):
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(f"# fixture for {script.name}\n", encoding="utf-8")
        plugin = self.root / "plugin"
        manifest = plugin / ".codex-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"version":"0.1.0"}\n', encoding="utf-8")
        local_home = Path(self.temp.name) / "kb-home"
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_HOME": str(codex_home),
                "SULDE_KB_HOME": str(local_home),
            }
        )
        launcher_contract.install_launchers(
            local_home,
            self.clean_launcher_source(),
            environment=environment,
        )

        with mock.patch.dict(os.environ, environment, clear=True):
            validate_command = shlex.join(
                [sys.executable, str(validate_script), str(plugin)]
            )
            validate_event = normalize_hook_event(
                {
                    "client": "codex",
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {"command": validate_command},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(validate_event["effect"], "read")
            self.assertEqual(
                evaluate_event(load_contract(self.contract_path), validate_event).action,
                "allow",
            )

            cachebuster_command = shlex.join(
                [
                    sys.executable,
                    str(cachebuster_script),
                    str(plugin),
                    "--cachebuster",
                    "verified-1",
                ]
            )
            cachebuster_event = normalize_hook_event(
                {
                    "client": "codex",
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {"command": cachebuster_command},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(cachebuster_event["effect"], "local_write")
            self.assertEqual(cachebuster_event["target"], str(manifest.resolve()))
            self.assertEqual(
                evaluate_event(load_contract(self.contract_path), cachebuster_event).action,
                "allow",
            )

    def test_unsealed_official_cachebuster_is_denied_without_pausing_lane(self) -> None:
        contract = self.contract()
        plugin = self.root / "integrations/codex/plugins/sulde"
        manifest = plugin / ".codex-plugin/plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"name":"sulde","version":"0.1.0"}\n', encoding="utf-8")
        contract["constraints"]["allowed_paths"] = [
            "integrations/codex/plugins/sulde/.codex-plugin/plugin.json"
        ]
        write_contract(self.contract_path, contract)
        helper = (
            self.codex_home
            / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        )
        command = shlex.join([sys.executable, str(helper), str(plugin)])

        with mock.patch.dict(
            os.environ,
            {**os.environ, "CODEX_HOME": str(self.codex_home)},
            clear=True,
        ):
            event = normalize_hook_event(
                {
                    "client": "codex",
                    "cwd": str(self.root),
                    "session_id": "cachebuster-session",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                },
                phase="started",
                provider="codex",
            )

        self.assertEqual(event["effect"], "local_write")
        self.assertEqual(event["write_targets"], [str(manifest.resolve())])
        self.assertIn("invocation_violation", event)
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "deny")
        self.assertFalse(decision.pause)
        persisted = load_contract(self.contract_path)
        self.assertEqual(persisted["status"], "active")
        self.assertEqual(persisted["runtime"]["open_events"], [])
        self.assertEqual(persisted["runtime"]["pending_verifications"], [])

        destructive = normalize_hook_event(
            {
                "client": "codex",
                "cwd": str(self.root),
                "session_id": "cachebuster-session",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf exact-target"},
            },
            phase="started",
            provider="codex",
        )
        destructive_decision = evaluate_event(persisted, destructive)
        self.assertEqual(destructive_decision.action, "deny")
        self.assertFalse(destructive_decision.pause)

    def test_verified_candidate_promotion_is_exact_external_install_effect(self) -> None:
        workspace = Path(self.temp.name) / "candidate-workspace"
        script = workspace / "scripts/release/candidate_codex_plugin.py"
        script.parent.mkdir(parents=True)
        script.write_text("# candidate fixture\n", encoding="utf-8")
        candidate_home = Path(self.temp.name) / "candidates"
        slot = candidate_home / "candidate-one"
        artifact = slot / "artifact"
        generation_path = artifact / "plugins/sulde/.codex-plugin/generation.json"
        generation_path.parent.mkdir(parents=True)
        generation = "0.2.5+candidate:" + "e" * 64
        generation_path.write_text(
            json.dumps(
                {"generation": generation, "plugin_version": "0.2.5+candidate"}
            ),
            encoding="utf-8",
        )
        interpreter = Path(sys.executable).resolve()
        binding = {
            "artifact_root": str(Path(self.temp.name) / "production-artifact"),
            "codex_path": "/opt/codex",
            "codex_sha256": "c" * 64,
            "codex_home": str(self.codex_home),
            "interpreter_path": str(interpreter),
            "interpreter_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(),
            "kb_home": str((Path(self.temp.name) / "live-kb").resolve()),
            "platform": "posix",
            "plugin_version": "0.2.5+candidate",
            "script_path": str(workspace / "scripts/release/install_codex_plugin.py"),
            "script_sha256": "d" * 64,
            "tracked_tree_sha256": "e" * 64,
            "workspace_root": str(workspace),
            "python_env": "PYTHONDONTWRITEBYTECODE=1",
            "python_flag": "-B",
        }
        receipt = {
            "schema": "sulde-codex-candidate-verification-v1",
            "status": "verified",
            "candidate_id": slot.name,
            "python": {
                "executable": str(interpreter),
                "executable_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(),
            },
            "source": {"commit": "a" * 40, "tree": "b" * 40},
            "artifact": {
                "path": str(artifact),
                "generation": generation,
                "plugin_version": "0.2.5+candidate",
            },
            "codex": {"executable": "/opt/codex"},
        }

        def seal(value: dict, field: str) -> dict:
            selected = dict(value)
            selected[field] = hashlib.sha256(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return selected

        receipt = seal(receipt, "receipt_sha256")
        state = seal(
            {
                "schema": "sulde-codex-candidate-state-v1",
                "status": "verified",
                "candidate_id": slot.name,
                "receipt_sha256": receipt["receipt_sha256"],
            },
            "state_sha256",
        )
        (slot / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (slot / "verification-receipt.json").write_text(
            json.dumps(receipt), encoding="utf-8"
        )
        command = shlex.join(
            [
                str(interpreter), "-B", str(script), "--candidate-home", str(candidate_home),
                "--json", "promote", slot.name, "--kb-home", binding["kb_home"],
            ]
        )
        legacy_command = shlex.join(
            [
                str(interpreter), str(script), "--candidate-home", str(candidate_home),
                "--json", "promote", slot.name, "--kb-home", binding["kb_home"],
            ]
        )
        legacy_binding = {
            key: value
            for key, value in binding.items()
            if key not in {"python_env", "python_flag"}
        }
        git_values = {("rev-parse", "HEAD"): "a" * 40,
                      ("rev-parse", "HEAD^{tree}"): "b" * 40}
        with (
            mock.patch.object(
                guardian_resource_preflight,
                "_codex_plugin_install_v2_binding",
                return_value=binding,
            ),
            mock.patch.object(
                guardian_resource_preflight,
                "_codex_plugin_install_binding",
                return_value=legacy_binding,
            ),
            mock.patch.object(
                guardian_resource_preflight,
                "_candidate_git_output",
                side_effect=lambda _root, *args: git_values[args],
            ),
        ):
            candidate = guardian_resources._codex_candidate_promotion_candidate(
                command, cwd=workspace
            )
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate["effect"], "external_write")
            self.assertEqual(candidate["profile_id"], "codex-plugin-install-v2")
            self.assertEqual(candidate["binding"]["python_flag"], "-B")
            self.assertEqual(candidate["dispatch_adapter"], "candidate-promotion-v1")
            legacy_candidate = guardian_resources._codex_candidate_promotion_candidate(
                legacy_command, cwd=workspace
            )
            self.assertEqual(
                legacy_candidate["profile_id"], "codex-plugin-install-v1"
            )
            self.assertIsNone(
                guardian_resources._codex_candidate_promotion_candidate(
                    command.replace(" promote ", " verify "), cwd=workspace
                )
            )
            event = normalize_hook_event(
                {
                    "client": "codex",
                    "cwd": str(workspace),
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                },
                phase="started",
                provider="codex",
            )
        decision = evaluate_event(self.contract(), event)
        self.assertEqual(event["effect"], "external_write")
        self.assertEqual(decision.action, "deny")
        self.assertEqual(decision.reason_code, "external_effect_not_authorized")

    def test_unsealed_candidate_promotion_fails_closed_with_misaligned_hook_cwd(self) -> None:
        self.contract()
        hook_cwd = Path(self.temp.name) / "session-root"
        hook_cwd.mkdir()
        command = shlex.join(
            [
                sys.executable,
                "scripts/release/candidate_codex_plugin.py",
                "--candidate-home",
                str(Path(self.temp.name) / "candidates"),
                "--json",
                "promote",
                "candidate-one",
                "--kb-home",
                str(Path(self.temp.name) / "kb"),
            ]
        )

        event = normalize_hook_event(
            {
                "client": "codex",
                "cwd": str(hook_cwd),
                "session_id": "candidate-promotion-session",
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(event["effect"], "external_write")
        self.assertTrue(event["formal_maintenance"])
        self.assertEqual(event["target"], "[host-local:codex-plugin]")
        self.assertIn("invocation_violation", event)
        self.assertEqual(
            evaluate_event(load_contract(self.contract_path), event).action,
            "deny",
        )
        for subcommand in ("prepare", "verify", "show"):
            with self.subTest(subcommand=subcommand):
                nonpromotion = command.replace(" promote ", f" {subcommand} ")
                candidate = normalize_hook_event(
                    {
                        "client": "codex",
                        "cwd": str(hook_cwd),
                        "tool_name": "Bash",
                        "tool_input": {"command": nonpromotion},
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertFalse(candidate.get("formal_maintenance", False))
                self.assertNotIn("invocation_violation", candidate)

    def test_trusted_script_drift_chaining_and_invalid_argv_remain_unknown(self) -> None:
        self.contract()
        codex_home = Path(self.temp.name) / "codex-home"
        validate_script = (
            codex_home / "skills/.system/plugin-creator/scripts/validate_plugin.py"
        )
        cachebuster_script = (
            codex_home
            / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        )
        for script in (validate_script, cachebuster_script):
            script.parent.mkdir(parents=True, exist_ok=True)
            script.write_text(f"# fixture for {script.name}\n", encoding="utf-8")
        plugin = self.root / "plugin"
        manifest = plugin / ".codex-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"version":"0.1.0"}\n', encoding="utf-8")
        duplicate = self.root / "other" / validate_script.name
        duplicate.parent.mkdir()
        duplicate.write_bytes(validate_script.read_bytes())
        local_home = Path(self.temp.name) / "kb-home"
        environment = os.environ.copy()
        environment.update(
            {
                "CODEX_HOME": str(codex_home),
                "SULDE_KB_HOME": str(local_home),
            }
        )
        launcher_contract.install_launchers(
            local_home,
            self.clean_launcher_source(),
            environment=environment,
        )

        with mock.patch.dict(os.environ, environment, clear=True):
            untrusted_commands = (
                shlex.join([sys.executable, str(duplicate), str(plugin)]),
                shlex.join(
                    [sys.executable, str(validate_script), str(plugin), "--extra"]
                ),
                shlex.join(
                    [
                        sys.executable,
                        str(cachebuster_script),
                        str(plugin),
                        "--cachebuster",
                        "bad/value",
                    ]
                ),
            )
            for index, command in enumerate(untrusted_commands):
                event = normalize_hook_event(
                    {
                        "client": "codex",
                        "cwd": str(self.root),
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "destructive", command)
                decision = evaluate_event(load_contract(self.contract_path), event)
                self.assertEqual(decision.action, "deny", command)
                self.assertEqual(decision.pause, index == 0, command)
                if index:
                    self.assertEqual(
                        event["invocation_violation"]["kind"],
                        "declared-script-integrity",
                    )
                    self.assertTrue(
                        event["invocation_violation"][
                            "bounded_pre_execution_denial"
                        ]
                    )
                self.assertFalse(decision.awaiting_human, command)

            composed_local_write = (
                shlex.join([sys.executable, str(validate_script), str(plugin)])
                + f" ; touch {shlex.quote(str(self.root / 'drift'))}"
            )
            composed_event = normalize_hook_event(
                {
                    "client": "codex",
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {"command": composed_local_write},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(composed_event["effect"], "unknown")
            self.assertEqual(
                composed_event["invocation_violation"]["kind"],
                "invalid-composition",
            )
            composed_decision = evaluate_event(
                load_contract(self.contract_path), composed_event
            )
            self.assertEqual(composed_decision.action, "deny")
            self.assertFalse(composed_decision.pause)
            self.assertFalse(composed_decision.awaiting_human)

            validate_script.write_text("# changed after install\n", encoding="utf-8")
            changed = normalize_hook_event(
                {
                    "client": "codex",
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": shlex.join(
                            [sys.executable, str(validate_script), str(plugin)]
                        )
                    },
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(changed["effect"], "destructive")
            self.assertEqual(
                changed["invocation_violation"]["kind"],
                "declared-script-integrity",
            )
            changed_decision = GuardianSession(self.contract_path).observe(changed)
            self.assertEqual(changed_decision.action, "deny")
            self.assertFalse(changed_decision.pause)
            self.assertEqual(load_contract(self.contract_path)["status"], "active")

    @unittest.skip("retired: direct Git metadata writes are outside Guardian policy")
    def test_child_scope_cannot_authorize_repository_git_metadata(self) -> None:
        contract = self.contract()
        expected_targets = {
            "git add resume.md": ".git",
            "git commit -m 'change'": ".",
            "git merge --no-edit origin/main": ".",
        }
        for command, expected_target in expected_targets.items():
            event = normalize_hook_event(
                {"tool_name": "Bash", "tool_input": {"command": command}},
                phase="started",
                provider="codex",
            )
            self.assertEqual(event["target"], expected_target, command)
            self.assertEqual(evaluate_event(contract, event).action, "deny", command)

    @unittest.skip("retired: Git pathspecs are decided by Agent, human and host")
    def test_literal_git_add_rejects_directories_symlinks_and_special_pathspecs(self) -> None:
        (self.root / "resume.md").write_text("resume\n", encoding="utf-8")
        directory = self.root / "notes"
        directory.mkdir()
        (directory / "inside.md").write_text("inside\n", encoding="utf-8")
        symlink = self.root / "resume-link.md"
        try:
            symlink.symlink_to(self.root / "resume.md")
        except OSError as error:
            self.skipTest(f"symlink fixture unavailable: {error}")
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = [str(self.root)]
        write_contract(self.contract_path, contract)
        for command in (
            "git add -- notes",
            "git add -- resume-link.md",
            "git add -- '*.md'",
            "git add -- ':(glob)*.md'",
            "git add -- .git/config",
        ):
            event = normalize_hook_event(
                {
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(event["target"], ".git", command)
            self.assertEqual(
                evaluate_event(load_contract(self.contract_path), event).action,
                "deny",
                command,
            )

    @unittest.skip("retired: Git operation semantics are outside Guardian policy")
    def test_git_metadata_exception_excludes_compound_rewrite_and_unsafe_merge(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = [str(self.root)]
        write_contract(self.contract_path, contract)
        for command in (
            "git commit --amend -m rewritten",
            "git add -A && touch resume.md",
            "git merge --strategy custom feature",
            "git merge --abort",
            "git reset --hard HEAD~1",
            "git push --force origin main",
        ):
            event = normalize_hook_event(
                {"tool_name": "Bash", "tool_input": {"command": command}},
                phase="started",
                provider="codex",
            )
            self.assertEqual(evaluate_event(load_contract(self.contract_path), event).action, "deny", command)

    def test_absolute_target_cannot_bypass_relative_frozen_path(self) -> None:
        contract = self.contract()
        contract["constraints"]["frozen_paths"] = ["resume.md"]
        write_contract(self.contract_path, contract)
        event = normalize_hook_event(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.root / "resume.md")},
            },
            phase="started",
        )
        decision = evaluate_event(load_contract(self.contract_path), event)
        self.assertEqual(decision.action, "deny")
        self.assertIn("冻结", decision.reason)

    def test_shell_redirection_is_checked_against_real_write_target(self) -> None:
        contract = self.contract()
        allowed = normalize_hook_event(
            {"tool_name": "Bash", "tool_input": {"command": "printf '%s' ok > resume.md"}},
            phase="started",
        )
        denied = normalize_hook_event(
            {"tool_name": "Bash", "tool_input": {"command": "printf '%s' bad > other.md"}},
            phase="started",
        )
        self.assertEqual(allowed["target"], "resume.md")
        self.assertEqual(allowed["effect"], "local_write")
        self.assertEqual(evaluate_event(contract, allowed).action, "allow")
        self.assertEqual(evaluate_event(contract, denied).action, "allow")

    def test_command_audit_target_never_persists_raw_secret_bearing_command(self) -> None:
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "curl -X POST -H 'Authorization: Bearer sensitive-value' https://example.test"},
            },
            phase="started",
        )
        self.assertEqual(event["effect"], "external_write")
        self.assertTrue(event["target"].startswith("[command:"))
        self.assertNotIn("sensitive-value", json.dumps(event))

    def test_git_remote_credentials_are_hashed_out_of_the_event(self) -> None:
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "git push https://user:sensitive-value@example.test/repo.git main"
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        serialized = json.dumps(event)
        self.assertEqual(event["supervision_domain"], "execution_passthrough")
        self.assertEqual(event["effect"], "unknown")
        self.assertNotIn("sensitive-value", serialized)
        self.assertNotIn("example.test", serialized)

    def test_read_search_that_mentions_guardian_file_is_not_a_control_command(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "rg -n \"cannot change|open events\" "
                        "scripts/kb/intent-guardian.py hooks tests"
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(event["effect"], "read")
        self.assertNotIn("control_plane", event)
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "allow")
        self.assertEqual(load_contract(self.contract_path)["status"], "active")

    def test_read_search_argument_cannot_upgrade_to_external_effect(self) -> None:
        for command in (
            'rg -n "git push|gh pr create" scripts tests',
            'grep -n "curl -X POST" README.md',
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "read")

    def test_f06_002_remote_write_phrases_as_interpreter_data_do_not_upgrade(self) -> None:
        commands = {
            "python-json-heredoc": (
                "python3 - <<'PY'\n"
                "payload = {'command': 'git push origin main', "
                "'request': 'curl -X POST https://example.invalid'}\n"
                "print(payload)\n"
                "PY\n"
            ),
            "python-literal-eval": (
                "python3 -c \"payload = {'cmd': 'gh pr create'}; print(payload)\""
            ),
            "node-json-heredoc": (
                "node <<'JS'\n"
                "const fixture = {'command': 'git push origin main'};\n"
                "console.log(fixture);\n"
                "JS\n"
            ),
            "shell-data-heredoc": "cat <<'EOF'\ngit push origin main\nEOF\n",
        }
        for label, command in commands.items():
            with self.subTest(label=label):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "read", command)

        fixture_write = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "python3 -c \"from pathlib import Path; "
                        "Path('case.json').write_text('git push origin main')\""
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(fixture_write["effect"], "local_write")

    def test_f06_002_nested_git_is_not_reclassified_as_an_external_effect(self) -> None:
        commands = {
            "shell-wrapper": "/bin/sh -c 'git push origin main'",
            "python-system": (
                "python3 - <<'PY'\n"
                "import os\n"
                "os.system('git push origin main')\n"
                "PY\n"
            ),
            "python-aliased-subprocess": (
                "python3 -c \"import subprocess as sp; "
                "sp.run(['git', 'push', 'origin', 'main'])\""
            ),
            "node-child-process": (
                "node <<'JS'\n"
                "const {execSync} = require('child_process');\n"
                "execSync('git push origin main');\n"
                "JS\n"
            ),
            "shell-source-heredoc": (
                "/bin/sh <<'SH'\n"
                "git push origin main\n"
                "SH\n"
            ),
            "unquoted-heredoc-expansion": (
                'python3 - <<PY\nprint("$(git push origin main)")\nPY\n'
            ),
        }
        for label, command in commands.items():
            with self.subTest(label=label):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "unknown", command)
                self.assertEqual(event["uncertainty_kind"], "opaque_execution")

    def test_f06_002_unproved_interpreter_calls_never_default_to_read(self) -> None:
        cases = {
            "requests-post": (
                "python3 -c \"import requests; "
                "requests.post('https://example.invalid', data='x')\"",
                "unknown",
            ),
            "urllib-post": (
                "python3 -c \"import urllib.request; "
                "urllib.request.urlopen('https://example.invalid', data=b'x')\"",
                "unknown",
            ),
            "path-touch": (
                "python3 -c \"from pathlib import Path; "
                "Path('/tmp/x').touch()\"",
                "local_write",
            ),
            "os-chmod": (
                "python3 -c \"import os; os.chmod('/tmp/x', 0o600)\"",
                "unknown",
            ),
            "shutil-copy": (
                "python3 -c \"import shutil; shutil.copy('a', 'b')\"",
                "unknown",
            ),
            "dynamic-open-mode": (
                "python3 -c \"m='w'; open('/tmp/x', m).write('x')\"",
                "unknown",
            ),
            "node-fetch-post": (
                "node -e \"fetch('https://example.invalid',{method:'POST'})\"",
                "unknown",
            ),
        }
        for label, (command, expected) in cases.items():
            with self.subTest(label=label):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], expected, command)
                self.assertNotEqual(event["effect"], "read", command)

    def test_f06_002_rename_and_replace_are_destructive_second_stage_actions(self) -> None:
        for command in (
            "python3 -c \"import os; os.rename('before', 'after')\"",
            "python3 -c \"from pathlib import Path; "
            "Path('before').replace('after')\"",
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "destructive", command)

    def test_known_repository_and_kb_queries_are_read_only(self) -> None:
        for command in (
            "git ls-remote origin refs/heads/main",
            "git -C /tmp ls-remote origin refs/heads/main",
            "git blame -L 1,20 scripts/kb/intent_guardian.py",
            "git blame -L 1,20 scripts/kb/intent_guardian.py 2>/dev/null",
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["supervision_domain"], "execution_passthrough")
                self.assertEqual(event["effect"], "unknown")
        for command in (
            "/opt/sulde/bin/kb-index search self-lock -k 5 --json",
            "/opt/sulde/bin/kb-index mem-graph Entity -k 5 --json",
            "python3 -m unittest tests.test_intent_guardian -v",
            "python3 -m py_compile scripts/kb/intent_guardian.py",
            "pytest --last-failed tests/test_intent_guardian.py",
            "codex plugin --help",
            "codex plugin list",
            "codex plugin list --json",
            "codex plugin marketplace list",
            "codex plugin marketplace --help",
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "read")

    def test_plugin_maintenance_diagnostics_do_not_cross_the_write_boundary(self) -> None:
        installer = ROOT / "scripts" / "release" / "install_codex_plugin.py"
        helper = (
            self.codex_home
            / "skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py"
        )
        for command in (
            shlex.join([sys.executable, str(installer), "--help"]),
            shlex.join([sys.executable, str(installer), "--dry-run", "--json"]),
            shlex.join([sys.executable, str(helper), "-h"]),
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                        "cwd": str(ROOT),
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "read")

        for command in (
            shlex.join([sys.executable, str(installer), "--json"]),
            shlex.join([sys.executable, str(installer), "--help", "--json"]),
            shlex.join([sys.executable, str(helper), "--help", "--cachebuster", "x"]),
            f"{shlex.join([sys.executable, str(installer), '--help'])} ; echo chained",
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                        "cwd": str(ROOT),
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertNotEqual(event["effect"], "read")

        probe_home = Path(self.temp.name) / "probe-kb"
        trusted_launcher = probe_home / "bin" / "intent-guardian"
        trusted_launcher.parent.mkdir(parents=True)
        trusted_launcher.write_text("trusted launcher fixture\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(probe_home)}):
            trusted_probe = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": shlex.join(
                            [str(trusted_launcher), "--sulde-launcher-probe"]
                        )
                    },
                },
                phase="started",
                provider="codex",
            )
        self.assertEqual(trusted_probe["effect"], "read")

        fake_guardian = self.root / "intent-guardian.py"
        fake_guardian.write_text("print('not trusted')\n", encoding="utf-8")
        untrusted_probe = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(
                        [str(fake_guardian), "--sulde-launcher-probe"]
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(untrusted_probe["effect"], "destructive")

        force = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git -C /tmp push --force origin main"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(force["supervision_domain"], "execution_passthrough")
        for command in (
            "git push origin +main:main",
            "git push --mirror origin",
            "git push --prune origin",
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {"tool_name": "Bash", "tool_input": {"command": command}},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["supervision_domain"], "execution_passthrough")

    def test_guardian_query_composition_checks_filters_without_safety_pause(self) -> None:
        self.contract()
        probe_home = Path(self.temp.name) / "probe-kb"
        launcher = str(probe_home / "bin" / "intent-guardian")
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(probe_home)}):
            launcher_contract.install_launchers(
                probe_home,
                self.clean_launcher_source(),
            )
            known_filter = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": f"{shlex.quote(launcher)} doctor --workspace . | jq .status"
                    },
                },
                phase="started",
                provider="codex",
            )
            unproven_filter = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": (
                            f"{shlex.quote(launcher)} doctor --workspace . | "
                            "python3 -c 'import json,sys; print(json.load(sys.stdin).get(\"status\"))'"
                        )
                    },
                },
                phase="started",
                provider="codex",
            )
            destructive_tail = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": f"{shlex.quote(launcher)} doctor --workspace . ; rm -rf output"
                    },
                },
                phase="started",
                provider="codex",
            )

        self.assertEqual(known_filter["control_route"], "agent" if os.name == "nt" else "composition")
        self.assertEqual(
            GuardianSession(self.contract_path).observe(known_filter).action,
            "allow",
        )
        self.assertTrue(unproven_filter["control_plane"])
        self.assertEqual(unproven_filter["control_route"], "invalid-composition" if os.name == "nt" else "composition")
        self.assertEqual(unproven_filter["effect"], "unknown" if os.name == "nt" else "read")
        unproven_decision = GuardianSession(self.contract_path).observe(
            unproven_filter
        )
        self.assertEqual(unproven_decision.action, "deny" if os.name == "nt" else "allow")
        self.assertFalse(unproven_decision.pause)
        self.assertEqual(load_contract(self.contract_path)["status"], "active")

        self.assertTrue(destructive_tail["control_plane"])
        self.assertEqual(destructive_tail["control_route"], "invalid-composition" if os.name == "nt" else "composition")
        self.assertEqual(destructive_tail["effect"], "destructive")
        destructive_decision = GuardianSession(self.contract_path).observe(
            destructive_tail
        )
        self.assertEqual(destructive_decision.action, "deny")
        self.assertFalse(destructive_decision.pause)
        after = load_contract(self.contract_path)
        self.assertEqual(after["status"], "active")
        self.assertEqual(after["runtime"]["open_events"], [])
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        # This is not an exception for standalone deletion or an executed gap.
        completed = GuardianSession(self.contract_path).observe(
            {**destructive_tail, "phase": "completed", "success": True}
        )
        self.assertTrue(completed.pause)

    def test_native_guardian_control_still_rejects_shell_composition(self) -> None:
        self.contract()
        probe_home = Path(self.temp.name) / "probe-kb"
        launcher = str(probe_home / "bin" / "intent-guardian")
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(probe_home)}):
            launcher_contract.install_launchers(
                probe_home,
                self.clean_launcher_source(),
            )
            event = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": (
                            f"{shlex.quote(launcher)} native-decision resume "
                            "--decision resume --target current --contract contract.json "
                            "--provider codex --session-id thread | jq .status"
                        )
                    },
                },
                phase="started",
                provider="codex",
            )
        self.assertTrue(event["control_plane"])
        self.assertEqual(event["control_route"], "invalid-composition" if os.name == "nt" else "composition")
        self.assertEqual(event["effect"], "unknown")
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "deny")
        self.assertFalse(decision.pause)
        self.assertEqual(load_contract(self.contract_path)["status"], "active")

    def test_known_sulde_mcp_observation_tools_are_reads(self) -> None:
        cases = (
            ("mcp__sulde_kb__memory_graph", {"entity": "A", "limit": 10}),
            ("mcp__sulde_kb__kb_related", {"doc_id": "kb-1", "limit": 5}),
            ("mcp__sulde_kb__event_observe", {"limit": 20}),
        )
        for tool_name, tool_input in cases:
            with self.subTest(tool_name=tool_name):
                event = normalize_hook_event(
                    {"tool_name": tool_name, "tool_input": tool_input},
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["effect"], "read")

    def test_unknown_ordinary_tool_is_non_material_observation(self) -> None:
        contract = self.contract()
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "opaque-runner --do-something"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(event["effect"], "unknown")
        decision = evaluate_event(contract, event)
        self.assertEqual(decision.action, "allow")
        self.assertFalse(decision.observation_gap)
        self.assertEqual(decision.reason_code, "non_material_observation")
        self.assertFalse(decision.pause)

    def test_trusted_control_command_is_audited_without_becoming_open_work(self) -> None:
        self.contract()
        launcher = f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'}"
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{launcher} apply-proposal /tmp/proposal.json "
                        f"--contract {self.contract_path}"
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(event["control_plane"])
        self.assertEqual(event["control_route"], "agent")
        self.assertRegex(event["control_runtime_sha256"], r"^[0-9a-f]{64}$")
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "allow")
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["open_events"], [])
        audit = json.loads(
            self.contract_path.with_name("intent.events.jsonl").read_text().splitlines()[-1]
        )
        self.assertTrue(audit["event"]["control_plane"])

    def test_trusted_skill_registration_help_is_read_only_control_work(self) -> None:
        self.contract()
        launcher = f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'}"
        for action in ("skill-start", "skill-end"):
            with self.subTest(action=action):
                event = normalize_hook_event(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": f"{launcher} {action} --help"},
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertTrue(event["control_plane"])
                self.assertEqual(event["control_route"], "agent")
                self.assertEqual(event["effect"], "read")
                self.assertEqual(
                    GuardianSession(self.contract_path).observe(event).action,
                    "allow",
                )

        untrusted = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "/tmp/intent-guardian skill-start --help"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertFalse(untrusted.get("control_plane", False))

        composed = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": f"{launcher} skill-end --help ; echo chained"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(composed["control_plane"])
        self.assertEqual(composed["control_route"], "invalid-composition" if os.name == "nt" else "composition")
        self.assertEqual(composed["effect"], "unknown" if os.name == "nt" else "read")

        current = load_contract(self.contract_path)
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["runtime"]["open_events"], [])

    def test_composed_trusted_audit_controls_run_without_pausing_lane(self) -> None:
        contract = self.contract()
        guardian_module._upsert_task_lane_locked(
            contract,
            provider="codex",
            session_id="thread-composed-control",
            state="bound",
            source="test",
        )
        write_contract(self.contract_path, contract)
        launcher = f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'}"
        command = (
            f"{launcher} skill-end --help ; "
            f"{launcher} skill-end --help ; jq -n true"
        )
        effect_store_before = guardian_module.authoritative_store_bytes(
            self.contract_path
        )

        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-composed-control",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(event["control_plane"])
        self.assertEqual(event["control_route"], "invalid-composition" if os.name == "nt" else "composition")
        self.assertEqual(event["effect"], "unknown" if os.name == "nt" else "read")
        decision = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="thread-composed-control",
        ).observe(event)
        self.assertEqual(decision.action, "deny" if os.name == "nt" else "allow")
        self.assertFalse(decision.pause)

        current = load_contract(self.contract_path)
        self.assertEqual(current["status"], "active")
        lane = guardian_module._task_lane(
            current,
            provider="codex",
            session_id="thread-composed-control",
        )
        self.assertIsNotNone(lane)
        self.assertEqual(lane["state"], "bound")
        self.assertEqual(current["runtime"]["open_events"], [])
        self.assertEqual(current["runtime"]["pending_verifications"], [])
        self.assertEqual(
            guardian_module.authoritative_store_bytes(self.contract_path),
            effect_store_before,
        )

        destructive = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-composed-control",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf ./generated-cache"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(destructive["effect"], "destructive")
        destructive_decision = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="thread-composed-control",
        ).observe(destructive)
        self.assertEqual(destructive_decision.action, "deny")
        self.assertFalse(destructive_decision.pause)
        self.assertEqual(load_contract(self.contract_path)["status"], "active")

    def test_quoted_destructive_test_data_never_pauses_the_lane(self) -> None:
        self.contract()
        source = """from pathlib import Path
path = Path('tests/test_command_policy.py')
text = path.read_text()
text += 'command = \\\"rm -rf output\\\"\\n'
path.write_text(text)
"""
        source_command = shlex.join([sys.executable, "-c", source])
        source_event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "quoted-negative-data",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": source_command},
            },
            phase="started",
            provider="codex",
        )
        self.assertNotEqual(source_event["effect"], "destructive")
        source_decision = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="quoted-negative-data",
        ).observe(source_event)
        self.assertFalse(source_decision.pause)
        self.assertEqual(load_contract(self.contract_path)["status"], "active")

        # A classified, allowed local write has an open event until PostToolUse;
        # a later pre-denial must preserve it, not erase that execution fact.
        open_before = load_contract(self.contract_path)["runtime"]["open_events"]
        prefix = "python3 /installed/agent-runtime.py verify /task task"
        identity = {"effect": "unknown", "invalid_composition": True}
        with mock.patch.object(
            guardian_resources,
            "_trusted_script_command",
            side_effect=(
                lambda command, **_kwargs: identity
                if command.startswith(prefix)
                else None
            ),
        ):
            invalid_event = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "quoted-negative-data",
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {"command": prefix + " | opaque-filter"},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(invalid_event["effect"], "unknown")
            self.assertEqual(
                invalid_event["invocation_violation"]["kind"],
                "invalid-composition",
            )
            before = guardian_module.authoritative_store_bytes(self.contract_path)
            invalid_decision = GuardianSession(
                self.contract_path,
                provider="codex",
                session_id="quoted-negative-data",
            ).observe(invalid_event)
            self.assertEqual(invalid_decision.action, "deny")
            self.assertFalse(invalid_decision.pause)
            current = load_contract(self.contract_path)
            self.assertEqual(current["status"], "active")
            self.assertEqual(current["runtime"]["open_events"], open_before)
            self.assertEqual(current["runtime"]["pending_verifications"], [])
            self.assertEqual(
                guardian_module.authoritative_store_bytes(self.contract_path),
                before,
            )

            destructive_event = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "quoted-negative-data",
                    "cwd": str(self.root),
                    "tool_name": "Bash",
                    "tool_input": {"command": prefix + " ; rm -rf output"},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(destructive_event["effect"], "destructive")
            destructive_decision = GuardianSession(
                self.contract_path,
                provider="codex",
                session_id="quoted-negative-data",
            ).observe(destructive_event)
            self.assertEqual(destructive_decision.action, "deny")
            self.assertFalse(destructive_decision.pause)

    def test_trusted_human_control_is_denied_without_pausing_task_contract(self) -> None:
        self.contract()
        launcher = f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'}"
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": f"{launcher} resume reason --contract {self.contract_path}"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(event["control_plane"])
        self.assertEqual(event["control_route"], "human")
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "deny")
        self.assertFalse(decision.pause)
        self.assertIn("可读卡片", decision.reason)
        self.assertIn("机械执行", decision.reason)
        current = load_contract(self.contract_path)
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["runtime"]["open_events"], [])

    def test_break_glass_cli_is_distinct_from_normal_human_decision_path(self) -> None:
        self.contract()
        launcher = f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'}"
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        f"{launcher} retire-workspace --contract "
                        f"{self.contract_path} --reason abandoned"
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        decision = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(decision.action, "deny")
        self.assertFalse(decision.pause)
        self.assertIn("原生 Allow/Deny", decision.reason)
        self.assertIn("仍由 Agent 执行", decision.reason)

    def test_pause_keeps_narrow_host_control_plane_available(self) -> None:
        self.contract()
        contract = load_contract(self.contract_path)
        contract["status"] = "paused"
        contract["runtime"]["pause_reason"] = "awaiting-human"
        write_contract(self.contract_path, contract)
        session = GuardianSession(self.contract_path, provider="codex", session_id="thread")
        for tool_name in (
            "get_goal",
            "update_goal",
            "update_plan",
            "request_user_input",
            "wait",
            "collaboration.wait_agent",
            "collaboration.list_agents",
            "collaboration.interrupt_agent",
        ):
            event = normalize_hook_event(
                {"tool_name": tool_name, "tool_input": {"reason": "report-or-stop"}},
                phase="started",
                provider="codex",
            )
            self.assertTrue(event["control_plane"], tool_name)
            self.assertEqual(event["effect"], "read", tool_name)
            self.assertEqual(session.observe(event).action, "allow", tool_name)
        current = load_contract(self.contract_path)
        self.assertEqual(current["status"], "paused")
        self.assertEqual(current["runtime"]["open_events"], [])

    def test_pause_still_blocks_coordination_that_can_expand_execution(self) -> None:
        self.contract()
        contract = load_contract(self.contract_path)
        contract["status"] = "paused"
        contract["runtime"]["pause_reason"] = "awaiting-human"
        write_contract(self.contract_path, contract)
        for tool_name in (
            "collaboration.spawn_agent",
            "collaboration.followup_task",
            "collaboration.send_message",
        ):
            event = normalize_hook_event(
                {"tool_name": tool_name, "tool_input": {"message": "continue"}},
                phase="started",
                provider="codex",
            )
            self.assertNotIn("control_plane", event, tool_name)
            self.assertEqual(evaluate_event(load_contract(self.contract_path), event).action, "deny", tool_name)

    def test_correction_storm_pauses_and_human_resume_clears_it(self) -> None:
        home = Path(self.temp.name) / "kb"
        payload = {
            "client": "claude",
            "session_id": "thread-1",
            "cwd": str(self.root),
            "prompt": "先修改我的简历",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            context = observe_user_prompt(payload, provider="claude")
            path = active_contract_path(home, self.root)
            provisional = load_contract(path)
            provisional["mode"] = "enforce"
            provisional["confirmed_by"] = "human"
            write_contract(path, provisional)
            payload["prompt"] = "不是这样，这不是我想要的"
            observe_user_prompt(payload, provider="claude")
            payload["prompt"] = "又改错了，越来越偏"
            paused = observe_user_prompt(payload, provider="claude")
            self.assertIn("PAUSED", paused)
            self.assertEqual(load_contract(path)["status"], "paused")
            proposal, digest = create_revision_proposal(
                path,
                objective="只按已确认的本人表达润色简历",
                acceptance_criteria=["事实与数字不变", "不使用营销式措辞"],
                mode="enforce",
                preserve=["事实", "已认可段落"],
                reject=["夸大", "营销式措辞"],
                allowed_paths=["resume.md"],
            )
            self.live_approve_proposal(path, digest, session_id="thread-1")
            resumed = load_contract(path)
            self.assertEqual(resumed["status"], "active")
            self.assertEqual(resumed["revision"], 2)
        self.assertIn("contract=", context)

    def test_codex_pause_text_and_native_resume_record_distinct_controls(self) -> None:
        home = Path(self.temp.name) / "kb"
        payload = {
            "client": "codex",
            "session_id": "thread-controls",
            "cwd": str(self.root),
            "prompt": "start",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(payload, provider="codex")
            path = active_contract_path(home, self.root)
            payload["prompt"] = "先暂停修改"
            paused_context = observe_user_prompt(payload, provider="codex")
            payload["prompt"] = "确认意图并恢复"
            resumed_context = observe_user_prompt(payload, provider="codex")
            paused = load_contract(path)
            self.assertEqual(paused["status"], "paused")
            preview = native_decision_preview(
                path,
                kind="resume",
                decision="resume",
                target="current",
                provider="codex",
                session_id="thread-controls",
            )
            observed = observe_native_permission_request(
                self.native_permission_payload(
                    preview,
                    session_id="thread-controls",
                    contract_path=path,
                ),
                provider="codex",
            )
            result = execute_native_decision(
                path,
                kind="resume",
                decision="resume",
                target=preview["target"],
                provider="codex",
                session_id="thread-controls",
            )
            contract = load_contract(path)

        self.assertIn("CONTROL_RECORDED action=pause", paused_context)
        self.assertIn("NATIVE_DECISION_REQUIRED action=resume", resumed_context)
        self.assertEqual(observed["action"], "defer")
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(contract["status"], "active")
        self.assertEqual(
            [row["action"] for row in contract["runtime"]["approval_receipts"]],
            ["pause", "resume"],
        )
        pause_receipt, resume_receipt = contract["runtime"]["approval_receipts"]
        self.assertEqual(pause_receipt["channel"], "user-prompt")
        self.assertEqual(pause_receipt["consumed_by"], "guardian-control-executor")
        self.assertEqual(resume_receipt["channel"], "codex-native-permission")
        self.assertEqual(
            resume_receipt["consumed_by"],
            "native-permission-control-executor",
        )
        self.assertTrue(pause_receipt["consumed_at"])
        self.assertTrue(resume_receipt["consumed_at"])

    def test_claude_and_codex_sessions_do_not_implicitly_share_task_truth(self) -> None:
        home = Path(self.temp.name) / "kb"
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            codex = observe_user_prompt(
                {
                    "client": "codex",
                    "session_id": "codex-thread",
                    "cwd": str(self.root),
                    "prompt": "修改简历但保留事实",
                },
                provider="codex",
            )
            claude = observe_user_prompt(
                {
                    "client": "claude",
                    "session_id": "claude-session",
                    "cwd": str(self.root),
                    "prompt": "继续同一个简历任务",
                },
                provider="claude",
            )
            path = active_contract_path(home, self.root)
            claude_path = guardian_module.session_contract_path(
                home,
                provider="claude",
                session_id="claude-session",
            )
            self.assertTrue(path.is_file())
            self.assertTrue(claude_path.is_file())
            self.assertIn(str(path), codex)
            self.assertIn(str(claude_path), claude)
            self.assertEqual(len(list((home / "intent" / "workspaces").glob("*.active.json"))), 1)
            self.assertEqual(load_contract(path)["objective"], "修改简历但保留事实")
            self.assertEqual(load_contract(claude_path)["objective"], "继续同一个简历任务")

    def test_codex_skill_registration_uses_product_launcher_home(self) -> None:
        sulde_home = Path(self.temp.name) / "sulde-home"
        home = sulde_home / "data" / "kb"
        with mock.patch.dict(
            os.environ,
            {"SULDE_HOME": str(sulde_home), "SULDE_KB_HOME": str(home)},
        ):
            context = observe_user_prompt(
                {
                    "client": "codex",
                    "session_id": "canonical-home-thread",
                    "cwd": str(self.root),
                    "prompt": "继续修复当前任务",
                },
                provider="codex",
            )

        self.assertIn(str(sulde_home / "bin" / "intent-guardian"), context)
        self.assertNotIn(str(home / "bin" / "intent-guardian"), context)

    def test_skill_lineage_is_isolated_per_provider_session(self) -> None:
        self.contract()
        record_skill_event(
            self.contract_path,
            name="resume-kit",
            phase="started",
            provider="codex",
            session_id="one",
            skill_path=self.skill_path,
        )
        other = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "two",
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc://resume"},
            },
            phase="started",
            provider="codex",
        )
        GuardianSession(self.contract_path).observe(other)
        same = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "one",
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc://resume"},
            },
            phase="started",
            provider="codex",
        )
        GuardianSession(self.contract_path).observe(same)
        rows = [json.loads(line) for line in self.contract_path.with_name("intent.events.jsonl").read_text().splitlines()]
        self.assertEqual(rows[-2]["event"]["parent_skills"], [])
        self.assertEqual(rows[-1]["event"]["parent_skills"], ["resume-kit"])

    def test_forbidden_skill_pauses_before_downstream_tools(self) -> None:
        contract = self.contract()
        contract["skills"]["deny"] = ["unsafe-rewriter"]
        write_contract(self.contract_path, contract)
        denied = record_skill_event(
            self.contract_path,
            name="unsafe-rewriter",
            phase="started",
            provider="codex",
            session_id="one",
            skill_path=self.skill_path,
        )
        self.assertEqual(denied.action, "deny")
        current = load_contract(self.contract_path)
        self.assertEqual(current["status"], "paused")
        self.assertEqual(current["runtime"]["active_skill_frames"], [])

    def test_codex_l3_skill_registration_is_adjudicated_from_provider_stream(self) -> None:
        self.contract()
        session = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="l3:test",
        )
        start_command = (
            f"python3 {SCRIPT_DIR / 'intent-guardian.py'} skill-start resume-kit "
            f"--skill-path {self.skill_path} --provider codex "
            f"--contract {self.contract_path} --session-id l3:test"
        )
        start = {
            "type": "item.started",
            "item": {
                "id": "skill-start-call",
                "type": "command_execution",
                "command": start_command,
                "status": "in_progress",
            },
        }
        self.assertEqual(session.observe_provider_line(json.dumps(start)).action, "allow")
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["active_skills"], ["resume-kit"])
        self.assertEqual(runtime["open_events"], [])

        # Codex emits the same command again as item.completed. It must not
        # create a second frame or prematurely close the Skill boundary.
        completed_start = json.loads(json.dumps(start))
        completed_start["type"] = "item.completed"
        completed_start["item"]["status"] = "completed"
        self.assertIsNone(session.observe_provider_line(json.dumps(completed_start)))
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["active_skills"], ["resume-kit"])
        self.assertEqual(runtime["open_events"], [])

        mcp = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "l3:test",
                "tool_name": "mcp__docs__read_document",
                "tool_input": {"uri": "doc://resume"},
            },
            phase="completed",
            provider="codex",
        )
        session.observe(mcp)
        audit_rows = [
            json.loads(line)
            for line in self.contract_path.with_name("intent.events.jsonl").read_text().splitlines()
        ]
        self.assertEqual(audit_rows[-1]["event"]["parent_skills"], ["resume-kit"])

        end_command = start_command.replace("skill-start", "skill-end")
        end_started = {
            "type": "item.started",
            "item": {
                "id": "skill-end-call",
                "type": "command_execution",
                "command": end_command,
                "status": "in_progress",
            },
        }
        self.assertIsNone(session.observe_provider_line(json.dumps(end_started)))
        end_completed = json.loads(json.dumps(end_started))
        end_completed["type"] = "item.completed"
        end_completed["item"]["status"] = "completed"
        self.assertEqual(session.observe_provider_line(json.dumps(end_completed)).action, "allow")
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["active_skill_frames"], [])
        self.assertEqual(runtime["open_events"], [])

    def test_managed_l3_skill_child_only_previews_parent_policy(self) -> None:
        self.contract()
        before = load_contract(self.contract_path)["runtime"]["sequence"]
        with mock.patch.dict(
            os.environ,
            {
                "SULDE_GUARDIAN_STREAM_OWNER": "1",
                "SULDE_GUARDIAN_STREAM_PROVIDER": "codex",
            },
        ):
            decision = record_skill_event(
                self.contract_path,
                name="resume-kit",
                phase="started",
                provider="codex",
                skill_path=self.skill_path,
            )
        self.assertEqual(decision.action, "allow")
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["sequence"], before)
        self.assertEqual(current["runtime"]["active_skill_frames"], [])

    def test_skill_instruction_change_during_use_pauses_managed_lineage(self) -> None:
        self.contract()
        skill_dir = Path(self.temp.name) / "mutable-skill"
        skill_dir.mkdir()
        skill = skill_dir / "SKILL.md"
        skill.write_text("# v1\n", encoding="utf-8")
        session = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="managed:test",
        )

        def record(action: str, call_id: str) -> dict:
            return {
                "type": "item.started" if action == "skill-start" else "item.completed",
                "item": {
                    "id": call_id,
                    "type": "command_execution",
                    "command": (
                        f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'} "
                        f"{action} mutable --skill-path {skill} "
                        f"--provider codex --contract {self.contract_path} "
                        "--session-id managed:test"
                    ),
                    "status": "in_progress" if action == "skill-start" else "completed",
                },
            }

        self.assertEqual(
            session.observe_provider_line(json.dumps(record("skill-start", "start"))).action,
            "allow",
        )
        skill.write_text("# v2 changed mid-use\n", encoding="utf-8")
        decision = session.observe_provider_line(json.dumps(record("skill-end", "end")))
        self.assertEqual(decision.action, "deny")
        self.assertIn("破坏性", decision.reason)
        self.assertEqual(load_contract(self.contract_path)["status"], "paused")

    def test_guardian_shell_chain_cannot_masquerade_as_skill_registration(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": (
                        "/tmp/intent-guardian skill-start resume-kit --provider codex "
                        f"--skill-path {self.skill_path} --contract {self.contract_path} "
                        "--session-id thread && git reset --hard"
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(event["effect"], "destructive")
        self.assertEqual(evaluate_event(load_contract(self.contract_path), event).action, "deny")

    def test_malformed_or_wrong_contract_skill_registration_is_denied(self) -> None:
        self.contract()
        missing_contract = normalize_hook_event(
            {
                "client": "codex",
                "tool_name": "Bash",
                "tool_input": {
                    "command": "/tmp/intent-guardian skill-start resume-kit --provider codex"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(missing_contract["effect"], "destructive")

        session = GuardianSession(self.contract_path, provider="codex")
        wrong = {
            "type": "item.started",
            "item": {
                "id": "wrong-contract",
                "type": "command_execution",
                "command": (
                    f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'} "
                    "skill-start resume-kit --provider codex "
                    f"--skill-path {self.skill_path} --contract /tmp/other.intent.json "
                    "--session-id l3:test"
                ),
                "status": "in_progress",
            },
        }
        decision = session.observe_provider_line(json.dumps(wrong))
        self.assertEqual(decision.action, "deny")
        self.assertIn("破坏性", decision.reason)
        self.assertEqual(load_contract(self.contract_path)["runtime"]["active_skills"], [])

    def test_revision_proposal_cannot_apply_without_exact_human_approval(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="只润色表达，不增加经历",
            acceptance_criteria=["事实不变", "语气克制"],
            mode="enforce",
            preserve=["事实"],
            reject=["夸大"],
            allowed_paths=["resume.md"],
        )
        self.assertEqual(load_contract(self.contract_path)["revision"], 1)
        with self.assertRaisesRegex(IntentGuardianError, "not been approved"):
            apply_revision_proposal(self.contract_path, proposal)
        self.live_approve_proposal(self.contract_path, digest)
        applied = load_contract(self.contract_path)
        self.assertEqual(applied["revision"], 2)
        self.assertEqual(applied["objective"], "只润色表达，不增加经历")
        self.assertEqual(applied["confirmed_by"], "human-readable-proposal-approval")
        self.assertEqual(applied["applied_decision_authority"], "human")
        self.assertEqual(applied["applied_approval_channel"], "codex-native-permission")
        self.assertRegex(applied["applied_approval_receipt_id"], r"^[0-9a-f]{64}$")
        owner_lanes = [
            row
            for row in applied["runtime"]["task_lanes"]
            if row["task_epoch"] == applied["task_epoch"]
            and row["source"] == "approved_revision"
        ]
        self.assertEqual(len(owner_lanes), 1)
        self.assertTrue(owner_lanes[0]["continuation_eligible"])

    def test_task_continuation_reconciles_only_terminal_stale_local_write(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-local",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": "resume.md"},
            },
            phase="started",
            provider="codex",
        )
        decision = GuardianSession(self.contract_path, provider="codex").observe(event)
        self.assertEqual(decision.action, "allow")
        self.assertEqual(len(load_contract(self.contract_path)["runtime"]["open_events"]), 1)

        active = reconcile_stale_local_write_events(
            self.contract_path,
            provider="codex",
            session_id="thread-local",
            minimum_age_seconds=0,
        )
        self.assertEqual(active, [])

        contract = load_contract(self.contract_path)
        guardian_module._upsert_task_lane_locked(
            contract,
            provider="codex",
            session_id="thread-local",
            state="bound",
            source="approved_revision",
            proposal_digest="a" * 64,
            continuation_eligible=True,
        )
        guardian_module._upsert_task_lane_locked(
            contract,
            provider="codex",
            session_id="new-session",
            state="review_required",
            source="workspace_discovery",
            pending_task_instance_id="continued-task",
        )
        contract["runtime"]["open_events"][0]["started_at"] = (
            "2000-01-01T00:00:00+00:00"
        )
        write_contract(self.contract_path, contract)

        audit_rows = [
            json.loads(line)
            for line in audit_path(self.contract_path).read_text(encoding="utf-8").splitlines()
        ]
        audit_rows[-1]["event"]["at"] = "2000-01-01T00:00:00+00:00"
        audit_path(self.contract_path).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in audit_rows),
            encoding="utf-8",
        )

        before_continuation = reconcile_stale_local_write_events(
            self.contract_path,
            provider="codex",
            session_id="new-session",
            minimum_age_seconds=0,
        )
        self.assertEqual(before_continuation, [])
        preview = native_decision_preview(
            self.contract_path,
            kind="task-continuation",
            decision="approve",
            target="current",
            provider="codex",
            session_id="new-session",
        )
        self.assertEqual(
            observe_native_permission_request(
                self.native_permission_payload(preview, session_id="new-session"),
                provider="codex",
            )["action"],
            "defer",
        )
        result = execute_native_decision(
            self.contract_path,
            kind="task-continuation",
            decision="approve",
            target=preview["target"],
            provider="codex",
            session_id="new-session",
        )
        self.assertEqual(result["status"], "applied")
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["open_events"], [])
        outcome = runtime["inconclusive_outcomes"][-1]
        self.assertEqual(outcome["schema"], guardian_stale_events.SETTLEMENT_SCHEMA)
        self.assertFalse(outcome["authority_transferred"])
        self.assertFalse(outcome["effect_asserted"])
        settlement_rows = [
            json.loads(line)
            for line in audit_path(self.contract_path).read_text(encoding="utf-8").splitlines()
            if guardian_stale_events.SETTLEMENT_SCHEMA in line
        ]
        self.assertEqual(len(settlement_rows), 1)
        self.assertEqual(settlement_rows[0]["outcome"], "inconclusive")
        self.assertEqual(settlement_rows[0]["terminal_reason"], "formal_task_continuation")
        self.assertEqual(
            reconcile_stale_local_write_events(
                self.contract_path,
                provider="codex",
                session_id="new-session",
                minimum_age_seconds=0,
            ),
            [],
        )

    def test_aged_current_lane_local_write_blocks_only_overlapping_revision(self) -> None:
        _, path, _ = self.stale_local_write_fixture(
            "current-lane-disjoint-proposal",
            source_session="current-session",
        )
        self.age_open_event(path)

        with self.assertRaisesRegex(IntentGuardianError, "resource event is still open"):
            create_revision_proposal(
                path,
                objective="continue editing the same file",
                acceptance_criteria=["same resource remains protected"],
                mode="enforce",
                allowed_paths=["notes.md"],
                provider="codex",
                session_id="current-session",
            )

        proposal, digest = create_revision_proposal(
            path,
            objective="edit a provably disjoint local file",
            acceptance_criteria=["the old event remains append-only and unresolved"],
            mode="enforce",
            allowed_paths=["unrelated.md"],
            decision_route="agent",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore unrelated.md",
            provider="codex",
            session_id="current-session",
        )
        self.assertTrue(proposal.is_file())
        current = load_contract(path)
        self.assertEqual(len(current["runtime"]["open_events"]), 1)
        self.assertEqual(current["runtime"]["inconclusive_outcomes"], [])

        self.codex_agent_decide(
            path,
            digest,
            rationale="the new local target is exact and provably disjoint",
            evidence=["typed path overlap returned false and the old audit digest is valid"],
            session_id="current-session",
        )
        applied = apply_revision_proposal(path, proposal)
        self.assertEqual(applied["applied_decision_authority"], "agent-policy")
        self.assertEqual(len(applied["runtime"]["open_events"]), 1)
        self.assertEqual(applied["runtime"]["inconclusive_outcomes"], [])
        self.assertEqual(
            applied["runtime"]["open_events"][0]["event_id"],
            current["runtime"]["open_events"][0]["event_id"],
        )

    def test_cli_can_create_decide_and_apply_agent_eligible_revision_atomically(self) -> None:
        self.contract()
        session_id = "atomic-agent-revision"
        command = [
            sys.executable,
            "-B",
            str(SCRIPT_DIR / "intent-guardian.py"),
            "propose-revision",
            str(self.contract_path),
            "--objective",
            "refresh one deterministic local fixture",
            "--accept",
            "atomic.md has the expected deterministic content",
            "--allow-path",
            "atomic.md",
            "--decision-route",
            "auto",
            "--intent-kind",
            "deterministic",
            "--risk",
            "low",
            "--effect",
            "local_write",
            "--reversibility",
            "reversible",
            "--cost",
            "none",
            "--rollback",
            "restore atomic.md from the task branch",
            "--provider",
            "codex",
            "--session-id",
            session_id,
            "--apply-agent-eligible",
            "--agent-rationale",
            "the target is exact, local, deterministic and reversible",
            "--agent-evidence",
            "the proposal gate selected the Agent route",
        ]
        env = os.environ.copy()
        env["CODEX_THREAD_ID"] = session_id
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        output = json.loads(result.stdout)
        applied = load_contract(self.contract_path)

        self.assertEqual(output["decision_route"], "agent")
        self.assertEqual(output["applied_revision"], 2)
        self.assertEqual(output["applied_decision_authority"], "agent-policy")
        self.assertEqual(applied["revision"], 2)
        self.assertEqual(applied["applied_decision_authority"], "agent-policy")
        self.assertEqual(applied["runtime"]["pending_proposal_digest"], "")

    def test_r193_keyless_control_event_is_quarantined_not_globalized(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = ["scripts/kb/**", "resume.md"]
        write_contract(self.contract_path, contract)
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "r193-source",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": "scripts/kb/intent_guardian.py"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(GuardianSession(self.contract_path).observe(event).action, "allow")

        current = load_contract(self.contract_path)
        opened = current["runtime"]["open_events"][0]
        opened["event_id"] = "bf54cf4dfbd0808a4b5e39b8"
        opened["target"] = "[local-target-set:bc2a10f4854d98e7]"
        opened["started_at"] = "2000-01-01T00:00:00+00:00"
        rows = [
            json.loads(line)
            for line in audit_path(self.contract_path).read_text(encoding="utf-8").splitlines()
        ]
        source = rows[-1]["event"]
        source["event_id"] = opened["event_id"]
        source["target"] = opened["target"]
        source["at"] = opened["started_at"]
        source["write_targets"] = [
            ".worktrees/guardian-v3-session-handoff/integrations/codex/plugins/sulde/scripts/pre-tool-use.py",
            ".worktrees/guardian-v3-session-handoff/scripts/kb/intent_guardian.py",
        ]
        fingerprint = guardian_module.event_fingerprint(source)
        source["fingerprint"] = fingerprint
        rows[-1]["decision"]["fingerprint"] = fingerprint
        opened["fingerprint"] = fingerprint
        write_contract(self.contract_path, current)
        audit_path(self.contract_path).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

        self.assertEqual(
            reconcile_stale_local_write_events(
                self.contract_path,
                provider="codex",
                session_id="new-session",
                minimum_age_seconds=0,
            ),
            [],
        )
        report = guardian_stale_events.stale_event_report(
            self.contract_path,
            provider="codex",
            session_id="new-session",
            minimum_age_seconds=0,
        )
        self.assertEqual(report["current_lane_blockers"], [])
        self.assertEqual(report["effect_debt"], [])
        self.assertEqual(
            report["quarantined_high_risk"][0]["reason"],
            "control_plane_local_write",
        )
        doctor_projection = guardian_report(
            self.contract_path,
            provider="codex",
            session_id="new-session",
        )["stale_events"]
        self.assertEqual(
            set(doctor_projection),
            {
                "schema",
                "current_lane_blockers",
                "other_lane_stale",
                "effect_debt",
                "settled_inconclusive",
                "settled_inconclusive_total",
                "quarantined_high_risk",
                "eligible_for_reconciliation",
                "audit_integrity",
            },
        )

        with self.assertRaisesRegex(IntentGuardianError, "resource event is still open"):
            create_revision_proposal(
                self.contract_path,
                objective="change the same guardian module",
                acceptance_criteria=["same resource remains protected"],
                mode="enforce",
                allowed_paths=["scripts/kb/intent_guardian.py"],
                provider="codex",
                session_id="new-session",
            )
        proposal, _ = create_revision_proposal(
            self.contract_path,
            objective="edit an unrelated resume",
            acceptance_criteria=["control-plane event is preserved"],
            mode="enforce",
            allowed_paths=["resume.md"],
            provider="codex",
            session_id="new-session",
        )
        self.assertTrue(proposal.is_file())
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["open_events"][0]["event_id"],
            "bf54cf4dfbd0808a4b5e39b8",
        )

    def test_stale_reconciler_rejects_effect_grant_pending_and_fresh_events(self) -> None:
        cases = (
            ("external", "effect", "external_write", "effect_debt"),
            ("destructive", "effect", "destructive", "effect_debt"),
            ("unknown", "effect", "unknown", "effect_debt"),
            ("attempt", "attempt_id", "att-legacy", "effect_debt"),
            ("grant", "continuation_grant_id", "grant-legacy", "effect_debt"),
            ("profile", "continuation_profile_id", "profile-legacy", "effect_debt"),
            ("fresh", "none", "", "other_lane_stale"),
        )
        for name, field, value, category in cases:
            with self.subTest(case=name):
                _, path, _ = self.stale_local_write_fixture(name)
                if name != "fresh":
                    self.age_open_event(path)
                self.add_formal_continuation(path)
                current = load_contract(path)
                if field != "none":
                    current["runtime"]["open_events"][0][field] = value
                    if field == "effect":
                        rows = [
                            json.loads(line)
                            for line in audit_path(path).read_text(encoding="utf-8").splitlines()
                        ]
                        rows[-1]["event"]["effect"] = value
                        audit_path(path).write_text(
                            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                            encoding="utf-8",
                        )
                    write_contract(path, current)
                self.assertEqual(
                    reconcile_stale_local_write_events(
                        path,
                        provider="codex",
                        session_id="new-session",
                        minimum_age_seconds=86400 if name == "fresh" else 0,
                    ),
                    [],
                )
                report = guardian_stale_events.stale_event_report(
                    path,
                    provider="codex",
                    session_id="new-session",
                    minimum_age_seconds=86400 if name == "fresh" else 0,
                )
                self.assertEqual(len(report[category]), 1)
                self.assertEqual(len(load_contract(path)["runtime"]["open_events"]), 1)

        _, pending_path, _ = self.stale_local_write_fixture("pending")
        self.age_open_event(pending_path)
        self.add_formal_continuation(pending_path)
        pending = load_contract(pending_path)
        opened = pending["runtime"]["open_events"][0]
        pending["runtime"]["pending_verifications"].append(
            {"event_id": opened["event_id"], "fingerprint": opened["fingerprint"]}
        )
        write_contract(pending_path, pending)
        self.assertEqual(
            reconcile_stale_local_write_events(
                pending_path,
                provider="codex",
                session_id="new-session",
                minimum_age_seconds=0,
            ),
            [],
        )
        self.assertEqual(
            len(
                guardian_stale_events.stale_event_report(
                    pending_path,
                    provider="codex",
                    session_id="new-session",
                    minimum_age_seconds=0,
                )["effect_debt"]
            ),
            1,
        )

    def test_stale_reconciler_rejects_active_corrupt_and_mismatched_sources(self) -> None:
        _, active_path, _ = self.stale_local_write_fixture("active-source")
        self.age_open_event(active_path)
        self.assertEqual(
            reconcile_stale_local_write_events(
                active_path,
                provider="codex",
                session_id="source-session",
                minimum_age_seconds=0,
            ),
            [],
        )
        active_report = guardian_stale_events.stale_event_report(
            active_path,
            provider="codex",
            session_id="source-session",
            minimum_age_seconds=0,
        )
        self.assertEqual(len(active_report["current_lane_blockers"]), 1)

        _, corrupt_path, _ = self.stale_local_write_fixture("corrupt-source")
        self.age_open_event(corrupt_path)
        self.add_formal_continuation(corrupt_path)
        with audit_path(corrupt_path).open("a", encoding="utf-8") as handle:
            handle.write("{broken-json\n")
        self.assertEqual(
            reconcile_stale_local_write_events(
                corrupt_path,
                provider="codex",
                session_id="new-session",
                minimum_age_seconds=0,
            ),
            [],
        )
        corrupt_report = guardian_stale_events.stale_event_report(
            corrupt_path,
            provider="codex",
            session_id="new-session",
            minimum_age_seconds=0,
        )
        self.assertEqual(corrupt_report["audit_integrity"]["status"], "invalid")
        self.assertEqual(
            corrupt_report["quarantined_high_risk"][0]["reason"], "audit_corrupt"
        )

        _, mismatch_path, _ = self.stale_local_write_fixture("mismatch-source")
        self.age_open_event(mismatch_path)
        self.add_formal_continuation(mismatch_path)
        mismatched = load_contract(mismatch_path)
        mismatched["runtime"]["open_events"][0]["target"] = "different.md"
        write_contract(mismatch_path, mismatched)
        self.assertEqual(
            reconcile_stale_local_write_events(
                mismatch_path,
                provider="codex",
                session_id="new-session",
                minimum_age_seconds=0,
            ),
            [],
        )
        mismatch_report = guardian_stale_events.stale_event_report(
            mismatch_path,
            provider="codex",
            session_id="new-session",
            minimum_age_seconds=0,
        )
        self.assertTrue(
            mismatch_report["quarantined_high_risk"][0]["reason"].startswith(
                "source_event_mismatch:"
            )
        )

        _, stop_path, _ = self.stale_local_write_fixture("stop-is-not-terminal")
        self.age_open_event(stop_path)
        stopped = load_contract(stop_path)
        stopped["runtime"]["host_observations"].append(
            {
                "event": "stop",
                "provider": "codex",
                "session_id": "source-session",
                "source": "live_host_hook",
                "status": "completed",
                "at": "2026-09-03T00:00:00+00:00",
            }
        )
        write_contract(stop_path, stopped)
        self.assertEqual(
            reconcile_stale_local_write_events(
                stop_path,
                provider="codex",
                session_id="new-session",
                minimum_age_seconds=0,
            ),
            [],
        )
        stop_report = guardian_stale_events.stale_event_report(
            stop_path,
            provider="codex",
            session_id="new-session",
            minimum_age_seconds=0,
        )
        self.assertEqual(
            stop_report["other_lane_stale"][0]["reason"],
            "source_session_not_terminal",
        )

        _, grant_mismatch_path, _ = self.stale_local_write_fixture(
            "source-grant-mismatch"
        )
        self.age_open_event(grant_mismatch_path)
        self.add_formal_continuation(grant_mismatch_path)
        grant_rows = [
            json.loads(line)
            for line in audit_path(grant_mismatch_path)
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        grant_rows[-1]["event"]["continuation_authority"] = {
            "grant_id": "grant-from-source-audit",
            "profile_id": "profile-from-source-audit",
        }
        audit_path(grant_mismatch_path).write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in grant_rows),
            encoding="utf-8",
        )
        self.assertEqual(
            reconcile_stale_local_write_events(
                grant_mismatch_path,
                provider="codex",
                session_id="new-session",
                minimum_age_seconds=0,
            ),
            [],
        )
        grant_mismatch_report = guardian_stale_events.stale_event_report(
            grant_mismatch_path,
            provider="codex",
            session_id="new-session",
            minimum_age_seconds=0,
        )
        self.assertEqual(
            grant_mismatch_report["quarantined_high_risk"][0]["reason"],
            "source_event_mismatch:continuation_grant_id",
        )

    def test_proposal_boundary_settles_same_lane_apply_patch_inconclusively(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "same-session",
                "cwd": str(self.root),
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": "*** Begin Patch\n*** Update File: resume.md\n@@\n-old\n+new\n*** End Patch"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(GuardianSession(self.contract_path).observe(event).action, "allow")
        self.age_open_event(self.contract_path)

        settled = reconcile_stale_local_write_events(
            self.contract_path,
            provider="codex",
            session_id="same-session",
            minimum_age_seconds=0,
            boundary="proposal_request",
        )
        self.assertEqual(len(settled), 1)
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["open_events"], [])
        outcome = current["runtime"]["inconclusive_outcomes"][-1]
        self.assertFalse(outcome["authority_transferred"])
        self.assertFalse(outcome["effect_asserted"])

    def test_same_lane_apply_patch_stays_blocked_outside_proposal_boundary(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "same-session",
                "cwd": str(self.root),
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": "*** Begin Patch\n*** Update File: resume.md\n@@\n-old\n+new\n*** End Patch"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(GuardianSession(self.contract_path).observe(event).action, "allow")
        self.age_open_event(self.contract_path)

        self.assertEqual(
            reconcile_stale_local_write_events(
                self.contract_path,
                provider="codex",
                session_id="same-session",
                minimum_age_seconds=0,
                boundary="task_continuation_request",
            ),
            [],
        )
        self.assertEqual(len(load_contract(self.contract_path)["runtime"]["open_events"]), 1)

    def test_proposal_boundary_settles_prior_epoch_patch_from_bound_session(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "same-session",
                "cwd": str(self.root),
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": "*** Begin Patch\n*** Update File: resume.md\n@@\n-old\n+new\n*** End Patch"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(GuardianSession(self.contract_path).observe(event).action, "allow")
        self.age_open_event(self.contract_path)
        current = load_contract(self.contract_path)
        current["task_epoch"] = "new-task-epoch"
        write_contract(self.contract_path, current)
        seed_session_workspace_hint(
            Path(os.environ["SULDE_KB_HOME"]),
            provider="codex",
            session_id="same-session",
            contract_path=self.contract_path,
        )

        settled = reconcile_stale_local_write_events(
            self.contract_path,
            provider="codex",
            session_id="same-session",
            minimum_age_seconds=0,
            boundary="proposal_request",
        )
        self.assertEqual(len(settled), 1)
        self.assertEqual(load_contract(self.contract_path)["runtime"]["open_events"], [])

    def test_stale_reconciler_is_concurrent_and_idempotent(self) -> None:
        _, path, _ = self.stale_local_write_fixture("concurrent-settlement")
        self.age_open_event(path)
        self.add_formal_continuation(path)

        def settle(_: int) -> list[dict]:
            return reconcile_stale_local_write_events(
                path,
                provider="codex",
                session_id="new-session",
                minimum_age_seconds=0,
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(settle, range(8)))
        self.assertEqual(sum(bool(result) for result in results), 1)
        current = load_contract(path)
        self.assertEqual(current["runtime"]["open_events"], [])
        self.assertEqual(
            len(
                [
                    row
                    for row in current["runtime"]["inconclusive_outcomes"]
                    if row.get("schema") == guardian_stale_events.SETTLEMENT_SCHEMA
                ]
            ),
            1,
        )
        settlement_rows = [
            json.loads(line)
            for line in audit_path(path).read_text(encoding="utf-8").splitlines()
            if guardian_stale_events.SETTLEMENT_SCHEMA in line
        ]
        self.assertEqual(len(settlement_rows), 1)
        self.assertRegex(settlement_rows[0]["settlement_id"], r"^[0-9a-f]{64}$")
        self.assertRegex(settlement_rows[0]["source_event_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(settlement_rows[0]["settlement_sha256"], r"^[0-9a-f]{64}$")

    def test_stale_reconciler_replays_append_before_projection_crash(self) -> None:
        _, path, _ = self.stale_local_write_fixture("append-before-projection")
        self.age_open_event(path)
        self.add_formal_continuation(path)
        with mock.patch.object(
            guardian_stale_events,
            "_write_contract_unlocked",
            side_effect=OSError("injected projection failure"),
        ):
            with self.assertRaisesRegex(OSError, "injected projection failure"):
                reconcile_stale_local_write_events(
                    path,
                    provider="codex",
                    session_id="new-session",
                    minimum_age_seconds=0,
                )
        self.assertEqual(len(load_contract(path)["runtime"]["open_events"]), 1)
        first_rows = [
            line
            for line in audit_path(path).read_text(encoding="utf-8").splitlines()
            if guardian_stale_events.SETTLEMENT_SCHEMA in line
        ]
        self.assertEqual(len(first_rows), 1)

        replayed = reconcile_stale_local_write_events(
            path,
            provider="codex",
            session_id="new-session",
            minimum_age_seconds=0,
        )
        self.assertEqual(len(replayed), 1)
        self.assertEqual(load_contract(path)["runtime"]["open_events"], [])
        final_rows = [
            line
            for line in audit_path(path).read_text(encoding="utf-8").splitlines()
            if guardian_stale_events.SETTLEMENT_SCHEMA in line
        ]
        self.assertEqual(final_rows, first_rows)

    def test_declared_effects_drive_one_consistent_permission_policy(self) -> None:
        contract = self.contract()
        contract["permissions"]["local_write"] = False
        contract["permissions"]["external_write"] = "deny"
        write_contract(self.contract_path, contract)
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="修复并推送已验证的控制面",
            acceptance_criteria=["测试通过", "非强制推送可核验"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["external_write", "local_write", "local_write"],
            reversibility="reversible",
            cost="none",
            rollback="git revert",
        )
        candidate = load_contract(proposal)
        self.assertEqual(
            candidate["decision"]["effects"],
            ["local_write", "external_write"],
        )
        self.assertTrue(candidate["permissions"]["local_write"])
        self.assertEqual(candidate["permissions"]["external_write"], "confirm")
        card = proposal_review_for_digest(self.contract_path, digest)["decision_card"]
        self.assertEqual(card["执行权限边界"]["本地写入"], "允许")
        self.assertEqual(
            card["执行权限边界"]["外部写入"],
            "当前可读方案内由监督器执行；扩大范围时在对话中确认",
        )

        candidate["permissions"]["local_write"] = False
        with self.assertRaisesRegex(IntentGuardianError, "local_write requires"):
            write_contract(Path(self.temp.name) / "mismatch.json", candidate)

    def test_multifile_proposal_does_not_infer_checkpoint_from_path_count(self) -> None:
        self.contract()
        proposal, _digest = create_revision_proposal(
            self.contract_path,
            objective="完成一个三文件的原子修复",
            acceptance_criteria=["三个文件共同满足验收"],
            mode="enforce",
            allowed_paths=["one.py", "two.py", "three.py"],
            semantic_critic=True,
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复三个文件的原字节",
        )
        candidate = load_contract(proposal)
        self.assertNotIn("cadence_writes", candidate["critic"])
        self.assertEqual(
            candidate["critic"]["checkpoint_boundary"],
            "turn_stop_or_managed_terminal",
        )
        self.assertFalse(hasattr(guardian_module, "semantic_critic_due"))

    def test_legacy_critic_cadence_migrates_to_terminal_boundary(self) -> None:
        contract = self.contract()
        contract["critic"].pop("checkpoint_boundary", None)
        contract["critic"]["cadence_writes"] = 7

        write_contract(self.contract_path, contract)

        migrated = load_contract(self.contract_path)
        self.assertNotIn("cadence_writes", migrated["critic"])
        self.assertEqual(
            migrated["critic"]["checkpoint_boundary"],
            "turn_stop_or_managed_terminal",
        )

    def test_stop_claims_one_semantic_batch_outside_the_contract_lock(self) -> None:
        contract = self.contract()
        contract["critic"]["enabled"] = True
        contract["constraints"]["allowed_paths"] = ["one.py", "two.py"]
        guardian_module._upsert_task_lane_locked(
            contract,
            provider="codex",
            session_id="thread-batch",
            state="bound",
            source="test",
        )
        write_contract(self.contract_path, contract)
        for index, target in enumerate(("one.py", "two.py"), start=1):
            started = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "thread-batch",
                    "call_id": f"write-{index}",
                    "cwd": str(self.root),
                    "tool_name": "Write",
                    "tool_input": {"file_path": target},
                },
                phase="started",
                provider="codex",
            )
            completed = dict(started, phase="completed", success=True)
            GuardianSession(self.contract_path, provider="codex").observe(started)
            GuardianSession(self.contract_path, provider="codex").observe(completed)

        calls: list[dict] = []

        def critic_runner(contract_snapshot, event, *, provider):
            # A nested acquisition succeeds only because the model callback is
            # invoked after the claim transaction released the contract lock.
            with guardian_module.contract_lock(self.contract_path):
                self.assertEqual(load_contract(self.contract_path)["revision"], 1)
            calls.append({"event": event, "provider": provider})
            return {
                "verdict": "aligned",
                "confidence": 0.99,
                "summary": "batch matches the contract",
                "violated_constraints": [],
                "evidence": ["two exact targets"],
                "next_action": "continue",
            }

        payload = {
            "client": "codex",
            "session_id": "thread-batch",
            "intent_contract": str(self.contract_path),
        }
        self.assertEqual(
            finalize_host_turn(
                payload,
                provider="codex",
                critic_runner=critic_runner,
            ),
            "",
        )
        self.assertEqual(
            finalize_host_turn(
                payload,
                provider="codex",
                critic_runner=critic_runner,
            ),
            "",
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["event"]["write_targets"], ["one.py", "two.py"])
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["critic_batches"], [])
        self.assertEqual(runtime["critic_checkpoints"][-1]["verdict"], "aligned")

    def test_concurrent_material_change_supersedes_stale_critic_result(self) -> None:
        contract = self.contract()
        contract["critic"]["enabled"] = True
        contract["constraints"]["allowed_paths"] = ["one.py", "two.py"]
        for session_id in ("thread-a", "thread-b"):
            guardian_module._upsert_task_lane_locked(
                contract,
                provider="codex",
                session_id=session_id,
                state="bound",
                source="test",
            )
        write_contract(self.contract_path, contract)

        def complete_write(session_id: str, target: str, call_id: str) -> None:
            started = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": session_id,
                    "call_id": call_id,
                    "cwd": str(self.root),
                    "tool_name": "Write",
                    "tool_input": {"file_path": target},
                },
                phase="started",
                provider="codex",
            )
            GuardianSession(self.contract_path, provider="codex").observe(started)
            GuardianSession(self.contract_path, provider="codex").observe(
                dict(started, phase="completed", success=True)
            )

        complete_write("thread-a", "one.py", "write-a")

        def drifting_runner(_contract, _event, *, provider):
            self.assertEqual(provider, "codex")
            # This would deadlock if the critic were still invoked while the
            # contract lock was held.  It also changes material_sequence, so
            # thread-a's model result must fail its final CAS.
            complete_write("thread-b", "two.py", "write-b")
            return {
                "verdict": "drift",
                "confidence": 0.99,
                "summary": "stale result must not pause",
                "violated_constraints": ["synthetic constraint"],
                "evidence": ["synthetic stale evidence"],
                "next_action": "pause_and_clarify",
            }

        context = finalize_host_turn(
            {
                "client": "codex",
                "session_id": "thread-a",
                "intent_contract": str(self.contract_path),
            },
            provider="codex",
            critic_runner=drifting_runner,
        )

        current = load_contract(self.contract_path)
        self.assertEqual(context, "")
        self.assertEqual(current["status"], "active")
        self.assertFalse(current["runtime"]["critic_checkpoints"][-1]["state_consistent"])
        self.assertEqual(
            current["runtime"]["critic_batches"][0]["session_id"],
            "thread-b",
        )

    def test_stop_drift_pauses_only_the_claimed_lane(self) -> None:
        contract = self.contract()
        contract["critic"]["enabled"] = True
        for session_id in ("thread-a", "thread-b"):
            guardian_module._upsert_task_lane_locked(
                contract,
                provider="codex",
                session_id=session_id,
                state="bound",
                source="test",
            )
        write_contract(self.contract_path, contract)
        started = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-a",
                "call_id": "write-a",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": "resume.md"},
            },
            phase="started",
            provider="codex",
        )
        GuardianSession(self.contract_path, provider="codex").observe(started)
        GuardianSession(self.contract_path, provider="codex").observe(
            dict(started, phase="completed", success=True)
        )

        context = finalize_host_turn(
            {
                "client": "codex",
                "session_id": "thread-a",
                "intent_contract": str(self.contract_path),
            },
            provider="codex",
            critic_runner=lambda *_args, **_kwargs: {
                "verdict": "drift",
                "confidence": 0.99,
                "summary": "concrete lane drift",
                "violated_constraints": ["事实不可改变"],
                "evidence": ["具体变更证据"],
                "next_action": "pause_and_clarify",
            },
        )

        current = load_contract(self.contract_path)
        self.assertIn("PAUSED current lane", context)
        self.assertIsNotNone(
            guardian_module._pause_state(
                current,
                provider="codex",
                session_id="thread-a",
            )
        )
        self.assertIsNone(
            guardian_module._pause_state(
                current,
                provider="codex",
                session_id="thread-b",
            )
        )
        sibling = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-b",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": "resume.md"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(evaluate_event(current, sibling).action, "allow")

    def test_prepare_proposal_bootstraps_without_claiming_human_authority(self) -> None:
        home = Path(self.temp.name) / "kb"
        path, proposal, digest, review = prepare_workspace_proposal(
            home,
            self.root,
            intent_id="discussion-review",
            objective="发布一条经过事实核验的设计讨论",
            acceptance_criteria=["发布后返回可访问链接", "不虚构数据"],
            mode="enforce",
            rationale="向维护者确认上下文预算设计",
            preserve=["自然开发者口吻", "事实准确"],
            reject=["夸大收益", "泄露本机路径"],
            allowed_paths=[],
        )

        active = load_contract(path)
        self.assertEqual(active["revision"], 1)
        self.assertEqual(active["mode"], "shadow")
        self.assertEqual(active["confirmed_by"], "unconfirmed")
        self.assertTrue(active["confirmation"]["required"])
        self.assertEqual(active["runtime"]["approved_proposal_digests"], [])
        self.assertTrue(proposal.is_file())
        self.assertEqual(review["proposal_digest"], digest)
        self.assertTrue(review["workspace_bootstrapped"])
        self.assertEqual(review["review"]["outcome"], "发布一条经过事实核验的设计讨论")
        self.assertEqual(
            review["review"]["observable_acceptance"],
            ["发布后返回可访问链接", "不虚构数据"],
        )
        self.assertEqual(review["review"]["preserve"], ["自然开发者口吻", "事实准确"])
        self.assertEqual(review["review"]["reject"], ["夸大收益", "泄露本机路径"])
        self.assertNotIn("approval_prompt", review)
        self.assertNotIn("human_choices", review)
        self.assertEqual(
            review["decision_surface"]["type"],
            "NativeDecisionUnavailable",
        )
        self.assertFalse(review["decision_surface"]["text_authority"])
        self.assertEqual(review["decision_surface"]["status"], "pending")
        self.assertEqual(
            review["technical_binding"]["proposal_digest"],
            digest,
        )
        self.assertEqual(
            review["decision_card"]["要完成的结果"],
            "发布一条经过事实核验的设计讨论",
        )
        self.assertEqual(review["decision_card"]["风险与恢复"]["风险"], "尚未判断")
        self.assertEqual(
            review["decision_card"]["执行权限边界"]["外部写入"],
            "当前可读方案内由监督器执行；扩大范围时在对话中确认",
        )
        self.assertNotIn(
            digest,
            json.dumps(review["decision_card"], ensure_ascii=False),
        )
        card_text = json.dumps(review["decision_card"], ensure_ascii=False).lower()
        self.assertNotIn("复制摘要", card_text)
        self.assertNotIn("外部终端", card_text)
        self.assertNotIn("copy digest", card_text)
        self.assertIn("remains pending", review["approval_requirement"])
        self.assertEqual(proposal_digest(review["digest_bound_contract"]), digest)
        stable_review = dict(review)
        stable_review.pop("workspace_bootstrapped")
        stable_review.pop("continuation")
        self.assertEqual(
            guardian_module.proposal_review_for_provider(
                proposal_review_for_digest(path, digest),
                "unknown",
            ),
            stable_review,
        )
        with self.assertRaisesRegex(IntentGuardianError, "not been approved"):
            apply_revision_proposal(path, proposal)

    def test_prepare_codex_proposal_exposes_only_native_decision_surface(self) -> None:
        home = Path(self.temp.name) / "kb-codex"
        _, _, digest, review = prepare_workspace_proposal(
            home,
            self.root,
            intent_id="codex-native-review",
            objective="只通过当前会话原生卡片确认",
            acceptance_criteria=["普通聊天文字不能产生授权"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
            provider="codex",
            session_id="thread-native-review",
        )

        self.assertEqual(review["proposal_digest"], digest)
        self.assertNotIn("approval_prompt", review)
        self.assertNotIn("human_choices", review)
        self.assertEqual(review["decision_surface"]["type"], "PermissionRequest")
        self.assertEqual(review["decision_surface"]["choices"], ["Allow", "Deny"])
        self.assertFalse(review["decision_surface"]["text_authority"])
        self.assertIn("current-session Allow/Deny", review["approval_requirement"])
        self.assertIn("Allow/Deny", review["continuation"]["next_action"])
        self.assertNotIn("批准当前方案", review["continuation"]["next_action"])

    def test_prepare_proposal_cli_replaces_manual_create_and_activate(self) -> None:
        home = Path(self.temp.name) / "kb-cli"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "prepare-proposal",
                "--intent-id",
                "one-step",
                "--objective",
                "只发布一条讨论",
                "--accept",
                "内容可核验",
                "--preserve",
                "自然措辞",
                "--reject",
                "重复发布",
                "--workspace",
                str(self.root),
                "--home",
                str(home),
                "--mode",
                "enforce",
                "--provider",
                "unknown",
                "--session-id",
                "cli-thread",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        review = json.loads(completed.stdout)
        self.assertEqual(review["schema"], "sulde-intent-proposal-review-v1")
        self.assertEqual(review["review"]["outcome"], "只发布一条讨论")
        self.assertEqual(review["continuation"]["status"], "ready")
        self.assertFalse(review["continuation"]["authority_transferred"])
        active = load_contract(active_contract_path(home, self.root))
        self.assertEqual(active["confirmed_by"], "unconfirmed")
        self.assertEqual(active["runtime"]["approval_receipts"], [])

        repeated = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "prepare-continuation",
                "--workspace",
                str(self.root),
                "--home",
                str(home),
                "--provider",
                "unknown",
                "--session-id",
                "cli-thread",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        repeated_summary = json.loads(repeated.stdout)
        self.assertEqual(
            repeated_summary["capsule_id"],
            review["continuation"]["capsule_id"],
        )

    def test_legacy_create_command_never_claims_human_confirmation(self) -> None:
        contract_path = Path(self.temp.name) / "legacy-create.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "create",
                "--intent-id",
                "opaque-copy",
                "--objective",
                "Agent supplied these words",
                "--accept",
                "human must still review",
                "--workspace",
                str(self.root),
                "--output",
                str(contract_path),
                "--mode",
                "enforce",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        contract = load_contract(contract_path)
        self.assertEqual(contract["confirmed_by"], "unconfirmed")
        self.assertTrue(contract["confirmation"]["required"])
        write = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": "note.md"}},
            phase="started",
            provider="codex",
        )
        self.assertEqual(evaluate_event(contract, write).action, "deny")

    def test_prepare_proposal_preserves_existing_live_workspace_lineage(self) -> None:
        home = Path(self.temp.name) / "kb-live"
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(
                {
                    "client": "codex",
                    "session_id": "thread-live",
                    "cwd": str(self.root),
                    "prompt": "先讨论发布内容",
                    "sulde_observation_source": "live_host_hook",
                },
                provider="codex",
            )
        path = active_contract_path(home, self.root)
        original_intent_id = load_contract(path)["intent_id"]
        prepared_path, _, _, review = prepare_workspace_proposal(
            home,
            self.root,
            intent_id="agent-suggested-label",
            objective="发布经过审阅的讨论",
            acceptance_criteria=["内容可核验"],
            mode="enforce",
        )
        self.assertEqual(prepared_path, path)
        self.assertFalse(review["workspace_bootstrapped"])
        self.assertEqual(review["intent_id"], original_intent_id)

    def test_noninteractive_cli_proposal_approval_is_retired(self) -> None:
        self.contract()
        _, digest = create_revision_proposal(
            self.contract_path,
            objective="只改结构",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "approve-proposal",
                digest,
                "--contract",
                str(self.contract_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("readable Allow/Deny decision surface", completed.stderr)
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["approved_proposal_digests"], [])
        self.assertEqual(current["runtime"]["approval_receipts"], [])

    def test_cli_or_synthetic_receipt_cannot_grant_proposal_authority(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="只改结构",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        approve_proposal(self.contract_path, digest, actor="human-cli")
        with self.assertRaisesRegex(IntentGuardianError, "live human decision receipt"):
            apply_revision_proposal(self.contract_path, proposal)

        current = load_contract(self.contract_path)
        current["runtime"]["approved_proposal_digests"] = []
        current["runtime"]["approval_receipts"] = []
        write_contract(self.contract_path, current)
        proposal, _ = create_revision_proposal(
            self.contract_path,
            objective="只改结构",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        context = observe_user_prompt(
            {
                "client": "codex",
                "session_id": "synthetic",
                "cwd": str(self.root),
                "intent_contract": str(self.contract_path),
                "prompt": "批准当前方案",
                "sulde_observation_source": "synthetic_smoke",
            },
            provider="codex",
        )
        self.assertIn("NATIVE_DECISION_REQUIRED", context)
        with self.assertRaisesRegex(IntentGuardianError, "not been approved"):
            apply_revision_proposal(self.contract_path, proposal)

    def test_noninteractive_cli_event_approval_is_retired(self) -> None:
        self.contract()
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "approve-event",
                "a" * 64,
                "--contract",
                str(self.contract_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("event digest approval is retired", completed.stderr)
        self.assertEqual(load_contract(self.contract_path)["approved_event_fingerprints"], [])

    def test_skill_requires_visible_review_and_never_delegates_bootstrap_cli(self) -> None:
        instructions = self.skill_path.read_text(encoding="utf-8")
        self.assertIn("prepare-proposal", instructions)
        self.assertIn("`decision_card` is for people", instructions)
        self.assertIn("never ask a\nperson to understand or copy them", instructions)
        self.assertIn("current conversation's native Allow/Deny surface", instructions)
        self.assertNotIn("On Codex, do not ask the user to type", instructions)
        self.assertIn("`native-decision-preview", instructions)
        self.assertIn("`command_argv`", instructions)
        self.assertIn("`description` verbatim", instructions)
        self.assertIn("`PermissionRequest` records the paired", instructions)
        self.assertIn("never request or store a persistent prefix approval", instructions)
        self.assertIn("agent-decide-proposal", instructions)
        self.assertIn("never ask the user to copy", instructions)
        self.assertIn("Never use `approve-proposal`", instructions)
        self.assertNotIn("give the human the exact\n`approve-proposal", instructions)

    def test_agent_can_prepare_or_show_but_cannot_approve_control_plane(self) -> None:
        self.contract()
        launcher = f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'}"
        for action in (
            "prepare-proposal",
            "prepare-continuation",
            "proposal-show",
            "propose-revision",
            "agent-decide-proposal",
            "apply-proposal",
            "pre-execution-proof-prepare",
            "pre-execution-proof-finalize",
            "release-completed-workspace",
            "finalize-workspace-cleanup",
        ):
            event = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": f"{launcher} {action} placeholder"},
                },
                phase="started",
            )
            self.assertEqual(event["effect"], "read", action)
            self.assertTrue(event["control_plane"], action)
            self.assertEqual(event["control_route"], "agent", action)
        for action in ("approve-proposal", "approve-event"):
            event = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": f"{launcher} {action} {'a' * 64}"},
                },
                phase="started",
            )
            self.assertTrue(event["control_plane"], action)
            self.assertEqual(event["control_route"], "human", action)
            decision = GuardianSession(self.contract_path).observe(event)
            self.assertEqual(decision.action, "deny")
            self.assertFalse(decision.pause)

    def test_codex_text_proposal_choice_is_non_authorizing(self) -> None:
        home = Path(self.temp.name) / "kb"
        payload = {
            "client": "codex",
            "session_id": "thread-approval",
            "cwd": str(self.root),
            "prompt": "start",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(payload, provider="codex")
            path = active_contract_path(home, self.root)
            proposal, digest = create_revision_proposal(
                path,
                objective="只改结构",
                acceptance_criteria=["事实不变"],
                mode="enforce",
                allowed_paths=["resume.md"],
            )
            payload["prompt"] = "批准当前方案"
            context = observe_user_prompt(payload, provider="codex")
            current = load_contract(path)

        self.assertIn("NATIVE_DECISION_REQUIRED action=approve-proposal", context)
        self.assertEqual(current["runtime"]["approval_receipts"], [])
        self.assertEqual(current["runtime"]["approved_proposal_digests"], [])
        self.assertEqual(current["runtime"]["pending_proposal_digest"], digest)
        with self.assertRaisesRegex(IntentGuardianError, "not been approved"):
            apply_revision_proposal(path, proposal)

    def test_non_codex_text_proposal_choice_is_also_non_authorizing(self) -> None:
        home = Path(self.temp.name) / "kb-non-codex"
        payload = {
            "client": "claude",
            "session_id": "thread-no-native-surface",
            "cwd": str(self.root),
            "prompt": "start",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(payload, provider="claude")
            path = active_contract_path(home, self.root)
            proposal, digest = create_revision_proposal(
                path,
                objective="只改结构",
                acceptance_criteria=["普通聊天不能产生授权"],
                mode="enforce",
                allowed_paths=["resume.md"],
            )
            payload["prompt"] = "批准当前方案"
            context = observe_user_prompt(payload, provider="claude")
            current = load_contract(path)

        self.assertIn("NATIVE_DECISION_REQUIRED action=approve-proposal", context)
        self.assertIn("decision remains pending", context)
        self.assertEqual(current["runtime"]["approval_receipts"], [])
        self.assertEqual(current["runtime"]["approved_proposal_digests"], [])
        self.assertEqual(current["runtime"]["pending_proposal_digest"], digest)
        with self.assertRaisesRegex(IntentGuardianError, "not been approved"):
            apply_revision_proposal(path, proposal)

    def test_legacy_event_authority_is_migrated_before_next_task_epoch(self) -> None:
        contract = self.contract()
        stale_fingerprint = "b" * 64
        contract["approved_event_fingerprints"] = [stale_fingerprint]
        self.contract_path.write_text(
            json.dumps(contract, ensure_ascii=False), encoding="utf-8"
        )
        migrated = load_contract(self.contract_path)
        self.assertEqual(migrated["approved_event_fingerprints"], [])
        self.assertEqual(
            migrated["runtime"]["legacy_event_authority_migrations"], 1
        )
        prior_epoch = migrated["task_epoch"]
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="只改结构",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        self.live_approve_proposal(self.contract_path, digest)
        applied = load_contract(self.contract_path)
        self.assertNotEqual(applied["task_epoch"], prior_epoch)
        self.assertEqual(applied["approved_event_fingerprints"], [])

    def test_human_can_reject_the_current_readable_proposal(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="改成营销式表达",
            acceptance_criteria=["文案更强势"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )

        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="reject",
            target="current",
            provider="codex",
            session_id="human-reject",
        )
        observed = observe_native_permission_request(
            self.native_permission_payload(
                preview,
                session_id="human-reject",
            ),
            provider="codex",
        )
        result = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="reject",
            target=digest,
            provider="codex",
            session_id="human-reject",
        )

        current = load_contract(self.contract_path)
        self.assertEqual(observed["action"], "defer")
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(current["runtime"]["pending_proposal_digest"], "")
        self.assertEqual(current["runtime"]["approved_proposal_digests"], [])
        decision = current["runtime"]["proposal_decisions"][-1]
        self.assertEqual(decision["authority"], "human")
        self.assertEqual(decision["verdict"], "reject")
        with self.assertRaisesRegex(IntentGuardianError, "no longer the current"):
            apply_revision_proposal(self.contract_path, proposal)

    def test_native_choice_applies_only_the_current_proposal(self) -> None:
        self.contract()
        first, first_digest = create_revision_proposal(
            self.contract_path,
            objective="第一个候选方案",
            acceptance_criteria=["不应被后续批准误用"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        self.live_approve_proposal(
            self.contract_path,
            first_digest,
            session_id="first-choice",
        )
        after_first = load_contract(self.contract_path)
        first_receipt_id = after_first["runtime"][
            "approval_receipts"
        ][-1]["receipt_id"]
        self.assertEqual(after_first["objective"], "第一个候选方案")
        second, second_digest = create_revision_proposal(
            self.contract_path,
            objective="用户最后看到的当前方案",
            acceptance_criteria=["只应用最后方案"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )

        result = self.live_approve_proposal(
            self.contract_path,
            second_digest,
            session_id="first-choice",
        )
        current = load_contract(self.contract_path)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(current["objective"], "用户最后看到的当前方案")
        self.assertNotIn(first_digest, current["runtime"]["approved_proposal_digests"])
        consumed_receipt = next(
            row
            for row in current["runtime"]["approval_receipts"]
            if row["receipt_id"] == first_receipt_id
        )
        self.assertTrue(consumed_receipt["consumed_at"])
        with self.assertRaisesRegex(IntentGuardianError, "base revision is stale|no longer the current"):
            apply_revision_proposal(self.contract_path, first)
        with self.assertRaisesRegex(IntentGuardianError, "base revision is stale|no longer the current"):
            apply_revision_proposal(self.contract_path, second)

    def test_agent_decision_applies_only_bounded_low_risk_local_proposal(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="格式化一个确定的本地配置文件",
            acceptance_criteria=["格式检查通过", "diff 仅包含空白规范化"],
            mode="enforce",
            rationale="消除确定性的格式漂移",
            preserve=["字段和值不变"],
            reject=["不得修改语义"],
            allowed_paths=["config.json"],
            decision_route="agent",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="放弃 config.json 的未提交格式化差异",
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(review["decision_route"], "agent")
        self.assertEqual(
            review["decision_card"]["系统分流"],
            "Agent 可按受限规则决断",
        )

        with mock.patch.dict(os.environ, {"SULDE_GUARDIAN_STREAM_OWNER": "1"}):
            with self.assertRaisesRegex(IntentGuardianError, "managed L3 child"):
                self.codex_agent_decide(
                    self.contract_path,
                    digest,
                    rationale="子进程不得自批",
                    evidence=["不应消费"],
                    session_id="agent-session",
                )
        result = self.codex_agent_decide(
            self.contract_path,
            digest,
            rationale="所有资格条件均由不可变提案字段满足",
            evidence=["仅 config.json", "外部写入和破坏性操作均未放行"],
            session_id="agent-session",
        )
        self.assertEqual(result["decision"]["authority"], "agent-policy")
        self.assertEqual(result["receipt"]["schema"], "sulde-decision-receipt-v2")
        self.assertNotIn("human", result["receipt"]["schema"])
        applied = apply_revision_proposal(self.contract_path, proposal)
        self.assertEqual(applied["confirmed_by"], "agent-policy-decision")
        self.assertEqual(applied["applied_decision_authority"], "agent-policy")
        self.assertEqual(
            applied["applied_by"],
            "agent-after-agent-policy-decision",
        )
        self.assertEqual(applied["applied_approval_channel"], "agent-policy")
        self.assertEqual(
            applied["applied_approval_source"],
            "deterministic_agent_gate",
        )
        report = guardian_report(self.contract_path)
        self.assertEqual(report["proposal_decisions"]["agent_approved"], 1)
        self.assertFalse(report["proposal_decisions"]["pending"])
        consumed = next(
            row
            for row in applied["runtime"]["approval_receipts"]
            if row["receipt_id"] == result["receipt"]["receipt_id"]
        )
        self.assertEqual(
            consumed["consumed_by"],
            "agent-after-agent-policy-decision",
        )

    def test_unattended_safe_proposal_routes_to_agent_before_human_prompt(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="规范化一个确定的本地配置文件",
            acceptance_criteria=["格式检查通过", "字段和值保持不变"],
            mode="enforce",
            rationale="消除可机器验证的格式漂移",
            preserve=["字段和值"],
            reject=["不得改变语义"],
            allowed_paths=["config.json"],
            decision_route="human",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 config.json 的未提交差异",
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(review["decision_route"], "agent")
        self.assertIn("弹出人工确认前通过", review["decision_card"]["无人值守策略"])
        codex_review = guardian_module.proposal_review_for_provider(
            review, "codex"
        )
        self.assertEqual(
            codex_review["decision_surface"]["type"],
            "AgentPolicy",
        )
        self.assertFalse(
            codex_review["decision_surface"]["human_prompt_presented"]
        )
        self.assertEqual(
            [
                row
                for row in load_approval_projection(self.contract_path)[
                    "requests"
                ].values()
                if row["kind"] == "proposal"
            ],
            [],
        )
        decided = self.codex_agent_decide(
            self.contract_path,
            digest,
            session_id="native-review",
            rationale="安全门在任何人工确认框出现前完成",
            evidence=["确定性低风险", "精确本地路径", "有回滚且无费用"],
        )
        self.assertEqual(decided["decision"]["authority"], "agent-policy")
        applied = apply_revision_proposal(self.contract_path, proposal)
        self.assertEqual(applied["applied_decision_authority"], "agent-policy")

        late = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(late["status"], "already_agent_decided")
        self.assertFalse(late["authority_transferred"])

    def test_silence_after_permission_prompt_never_overrides_possible_deny(self) -> None:
        self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="规范化一个确定的本地配置文件",
            acceptance_criteria=["格式检查通过"],
            mode="enforce",
            allowed_paths=["config.json"],
            decision_route="human",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            unattended_policy="wait",
            rollback="恢复 config.json 的未提交差异",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        observe_native_permission_request(
            self.native_permission_payload(preview), provider="codex"
        )
        request = [
            row
            for row in load_approval_projection(self.contract_path)[
                "requests"
            ].values()
            if row.get("source") == "codex_permission_request"
        ][0]
        reassess_at = datetime.fromisoformat(request["reassess_at"])
        expires_at = datetime.fromisoformat(request["expires_at"])
        grace_seconds = (
            reassess_at - datetime.fromisoformat(request["asked_at"])
        ).total_seconds()
        self.assertGreater(grace_seconds, 299)
        self.assertLessEqual(grace_seconds, 300)
        self.assertGreater((expires_at - reassess_at).total_seconds(), 23 * 3600)
        self.force_native_request_timing(
            reassess_at="2000-01-01T00:00:00+00:00"
        )
        self.assertEqual(
            guardian_report(self.contract_path)["approval_requests"][
                "reassess_due"
            ],
            1,
        )
        reassessed = reassess_unattended_proposal(
            self.contract_path,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(reassessed["status"], "remind_and_wait")
        after_reassessment = load_approval_projection(self.contract_path)[
            "requests"
        ][request["request_id"]]
        self.assertEqual(after_reassessment["status"], "asked")
        self.assertIsNone(after_reassessment["outcome"])
        self.assertEqual(
            load_contract(self.contract_path)["runtime"][
                "pending_proposal_digest"
            ],
            digest,
        )
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["approval_receipts"],
            [],
        )
        # Five minutes elapsed, but the durable human question remains live.
        late = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(late["status"], "applied")
        self.assertEqual(
            load_contract(self.contract_path)["applied_decision_authority"],
            "human",
        )
        decided_request = load_approval_projection(self.contract_path)[
            "requests"
        ][request["request_id"]]
        self.assertEqual(decided_request["status"], "decided")
        self.assertEqual(decided_request["outcome"], "allow")
        self.assertTrue(decided_request.get("typed", False))
        self.assertEqual(
            load_contract(self.contract_path)["runtime"][
                "pending_proposal_digest"
            ],
            "",
        )

    def test_native_click_after_durable_ttl_returns_structured_expiry(self) -> None:
        self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="等待人工检查本地配置",
            acceptance_criteria=["人工卡片仍是唯一权限来源"],
            mode="enforce",
            allowed_paths=["config.json"],
            decision_route="human",
            unattended_policy="wait",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        observed = observe_native_permission_request(
            self.native_permission_payload(preview), provider="codex"
        )
        self.force_native_request_timing(
            reassess_at="2000-01-01T00:00:00+00:00",
            expires_at="2000-01-01T00:05:00+00:00",
        )
        result = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(result["status"], "approval_expired")
        self.assertEqual(result["request_id"], observed["request_id"])
        self.assertTrue(result["requires_fresh_permission_request"])
        self.assertFalse(result["authority_transferred"])
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["approval_receipts"],
            [],
        )
        refreshed = observe_native_permission_request(
            self.native_permission_payload(preview), provider="codex"
        )
        self.assertEqual(refreshed["action"], "defer", refreshed)
        self.assertNotEqual(refreshed["request_id"], observed["request_id"])
        retried = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(retried["status"], "applied")

    def test_unattended_reassessment_fails_closed_on_sensitive_scope_and_drift(self) -> None:
        self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="调整守卫内部规则",
            acceptance_criteria=["守卫测试通过"],
            mode="enforce",
            allowed_paths=["scripts/kb/intent_guardian.py"],
            decision_route="human",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复守卫文件",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        observed = observe_native_permission_request(
            self.native_permission_payload(preview), provider="codex"
        )
        self.force_native_request_timing(
            reassess_at="2000-01-01T00:00:00+00:00"
        )
        blocked = reassess_unattended_proposal(
            self.contract_path,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(blocked["status"], "remind_and_wait")
        self.assertTrue(blocked["agent_ineligible_reasons"])
        request = load_approval_projection(self.contract_path)["requests"][
            observed["request_id"]
        ]
        self.assertEqual(request["status"], "asked")
        self.assertIsNone(request["outcome"])
        self.assertEqual(
            load_contract(self.contract_path)["runtime"]["approval_receipts"],
            [],
        )
        self.assertEqual(
            load_contract(self.contract_path)["runtime"][
                "pending_proposal_digest"
            ],
            digest,
        )

        current = load_contract(self.contract_path)
        current["runtime"]["material_sequence"] += 1
        write_contract(self.contract_path, current)
        drifted = reassess_unattended_proposal(
            self.contract_path,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(drifted["status"], "cancel_and_rerender")
        cancelled = load_approval_projection(self.contract_path)["requests"][
            observed["request_id"]
        ]
        self.assertEqual(cancelled["status"], "decided")
        self.assertEqual(cancelled["outcome"], "cancelled")
        after_drift = load_contract(self.contract_path)
        self.assertEqual(after_drift["runtime"]["approval_receipts"], [])
        self.assertEqual(after_drift["runtime"]["pending_proposal_digest"], "")
        late = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(late["status"], "superseded")
        self.assertFalse(late["authority_transferred"])

    def test_settled_effect_cancels_stale_question_but_preserves_live_one(self) -> None:
        contract = self.contract()
        self.declare_effects(self.contract_path, "external_write")
        payload = {
            "client": "codex",
            "session_id": "stale-effect-question",
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://stale-question", "content": "new"},
        }
        started = normalize_hook_event(payload, phase="started", provider="codex")
        session = GuardianSession(self.contract_path)
        self.assertEqual(session.observe(started).action, "allow")
        self.assertEqual(
            session.observe(dict(started, phase="completed", success=False)).action,
            "allow",
        )
        effect_projection = load_intervention_projection(self.contract_path)
        intervention_id = next(iter(effect_projection["interventions"]))
        intervention = effect_projection["interventions"][intervention_id]
        attempt = effect_projection["attempts"][intervention["attempt_id"]]
        card = guardian_module._effect_intervention_card(intervention, attempt)
        request = guardian_module.ask_approval(
            self.contract_path,
            intent_id=contract["intent_id"],
            intent_revision=contract["revision"],
            kind="effect-intervention",
            target=intervention_id,
            provider="codex",
            session_id="stale-effect-question",
            source=guardian_module.NATIVE_PERMISSION_SOURCE,
            card=card,
            workspace=contract["workspace_root"],
            route="human",
        )

        GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="stale-effect-question",
        )
        self.assertEqual(
            load_approval_projection(self.contract_path)["requests"][
                request["request_id"]
            ]["status"],
            "asked",
        )

        resolve_effect_intervention(
            self.contract_path,
            intervention_id,
            decision="confirmed_failed",
            evidence="synthetic failure evidence",
            actor="test-human",
        )
        GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="stale-effect-question",
        )
        cancelled = load_approval_projection(self.contract_path)["requests"][
            request["request_id"]
        ]
        self.assertEqual(cancelled["status"], "decided")
        self.assertEqual(cancelled["outcome"], "cancelled")
        self.assertEqual(
            guardian_module.approval_pair_summary(self.contract_path)["open"], 0
        )
        self.assertEqual(
            guardian_module.reconcile_obsolete_approval_requests(
                self.contract_path
            ),
            0,
        )

    def test_superseded_proposal_question_is_cancelled_at_guardian_boundary(self) -> None:
        contract = self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="等待人工检查一个本地文件",
            acceptance_criteria=["旧问题不得在提案消失后继续开放"],
            mode="enforce",
            allowed_paths=["config.json"],
            decision_route="human",
            unattended_policy="wait",
        )
        card = proposal_review_for_digest(self.contract_path, digest)[
            "decision_card"
        ]
        request = guardian_module.ask_approval(
            self.contract_path,
            intent_id=contract["intent_id"],
            intent_revision=contract["revision"],
            kind="proposal",
            target=digest,
            provider="codex",
            session_id="stale-proposal-question",
            source=guardian_module.NATIVE_PERMISSION_SOURCE,
            card=card,
            workspace=contract["workspace_root"],
            route="human",
        )
        current = load_contract(self.contract_path)
        current["runtime"]["pending_proposal_digest"] = ""
        write_contract(self.contract_path, current)

        GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="stale-proposal-question",
        )
        cancelled = load_approval_projection(self.contract_path)["requests"][
            request["request_id"]
        ]
        self.assertEqual(cancelled["status"], "decided")
        self.assertEqual(cancelled["outcome"], "cancelled")

    def test_concurrent_human_outcome_wins_over_stale_question_cleanup(self) -> None:
        contract = self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="等待人工检查并发决定",
            acceptance_criteria=["人工结果不得被清理器覆盖"],
            mode="enforce",
            allowed_paths=["config.json"],
            decision_route="human",
            unattended_policy="wait",
        )
        card = proposal_review_for_digest(self.contract_path, digest)[
            "decision_card"
        ]
        request = guardian_module.ask_approval(
            self.contract_path,
            intent_id=contract["intent_id"],
            intent_revision=contract["revision"],
            kind="proposal",
            target=digest,
            provider="codex",
            session_id="cleanup-race",
            source=guardian_module.NATIVE_PERMISSION_SOURCE,
            card=card,
            workspace=contract["workspace_root"],
            route="human",
        )
        current = load_contract(self.contract_path)
        current["runtime"]["pending_proposal_digest"] = ""
        write_contract(self.contract_path, current)

        def human_decides_first(
            path: Path,
            request_id: str,
            *,
            actor: str,
        ) -> dict[str, object]:
            guardian_module.decide_approval(
                path,
                kind="proposal",
                target=digest,
                outcome="rejected",
                provider="codex",
                session_id="cleanup-race",
                actor="native-human",
                card=card,
                workspace=contract["workspace_root"],
                route="human",
                source=guardian_module.NATIVE_PERMISSION_SOURCE,
            )
            raise guardian_module.ApprovalInvariantError(
                "approval cancellation targets an already decided question"
            )

        with mock.patch.object(
            guardian_recovery,
            "cancel_approval_request",
            side_effect=human_decides_first,
        ):
            self.assertEqual(
                guardian_module.reconcile_obsolete_approval_requests(
                    self.contract_path
                ),
                0,
            )
        decided = load_approval_projection(self.contract_path)["requests"][
            request["request_id"]
        ]
        self.assertEqual(decided["status"], "decided")
        self.assertEqual(decided["outcome"], "rejected")

    def test_agent_can_bootstrap_and_decide_without_a_human_ceremony(self) -> None:
        home = Path(self.temp.name) / "agent-bootstrap-home"
        path, proposal, digest, review = prepare_workspace_proposal(
            home,
            self.root,
            intent_id="deterministic-bootstrap",
            objective="规范化一个本地 JSON fixture",
            acceptance_criteria=["JSON 解析通过", "字段和值不变"],
            mode="enforce",
            rationale="执行确定性格式修复",
            preserve=["业务字段和值"],
            reject=["不得增加或删除字段"],
            allowed_paths=["tests/fixtures/example.json"],
            decision_route="auto",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 fixture 的未提交差异",
        )
        self.assertTrue(review["workspace_bootstrapped"])
        self.assertEqual(review["decision_route"], "agent")
        self.codex_agent_decide(
            path,
            digest,
            rationale="所有结构化门禁均通过",
            evidence=["单文件范围", "无外部效果", "有回滚方法"],
            session_id="bootstrap-agent",
        )
        applied = apply_revision_proposal(path, proposal)
        self.assertEqual(applied["mode"], "enforce")
        self.assertEqual(applied["applied_decision_authority"], "agent-policy")

    def test_bounded_local_memory_work_does_not_force_external_route(self) -> None:
        self.contract()
        _, digest = create_revision_proposal(
            self.contract_path,
            objective="更新一份本地问题卡并记录受限 memory_annotate 关系",
            acceptance_criteria=[
                "问题卡 lint 通过",
                "memory_annotate 满足固定 schema、批量限额和 SQLite 独立验证",
            ],
            mode="enforce",
            rationale="把可机器证明的本机记忆闭环留在本地写入权限内",
            allowed_paths=["knowledge/anti-patterns/example.md"],
            decision_route="auto",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="撤销问题卡差异并删除本轮精确关系",
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(review["decision_route"], "agent")
        self.assertFalse(
            any(
                "外部写入" in reason
                for reason in review["decision_card"]["不能由 Agent 决断的原因"]
            )
        )

    def test_agent_read_only_decision_removes_latent_local_write_authority(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="读取并报告本地状态",
            acceptance_criteria=["报告包含可核验文件位置", "不发布任何内容"],
            mode="enforce",
            rationale="只做诊断，不修改文件",
            decision_route="agent",
            intent_kind="deterministic",
            risk="low",
            effects=["read"],
            reversibility="reversible",
            cost="none",
            rollback="无需回滚，因为不产生写入",
        )
        candidate = load_contract(proposal)
        self.assertFalse(candidate["permissions"]["local_write"])
        self.assertEqual(candidate["decision"]["selected_route"], "agent")
        self.codex_agent_decide(
            self.contract_path,
            digest,
            rationale="提案执行权限已收窄为只读",
            evidence=["permissions.local_write=false"],
            session_id="read-only-agent",
        )
        applied = apply_revision_proposal(self.contract_path, proposal)
        write = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": "unexpected.md"}},
            phase="started",
            provider="codex",
        )
        self.assertEqual(evaluate_event(applied, write).action, "deny")

    def test_local_release_artifact_noun_does_not_become_an_external_publish_action(self) -> None:
        self.contract()
        _, digest = create_revision_proposal(
            self.contract_path,
            objective="核对已安装发布件的本地摘要",
            acceptance_criteria=["发布件摘要与源码一致", "不发布任何内容"],
            mode="enforce",
            rationale="证明本地发布件能够被只读检查",
            allowed_paths=["README.md"],
            decision_route="auto",
            intent_kind="deterministic",
            risk="low",
            effects=["read"],
            reversibility="reversible",
            cost="none",
            rollback="无需回滚，因为不产生写入",
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(review["decision_route"], "agent")
        self.assertFalse(
            any(
                "外部写入或公开传播" in reason
                for reason in review["decision_card"]["不能由 Agent 决断的原因"]
            )
        )

    def test_post_only_hook_term_does_not_become_a_public_post_action(self) -> None:
        self.contract()
        _, digest = create_revision_proposal(
            self.contract_path,
            objective="记录 Post-only Hook 缺口的本地诊断",
            acceptance_criteria=["PostToolUse 证据写入本地报告"],
            mode="enforce",
            rationale="区分执行前保护与 Post-only 事后观察",
            allowed_paths=["reports/hook-gap.json"],
            decision_route="auto",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="删除本轮精确诊断报告",
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(review["decision_route"], "agent")
        self.assertFalse(
            any(
                "外部写入或公开传播" in reason
                for reason in review["decision_card"]["不能由 Agent 决断的原因"]
            )
        )

    def test_agent_decision_falls_back_to_human_for_subjective_external_work(self) -> None:
        self.contract()
        _, digest = create_revision_proposal(
            self.contract_path,
            objective="按个人表达发布一条公开讨论",
            acceptance_criteria=["公开页面可访问"],
            mode="enforce",
            rationale="与外部维护者沟通",
            allowed_paths=["draft.md"],
            decision_route="agent",
            intent_kind="subjective",
            risk="low",
            effects=["external_write"],
            reversibility="compensatable",
            cost="none",
            rollback="删除讨论并保留审计记录",
        )
        review = proposal_review_for_digest(self.contract_path, digest)
        self.assertEqual(review["decision_route"], "human")
        reasons = review["decision_card"]["不能由 Agent 决断的原因"]
        self.assertTrue(any("确定性任务" in reason for reason in reasons))
        self.assertTrue(any("本地读取/写入之外" in reason for reason in reasons))
        with self.assertRaisesRegex(IntentGuardianError, "routed to human"):
            self.codex_agent_decide(
                self.contract_path,
                digest,
                rationale="Agent 想自行发布",
                evidence=["仅有 Agent 自述"],
                session_id="subjective-agent",
            )

        _, sensitive_digest = create_revision_proposal(
            self.contract_path,
            objective="修改自动发布工作流",
            acceptance_criteria=["YAML 可以解析"],
            mode="enforce",
            rationale="调整自动化",
            allowed_paths=[".github/workflows/release.yml"],
            decision_route="agent",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复工作流文件",
        )
        sensitive_review = proposal_review_for_digest(
            self.contract_path,
            sensitive_digest,
        )
        self.assertEqual(sensitive_review["decision_route"], "human")
        self.assertTrue(
            any(
                "治理、发布、自动化或敏感路径" in reason
                for reason in sensitive_review["decision_card"]["不能由 Agent 决断的原因"]
            )
        )

    def test_agent_decision_cli_records_distinct_nonhuman_authority(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="更新单个本地 fixture",
            acceptance_criteria=["定向测试通过"],
            mode="enforce",
            rationale="保持 fixture 与确定性 schema 一致",
            allowed_paths=["tests/fixtures/example.json"],
            decision_route="auto",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复该 fixture 的未提交差异",
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "agent-decide-proposal",
                digest,
                "--contract",
                str(self.contract_path),
                "--provider",
                "codex",
                "--session-id",
                "agent-cli-session",
                "--rationale",
                "不可变提案满足全部低风险条件",
                "--evidence",
                "写入范围只有一个 fixture",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env={
                **os.environ,
                "CODEX_THREAD_ID": "agent-cli-session",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["decision"]["authority"], "agent-policy")
        applied = apply_revision_proposal(self.contract_path, proposal)
        self.assertEqual(applied["applied_decision_authority"], "agent-policy")

    def test_user_prompt_ignores_opaque_digest_approval_without_blocking(self) -> None:
        home = Path(self.temp.name) / "kb"
        payload = {
            "client": "codex",
            "session_id": "thread",
            "cwd": str(self.root),
            "prompt": "start",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(payload, provider="codex")
            path = active_contract_path(home, self.root)
            payload["prompt"] = "批准意图提案 " + "a" * 64
            context = observe_user_prompt(payload, provider="codex")
            current = load_contract(path)

        self.assertIn("LEGACY_TEXT_CONTROL_IGNORED", context)
        self.assertEqual(current["runtime"]["approved_proposal_digests"], [])
        self.assertEqual(current["runtime"]["approval_receipts"], [])

    def test_approved_digest_without_receipt_cannot_apply(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="只改结构",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        contract = load_contract(self.contract_path)
        contract["runtime"]["approved_proposal_digests"].append(digest)
        write_contract(self.contract_path, contract)

        with self.assertRaisesRegex(IntentGuardianError, "decision receipt"):
            apply_revision_proposal(self.contract_path, proposal)

    def test_prompt_observation_distinguishes_live_and_synthetic_sources(self) -> None:
        home = Path(self.temp.name) / "kb"
        payload = {
            "client": "codex",
            "session_id": "synthetic",
            "cwd": str(self.root),
            "prompt": "start",
            "sulde_observation_source": "synthetic_smoke",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(payload, provider="codex")
            path = active_contract_path(home, self.root)
            payload.update(
                {
                    "session_id": "live",
                    "prompt": "continue",
                    "sulde_observation_source": "live_host_hook",
                }
            )
            observe_user_prompt(payload, provider="codex")
            live_path = guardian_module.session_contract_path(home, "codex", "live")
            synthetic_observations = load_contract(path)["runtime"]["host_observations"]
            live_observations = load_contract(live_path)["runtime"]["host_observations"]

        self.assertEqual(
            [row["source"] for row in synthetic_observations],
            ["synthetic_smoke"],
        )
        self.assertEqual(
            [row["source"] for row in live_observations],
            ["live_host_hook"],
        )

    def test_new_session_gets_independent_contract_in_same_workspace(self) -> None:
        home = Path(self.temp.name) / "kb-task-lanes"
        owner_prompt = {
            "client": "codex",
            "session_id": "task-owner",
            "cwd": str(self.root),
            "prompt": "检查当前模块的状态机",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(
            os.environ,
            {"SULDE_KB_HOME": str(home)},
            clear=False,
        ):
            owner_context = observe_user_prompt(owner_prompt, provider="codex")
            path = active_contract_path(home, self.root)
            new_prompt = "改成发布流水线任务"
            new_context = observe_user_prompt(
                {
                    **owner_prompt,
                    "session_id": "another-terminal",
                    "prompt": new_prompt,
                },
                provider="codex",
            )

            current = load_contract(path)
            session_path = guardian_module.session_contract_path(
                home, "codex", "another-terminal"
            )
            isolated = load_contract(session_path)
            self.assertIn("ACTIVE", owner_context)
            self.assertIn("ACTIVE", new_context)
            self.assertEqual(current["objective"], owner_prompt["prompt"])
            self.assertEqual(isolated["objective"], new_prompt)
            self.assertNotEqual(isolated["task_epoch"], current["task_epoch"])
            self.assertFalse(isolated["runtime"]["open_events"])
            self.assertFalse(isolated["runtime"]["pending_verifications"])
            self.assertFalse(isolated["continuation"]["grants"])

            material = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "another-terminal",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(self.root / "resume.md")},
                },
                phase="started",
                provider="codex",
            )
            allowed = GuardianSession(session_path).observe(material)
            self.assertEqual(allowed.action, "allow")

            read = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "another-terminal",
                    "tool_name": "Read",
                    "tool_input": {"file_path": str(self.root / "resume.md")},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(GuardianSession(session_path).observe(read).action, "allow")

            rebound = observe_user_prompt(
                {
                    **owner_prompt,
                    "session_id": "another-terminal",
                    "intent_contract": str(path),
                    "prompt": "显式续接当前任务",
                },
                provider="codex",
            )
            self.assertIn("ACTIVE", rebound)
            self.assertEqual(load_contract(session_path)["objective"], new_prompt)
            self.assertEqual(GuardianSession(session_path).observe(material).action, "allow")

    def test_new_session_continues_only_after_exact_native_allow(self) -> None:
        self.contract()
        seeded = load_contract(self.contract_path)
        seeded["applied_proposal_digest"] = "a" * 64
        # A proposal for the next revision is not authority and must not stop
        # a new lane from joining the currently approved task.
        seeded["runtime"]["pending_proposal_digest"] = "b" * 64
        owner = guardian_module._upsert_task_lane_locked(
            seeded,
            provider="codex",
            session_id="task-owner",
            state="bound",
            source="approved_revision",
            proposal_digest="a" * 64,
            prompt_sha256="1" * 64,
            task_instance_id="owner-task",
            # Upgrade compatibility: old runtimes wrote false here even for
            # the exact lane that applied the current revision.
            continuation_eligible=False,
        )
        reviewer = guardian_module._upsert_task_lane_locked(
            seeded,
            provider="codex",
            session_id="new-session",
            state="review_required",
            source="workspace_discovery",
            prompt_sha256="2" * 64,
            pending_task_instance_id="continued-task",
            continuation_eligible=False,
        )
        write_contract(self.contract_path, seeded)

        material = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "new-session",
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.root / "resume.md")},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(
            GuardianSession(self.contract_path).observe(material).action,
            "deny",
        )
        before = load_contract(self.contract_path)
        authority_before = {
            key: json.loads(json.dumps(before["runtime"][key]))
            for key in (
                "authorized_events",
                "continuation_uses",
                "open_events",
                "pending_verifications",
            )
        }
        preview = native_decision_preview(
            self.contract_path,
            kind="task-continuation",
            decision="approve",
            target="current",
            provider="codex",
            session_id="new-session",
        )
        self.assertEqual(
            preview["decision_card"]["operation_id"], "task-continuation"
        )
        self.assertIn("不继承旧会话", preview["description"])
        self.assertEqual(
            observe_native_permission_request(
                self.native_permission_payload(
                    preview,
                    session_id="another-session",
                ),
                provider="codex",
            )["action"],
            "deny",
        )
        observed = observe_native_permission_request(
            self.native_permission_payload(
                preview,
                session_id="new-session",
            ),
            provider="codex",
        )
        self.assertEqual(observed["action"], "defer")
        result = execute_native_decision(
            self.contract_path,
            kind="task-continuation",
            decision="approve",
            target=preview["target"],
            provider="codex",
            session_id="new-session",
        )
        self.assertEqual(result["status"], "applied")

        continued = load_contract(self.contract_path)
        self.assertEqual(
            continued["runtime"]["pending_proposal_digest"],
            "b" * 64,
        )
        lane = guardian_module._task_lane(
            continued,
            provider="codex",
            session_id="new-session",
        )
        self.assertEqual(lane["state"], "bound")
        self.assertEqual(lane["source"], "native_session_continuation")
        self.assertEqual(lane["task_instance_id"], "continued-task")
        self.assertNotEqual(lane["continuation_token"], owner["continuation_token"])
        self.assertEqual(reviewer["state"], "review_required")
        self.assertEqual(len(continued["runtime"]["task_continuations"]), 1)
        continuation = continued["runtime"]["task_continuations"][0]
        self.assertFalse(continuation["authority_transferred"])
        self.assertEqual(continuation["target"], preview["target"])
        for key, value in authority_before.items():
            self.assertEqual(continued["runtime"][key], value)
        self.assertEqual(
            GuardianSession(self.contract_path).observe(material).action,
            "allow",
        )
        outside = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "new-session",
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.root / "backend.txt")},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(
            GuardianSession(self.contract_path).observe(outside).action,
            "allow",
        )
        tampered = load_contract(self.contract_path)
        tampered["runtime"]["task_continuations"][0][
            "target_lane_sha256"
        ] = "0" * 64
        with self.assertRaisesRegex(
            IntentGuardianError,
            "target lane digest",
        ):
            write_contract(self.contract_path, tampered)
        with self.assertRaisesRegex(
            IntentGuardianError,
            "not awaiting task continuation review",
        ):
            native_decision_preview(
                self.contract_path,
                kind="task-continuation",
                decision="approve",
                target=preview["target"],
                provider="codex",
                session_id="new-session",
            )

    def test_task_continuation_does_not_upgrade_an_arbitrary_ineligible_lane(self) -> None:
        self.contract()
        seeded = load_contract(self.contract_path)
        seeded["applied_proposal_digest"] = "b" * 64
        guardian_module._upsert_task_lane_locked(
            seeded,
            provider="codex",
            session_id="untrusted-bound-lane",
            state="bound",
            source="workspace_discovery",
            proposal_digest="b" * 64,
            continuation_eligible=False,
        )
        guardian_module._upsert_task_lane_locked(
            seeded,
            provider="codex",
            session_id="new-session",
            state="review_required",
            source="workspace_discovery",
            continuation_eligible=False,
        )
        write_contract(self.contract_path, seeded)
        with self.assertRaisesRegex(
            IntentGuardianError,
            "no bound Codex source lane eligible",
        ):
            native_decision_preview(
                self.contract_path,
                kind="task-continuation",
                decision="approve",
                target="current",
                provider="codex",
                session_id="new-session",
            )

    def test_task_continuation_fails_closed_on_world_drift_and_recovers_after_crash(self) -> None:
        self.contract()
        seeded = load_contract(self.contract_path)
        guardian_module._upsert_task_lane_locked(
            seeded,
            provider="codex",
            session_id="task-owner",
            state="bound",
            source="workspace_discovery",
            prompt_sha256="3" * 64,
            continuation_eligible=True,
        )
        guardian_module._upsert_task_lane_locked(
            seeded,
            provider="codex",
            session_id="new-session",
            state="review_required",
            source="workspace_discovery",
            prompt_sha256="4" * 64,
            continuation_eligible=False,
        )
        write_contract(self.contract_path, seeded)
        stale = native_decision_preview(
            self.contract_path,
            kind="task-continuation",
            decision="approve",
            target="current",
            provider="codex",
            session_id="new-session",
        )
        drifted = load_contract(self.contract_path)
        drifted["runtime"]["material_sequence"] += 1
        write_contract(self.contract_path, drifted)
        self.assertEqual(
            observe_native_permission_request(
                self.native_permission_payload(
                    stale,
                    session_id="new-session",
                ),
                provider="codex",
            )["action"],
            "deny",
        )

        fresh = native_decision_preview(
            self.contract_path,
            kind="task-continuation",
            decision="approve",
            target="current",
            provider="codex",
            session_id="new-session",
        )
        observe_native_permission_request(
            self.native_permission_payload(
                fresh,
                session_id="new-session",
            ),
            provider="codex",
        )

        def crash_after_approval(stage: str) -> None:
            if stage == "after_approval_decided":
                raise RuntimeError("injected continuation crash")

        with mock.patch.object(
            guardian_recovery,
            "_native_decision_failpoint",
            side_effect=crash_after_approval,
        ):
            with self.assertRaisesRegex(RuntimeError, "continuation crash"):
                execute_native_decision(
                    self.contract_path,
                    kind="task-continuation",
                    decision="approve",
                    target=fresh["target"],
                    provider="codex",
                    session_id="new-session",
                )
        GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="new-session",
        )
        recovered = load_contract(self.contract_path)
        lane = guardian_module._task_lane(
            recovered,
            provider="codex",
            session_id="new-session",
        )
        self.assertEqual(lane["state"], "bound")
        self.assertEqual(len(recovered["runtime"]["task_continuations"]), 1)
        transaction = next(
            iter(load_native_decision_projection(self.contract_path)["transactions"].values())
        )
        self.assertEqual(transaction["stage"], "committed")

    def test_explicit_task_instance_change_requires_token_but_followups_do_not(self) -> None:
        home = Path(self.temp.name) / "kb-task-instance"
        first = {
            "client": "codex",
            "session_id": "same-terminal",
            "task_instance_id": "host-task-a",
            "cwd": str(self.root),
            "prompt": "检查当前模块的状态机",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}, clear=False):
            initial = observe_user_prompt(first, provider="codex")
            path = active_contract_path(home, self.root)
            seeded = load_contract(path)
            lane = next(
                row
                for row in seeded["runtime"]["task_lanes"]
                if row["session_id"] == "same-terminal"
            )
            continuation_token = lane["continuation_token"]

            replayed_in_new_session = observe_user_prompt(
                {
                    **first,
                    "session_id": "token-replay-terminal",
                    "prompt": "尝试复用可读 token",
                    "task_continuation_token": continuation_token,
                },
                provider="codex",
            )

            followup = observe_user_prompt(
                {
                    **first,
                    "prompt": "继续检查这一状态机",
                    "task_instance_id": "",
                },
                provider="codex",
            )
            after_followup = load_contract(path)
            changed = observe_user_prompt(
                {
                    **first,
                    "prompt": "切换到另一个宿主任務",
                    "task_instance_id": "host-task-b",
                },
                provider="codex",
            )
            after_change = load_contract(path)
            continued = observe_user_prompt(
                {
                    **first,
                    "prompt": "宿主确认这是同一任务的后续 turn",
                    "task_instance_id": "host-task-b",
                    "task_continuation_token": continuation_token,
                },
                provider="codex",
            )
            after_continue = load_contract(path)

        self.assertIn("ACTIVE", initial)
        self.assertIn("task_identity=explicit", initial)
        self.assertIn("TASK_REVIEW_REQUIRED", replayed_in_new_session)
        self.assertIn("ACTIVE", followup)
        self.assertIn("task_identity=unknown", followup)
        self.assertEqual(after_followup["objective"], first["prompt"])
        self.assertIn("TASK_REVIEW_REQUIRED", changed)
        changed_lane = next(
            row
            for row in after_change["runtime"]["task_lanes"]
            if row["session_id"] == "same-terminal"
        )
        self.assertEqual(changed_lane["state"], "review_required")
        self.assertEqual(changed_lane["task_instance_id"], "host-task-a")
        self.assertEqual(changed_lane["pending_task_instance_id"], "host-task-b")
        self.assertIn("ACTIVE", continued)
        self.assertIn("task_identity=continued", continued)
        continued_lane = next(
            row
            for row in after_continue["runtime"]["task_lanes"]
            if row["session_id"] == "same-terminal"
        )
        self.assertEqual(continued_lane["state"], "bound")
        self.assertEqual(continued_lane["task_instance_id"], "host-task-b")
        self.assertEqual(continued_lane["pending_task_instance_id"], "")

    def test_same_turn_control_prompt_does_not_detach_task_instance(self) -> None:
        home = Path(self.temp.name) / "kb-task-control"
        payload = {
            "client": "codex",
            "session_id": "control-terminal",
            "task_instance_id": "host-task-a",
            "cwd": str(self.root),
            "prompt": "检查当前模块",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}, clear=False):
            observe_user_prompt(payload, provider="codex")
            path = active_contract_path(home, self.root)
            paused = observe_user_prompt(
                {
                    **payload,
                    "prompt": "先暂停修改",
                    "task_instance_id": "host-control-turn",
                    "task_transition": "new",
                },
                provider="codex",
            )
            current = load_contract(path)

        self.assertIn("PAUSED", paused)
        self.assertIn("task_identity=control", paused)
        lane = next(
            row
            for row in current["runtime"]["task_lanes"]
            if row["session_id"] == "control-terminal"
        )
        self.assertEqual(lane["state"], "paused")
        self.assertEqual(lane["task_instance_id"], "host-task-a")
        self.assertEqual(lane["pending_task_instance_id"], "")

    def test_sibling_lane_keeps_sealed_continuation_while_other_lane_is_paused(self) -> None:
        self.contract()
        owner = {
            "client": "codex",
            "session_id": "lane-a",
            "cwd": str(self.root),
            "intent_contract": str(self.contract_path),
            "prompt": "显式绑定 lane a",
            "sulde_observation_source": "live_host_hook",
        }
        observe_user_prompt(owner, provider="codex")
        observe_user_prompt(
            {**owner, "session_id": "lane-b", "prompt": "显式绑定 lane b"},
            provider="codex",
        )
        seeded = load_contract(self.contract_path)
        guardian_module._upsert_task_lane_locked(
            seeded,
            provider="codex",
            session_id="lane-b",
            state="bound",
            source="applied_revision_fixture",
        )
        write_contract(self.contract_path, seeded)
        observe_user_prompt(
            {**owner, "prompt": "先暂停修改"},
            provider="codex",
        )
        contract = load_contract(self.contract_path)
        self.assertEqual(contract["status"], "paused")
        self.assertIsNone(
            guardian_module._pause_state(
                contract,
                provider="codex",
                session_id="lane-b",
            )
        )

        home = Path(self.temp.name) / "memory-kb"
        payload = {
            "client": "codex",
            "session_id": "lane-b",
            "cwd": str(self.root),
            "tool_name": "mcp__sulde_kb__memory_annotate",
            "tool_input": {
                "entities": [
                    {"name": "A", "type": "component"},
                    {"name": "B", "type": "risk"},
                ],
                "edges": [
                    {"src": "A", "rel": "prevents", "dst": "B", "confidence": 1.0}
                ],
                "extracted_by": "codex",
            },
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}, clear=False):
            event = normalize_hook_event(payload, phase="started", provider="codex")
        decision = GuardianSession(self.contract_path).observe(event)
        current = load_contract(self.contract_path)

        self.assertEqual(decision.action, "allow")
        self.assertEqual(
            current["runtime"]["continuation_uses"][-1]["profile_id"],
            guardian_module.SYSTEM_MEMORY_PROFILE,
        )

    def test_lane_pauses_are_independent_and_resume_preserves_task_debt(self) -> None:
        home = Path(self.temp.name) / "kb-lane-pauses"
        owner = {
            "client": "codex",
            "session_id": "lane-a",
            "cwd": str(self.root),
            "prompt": "继续当前受管任务",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}, clear=False):
            observe_user_prompt(owner, provider="codex")
            path = active_contract_path(home, self.root)
            observe_user_prompt(
                {
                    **owner,
                    "session_id": "lane-b",
                    "intent_contract": str(path),
                    "prompt": "显式续接同一任务",
                },
                provider="codex",
            )
            seeded = load_contract(path)
            guardian_module._upsert_task_lane_locked(
                seeded,
                provider="codex",
                session_id="lane-b",
                state="bound",
                source="applied_revision_fixture",
            )
            original_revision = seeded["revision"]
            original_epoch = seeded["task_epoch"]
            seeded["runtime"]["pending_verifications"].append(
                {
                    "event_id": "debt-survives-resume",
                    "task_epoch": original_epoch,
                }
            )
            write_contract(path, seeded)
            guardian_session_workspace.bind_session_workspace(
                home,
                provider="codex",
                session_id="lane-b",
                contract_path=path,
            )

            destructive = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "lane-a",
                    "tool_name": "Bash",
                    "tool_input": {"command": "drop table users"},
                },
                phase="started",
                provider="codex",
            )
            a_pause = GuardianSession(path).observe(destructive)
            self.assertEqual(a_pause.action, "deny")
            self.assertTrue(a_pause.pause)

            b_write = normalize_hook_event(
                {
                    "client": "codex",
                    "session_id": "lane-b",
                    "call_id": "lane-b-write",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(self.root / "resume.md")},
                },
                phase="started",
                provider="codex",
            )
            self.assertEqual(GuardianSession(path).observe(b_write).action, "allow")
            self.assertEqual(
                GuardianSession(path).observe(
                    {**b_write, "phase": "completed", "success": True}
                ).action,
                "allow",
            )
            a_write = {**b_write, "session_id": "lane-a", "call_id": "lane-a-write"}
            denied_again = GuardianSession(path).observe(a_write)
            self.assertEqual(denied_again.action, "deny")
            self.assertIn("task lane", denied_again.reason)

            observe_user_prompt(
                {
                    **owner,
                    "session_id": "lane-b",
                    "intent_contract": str(path),
                    "prompt": "先暂停修改",
                },
                provider="codex",
            )
            both_paused = load_contract(path)
            paused_lanes = {
                row["session_id"]
                for row in both_paused["runtime"]["task_lanes"]
                if row["task_epoch"] == original_epoch and row["state"] == "paused"
            }
            self.assertEqual(paused_lanes, {"lane-a", "lane-b"})
            self.assertEqual(both_paused["runtime"]["pause_scope"], "lane")

            preview_a = native_decision_preview(
                path,
                kind="resume",
                decision="resume",
                target="current",
                provider="codex",
                session_id="lane-a",
            )
            self.assertEqual(
                observe_native_permission_request(
                    self.native_permission_payload(
                        preview_a,
                        session_id="lane-a",
                        contract_path=path,
                    ),
                    provider="codex",
                )["action"],
                "defer",
            )
            execute_native_decision(
                path,
                kind="resume",
                decision="resume",
                target=preview_a["target"],
                provider="codex",
                session_id="lane-a",
            )

            after_a = load_contract(path)
            recovery = after_a["resumed_lane"]
            self.assertEqual(recovery["session_id"], "lane-a")
            self.assertEqual(recovery["original_pause_sha256"], hashlib.sha256(
                json.dumps(recovery["original_pause"], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest())
            audit_rows = [json.loads(line) for line in audit_path(path).read_text().splitlines()]
            self.assertTrue(any(row.get("pause_recovery") == recovery for row in audit_rows))
            self.assertEqual(after_a["revision"], original_revision)
            self.assertEqual(after_a["task_epoch"], original_epoch)
            self.assertEqual(
                [row["event_id"] for row in after_a["runtime"]["pending_verifications"]],
                ["debt-survives-resume"],
            )
            states = {
                row["session_id"]: row["state"]
                for row in after_a["runtime"]["task_lanes"]
                if row["task_epoch"] == original_epoch
            }
            self.assertEqual(states["lane-a"], "bound")
            self.assertEqual(states["lane-b"], "paused")
            self.assertEqual(after_a["status"], "paused")
            self.assertEqual(b_write["provider"], "codex")
            self.assertEqual(b_write["session_id"], "lane-b")
            self.assertEqual(b_write["effect"], "local_write")
            self.assertEqual(
                guardian_module._pause_state(
                    after_a,
                    provider=b_write["provider"],
                    session_id=b_write["session_id"],
                )["scope"],
                "lane",
            )
            self.assertEqual(evaluate_event(after_a, a_write).action, "allow")
            self.assertEqual(evaluate_event(after_a, b_write).action, "deny")

            preview_b = native_decision_preview(
                path,
                kind="resume",
                decision="resume",
                target="current",
                provider="codex",
                session_id="lane-b",
            )
            observe_native_permission_request(
                self.native_permission_payload(
                    preview_b,
                    session_id="lane-b",
                    contract_path=path,
                ),
                provider="codex",
            )
            execute_native_decision(
                path,
                kind="resume",
                decision="resume",
                target=preview_b["target"],
                provider="codex",
                session_id="lane-b",
            )
            guardian_module.pause_contract(path, "workspace maintenance")
            globally_paused = load_contract(path)
            self.assertEqual(globally_paused["runtime"]["pause_scope"], "global")
            self.assertEqual(evaluate_event(globally_paused, a_write).action, "deny")
            self.assertEqual(evaluate_event(globally_paused, b_write).action, "deny")
            resume_contract(path, "workspace maintenance completed")
            final = load_contract(path)

        self.assertEqual(final["status"], "active")
        self.assertEqual(final["revision"], original_revision)
        self.assertEqual(final["task_epoch"], original_epoch)
        self.assertEqual(final["runtime"]["pause_scope"], "")

    def test_doctor_does_not_claim_chat_approval_without_live_hook_evidence(self) -> None:
        home = Path(self.temp.name) / "kb"

        missing = guardian_doctor(home, self.root)

        self.assertEqual(missing["status"], "unobserved")
        self.assertFalse(missing["contract_exists"])
        self.assertEqual(missing["approval_capture"]["status"], "unobserved")
        self.assertIn("prepare-proposal", missing["next_action"])
        self.assertIn("not a substitute", missing["next_action"])

        payload = {
            "client": "codex",
            "session_id": "smoke",
            "cwd": str(self.root),
            "prompt": "start",
            "sulde_observation_source": "synthetic_smoke",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(payload, provider="codex")
            synthetic = guardian_doctor(home, self.root)
            payload.update(
                {
                    "session_id": "live",
                    "prompt": "continue",
                    "sulde_observation_source": "live_host_hook",
                }
            )
            observe_user_prompt(payload, provider="codex")
            live = guardian_doctor(
                home,
                self.root,
                provider="codex",
                session_id="live",
            )

        self.assertEqual(synthetic["status"], "degraded")
        self.assertEqual(synthetic["approval_capture"]["status"], "synthetic_only")
        self.assertNotIn("Chat approval is available", synthetic["next_action"])
        self.assertEqual(live["status"], "degraded")
        self.assertEqual(live["approval_capture"]["status"], "live_verified")
        self.assertEqual(live["operational_readiness"]["status"], "degraded")
        self.assertNotIn("Chat approval is available", live["next_action"])

        with mock.patch.object(
            guardian_readiness,
            "operational_readiness_projection",
            return_value={
                "status": "ready",
                "interactive_readiness": {"status": "ready", "reasons": []},
                "scheduler_readiness": {"status": "ready", "reasons": []},
                "effect_truth": {"status": "clear"},
                "reasons": [],
            },
        ):
            fully_ready = guardian_doctor(
                home,
                self.root,
                provider="codex",
                session_id="live",
            )
        self.assertEqual(fully_ready["status"], "ready")
        self.assertEqual(
            fully_ready["next_action"],
            "Chat approval is available in the current host session.",
        )

    def test_doctor_does_not_use_claude_live_evidence_for_codex(self) -> None:
        home = Path(self.temp.name) / "kb"
        payload = {
            "client": "claude",
            "session_id": "claude-live",
            "cwd": str(self.root),
            "prompt": "start",
            "sulde_observation_source": "live_host_hook",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(payload, provider="claude")
            claude = guardian_doctor(home, self.root, provider="claude")
            codex = guardian_doctor(home, self.root, provider="codex")

        self.assertEqual(claude["status"], "degraded")
        self.assertEqual(claude["approval_capture"]["status"], "live_verified")
        self.assertEqual(codex["status"], "degraded")
        self.assertEqual(codex["approval_capture"]["status"], "unobserved")
        self.assertEqual(codex["approval_capture"]["overall_status"], "live_verified")

    def test_doctor_cli_binds_to_current_codex_thread_environment(self) -> None:
        home = Path(self.temp.name) / "kb-doctor-cli"
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(
                {
                    "client": "codex",
                    "session_id": "old-live-thread",
                    "cwd": str(self.root),
                    "prompt": "start",
                    "sulde_observation_source": "live_host_hook",
                },
                provider="codex",
            )
        env = os.environ.copy()
        env.update(
            {
                "SULDE_KB_HOME": str(home),
                "CODEX_THREAD_ID": "current-unobserved-thread",
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "intent-guardian.py"),
                "doctor",
                "--workspace",
                str(self.root),
                "--provider",
                "codex",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "degraded")
        self.assertEqual(
            report["approval_capture"]["session_id"],
            "current-unobserved-thread",
        )
        self.assertEqual(report["approval_capture"]["provider_status"], "live_verified")

    def test_session_start_does_not_inject_another_sessions_continuation(self) -> None:
        home = Path(self.temp.name) / "kb-continuation"
        codex_home = Path(self.temp.name) / "codex-home"
        source_session = "00000000-0000-7000-8000-000000000001"
        rollout_dir = codex_home / "sessions" / "2026" / "08" / "15"
        rollout_dir.mkdir(parents=True)
        rollout = rollout_dir / f"rollout-2026-08-15T00-00-00-{source_session}.jsonl"
        rollout.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "user_message",
                        "message": "确认先做 SyntheticApplication 测试样例页面",
                    },
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        path, _, digest, review = prepare_workspace_proposal(
            home,
            self.root,
            intent_id="synthetic-application-brand-visual-grammar-v1",
            objective="Create an isolated SyntheticApplication test example page",
            acceptance_criteria=["去掉颜色和文字后仍能识别统一图形语言"],
            mode="enforce",
            preserve=["Gate C", "现有产品代码"],
            reject=["通用线性图标换皮"],
            decision_route="human",
            provider="codex",
            session_id=source_session,
            codex_home=codex_home,
        )
        self.assertEqual(review["continuation"]["status"], "ready")
        self.assertTrue(review["continuation"]["source_rollout_available"])

        observe_user_prompt(
            {
                "client": "codex",
                "session_id": source_session,
                "cwd": str(self.root),
                "intent_contract": str(path),
                "prompt": "检查已冻结方案",
                "sulde_observation_source": "live_host_hook",
            },
            provider="codex",
        )
        old_session = guardian_doctor(
            home,
            self.root,
            provider="codex",
            session_id=source_session,
        )
        new_session = guardian_doctor(
            home,
            self.root,
            provider="codex",
            session_id="new-thread",
        )
        self.assertEqual(old_session["status"], "degraded")
        self.assertEqual(new_session["status"], "degraded")
        self.assertEqual(new_session["approval_capture"]["provider_status"], "live_verified")
        self.assertIn("Do not repeat", new_session["next_action"])

        first = continuation_context(
            home,
            self.root,
            provider="codex",
            session_id="new-thread",
        )
        second = continuation_context(
            home,
            self.root,
            provider="codex",
            session_id="new-thread",
        )
        self.assertEqual(first, second)
        self.assertEqual(first, "")
        owner_context = continuation_context(
            home,
            self.root,
            provider="codex",
            session_id=source_session,
        )
        self.assertIn("Create an isolated SyntheticApplication test example page", owner_context)
        self.assertIn("确认先做 SyntheticApplication 测试样例页面", owner_context)
        self.assertIn("不转移人工批准", owner_context)

        sibling_contract = load_contract(path)
        guardian_module._upsert_task_lane_locked(
            sibling_contract,
            provider="codex",
            session_id="bound-sibling",
            state="bound",
            source="approved_revision",
            continuation_eligible=True,
        )
        write_contract(path, sibling_contract)
        self.assertEqual(
            continuation_context(
                home,
                self.root,
                provider="codex",
                session_id="bound-sibling",
            ),
            "",
        )

        rows = [
            json.loads(line)
            for line in audit_path(path).read_text(encoding="utf-8").splitlines()
        ]
        continuation_rows = [
            row for row in rows if row.get("schema") == "sulde-continuation-event-v1"
        ]
        self.assertEqual(
            [row["action"] for row in continuation_rows],
            ["created", "loaded"],
        )
        self.assertTrue(all(row["authority_transferred"] is False for row in continuation_rows))

    def test_prepare_continuation_is_idempotent_for_one_proposal(self) -> None:
        home = Path(self.temp.name) / "kb-continuation-idempotent"
        path, _, digest, review = prepare_workspace_proposal(
            home,
            self.root,
            intent_id="one-capsule",
            objective="冻结一份可恢复方案",
            acceptance_criteria=["新会话可读取"],
            mode="enforce",
            decision_route="human",
            provider="codex",
            session_id="old-thread",
        )
        repeated = prepare_continuation(
            path,
            proposal_digest_value=digest,
            provider="codex",
            session_id="another-thread",
        )
        self.assertEqual(repeated["capsule_id"], review["continuation"]["capsule_id"])
        rows = [
            json.loads(line)
            for line in audit_path(path).read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(
            sum(row.get("action") == "created" for row in rows),
            1,
        )

    def test_concurrent_continuation_creation_keeps_one_immutable_capsule(self) -> None:
        self.contract()
        _, digest = create_revision_proposal(
            self.contract_path,
            objective="并发冻结同一份人工方案",
            acceptance_criteria=["只生成一个不可变续接包"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(
                    lambda index: prepare_continuation(
                        self.contract_path,
                        proposal_digest_value=digest,
                        provider="codex",
                        session_id=f"thread-{index}",
                    ),
                    range(8),
                )
            )

        self.assertEqual(len({row["capsule_id"] for row in results}), 1)
        self.assertEqual(
            len(list(self.contract_path.parent.glob("intent.continuation.*.json"))),
            1,
        )
        rows = [
            json.loads(line)
            for line in audit_path(self.contract_path).read_text(encoding="utf-8").splitlines()
        ]
        created = [
            row
            for row in rows
            if row.get("schema") == "sulde-continuation-event-v1"
            and row.get("action") == "created"
        ]
        self.assertEqual(len(created), 1)

    def test_orphan_inventory_and_human_rebind_force_fresh_intent_review(self) -> None:
        home = Path(self.temp.name) / "kb"
        enclosing_repository = Path(self.temp.name) / "enclosing-repository"
        enclosing_repository.mkdir()
        (enclosing_repository / ".git").mkdir()
        old_root = enclosing_repository / "old-workspace"
        old_root.mkdir()
        (old_root / ".git").mkdir()
        path = active_contract_path(home, old_root)
        write_contract(
            path,
            default_contract(
                intent_id="moved-project",
                objective="continue the reviewed task",
                acceptance_criteria=["facts stay unchanged"],
                workspace=old_root,
                mode="enforce",
                allowed_paths=["resume.md"],
                confirmed_by="human",
            ),
        )
        old_proposal, old_digest = create_revision_proposal(
            path,
            objective="old approved objective",
            acceptance_criteria=["old approval"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        old_receipt = approve_proposal(path, old_digest, actor="human-cli")
        retired_directory = enclosing_repository / "retired-directory"
        old_root.rename(retired_directory)
        new_root = Path(self.temp.name) / "new-workspace"
        new_root.mkdir()
        (new_root / ".git").mkdir()

        inventory = guardian_inventory(home, provider="codex")
        result = rebind_workspace_contract(
            path,
            home=home,
            new_workspace=new_root,
            reason="temporary worktree was removed after the repository moved",
        )
        target = Path(result["contract_path"])
        rebound = load_contract(target)

        self.assertEqual(inventory["status"], "degraded")
        self.assertEqual(inventory["counts"]["orphaned"], 1)
        self.assertTrue(inventory["orphaned"][0]["rebind_eligible"])
        self.assertFalse(path.exists())
        self.assertTrue(Path(result["archive_contract"]).is_file())
        self.assertEqual(rebound["workspace_root"], str(new_root.resolve()))
        self.assertEqual(rebound["status"], "paused")
        self.assertTrue(rebound["runtime"]["pause_requires_revision"])
        self.assertEqual(rebound["runtime"]["approved_proposal_digests"], [])
        invalidated = next(
            row
            for row in rebound["runtime"]["approval_receipts"]
            if row["receipt_id"] == old_receipt["receipt_id"]
        )
        self.assertEqual(
            invalidated["consumed_by"],
            "invalidated-by-workspace-rebind",
        )
        with self.assertRaises(IntentGuardianError):
            apply_revision_proposal(target, old_proposal)

        old_doctor = guardian_doctor(home, old_root, provider="codex")
        new_doctor = guardian_doctor(home, new_root, provider="codex")
        self.assertEqual(old_doctor["status"], "rebound")
        self.assertEqual(old_doctor["rebind"]["to_contract"], str(target))
        self.assertEqual(new_doctor["status"], "degraded")
        self.assertEqual(new_doctor["approval_capture"]["status"], "unobserved")

        proposal, digest = create_revision_proposal(
            target,
            objective="reviewed objective in the new workspace",
            acceptance_criteria=["new workspace binding confirmed"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="agent",
            intent_kind="deterministic",
            risk="low",
            effects=["local_write"],
            reversibility="reversible",
            cost="none",
            rollback="恢复 resume.md 的未提交差异",
        )
        rebound_review = proposal_review_for_digest(target, digest)
        self.assertEqual(rebound_review["decision_route"], "human")
        self.assertTrue(
            any(
                "工作区迁移" in reason or "暂停状态" in reason
                for reason in rebound_review["decision_card"]["不能由 Agent 决断的原因"]
            )
        )
        self.live_approve_proposal(target, digest)
        applied = load_contract(target)
        self.assertEqual(applied["status"], "active")
        self.assertFalse(applied["confirmation"]["required"])

    def test_orphan_rebind_moves_matching_session_mapping_to_registered_worktree(self) -> None:
        _repo, source, target, home, source_path = self.orphan_rebind_fixture()

        result = rebind_workspace_contract(
            source_path,
            home=home,
            new_workspace=target,
            reason="the mapped task worktree was removed after acceptance",
        )

        target_path = active_contract_path(home, target).resolve()
        self.assertEqual(result["session_mappings_rebound"], 2)
        self.assertEqual(
            resolve_session_contract(home, "codex", "mapped-orphan-session"),
            target_path,
        )
        rebound = load_contract(target_path)
        self.assertEqual(rebound["workspace_root"], str(target.resolve()))
        self.assertEqual(rebound["status"], "paused")
        self.assertFalse(source.exists())

    def test_orphan_rebind_refuses_non_git_target_for_mapped_session(self) -> None:
        _repo, _source, _target, home, source_path = self.orphan_rebind_fixture()
        scratch = Path(self.temp.name) / "non-git-rebind-target"
        scratch.mkdir()
        mapping_path = next((home / "intent" / "sessions").glob("*.workspace.json"))
        mapping_before = mapping_path.read_bytes()

        with self.assertRaisesRegex(IntentGuardianError, "Git identity"):
            rebind_workspace_contract(
                source_path,
                home=home,
                new_workspace=scratch,
                reason="must not strand a mapped session in a scratch directory",
            )

        self.assertTrue(source_path.is_file())
        self.assertEqual(mapping_path.read_bytes(), mapping_before)
        self.assertFalse(active_contract_path(home, scratch).exists())

    def test_orphan_rebind_rolls_back_all_session_mappings_on_partial_failure(self) -> None:
        _repo, _source, target, home, source_path = self.orphan_rebind_fixture()
        mapping_paths = sorted((home / "intent" / "sessions").glob("*.workspace.json"))
        mapping_before = {path: path.read_bytes() for path in mapping_paths}
        original_write = guardian_session_workspace._write_mapping
        calls = 0

        def fail_second_mapping(selected_home, mapping):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected second mapping failure")
            return original_write(selected_home, mapping)

        with mock.patch.object(
            guardian_session_workspace,
            "_write_mapping",
            side_effect=fail_second_mapping,
        ), self.assertRaisesRegex(OSError, "second mapping failure"):
            rebind_workspace_contract(
                source_path,
                home=home,
                new_workspace=target,
                reason="exercise transactional session mapping rollback",
            )

        self.assertTrue(source_path.is_file())
        self.assertFalse(active_contract_path(home, target).exists())
        for path, before in mapping_before.items():
            self.assertEqual(path.read_bytes(), before)

    def test_rebind_refuses_a_workspace_that_still_exists(self) -> None:
        home = Path(self.temp.name) / "kb"
        path = active_contract_path(home, self.root)
        write_contract(
            path,
            default_contract(
                intent_id="live-project",
                objective="do not move active authority",
                acceptance_criteria=["source must be gone"],
                workspace=self.root,
                mode="enforce",
                confirmed_by="human",
            ),
        )
        destination = Path(self.temp.name) / "destination"
        destination.mkdir()
        (destination / ".git").mkdir()

        with self.assertRaisesRegex(IntentGuardianError, "still exists"):
            rebind_workspace_contract(
                path,
                home=home,
                new_workspace=destination,
                reason="should be rejected",
            )

    def test_human_can_retire_an_abandoned_orphan(self) -> None:
        home = Path(self.temp.name) / "kb"
        enclosing_repository = Path(self.temp.name) / "retirement-parent"
        enclosing_repository.mkdir()
        (enclosing_repository / ".git").mkdir()
        old_root = enclosing_repository / "abandoned-workspace"
        old_root.mkdir()
        (old_root / ".git").mkdir()
        path = active_contract_path(home, old_root)
        write_contract(
            path,
            default_contract(
                intent_id="abandoned-task",
                objective="obsolete task",
                acceptance_criteria=["archive it"],
                workspace=old_root,
                mode="enforce",
                confirmed_by="human",
            ),
        )
        proposal, digest = create_revision_proposal(
            path,
            objective="obsolete proposal",
            acceptance_criteria=["must not survive retirement"],
            mode="enforce",
        )
        receipt = approve_proposal(path, digest, actor="human-cli")
        old_root.rename(enclosing_repository / "abandoned-workspace-removed")

        result = retire_orphan_contract(
            path,
            home=home,
            reason="the temporary task and worktree are no longer needed",
        )
        archived = load_contract(Path(result["archive_contract"]))
        doctor = guardian_doctor(home, old_root, provider="codex")
        inventory = guardian_inventory(home, provider="codex")

        self.assertFalse(path.exists())
        self.assertEqual(archived["status"], "closed")
        invalidated = next(
            row
            for row in archived["runtime"]["approval_receipts"]
            if row["receipt_id"] == receipt["receipt_id"]
        )
        self.assertEqual(
            invalidated["consumed_by"],
            "invalidated-by-workspace-retirement",
        )
        self.assertEqual(doctor["status"], "retired")
        self.assertEqual(doctor["retirement"]["archive_contract"], result["archive_contract"])
        self.assertEqual(inventory["status"], "ready")
        self.assertEqual(inventory["counts"]["orphaned"], 0)

        with self.assertRaises(IntentGuardianError):
            apply_revision_proposal(Path(result["archive_contract"]), proposal)

    def test_proposal_digest_binds_runtime_authority_fields(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="只润色表达",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        tampered = load_contract(proposal)
        tampered["runtime"]["supervision_metrics"]["allowed"] += 1
        write_contract(proposal, tampered)
        with self.assertRaisesRegex(IntentGuardianError, "digest field"):
            apply_revision_proposal(self.contract_path, proposal)

    def test_per_session_activation_is_retired_to_preserve_one_workspace_truth(self) -> None:
        self.contract()
        with self.assertRaisesRegex(IntentGuardianError, "per-session intent activation is retired"):
            activate_contract(
                self.contract_path,
                home=Path(self.temp.name) / "kb",
                workspace=self.root,
                provider="codex",
                session_id="thread",
            )

    def test_apply_patch_targets_are_checked_against_contract_scope(self) -> None:
        contract = self.contract()
        allowed = normalize_hook_event(
            {
                "tool_name": "apply_patch",
                "tool_input": {"patch": "*** Begin Patch\n*** Update File: resume.md\n@@\n-old\n+new\n*** End Patch"},
            },
            phase="started",
        )
        denied = normalize_hook_event(
            {
                "tool_name": "apply_patch",
                "tool_input": {"patch": "*** Begin Patch\n*** Add File: other.md\n+new\n*** End Patch"},
            },
            phase="started",
        )
        absolute = normalize_hook_event(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.root / "resume.md")},
            },
            phase="started",
        )
        self.assertEqual(allowed["target"], "resume.md")
        self.assertEqual(allowed["write_targets"], ["resume.md"])
        self.assertEqual(
            allowed["local_file_operations"],
            [{"operation": "update", "path": "resume.md"}],
        )
        self.assertEqual(evaluate_event(contract, allowed).action, "allow")
        self.assertEqual(evaluate_event(contract, absolute).action, "allow")
        self.assertEqual(evaluate_event(contract, denied).action, "allow")

    def test_exact_apply_patch_delete_is_agent_owned_local_work(self) -> None:
        self.contract()
        with self.assertRaisesRegex(IntentGuardianError, "local_write transport"):
            create_revision_proposal(
                self.contract_path,
                objective="删除废弃文件",
                acceptance_criteria=["文件不存在"],
                mode="enforce",
                allowed_paths=["obsolete.md"],
                decision_route="human",
                intent_kind="deterministic",
                risk="high",
                effects=["destructive"],
                reversibility="irreversible",
                cost="none",
                rollback="重新实现",
            )

        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="删除废弃文件",
            acceptance_criteria=["obsolete.md 不再存在"],
            mode="enforce",
            allowed_paths=["obsolete.md", "notes,2026.md"],
            decision_route="human",
            intent_kind="deterministic",
            risk="high",
            effects=["local_write", "destructive"],
            reversibility="irreversible",
            cost="none",
            rollback="从已审阅来源重新实现",
        )
        candidate = load_contract(proposal)
        self.assertEqual(candidate["permissions"]["destructive"], "confirm")
        self.live_approve_proposal(self.contract_path, digest)
        applied = load_contract(self.contract_path)

        delete = normalize_hook_event(
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": (
                        "*** Begin Patch\n"
                        "*** Delete File: obsolete.md\n"
                        "*** End Patch"
                    )
                },
            },
            phase="started",
        )
        comma_name = normalize_hook_event(
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": (
                        "*** Begin Patch\n"
                        "*** Delete File: notes,2026.md\n"
                        "*** End Patch"
                    )
                },
            },
            phase="started",
        )
        outside = normalize_hook_event(
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": (
                        "*** Begin Patch\n"
                        "*** Delete File: other.md\n"
                        "*** End Patch"
                    )
                },
            },
            phase="started",
        )

        self.assertEqual(delete["effect"], "local_write")
        self.assertTrue(delete["destructive_local_operation"])
        self.assertFalse(delete["high_risk_local_operation"])
        self.assertEqual(delete["write_targets"], ["obsolete.md"])
        self.assertEqual(evaluate_event(applied, delete).action, "allow")
        self.assertEqual(comma_name["write_targets"], ["notes,2026.md"])
        self.assertEqual(evaluate_event(applied, comma_name).action, "allow")
        self.assertEqual(evaluate_event(applied, outside).action, "allow")

        unapproved = json.loads(json.dumps(applied))
        unapproved["applied_approval_receipt_id"] = ""
        self.assertEqual(evaluate_event(unapproved, delete).action, "allow")

    def test_exact_nonrecursive_file_cleanup_is_agent_owned(self) -> None:
        contract = self.contract()
        target = self.root / "one-empty-canary"
        target.touch()
        event = normalize_hook_event(
            {
                "tool_name": "exec_command",
                "cwd": str(self.root),
                "tool_input": {"cmd": "rm -- one-empty-canary"},
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(event["destructive_local_operation"])
        self.assertFalse(event["high_risk_local_operation"])
        self.assertEqual(evaluate_event(contract, event).action, "allow")

        formal_target = self.root / "sulde-pre-execution-canary-fixture"
        formal_target.touch()
        formal = normalize_hook_event(
            {
                "tool_name": "exec_command",
                "cwd": str(self.root),
                "tool_input": {
                    "cmd": "rm -- sulde-pre-execution-canary-fixture"
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertTrue(formal["high_risk_local_operation"])
        self.assertEqual(evaluate_event(contract, formal).action, "deny")

    def test_rejected_shell_delete_is_destructive_and_fail_closed(self) -> None:
        contract = self.contract()
        event = normalize_hook_event(
            {
                "tool_name": "Bash",
                "cwd": str(self.root.resolve()),
                "tool_input": {"command": "rm -f unsealed-target"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(event["typed_resource"]["status"], "rejected")
        self.assertEqual(event["effect"], "destructive")
        self.assertEqual(event["uncertainty_kind"], "rejected_local_delete")
        decision = evaluate_event(contract, event)
        self.assertEqual(decision.action, "deny")
        self.assertEqual(decision.lifecycle, "continue")

        observed = GuardianSession(
            self.contract_path, provider="codex"
        ).observe(event)
        self.assertEqual(observed.action, "deny")
        self.assertEqual(observed.lifecycle, "continue")
        self.assertEqual(load_contract(self.contract_path)["status"], "active")

        completed = dict(event)
        completed["phase"] = "completed"
        completed_decision = evaluate_event(contract, completed)
        self.assertEqual(completed_decision.action, "deny")
        self.assertEqual(completed_decision.lifecycle, "pause")

    def test_literal_shell_delete_requires_exact_native_human_authority(self) -> None:
        self.contract()
        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="删除两个已审阅的本地缓存目录",
            acceptance_criteria=["cache-one 和 cache-two 不再存在"],
            mode="enforce",
            allowed_paths=["cache-one", "cache-two"],
            decision_route="human",
            intent_kind="deterministic",
            risk="high",
            effects=["local_write", "destructive"],
            reversibility="irreversible",
            cost="none",
            rollback="重新生成缓存",
        )
        self.live_approve_proposal(self.contract_path, digest)
        applied = load_contract(self.contract_path)
        cache_one = self.root / "cache-one"
        cache_two = self.root / "cache-two"
        cache_one.mkdir()
        cache_two.mkdir()
        command = "rm -rf cache-one cache-two"

        dispatched = normalize_hook_event(
            {
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            phase="started",
            provider="codex",
        )
        exact_targets = [str(cache_one.resolve()), str(cache_two.resolve())]
        self.assertEqual(dispatched["effect"], "local_write")
        self.assertEqual(dispatched["write_targets"], exact_targets)
        self.assertEqual(
            dispatched["local_file_operations"],
            [
                {"operation": "delete", "path": exact_targets[0]},
                {"operation": "delete", "path": exact_targets[1]},
            ],
        )
        self.assertTrue(dispatched["destructive_local_operation"])
        self.assertTrue(dispatched["high_risk_local_operation"])
        self.assertEqual(evaluate_event(applied, dispatched).action, "allow")
        codex_dispatched = normalize_hook_event(
            {
                "cwd": str(self.root),
                "tool_name": "exec_command",
                "tool_input": {"cmd": command},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(codex_dispatched["write_targets"], exact_targets)
        self.assertEqual(evaluate_event(applied, codex_dispatched).action, "allow")

        cache_one.rmdir()
        cache_two.rmdir()
        completed = normalize_hook_event(
            {
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
            phase="completed",
            provider="codex",
        )
        self.assertEqual(completed["effect"], dispatched["effect"])
        self.assertEqual(completed["write_targets"], exact_targets)
        self.assertEqual(
            completed["local_file_operations"],
            dispatched["local_file_operations"],
        )

        unapproved = json.loads(json.dumps(applied))
        unapproved["applied_approval_receipt_id"] = ""
        unapproved_decision = evaluate_event(unapproved, dispatched)
        self.assertEqual(unapproved_decision.action, "deny")
        self.assertFalse(unapproved_decision.pause)

        mismatched = json.loads(json.dumps(dispatched))
        mismatched["local_file_operations"][0]["path"] = str(
            self.root / "other-cache"
        )
        mismatched_decision = evaluate_event(applied, mismatched)
        self.assertEqual(mismatched_decision.action, "deny")
        self.assertFalse(mismatched_decision.pause)

        outside = self.root / "other-cache"
        outside.mkdir()
        outside_event = normalize_hook_event(
            {
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf other-cache"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(outside_event["effect"], "local_write")
        self.assertEqual(evaluate_event(applied, outside_event).action, "deny")

        target = self.root / "linked-target"
        target.mkdir()
        alias = self.root / "cache-link"
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink fixture unavailable: {error}")
        unsafe_commands = (
            "rm -rf other-cache ; true",
            "rm -rf other-*",
            "rm -rf cache-link",
            "rm -rf ../outside",
            "rm -rf /",
        )
        for unsafe_command in unsafe_commands:
            with self.subTest(command=unsafe_command):
                event = normalize_hook_event(
                    {
                        "cwd": str(self.root),
                        "tool_name": "Bash",
                        "tool_input": {"command": unsafe_command},
                    },
                    phase="started",
                    provider="codex",
                )
                decision = evaluate_event(applied, event)
                self.assertEqual(event["effect"], "destructive")
                self.assertEqual(decision.action, "deny")
                self.assertTrue(decision.pause)

    def test_codex_unified_exec_projects_one_literal_nested_command_at_pre(self) -> None:
        contract = self.contract()
        target = "/private/tmp/sulde-unified-exec-negative"
        source = (
            "const result = await tools.exec_command({"
            f"cmd:\"touch {target}\","
            f"workdir:\"{self.root}\",yield_time_ms:10000"
            "}); text(result.output);"
        )
        wrapped = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "wrapped-session",
                "cwd": str(self.root),
                "tool_name": "exec",
                "tool_input": source,
            },
            phase="started",
            provider="codex",
        )
        direct = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "wrapped-session",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": f"touch {target}"},
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(wrapped["orchestrator_wrapper"], "codex_unified_exec")
        self.assertEqual(wrapped["capability"], "tool:Bash")
        self.assertEqual(wrapped["effect"], "local_write")
        self.assertEqual(wrapped["target"], target)
        self.assertEqual(wrapped["write_targets"], [target])
        self.assertEqual(wrapped["arguments_digest"], direct["arguments_digest"])
        decision = evaluate_event(contract, wrapped)
        self.assertEqual(decision.action, "allow")
        self.assertFalse(decision.pause)

    def test_codex_unified_exec_dynamic_material_call_fails_closed_without_pause(self) -> None:
        contract = self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "wrapped-session",
                "cwd": str(self.root),
                "tool_name": "exec",
                "tool_input": (
                    "const command = getCommand();"
                    "await tools.exec_command({cmd: command});"
                ),
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(event["effect"], "unknown")
        self.assertEqual(
            event["uncertainty_kind"],
            "unresolved_orchestrator_effect",
        )
        decision = evaluate_event(contract, event)
        self.assertEqual(decision.action, "deny")
        self.assertFalse(decision.pause)

    def test_codex_unified_exec_projects_literal_apply_patch(self) -> None:
        contract = self.contract()
        patch = (
            "*** Begin Patch\n"
            "*** Update File: resume.md\n"
            "@@\n-old\n+new\n"
            "*** End Patch"
        )
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "wrapped-session",
                "cwd": str(self.root),
                "tool_name": "exec",
                "tool_input": (
                    "const result = await tools.apply_patch("
                    f"{json.dumps(patch)}"
                    "); text(result);"
                ),
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(event["capability"], "tool:apply_patch")
        self.assertEqual(event["effect"], "local_write")
        self.assertEqual(event["target"], "resume.md")
        self.assertEqual(evaluate_event(contract, event).action, "allow")

    def test_codex_unified_exec_keeps_literal_git_outside_intent_control(self) -> None:
        contract = self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "wrapped-session",
                "cwd": str(self.root),
                "tool_name": "exec",
                "tool_input": (
                    "const result = await tools.exec_command({"
                    "cmd:\"git status --short\""
                    "}); text(result.output);"
                ),
            },
            phase="started",
            provider="codex",
        )

        self.assertEqual(event["supervision_domain"], "execution_passthrough")
        self.assertEqual(event["execution_domain"], "git")
        self.assertEqual(evaluate_event(contract, event).action, "allow")

    def test_apply_patch_extracts_nested_payload_and_unresolved_target_fails_closed(self) -> None:
        contract = self.contract()
        nested = normalize_hook_event(
            {
                "tool_name": "apply_patch",
                "tool_input": {
                    "arguments": {
                        "input": {
                            "patch": (
                                "*** Begin Patch\n"
                                "*** Update File: resume.md\n"
                                "@@\n-old\n+new\n"
                                "*** End Patch"
                            )
                        }
                    }
                },
            },
            phase="started",
            provider="codex",
        )
        unresolved = normalize_hook_event(
            {
                "tool_name": "apply_patch",
                "tool_input": {"arguments": {"value": "not a patch envelope"}},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(nested["effect"], "local_write")
        self.assertEqual(nested["target"], "resume.md")
        self.assertEqual(evaluate_event(contract, nested).action, "allow")
        self.assertEqual(unresolved["effect"], "unknown")
        self.assertEqual(unresolved["target"], "[unresolved-patch-target]")
        self.assertEqual(evaluate_event(contract, unresolved).action, "deny")

    def test_subjective_task_requires_confirmed_intent_before_material_write(self) -> None:
        home = Path(self.temp.name) / "kb"
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            context = observe_user_prompt(
                {
                    "client": "codex",
                    "session_id": "thread",
                    "cwd": str(self.root),
                    "prompt": "帮我修改简历表达",
                },
                provider="codex",
            )
        path = active_contract_path(home, self.root)
        write = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": "resume.md"}},
            phase="started",
            provider="codex",
        )
        decision = evaluate_event(load_contract(path), write)
        self.assertEqual(decision.action, "deny")
        self.assertIn("尚未确认意图镜像", decision.reason)
        self.assertIn("confirmed_by=unconfirmed", context)
        denied = GuardianSession(path).observe(write)
        with self.assertRaisesRegex(IntentGuardianError, "retired"):
            approve_event(path, denied.fingerprint)
        self.assertEqual(load_contract(path)["status"], "active")
        self.assertEqual(evaluate_event(load_contract(path), write).action, "deny")
        with self.assertRaisesRegex(IntentGuardianError, "not paused"):
            resume_contract(path, "只确认恢复，不足以替代新镜像")

    def test_workspace_contract_is_created_even_without_native_session_id(self) -> None:
        home = Path(self.temp.name) / "kb"
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            context = observe_user_prompt(
                {
                    "client": "codex",
                    "cwd": str(self.root),
                    "prompt": "检查当前实现",
                },
                provider="codex",
            )
        self.assertIn("[sulde intent] ACTIVE", context)
        self.assertTrue(active_contract_path(home, self.root).is_file())

    def test_legacy_pre_gate_does_not_leave_phantom_guardian_event(self) -> None:
        try:
            __import__("yaml")
        except ModuleNotFoundError:
            self.skipTest("legacy hook fixture requires optional PyYAML")
        self.contract()
        frontend = self.root / "app"
        frontend.mkdir()
        (self.root / ".sulde-config.yaml").write_text(
            "role: coordinator\n"
            "enforcement_level: balanced\n"
            "enabled: true\n"
            "frontends:\n"
            "  - name: app\n"
            f"    path: {frontend}\n"
            "    stack: mobile-android\n",
            encoding="utf-8",
        )
        completed = self.run_hook(
            ROOT / "hooks" / "pre_tool_use.py",
            {
                "client": "claude",
                "session_id": "session",
                "cwd": str(self.root),
                "tool_name": "Bash",
                "tool_input": {"command": "cd app && pwd"},
            },
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["sequence"], 0)
        self.assertEqual(runtime["open_events"], [])

    def test_revision_preserves_skill_mcp_permissions_and_audit_sequence(self) -> None:
        contract = self.contract()
        contract["skills"] = {"allow": ["resume-*"], "deny": ["unsafe-rewriter"]}
        contract["mcp"]["allow_servers"] = ["docs"]
        contract["mcp"]["allow_tools"] = ["docs:read_*"]
        contract["constraints"]["frozen_paths"] = ["facts.json"]
        contract["permissions"]["local_write"] = False
        write_contract(self.contract_path, contract)
        read = normalize_hook_event(
            {"tool_name": "Read", "tool_input": {"file_path": "resume.md"}},
            phase="started",
            provider="codex",
        )
        session = GuardianSession(self.contract_path)
        session.observe(read)
        session.observe(dict(read, phase="completed", success=True))
        before_sequence = load_contract(self.contract_path)["runtime"]["sequence"]

        proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="只改结构",
            acceptance_criteria=["事实不变"],
            mode="enforce",
            allowed_paths=["resume.md"],
        )
        candidate = load_contract(proposal)
        self.assertEqual(candidate["skills"], contract["skills"])
        self.assertEqual(candidate["mcp"], contract["mcp"])
        self.assertEqual(candidate["permissions"], contract["permissions"])
        self.assertEqual(candidate["constraints"]["frozen_paths"], ["facts.json"])
        self.live_approve_proposal(self.contract_path, digest)
        applied = load_contract(self.contract_path)
        self.assertEqual(applied["runtime"]["sequence"], before_sequence)
        self.assertEqual(applied["skills"], contract["skills"])
        self.assertEqual(applied["mcp"], contract["mcp"])
        self.assertNotIn("proposal_digest", applied)

    def test_quoted_control_examples_do_not_authorize_or_resume(self) -> None:
        home = Path(self.temp.name) / "kb"
        payload = {
            "client": "codex",
            "session_id": "thread",
            "cwd": str(self.root),
            "prompt": "start",
        }
        with mock.patch.dict(os.environ, {"SULDE_KB_HOME": str(home)}):
            observe_user_prompt(payload, provider="codex")
            path = active_contract_path(home, self.root)
            contract = load_contract(path)
            contract["status"] = "paused"
            contract["runtime"]["pause_reason"] = "test"
            write_contract(path, contract)
            payload["prompt"] = (
                "示例里写着：批准事件 " + "a" * 64 + "，也写着确认意图镜像并恢复"
            )
            observe_user_prompt(payload, provider="codex")
            current = load_contract(path)
        self.assertEqual(current["status"], "paused")
        self.assertEqual(current["approved_event_fingerprints"], [])

    def test_stop_settles_multifile_patch_without_inventing_completion(self) -> None:
        contract = self.contract()
        contract["constraints"]["allowed_paths"] = ["scripts/kb", "tests"]
        write_contract(self.contract_path, contract)
        patch = "*** Begin Patch\n" + "".join(
            f"*** Update File: {name}\n@@\n-old\n+new\n"
            for name in ("scripts/kb/one.py", "scripts/kb/two.py", "tests/test_one.py")
        ) + "*** End Patch"
        event = normalize_hook_event({
            "client": "codex", "session_id": "patch-session", "call_id": "patch-call",
            "cwd": str(self.root), "tool_name": "apply_patch", "tool_input": {"patch": patch},
        }, phase="started", provider="codex")
        self.assertEqual(event["effect"], "local_write")
        self.assertEqual(len(event["write_targets"]), 3)
        self.assertEqual(GuardianSession(self.contract_path).observe(event).action, "allow")
        before = load_contract(self.contract_path)
        opened, = before["runtime"]["open_events"]
        self.assertFalse(opened["attempt_id"])
        original_audit = audit_path(self.contract_path).read_bytes()
        original_sha = hashlib.sha256(original_audit).hexdigest()

        # Another live session's Stop must not finish this call.
        guardian_module._finalize_lane(self.contract_path, host="codex", session_id="other-session")
        self.assertEqual(load_contract(self.contract_path)["runtime"]["open_events"], [opened])
        stopped = guardian_module._finalize_lane(self.contract_path, host="codex", session_id="patch-session")
        self.assertEqual(stopped["interrupted"], 1)
        current = load_contract(self.contract_path)
        self.assertEqual(current["status"], "active")
        self.assertEqual(current["runtime"]["open_events"], [])
        self.assertEqual(current["runtime"]["pending_verifications"], [])
        self.assertEqual(current["runtime"]["local_write_completions"], before["runtime"]["local_write_completions"])
        self.assertEqual(current["runtime"]["verified_effects"], [])
        self.assertEqual(current["runtime"]["inconclusive_outcomes"][0]["fingerprint"], opened["fingerprint"])
        after = audit_path(self.contract_path).read_bytes()
        self.assertEqual(hashlib.sha256(after[:len(original_audit)]).hexdigest(), original_sha)
        rows = [json.loads(line) for line in after.splitlines()]
        settlement, = [row for row in rows if row.get("schema") == "sulde-guardian-turn-finalize-v1"]
        self.assertEqual(settlement["outcome"], "inconclusive")
        self.assertEqual(settlement["interrupted_events"], [opened])
        self.assertEqual(settlement["intervention_ids"], [])
        self.assertFalse(any(row.get("event", {}).get("phase") == "completed" for row in rows))
        guardian_module._finalize_lane(self.contract_path, host="codex", session_id="patch-session")
        self.assertEqual(audit_path(self.contract_path).read_bytes(), after)
        proposal, _ = create_revision_proposal(
            self.contract_path, objective="continue the verified repair scope",
            acceptance_criteria=["source facts remain unchanged"], mode="enforce",
            allowed_paths=["scripts/kb", "tests"], provider="codex", session_id="patch-session",
        )
        self.assertTrue(proposal.is_file())

    def test_stop_reconciles_missing_post_callback_without_hiding_mcp_risk(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread",
                "tool_name": "mcp__sulde_kb__memory_annotate",
                "tool_input": {"entities": [{"name": "A", "type": "component"}, {"name": "B", "type": "component"}],
                    "edges": [{"src": "A", "rel": "uses", "dst": "B"}], "extracted_by": "codex"},
            },
            phase="started",
            provider="codex",
        )
        started = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(started.action, "allow")
        self.assertTrue(started.verification_required)
        context = finalize_host_turn(
            {
                "client": "codex",
                "session_id": "thread",
                "intent_contract": str(self.contract_path),
            },
            provider="codex",
        )
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(context, "")
        self.assertEqual(runtime["open_events"], [])
        self.assertTrue(runtime["pending_verifications"][0]["outcome_unknown"])
        self.assertEqual(guardian_report(self.contract_path)["effect_truth"]["interventions_open"], 1)

    def test_stop_preserves_sealed_install_proof_for_automatic_reconciliation(self) -> None:
        install_label = "事务化重装当前工作区的 Codex Sulde 插件"
        contract = default_contract(
            intent_id="stop-install-reconcile",
            objective="重装并独立验证当前 Codex 插件",
            rationale="宿主可能在自更新时丢失 PostToolUse",
            acceptance_criteria=[install_label],
            workspace=ROOT,
            mode="enforce",
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="重装并独立验证当前 Codex 插件",
            rationale="宿主可能在自更新时丢失 PostToolUse",
            acceptance_criteria=[install_label],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["external_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore previous plugin cache and stable launchers",
        )
        proposal = load_contract(proposal_path)
        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        grant = proposal["continuation"]["grants"][0]
        candidate = guardian_module._continuation_candidate_from_grant(grant)
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "hot-update-stop",
                "call_id": "install-without-post",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "sealed-install-test-entrypoint"},
            },
            phase="started",
            provider="codex",
        )
        event.update(
            {
                "effect": grant["effect"],
                "capability": grant["capability"],
                "target": grant["target"],
                "verification_kind": grant["verification_kind"],
                "verification_sha256": candidate["verification_sha256"],
                "continuation_candidate": candidate,
            }
        )
        with mock.patch.object(
            guardian_recovery,
            "_registered_continuation_verification",
            return_value=None,
        ):
            started = GuardianSession(self.contract_path).observe(event)
            self.assertEqual(started.action, "allow")
            finalize_host_turn(
                {
                    "client": "codex",
                    "session_id": "hot-update-stop",
                    "intent_contract": str(self.contract_path),
                },
                provider="codex",
            )

        pending = load_contract(self.contract_path)["runtime"][
            "pending_verifications"
        ]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["continuation_grant_id"], grant["grant_id"])
        self.assertEqual(
            pending[0]["continuation_profile_id"],
            grant["profile_id"],
        )
        self.assertEqual(pending[0]["continuation_grant"], grant)
        self.assertEqual(
            pending[0]["verification_sha256"],
            candidate["verification_sha256"],
        )

        independent = {
            "capability": "tool:codex_plugin_install_verify",
            "source": "local_codex_install_read",
            "evidence": {"content": [candidate["verification_sha256"]]},
        }
        with mock.patch.object(
            guardian_recovery,
            "_registered_continuation_verification",
            return_value=independent,
        ):
            reconciled = guardian_module.reconcile_pending_verifications(
                self.contract_path
            )
        self.assertEqual(len(reconciled), 1)
        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["pending_verifications"], [])
        projection = load_intervention_projection(self.contract_path)
        attempt_id = reconciled[0]["attempt_id"]
        self.assertEqual(projection["attempts"][attempt_id]["state"], "system_verified")

    def test_stop_runs_registered_verifier_before_returning(self) -> None:
        install_label = "事务化重装当前工作区的 Codex Sulde 插件"
        contract = default_contract(
            intent_id="stop-install-same-boundary",
            objective="重装并独立验证当前 Codex 插件",
            rationale="Stop 必须闭合可由本机证明的结果",
            acceptance_criteria=[install_label],
            workspace=ROOT,
            mode="enforce",
            confirmed_by="human",
        )
        write_contract(self.contract_path, contract)
        proposal_path, _ = create_revision_proposal(
            self.contract_path,
            objective="重装并独立验证当前 Codex 插件",
            rationale="Stop 必须闭合可由本机证明的结果",
            acceptance_criteria=[install_label],
            mode="enforce",
            decision_route="human",
            intent_kind="deterministic",
            risk="medium",
            effects=["external_write"],
            reversibility="reversible",
            cost="none",
            rollback="restore previous plugin cache and stable launchers",
        )
        proposal = load_contract(proposal_path)
        proposal["confirmed_by"] = "human-readable-proposal-approval"
        proposal["confirmation"] = {"required": False, "reason": ""}
        proposal["status"] = "active"
        write_contract(self.contract_path, proposal)
        grant = proposal["continuation"]["grants"][0]
        candidate = guardian_module._continuation_candidate_from_grant(grant)
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "hot-update-stop-immediate",
                "call_id": "install-without-post-immediate",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {"command": "sealed-install-test-entrypoint"},
            },
            phase="started",
            provider="codex",
        )
        event.update(
            {
                "effect": grant["effect"],
                "capability": grant["capability"],
                "target": grant["target"],
                "verification_kind": grant["verification_kind"],
                "verification_sha256": candidate["verification_sha256"],
                "continuation_candidate": candidate,
            }
        )
        independent = {
            "capability": "tool:codex_plugin_install_verify",
            "source": "local_codex_install_read",
            "evidence": {"content": [candidate["verification_sha256"]]},
        }
        with mock.patch.object(
            guardian_recovery,
            "_registered_continuation_verification",
            return_value=independent,
        ):
            started = GuardianSession(self.contract_path).observe(event)
            self.assertEqual(started.action, "allow")
            result = guardian_module._finalize_lane(
                self.contract_path,
                host="codex",
                session_id="hot-update-stop-immediate",
            )

        current = load_contract(self.contract_path)
        self.assertEqual(current["runtime"]["pending_verifications"], [])
        self.assertEqual(len(result["reconciled_attempt_ids"]), 1)
        attempt_id = result["reconciled_attempt_ids"][0]
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(projection["attempts"][attempt_id]["state"], "system_verified")
        self.assertEqual(
            current["runtime"]["verified_effects"][-1]["verification_source"],
            "system_reconciliation",
        )

    def test_stop_does_not_promote_interrupted_read_only_mcp_to_effect_intervention(self) -> None:
        self.contract()
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-read",
                "tool_name": "mcp__codex_apps__figma__get_screenshot",
                "tool_input": {"node_id": "954:321"},
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(event["effect"], "read")
        started = GuardianSession(self.contract_path).observe(event)
        self.assertEqual(started.action, "allow")

        context = finalize_host_turn(
            {
                "client": "codex",
                "session_id": "thread-read",
                "intent_contract": str(self.contract_path),
            },
            provider="codex",
        )

        runtime = load_contract(self.contract_path)["runtime"]
        report = guardian_report(self.contract_path)
        self.assertEqual(context, "")
        self.assertEqual(runtime["open_events"], [])
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(report["effect_truth"]["attempts"], 0)
        self.assertEqual(report["effect_truth"]["interventions_open"], 0)

    def test_reconcile_closes_legacy_read_only_effect_debt_without_erasing_audit(self) -> None:
        contract = self.contract()
        attempt = begin_effect_attempt(
            self.contract_path,
            intent_id=contract["intent_id"],
            intent_revision=contract["revision"],
            fingerprint="e" * 64,
            source_event_id="legacy-read-event",
            capability="mcp:codex_apps:figma__get_screenshot",
            target="954:321",
            effect="read",
            provider="codex",
            session_id="legacy-thread",
            idempotency_key="legacy-read-only-effect-debt",
            **self.typed_effect_identity(
                target="954:321",
                capability="mcp:codex_apps:figma__get_screenshot",
                effect="read",
                arguments_digest="e" * 64,
            ),
        )
        intervention = guardian_module.mark_attempt_unknown(
            self.contract_path,
            str(attempt["attempt_id"]),
            reason="legacy runtime treated every interrupted MCP call as material",
        )
        current = load_contract(self.contract_path)
        current["runtime"]["pending_verifications"].append(
            {
                "attempt_id": attempt["attempt_id"],
                "task_epoch": current["task_epoch"],
                "runtime_generation": "legacy",
                "fingerprint": "e" * 64,
                "capability": "mcp:codex_apps:figma__get_screenshot",
                "target": "954:321",
                "provider": "codex",
                "session_id": "legacy-thread",
                "created_at": guardian_module.now_iso(),
                "outcome_unknown": True,
            }
        )
        write_contract(self.contract_path, current)
        self.assertEqual(
            guardian_report(self.contract_path)["effect_truth"]["interventions_open"],
            1,
        )

        verified = guardian_module.reconcile_pending_verifications(self.contract_path)

        after = load_contract(self.contract_path)
        projection = load_intervention_projection(self.contract_path)
        resolved = projection["interventions"][intervention["intervention_id"]]
        self.assertEqual(verified, [])
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["decision"], "abort")
        self.assertEqual(resolved["actor"], "system-read-only-reconciler")
        self.assertEqual(
            guardian_report(self.contract_path)["effect_truth"]["interventions_open"],
            0,
        )

    def test_reconcile_corrects_production_shaped_figma_read_from_exact_rollout(self) -> None:
        contract = self.contract()
        session_id = "00000000-0000-7000-8000-000000000002"
        call_id = "exec-b6edc9b5-363d-4470-9b12-2e3b8f7fa297"
        arguments = {
            "fileKey": "0G32qTbFLqMfW5gG8wvv8X",
            "description": "Inspect existing pages and fonts",
            "skillNames": "figma-use",
            "code": (
                "const pages=figma.root.children.map(p=>"
                "({id:p.id,name:p.name,childCount:p.children.length}));"
                "const fonts=await figma.listAvailableFontsAsync();"
                "return {editorType:figma.editorType,pages,fonts:fonts.slice(0,80)};"
            ),
        }
        arguments_digest = guardian_resources._input_digest(arguments)
        unresolved_target = "[unresolved-figma-target]"
        resource_context = {
            "server": "figma",
            "resource_kind": "use_figma",
            "identifier": unresolved_target,
        }
        resource_key = guardian_module.canonical_resource_key(
            ("figma", "use_figma", unresolved_target), kind="mcp"
        )
        operation_fingerprint = guardian_module.effect_operation_fingerprint(
            provider="codex",
            capability="mcp:figma:use_figma",
            target=unresolved_target,
            resource_key=resource_key,
            effect="external_write",
            arguments_digest=arguments_digest,
        )
        attempt = begin_effect_attempt(
            self.contract_path,
            intent_id=contract["intent_id"],
            intent_revision=contract["revision"],
            fingerprint="a" * 64,
            source_event_id="production-shaped-figma-read",
            capability="mcp:figma:use_figma",
            target=unresolved_target,
            resource_key=resource_key,
            resource_context=resource_context,
            effect="external_write",
            provider="codex",
            session_id=session_id,
            idempotency_key=(
                f"dispatch:codex:{session_id}:{call_id}:" + "a" * 64
            ),
            operation_arguments_digest=arguments_digest,
            operation_fingerprint=operation_fingerprint,
            verification_kind="unsupported",
        )
        guardian_module.mark_attempt_result(
            self.contract_path,
            attempt["attempt_id"],
            success=True,
            reason="observable completion callback returned",
        )
        intervention = guardian_module.mark_attempt_unknown(
            self.contract_path,
            attempt["attempt_id"],
            reason="host turn ended before independent verification completed",
        )
        resolve_effect_intervention(
            self.contract_path,
            intervention["intervention_id"],
            decision="abort",
            evidence="operator ended intervention without replay",
            actor="permission-request:codex",
        )
        current = load_contract(self.contract_path)
        current["runtime"]["pending_verifications"].append(
            {
                "attempt_id": attempt["attempt_id"],
                "fingerprint": "a" * 64,
                "capability": "mcp:figma:use_figma",
                "target": unresolved_target,
                "provider": "codex",
                "session_id": session_id,
                "created_at": guardian_module.now_iso(),
                "outcome_unknown": True,
            }
        )
        write_contract(self.contract_path, current)
        rollout = (
            self.codex_home
            / "sessions/2026/09/02"
            / f"rollout-2026-09-02T00-00-00-{session_id}.jsonl"
        )
        rollout.parent.mkdir(parents=True)
        rollout.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "item_completed",
                        "item": {
                            "type": "McpToolCall",
                            "id": call_id,
                            "server": "codex_apps",
                            "tool": "figma.use_figma",
                            "arguments": arguments,
                            "readOnlyHint": False,
                            "status": "completed",
                            "result": {"content": [{"type": "text", "text": "{}"}], "isError": False},
                        },
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        before = guardian_module.authoritative_store_bytes(self.contract_path)

        reconciled = guardian_module.reconcile_pending_verifications(
            self.contract_path, recover_rollout_reads=True
        )

        after = load_contract(self.contract_path)
        projection = load_intervention_projection(self.contract_path)
        corrected = projection["attempts"][attempt["attempt_id"]]
        resolved = projection["interventions"][intervention["intervention_id"]]
        rows = [json.loads(line) for line in guardian_module.authoritative_store_bytes(
            self.contract_path
        ).decode("utf-8").splitlines()]
        self.assertEqual([row["attempt_id"] for row in reconciled], [attempt["attempt_id"]])
        self.assertEqual(after["runtime"]["pending_verifications"], [])
        self.assertEqual(corrected["effect"], "read")
        self.assertEqual(len(corrected["effect_classification_history"]), 1)
        self.assertEqual(resolved["decision"], "abort")
        self.assertEqual(resolved["actor"], "permission-request:codex")
        self.assertTrue(
            guardian_module.authoritative_store_bytes(self.contract_path).startswith(before)
        )
        self.assertEqual(rows[0]["effect"], "external_write")
        self.assertEqual(rows[-1]["type"], "effect.attempt_classification_corrected")

    def test_rollout_evidence_rejects_figma_argument_digest_mismatch(self) -> None:
        session_id = "00000000-0000-7000-8000-000000000002"
        call_id = "exec-b6edc9b5-363d-4470-9b12-2e3b8f7fa297"
        stored_arguments = {
            "fileKey": "0G32qTbFLqMfW5gG8wvv8X",
            "code": "return figma.root.children.map(page => page.name);",
        }
        rollout_arguments = {
            **stored_arguments,
            "code": "return figma.root.children.map(page => page.id);",
        }
        rollout = (
            self.codex_home
            / "sessions/2026/09/02"
            / f"rollout-2026-09-02T00-00-00-{session_id}.jsonl"
        )
        rollout.parent.mkdir(parents=True)
        rollout.write_text(
            json.dumps(
                {
                    "payload": {
                        "item": {
                            "type": "McpToolCall",
                            "id": call_id,
                            "server": "codex_apps",
                            "tool": "figma.use_figma",
                            "arguments": rollout_arguments,
                            "status": "completed",
                            "result": {"isError": False},
                        }
                    }
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        attempt = {
            "session_id": session_id,
            "idempotency_key": f"dispatch:codex:{session_id}:{call_id}:fixture",
            "operation_arguments_digest": guardian_resources._input_digest(
                stored_arguments
            ),
        }

        self.assertIsNone(
            guardian_figma_recovery._rollout_figma_read_evidence(attempt)
        )

    def test_stop_recovers_dispatch_logged_before_contract_runtime_crash(self) -> None:
        contract = self.contract()
        begin_effect_attempt(
            self.contract_path,
            intent_id=contract["intent_id"],
            intent_revision=contract["revision"],
            fingerprint="f" * 64,
            source_event_id="crash-window-event",
            capability="mcp:docs:update_document",
            target="doc://resume",
            effect="external_write",
            provider="codex",
            session_id="thread-crash",
            idempotency_key="dispatch-before-contract-crash",
        )
        self.assertEqual(load_contract(self.contract_path)["runtime"]["open_events"], [])
        finalize_host_turn(
            {
                "client": "codex",
                "session_id": "thread-crash",
                "intent_contract": str(self.contract_path),
            },
            provider="codex",
        )
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(len(runtime["pending_verifications"]), 1)
        self.assertTrue(runtime["pending_verifications"][0]["outcome_unknown"])
        self.assertEqual(guardian_report(self.contract_path)["effect_truth"]["interventions_open"], 1)

    def test_parallel_mixed_host_events_do_not_lose_sequence_updates(self) -> None:
        self.contract()

        def record(index: int) -> None:
            provider = "codex" if index % 2 else "claude"
            event = normalize_hook_event(
                {
                    "client": provider,
                    "session_id": f"session-{index}",
                    "tool_name": "Read",
                    "tool_input": {"file_path": "resume.md"},
                },
                phase="started",
                provider=provider,
            )
            GuardianSession(self.contract_path, provider=provider).observe(event)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(record, range(24)))
        contract = load_contract(self.contract_path)
        self.assertEqual(contract["runtime"]["sequence"], 24)
        rows = self.contract_path.with_name("intent.events.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 24)
        self.assertEqual(len({json.loads(row)["event"]["sequence"] for row in rows}), 24)

    def test_guardian_report_discloses_observation_limits(self) -> None:
        self.contract()
        report = guardian_report(self.contract_path)
        self.assertIn("explicit skill-start", report["coverage"]["codex_skill"])
        self.assertIn("not observed", report["coverage"]["reasoning"])

    def test_agent_control_plane_cannot_self_approve_or_resume(self) -> None:
        self.contract()
        launcher = f"{sys.executable} {SCRIPT_DIR / 'intent-guardian.py'}"
        for action in (
            "approve-event",
            "approve-proposal",
            "resume",
            "activate",
            "rebind-workspace",
            "retire-workspace",
        ):
            event = normalize_hook_event(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": f"{launcher} {action} {'a' * 64}"},
                },
                phase="started",
            )
            self.assertTrue(event["control_plane"])
            self.assertEqual(event["control_route"], "human")
            decision = GuardianSession(self.contract_path).observe(event)
            self.assertEqual(decision.action, "deny")
            self.assertFalse(decision.pause)
        self.assertEqual(load_contract(self.contract_path)["status"], "active")

    def test_native_proposal_description_discloses_destructive_and_external_scope(self) -> None:
        base_card = {
            "要完成的结果": "删除两个废弃模块并事务化安装",
            "允许改变": {"可修改路径": ["one.py", "two.py", "manifest.json"]},
            "风险与恢复": {"回滚方法": "恢复上一不可变版本"},
        }
        destructive = guardian_module.native_decision_description(
            {
                "kind": "proposal",
                "decision": "approve",
                "card": {
                    "决策内容": {
                        **base_card,
                        "执行权限边界": {
                            "破坏性操作": "当前可读方案内由监督器执行",
                            "外部写入": "卡片内声明且可独立验证的动作由监督器执行",
                        },
                    }
                },
            }
        )
        self.assertIn("包含卡片列明的破坏性操作", destructive)
        self.assertIn("外部写入仅限卡片列明的密封动作", destructive)
        self.assertNotIn("破坏性操作仍禁止", destructive)

        nondestructive = guardian_module.native_decision_description(
            {
                "kind": "proposal",
                "decision": "approve",
                "card": {
                    "决策内容": {
                        **base_card,
                        "执行权限边界": {
                            "破坏性操作": "禁止",
                            "外部写入": "禁止",
                        },
                    }
                },
            }
        )
        self.assertIn("破坏性操作仍禁止", nondestructive)
        self.assertNotIn("包含卡片列明的破坏性操作", nondestructive)

    def test_native_decision_precheck_defers_only_in_interactive_codex_mode(self) -> None:
        self.contract()
        _proposal, _digest = create_revision_proposal(
            self.contract_path,
            objective="通过当前会话原生确认框批准方案",
            acceptance_criteria=["不再复制事件摘要或命令"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        payload = self.native_permission_payload(preview)
        event = normalize_hook_event(payload, phase="started", provider="codex")
        self.assertEqual(event["control_route"], "native-permission")
        self.assertEqual(GuardianSession(self.contract_path).observe(event).action, "allow")

        for mode in ("dontAsk", "bypassPermissions", "plan"):
            with self.subTest(permission_mode=mode):
                blocked = normalize_hook_event(
                    {**payload, "permission_mode": mode},
                    phase="started",
                    provider="codex",
                )
                decision = GuardianSession(self.contract_path).observe(blocked)
                self.assertEqual(decision.action, "deny")
                self.assertIn("不会提供可验证的交互批准", decision.reason)

    def test_agent_cannot_forge_permission_request_hook_callback(self) -> None:
        self.contract()
        launcher = SCRIPT_DIR / "intent-guardian.py"
        run_hook = (
            ROOT
            / "integrations"
            / "codex"
            / "plugins"
            / "sulde"
            / "scripts"
            / "run-hook.sh"
        )
        for command in (
            shlex.join([sys.executable, str(ROOT / "hooks" / "pre_tool_use.py")]),
            shlex.join(["bash", str(run_hook), "permission-request"]),
            shlex.join(
                [sys.executable, str(launcher), "codex-hook", "permission-request"]
            ),
        ):
            with self.subTest(command=command):
                event = normalize_hook_event(
                    {
                        "client": "codex",
                        "session_id": "native-review",
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    },
                    phase="started",
                    provider="codex",
                )
                self.assertEqual(event["control_route"], "host-callback-invalid")
                decision = GuardianSession(self.contract_path).observe(event)
                self.assertEqual(decision.action, "deny")
                self.assertIn("不得伪造", decision.reason)

        syntax_check = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "native-review",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(["/bin/sh", "-n", str(run_hook)])
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertNotIn("control_route", syntax_check)
        self.assertEqual(syntax_check["effect"], "read")
        self.assertEqual(syntax_check["target"], str(run_hook))

        wrapped_source_read = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "native-review",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(
                        [
                            "/bin/sh",
                            "-c",
                            shlex.join(["sed", "-n", "1,20p", str(run_hook)]),
                        ]
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertNotIn("control_route", wrapped_source_read)
        self.assertEqual(wrapped_source_read["effect"], "read")

        wrapped_callback = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "native-review",
                "cwd": str(ROOT),
                "tool_name": "Bash",
                "tool_input": {
                    "command": shlex.join(
                        [
                            "/bin/sh",
                            "-c",
                            shlex.join(["bash", str(run_hook), "permission-request"]),
                        ]
                    )
                },
            },
            phase="started",
            provider="codex",
        )
        self.assertEqual(wrapped_callback["control_route"], "host-callback-invalid")

    def test_native_permission_applies_exact_readable_proposal_once(self) -> None:
        self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="通过当前会话原生确认框批准方案",
            acceptance_criteria=["一次 Allow 后直接继续"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        payload = self.native_permission_payload(preview)
        payload["tool_input"] = {
            "cmd": payload["tool_input"]["command"],
            "justification": preview["description"],
        }

        unpaired = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(unpaired["status"], "awaiting_human")
        self.assertFalse(unpaired["authority_transferred"])

        observed = observe_native_permission_request(payload, provider="codex")
        self.assertEqual(observed["action"], "defer")
        self.assertEqual(preview["decision_card"]["operation_id"], "proposal")
        self.assertEqual(preview["decision_card"]["decision_id"], "approve")
        self.assertEqual(preview["decision_card"]["action"], "approve-proposal")
        persisted_request = load_approval_projection(self.contract_path)[
            "requests"
        ][observed["request_id"]]
        self.assertEqual(
            persisted_request["card_sha256"],
            hashlib.sha256(
                json.dumps(
                    preview["decision_card"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )
        result = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )

        applied = load_contract(self.contract_path)
        self.assertEqual(result["status"], "applied")
        self.assertEqual(applied["objective"], "通过当前会话原生确认框批准方案")
        self.assertEqual(applied["applied_approval_channel"], "codex-native-permission")
        self.assertEqual(applied["applied_approval_source"], "live_host_hook")
        self.assertEqual(applied["applied_decision_authority"], "human")
        self.assertEqual(
            guardian_module.approval_pair_summary(self.contract_path)["open"], 0
        )

    def test_native_proposal_recovers_after_durable_human_decision(self) -> None:
        self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="批准落盘后崩溃仍自动完成内部方案应用",
            acceptance_criteria=["不再请求第二次人工批准"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-recovery",
        )
        observe_native_permission_request(
            self.native_permission_payload(
                preview,
                session_id="native-recovery",
            ),
            provider="codex",
        )
        receipt_fixture = load_contract(self.contract_path)
        guardian_module._record_approval_receipt_locked(
            receipt_fixture,
            action="approve-proposal",
            target=digest,
            actor="permission-request:codex",
            provider="codex",
            session_id="native-recovery",
            channel="codex-native-permission",
            observation_source="live_host_hook",
            approval_request_id="apr-000000000000000000000000",
        )
        self.assertIsNone(
            guardian_module._existing_approval_receipt_locked(
                receipt_fixture,
                action="approve-proposal",
                target=digest,
                actor="permission-request:codex",
                provider="codex",
                session_id="native-recovery",
                channel="codex-native-permission",
                observation_source="live_host_hook",
                approval_request_id="apr-111111111111111111111111",
            )
        )

        def crash_after_approval(stage: str) -> None:
            if stage == "after_approval_decided":
                raise RuntimeError("injected crash after native approval")

        with mock.patch.object(
            guardian_recovery,
            "_native_decision_failpoint",
            side_effect=crash_after_approval,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected crash"):
                execute_native_decision(
                    self.contract_path,
                    kind="proposal",
                    decision="approve",
                    target=digest,
                    provider="codex",
                    session_id="native-recovery",
                )

        before = load_native_decision_projection(self.contract_path)
        transaction = next(iter(before["transactions"].values()))
        self.assertEqual(transaction["stage"], "approval_decided")
        substituted = dict(transaction["binding"])
        substituted["card_sha256"] = "0" * 64
        self.assertFalse(
            guardian_module._native_approval_was_decided(
                self.contract_path,
                substituted,
            )
        )
        native_requests = [
            row
            for row in guardian_module.load_approval_projection(
                self.contract_path
            )["requests"].values()
            if row.get("source") == guardian_module.NATIVE_PERMISSION_SOURCE
        ]
        self.assertEqual(len(native_requests), 1)
        self.assertTrue(all(row["status"] == "decided" for row in native_requests))
        self.assertEqual(
            sum(
                row.get("event") == "permission_request"
                and row.get("status") == "control_presented"
                for row in load_contract(self.contract_path)["runtime"][
                    "host_observations"
                ]
            ),
            1,
        )

        GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="native-recovery",
        )
        applied = load_contract(self.contract_path)
        after = load_native_decision_projection(self.contract_path)
        transaction = next(iter(after["transactions"].values()))
        self.assertEqual(transaction["stage"], "committed")
        self.assertEqual(transaction["status"], "external_authority_unverified")
        self.assertEqual(transaction["historical_status"], "committed")
        replayed_head = advance_native_with_authority(
            self.contract_path.resolve(),
            transaction["transaction_id"],
            readers=NativeAuthorityReaders(None, None, None, None),
        )
        self.assertEqual(replayed_head["status"], "already_advanced")
        self.assertTrue(replayed_head["external_authority_verified"])
        self.assertEqual(
            applied["objective"],
            "批准落盘后崩溃仍自动完成内部方案应用",
        )
        native_requests = [
            row
            for row in guardian_module.load_approval_projection(
                self.contract_path
            )["requests"].values()
            if row.get("source") == guardian_module.NATIVE_PERMISSION_SOURCE
        ]
        self.assertEqual(len(native_requests), 1)

    def test_native_resume_recovers_commit_without_second_decision(self) -> None:
        original_path = self.contract_path
        cases = (
            ("after_prepared", "prepared", "paused"),
            ("after_contract_applied", "contract_applied", "active"),
            ("after_anchor_receipt", "contract_applied", "active"),
        )
        try:
            for index, (failpoint, expected_stage, expected_status) in enumerate(
                cases, 1
            ):
                with self.subTest(failpoint=failpoint):
                    case_root = Path(self.temp.name) / f"resume-crash-{index}"
                    case_root.mkdir()
                    self.contract_path = case_root / "intent.json"
                    self.contract()
                    guardian_module.pause_contract(
                        self.contract_path,
                        "等待当前会话明确恢复",
                        actor="human",
                    )
                    session_id = f"resume-recovery-{index}"
                    preview = native_decision_preview(
                        self.contract_path,
                        kind="resume",
                        decision="resume",
                        target="current",
                        provider="codex",
                        session_id=session_id,
                    )
                    observe_native_permission_request(
                        self.native_permission_payload(
                            preview,
                            session_id=session_id,
                        ),
                        provider="codex",
                    )

                    def crash_at_stage(stage: str) -> None:
                        if stage == failpoint:
                            raise RuntimeError(f"injected crash at {failpoint}")

                    with mock.patch.object(
                        guardian_recovery,
                        "_native_decision_failpoint",
                        side_effect=crash_at_stage,
                    ):
                        with self.assertRaisesRegex(RuntimeError, "injected crash"):
                            execute_native_decision(
                                self.contract_path,
                                kind="resume",
                                decision="resume",
                                target=preview["target"],
                                provider="codex",
                                session_id=session_id,
                            )

                    before = load_native_decision_projection(self.contract_path)
                    transaction = next(iter(before["transactions"].values()))
                    self.assertEqual(transaction["stage"], expected_stage)
                    self.assertEqual(
                        load_contract(self.contract_path)["status"], expected_status
                    )

                    GuardianSession(
                        self.contract_path,
                        provider="codex",
                        session_id=session_id,
                    )
                    after = load_native_decision_projection(self.contract_path)
                    transaction = next(iter(after["transactions"].values()))
                    self.assertEqual(transaction["stage"], "committed")
                    self.assertEqual(
                        guardian_module.approval_pair_summary(
                            self.contract_path
                        )["requests"],
                        1,
                    )
        finally:
            self.contract_path = original_path

    def test_native_effect_reprojects_authoritative_resolution_after_crash(self) -> None:
        self.contract()
        self.declare_effects(self.contract_path, "external_write")
        payload = {
            "client": "codex",
            "session_id": "effect-origin",
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://journal-recovery", "content": "new"},
        }
        started = normalize_hook_event(payload, phase="started", provider="codex")
        session = GuardianSession(self.contract_path)
        self.assertEqual(session.observe(started).action, "allow")
        self.assertEqual(
            session.observe(dict(started, phase="completed", success=False)).action,
            "allow",
        )
        intervention_id = next(
            iter(load_intervention_projection(self.contract_path)["interventions"])
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="effect-intervention",
            decision="retry_authorized",
            target=intervention_id,
            provider="codex",
            session_id="effect-recovery",
        )
        observe_native_permission_request(
            self.native_permission_payload(
                preview,
                session_id="effect-recovery",
            ),
            provider="codex",
        )

        def crash_after_effect(stage: str) -> None:
            if stage == "after_effect_applied":
                raise RuntimeError("injected crash after effect ledger")

        with mock.patch.object(
            guardian_recovery,
            "_native_decision_failpoint",
            side_effect=crash_after_effect,
        ):
            with self.assertRaisesRegex(RuntimeError, "injected crash"):
                execute_native_decision(
                    self.contract_path,
                    kind="effect-intervention",
                    decision="retry_authorized",
                    target=intervention_id,
                    provider="codex",
                    session_id="effect-recovery",
                )

        resolved = load_intervention_projection(self.contract_path)["interventions"][
            intervention_id
        ]
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["decision"], "retry_authorized")
        self.assertFalse(
            any(
                row.get("approval_request_id")
                for row in load_contract(self.contract_path)["runtime"][
                    "approval_receipts"
                ]
            )
        )

        GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="effect-recovery",
        )
        contract = load_contract(self.contract_path)
        receipts = [
            row
            for row in contract["runtime"]["approval_receipts"]
            if row.get("action") == "intervention-resolve"
        ]
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["consumed_at"])
        after = load_native_decision_projection(self.contract_path)
        transaction = next(iter(after["transactions"].values()))
        self.assertEqual(transaction["stage"], "committed")
        self.assertEqual(
            guardian_module.approval_pair_summary(self.contract_path)["requests"],
            1,
        )

    def test_native_preview_only_offers_abort_for_historical_attempt(self) -> None:
        self.contract()
        projection = {
            "attempts": {
                "attempt-historical": {
                    "attempt_id": "attempt-historical",
                    "provider": "codex",
                    "session_id": "origin-session",
                    "replay_authoritative": False,
                    "state": "effect_unknown",
                    "effect": "external_write",
                    "capability": "mcp:docs:update_document",
                    "target": "doc://historical",
                }
            },
            "interventions": {
                "int-historical": {
                    "intervention_id": "int-historical",
                    "attempt_id": "attempt-historical",
                    "status": "open",
                    "reason": "historical attempt has no replay binding",
                }
            },
        }
        with mock.patch.object(
            guardian_approvals,
            "load_intervention_projection",
            return_value=projection,
        ):
            for decision in ("retry_authorized", "reprobe_authorized"):
                with self.subTest(decision=decision):
                    with self.assertRaisesRegex(
                        IntentGuardianError, "only abort is available"
                    ):
                        native_decision_preview(
                            self.contract_path,
                            kind="effect-intervention",
                            decision=decision,
                            target="int-historical",
                            provider="codex",
                            session_id="recovery-session",
                        )
            preview = native_decision_preview(
                self.contract_path,
                kind="effect-intervention",
                decision="abort",
                target="int-historical",
                provider="codex",
                session_id="recovery-session",
            )
        self.assertEqual(preview["decision"], "abort")
        self.assertEqual(preview["target"], "int-historical")

    def test_native_recovery_continues_after_one_transaction_failure(self) -> None:
        first = {
            "transaction_id": "ndt-first",
            "stage": "approval_decided",
            "binding": {},
        }
        second = {
            "transaction_id": "ndt-second",
            "stage": "approval_decided",
            "binding": {},
        }
        with (
            mock.patch.object(
                guardian_recovery,
                "pending_native_transactions",
                return_value=[first, second],
            ),
            mock.patch.object(
                guardian_recovery,
                "_advance_native_transaction",
                side_effect=[
                    InterventionError("historical synthetic failure"),
                    {**second, "stage": "committed"},
                ],
            ),
        ):
            recovered = guardian_recovery.recover_native_decisions(
                self.contract_path
            )
        self.assertEqual(recovered[0]["transaction_id"], "ndt-first")
        self.assertEqual(recovered[0]["recovery_status"], "failed")
        self.assertEqual(recovered[1]["transaction_id"], "ndt-second")
        self.assertEqual(recovered[1]["stage"], "committed")

    def test_native_permission_rejects_changed_card_and_prompt_substitution(self) -> None:
        self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="审批精确绑定的方案",
            acceptance_criteria=["其他通道不能替代原生确认"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        changed = self.native_permission_payload(
            preview,
            description="批准一个没有绑定到当前方案的模糊动作",
        )
        self.assertEqual(
            observe_native_permission_request(changed, provider="codex")["action"],
            "deny",
        )

        observe_user_prompt(
            {
                "client": "codex",
                "session_id": "native-review",
                "cwd": str(self.root),
                "intent_contract": str(self.contract_path),
                "prompt": "先显示当前方案",
                "sulde_observation_source": "live_host_hook",
            },
            provider="codex",
        )
        unpaired = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(unpaired["status"], "awaiting_human")
        self.assertFalse(unpaired["authority_transferred"])

    def test_native_prompt_without_command_execution_grants_no_authority(self) -> None:
        self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="允许用户在原生确认框拒绝",
            acceptance_criteria=["拒绝时没有状态迁移"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        observed = observe_native_permission_request(
            self.native_permission_payload(preview), provider="codex"
        )
        current = load_contract(self.contract_path)
        self.assertEqual(observed["action"], "defer")
        self.assertEqual(current["runtime"]["approved_proposal_digests"], [])
        self.assertEqual(current["runtime"]["approval_receipts"], [])
        self.assertEqual(current["runtime"]["pending_proposal_digest"], digest)

    def test_permission_request_hook_defers_exact_card_and_denies_changed_text(self) -> None:
        self.contract()
        _proposal, digest = create_revision_proposal(
            self.contract_path,
            objective="验证 Codex PermissionRequest Hook",
            acceptance_criteria=["Hook 不替用户选择 Allow 或 Deny"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        payload = self.native_permission_payload(preview)
        hook = ROOT / "hooks" / "pre_tool_use.py"

        deferred = self.run_hook(
            hook, {**payload, "hook_event_name": "PermissionRequest"}
        )
        self.assertEqual(deferred.returncode, 0, deferred.stderr)
        self.assertEqual(deferred.stdout.strip(), "")
        applied = execute_native_decision(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target=digest,
            provider="codex",
            session_id="native-review",
        )
        self.assertEqual(applied["status"], "applied")

        # A stale or rewritten description is blocked before Codex can attach
        # the user's native click to a different decision card.
        other_contract = self.contract()
        self.assertEqual(other_contract["objective"], "改进简历表达，但不得改变事实")
        _proposal, _digest = create_revision_proposal(
            self.contract_path,
            objective="拒绝被替换的审批说明",
            acceptance_criteria=["说明必须逐字绑定"],
            mode="enforce",
            allowed_paths=["resume.md"],
            decision_route="human",
        )
        second_preview = native_decision_preview(
            self.contract_path,
            kind="proposal",
            decision="approve",
            target="current",
            provider="codex",
            session_id="native-review",
        )
        denied = self.run_hook(
            hook,
            {
                **self.native_permission_payload(
                    second_preview, description="批准未绑定的模糊方案"
                ),
                "hook_event_name": "PermissionRequest",
            },
        )
        output = json.loads(denied.stdout)
        decision = output["hookSpecificOutput"]["decision"]
        self.assertEqual(decision["behavior"], "deny")
        self.assertIn("description does not match", decision["message"])

    def test_native_permission_can_transfer_one_exact_effect_retry(self) -> None:
        self.contract()
        self.declare_effects(self.contract_path, "external_write")
        payload = {
            "client": "codex",
            "session_id": "original-session",
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://resume", "content": "new"},
        }
        started = normalize_hook_event(payload, phase="started", provider="codex")
        session = GuardianSession(self.contract_path)
        self.assertEqual(session.observe(started).action, "allow")
        self.assertEqual(
            session.observe(dict(started, phase="completed", success=False)).action,
            "allow",
        )
        intervention_id = next(
            iter(load_intervention_projection(self.contract_path)["interventions"])
        )
        preview = native_decision_preview(
            self.contract_path,
            kind="effect-intervention",
            decision="retry_authorized",
            target=intervention_id,
            provider="codex",
            session_id="recovery-session",
        )
        observed = observe_native_permission_request(
            self.native_permission_payload(
                preview,
                session_id="recovery-session",
            ),
            provider="codex",
        )
        self.assertEqual(observed["action"], "defer")
        result = execute_native_decision(
            self.contract_path,
            kind="effect-intervention",
            decision="retry_authorized",
            target=intervention_id,
            provider="codex",
            session_id="recovery-session",
        )
        projection = load_intervention_projection(self.contract_path)
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(
            projection["interventions"][intervention_id]["decision"],
            "retry_authorized",
        )
        self.assertEqual(
            projection["interventions"][intervention_id]["status"], "resolved"
        )
        self.assertEqual(
            projection["interventions"][intervention_id]["takeover_session_id"],
            "recovery-session",
        )

        retry = normalize_hook_event(
            {**payload, "session_id": "recovery-session", "call_id": "retry-call"},
            phase="started",
            provider="codex",
        )
        retry_operation = guardian_module.effect_operation_fingerprint(
            provider=retry["provider"],
            capability=retry["capability"],
            target=guardian_module._effect_attempt_target(retry),
            resource_key=guardian_module._effect_resource_identity(
                load_contract(self.contract_path),
                retry,
            )[0],
            effect=retry["effect"],
            arguments_digest=retry["arguments_digest"],
        )
        self.assertEqual(
            projection["interventions"][intervention_id]["operation_fingerprint"],
            retry_operation,
        )
        self.assertIsNotNone(
            guardian_module.retry_grant_for_event(
                self.contract_path,
                fingerprint=guardian_module.event_fingerprint(retry),
                operation_fingerprint=retry_operation,
                provider="codex",
                session_id="recovery-session",
            ),
            projection["interventions"][intervention_id],
        )
        retry_decision = GuardianSession(self.contract_path).observe(retry)
        self.assertEqual(retry_decision.action, "allow", retry_decision.reason)
        projection = load_intervention_projection(self.contract_path)
        attempts = list(projection["attempts"].values())
        self.assertEqual(len(attempts), 2)
        retry_attempt = next(
            row for row in attempts if row["session_id"] == "recovery-session"
        )
        self.assertEqual(
            retry_attempt["predecessor_attempt_id"],
            projection["interventions"][intervention_id]["attempt_id"],
        )
        self.assertEqual(
            projection["interventions"][intervention_id]["retry_consumed_by"],
            retry_attempt["attempt_id"],
        )

    def run_hook(self, script: Path, payload: dict) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(
            {
                "SULDE_INTENT_CONTRACT": str(self.contract_path),
                "SULDE_KB_HOME": str(Path(self.temp.name) / "kb"),
                "SULDE_SOURCE_ROOT": str(ROOT),
            }
        )
        return subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(payload),
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            timeout=20,
            check=False,
        )

    def test_claude_hooks_execute_declared_external_mcp_write_then_verify(self) -> None:
        self.contract()
        self.declare_effects(self.contract_path, "external_write")
        payload = {
            "client": "claude",
            "session_id": "session",
            "cwd": str(self.root),
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://resume", "content": "new"},
        }
        pre_script = ROOT / "hooks" / "pre_tool_use.py"
        post_script = ROOT / "hooks" / "post_tool_use.py"
        allowed = self.run_hook(pre_script, payload)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertFalse(allowed.stdout.strip())
        completed = self.run_hook(post_script, {**payload, "success": True})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(len(load_contract(self.contract_path)["runtime"]["pending_verifications"]), 1)

        read = {
            **payload,
            "tool_name": "mcp__docs__read_document",
            "tool_input": {"uri": "doc://resume"},
        }
        self.assertEqual(self.run_hook(pre_script, read).returncode, 0)
        self.assertEqual(
            self.run_hook(
                post_script,
                {**read, "tool_response": {"content": "new"}, "success": True},
            ).returncode,
            0,
        )
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(len(runtime["verified_effects"]), 1)

    def test_mcp_effect_identity_is_typed_complete_and_recomputed(self) -> None:
        self.contract()
        self.declare_effects(self.contract_path, "external_write")
        payload = {
            "client": "codex",
            "session_id": "typed-resource",
            "tool_name": "mcp__docs__update_document",
            "tool_input": {"uri": "doc://resume", "content": "new"},
        }
        started = normalize_hook_event(payload, phase="started", provider="codex")
        started["effect_resource_key"] = "v2:opaque:forged"
        started["effect_resource_context"] = {"schema": "exact", "value": "forged"}
        decision = GuardianSession(self.contract_path).observe(started)
        self.assertEqual(decision.action, "allow", decision.reason)

        projection = load_intervention_projection(self.contract_path)
        attempt = next(iter(projection["attempts"].values()))
        self.assertTrue(attempt["resource_key"].startswith("v2:mcp:"))
        self.assertEqual(
            attempt["resource_context"],
            {
                "server": "docs",
                "resource_kind": "document",
                "identifier": "doc://resume",
            },
        )
        self.assertEqual(
            attempt["operation_arguments_digest"], started["arguments_digest"]
        )
        self.assertNotEqual(attempt["resource_key"], "v2:opaque:forged")

        tampered = normalize_hook_event(payload, phase="started", provider="codex")
        tampered.update(
            {
                "fingerprint": guardian_module.event_fingerprint(tampered),
                "effect_resource_key": attempt["resource_key"],
                "effect_resource_context": {
                    **attempt["resource_context"],
                    "identifier": "doc://other",
                },
            }
        )
        with self.assertRaisesRegex(Exception, "identifier"):
            guardian_module.material_event_blocker(self.contract_path, tampered)

        missing_identifier = normalize_hook_event(
            {
                **payload,
                "tool_input": {"content": "new"},
            },
            phase="started",
            provider="codex",
        )
        with self.assertRaisesRegex(IntentGuardianError, "MCP resource identity"):
            GuardianSession(self.contract_path).observe(missing_identifier)

    def test_claude_failure_hook_closes_event_but_keeps_verification_debt(self) -> None:
        self.contract()
        payload = {
            "client": "claude",
            "session_id": "session",
            "cwd": str(self.root),
            "tool_name": "mcp__sulde_kb__memory_annotate",
            "tool_input": {"entities": [{"name": "A", "type": "component"}, {"name": "B", "type": "component"}],
                "edges": [{"src": "A", "rel": "uses", "dst": "B"}], "extracted_by": "claude"},
        }
        pre_script = ROOT / "hooks" / "pre_tool_use.py"
        post_script = ROOT / "hooks" / "post_tool_use.py"
        allowed = self.run_hook(pre_script, payload)
        self.assertEqual(allowed.returncode, 0)
        self.assertFalse(allowed.stdout.strip())
        failed = self.run_hook(
            post_script,
            {**payload, "hook_event_name": "PostToolUseFailure", "error": "server failed"},
        )
        self.assertEqual(failed.returncode, 0, failed.stderr)
        runtime = load_contract(self.contract_path)["runtime"]
        self.assertEqual(runtime["open_events"], [])
        self.assertTrue(runtime["pending_verifications"][0]["outcome_unknown"])

    def test_codex_adapter_emits_structured_pre_tool_denial_protocol(self) -> None:
        self.contract()
        script = ROOT / "integrations" / "codex" / "plugins" / "sulde" / "scripts" / "pre-tool-use.py"
        completed = self.run_hook(
            script,
            {
                "sessionId": "thread",
                "cwd": str(self.root),
                "toolName": "mcp__docs__update_document",
                "toolInput": {"uri": "doc://resume", "content": "new"},
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        output = json.loads(completed.stdout.strip())
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_broken_guardian_fails_closed_for_material_but_not_read(self) -> None:
        self.contract_path.write_text("{}\n", encoding="utf-8")
        hook = ROOT / "hooks" / "pre_tool_use.py"
        material = self.run_hook(
            hook,
            {
                "client": "codex",
                "session_id": "busy-session",
                "cwd": str(self.root),
                "tool_name": "Write",
                "tool_input": {"file_path": str(self.root / "resume.md")},
            },
        )
        self.assertEqual(material.returncode, 0, material.stderr)
        output = json.loads(material.stdout.strip())
        self.assertEqual(
            output["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertIn(
            "busy or unavailable",
            output["hookSpecificOutput"]["permissionDecisionReason"],
        )

        read = self.run_hook(
            hook,
            {
                "client": "codex",
                "session_id": "busy-session",
                "cwd": str(self.root),
                "tool_name": "Read",
                "tool_input": {"file_path": str(self.root / "resume.md")},
            },
        )
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(read.stdout, "")

        for command in (
            "git status --short",
            "git status && git diff --stat",
            f"{ROOT / 'scripts/kb/install-agents.sh'} --uninstall --provider codex",
        ):
            with self.subTest(command=command):
                recovery = self.run_hook(
                    hook,
                    {
                        "client": "codex",
                        "session_id": "busy-session",
                        "cwd": str(self.root),
                        "tool_name": "Bash",
                        "tool_input": {"command": command},
                    },
                )
                self.assertEqual(recovery.returncode, 0, recovery.stderr)
                self.assertEqual(recovery.stdout, "")

    def test_ordinary_hook_session_does_not_replay_entire_audit(self) -> None:
        self.contract()
        audit_path(self.contract_path).write_text(
            '{"event":"old"}\n' * 100,
            encoding="utf-8",
        )
        with mock.patch.object(
            GuardianSession,
            "_audit_digests",
            side_effect=AssertionError("ordinary Hook replayed historical audit"),
        ):
            session = GuardianSession(self.contract_path)
        self.assertFalse(session.authoritative_memory)

    def test_secret_in_artifact_prevents_critic_egress(self) -> None:
        contract = self.contract()
        baseline = self.initialize_critic_baseline()
        (self.root / "resume.md").write_text(
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n",
            encoding="utf-8",
        )
        event = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": "resume.md"}},
            phase="completed",
        )
        scope = intent_critic.build_task_critic_scope(
            {
                "task_id": "critic-secret-egress",
                "base_commit": baseline,
                "verification_run_id": "critic-secret-egress-run",
                "owned_paths": ["resume.md"],
                "evidence_floor_sequence": 0,
            },
            [],
            {"resume.md": "!missing"},
        )
        contract["critic"]["task_scope"] = scope.as_projection()
        event = intent_critic.bind_task_critic_checkpoint_event(event, scope)
        result = run_critic(
            contract,
            event,
            provider="codex",
            command=["/definitely/not/called"],
        )
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIn("密钥扫描", result["summary"])

    def test_critic_reads_one_structured_batch_without_splitting_commas(self) -> None:
        contract = self.contract()
        baseline = self.initialize_critic_baseline()
        first = self.root / "one.py"
        second = self.root / "name,with-comma.py"
        first.write_text("FIRST = True\n", encoding="utf-8")
        second.write_text("SECOND = True\n", encoding="utf-8")
        scope = intent_critic.build_task_critic_scope(
            {
                "task_id": "critic-structured-batch",
                "base_commit": baseline,
                "verification_run_id": "critic-structured-batch-run",
                "owned_paths": [first.name, second.name],
                "evidence_floor_sequence": 0,
            },
            [],
            {first.name: "!missing", second.name: "!missing"},
        )
        contract["critic"]["task_scope"] = scope.as_projection()
        batch_event = intent_critic.bind_task_critic_checkpoint_event(
            {
                "effect": "local_write",
                "target": guardian_module._local_target_label(
                    [first.name, second.name]
                ),
                "write_targets": [first.name, second.name],
                "target_overflow": 0,
            },
            scope,
        )
        evidence, missing = intent_critic._read_target(
            contract,
            batch_event,
        )

        self.assertEqual(missing, "")
        self.assertIn("TARGET: one.py", evidence)
        self.assertIn("TARGET: name,with-comma.py", evidence)
        self.assertIn("FIRST = True", evidence)
        self.assertIn("SECOND = True", evidence)

    def test_critic_drift_requires_constraint_and_evidence(self) -> None:
        with self.assertRaisesRegex(Exception, "requires violated constraints"):
            validate_result(
                {
                    "verdict": "drift",
                    "confidence": 0.99,
                    "summary": "looks wrong",
                    "violated_constraints": [],
                    "evidence": [],
                    "next_action": "pause_and_clarify",
                }
            )

    def test_critic_knowledge_consumer_honors_top_boundary(self) -> None:
        write_examples(self.root / "knowledge")
        contract = self.contract()
        event = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": "resume.md"}},
            phase="completed",
        )
        results = [
            {
                "doc_id": "skip-me",
                "source_path": "knowledge/synthetic-0.md",
                "score": 0.99,
                "applicability": "skip",
                "evidence_status": "verified",
                "role": "route_negative",
            },
            {
                "doc_id": "uncertain",
                "source_path": "knowledge/synthetic-0.md",
                "score": 0.95,
                "applicability": "inconclusive",
                "evidence_status": "inconclusive",
                "role": "root_cause",
            },
            {
                "doc_id": "work-model/synthetic-range-0",
                "source_path": "knowledge/synthetic-0.md",
                "score": 0.90,
                "applicability": "apply",
                "evidence_status": "verified",
                "role": "route_positive",
            },
        ]
        cli_result = intent_critic.kb_cli.CliResult(
            "ok", stdout=json.dumps(results, ensure_ascii=False)
        )
        with mock.patch.object(intent_critic, "__file__", str(self.root / "scripts/kb/intent_critic.py")), mock.patch.object(
            intent_critic.kb_cli, "run_cli", return_value=cli_result
        ):
            knowledge = intent_critic.relevant_knowledge(contract, event)

        self.assertEqual(knowledge, [])

    def test_critic_knowledge_consumer_accepts_top_verified_apply(self) -> None:
        write_examples(self.root / "knowledge")
        contract = self.contract()
        event = normalize_hook_event(
            {"tool_name": "Write", "tool_input": {"file_path": "resume.md"}},
            phase="completed",
        )
        results = [
            {
                "doc_id": "work-model/synthetic-range-0",
                "source_path": "knowledge/synthetic-0.md",
                "score": 0.99,
                "applicability": "apply",
                "evidence_status": "verified",
                "role": "route_positive",
            },
            {
                "doc_id": "skip-me",
                "source_path": "knowledge/synthetic-0.md",
                "score": 0.95,
                "applicability": "skip",
                "evidence_status": "verified",
                "role": "route_negative",
            },
        ]
        cli_result = intent_critic.kb_cli.CliResult(
            "ok", stdout=json.dumps(results, ensure_ascii=False)
        )
        with mock.patch.object(intent_critic, "__file__", str(self.root / "scripts/kb/intent_critic.py")), mock.patch.object(
            intent_critic.kb_cli, "run_cli", return_value=cli_result
        ) as run_cli:
            knowledge = intent_critic.relevant_knowledge(contract, event)

        self.assertEqual(
            [item["doc_id"] for item in knowledge],
            ["work-model/synthetic-range-0"],
        )
        self.assertIn("路由反例", knowledge[0]["guidance"])
        self.assertEqual(
            run_cli.call_args.args[3][-2:], ["--purpose", "route"]
        )
        prompt = intent_critic.build_prompt(contract, event, "observable diff", knowledge)
        self.assertIn("相关结构化沉淀", prompt)
        self.assertIn("意图契约优先于知识", prompt)

    def test_high_confidence_critic_drift_pauses(self) -> None:
        contract = self.contract()
        contract["critic"]["enabled"] = True
        for session_id in ("thread-a", "thread-b"):
            guardian_module._upsert_task_lane_locked(
                contract,
                provider="codex",
                session_id=session_id,
                state="bound",
                source="test",
            )
        write_contract(self.contract_path, contract)
        session = GuardianSession(
            self.contract_path,
            provider="codex",
            session_id="thread-a",
        )
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "thread-a",
                "tool_name": "Write",
                "tool_input": {"file_path": "resume.md"},
            },
            phase="completed",
            provider="codex",
        )
        paused = session.record_critic(
            {
                "verdict": "drift",
                "confidence": 0.98,
                "summary": "新增了未授权管理职责",
                "violated_constraints": ["事实不可改变"],
                "evidence": ["新增：带领十人团队"],
                "next_action": "pause_and_clarify",
            },
            event=event,
        )
        self.assertTrue(paused)
        current = load_contract(self.contract_path)
        self.assertEqual(current["status"], "paused")
        self.assertEqual(current["runtime"]["pause_scope"], "lane")
        self.assertIsNotNone(
            guardian_module._pause_state(
                current,
                provider="codex",
                session_id="thread-a",
            )
        )
        self.assertIsNone(
            guardian_module._pause_state(
                current,
                provider="codex",
                session_id="thread-b",
            )
        )


class H04TypedResourceHookRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "original"
        self.root.mkdir()
        self.git_env = {
            **os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, root: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=root, env=self.git_env,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def repository(self, name: str, branch: str = "feature") -> Path:
        root = self.base / name
        root.mkdir()
        self.git(root, "init", "-b", branch)
        self.git(root, "config", "user.name", "H04")
        self.git(root, "config", "user.email", "h04@example.invalid")
        (root / "tracked.txt").write_text("one\n", encoding="utf-8")
        self.git(root, "add", "--", "tracked.txt")
        self.git(root, "commit", "-m", "initial")
        return root

    def event(self, tool_name: str, tool_input: dict, *, cwd: Path | None = None) -> dict:
        return normalize_hook_event(
            {"client": "codex", "session_id": "h04-hook",
             "cwd": str(cwd or self.root), "tool_name": tool_name,
             "tool_input": tool_input},
            phase="started", provider="codex",
        )

    @unittest.skip("retired: Hook routing no longer classifies Git resources")
    def test_I04_linked_git_route_and_negative_boundaries(self) -> None:
        repository = self.repository("git-origin")
        self.git(repository, "branch", "linked")
        linked = self.base / "linked"
        self.git(repository, "worktree", "add", str(linked), "linked")
        read = self.event("Bash", {"command": "git status --short"}, cwd=linked)
        self.assertEqual(
            (read["resource_kind"], read["typed_resource"]["status"],
             read["typed_resource"]["action"]),
            ("git_metadata", "classified", "status"),
        )
        broad = self.event("Bash", {"command": "git add -A"}, cwd=linked)
        self.assertEqual(broad["typed_resource"]["status"], "rejected")
        main = self.repository("git-main", branch="main")
        release = self.event(
            "Bash", {"command": "git add -- tracked.txt"}, cwd=main
        )
        self.assertEqual(release["typed_resource"]["status"], "rejected")

    def worktree_repository(self, name: str) -> tuple[Path, Path]:
        repository = self.repository(name, branch="main")
        (repository / ".worktrees").mkdir()
        self.git(repository, "branch", "dev")
        dev = repository / ".worktrees" / "dev"
        self.git(repository, "worktree", "add", str(dev), "dev")
        return repository, dev

    def worktree_contract(self, repository: Path, target: Path) -> dict:
        contract = default_contract(
            intent_id="guardian-v3-worktree-test",
            objective="建立精确的隔离任务 worktree",
            rationale="验证 worktree 生命周期 Harness",
            acceptance_criteria=["精确目标被绑定且危险变体 fail closed"],
            workspace=repository,
            mode="enforce",
            preserve=["main 和现有 worktree 状态"],
            reject=["通用 .git 权限"],
            allowed_paths=[str(target)],
            confirmed_by="human",
        )
        contract["decision"] = {"effects": ["local_write"], "risk": "medium"}
        return contract

    @unittest.skip("retired: worktree lifecycle belongs to Git execution domain")
    def test_worktree_attach_existing_routes_to_exact_capability(self) -> None:
        repository, _dev = self.worktree_repository("worktree-attach-hook")
        self.git(repository, "branch", "task/restored")
        (repository / "tracked.txt").write_text(
            "unrelated dirty state\n", encoding="utf-8",
        )
        target = repository / ".worktrees" / "restored"
        event = self.event(
            "Bash",
            {"command": "git worktree add .worktrees/restored task/restored"},
            cwd=repository,
        )
        self.assertEqual(event["effect"], "local_write")
        self.assertEqual(event["capability"], "git.worktree.attach_existing")
        self.assertEqual(event["target"], str(target))
        self.assertEqual(event["write_targets"], [str(target)])
        self.assertEqual(
            (event["resource_kind"], event["typed_resource"]["status"]),
            ("git_worktree_lifecycle", "classified"),
        )
        decision = evaluate_event(self.worktree_contract(repository, target), event)
        self.assertIsInstance(decision, DecisionV2)
        self.assertEqual(decision.dispatch, "allow")
        self.assertEqual(decision.lifecycle, "continue")
        self.assertEqual(decision.authority, "task")
        self.assertEqual(decision.verification, "required")

    @unittest.skip("retired: worktree lifecycle belongs to Git execution domain")
    def test_worktree_create_branch_has_distinct_capability(self) -> None:
        repository, _dev = self.worktree_repository("worktree-create-hook")
        target = repository / ".worktrees" / "new-task"
        event = self.event(
            "exec_command",
            {
                "cmd": shlex.join([
                    "git", "-C", str(repository), "worktree", "add", "-b",
                    "task/new-task", str(target), "dev",
                ])
            },
            cwd=self.root,
        )
        self.assertEqual(event["capability"], "git.worktree.create_branch")
        self.assertEqual(event["typed_resource"]["status"], "classified")
        self.assertEqual(
            evaluate_event(self.worktree_contract(repository, target), event).dispatch,
            "allow",
        )

    @unittest.skip("retired: worktree lifecycle belongs to Git execution domain")
    def test_linked_worktree_add_uses_tool_workdir_not_session_cwd(self) -> None:
        repository, _dev = self.worktree_repository("worktree-tool-workdir")
        self.git(repository, "branch", "task/stage")
        task = repository / ".worktrees" / "stage"
        self.git(repository, "worktree", "add", str(task), "task/stage")
        (task / "tracked.txt").write_text("task change\n", encoding="utf-8")
        event = normalize_hook_event(
            {
                "client": "codex",
                "session_id": "h04-hook",
                "cwd": str(repository),
                "tool_name": "exec_command",
                "tool_input": {
                    "cmd": "git add -- tracked.txt",
                    "workdir": str(task),
                },
            },
            phase="started",
            provider="codex",
        )
        exact_target = str(task / "tracked.txt")
        self.assertEqual(event["target"], exact_target)
        self.assertEqual(event["write_targets"], [exact_target])
        contract = self.worktree_contract(repository, task)
        self.assertEqual(evaluate_event(contract, event).dispatch, "allow")

    @unittest.skip("retired: Guardian no longer rejects Git pre-tool events")
    def test_worktree_pretool_rejection_never_pauses_or_creates_debt(self) -> None:
        repository, _dev = self.worktree_repository("worktree-deny-hook")
        occupied = repository / ".worktrees" / "occupied"
        self.git(repository, "branch", "task/occupied")
        self.git(repository, "worktree", "add", str(occupied), "task/occupied")
        target = repository / ".worktrees" / "second"
        event = self.event(
            "Bash",
            {"command": "git worktree add .worktrees/second task/occupied"},
            cwd=repository,
        )
        self.assertEqual(event["typed_resource"]["status"], "rejected")
        decision = evaluate_event(self.worktree_contract(repository, target), event)
        self.assertEqual(decision.dispatch, "deny")
        self.assertEqual(decision.lifecycle, "continue")
        self.assertEqual(decision.verification, "none")
        self.assertEqual(decision.evidence_state, "observed")
        self.assertFalse(decision.pause)
        self.assertFalse(decision.verification_required)

        broad = self.event(
            "Bash",
            {
                "command": (
                    "git worktree add --force .worktrees/second task/occupied"
                )
            },
            cwd=repository,
        )
        broad_decision = evaluate_event(
            self.worktree_contract(repository, target), broad,
        )
        self.assertEqual(broad_decision.dispatch, "deny")
        self.assertEqual(broad_decision.lifecycle, "continue")
        self.assertEqual(broad_decision.verification, "none")

        contract_path = self.base / "worktree-deny.intent.json"
        write_contract(
            contract_path, self.worktree_contract(repository, target),
        )
        observed = GuardianSession(
            contract_path, provider="codex", session_id="h04-hook",
        ).observe(event)
        persisted = load_contract(contract_path)
        self.assertEqual(observed.action, "deny")
        self.assertEqual(persisted["status"], "active")
        self.assertEqual(persisted["runtime"]["open_events"], [])
        self.assertEqual(persisted["runtime"]["pending_verifications"], [])

    @unittest.skip("retired: Guardian no longer verifies Git completion")
    def test_worktree_completion_uses_sealed_prestate_and_settles(self) -> None:
        repository, _dev = self.worktree_repository("worktree-complete-hook")
        self.git(repository, "branch", "task/restored")
        target = repository / ".worktrees" / "restored"
        contract_path = self.base / "worktree-complete.intent.json"
        write_contract(
            contract_path, self.worktree_contract(repository, target),
        )
        payload = {
            "client": "codex",
            "session_id": "h04-hook",
            "call_id": "worktree-call-1",
            "cwd": str(repository),
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "git worktree add .worktrees/restored task/restored"
                )
            },
        }
        started = normalize_hook_event(
            payload, phase="started", provider="codex",
        )
        authorized = GuardianSession(
            contract_path, provider="codex", session_id="h04-hook",
        ).observe(started)
        self.assertEqual(authorized.dispatch, "allow")
        self.assertEqual(authorized.verification, "required")
        opened = load_contract(contract_path)["runtime"]["open_events"]
        self.assertEqual(len(opened), 1)
        self.assertEqual(
            opened[0]["typed_resource"]["resource"]["resource_id"],
            started["typed_resource"]["resource_id"],
        )

        self.git(
            repository, "worktree", "add", str(target), "task/restored",
        )
        completed = normalize_hook_event(
            {**payload, "success": True}, phase="completed", provider="codex",
        )
        self.assertEqual(completed["typed_resource"]["status"], "completion")
        settled, resolved_path = guardian_module.process_hook(
            {
                **payload,
                "success": True,
                "intent_contract": str(contract_path),
            },
            phase="completed",
            provider="codex",
        )
        self.assertEqual(resolved_path, contract_path)
        self.assertIsNotNone(settled)
        self.assertEqual(settled.dispatch, "allow")
        runtime = load_contract(contract_path)["runtime"]
        self.assertEqual(runtime["open_events"], [])
        self.assertEqual(runtime["pending_verifications"], [])
        self.assertEqual(
            runtime["verified_effects"][-1]["evidence_source"],
            "local_git_worktree_lifecycle_read",
        )
        attempts = load_intervention_projection(contract_path)["attempts"]
        self.assertEqual(next(iter(attempts.values()))["state"], "system_verified")

    @unittest.skip("retired: Guardian no longer creates Git completion debt")
    def test_worktree_completion_drift_keeps_debt_without_pause(self) -> None:
        repository, _dev = self.worktree_repository("worktree-drift-hook")
        self.git(repository, "branch", "task/drifted")
        target = repository / ".worktrees" / "drifted"
        contract_path = self.base / "worktree-drift.intent.json"
        write_contract(
            contract_path, self.worktree_contract(repository, target),
        )
        payload = {
            "client": "codex",
            "session_id": "h04-hook",
            "call_id": "worktree-call-drift",
            "cwd": str(repository),
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "git worktree add .worktrees/drifted task/drifted"
                )
            },
        }
        started = normalize_hook_event(
            payload, phase="started", provider="codex",
        )
        GuardianSession(
            contract_path, provider="codex", session_id="h04-hook",
        ).observe(started)
        (repository / "tracked.txt").write_text(
            "drift after authorization\n", encoding="utf-8",
        )
        self.git(
            repository, "worktree", "add", str(target), "task/drifted",
        )
        completed = normalize_hook_event(
            {**payload, "success": True}, phase="completed", provider="codex",
        )
        guardian_audit._prepare_git_worktree_completion_verification(
            completed, load_contract(contract_path),
        )
        self.assertEqual(
            completed["independent_verification"]["receipt"]["status"],
            "failed",
        )
        observed = GuardianSession(
            contract_path, provider="codex", session_id="h04-hook",
        ).observe(completed)
        runtime = load_contract(contract_path)["runtime"]
        self.assertEqual(observed.lifecycle, "continue")
        self.assertEqual(runtime["open_events"], [])
        self.assertEqual(len(runtime["pending_verifications"]), 1)
        self.assertEqual(
            runtime["pending_verifications"][0]["independent_verifier_status"],
            "failed",
        )
        self.assertEqual(load_contract(contract_path)["status"], "active")

    @unittest.skip("retired: Guardian no longer tracks Git dispatch completion")
    def test_worktree_failed_completion_closes_dispatch_without_verifier(self) -> None:
        repository, _dev = self.worktree_repository("worktree-failed-hook")
        self.git(repository, "branch", "task/failed")
        target = repository / ".worktrees" / "failed"
        contract_path = self.base / "worktree-failed.intent.json"
        write_contract(
            contract_path, self.worktree_contract(repository, target),
        )
        payload = {
            "client": "codex",
            "session_id": "h04-hook",
            "call_id": "worktree-call-failed",
            "cwd": str(repository),
            "tool_name": "Bash",
            "tool_input": {
                "command": "git worktree add .worktrees/failed task/failed"
            },
        }
        started = normalize_hook_event(
            payload, phase="started", provider="codex",
        )
        GuardianSession(
            contract_path, provider="codex", session_id="h04-hook",
        ).observe(started)
        completed = normalize_hook_event(
            {**payload, "success": False},
            phase="completed",
            provider="codex",
        )
        guardian_audit._prepare_git_worktree_completion_verification(
            completed, load_contract(contract_path),
        )
        self.assertEqual(completed["verification_kind"], "relation")
        self.assertNotIn("independent_verification", completed)
        GuardianSession(
            contract_path, provider="codex", session_id="h04-hook",
        ).observe(completed)
        runtime = load_contract(contract_path)["runtime"]
        self.assertEqual(runtime["open_events"], [])
        self.assertEqual(len(runtime["pending_verifications"]), 1)
        self.assertTrue(runtime["pending_verifications"][0]["outcome_unknown"])
        self.assertFalse(target.exists())

    def test_I09_recursive_delete_route_and_alias_failure(self) -> None:
        target = self.root / "failed-package"
        target.mkdir()
        (target / "temporary").write_text("x", encoding="utf-8")
        event = self.event("Bash", {"command": "rm -rf -- failed-package"})
        typed = event["typed_resource"]
        self.assertEqual(
            (typed["kind"], typed["status"], typed["action"]),
            ("local_delete", "classified", "delete_tree"),
        )
        alias = self.root / "alias"
        alias.symlink_to(target, target_is_directory=True)
        rejected = self.event("Bash", {"command": "rm -rf -- alias"})
        self.assertEqual(rejected["typed_resource"]["status"], "rejected")

    @unittest.skip("retired: cross-project authority is path-root based, not Git based")
    def test_I14_cross_project_route_names_only_one_repository(self) -> None:
        granted = self.repository("granted")
        sibling = self.repository("sibling")
        event = self.event(
            "Bash", {"command": f"git -C {shlex.quote(str(granted))} status --short"}
        )
        typed = event["typed_resource"]
        self.assertEqual((typed["kind"], typed["status"]), ("workspace", "classified"))
        self.assertEqual(
            typed["constraints"]["repository_id"],
            resource_adapters.classify_git_metadata(granted)["resource_id"],
        )
        self.assertNotEqual(
            typed["constraints"]["repository_id"],
            resource_adapters.classify_git_metadata(sibling)["resource_id"],
        )

    def test_I15_figma_readback_and_empty_target_isolation(self) -> None:
        event = self.event(
            "mcp__figma__use_figma",
            {"fileKey": "File_123", "pageId": "page:1", "nodeId": "12:34",
             "mutationKind": "set_text", "payload": {"text": "approved"},
             "readback": {"kind": "get_design_context", "node": "12:34"}},
        )
        typed = event["typed_resource"]
        self.assertEqual((typed["kind"], typed["status"]), ("figma", "classified"))
        self.assertRegex(typed["constraints"]["readback_sha256"], r"^sha256:[0-9a-f]{64}$")
        missing = self.event(
            "mcp__figma__use_figma",
            {"mutationKind": "set_text", "payload": {},
             "readback": {"node": "1:2"}},
        )
        self.assertEqual(missing["typed_resource"]["status"], "rejected")
        self.assertEqual(missing["target"], "[unresolved-figma-target]")
        local = self.event(
            "apply_patch", {"patch": "*** Begin Patch\n*** End Patch"}
        )
        self.assertNotIn("resource_kind", local)
        self.assertNotEqual(local["target"], "[unresolved-figma-target]")

    def test_I17_device_artifact_and_denied_operations(self) -> None:
        artifact = self.root / "fixture.apk"
        artifact.write_bytes(b"fixture")
        installed = self.event(
            "mcp__device__install",
            {"serial": "device-01", "package": "com.example.fixture",
             "artifact": str(artifact), "data_namespace": "test:fixture",
             "original_user_data": False},
        )
        typed = installed["typed_resource"]
        self.assertEqual((typed["kind"], typed["status"]), ("device", "classified"))
        self.assertEqual(typed["constraints"]["artifact_path"], str(artifact))
        for operation in ("purchase", "clear_data"):
            denied = self.event(
                f"mcp__device__{operation}",
                {"serial": "device-01", "package": "com.example.fixture"},
            )
            self.assertEqual(denied["typed_resource"]["status"], "rejected")

    def test_I19_terminal_debt_vs_live_unresolved_write(self) -> None:
        resource = resource_adapters.classify_figma(
            "use_figma", {"fileKey": "File", "nodeId": "1:2",
            "mutationKind": "set_text", "payload": {"text": "x"},
            "readback": {"node": "1:2"}}, provider="codex",
        )
        action = resource_adapters.prepare_figma_action(
            resource, grant_identity="sha256:" + "a" * 64,
            dispatch_identity="gbd-i19", provider="codex",
            session_id="h04-hook", task_epoch="1" * 24,
        )
        terminal = [{"resource_id": resource["resource_id"],
            "resource_kind": "figma", "effect": "external_write",
            "state": "quarantined"}]
        unresolved = [{"resource_id": "", "resource_kind": "figma",
            "effect": "external_write", "state": "pending"}]
        self.assertIsNone(resource_adapters.resource_debt_blocker(action, terminal))
        self.assertEqual(
            resource_adapters.resource_debt_blocker(action, unresolved),
            unresolved[0],
        )
        local = self.event(
            "apply_patch", {"patch": "*** Begin Patch\n*** End Patch"}
        )
        self.assertNotEqual(local["effect"], "external_write")


if __name__ == "__main__":
    unittest.main()

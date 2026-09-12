from __future__ import annotations

import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "kb"))

STATUS_SPEC = importlib.util.spec_from_file_location(
    "sulde_status_readiness_test",
    ROOT / "scripts" / "kb" / "sulde-status.py",
)
assert STATUS_SPEC is not None and STATUS_SPEC.loader is not None
STATUS = importlib.util.module_from_spec(STATUS_SPEC)
STATUS_SPEC.loader.exec_module(STATUS)

LIFE_SPEC = importlib.util.spec_from_file_location(
    "sulde_life_cycle_readiness_test",
    ROOT / "scripts" / "kb" / "life-cycle.py",
)
assert LIFE_SPEC is not None and LIFE_SPEC.loader is not None
LIFE = importlib.util.module_from_spec(LIFE_SPEC)
LIFE_SPEC.loader.exec_module(LIFE)

from approval_invariant import (  # noqa: E402
    ask_approval,
    decide_approval,
    event_store_path as approval_store_path,
)
from host_capabilities import (  # noqa: E402
    issue_host_provenance,
    provision_provenance_key,
    record_observation,
    workspace_identifier,
)
from intervention import (  # noqa: E402
    begin_attempt,
    canonical_resource_key,
    mark_attempt_result,
    mark_attempt_unknown,
    resolve_intervention,
    verify_from_read,
)
from intent_guardian_parts.pre_execution_proof import (  # noqa: E402
    PROOF_SCHEMA,
    proof_id as pre_execution_proof_id,
)
from operational_readiness import (  # noqa: E402
    project,
    runtime_tree_digest,
    scheduler_process_projection,
)
import native_decision_journal  # noqa: E402
from session_continuity import build_capsule, continuation_path  # noqa: E402


class OperationalReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name) / "kb"
        self.workspace = Path(self.temporary.name) / "project"
        self.runtime_root = Path(self.temporary.name) / "runtime"
        self.runtime_root.mkdir()
        (self.runtime_root / "runtime.txt").write_text("fixture\n", encoding="utf-8")
        state_module = (
            self.runtime_root / "scripts/kb/intent_guardian_parts/state.py"
        )
        state_module.parent.mkdir(parents=True)
        state_module.write_text("# guardian module fixture\n", encoding="utf-8")
        self.loaded_module_generation = hashlib.sha256(
            state_module.read_bytes()
        ).hexdigest()
        self.runtime_digest = runtime_tree_digest(self.runtime_root)
        self.generation = f"fixture:{self.runtime_digest}"
        labels = [f"com.sulde.fixture-{index:02d}" for index in range(1, 16)]
        self.labels = labels
        self.retired_labels = ["com.sulde.retired-fixture"]
        self.ready_scheduler_probe = {
            "status": "ready",
            "reasons": [],
            "managed": len(labels),
            "loaded": len(labels),
            "missing_labels": [],
            "failed_labels": {},
            "retired_loaded_labels": [],
            "probe_status": "observed",
            "inventory_sha256": hashlib.sha256(
                (
                    "managed\0"
                    + "\0".join(sorted(labels))
                    + "\nretired\0"
                    + "\0".join(sorted(self.retired_labels))
                ).encode("utf-8")
            ).hexdigest(),
        }
        self.home.mkdir()
        (self.home / "deployment-generation.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "installed_live_unverified",
                    "provider": "codex",
                    "runtime_root": str(self.runtime_root.resolve()),
                    "runtime_tree_sha256": self.runtime_digest,
                    "generation": self.generation,
                    "managed_labels": labels,
                    "retired_labels": self.retired_labels,
                }
            ),
            encoding="utf-8",
        )
        (self.home / "runtime-owner.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "status": "active",
                    "provider": "codex",
                    "scheduler": "launchd",
                    "executable": sys.executable,
                    "runtime_root": str(self.runtime_root.resolve()),
                    "runtime_tree_sha256": self.runtime_digest,
                    "generation": self.generation,
                    "managed_labels": labels,
                    "retired_labels": self.retired_labels,
                }
            ),
            encoding="utf-8",
        )
        self.environment = mock.patch.dict(
            os.environ,
            {
                "SULDE_RUNTIME_ROOT": str(self.runtime_root),
                "SULDE_RUNTIME_GENERATION": self.generation,
                "SULDE_TEST_MODE": "1",
                "SULDE_KB_HOME": str(self.home),
                # Unit fixtures own their temporary append-only authorities;
                # the parent managed L3 stream must not leak into that scope.
                "SULDE_GUARDIAN_STREAM_OWNER": "",
            },
            clear=False,
        )
        self.environment.start()
        for name in ("SULDE_HOST_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID"):
            os.environ.pop(name, None)
        (self.workspace / ".git").mkdir(parents=True)
        key = workspace_identifier(self.workspace).split(":", 1)[1]
        self.contract_path = (
            self.home / "intent" / "workspaces" / f"{key}.active.json"
        )
        self.contract_path.parent.mkdir(parents=True)
        provision_provenance_key(self.home)

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def write_contract(
        self,
        *,
        status: str = "active",
        task_epoch: str = "epoch-one",
        pending_proposal: str = "",
        pending_verifications: list[dict] | None = None,
        task_lanes: list[dict] | None = None,
        pause_scope: str = "",
    ) -> None:
        self.contract_path.write_text(
            json.dumps(
                {
                    "intent_id": "operational-fixture",
                    "revision": 1,
                    "task_epoch": task_epoch,
                    "status": status,
                    "mode": "enforce",
                    "confirmed_by": "test",
                    "confirmation": {"required": False},
                    "runtime": {
                        "pending_proposal_digest": pending_proposal,
                        "pending_verifications": pending_verifications or [],
                        "task_lanes": task_lanes or [],
                        "pause_scope": pause_scope,
                    },
                }
            ),
            encoding="utf-8",
        )

    def observe(
        self,
        event: str,
        *,
        source: str = "live_host_hook",
        session_id: str = "session-one",
        now: datetime | None = None,
        call_id: str = "",
        runtime_sha256: str | None = None,
    ) -> None:
        def record() -> None:
            proof = (
                issue_host_provenance(
                    provider="codex",
                    hook_event=event,
                    session_id=session_id,
                    workspace=self.workspace,
                    call_id=call_id,
                    source=source,
                    home=self.home,
                    now=now,
                )
                if source == "live_host_hook"
                else None
            )
            record_observation(
                provider="codex",
                hook_event=event,
                session_id=session_id,
                workspace=self.workspace,
                call_id=call_id,
                source=source,
                provenance=proof,
                home=self.home,
                now=now,
            )

        if runtime_sha256 is None:
            record()
            return
        with mock.patch(
            "host_capabilities.runtime_identity", return_value=runtime_sha256
        ):
            record()

    def readiness(self, *, session_id: str = "session-one") -> dict:
        return project(
            self.home,
            provider="codex",
            session_id=session_id,
            workspace=self.workspace,
            scheduler_probe=self.ready_scheduler_probe,
        )

    def projected(self, **kwargs: object) -> dict:
        kwargs.setdefault("provider", "codex")
        kwargs.setdefault("scheduler_probe", self.ready_scheduler_probe)
        return project(self.home, **kwargs)

    def launchctl_output(
        self,
        *,
        missing: str = "",
        failed: str = "",
        retired_loaded: bool = False,
    ) -> str:
        rows = []
        for index, label in enumerate(self.labels):
            if label == missing:
                continue
            status = "7" if label == failed else "0"
            pid = "-" if label == failed else str(1000 + index)
            rows.append(f"{pid}\t{status}\t{label}")
        if retired_loaded:
            rows.append(f"-\t0\t{self.retired_labels[0]}")
        return "\n".join(rows)

    def observe_operational_cycle(self, *, session_id: str = "session-one") -> None:
        for event in (
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "Stop",
        ):
            self.observe(event, session_id=session_id)

    def write_pre_execution_proof(
        self,
        *,
        session_id: str = "session-one",
        generation: str | None = None,
    ) -> dict:
        contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        proof = {
            "schema": PROOF_SCHEMA,
            "probe_id": "a" * 32,
            "provider": "codex",
            "session_id": session_id,
            "runtime_generation": self.loaded_module_generation,
            "loaded_module_generation": self.loaded_module_generation,
            "artifact_generation": generation or self.generation,
            "target": "/private/tmp/sulde-readiness-proof-fixture",
            "started_event_id": "started-fixture",
            "started_call_id": "call-fixture",
            "decision_fingerprint": "b" * 64,
            "prepared_at": "2026-08-31T00:00:00+00:00",
            "verified_at": "2026-08-31T00:00:01+00:00",
            "gaps_cleared": 0,
        }
        proof["proof_id"] = pre_execution_proof_id(proof)
        contract["runtime"].setdefault("pre_execution_proofs", []).append(proof)
        self.contract_path.write_text(json.dumps(contract), encoding="utf-8")
        return proof

    def ask_native_proposal(
        self,
        target: str,
        *,
        session_id: str = "session-one",
    ) -> tuple[dict, dict]:
        card = {"question": "apply fixture proposal", "target": target}
        request = ask_approval(
            self.contract_path,
            intent_id="operational-fixture",
            intent_revision=1,
            kind="proposal",
            target=target,
            provider="codex",
            session_id=session_id,
            source="codex_permission_request",
            card=card,
            workspace=self.workspace,
            route="human",
            reassess_after_seconds=300,
            ttl_seconds=86_400,
        )
        return request, card

    def current_lane(
        self,
        proposal_digest: str,
        *,
        task_epoch: str = "epoch-one",
    ) -> dict:
        return {
            "provider": "codex",
            "session_id": "session-one",
            "task_epoch": task_epoch,
            "proposal_digest": proposal_digest,
            "state": "bound",
            "source": "fixture",
        }

    def write_pending_capsule(self, digest: str, *, source_session: str) -> None:
        capsule = build_capsule(
            contract_path=self.contract_path,
            proposal_path=self.contract_path.with_name("proposal.json"),
            review={
                "intent_id": "operational-fixture",
                "base_revision": 1,
                "proposed_revision": 2,
                "proposal_digest": digest,
                "decision_route": "human",
                "decision_card": {"question": "next revision"},
            },
            workspace_root=self.workspace,
            created_at="2026-08-31T00:00:00+00:00",
            provider="codex",
            session_id=source_session,
        )
        continuation_path(self.contract_path, digest).write_text(
            json.dumps(capsule),
            encoding="utf-8",
        )

    def native_binding(
        self,
        request: dict,
        target: str,
        *,
        session_id: str = "session-one",
        revision: int = 1,
        task_epoch: str | None = "epoch-one",
        schema: str = "sulde-native-transaction-binding-v5",
    ) -> dict:
        binding = {
            "schema": schema,
            "operation": "proposal",
            "request_id": request["request_id"],
            "kind": "proposal",
            "decision": "approve",
            "target": target,
            "action": "approve-proposal",
            "approval_kind": "proposal",
            "intent_id": "operational-fixture",
            "intent_revision": revision,
            "workspace": str(self.workspace.resolve()),
            "provider": "codex",
            "session_id": session_id,
            "source": "codex_permission_request",
            "card_sha256": request["card_sha256"],
            "request_binding_sha256": "a" * 64,
            "seal_id": "nds-" + "b" * 24,
            "seal_event_id": "c" * 64,
        }
        if task_epoch is not None:
            binding["task_epoch"] = task_epoch
        if schema == "sulde-native-transaction-binding-v5":
            binding["effect_attempt_id"] = ""
            binding["effect_subject_intent_revision"] = 0
        return binding

    @staticmethod
    def native_transaction(
        suffix: int,
        binding: dict,
        *,
        status: str = "active",
        stage: str = "prepared",
    ) -> dict:
        return {
            "transaction_id": f"ndt-{suffix:032x}",
            "binding": binding,
            "stage": stage,
            "status": status,
            "historical_status": (
                "committed" if status == "external_authority_unverified" else status
            ),
            "local_consistency_verified": status != "active",
            "external_authority_verified": False,
        }

    def set_request_deadlines(
        self,
        *,
        reassess_at: datetime,
        expires_at: datetime,
    ) -> None:
        store = approval_store_path(self.contract_path)
        rows = [json.loads(line) for line in store.read_text(encoding="utf-8").splitlines()]
        rows[0]["reassess_at"] = reassess_at.isoformat()
        rows[0]["expires_at"] = expires_at.isoformat()
        store.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def test_active_enforced_contract_with_fresh_live_session_is_ready(self) -> None:
        self.write_contract()
        self.observe_operational_cycle()
        readiness = self.readiness()
        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(all(readiness["gates"].values()))

    def test_native_task_continuation_requires_current_generation_pre_denial(self) -> None:
        lane = self.current_lane("a" * 64)
        lane["source"] = "native_session_continuation"
        self.write_contract(task_lanes=[lane])
        self.observe_operational_cycle()

        unproven = self.readiness()
        self.assertEqual(unproven["status"], "degraded")
        self.assertFalse(unproven["gates"]["pre_execution_safety_proven"])
        self.assertEqual(
            unproven["pre_execution_safety_readiness"]["status"], "unverified"
        )

        self.write_pre_execution_proof(generation="old:" + "0" * 64)
        stale = self.readiness()
        self.assertFalse(stale["gates"]["pre_execution_safety_proven"])

        proof = self.write_pre_execution_proof()
        proven = self.readiness()
        self.assertEqual(proven["status"], "ready")
        self.assertTrue(proven["gates"]["pre_execution_safety_proven"])
        self.assertEqual(
            proven["pre_execution_safety_readiness"]["last_proof"], proof
        )

    def test_foreign_pending_proposal_does_not_degrade_bound_task_lane(self) -> None:
        target = "f" * 64
        self.write_contract(
            pending_proposal=target,
            task_lanes=[self.current_lane("a" * 64)],
        )
        self.write_pending_capsule(target, source_session="session-two")
        self.observe_operational_cycle()

        readiness = self.readiness()

        self.assertFalse(readiness["approval_required"])
        self.assertEqual(
            readiness["native_decision_pairing_readiness"]["status"],
            "not_required",
        )
        self.assertEqual(readiness["status"], "ready")

    def test_pending_proposal_owner_lane_has_one_unsettled_decision(self) -> None:
        target = "e" * 64
        self.write_contract(
            pending_proposal=target,
            task_lanes=[self.current_lane("a" * 64)],
        )
        self.write_pending_capsule(target, source_session="session-one")
        self.observe_operational_cycle()

        readiness = self.readiness()
        decision = readiness["native_decision_pairing_readiness"]

        self.assertTrue(readiness["approval_required"])
        self.assertEqual(decision["status"], "unsettled")
        self.assertEqual(decision["unsettled"], 1)
        self.assertEqual(readiness["status"], "degraded")

    def test_post_only_material_gap_blocks_green_readiness_for_same_session(self) -> None:
        self.write_contract()
        contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        contract["runtime"]["pre_execution_gaps"] = [{
            "at": "2026-08-30T09:58:07+00:00",
            "provider": "codex",
            "session_id": "session-one",
            "runtime_generation": self.generation,
            "event_id": "gap-event",
            "capability": "tool:Bash",
            "effect": "local_write",
            "target": "/private/tmp/sulde-canary",
            "reason_code": "task_scope_denied",
        }]
        self.contract_path.write_text(json.dumps(contract), encoding="utf-8")
        self.observe_operational_cycle()

        readiness = self.readiness()

        self.assertEqual(readiness["status"], "degraded")
        self.assertFalse(readiness["gates"]["pre_execution_safety_clear"])
        self.assertEqual(
            readiness["pre_execution_safety_readiness"]["blocking_gaps"], 1
        )
        self.assertEqual(
            readiness["pre_execution_safety_readiness"]["reset_boundary"],
            "verified_negative_canary_same_session_generation",
        )

    def test_scheduler_failure_does_not_reclassify_live_interactive_supervision(self) -> None:
        self.write_contract()
        self.observe_operational_cycle()
        readiness = self.projected(
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            scheduler_probe={
                "status": "degraded",
                "reasons": ["managed_actor_last_exit_nonzero"],
            },
        )
        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(readiness["readiness_scope"], "interactive")
        self.assertEqual(readiness["interactive_readiness"]["status"], "ready")
        self.assertEqual(readiness["scheduler_readiness"]["status"], "degraded")
        self.assertNotIn("scheduler_ready", readiness["gates"])
        self.assertNotIn("scheduler_generation_ready", readiness["gates"])

    def test_long_lived_active_session_does_not_require_restart(self) -> None:
        self.write_contract()
        started = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)
        self.observe("SessionStart", now=started)
        for event in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
            self.observe(event, now=started + timedelta(hours=3))
        readiness = self.projected(
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            now=started + timedelta(hours=3, minutes=1),
        )
        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["gates"]["host_interactive_fresh"])
        self.assertTrue(readiness["gates"]["host_supervision_fresh"])

    def test_hot_rebound_active_turn_is_operational_without_a_restart_or_stop(self) -> None:
        self.write_contract()
        started = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)
        previous_runtime = "7" * 64
        current_runtime = "8" * 64
        self.observe(
            "SessionStart", now=started, runtime_sha256=previous_runtime
        )
        self.observe(
            "UserPromptSubmit",
            now=started + timedelta(minutes=1),
            runtime_sha256=previous_runtime,
        )
        self.observe(
            "PreToolUse",
            now=started + timedelta(hours=2),
            call_id="hot-roundtrip",
            runtime_sha256=current_runtime,
        )
        self.observe(
            "PostToolUse",
            now=started + timedelta(hours=2, seconds=1),
            call_id="hot-roundtrip",
            runtime_sha256=current_runtime,
        )

        readiness = self.projected(
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            expected_runtime_sha256=current_runtime,
            now=started + timedelta(hours=2, minutes=1),
        )

        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(
            readiness["host_readiness"]["runtime_continuity"]["status"],
            "verified",
        )
        self.assertEqual(
            readiness["host_readiness"]["capabilities"]["turn_reconcile"]["status"],
            "unobserved",
        )
        self.assertTrue(readiness["gates"]["host_interactive_fresh"])
        self.assertTrue(readiness["gates"]["host_supervision_fresh"])

    def test_background_scheduler_can_be_ready_without_claiming_interactive_ready(self) -> None:
        probe = scheduler_process_projection(
            self.home,
            platform_name="darwin",
            launchctl_list_output=self.launchctl_output(),
        )
        readiness = project(self.home, provider="codex", scheduler_probe=probe)
        self.assertEqual(readiness["readiness_scope"], "scheduler")
        self.assertEqual(readiness["status"], "ready")
        self.assertEqual(readiness["scheduler_readiness"]["status"], "ready")
        self.assertEqual(readiness["interactive_readiness"]["status"], "unobserved")
        self.assertEqual(readiness["host_readiness"]["status"], "unobserved")
        self.assertEqual(readiness["artifact_generation_readiness"]["status"], "ready")
        self.assertEqual(probe["loaded"], 15)
        # Recovery is a separate additive domain: its reachability must remain
        # observable even when scheduler or ordinary interactive readiness fails.
        self.assertEqual(
            set(readiness["domains"]),
            {
                "artifact_generation",
                "scheduler",
                "interactive",
                "pre_execution_safety",
                "effect_debt",
                "native_decision_pairing",
                "recovery",
            },
        )

    def test_project_without_explicit_probe_is_never_scheduler_ready(self) -> None:
        with mock.patch("operational_readiness.sys.platform", "linux"):
            readiness = project(self.home, provider="codex")
        self.assertEqual(readiness["artifact_generation_readiness"]["status"], "ready")
        self.assertEqual(readiness["scheduler_readiness"]["status"], "degraded")
        self.assertEqual(readiness["status"], "degraded")
        self.assertIn(
            "scheduler_probe:launchd_runtime_unavailable",
            readiness["reasons"],
        )

    def test_installed_live_unverified_is_not_live_process_truth(self) -> None:
        probe = scheduler_process_projection(
            self.home,
            platform_name="darwin",
            runner=lambda *args, **kwargs: types.SimpleNamespace(
                returncode=1,
                stdout="",
            ),
            aqua_session_available=True,
        )
        readiness = project(self.home, provider="codex", scheduler_probe=probe)
        self.assertEqual(
            readiness["artifact_generation_readiness"]["deployment_status"],
            "installed_live_unverified",
        )
        self.assertEqual(readiness["artifact_generation_readiness"]["status"], "ready")
        self.assertEqual(readiness["scheduler_readiness"]["status"], "degraded")
        self.assertIn("launchctl_list_unavailable", probe["reasons"])
        self.assertIsNone(probe["loaded"])
        self.assertEqual(probe["missing_labels"], [])
        self.assertFalse(probe["missing_observed"])

    def test_readiness_never_enters_native_journal_recovery_lock(self) -> None:
        with mock.patch.object(
            native_decision_journal,
            "_store_lock",
            side_effect=AssertionError("readiness entered write/recovery lock"),
        ):
            readiness = project(
                self.home,
                provider="codex",
                session_id="readonly-diagnostic",
                workspace=self.workspace,
                scheduler_probe=self.ready_scheduler_probe,
            )
        self.assertIn(readiness["native_decision_pairing_readiness"]["status"], {
            "ready", "degraded", "cas_mismatch", "unavailable"
        })

    def test_live_probe_invokes_only_minimal_launchctl_list(self) -> None:
        calls = []

        def runner(arguments: list[str], **kwargs: object) -> object:
            calls.append((arguments, kwargs))
            return types.SimpleNamespace(
                returncode=0,
                stdout=self.launchctl_output(),
            )

        probe = scheduler_process_projection(
            self.home,
            platform_name="darwin",
            runner=runner,
            aqua_session_available=True,
        )
        self.assertEqual(probe["status"], "ready")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], ["launchctl", "list"])
        self.assertNotIn("env", calls[0][1])

    def test_live_probe_ignores_historical_exit_for_running_actor(self) -> None:
        label = self.labels[0]
        running_rows = self.launchctl_output().replace(
            f"1000\t0\t{label}", f"1000\t7\t{label}"
        )
        running = scheduler_process_projection(
            self.home,
            platform_name="darwin",
            runner=lambda *args, **kwargs: types.SimpleNamespace(
                returncode=0,
                stdout=running_rows,
            ),
            aqua_session_available=True,
        )
        self.assertEqual(running["status"], "ready")
        self.assertEqual(running["failed_labels"], {})

        exited_rows = running_rows.replace(
            f"1000\t7\t{label}", f"-\t7\t{label}"
        )
        exited = scheduler_process_projection(
            self.home,
            platform_name="darwin",
            runner=lambda *args, **kwargs: types.SimpleNamespace(
                returncode=0,
                stdout=exited_rows,
            ),
            aqua_session_available=True,
        )
        self.assertEqual(exited["status"], "degraded")
        self.assertEqual(exited["failed_labels"], {label: "7"})

    def test_life_cycle_fails_closed_for_each_scheduler_process_failure(self) -> None:
        fake_l2 = types.SimpleNamespace(
            build_registry=lambda _home: {"status": "ready", "channels": {}}
        )
        fake_evolution = types.SimpleNamespace(
            reconcile=lambda _home, _l2, _l3, _apply: {
                "status": "ready",
                "active": 0,
                "recommendations": 0,
            }
        )

        def load_module(_name: str, path: Path) -> object:
            return fake_l2 if path == LIFE.L2_SCRIPT else fake_evolution

        unavailable = scheduler_process_projection(
            self.home,
            platform_name="darwin",
            runner=lambda *args, **kwargs: types.SimpleNamespace(
                returncode=1,
                stdout="",
            ),
            aqua_session_available=True,
        )
        failures = (
            scheduler_process_projection(
                self.home,
                platform_name="darwin",
                launchctl_list_output=self.launchctl_output(
                    missing=self.labels[-1]
                ),
            ),
            scheduler_process_projection(
                self.home,
                platform_name="darwin",
                launchctl_list_output=self.launchctl_output(
                    failed=self.labels[-1]
                ),
            ),
            unavailable,
        )
        with mock.patch.object(LIFE, "load_module", side_effect=load_module), mock.patch.object(
            LIFE,
            "l3_projection",
            return_value={"status": "ready", "counts": {}, "items": []},
        ):
            for probe in failures:
                reason = probe["reasons"][-1]
                with self.subTest(reason=reason):
                    state = LIFE.build(self.home, scheduler_probe=probe)
                    self.assertEqual(state["status"], "degraded")
                    self.assertEqual(
                        state["operational_readiness"]["status"],
                        "degraded",
                    )
                    self.assertIn(
                        f"scheduler_probe:{reason}",
                        state["operational_readiness"]["reasons"],
                    )

    def test_status_and_life_cycle_share_one_injected_probe_truth(self) -> None:
        probe = {
            **self.ready_scheduler_probe,
            "status": "degraded",
            "reasons": ["retired_actors_loaded"],
            "retired_loaded_labels": self.retired_labels,
        }
        status = STATUS.collect(scheduler_probe=probe)
        status_projection = status["operational_readiness"]
        fake_l2 = types.SimpleNamespace(
            build_registry=lambda _home: {"status": "ready", "channels": {}}
        )
        fake_evolution = types.SimpleNamespace(
            reconcile=lambda _home, _l2, _l3, _apply: {
                "status": "ready",
                "active": 0,
                "recommendations": 0,
            }
        )

        def load_module(_name: str, path: Path) -> object:
            return fake_l2 if path == LIFE.L2_SCRIPT else fake_evolution

        with mock.patch.object(LIFE, "load_module", side_effect=load_module), mock.patch.object(
            LIFE,
            "l3_projection",
            return_value={"status": "ready", "counts": {}, "items": []},
        ):
            life = LIFE.build(self.home, scheduler_probe=probe)
        self.assertEqual(status_projection["status"], "degraded")
        self.assertEqual(status["scheduler_health"]["status"], "degraded")
        self.assertEqual(life["status"], "degraded")
        self.assertEqual(life["operational_readiness"], status_projection)

    def test_background_scheduler_process_failure_is_not_hidden_by_artifact_pass(self) -> None:
        readiness = self.projected(
            provider="codex",
            scheduler_probe={
                "status": "degraded",
                "reasons": ["managed_actors_missing"],
            },
        )
        self.assertEqual(readiness["artifact_generation_readiness"]["status"], "ready")
        self.assertEqual(readiness["scheduler_readiness"]["status"], "degraded")
        self.assertEqual(readiness["interactive_readiness"]["status"], "unobserved")
        self.assertEqual(readiness["status"], "degraded")
        self.assertIn(
            "scheduler_probe:managed_actors_missing",
            readiness["reasons"],
        )

    def test_interactive_provider_does_not_rewrite_scheduler_owner_truth(self) -> None:
        readiness = self.projected(
            provider="claude",
            session_id="claude-session",
            workspace=self.workspace,
        )
        self.assertEqual(readiness["scheduler_readiness"]["status"], "ready")
        self.assertEqual(readiness["scheduler_readiness"]["provider"], "codex")
        self.assertEqual(readiness["provider"], "claude")
        self.assertEqual(readiness["interactive_readiness"]["status"], "degraded")

    def test_status_cli_surfaces_share_projection_and_nonzero_exit(self) -> None:
        operational = self.projected(
            provider="codex",
            scheduler_probe={
                "status": "degraded",
                "reasons": ["managed_actor_last_exit_nonzero"],
            },
        )
        status = {
            "ok": False,
            "warn": True,
            "kb_home": str(self.home),
            "missing_sources": [],
            "kb_docs": 1,
            "kb_edges": 1,
            "mem_total": 1,
            "mem_today": 0,
            "mem_pending_embedding": 0,
            "harvest_age_seconds": 0,
            "distill_age_seconds": 0,
            "mem_last_capture_age_seconds": 0,
            "life_status": "ready",
            "life_evolution_status": "ready",
            "life_age_seconds": 0,
            "runtime_available": True,
            "launcher_contract_healthy": True,
            "launcher_contract_issues": [],
            "kb_index_stale": False,
            "event_contract_violations": 0,
            "interventions_open": 0,
            "intervention_invalid_stores": 0,
            "effect_blocking": 0,
            "fleet_stalled": 0,
            "scheduler_health": operational["scheduler_readiness"],
            "operational_readiness": operational,
        }

        with mock.patch.object(STATUS, "collect", return_value=status), mock.patch.object(
            sys, "argv", ["sulde-status.py", "--json"]
        ), io.StringIO() as output, contextlib.redirect_stdout(output):
            json_exit = STATUS.main()
            json_payload = json.loads(output.getvalue())
        self.assertEqual(json_exit, 1)
        self.assertEqual(json_payload["operational_readiness"], operational)

        with mock.patch.object(
            STATUS, "kb_home", return_value=self.home
        ), mock.patch.object(
            STATUS, "collect", side_effect=AssertionError("statusline performed full scan")
        ), mock.patch.object(
            sys, "argv", ["sulde-status.py", "--statusline"]
        ), io.StringIO() as output, contextlib.redirect_stdout(output):
            statusline_exit = STATUS.main()
            rendered = output.getvalue()
        self.assertEqual(statusline_exit, 1)
        self.assertIn("交互可用·调度降级", rendered)
        self.assertIn("scheduler_process_ready", rendered)

        with mock.patch.object(STATUS, "collect", return_value=status), mock.patch.object(
            STATUS, "notify"
        ) as notify, mock.patch.object(
            sys, "argv", ["sulde-status.py", "--notify"]
        ):
            notify_exit = STATUS.main()
        self.assertEqual(notify_exit, 0)
        notify.assert_called_once_with(status)
        warnings = STATUS.notification_warnings(status)
        self.assertTrue(
            any(
                warning.startswith("后台调度未就绪: scheduler_process_ready")
                for warning in warnings
            )
        )

        self.write_contract(status="paused")
        self.observe_operational_cycle()
        interactive = self.readiness()
        interactive_status = {
            **status,
            "operational_readiness": interactive,
            "scheduler_health": interactive["scheduler_readiness"],
        }
        self.assertIn("交互未就绪", STATUS.statusline(interactive_status))
        self.assertTrue(
            any(
                warning.startswith("当前交互未就绪:")
                for warning in STATUS.notification_warnings(interactive_status)
            )
        )

    def test_decision_clock_phases_remain_distinct_and_never_imply_approval(self) -> None:
        target = "a" * 64
        self.write_contract(pending_proposal=target)
        original_request, _card = self.ask_native_proposal(target)
        self.observe_operational_cycle()
        self.observe("PermissionRequest")
        current = datetime.now(timezone.utc)

        fresh = self.projected(
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            now=current,
        )
        self.assertEqual(
            fresh["native_decision_pairing_readiness"]["status"],
            "awaiting_human",
        )
        self.assertEqual(
            fresh["native_decision_pairing_readiness"]["awaiting_human"], 1
        )
        self.assertFalse(fresh["gates"]["native_decision_pairing_settled"])

        self.set_request_deadlines(
            reassess_at=current - timedelta(seconds=1),
            expires_at=current + timedelta(hours=23),
        )
        due = self.projected(
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            now=current,
        )
        decision = due["native_decision_pairing_readiness"]
        self.assertEqual(decision["status"], "reassess_due")
        self.assertEqual(decision["reassess_due"], 1)
        self.assertEqual(decision["awaiting_human"], 1)
        self.assertEqual(decision["paired_committed"], 0)
        reused_request, _card = self.ask_native_proposal(target)
        self.assertEqual(reused_request["request_id"], original_request["request_id"])
        self.assertEqual(
            len(
                approval_store_path(self.contract_path)
                .read_text(encoding="utf-8")
                .splitlines()
            ),
            1,
        )

        self.set_request_deadlines(
            reassess_at=current - timedelta(hours=24),
            expires_at=current - timedelta(seconds=1),
        )
        expired = self.projected(
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            now=current,
        )
        self.assertEqual(
            expired["native_decision_pairing_readiness"]["status"],
            "expired",
        )
        self.assertEqual(
            expired["native_decision_pairing_readiness"]["expired"], 1
        )
        self.assertEqual(expired["host_readiness"]["status"], "interactive_ready")
        self.assertEqual(expired["status"], "degraded")

    def test_decided_request_without_committed_native_cas_is_mismatch(self) -> None:
        target = "b" * 64
        self.write_contract(pending_proposal=target)
        _request, card = self.ask_native_proposal(target)
        decide_approval(
            self.contract_path,
            kind="proposal",
            target=target,
            outcome="approved",
            provider="codex",
            session_id="session-one",
            actor="permission-request:codex",
            card=card,
            workspace=self.workspace,
            route="human",
            source="codex_permission_request",
        )
        self.write_contract()
        self.observe_operational_cycle()

        readiness = self.readiness()

        decision = readiness["native_decision_pairing_readiness"]
        self.assertEqual(decision["status"], "cas_mismatch")
        self.assertEqual(decision["cas_mismatch"], 1)
        self.assertFalse(readiness["gates"]["native_decision_pairing_settled"])
        self.assertEqual(readiness["status"], "degraded")

    def test_production_shaped_history_is_visible_without_amplifying_current_mismatch(
        self,
    ) -> None:
        target = "9" * 64
        task_epoch = "d" * 24
        self.write_contract(
            task_epoch=task_epoch,
            pending_proposal=target,
            task_lanes=[self.current_lane(target, task_epoch=task_epoch)],
        )
        current_request, _card = self.ask_native_proposal(target)
        other_request, _other_card = self.ask_native_proposal(
            target,
            session_id="session-two",
        )
        historical_request = {
            **current_request,
            "request_id": "apr-" + "d" * 24,
            "intent_revision": 2,
        }
        self.observe_operational_cycle()
        self.observe("PermissionRequest")

        transactions: dict[str, dict] = {}
        # Production had a large historical terminal population.  These v3
        # rows remain visible but are not current v4/task-epoch authority.
        for index in range(1, 26):
            binding = self.native_binding(
                current_request,
                target,
                schema="sulde-native-transaction-binding-v3",
                task_epoch=None,
            )
            transaction = self.native_transaction(
                index,
                binding,
                status="external_authority_unverified",
                stage="committed",
            )
            transactions[transaction["transaction_id"]] = transaction

        for index, session_id in enumerate(
            ("session-two", "session-three"),
            start=26,
        ):
            binding = self.native_binding(
                other_request,
                target,
                session_id=session_id,
                task_epoch=task_epoch,
            )
            transaction = self.native_transaction(index, binding)
            transactions[transaction["transaction_id"]] = transaction

        legacy_active = self.native_transaction(
            28,
            self.native_binding(
                current_request,
                target,
                schema="sulde-native-transaction-binding-v3",
                task_epoch=None,
            ),
        )
        transactions[legacy_active["transaction_id"]] = legacy_active
        old_epoch_active = self.native_transaction(
            29,
            self.native_binding(
                current_request,
                target,
                task_epoch="e" * 24,
            ),
        )
        transactions[old_epoch_active["transaction_id"]] = old_epoch_active

        with mock.patch(
            "operational_readiness.load_approval_projection",
            return_value={
                "requests": {
                    current_request["request_id"]: current_request,
                    other_request["request_id"]: other_request,
                    historical_request["request_id"]: historical_request,
                }
            },
        ), mock.patch(
            "operational_readiness.load_native_decision_projection",
            return_value={"transactions": transactions},
        ), mock.patch(
            "operational_readiness.load_native_head_proof",
            return_value=self.native_head_proof(),
        ):
            decision = self.readiness()["native_decision_pairing_readiness"]

        self.assertEqual(decision["status"], "awaiting_human")
        self.assertEqual(decision["cas_mismatch"], 0)
        self.assertEqual(
            decision["request_scope"],
            {
                "current_active": 1,
                "other_lane_active": 1,
                "historical_active": 1,
                "terminal": 0,
            },
        )
        self.assertEqual(
            decision["transaction_scope"],
            {
                "current_active": 0,
                "other_lane_active": 2,
                "historical_active": 2,
                "terminal": 25,
                "malformed": 0,
            },
        )

    def test_only_malformed_exact_current_transaction_counts_as_current_mismatch(
        self,
    ) -> None:
        target = "8" * 64
        task_epoch = "d" * 24
        self.write_contract(
            task_epoch=task_epoch,
            pending_proposal=target,
            task_lanes=[self.current_lane(target, task_epoch=task_epoch)],
        )
        request, _card = self.ask_native_proposal(target)
        self.observe_operational_cycle()
        self.observe("PermissionRequest")

        missing_request = dict(request)
        missing_request["request_id"] = "apr-" + "f" * 24
        current = self.native_transaction(
            100,
            self.native_binding(missing_request, target, task_epoch=task_epoch),
        )
        transactions = {current["transaction_id"]: current}
        for index in range(101, 141):
            historical = self.native_transaction(
                index,
                self.native_binding(
                    request,
                    target,
                    schema="sulde-native-transaction-binding-v3",
                    task_epoch=None,
                ),
                status="external_authority_unverified",
                stage="committed",
            )
            transactions[historical["transaction_id"]] = historical

        with mock.patch(
            "operational_readiness.load_approval_projection",
            return_value={"requests": {request["request_id"]: request}},
        ), mock.patch(
            "operational_readiness.load_native_decision_projection",
            return_value={"transactions": transactions},
        ), mock.patch(
            "operational_readiness.load_native_head_proof",
            return_value=self.native_head_proof(),
        ):
            decision = self.readiness()["native_decision_pairing_readiness"]

        self.assertEqual(decision["status"], "cas_mismatch")
        self.assertEqual(decision["cas_mismatch"], 1)
        self.assertEqual(decision["transaction_scope"]["current_active"], 1)
        self.assertEqual(decision["transaction_scope"]["terminal"], 40)
        self.assertIn("native_transaction_request_missing", decision["reasons"])

    def test_multiple_exact_current_active_transactions_fail_closed_once(self) -> None:
        target = "7" * 64
        task_epoch = "d" * 24
        self.write_contract(
            task_epoch=task_epoch,
            pending_proposal=target,
            task_lanes=[self.current_lane(target, task_epoch=task_epoch)],
        )
        request, _card = self.ask_native_proposal(target)
        second_request = dict(request)
        second_request["request_id"] = "apr-" + "e" * 24
        transactions = {}
        for index, candidate in enumerate((request, second_request), start=201):
            transaction = self.native_transaction(
                index,
                self.native_binding(candidate, target, task_epoch=task_epoch),
            )
            transactions[transaction["transaction_id"]] = transaction

        with mock.patch(
            "operational_readiness.load_approval_projection",
            return_value={
                "requests": {
                    request["request_id"]: request,
                    second_request["request_id"]: second_request,
                }
            },
        ), mock.patch(
            "operational_readiness.load_native_decision_projection",
            return_value={"transactions": transactions},
        ), mock.patch(
            "operational_readiness.load_native_head_proof",
            return_value=self.native_head_proof(),
        ):
            decision = self.readiness()["native_decision_pairing_readiness"]

        self.assertEqual(decision["status"], "cas_mismatch")
        self.assertEqual(decision["cas_mismatch"], 1)
        self.assertEqual(decision["transaction_scope"]["current_active"], 2)
        self.assertIn("native_current_scope_conflict", decision["reasons"])

    def test_local_only_committed_replay_remains_external_authority_unverified(self) -> None:
        target = "c" * 64
        self.write_contract(pending_proposal=target)
        request, card = self.ask_native_proposal(target)
        current = datetime.now(timezone.utc)
        self.set_request_deadlines(
            reassess_at=current - timedelta(seconds=1),
            expires_at=current + timedelta(hours=23),
        )
        due = self.projected(
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            now=current,
        )
        self.assertEqual(
            due["native_decision_pairing_readiness"]["status"],
            "reassess_due",
        )
        binding = {
            "request_id": request["request_id"],
            "kind": "proposal",
            "decision": "approve",
            "target": target,
            "action": "apply-proposal",
            "approval_kind": "proposal",
            "intent_id": "operational-fixture",
            "intent_revision": 1,
            "workspace": str(self.workspace.resolve()),
            "provider": "codex",
            "session_id": "session-one",
            "card_sha256": request["card_sha256"],
        }
        decide_approval(
            self.contract_path,
            kind="proposal",
            target=target,
            outcome="approved",
            provider="codex",
            session_id="session-one",
            actor="permission-request:codex",
            card=card,
            workspace=self.workspace,
            route="human",
            source="codex_permission_request",
        )
        self.write_contract()
        self.observe_operational_cycle()

        transaction = {
            "transaction_id": "ndt-" + "d" * 32,
            "binding": binding,
            "stage": "committed",
            "historical_status": "committed",
            "status": "external_authority_unverified",
            "local_consistency_verified": True,
            "external_authority_verified": False,
        }
        native = {"transactions": {transaction["transaction_id"]: transaction}}
        head = self.native_head_proof()
        with mock.patch(
            "operational_readiness.load_native_decision_projection",
            return_value=native,
        ), mock.patch(
            "operational_readiness.load_native_head_proof",
            return_value=head,
        ):
            readiness = self.readiness()

        decision = readiness["native_decision_pairing_readiness"]
        self.assertEqual(decision["status"], "cas_mismatch")
        self.assertEqual(decision["paired_committed"], 0)
        self.assertIn("external_authority_unverified", decision["reasons"])
        self.assertFalse(readiness["gates"]["native_decision_pairing_settled"])

    def native_head_proof(self) -> dict:
        head = {
            "schema": "sulde-native-decision-journal-head-proof-v2",
            "contract_sha256": "1" * 64,
            "generation": 4,
            "sequence": 4,
            "event_id": "2" * 64,
            "event_sha256": "2" * 64,
            "journal_sha256": "3" * 64,
            "anchor_sha256": "4" * 64,
            "local_consistency_verified": True,
            "external_authority_verified": False,
            "external_authority_status": "external_authority_unverified",
            "recovery_status": "pending",
            "external_anchor_required": True,
            "external_anchor_boundary": "fixture T06 boundary",
            "proof_sha256": "",
        }
        canonical = json.dumps(
            {key: value for key, value in head.items() if key != "proof_sha256"},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        head["proof_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        return head

    def test_only_exact_external_authority_proof_can_settle(self) -> None:
        target = "e" * 64
        self.write_contract(pending_proposal=target)
        request, card = self.ask_native_proposal(target)
        decide_approval(
            self.contract_path,
            kind="proposal",
            target=target,
            outcome="approved",
            provider="codex",
            session_id="session-one",
            actor="permission-request:codex",
            card=card,
            workspace=self.workspace,
            route="human",
            source="codex_permission_request",
        )
        self.write_contract()
        self.observe_operational_cycle()
        binding = {
            "request_id": request["request_id"],
            "kind": "proposal",
            "decision": "approve",
            "target": target,
            "action": "apply-proposal",
            "approval_kind": "proposal",
            "intent_id": "operational-fixture",
            "intent_revision": 1,
            "workspace": str(self.workspace.resolve()),
            "provider": "codex",
            "session_id": "session-one",
            "card_sha256": request["card_sha256"],
        }
        transaction = {
            "transaction_id": "ndt-" + "f" * 32,
            "binding": binding,
            "stage": "committed",
            "historical_status": "committed",
            "status": "external_authority_unverified",
            "local_consistency_verified": True,
            "external_authority_verified": False,
        }
        native = {"transactions": {transaction["transaction_id"]: transaction}}
        head = self.native_head_proof()

        with mock.patch(
            "operational_readiness.load_native_decision_projection",
            return_value=native,
        ), mock.patch(
            "operational_readiness.load_native_head_proof",
            return_value=head,
        ):
            query = self.readiness()["native_decision_pairing_readiness"][
                "external_authority_queries"
            ][0]
            proof = {**query, "schema": "sulde-t06-external-authority-proof-v1"}
            proof["journal_head_proof"] = head

            def reader(_query: dict) -> dict:
                return proof

            settled = project(
                self.home,
                provider="codex",
                session_id="session-one",
                workspace=self.workspace,
                scheduler_probe=self.ready_scheduler_probe,
                external_authority_reader=reader,
            )
            self.assertEqual(
                settled["native_decision_pairing_readiness"]["status"],
                "settled",
            )
            self.assertTrue(settled["gates"]["native_decision_pairing_settled"])

            for field in (
                "contract_sha256",
                "workspace_sha256",
                "provider",
                "session_id_sha256",
                "intent_id_sha256",
                "intent_revision",
                "request_id",
                "card_sha256",
                "target_sha256",
                "transaction_id",
                "transaction_binding_sha256",
                "journal_head_proof",
            ):
                with self.subTest(field=field):
                    drifted = dict(proof)
                    drifted[field] = (
                        {**head, "generation": 3}
                        if field == "journal_head_proof"
                        else 2
                        if field == "intent_revision"
                        else "drifted"
                    )
                    rejected = project(
                        self.home,
                        provider="codex",
                        session_id="session-one",
                        workspace=self.workspace,
                        scheduler_probe=self.ready_scheduler_probe,
                        external_authority_reader=lambda _query, value=drifted: value,
                    )
                    decision = rejected["native_decision_pairing_readiness"]
                    self.assertEqual(decision["status"], "cas_mismatch")
                    self.assertFalse(decision["settled"])

            malformed_proofs = (
                None,
                True,
                "verified",
                {key: value for key, value in proof.items() if key != "request_id"},
            )
            for malformed in malformed_proofs:
                with self.subTest(malformed=type(malformed).__name__):
                    rejected = project(
                        self.home,
                        provider="codex",
                        session_id="session-one",
                        workspace=self.workspace,
                        scheduler_probe=self.ready_scheduler_probe,
                        external_authority_reader=lambda _query, value=malformed: value,
                    )
                    self.assertEqual(
                        rejected["native_decision_pairing_readiness"]["status"],
                        "cas_mismatch",
                    )

            with mock.patch(
                "operational_readiness.verify_recorded_external_head_receipt",
                return_value={"schema": "sulde-native-external-head-receipt-v1"},
            ):
                durable = self.readiness()
            self.assertEqual(
                durable["native_decision_pairing_readiness"]["status"],
                "settled",
            )
            self.assertEqual(
                durable["native_decision_pairing_readiness"][
                    "external_authority_queries"
                ],
                [],
            )

    def test_delivery_generation_failures_are_fail_closed(self) -> None:
        deployment = self.home / "deployment-generation.json"
        owner = self.home / "runtime-owner.json"
        original_deployment = json.loads(deployment.read_text(encoding="utf-8"))
        original_owner = json.loads(owner.read_text(encoding="utf-8"))
        cases = (
            *(
                (
                    deployment,
                    {**original_deployment, "status": state},
                    "deployment_state_eligible",
                )
                for state in ("activating", "degraded", "stale")
            ),
            (
                owner,
                {**original_owner, "generation": "stale-generation"},
                "generation_matches",
            ),
            (
                owner,
                {**original_owner, "status": "degraded"},
                "runtime_owner_active",
            ),
            (
                owner,
                {**original_owner, "provider": "claude"},
                "provider_matches",
            ),
            (
                owner,
                {
                    **original_owner,
                    "runtime_root": str(Path(self.temporary.name) / "other-runtime"),
                },
                "runtime_root_matches",
            ),
            (
                owner,
                {**original_owner, "managed_labels": ["com.sulde.other"]},
                "managed_actor_inventory_matches",
            ),
        )
        for path, payload, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason):
                deployment.write_text(json.dumps(original_deployment), encoding="utf-8")
                owner.write_text(json.dumps(original_owner), encoding="utf-8")
                path.write_text(json.dumps(payload), encoding="utf-8")
                readiness = self.projected()
                self.assertEqual(readiness["status"], "degraded")
                self.assertIn(
                    expected_reason,
                    readiness["scheduler_readiness"]["reasons"],
                )

        deployment.write_text(json.dumps(original_deployment), encoding="utf-8")
        owner.write_text(json.dumps(original_owner), encoding="utf-8")
        (self.runtime_root / "runtime.txt").write_text("tampered\n", encoding="utf-8")
        readiness = self.projected()
        self.assertEqual(readiness["status"], "degraded")
        self.assertIn(
            "runtime_tree_digest_matches",
            readiness["scheduler_readiness"]["reasons"],
        )

    def test_paused_contract_requires_permission_request_and_remains_degraded(self) -> None:
        self.write_contract(status="paused")
        self.observe_operational_cycle()
        before = self.readiness()
        self.assertTrue(before["approval_required"])
        self.assertFalse(before["gates"]["contract_active"])
        self.assertFalse(before["gates"]["permission_request_fresh"])

        self.observe("PermissionRequest")
        after = self.readiness()
        self.assertTrue(after["gates"]["permission_request_fresh"])
        self.assertFalse(after["gates"]["native_decision_pairing_settled"])
        self.assertEqual(
            after["authority"]["host_provenance"],
            "telemetry_integrity_only",
        )
        self.assertEqual(after["status"], "degraded")

    def test_lane_pause_degrades_only_the_current_paused_session(self) -> None:
        self.write_contract(
            status="paused",
            pause_scope="lane",
            task_lanes=[
                {
                    "provider": "codex",
                    "session_id": "session-one",
                    "task_epoch": "epoch-one",
                    "state": "paused",
                    "pause_reason": "lane-one safety stop",
                },
                {
                    "provider": "codex",
                    "session_id": "session-two",
                    "task_epoch": "epoch-one",
                    "state": "bound",
                },
            ],
        )
        self.observe_operational_cycle(session_id="session-one")
        self.observe_operational_cycle(session_id="session-two")

        paused = self.readiness(session_id="session-one")
        sibling = self.readiness(session_id="session-two")

        self.assertEqual(paused["effective_contract_status"], "paused")
        self.assertEqual(paused["task_lane_state"], "paused")
        self.assertFalse(paused["gates"]["contract_active"])
        self.assertFalse(paused["gates"]["task_lane_bound"])
        self.assertEqual(paused["status"], "degraded")
        self.assertEqual(sibling["contract_status"], "paused")
        self.assertEqual(sibling["effective_contract_status"], "active")
        self.assertEqual(sibling["task_lane_state"], "bound")
        self.assertTrue(sibling["gates"]["contract_active"])
        self.assertTrue(sibling["gates"]["task_lane_bound"])
        self.assertEqual(sibling["status"], "ready")

    def test_pending_verification_is_current_effect_debt(self) -> None:
        self.write_contract(
            pending_verifications=[{"task_epoch": "old-epoch", "event_id": "pending"}]
        )
        self.observe_operational_cycle()
        readiness = self.readiness()
        self.assertEqual(readiness["effect_truth"]["pending_verifications"], 1)
        self.assertFalse(readiness["gates"]["current_effect_clear"])
        self.assertEqual(readiness["status"], "degraded")

    def test_only_authoritative_settlement_clears_derived_pending_debt(self) -> None:
        self.write_contract()
        target = "fixture://object/one"
        resource_context = {
            "server": "fixture",
            "resource_kind": "object",
            "identifier": target,
        }
        resource_key = canonical_resource_key(
            ("fixture", "object", target),
            kind="mcp",
        )
        attempt = begin_attempt(
            self.contract_path,
            intent_id="operational-fixture",
            intent_revision=1,
            fingerprint="f" * 64,
            source_event_id="event-one",
            capability="mcp:fixture:create_object",
            target=target,
            resource_key=resource_key,
            resource_context=resource_context,
            effect="external_write",
            provider="codex",
            session_id="session-one",
            idempotency_key="fixture-attempt-one",
            verification_kind="existence",
        )
        mark_attempt_result(
            self.contract_path,
            attempt["attempt_id"],
            success=True,
        )
        contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        contract["runtime"]["pending_verifications"] = [
            {"attempt_id": attempt["attempt_id"], "task_epoch": "old-epoch"}
        ]
        self.contract_path.write_text(json.dumps(contract), encoding="utf-8")
        self.observe_operational_cycle()
        before = self.readiness()
        self.assertEqual(before["effect_truth"]["pending_verifications"], 1)

        verified = verify_from_read(
            self.contract_path,
            provider="codex",
            session_id="session-one",
            capability="mcp:fixture:get_object",
            target=target,
            resource_key=resource_key,
            resource_context=resource_context,
            verification_event_id="verification-one",
            explicit_attempt_id=attempt["attempt_id"],
            evidence={"existence": [attempt["target_sha256"]]},
        )
        self.assertEqual([row["attempt_id"] for row in verified], [attempt["attempt_id"]])
        after = self.readiness()
        self.assertEqual(after["effect_truth"]["pending_verifications"], 0)
        self.assertEqual(after["effect_truth"]["authoritative_settled_pending"], 1)
        self.assertEqual(after["status"], "ready")

    def test_aborted_debt_is_quarantined_from_global_readiness_not_settled(self) -> None:
        self.write_contract()
        target = "fixture://quarantined/object"
        resource_key = canonical_resource_key(target, kind="uri")
        attempt = begin_attempt(
            self.contract_path,
            intent_id="operational-fixture",
            intent_revision=1,
            fingerprint="a" * 64,
            source_event_id="quarantined-event",
            capability="mcp:fixture:update_object",
            target=target,
            resource_key=resource_key,
            effect="external_write",
            provider="codex",
            session_id="session-one",
            idempotency_key="quarantined-attempt",
            verification_kind="existence",
        )
        intervention = mark_attempt_unknown(
            self.contract_path, attempt["attempt_id"], reason="callback lost"
        )
        resolve_intervention(
            self.contract_path,
            intervention["intervention_id"],
            decision="abort",
            evidence="operator stopped recovery without proving external outcome",
        )
        contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        contract["runtime"]["pending_verifications"] = [
            {"attempt_id": attempt["attempt_id"], "task_epoch": "old-epoch"}
        ]
        self.contract_path.write_text(json.dumps(contract), encoding="utf-8")
        self.observe_operational_cycle()

        readiness = self.readiness()
        effect = readiness["effect_truth"]
        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["gates"]["current_effect_clear"])
        self.assertEqual(effect["blocking"], 0)
        self.assertEqual(effect["authoritative_blocking"], 1)
        self.assertEqual(effect["terminal_quarantined"], 1)
        self.assertEqual(effect["pending_verifications"], 0)
        self.assertEqual(effect["authoritative_settled_pending"], 0)
        self.assertEqual(effect["terminal_quarantined_pending"], 1)

    def test_prompt_capture_without_tool_result_and_stop_is_not_operational(self) -> None:
        self.write_contract()
        self.observe("SessionStart")
        self.observe("UserPromptSubmit")

        readiness = self.readiness()

        self.assertTrue(readiness["gates"]["host_interactive_fresh"])
        self.assertFalse(readiness["gates"]["host_supervision_fresh"])
        self.assertEqual(readiness["status"], "degraded")

    def test_synthetic_session_never_authorizes_operational_readiness(self) -> None:
        self.write_contract()
        self.observe("SessionStart", source="synthetic_smoke")
        self.observe("UserPromptSubmit", source="synthetic_smoke")
        readiness = self.readiness()
        self.assertEqual(
            readiness["host_readiness"]["interactive_status"],
            "synthetic_only",
        )
        self.assertFalse(readiness["gates"]["host_interactive_fresh"])
        self.assertEqual(readiness["status"], "degraded")

    def test_paused_task_lane_does_not_hide_recovery_availability(self) -> None:
        self.write_contract(
            status="paused",
            pause_scope="lane",
            task_lanes=[{
                "provider": "codex", "session_id": "session-one",
                "task_epoch": "epoch-one", "state": "paused",
                "pause_reason": "fixture pause",
            }],
        )
        readiness = project(
            self.home,
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            scheduler_probe=self.ready_scheduler_probe,
            recovery_truth={
                "lane_available": True,
                "typed_route_available": True,
            },
        )
        self.assertEqual(readiness["interactive_readiness"]["status"], "degraded")
        self.assertEqual(readiness["recovery_readiness"]["status"], "diagnosis_available")
        self.assertFalse(
            readiness["recovery_readiness"]["ordinary_task_lane_required"]
        )
        self.assertEqual(
            readiness["domains"]["recovery"]["task_lane_state"], "paused"
        )

    def test_recovery_truth_keeps_snapshot_hook_and_skill_generations_distinct(
        self,
    ) -> None:
        self.write_contract()
        readiness = project(
            self.home,
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            scheduler_probe={
                **self.ready_scheduler_probe,
                "status": "degraded",
                "reasons": ["scheduler_fixture"],
            },
            recovery_truth={
                "lane_available": True,
                "typed_route_available": True,
                "snapshot_status": "stale",
                "hook_generation_status": "current",
                "skill_catalog_status": "old",
            },
        )
        recovery_status = readiness["recovery_readiness"]
        self.assertEqual(recovery_status["status"], "diagnosis_available")
        self.assertEqual(recovery_status["snapshot_status"], "stale")
        self.assertEqual(recovery_status["hook_generation_status"], "current")
        self.assertTrue(recovery_status["skill_catalog_restart_required"])
        self.assertEqual(readiness["scheduler_readiness"]["status"], "degraded")

    def test_absent_recovery_truth_is_unobserved_and_fail_closed(self) -> None:
        self.write_contract()
        readiness = project(
            self.home,
            provider="codex",
            session_id="session-one",
            workspace=self.workspace,
            scheduler_probe=self.ready_scheduler_probe,
            recovery_truth=None,
        )
        recovery_status = readiness["recovery_readiness"]
        self.assertEqual(recovery_status["status"], "unobserved")
        self.assertIsNone(recovery_status["lane_available"])
        self.assertIsNone(recovery_status["typed_route_available"])
        self.assertEqual(recovery_status["snapshot_status"], "unknown")
        self.assertEqual(recovery_status["hook_generation_status"], "unknown")
        self.assertEqual(recovery_status["skill_catalog_status"], "unknown")
        self.assertIsNone(recovery_status["skill_catalog_restart_required"])
        self.assertEqual(recovery_status["available_actions"], [])
        self.assertIn("recovery_truth_unobserved", recovery_status["reasons"])

    def test_incomplete_or_malformed_recovery_truth_is_never_ready(self) -> None:
        self.write_contract()
        cases = (
            (
                "missing_typed_route",
                {"lane_available": True},
                "recovery_truth_missing_typed_route_available",
            ),
            (
                "string_typed_route",
                {
                    "lane_available": True,
                    "typed_route_available": "true",
                },
                "recovery_truth_invalid_typed_route_available",
            ),
            (
                "malformed_snapshot",
                {
                    "lane_available": True,
                    "typed_route_available": True,
                    "snapshot_status": [],
                },
                "recovery_truth_invalid_snapshot_status",
            ),
        )
        for name, recovery_truth, expected_reason in cases:
            with self.subTest(name=name):
                readiness = project(
                    self.home,
                    provider="codex",
                    session_id="session-one",
                    workspace=self.workspace,
                    scheduler_probe=self.ready_scheduler_probe,
                    recovery_truth=recovery_truth,
                )
                recovery_status = readiness["recovery_readiness"]
                self.assertEqual(recovery_status["status"], "unobserved")
                self.assertNotEqual(recovery_status["status"], "ready")
                self.assertEqual(recovery_status["snapshot_status"], "unknown")
                self.assertEqual(
                    recovery_status["hook_generation_status"], "unknown"
                )
                self.assertEqual(
                    recovery_status["skill_catalog_status"], "unknown"
                )
                self.assertIn(expected_reason, recovery_status["reasons"])


if __name__ == "__main__":
    unittest.main()

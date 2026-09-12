from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/kb/life-cycle.py"
SPEC = importlib.util.spec_from_file_location("life_cycle", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
LIFE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIFE)

from host_capabilities import (  # noqa: E402
    issue_host_provenance,
    provision_provenance_key,
    record_observation,
    workspace_identifier,
)
from operational_readiness import (  # noqa: E402
    runtime_tree_digest,
    scheduler_process_projection,
)


class LifeCycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.runtime_root = self.home / "runtime-fixture"
        self.runtime_root.mkdir()
        (self.runtime_root / "runtime.txt").write_text("fixture\n", encoding="utf-8")
        guardian_module = self.runtime_root / "scripts/kb/intent_guardian_parts/state.py"
        guardian_module.parent.mkdir(parents=True)
        guardian_module.write_text("# immutable fixture guardian\n", encoding="utf-8")
        runtime_digest = runtime_tree_digest(self.runtime_root)
        generation = f"fixture:{runtime_digest}"
        labels = ["com.sulde.fixture"]
        (self.home / "deployment-generation.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "installed_live_unverified",
                    "provider": "codex",
                    "runtime_root": str(self.runtime_root.resolve()),
                    "runtime_tree_sha256": runtime_digest,
                    "generation": generation,
                    "managed_labels": labels,
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
                    "runtime_tree_sha256": runtime_digest,
                    "generation": generation,
                    "managed_labels": labels,
                    "retired_labels": [],
                }
            ),
            encoding="utf-8",
        )
        self.scheduler_probe = scheduler_process_projection(
            self.home,
            platform_name="darwin",
            launchctl_list_output="123\t0\tcom.sulde.fixture\n",
        )
        self.assertEqual(self.scheduler_probe["status"], "ready")
        self.assertEqual(self.scheduler_probe["probe_status"], "observed")
        self.environment = mock.patch.dict(
            os.environ,
            {
                "SULDE_HOST_PROVIDER": "codex",
                "SULDE_RUNTIME_ROOT": str(self.runtime_root),
                "SULDE_RUNTIME_GENERATION": generation,
                "SULDE_TEST_MODE": "1",
                "SULDE_KB_HOME": str(self.home),
            },
            clear=False,
        )
        self.environment.start()
        for name in ("SULDE_HOST_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID"):
            os.environ.pop(name, None)
        (self.home / "self-repair").mkdir()
        (self.home / "self-repair/pending.json").write_text("[]", encoding="utf-8")
        (self.home / "golden-candidates.jsonl").write_text(
            json.dumps({"id": "golden-one"}) + "\n", encoding="utf-8"
        )
        (self.home / "distill-candidates.md").write_text("- candidate\n", encoding="utf-8")
        (self.home / "governance").mkdir()
        (self.home / "governance/report-20260811.md").write_text(
            "**待审提案 P-1（不实施）**：test\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def test_complete_projection_has_three_truth_levels(self) -> None:
        state = LIFE.build(self.home, scheduler_probe=self.scheduler_probe)
        self.assertEqual(state["status"], "degraded")
        self.assertEqual(set(state["levels"]), {"L2", "L3", "L4"})
        self.assertFalse(state["closed_loop"]["human_gates"]["preserved"])
        self.assertFalse(state["closed_loop"]["identity_resume"]["guarded"])
        self.assertFalse(state["closed_loop"]["overall_ready"])
        self.assertTrue(state["closed_loop"]["evolve_organs"])
        self.assertEqual(state["evolution"]["status"], "ready")
        self.assertGreater(state["payloads"]["l4"]["active"], 0)
        self.assertEqual(state["operational_readiness"]["status"], "ready")
        self.assertEqual(
            state["operational_readiness"]["readiness_scope"],
            "scheduler",
        )
        self.assertEqual(
            state["operational_readiness"]["interactive_readiness"]["status"],
            "unobserved",
        )
        self.assertFalse(LIFE.scheduler_execution_succeeded(state))

    def test_scheduler_execution_ignores_only_its_own_previous_exit(self) -> None:
        own_failure = {
            **self.scheduler_probe,
            "status": "degraded",
            "reasons": ["managed_actor_last_exit_nonzero"],
            "failed_labels": {LIFE.LIFE_CYCLE_SCHEDULER_LABEL: "1"},
        }
        state = LIFE.build(self.home, apply=True, scheduler_probe=own_failure)
        self.assertEqual(state["status"], "degraded")
        self.assertTrue(LIFE.scheduler_execution_succeeded(state))

        other_failure = {
            **own_failure,
            "failed_labels": {
                LIFE.LIFE_CYCLE_SCHEDULER_LABEL: "1",
                "com.sulde.fixture": "1",
            },
        }
        state = LIFE.build(self.home, apply=True, scheduler_probe=other_failure)
        self.assertFalse(LIFE.scheduler_execution_succeeded(state))

    def test_main_reports_successful_scheduler_execution_separately(self) -> None:
        own_failure = {
            **self.scheduler_probe,
            "status": "degraded",
            "reasons": ["managed_actor_last_exit_nonzero"],
            "failed_labels": {LIFE.LIFE_CYCLE_SCHEDULER_LABEL: "1"},
        }
        state = LIFE.build(self.home, apply=True, scheduler_probe=own_failure)
        with mock.patch.object(LIFE, "kb_home", return_value=self.home), mock.patch.object(
            LIFE, "build", return_value=state
        ), mock.patch.object(LIFE, "atomic_json"), mock.patch.object(
            sys, "argv", ["life-cycle.py", "--run"]
        ), io.StringIO() as output, contextlib.redirect_stdout(output):
            self.assertEqual(LIFE.main(), 0)
            self.assertIn("LIFE CYCLE: DEGRADED", output.getvalue())
            self.assertIn("execution=ready", output.getvalue())

    def test_complete_current_host_and_contract_evidence_is_ready(self) -> None:
        workspace = self.home / "project"
        (workspace / ".git").mkdir(parents=True)
        identifier = workspace_identifier(workspace).split(":", 1)[1]
        contract = self.home / "intent" / "workspaces" / f"{identifier}.active.json"
        contract.parent.mkdir(parents=True)
        contract.write_text(
            json.dumps(
                {
                    "intent_id": "fixture-intent",
                    "revision": 1,
                    "task_epoch": "fixture-epoch",
                    "status": "active",
                    "mode": "enforce",
                    "confirmed_by": "test",
                    "confirmation": {"required": False},
                    "runtime": {
                        "pending_proposal_digest": "",
                        "pending_verifications": [],
                    },
                }
            ),
            encoding="utf-8",
        )
        provision_provenance_key(self.home)
        for event in (
            "SessionStart",
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "Stop",
        ):
            proof = issue_host_provenance(
                provider="codex",
                hook_event=event,
                session_id="fixture-session",
                workspace=workspace,
                home=self.home,
            )
            record_observation(
                provider="codex",
                hook_event=event,
                session_id="fixture-session",
                workspace=workspace,
                source="live_host_hook",
                provenance=proof,
                home=self.home,
            )
        with mock.patch.dict(
            os.environ,
            {
                "SULDE_HOST_PROVIDER": "codex",
                "SULDE_HOST_SESSION_ID": "fixture-session",
                "SULDE_WORKSPACE_ROOT": str(workspace),
            },
            clear=False,
        ):
            state = LIFE.build(
                self.home, apply=True, scheduler_probe=self.scheduler_probe
            )
        self.assertEqual(state["operational_readiness"]["status"], "ready")
        self.assertTrue(all(state["closed_loop"]["dimensions"].values()))
        self.assertTrue(state["closed_loop"]["human_gates"]["preserved"])
        self.assertTrue(state["closed_loop"]["identity_resume"]["guarded"])
        self.assertTrue(state["closed_loop"]["overall_ready"])
        self.assertEqual(state["status"], "ready")

    def test_apply_links_one_evolution_brief_into_l3(self) -> None:
        state = LIFE.build(self.home, apply=True)
        self.assertEqual(state["evolution"]["active"], 1)
        self.assertEqual(state["payloads"]["l3"]["counts"]["pending"], 1)
        self.assertTrue((self.home / "evolution/registry.json").is_file())

    def test_l3_failure_degrades_life_and_creates_repair_goal(self) -> None:
        (self.home / "self-repair/pending.json").write_text(
            json.dumps([{"slug": "broken", "status": "failed", "failure_reason": "x"}]),
            encoding="utf-8",
        )
        state = LIFE.build(self.home)
        self.assertEqual(state["status"], "degraded")
        kinds = {row["kind"] for row in state["payloads"]["l4"]["items"] if row["status"] == "active"}
        self.assertIn("repair_l3_failure", kinds)

    def test_l3_unknown_effect_is_not_reported_ready_and_routes_to_human(self) -> None:
        (self.home / "self-repair/pending.json").write_text(
            json.dumps(
                [
                    {
                        "slug": "unknown-effect",
                        "status": "awaiting_human",
                        "intervention_ids": ["int-" + "a" * 24],
                    }
                ]
            ),
            encoding="utf-8",
        )
        state = LIFE.build(self.home)
        self.assertEqual(state["levels"]["L3"]["status"], "awaiting_human")
        self.assertEqual(state["status"], "degraded")
        kinds = {
            row["kind"]
            for row in state["payloads"]["l4"]["items"]
            if row["status"] == "active"
        }
        self.assertIn("human_intervention_required", kinds)
        self.assertTrue(state["closed_loop"]["unknown_effects_fail_closed"])

    def test_goal_completes_when_trigger_disappears(self) -> None:
        first = LIFE.build(self.home)
        LIFE.atomic_json(self.home / "goals/registry.json", first["payloads"]["l4"])
        (self.home / "distill-candidates.md").write_text("- done（✅ resolved）\n", encoding="utf-8")
        second = LIFE.build(self.home)
        sediment = [row for row in second["payloads"]["l4"]["items"] if row.get("target") == "sediment_draft"]
        self.assertEqual(sediment[0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()

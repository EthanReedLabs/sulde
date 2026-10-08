from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPLAY_PATH = ROOT / "tests/fixtures/r2-guardian-incidents/replay-cases.json"
INCIDENTS_PATH = ROOT / "guardian-r2-program/fixtures/incidents.json"
BASE = "10ad8d876d74fe5c4dea8e3b1cc27e178078bdc2"

LIVE_MODES = {
    "native_host_required",
    "native_os_required",
    "live_host_required",
    "live_resource_required",
    "integration_and_live",
    "integration_and_installed",
    "independent_evidence_required",
}

COMPOSITION_CASES = (
    "tests.test_human_grant.HumanGrantV2Tests.test_unchanged_grant_consumes_once_into_direct_execution_authority",
    "tests.test_human_grant.HumanGrantV2Tests.test_world_drift_returns_stable_readable_diff_and_does_not_mutate",
    "tests.test_grant_broker.GrantBrokerTests.test_typed_end_to_end_transaction_and_no_second_policy_decision",
    "tests.test_grant_broker.GrantBrokerTests.test_all_durable_boundaries_recover_before_and_after_crash",
    "tests.test_recovery_supervisor.HeartbeatAndProgressTests.test_fresh_five_second_card_and_thirty_second_typed_reason",
    "tests.test_recovery_supervisor.OrphanLockTests.test_both_predicates_reclaim_within_ten_second_window",
    "tests.test_recovery_supervisor.ConflictTests.test_overlap_pauses_only_minimal_task_lanes_and_preserves_snapshots",
    "tests.test_resource_adapters.ResourceAdapterTests.test_git_exact_add_commit_and_read_have_independent_verifiers",
    "tests.test_resource_adapters.ResourceAdapterTests.test_figma_binds_file_node_page_mutation_payload_and_readback",
    "tests.test_resource_adapters.ResourceAdapterTests.test_device_binds_serial_package_artifact_and_denies_unsafe_actions",
    "tests.test_resource_adapters.ResourceAdapterTests.test_strict_decoders_and_resource_scoped_debt_fail_closed",
    "tests.test_recovery_lane.RecoveryLaneTests.test_read_routes_bypass_every_broken_ordinary_state",
    "tests.test_recovery_lane.RecoveryLaneTests.test_five_thirty_sla_waiting_suppression_and_bounded_reprobe",
    "tests.test_recovery_lane.RecoveryLaneTests.test_crash_after_adapter_reprobes_without_reapplying",
    "tests.test_agent_runtime.AgentRuntimeTests.test_unmatched_external_completion_enters_awaiting_human_not_blind_failure",
    "tests.test_native_agent_broker.NativeAgentBrokerTest.test_zero_provider_terminal_requires_complete_local_interruption_domain",
)


def validate_replay(document: dict, incidents: dict) -> None:
    if document.get("schema") != "sulde-r2-guardian-replay-cases-v2":
        raise ValueError("schema")
    authority = document.get("authority")
    if not isinstance(authority, dict) or authority != {
        "base_commit": BASE,
        "task_id": "H06H-r2-final-acceptance",
        "incident_source": "guardian-r2-program/fixtures/incidents.json",
        "provider": "codex",
    }:
        raise ValueError("authority")
    incident_ids = [row.get("id") for row in document.get("incidents", [])]
    if incident_ids != [row["id"] for row in incidents["cases"]]:
        raise ValueError("incidents")
    if len(set(incident_ids)) != 19:
        raise ValueError("incident cardinality")
    for actual, source in zip(document["incidents"], incidents["cases"]):
        if actual.get("expected_terminal") != source.get("expected_terminal"):
            raise ValueError("incident terminal")
        if actual.get("mechanisms") != source.get("mechanisms"):
            raise ValueError("incident mechanisms")
    axes = document.get("failure_axes", [])
    if [row.get("axis") for row in axes] != incidents["required_failure_axes"]:
        raise ValueError("failure axes")
    if len({row["axis"] for row in axes}) != 13:
        raise ValueError("failure axis cardinality")
    gates = document.get("hard_gates", [])
    if [row.get("gate") for row in gates] != list(range(1, 15)):
        raise ValueError("hard gates")
    if len({row.get("name") for row in gates}) != 14:
        raise ValueError("hard gate names")
    for row in axes:
        if row.get("evidence_mode") in LIVE_MODES and row.get("candidate_expected") == "pass":
            raise ValueError("synthetic live pass")


class R2GuardianIntegrationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.replay = json.loads(REPLAY_PATH.read_text(encoding="utf-8"))
        self.incidents = json.loads(INCIDENTS_PATH.read_text(encoding="utf-8"))

    def test_replay_matrix_is_bound_to_h06h_and_authoritative_sources(self) -> None:
        validate_replay(self.replay, self.incidents)
        self.assertEqual(len(self.replay["incidents"]), 19)
        self.assertEqual(len(self.replay["failure_axes"]), 13)
        self.assertEqual(len(self.replay["hard_gates"]), 14)

    def test_hostile_fixture_mutations_fail_closed(self) -> None:
        mutations = []
        missing_incident = copy.deepcopy(self.replay)
        missing_incident["incidents"].pop()
        mutations.append(missing_incident)
        missing_axis = copy.deepcopy(self.replay)
        missing_axis["failure_axes"].pop()
        mutations.append(missing_axis)
        wrong_authority = copy.deepcopy(self.replay)
        wrong_authority["authority"]["base_commit"] = "0" * 40
        mutations.append(wrong_authority)
        duplicate_gate = copy.deepcopy(self.replay)
        duplicate_gate["hard_gates"][-1]["gate"] = 13
        mutations.append(duplicate_gate)
        synthetic_live = copy.deepcopy(self.replay)
        synthetic_live["failure_axes"][0]["candidate_expected"] = "pass"
        mutations.append(synthetic_live)
        for mutation in mutations:
            with self.assertRaises(ValueError):
                validate_replay(mutation, self.incidents)

    def test_accepted_public_boundaries_compose_without_skips_or_errors(self) -> None:
        suite = unittest.defaultTestLoader.loadTestsFromNames(COMPOSITION_CASES)
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(result.testsRun, len(COMPOSITION_CASES))
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])


if __name__ == "__main__":
    unittest.main()

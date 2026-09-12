"""Data-free composition regression; not private historical acceptance."""
import unittest

COMPOSITION_CASES = ('tests.test_human_grant.HumanGrantV2Tests.test_unchanged_grant_consumes_once_into_direct_execution_authority', 'tests.test_human_grant.HumanGrantV2Tests.test_world_drift_returns_stable_readable_diff_and_does_not_mutate', 'tests.test_grant_broker.GrantBrokerTests.test_typed_end_to_end_transaction_and_no_second_policy_decision', 'tests.test_grant_broker.GrantBrokerTests.test_all_durable_boundaries_recover_before_and_after_crash', 'tests.test_recovery_supervisor.HeartbeatAndProgressTests.test_fresh_five_second_card_and_thirty_second_typed_reason', 'tests.test_recovery_supervisor.OrphanLockTests.test_both_predicates_reclaim_within_ten_second_window', 'tests.test_recovery_supervisor.ConflictTests.test_overlap_pauses_only_minimal_task_lanes_and_preserves_snapshots', 'tests.test_resource_adapters.ResourceAdapterTests.test_git_exact_add_commit_and_read_have_independent_verifiers', 'tests.test_resource_adapters.ResourceAdapterTests.test_figma_binds_file_node_page_mutation_payload_and_readback', 'tests.test_resource_adapters.ResourceAdapterTests.test_device_binds_serial_package_artifact_and_denies_unsafe_actions', 'tests.test_resource_adapters.ResourceAdapterTests.test_strict_decoders_and_resource_scoped_debt_fail_closed', 'tests.test_recovery_lane.RecoveryLaneTests.test_read_routes_bypass_every_broken_ordinary_state', 'tests.test_recovery_lane.RecoveryLaneTests.test_five_thirty_sla_waiting_suppression_and_bounded_reprobe', 'tests.test_recovery_lane.RecoveryLaneTests.test_crash_after_adapter_reprobes_without_reapplying', 'tests.test_agent_runtime.AgentRuntimeTests.test_unmatched_external_completion_enters_awaiting_human_not_blind_failure', 'tests.test_native_agent_broker.NativeAgentBrokerTest.test_zero_provider_terminal_requires_complete_local_interruption_domain')

class PublicGuardianCompositionTests(unittest.TestCase):
    def test_public_boundaries_compose_without_skips_or_errors(self):
        suite = unittest.defaultTestLoader.loadTestsFromNames(COMPOSITION_CASES)
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(result.testsRun, len(COMPOSITION_CASES))
        self.assertEqual(result.failures, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, [])

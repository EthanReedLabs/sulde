# Reproduction commands

Run in the U01 worktree; no production install. Baseline controls were executed
before changing source at `ef5e7d6`; the new missing-journal test was present for
the baseline red assertion. Final expanded test retains that assertion.

```sh
/Users/eric/.sulde/data/kb/venv/bin/python -B -m unittest \
  tests.test_install_transaction_journal.InstallTransactionJournalTests.test_owner_only_content_addressed_snapshot_and_monotonic_journal \
  tests.test_codex_plugin_install.GenerationSwitchFenceChainTests.test_fence_is_in_switch_during_chain_and_cleared_after_commit

/Users/eric/.sulde/data/kb/venv/bin/python -B -m unittest \
  tests.test_guardian_u01_recovery.GuardianU01RecoveryTests.test_missing_journal_is_not_positive_premutation_evidence

/Users/eric/.sulde/data/kb/venv/bin/python -B -m unittest \
  tests.test_install_transaction_journal \
  tests.test_guardian_u01_recovery.GuardianU01RecoveryTests

/Users/eric/.sulde/data/kb/venv/bin/python -B scripts/kb/run-isolated-tests.py \
  tests.test_install_transaction_journal \
  tests.test_guardian_u01_recovery \
  tests.test_orchestration_r3_closeout \
  tests.test_orchestration_r3f.FenceAtomicityTests \
  tests.test_codex_plugin_install.CodexPluginInstallTests.test_install_repins_command_effects_after_codex_refreshes_system_skills \
  tests.test_codex_plugin_install.CodexPluginInstallTests.test_failed_installed_smoke_rolls_back_registry_and_launchers \
  tests.test_codex_plugin_install.GenerationSwitchFenceChainTests.test_fence_is_in_switch_during_chain_and_cleared_after_commit \
  tests.test_codex_plugin_install.GenerationSwitchFenceChainTests.test_recovery_clears_only_the_matching_fence \
  tests.test_codex_plugin_install.GenerationSwitchFenceChainTests.test_block_refusal_with_active_old_generation_lease_mutates_nothing \
  tests.test_codex_plugin_install.GenerationSwitchFenceChainTests.test_unrelated_install_retains_orphan_fence \
  tests.test_codex_plugin_install.RecoverOnlyFenceLifecycleTests.test_recover_only_clears_matching_fence_and_restores_admission \
  tests.test_codex_plugin_install.RecoverOnlyFenceLifecycleTests.test_recover_only_keeps_foreign_identity_fence \
  tests.test_codex_plugin_install.RecoverOnlyFenceLifecycleTests.test_recover_only_repeats_are_idempotent \
  tests.test_codex_plugin_install.RecoverOnlyFenceLifecycleTests.test_observe_install_keeps_preexisting_historical_fence
```

Post-commit cleanup follow-up, on top of `0d46aff` (the first test below was also
run alone before the follow-up source correction and failed as recorded):

```sh
/Users/eric/.sulde/data/kb/venv/bin/python -B -m unittest \
  tests.test_guardian_u01_recovery.GuardianU01RecoveryTests.test_committed_fsync_error_never_rolls_back_and_preserves_active_authority \
  tests.test_guardian_u01_recovery.GuardianU01RecoveryTests.test_committed_cleanup_lock_error_is_not_a_rollback \
  tests.test_guardian_u01_recovery.GuardianU01RecoveryTests.test_recovery_cleanup_error_retains_real_committed_authority

/Users/eric/.sulde/data/kb/venv/bin/python -B scripts/kb/run-isolated-tests.py \
  tests.test_guardian_u01_recovery \
  tests.test_install_transaction_journal \
  tests.test_codex_plugin_install.GenerationSwitchFenceChainTests.test_fence_is_in_switch_during_chain_and_cleared_after_commit \
  tests.test_codex_plugin_install.RecoverOnlyFenceLifecycleTests.test_recover_only_clears_matching_fence_and_restores_admission \
  tests.test_codex_plugin_install.RecoverOnlyFenceLifecycleTests.test_recover_only_keeps_foreign_identity_fence \
  tests.test_codex_plugin_install.CodexPluginInstallTests.test_failed_installed_smoke_rolls_back_registry_and_launchers \
  tests.test_codex_plugin_install.CodexPluginInstallTests.test_install_repins_command_effects_after_codex_refreshes_system_skills

/Users/eric/.sulde/data/kb/venv/bin/python -B scripts/kb/run-isolated-tests.py \
  tests.test_guardian_u01_recovery.GuardianU01RecoveryTests.test_rollback_recovery_cleanup_error_retains_real_terminal_authority
```

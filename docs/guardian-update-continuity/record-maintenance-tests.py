"""Freeze and record r16 worker/installer evidence using the official runner."""
import argparse
import json
import os
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
BASE = "b70a75d"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--review-fixes", action="store_true")
    parser.add_argument("--review-counterexamples", action="store_true")
    parser.add_argument("--reversal", action="store_true")
    parser.add_argument("--reversal-normal", action="store_true")
    parser.add_argument("--reversal-injection", action="store_true")
    args = parser.parse_args()
    os.environ["SULDE_TEST_EVIDENCE_HOME"] = str(ROOT / ".codex-agent/s3c-maintenance-evidence/formal")
    evidence = runpy.run_path(str(ROOT / "scripts/kb/test-evidence.py"))
    plan = evidence["plan"](BASE)
    if not args.full:
        plan["tests"] = ["tests.test_legacy_maintenance", "tests.test_legacy_maintenance_install",
                         "tests.test_codex_stable_entry_install", "tests.test_codex_stable_hook_entry",
                         "tests.test_codex_plugin_install", "tests.test_candidate_codex_plugin",
                         "tests.test_install_transaction_journal", "tests.test_subprocess_text_encoding_guard"]
        plan["suite"] = "targeted"
    if args.review_fixes:
        plan["tests"] = ["tests.test_legacy_maintenance", "tests.test_legacy_maintenance_install",
                         "tests.test_sulde_home_migration", "tests.test_subprocess_text_encoding_guard"]
    if args.review_counterexamples:
        plan["tests"] = ["tests.test_legacy_maintenance_install.MaintenanceInstallTests." + name for name in (
            "test_claim_precedes_candidate_publication", "test_partial_source_catalog_refuses_before_claim",
            "test_maintenance_cannot_reclassify_existing_stable_lineage")]
    if args.reversal:
        plan["tests"] = ["tests.test_first_migration_reversal_journal", "tests.test_first_migration_reversal",
                         "tests.test_install_transaction_journal", "tests.test_legacy_maintenance",
                         "tests.test_legacy_maintenance_install", "tests.test_subprocess_text_encoding_guard"]
        plan["suite"] = "targeted"
    if args.reversal_normal:
        plan["tests"] = ["tests.test_first_migration_reversal.FirstMigrationReversalTests.test_normal_committed_inverse_restores_old_and_replay_is_read_only"]
        plan["suite"] = "targeted"
    if args.reversal_injection:
        plan["tests"] = ["tests.test_first_migration_reversal", "tests.test_first_migration_reversal_journal"]
        plan["suite"] = "targeted"
    plan["scope"] = {"selected_tests": plan["tests"], "source_worker_and_installer": True,
                     "production_migration_proven": False, "human_receipt_from_tests": False,
                     "full_suite_requested": args.full}
    code, record = evidence["run_plan"](plan, reuse=False)
    print(json.dumps({key: record[key] for key in (
        "run_id", "head", "status", "exit_code", "duration_seconds", "log_sha256", "input_drift")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

"""Persist integration evidence without claiming production migration is proven."""
import argparse
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true")
    mode.add_argument("--closeout", action="store_true")
    args = parser.parse_args()
    evidence = runpy.run_path(str(ROOT / "scripts/kb/test-evidence.py"))
    plan = evidence["plan"]("eacee08", requested="refactor")
    if args.closeout:
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", "1544da5", "HEAD", "--", "scripts", "integrations", "tools"],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        ).splitlines()
        if changed != ["scripts/release/candidate_codex_plugin.py"]:
            raise SystemExit("closeout scope changed; reassess test selection")
        plan["tests"] = [
            "tests.test_candidate_codex_plugin",
            "tests.test_codex_hook_registration", "tests.test_codex_stable_hook_entry",
            "tests.test_codex_plugin_install.CodexPluginInstallTests.test_candidate_install_routes_receipt_evidence_to_canonical_marketplace",
            "tests.test_guardian_s2_evidence.InstallerCollectionTests",
            "tests.test_orchestration_r2.InstallerGateOrderTests",
            "tests.test_guardian_string_flow.GuardianStringFlowNativeTests",
            "tests.test_native_pretool_delivery", "tests.test_native_memory_continuation",
            "tests.test_historical_retirement.InstalledHistoricalRetirementTests",
            "tests.test_repository_relocation.InstalledRepositoryRelocationTests",
            "tests.test_native_session_continuity", "tests.test_native_control_composition",
            "tests.test_native_memory_consistency", "tests.test_subprocess_text_encoding_guard",
        ]
        plan["suite"] = "targeted"
        plan["scope"] = {
            "selected_tests": plan["tests"],
            "selection": "All 18 full-run failures, candidate setup consumers and transport guards",
            "full_reference_run_id": "20261006T043048.824424-26365881683b",
            "full_reference_head": "1544da5ca876d3d7dbe4f44e26d0840297cec07c",
            "changed_production_files": changed,
            "full_suite_satisfied": False,
            "production_migration_proven": False,
        }
    elif not args.full:
        plan["tests"] = [
            "tests.test_codex_hook_registration", "tests.test_codex_stable_hook_entry",
            "tests.test_codex_stable_entry_install", "tests.test_codex_plugin_install",
            "tests.test_codex_update_window", "tests.test_launcher_contract",
            "tests.test_candidate_codex_plugin", "tests.test_install_transaction_journal",
            "tests.test_guardian_u01_recovery", "tests.test_orchestration_r3_closeout",
            "tests.test_production_recovery_control",
            "tests.test_stage_plugin", "tests.test_host_capabilities",
            "tests.test_hook_observer_continuity", "tests.test_hook_observer_closure",
            "tests.test_codex_hook_bridge", "tests.test_sulde_health_scopes",
            "tests.test_sulde_statusline", "tests.test_kb_mcp_entry",
            "tests.test_operational_readiness", "tests.test_subprocess_text_encoding_guard",
        ]
        plan["suite"] = "targeted"
        plan["scope"] = {
            "selected_tests": plan["tests"],
            "selection": "Stable transport, actual installer/recovery, registration and A/C consumers",
            "full_suite_satisfied": False,
            "production_migration_proven": False,
        }
    code, record = evidence["run_plan"](plan, reuse=False)
    print(json.dumps({key: record[key] for key in (
        "run_id", "head", "status", "exit_code", "duration_seconds", "log_sha256", "input_drift")},
        ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

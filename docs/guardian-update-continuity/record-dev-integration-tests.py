"""Official scoped record for the reviewed dev delta and stable-entry consumers."""
import json
import os
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "e56bde62b01e002159ffbb40bb51a232d16909cc"
INCOMING = "3012363a50be1d73e8f7f6f415e650d4ae9f3b9c"
EXPECTED = {
    "scripts/kb/decision_kernel.py", "scripts/kb/intervention.py",
    "scripts/kb/intent_guardian_parts/remote_identity.py",
    "scripts/kb/intent_guardian_parts/resources.py",
}


def main():
    subprocess.run(["git", "merge-base", "--is-ancestor", INCOMING, "HEAD"], cwd=ROOT, check=True)
    changed = subprocess.check_output(["git", "diff", "--name-only", BASE, "HEAD", "--",
        "scripts", "integrations", "hooks", "tools"], cwd=ROOT,
        text=True, encoding="utf-8", errors="replace").splitlines()
    if set(changed) != EXPECTED:
        raise SystemExit("incoming production delta changed; reassess selection")
    os.environ["SULDE_TEST_EVIDENCE_HOME"] = str(ROOT / ".codex-agent/s3c-dev-integration-evidence/formal")
    evidence = runpy.run_path(str(ROOT / "scripts/kb/test-evidence.py"))
    plan = evidence["plan"](BASE, requested="medium")
    ssh = "tests.test_ssh_recovery_scope.SSHRecoveryScopeTests."
    plan["tests"] = [
        "tests.test_stable_entry_ssh_integration",
        *[ssh + name for name in (
            "test_inspection_is_read_and_does_not_settle_unknown",
            "test_read_prefix_cannot_hide_material_operation",
            "test_private_mkdir_with_identity_file_is_material_not_read",
            "test_multiple_debts_can_be_reviewed_without_settling_them")],
        "tests.test_guardian_s1_recovery", "tests.test_guardian_s1_grants",
        "tests.test_guardian_s1_semantics", "tests.test_guardian_u18_architecture",
        "tests.test_intervention", "tests.test_decision_kernel",
        "tests.test_codex_hook_registration", "tests.test_codex_stable_hook_entry",
        "tests.test_production_recovery_control", "tests.test_native_pretool_delivery",
        "tests.test_subprocess_text_encoding_guard",
    ]
    plan["suite"] = "targeted"
    plan["scope"] = {"selected_tests": plan["tests"], "incoming_dev": INCOMING,
        "changed_production_files": changed, "full_suite_satisfied": False,
        "production_migration_proven": False,
        "selection": "Exact SSH/multi-debt delta plus stable staged transport, original recovery and native unified executor"}
    code, record = evidence["run_plan"](plan, reuse=False)
    print(json.dumps({key: record[key] for key in (
        "run_id", "head", "status", "exit_code", "duration_seconds", "log_sha256", "input_drift")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

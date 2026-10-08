"""Record isolated native bootstrap protocol; not a production approval."""
import json
import os
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "9c9f8a81c34df01f842f7a0e311dda9917a66d8b"


def main():
    changed = subprocess.check_output(["git", "diff", "--name-only", BASE, "HEAD", "--",
        "scripts", "integrations", "hooks", "tools"], cwd=ROOT,
        text=True, encoding="utf-8", errors="replace").splitlines()
    if changed:
        raise SystemExit("bootstrap design/fixture cannot change product code: " + repr(changed))
    os.environ["SULDE_TEST_EVIDENCE_HOME"] = str(ROOT / ".codex-agent/s3c-bootstrap-evidence/formal")
    evidence = runpy.run_path(str(ROOT / "scripts/kb/test-evidence.py"))
    plan = evidence["plan"](BASE, requested="small")
    plan["tests"] = ["tests.test_maintenance_bootstrap_host", "tests.test_m1_host_migration",
                     "tests.test_m2_maintenance_migration", "tests.test_subprocess_text_encoding_guard"]
    plan["suite"] = "targeted"
    plan["scope"] = {"selected_tests": plan["tests"], "native_protocol_fixture_only": True,
        "human_approval_verified": False, "full_suite_satisfied": False,
        "sulde_transaction_exercised": False, "production_migration_proven": False}
    code, record = evidence["run_plan"](plan, reuse=False)
    print(json.dumps({key: record[key] for key in (
        "run_id", "head", "status", "exit_code", "duration_seconds", "log_sha256", "input_drift")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

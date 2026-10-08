"""Persist bounded host-mechanism observations via the official evidence runner."""
import json
import os
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "ab8b41948bfc78a0ea2889956c5db9c7b79b3e46"


def main():
    changed = subprocess.check_output(["git", "diff", "--name-only", BASE, "HEAD", "--",
        "scripts", "integrations", "hooks", "tools"], cwd=ROOT,
        text=True, encoding="utf-8", errors="replace").splitlines()
    if changed:
        raise SystemExit("M1 cannot change production code: " + repr(changed))
    os.environ["SULDE_TEST_EVIDENCE_HOME"] = str(ROOT / ".codex-agent/s3c-m1-evidence/formal")
    evidence = runpy.run_path(str(ROOT / "scripts/kb/test-evidence.py"))
    plan = evidence["plan"](BASE, requested="small")
    plan["tests"] = ["tests.test_m1_host_migration", "tests.test_subprocess_text_encoding_guard"]
    plan["suite"] = "targeted"
    plan["scope"] = {"selected_tests": plan["tests"], "host_feasibility_only": True,
        "production_migration_proven": False, "full_suite_satisfied": False,
        "selection": "Synthetic exact-hash trusted Hooks; three real isolated hosts, local model fixture only"}
    code, record = evidence["run_plan"](plan, reuse=False)
    print(json.dumps({key: record[key] for key in (
        "run_id", "head", "status", "exit_code", "duration_seconds", "log_sha256", "input_drift")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Persist task-scoped test evidence using the repository's supported runner."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
BASE = "086f49bd372c21ef0c63613b1682d803c0047eec"
GROUPS = {
    "regression": [
        "tests.test_control_composition", "tests.test_intent_guardian", "tests.test_decision_kernel",
        "tests.test_command_policy", "tests.test_command_template_split", "tests.test_recovery_lane",
        "tests.test_codex_hook_bridge",
    ],
    "native": ["tests.test_native_control_composition", "tests.test_native_pretool_delivery"],
    "performance": ["tests.test_control_composition_performance"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("group", choices=GROUPS)
    args = parser.parse_args()
    os.environ["SULDE_TEST_EVIDENCE_HOME"] = str(ROOT / ".sulde/data/guardian-control-composition")
    module = runpy.run_path(str(ROOT / "scripts/kb/test-evidence.py"))
    tests = GROUPS[args.group]
    before = module["_workspace_digest"]()
    plan = {
        "base": BASE, "baseline_commit": BASE,
        "head": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "risk": "medium", "suite": args.group, "tests": tests,
        "scope": {"selection": "bounded control-composition path; no global policy rewrite",
                  "selected_tests": tests, "changed_paths": module["changed_paths"](BASE)},
    }
    code, record = module["run_plan"](plan, reuse=False)
    after = module["_workspace_digest"]()
    print(json.dumps({"source_unchanged": before == after, "evidence": record}, ensure_ascii=False, indent=2))
    return code if code else (0 if before == after else 2)


if __name__ == "__main__":
    raise SystemExit(main())

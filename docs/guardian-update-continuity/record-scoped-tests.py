"""Persist scoped evidence; this is NOT the frozen full-suite acceptance."""
import json
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]


def main():
    evidence = runpy.run_path(str(ROOT / "scripts/kb/test-evidence.py"))
    plan = evidence["plan"]("eacee08", requested="refactor")
    plan["tests"] = [
        "tests.test_hook_observer_continuity", "tests.test_hook_observer_closure",
        "tests.test_codex_hook_bridge", "tests.test_sulde_health_scopes",
        "tests.test_sulde_statusline", "tests.test_kb_mcp_entry",
        "tests.test_operational_readiness",
    ]
    plan["suite"] = "targeted"
    plan["scope"] = {
        "selected_tests": plan["tests"],
        "selection": "Integrated A/C consumers; full acceptance blocked by unstarted legacy path pruning",
        "full_suite_satisfied": False,
    }
    code, record = evidence["run_plan"](plan, reuse=False)
    print(json.dumps({key: record[key] for key in (
        "run_id", "head", "status", "exit_code", "duration_seconds", "log_sha256", "input_drift")},
        ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the frozen integration plan with the repository evidence writer."""

import argparse
import json
import os
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
ROOT = Path(__file__).resolve().parents[2]
PLAN = Path(__file__).with_name("verification-plan.json")
os.environ["SULDE_TEST_EVIDENCE_HOME"] = str(ROOT / ".sulde/data/test-evidence")
sys.path.insert(0, str(ROOT / "scripts/kb"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    module = runpy.run_path(str(ROOT / "scripts/kb/test-evidence.py"))
    selected = json.loads(PLAN.read_text(encoding="utf-8"))
    if args.preflight_only:
        selected["tests"] = ["tests.test_python_environment_preflight"]
        selected["scope"] = {"selection": "dependency_relocation_red_green",
                             "rationale": "Isolate the integration dependency-identity blocker before rerunning its consumers."}
    selected["head"] = module["_git"]("rev-parse", "HEAD").strip()
    status, record = module["run_plan"](selected, reuse=False)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    raise SystemExit(status)

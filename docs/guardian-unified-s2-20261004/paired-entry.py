"""Five alternating serial baseline/candidate managed-entry pairs, no model."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

CHILD = """
import sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from tests.test_r3_real_entry_chain import _Chain
with tempfile.TemporaryDirectory() as directory:
    chain = _Chain(Path(directory), mode='wellbehaved')
    result = chain.run()
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)
    probe = chain.probe()
    assert probe.returncode == 0 and probe.stdout.strip() == 'ok 2'
"""


def identity(root):
    names = ("scripts/kb/agent-runtime.py", "scripts/kb/execution_method.py",
             "scripts/kb/experience_maintenance.py", "scripts/kb/agent-experience.py",
             "scripts/kb/prediction_feedback.py", "scripts/kb/incremental_facts.py",
             "tests/test_r3_real_entry_chain.py")
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            if (root / name).is_file() else None for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    identities = {label: identity(getattr(args, label).resolve()) for label in ("baseline", "candidate")}
    samples = []
    for pair in range(5):
        for label in (("baseline", "candidate") if pair % 2 == 0 else ("candidate", "baseline")):
            root = getattr(args, label).resolve()
            before = time.monotonic()
            result = subprocess.run(
                [sys.executable, "-B", "-c", CHILD, str(args.candidate.resolve())],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                     "SULDE_R3_SOURCE_ROOT": str(root)},
                capture_output=True, check=False, timeout=45,
            )
            elapsed = time.monotonic() - before
            samples.append({"pair": pair, "tree": label, "seconds": elapsed,
                            "exit_code": result.returncode,
                            "output_sha256": hashlib.sha256(result.stdout + result.stderr).hexdigest()})
            if result.returncode:
                raise RuntimeError("entry control failed: " + (result.stdout + result.stderr).decode("utf-8", "replace"))
    stats = {}
    for label in ("baseline", "candidate"):
        values = sorted(row["seconds"] for row in samples if row["tree"] == label)
        stats[label] = {"median": statistics.median(values), "p95": values[math.ceil(.95 * len(values)) - 1]}
    checks = {}
    for metric, fixed, ratio in (("median", .020, .05), ("p95", .050, .10)):
        delta = stats["candidate"][metric] - stats["baseline"][metric]
        budget = max(fixed, ratio * stats["baseline"][metric])
        checks[metric] = {"delta_seconds": delta, "budget_seconds": budget, "passed": delta <= budget}
    report = {"schema": "sulde-s2-paired-entry-v1", "samples": samples, "summary": stats,
              "checks": checks, "real_model_calls": 0,
              "inputs": identities,
              "inputs_unchanged": all(identity(getattr(args, label).resolve()) == value
                                      for label, value in identities.items()),
              "note": "Five paired protocol samples; p95 is sample maximum, not a population estimate."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps(report, indent=2))
    return 0 if report["inputs_unchanged"] and all(check["passed"] for check in checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

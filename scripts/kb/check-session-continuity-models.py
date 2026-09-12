#!/usr/bin/env python3
"""Offline positive and intentional-negative TLC checks with persistent evidence."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SPECS = ROOT / "spec" / "guardian-session-continuity"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases = (
        ("DenialRecovery", "DenialRecovery", None),
        ("DenialRecovery", "DenialRecoveryNegative", "NoFalsePause"),
        ("SessionContinuity", "SessionContinuity", None),
        ("SessionContinuity", "SessionContinuityNegative", "NoAuthorityTransfer"),
    )
    records = []
    for module, config, invariant in cases:
        state = args.output_dir / (config + "-states")
        argv = ["java", "-XX:+UseParallelGC", "-Xmx768m", "-jar", str(args.jar.resolve()),
                "-workers", "2", "-metadir", str(state.resolve()),
                "-config", str(SPECS / (config + ".cfg")), str(SPECS / (module + ".tla"))]
        started = time.monotonic()
        try:
            process = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
            output = process.stdout + process.stderr
            passed = (process.returncode == 0 and "No error has been found" in output) if invariant is None else (
                process.returncode != 0 and f"Invariant {invariant} is violated" in output
            )
            exit_code = process.returncode
        except subprocess.TimeoutExpired as error:
            output = "TLC timed out; not accepted.\n" + str(error.stdout or "")
            passed, exit_code = False, None
        (args.output_dir / (config + ".log")).write_text(output, encoding="utf-8")
        record = {"config": config, "accepted": passed, "exit_code": exit_code,
                  "expected_counterexample": invariant, "elapsed_seconds": round(time.monotonic() - started, 3),
                  "spec_sha256": hashlib.sha256((SPECS / (module + ".tla")).read_bytes()).hexdigest(),
                  "config_sha256": hashlib.sha256((SPECS / (config + ".cfg")).read_bytes()).hexdigest(),
                  "output_sha256": hashlib.sha256(output.encode()).hexdigest()}
        records.append(record)
        print(json.dumps(record, sort_keys=True), flush=True)
    report = {"schema": "guardian-offline-model-evidence-v1", "records": records,
              "jar_sha256": hashlib.sha256(args.jar.read_bytes()).hexdigest(),
              "platform": platform.system(), "status": "passed" if all(row["accepted"] for row in records) else "failed",
              "not_evidence_for": ["implementation correctness", "live host correctness", "production readiness"]}
    (args.output_dir / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

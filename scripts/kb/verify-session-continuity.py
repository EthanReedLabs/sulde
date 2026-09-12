#!/usr/bin/env python3
"""Persist isolated verification, bound to unchanged tracked source contents."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def source_identity() -> dict:
    # Report-only files are excluded to avoid a report hashing itself. All
    # tracked implementation, tests, models, dependency/config/KB inputs remain.
    rows = subprocess.check_output(["git", "ls-files", "-s", "-z"], cwd=ROOT).split(b"\0")
    digest = hashlib.sha256()
    count = 0
    entries = []
    for row in filter(None, rows):
        metadata, name = row.split(b"\t", 1)
        mode, _object, stage = metadata.split()
        entries.append((name, stage, mode))
    for name, stage, mode in sorted(entries):
        if name.startswith(b"docs/guardian-session-continuity/"):
            continue
        path = ROOT / os.fsdecode(name)
        content = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        digest.update(mode + b"\0" + stage + b"\0" + name + b"\0" + hashlib.sha256(content).digest())
        count += 1
    return {"source_tree_sha256": digest.hexdigest(), "tracked_inputs": count,
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, encoding="utf-8", errors="replace").strip(),
            "excluded_report_directory": "docs/guardian-session-continuity/"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("full", "performance", "fresh-performance", "targeted"))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("tests", nargs="*")
    args = parser.parse_args()
    if args.phase in {"performance", "fresh-performance"} and args.baseline is None:
        parser.error("performance requires an explicit baseline")
    if args.phase == "targeted" and not args.tests:
        parser.error("targeted requires explicit test names")
    before = source_identity()
    identifier = args.phase + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = ROOT / ".sulde/data/guardian-session-continuity" / identifier
    directory.mkdir(parents=True, mode=0o700)
    command = [sys.executable, "-B", str(ROOT / "scripts/kb/run-isolated-tests.py")]
    environment = dict(os.environ)
    if args.phase in {"performance", "fresh-performance"}:
        environment["CONTINUITY_BASELINE_ROOT"] = str(args.baseline.resolve())
        command.append("tests.test_session_continuity_benchmark" if args.phase == "performance" else
                       "tests.test_session_continuity_benchmark.SessionContinuityBenchmarkTests.test_new_tool_events_before_after")
    elif args.phase == "targeted":
        command.extend(args.tests)
    started = time.monotonic()
    print(json.dumps({"status": "running", "run": identifier, **before}), flush=True)
    output_digest = hashlib.sha256()
    tail = []
    evidence = {}
    with os.fdopen(os.open(directory / "output.log", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as output:
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for number, line in enumerate(iter(process.stdout.readline, b""), 1):
            output.write(line)
            output_digest.update(line)
            decoded = line.decode("utf-8", "replace").rstrip()
            tail = (tail + [decoded])[-20:]
            for marker in ("NATIVE_CONTINUITY_EVIDENCE=", "NATIVE_PRETOOL_EVIDENCE=", "CONTINUITY_PERFORMANCE=", "CONTINUITY_FRESH_PERFORMANCE="):
                if marker in decoded:
                    evidence[marker[:-1]] = json.loads(decoded.split(marker, 1)[1])
            if number % 100 == 0:
                print(json.dumps({"run": identifier, "output_lines": number,
                                  "elapsed_seconds": round(time.monotonic() - started, 1)}), flush=True)
        exit_code = process.wait()
        process.stdout.close()
        output.flush()
        os.fsync(output.fileno())
    after = source_identity()
    status = "passed" if exit_code == 0 and before == after else "source_changed" if before != after else "failed"
    report = {"schema": "guardian-session-continuity-verification-v1", "run": identifier,
              "status": status, "test_exit_code": exit_code, "source_before": before, "source_after": after,
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "output_sha256": output_digest.hexdigest(), "tail": tail, "evidence": evidence,
              "not_evidence_for": ["production installation", "Windows live readiness"]}
    with os.fdopen(os.open(directory / "summary.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

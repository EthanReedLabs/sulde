"""Persist source-bound evidence through the official isolated test runner."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / ".sulde/data/guardian-python-dataflow"
spec = importlib.util.spec_from_file_location("receipt_checks", ROOT / "docs/guardian-receipt-consistency/run_checks.py")
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("tests", nargs="*")
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    if not args.label.replace("-", "").isalnum():
        parser.error("use an alphanumeric run label")
    root = ROOT.parent / "guardian-v3-dev-merge" if args.baseline else ROOT
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run = OUT / (stamp + "-" + args.label)
    run.mkdir()
    command = [sys.executable, "-B", "scripts/kb/run-isolated-tests.py", *args.tests]
    before = helpers.source_digest(root)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    started = time.monotonic()
    identity = helpers.inspect_python(Path(sys.executable))
    with tempfile.TemporaryDirectory(prefix="sulde-string-flow-", dir="/private/tmp") as temporary:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", TMPDIR=temporary,
                   SULDE_AUDIT_CURSOR_HOME=str(OUT / "audit-cursors"))
        with (run / "output.log").open("xb") as output:
            result = subprocess.run(command, cwd=root, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, check=False)
    after = helpers.source_digest(root)
    record = {"schema": "guardian-python-dataflow-checks-v1", "label": args.label,
              "head": head, "source_role": "baseline" if args.baseline else "task",
              "source_sha256_before": before, "source_sha256_after": after,
              "command": command, "python_identity": identity, "started_at": stamp,
              "duration_seconds": time.monotonic() - started, "exit_code": result.returncode,
              "evidence_tier": "isolated_regression", "reusable_success": result.returncode == 0 and before == after,
              "log_sha256": hashlib.sha256((run / "output.log").read_bytes()).hexdigest()}
    (run / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": str((run / "result.json").relative_to(ROOT)), **record}, indent=2))
    print("\n".join((run / "output.log").read_text(errors="replace").splitlines()[-18:]))
    return result.returncode or (0 if before == after else 4)


if __name__ == "__main__":
    raise SystemExit(main())
